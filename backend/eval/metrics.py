"""Scoring metrics (Task 2.8, item 5).

The headline number is directional accuracy, but it is reported alongside
NIFTY-relative accuracy for a specific reason: Indian indices have trended up
strongly, so a model that answers "up" every time can post ~60% raw accuracy and
look like a forecaster. Excess-return scoring removes that illusion, and an
examiner will ask for it.

Calibration is scored with the Brier score plus a reliability table. This is where
a multi-agent system with an explicit risk officer ought to beat a single call:
not necessarily by being right more often, but by knowing when it is unsure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Iterable, Optional


@dataclass
class Scored:
    """One forecast joined to its realised outcome."""

    ticker: str
    as_of: str
    system: str
    predicted_direction: Optional[str]
    actual_direction: Optional[str]
    confidence_pct: Optional[float]
    target_low: Optional[float]
    target_high: Optional[float]
    actual_close: Optional[float]
    return_pct: Optional[float]
    benchmark_return_pct: Optional[float]
    excess_return_pct: Optional[float]
    tokens: int = 0
    seconds: float = 0.0
    llm_calls: int = 0
    parse_failed: bool = False
    note: Optional[str] = None

    @property
    def scoreable(self) -> bool:
        return self.predicted_direction is not None and self.actual_direction is not None

    @property
    def direction_correct(self) -> Optional[bool]:
        if not self.scoreable:
            return None
        return self.predicted_direction == self.actual_direction

    @property
    def relative_correct(self) -> Optional[bool]:
        """Did the model call the stock's move versus NIFTY 50 correctly?

        "up" is read as "expected to beat the index" — the excess-return reading
        of a directional call.
        """
        if self.predicted_direction is None or self.excess_return_pct is None:
            return None
        actual_beat = self.excess_return_pct > 0
        predicted_beat = self.predicted_direction == "up"
        return actual_beat == predicted_beat

    @property
    def target_midpoint(self) -> Optional[float]:
        if self.target_low is None or self.target_high is None:
            return None
        return (self.target_low + self.target_high) / 2

    @property
    def absolute_error(self) -> Optional[float]:
        mid = self.target_midpoint
        if mid is None or self.actual_close is None:
            return None
        return abs(mid - self.actual_close)

    @property
    def absolute_pct_error(self) -> Optional[float]:
        mid = self.target_midpoint
        if mid is None or not self.actual_close:
            return None
        return abs(mid - self.actual_close) / self.actual_close * 100

    @property
    def in_range(self) -> Optional[bool]:
        if self.target_low is None or self.target_high is None or self.actual_close is None:
            return None
        return self.target_low <= self.actual_close <= self.target_high

    @property
    def brier(self) -> Optional[float]:
        """Brier score for the directional call.

        The forecast probability is confidence in the stated direction, mapped to
        P(up). Lower is better; 0.25 is what you get by always saying 50%.
        """
        if self.confidence_pct is None or self.actual_direction is None:
            return None
        p_stated = max(0.0, min(1.0, self.confidence_pct / 100.0))
        p_up = p_stated if self.predicted_direction == "up" else 1.0 - p_stated
        outcome_up = 1.0 if self.actual_direction == "up" else 0.0
        return (p_up - outcome_up) ** 2


def _pct(values: Iterable[Optional[bool]]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return round(100.0 * sum(1 for v in vals if v) / len(vals), 2)


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return round(mean(vals), 4) if vals else None


def reliability_table(rows: list[Scored], bins: int = 5) -> list[dict]:
    """Confidence bucket -> claimed vs realised accuracy.

    A well-calibrated forecaster is right about 70% of the time when it says 70%.
    Systematic overconfidence shows here as realised accuracy sitting below the
    bucket, and it is the plot that goes in the report.
    """
    usable = [r for r in rows if r.confidence_pct is not None and r.direction_correct is not None]
    width = 100.0 / bins
    out = []
    for i in range(bins):
        lo, hi = i * width, (i + 1) * width
        bucket = [r for r in usable if lo <= r.confidence_pct < hi or (i == bins - 1 and r.confidence_pct == 100)]
        if not bucket:
            out.append({"bucket": f"{lo:.0f}-{hi:.0f}%", "n": 0,
                        "mean_confidence": None, "realised_accuracy": None, "gap": None})
            continue
        claimed = mean(r.confidence_pct for r in bucket)
        realised = 100.0 * sum(1 for r in bucket if r.direction_correct) / len(bucket)
        out.append({
            "bucket": f"{lo:.0f}-{hi:.0f}%",
            "n": len(bucket),
            "mean_confidence": round(claimed, 1),
            "realised_accuracy": round(realised, 1),
            "gap": round(realised - claimed, 1),  # negative = overconfident
        })
    return out


def summarise(rows: list[Scored], system: str = "") -> dict:
    """Aggregate metrics for one system over the frozen test set."""
    scoreable = [r for r in rows if r.scoreable]
    return {
        "system": system or (rows[0].system if rows else ""),
        "n_forecasts": len(rows),
        "n_scoreable": len(scoreable),
        "n_parse_failures": sum(1 for r in rows if r.parse_failed),

        # Headline
        "directional_accuracy_pct": _pct(r.direction_correct for r in rows),
        # The number that kills the "always say up" illusion
        "nifty_relative_accuracy_pct": _pct(r.relative_correct for r in rows),

        "mae_inr": _mean(r.absolute_error for r in rows),
        "mape_pct": _mean(r.absolute_pct_error for r in rows),
        "target_hit_rate_pct": _pct(r.in_range for r in rows),

        "brier_score": _mean(r.brier for r in rows),
        "mean_confidence_pct": _mean(r.confidence_pct for r in rows),
        # Positive = overconfident by this many points
        "overconfidence_gap_pts": (
            round(_mean(r.confidence_pct for r in rows) - _pct(r.direction_correct for r in rows), 2)
            if _mean(r.confidence_pct for r in rows) is not None
            and _pct(r.direction_correct for r in rows) is not None else None
        ),

        # Cost — the other half of "is the debate worth it?"
        "total_tokens": sum(r.tokens for r in rows),
        "mean_tokens_per_forecast": _mean(float(r.tokens) for r in rows),
        "mean_seconds_per_forecast": _mean(r.seconds for r in rows),
        "total_llm_calls": sum(r.llm_calls for r in rows),

        "mean_return_pct": _mean(r.return_pct for r in rows),
        "mean_excess_return_pct": _mean(r.excess_return_pct for r in rows),
    }


def markdown_table(summaries: list[dict]) -> str:
    """Comparison table across systems, ready to paste into the report."""
    if not summaries:
        return "_no results_"
    cols = [
        ("system", "System"),
        ("n_scoreable", "N"),
        ("directional_accuracy_pct", "Dir. acc %"),
        ("nifty_relative_accuracy_pct", "vs NIFTY %"),
        ("mape_pct", "MAPE %"),
        ("brier_score", "Brier"),
        ("overconfidence_gap_pts", "Overconf."),
        ("mean_tokens_per_forecast", "Tokens/fc"),
        ("mean_seconds_per_forecast", "Sec/fc"),
    ]
    head = "| " + " | ".join(label for _, label in cols) + " |"
    rule = "| " + " | ".join([":---"] + ["---:"] * (len(cols) - 1)) + " |"
    lines = [head, rule]
    for s in summaries:
        cells = []
        for key, _ in cols:
            v = s.get(key)
            cells.append("—" if v is None else (f"{v:,.2f}" if isinstance(v, float) else str(v)))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
