import sys
import os

path = 'backend/eval/ablation.py'
with open(path, 'r', encoding='utf-8') as f:
    code = f.read()

# Add stats import
code = code.replace('from backend.eval import harness, metrics', 'from backend.eval import harness, metrics, stats')

# Add helper for scored map
map_helper = """
def _make_map(scored_by_run: list[list]) -> dict:
    out = {}
    for run_idx, run_scored in enumerate(scored_by_run):
        for s in run_scored:
            if s.direction_correct is not None:
                out[(f"{s.ticker}_{run_idx}", s.as_of)] = float(s.direction_correct)
    return out
"""
code = code.replace('def aggregate(summaries: list[dict]) -> dict:', map_helper + '\ndef aggregate(summaries: list[dict]) -> dict:')

# Modify run_suite
run_suite_old = """        for i in range(1, repeats + 1):
            # Unique nonce per repeat -- see the module docstring.
            nonce = f"r{i}" if repeats > 1 else ""
            if progress:
                label = f"{system} (repeat {i}/{repeats})" if repeats > 1 else system
                print(f"\\n  === {label} ===")
            try:
                result = harness.run(system, limit=limit, nonce=nonce, progress=progress)
            except Exception as exc:
                print(f"  SKIPPED {system}: {type(exc).__name__}: {exc}")
                continue
            harness.write_results(result)
            per_run.append(result["summary"])
        if per_run:
            results[system] = aggregate(per_run)"""

run_suite_new = """        scored_by_run = []
        for i in range(1, repeats + 1):
            # Unique nonce per repeat -- see the module docstring.
            nonce = f"r{i}" if repeats > 1 else ""
            if progress:
                label = f"{system} (repeat {i}/{repeats})" if repeats > 1 else system
                print(f"\\n  === {label} ===")
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
            results[system] = agg"""
code = code.replace(run_suite_old, run_suite_new)

# Modify _fmt to handle CIs
fmt_old = 'def _fmt(value, suffix: str = "", std=None) -> str:'
fmt_new = """def _fmt(value, suffix: str = "", std=None, ci_low=None, ci_high=None) -> str:
    if value is None:
        return "—"
    text = f"{value:,.2f}{suffix}" if isinstance(value, float) else f"{value:,}{suffix}"
    if std is not None:
        text += f" ±{std:,.2f}"
    if ci_low is not None and ci_high is not None:
        text += f" [{ci_low:,.1f}, {ci_high:,.1f}]"
    return text"""
code = code.replace('def _fmt(value, suffix: str = "", std=None) -> str:\n    if value is None:\n        return "—"\n    text = f"{value:,.2f}{suffix}" if isinstance(value, float) else f"{value:,}{suffix}"\n    if std:\n        text += f" ±{std:,.2f}"\n    return text', fmt_new)

# Update comparison_table
comp_old = """        cells = [_fmt(s.get(k), std=s.get(f"{k}_std")) for k, _ in cols]"""
comp_new = """        cells = []
        for k, _ in cols:
            if k == "directional_accuracy_pct" and "dir_acc_ci_low" in s:
                cells.append(_fmt(s.get(k), std=s.get(f"{k}_std"), ci_low=s.get("dir_acc_ci_low"), ci_high=s.get("dir_acc_ci_high")))
            else:
                cells.append(_fmt(s.get(k), std=s.get(f"{k}_std")))"""
code = code.replace(comp_old, comp_new)

# Add pair evaluation helper
pair_helper = """
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
"""
code = code.replace('def debate_verdict(results: dict[str, dict]) -> str:', pair_helper + '\ndef debate_verdict(results: dict[str, dict]) -> str:')

# Modify debate_verdict
deb_old = """    acc_delta = _delta(full.get("directional_accuracy_pct"),
                       lean.get("directional_accuracy_pct"))"""
deb_new = """    acc_delta = _delta(full.get("directional_accuracy_pct"),
                       lean.get("directional_accuracy_pct"))
    acc_stats = _pair_stats("multiagent", "multiagent-nodebate", results)"""
code = code.replace(deb_old, deb_new)

deb_table_old = """        f"| Directional accuracy % | {_fmt(full.get('directional_accuracy_pct'))} | "
        f"{_fmt(lean.get('directional_accuracy_pct'))} | {acc_delta} |","""
deb_table_new = """        f"| Directional accuracy % | {_fmt(full.get('directional_accuracy_pct'))} | "
        f"{_fmt(lean.get('directional_accuracy_pct'))} | {acc_delta}<br/>_{acc_stats}_ |","""
code = code.replace(deb_table_old, deb_table_new)

# Modify leave_one_out_table
loo_old = """        name = system.replace("multiagent-no-", "")
        lines.append(
            f"| {name} | {_fmt(s.get('directional_accuracy_pct'))} | "
            f"{_delta(s.get('directional_accuracy_pct'), full.get('directional_accuracy_pct'))} | "
            f"{_fmt(s.get('nifty_relative_accuracy_pct'))} | "
            f"{_fmt(s.get('mean_tokens_per_forecast'))} |"
        )"""
loo_new = """        name = system.replace("multiagent-no-", "")
        diff_stats = _pair_stats(system, "multiagent", results)
        lines.append(
            f"| {name} | {_fmt(s.get('directional_accuracy_pct'))} | "
            f"{_delta(s.get('directional_accuracy_pct'), full.get('directional_accuracy_pct'))}<br/>_{diff_stats}_ | "
            f"{_fmt(s.get('nifty_relative_accuracy_pct'))} | "
            f"{_fmt(s.get('mean_tokens_per_forecast'))} |"
        )"""
code = code.replace(loo_old, loo_new)

with open(path, 'w', encoding='utf-8') as f:
    f.write(code)
print("done")
