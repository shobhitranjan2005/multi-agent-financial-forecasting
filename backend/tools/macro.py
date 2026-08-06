"""Macroeconomic & Sectoral tool for Indian equities.

Key Indian macro drivers (all time-aware & cached):
- USD/INR exchange rate (INR=X or FRED DEXINUS)
- India VIX (^INDIAVIX) — regime & risk appetite
- Brent Crude (BZ=F) — India imports ~85% of crude
- NIFTY 50 Benchmark (^NSEI)
- NIFTY Sectoral Indices (^CNXIT, ^NSEBANK, ^CNXAUTO, ^CNXPHARMA, etc.)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import yfinance as yf

from backend.cache import get_cache
from backend.config import Config
from backend.tools import calendar_nse, market_data

logger = logging.getLogger(__name__)


def get_macro_data(as_of: str | datetime) -> Dict[str, Any]:
    """Fetch macroeconomic drivers as of `as_of`."""
    if isinstance(as_of, str):
        as_of_dt = datetime.fromisoformat(as_of)
    else:
        as_of_dt = as_of

    as_of_session = calendar_nse.previous_trading_day(as_of_dt)
    as_of_iso = as_of_session.isoformat()

    cache = get_cache()

    def loader() -> Dict[str, Any]:
        start_dt = datetime.combine(as_of_session - timedelta(days=10), datetime.min.time())
        end_dt = datetime.combine(as_of_session, datetime.min.time())

        # USD/INR
        usdinr_df = market_data.get_price_history(Config.USDINR_SYMBOL, start_dt, end_dt, as_of_iso)
        usdinr_val = float(usdinr_df["close"].iloc[-1]) if not usdinr_df.empty else 84.5

        # India VIX
        vix_df = market_data.get_price_history(Config.VIX_SYMBOL, start_dt, end_dt, as_of_iso)
        vix_val = float(vix_df["close"].iloc[-1]) if not vix_df.empty else 14.0

        # Brent Crude
        crude_df = market_data.get_price_history(Config.CRUDE_SYMBOL, start_dt, end_dt, as_of_iso)
        crude_val = float(crude_df["close"].iloc[-1]) if not crude_df.empty else 75.0

        # NIFTY 50 Benchmark
        nifty_df = market_data.get_benchmark_history(start_dt, end_dt, as_of_iso)
        nifty_val = float(nifty_df["close"].iloc[-1]) if not nifty_df.empty else 23000.0

        # Macro regime evaluation logic
        # High VIX (> 18) or Crude spike (> 85 USD) is a headwind for Indian equities
        if vix_val > 18.0 or crude_val > 85.0:
            regime = "Headwind"
            reason = f"Elevated India VIX ({vix_val:.1f}) or high crude prices (${crude_val:.1f})."
        elif vix_val < 14.0 and crude_val < 78.0:
            regime = "Tailwind"
            reason = f"Subdued India VIX ({vix_val:.1f}) and moderate crude prices (${crude_val:.1f})."
        else:
            regime = "Neutral"
            reason = f"Balanced macro indicators (VIX: {vix_val:.1f}, Crude: ${crude_val:.1f})."

        return {
            "as_of": as_of_iso,
            "regime": regime,
            "reasoning": reason,
            "usdinr": round(usdinr_val, 2),
            "india_vix": round(vix_val, 2),
            "brent_crude_usd": round(crude_val, 2),
            "nifty_50": round(nifty_val, 2),
        }

    return cache.historical("macro", "_india", "indicators", as_of_iso, loader)


def get_sector_performance(sector_key: str, as_of: str | datetime) -> Dict[str, Any]:
    """Fetch NIFTY sector index relative performance vs NIFTY 50 as of `as_of`."""
    symbol = Config.SECTOR_INDICES.get(sector_key.upper(), "^CNXIT")
    if isinstance(as_of, str):
        as_of_dt = datetime.fromisoformat(as_of)
    else:
        as_of_dt = as_of

    as_of_session = calendar_nse.previous_trading_day(as_of_dt)
    as_of_iso = as_of_session.isoformat()

    cache = get_cache()

    def loader() -> Dict[str, Any]:
        start_dt = datetime.combine(as_of_session - timedelta(days=30), datetime.min.time())
        end_dt = datetime.combine(as_of_session, datetime.min.time())

        sec_df = market_data.get_price_history(symbol, start_dt, end_dt, as_of_iso)
        nifty_df = market_data.get_benchmark_history(start_dt, end_dt, as_of_iso)

        if not sec_df.empty and len(sec_df) >= 2 and not nifty_df.empty and len(nifty_df) >= 2:
            sec_return = (sec_df["close"].iloc[-1] - sec_df["close"].iloc[0]) / sec_df["close"].iloc[0] * 100.0
            nifty_return = (nifty_df["close"].iloc[-1] - nifty_df["close"].iloc[0]) / nifty_df["close"].iloc[0] * 100.0
            excess = sec_return - nifty_return
            perf = "Outperforming" if excess > 1.5 else "Underperforming" if excess < -1.5 else "Inline"
        else:
            sec_return, excess, perf = 0.0, 0.0, "Inline"

        return {
            "sector_key": sector_key.upper(),
            "sector_symbol": symbol,
            "as_of": as_of_iso,
            "sector_30d_return_pct": round(sec_return, 2),
            "nifty_30d_return_pct": round(nifty_return, 2) if 'nifty_return' in locals() else 0.0,
            "excess_return_pct": round(excess, 2),
            "performance_label": perf,
        }

    return cache.historical("macro", f"sector_{sector_key}", "perf", as_of_iso, loader)


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    as_of_val = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--as-of" else "2025-01-15"
    m_data = get_macro_data(as_of_val)
    s_data = get_sector_performance("IT", as_of_val)
    print(f"Macro Data as of {as_of_val}:")
    print(m_data)
    print(f"NIFTY IT Sector Performance as of {as_of_val}:")
    print(s_data)
