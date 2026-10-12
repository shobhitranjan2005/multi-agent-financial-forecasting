"""Training-cutoff recall probe (Task 2.8, item 1).

The problem this solves: if the test window sits inside the model's training
data, the "forecast" may be recall. The result would look excellent and mean
nothing. Every backtest of an LLM has this problem and most papers wave at it.

The probe asks Gemini for hard, verifiable Indian market facts on specific dates —
a NIFTY 50 close, a quarterly revenue figure — and compares the answer to the real
value from our own data layer. Dates where it can recall the answer are inside the
training window and are disqualified from the test set.

The output is a figure in the report: "the model could recall market outcomes up
to approximately DATE, so the evaluation window begins after it."

Interpretation matters, and both directions are informative:
  - Accurate recall  -> that date is contaminated. Exclude it.
  - Refusal / wrong  -> evidence the date is outside the training window.
A refusal is weaker evidence than a wrong answer: a model may decline to guess
something it does know. Say so in the report rather than overclaiming.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from backend import llm
from backend.config import Config
from backend.tools import calendar_nse, market_data, macro

PROBE_PATH = Config.DATA_DIR / "recall_probe.json"

# Tolerance for "did it actually recall this?" NIFTY 50 sits around 20-25k, so
# 0.5% is roughly +/-110 points: far tighter than a guess, loose enough that a
# genuine memory with rounding still counts as recall.
RECALL_TOLERANCE_PCT = 0.5


class NiftyRecall(BaseModel):
    """Flat schema — Gemini misreads nested ones as tool calls."""

    knows_answer: bool = Field(description="True only if you actually recall this specific value")
    nifty_close: Optional[float] = Field(description="NIFTY 50 closing level, or null if unknown")
    stated_confidence: float = Field(description="0-1")
    source_of_knowledge: str = Field(description="Briefly: recall, inference, or guess")


class EventRecall(BaseModel):
    """Second contamination signal: dated macroeconomic event verifiable from cached data."""

    knows_answer: bool = Field(description="True only if you actually recall this specific event fact")
    repo_rate: Optional[float] = Field(description="RBI policy repo rate in percentage (e.g. 6.50, 6.25, 6.00), or null if unknown")
    stated_confidence: float = Field(description="0-1")
    source_of_knowledge: str = Field(description="Briefly: recall, inference, or guess")


@dataclass
class ProbeResult:
    probe_date: str
    actual_close: Optional[float]
    claimed_close: Optional[float]
    claims_knowledge: bool
    error_pct: Optional[float]
    recalled: bool
    note: str
    actual_event_repo_rate: Optional[float] = None
    claimed_event_repo_rate: Optional[float] = None
    event_claims_knowledge: bool = False
    event_recalled: bool = False
    event_note: str = ""


PROMPT = """What was the closing level of the NIFTY 50 index on {d}?

Answer only if you genuinely recall this specific figure. Do not estimate from a
trend, do not interpolate, and do not infer it from nearby dates — if you do not
know it, set knows_answer to false and nifty_close to null. An honest "I do not
know" is the correct and useful answer here; a plausible-looking guess is worse
than useless because it corrupts a measurement."""


EVENT_PROMPT = """What was the Reserve Bank of India (RBI) benchmark policy repo rate (in percentage) in effect on {d}?

Answer only if you genuinely recall this specific fact. Do not infer or guess — if you do not
know it, set knows_answer to false and repo_rate to null. An honest "I do not
know" is the correct and useful answer here; a plausible-looking guess is worse
than useless because it corrupts a measurement."""


def _actual_nifty_close(d: date) -> Optional[float]:
    """Ground truth from our own data layer."""
    try:
        df = market_data.get_benchmark_history(
            start=(d - timedelta(days=30)).isoformat(),
            end=d.isoformat(),
            as_of=d.isoformat(),
        )
        if df.empty:
            return None
        return round(float(df["close"].iloc[-1]), 2)
    except Exception:
        return None


def _actual_rbi_repo_rate(d: date) -> Optional[float]:
    """Ground truth from cached RBI monetary policy schedule, verified through 2025-08-31."""
    try:
        info = macro.repo_rate_at(d)
        if not info.get("verified", False):
            return None  # Ground truth verified only through 2025-08-31
        return info.get("repo_rate_pct")
    except Exception:
        return None


def probe_date(d: date, *, nonce: str = "") -> ProbeResult:
    """Probe one date with two signals (index price recall + dated event recall). Uses temperature 0."""
    actual = _actual_nifty_close(d)
    res = llm.generate(
        PROMPT.format(d=d.isoformat()),
        schema=NiftyRecall,
        temperature=0.0,
        nonce=nonce,
        system=("You are being tested for factual recall of Indian market history. "
                "Accuracy about what you do and do not know matters more than "
                "appearing knowledgeable."),
    )
    parsed: Optional[NiftyRecall] = res.parsed  # type: ignore[assignment]

    if parsed is None:
        p_res = ProbeResult(d.isoformat(), actual, None, False, None, False,
                            f"probe parse failure: {res.parse_error}")
    elif actual is None:
        p_res = ProbeResult(d.isoformat(), None, parsed.nifty_close, parsed.knows_answer,
                            None, False, "no ground truth available for this date")
    elif not parsed.knows_answer or parsed.nifty_close is None:
        p_res = ProbeResult(d.isoformat(), actual, None, False, None, False,
                            "model declined — weak evidence the date is post-cutoff")
    else:
        err = abs(parsed.nifty_close - actual) / actual * 100
        recalled = err <= RECALL_TOLERANCE_PCT
        p_res = ProbeResult(
            d.isoformat(), actual, parsed.nifty_close, True, round(err, 3), recalled,
            "RECALLED — this date is inside the training window"
            if recalled else f"claimed but wrong by {err:.2f}% — not genuine recall",
        )

    # Signal 2: Dated event verifiable from cached macro data (RBI policy repo rate in effect)
    actual_repo = _actual_rbi_repo_rate(d)
    res_ev = llm.generate(
        EVENT_PROMPT.format(d=d.isoformat()),
        schema=EventRecall,
        temperature=0.0,
        nonce=nonce,
        system=("You are being tested for factual recall of Indian macroeconomic events. "
                "Accuracy about what you do and do not know matters more than "
                "appearing knowledgeable."),
    )
    parsed_ev: Optional[EventRecall] = res_ev.parsed  # type: ignore[assignment]
    if parsed_ev is None:
        p_res.actual_event_repo_rate = actual_repo
        p_res.event_note = f"event probe parse failure: {res_ev.parse_error}"
    elif actual_repo is None:
        p_res.event_note = f"date is past verified RBI decision calendar (through {macro.RBI_VERIFIED_THROUGH}) — unverified"
    elif not parsed_ev.knows_answer or parsed_ev.repo_rate is None:
        p_res.actual_event_repo_rate = actual_repo
        p_res.event_note = "model declined repo rate — weak evidence the date is post-cutoff"
    else:
        p_res.actual_event_repo_rate = actual_repo
        p_res.claimed_event_repo_rate = parsed_ev.repo_rate
        p_res.event_claims_knowledge = True
        p_res.event_recalled = abs(parsed_ev.repo_rate - actual_repo) <= 0.05
        p_res.event_note = (
            "EVENT RECALLED — RBI repo rate known"
            if p_res.event_recalled
            else f"claimed {parsed_ev.repo_rate}% vs actual {actual_repo}% — not genuine recall"
        )

    return p_res


def sweep(
    start: date,
    end: date,
    *,
    step_days: int = 30,
    nonce: str = "",
) -> dict:
    """Probe across a date range to locate the recall boundary."""
    results: list[ProbeResult] = []
    d = start
    while d <= end:
        session = calendar_nse.previous_trading_day(d)
        results.append(probe_date(session, nonce=nonce))
        d += timedelta(days=step_days)

    recalled = [r for r in results if r.recalled]
    latest_recalled = max((r.probe_date for r in recalled), default=None)
    errors = [r.error_pct for r in results if r.error_pct is not None]

    event_recalled = [r for r in results if r.event_recalled]
    latest_event_recalled = max((r.probe_date for r in event_recalled), default=None)

    # Any signal recall
    any_recalled_dates = sorted(set([r.probe_date for r in recalled] + [r.probe_date for r in event_recalled]))
    latest_any_recalled = max(any_recalled_dates, default=None)

    return {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "model": Config.GEMINI_MODEL,
        "tolerance_pct": RECALL_TOLERANCE_PCT,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "n_probes": len(results),
        "n_recalled": len(recalled),
        "latest_recalled_date": latest_recalled,
        "median_error_pct": round(statistics.median(errors), 3) if errors else None,
        "n_event_recalled": len(event_recalled),
        "latest_event_recalled_date": latest_event_recalled,
        "latest_any_recalled_date": latest_any_recalled,
        "primary_criterion": (
            "Documented model training cutoff (January 2025 for gemini-3.1-flash-lite) is "
            "the primary criterion: all test set as_of dates must begin >= cutoff + 2 months "
            "(i.e. >= 2025-04-01). Exact price and dated event recall probes serve as secondary "
            "empirical checks."
        ),
        "recommended_testset_start": (
            max(
                "2025-04-01",
                (datetime.fromisoformat(latest_any_recalled).date() + timedelta(days=30)).isoformat()
                if latest_any_recalled else "2025-04-01"
            )
        ),
        "interpretation": (
            "Test-set as_of dates must sit post-cutoff. Documented cutoff is primary; "
            "empirical probes report both exact index close and dated RBI repo rate events. "
            "A refusal is weaker evidence than a wrong answer."
        ),
        "probes": [r.__dict__ for r in results],
    }


def save(result: dict, path: Path = PROBE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return path
