"""NSE/BSE OHLCV fetcher with as_of cutoff and an NSE-bhavcopy fallback.

Scope: Indian equities only. Every ticker passes through tickers.resolve() first,
so nothing downstream ever has to detect a market.

All public functions accept an `as_of` date and never return rows after it.
The cutoff is enforced in this layer, never by prompting the model.

Fallback note (verified 2026-08-06): the old Stooq fallback is dead — stooq.com
now serves a JavaScript proof-of-work challenge page to scripted clients instead
of CSV, so it silently yields nothing. It is replaced by the NSE cash-market
bhavcopy archive: keyless, complete, and India-native. It does require a browser
User-Agent header.

Adjustment caveat: bhavcopy prices are UNADJUSTED for splits/bonuses, while
yfinance auto-adjust prices are adjusted. Never mix the two within one series —
each returned frame records its source in df.attrs["source"].
"""
from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, timedelta
from typing import Optional

import httpx
import pandas as pd
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from backend.cache import get_cache
from backend.config import Config
from backend.tools import calendar_nse, tickers

_OHLCV = ["open", "high", "low", "close", "adj_close", "volume"]


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
    keep = [c for c in _OHLCV if c in df.columns]
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
    out = _normalize_yahoo_columns(df)
    # yfinance returns a tz-aware index in Asia/Kolkata for .NS — drop to naive
    # dates so it joins cleanly with bhavcopy rows.
    out.index = pd.to_datetime(out.index).tz_localize(None).normalize()
    return out


@retry(wait=wait_exponential(multiplier=1, min=2, max=20), stop=stop_after_attempt(3), reraise=True)
def _fetch_bhavcopy_day(d: date) -> pd.DataFrame:
    """One day's full NSE cash-market bhavcopy (UDiFF CSV inside a zip).

    Returns an empty frame for non-trading days (the archive 404s, which is
    exactly how calendar_nse derives the trading calendar).
    """
    url = Config.NSE_BHAVCOPY_URL.format(yyyymmdd=d.strftime("%Y%m%d"))
    r = httpx.get(url, headers={"User-Agent": Config.BROWSER_UA}, timeout=60.0,
                  follow_redirects=True)
    if r.status_code == 404:
        return pd.DataFrame()
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        with z.open(z.namelist()[0]) as fh:
            return pd.read_csv(fh)


def _fetch_nse_archive(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Fallback price history assembled day-by-day from the NSE archive.

    BSE tickers have no equivalent free archive here — for .BO the fallback is
    unavailable and we say so rather than silently returning NSE prices for a
    different listing.
    """
    if tickers.exchange(ticker) != "NSE":
        raise RuntimeError(
            f"No archive fallback for BSE ticker {ticker}; retry via the NSE listing."
        )

    symbol = tickers.base_symbol(ticker)
    frames = []
    cur = start
    while cur <= end:
        if calendar_nse.is_trading_day(cur):
            day = _fetch_bhavcopy_day(cur)
            if not day.empty:
                row = day[
                    (day["TckrSymb"] == symbol)
                    & (day["SctySrs"] == "EQ")
                    & (day["FinInstrmTp"] == "STK")
                ]
                if not row.empty:
                    r = row.iloc[0]
                    frames.append({
                        "date": pd.Timestamp(cur),
                        "open": float(r["OpnPric"]),
                        "high": float(r["HghPric"]),
                        "low": float(r["LwPric"]),
                        "close": float(r["ClsPric"]),
                        "adj_close": float(r["ClsPric"]),   # UNADJUSTED — see module docstring
                        "volume": float(r["TtlTradgVol"]),
                    })
        cur += timedelta(days=1)

    if not frames:
        return pd.DataFrame()
    out = pd.DataFrame(frames).set_index("date").sort_index()
    return out


def get_price_history(
    ticker: str,
    start: str | datetime,
    end: str | datetime,
    as_of: str | datetime,
) -> pd.DataFrame:
    """Return OHLCV for [start, end], hard-capped at `as_of`.

    India-only: `ticker` is resolved to .NS/.BO or the call raises.
    Always fetches >= 2 years so SMA-200 is never NaN.
    """
    ticker = tickers.resolve(ticker)

    if isinstance(start, str):
        start = datetime.fromisoformat(start)
    if isinstance(end, str):
        end = datetime.fromisoformat(end)
    if isinstance(as_of, str):
        as_of = datetime.fromisoformat(as_of)

    # Snap as_of onto a real NSE session — a forecast dated on Holi is a bug.
    as_of = datetime.combine(calendar_nse.previous_trading_day(as_of), datetime.min.time())

    # Enforce >= 2 years so SMA-200 is defined regardless of chart window.
    earliest = start - timedelta(days=Config.SMA200_MIN_HISTORY_DAYS)
    # Hard cap: never return data after as_of.
    end = min(end, as_of)

    cache = get_cache()
    as_of_iso = as_of.date().isoformat()

    def loader() -> dict:
        source = "yfinance"
        try:
            df = _fetch_yahoo(ticker, earliest, end + timedelta(days=1))
        except RateLimitError:
            df = _fetch_nse_archive(ticker, earliest.date(), end.date())
            source = "nse_bhavcopy"
        # Trim back to the requested window after fetching extra for SMA.
        df = df.loc[(df.index >= earliest) & (df.index <= end)]
        return {"source": source, "rows": df.reset_index().to_dict(orient="records")}

    payload = cache.historical("market_data", ticker, "ohlcv", as_of_iso, loader)
    rows = payload["rows"] if isinstance(payload, dict) else payload
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.set_index(pd.to_datetime(df.iloc[:, 0])).drop(columns=df.columns[0])
    df.index.name = "date"
    df = df.sort_index()
    # Record provenance: adjusted (yfinance) vs unadjusted (bhavcopy) must never mix.
    df.attrs["source"] = payload.get("source", "yfinance") if isinstance(payload, dict) else "yfinance"
    df.attrs["currency"] = Config.CURRENCY
    return df


def get_benchmark_history(
    start: str | datetime,
    end: str | datetime,
    as_of: str | datetime,
) -> pd.DataFrame:
    """NIFTY 50 history — required for NIFTY-relative scoring in the harness.

    Raw directional accuracy flatters any model on a trending index; the
    benchmark series is what turns it into an excess-return number.
    """
    if isinstance(start, str):
        start = datetime.fromisoformat(start)
    if isinstance(end, str):
        end = datetime.fromisoformat(end)
    if isinstance(as_of, str):
        as_of = datetime.fromisoformat(as_of)

    as_of = datetime.combine(calendar_nse.previous_trading_day(as_of), datetime.min.time())
    end = min(end, as_of)
    cache = get_cache()

    def loader() -> list:
        df = _fetch_yahoo(Config.BENCHMARK, start, end + timedelta(days=1))
        df = df.loc[(df.index >= start) & (df.index <= end)]
        return df.reset_index().to_dict(orient="records")

    rows = cache.historical("market_data", Config.BENCHMARK, "ohlcv",
                            as_of.date().isoformat(), loader)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.set_index(pd.to_datetime(df.iloc[:, 0])).drop(columns=df.columns[0])
    df.index.name = "date"
    return df.sort_index()


def get_current_price(ticker: str) -> Optional[float]:
    """Live INR quote for demo only. 15-minute cache."""
    ticker = tickers.resolve(ticker)
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


def get_traded_universe(as_of: str | date | datetime) -> list[str]:
    """Every NSE equity that actually traded on `as_of`, from that day's bhavcopy.

    This is the survivorship-bias fix: build the Phase 2 test-set universe from
    what was listed and trading on the date in question, not from today's NIFTY
    membership list.
    """
    d = calendar_nse.previous_trading_day(as_of)
    cache = get_cache()

    def loader() -> list[str]:
        day = _fetch_bhavcopy_day(d)
        if day.empty:
            return []
        eq = day[(day["SctySrs"] == "EQ") & (day["FinInstrmTp"] == "STK")]
        return sorted(f"{s}.NS" for s in eq["TckrSymb"].unique())

    return cache.historical("nse_bhavcopy", "_universe", "tickers", d.isoformat(), loader)
