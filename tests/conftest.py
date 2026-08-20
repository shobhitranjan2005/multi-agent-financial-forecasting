"""Shared fixtures.

Everything here is synthetic and offline. The test suite must pass with no
GEMINI_API_KEY, no network and no NSE archive access, because it runs on machines
that have none of those and because a test that needs the internet to tell you
your code is correct is not a test, it is a monitor.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from backend.context import MarketContext
from backend.tools import indicators


@pytest.fixture(scope="session")
def prices() -> pd.DataFrame:
    """300 sessions of a gently rising synthetic series, ending around 1,400 INR."""
    n = 300
    idx = pd.date_range("2024-03-01", periods=n, freq="B")
    rng = np.random.RandomState(20260806)
    close = pd.Series(np.linspace(1200, 1400, n) + rng.randn(n) * 12, index=idx)
    return pd.DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.008,
            "low": close * 0.992,
            "close": close,
            "adj_close": close,
            "volume": rng.randint(1_000_000, 5_000_000, n).astype(float),
        },
        index=idx,
    )


@pytest.fixture(scope="session")
def ctx(prices: pd.DataFrame) -> MarketContext:
    """A complete evidence pack, built without touching the network."""
    return MarketContext(
        ticker="RELIANCE.NS",
        as_of=date(2025, 6, 2),
        last_close=float(prices["close"].iloc[-1]),
        prices=prices,
        indicators=indicators.compute_all(prices),
        benchmark={"last_close": 24_500.0, "return_21d_pct": 1.8, "return_252d_pct": 9.4},
        horizon_sessions=21,
        target_date=date(2025, 7, 1),
        source="yfinance",
        fundamentals={
            # Strict point-in-time mode: no admissible valuation metrics, which is
            # the normal state for a backtested date.
            "metrics": {},
            "current_snapshot": {"pe_trailing": 24.3},
            "point_in_time": True,
            "quarters_visible": [],
            "hidden_quarters": ["2025-03-31"],
            "sector": "Energy",
            "limitations": ["yfinance serves restated financials."],
        },
        news={
            "headlines": [
                {"title": "Company posts steady quarter", "url": "https://example.in/a",
                 "date": "2025-05-30", "domain": "example.in"},
                {"title": "Analysts split on outlook", "url": "https://example.in/b",
                 "date": "2025-05-28", "domain": "example.in"},
            ]
        },
        macro={
            "indicators": {"RBI repo rate %": 6.0},
            "repo_rate": {"repo_rate_pct": 6.0, "effective_from": "2025-04-09",
                          "verified": True},
        },
        notes=[],
    )
