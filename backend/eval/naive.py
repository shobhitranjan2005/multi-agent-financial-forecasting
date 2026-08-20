"""Non-LLM baselines (Task 2.8, item 5).

Two of them, and both are load-bearing:

momentum_persistence
    "Tomorrow looks like yesterday." Predicts the next 21 sessions will move the
    same way as the last 21. If the LLM cannot beat this, the LLM is not adding
    anything a two-line rule does not already provide — and that is a publishable
    finding, not a failure.

always_up (buy-and-hold NIFTY proxy)
    Predicts "up" every single time. Its raw directional accuracy on a rising
    Indian market is embarrassingly high, which is precisely the point: printing
    it next to the LLM's raw accuracy is what forces the NIFTY-relative column to
    be taken seriously.

Neither costs a token, so both run before any key exists.
"""
from __future__ import annotations

import time
from datetime import date, datetime

from backend.agents.schemas import FinalForecast, ForecastRecord
from backend.config import Config
from backend.context import MarketContext, build as build_context


def _record(
    ctx: MarketContext,
    system: str,
    direction: str,
    confidence: float,
    reasoning: str,
    started: float,
    target_move_pct: float = 0.0,
) -> ForecastRecord:
    last = ctx.last_close
    if last is None:
        forecast = None
    else:
        mid = last * (1 + target_move_pct / 100.0)
        band = abs(last * 0.03)  # +/-3% band, deliberately naive
        forecast = FinalForecast(
            signal="Buy" if direction == "up" else "Sell",
            target_low_inr=round(mid - band, 2),
            target_high_inr=round(mid + band, 2),
            confidence_pct=confidence,
            expected_direction=direction,  # type: ignore[arg-type]
            risk_report="Mechanical baseline. No risk analysis is performed.",
            key_risks=[],
            reasoning=reasoning,
            citations=[],
        )
    return ForecastRecord(
        ticker=ctx.ticker,
        as_of=str(ctx.as_of),
        system=system,
        last_close_inr=last,
        forecast=forecast,
        horizon_sessions=ctx.horizon_sessions,
        target_date=str(ctx.target_date) if ctx.target_date else None,
        llm_calls=0,
        total_tokens=0,
        seconds=round(time.time() - started, 3),
        parse_failures=0,
        nonce="",
        notes=list(ctx.notes),
    )


def momentum_persistence(
    ticker: str,
    as_of: str | date | datetime,
    *,
    horizon_sessions: int = Config.HORIZON_SESSIONS,
    ctx: MarketContext | None = None,
    **_ignored,
) -> ForecastRecord:
    """Extrapolate the trailing `horizon_sessions` return forwards."""
    started = time.time()
    if ctx is None:
        ctx = build_context(ticker, as_of, horizon_sessions=horizon_sessions)

    closes = ctx.prices["close"] if not ctx.prices.empty else None
    if closes is None or len(closes) <= horizon_sessions:
        return _record(ctx, "naive-momentum", "up", 50.0,
                       "Insufficient history; defaulted to up.", started)

    trailing = float(closes.iloc[-1] / closes.iloc[-horizon_sessions - 1] - 1) * 100
    direction = "up" if trailing >= 0 else "down"
    return _record(
        ctx, "naive-momentum", direction,
        # Confidence scales mildly with the strength of the trend, capped so the
        # calibration comparison stays meaningful.
        min(75.0, 50.0 + abs(trailing)),
        f"Trailing {horizon_sessions}-session return was {trailing:+.2f}%; assumed to persist.",
        started,
        target_move_pct=trailing,
    )


def always_up(
    ticker: str,
    as_of: str | date | datetime,
    *,
    horizon_sessions: int = Config.HORIZON_SESSIONS,
    ctx: MarketContext | None = None,
    **_ignored,
) -> ForecastRecord:
    """Always predicts up — the buy-and-hold proxy."""
    started = time.time()
    if ctx is None:
        ctx = build_context(ticker, as_of, horizon_sessions=horizon_sessions)
    return _record(
        ctx, "naive-alwaysup", "up", 60.0,
        "Unconditional long. Included to expose how flattering raw directional "
        "accuracy is on a trending index.",
        started, target_move_pct=1.5,
    )


REGISTRY = {
    "naive-momentum": momentum_persistence,
    "naive-alwaysup": always_up,
}
