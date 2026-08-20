"""Multi-agent pipeline tests, run against a stubbed LLM.

The point of stubbing Gemini is not speed, it is determinism. These tests assert
things about the GRAPH — that four specialists run, that the debate produces four
turns, that --no-debate removes exactly one stage, that a dropped specialist takes
its evidence with it — and none of those claims should depend on what a model
happened to say. The stub returns schema-valid canned reports, so a failure here
is always a wiring failure.

It also means the whole Phase 3 architecture is verifiable with no API key.
"""
from __future__ import annotations

import pytest

from backend import llm
from backend.agents.schemas import (
    DebateArgument,
    FinalForecast,
    FundamentalReport,
    MacroReport,
    SentimentReport,
    TechnicalReport,
)

CANNED = {
    TechnicalReport: dict(
        score=3.0, trend="Uptrend", support_inr=1350.0, resistance_inr=1450.0,
        rsi_reading="RSI 55.0 - Neutral", macd_reading="MACD - Bullish",
        sma_reading="Price above SMA-50", reasoning="Stubbed technical view.",
        citations=["RSI(14)=55.0"],
    ),
    FundamentalReport: dict(
        valuation_score=1.0, intrinsic_value_inr=None, health="Stable",
        pe_ratio=None, revenue_growth_pct=None, debt_to_equity=None,
        unavailable_fields=["pe_trailing"], reasoning="No admissible metrics.",
        citations=[],
    ),
    SentimentReport: dict(
        polarity=0.2, relevance=0.7, confidence=0.5, catalysts=["results"],
        article_links=["https://example.in/a"], headline_count=2,
        reasoning="Stubbed sentiment.",
    ),
    MacroReport: dict(
        regime="Neutral", usdinr_reading="stable", crude_reading="soft",
        rates_reading="repo 6.0%", sector_reading="in line",
        key_indicators=["repo 6.0%"], reasoning="Stubbed macro.",
    ),
    DebateArgument: dict(
        position="bull", round_number=1, points=["stubbed point"],
        target_inr=1450.0, confidence=0.6, rebuttal=None,
    ),
    FinalForecast: dict(
        signal="Buy", target_low_inr=1400.0, target_high_inr=1460.0,
        confidence_pct=61.0, expected_direction="up",
        risk_report="Stubbed risk report.", key_risks=["stub risk"],
        reasoning="Stubbed synthesis.", citations=["last close"],
    ),
}


@pytest.fixture
def stub_llm(monkeypatch):
    """Replace Gemini with a deterministic schema-valid stub, and count the calls."""
    calls: list[str] = []

    def fake_generate(prompt, *, model=None, system=None, temperature=0.0,
                      schema=None, nonce="", use_cache=True):
        calls.append(schema.__name__ if schema else "text")
        usage = llm.Usage(calls=1, prompt_tokens=500, completion_tokens=200, seconds=0.01)
        result = llm.LLMResult(text="{}", model="stub", usage=usage)
        if schema is not None:
            result.parsed = schema(**CANNED[schema])
        llm._session_usage.add(usage)
        return result

    monkeypatch.setattr(llm, "generate", fake_generate)
    monkeypatch.setattr(llm, "is_configured", lambda: True)
    return calls


# ---------------------------------------------------------------------------
# graph construction
# ---------------------------------------------------------------------------
def test_graph_compiles_with_expected_nodes():
    from backend.graph.pipeline import build_graph

    graph = build_graph()
    nodes = set(graph.get_graph().nodes)
    for expected in ("technical", "fundamental", "sentiment", "macro",
                     "reconcile", "debate", "risk_officer"):
        assert expected in nodes, f"node '{expected}' missing from the compiled graph"


def test_specialists_have_distinct_state_keys():
    """Shared keys under a parallel fan-out raise INVALID_CONCURRENT_GRAPH_UPDATE."""
    from backend.graph.state import AgentState

    keys = AgentState.__annotations__
    for name in ("technical_report", "fundamental_report",
                 "sentiment_report", "macro_report"):
        assert name in keys, f"{name} must be its own state key, never shared"


def test_accumulated_lists_carry_reducers():
    """Without operator.add the last writer wins and earlier turns vanish silently."""
    import operator
    import typing

    from backend.graph.state import AgentState

    # include_extras=True is required: state.py uses `from __future__ import
    # annotations`, so the raw __annotations__ are strings. LangGraph resolves
    # them the same way, which is why the reducers work at runtime.
    hints = typing.get_type_hints(AgentState, include_extras=True)
    for name in ("debate", "errors"):
        assert typing.get_origin(hints[name]) is not None, f"{name} lost its annotation"
        metadata = getattr(hints[name], "__metadata__", ())
        assert metadata, (
            f"{name} is written by more than one node and needs a reducer; "
            f"without it the last writer wins and earlier entries vanish silently"
        )
        assert metadata[0] is operator.add


# ---------------------------------------------------------------------------
# end-to-end, stubbed
# ---------------------------------------------------------------------------
def test_full_pipeline_produces_a_forecast(ctx, stub_llm):
    from backend.graph.pipeline import run

    rec, state = run(ctx.ticker, ctx.as_of, ctx=ctx, return_state=True)

    assert rec.system == "multiagent"
    assert rec.forecast is not None
    assert rec.forecast.signal in ("Buy", "Hold", "Sell")
    # 4 specialists + 4 debate turns + 1 risk officer
    assert len(stub_llm) == 9, f"expected 9 LLM calls, got {len(stub_llm)}: {stub_llm}"
    assert rec.llm_calls == 9
    assert rec.total_tokens > 0

    for key in ("technical_report", "fundamental_report",
                "sentiment_report", "macro_report"):
        assert state[key] is not None, f"{key} was not produced"


def test_debate_runs_two_rounds_of_two_turns(ctx, stub_llm):
    from backend.graph.pipeline import run

    _, state = run(ctx.ticker, ctx.as_of, ctx=ctx, return_state=True)

    turns = state["debate"]
    assert len(turns) == 4
    assert [(t.position, t.round_number) for t in turns] == [
        ("bull", 1), ("bear", 1), ("bull", 2), ("bear", 2)
    ]
    assert state["transcript"], "the transcript feeds the Risk Officer and the dashboard"


def test_no_debate_ablation_removes_exactly_the_debate(ctx, stub_llm):
    """The central ablation: same everything, minus four LLM calls."""
    from backend.graph.pipeline import run

    rec, state = run(ctx.ticker, ctx.as_of, ctx=ctx, debate=False, return_state=True)

    assert rec.system == "multiagent-nodebate"
    assert state["debate"] == []
    assert state["transcript"] == ""
    assert rec.forecast is not None, "the no-debate path must still produce a forecast"
    # 4 specialists + 1 risk officer, and nothing else.
    assert len(stub_llm) == 5


def test_debate_costs_measurably_more_than_no_debate(ctx, stub_llm):
    """The cost half of the research question has to be measurable, not asserted."""
    from backend.graph.pipeline import run

    full = run(ctx.ticker, ctx.as_of, ctx=ctx, debate=True)
    lean = run(ctx.ticker, ctx.as_of, ctx=ctx, debate=False)

    assert full.llm_calls > lean.llm_calls
    assert full.total_tokens > lean.total_tokens


@pytest.mark.parametrize("dropped", ["technical", "fundamental", "sentiment", "macro"])
def test_leave_one_out_drops_the_specialist_and_its_evidence(ctx, stub_llm, dropped):
    from backend.graph.pipeline import run

    rec, state = run(ctx.ticker, ctx.as_of, ctx=ctx, drop=(dropped,), return_state=True)

    assert rec.system == f"multiagent-no-{dropped}"
    assert state[f"{dropped}_report"] is None
    assert any(dropped in n for n in rec.notes)
    # 3 specialists + 4 debate + 1 risk officer
    assert len(stub_llm) == 8
    assert rec.forecast is not None, "a leave-one-out run must still be scoreable"


def test_unknown_specialist_is_rejected(ctx):
    from backend.graph.pipeline import run

    with pytest.raises(ValueError, match="unknown specialist"):
        run(ctx.ticker, ctx.as_of, ctx=ctx, drop=("astrology",))


# ---------------------------------------------------------------------------
# the record contract the harness depends on
# ---------------------------------------------------------------------------
def test_record_matches_the_shape_the_harness_scores(ctx, stub_llm):
    """Baseline, naive and multi-agent must be scoreable through one code path."""
    from backend.eval.harness import score_record
    from backend.graph.pipeline import run

    rec = run(ctx.ticker, ctx.as_of, ctx=ctx)
    scored = score_record(rec)

    assert scored.system == "multiagent"
    assert scored.predicted_direction in ("up", "down")
    assert scored.confidence_pct is not None
    assert scored.llm_calls == 9


def test_reconciliation_runs_inside_the_pipeline(ctx, stub_llm):
    from backend.graph.pipeline import run

    _, state = run(ctx.ticker, ctx.as_of, ctx=ctx, return_state=True)

    recon = state["reconciliation"]
    assert recon["n_checked"] > 0, "the gate must actually check claims in a real run"
    assert "forecast_checks" in recon, "the final forecast must be re-verified too"
