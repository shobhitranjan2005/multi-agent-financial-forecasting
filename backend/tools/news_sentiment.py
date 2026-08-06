"""News & Sentiment tool for Indian equities (NSE/BSE).

Uses GDELT Doc API for historical news (filtered by as_of date & domestic India scope).
Deduplicates syndicated press wire articles (PTI, ANI, Moneycontrol, Economic Times).

Handles GDELT rate limiting:
- Explicitly detects HTTP 200 body string "Please limit requests..." and triggers tenacity retry.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from backend.cache import get_cache
from backend.config import Config
from backend.tools import calendar_nse, tickers

logger = logging.getLogger(__name__)


class GDELTRateLimitError(Exception):
    pass


@retry(
    retry=retry_if_exception_type((GDELTRateLimitError, httpx.HTTPError)),
    wait=wait_exponential(multiplier=1, min=5, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _fetch_gdelt_headlines(query: str, start_date: str, end_date: str) -> List[Dict[str, str]]:
    """Fetch headlines from GDELT Doc API v2."""
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query": f"{query} sourcecountry:india",
        "mode": "artlist",
        "maxrecords": "25",
        "format": "json",
        "startdatetime": f"{start_date}000000",
        "enddatetime": f"{end_date}235959",
    }
    r = httpx.get(url, params=params, headers={"User-Agent": Config.BROWSER_UA}, timeout=20.0)

    if "Please limit requests" in r.text:
        raise GDELTRateLimitError("GDELT rate limit body detected")

    if r.status_code != 200:
        return []

    try:
        data = r.json()
        articles = data.get("articles", [])
        out = []
        for a in articles:
            out.append({
                "title": a.get("title", "").strip(),
                "url": a.get("url", ""),
                "seendate": a.get("seendate", ""),
                "domain": a.get("domain", ""),
            })
        return out
    except Exception:
        return []


def deduplicate_headlines(articles: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Deduplicate syndicated news stories by title similarity."""
    seen_titles = set()
    deduped = []
    for a in articles:
        title = a.get("title", "")
        # Normalize title for comparison
        clean = "".join(c.lower() for c in title if c.isalnum())[:40]
        if clean and clean not in seen_titles:
            seen_titles.add(clean)
            deduped.append(a)
    return deduped


def get_news(ticker: str, as_of: str | datetime) -> Dict[str, Any]:
    """Fetch time-aware news for `ticker` as of `as_of`."""
    resolved_ticker = tickers.resolve(ticker)
    base_sym = tickers.base_symbol(resolved_ticker)

    if isinstance(as_of, str):
        as_of_dt = datetime.fromisoformat(as_of)
    else:
        as_of_dt = as_of

    as_of_session = calendar_nse.previous_trading_day(as_of_dt)
    as_of_iso = as_of_session.isoformat()

    start_date = (as_of_session - timedelta(days=14)).strftime("%Y%m%d")
    end_date = as_of_session.strftime("%Y%m%d")

    cache = get_cache()

    def loader() -> Dict[str, Any]:
        try:
            articles = _fetch_gdelt_headlines(base_sym, start_date, end_date)
        except Exception as e:
            logger.warning(f"GDELT fetch failed for {base_sym} ({e}); returning 0 headlines.")
            articles = []
        deduped = deduplicate_headlines(articles)
        return {
            "ticker": resolved_ticker,
            "as_of": as_of_iso,
            "headline_count": len(deduped),
            "articles": deduped,
        }


    return cache.historical("news_sentiment", resolved_ticker, "gdelt", as_of_iso, loader)


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    symbol = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE.NS"
    as_of_val = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--as-of" else "2025-01-15"
    news_data = get_news(symbol, as_of_val)
    print(f"News headlines for {symbol} as of {as_of_val}:")
    print(f"Total deduplicated headlines: {news_data.get('headline_count')}")
    for i, a in enumerate(news_data.get("articles", [])[:5], 1):
        print(f"{i}. {a.get('title')} ({a.get('domain')})")
