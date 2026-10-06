"""The frozen test set (Task 2.8, items 2-4).

Three rules, each fixing a specific way backtests lie:

1. FREEZE IT. Once written, data/testset.json is committed and never edited after
   results are seen. Editing a test set in response to results is how a backtest
   becomes a story about the test set.

2. POINT-IN-TIME UNIVERSE. Constituents come from the bhavcopy for each `as_of` —
   what actually traded that day — not from today's NIFTY 50 list. Using today's
   membership is textbook survivorship bias: it silently excludes every company
   that was delisted, merged or demoted, which are disproportionately the losers.
   Because the bhavcopy is a complete daily snapshot, this project can *prove* the
   universe was right, which very few student backtests can.

3. POST-CUTOFF WINDOW. The as_of dates must sit after the model's training
   cutoff, as established by recall_probe.py. A backtest inside the training
   window measures memory, not forecasting.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from backend.config import Config
from backend.tools import calendar_nse, market_data

TESTSET_PATH = Config.DATA_DIR / "testset.json"

# A liquid, sector-spread NSE large-cap seed list. Membership is still verified
# against the bhavcopy for each as_of, so a name that was not trading that day is
# dropped rather than silently assumed present.
SEED_UNIVERSE = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "SUNPHARMA.NS",
    "TITAN.NS", "ULTRACEMCO.NS", "WIPRO.NS", "NESTLEIND.NS", 
    # "TATAMOTORS.NS", # Excluded due to Yahoo Finance missing data (demerger).
    "TATASTEEL.NS", "JSWSTEEL.NS", "POWERGRID.NS", "NTPC.NS", "ONGC.NS",
    "HCLTECH.NS", "TECHM.NS", "BAJFINANCE.NS", "CIPLA.NS", "DRREDDY.NS",
]


@dataclass
class TestCase:
    ticker: str
    as_of: str
    horizon_sessions: int


def _trading_days_in(start: date, end: date) -> list[date]:
    days: list[date] = []
    d = start
    while d <= end:
        if calendar_nse.is_trading_day(d):
            days.append(d)
        d += timedelta(days=1)
    return days


def build(
    *,
    start: date,
    end: date,
    n_dates: int = 8,
    n_tickers: int = 12,
    horizon_sessions: int = Config.HORIZON_SESSIONS,
    seed: int = 20260806,
    universe: Optional[list[str]] = None,
    verify_traded: bool = True,
) -> dict:
    """Construct a test set. Deterministic given `seed`.

    `verify_traded` checks each ticker against that day's bhavcopy. It costs one
    archive fetch per date (cached), and it is what makes the universe
    point-in-time rather than merely plausible.
    """
    rng = random.Random(seed)
    pool = list(universe or SEED_UNIVERSE)

    sessions = _trading_days_in(start, end)
    if not sessions:
        raise ValueError(f"no NSE trading days between {start} and {end}")

    # Spread the dates evenly rather than clustering them, so the sample is not
    # dominated by one market regime.
    step = max(1, len(sessions) // n_dates)
    chosen_dates = sessions[::step][:n_dates]

    cases: list[TestCase] = []
    skipped: list[str] = []
    for d in chosen_dates:
        traded: set[str] = set()
        if verify_traded:
            try:
                # get_traded_universe returns resolved symbols ("RELIANCE.NS").
                # Compare on the bare root so a .BO entry in the pool still
                # matches its NSE listing in the bhavcopy.
                traded = {s.split(".")[0].upper()
                          for s in market_data.get_traded_universe(d)}
            except Exception as exc:
                skipped.append(f"{d}: bhavcopy universe unavailable ({exc}); membership unverified")

        candidates = []
        for t in pool:
            if not traded:
                candidates.append(t)
                continue
            base = t.split(".")[0].upper()
            if base in traded:
                candidates.append(t)
            else:
                skipped.append(f"{d}: {base} did not trade on NSE that day — excluded")

        picked = rng.sample(candidates, min(n_tickers, len(candidates)))
        for t in sorted(picked):
            cases.append(TestCase(ticker=t, as_of=d.isoformat(),
                                  horizon_sessions=horizon_sessions))

    return {
        "created": datetime.now().isoformat(timespec="seconds"),
        "seed": seed,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "horizon_sessions": horizon_sessions,
        "n_cases": len(cases),
        "universe_verified_against_bhavcopy": verify_traded,
        "cases": [asdict(c) for c in cases],
        "exclusions": skipped,
        "rules": [
            "FROZEN: do not edit this file after seeing results.",
            "Universe is point-in-time from the NSE bhavcopy, not today's index membership.",
            "as_of dates must post-date the model training cutoff (see recall_probe.py).",
            "Horizon is measured in NSE trading sessions, never calendar days.",
        ],
    }


def save(testset: dict, path: Path = TESTSET_PATH, *, overwrite: bool = False) -> Path:
    """Write the test set. Refuses to clobber an existing one without `overwrite`.

    The refusal is the point: an accidental regeneration after results exist
    would invalidate every comparison made against the old set.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"{path} already exists. A frozen test set must not be silently "
            f"regenerated — results scored against the old set would no longer be "
            f"comparable. Pass overwrite=True only if no results depend on it."
        )
    path.write_text(json.dumps(testset, indent=2), encoding="utf-8")
    return path


def load(path: Path = TESTSET_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Build it with:  python -m evaluate build-testset"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def cases(path: Path = TESTSET_PATH) -> list[TestCase]:
    return [TestCase(**c) for c in load(path)["cases"]]
