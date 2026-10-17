"""Unit tests for paced resumable prefetch worker (hermetic)."""
import json
import sqlite3
from unittest.mock import MagicMock, patch
import pytest

from backend.eval import prefetch


def test_is_cached_returns_data_or_none(tmp_path):
    db_file = tmp_path / "cache.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE cache (key TEXT PRIMARY KEY, value TEXT, created_at REAL, ttl REAL)")
    conn.execute(
        "INSERT INTO cache VALUES (?, ?, ?, ?)",
        ("hist::gdelt::RELIANCE.NS::news_v5_30d::2025-06-02", json.dumps({"headlines": [{"title": "RIL"}]}), 0, 0),
    )
    conn.commit()

    assert prefetch._is_cached(conn, "RELIANCE.NS", "2025-06-02", 30) is not None
    assert prefetch._is_cached(conn, "INFY.NS", "2025-06-02", 30) is None
    conn.close()


def test_prefetch_skips_cached_cases_and_calls_loader_for_uncached(tmp_path):
    ts_file = tmp_path / "testset.json"
    ts_file.write_text(json.dumps({
        "cases": [
            {"ticker": "RELIANCE.NS", "as_of": "2025-06-02", "horizon_sessions": 21},
            {"ticker": "INFY.NS", "as_of": "2025-06-02", "horizon_sessions": 21},
        ]
    }), encoding="utf-8")

    db_file = tmp_path / "cache.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE cache (key TEXT PRIMARY KEY, value TEXT, created_at REAL, ttl REAL)")
    # RELIANCE is already cached with 6 headlines
    conn.execute(
        "INSERT INTO cache VALUES (?, ?, ?, ?)",
        ("hist::gdelt::RELIANCE.NS::news_v5_30d::2025-06-02", json.dumps({
            "status": "ok",
            "headlines": [{"title": f"Head {i}"} for i in range(6)]
        }), 0, 0),
    )
    conn.commit()
    conn.close()

    mock_news = {
        "status": "ok",
        "headlines": [{"title": "Infosys AI service"}] * 3,
    }

    with patch("backend.eval.prefetch.Config.CACHE_DB", db_file), \
         patch("backend.eval.prefetch.PROGRESS_FILE", tmp_path / "prefetch_progress.json"), \
         patch("backend.eval.prefetch._pace"), \
         patch("backend.tools.news_sentiment.get_news", return_value=mock_news) as mock_get_news:

        res = prefetch.run_prefetch(ts_file, lookback_days=30)
        # get_news should only be called once (for INFY, since RELIANCE was cached)
        assert mock_get_news.call_count == 1
        assert res["status_counts"]["ok"] == 2
        assert res["distribution"]["ge_5"] == 1        # RELIANCE had 6
        assert res["distribution"]["low_1_to_4"] == 1  # INFY had 3
        assert res["distribution"]["zero"] == 0


def test_prefetch_retries_on_429(tmp_path):
    ts_file = tmp_path / "testset.json"
    ts_file.write_text(json.dumps({
        "cases": [{"ticker": "INFY.NS", "as_of": "2025-06-02", "horizon_sessions": 21}]
    }), encoding="utf-8")

    db_file = tmp_path / "cache.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE cache (key TEXT PRIMARY KEY, value TEXT, created_at REAL, ttl REAL)")
    conn.commit()
    conn.close()

    calls = 0

    def mock_get_news(ticker, as_of, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("HTTP 429: Please limit requests to one every 5 seconds")
        return {"status": "ok", "headlines": [{"title": "Infosys Q4"}]}

    with patch("backend.eval.prefetch.Config.CACHE_DB", db_file), \
         patch("backend.eval.prefetch.PROGRESS_FILE", tmp_path / "prefetch_progress.json"), \
         patch("backend.eval.prefetch._pace"), \
         patch("time.sleep") as mock_sleep, \
         patch("backend.tools.news_sentiment.get_news", side_effect=mock_get_news):

        res = prefetch.run_prefetch(ts_file, lookback_days=30, max_retries_429=2)
        assert calls == 2
        assert res["status_counts"]["ok"] == 1
        assert res["distribution"]["low_1_to_4"] == 1
        # Cooldown was triggered
        assert mock_sleep.called
