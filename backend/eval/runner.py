"""Staged execution runner for free-tier evaluations with daily quota pauses.

Responsibilities:
1. Executes the evaluation plan:
   - Round 1: naive-momentum, naive-alwaysup, baseline, multiagent,
              multiagent-nodebate, 4 leave-one-out configs (1 repeat, nonce="")
   - Round 2: 2 more repeats (r2, r3) for baseline, multiagent, multiagent-nodebate
   - Cost table: uncached run of at least 10 cases with fresh nonce per system
2. Daily quota management:
   - Treats "Daily Gemini quota exhausted" as a PAUSE signal (not an abort)
   - Logs pause events and daily call counts to results/runner_progress.json
   - Sleeps in 30-minute intervals until quota resets (midnight Pacific)
   - Resumes execution cleanly from cache
3. Safety and integrity:
   - Enforces clean working tree before execution
   - Commits and pushes results after each completed system (showing git status)
   - Never stages or commits .env, data/cache.db, or scratch/
   - Aborts on STOP CONDITIONS: non-quota strict mode errors, parse failure rate > 10%,
     or unexpected 4xx errors
   - Keeps client-side LLM_MAX_RPM pacing throughout
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from backend.config import Config
from backend.eval import harness, metrics, provenance, testset as testset_mod

PT_TZ = ZoneInfo("US/Pacific")
RESULTS_DIR = Config.DATA_DIR.parent / "results"
PROGRESS_FILE = RESULTS_DIR / "runner_progress.json"

STAGE_ROUND_1 = [
    ("naive-momentum", ""),
    ("naive-alwaysup", ""),
    ("baseline", ""),
    ("multiagent", ""),
    ("multiagent-nodebate", ""),
    ("multiagent-no-technical", ""),
    ("multiagent-no-fundamental", ""),
    ("multiagent-no-sentiment", ""),
    ("multiagent-no-macro", ""),
]

STAGE_ROUND_2 = [
    ("baseline", "r2"),
    ("baseline", "r3"),
    ("multiagent", "r2"),
    ("multiagent", "r3"),
    ("multiagent-nodebate", "r2"),
    ("multiagent-nodebate", "r3"),
]

STAGE_COST = [
    ("naive-momentum", "cost"),
    ("naive-alwaysup", "cost"),
    ("baseline", "cost"),
    ("multiagent", "cost"),
    ("multiagent-nodebate", "cost"),
    ("multiagent-no-technical", "cost"),
    ("multiagent-no-fundamental", "cost"),
    ("multiagent-no-sentiment", "cost"),
    ("multiagent-no-macro", "cost"),
]


class RunnerStopCondition(RuntimeError):
    """Hard stop condition encountered during evaluation."""


class Clock:
    """Clock interface to allow fake-clock testing for pause/retry mechanisms."""

    def now(self, tz: Optional[Any] = None) -> datetime:
        return datetime.now(tz)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class FakeClock:
    """Mock clock for deterministic testing of daily quota resets and 30m pauses."""

    def __init__(self, initial_time: Optional[datetime] = None):
        self._current = initial_time or datetime(2026, 10, 16, 12, 0, 0, tzinfo=PT_TZ)
        self.sleep_calls: list[float] = []

    def now(self, tz: Optional[Any] = None) -> datetime:
        if tz is not None:
            return self._current.astimezone(tz)
        return self._current

    def advance(self, seconds: float) -> None:
        self._current += timedelta(seconds=seconds)

    def set_time(self, dt: datetime) -> None:
        self._current = dt

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.advance(seconds)


def is_daily_quota_error(exc: BaseException) -> bool:
    """Identify if an exception corresponds to daily Gemini quota exhaustion."""
    curr: Optional[BaseException] = exc
    while curr is not None:
        text = str(curr).lower()
        if "daily gemini quota" in text:
            return True
        if any(k in text for k in ("perday", "requestsperday", "per day", "requests per day")):
            return True
        if ("quota" in text or "resource_exhausted" in text or "429" in text) and ("daily" in text or "day" in text):
            return True
        curr = curr.__cause__ or curr.__context__
    return False


def is_fatal_4xx_error(exc: BaseException) -> bool:
    """Check for 4xx errors other than 429 (which would indicate non-quota API failure)."""
    curr: Optional[BaseException] = exc
    while curr is not None:
        text = str(curr).lower()
        for code in ("400", "401", "403", "404", "invalid_argument", "permission_denied", "unauthenticated"):
            if code in text and "429" not in text:
                return True
        curr = curr.__cause__ or curr.__context__
    return False


def next_midnight_pacific(clock: Clock) -> datetime:
    """Return the next midnight in Pacific Time."""
    pt_now = clock.now(PT_TZ)
    return datetime(pt_now.year, pt_now.month, pt_now.day, tzinfo=PT_TZ) + timedelta(days=1)


def seconds_until_midnight_pacific(clock: Clock) -> float:
    """Seconds remaining until midnight in Pacific Time."""
    pt_now = clock.now(PT_TZ)
    midnight = next_midnight_pacific(clock)
    return max(0.0, (midnight - pt_now).total_seconds())


def load_progress(path: Path = PROGRESS_FILE) -> dict:
    """Load runner progress log if present, or initialize empty structure."""
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "updated_at": "",
        "status": "NOT_STARTED",
        "current_stage": "",
        "current_system": "",
        "daily_calls": {},
        "pause_history": [],
        "completed_systems": [],
    }


def save_progress(data: dict, path: Path = PROGRESS_FILE) -> None:
    """Atomically persist runner progress to JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp_path.replace(path)


def git_commit_and_push(
    system: str,
    nonce: str,
    stage: str,
    paths: dict[str, Path],
    progress_file: Path = PROGRESS_FILE,
) -> None:
    """Safely commit and push newly completed system results."""
    repo_root = Config.DATA_DIR.parent

    # 1. Print git status before commit
    status = subprocess.check_output(["git", "status", "--short"], cwd=repo_root, text=True)
    print("\n  [GIT STATUS BEFORE COMMIT]\n" + (status if status.strip() else "  (clean)\n"))

    # 2. Stage only results files and runner_progress.json
    files_to_stage = [str(p.relative_to(repo_root)).replace("\\", "/") for p in paths.values()]
    try:
        prog_rel = str(progress_file.relative_to(repo_root)).replace("\\", "/")
        if prog_rel not in files_to_stage:
            files_to_stage.append(prog_rel)
    except ValueError:
        pass

    # Safety check on path strings
    for f in files_to_stage:
        if ".env" in f or "cache.db" in f or "scratch" in f:
            raise RuntimeError(f"SECURITY CHECK FAILED: attempted to stage forbidden file: {f}")

    subprocess.check_call(["git", "add", *files_to_stage], cwd=repo_root)

    # 3. Verify staged files with git diff --cached
    cached = subprocess.check_output(
        ["git", "diff", "--name-only", "--cached"], cwd=repo_root, text=True
    ).splitlines()
    for cf in cached:
        norm = cf.strip().replace("\\", "/")
        if norm == ".env" or "cache.db" in norm or norm.startswith("scratch/"):
            subprocess.check_call(["git", "reset", "HEAD"], cwd=repo_root)
            raise RuntimeError(f"SECURITY CHECK FAILED: forbidden file in index: {cf}")

    # 4. Commit and push
    tag = f"{system}{('_' + nonce) if nonce else ''}"
    commit_msg = f"eval: complete {tag} [{stage}] [skip ci]"
    subprocess.check_call(["git", "commit", "-m", commit_msg], cwd=repo_root)
    subprocess.check_call(["git", "push", "origin", "main"], cwd=repo_root)
    print(f"  [GIT] Successfully committed and pushed {tag}.\n")


def is_system_completed(
    system: str,
    nonce: str,
    expected_cases: int,
    progress_data: dict,
    results_dir: Path = RESULTS_DIR,
) -> bool:
    """Check if a system and nonce already produced valid completed results."""
    # Check runner progress completed list
    for entry in progress_data.get("completed_systems", []):
        if entry.get("system") == system and entry.get("nonce", "") == nonce:
            if entry.get("n_scoreable", 0) >= expected_cases:
                return True

    # Check results directory for existing JSON
    prefix = f"{system}{('_' + nonce) if nonce else ''}_"
    if results_dir.exists():
        for p in results_dir.glob(f"{prefix}*.json"):
            if p.name.startswith("preflight_") or p.name.startswith("comparison_") or p.name.startswith("ablation_"):
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("system") == system and data.get("nonce", "") == nonce:
                    scored = data.get("scored", [])
                    failures = data.get("failures", [])
                    if len(scored) >= expected_cases and len(failures) == 0:
                        return True
            except Exception:
                continue
    return False


def run_staged_plan(
    *,
    stage_name: str = "all",
    testset_path: Path = testset_mod.TESTSET_PATH,
    limit: Optional[int] = None,
    clock: Optional[Clock] = None,
    auto_push: bool = True,
    progress_file: Path = PROGRESS_FILE,
    results_dir: Path = RESULTS_DIR,
) -> dict:
    """Execute the free-tier staged evaluation plan with quota pauses and progress tracking."""
    from backend import llm

    clock = clock or Clock()

    # Pre-check working tree cleanliness
    if provenance.is_git_dirty():
        raise RunnerStopCondition(
            "Working tree is dirty (uncommitted tracked modifications or untracked source files). "
            "Evaluation must execute against a clean tree."
        )

    progress_data = load_progress(progress_file)
    progress_data["status"] = "RUNNING"
    progress_data["updated_at"] = clock.now(timezone.utc).isoformat(timespec="seconds")
    if not progress_data.get("run_started_at"):
        progress_data["run_started_at"] = progress_data["updated_at"]
    save_progress(progress_data, progress_file)

    # Register live call tracking hook
    def _on_live_call():
        pt_date = str(clock.now(PT_TZ).date())
        progress_data["daily_calls"][pt_date] = progress_data["daily_calls"].get(pt_date, 0) + 1
        progress_data["updated_at"] = clock.now(timezone.utc).isoformat(timespec="seconds")
        # Save every 5 calls to keep file reasonably in sync without excessive disk writes
        if progress_data["daily_calls"][pt_date] % 5 == 0:
            save_progress(progress_data, progress_file)

    if hasattr(llm, "register_live_call_hook"):
        llm.register_live_call_hook(_on_live_call)

    # Determine stages to run
    stages: list[tuple[str, list[tuple[str, str]]]] = []
    if stage_name in ("all", "1", "round1"):
        stages.append(("round1", STAGE_ROUND_1))
    if stage_name in ("all", "2", "round2"):
        stages.append(("round2", STAGE_ROUND_2))
    if stage_name in ("all", "cost"):
        stages.append(("cost", STAGE_COST))

    all_cases = testset_mod.cases(testset_path)
    total_testset_cases = len(all_cases) if not limit else min(len(all_cases), limit)

    try:
        for stage_id, system_list in stages:
            progress_data["current_stage"] = stage_id
            save_progress(progress_data, progress_file)
            print(f"\n==================================================================")
            print(f"  STAGE: {stage_id.upper()} ({len(system_list)} configurations)")
            print(f"==================================================================\n")

            is_cost_stage = stage_id == "cost"
            expected_n = min(10, total_testset_cases) if is_cost_stage else total_testset_cases
            current_limit = 10 if is_cost_stage else limit

            for system, nonce in system_list:
                progress_data["current_system"] = f"{system}{('_' + nonce) if nonce else ''}"
                save_progress(progress_data, progress_file)

                # Check if already completed
                if is_system_completed(system, nonce, expected_n, progress_data, results_dir):
                    print(f"  [SKIP] {system} (nonce='{nonce}') already completed. Skipping.\n")
                    continue

                print(f"\n  >>> Running {system} (stage: {stage_id}, nonce: '{nonce or 'base'}', limit: {current_limit or 'all'})")

                def _quota_handler(exc, case, case_num, total_cases):
                    paused_at = clock.now(timezone.utc).isoformat(timespec="seconds")
                    sec_to_midnight = seconds_until_midnight_pacific(clock)
                    pt_time_str = clock.now(PT_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")

                    print(
                        f"\n  ================================================================"
                        f"\n  [DAILY QUOTA PAUSE] {system} (nonce='{nonce}') case [{case_num}/{total_cases}]"
                        f"\n  Time (PT): {pt_time_str}"
                        f"\n  Seconds until midnight Pacific: {sec_to_midnight:.0f}s ({sec_to_midnight / 3600:.1f}h)"
                        f"\n  Reason: {exc}"
                        f"\n  Sleeping 30 minutes (1800s) and retrying..."
                        f"\n  ================================================================\n",
                        flush=True,
                    )

                    pause_entry = {
                        "paused_at": paused_at,
                        "system": system,
                        "nonce": nonce,
                        "case": f"{case.ticker} {case.as_of}",
                        "case_num": case_num,
                        "total_cases": total_cases,
                        "reason": str(exc)[:300],
                        "seconds_to_midnight_pacific": round(sec_to_midnight, 1),
                    }
                    progress_data["status"] = "PAUSED"
                    progress_data["updated_at"] = paused_at
                    progress_data["pause_history"].append(pause_entry)
                    save_progress(progress_data, progress_file)

                    # Pause for 30 minutes
                    clock.sleep(1800)

                    resumed_at = clock.now(timezone.utc).isoformat(timespec="seconds")
                    pause_entry["resumed_at"] = resumed_at
                    progress_data["status"] = "RUNNING"
                    progress_data["updated_at"] = resumed_at
                    save_progress(progress_data, progress_file)
                    print(f"  [RESUMING] Woke up at {clock.now(PT_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')}. Retrying from cache...\n", flush=True)

                try:
                    result = harness.run(
                        system,
                        limit=current_limit,
                        nonce=nonce,
                        testset_path=testset_path,
                        progress=True,
                        strict=True,
                        pause_on_quota=True,
                        quota_handler=_quota_handler,
                    )
                except Exception as exc:
                    if is_fatal_4xx_error(exc):
                        progress_data["status"] = "STOPPED"
                        progress_data["stop_reason"] = f"Fatal 4xx client error: {exc}"
                        save_progress(progress_data, progress_file)
                        raise RunnerStopCondition(f"STOP CONDITION: Fatal 4xx error: {exc}") from exc

                    progress_data["status"] = "STOPPED"
                    progress_data["stop_reason"] = f"Strict-mode abort: {exc}"
                    save_progress(progress_data, progress_file)
                    raise RunnerStopCondition(f"STOP CONDITION: Strict-mode abort on {system}: {exc}") from exc

                # Check parse-failure stop condition (>10%)
                scored_records = result.get("scored", [])
                parse_failed_count = sum(1 for s in scored_records if s.parse_failed)
                total_scored = len(scored_records)
                parse_fail_rate = (parse_failed_count / total_scored) if total_scored > 0 else 0.0

                paths = harness.write_results(result, outdir=results_dir)

                if parse_fail_rate > 0.10:
                    progress_data["status"] = "STOPPED"
                    progress_data["stop_reason"] = (
                        f"Parse failure rate {parse_fail_rate:.1%} ({parse_failed_count}/{total_scored}) "
                        f"exceeds 10% threshold in {system}"
                    )
                    save_progress(progress_data, progress_file)
                    raise RunnerStopCondition(progress_data["stop_reason"])

                summary = result.get("summary", {})
                completed_entry = {
                    "system": system,
                    "nonce": nonce,
                    "stage": stage_id,
                    "completed_at": clock.now(timezone.utc).isoformat(timespec="seconds"),
                    "n_scoreable": summary.get("n_scoreable", len(scored_records)),
                    "directional_accuracy_pct": summary.get("directional_accuracy_pct"),
                    "parse_failures": parse_failed_count,
                    "parse_failure_rate_pct": round(parse_fail_rate * 100, 2),
                    "files": {k: str(p) for k, p in paths.items()},
                }
                progress_data["completed_systems"].append(completed_entry)
                progress_data["updated_at"] = clock.now(timezone.utc).isoformat(timespec="seconds")
                save_progress(progress_data, progress_file)

                # Commit and push results after each completed system
                if auto_push:
                    git_commit_and_push(system, nonce, stage_id, paths, progress_file)

        progress_data["status"] = "COMPLETED"
        progress_data["updated_at"] = clock.now(timezone.utc).isoformat(timespec="seconds")
        save_progress(progress_data, progress_file)
        print(f"\n==================================================================")
        print(f"  ALL REQUESTED STAGES COMPLETED SUCCESSFULLY.")
        print(f"==================================================================\n")

    finally:
        if hasattr(llm, "unregister_live_call_hook"):
            llm.unregister_live_call_hook(_on_live_call)

    return progress_data
