"""FastAPI backend tests.

Only hermetic checks live here: the boundary, input validation, degradation
without a key, and the security posture. The price and evidence endpoints are
exercised through the data-layer tests instead, because asserting on them here
would make the suite depend on a warm cache or a live network.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import ALLOWED_ORIGINS, app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------
def test_health_reports_capability_without_leaking_the_key(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()

    assert body["status"] == "ok"
    assert body["currency"] == "INR"
    assert body["benchmark"] == "^NSEI"
    assert body["horizon_sessions"] == 21
    assert isinstance(body["llm_configured"], bool)

    # The key itself must never cross this boundary in any form.
    text = r.text.lower()
    for forbidden in ("aiza", "api_key", "apikey", "secret", "token"):
        assert forbidden not in text


# ---------------------------------------------------------------------------
# the India boundary, enforced at the API exactly as at the CLI
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ticker", ["AAPL", "BP.L", "7203.T", "SAP.DE"])
def test_non_indian_tickers_are_rejected_with_400(client, ticker):
    r = client.get(f"/api/price/{ticker}", params={"as_of": "2025-06-02"})
    assert r.status_code == 400
    assert "Indian equities only" in r.json()["detail"]


def test_forecast_rejects_non_indian_ticker_before_spending_anything(client):
    """The boundary must be checked before the key check, not after."""
    r = client.post("/api/forecast/AAPL", json={"as_of": "2025-06-02"})
    assert r.status_code == 400
    assert "Indian equities only" in r.json()["detail"]


# ---------------------------------------------------------------------------
# input validation
# ---------------------------------------------------------------------------
def test_malformed_date_is_rejected(client):
    r = client.get("/api/price/RELIANCE.NS", params={"as_of": "not-a-date"})
    assert r.status_code == 400
    assert "YYYY-MM-DD" in r.json()["detail"]


def test_missing_as_of_is_rejected(client):
    r = client.get("/api/price/RELIANCE.NS")
    assert r.status_code == 422


def test_session_count_is_bounded(client):
    """An unbounded row count is a cheap way to make a server allocate forever."""
    r = client.get("/api/price/RELIANCE.NS",
                   params={"as_of": "2025-06-02", "sessions": 999999})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# degradation without a key
# ---------------------------------------------------------------------------
def test_forecast_degrades_with_503_when_no_key(client):
    from backend import llm

    if llm.is_configured():
        pytest.skip("a key is configured; this asserts the no-key path")

    r = client.post("/api/forecast/RELIANCE.NS", json={"as_of": "2025-06-02"})
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "GEMINI_API_KEY" in detail
    # The message must point at what still works, not just refuse.
    assert "/api/evidence" in detail


def test_health_lists_naive_systems_when_no_key(client):
    from backend import llm

    if llm.is_configured():
        pytest.skip("a key is configured")

    systems = client.get("/api/health").json()["available_systems"]
    assert "naive-momentum" in systems


# ---------------------------------------------------------------------------
# security posture
# ---------------------------------------------------------------------------
def test_cors_is_an_explicit_allowlist_never_a_wildcard():
    """allow_origins=['*'] with credentials enabled is an open door."""
    assert "*" not in ALLOWED_ORIGINS
    assert all(o.startswith("http://localhost") or o.startswith("http://127.0.0.1")
               for o in ALLOWED_ORIGINS)


def test_rate_limiter_trips(client):
    """The forecast limit is deliberately tight — those calls cost real quota."""
    from backend.api.main import FORECAST_LIMIT_REQUESTS, _hits
    from unittest.mock import patch

    _hits.clear()
    with patch("backend.llm.is_configured", return_value=False):
        codes = [
            client.post("/api/forecast/RELIANCE.NS", json={"as_of": "2025-06-02"}).status_code
            for _ in range(FORECAST_LIMIT_REQUESTS + 2)
        ]
    assert 429 in codes, f"rate limiter never tripped: {codes}"
    _hits.clear()


def test_websocket_rejects_a_request_with_no_as_of(client):
    with client.websocket_connect("/api/stream/RELIANCE.NS") as ws:
        ws.send_json({})
        event = ws.receive_json()
    assert event["event"] == "error"
    assert "as_of" in event["detail"]


def test_websocket_enforces_the_india_boundary(client):
    with client.websocket_connect("/api/stream/AAPL") as ws:
        ws.send_json({"as_of": "2025-06-02"})
        event = ws.receive_json()
    assert event["event"] == "error"
    assert "Indian equities only" in event["detail"]


# ---------------------------------------------------------------------------
# results listing
# ---------------------------------------------------------------------------
def test_results_endpoint_lists_committed_files(client):
    r = client.get("/api/results")
    assert r.status_code == 200
    results = r.json()["results"]
    assert isinstance(results, list)
    if results:
        assert {"name", "kind", "modified"} <= set(results[0])
