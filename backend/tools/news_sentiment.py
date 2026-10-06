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

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# The exact shape of GDELT's rate-limit reply, which arrives as HTTP 200.
_RATE_LIMIT_MARKERS = (
    "please limit requests",
    "your query was too short",
    "rate limit",
)

_MIN_REQUEST_SPACING = 5.5  # seconds; GDELT asks for one every 5
_last_request_at = 0.0

# Indian financial RSS — live demo path only, never the backtest.
INDIAN_RSS_FEEDS = {
    "economic_times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "business_standard": "https://www.business-standard.com/rss/markets-106.rss",
    "moneycontrol": "https://www.moneycontrol.com/rss/marketreports.xml",
    "livemint": "https://www.livemint.com/rss/markets",
}


class GDELTRateLimit(RuntimeError):
    """GDELT throttled us. Retryable — and NOT to be cached."""


def _as_date(d: str | date | datetime) -> date:
    if isinstance(d, str):
        return datetime.fromisoformat(d).date()
    if isinstance(d, datetime):
        return d.date()
    return d


def _throttle() -> None:
    global _last_request_at
    wait = _MIN_REQUEST_SPACING - (time.time() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.time()


@retry(
    retry=retry_if_exception_type(GDELTRateLimit),
    wait=wait_exponential(multiplier=2, min=6, max=60),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _gdelt_request(params: dict) -> dict:
    """One GDELT call, with the 200-that-means-429 handled."""
    _throttle()
    with httpx.Client(timeout=45.0, headers={"User-Agent": Config.BROWSER_UA}) as client:
        resp = client.get(GDELT_URL, params=params)

    body = resp.text or ""
    lowered = body.strip().lower()
    # Check BEFORE parsing: this arrives as 200 with a plain-text body.
    if any(m in lowered for m in _RATE_LIMIT_MARKERS):
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
NEWS_ALIASES: dict[str, list[str]] = {
    "RELIANCE": ["Reliance Industries"], "TCS": ["Tata Consultancy Services", "TCS"],
    "HDFCBANK": ["HDFC Bank"], "INFY": ["Infosys"], "ICICIBANK": ["ICICI Bank"],
    "HINDUNILVR": ["Hindustan Unilever"], "ITC": ["ITC Limited", "ITC share"],
    "SBIN": ["State Bank of India", "SBI"], "BHARTIARTL": ["Bharti Airtel"],
    "KOTAKBANK": ["Kotak Mahindra Bank"], "LT": ["Larsen & Toubro", "Larsen and Toubro"],
    "AXISBANK": ["Axis Bank"], "ASIANPAINT": ["Asian Paints"], "MARUTI": ["Maruti Suzuki"],
    "SUNPHARMA": ["Sun Pharma", "Sun Pharmaceutical"], "TITAN": ["Titan Company"],
    "ULTRACEMCO": ["UltraTech Cement"], "WIPRO": ["Wipro"], "NESTLEIND": ["Nestle India"],
    "TATAMOTORS": ["Tata Motors"], "TATASTEEL": ["Tata Steel"], "JSWSTEEL": ["JSW Steel"],
    "POWERGRID": ["Power Grid Corporation", "Power Grid"], "NTPC": ["NTPC"],
    "ONGC": ["ONGC", "Oil and Natural Gas Corporation"], "HCLTECH": ["HCLTech", "HCL Technologies"],
    "TECHM": ["Tech Mahindra"], "BAJFINANCE": ["Bajaj Finance"], "CIPLA": ["Cipla"],
    "DRREDDY": ["Dr Reddy's", "Dr Reddys"],
}
_LEGAL = re.compile(r"\s+(limited|ltd\.?|corporation|corp\.?|inc\.?)\s*$", re.I)


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
    return f"{q} sourcecountry:india"


def get_news(
    ticker: str,
    as_of: str | date | datetime,
    *,
    lookback_days: int = 30,
    max_records: int = 75,
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

        deduped = _dedup(articles)
        return {
            "ticker": ticker,
            "as_of": as_of_d.isoformat(),
            "query": params["query"],
            "company_name": company_name,
            "window_days": lookback_days,
            "headlines": deduped,
            "raw_count": len(raw),
            "after_cutoff_filter": len(articles),
            "after_dedup": len(deduped),
            "limitations": [
                "GDELT provides headline metadata and tone, not full article text.",
                "Coverage of smaller Indian outlets is uneven.",
            ],
        }

    return cache.historical("gdelt", ticker, f"news_v2_{lookback_days}d", as_of_d.isoformat(), loader)


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
