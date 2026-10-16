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
    if not path.exists():
        return None
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()


def _git(*args: str) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", *args], cwd=Config.DATA_DIR.parent, text=True, stderr=subprocess.DEVNULL
        )
        return out.rstrip("\r\n")
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
        "cache_key_prefix": "news_v5_30d",
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
        cache_key = f"hist::gdelt::{c.ticker}::news_v5_30d::{c.as_of}"
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


def is_git_dirty() -> bool:
    """True if working tree has relevant uncommitted changes.

    Ignores EVERYTHING under results/ (tracked or untracked) and
    any data/*.db* (cache or checkpoints), while modified source/config
    files elsewhere must still count.
    """
    raw = _git("status", "--porcelain")
    if not raw:
        return False
    for line in raw.splitlines():
        line_clean = line.rstrip("\r\n")
        if not line_clean.strip():
            continue

        if line_clean.startswith("?? ") or line_clean.startswith("R  ") or line_clean.startswith("D  ") or line_clean.startswith("A  "):
            path = line_clean[3:].strip()
        elif line_clean.startswith("M  "):
            path = line_clean[3:].strip()
        elif line_clean.startswith("M "):
            path = line_clean[2:].strip()
        elif len(line_clean) >= 3 and line_clean[2] == " ":
            path = line_clean[3:].strip()
        else:
            parts = line_clean.split(None, 1)
            path = parts[1] if len(parts) > 1 else ""

        if " -> " in path:
            # Handle renames: orig -> dest
            parts = [p.strip().strip('"').replace("\\", "/") for p in path.split(" -> ")]
            if all(
                p.startswith("results/")
                or (p.startswith("data/") and (".db" in p or "cache" in p.lower()))
                or p.startswith("scratch/")
                for p in parts
            ):
                continue
            return True

        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        norm_path = path.replace("\\", "/")

        # Ignore EVERYTHING under results/ (tracked modifications, untracked, etc.)
        if norm_path.startswith("results/"):
            continue

        # Ignore any SQLite database or WAL/SHM file under data/
        if norm_path.startswith("data/") and (
            norm_path.endswith(".db")
            or norm_path.endswith(".db-wal")
            or norm_path.endswith(".db-shm")
            or norm_path.endswith(".db-journal")
            or "cache" in norm_path.lower()
        ):
            continue

        # Ignore scratch/
        if norm_path.startswith("scratch/"):
            continue

        return True
    return False


def collect(testset_path: Path, system: str) -> dict:
    data = {
        "testset_sha256": _sha256(Path(testset_path)),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": is_git_dirty(),
        "model": None if system.startswith("naive") else Config.GEMINI_MODEL,
        "horizon_sessions": Config.HORIZON_SESSIONS,
        "packages": {p: _ver(p) for p in _PKGS},
    }
    if not system.startswith("naive"):
        data["news_provenance"] = _news_provenance(testset_path)
    return data
