"""Indian financial news via GDELT, time-aware (Task 2.6).

Why GDELT and not NewsAPI: NewsAPI's free tier has a one-month archive with a
24-hour delay and is localhost-only. It cannot backtest. GDELT indexes 100+
languages back to 1979, free and keyless.

THE TRAP THIS MODULE EXISTS TO HANDLE (verified 2026-08-06): when you exceed
GDELT's rate limit it does NOT return 429. It returns HTTP 200 with the body

    "Please limit requests to one every 5 seconds"

A naive client stores that string as if it were an article list, and the cache
makes the poisoning permanent. So the body is inspected explicitly and treated as
a retryable error, and requests are spaced >= 5 seconds apart.

Two deliberately separate paths:
  get_news()      -- GDELT, archival, `as_of`-filtered. The ONLY backtest path.
  get_live_rss()  -- Indian RSS feeds. LIVE DEMO ONLY. RSS carries no usable
                     archive, so it can never be used in an evaluation. Keeping
                     them in different functions makes that impossible to violate
                     by accident rather than merely discouraged.
"""
from __future__ import annotations

import re
import threading
import time
import warnings
from datetime import date, datetime, time as dtime, timedelta
from difflib import SequenceMatcher
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from backend.cache import get_cache
from backend.config import Config
from backend.tools import tickers

GDELT_HTTPS_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_HTTP_URL = "http://api.gdeltproject.org/api/v2/doc/doc"


def _gdelt_url() -> str:
    """Return GDELT endpoint URL based on Config.GDELT_ALLOW_HTTP flag or env var."""
    allow_http = Config.GDELT_ALLOW_HTTP or os.getenv("GDELT_ALLOW_HTTP", "0").lower() in ("1", "true", "yes")
    return GDELT_HTTP_URL if allow_http else GDELT_HTTPS_URL

# The exact shape of GDELT's rate-limit reply, which arrives as HTTP 200.
_RATE_LIMIT_MARKERS = (
    "please limit requests",
    "your query was too short",
    "rate limit",
)

_gdelt_lock = threading.Lock()
_next_gdelt_slot = 0.0
_MIN_REQUEST_SPACING = 10.0  # seconds; strict global spacing (>= 8s, 10s safe margin)

# Indian financial RSS — live demo path only, never the backtest.
INDIAN_RSS_FEEDS = {
    "economic_times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "business_standard": "https://www.business-standard.com/rss/markets-106.rss",
    "moneycontrol": "https://www.moneycontrol.com/rss/marketreports.xml",
    "livemint": "https://www.livemint.com/rss/markets",
}


class GDELTRateLimit(RuntimeError):
    """GDELT throttled us (429 or text throttle). Retryable — and NOT to be cached."""


class GDELTConnectionError(RuntimeError):
    """Connection reset / TLS failure from GDELT. Retryable — and NOT to be cached."""


def _as_date(d: str | date | datetime) -> date:
    if isinstance(d, str):
        return datetime.fromisoformat(d).date()
    if isinstance(d, datetime):
        return d.date()
    return d


def _throttle() -> None:
    global _next_gdelt_slot
    with _gdelt_lock:
        now = time.monotonic()
        wait = max(0.0, _next_gdelt_slot - now)
        _next_gdelt_slot = max(now, _next_gdelt_slot) + _MIN_REQUEST_SPACING
    if wait > 0:
        time.sleep(wait)


def _penalise(delay: float = 35.0) -> None:
    global _next_gdelt_slot
    with _gdelt_lock:
        _next_gdelt_slot = max(_next_gdelt_slot, time.monotonic() + delay)


@retry(
    retry=retry_if_exception_type((GDELTRateLimit, GDELTConnectionError, httpx.ConnectError, httpx.HTTPStatusError)),
    wait=wait_exponential(multiplier=2, min=10, max=90),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _gdelt_request(params: dict) -> dict:
    """One GDELT call, with 429, plain-text throttle, and connection resets handled."""
    _throttle()
    try:
        with httpx.Client(timeout=45.0, headers={"User-Agent": Config.BROWSER_UA}) as client:
            resp = client.get(_gdelt_url(), params=params)
    except (httpx.ConnectError, ConnectionResetError) as exc:
        _penalise(15.0)
        raise GDELTConnectionError(f"Connection reset by GDELT host ({exc})") from exc

    if resp.status_code == 429:
        _penalise(25.0)
        raise GDELTRateLimit(f"HTTP 429: {resp.text[:200]}")

    body = resp.text or ""
    lowered = body.strip().lower()
    # Check BEFORE parsing: this arrives as 200 with a plain-text body.
    if any(m in lowered for m in _RATE_LIMIT_MARKERS):
        _penalise(25.0)
        raise GDELTRateLimit(body.strip()[:200])

    resp.raise_for_status()

    if not lowered:
        return {"articles": []}
    try:
        return resp.json()
    except Exception as exc:
        # Non-JSON that is not a known throttle message: surface it rather than
        # caching an empty result that looks like "no news".
        raise RuntimeError(f"GDELT returned non-JSON ({len(body)} bytes): {body[:200]}") from exc


def _dedup(articles: list[dict], threshold: float = 0.88) -> list[dict]:
    """Drop duplicate stories.

    Indian outlets republish PTI/ANI wire copy heavily, so one event routinely
    appears 5-10 times with near-identical headlines. Counting each copy would
    scale sentiment by syndication volume rather than by significance.
    """
    seen_urls: set[str] = set()
    kept: list[dict] = []
    for art in articles:
        url = (art.get("url") or "").strip()
        if url and url in seen_urls:
            continue
        title = (art.get("title") or "").strip()
        norm = re.sub(r"\W+", " ", title.lower()).strip()
        if not norm:
            continue
        if any(SequenceMatcher(None, norm, k["_norm"]).ratio() >= threshold for k in kept):
            continue
        seen_urls.add(url)
        kept.append({**art, "_norm": norm})
    for k in kept:
        k.pop("_norm", None)
    return kept


# Names Indian press actually prints. The legal name Yahoo returns ("Axis Bank
# Limited") is almost never written that way, and GDELT matches exact phrases, so
# querying it silently returns nothing. A fixed table also makes the query
# independent of Yahoo (reproducible, and no non-point-in-time lookup). Reviewable
# by a human: edit here, never inside a result.
# Names Indian press actually prints. The legal name Yahoo returns ("Axis Bank
# Limited") is almost never written that way, and GDELT matches exact phrases, so
# querying it silently returns nothing. A fixed table also makes the query
# independent of Yahoo (reproducible, and no non-point-in-time lookup). Reviewable
# by a human: edit here, never inside a result.
NEWS_ALIASES: dict[str, list[str]] = {
    "RELIANCE": ["Reliance Industries", "RIL", "Reliance Jio", "Jio Platforms", "Reliance Retail"],
    "TCS": ["Tata Consultancy Services", "TCS"],
    "HDFCBANK": ["HDFC Bank"],
    "INFY": ["Infosys", "Infy"],
    "ICICIBANK": ["ICICI Bank"],
    "HINDUNILVR": ["Hindustan Unilever", "HUL"],
    "ITC": ["ITC Limited", "ITC Ltd"],
    "SBIN": ["State Bank of India"],
    "BHARTIARTL": ["Bharti Airtel"],
    "KOTAKBANK": ["Kotak Mahindra Bank", "Kotak Bank"],
    "LT": ["Larsen and Toubro"],
    "AXISBANK": ["Axis Bank"],
    "ASIANPAINT": ["Asian Paints", "Asian Paint"],
    "MARUTI": ["Maruti Suzuki"],
    "SUNPHARMA": ["Sun Pharma", "Sun Pharmaceutical"],
    "TITAN": ["Titan Company"],
    "ULTRACEMCO": ["UltraTech Cement"],
    "WIPRO": ["Wipro"],
    "NESTLEIND": ["Nestle India"],
    "TATAMOTORS": ["Tata Motors"],
    "TATASTEEL": ["Tata Steel"],
    "JSWSTEEL": ["JSW Steel"],
    "POWERGRID": ["Power Grid Corporation", "Powergrid", "PGCIL"],
    "NTPC": ["NTPC"],
    "ONGC": ["ONGC", "Oil and Natural Gas Corporation"],
    "HCLTECH": ["HCLTech", "HCL Technologies"],
    "TECHM": ["Tech Mahindra"],
    "BAJFINANCE": ["Bajaj Finance", "Bajaj Finserv"],
    "CIPLA": ["Cipla"],
    "DRREDDY": ["Dr Reddy's", "Dr Reddys"],
}
_LEGAL = re.compile(r"\s+(limited|ltd\.?|corporation|corp\.?|inc\.?)\s*$", re.I)


# Primary unambiguous aliases matched as case-insensitive whole words (\b<alias>\b).
# Specifically audited: bare "reliance" and bare "power grid" are disallowed to prevent
# generic English collisions ("reliance on oil", "US power grid").
PRIMARY_TITLE_ALIASES: dict[str, list[str]] = {
    "RELIANCE": ["reliance industries", "ril", "reliance jio", "jio platforms", "reliance retail"],
    "TCS": ["tata consultancy services", "tcs"],
    "HDFCBANK": ["hdfc bank"],
    "INFY": ["infosys", "infy"],
    "ICICIBANK": ["icici bank"],
    "HINDUNILVR": ["hindustan unilever", "hul"],
    "ITC": ["itc limited", "itc ltd"],
    "SBIN": ["state bank of india"],
    "BHARTIARTL": ["bharti airtel", "airtel"],
    "KOTAKBANK": ["kotak mahindra bank", "kotak bank"],
    "LT": ["larsen & toubro", "larsen and toubro", "l&t"],
    "AXISBANK": ["axis bank"],
    "ASIANPAINT": ["asian paints", "asian paint"],
    "MARUTI": ["maruti suzuki"],
    "SUNPHARMA": ["sun pharma", "sun pharmaceutical", "sun pharmaceuticals"],
    "TITAN": ["titan company", "titan co"],
    "ULTRACEMCO": ["ultratech cement", "ultratech"],
    "WIPRO": ["wipro"],
    "NESTLEIND": ["nestle india"],
    "TATAMOTORS": ["tata motors"],
    "TATASTEEL": ["tata steel"],
    "JSWSTEEL": ["jsw steel"],
    "POWERGRID": ["power grid corporation", "power grid corp", "pgcil", "powergrid"],
    "NTPC": ["ntpc", "national thermal power corporation"],
    "ONGC": ["ongc", "oil and natural gas corporation"],
    "HCLTECH": ["hcltech", "hcl technologies", "hcl tech"],
    "TECHM": ["tech mahindra", "techm"],
    "BAJFINANCE": ["bajaj finance", "bajaj finserv"],
    "CIPLA": ["cipla"],
    "DRREDDY": ["dr reddy", "dr reddys", "dr reddy's", "dr. reddy"],
}

# Ticker-specific conditional rules: (alias, required_context_words_set)
# Note: LT and AXISBANK are removed from conditional rules to eliminate collisions
# with military rank / civil administrative titles ("Lt Governor") and geometry / unrelated text ("axis").
CONDITIONAL_TITLE_RULES: dict[str, list[tuple[str, set[str]]]] = {
    "ITC": [("itc", {
        "share", "shares", "stock", "stocks", "cigarette", "cigarettes",
        "tobacco", "fmcg", "hotel", "hotels", "dividend", "results",
        "profit", "pat", "q1", "q2", "q3", "q4", "revenue", "paperboards"
    })],
    "TITAN": [("titan", {
        "jewellery", "jewelry", "watch", "watches", "eyewear", "tanishq",
        "fastrack", "mia", "caratlane", "zoya", "shares", "stock", "stocks",
        "sales", "profit", "q1", "q2", "q3", "q4", "results"
    })],
    "SBIN": [("sbi", {
        "bank", "banking", "shares", "stock", "stocks", "loan", "loans",
        "branch", "branches", "chairman", "q1", "q2", "q3", "q4", "results",
        "pat", "profit", "lender", "deposit", "deposits", "npa", "npas"
    })],
    "HDFCBANK": [("hdfc", {
        "bank", "banking", "shares", "stock", "stocks", "loan", "loans",
        "pat", "profit", "q1", "q2", "q3", "q4", "results", "lender",
        "deposit", "deposits", "npa", "npas"
    })],
    "ICICIBANK": [("icici", {
        "bank", "banking", "shares", "stock", "stocks", "loan", "loans",
        "pat", "profit", "q1", "q2", "q3", "q4", "results", "lender",
        "deposit", "deposits", "npa", "npas"
    })],
    "KOTAKBANK": [("kotak", {
        "bank", "banking", "shares", "stock", "stocks", "loan", "loans",
        "pat", "profit", "q1", "q2", "q3", "q4", "results", "mahindra",
        "lender", "deposit", "deposits"
    })],
    "MARUTI": [("maruti", {
        "suzuki", "car", "cars", "auto", "automobile", "sales", "suv",
        "plant", "ev", "shares", "stock", "stocks", "q1", "q2", "q3", "q4", "results"
    })],
    "NESTLEIND": [("nestle", {
        "india", "maggi", "nescafe", "cerelac", "kitkat", "fmcg",
        "food", "packaged", "shares", "stock", "stocks", "q1", "q2", "q3", "q4", "results"
    })],
}

# Exclusion rules: if any pattern matches, the headline is rejected UNLESS the full,
# unambiguous corporate name (e.g. "Tata Consultancy Services", "HDFC Bank", "JSW Steel")
# is explicitly present and not part of an excluded sister company or division.
EXCLUSION_RULES: dict[str, list[re.Pattern]] = {
    "HDFCBANK": [
        re.compile(r"\b(?:hdfc\s+(?:life|amc|mutual fund|ergo|standard life|securities))\b", re.I),
    ],
    "SBIN": [
        re.compile(r"\b(?:sbi\s+(?:cards?|life|general insurance|mutual fund|mf))\b", re.I),
    ],
    "ICICIBANK": [
        re.compile(r"\b(?:icici\s+(?:prudential|pru|lombard|securities))\b", re.I),
    ],
    "KOTAKBANK": [
        re.compile(r"\b(?:kotak\s+(?:life|general insurance|amc|mutual fund))\b", re.I),
    ],
    "BAJFINANCE": [
        re.compile(r"\b(?:bajaj\s+(?:auto|electricals|consumer|hindusthan))\b", re.I),
    ],
    "TATASTEEL": [
        re.compile(r"\b(?:tata\s+(?:motors|power|consultancy|chemicals|consumer|elxsi|technologies))\b", re.I),
    ],
    "JSWSTEEL": [
        re.compile(r"\b(?:jsw\s+(?:infrastructure|infra|utkal(?:\s+steel)?|energy|cement|paints|severfield))\b", re.I),
    ],
    "TITAN": [
        re.compile(r"\b(?:tech|industry|global|corporate|oil|retail|software|banking|wall street|asian)\s+titan\b", re.I),
        re.compile(r"\b(?:clash of the titans|titan submersible|saturn(?:'s)?\s+moon\s+titan)\b", re.I),
    ],
    "ITC": [
        re.compile(r"\b(?:input tax credit|fake itc|itc fraud|itc reversal|itc mismatch|availment of itc)\b", re.I),
        re.compile(r"\b(?:gst|tax|customs)\b.*\b(?:itc|input tax credit)\b", re.I),
    ],
    "MARUTI": [
        re.compile(r"\b(?:temple|mandir|hanuman|jayanti|puja|devotees|idol|darshan)\b", re.I),
    ],
    "NESTLEIND": [
        re.compile(r"\b(?:switzerland|swiss|germany|vevey)\b", re.I),
    ],
    "TCS": [
        re.compile(r"\b(?:tax collected at source|remittance|remittances|lrs|tour packages?|foreign tour)\b", re.I),
    ],
    "NTPC": [
        re.compile(r"\b(?:rrb|railway recruitment|admit card|typing test|cbt|exam dates?)\b", re.I),
    ],
    "RELIANCE": [
        re.compile(r"\b(?:reliance\s+(?:power|infrastructure|infra|capital|communications|naval))\b", re.I),
    ],
}

FULL_NAME_OVERRIDES: dict[str, list[str]] = {
    "TCS": ["tata consultancy services"],
    "NTPC": ["national thermal power corporation"],
    "RELIANCE": ["reliance industries", "ril", "reliance jio", "reliance retail"],
    "HDFCBANK": ["hdfc bank"],
    "SBIN": ["state bank of india"],
    "ICICIBANK": ["icici bank"],
    "KOTAKBANK": ["kotak mahindra bank", "kotak bank"],
    "JSWSTEEL": ["jsw steel"],
}


def is_headline_relevant(title: str, ticker: str, lang: str = "English") -> bool:
    """Deterministic title-level relevance filter.

    Guarantees that generic market roundups, regional language text, and incidental
    word collisions (e.g. 'reliance on oil', 'US power grid') are rejected.
    """
    if not title:
        return False
    if lang and lang.lower() not in ("english", "eng", "unknown", ""):
        return False
    ascii_ratio = sum(1 for c in title if ord(c) < 128) / len(title)
    if ascii_ratio < 0.80:
        return False

    base = tickers.base_symbol(ticker)
    low = title.lower()

    # 1. Check exclusions (sister companies, unrelated government/exam acronyms, idioms)
    exclusions = EXCLUSION_RULES.get(base, [])
    has_exclusion = any(ex.search(low) for ex in exclusions)

    # 2. Primary unambiguous alias match
    primaries = PRIMARY_TITLE_ALIASES.get(base, [base.lower()])
    primary_matched = any(re.search(r"\b" + re.escape(p) + r"\b", low) for p in primaries)

    if primary_matched:
        if not has_exclusion:
            return True
        # If an exclusion pattern matched (e.g. sister company mentioned),
        # only accept if an unambiguous full corporate name override is present.
        fns = FULL_NAME_OVERRIDES.get(base, [])
        if fns and any(re.search(r"\b" + re.escape(fn) + r"\b", low) for fn in fns):
            # Special check for JSW Steel: "jsw utkal steel" should NOT match "jsw steel"
            if base == "JSWSTEEL" and re.search(r"\bjsw utkal steel\b", low) and not re.search(r"\bjsw steel\b", low):
                return False
            return True
        return False

    if has_exclusion:
        return False

    # 3. Special handling for JSWSTEEL conditional:
    # Require "jsw" plus "steel" within 3 words (excluding sister entities)
    if base == "JSWSTEEL":
        m = re.search(r"\bjsw\b(?:\W+(\w+)){1,3}?\W+\bsteel\b|\bsteel\b(?:\W+(\w+)){1,3}?\W+\bjsw\b", low)
        if m:
            span_text = m.group(0)
            words_in_span = set(re.findall(r"\b\w+\b", span_text))
            disallowed = {"utkal", "infrastructure", "infra", "energy", "cement", "paints", "severfield"}
            if not words_in_span.intersection(disallowed):
                return True
        return False

    # 4. Conditional alias match with required company context
    conditionals = CONDITIONAL_TITLE_RULES.get(base, [])
    if conditionals:
        words = set(re.findall(r"\b\w+\b", low))
        for alias, context_set in conditionals:
            if re.search(r"\b" + re.escape(alias) + r"\b", low):
                if words.intersection(context_set):
                    return True

    return False


def _strip_legal(name: str) -> str:
    return _LEGAL.sub("", name.strip())


def _company_query(ticker: str, company_name: Optional[str]) -> str:
    """Build the GDELT query: curated aliases first, else the de-suffixed legal name."""
    base = tickers.base_symbol(ticker)
    if company_name is None and base in NEWS_ALIASES:
        names = NEWS_ALIASES[base]
    else:
        names = [_strip_legal(company_name or base)]
    phrases = [f'"{n}"' if " " in n else n for n in names]
    q = phrases[0] if len(phrases) == 1 else "(" + " OR ".join(phrases) + ")"
    return f"{q} sourcecountry:IN sourcelang:eng"


def get_news(
    ticker: str,
    as_of: str | date | datetime,
    *,
    lookback_days: int = 30,
    max_records: int = 250,
    company_name: Optional[str] = None,
) -> dict:
    """Indian-press headlines published at or before `as_of`.

    The cutoff is applied twice: GDELT is asked for a bounded window, and every
    returned article is re-checked locally. Trusting a remote filter alone is how
    leakage gets in.
    """
    ticker = tickers.resolve(ticker)
    as_of_d = _as_date(as_of)
    cache = get_cache()

    if company_name is None and tickers.base_symbol(ticker) not in NEWS_ALIASES:
        try:
            from backend.tools.fundamentals import get_company_info
            company_name = get_company_info(ticker).get("name")
        except Exception:
            company_name = None

    start_dt = datetime.combine(as_of_d - timedelta(days=lookback_days), dtime.min)
    end_dt = datetime.combine(as_of_d, dtime.max)

    def loader() -> dict:
        params = {
            "query": _company_query(ticker, company_name),
            "mode": "artlist",
            "format": "json",
            "maxrecords": max_records,
            "sort": "datedesc",
            "startdatetime": start_dt.strftime("%Y%m%d%H%M%S"),
            "enddatetime": end_dt.strftime("%Y%m%d%H%M%S"),
        }
        try:
            data = _gdelt_request(params)
        except GDELTRateLimit as exc:
            # Never cache a throttle message as if it were data.
            raise RuntimeError(f"GDELT rate-limited after retries: {exc}") from exc

        raw = data.get("articles") or []
        articles: list[dict] = []
        for a in raw:
            stamp = a.get("seendate") or ""
            try:
                seen = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ")
            except ValueError:
                continue
            # Local re-check of the cutoff.
            if seen.date() > as_of_d:
                continue
            articles.append({
                "title": a.get("title"),
                "url": a.get("url"),
                "date": seen.date().isoformat(),
                "domain": a.get("domain") or urlparse(a.get("url") or "").netloc,
                "language": a.get("language"),
            })

        # 1. Deterministic title relevance filtering
        relevant_articles = [
            a for a in articles
            if is_headline_relevant(a.get("title", ""), ticker, a.get("language") or "English")
        ]
        # 2. Sort newest first deterministically
        relevant_articles.sort(key=lambda x: x.get("date", ""), reverse=True)
        # 3. Deduplicate
        deduped = _dedup(relevant_articles)
        # 4. Retain at most 15 newest headlines deterministically
        final_headlines = deduped[:15]

        return {
            "ticker": ticker,
            "as_of": as_of_d.isoformat(),
            "query": params["query"],
            "company_name": company_name,
            "window_days": lookback_days,
            "headlines": final_headlines,
            "raw_count": len(raw),
            "after_cutoff_filter": len(articles),
            "after_relevance_filter": len(relevant_articles),
            "after_dedup": len(deduped),
            "retained_count": len(final_headlines),
            "status": "ok" if final_headlines else "empty",
            "limitations": [
                "GDELT provides headline metadata and tone, not full article text.",
                "Coverage of smaller Indian outlets is uneven.",
            ],
        }

    return cache.historical("gdelt", ticker, f"news_v5_{lookback_days}d", as_of_d.isoformat(), loader)


def get_live_rss(limit_per_feed: int = 15) -> dict:
    """Indian financial RSS — LIVE DEMO ONLY.

    Never call this from the evaluation harness. RSS feeds carry only current
    items, so there is no way to reconstruct what they said on a past date; using
    them in a backtest would silently inject present-day news into a past
    forecast. That is exactly the leakage this project exists to eliminate.
    """
    import feedparser

    out: dict[str, Any] = {"fetched_at": datetime.now().isoformat(), "feeds": {}}
    for name, url in INDIAN_RSS_FEEDS.items():
        try:
            parsed = feedparser.parse(url)
            out["feeds"][name] = [
                {"title": e.get("title"), "link": e.get("link"), "published": e.get("published")}
                for e in parsed.entries[:limit_per_feed]
            ]
        except Exception as exc:
            warnings.warn(f"RSS {name} failed: {exc}", RuntimeWarning)
            out["feeds"][name] = []
    return out


def score_sentiment(
    news: dict,
    ticker: str,
    as_of: str,
    *,
    temperature: float = 0.0,
    nonce: str = "",
):
    """Score deduped headlines with Gemini into a SentimentReport.

    Headlines are untrusted web text and are delimited and labelled as data, so a
    headline containing instructions cannot redirect the model.
    """
    from backend.agents.base import run_specialist
    from backend.agents.schemas import SentimentReport
    from backend.prompts import SENTIMENT_ROLE, UNTRUSTED_TEXT_RULE

    heads = news.get("headlines", [])
    if not heads:
        return None, "no headlines available"

    listing = "\n".join(
        f"  [{h.get('date')}] {h.get('title')}  ({h.get('domain')})" for h in heads[:40]
    )
    task = f"""Assess the sentiment around {ticker} as of {as_of} from the Indian
financial press below.

{UNTRUSTED_TEXT_RULE}

Return polarity (-1 to +1), relevance (0-1: how much of this coverage is actually
about this company rather than the sector or the market), confidence (0-1),
specific catalysts, and the article links you relied on."""

    return run_specialist(
        role=SENTIMENT_ROLE,
        task=task,
        evidence=f"<headlines>\n{listing}\n</headlines>",
        schema=SentimentReport,
        as_of=as_of,
        temperature=temperature,
        nonce=nonce,
    )
