"""Evaluation Metrics Engine for Financial Forecasting.

Computes:
1. Directional Accuracy (Raw Up/Down/Hold match)
2. NIFTY-Relative Directional Accuracy (Outperformed NIFTY 50 or not)
3. MAE & MAPE on target price (INR)
4. Brier Score & Confidence Calibration Error
5. Cost & Latency accounting
"""
from __future__ import annotations

import math
from typing import Any, Dict, List


def compute_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute overall evaluation metrics across a list of test item results.

    Each item in `results` must contain:
    - signal: "BUY" | "HOLD" | "SELL"
    - target_price_mid: float
    - confidence_pct: float
    - actual_start_price: float
    - actual_end_price: float
    - actual_nifty_start: float
    - actual_nifty_end: float
    - wall_time_seconds: float
    """
    if not results:
        return {"total_evaluations": 0}

    total = len(results)
    raw_directional_correct = 0
    nifty_relative_correct = 0
    mae_sum = 0.0
    mape_sum = 0.0
    brier_sum = 0.0
    total_time = 0.0

    for item in results:
        p_start = item["actual_start_price"]
        p_end = item["actual_end_price"]
        n_start = item["actual_nifty_start"]
        n_end = item["actual_nifty_end"]

        stock_return_pct = (p_end - p_start) / p_start * 100.0 if p_start > 0 else 0.0
        nifty_return_pct = (n_end - n_start) / n_start * 100.0 if n_start > 0 else 0.0
        excess_return_pct = stock_return_pct - nifty_return_pct

        signal = item.get("signal", "HOLD").upper()
        target_mid = item.get("target_price_mid", p_start)

        # 1. Raw Directional Accuracy
        if signal == "BUY" and stock_return_pct > 0:
            raw_directional_correct += 1
        elif signal == "SELL" and stock_return_pct < 0:
            raw_directional_correct += 1
        elif signal == "HOLD" and abs(stock_return_pct) <= 3.0:
            raw_directional_correct += 1

        # 2. NIFTY-Relative Directional Accuracy
        if signal == "BUY" and excess_return_pct > 0:
            nifty_relative_correct += 1
        elif signal == "SELL" and excess_return_pct < 0:
            nifty_relative_correct += 1
        elif signal == "HOLD" and abs(excess_return_pct) <= 2.0:
            nifty_relative_correct += 1

        # 3. MAE & MAPE on Price Target
        mae = abs(target_mid - p_end)
        mape = (mae / p_end * 100.0) if p_end > 0 else 0.0
        mae_sum += mae
        mape_sum += mape

        # 4. Brier Score Calibration (for binary direction outcome)
        conf_prob = min(1.0, max(0.0, item.get("confidence_pct", 50.0) / 100.0))
        actual_success = 1.0 if (
            (signal == "BUY" and stock_return_pct > 0) or
            (signal == "SELL" and stock_return_pct < 0) or
            (signal == "HOLD" and abs(stock_return_pct) <= 3.0)
        ) else 0.0

        brier_sum += (conf_prob - actual_success) ** 2
        total_time += item.get("wall_time_seconds", 0.0)

    raw_accuracy_pct = round(raw_directional_correct / total * 100.0, 2)
    nifty_relative_accuracy_pct = round(nifty_relative_correct / total * 100.0, 2)
    avg_mae = round(mae_sum / total, 2)
    avg_mape = round(mape_sum / total, 2)
    brier_score = round(brier_sum / total, 4)
    avg_latency_s = round(total_time / total, 2)

    return {
        "total_evaluations": total,
        "raw_directional_accuracy_pct": raw_accuracy_pct,
        "nifty_relative_accuracy_pct": nifty_relative_accuracy_pct,
        "avg_mae_inr": avg_mae,
        "avg_mape_pct": avg_mape,
        "brier_score": brier_score,
        "avg_latency_seconds": avg_latency_s,
    }
