"""Tests for evaluation harness strict mode and error propagation (Task: Step 4 strict mode)."""
from unittest.mock import patch
import pytest

from backend.eval import harness, naive


def test_type_error_inside_forecaster_aborts_in_strict_mode(tmp_path):
    """A real TypeError inside a forecaster must NOT be swallowed or retried without strict."""
    # Create a minimal testset file
    testset_file = tmp_path / "testset.json"
    testset_file.write_text(
        '{"cases": [{"ticker": "RELIANCE.NS", "as_of": "2025-06-02", "horizon_sessions": 21}]}',
        encoding="utf-8",
    )

    def buggy_forecaster(ticker, as_of, **kwargs):
        raise TypeError("simulated inner calculation error in forecaster")

    with patch.dict(naive.REGISTRY, {"test-buggy": buggy_forecaster}):
        # In strict mode, must abort immediately by raising RuntimeError
        with pytest.raises(RuntimeError) as exc_info:
            harness.run("test-buggy", testset_path=testset_file, strict=True, progress=False)

        assert "ABORTED RUN (strict mode)" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, TypeError)
        assert "simulated inner calculation error" in str(exc_info.value.__cause__)

        # In non-strict mode, does not raise; records in failures list
        res = harness.run("test-buggy", testset_path=testset_file, strict=False, progress=False)
        assert len(res["failures"]) == 1
        assert "TypeError" in res["failures"][0]["error"]
