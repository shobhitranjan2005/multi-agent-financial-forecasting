"""Chief Risk Officer / Synthesiser (Task 3.5) — the stage that issues the call.

Receives the four specialist reports and, when the debate ran, the full
transcript. Emits the same FinalForecast schema the single-LLM baseline emits, so
the harness scores both through one code path and the comparison is architecture
versus architecture rather than format versus format.

Three things this stage is responsible for:

1. WEIGHING, NOT AVERAGING. The prompt says so explicitly, because splitting the
   difference is the failure mode of any synthesis step: given a +7 technical and
   a -7 fundamental, the lazy answer is Hold at 50% confidence every time, and a
   system that always says Hold is unscoreable on direction and uninformative in
   the report.

2. CALIBRATED CONFIDENCE. The confidence figure is scored with a Brier score and
   a reliability table, so it is a measured output, not decoration. This is the
   most plausible place for the multi-agent system to beat the baseline: not by
   being right more often, but by knowing when it is unsure. The prompt states
   that confidence is scored, which is the honest way to ask for calibration.

3. TEMPERATURE 0. Reproducibility. The Phase 4 variance runs vary the cache nonce,
   not the temperature, so any variance reported is the model's own sampling noise
   at a fixed setting rather than noise we introduced.

The NSE price-band and volatility sanity check on the emitted target is applied
after this stage by the reconciliation gate, which flags rather than clamps in
any scored run - see agents/reconciliation.py.
"""
from __future__ import annotations

from typing import Optional

from backend.agents.base import render_reports, run_specialist
from backend.agents.schemas import FinalForecast
from backend.context import MarketContext
from backend.prompts import RISK_OFFICER_ROLE

TASK = """Issue the final forecast for {ticker} over the next {horizon} NSE
trading sessions, from {as_of} to approximately {target_date}. The last close was
{last_close} INR.

You have four specialist reports{debate_clause}. Weigh them. Where they disagree,
say which analyst you found more credible and why - do not split the difference,
and do not retreat to Hold merely because the evidence is mixed.

Return:
  - signal: Buy, Hold or Sell
  - expected_direction: "up" or "down" versus the last close of {last_close}
  - target_low_inr / target_high_inr: a price RANGE in plain INR
  - confidence_pct: 0-100
  - risk_report: what would have to happen for this call to be wrong
  - key_risks: the specific risks, most material first
  - reasoning: how you weighed the evidence, naming the analysts you relied on
  - citations: the specific figures behind the call

Two constraints on the numbers:

TARGET RANGE. It must be reachable in {horizon} sessions given this stock's own
volatility. A range implying a move far beyond that is not a bold call, it is an
invalid one, and it will be flagged before it reaches a reader.

CONFIDENCE. This figure is scored against outcomes with a Brier score and a
reliability curve. Systematically overconfident forecasts are penalised, and so is
hedging everything at 50. State what you actually believe given how thin or how
strong the evidence turned out to be."""

NO_DEBATE_NOTE = """
This run had NO debate stage: you are reading the specialist reports directly.
Do not invent or imagine an adversarial exchange - reason from the reports."""


def synthesise(
    ctx: MarketContext,
    *,
    technical=None,
    fundamental=None,
    sentiment=None,
    macro=None,
    transcript: str = "",
    temperature: float = 0.0,
    nonce: str = "",
) -> tuple[Optional[FinalForecast], Optional[str]]:
    """Produce the FinalForecast from the specialist reports and the debate.

    `transcript` empty means the --no-debate ablation path. The difference between
    the two calls is exactly one evidence block, which is what makes the ablation
    a clean measurement of the debate's contribution.
    """
    debate_clause = (" and the full Bull/Bear debate transcript" if transcript
                     else ", and no debate transcript (the debate stage was disabled)")

    task = TASK.format(
        ticker=ctx.ticker,
        horizon=ctx.horizon_sessions,
        as_of=ctx.as_of,
        target_date=ctx.target_date,
        last_close=ctx.last_close,
        debate_clause=debate_clause,
    )
    if not transcript:
        task += NO_DEBATE_NOTE

    evidence = (
        "SPECIALIST REPORTS\n==================\n"
        + render_reports(technical, fundamental, sentiment, macro)
    )
    if transcript:
        evidence += "\n\nBULL vs BEAR DEBATE\n===================\n" + transcript

    # The price context is repeated here because the Risk Officer sees the
    # specialists' conclusions rather than the raw series, and a target range has
    # to be anchored to a price to mean anything.
    evidence += (
        f"\n\nPRICE ANCHOR\n============\n"
        f"  Last close on {ctx.as_of}: {ctx.last_close} INR\n"
        f"  Horizon: {ctx.horizon_sessions} NSE sessions to {ctx.target_date}\n"
        f"  Data source: {ctx.source}"
    )
    vol = (ctx.indicators or {}).get("realised_vol_21") or {}
    if vol.get("annualised_vol") is not None:
        evidence += f"\n  Realised annualised volatility: {vol['annualised_vol']:.1%}"

    return run_specialist(
        role=RISK_OFFICER_ROLE,
        task=task,
        evidence=evidence,
        schema=FinalForecast,
        as_of=str(ctx.as_of),
        temperature=temperature,
        nonce=nonce,
    )
