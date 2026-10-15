"""Paced, resumable prefetch worker for point-in-time financial news (news_v5).

Enforces:
  1. Strict spacing: >= 18.0 seconds between consecutive remote calls.
  2. Cooldown on HTTP 429: sleeps 90.0 seconds and retries.
  3. Resumable: skips any (ticker, as_of) already cached under news_v5_30d.
  4. Fault-tolerant: errors are never cached; failures are recorded in progress log.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
os.environ["GDELT_ALLOW_HTTP"] = "1"

from backend.config import Config, enable_utf8_console
from backend.tools import news_sentiment
from backend.eval import testset as ts_mod

DEFAULT_TESTSET = Config.DATA_DIR / "testset_draft_v3.json"
PROGRESS_FILE = Config.DATA_DIR.parent / "results" / "prefetch_progress.json"

_MIN_CALL_INTERVAL = 18.0  # seconds between remote GDELT queries
_COOLDOWN_429 = 90.0       # seconds to sleep when 429 rate limit is encountered
_last_remote_call_time: float = 0.0


def _pace() -> None:
    """Ensure at least _MIN_CALL_INTERVAL seconds elapsed since last remote call."""
    global _last_remote_call_time
    now = time.monotonic()
    elapsed = now - _last_remote_call_time
    if elapsed < _MIN_CALL_INTERVAL:
        time.sleep(_MIN_CALL_INTERVAL - elapsed)
    _last_remote_call_time = time.monotonic()


def _is_cached(conn: sqlite3.Connection, ticker: str, as_of: str, lookback: int = 30) -> Optional[dict]:
    key = f"hist::gdelt::{ticker}::news_v5_{lookback}d::{as_of}"
    row = conn.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
    if row:
        try:
            return json.loads(row[0])
        except Exception:
            return None
    return None


def run_prefetch(
    testset_path: Path | str = DEFAULT_TESTSET,
    *,
    lookback_days: int = 30,
    max_records: int = 250,
    max_retries_429: int = 3,
    progress_cb: Optional[Any] = None,
) -> dict:
    enable_utf8_console()
    testset_path = Path(testset_path)
    cases = ts_mod.cases(testset_path)
    total = len(cases)

    status_counts = {"ok": 0, "empty": 0, "error": 0}
    dist_counts = {"zero": 0, "low_1_to_4": 0, "ge_5": 0}
    results_log = []

    conn = sqlite3.connect(Config.CACHE_DB)
    print(f"\n=== STARTING RESUMABLE NEWS PREFETCH ({total} cases) ===", flush=True)
    print(f"Testset: {testset_path}", flush=True)
    print(f"Pacing: >= {_MIN_CALL_INTERVAL}s spacing | 429 Cooldown: {_COOLDOWN_429}s", flush=True)

    for i, c in enumerate(cases, 1):
        ticker = c.ticker
        as_of = str(c.as_of)

        # Check existing cache
        cached = _is_cached(conn, ticker, as_of, lookback_days)
        if cached is not None:
            headlines = cached.get("headlines") or []
            h_count = len(headlines)
            st = cached.get("status") or ("ok" if h_count > 0 else "empty")
            status_counts[st] = status_counts.get(st, 0) + 1

            if h_count == 0:
                dist_counts["zero"] += 1
            elif h_count < 5:
                dist_counts["low_1_to_4"] += 1
            else:
                dist_counts["ge_5"] += 1

            msg = f"[{i}/{total}] CACHED: {ticker} {as_of} -> status={st}, headlines={h_count}"
            print(msg, flush=True)
            results_log.append({"ticker": ticker, "as_of": as_of, "status": st, "count": h_count, "cached": True})
            if progress_cb:
                progress_cb(i, total, ticker, as_of, st, h_count)
            continue

        # Remote fetch with pacing and 429 retry
        attempt = 0
        success = False
        while attempt <= max_retries_429 and not success:
            attempt += 1
            _pace()
            print(f"[{i}/{total}] FETCHING: {ticker} {as_of} (attempt {attempt}) ...", end=" ", flush=True)
            t0 = time.time()
            try:
                data = news_sentiment.get_news(
                    ticker, as_of, lookback_days=lookback_days, max_records=max_records
                )
                headlines = data.get("headlines") or []
                h_count = len(headlines)
                st = data.get("status") or ("ok" if h_count > 0 else "empty")
                status_counts[st] = status_counts.get(st, 0) + 1

                if h_count == 0:
                    dist_counts["zero"] += 1
                elif h_count < 5:
                    dist_counts["low_1_to_4"] += 1
                else:
                    dist_counts["ge_5"] += 1

                elapsed = round(time.time() - t0, 1)
                print(f"-> status={st}, headlines={h_count} ({elapsed}s)", flush=True)
                results_log.append({
                    "ticker": ticker,
                    "as_of": as_of,
                    "status": st,
                    "count": h_count,
                    "cached": False,
                    "elapsed": elapsed,
                })
                success = True
            except Exception as exc:
                err_str = str(exc)
                is_429 = "429" in err_str or "rate limit" in err_str.lower()
                elapsed = round(time.time() - t0, 1)
                print(f"-> FAILED: {type(exc).__name__}: {err_str[:90]} ({elapsed}s)", flush=True)

                if is_429 and attempt <= max_retries_429:
                    print(f"   [429 Throttled] Cooling down {_COOLDOWN_429}s before retry...", flush=True)
                    time.sleep(_COOLDOWN_429)
                elif attempt > max_retries_429 or not is_429:
                    status_counts["error"] = status_counts.get("error", 0) + 1
                    dist_counts["zero"] += 1
                    results_log.append({
                        "ticker": ticker,
                        "as_of": as_of,
                        "status": "error",
                        "count": 0,
                        "error": err_str,
                        "cached": False,
                    })
                    break

        # Save progress snapshot
        try:
            PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
            PROGRESS_FILE.write_text(json.dumps({
                "timestamp": datetime.now().isoformat(),
                "completed": i,
                "total": total,
                "status_counts": status_counts,
                "distribution": dist_counts,
                "results": results_log,
            }, indent=2), encoding="utf-8")
        except Exception:
            pass

    conn.close()

    total_valid = status_counts.get("ok", 0) + status_counts.get("empty", 0)
    ge_5_pct = (dist_counts["ge_5"] / total * 100) if total else 0.0

    print("\n=== PREFETCH COMPLETE ===", flush=True)
    print(f"Status counts: {status_counts}", flush=True)
    print(f"Headline distribution: 0={dist_counts['zero']}, 1-4={dist_counts['low_1_to_4']}, >=5={dist_counts['ge_5']} ({ge_5_pct:.1f}% >=5)", flush=True)

    return {
        "status_counts": status_counts,
        "distribution": dist_counts,
        "share_ge_5": ge_5_pct,
        "total_cases": total,
        "results": results_log,
    }


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TESTSET
    run_prefetch(path)
