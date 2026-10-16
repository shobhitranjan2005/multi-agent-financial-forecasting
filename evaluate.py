"""Phase 2 exit gate — the evaluation CLI.

    python -m evaluate build-testset --start 2025-06-02 --end 2025-12-31
    python -m evaluate recall-probe  --start 2024-01-01 --end 2026-01-01
    python -m evaluate run --system baseline
    python -m evaluate run --system naive-momentum
    python -m evaluate compare --systems naive-momentum,naive-alwaysup,baseline
    python -m evaluate ablate --repeats 3          # Phase 4, one command

Every run writes a CSV, a JSON summary and a markdown table under results/, so
each number in the report traces to a committed file.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from backend.config import enable_utf8_console
from backend.eval import ablation, harness, metrics, recall_probe, testset as testset_mod


def _d(s: str) -> date:
    return datetime.fromisoformat(s).date()


def cmd_build_testset(args) -> int:
    ts = testset_mod.build(
        start=_d(args.start),
        end=_d(args.end),
        n_dates=args.dates,
        n_tickers=args.tickers,
        horizon_sessions=args.horizon,
        seed=args.seed,
        verify_traded=not args.no_verify,
    )
    try:
        dest = Path(args.out) if getattr(args, "out", None) else testset_mod.TESTSET_PATH
        path = testset_mod.save(ts, path=dest, overwrite=args.overwrite)
    except FileExistsError as exc:
        print(f"\n  {exc}\n", file=sys.stderr)
        return 1

    print(f"\n  Wrote {path}")
    print(f"  {ts['n_cases']} cases — {args.dates} dates x {args.tickers} tickers")
    print(f"  Window {ts['window']['start']} to {ts['window']['end']}, "
          f"horizon {ts['horizon_sessions']} sessions")
    print(f"  Universe verified against bhavcopy: {ts['universe_verified_against_bhavcopy']}")
    if ts["exclusions"]:
        print(f"  {len(ts['exclusions'])} exclusions (survivorship-bias control):")
        for e in ts["exclusions"][:10]:
            print(f"    - {e}")
    print("\n  COMMIT THIS FILE. Do not regenerate it after seeing results.\n")
    return 0


def cmd_recall_probe(args) -> int:
    from backend import llm
    if not llm.is_configured():
        print("\n  GEMINI_API_KEY not set — the recall probe requires it.\n", file=sys.stderr)
        return 3
    res = recall_probe.sweep(_d(args.start), _d(args.end), step_days=args.step)
    path = recall_probe.save(res)
    print(f"\n  Probed {res['n_probes']} dates; {res['n_recalled']} index closes recalled; {res.get('n_event_recalled', 0)} macro events recalled.")
    print(f"  Latest index recalled:       {res['latest_recalled_date']}")
    print(f"  Latest event recalled:       {res.get('latest_event_recalled_date')}")
    print(f"  Recommended test-set start:  {res['recommended_testset_start']}")
    print(f"  Written to {path}\n")
    for p in res["probes"]:
        mark = "PRICE_RECALL" if p["recalled"] else "  --  "
        ev_mark = "EVENT_RECALL" if p.get("event_recalled") else "  --  "
        print(f"    {mark:<12} {p['probe_date']}  actual={p['actual_close']} claimed={p['claimed_close']}  {p['note']}")
        if p.get("actual_event_repo_rate") is not None or p.get("claimed_event_repo_rate") is not None:
            print(f"      {ev_mark:<12} repo_rate: actual={p.get('actual_event_repo_rate')}% claimed={p.get('claimed_event_repo_rate')}%  {p.get('event_note')}")
    print()
    return 0


def cmd_run(args) -> int:
    if args.system in ("baseline", "multiagent", "multiagent-nodebate"):
        from backend import llm
        if not llm.is_configured():
            print(f"\n  GEMINI_API_KEY not set — '{args.system}' needs it.\n"
                  f"  The naive baselines run without a key:\n"
                  f"    python -m evaluate run --system naive-momentum\n", file=sys.stderr)
            return 3

    print(f"\n  Running {args.system} over the frozen test set\n")
    result = harness.run(args.system, limit=args.limit, nonce=args.nonce)
    paths = harness.write_results(result)

    print("\n" + metrics.markdown_table([result["summary"]]) + "\n")
    for k, p in paths.items():
        print(f"  {k:<9} {p}")
    print()
    return 0


def cmd_compare(args) -> int:
    systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    summaries = []
    for s in systems:
        print(f"\n  === {s} ===")
        try:
            result = harness.run(s, limit=args.limit, nonce=args.nonce)
        except Exception as exc:
            print(f"  SKIPPED {s}: {type(exc).__name__}: {exc}")
            continue
        harness.write_results(result)
        summaries.append(result["summary"])

    if not summaries:
        print("\n  No systems produced results.\n", file=sys.stderr)
        return 1

    table = metrics.markdown_table(summaries)
    print("\n\n" + table + "\n")

    out = harness.RESULTS_DIR / f"comparison_{datetime.now():%Y%m%d_%H%M%S}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"# System comparison — {datetime.now():%Y-%m-%d %H:%M}\n\n{table}\n\n"
        "Raw directional accuracy is reported next to NIFTY-relative accuracy "
        "deliberately: on a trending index an unconditionally bullish rule scores "
        "well on the former and near chance on the latter.\n",
        encoding="utf-8",
    )
    print(f"  Written to {out}\n")
    return 0


def cmd_ablate(args) -> int:
    """Phase 4 in one command: every configuration, every repeat, one report."""
    from backend import llm

    systems = ([s.strip() for s in args.systems.split(",") if s.strip()]
               if args.systems else list(ablation.FULL_SUITE))

    needs_key = [s for s in systems if s not in ("naive-momentum", "naive-alwaysup")]
    if needs_key and not llm.is_configured():
        print(f"\n  GEMINI_API_KEY not set — {len(needs_key)} of {len(systems)} "
              f"configurations need it.\n  Running the naive baselines only.\n",
              file=sys.stderr)
        systems = [s for s in systems if s not in needs_key]
        if not systems:
            return 3

    print(f"\n  Ablation suite: {len(systems)} configuration(s) "
          f"x {args.repeats} repeat(s)")
    if args.repeats > 1:
        print("  Each repeat uses a unique cache nonce, so the reported variance is real.")

    results = ablation.run_suite(systems, repeats=args.repeats, limit=args.limit)
    if not results:
        print("\n  No configuration produced results.\n", file=sys.stderr)
        return 1

    path = ablation.write_report(results, repeats=args.repeats, limit=args.limit)
    ran = [s for s in ablation.FULL_SUITE if s in results]
    print("\n\n" + ablation.comparison_table(results, ran))
    print(f"\n  Full report written to {path}\n")
    return 0


def cmd_preflight(args) -> int:
    from backend import llm
    from backend.eval import preflight
    if not llm.is_configured():
        print("\n  GEMINI_API_KEY not set in .env\n", file=sys.stderr)
        return 3
    try:
        p_path = Path(args.path) if getattr(args, "path", None) else None
        rep = preflight.run(_d(args.start), _d(args.end), step=args.step, path=p_path)
    except preflight.provenance.UnpinnedModelError as exc:
        print(f"\n  {exc}\n", file=sys.stderr)
        return 4
    print("\n  PREFLIGHT VERDICT")
    for line in rep["verdict"]:
        print(f"   - {line}")
    print(f"\n  Full report: {rep['path']}\n  Paste that file's 'verdict' and 'probe' blocks back for analysis.\n")
    return 0


def cmd_subset(args) -> int:
    from backend.config import Config
    from backend.eval import provenance, testset as testset_mod
    src = Path(args.src) if getattr(args, "src", None) else Config.DATA_DIR / "testset_draft_v3.json"
    dest = Path(args.out) if getattr(args, "out", None) else testset_mod.TESTSET_PATH
    ts = testset_mod.create_subset(src, per_date=args.per_date, status="FROZEN")
    try:
        path = testset_mod.save(ts, path=dest, overwrite=args.overwrite)
    except FileExistsError as exc:
        print(f"\n  {exc}\n", file=sys.stderr)
        return 1

    norm_hash = provenance._sha256(path)
    print(f"\n  Wrote frozen subset with {ts['n_cases']} cases to {path}")
    print(f"  SHA-256 (normalised LF): {norm_hash}\n")
    return 0


def cmd_run_staged(args) -> int:
    from backend.eval import runner, testset as testset_mod
    ts_path = Path(args.testset) if getattr(args, "testset", None) else testset_mod.TESTSET_PATH
    try:
        runner.run_staged_plan(
            stage_name=args.round,
            testset_path=ts_path,
            limit=args.limit,
            auto_push=not args.no_push,
        )
    except runner.RunnerStopCondition as exc:
        print(f"\n  RUNNER STOP CONDITION: {exc}\n", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"\n  UNEXPECTED ERROR: {type(exc).__name__}: {exc}\n", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evaluate", description="Leakage-free evaluation harness.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build-testset", help="freeze a point-in-time test set")
    b.add_argument("--start", required=True)
    b.add_argument("--end", required=True)
    b.add_argument("--dates", type=int, default=8)
    b.add_argument("--tickers", type=int, default=12)
    b.add_argument("--horizon", type=int, default=21)
    b.add_argument("--seed", type=int, default=20260806)
    b.add_argument("--out", default="", help="custom path to candidate testset json")
    b.add_argument("--overwrite", action="store_true", help="DANGER: invalidates existing results")
    b.add_argument("--no-verify", action="store_true", help="skip bhavcopy membership check")
    b.set_defaults(func=cmd_build_testset)

    sb = sub.add_parser("subset", help="create a deterministic subset from draft test set")
    sb.add_argument("--src", default="", help="source draft test set (default: data/testset_draft_v3.json)")
    sb.add_argument("--out", default="", help="destination test set (default: data/testset.json)")
    sb.add_argument("--per-date", type=int, default=4, help="number of cases per date to select in file order")
    sb.add_argument("--overwrite", action="store_true", help="overwrite destination if exists")
    sb.set_defaults(func=cmd_subset)

    p = sub.add_parser("recall-probe", help="locate the model's training cutoff")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--step", type=int, default=30)
    p.set_defaults(func=cmd_recall_probe)

    r = sub.add_parser("run", help="score one system")
    r.add_argument("--system", required=True)
    r.add_argument("--limit", type=int)
    r.add_argument("--nonce", default="")
    r.set_defaults(func=cmd_run)

    rs = sub.add_parser("run-staged", help="run evaluation suite with free-tier staged execution and quota pauses")
    rs.add_argument("--round", choices=["all", "1", "2", "cost"], default="all",
                    help="which stage to execute (default: all)")
    rs.add_argument("--testset", default="", help="path to test set (default: data/testset.json)")
    rs.add_argument("--limit", type=int, help="limit test cases per system (for testing)")
    rs.add_argument("--no-push", action="store_true", help="skip git commit and push after each system")
    rs.set_defaults(func=cmd_run_staged)

    a = sub.add_parser("ablate", help="Phase 4: run the whole ablation suite")
    a.add_argument("--systems", default="",
                   help="comma-separated; default is the full standard suite")
    a.add_argument("--repeats", type=int, default=1,
                   help="repeats per configuration; >1 reports variance (unique nonce each)")
    a.add_argument("--limit", type=int, help="cap the number of test cases")
    a.set_defaults(func=cmd_ablate)

    c = sub.add_parser("compare", help="score several systems side by side")
    c.add_argument("--systems",
                   default="naive-momentum,naive-alwaysup,baseline,multiagent,multiagent-nodebate")
    c.add_argument("--limit", type=int)
    c.add_argument("--nonce", default="")
    c.set_defaults(func=cmd_compare)

    pf = sub.add_parser("preflight", help="gate: pinned model, recall cutoff, data availability")
    pf.add_argument("--start", default="2024-01-01")
    pf.add_argument("--end", default="2026-09-01")
    pf.add_argument("--step", type=int, default=30)
    pf.add_argument("--path", default="", help="custom path to candidate testset json")
    pf.set_defaults(func=cmd_preflight)

    args = ap.parse_args(argv)
    enable_utf8_console()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
