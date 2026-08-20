"""Macro & Sector specialist (Task 3.2).

Agent-side wrapper over tools/macro.analyse_macro, mirroring sentiment.py: the
payload assembly and the vintage filtering live with the data source, and this
module exists so all four specialists share one `analyse(ctx)` signature.

The judgement asked for is deliberately stock-specific rather than market-wide.
A weakening rupee is a tailwind for an IT exporter earning in dollars and a
headwind for an importer or a rate-sensitive bank, so "the macro backdrop is
negative" is not an answer — which way it cuts for THIS stock is.
"""
from __future__ import annotations

from typing import Optional

from backend.agents.schemas import MacroReport
from backend.context import MarketContext


def analyse(
    ctx: MarketContext,
    *,
    temperature: float = 0.0,
    nonce: str = "",
) -> tuple[Optional[MacroReport], Optional[str]]:
    """Produce a MacroReport from the Indian macro payload in `ctx`."""
    if ctx.macro is None:
        return None, "no macro data in context (build with with_macro=True)"

    from backend.tools.macro import analyse_macro

    return analyse_macro(
        ctx.macro, ctx.ticker, str(ctx.as_of), temperature=temperature, nonce=nonce
    )
