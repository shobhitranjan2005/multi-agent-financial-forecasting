"""LangGraph AgentState Definition.

Distinct specialist keys prevent INVALID_CONCURRENT_GRAPH_UPDATE errors
during parallel fan-out execution.
"""
from __future__ import annotations

from typing import List, Optional, TypedDict

from backend.agents.schemas import (
    DebateArgument,
    FinalForecast,
    FundamentalReport,
    MacroReport,
    SentimentReport,
    TechnicalReport,
)


class AgentState(TypedDict, total=False):
    ticker: str
    as_of: str
    nonce: str
    enable_debate: bool

    # Distinct specialist report slots for parallel fan-out
    technical_report: Optional[TechnicalReport]
    fundamental_report: Optional[FundamentalReport]
    sentiment_report: Optional[SentimentReport]
    macro_report: Optional[MacroReport]

    # Reconciliation Gate results
    reconciliation_passed: bool
    reconciliation_notes: List[str]

    # Debate & Synthesis
    debate_transcript: Optional[List[DebateArgument]]
    final_forecast: Optional[FinalForecast]
