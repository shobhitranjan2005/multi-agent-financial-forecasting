"""Tabulate every wrong directional forecast of one run (descriptive only; no interpretation).

Usage:  python scripts/make_failures.py results/multiagent_20261017_125750
Reads <base>.csv and writes results/failures_<name>.md. Deterministic: the "review
shortlist" is the 10 wrong forecasts with the highest stated confidence (ties: larger
absolute realised move), a rule fixed here and not tuned on anything else.
"""
import csv, collections, pathlib, sys

base = pathlib.Path(sys.argv[1])
rows = list(csv.DictReader(open(f"{base}.csv", encoding="utf-8-sig")))
wrong = [r for r in rows if r["direction_correct"] != "True"]
f = lambda r, k: float(r[k]) if r.get(k) not in ("", None) else float("nan")
ok = [r for r in rows if r["direction_correct"] == "True"]
mean = lambda xs: sum(xs) / len(xs) if xs else float("nan")
by_dir = collections.Counter(r["predicted_direction"] for r in wrong)
by_date = collections.Counter(r["as_of"] for r in wrong)
per_date_total = collections.Counter(r["as_of"] for r in rows)
wrong_sorted = sorted(wrong, key=lambda r: (-f(r, "confidence_pct"), -abs(f(r, "return_pct"))))
L = [f"# Failure tabulation: {base.name}", "",
     "Descriptive only. Interpretation of individual failures is the author's task.", "",
     f"- Forecasts: {len(rows)}; wrong direction: {len(wrong)}; right: {len(ok)}",
     f"- Wrong forecasts by predicted direction: {dict(by_dir)}",
     f"- Mean stated confidence: wrong = {mean([f(r,'confidence_pct') for r in wrong]):.1f}%, right = {mean([f(r,'confidence_pct') for r in ok]):.1f}%",
     f"- Wrong forecasts with confidence >= 65%: {sum(f(r,'confidence_pct')>=65 for r in wrong)}",
     f"- Dates (of {len(per_date_total)}) on which at least half of the cases were wrong: "
     f"{sum(by_date[d]*2>=per_date_total[d] for d in per_date_total)}", "",
     "## Review shortlist (10 most confident wrong forecasts)", "",
     "| Ticker | as_of | Predicted | Actual | Conf % | Target range | Actual close | Return % | Excess vs NIFTY % |",
     "| :--- | :--- | :---: | :---: | ---: | :--- | ---: | ---: | ---: |"]
def line(r):
    return (f"| {r['ticker']} | {r['as_of']} | {r['predicted_direction']} | {r['actual_direction']} | {f(r,'confidence_pct'):.0f} | "
            f"{f(r,'target_low'):.0f}-{f(r,'target_high'):.0f} | {f(r,'actual_close'):.1f} | {f(r,'return_pct'):+.1f} | {f(r,'excess_return_pct'):+.1f} |")
L += [line(r) for r in wrong_sorted[:10]]
L += ["", "## Wrong forecasts per date (shows clustering)", "", "| as_of | wrong / cases |", "| :--- | ---: |"]
L += [f"| {d} | {by_date.get(d,0)} / {per_date_total[d]} |" for d in sorted(per_date_total)]
L += ["", "## All wrong forecasts (confidence descending)", "",
      "| Ticker | as_of | Predicted | Actual | Conf % | Target range | Actual close | Return % | Excess vs NIFTY % |",
      "| :--- | :--- | :---: | :---: | ---: | :--- | ---: | ---: | ---: |"]
L += [line(r) for r in wrong_sorted]
out = base.parent / f"failures_{base.name}.md"
out.write_text("\n".join(L) + "\n", encoding="utf-8"); print("wrote", out, f"({len(wrong)} wrong of {len(rows)})")
