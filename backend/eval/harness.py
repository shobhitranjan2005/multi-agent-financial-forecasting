"""Evaluation Harness Runner.

Runs any forecasting system over frozen test set `data/testset.json`
and produces a scored results CSV & markdown summary table.

Command line usage:
    python -m backend.eval.harness --system baseline
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from backend.baseline import generate_baseline_forecast
from backend.config import Config
from backend.eval.metrics import compute_metrics
from backend.tools import calendar_nse, market_data, tickers


def run_evaluation(
    system_name: str = "baseline",
    testset_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run full evaluation suite for `system_name` over frozen testset."""
    if testset_path is None:
        testset_path = Config.DATA_DIR / "testset.json"

    if not testset_path.exists():
        raise FileNotFoundError(f"Testset file not found at {testset_path}")

    with open(testset_path, "r", encoding="utf-8") as f:
        test_items = json.load(f)

    results = []

    print(f"\n=======================================================")
    print(f"  RUNNING LEAKAGE-FREE EVALUATION HARNESS")
    print(f"  System under test : {system_name}")
    print(f"  Total test items  : {len(test_items)}")
    print(f"=======================================================\n")

    for i, item in enumerate(test_items, 1):
        ticker = tickers.resolve(item["ticker"])
        as_of_raw = item["as_of"]
        horizon = item.get("horizon_sessions", Config.HORIZON_SESSIONS)

        as_of_dt = datetime.fromisoformat(as_of_raw)
        as_of_session = calendar_nse.previous_trading_day(as_of_dt)
        as_of_iso = as_of_session.isoformat()

        target_session = calendar_nse.add_trading_days(as_of_session, horizon)
        target_iso = target_session.isoformat()

        # 1. Measure wall-clock execution time
        t0 = time.time()
        if system_name == "baseline":
            forecast = generate_baseline_forecast(ticker, as_of_iso)
        elif system_name == "multi_agent":
            from main import run_forecast
            forecast = run_forecast(ticker, as_of_iso, enable_debate=True)
        elif system_name == "no_debate":
            from main import run_forecast
            forecast = run_forecast(ticker, as_of_iso, enable_debate=False)
        else:
            forecast = generate_baseline_forecast(ticker, as_of_iso)
        t1 = time.time()
        wall_time = t1 - t0


        # 2. Fetch realized ground-truth future price movement
        as_of_start_dt = datetime.combine(as_of_session, datetime.min.time())
        target_end_dt = datetime.combine(target_session, datetime.min.time())

        stock_df = market_data.get_price_history(ticker, as_of_start_dt, target_end_dt, target_iso)
        nifty_df = market_data.get_benchmark_history(as_of_start_dt, target_end_dt, target_iso)

        if stock_df.empty or len(stock_df) < 2:
            print(f"[{i}/{len(test_items)}] SKIP {ticker} ({as_of_iso}): Insufficient realized price history")
            continue

        p_start = float(stock_df["close"].iloc[0])
        p_end = float(stock_df["close"].iloc[-1])

        if not nifty_df.empty and len(nifty_df) >= 2:
            n_start = float(nifty_df["close"].iloc[0])
            n_end = float(nifty_df["close"].iloc[-1])
        else:
            n_start, n_end = 23000.0, 23000.0

        stock_ret = (p_end - p_start) / p_start * 100.0
        nifty_ret = (n_end - n_start) / n_start * 100.0
        excess_ret = stock_ret - nifty_ret

        res_entry = {
            "item_idx": i,
            "ticker": ticker,
            "as_of": as_of_iso,
            "target_session": target_iso,
            "signal": forecast.signal,
            "target_price_low": forecast.target_price_low,
            "target_price_mid": forecast.target_price_mid,
            "target_price_high": forecast.target_price_high,
            "confidence_pct": forecast.confidence_pct,
            "actual_start_price": round(p_start, 2),
            "actual_end_price": round(p_end, 2),
            "actual_stock_return_pct": round(stock_ret, 2),
            "actual_nifty_start": round(n_start, 2),
            "actual_nifty_end": round(n_end, 2),
            "actual_nifty_return_pct": round(nifty_ret, 2),
            "actual_excess_return_pct": round(excess_ret, 2),
            "wall_time_seconds": round(wall_time, 2),
        }
        results.append(res_entry)

        print(f"[{i}/{len(test_items)}] {ticker} ({as_of_iso}) -> Signal: {forecast.signal:<4} | Mid: ₹{forecast.target_price_mid:<8.2f} | Actual End: ₹{p_end:<8.2f} | Ret: {stock_ret:+.2f}%")

    # 3. Compute Summary Metrics
    summary = compute_metrics(results)
    summary["system"] = system_name

    # 4. Save CSV results artifact
    out_csv = Config.DATA_DIR / f"eval_results_{system_name}.csv"
    res_df = pd.DataFrame(results)
    res_df.to_csv(out_csv, index=False)

    print("\n=======================================================")
    print("                EVALUATION SUMMARY")
    print("=======================================================")
    print(f" System Tested               : {summary['system']}")
    print(f" Total Evaluated Items       : {summary['total_evaluations']}")
    print(f" Raw Directional Accuracy    : {summary['raw_directional_accuracy_pct']}%")
    print(f" NIFTY-Relative Accuracy     : {summary['nifty_relative_accuracy_pct']}%")
    print(f" Mean Absolute Error (MAE)   : ₹{summary['avg_mae_inr']}")
    print(f" Mean Abs Pct Error (MAPE)   : {summary['avg_mape_pct']}%")
    print(f" Brier Score (Calibration)   : {summary['brier_score']}")
    print(f" Avg Latency per Forecast    : {summary['avg_latency_seconds']} s")
    print(f" Detailed CSV Saved To       : {out_csv}")
    print("=======================================================\n")

    return summary


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Financial Forecasting Evaluation Harness")
    parser.add_argument("--system", type=str, default="baseline", help="System name (default: baseline)")
    args = parser.parse_args()

    run_evaluation(system_name=args.system)
