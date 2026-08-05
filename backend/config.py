"""Centralised configuration loaded from .env.

Never hardcode API keys. Never print secrets. Never commit .env.
"""
import os
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

    # Paths
    @staticmethod
    def ensure_dirs() -> None:
        Config.DATA_DIR.mkdir(parents=True, exist_ok=True)


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
