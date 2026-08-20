"""Technical Analysis specialist (Task 1.8).

This is the template the other three specialists follow: take the slice of the
evidence pack this analyst is entitled to, run one structured call, return a
typed report.

Note the deliberate narrowing — the technical agent is given price and indicator
evidence ONLY, not fundamentals or news. If every specialist sees everything they
converge on the same answer and the ensemble adds nothing, which would make the
Phase 4 leave-one-out ablation meaningless.
"""
from __future__ import annotations

from typing import Optional

from backend.agents.base import run_specialist
from backend.agents.schemas import TechnicalReport
from backend.context import MarketContext
from backend.prompts import TECHNICAL_ROLE

TASK = """Analyse the price action and momentum of {ticker} as of {as_of}, and
judge the outlook over the next {horizon} NSE trading sessions.

Return:
  - score: -10 (max bearish) to +10 (max bullish)
  - trend: Uptrend, Downtrend or Sideways
  - support_inr / resistance_inr: nearest levels in plain INR, from the price data
  - rsi_reading, macd_reading, sma_reading: short plain-English readings
  - reasoning
  - citations: the exact indicator values you used, e.g. "RSI(14)=72.4 at {as_of}"

Use only the indicator values supplied. If an indicator is marked unavailable,
say so - do not estimate it from the price series yourself."""


def analyse(
    ctx: MarketContext,
    *,
    temperature: float = 0.0,
    nonce: str = "",
) -> tuple[Optional[TechnicalReport], Optional[str]]:
    """Produce a TechnicalReport from the price/indicator evidence in `ctx`."""
    evidence = "\n\n".join([
        ctx.price_block(),
        ctx.indicator_block(),
        ctx.benchmark_block(),
    ])
    return run_specialist(
        role=TECHNICAL_ROLE,
        task=TASK.format(
            ticker=ctx.ticker, as_of=ctx.as_of, horizon=ctx.horizon_sessions
        ),
        evidence=evidence,
        schema=TechnicalReport,
        as_of=str(ctx.as_of),
        temperature=temperature,
        nonce=nonce,
    )
