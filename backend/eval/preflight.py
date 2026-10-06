"""One-command pre-experiment gate.

Answers, from real runs, the three questions that decide whether the frozen test
set is usable BEFORE any LLM experiment is scored:
  1. Is the model a pinned version?
  2. Does the test window post-date the model's training cutoff (recall probe)?
  3. Do the Sentiment / Fundamental agents actually receive evidence for the
     test dates (or would their ablations be vacuous)?
It never edits the test set and never scores anything. It reports; a human acts.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from backend.config import Config
from backend.eval import provenance, recall_probe, testset as testset_mod

RESULTS = Config.DATA_DIR.parent / "results"


def non_null(x) -> int:
    """Count non-null leaf values in any nested dict/list (shape-agnostic)."""
    if isinstance(x, dict):
        return sum(non_null(v) for v in x.values())
    if isinstance(x, (list, tuple)):
        return sum(non_null(v) for v in x)
    return 0 if x is None or x == "" else 1


def audit_case(ticker: str, as_of: date) -> dict:
    from backend.context import build
    try:
        c = build(ticker, as_of, with_fundamentals=True, with_news=True, with_macro=True)
    except Exception as exc:  # recorded, never hidden
        return {"ticker": ticker, "as_of": str(as_of), "error": str(exc)}
    heads = (c.news or {}).get("headlines") or []
    return {"ticker": ticker, "as_of": str(as_of), "news_items": len(heads),
            "fundamental_values": non_null(c.fundamentals), "macro_values": non_null(c.macro)}


def verdict(probe: dict | None, audit: list[dict], case_dates: list[str], llm_results_exist: bool) -> list[str]:
    out: list[str] = []
    ok = [a for a in audit if "error" not in a]
    if probe and probe.get("latest_recalled_date"):
        cut = probe["latest_recalled_date"]
        bad = sum(d <= cut for d in case_dates)
        if bad:
            out.append(f"CONTAMINATED: {bad}/{len(case_dates)} test cases have as_of <= {cut}, "
                       f"a date the model recalled. Rebuild the test set from "
                       f"{probe['recommended_testset_start']}. "
                       + ("Re-freezing is still legitimate: no LLM results exist yet."
                          if not llm_results_exist else
                          "LLM results already exist -- a rebuild must be disclosed in the report."))
    elif probe:
        out.append("No recall detected in the probed window (a refusal is weaker evidence than a wrong answer; "
                   "report probe counts, not just the boundary).")
    if ok:
        for key, label in (("news_items", "Sentiment (news)"), ("fundamental_values", "Fundamental")):
            empty = sum(a[key] == 0 for a in ok) / len(ok)
            if empty >= 0.5:
                out.append(f"VACUOUS ABLATION RISK: {label} evidence is empty for {empty:.0%} of cases; "
                           f"removing that specialist cannot change results by construction. "
                           f"Report as a limitation or change the data source.")
    if len(ok) < len(audit):
        out.append(f"{len(audit) - len(ok)} case(s) failed the audit; see errors in the JSON.")
    return out or ["No blocking issues found."]


def run(start: date, end: date, step: int = 30, path: Path | None = None) -> dict:
    provenance.require_pinned_model()          # stop early: probe is tied to the model ID
    print("\nStep 1/2  Recall probe (Gemini calls, paced to your quota). Safe to rerun: answers are cached.", flush=True)
    probe = recall_probe.sweep(start, end, step_days=step)
    print("          probe finished.", flush=True)
    path = path or Config.DATA_DIR / "testset.json"
    cases = testset_mod.cases(path)
    print(f"\nStep 2/2  Data audit of {len(cases)} test cases. First run downloads a lot and can take "
          f"30+ minutes; do NOT press Ctrl+C (everything is cached for next time).", flush=True)
    audit, interrupted = [], False
    try:
        for i, c in enumerate(cases, 1):
            print(f"  [{i}/{len(cases)}] {c.ticker} {c.as_of} ...", flush=True)
            a = audit_case(c.ticker, date.fromisoformat(str(c.as_of)))
            print("      FAILED: " + a["error"][:90] if "error" in a else
                  f"      news={a['news_items']}  fundamentals={a['fundamental_values']}  macro={a['macro_values']}",
                  flush=True)
            audit.append(a)
    except KeyboardInterrupt:
        interrupted = True
        print("\n  Stopped early; reporting what finished.", flush=True)
    llm_exist = any(not p.name.startswith("naive") for p in RESULTS.glob("*.json")
                    if not p.name.startswith("preflight"))
    report = {"run_at": datetime.now().isoformat(timespec="seconds"),
              "provenance": provenance.collect(path, "preflight"),
              "probe": {k: v for k, v in probe.items() if k != "probes"},
              "probes": probe["probes"], "audit": audit,
              "verdict": ([f"PARTIAL: audit covers {len(audit)}/{len(cases)} cases; rerun to finish."]
                          if interrupted or len(audit) < len(cases) else [])
              + verdict(probe, audit, [str(c.as_of) for c in cases], llm_exist)}
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"preflight_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    report["path"] = str(out)
    return report
