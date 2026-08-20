"""Environment smoke test. Works two ways:

    python -m tests.test_env      # human-readable report, exit code 0/1
    python -m pytest tests/       # collected as an ordinary test

The body lives in main() rather than at module scope for that second reason: a
module that calls sys.exit() while pytest is importing it aborts the entire
collection run with an INTERNALERROR, taking every other test with it.

Critical detail: imports `pandas_ta_classic`, NOT `pandas_ta`. The PyPI package
is `pandas-ta-classic` (the maintained fork) and it imports under the underscored
name. Getting this wrong makes every indicator silently return None — the
functions catch the ImportError and degrade, so the pipeline keeps running and
simply reports "unavailable" for RSI, MACD and every moving average.
"""
from __future__ import annotations

import sys
from pathlib import Path

CHECKS = [
    ("yfinance",          "yfinance"),
    ("pandas_ta_classic", "pandas_ta_classic"),   # NOT pandas_ta
    ("google-genai",      "google.genai"),
    ("langgraph",         "langgraph"),
    ("langgraph-sqlite",  "langgraph.checkpoint.sqlite"),
    ("pandas",            "pandas"),
    ("pydantic",          "pydantic"),
    ("tenacity",          "tenacity"),
    ("python-dotenv",     "dotenv"),
    ("httpx",             "httpx"),
]

# Files that must exist for each phase to be considered built.
PHASE_FILES = {
    "Phase 1  foundation": [
        "backend/config.py", "backend/cache.py", "backend/llm.py",
        "backend/context.py", "backend/baseline.py",
        "backend/agents/technical.py", "forecast.py",
    ],
    "Phase 2  data + harness": [
        "backend/tools/tickers.py", "backend/tools/calendar_nse.py",
        "backend/tools/market_data.py", "backend/tools/indicators.py",
        "backend/tools/fundamentals.py", "backend/tools/news_sentiment.py",
        "backend/tools/macro.py", "backend/eval/harness.py",
        "backend/eval/metrics.py", "backend/eval/outcomes.py",
        "backend/eval/testset.py", "backend/eval/naive.py",
        "backend/eval/recall_probe.py", "evaluate.py",
    ],
    "Phase 3  multi-agent": [
        "backend/agents/schemas.py", "backend/agents/base.py",
        "backend/agents/fundamental.py", "backend/agents/sentiment.py",
        "backend/agents/macro.py", "backend/agents/reconciliation.py",
        "backend/agents/debate.py", "backend/agents/risk_officer.py",
        "backend/graph/state.py", "backend/graph/pipeline.py",
    ],
}

ROOT = Path(__file__).resolve().parent.parent


def missing_imports() -> list[str]:
    bad = []
    for label, module in CHECKS:
        try:
            __import__(module)
        except ImportError:
            bad.append(label)
    return bad


def missing_files() -> dict[str, list[str]]:
    return {
        phase: [f for f in files if not (ROOT / f).exists()]
        for phase, files in PHASE_FILES.items()
    }


# --------------------------------------------------------------------------
# pytest entry points
# --------------------------------------------------------------------------
def test_required_packages_are_installed():
    bad = missing_imports()
    assert not bad, f"missing packages: {', '.join(bad)} — see requirements.txt"


def test_config_loads():
    from backend.config import Config

    assert Config.HORIZON_SESSIONS == 21
    assert Config.ALLOWED_SUFFIXES == (".NS", ".BO")
    assert Config.BENCHMARK == "^NSEI"


def test_cache_opens():
    from backend.cache import get_cache

    assert get_cache() is not None


def test_all_phase_files_are_present():
    gaps = {p: f for p, f in missing_files().items() if f}
    assert not gaps, f"missing files: {gaps}"


# --------------------------------------------------------------------------
# CLI entry point
# --------------------------------------------------------------------------
def main() -> int:
    print(f"Python: {sys.executable}")

    ok = True
    for label, module in CHECKS:
        try:
            __import__(module)
            print(f"OK    {label}")
        except ImportError as e:
            print(f"FAIL  {label}: {e}")
            ok = False

    try:
        from backend.config import Config
        print("OK    backend.config")
        if not Config.GEMINI_API_KEY or Config.GEMINI_API_KEY == "your_gemini_key_here":
            print("WARN  GEMINI_API_KEY not set in .env (only required for LLM calls)")
        else:
            print("OK    GEMINI_API_KEY present")
        if not Config.FRED_API_KEY or Config.FRED_API_KEY == "your_fred_key_here":
            print("WARN  FRED_API_KEY not set (macro falls back to the keyless CSV path)")
        else:
            print("OK    FRED_API_KEY present")
    except Exception as e:
        print(f"FAIL  backend.config: {e}")
        ok = False

    try:
        from backend.cache import get_cache
        get_cache()
        print("OK    backend.cache (SQLite ready)")
    except Exception as e:
        print(f"FAIL  backend.cache: {e}")
        ok = False

    print()
    print("ENVIRONMENT:", "PASS" if ok else "FAIL")
    print()

    gaps = missing_files()
    for phase, absent in gaps.items():
        if absent:
            print(f"{phase}: INCOMPLETE — missing {len(absent)} file(s)")
            for f in absent:
                print(f"    - {f}")
        else:
            print(f"{phase}: all files present")

    print("\nFile presence is not an exit gate. Confirm with:")
    print("  python -m pytest tests/ -q")
    print("  python -m forecast RELIANCE.NS --as-of 2025-01-15")
    print("  python -m forecast TCS.NS --as-of 2025-06-02 --system multiagent")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
