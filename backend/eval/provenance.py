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


def collect(testset_path: Path, system: str) -> dict:
    return {
        "testset_sha256": _sha256(Path(testset_path)),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "model": None if system.startswith("naive") else Config.GEMINI_MODEL,
        "horizon_sessions": Config.HORIZON_SESSIONS,
        "packages": {p: _ver(p) for p in _PKGS},
    }
