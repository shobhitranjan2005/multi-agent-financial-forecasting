"""LangGraph orchestrator (Task 3.6) — the full multi-agent pipeline.

    START -> [technical | fundamental | sentiment | macro]   (parallel fan-out)
          -> reconcile                                        (fan-in)
          -> debate?  --yes--> debate -> risk_officer -> END
                      --no---------------> risk_officer -> END

The parallel fan-out is real concurrency, not a loop: the four specialists are
independent, and running them in sequence would triple the wall-clock cost of a
forecast for no analytical benefit. The stages after it are genuinely sequential —
the debate needs the reports, the Risk Officer needs the debate.

Why the debate is ONE node rather than four. Each turn depends on the previous
turn's text, so splitting it across graph nodes would add machinery without adding
parallelism, and would put four more serialisation boundaries between the turns.
The graph-level structure that matters for the research question is the
conditional edge: `--no-debate` routes straight to the synthesiser, and that edge
is what makes the ablation a configuration change rather than a second code path.

The evidence a dropped specialist would have contributed is never fetched, so the
leave-one-out ablation removes the analyst AND its data. Dropping the analyst
while leaving its numbers in the Risk Officer's evidence pack would measure
nothing.
"""
from __future__ import annotations

import time
import uuid
from datetime import date, datetime
from typing import Any, Optional

from langgraph.graph import END, START, StateGraph

from backend import llm
from backend.agents import (
    debate as debate_mod,
    fundamental as fundamental_agent,
    macro as macro_agent,
    reconciliation,
    risk_officer,
    sentiment as sentiment_agent,
    technical as technical_agent,
)
from backend.agents.schemas import ForecastRecord
from backend.config import Config
from backend.context import MarketContext, build as build_context
from backend.graph.state import AgentState

SPECIALISTS = ("technical", "fundamental", "sentiment", "macro")

# Contexts for in-flight runs, keyed by run_key. The state carries the key rather
# than the object: a MarketContext holds a DataFrame, and the checkpointer should
# not be asked to serialise one. See graph/state.py.
_CONTEXTS: dict[str, MarketContext] = {}


def _ctx(state: AgentState) -> MarketContext:
    """Fetch this run's evidence pack, rebuilding it from cache if resumed.

    A resumed run finds nothing in the registry (the process died) and rebuilds
    from the permanent SQLite cache. Same evidence, no network, no pickled frames.
    """
    key = state["run_key"]
    ctx = _CONTEXTS.get(key)
    if ctx is None:
        dropped = set(state.get("dropped") or ())
        ctx = build_context(
            state["ticker"], state["as_of"],
            horizon_sessions=state["horizon_sessions"],
            with_fundamentals="fundamental" not in dropped,
            with_news="sentiment" not in dropped,
            with_macro="macro" not in dropped,
        )
        _CONTEXTS[key] = ctx
    return ctx


# ---------------------------------------------------------------------------
# specialist nodes
# ---------------------------------------------------------------------------
def _specialist_node(name: str, module, state_key: str):
    """Build one specialist node. All four are the same shape by construction.

    A specialist that fails returns None into its own key and appends an error;
    it never raises. One broken report should degrade a forecast, not lose it —
    and the parse failure is already counted as a reported metric in llm.py.
    """
    def node(state: AgentState) -> dict:
        if name in (state.get("dropped") or ()):
            return {"errors": [f"{name}: dropped for ablation"]}
        try:
            rep, err = module.analyse(
                _ctx(state),
                temperature=state.get("temperature", 0.0),
                nonce=state.get("nonce", ""),
            )
        except Exception as exc:
            return {state_key: None, "errors": [f"{name}: {type(exc).__name__}: {exc}"]}
        return {state_key: rep, "errors": [f"{name}: {err}"] if err else []}

    node.__name__ = f"{name}_node"
    return node


technical_node = _specialist_node("technical", technical_agent, "technical_report")
fundamental_node = _specialist_node("fundamental", fundamental_agent, "fundamental_report")
sentiment_node = _specialist_node("sentiment", sentiment_agent, "sentiment_report")
macro_node = _specialist_node("macro", macro_agent, "macro_report")


# ---------------------------------------------------------------------------
# reconciliation, debate, synthesis
# ---------------------------------------------------------------------------
def reconcile_node(state: AgentState) -> dict:
    """Re-verify every specialist number against source data before it propagates."""
    ctx = _ctx(state)
    report = reconciliation.reconcile(
        ctx,
        technical=state.get("technical_report"),
        fundamental=state.get("fundamental_report"),
        sentiment=state.get("sentiment_report"),
        macro=state.get("macro_report"),
    )
    return {
        "reconciliation": report.as_dict(),
        "errors": [f"reconciliation: {w}" for w in report.warnings()],
    }


def debate_node(state: AgentState) -> dict:
    ctx = _ctx(state)
    turns, transcript, errors = debate_mod.run_debate(
        ctx,
        technical=state.get("technical_report"),
        fundamental=state.get("fundamental_report"),
        sentiment=state.get("sentiment_report"),
        macro=state.get("macro_report"),
        rounds=state.get("debate_rounds", 2),
        temperature=state.get("temperature", 0.0),
        nonce=state.get("nonce", ""),
    )
    return {"debate": turns, "transcript": transcript, "errors": errors}


def risk_node(state: AgentState) -> dict:
    ctx = _ctx(state)
    final, err = risk_officer.synthesise(
        ctx,
        technical=state.get("technical_report"),
        fundamental=state.get("fundamental_report"),
        sentiment=state.get("sentiment_report"),
        macro=state.get("macro_report"),
        transcript=state.get("transcript", ""),
        temperature=state.get("temperature", 0.0),
        nonce=state.get("nonce", ""),
    )

    # Second reconciliation pass: the first stopped a bad number entering the
    # debate, this one stops a bad number leaving the system.
    errors = [f"risk_officer: {err}"] if err else []
    merged = dict(state.get("reconciliation") or {})
    if final is not None:
        final_check = reconciliation.reconcile(ctx, forecast=final)
        merged["forecast_checks"] = final_check.as_dict()
        errors += [f"reconciliation(final): {w}" for w in final_check.warnings()]

    return {"final": final, "reconciliation": merged, "errors": errors}


def _route_after_reconcile(state: AgentState) -> str:
    """The ablation switch, expressed as a graph edge."""
    return "debate" if state.get("debate_enabled", True) else "risk_officer"


# ---------------------------------------------------------------------------
# graph construction
# ---------------------------------------------------------------------------
def build_graph(checkpointer=None):
    """Compile the agent graph. Cheap; safe to call per run."""
    g = StateGraph(AgentState)

    g.add_node("technical", technical_node)
    g.add_node("fundamental", fundamental_node)
    g.add_node("sentiment", sentiment_node)
    g.add_node("macro", macro_node)
    g.add_node("reconcile", reconcile_node)
    g.add_node("debate", debate_node)
    g.add_node("risk_officer", risk_node)

    # Fan out to all four specialists, fan back in to reconciliation.
    for name in SPECIALISTS:
        g.add_edge(START, name)
        g.add_edge(name, "reconcile")

    g.add_conditional_edges(
        "reconcile", _route_after_reconcile,
        {"debate": "debate", "risk_officer": "risk_officer"},
    )
    g.add_edge("debate", "risk_officer")
    g.add_edge("risk_officer", END)

    return g.compile(checkpointer=checkpointer) if checkpointer else g.compile()


def _sqlite_checkpointer():
    """Persistent checkpointer so a crashed run resumes rather than restarts."""
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    Config.ensure_dirs()
    conn = sqlite3.connect(Config.DATA_DIR / "graph_checkpoints.db",
                           check_same_thread=False)
    return SqliteSaver(conn)


def system_name(debate: bool, dropped: tuple[str, ...]) -> str:
    """The label that lands in the results file. Every ablation is distinguishable."""
    if dropped:
        return "multiagent-no-" + "-".join(sorted(dropped))
    return "multiagent" if debate else "multiagent-nodebate"


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def run(
    ticker: str,
    as_of: str | date | datetime,
    *,
    horizon_sessions: int = Config.HORIZON_SESSIONS,
    debate: bool = True,
    debate_rounds: int = 2,
    drop: tuple[str, ...] | list[str] = (),
    nonce: str = "",
    temperature: float = 0.0,
    ctx: Optional[MarketContext] = None,
    checkpoint: bool = False,
    return_state: bool = False,
) -> ForecastRecord | tuple[ForecastRecord, dict]:
    """Run the multi-agent pipeline over one (ticker, as_of).

    Returns the same ForecastRecord the baseline and the naive rules return, so
    harness.py scores all of them without knowing which produced it.
    """
    started = time.time()
    llm.reset_session_usage()

    dropped = tuple(sorted(set(drop)))
    unknown = [d for d in dropped if d not in SPECIALISTS]
    if unknown:
        raise ValueError(f"unknown specialist(s) to drop: {unknown}. Known: {SPECIALISTS}")

    # Build the evidence pack ONCE, before the graph starts. Doing it here rather
    # than inside the nodes means the four parallel specialists never race to
    # fetch the same data, and every network call in the run is already done by
    # the time any concurrency begins.
    if ctx is None:
        ctx = build_context(
            ticker, as_of,
            horizon_sessions=horizon_sessions,
            with_fundamentals="fundamental" not in dropped,
            with_news="sentiment" not in dropped,
            with_macro="macro" not in dropped,
        )

    run_key = f"{ctx.ticker}:{ctx.as_of}:{nonce or 'base'}:{uuid.uuid4().hex[:8]}"
    _CONTEXTS[run_key] = ctx

    initial: AgentState = {
        "ticker": ctx.ticker,
        "as_of": str(ctx.as_of),
        "horizon_sessions": ctx.horizon_sessions,
        "nonce": nonce,
        "temperature": temperature,
        "run_key": run_key,
        "debate_enabled": debate,
        "debate_rounds": debate_rounds,
        "dropped": list(dropped),
        "technical_report": None,
        "fundamental_report": None,
        "sentiment_report": None,
        "macro_report": None,
        "debate": [],
        "errors": [],
        "transcript": "",
        "reconciliation": {},
        "final": None,
    }

    try:
        checkpointer = _sqlite_checkpointer() if checkpoint else None
        graph = build_graph(checkpointer)
        config: dict[str, Any] = (
            {"configurable": {"thread_id": run_key}} if checkpointer else {}
        )
        final_state = graph.invoke(initial, config=config)
    finally:
        _CONTEXTS.pop(run_key, None)

    record = _assemble_record(ctx, final_state, started,
                              debate=debate, dropped=dropped, nonce=nonce)
    return (record, final_state) if return_state else record


def _assemble_record(ctx, final_state, started, *, debate, dropped, nonce):
    """Turn a finished graph state into the ForecastRecord the harness scores."""
    usage = llm.session_usage()
    notes = list(ctx.notes) + list(final_state.get("errors") or [])

    recon = final_state.get("reconciliation") or {}
    if recon:
        notes.append(
            f"reconciliation: {recon.get('n_checked', 0)} claims checked, "
            f"{recon.get('n_failed', 0)} failed, "
            f"{recon.get('n_magnitude_errors', 0)} magnitude errors"
        )

    return ForecastRecord(
        ticker=ctx.ticker,
        as_of=str(ctx.as_of),
        system=system_name(debate, dropped),
        last_close_inr=ctx.last_close,
        forecast=final_state.get("final"),
        horizon_sessions=ctx.horizon_sessions,
        target_date=str(ctx.target_date) if ctx.target_date else None,
        llm_calls=usage.calls,
        total_tokens=usage.total_tokens,
        seconds=round(time.time() - started, 2),
        parse_failures=usage.parse_failures,
        nonce=nonce,
        notes=notes,
        transcript=final_state.get("transcript")
    )


# ---------------------------------------------------------------------------
# streaming
# ---------------------------------------------------------------------------
# Human-readable labels for the live agent log. The dashboard and the WebSocket
# both render these, so they live here rather than being duplicated in each UI.
NODE_LABELS = {
    "technical": "Technical analyst",
    "fundamental": "Fundamental analyst",
    "sentiment": "Sentiment analyst",
    "macro": "Macro analyst",
    "reconcile": "Reconciliation gate",
    "debate": "Bull vs Bear debate",
    "risk_officer": "Chief Risk Officer",
}


def stream(
    ticker: str,
    as_of: str | date | datetime,
    *,
    horizon_sessions: int = Config.HORIZON_SESSIONS,
    debate: bool = True,
    debate_rounds: int = 2,
    drop: tuple[str, ...] | list[str] = (),
    nonce: str = "",
    temperature: float = 0.0,
    ctx: Optional[MarketContext] = None,
):
    """Run the pipeline, yielding a progress event as each stage completes.

    Yields dicts shaped {"event": ..., ...}. The final event carries the finished
    record, so a consumer that only wants the answer can ignore everything else.

    This exists because a full multi-agent forecast takes 30-90 seconds. A UI that
    shows nothing for that long looks broken, and a plain POST would time out on
    many proxies anyway. Streaming the stages is also the honest demo: the point
    of the project is the pipeline, so the pipeline should be visible.

    Progress is derived from LangGraph's own update stream rather than from
    callbacks planted in the nodes, so the log can never drift out of step with
    what the graph actually did.
    """
    started = time.time()
    llm.reset_session_usage()

    dropped = tuple(sorted(set(drop)))
    unknown = [d for d in dropped if d not in SPECIALISTS]
    if unknown:
        raise ValueError(f"unknown specialist(s) to drop: {unknown}. Known: {SPECIALISTS}")

    yield {"event": "start", "ticker": ticker, "as_of": str(as_of)}

    if ctx is None:
        yield {"event": "stage", "stage": "evidence", "status": "running",
               "label": "Building the evidence pack"}
        ctx = build_context(
            ticker, as_of,
            horizon_sessions=horizon_sessions,
            with_fundamentals="fundamental" not in dropped,
            with_news="sentiment" not in dropped,
            with_macro="macro" not in dropped,
        )

    yield {
        "event": "context",
        "ticker": ctx.ticker,
        "as_of": str(ctx.as_of),
        "last_close": ctx.last_close,
        "sessions": len(ctx.prices),
        "source": ctx.source,
        "target_date": str(ctx.target_date) if ctx.target_date else None,
        "notes": list(ctx.notes),
    }

    run_key = f"{ctx.ticker}:{ctx.as_of}:{nonce or 'base'}:{uuid.uuid4().hex[:8]}"
    _CONTEXTS[run_key] = ctx

    initial: AgentState = {
        "ticker": ctx.ticker,
        "as_of": str(ctx.as_of),
        "horizon_sessions": ctx.horizon_sessions,
        "nonce": nonce,
        "temperature": temperature,
        "run_key": run_key,
        "debate_enabled": debate,
        "debate_rounds": debate_rounds,
        "dropped": list(dropped),
        "technical_report": None,
        "fundamental_report": None,
        "sentiment_report": None,
        "macro_report": None,
        "debate": [],
        "errors": [],
        "transcript": "",
        "reconciliation": {},
        "final": None,
    }

    merged: dict = dict(initial)
    try:
        graph = build_graph()
        for update in graph.stream(initial, stream_mode="updates"):
            for node_name, payload in (update or {}).items():
                if not isinstance(payload, dict):
                    continue
                # Merge by hand: stream_mode="updates" yields deltas, and we need
                # the accumulated state to assemble the record at the end.
                for key, value in payload.items():
                    if key in ("debate", "errors"):
                        merged[key] = list(merged.get(key) or []) + list(value or [])
                    else:
                        merged[key] = value
                yield {
                    "event": "stage",
                    "stage": node_name,
                    "status": "done",
                    "label": NODE_LABELS.get(node_name, node_name),
                    "detail": _stage_detail(node_name, payload),
                    "elapsed": round(time.time() - started, 1),
                }
    finally:
        _CONTEXTS.pop(run_key, None)

    record = _assemble_record(ctx, merged, started,
                              debate=debate, dropped=dropped, nonce=nonce)
    yield {
        "event": "done",
        "record": record.model_dump(mode="json"),
        "reports": {
            name: (merged.get(f"{name}_report").model_dump(mode="json")
                   if merged.get(f"{name}_report") is not None else None)
            for name in SPECIALISTS
        },
        "debate": [t.model_dump(mode="json") for t in (merged.get("debate") or [])],
        "transcript": merged.get("transcript", ""),
        "reconciliation": merged.get("reconciliation") or {},
    }


def _stage_detail(node_name: str, payload: dict) -> str:
    """One line describing what a finished stage produced, for the live log."""
    if node_name in SPECIALISTS:
        rep = payload.get(f"{node_name}_report")
        if rep is None:
            return "no report"
        for attr, label in (("score", "score"), ("valuation_score", "valuation"),
                            ("polarity", "polarity"), ("regime", "regime")):
            if hasattr(rep, attr):
                return f"{label} {getattr(rep, attr)}"
        return "report produced"
    if node_name == "reconcile":
        r = payload.get("reconciliation") or {}
        return (f"{r.get('n_checked', 0)} claims checked, "
                f"{r.get('n_failed', 0)} failed")
    if node_name == "debate":
        return f"{len(payload.get('debate') or [])} turns"
    if node_name == "risk_officer":
        final = payload.get("final")
        return f"{final.signal}, {final.confidence_pct:.0f}% confidence" if final else "failed"
    return ""
