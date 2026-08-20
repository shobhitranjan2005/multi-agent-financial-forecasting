"""Fundamental Analysis specialist (Task 3.2).

Follows the template set by technical.py: take only the evidence slice this
analyst is entitled to, run one structured call, return a typed report.

The interesting case here is the EMPTY one. Under the strict point-in-time rule
in tools/fundamentals.py, a backtest dated in the past gets no valuation metrics
at all — yfinance `.info` describes the company today, so serving it would tell
the model the answer it is meant to forecast. What survives is the sector, and
any quarterly result whose SEBI filing date had already passed.

That means this specialist frequently has almost nothing to work with, and the
prompt says so explicitly. The failure mode we are guarding against is a model
that fills the silence with a remembered P/E — which would be lookahead bias
arriving through the model's weights rather than through the data layer.
"""
from __future__ import annotations

from typing import Optional

from backend.agents.base import run_specialist
from backend.agents.schemas import FundamentalReport
from backend.context import MarketContext
from backend.prompts import FUNDAMENTAL_ROLE

TASK = """Assess the financial health and valuation of {ticker} as of {as_of},
over a {horizon}-session horizon.

Return:
  - valuation_score: -10 (badly overvalued) to +10 (badly undervalued)
  - intrinsic_value_inr: per-share fair value in plain INR, or null
  - health: Strong, Stable, Weak or Distressed
  - pe_ratio, revenue_growth_pct, debt_to_equity: ONLY if present in the evidence
  - unavailable_fields: every metric the evidence did not give you
  - reasoning
  - citations: the exact figures you used

CRITICAL. Some or all valuation metrics may be withheld, because a current
valuation snapshot is not what was knowable on {as_of}. If a figure is not in the
evidence below, it is unavailable to you. Do not recall it, do not infer it from
the share price, do not substitute a sector-typical value. List it in
unavailable_fields and lower your confidence accordingly.

If the evidence contains no admissible valuation data at all, the correct answer
is valuation_score near 0 with health judged only from what you were given, and a
reasoning that says the fundamental picture is unknown at this date. That is a
finding about free-data coverage, not a failure on your part."""


def analyse(
    ctx: MarketContext,
    *,
    temperature: float = 0.0,
    nonce: str = "",
) -> tuple[Optional[FundamentalReport], Optional[str]]:
    """Produce a FundamentalReport from the point-in-time fundamentals in `ctx`."""
    if ctx.fundamentals is None:
        return None, "no fundamentals in context (build with with_fundamentals=True)"

    from backend.context import _render_fundamentals

    evidence = _render_fundamentals(ctx.fundamentals)
    limits = ctx.fundamentals.get("limitations") or []
    if limits:
        evidence += "\n\nSOURCE LIMITATIONS\n" + "\n".join(f"  - {l}" for l in limits)

    return run_specialist(
        role=FUNDAMENTAL_ROLE,
        task=TASK.format(
            ticker=ctx.ticker, as_of=ctx.as_of, horizon=ctx.horizon_sessions
        ),
        evidence=evidence,
        schema=FundamentalReport,
        as_of=str(ctx.as_of),
        temperature=temperature,
        nonce=nonce,
    )
