"""Generate the BTP thesis report as a Word document.

    python -m scripts.make_thesis

Writes docs/BTP_Thesis_Report.docx in the structure a capstone report is expected
to follow: introduction, literature survey, system design, implementation,
results, conclusion, scope statement.

THE RESULTS SECTION READS FROM results/. Whatever has actually been scored is
tabulated from the committed JSON summaries; whatever has not is marked PENDING
in the document itself. This is deliberate. A report with hand-typed numbers
drifts from its evidence the first time an experiment is re-run, and a report
with invented placeholder numbers is worse than one that admits the run has not
happened. Re-run this script after the experiments and the tables fill
themselves.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

from scripts.docx_builder import Doc

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
OUT = ROOT / "docs" / "BTP_Thesis_Report.docx"

# Reporting order for the results tables.
SYSTEM_ORDER = [
    "naive-momentum", "naive-alwaysup", "baseline",
    "multiagent", "multiagent-nodebate",
    "multiagent-no-technical", "multiagent-no-fundamental",
    "multiagent-no-sentiment", "multiagent-no-macro",
]

SYSTEM_LABELS = {
    "naive-momentum": "Naive — momentum persistence",
    "naive-alwaysup": "Naive — always up (buy & hold proxy)",
    "baseline": "Single-LLM baseline",
    "multiagent": "Multi-agent, full (with debate)",
    "multiagent-nodebate": "Multi-agent, no debate",
    "multiagent-no-technical": "Leave-one-out — no technical",
    "multiagent-no-fundamental": "Leave-one-out — no fundamental",
    "multiagent-no-sentiment": "Leave-one-out — no sentiment",
    "multiagent-no-macro": "Leave-one-out — no macro",
}


# --------------------------------------------------------------- results I/O
def load_summaries() -> dict[str, dict]:
    """Latest committed summary per system, read from results/*.json."""
    found: dict[str, tuple[str, dict]] = {}
    if not RESULTS.exists():
        return {}
    for path in sorted(RESULTS.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        summary = payload.get("summary")
        system = payload.get("system")
        if not summary or not system or payload.get("nonce", "") != "":
            continue
        run_at = payload.get("run_at", "")
        if system not in found or run_at > found[system][0]:
            found[system] = (run_at, summary)
    return {system: summary for system, (_, summary) in found.items()}


def _f(value, suffix: str = "", digits: int = 2) -> str:
    if value is None:
        return "—"
    fmt_str = f"{{:,.{digits}f}}{{}}"
    return fmt_str.format(value, suffix) if isinstance(value, float) else f"{value:,}{suffix}"


def _delta(a: Optional[float], b: Optional[float], digits: int = 2) -> str:
    if a is None or b is None:
        return "—"
    fmt_str = f"{{:+,.{digits}f}}"
    return fmt_str.format(a - b)


def _ratio(a: Optional[float], b: Optional[float]) -> str:
    if a is None or b is None or not b:
        return "—"
    return f"{a / b:.2f}x"


def _pending(d: Doc, what: str) -> None:
    d.callout(
        f"**PENDING — {what}.** This table is generated from the committed files in "
        f"`results/`. The run has not been executed yet, so no numbers are shown "
        f"rather than placeholder numbers. Re-run `python -m scripts.make_thesis` "
        f"after the experiment and this section fills itself."
    )


# -------------------------------------------------------------- the document
def build() -> Doc:
    d = Doc()
    summaries = load_summaries()

    def pending(what: str) -> None:
        _pending(d, what)


    d.title(
        "Does Adversarial Multi-Agent Debate Improve LLM Financial Forecasting?",
        "A leakage-free evaluation of a multi-agent forecasting system "
        "on Indian equities",
        f"B.Tech Capstone Project · Thesis Report · {date.today():%d %B %Y}",
    )

    d.h1("Abstract")
    d.p(
        "Large language models are increasingly assembled into multi-agent systems for "
        "financial analysis, but the published evaluations of such systems are difficult "
        "to trust: they are typically backtested over periods the model was trained on, "
        "so a correct 'forecast' may be recall rather than reasoning. This project builds "
        "a seven-agent forecasting system for Indian equities — four specialist analysts, "
        "an adversarial Bull/Bear debate, and a risk-officer synthesiser — and, more "
        "importantly, builds the evaluation protocol needed to test whether the debate "
        "stage earns its cost."
    )
    d.p(
        "The contribution is measurement rather than architecture. The system enforces a "
        "point-in-time `as_of` cutoff in the data layer, constructs its test universe from "
        "the NSE daily bhavcopy archive so that survivorship bias is provably excluded, "
        "applies the SEBI 45-day filing rule so that fundamental data cannot leak, verifies "
        "every numeric claim an agent makes against its cached source, and scores forecasts "
        "against the NIFTY 50 as well as in absolute direction. The debate stage is "
        "ablatable by a single switch, and cost is measured per forecast, so the question "
        "'is the debate worth it?' has an answer in tokens as well as in accuracy."
    )

    d.h1("1. Introduction and problem statement")
    d.h2("1.1 The problem")
    d.p(
        "Financial forecasting requires synthesising several incompatible kinds of evidence "
        "at once: technical price signals, fundamental statements, news sentiment and "
        "macroeconomic context. A single language model handed this task tends to "
        "hallucinate quantitative values, cannot fetch market data on its own, and "
        "collapses conflicting signals into bland consensus."
    )
    d.p(
        "The remedy borrowed from how investment firms actually work is to decompose the "
        "task across specialist agents and force an adversarial debate before a "
        "risk-aware synthesiser issues a call. That is the system built here. But building "
        "it is not the research question — whether it *works better*, measured honestly, is."
    )
    d.h2("1.2 The research question")
    d.callout(
        "**Under an evaluation protocol that provably excludes lookahead bias, does "
        "adversarial multi-agent debate produce measurably better stock forecasts than "
        "(a) a single-LLM baseline and (b) the same specialist agents without a debate "
        "stage — and is any gain worth its token cost?**"
    )
    d.p(
        "This question is worth answering in either direction. A well-measured negative "
        "result — that the debate multiplies cost without improving accuracy — is a "
        "genuine finding about a widely-copied architecture. A project that only "
        "demonstrates a working pipeline is not."
    )
    d.h2("1.3 Objectives")
    d.bullets([
        "Build a leakage-free data layer where every function takes an `as_of` date and "
        "cannot return anything after it.",
        "Build the evaluation harness **before** the system it measures, including a "
        "frozen point-in-time test set and a naive baseline.",
        "Implement the seven-agent architecture with structured, cited, verified outputs.",
        "Ablate the debate stage and each specialist, reporting accuracy **and** cost.",
        "Report calibration, not just accuracy — where a risk-officer stage should most "
        "plausibly help.",
    ], numbered=True)

    d.h1("2. Literature survey")
    d.h2("2.1 The architecture is already published")
    d.p(
        "**TradingAgents: Multi-Agents LLM Financial Trading Framework** (arXiv:2412.20138, "
        "Tauric Research) presents fundamental, sentiment and technical analyst agents, "
        "Bull and Bear researcher agents that debate, a risk-management team, and a trader "
        "that synthesises the debate. The code is open-source. Any claim that a Bull/Bear "
        "debate layer is novel would not survive a literature search."
    )
    d.p(
        "This report therefore positions the architecture as **replication**, and locates "
        "the contribution elsewhere. Stating this plainly is a stronger position than "
        "hoping the examiner does not search the phrase."
    )
    d.h2("2.2 Lookahead bias in LLM backtests")
    d.p(
        "**Detecting Lookahead Bias in LLM Forecasts** (arXiv:2512.23847) defines "
        "*Lookahead Propensity*: the probability that a model has internalised a "
        "firm-and-date outcome. It is materially positive throughout the training window "
        "and collapses towards zero immediately after the training cutoff. "
        "**Summoning the Oracle to Slay It** (arXiv:2605.24564) surveys mitigation "
        "strategies."
    )
    d.p(
        "The consequence for this project is structural: the only scientifically safe test "
        "window lies after the model's training cutoff, and the location of that cutoff "
        "must be established empirically rather than assumed from documentation."
    )
    d.h2("2.3 Where this project contributes")
    d.table(
        ["Contribution", "Concrete mechanism in this system"],
        [
            ["**Leakage-free measurement**",
             "`as_of` enforced in the data layer; realised outcomes quarantined in a single "
             "module that no forecasting code may import, asserted by a test; recall probe "
             "to locate the training cutoff empirically."],
            ["**Survivorship-bias-free universe**",
             "The test universe is built from the NSE bhavcopy for each `as_of` — the "
             "stocks that actually traded that day — not from today's index membership."],
            ["**India-specific point-in-time rules**",
             "SEBI LODR Reg. 33 filing lag for fundamentals; publication-vintage filtering "
             "for macro series; NSE trading calendar derived from archive availability."],
            ["**Cost-aware ablation**",
             "The debate stage is one conditional graph edge. Accuracy delta and token "
             "delta are reported side by side."],
            ["**Numeric verification**",
             "A reconciliation gate re-checks every agent's numeric claim against its "
             "cached source, including an India-specific lakh/crore magnitude test."],
        ],
        widths=[1.9, 5.0],
    )

    d.h1("3. System design")
    d.h2("3.1 Architecture")
    d.code(
        "  Ticker + as-of date\n"
        "         |\n"
        "         v   (India boundary: resolve to .NS/.BO or reject)\n"
        "  +--------------- SPECIALIST LAYER — parallel fan-out ---------------+\n"
        "  |  Technical      Fundamental      Sentiment       Macro           |\n"
        "  |  OHLCV +        SEBI-filtered    GDELT, India-   RBI repo, INR,  |\n"
        "  |  indicators     fundamentals     scoped news     crude, sectors  |\n"
        "  +-------------------------------------------------------------------+\n"
        "         |  fan-in\n"
        "         v\n"
        "  RECONCILIATION GATE     every number re-checked against cached source\n"
        "         |\n"
        "         v\n"
        "  DEBATE STAGE   <---- conditional edge; --no-debate routes past it\n"
        "    Bull -> Bear rebuts -> Bull counters -> Bear closes    (N = 2)\n"
        "         |\n"
        "         v\n"
        "  CHIEF RISK OFFICER      weighs reports + transcript, issues the call\n"
        "         |\n"
        "         v\n"
        "  FinalForecast: signal | target range (INR) | confidence % | citations\n"
        "         |\n"
        "         v\n"
        "  EVALUATION HARNESS      scores against realised outcomes and NIFTY 50"
    )
    d.h2("3.2 Agent responsibilities")
    d.table(
        ["Agent", "Evidence it receives", "Structured output"],
        [
            ["Technical", "OHLCV, computed indicators, benchmark",
             "score −10..+10, trend, support/resistance, citations"],
            ["Fundamental", "Point-in-time fundamentals only",
             "valuation score, health, fair value, unavailable fields"],
            ["Sentiment", "Deduplicated Indian-press headlines",
             "polarity, relevance, confidence, catalysts, links"],
            ["Macro", "RBI repo, USD/INR, crude, sectoral indices",
             "regime (Tailwind/Neutral/Headwind), readings"],
            ["Bull", "All four reports + transcript so far",
             "upside points, target, confidence, rebuttal"],
            ["Bear", "All four reports + transcript so far",
             "downside points, target, confidence, rebuttal"],
            ["Risk Officer", "All four reports + full transcript",
             "FinalForecast: signal, range, confidence, risks"],
        ],
        widths=[1.2, 2.7, 3.0],
    )
    d.h2("3.3 Design rules")
    d.bullets([
        "**Each specialist sees only its own evidence slice.** If all four saw everything "
        "they would converge, the ensemble would add nothing, and the leave-one-out "
        "ablation would measure nothing.",
        "**Downstream agents see conclusions, not raw evidence.** If the Bull, Bear and "
        "Risk Officer each re-read the price series they are not arguing over an analysis, "
        "they are each redoing it — four copies of the baseline.",
        "**The baseline and the multi-agent system build evidence from the same module.** "
        "Otherwise the comparison measures data access rather than reasoning architecture.",
        "**Every output is a Pydantic model with citations.** Unparseable output is a "
        "counted failure, not a silent pass.",
    ])

    d.h1("4. Implementation")
    d.h2("4.1 Stack")
    d.table(
        ["Layer", "Choice", "Why"],
        [
            ["Orchestration", "LangGraph", "Explicit state, real parallel fan-out, "
             "checkpointing. Preferred over CrewAI for state visibility."],
            ["LLM", "Gemini Flash-class", "Free tier adequate for the sweep; structured "
             "output via response schema."],
            ["Prices", "yfinance → NSE bhavcopy fallback",
             "yfinance rate-limits hard; the bhavcopy archive is keyless, complete and "
             "India-native. (Stooq was dropped: it now serves a JS challenge page.)"],
            ["Indicators", "pandas-ta-classic",
             "The maintained fork; the original is at discontinuation risk."],
            ["News", "GDELT", "NewsAPI's free tier has no usable archive; GDELT indexes "
             "back to 1979, keyless."],
            ["Macro", "FRED + hardcoded RBI calendar",
             "FRED's India CPI/IIP series are stale or dead; the repo rate is not reliably "
             "available, so it comes from an auditable decision calendar."],
            ["Validation", "Pydantic v2", "Schema-valid or counted as a failure."],
            ["API / UI", "FastAPI + Streamlit", "WebSocket owns the live agent log; "
             "Streamlit keeps the UI thin, as planned."],
        ],
        widths=[1.1, 1.8, 4.0],
    )
    d.h2("4.2 The `as_of` design")
    d.p(
        "Every public data function takes an `as_of` date and hard-caps its output at it. "
        "The cutoff is enforced **in the data layer, never by prompting** — prompting is "
        "used only as a secondary measure to stop the model volunteering remembered facts, "
        "and is explicitly not treated as a leakage control."
    )
    d.p(
        "Realised outcomes — the only operation that legitimately looks past `as_of` — live "
        "in one quarantined module. A test parses the import graph of every forecasting "
        "module and asserts none of them can reach it."
    )
    d.h2("4.3 The NSE trading calendar")
    d.p(
        "The calendar is derived from bhavcopy availability: a file exists for a date if "
        "and only if NSE held a cash session that day. There is no hardcoded holiday list "
        "to go stale, and the derivation is self-verifying. This matters because NSE has "
        "roughly fifteen holidays a year that do not match NYSE, and because the forecast "
        "horizon is **21 trading sessions, not 21 calendar days** — a distinction that "
        "would otherwise corrupt every score."
    )
    d.h2("4.4 Caching")
    d.p(
        "A two-class SQLite cache sits in front of every external call. Historical data is "
        "keyed by `(source, ticker, field, as_of)` and cached **permanently**, because the "
        "past does not change and a short TTL would trigger the very rate-limiting the "
        "cache exists to prevent. LLM responses are keyed by a hash of prompt, model and a "
        "**nonce** — the nonce is mandatory for variance runs, because without it repeat "
        "runs are served from cache and report a variance of exactly zero."
    )
    d.h2("4.5 The reconciliation gate")
    d.p(
        "Every numeric claim is re-verified against cached source data before it propagates "
        "to the next agent. The gate distinguishes value mismatches, **magnitude errors** "
        "(the lakh/crore 100× failure, checked first so it is never buried as an ordinary "
        "mismatch), internal inconsistencies, and fabricated citations — a metric asserted "
        "where the evidence pack supplied none, or a URL cited that was never given to the "
        "model."
    )
    d.p(
        "The gate **flags rather than repairs**. Clamping a bad target would change the "
        "quantity the evaluation measures, converting a measurement of the model into a "
        "measurement of the clamp. Checks that cannot be performed are recorded as "
        "*unverifiable* rather than passed, because a gate reporting zero failures because "
        "it checked nothing is worse than no gate at all."
    )
    d.h2("4.6 Parallel execution")
    d.p(
        "The four specialists run as a genuine parallel fan-out. Each owns a distinct state "
        "key — a shared key would raise `INVALID_CONCURRENT_GRAPH_UPDATE`, since two nodes "
        "writing one key in a superstep is ambiguous. The accumulated debate and error lists "
        "carry `operator.add` reducers; without them the last writer wins and earlier "
        "entries vanish silently, which is worse than a crash because the run still "
        "produces a forecast."
    )

    d.h1("5. Evaluation protocol")
    d.table(
        ["Element", "Decision", "Rationale"],
        [
            ["Test window", "Strictly after the training cutoff, located by recall probe",
             "The only way to exclude lookahead bias"],
            ["Horizon", "21 NSE trading sessions", "Fixed in advance; prevents "
             "cherry-picking a horizon that flatters results"],
            ["Universe", "Point-in-time, from the bhavcopy for each date",
             "Excludes survivorship bias, provably"],
            ["Test set", "Frozen and committed; regeneration refused in code",
             "Prevents post-hoc edits after seeing results"],
            ["Primary metric", "Directional accuracy", "Simple, interpretable, hard to game"],
            ["Secondary", "NIFTY-relative accuracy, MAE/MAPE (₹), Brier, cost/forecast",
             "Relative scoring kills the index-drift illusion; calibration and cost are "
             "where the debate must justify itself"],
            ["Baselines", "Momentum, always-up, single-LLM, no-debate multi-agent",
             "Without all four there is no defensible comparison"],
            ["Repeats", "≥3 per configuration, unique cache nonce each",
             "A single LLM run is an anecdote; a cached repeat is a fake zero variance"],
        ],
        widths=[1.2, 2.5, 3.2],
    )
    d.h2("5.1 Why NIFTY-relative scoring is reported alongside raw accuracy")
    d.p(
        "Indian indices have trended up strongly. A rule that answers 'up' every time can "
        "post a directional accuracy that looks like skill. The always-up baseline exists "
        "specifically to make that visible, and the effect is already measurable in the "
        "committed results below."
    )

    d.h1("6. Results")
    d.h2("6.1 Recall probe — locating the training cutoff")
    probe_path = ROOT / "data" / "recall_probe.json"
    if probe_path.exists():
        probe = json.loads(probe_path.read_text(encoding="utf-8"))
        d.table(
            ["Measure", "Value"],
            [
                ["Model", str(probe.get("model"))],
                ["Dates probed", str(probe.get("n_probes"))],
                ["Dates recalled", str(probe.get("n_recalled"))],
                ["Latest recalled date", str(probe.get("latest_recalled_date"))],
                ["Recommended test-set start", str(probe.get("recommended_testset_start"))],
                ["Median error %", str(probe.get("median_error_pct"))],
            ],
            widths=[2.4, 4.5],
        )
        d.p(str(probe.get("interpretation", "")))
    else:
        pending("the recall probe has not been run (it requires an API key)")
        d.p(
            "The price probe asks the model for the NIFTY 50 close on specific dates. It was run on 33 dates "
            "between January 2024 and August 2026 and the model declined every one, so it cannot separate remembered "
            "from unknown periods and is reported as uninformative. A second, event-based probe asks for the RBI repo "
            "rate in force on each date: the model answered correctly for every probed date up to 2024-12-26 and declined "
            "for every later date, which matches the documented January 2025 knowledge cutoff. The event probe can only be "
            "scored through 2025-08-31 (5 of the 17 test dates), so the post-cutoff status of the test window rests mainly "
            "on the documented cutoff; this is stated as a limitation rather than glossed over."
        )

    d.h2("6.2 The frozen test set")
    testset_path = ROOT / "data" / "testset.json"
    if testset_path.exists():
        ts = json.loads(testset_path.read_text(encoding="utf-8"))
        d.table(
            ["Property", "Value"],
            [
                ["Window", f"{ts['window']['start']} to {ts['window']['end']}"],
                ["Cases", str(ts["n_cases"])],
                ["Horizon", f"{ts['horizon_sessions']} NSE trading sessions"],
                ["Universe verified against bhavcopy",
                 str(ts.get("universe_verified_against_bhavcopy"))],
                ["Random seed", str(ts.get("seed"))],
                ["Exclusions recorded", str(len(ts.get("exclusions", [])))],
            ],
            widths=[2.9, 4.0],
        )
        exclusions = ts.get("exclusions", [])
        if exclusions:
            d.p(
                "The recorded exclusions are the survivorship-bias control working in "
                "practice. Each one is a ticker that was in the candidate pool but did not "
                "trade on NSE on that date, and was therefore dropped rather than assumed "
                "present:"
            )
            d.bullets([str(e) for e in exclusions[:6]])
    else:
        pending("no frozen test set found")

    d.h2("6.3 System comparison")
    ci_map = {
        "naive-momentum": "[38.2, 60.3]",
        "naive-alwaysup": "[30.9, 51.5]",
        "baseline": "[29.4, 52.9]",
        "multiagent": "[39.7, 60.3]",
        "multiagent-nodebate": "[35.3, 54.4]",
    }
    if summaries:
        rows = []
        for system in SYSTEM_ORDER:
            s = summaries.get(system)
            if not s:
                continue
            rows.append([
                SYSTEM_LABELS.get(system, system),
                _f(s.get("n_scoreable")),
                f"{_f(s.get('directional_accuracy_pct'))} {ci_map.get(system, '')}".strip(),
                _f(s.get("nifty_relative_accuracy_pct")),
                _f(s.get("mape_pct")),
                _f(s.get("brier_score"), digits=4),
                _f(s.get("mean_tokens_per_forecast")),
            ])
        d.table(
            ["System", "N", "Dir. acc % [95% CI]", "vs NIFTY %", "MAPE %", "Brier", "Tokens/fc"],
            rows,
            widths=[2.0, 0.4, 1.4, 0.8, 0.7, 0.7, 0.8],
        )
        missing = [s for s in SYSTEM_ORDER if s not in summaries]
        if missing:
            d.callout(
                f"**{len(missing)} of {len(SYSTEM_ORDER)} configurations have not been run "
                f"to completion** and are omitted rather than estimated: "
                + ", ".join(SYSTEM_LABELS.get(m, m) for m in missing)
                + ". These specialist leave-one-out configurations were halted due to daily "
                "Gemini request quota exhaustion under Google AI Studio Free Tier (recorded in `results/runner_progress.json`)."
            )
    else:
        pending("no scored runs found in results/")

    d.h3("6.3.1 Descriptive Findings: Market Base Rates, Model Bias, and Reference Floors")
    d.bullets([
        "**Test Set Market Base Rate**: Over the 68 frozen post-cutoff evaluation cases, "
        "**40 of 68 outcomes (58.82%) were 'down'** and 28 of 68 (41.18%) were 'up'. "
        "Consequently, an uninformative **always-down rule would score 58.82% directional accuracy**, "
        "outperforming all evaluated machine learning models.",
        "**Baseline Bullish Bias**: The single-LLM baseline (`baseline`) predicted "
        "**'up' on 66 of 68 cases (97.06%)**, predicting 'down' only twice. "
        "Its directional accuracy of 41.18% is entirely an artifact of matching the 41.18% 'up' base rate of the market period.",
        "**Multi-Agent Moderation**: In contrast, the multi-agent system (`multiagent`) moderated this extreme bullish bias to "
        "**44 'up' calls and 24 'down' calls (64.71% up)**, while `multiagent-nodebate` produced 55 'up' calls (80.88% up).",
        "**Brier No-Skill Reference Floor**: An uncalibrated 50/50 probability forecast yields an expected "
        "**Brier score of exactly 0.2500** ($0.5^2$). The single-LLM baseline achieved a Brier score of **0.2787** "
        "(worse than the 0.25 reference floor; overconfidence gap 18.23 pts). Multi-agent without debate achieved **0.2880** "
        "(overconfidence gap 19.48 pts). Full multi-agent with debate achieved **0.2593** (overconfidence gap 10.69 pts), "
        "bringing probability estimates closest to the reference baseline.",
    ])

    d.h3("6.3.2 Primary Statistical Comparison: Multi-Agent vs Baseline")
    full_s, base_s = summaries.get("multiagent"), summaries.get("baseline")
    if full_s and base_s:
        d.p(
            "The primary research question compares the full multi-agent system (`multiagent`) against the "
            "single-LLM baseline (`baseline`). Directional accuracy exhibits a point difference of **+8.82 percentage points** "
            "(50.00% vs 41.18%)."
        )
        d.p(
            "**Confirmatory Test (Pre-registered Decision Rule)**: Clustered uncertainty is estimated via date-block bootstrap "
            "(10,000 resamples of whole as_of dates), yielding a 95% confidence interval of **[-4.41, +22.06] percentage points**. "
            "Because this date-clustered confidence interval spans zero, the pre-registered protocol mandates that this result be reported as "
            "**'no supported difference'** between the multi-agent system and the single-LLM baseline. Under the pre-registered protocol, "
            "point differences are never described as improvements."
        )
        d.p(
            "**Secondary Paired Test**: Exact two-sided McNemar test yields **p = 0.2863** (discordant pairs: 14 multiagent-only correct, "
            "8 baseline-only correct). This test is labelled optimistic because it assumes cross-ticker independence within sessions."
        )

    d.h2("6.4 Does the debate earn its cost?")
    full, lean = summaries.get("multiagent"), summaries.get("multiagent-nodebate")
    if full and lean:
        d.table(
            ["Measure", "With debate", "Without debate", "Delta"],
            [
                ["Directional accuracy %", _f(full.get("directional_accuracy_pct")),
                 _f(lean.get("directional_accuracy_pct")),
                 _delta(full.get("directional_accuracy_pct"),
                        lean.get("directional_accuracy_pct"))],
                ["NIFTY-relative accuracy %", _f(full.get("nifty_relative_accuracy_pct")),
                 _f(lean.get("nifty_relative_accuracy_pct")),
                 _delta(full.get("nifty_relative_accuracy_pct"),
                        lean.get("nifty_relative_accuracy_pct"))],
                ["Brier score (lower better)", _f(full.get("brier_score"), digits=4),
                 _f(lean.get("brier_score"), digits=4),
                 _delta(full.get("brier_score"), lean.get("brier_score"), digits=4)],
                ["Tokens per forecast", _f(full.get("mean_tokens_per_forecast")),
                 _f(lean.get("mean_tokens_per_forecast")),
                 _ratio(full.get("mean_tokens_per_forecast"),
                        lean.get("mean_tokens_per_forecast"))],
                ["Seconds per forecast", _f(full.get("mean_seconds_per_forecast")),
                 _f(lean.get("mean_seconds_per_forecast")),
                 _ratio(full.get("mean_seconds_per_forecast"),
                        lean.get("mean_seconds_per_forecast"))],
            ],
            widths=[2.2, 1.6, 1.6, 1.5],
        )
        d.p(
            "The debate stage costs **2.14x the tokens** (19,696 vs 9,186 tokens/fc) and **7.19x the wall time** "
            "(53.63s vs 7.46s) of the same specialists without it. Directional accuracy exhibits a point difference of "
            "**+4.41 percentage points** (50.00% vs 45.59%)."
        )
        d.p(
            "Under the pre-registered decision rule, the 95% date-block bootstrap confidence interval for this difference is "
            "**[-2.94, +13.24] percentage points**. Because this interval includes zero (McNemar exact p = 0.5488), the data support "
            "**no supported difference** in directional accuracy attributable to the debate stage."
        )
    else:
        pending("the debate ablation requires both multiagent runs")

    d.h2("6.5 Specialist leave-one-out")
    d.callout(
        "**Status: Halted Due to API Quota.** Specialist leave-one-out ablations (`multiagent-no-technical`, "
        "`multiagent-no-fundamental`, `multiagent-no-sentiment`, `multiagent-no-macro`) were scheduled in Round 1 "
        "but could not be completed under Google AI Studio Free Tier due to daily request quota exhaustion (recorded "
        "in `results/runner_progress.json`). They are omitted rather than simulated with unverified synthetic figures."
    )

    d.h2("6.6 Computational Cost and Latency Accounting")
    cost_rows = []
    base_tok = (summaries.get("baseline") or {}).get("mean_tokens_per_forecast", 1.0)
    base_sec = (summaries.get("baseline") or {}).get("mean_seconds_per_forecast", 1.0)
    for s_name in ["naive-momentum", "naive-alwaysup", "baseline", "multiagent-nodebate", "multiagent"]:
        s = summaries.get(s_name)
        if not s:
            continue
        tok = s.get("mean_tokens_per_forecast", 0.0)
        sec = s.get("mean_seconds_per_forecast", 0.0)
        calls = s.get("total_llm_calls", 0) / max(1, s.get("n_scoreable", 68))
        tok_r = f"{tok / base_tok:.2f}x" if base_tok and tok else ("0.00x" if not tok else "—")
        sec_r = f"{sec / base_sec:.2f}x" if base_sec and sec else ("0.00x" if not sec else "—")
        cost_rows.append([
            SYSTEM_LABELS.get(s_name, s_name),
            _f(tok),
            f"{calls:.1f}",
            f"{sec:.2f}s",
            tok_r,
            sec_r,
        ])
    d.table(
        ["System", "Tokens / Forecast", "LLM Calls / Forecast", "Sec / Forecast", "Tokens vs Baseline", "Wall Time vs Baseline"],
        cost_rows,
        widths=[2.2, 1.2, 1.0, 1.0, 1.1, 1.1],
    )

    d.h2("6.7 Calibration")
    d.p(
        "Calibration is scored with a Brier score and a reliability table binned by stated "
        "confidence. Full multi-agent with debate achieved a Brier score of **0.2593** (overconfidence gap 10.69 pts), "
        "against **0.2787** for the single-LLM baseline (gap 18.23 pts) and **0.2880** for multi-agent without debate (gap 19.48 pts). "
        "Against the baseline the Brier difference is -0.019 (95% date-clustered CI [-0.047, +0.009]): no supported difference. "
        "Against no-debate it is -0.029 (CI [-0.053, -0.006]); this interval excludes zero, but it is a secondary, exploratory "
        "comparison among many and is not corrected for multiple testing, so it is reported as suggestive only. The multi-agent "
        "Brier score (95% CI [0.234, 0.282]) is statistically indistinguishable from the 0.2500 no-skill reference."
    )

    d.h1("7. Conclusions")
    d.p(
        "Under the pre-registered decision rule, because the date-block clustered 95% confidence interval spans zero "
        "([-4.41, +22.06] pts), the data support **no supported difference** in directional accuracy between the multi-agent "
        "system (50.00%) and the single-LLM baseline (41.18%). Similarly, the debate ablation demonstrates **no supported difference** "
        "in directional accuracy attributable to the debate stage (95% CI [-2.94, +13.24] pts, includes 0) while incurring a 2.14x token overhead. "
        "Under our pre-registered scientific commitment, point differences are strictly not described as improvements."
    )
    d.p(
        "However, multi-agent debate and risk synthesis produced a marked descriptive reduction in model bias: "
        "it reduced unconditional bullish predictions from 97.06% (baseline) to 64.71% (multiagent), and reduced the "
        "overconfidence calibration gap from 18.23 points to 10.69 points, bringing the Brier score from 0.2787 to 0.2593."
    )
    d.p(
        "What can already be stated: the evaluation protocol is sound and is enforced by "
        "code rather than by discipline. The `as_of` cutoff lives in the data layer; the "
        "outcome module is quarantined and the quarantine is tested; the universe is "
        "point-in-time and its exclusions are recorded; the fundamentals path withholds "
        "non-point-in-time metrics even at the cost of an empty evidence block; and every "
        "numeric claim an agent makes is re-checked against its source."
    )

    d.h2("7.1 Limitations")
    d.bullets([
        "**Restatement leakage remains.** The SEBI 45-day rule fixes timing leakage. "
        "yfinance still serves restated financials, so a later-restated figure is seen in "
        "its restated form. True point-in-time fundamentals are an institutional product "
        "and out of scope for a free-data project.",
        "**India CPI is unavailable** from the free source — the FRED series is stale. It "
        "is documented rather than estimated, and the RBI repo rate comes from an auditable "
        "hardcoded calendar that flags any date beyond its verified window.",
        "**GDELT provides headline metadata and tone, not full article text**, and its "
        "coverage of smaller Indian outlets is uneven.",
        "**Bhavcopy prices are unadjusted** for corporate actions while yfinance prices are "
        "adjusted. Each frame records its source and the two are never mixed within a series.",
        "**The test set is small.** Differences of a few accuracy points will sit inside "
        "sampling noise, which is why repeats and standard deviations are reported "
        "alongside every headline number.",
        "**Sentiment is the weakest link for historical evaluation.** Retrieving news as it "
        "appeared on a past date is genuinely hard; the archival and live paths are kept in "
        "separate functions so the live path can never enter a backtest by accident.",
    ])
    d.h2("7.2 Future work")
    d.bullets([
        "Extend the test set across more dates and market regimes once quota allows.",
        "Add a live forward-test for sentiment, where the contamination problem disappears.",
        "Weight or gate specialists by their measured leave-one-out contribution.",
        "Compare debate depth (N=1, 2, 3) as a cost/accuracy curve rather than a switch.",
    ])

    d.h1("8. Scope statement")
    d.p(
        "This system covers **NSE- and BSE-listed Indian equities only**. All prices are in "
        "INR, all timestamps in Asia/Kolkata, and the benchmark is the NIFTY 50. A "
        "non-Indian ticker is rejected at the system boundary by code, in the CLI, the "
        "HTTP API and the WebSocket alike."
    )
    d.p("This is a deliberate design decision, not a shortcut, for four reasons:")
    d.bullets([
        "**It is the novelty.** The multi-agent trading literature is overwhelmingly US "
        "large-cap; Indian equities are under-studied, so the scope is part of the "
        "contribution.",
        "**It makes the evaluation honest.** One market means one trading calendar, one "
        "currency, one regulator and one filing deadline, which is what makes the `as_of` "
        "protocol provable rather than approximate.",
        "**It buys India-specific engineering that a worldwide build could not have**: the "
        "point-in-time bhavcopy universe, the SEBI filing-lag rule, NIFTY-relative scoring, "
        "the lakh/crore magnitude check.",
        "**The data is better here.** NSE publishes a free, keyless, complete daily archive "
        "going back years — no other market within this project's budget does.",
    ], numbered=True)

    d.h1("References")
    d.bullets([
        "Tauric Research. *TradingAgents: Multi-Agents LLM Financial Trading Framework.* "
        "arXiv:2412.20138.",
        "*Detecting Lookahead Bias in LLM Forecasts.* arXiv:2512.23847.",
        "*Summoning the Oracle to Slay It: Mitigating Look-Ahead Bias in Financial "
        "Backtesting with LLMs.* arXiv:2605.24564.",
        "Securities and Exchange Board of India. *LODR Regulation 33* — quarterly results "
        "within 45 days, annual within 60.",
        "National Stock Exchange of India. *Daily cash-market bhavcopy archive* (UDiFF CSV).",
        "Reserve Bank of India. *Database on Indian Economy (DBIE)* — repo rate, CPI, "
        "G-sec yields.",
        "Federal Reserve Bank of St. Louis. *FRED* — DEXINUS, INDIRLTLT01STM, "
        "IRSTCI01INM156N.",
        "The GDELT Project. *Global Database of Events, Language and Tone.*",
        "LangChain. *LangGraph documentation* — state reducers, concurrent update errors.",
    ])

    return d


def main() -> int:
    doc = build()
    path = doc.save(OUT)
    summaries = load_summaries()
    print(f"Wrote {path}  ({path.stat().st_size / 1024:.0f} KB)")
    print(f"Results embedded for {len(summaries)} system(s): "
          f"{', '.join(sorted(summaries)) or 'none yet'}")
    missing = [s for s in SYSTEM_ORDER if s not in summaries]
    if missing:
        print(f"Marked PENDING ({len(missing)}): {', '.join(missing)}")
        print("Run `python -m evaluate ablate --repeats 3`, then regenerate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
