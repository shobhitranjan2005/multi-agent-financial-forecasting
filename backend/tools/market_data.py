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
def _download_bhavcopy(d: date) -> bytes | None:
    url = Config.NSE_BHAVCOPY_URL.format(yyyymmdd=d.strftime("%Y%m%d"))
    r = httpx.get(url, headers={"User-Agent": Config.BROWSER_UA}, timeout=60.0,
                  follow_redirects=True)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.content


def _fetch_bhavcopy_day(d: date) -> pd.DataFrame:
    """One day's full NSE cash-market bhavcopy (UDiFF CSV inside a zip).

    The zip is cached on disk under data/bhavcopy/. One file serves every ticker
    for that date, so a backtest over N tickers costs N=1 downloads per day, not
    N. Without this the fallback re-downloads ~170 KB per ticker per day and a
    two-year window takes tens of minutes.

    Returns an empty frame for non-trading days (the archive 404s, which is
    exactly how calendar_nse derives the trading calendar).
    """
    cache_dir = Config.DATA_DIR / "bhavcopy"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{d:%Y%m%d}.zip"

    if path.exists():
        content = path.read_bytes()
    else:
        content = _download_bhavcopy(d)
        if content is None:
            return pd.DataFrame()
        path.write_bytes(content)

    with zipfile.ZipFile(io.BytesIO(content)) as z:
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
    if isinstance(start, str):
        start = datetime.fromisoformat(start)
    if isinstance(end, str):
        end = datetime.fromisoformat(end)
    if isinstance(as_of, str):
        as_of = datetime.fromisoformat(as_of)

    # Validate membership as at as_of, not today — see tickers.resolve.
    ticker = tickers.resolve(ticker, as_of=as_of.date())

    # Snap as_of onto a real NSE session — a forecast dated on Holi is a bug.
    as_of = datetime.combine(calendar_nse.previous_trading_day(as_of), datetime.min.time())

    # Enforce >= 2 years so SMA-200 is defined regardless of chart window.
    earliest = start - timedelta(days=Config.SMA200_MIN_HISTORY_DAYS)
    # Hard cap: never return data after as_of.
    end = min(end, as_of)

    # One canonical fetch per (ticker, as_of), spanning further back than any caller
    # should need, then sliced locally.
    #
    # The cache key is (ticker, as_of) and deliberately does NOT include start/end.
    # So the cached payload must not depend on them either — otherwise the first
    # call for a ticker freezes the window for every later call and short frames
    # are served silently, with no error, to callers that asked for more history.
    # Fetching a fixed long span keeps key and payload in agreement.
    span_start = as_of - timedelta(days=Config.PRICE_FETCH_DAYS)
    if earliest < span_start:
        raise ValueError(
            f"{ticker}: requested history from {earliest.date()} but the cached span "
            f"starts {span_start.date()} ({Config.PRICE_FETCH_DAYS} days before as_of). "
            f"Raise Config.PRICE_FETCH_DAYS if a longer window is genuinely needed."
        )

    cache = get_cache()
    as_of_iso = as_of.date().isoformat()

    def loader() -> dict:
        source = "yfinance"
        try:
            df = _fetch_yahoo(ticker, span_start, as_of + timedelta(days=1))
        except RateLimitError:
            df = _fetch_nse_archive(ticker, span_start.date(), as_of.date())
            source = "nse_bhavcopy"
        # Cap at as_of only. The caller's narrower window is applied after the cache,
        # so one cached fetch serves every window for this (ticker, as_of).
        df = df.loc[df.index <= as_of]
        return {"source": source, "rows": df.reset_index().to_dict(orient="records")}

    # "ohlcv_v2" = full-span payload. The v1 key held only the first caller's narrow
    # window; reusing that key would serve those truncated frames forever.
    payload = cache.historical("market_data", ticker, "ohlcv_v2", as_of_iso, loader)
    rows = payload["rows"] if isinstance(payload, dict) else payload
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.set_index(pd.to_datetime(df.iloc[:, 0])).drop(columns=df.columns[0])
    df.index.name = "date"
    df = df.sort_index()
    # Slice to what this caller asked for (plus the SMA-200 warm-up).
    df = df.loc[(df.index >= earliest) & (df.index <= end)]
    # Record provenance: adjusted (yfinance) vs unadjusted (bhavcopy) must never mix.
    df.attrs["source"] = payload.get("source", "yfinance") if isinstance(payload, dict) else "yfinance"
    df.attrs["currency"] = Config.CURRENCY
    return df


def get_raw_history(
    symbol: str,
    start: str | date | datetime,
    end: str | date | datetime,
    as_of: str | date | datetime,
) -> pd.DataFrame:
    """OHLCV for a NON-EQUITY Yahoo symbol, capped at as_of.

    Deliberately bypasses tickers.resolve(): the India boundary applies to
    tradable equities, but the macro layer legitimately needs indices and
    non-Indian reference series — ^NSEI, ^INDIAVIX, INR=X, BZ=F (Brent, because
    India imports ~85% of its crude), and the NIFTY sectoral indices. Routing
    those through resolve() would reject them as "not listed on NSE", which is
    true and beside the point.

    Equity prices must still go through get_price_history so the boundary holds
    where it matters.
    """
    def _dt(v) -> datetime:
        if isinstance(v, str):
            return datetime.fromisoformat(v)
        if isinstance(v, datetime):
            return v
        return datetime.combine(v, datetime.min.time())

    start, end, as_of = _dt(start), _dt(end), _dt(as_of)
    as_of = datetime.combine(calendar_nse.previous_trading_day(as_of), datetime.min.time())
    end = min(end, as_of)

    # Same fixed-span rule as get_price_history: the cache key is (symbol, as_of)
    # with no window in it, so the cached payload must not depend on the window.
    span_start = as_of - timedelta(days=Config.PRICE_FETCH_DAYS)
    if start < span_start:
        raise ValueError(
            f"{symbol}: requested history from {start.date()} but the cached span "
            f"starts {span_start.date()}. Raise Config.PRICE_FETCH_DAYS if needed."
        )

    cache = get_cache()

    def loader() -> list:
        df = _fetch_yahoo(symbol, span_start, as_of + timedelta(days=1))
        df = df.loc[df.index <= as_of]
        return df.reset_index().to_dict(orient="records")

    rows = cache.historical("market_data", symbol, "raw_ohlcv_v2",
                            as_of.date().isoformat(), loader)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.set_index(pd.to_datetime(df.iloc[:, 0])).drop(columns=df.columns[0])
    df.index.name = "date"
    df = df.sort_index()
    return df.loc[(df.index >= start) & (df.index <= end)]


def get_benchmark_history(
    start: str | date | datetime,
    end: str | date | datetime,
    as_of: str | date | datetime,
) -> pd.DataFrame:
    """NIFTY 50 history — required for NIFTY-relative scoring in the harness.

    Raw directional accuracy flatters any model on a trending index; the
    benchmark series is what turns it into an excess-return number.
    """
    return get_raw_history(Config.BENCHMARK, start, end, as_of)


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
