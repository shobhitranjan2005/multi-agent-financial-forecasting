"""Pacing logic with a fake clock. No network, no API key."""
import pytest
from backend import llm


def _reset(monkeypatch, now=100.0):
    monkeypatch.setattr(llm, "_next_slot", 0.0)
    monkeypatch.setattr(llm.time, "monotonic", lambda: now)
    sleeps = []
    monkeypatch.setattr(llm.time, "sleep", sleeps.append)
    return sleeps


def test_calls_are_spaced_by_the_configured_rate(monkeypatch):
    monkeypatch.setenv("LLM_MAX_RPM", "60")          # 1 call / second
    sleeps = _reset(monkeypatch)
    for _ in range(3):
        llm._throttle()
    assert sleeps == [1.0, 2.0]                      # first call immediate


def test_server_retry_delay_pauses_every_thread(monkeypatch):
    monkeypatch.setenv("LLM_MAX_RPM", "60")
    sleeps = _reset(monkeypatch)
    llm._penalise(RuntimeError("429 ... Please retry in 12.35s."))
    llm._throttle()
    assert sleeps == [pytest.approx(13.35)]          # 12.35s + 1s margin
