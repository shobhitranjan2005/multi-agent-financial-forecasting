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
from backend.tools import calendar_nse, market_data

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


@dataclass
class ProbeResult:
    probe_date: str
    actual_close: Optional[float]
    claimed_close: Optional[float]
    claims_knowledge: bool
    error_pct: Optional[float]
    recalled: bool
    note: str


PROMPT = """What was the closing level of the NIFTY 50 index on {d}?

Answer only if you genuinely recall this specific figure. Do not estimate from a
trend, do not interpolate, and do not infer it from nearby dates — if you do not
know it, set knows_answer to false and nifty_close to null. An honest "I do not
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


def probe_date(d: date, *, nonce: str = "") -> ProbeResult:
    """Probe one date. Uses temperature 0 — we are testing memory, not creativity."""
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
        return ProbeResult(d.isoformat(), actual, None, False, None, False,
                           f"probe parse failure: {res.parse_error}")
    if actual is None:
        return ProbeResult(d.isoformat(), None, parsed.nifty_close, parsed.knows_answer,
                           None, False, "no ground truth available for this date")
    if not parsed.knows_answer or parsed.nifty_close is None:
        return ProbeResult(d.isoformat(), actual, None, False, None, False,
                           "model declined — weak evidence the date is post-cutoff")

    err = abs(parsed.nifty_close - actual) / actual * 100
    recalled = err <= RECALL_TOLERANCE_PCT
    return ProbeResult(
        d.isoformat(), actual, parsed.nifty_close, True, round(err, 3), recalled,
        "RECALLED — this date is inside the training window"
        if recalled else f"claimed but wrong by {err:.2f}% — not genuine recall",
    )


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

    return {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "model": Config.GEMINI_MODEL,
        "tolerance_pct": RECALL_TOLERANCE_PCT,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "n_probes": len(results),
        "n_recalled": len(recalled),
        "latest_recalled_date": latest_recalled,
        "median_error_pct": round(statistics.median(errors), 3) if errors else None,
        "recommended_testset_start": (
            (datetime.fromisoformat(latest_recalled).date() + timedelta(days=30)).isoformat()
            if latest_recalled else start.isoformat()
        ),
        "interpretation": (
            "Test-set as_of dates must start after latest_recalled_date. A refusal is "
            "weaker evidence than a wrong answer — the model may decline on facts it "
            "holds. Report both counts rather than only the boundary."
        ),
        "probes": [r.__dict__ for r in results],
    }


def save(result: dict, path: Path = PROBE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return path
