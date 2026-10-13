"""Hermetic unit tests for dual contamination probe (recall_probe.py).

Zero network, zero external API keys. Tests the price recall and event recall logic
across all four outcomes:
1. Event recalled (model knows actual RBI repo rate within tolerance)
2. Event not recalled (model claims knowledge but gives wrong repo rate)
3. Event declined (model sets knows_answer=False or repo_rate=None)
4. Date past verified calendar (ground truth is unverified beyond 2025-08-31)
"""
from datetime import date
from unittest.mock import patch

import pytest

from backend.eval import recall_probe
from backend.eval.recall_probe import EventRecall, NiftyRecall, ProbeResult
from backend.llm import LLMResult, Usage


def _mock_llm_result(parsed_obj) -> LLMResult:
    return LLMResult(
        text="{}",
        model="fake-model",
        usage=Usage(),
        parsed=parsed_obj,
    )


@pytest.fixture(autouse=True)
def mock_nifty_price():
    """Mock ground truth NIFTY close so tests never call yfinance."""
    with patch("backend.eval.recall_probe._actual_nifty_close", return_value=24500.0):
        yield


def test_event_probe_recalled():
    """Case 1: Model knows the exact RBI repo rate on a verified date -> event_recalled is True."""
    target_date = date(2025, 4, 15)  # Actual repo rate is 6.00% (effective 2025-04-09, verified)

    def fake_generate(prompt, schema=None, **kwargs):
        if schema is NiftyRecall:
            return _mock_llm_result(NiftyRecall(knows_answer=False, nifty_close=None, stated_confidence=0.0, source_of_knowledge="declined"))
        elif schema is EventRecall:
            return _mock_llm_result(EventRecall(knows_answer=True, repo_rate=6.00, stated_confidence=0.9, source_of_knowledge="recall"))
        return _mock_llm_result(None)

    with patch("backend.llm.generate", side_effect=fake_generate):
        res = recall_probe.probe_date(target_date)

    assert res.actual_event_repo_rate == 6.00
    assert res.claimed_event_repo_rate == 6.00
    assert res.event_claims_knowledge is True
    assert res.event_recalled is True
    assert "EVENT RECALLED" in res.event_note


def test_event_probe_not_recalled():
    """Case 2: Model claims knowledge but gives an incorrect repo rate -> event_recalled is False."""
    target_date = date(2025, 4, 15)  # Actual repo rate is 6.00%

    def fake_generate(prompt, schema=None, **kwargs):
        if schema is NiftyRecall:
            return _mock_llm_result(NiftyRecall(knows_answer=False, nifty_close=None, stated_confidence=0.0, source_of_knowledge="declined"))
        elif schema is EventRecall:
            # Model claims 6.50% when actual is 6.00%
            return _mock_llm_result(EventRecall(knows_answer=True, repo_rate=6.50, stated_confidence=0.8, source_of_knowledge="guess"))
        return _mock_llm_result(None)

    with patch("backend.llm.generate", side_effect=fake_generate):
        res = recall_probe.probe_date(target_date)

    assert res.actual_event_repo_rate == 6.00
    assert res.claimed_event_repo_rate == 6.50
    assert res.event_claims_knowledge is True
    assert res.event_recalled is False
    assert "not genuine recall" in res.event_note


def test_event_probe_model_declined():
    """Case 3: Model honestly declines to state an answer -> event_recalled is False."""
    target_date = date(2025, 4, 15)

    def fake_generate(prompt, schema=None, **kwargs):
        if schema is NiftyRecall:
            return _mock_llm_result(NiftyRecall(knows_answer=False, nifty_close=None, stated_confidence=0.0, source_of_knowledge="declined"))
        elif schema is EventRecall:
            return _mock_llm_result(EventRecall(knows_answer=False, repo_rate=None, stated_confidence=0.0, source_of_knowledge="declined"))
        return _mock_llm_result(None)

    with patch("backend.llm.generate", side_effect=fake_generate):
        res = recall_probe.probe_date(target_date)

    assert res.actual_event_repo_rate == 6.00
    assert res.claimed_event_repo_rate is None
    assert res.event_claims_knowledge is False
    assert res.event_recalled is False
    assert "model declined repo rate" in res.event_note


def test_event_probe_date_past_verified_calendar():
    """Case 4: Date is past 2025-08-31 (unverified RBI calendar) -> ground truth is None and marked unverified."""
    target_date = date(2025, 10, 15)  # past 2025-08-31

    def fake_generate(prompt, schema=None, **kwargs):
        if schema is NiftyRecall:
            return _mock_llm_result(NiftyRecall(knows_answer=False, nifty_close=None, stated_confidence=0.0, source_of_knowledge="declined"))
        elif schema is EventRecall:
            return _mock_llm_result(EventRecall(knows_answer=True, repo_rate=5.50, stated_confidence=0.9, source_of_knowledge="recall"))
        return _mock_llm_result(None)

    with patch("backend.llm.generate", side_effect=fake_generate):
        res = recall_probe.probe_date(target_date)

    assert res.actual_event_repo_rate is None
    assert res.event_recalled is False
    assert "past verified RBI decision calendar" in res.event_note
