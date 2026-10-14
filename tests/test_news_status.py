"""Unit tests for news_status semantics and provenance hashing (hermetic)."""
import json
import sqlite3
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from backend.context import build
from backend.eval import provenance


def _fake_prices():
    idx = pd.date_range("2025-01-01", periods=20, freq="B")
    return pd.DataFrame({"close": [100.0] * 20, "open": [100.0] * 20, "high": [105.0] * 20, "low": [95.0] * 20, "volume": [1000] * 20}, index=idx)


@patch("backend.tools.market_data.get_price_history")
@patch("backend.tools.news_sentiment.get_news")
def test_news_status_ok(mock_news, mock_prices):
    mock_prices.return_value = _fake_prices()
    mock_news.return_value = {
        "status": "ok",
        "headlines": [{"title": "Reliance Q4 results positive", "url": "https://example.com/1"}],
    }

    ctx = build("RELIANCE.NS", "2025-06-02", with_fundamentals=False, with_news=True, with_macro=False)
    assert ctx.news_status == "ok"
    assert len(ctx.news["headlines"]) == 1


@patch("backend.tools.market_data.get_price_history")
@patch("backend.tools.news_sentiment.get_news")
def test_news_status_empty(mock_news, mock_prices):
    mock_prices.return_value = _fake_prices()
    mock_news.return_value = {
        "status": "empty",
        "headlines": [],
    }

    ctx = build("RELIANCE.NS", "2025-06-02", with_fundamentals=False, with_news=True, with_macro=False)
    assert ctx.news_status == "empty"
    assert len(ctx.news["headlines"]) == 0


@patch("backend.tools.market_data.get_price_history")
@patch("backend.tools.news_sentiment.get_news")
def test_news_status_error_non_strict(mock_news, mock_prices):
    mock_prices.return_value = _fake_prices()
    mock_news.side_effect = RuntimeError("GDELT connection reset")

    ctx = build("RELIANCE.NS", "2025-06-02", with_fundamentals=False, with_news=True, with_macro=False, strict=False)
    assert ctx.news_status == "error"
    assert any("news unavailable" in n for n in ctx.notes)


@patch("backend.tools.market_data.get_price_history")
@patch("backend.tools.news_sentiment.get_news")
def test_news_status_error_strict_aborts(mock_news, mock_prices):
    mock_prices.return_value = _fake_prices()
    mock_news.side_effect = RuntimeError("GDELT connection reset")

    with pytest.raises(RuntimeError) as exc_info:
        build("RELIANCE.NS", "2025-06-02", with_fundamentals=False, with_news=True, with_macro=False, strict=True)
    assert "Strict evidence error (news)" in str(exc_info.value)


def test_news_provenance_hashing(tmp_path):
    # Setup a mock testset
    ts_file = tmp_path / "testset.json"
    ts_file.write_text(json.dumps({
        "cases": [
            {"ticker": "RELIANCE.NS", "as_of": "2025-06-02", "horizon_sessions": 21},
            {"ticker": "INFY.NS", "as_of": "2025-06-02", "horizon_sessions": 21},
        ]
    }), encoding="utf-8")

    # Setup a mock cache.db
    db_file = tmp_path / "cache.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE cache (key TEXT PRIMARY KEY, value TEXT, created_at REAL, ttl REAL)")
    conn.execute(
        "INSERT INTO cache VALUES (?, ?, ?, ?)",
        ("hist::gdelt::RELIANCE.NS::news_v3_30d::2025-06-02", json.dumps({"headlines": [{"title": "RIL"}]}), 0, 0),
    )
    conn.commit()
    conn.close()

    with patch("backend.eval.provenance.Config.CACHE_DB", db_file):
        prov = provenance._news_provenance(ts_file)
        assert prov["cache_key_prefix"] == "news_v3_30d"
        assert "RELIANCE.NS::2025-06-02" in prov["case_hashes"]
        assert prov["case_hashes"]["RELIANCE.NS::2025-06-02"] is not None
        assert prov["case_hashes"]["INFY.NS::2025-06-02"] is None
        assert prov["composite_sha256"] is not None
