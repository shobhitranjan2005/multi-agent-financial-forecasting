"""LangGraph StateGraph Builder.

Implements the multi-agent financial forecasting graph:
1. Parallel Fan-Out: Technical + Fundamental + Sentiment + Macro specialists.
2. Reconciliation Gate: Anti-hallucination verifier.
3. Conditional Edge: Bypasses debate if `enable_debate=False` (--no-debate ablation switch).
4. Debate Engine: Bull vs Bear adversarial debate.
5. Chief Risk Officer Synthesiser: Emits FinalForecast.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Literal

from langgraph.graph import END, START, StateGraph

from backend.agents.debate import run_bull_bear_debate
from backend.agents.fundamental import analyze_fundamental
from backend.agents.macro import analyze_macro
from backend.agents.reconciliation import reconcile_specialist_reports
from backend.agents.risk_synthesiser import synthesize_final_forecast
from backend.agents.sentiment import analyze_sentiment
from backend.agents.technical import analyze_technical
from backend.graph.state import AgentState

logger = logging.getLogger(__name__)


# --- Node Handlers ---

def node_technical(state: AgentState) -> Dict[str, Any]:
    ticker, as_of, nonce = state["ticker"], state["as_of"], state.get("nonce", "")
    rep = analyze_technical(ticker, as_of, nonce=nonce)
    return {"technical_report": rep}


def node_fundamental(state: AgentState) -> Dict[str, Any]:
    ticker, as_of, nonce = state["ticker"], state["as_of"], state.get("nonce", "")
    rep = analyze_fundamental(ticker, as_of, nonce=nonce)
    return {"fundamental_report": rep}


def node_sentiment(state: AgentState) -> Dict[str, Any]:
    ticker, as_of, nonce = state["ticker"], state["as_of"], state.get("nonce", "")
    rep = analyze_sentiment(ticker, as_of, nonce=nonce)
    return {"sentiment_report": rep}


def node_macro(state: AgentState) -> Dict[str, Any]:
    ticker, as_of, nonce = state["ticker"], state["as_of"], state.get("nonce", "")
    rep = analyze_macro(ticker, as_of, nonce=nonce)
    return {"macro_report": rep}


def node_reconciliation(state: AgentState) -> Dict[str, Any]:
    passed, notes = reconcile_specialist_reports(
        state["ticker"],
        state["as_of"],
        state["technical_report"],
        state["fundamental_report"],
        state["sentiment_report"],
        state["macro_report"],
    )
    return {"reconciliation_passed": passed, "reconciliation_notes": notes}


def route_after_reconciliation(state: AgentState) -> Literal["debate", "synthesiser"]:
    """Conditional edge router: checks enable_debate ablation flag."""
    if state.get("enable_debate", True):
        return "debate"
    return "synthesiser"


def node_debate(state: AgentState) -> Dict[str, Any]:
    transcript = run_bull_bear_debate(
        state["ticker"],
        state["as_of"],
        state["technical_report"],
        state["fundamental_report"],
        state["sentiment_report"],
        state["macro_report"],
        rounds=2,
        nonce=state.get("nonce", ""),
    )
    return {"debate_transcript": transcript}


def node_synthesiser(state: AgentState) -> Dict[str, Any]:
    final_fc = synthesize_final_forecast(
        state["ticker"],
        state["as_of"],
        state["technical_report"],
        state["fundamental_report"],
        state["sentiment_report"],
        state["macro_report"],
        debate_transcript=state.get("debate_transcript"),
        nonce=state.get("nonce", ""),
    )
    return {"final_forecast": final_fc}


# --- Graph Assembly ---

def build_forecasting_graph():
    """Build and compile the multi-agent StateGraph."""
    workflow = StateGraph(AgentState)

    # 1. Add Nodes
    workflow.add_node("technical", node_technical)
    workflow.add_node("fundamental", node_fundamental)
    workflow.add_node("sentiment", node_sentiment)
    workflow.add_node("macro", node_macro)
    workflow.add_node("reconciliation", node_reconciliation)
    workflow.add_node("debate", node_debate)
    workflow.add_node("synthesiser", node_synthesiser)

    # 2. Parallel Fan-Out from START
    workflow.add_edge(START, "technical")
    workflow.add_edge(START, "fundamental")
    workflow.add_edge(START, "sentiment")
    workflow.add_edge(START, "macro")

    # 3. Fan-In to Reconciliation Gate
    workflow.add_edge("technical", "reconciliation")
    workflow.add_edge("fundamental", "reconciliation")
    workflow.add_edge("sentiment", "reconciliation")
    workflow.add_edge("macro", "reconciliation")

    # 4. Conditional Edge after Reconciliation
    workflow.add_conditional_edges(
        "reconciliation",
        route_after_reconciliation,
        {
            "debate": "debate",
            "synthesiser": "synthesiser",
        },
    )

    # 5. Debate to Synthesiser & Synthesiser to END
    workflow.add_edge("debate", "synthesiser")
    workflow.add_edge("synthesiser", END)

    return workflow.compile()
