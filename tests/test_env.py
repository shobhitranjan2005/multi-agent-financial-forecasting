"""Environment smoke test. Run as a module from the project root:

    python -m tests.test_env

Critical fix: imports `pandas_ta_classic`, NOT `pandas_ta`.
"""
import sys

print(f"Python: {sys.executable}")

CHECKS = [
    ("yfinance",            "yfinance"),
    ("pandas_ta_classic",   "pandas_ta_classic"),   # PyPI name imports as `pandas_ta_classic`
    ("google-genai",        "google.genai"),
    ("langgraph",           "langgraph"),
    ("pandas",              "pandas"),
    ("pydantic",            "pydantic"),
    ("tenacity",            "tenacity"),
    ("python-dotenv",       "dotenv"),
]

ok = True
for label, module in CHECKS:
    try:
        __import__(module)
        print(f"OK    {label}")
    except ImportError as e:
        print(f"FAIL  {label}: {e}")
        ok = False

# Project-local imports only succeed if run as `python -m tests.test_env` from project root.
try:
    from backend.config import Config
    print("OK    backend.config")
    if not Config.GEMINI_API_KEY or Config.GEMINI_API_KEY == "your_gemini_key_here":
        print("WARN  GEMINI_API_KEY not set in .env (only required for LLM calls)")
    else:
        print("OK    GEMINI_API_KEY present")
except Exception as e:
    print(f"FAIL  backend.config: {e}")
    ok = False

try:
    from backend.cache import get_cache
    c = get_cache()
    print("OK    backend.cache (SQLite ready)")
except Exception as e:
    print(f"FAIL  backend.cache: {e}")
    ok = False

print()
print("PHASE 1 EXIT GATE:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
