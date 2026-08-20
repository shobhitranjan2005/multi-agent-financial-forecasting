"""Shared specialist-agent runner.

Every specialist is the same shape: role + evidence slice -> one structured
report. Only the role, the evidence and the output schema differ, so that shape
lives here once. Keeping it in one place also means the leave-one-out ablation in
Phase 4 drops a specialist by not calling it, never by editing agent code.

A specialist that fails to parse returns None rather than raising: one broken
report should degrade the forecast, not abort the run. The failure is counted in
llm.session_usage().parse_failures and reported.
"""
from __future__ import annotations

from typing import Optional, Type, TypeVar

from pydantic import BaseModel

from backend import llm
from backend.prompts import system_prompt

T = TypeVar("T", bound=BaseModel)


def run_specialist(
    *,
    role: str,
    task: str,
    evidence: str,
    schema: Type[T],
    as_of: str,
    temperature: float = 0.0,
    nonce: str = "",
) -> tuple[Optional[T], Optional[str]]:
    """Run one specialist. Returns (report, error_message)."""
    prompt = f"{task.strip()}\n\nEVIDENCE\n========\n{evidence}"
    result = llm.generate(
        prompt,
        system=system_prompt(role, as_of),
        schema=schema,
        temperature=temperature,
        nonce=nonce,
    )
    if result.parsed is None:
        return None, result.parse_error or "empty response"
    return result.parsed, None  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Shared rendering of specialist output
# ---------------------------------------------------------------------------
def render_reports(
    technical=None, fundamental=None, sentiment=None, macro=None
) -> str:
    """Compact digest of the specialist reports, for the debate and the synthesiser.

    Downstream agents see the specialists' CONCLUSIONS, not the raw evidence.
    That is deliberate: if the Bull, the Bear and the Risk Officer all re-read the
    raw price series they are no longer arguing over an analysis, they are each
    redoing it, and the architecture collapses into four copies of the baseline.

    A dropped specialist is rendered as an explicit absence rather than omitted.
    Silence would let the model assume the evidence was neutral; the leave-one-out
    ablation needs it to know the evidence is missing.
    """
    blocks: list[str] = []

    if technical is not None:
        blocks.append(
            f"TECHNICAL ANALYST — score {technical.score:+.1f}/10, trend {technical.trend}\n"
            f"  Support: {technical.support_inr}   Resistance: {technical.resistance_inr}\n"
            f"  {technical.rsi_reading or 'RSI unavailable'}\n"
            f"  {technical.macd_reading or 'MACD unavailable'}\n"
            f"  {technical.sma_reading or 'SMA unavailable'}\n"
            f"  {technical.reasoning}"
        )
    else:
        blocks.append("TECHNICAL ANALYST — no report (specialist unavailable or dropped).")

    if fundamental is not None:
        blocks.append(
            f"FUNDAMENTAL ANALYST — valuation score {fundamental.valuation_score:+.1f}/10, "
            f"health {fundamental.health}\n"
            f"  Intrinsic value: {fundamental.intrinsic_value_inr}   P/E: {fundamental.pe_ratio}\n"
            f"  Revenue growth: {fundamental.revenue_growth_pct}   D/E: {fundamental.debt_to_equity}\n"
            f"  Unavailable fields: {', '.join(fundamental.unavailable_fields) or 'none'}\n"
            f"  {fundamental.reasoning}"
        )
    else:
        blocks.append("FUNDAMENTAL ANALYST — no report (specialist unavailable or dropped).")

    if sentiment is not None:
        blocks.append(
            f"SENTIMENT ANALYST — polarity {sentiment.polarity:+.2f}, "
            f"relevance {sentiment.relevance:.2f}, confidence {sentiment.confidence:.2f}\n"
            f"  Headlines considered: {sentiment.headline_count}\n"
            f"  Catalysts: {'; '.join(sentiment.catalysts) or 'none identified'}\n"
            f"  {sentiment.reasoning}"
        )
    else:
        blocks.append("SENTIMENT ANALYST — no report (specialist unavailable or dropped).")

    if macro is not None:
        blocks.append(
            f"MACRO ANALYST — regime {macro.regime}\n"
            f"  USD/INR: {macro.usdinr_reading or 'unavailable'}\n"
            f"  Crude: {macro.crude_reading or 'unavailable'}\n"
            f"  Rates: {macro.rates_reading or 'unavailable'}\n"
            f"  Sector: {macro.sector_reading or 'unavailable'}\n"
            f"  {macro.reasoning}"
        )
    else:
        blocks.append("MACRO ANALYST — no report (specialist unavailable or dropped).")

    return "\n\n".join(blocks)
