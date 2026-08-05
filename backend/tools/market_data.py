"""Worldwide OHLCV fetcher with as_of cutoff and Stooq fallback on HTTP 429.

All public functions accept an `as_of` date and never return rows after it.
The cutoff is enforced in this layer, never by prompting the model.
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from backend.cache import get_cache
from backend.config import Config


class RateLimitError(Exception):
    pass


def _normalize_yahoo_columns(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance returns MultiIndex columns on .history(); flatten and rename."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Adj Close": "adj_close", "Volume": "volume",
    })
    keep = [c for c in ["open", "high", "low", "close", "adj_close", "volume"] if c in df.columns]
    return df[keep]


@retry(
    retry=retry_if_exception_type((RateLimitError, Exception)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _fetch_yahoo(ticker: str, start: datetime, end: datetime) -> pd.DataFrame:
    try:
        df = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=False)
    except Exception as e:
        msg = str(e).lower()
        if "429" in msg or "rate" in msg:
            raise RateLimitError(msg) from e
        raise
    if df is None or df.empty:
        raise RateLimitError("empty response (likely rate-limited)")
    return _normalize_yahoo_columns(df)


def _fetch_stooq(ticker: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Stooq CSV download — keyless, global, decades of history.
    Normalised to the same schema as the Yahoo path.
    """
    import httpx
    # Stooq uses .us for US, plain suffix otherwise; safest to pass as-is for non-US.
    sym = ticker.lower().replace(".", "-")
    url = f"https://stooq.com/q/d/l/?s={sym}&d1={start:%Y%m%d}&d2={end:%Y%m%d}&i=d"
    r = httpx.get(url, timeout=30.0)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    if df.empty or "Date" not in df.columns:
        return pd.DataFrame()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date").sort_index()
    return df.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Adj Close": "adj_close", "Volume": "volume",
    })


def get_price_history(
    ticker: str,
    start: str | datetime,
    end: str | datetime,
    as_of: str | datetime,
) -> pd.DataFrame:
    """Return OHLCV for [start, end], hard-capped at `as_of`.

    Worldwide by design — accept any Yahoo suffix (AAPL, RELIANCE.NS, 7203.T, ...).
    Always fetches >= 2 years so SMA-200 is never NaN.
    """
    if isinstance(start, str):
        start = datetime.fromisoformat(start)
    if isinstance(end, str):
        end = datetime.fromisoformat(end)
    if isinstance(as_of, str):
        as_of = datetime.fromisoformat(as_of)

    # Enforce >= 2 years so SMA-200 is defined regardless of chart window.
    earliest = start - timedelta(days=Config.SMA200_MIN_HISTORY_DAYS)
    # Hard cap: never return data after as_of.
    end = min(end, as_of)

    cache = get_cache()
    as_of_iso = as_of.date().isoformat()

    def loader() -> dict:
        try:
            df = _fetch_yahoo(ticker, earliest, end + timedelta(days=1))
        except RateLimitError:
            df = _fetch_stooq(ticker, earliest, end + timedelta(days=1))
        # Trim back to the requested window after fetching extra for SMA.
        df = df.loc[(df.index >= earliest) & (df.index <= end)]
        return df.reset_index().to_dict(orient="records")

    rows = cache.historical("market_data", ticker, "ohlcv", as_of_iso, loader)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.set_index(pd.to_datetime(df.iloc[:, 0])).drop(columns=df.columns[0])
    df.index.name = "date"
    return df.sort_index()


def get_current_price(ticker: str) -> Optional[float]:
    """Live quote for demo only. 15-minute cache."""
    cache = get_cache()

    def loader() -> float | None:
        try:
            t = yf.Ticker(ticker)
            info = getattr(t, "fast_info", None)
            if info and "last_price" in info:
                return float(info["last_price"])
            hist = t.history(period="1d")
            if hist is not None and not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception:
            return None
        return None

    return cache.live("market_data", ticker, "last_price", loader)
