"""Two-class SQLite cache. Sits in front of every external call.

Classes
-------
HistoricalCache    — keyed by (source, ticker, field, as_of). Permanent TTL.
                     For point-in-time data: the past never changes.
LiveCache          — keyed by (source, ticker, field). 15-minute TTL.
                     For current quotes / live demo data only.
LLMCache           — keyed by sha256(prompt + model [+ nonce]). Permanent TTL.
                     Phase 4 variance runs MUST pass a nonce or they will hit
                     the cache and report zero variance (artifact, not signal).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from backend.config import Config


import threading

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,        -- JSON-serialised
    created_at REAL NOT NULL,
    ttl        REAL NOT NULL         -- seconds; 0 = permanent
);

CREATE INDEX IF NOT EXISTS idx_cache_created ON cache(created_at);
"""


class Cache:
    """Single SQLite store with TTL semantics. Thread-safe with RLock."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        Config.ensure_dirs()
        self.db_path = db_path or Config.CACHE_DB
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ---- low-level helpers ----
    def _get(self, key: str) -> Any | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value, created_at, ttl FROM cache WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            value_json, created_at, ttl = row
            if ttl > 0 and (time.time() - created_at) > ttl:
                return None
            return json.loads(value_json)

    def _set(self, key: str, value: Any, ttl: float) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache (key, value, created_at, ttl) VALUES (?, ?, ?, ?)",
                (key, json.dumps(value, default=str), time.time(), ttl),
            )
            self._conn.commit()


    def get_or_set(self, key: str, ttl: float, loader) -> Any:
        """Return cached value if present and fresh; otherwise call loader(), cache, return."""
        hit = self._get(key)
        if hit is not None:
            return hit
        value = loader()
        self._set(key, value, ttl)
        return value

    def has(self, key: str) -> bool:
        return self._get(key) is not None

    def clear(self) -> None:
        self._conn.execute("DELETE FROM cache")
        self._conn.commit()

    # ---- typed accessors (the API the rest of the codebase should use) ----
    def historical(self, source: str, ticker: str, field: str, as_of: str, loader) -> Any:
        """Permanent cache for point-in-time data. Key includes as_of."""
        key = f"hist::{source}::{ticker}::{field}::{as_of}"
        return self.get_or_set(key, Config.HISTORICAL_TTL_SECONDS, loader)

    def live(self, source: str, ticker: str, field: str, loader) -> Any:
        """15-minute TTL cache for live quotes (demo only)."""
        key = f"live::{source}::{ticker}::{field}"
        return self.get_or_set(key, Config.LIVE_TTL_SECONDS, loader)

    def llm(self, prompt: str, model: str, loader, nonce: str = "") -> Any:
        """Cache LLM responses by prompt+model+nonce hash.

        Pass a unique nonce for Phase 4 variance runs or the cache will mask
        real sampling variance as zero.
        """
        h = hashlib.sha256(f"{prompt}|{model}|{nonce}".encode("utf-8")).hexdigest()
        key = f"llm::{model}::{h}"
        return self.get_or_set(key, Config.HISTORICAL_TTL_SECONDS, loader)


# Module-level singleton — cheap, thread-safe enough for the Phase 1 walking skeleton.
_cache: Cache | None = None


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        _cache = Cache()
    return _cache
