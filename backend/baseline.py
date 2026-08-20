"""Single-LLM baseline (Task 1.7) — the thing the multi-agent system must beat.

One Gemini call. Same evidence pack, same output schema, same scoring path as the
full system. If the multi-agent architecture cannot beat this, that is the
finding, and it is a legitimate result rather than a failure.

Built in Phase 1 deliberately: a comparative claim needs its comparison target to
exist before the harness is written, not after.
"""
from __future__ import annotations

import time
from datetime import date, datetime

from backend import llm
from backend.agents.schemas import FinalForecast, ForecastRecord
from backend.config import Config
from backend.context import MarketContext, build as build_context
from backend.prompts import BASELINE_ROLE, system_prompt

SYSTEM = BASELINE_ROLE

INSTRUCTION = """Issue a forecast for {ticker} over the next {horizon} NSE trading
sessions (from {as_of} to approximately {target_date}).

Return:
  - signal: Buy, Hold or Sell
  - expected_direction: "up" or "down" versus the last close of {last_close}
  - target_low_inr / target_high_inr: a price RANGE in plain INR
  - confidence_pct: 0-100, honestly calibrated
  - risk_report and key_risks
  - reasoning: your analysis
  - citations: the specific evidence values you relied on

Your target range must be reachable in {horizon} sessions. NSE price bands cap
daily moves, so a range implying a move far beyond what {horizon} sessions can
deliver is not a bold call, it is an invalid one.

EVIDENCE
========
{evidence}"""


def forecast(
    ticker: str,
    as_of: str | date | datetime,
    *,
    horizon_sessions: int = Config.HORIZON_SESSIONS,
    nonce: str = "",
    ctx: MarketContext | None = None,
    temperature: float = 0.0,
    with_extras: bool = True,
) -> ForecastRecord:
    """Run the baseline forecaster over one (ticker, as_of).

    `with_extras` controls whether fundamentals/news/macro are included. The
    baseline must see the SAME evidence as the multi-agent system for the
    comparison to isolate architecture rather than data access.
    """
    started = time.time()
    llm.reset_session_usage()

    if ctx is None:
        ctx = build_context(
            ticker,
            as_of,
            horizon_sessions=horizon_sessions,
            with_fundamentals=with_extras,
            with_news=with_extras,
            with_macro=with_extras,
        )

    prompt = INSTRUCTION.format(
        ticker=ctx.ticker,
        horizon=ctx.horizon_sessions,
        as_of=ctx.as_of,
        target_date=ctx.target_date,
        last_close=ctx.last_close,
        evidence=ctx.to_prompt(),
    )

    result = llm.generate(
        prompt,
        system=system_prompt(SYSTEM, str(ctx.as_of)),
        schema=FinalForecast,
        temperature=temperature,
        nonce=nonce,
    )

    notes = list(ctx.notes)
    if result.parse_error:
        notes.append(f"baseline parse failure: {result.parse_error}")

    usage = llm.session_usage()
    return ForecastRecord(
        ticker=ctx.ticker,
        as_of=str(ctx.as_of),
        system="baseline",
        last_close_inr=ctx.last_close,
        forecast=result.parsed,  # type: ignore[arg-type]
        horizon_sessions=ctx.horizon_sessions,
        target_date=str(ctx.target_date) if ctx.target_date else None,
        llm_calls=usage.calls,
        total_tokens=usage.total_tokens,
        seconds=round(time.time() - started, 2),
        parse_failures=usage.parse_failures,
        nonce=nonce,
        notes=notes,
    )
