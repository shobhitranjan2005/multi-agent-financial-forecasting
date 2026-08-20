"""The harness: run any forecaster over the frozen test set and score it.

"Any forecaster" is the design constraint. The harness knows nothing about
whether it is scoring a naive rule, a single Gemini call, or the full debating
multi-agent graph — every one of them is a callable returning a ForecastRecord.
That is what makes the Phase 4 ablations one-liners instead of new code paths.
"""
from __future__ import annotations

import csv
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from backend.agents.schemas import ForecastRecord
from backend.config import Config
from backend.eval import metrics, naive, outcomes, testset as testset_mod
from backend.eval.metrics import Scored

RESULTS_DIR = Config.DATA_DIR.parent / "results"

Forecaster = Callable[..., ForecastRecord]


def get_forecaster(system: str) -> Forecaster:
    """Resolve a system name to a callable. Imports are lazy so the naive
    baselines run without google-genai configured."""
    if system in naive.REGISTRY:
        return naive.REGISTRY[system]
    if system == "baseline":
        from backend.baseline import forecast
        return forecast
    if system == "multiagent" or system.startswith("multiagent-"):
        from backend.graph.pipeline import SPECIALISTS, run as run_pipeline

        # Every Phase 4 ablation is a system NAME, not a new code path:
        #   multiagent                  full system
        #   multiagent-nodebate         debate stage removed
        #   multiagent-no-sentiment     leave-one-out on a specialist
        #   multiagent-no-macro-news    several at once
        debate = system != "multiagent-nodebate"
        dropped: tuple[str, ...] = ()
        if system.startswith("multiagent-no-") and system != "multiagent-nodebate":
            dropped = tuple(system[len("multiagent-no-"):].split("-"))
            unknown = [d for d in dropped if d not in SPECIALISTS]
            if unknown:
                raise ValueError(
                    f"unknown system '{system}': cannot drop {unknown}. "
                    f"Droppable specialists: {', '.join(SPECIALISTS)}"
                )

        def _run(ticker, as_of, **kw):
            kw.setdefault("debate", debate)
            kw.setdefault("drop", dropped)
            return run_pipeline(ticker, as_of, **kw)

        return _run
    raise ValueError(
        f"unknown system '{system}'. Known: "
        f"{', '.join(list(naive.REGISTRY))}, baseline, multiagent, multiagent-nodebate, "
        f"multiagent-no-<specialist>"
    )


def score_record(rec: ForecastRecord) -> Scored:
    """Join one forecast to its realised outcome."""
    out = outcomes.realised(
        rec.ticker, rec.as_of, horizon_sessions=rec.horizon_sessions
    )
    f = rec.forecast
    return Scored(
        ticker=rec.ticker,
        as_of=rec.as_of,
        system=rec.system,
        predicted_direction=f.expected_direction if f else None,
        actual_direction=out.get("actual_direction"),
        confidence_pct=f.confidence_pct if f else None,
        target_low=f.target_low_inr if f else None,
        target_high=f.target_high_inr if f else None,
        actual_close=out.get("end_close"),
        return_pct=out.get("return_pct"),
        benchmark_return_pct=out.get("benchmark_return_pct"),
        excess_return_pct=out.get("excess_return_pct"),
        tokens=rec.total_tokens,
        seconds=rec.seconds,
        llm_calls=rec.llm_calls,
        parse_failed=f is None,
        note=out.get("note"),
    )


def run(
    system: str,
    *,
    limit: Optional[int] = None,
    nonce: str = "",
    testset_path: Path = testset_mod.TESTSET_PATH,
    progress: bool = True,
    **forecaster_kwargs,
) -> dict:
    """Run `system` over the frozen test set and return scored results."""
    cases = testset_mod.cases(testset_path)
    if limit:
        cases = cases[:limit]
    fn = get_forecaster(system)

    records: list[ForecastRecord] = []
    scored: list[Scored] = []
    failures: list[dict] = []
    started = time.time()

    for i, case in enumerate(cases, 1):
        if progress:
            print(f"  [{i:>3}/{len(cases)}] {case.ticker:<14} {case.as_of} ... ",
                  end="", flush=True)
        try:
            rec = fn(
                case.ticker, case.as_of,
                horizon_sessions=case.horizon_sessions,
                nonce=nonce,
                **forecaster_kwargs,
            )
        except Exception as exc:
            # One bad case must not kill a 90-minute sweep.
            failures.append({"ticker": case.ticker, "as_of": case.as_of,
                             "error": f"{type(exc).__name__}: {exc}"})
            if progress:
                print(f"FAILED ({type(exc).__name__})")
            continue

        records.append(rec)
        s = score_record(rec)
        scored.append(s)
        if progress:
            mark = "?" if s.direction_correct is None else ("OK " if s.direction_correct else "X  ")
            print(f"{mark} pred={s.predicted_direction or '-':<5} "
                  f"actual={s.actual_direction or '-':<5}")

    summary = metrics.summarise(scored, system=system)
    summary["wall_seconds"] = round(time.time() - started, 1)
    summary["n_errors"] = len(failures)

    return {
        "system": system,
        "nonce": nonce,
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "testset": str(testset_path),
        "summary": summary,
        "reliability": metrics.reliability_table(scored),
        "scored": scored,
        "records": records,
        "failures": failures,
    }


def write_results(result: dict, outdir: Path = RESULTS_DIR) -> dict[str, Path]:
    """Persist a run: CSV of every forecast, JSON summary, markdown table.

    Every claim in the report must trace to one of these files (Phase 4 exit
    gate), so they are written even when the run had failures.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = f"{result['system']}{('_' + result['nonce']) if result['nonce'] else ''}_{stamp}"

    csv_path = outdir / f"{tag}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "ticker", "as_of", "system", "predicted_direction", "actual_direction",
            "direction_correct", "relative_correct", "confidence_pct",
            "target_low", "target_high", "actual_close", "return_pct",
            "benchmark_return_pct", "excess_return_pct", "abs_pct_error",
            "brier", "tokens", "llm_calls", "seconds", "parse_failed", "note",
        ])
        for s in result["scored"]:
            w.writerow([
                s.ticker, s.as_of, s.system, s.predicted_direction, s.actual_direction,
                s.direction_correct, s.relative_correct, s.confidence_pct,
                s.target_low, s.target_high, s.actual_close, s.return_pct,
                s.benchmark_return_pct, s.excess_return_pct,
                None if s.absolute_pct_error is None else round(s.absolute_pct_error, 3),
                None if s.brier is None else round(s.brier, 4),
                s.tokens, s.llm_calls, s.seconds, s.parse_failed, s.note,
            ])

    json_path = outdir / f"{tag}.json"
    json_path.write_text(json.dumps({
        "system": result["system"],
        "nonce": result["nonce"],
        "run_at": result["run_at"],
        "testset": result["testset"],
        "summary": result["summary"],
        "reliability": result["reliability"],
        "failures": result["failures"],
    }, indent=2, default=str), encoding="utf-8")

    md_path = outdir / f"{tag}.md"
    md_path.write_text(
        f"# {result['system']} — {result['run_at']}\n\n"
        + metrics.markdown_table([result["summary"]])
        + "\n\n## Calibration\n\n"
        + _reliability_md(result["reliability"])
        + (f"\n\n## Failures ({len(result['failures'])})\n\n"
           + "\n".join(f"- {f['ticker']} {f['as_of']}: {f['error']}" for f in result["failures"])
           if result["failures"] else ""),
        encoding="utf-8",
    )
    return {"csv": csv_path, "json": json_path, "markdown": md_path}


def _reliability_md(rows: list[dict]) -> str:
    lines = ["| Confidence bucket | N | Claimed | Realised | Gap |",
             "| :--- | ---: | ---: | ---: | ---: |"]
    for r in rows:
        claimed = "—" if r["mean_confidence"] is None else f"{r['mean_confidence']}%"
        realised = "—" if r["realised_accuracy"] is None else f"{r['realised_accuracy']}%"
        gap = "—" if r["gap"] is None else f"{r['gap']:+.1f}"
        lines.append(f"| {r['bucket']} | {r['n']} | {claimed} | {realised} | {gap} |")
    return "\n".join(lines)
