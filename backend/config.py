"""Centralised configuration loaded from .env.

Scope: Indian equities only — NSE (.NS) primary, BSE (.BO) secondary. INR, Asia/Kolkata.

Never hardcode API keys. Never print secrets. Never commit .env.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


class Config:
    # API keys
    GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")
    FRED_API_KEY: str | None = os.getenv("FRED_API_KEY")

    # Model selection — Flash-class is cheap and fast. Confirm exact model ID in AI Studio.
    # Aliases shift; "gemini-flash-latest" is a moving target.
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

    # Storage
    DATA_DIR: Path = PROJECT_ROOT / "data"
    CACHE_DB: Path = DATA_DIR / "cache.db"

    # Cache TTLs (seconds)
    LIVE_TTL_SECONDS: int = 15 * 60            # 15 minutes for live quote cache
    HISTORICAL_TTL_SECONDS: int = 0            # 0 = permanent (historical data does not change)

    # Indicators
    SMA200_MIN_HISTORY_DAYS: int = 730         # >= 2 years so SMA-200 is never NaN

    # One canonical price fetch per (ticker, as_of) spans this many days back, and
    # callers slice locally. The price cache key is (ticker, as_of) with no window in
    # it, so the fetched span must not depend on the window either -- see
    # market_data.get_price_history.
    PRICE_FETCH_DAYS: int = 365 * 12           # ~12 years, well beyond any test window

    # ---- India-only market constants ----
    MARKET_TZ: str = "Asia/Kolkata"
    CURRENCY: str = "INR"
    CURRENCY_SYMBOL: str = "₹"
    ALLOWED_SUFFIXES: tuple[str, ...] = (".NS", ".BO")   # NSE primary, BSE secondary
    DEFAULT_SUFFIX: str = ".NS"                          # bare "RELIANCE" -> NSE

    BENCHMARK: str = "^NSEI"                   # NIFTY 50 — the benchmark for relative scoring
    BENCHMARK_ALT: str = "^BSESN"              # SENSEX
    VIX_SYMBOL: str = "^INDIAVIX"
    USDINR_SYMBOL: str = "INR=X"
    CRUDE_SYMBOL: str = "BZ=F"                 # Brent — India imports ~85% of its crude

    # NIFTY sectoral indices (Yahoo symbols) — replaces US sector ETFs
    SECTOR_INDICES: dict[str, str] = {
        "IT": "^CNXIT",
        "BANK": "^NSEBANK",
        "AUTO": "^CNXAUTO",
        "PHARMA": "^CNXPHARMA",
        "FMCG": "^CNXFMCG",
        "METAL": "^CNXMETAL",
        "ENERGY": "^CNXENERGY",
        "REALTY": "^CNXREALTY",
    }

    # NSE cash-market bhavcopy archive (keyless, but needs a browser User-Agent).
    # Doubles as the fallback price source AND the trading-calendar oracle:
    # a file exists for a date <=> NSE traded that day.
    NSE_BHAVCOPY_URL: str = (
        "https://nsearchives.nseindia.com/content/cm/"
        "BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"
    )
    BROWSER_UA: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    NSE_CALENDAR_FILE: Path = DATA_DIR / "nse_calendar.json"

    # Forecast horizon is measured in TRADING SESSIONS, never calendar days.
    HORIZON_SESSIONS: int = 21

    # SEBI LODR Reg. 33: quarterly results filed within 45 days of quarter end
    # (annual: 60). A quarter is only "public" once that window has elapsed.
    SEBI_QUARTERLY_FILING_LAG_DAYS: int = 45
    SEBI_ANNUAL_FILING_LAG_DAYS: int = 60

    # Paths
    @staticmethod
    def ensure_dirs() -> None:
        Config.DATA_DIR.mkdir(parents=True, exist_ok=True)


def enable_utf8_console() -> None:
    """Make stdout/stderr UTF-8 so the rupee sign does not crash the CLI.

    Windows consoles default to cp1252, which has no glyph for U+20B9 (Rs). Every
    monetary value this project prints carries that sign, so an unguarded print
    raises UnicodeEncodeError and takes the whole run with it. It is a one-line
    fix and it fails on exactly the machine the demo runs on, which is the worst
    possible time to discover it.

    Call this at the top of every CLI entry point. Never inside library code —
    reconfiguring a stream the caller owns is not a library's business.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass  # already UTF-8, redirected to a pipe that cannot reconfigure, etc.


# Sanity check at import time — fail fast if a critical key is missing in a context that needs it.
def require_gemini_key() -> str:
    key = Config.GEMINI_API_KEY
    if not key or key == "your_gemini_key_here":
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    return key


def require_fred_key() -> str:
    key = Config.FRED_API_KEY
    if not key or key == "your_fred_key_here":
        raise RuntimeError(
            "FRED_API_KEY is not set. Register at fredaccount.stlouisfed.org."
        )
    return key
