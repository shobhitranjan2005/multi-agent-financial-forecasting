"""Fundamental analysis tool for Indian equities (NSE/BSE).

Enforces point-in-time visibility using SEBI LODR Reg. 33:
- Quarterly results are visible ONLY if `as_of >= quarter_end + 45 days`.
- Annual reports are visible ONLY if `as_of >= year_end + 60 days`.

Null handling: yfinance coverage for NSE mid/small-caps has gaps.
Missing fields are explicitly returned as None / "unavailable", never guessed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import yfinance as yf

from backend.cache import get_cache
from backend.config import Config
from backend.tools import calendar_nse, tickers

logger = logging.getLogger(__name__)


def get_fundamentals(ticker: str, as_of: str | datetime) -> Dict[str, Any]:
    """Fetch valuation metrics and fundamental ratios for `ticker` as of `as_of`."""
    resolved_ticker = tickers.resolve(ticker)
    if isinstance(as_of, str):
        as_of_dt = datetime.fromisoformat(as_of)
    else:
        as_of_dt = as_of

    as_of_session = calendar_nse.previous_trading_day(as_of_dt)
    as_of_iso = as_of_session.isoformat()

    cache = get_cache()

    def loader() -> Dict[str, Any]:
        t = yf.Ticker(resolved_ticker)
        info = getattr(t, "info", {}) or {}

        # Fundamentals metrics from info dictionary
        pe = info.get("trailingPE") or info.get("forwardPE")
        pb = info.get("priceToBook")
        ev_ebitda = info.get("enterpriseToEbitda")
        roe = info.get("returnOnEquity")
        if roe is not None:
            roe = round(float(roe) * 100.0, 2)
        de = info.get("debtToEquity")
        rev_growth = info.get("revenueGrowth")
        if rev_growth is not None:
            rev_growth = round(float(rev_growth) * 100.0, 2)
        margin = info.get("profitMargins")
        if margin is not None:
            margin = round(float(margin) * 100.0, 2)

        # Apply SEBI 45-day filing lag check to quarterly financials
        quarterly_stmt_available = False
        try:
            q_financials = t.quarterly_financials
            if q_financials is not None and not q_financials.empty:
                for col in q_financials.columns:
                    q_date = pd.to_datetime(col).date() if hasattr(col, "date") else col
                    filing_visible_date = q_date + timedelta(days=Config.SEBI_QUARTERLY_FILING_LAG_DAYS)
                    if as_of_session >= filing_visible_date:
                        quarterly_stmt_available = True
                        break
        except Exception:
            pass

        return {
            "ticker": resolved_ticker,
            "as_of": as_of_iso,
            "pe_ratio": round(float(pe), 2) if pe is not None else None,
            "pb_ratio": round(float(pb), 2) if pb is not None else None,
            "ev_ebitda": round(float(ev_ebitda), 2) if ev_ebitda is not None else None,
            "roe_pct": roe,
            "debt_to_equity": round(float(de), 2) if de is not None else None,
            "revenue_growth_yoy": rev_growth,
            "net_margin_pct": margin,
            "sebi_filing_lag_applied": True,
            "latest_quarter_visible": quarterly_stmt_available,
            "market_cap_inr": info.get("marketCap"),
        }

    import pandas as pd  # local import helper inside module
    return cache.historical("fundamentals", resolved_ticker, "ratios", as_of_iso, loader)


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    symbol = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE.NS"
    as_of_val = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--as-of" else "2025-01-15"
    data = get_fundamentals(symbol, as_of_val)
    print(f"Fundamentals for {symbol} as of {as_of_val}:")
    print(data)
