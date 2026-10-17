from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from backend.agents.schemas import FinalForecast, ForecastRecord
from backend.eval import harness, testset as testset_mod
from backend.eval.runner import (
    FakeClock,
    PROGRESS_FILE,
    PT_TZ,
    RunnerStopCondition,
    is_daily_quota_error,
    is_fatal_4xx_error,
    is_system_completed,
    load_progress,
    next_midnight_pacific,
    run_staged_plan,
    save_progress,
    seconds_until_midnight_pacific,
)
from backend.llm import LLMError


def test_fake_clock_and_midnight_pacific():
    # 2026-10-16 14:00:00 Pacific
    dt = datetime(2026, 10, 16, 14, 0, 0, tzinfo=PT_TZ)
    clock = FakeClock(dt)

    assert clock.now(PT_TZ) == dt
    next_mid = next_midnight_pacific(clock)
    assert next_mid == datetime(2026, 10, 17, 0, 0, 0, tzinfo=PT_TZ)

    sec_rem = seconds_until_midnight_pacific(clock)
    assert sec_rem == 10 * 3600  # 10 hours

    # Sleep 1800 seconds (30m)
    clock.sleep(1800)
    assert clock.sleep_calls == [1800]
    assert clock.now(PT_TZ) == datetime(2026, 10, 16, 14, 30, 0, tzinfo=PT_TZ)
    assert seconds_until_midnight_pacific(clock) == 9.5 * 3600


def test_is_daily_quota_error():
    assert is_daily_quota_error(LLMError("Daily Gemini quota exhausted. Progress is cached..."))
    assert is_daily_quota_error(RuntimeError("ResourceExhausted: RequestsPerDay quota exceeded"))
    assert is_daily_quota_error(RuntimeError("Quota exceeded: requests per day limit reached"))
    assert is_daily_quota_error(Exception("429 RESOURCE_EXHAUSTED daily quota exceeded"))

    # Minute rate limit or other error should NOT match
    assert not is_daily_quota_error(RuntimeError("429 Rate limit exceeded. Retry in 15s"))
    assert not is_daily_quota_error(ValueError("Invalid ticker"))
    assert not is_daily_quota_error(RuntimeError("Data not available on Bhavcopy"))


def test_is_fatal_4xx_error():
    assert is_fatal_4xx_error(RuntimeError("400 Bad Request: Invalid argument"))
    assert is_fatal_4xx_error(RuntimeError("403 Forbidden: API key revoked"))
    assert is_fatal_4xx_error(RuntimeError("404 Not Found"))
    assert not is_fatal_4xx_error(RuntimeError("429 Too Many Requests"))
    assert not is_fatal_4xx_error(LLMError("Daily Gemini quota exhausted"))


def test_load_and_save_progress(tmp_path):
    pfile = tmp_path / "runner_progress.json"
    init_data = load_progress(pfile)
    assert init_data["status"] == "NOT_STARTED"

    init_data["status"] = "RUNNING"
    init_data["daily_calls"]["2026-10-16"] = 12
    save_progress(init_data, pfile)

    loaded = load_progress(pfile)
    assert loaded["status"] == "RUNNING"
    assert loaded["daily_calls"]["2026-10-16"] == 12


def test_is_system_completed(tmp_path):
    prog = {
        "completed_systems": [
            {"system": "baseline", "nonce": "", "n_scoreable": 4}
        ]
    }
    assert is_system_completed("baseline", "", 4, prog, tmp_path)
    assert not is_system_completed("baseline", "", 5, prog, tmp_path)
    assert not is_system_completed("baseline", "r2", 4, prog, tmp_path)


def _make_dummy_testset(tmp_path: Path) -> Path:
    p = tmp_path / "testset.json"
    p.write_text(json.dumps({
        "status": "FROZEN",
        "n_cases": 2,
        "cases": [
            {
                "ticker": "INFY",
                "as_of": "2025-06-02",
                "horizon_sessions": 21,
            },
            {
                "ticker": "TCS",
                "as_of": "2025-06-02",
                "horizon_sessions": 21,
            },
        ]
    }), encoding="utf-8")
    return p


def test_staged_runner_with_fake_clock_and_quota_pause(tmp_path, monkeypatch):
    from backend.config import Config
    monkeypatch.setattr(Config, "GEMINI_MODEL", "gemini-3.1-flash-lite")
    ts_file = _make_dummy_testset(tmp_path)
    res_dir = tmp_path / "results"
    prog_file = res_dir / "runner_progress.json"

    clock = FakeClock(datetime(2026, 10, 16, 23, 0, 0, tzinfo=PT_TZ))

    # Mock forecaster: on case 1, raises Daily Gemini quota exhausted on 1st attempt, then succeeds on 2nd attempt
    call_counts = {"count": 0}

    def fake_forecaster(ticker, as_of, **kw):
        call_counts["count"] += 1
        if call_counts["count"] == 1:
            raise LLMError("Daily Gemini quota exhausted. Progress is cached; rerun tomorrow.")
        return ForecastRecord(
            ticker=ticker,
            as_of=str(as_of),
            system="test-sys",
            last_close_inr=1000.0,
            forecast=FinalForecast(
                signal="Buy",
                expected_direction="up",
                target_low_inr=1050.0,
                target_high_inr=1100.0,
                confidence_pct=75,
                risk_report="Low",
                key_risks=["volatility"],
                reasoning="Trend is up",
                citations=["rsi=55"],
            ),
            horizon_sessions=21,
            target_date="2025-07-01",
            llm_calls=1,
            total_tokens=100,
            seconds=1.0,
            parse_failures=0,
            nonce="",
            notes=[],
        )

    with patch("backend.eval.harness.get_forecaster", return_value=fake_forecaster), \
         patch("backend.eval.provenance.is_git_dirty", return_value=False), \
         patch("backend.eval.runner.STAGE_ROUND_1", [("test-sys", "")]), \
         patch("backend.eval.runner.STAGE_ROUND_2", []), \
         patch("backend.eval.runner.STAGE_COST", []):

        prog = run_staged_plan(
            stage_name="1",
            testset_path=ts_file,
            clock=clock,
            auto_push=False,
            progress_file=prog_file,
            results_dir=res_dir,
        )

        assert prog["status"] == "COMPLETED"
        assert len(prog["pause_history"]) == 1
        pause_entry = prog["pause_history"][0]
        assert pause_entry["system"] == "test-sys"
        assert pause_entry["case"] == "INFY 2025-06-02"
        assert "Daily Gemini quota exhausted" in pause_entry["reason"]

        # FakeClock was advanced by 1800 seconds (30m)
        assert clock.sleep_calls == [1800]
        # Current time moved from 23:00 to 23:30 PT
        assert clock.now(PT_TZ) == datetime(2026, 10, 16, 23, 30, 0, tzinfo=PT_TZ)

        # Completed systems recorded
        assert len(prog["completed_systems"]) == 1
        comp = prog["completed_systems"][0]
        assert comp["system"] == "test-sys"
        assert comp["n_scoreable"] == 2
        assert comp["parse_failures"] == 0


def test_staged_runner_stop_condition_on_high_parse_failure(tmp_path, monkeypatch):
    from backend.config import Config
    monkeypatch.setattr(Config, "GEMINI_MODEL", "gemini-3.1-flash-lite")
    ts_file = _make_dummy_testset(tmp_path)
    res_dir = tmp_path / "results"
    prog_file = res_dir / "runner_progress.json"

    clock = FakeClock()

    def failing_forecaster(ticker, as_of, **kw):
        return ForecastRecord(
            ticker=ticker,
            as_of=str(as_of),
            system="bad-sys",
            last_close_inr=1000.0,
            forecast=None,  # parse failed
            horizon_sessions=21,
            target_date="2025-07-01",
            llm_calls=1,
            total_tokens=100,
            seconds=1.0,
            parse_failures=1,
            nonce="",
            notes=[],
        )

    with patch("backend.eval.harness.get_forecaster", return_value=failing_forecaster), \
         patch("backend.eval.provenance.is_git_dirty", return_value=False), \
         patch("backend.eval.runner.STAGE_ROUND_1", [("bad-sys", "")]), \
         patch("backend.eval.runner.STAGE_ROUND_2", []), \
         patch("backend.eval.runner.STAGE_COST", []):

        with pytest.raises(RunnerStopCondition) as exc_info:
            run_staged_plan(
                stage_name="1",
                testset_path=ts_file,
                clock=clock,
                auto_push=False,
                progress_file=prog_file,
                results_dir=res_dir,
            )

        assert "Parse failure rate 100.0%" in str(exc_info.value)
        prog = load_progress(prog_file)
        assert prog["status"] == "STOPPED"
        assert "Parse failure rate" in prog["stop_reason"]


def test_staged_runner_stop_condition_on_strict_abort(tmp_path, monkeypatch):
    from backend.config import Config
    monkeypatch.setattr(Config, "GEMINI_MODEL", "gemini-3.1-flash-lite")
    ts_file = _make_dummy_testset(tmp_path)
    res_dir = tmp_path / "results"
    prog_file = res_dir / "runner_progress.json"

    clock = FakeClock()

    def crashing_forecaster(ticker, as_of, **kw):
        raise ValueError("Missing critical price data")

    with patch("backend.eval.harness.get_forecaster", return_value=crashing_forecaster), \
         patch("backend.eval.provenance.is_git_dirty", return_value=False), \
         patch("backend.eval.runner.STAGE_ROUND_1", [("crash-sys", "")]), \
         patch("backend.eval.runner.STAGE_ROUND_2", []), \
         patch("backend.eval.runner.STAGE_COST", []):

        with pytest.raises(RunnerStopCondition) as exc_info:
            run_staged_plan(
                stage_name="1",
                testset_path=ts_file,
                clock=clock,
                auto_push=False,
                progress_file=prog_file,
                results_dir=res_dir,
            )

        assert "Strict-mode abort" in str(exc_info.value)
        prog = load_progress(prog_file)
        assert prog["status"] == "STOPPED"
        assert "Strict-mode abort" in prog["stop_reason"]
