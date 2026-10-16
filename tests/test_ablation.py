"""Unit tests for Step 5 statistical comparisons and ablation report formatting (P6)."""
import pytest
from backend.eval.ablation import (
    aggregate,
    _make_map,
    _pair_stats,
    primary_comparison_verdict,
    debate_verdict,
    leave_one_out_table,
    build_report,
)
from backend.eval.metrics import Scored


def _make_scored(ticker: str, as_of: str, system: str, correct: bool) -> Scored:
    return Scored(
        ticker=ticker,
        as_of=as_of,
        system=system,
        predicted_direction="up" if correct else "down",
        actual_direction="up",
        confidence_pct=65.0,
        target_low=100.0,
        target_high=110.0,
        actual_close=105.0,
        return_pct=5.0,
        benchmark_return_pct=2.0,
        excess_return_pct=3.0,
    )


def test_ablation_ci_and_pair_stats_synthetic():
    # Construct 4 distinct dates with 2 tickers each
    dates = ["2025-04-01", "2025-05-06", "2025-06-04", "2025-07-03"]
    tickers = ["T1.NS", "T2.NS"]

    scored_multi = []
    scored_base = []
    for d in dates:
        for t in tickers:
            scored_multi.append(_make_scored(t, d, "multiagent", correct=True))
            # Baseline gets half of them wrong
            scored_base.append(_make_scored(t, d, "baseline", correct=(t == "T1.NS")))

    map_multi = _make_map([scored_multi])
    map_base = _make_map([scored_base])

    results = {
        "multiagent": {
            "system": "multiagent",
            "directional_accuracy_pct": 100.0,
            "nifty_relative_accuracy_pct": 100.0,
            "brier_score": 0.15,
            "mape_pct": 4.5,
            "mae_inr": 45.0,
            "mean_tokens_per_forecast": 22000.0,
            "mean_seconds_per_forecast": 35.0,
            "n_scoreable": 8,
            "scored_map": map_multi,
        },
        "baseline": {
            "system": "baseline",
            "directional_accuracy_pct": 50.0,
            "nifty_relative_accuracy_pct": 50.0,
            "brier_score": 0.28,
            "mape_pct": 7.2,
            "mae_inr": 72.0,
            "mean_tokens_per_forecast": 3500.0,
            "mean_seconds_per_forecast": 8.0,
            "n_scoreable": 8,
            "scored_map": map_base,
        },
        "multiagent-nodebate": {
            "system": "multiagent-nodebate",
            "directional_accuracy_pct": 75.0,
            "nifty_relative_accuracy_pct": 75.0,
            "brier_score": 0.22,
            "mape_pct": 5.8,
            "mae_inr": 58.0,
            "mean_tokens_per_forecast": 9000.0,
            "mean_seconds_per_forecast": 12.0,
            "n_scoreable": 8,
            "scored_map": map_base,
        },
    }

    # Test pair stats
    pair_str = _pair_stats("multiagent", "baseline", results)
    assert "95% Date-Block CI" in pair_str
    assert "McNemar" in pair_str
    assert "optimistic" in pair_str

    # Test primary comparison verdict section
    prim_report = primary_comparison_verdict(results)
    assert "Directional Accuracy % (Primary)" in prim_report
    assert "Confirmatory Test" in prim_report
    assert "Secondary Paired Test" in prim_report
    assert "+50.00" in prim_report

    # Test debate verdict section
    deb_report = debate_verdict(results)
    assert "With debate" in deb_report
    assert "Without debate" in deb_report

    # Test build report containing primary section
    full_report = build_report(results, repeats=1, limit=None)
    assert "## 1. Primary Research Question: Multi-Agent vs Single-LLM Baseline" in full_report
    assert "## 2. All Configurations" in full_report
    assert "## 3. Exploratory: Does the debate earn its cost?" in full_report
    assert "## 4. Exploratory: Which specialists contribute? (leave-one-out)" in full_report
