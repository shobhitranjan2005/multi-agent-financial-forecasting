"""Phase 4 experiment runner — the ablation suite behind the research question.

The Phase 4 exit gate is that every claim destined for the report is regenerable
by one command. This module is that command's engine: it runs each configuration
over the frozen test set, repeats each one with a fresh cache nonce, and emits a
single markdown report containing the three comparisons the research question
actually asks for.

    Q1  Does the multi-agent system beat a single LLM, and does either beat a
        two-line naive rule?
    Q2  Does the debate stage earn its cost? Accuracy delta AND token delta, side
        by side, because either alone is unpublishable.
    Q3  Which specialists contribute anything? Leave-one-out. At least one
        specialist adding nothing is an expected finding, not a failure.

REPEATS AND THE NONCE. Each repeat passes a unique cache nonce. Without it the
second run of a configuration is served entirely from the LLM cache, reports
identical numbers, and the measured variance is exactly zero — an artifact that
looks like a remarkably stable system. The nonce is the difference between
reporting variance and fabricating its absence.

COST IS A FIRST-CLASS RESULT. A configuration that gains two points of accuracy
for 2.4x the tokens is a different finding from one that gains two points for
free, and only one of them is worth deploying. Both deltas appear in every table.
"""
from __future__ import annotations

import statistics
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.eval import harness, metrics, stats

# The standard suite, in reporting order. Non-LLM baselines first so the report
# reads as "here is the floor, now here is what the machinery buys you".
NAIVE = ["naive-momentum", "naive-alwaysup"]
CORE = ["baseline", "multiagent", "multiagent-nodebate"]
LEAVE_ONE_OUT = [
    "multiagent-no-technical",
    "multiagent-no-fundamental",
    "multiagent-no-sentiment",
    "multiagent-no-macro",
]
FULL_SUITE = NAIVE + CORE + LEAVE_ONE_OUT

# Metrics aggregated across repeats. Everything else is reported from run 1.
_AGGREGATED = [
    "directional_accuracy_pct",
    "nifty_relative_accuracy_pct",
    "mape_pct",
    "brier_score",
    "overconfidence_gap_pts",
    "mean_tokens_per_forecast",
    "mean_seconds_per_forecast",
    "total_llm_calls",
]


def _mean_std(values: list[Optional[float]]) -> tuple[Optional[float], Optional[float]]:
    vals = [v for v in values if v is not None]
    if not vals:
        return None, None
    mean = round(statistics.mean(vals), 3)
    std = round(statistics.stdev(vals), 3) if len(vals) > 1 else 0.0
    return mean, std



def _make_map(scored_by_run: list[list]) -> dict:
    out = {}
    for run_idx, run_scored in enumerate(scored_by_run):
        for s in run_scored:
            if s.direction_correct is not None:
                out[(f"{s.ticker}_{run_idx}", s.as_of)] = float(s.direction_correct)
    return out

def aggregate(summaries: list[dict]) -> dict:
    """Collapse repeats of one configuration into mean +/- std."""
    if not summaries:
        return {}
    out = dict(summaries[0])
    out["n_repeats"] = len(summaries)
    for key in _AGGREGATED:
        mean, std = _mean_std([s.get(key) for s in summaries])
        out[key] = mean
        out[f"{key}_std"] = std
    return out


def run_suite(
    systems: list[str],
    *,
    repeats: int = 1,
    limit: Optional[int] = None,
    progress: bool = True,
) -> dict[str, dict]:
    """Run every configuration `repeats` times. Returns {system: aggregated summary}.

    A configuration that fails outright is recorded and skipped rather than
    aborting the sweep: a full suite is a long run, and losing eight completed
    configurations because the ninth had no API quota left would be its own
    kind of engineering failure.
    """
    results: dict[str, dict] = {}
    for system in systems:
        per_run: list[dict] = []
        scored_by_run = []
        for i in range(1, repeats + 1):
            # Unique nonce per repeat -- see the module docstring.
            nonce = f"r{i}" if repeats > 1 else ""
            if progress:
                label = f"{system} (repeat {i}/{repeats})" if repeats > 1 else system
                print(f"\n  === {label} ===")
            try:
                result = harness.run(system, limit=limit, nonce=nonce, progress=progress)
            except Exception as exc:
                print(f"  SKIPPED {system}: {type(exc).__name__}: {exc}")
                continue
            harness.write_results(result)
            per_run.append(result["summary"])
            scored_by_run.append(result["scored"])
        if per_run:
            agg = aggregate(per_run)
            agg["scored_map"] = _make_map(scored_by_run)
            try:
                if len(agg["scored_map"]) > 0:
                    ci = stats.mean_ci(agg["scored_map"])
                    agg["dir_acc_ci_low"] = ci["ci_low"] * 100
                    agg["dir_acc_ci_high"] = ci["ci_high"] * 100
            except ValueError:
                pass
            results[system] = agg
    return results


# ---------------------------------------------------------------------------
# report rendering
# ---------------------------------------------------------------------------
def _fmt(value, suffix: str = "", std=None, ci_low=None, ci_high=None) -> str:
    if value is None:
        return "—"
    text = f"{value:,.2f}{suffix}" if isinstance(value, float) else f"{value:,}{suffix}"
    if std is not None:
        text += f" ±{std:,.2f}"
    if ci_low is not None and ci_high is not None:
        text += f" [{ci_low:,.1f}, {ci_high:,.1f}]"
    return text


def _delta(a: Optional[float], b: Optional[float]) -> str:
    """a minus b, signed. Both None-safe."""
    if a is None or b is None:
        return "—"
    return f"{a - b:+,.2f}"


def _ratio(a: Optional[float], b: Optional[float]) -> str:
    if a is None or b is None or not b:
        return "—"
    return f"{a / b:.2f}x"


def comparison_table(results: dict[str, dict], systems: list[str]) -> str:
    cols = [
        ("directional_accuracy_pct", "Dir. acc %"),
        ("nifty_relative_accuracy_pct", "vs NIFTY %"),
        ("mape_pct", "MAPE %"),
        ("brier_score", "Brier"),
        ("overconfidence_gap_pts", "Overconf."),
        ("mean_tokens_per_forecast", "Tokens/fc"),
        ("mean_seconds_per_forecast", "Sec/fc"),
    ]
    head = "| System | N | " + " | ".join(label for _, label in cols) + " |"
    rule = "| :--- | ---: |" + " ---: |" * len(cols)
    lines = [head, rule]
    for system in systems:
        s = results.get(system)
        if not s:
            continue
        cells = []
        for k, _ in cols:
            if k == "directional_accuracy_pct" and "dir_acc_ci_low" in s:
                cells.append(_fmt(s.get(k), std=s.get(f"{k}_std"), ci_low=s.get("dir_acc_ci_low"), ci_high=s.get("dir_acc_ci_high")))
            else:
                cells.append(_fmt(s.get(k), std=s.get(f"{k}_std")))
        lines.append(f"| {system} | {s.get('n_scoreable', 0)} | " + " | ".join(cells) + " |")
    return "\n".join(lines)



def _pair_stats(a_sys: str, b_sys: str, results: dict) -> str:
    if a_sys not in results or b_sys not in results:
        return "—"
    a_map = results[a_sys].get("scored_map", {})
    b_map = results[b_sys].get("scored_map", {})
    keys = sorted(set(a_map) & set(b_map))
    if not keys: return "—"
    try:
        diff_ci = stats.paired_diff_ci(a_map, b_map)
        a_bools = [bool(a_map[k]) for k in keys]
        b_bools = [bool(b_map[k]) for k in keys]
        mc = stats.mcnemar_exact(a_bools, b_bools)
        
        sig = "" if diff_ci["excludes_zero"] else " (no supported difference)"
        mc_text = f"p={mc['p_value']:.3f} optimistic: assumes independent cases"
        return f"{diff_ci['mean']*100:+.2f} [{diff_ci['ci_low']*100:+.2f}, {diff_ci['ci_high']*100:+.2f}]{sig} | {mc_text}"
    except Exception as exc:
        return f"error: {exc}"

def debate_verdict(results: dict[str, dict]) -> str:
    """The headline finding: what the debate bought, and what it cost."""
    full = results.get("multiagent")
    lean = results.get("multiagent-nodebate")
    if not full or not lean:
        return "_Debate ablation not available — run both `multiagent` and " \
               "`multiagent-nodebate`._"

    acc_delta = _delta(full.get("directional_accuracy_pct"),
                       lean.get("directional_accuracy_pct"))
    acc_stats = _pair_stats("multiagent", "multiagent-nodebate", results)
    rel_delta = _delta(full.get("nifty_relative_accuracy_pct"),
                       lean.get("nifty_relative_accuracy_pct"))
    brier_delta = _delta(full.get("brier_score"), lean.get("brier_score"))
    token_ratio = _ratio(full.get("mean_tokens_per_forecast"),
                         lean.get("mean_tokens_per_forecast"))
    time_ratio = _ratio(full.get("mean_seconds_per_forecast"),
                        lean.get("mean_seconds_per_forecast"))

    lines = [
        "| Measure | With debate | Without debate | Delta |",
        "| :--- | ---: | ---: | ---: |",
        f"| Directional accuracy % | {_fmt(full.get('directional_accuracy_pct'))} | "
        f"{_fmt(lean.get('directional_accuracy_pct'))} | {acc_delta}<br/>_{acc_stats}_ |",
        f"| NIFTY-relative accuracy % | {_fmt(full.get('nifty_relative_accuracy_pct'))} | "
        f"{_fmt(lean.get('nifty_relative_accuracy_pct'))} | {rel_delta} |",
        f"| Brier score (lower better) | {_fmt(full.get('brier_score'))} | "
        f"{_fmt(lean.get('brier_score'))} | {brier_delta} |",
        f"| Tokens per forecast | {_fmt(full.get('mean_tokens_per_forecast'))} | "
        f"{_fmt(lean.get('mean_tokens_per_forecast'))} | {token_ratio} |",
        f"| Seconds per forecast | {_fmt(full.get('mean_seconds_per_forecast'))} | "
        f"{_fmt(lean.get('mean_seconds_per_forecast'))} | {time_ratio} |",
        "",
        f"The debate stage costs **{token_ratio} the tokens** and "
        f"**{time_ratio} the wall time** of the same specialists without it. "
        f"Directional accuracy moves by **{acc_delta} points**.",
        "",
        "Read the accuracy delta against the repeat-to-repeat standard deviation in "
        "the table above before calling it an effect. On a test set this size a "
        "swing of a few points is comfortably inside sampling noise, and a "
        "well-measured null result is a legitimate finding — it is the answer to "
        "the question this project asked.",
    ]
    return "\n".join(lines)


def leave_one_out_table(results: dict[str, dict]) -> str:
    """What each specialist contributes, measured by removing it."""
    full = results.get("multiagent")
    if not full:
        return "_Leave-one-out requires a `multiagent` run to compare against._"

    lines = [
        "| Specialist removed | Dir. acc % | Delta vs full | vs NIFTY % | Tokens/fc |",
        "| :--- | ---: | ---: | ---: | ---: |",
        f"| _none (full system)_ | {_fmt(full.get('directional_accuracy_pct'))} | — | "
        f"{_fmt(full.get('nifty_relative_accuracy_pct'))} | "
        f"{_fmt(full.get('mean_tokens_per_forecast'))} |",
    ]
    for system in LEAVE_ONE_OUT:
        s = results.get(system)
        if not s:
            continue
        name = system.replace("multiagent-no-", "")
        diff_stats = _pair_stats(system, "multiagent", results)
        lines.append(
            f"| {name} | {_fmt(s.get('directional_accuracy_pct'))} | "
            f"{_delta(s.get('directional_accuracy_pct'), full.get('directional_accuracy_pct'))}<br/>_{diff_stats}_ | "
            f"{_fmt(s.get('nifty_relative_accuracy_pct'))} | "
            f"{_fmt(s.get('mean_tokens_per_forecast'))} |"
        )
    lines.append("")
    lines.append(
        "A **negative** delta means accuracy fell when that specialist was removed, "
        "so it was contributing. A delta near zero means it was not: that specialist "
        "is paying for tokens without earning them, which is a result worth "
        "reporting rather than a bug worth hiding."
    )
    return "\n".join(lines)


def build_report(results: dict[str, dict], *, repeats: int, limit: Optional[int]) -> str:
    ran = [s for s in FULL_SUITE if s in results]
    return "\n\n".join([
        f"# Phase 4 — Ablation results",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M} · {repeats} repeat(s) per "
        f"configuration · {'full test set' if not limit else f'first {limit} cases'}_",

        "## 1. All configurations",
        comparison_table(results, ran),
        "Values are means across repeats; ± is the standard deviation across "
        "repeats at fixed temperature, which is the sampling noise of the model "
        "itself. Raw directional accuracy sits next to NIFTY-relative accuracy "
        "deliberately: on a trending index an unconditionally bullish rule scores "
        "well on the first and near chance on the second.",

        "## 2. Does the debate earn its cost?",
        debate_verdict(results),

        "## 3. Which specialists contribute? (leave-one-out)",
        leave_one_out_table(results),

        "## 4. Reproduction",
        "```\npython -m evaluate ablate"
        + (f" --repeats {repeats}" if repeats > 1 else "")
        + (f" --limit {limit}" if limit else "")
        + "\n```\n"
        "Every row traces to a CSV and JSON file under `results/`, written per "
        "configuration per repeat at the time of the run.",
    ])


def write_report(results: dict[str, dict], *, repeats: int, limit: Optional[int],
                 outdir: Path = harness.RESULTS_DIR) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"ablation_{datetime.now():%Y%m%d_%H%M%S}.md"
    path.write_text(build_report(results, repeats=repeats, limit=limit), encoding="utf-8")
    return path
