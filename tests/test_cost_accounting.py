"""Unit tests for LLM cost accounting and cache hit preservation (Task 2).

Verifies that:
1. Fresh LLM calls record prompt_tokens, completion_tokens, latency_s.
2. Cache hits report the ORIGINAL values from the cached payload rather than zeroing them.
3. Cache hits set the `cached: true` flag on both Usage and LLMResult.
4. Aggregated Usage correctly tallies calls, cached_calls, tokens, and sets `cached`.
"""
import time
from unittest.mock import patch

import pytest

from backend import llm
from backend.cache import Cache


@pytest.fixture
def temp_cache(tmp_path):
    """Hermetic SQLite cache in a temporary directory."""
    db_file = tmp_path / "test_cache.db"
    c = Cache(db_file)
    with patch("backend.llm.get_cache", return_value=c):
        yield c


def test_cost_accounting_fresh_and_cache_hit(temp_cache):
    """Fresh call records tokens and latency; cache hit preserves original values with cached=True."""
    mock_response = ("Hello forecast", 350, 120)

    # 1. First call: miss
    with patch("backend.llm._call_gemini", return_value=mock_response) as mock_call:
        res1 = llm.generate("test prompt 1", model="test-model", nonce="test-nonce")
        assert mock_call.call_count == 1

    assert res1.from_cache is False
    assert res1.cached is False
    assert res1.usage.calls == 1
    assert res1.usage.cached_calls == 0
    assert res1.usage.cached is False
    assert res1.usage.prompt_tokens == 350
    assert res1.usage.completion_tokens == 120
    assert res1.usage.total_tokens == 470
    assert res1.usage.seconds >= 0.0

    # 2. Second call: hit (same prompt, model, and nonce)
    with patch("backend.llm._call_gemini", return_value=mock_response) as mock_call:
        res2 = llm.generate("test prompt 1", model="test-model", nonce="test-nonce")
        # Ensure _call_gemini was NOT called again
        assert mock_call.call_count == 0

    assert res2.from_cache is True
    assert res2.cached is True
    assert res2.usage.calls == 1
    assert res2.usage.cached_calls == 1
    assert res2.usage.cached is True
    # CRITICAL: original tokens and latency must NOT be zeroed out
    assert res2.usage.prompt_tokens == 350
    assert res2.usage.completion_tokens == 120
    assert res2.usage.total_tokens == 470
    assert res2.usage.seconds == pytest.approx(res1.usage.seconds, abs=0.01)

    # Check as_dict format
    d = res2.usage.as_dict()
    assert d["cached"] is True
    assert d["cached_calls"] == 1
    assert d["prompt_tokens"] == 350
    assert d["completion_tokens"] == 120
    assert d["total_tokens"] == 470


def test_usage_aggregation():
    """Aggregating Usage objects correctly sums tokens and updates cached status."""
    u1 = llm.Usage(calls=1, cached_calls=1, prompt_tokens=200, completion_tokens=50, seconds=1.2, cached=True)
    u2 = llm.Usage(calls=1, cached_calls=1, prompt_tokens=300, completion_tokens=70, seconds=1.5, cached=True)

    agg = llm.Usage()
    agg.add(u1)
    agg.add(u2)

    assert agg.calls == 2
    assert agg.cached_calls == 2
    assert agg.cached is True
    assert agg.prompt_tokens == 500
    assert agg.completion_tokens == 120
    assert agg.total_tokens == 620
    assert agg.seconds == pytest.approx(2.7)

    # Adding an uncached call flips agg.cached to False
    u3 = llm.Usage(calls=1, cached_calls=0, prompt_tokens=100, completion_tokens=20, seconds=0.8, cached=False)
    agg.add(u3)
    assert agg.calls == 3
    assert agg.cached_calls == 2
    assert agg.cached is False
    assert agg.total_tokens == 740
