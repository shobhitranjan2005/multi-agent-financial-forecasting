"""LangGraph state definition (Task 3.6).

Two details here are not stylistic — the graph crashes or corrupts without them.

DISTINCT KEYS PER SPECIALIST. The four specialists run as a parallel fan-out. If
they wrote to one shared `reports` key, LangGraph would raise
INVALID_CONCURRENT_GRAPH_UPDATE: two nodes returning a value for the same key in
one superstep is ambiguous, and the framework refuses to guess. Each specialist
therefore owns its own key and no two nodes ever write the same one.

REDUCERS ON THE ACCUMULATED LISTS. `debate` and `errors` are written by more than
one node, so they carry `operator.add`. Without the reducer the last writer wins
and every earlier turn or error silently disappears — which is worse than a crash,
because the run still produces a forecast and the transcript is just short.

WHAT IS NOT IN THE STATE. The MarketContext holds a pandas DataFrame and is not
usefully serialisable into a checkpoint. It is also entirely reconstructible from
(ticker, as_of) through the permanent SQLite cache, at zero network cost. So the
state carries the run key and the nodes look the context up. A resumed run rebuilds
the evidence pack from cache rather than restoring a pickled frame — same data,
no serialisation surface.
"""
from __future__ import annotations

import operator
from typing import Annotated, Optional, TypedDict

from backend.agents.schemas import (
    FinalForecast,
    FundamentalReport,
    MacroReport,
    SentimentReport,
    TechnicalReport,
)


class AgentState(TypedDict, total=False):
    # --- inputs, fixed for the run ---
    ticker: str                  # always NSE/BSE-resolved before entering the graph
    as_of: str
    horizon_sessions: int
    nonce: str
    temperature: float
    run_key: str                 # looks the MarketContext up; see module docstring

    # --- configuration, so the ablations are data rather than code paths ---
    debate_enabled: bool
    debate_rounds: int
    dropped: list[str]           # specialists to skip, for leave-one-out

    # --- specialist outputs: one key each, never shared ---
    technical_report: Optional[TechnicalReport]
    fundamental_report: Optional[FundamentalReport]
    sentiment_report: Optional[SentimentReport]
    macro_report: Optional[MacroReport]

    # --- accumulated across nodes: reducers required ---
    debate: Annotated[list, operator.add]
    errors: Annotated[list, operator.add]

    # --- single-writer outputs ---
    transcript: str
    reconciliation: dict
    final: Optional[FinalForecast]
