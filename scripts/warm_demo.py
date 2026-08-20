"""Pre-warm and verify the demo cache (Task 5.4).

    python -m scripts.warm_demo                 # warm, then verify
    python -m scripts.warm_demo --verify-only   # verify without spending quota

Run this the day BEFORE the defence, not an hour before.

Why it exists: a live API call during a viva is a single point of failure you do
not control. Quota resets, rate limits, a flaky network in the exam hall — any of
them turns a working project into a broken demo in front of the people grading
it. The LLM cache is permanent and keyed by (prompt, model, nonce), so a run that
has been executed once replays with zero network calls forever.

The verification is the real deliverable. Warming a cache and *assuming* it worked
is how people discover on stage that the second run still hits the network,
because one parameter differed. So the check asserts the strong condition: every
LLM call in the replay was served from cache.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from backend import llm
from backend.config import enable_utf8_console

# The exact runs the defence walks through. Keep this list identical to the demo
# script in the slide notes -- a warmed run that nobody demonstrates is useless,
# and a demonstrated run that nobody warmed is worse.
DEMO_RUNS = [
    {"ticker": "RELIANCE.NS", "as_of": "2025-06-02", "debate": True},
    {"ticker": "TCS.NS", "as_of": "2025-06-02", "debate": True},
    {"ticker": "TCS.NS", "as_of": "2025-06-02", "debate": False},   # the ablation
]


def run_once(spec: dict) -> tuple[bool, str]:
    """Execute one demo run. Returns (produced_a_forecast, summary_line)."""
    from backend.graph.pipeline import run as run_pipeline

    record = run_pipeline(
        spec["ticker"], spec["as_of"], debate=spec["debate"], nonce="",
    )
    usage = llm.session_usage()
    label = f"{spec['ticker']} {spec['as_of']} " \
            f"{'with debate' if spec['debate'] else 'no debate'}"
    signal = record.forecast.signal if record.forecast else "FAILED"
    return (
        record.forecast is not None,
        f"{label:<40} {signal:<7} "
        f"{usage.calls} calls ({usage.cached_calls} cached), "
        f"{usage.total_tokens:,} tokens, {record.seconds}s",
    )


def verify_cached(spec: dict) -> tuple[bool, str]:
    """Replay a run and assert every LLM call was served from cache."""
    from backend.graph.pipeline import run as run_pipeline

    llm.reset_session_usage()
    record = run_pipeline(
        spec["ticker"], spec["as_of"], debate=spec["debate"], nonce="",
    )
    usage = llm.session_usage()
    label = f"{spec['ticker']} {spec['as_of']} " \
            f"{'with debate' if spec['debate'] else 'no debate'}"

    fully_cached = usage.calls > 0 and usage.cached_calls == usage.calls
    ok = fully_cached and record.forecast is not None
    detail = (f"{usage.cached_calls}/{usage.calls} calls from cache, "
              f"{usage.total_tokens:,} fresh tokens")
    if not fully_cached:
        detail += "  <-- NOT fully cached; this run would hit the network live"
    return ok, f"{label:<40} {detail}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="warm_demo",
        description="Pre-warm and verify the cached demo runs.",
    )
    ap.add_argument("--verify-only", action="store_true",
                    help="check the cache without making any fresh calls")
    args = ap.parse_args(argv)
    enable_utf8_console()

    print()
    print("=" * 78)
    print(f"  Demo cache check — {date.today():%d %B %Y}")
    print("=" * 78)

    if not llm.is_configured():
        print("\n  GEMINI_API_KEY is not set, so no LLM run can be warmed or replayed.")
        print("  Add the key to .env and run this again — well before the defence.\n")
        return 3

    if not args.verify_only:
        print("\n  Warming (this spends quota — the whole point is to spend it now)\n")
        for spec in DEMO_RUNS:
            llm.reset_session_usage()
            try:
                ok, line = run_once(spec)
            except Exception as exc:
                print(f"    FAILED  {spec['ticker']} {spec['as_of']}: "
                      f"{type(exc).__name__}: {exc}")
                continue
            print(f"    {'ok    ' if ok else 'FAILED'}  {line}")

    print("\n  Verifying that a replay makes zero fresh calls\n")
    all_ok = True
    for spec in DEMO_RUNS:
        try:
            ok, line = verify_cached(spec)
        except Exception as exc:
            print(f"    FAILED  {spec['ticker']}: {type(exc).__name__}: {exc}")
            all_ok = False
            continue
        all_ok &= ok
        print(f"    {'CACHED' if ok else 'LIVE  '}  {line}")

    print()
    print("=" * 78)
    if all_ok:
        print("  READY — every demo run replays from cache with no network calls.")
        print("  The defence cannot be broken by quota, rate limits or the venue wifi.")
    else:
        print("  NOT READY — at least one run would call the API live.")
        print("  Re-run without --verify-only, then check again.")
    print("=" * 78)
    print()
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
