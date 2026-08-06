"""Multi-Agent Financial Forecasting CLI System.

Scope: Indian equities (NSE/BSE).

Usage:
    python main.py RELIANCE.NS --as-of 2025-01-15
    python main.py TCS.NS --as-of 2025-01-15 --no-debate
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from backend.agents.schemas import FinalForecast
from backend.config import Config
from backend.graph.builder import build_forecasting_graph
from backend.tools import calendar_nse, tickers


def run_forecast(
    ticker: str,
    as_of: str,
    enable_debate: bool = True,
    nonce: str = "",
) -> FinalForecast:
    """Run full multi-agent forecast workflow."""
    resolved_ticker = tickers.resolve(ticker)
    as_of_dt = datetime.fromisoformat(as_of)
    as_of_session = calendar_nse.previous_trading_day(as_of_dt)
    as_of_iso = as_of_session.isoformat()

    graph = build_forecasting_graph()

    initial_state = {
        "ticker": resolved_ticker,
        "as_of": as_of_iso,
        "enable_debate": enable_debate,
        "nonce": nonce,
    }

    final_state = graph.invoke(initial_state)
    return final_state["final_forecast"]


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Multi-Agent Financial Forecasting CLI System")
    parser.add_argument("ticker", type=str, help="NSE/BSE ticker symbol (e.g. RELIANCE.NS, TCS.NS)")
    parser.add_argument("--as-of", type=str, default="2025-01-15", help="As-of cutoff date YYYY-MM-DD")
    parser.add_argument("--no-debate", action="store_true", help="Bypass Bull vs Bear debate (Ablation mode)")
    parser.add_argument("--nonce", type=str, default="", help="Nonce for variance runs")

    args = parser.parse_args()

    enable_debate = not args.no_debate

    print(f"\n=======================================================")
    print(f"  MULTI-AGENT FINANCIAL FORECASTING SYSTEM")
    print(f"  Ticker         : {args.ticker}")
    print(f"  As-Of Date     : {args.as_of}")
    print(f"  Debate Mode    : {'ENABLED (Bull vs Bear)' if enable_debate else 'DISABLED (--no-debate ablation)'}")
    print(f"=======================================================\n")

    forecast = run_forecast(
        args.ticker,
        args.as_of,
        enable_debate=enable_debate,
        nonce=args.nonce,
    )

    print("Final Forecast Produced Successfully:")
    print(forecast.model_dump_json(indent=2))
