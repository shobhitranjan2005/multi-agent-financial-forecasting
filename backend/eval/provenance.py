"""Run provenance: what exactly produced a result file.

A result that cannot be tied to a test-set hash, a code revision and a model ID
cannot be defended. Every harness run embeds this block in its JSON.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from importlib import metadata
from pathlib import Path

from backend.config import Config

_PKGS = ("pandas", "numpy", "pydantic", "yfinance", "langgraph", "google-genai")


class UnpinnedModelError(RuntimeError):
    pass


def require_pinned_model() -> None:
    """Refuse LLM runs against a moving alias (e.g. gemini-flash-latest).

    The LLM cache is keyed on the model string, so an alias that silently changes
    would mix responses from different model versions inside one experiment.
    Override only for demos: ALLOW_MODEL_ALIAS=1.
    """
    m = Config.GEMINI_MODEL
    if m.endswith("-latest") and os.getenv("ALLOW_MODEL_ALIAS") != "1":
        raise UnpinnedModelError(
            f"GEMINI_MODEL={m!r} is a moving alias. Set GEMINI_MODEL in .env to an "
            f"exact model ID from AI Studio before running experiments."
        )


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _git(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=Config.DATA_DIR.parent, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return None


def _ver(pkg: str) -> str | None:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None


def _news_provenance(testset_path: Path) -> dict:
    """Hash all cached news payloads for test cases to establish immutable data provenance."""
    import sqlite3
    from backend.eval import testset as ts_mod

    out: dict[str, object] = {
        "gdelt_allow_http": Config.GDELT_ALLOW_HTTP,
        "cache_key_prefix": "news_v3_30d",
        "case_hashes": {},
        "composite_sha256": None,
    }
    if not Config.CACHE_DB.exists():
        return out

    try:
        cases = ts_mod.cases(testset_path)
    except Exception:
        return out

    conn = sqlite3.connect(Config.CACHE_DB)
    hasher = hashlib.sha256()
    case_hashes: dict[str, str | None] = {}
    for c in sorted(cases, key=lambda x: (str(x.as_of), x.ticker)):
        cache_key = f"hist::gdelt::{c.ticker}::news_v3_30d::{c.as_of}"
        row = conn.execute("SELECT value FROM cache WHERE key = ?", (cache_key,)).fetchone()
        if row:
            raw_bytes = row[0].encode("utf-8")
            h = hashlib.sha256(raw_bytes).hexdigest()
            case_hashes[f"{c.ticker}::{c.as_of}"] = h
            hasher.update(f"{cache_key}:{h}\n".encode("utf-8"))
        else:
            case_hashes[f"{c.ticker}::{c.as_of}"] = None
            hasher.update(f"{cache_key}:none\n".encode("utf-8"))

    out["case_hashes"] = case_hashes
    out["composite_sha256"] = hasher.hexdigest()
    return out


def collect(testset_path: Path, system: str) -> dict:
    data = {
        "testset_sha256": _sha256(Path(testset_path)),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "model": None if system.startswith("naive") else Config.GEMINI_MODEL,
        "horizon_sessions": Config.HORIZON_SESSIONS,
        "packages": {p: _ver(p) for p in _PKGS},
    }
    if not system.startswith("naive"):
        data["news_provenance"] = _news_provenance(testset_path)
    return data
