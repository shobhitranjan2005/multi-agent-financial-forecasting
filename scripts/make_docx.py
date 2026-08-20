"""Generate the project engineering report as a Word document.

    python -m scripts.make_docx

Writes docs/BTP_Engineering_Report.docx — a self-contained explanation of what
the project is, why it is designed the way it is, and what was actually built.
Written for a reader who has never seen the repository: a guide, an examiner, or
a teammate joining late.

The companion document is the thesis report (scripts/make_thesis.py). This one is
the engineering record; that one is the academic write-up.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from scripts.docx_builder import Doc

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "BTP_Engineering_Report.docx"


# ---------------------------------------------------------------- the report
def build() -> Doc:
    d = Doc()

    d.title(
        "Financial Forecasting by a Multi-Agent AI System",
        "Does adversarial multi-agent debate improve LLM stock forecasting? "
        "A leakage-free evaluation on Indian equities",
        f"B.Tech Capstone Project (BTP) · Engineering Report · {date.today():%d %B %Y}",
    )

    d.h1("1. What this project is")
    d.p(
        "This project builds an autonomous multi-agent AI system that forecasts the "
        "direction and price range of Indian equities, and — more importantly — it builds "
        "the measuring instrument needed to find out whether the multi-agent machinery "
        "actually helps."
    )
    d.p(
        "Four specialist AI agents (technical, fundamental, sentiment, macro) analyse a "
        "stock in parallel. Their conclusions are re-checked against source data, then fed "
        "into a structured **Bull vs Bear debate**. A Chief Risk Officer agent reads the "
        "reports and the debate and issues the final call: a signal, a price range in "
        "rupees, a confidence figure and citations."
    )
    d.h2("The research question")
    d.callout(
        "**Under an evaluation protocol that provably excludes lookahead bias, does "
        "adversarial multi-agent debate produce measurably better forecasts than (a) a "
        "single-LLM baseline and (b) the same specialists without a debate stage — and is "
        "any gain worth its token cost?**"
    )
    d.h2("Why the question matters more than the system")
    d.p(
        "The architecture itself is not novel and the report says so plainly. Specialist "
        "agents plus a Bull/Bear debate plus risk synthesis is already published as "
        "**TradingAgents (arXiv:2412.20138)**, with open-source code. Claiming the debate "
        "layer as a contribution would not survive a literature review — a supervisor who "
        "searches the phrase finds that paper immediately."
    )
    d.p("So the contribution is deliberately relocated from architecture to measurement:")
    d.bullets([
        "**Most multi-agent finance results leak the answer.** A language model has "
        "already read what happened to a stock in 2023. Backtesting inside the training "
        "window measures memory, not forecasting.",
        "**Almost nobody measures whether the debate earns its cost.** It roughly doubles "
        "the number of model calls. Does accuracy improve, or does it just produce more "
        "confident-sounding text?",
        "**Indian equities are under-studied** in this literature, which is overwhelmingly "
        "US large-cap.",
    ])
    d.p(
        "This question is worth answering **either way**. A well-measured negative result — "
        "'the debate costs 2.4x the tokens for no accuracy gain' — is a genuine, defensible "
        "finding. A project that merely demonstrates a working pipeline is not."
    )

    d.h1("2. Scope: Indian equities only, and why that is a choice")
    d.p(
        "The system covers **NSE (.NS) primary and BSE (.BO) secondary** listings only. All "
        "prices in **INR**, all timestamps in **Asia/Kolkata**, benchmark **NIFTY 50**. A "
        "non-Indian ticker is rejected by code at the system boundary, not by convention."
    )
    d.table(
        ["Reason", "What it buys the project"],
        [
            ["**It is the novelty.**",
             "The published literature is US-large-cap. Indian equities are under-studied, "
             "so the scope *is* part of the contribution."],
            ["**It makes the evaluation honest.**",
             "One market means one trading calendar, one currency, one regulator, one "
             "filing deadline. The point-in-time protocol becomes provable rather than "
             "approximate. A worldwide claim would need per-market holiday calendars, FX "
             "conversion and per-regulator disclosure timing."],
            ["**It buys India-specific engineering.**",
             "Point-in-time universe from NSE bhavcopy (kills survivorship bias), SEBI "
             "filing-date lag (kills fundamental leakage), NIFTY-relative scoring (kills "
             "the index-drift illusion). None of these exist in a 'worldwide' build."],
            ["**The data is better here.**",
             "NSE publishes a free, keyless, complete daily archive going back years. No "
             "other market within this project's budget offers that."],
        ],
        widths=[2.0, 4.9],
    )

    d.h1("3. The two problems that shaped the design")
    d.h2("Problem 1 — Lookahead bias makes naive backtesting invalid")
    d.p(
        "The obvious plan is: 'test a forecast made three months ago against what actually "
        "happened.' This does not work. The model's weights already encode what happened "
        "three months ago. It is a documented, measurable effect — **arXiv:2512.23847** "
        "defines *Lookahead Propensity*, which is materially positive throughout the "
        "training window and collapses to near zero immediately after the training cutoff."
    )
    d.p(
        "**Implication:** the only scientifically safe test window is after the model's "
        "training cutoff. This constrains the entire project, so it had to be decided "
        "early rather than discovered at the end."
    )
    d.h2("Problem 2 — Building the system before the ruler guarantees late failure")
    d.p(
        "A conventional plan builds the system for ten weeks and evaluates it last. Two "
        "consequences: if the evaluation turns out to be invalid there is no time left to "
        "fix it; and the claim 'multi-agent beats a single LLM' is impossible unless the "
        "single-LLM baseline exists first."
    )
    d.callout(
        "**The governing rule of this build: construct the measuring instrument before the "
        "thing being measured.** Evaluation is Phase 2, not Phase 5. The single-LLM "
        "baseline ships in Phase 1."
    )

    d.h1("4. System architecture")
    d.code(
        "  Ticker + as-of date\n"
        "         |\n"
        "         v\n"
        "  +--------------- SPECIALIST LAYER (runs in PARALLEL) ---------------+\n"
        "  |  Technical      Fundamental      Sentiment        Macro          |\n"
        "  |  price/momentum valuation/health Indian press     RBI/INR/crude  |\n"
        "  +-------------------------------------------------------------------+\n"
        "         |\n"
        "         v\n"
        "  RECONCILIATION GATE      every number re-checked against source data\n"
        "         |\n"
        "         v\n"
        "  DEBATE STAGE  <---- ABLATABLE (--no-debate routes straight past it)\n"
        "     Bull -> Bear rebuts -> Bull counters -> Bear closes   (2 rounds)\n"
        "         |\n"
        "         v\n"
        "  CHIEF RISK OFFICER       weighs evidence, issues the final forecast\n"
        "         |\n"
        "         v\n"
        "  Structured forecast: signal | target range | confidence | citations\n"
        "         |\n"
        "         v\n"
        "  EVALUATION HARNESS       leakage-free scoring against real outcomes"
    )
    d.h2("The seven agents")
    d.table(
        ["#", "Agent", "Sees", "Produces"],
        [
            ["1", "**Technical**", "OHLCV prices, computed indicators, benchmark",
             "score −10..+10, trend, support/resistance, citations"],
            ["2", "**Fundamental**", "Point-in-time fundamentals only (SEBI-filtered)",
             "valuation score, health rating, fair value, unavailable fields"],
            ["3", "**Sentiment**", "Deduplicated Indian-press headlines",
             "polarity, relevance, confidence, catalysts, article links"],
            ["4", "**Macro**", "RBI repo, USD/INR, crude, NIFTY sectoral indices",
             "regime (Tailwind/Neutral/Headwind), readings"],
            ["5", "**Bull**", "All four reports + transcript so far",
             "upside case, points, target, confidence"],
            ["6", "**Bear**", "All four reports + transcript so far",
             "downside case, points, target, confidence"],
            ["7", "**Risk Officer**", "All four reports + full debate transcript",
             "**FinalForecast**: signal, target range, confidence %, risks"],
        ],
        widths=[0.3, 1.3, 2.5, 2.8],
    )
    d.h2("Rules that apply to every agent")
    d.bullets([
        "Output is a **Pydantic model**, never free text. Unparseable output is a counted "
        "failure, not a silent pass.",
        "Every numeric claim carries a **citation** to the exact data point it came from.",
        "Every agent receives the **as_of date** and may never see data after it — enforced "
        "in the data layer, not by prompting.",
        "Each specialist sees **only its own evidence slice**. If all four saw everything "
        "they would converge on the same answer and the ensemble would add nothing, making "
        "the leave-one-out ablation meaningless.",
    ])

    d.page_break()
    d.h1("5. What was built, phase by phase")
    d.p(
        "Five phases, ordered so that risk is retired early. Each has an objective exit "
        "gate. The table below is the current state of the build."
    )
    d.table(
        ["Phase", "Goal", "Status"],
        [
            ["**1**", "Foundation & walking skeleton + single-LLM baseline", "**Complete**"],
            ["**2**", "Data layer with time-travel + leakage-free evaluation harness",
             "**Complete** (recall probe awaits an API key)"],
            ["**3**", "Multi-agent system: specialists, reconciliation, debate, synthesis",
             "**Complete** (verified end-to-end against a stubbed model)"],
            ["**4**", "Experiments & ablation tooling",
             "**Tooling complete**; scored runs await an API key"],
            ["**5**", "API, dashboard, report & slides", "**Complete**"],
        ],
        widths=[0.6, 3.9, 2.4],
    )

    d.h2("Phase 1 — Foundation & walking skeleton")
    d.p("One command produces one real, schema-valid forecast: thin, but complete end to end.")
    d.table(
        ["File", "What it does"],
        [
            ["`backend/config.py`", "Central configuration and the India constants: NIFTY 50 "
             "benchmark, 21-session horizon, SEBI filing lag, bhavcopy URL, sectoral indices."],
            ["`backend/cache.py`", "Two-class SQLite cache in front of every external call "
             "(see §6.2)."],
            ["`backend/llm.py`", "The single Gemini gateway: structured output, caching, "
             "cost accounting, counted parse failures."],
            ["`backend/context.py`", "Assembles the evidence pack. **Both** the baseline and "
             "the multi-agent system build their evidence here, so the comparison isolates "
             "reasoning architecture rather than data access."],
            ["`backend/baseline.py`", "The single-LLM baseline — one call, same evidence, "
             "same output schema. The thing the multi-agent system must beat."],
            ["`backend/agents/technical.py`", "The first specialist, built as the template "
             "the other three copy."],
            ["`forecast.py`", "The CLI."],
        ],
        widths=[2.0, 4.9],
    )

    d.h2("Phase 2 — Data layer & the leakage-free evaluation harness")
    d.p(
        "The academic core. Every data function takes an `as_of` date and cannot return "
        "anything after it; then the harness that scores forecasts is built on top."
    )
    d.h3("Data tools")
    d.table(
        ["File", "What it does"],
        [
            ["`tools/tickers.py`", "**The India boundary.** Resolves a symbol to .NS/.BO or "
             "raises. Membership is checked against the real NSE symbol master — a regex "
             "alone would happily turn AAPL into AAPL.NS."],
            ["`tools/calendar_nse.py`", "NSE trading calendar derived from bhavcopy "
             "availability: a file exists for a date **if and only if** NSE traded that day. "
             "No hardcoded holiday list to go stale, and it is self-verifying."],
            ["`tools/market_data.py`", "OHLCV with a hard `as_of` cap, yfinance primary and "
             "an NSE bhavcopy fallback. Each frame records which source served it, because "
             "adjusted and unadjusted prices must never mix within one series."],
            ["`tools/indicators.py`", "RSI, MACD, SMA 50/200, Bollinger, ATR, realised "
             "volatility — with plain-English readings and short-series safety."],
            ["`tools/fundamentals.py`", "Point-in-time fundamentals under the SEBI 45-day "
             "filing rule (see §6.4)."],
            ["`tools/news_sentiment.py`", "GDELT, scoped to India, `as_of`-filtered, "
             "deduplicated. Handles GDELT's rate-limit-as-HTTP-200 trap (see §6.5)."],
            ["`tools/macro.py`", "RBI repo rate, USD/INR, 10Y G-sec, crude, NIFTY sectoral "
             "indices — all filtered by **publication** date, not observation date."],
        ],
        widths=[1.9, 5.0],
    )
    d.h3("The evaluation harness")
    d.table(
        ["File", "What it does"],
        [
            ["`eval/testset.py`", "Builds and **freezes** the test set. Refuses to overwrite "
             "an existing one, because regenerating it after results exist would invalidate "
             "every comparison made against the old one."],
            ["`eval/outcomes.py`", "The **only** module allowed to look past `as_of`. "
             "Quarantined deliberately, and a test asserts no forecasting module imports it."],
            ["`eval/metrics.py`", "Directional accuracy, NIFTY-relative accuracy, MAE/MAPE "
             "in rupees, Brier score, reliability table, cost per forecast."],
            ["`eval/naive.py`", "Two non-LLM baselines: momentum persistence, and "
             "'always up' — the buy-and-hold proxy that exposes how flattering raw "
             "directional accuracy is."],
            ["`eval/recall_probe.py`", "Asks the model for hard, verifiable market facts on "
             "specific dates and compares them to ground truth, to locate the training "
             "cutoff empirically."],
            ["`eval/harness.py`", "Runs **any** forecaster over the frozen set and scores it. "
             "Knows nothing about which system produced a forecast — that is what makes the "
             "Phase 4 ablations one-liners instead of new code paths."],
        ],
        widths=[1.9, 5.0],
    )

    d.h2("Phase 3 — The multi-agent system")
    d.table(
        ["File", "What it does"],
        [
            ["`agents/schemas.py`", "Every agent's output schema, flat and with pinned field "
             "order to work around Gemini's structured-output constraints."],
            ["`agents/base.py`", "The shared specialist runner. All four specialists are the "
             "same shape by construction, so the leave-one-out ablation drops an agent by "
             "not calling it — never by editing agent code."],
            ["`agents/fundamental.py`, `sentiment.py`, `macro.py`", "The three remaining "
             "specialists, each exposing the same `analyse(ctx)` signature."],
            ["`agents/reconciliation.py`", "**The anti-hallucination gate** (see §6.7)."],
            ["`agents/debate.py`", "The bounded Bull/Bear exchange: 2 rounds, 4 turns, both "
             "sides seeing identical evidence."],
            ["`agents/risk_officer.py`", "The synthesiser that issues the final call."],
            ["`graph/state.py`", "The LangGraph state: distinct keys per specialist, "
             "reducers on the accumulated lists (see §6.8)."],
            ["`graph/pipeline.py`", "The orchestrator: parallel fan-out, fan-in, the "
             "conditional debate edge, the SQLite checkpointer."],
        ],
        widths=[2.2, 4.7],
    )

    d.h2("Phase 4 — Experiment tooling")
    d.p(
        "`backend/eval/ablation.py` plus `python -m evaluate ablate` runs the whole suite — "
        "naive baselines, single-LLM baseline, full multi-agent, no-debate, and four "
        "leave-one-out configurations — with repeats, and writes one report answering the "
        "three questions the project asked. Every row traces to a CSV and JSON file written "
        "at run time."
    )
    d.p(
        "Ablations are **system names, not code paths**: `multiagent-nodebate`, "
        "`multiagent-no-sentiment`, `multiagent-no-macro-technical`. Adding a new ablation "
        "requires no new code."
    )

    d.h2("Phase 5 — API, dashboard, report and slides")
    d.table(
        ["File", "What it does"],
        [
            ["`backend/api/main.py`", "FastAPI: health, price, evidence, forecast, and a "
             "**WebSocket** that streams each stage as it lands. The WebSocket owns the "
             "live UX because a 30-90 second POST times out on many proxies."],
            ["`backend/graph/pipeline.py` (`stream`)", "Yields a progress event per "
             "completed stage, derived from LangGraph's own update stream so the log "
             "cannot drift out of step with what the graph actually did."],
            ["`frontend/app.py`", "Streamlit dashboard: evidence pack, candlestick chart "
             "with SMA overlays, live agent log, Bull-vs-Bear split view, forecast card, "
             "and the reconciliation gate shown deliberately."],
            ["`scripts/make_thesis.py`", "Generates the thesis report, reading real numbers "
             "from `results/` and marking anything unrun as PENDING rather than inventing "
             "a placeholder."],
            ["`scripts/make_slides.py`", "Generates 20 defence slides with speaker notes, "
             "also reading from `results/`."],
            ["`scripts/warm_demo.py`", "Pre-warms the demo runs and then **verifies** that "
             "a replay makes zero fresh API calls."],
        ],
        widths=[2.2, 4.7],
    )
    d.h3("Security posture at the API boundary")
    d.bullets([
        "**The India boundary is enforced here too**, with the same error text the CLI "
        "uses, over HTTP and over the WebSocket. A boundary that holds in one entry point "
        "and not another is not a boundary.",
        "**CORS is an explicit allowlist**, never `allow_origins=['*']` — with credentials "
        "enabled that is an open door, and naming the two origins costs nothing.",
        "**Per-IP rate limiting**, tighter on forecast endpoints because those spend real "
        "quota. It is in-process and documented as protecting a single-node demo rather "
        "than as a substitute for a gateway.",
        "**No secret crosses the boundary.** `/api/health` reports whether a key is "
        "configured, never any part of it, and a test asserts the response body contains "
        "no key-like string.",
    ])

    d.page_break()
    d.h1("6. The engineering that constitutes the contribution")
    d.p(
        "This section is the heart of the project. Each item below is a specific way that "
        "a naive implementation would silently produce invalid results, and the concrete "
        "mechanism used to prevent it."
    )

    d.h2("6.1  Every data function takes an `as_of` date")
    d.p(
        "The cutoff is enforced in the data layer, so no agent, prompt or tool can see past "
        "it even by accident. Prompting a model to 'ignore what you know after this date' "
        "is not a leakage control and is never treated as one — it is used only as a "
        "secondary measure to stop the model volunteering remembered facts."
    )

    d.h2("6.2  A two-class cache, with permanent history")
    d.table(
        ["Class", "Key", "TTL", "Why"],
        [
            ["Historical", "(source, ticker, field, **as_of**)", "**Permanent**",
             "The past does not change. A short TTL would force constant re-fetching "
             "during ablation sweeps, triggering the exact rate-limiting the cache exists "
             "to prevent."],
            ["Live quote", "(source, ticker, field)", "15 minutes", "Demo path only."],
            ["LLM response", "sha256(prompt + model + **nonce**)", "Permanent",
             "Identical prompts cost nothing on re-run. The nonce is mandatory for variance "
             "runs — see §6.11."],
        ],
        widths=[1.0, 2.2, 1.0, 2.7],
    )

    d.h2("6.3  A point-in-time universe — the survivorship-bias fix")
    d.p(
        "The test set is built from the stocks that **actually traded on each as_of date**, "
        "read from that day's NSE bhavcopy — not from today's NIFTY 50 membership list. "
        "Using today's list is textbook survivorship bias: it silently excludes every "
        "company that was delisted, merged or demoted, which are disproportionately the "
        "losers."
    )
    d.callout(
        "Because the bhavcopy is a complete daily snapshot, this project can **prove** its "
        "universe was correct — something very few student backtests can do. The frozen "
        "test set records its exclusions: for example, TATAMOTORS is excluded from "
        "2025-11-06 because it did not trade on NSE that day."
    )
    d.p(
        "The same rule is applied inside the ticker boundary itself: membership is verified "
        "against the bhavcopy **for the date being analysed**. Otherwise a name that traded "
        "normally in mid-2025 but is absent from a current bhavcopy would be rejected on "
        "dates when it was perfectly valid — survivorship bias smuggled in through the "
        "validation layer."
    )

    d.h2("6.4  The SEBI 45-day filing rule — the fundamentals leakage fix")
    d.p(
        "Under **SEBI LODR Regulation 33**, a listed company files quarterly results within "
        "45 days of quarter end (60 for annual). So the numbers for a quarter ending "
        "31 December 2024 were not public until roughly 14 February 2025. A backtest dated "
        "20 January 2025 that can see them is reading the future."
    )
    d.p("**Rule implemented:** a quarter is visible only if `as_of ≥ quarter_end + 45 days`.")
    d.h3("And a stricter rule the data forced")
    d.p(
        "yfinance's company info is a **current** snapshot: today's P/E, today's market cap, "
        "today's margins. Feeding those into a forecast dated in the past is lookahead bias "
        "of the most direct kind — the model would be told today's valuation while "
        "predicting the past. So in strict point-in-time mode those fields are **withheld "
        "entirely**: they are recorded in a clearly-labelled `current_snapshot` for the "
        "report's data-coverage table, but they never reach a prompt."
    )
    d.callout(
        "The consequence is that fundamental evidence at a past date is often **empty**. "
        "That is the honest result and it is reported as such — a coverage limit of free "
        "data, not a bug. The alternative, quietly serving today's P/E, would invalidate "
        "every number in the evaluation."
    )

    d.h2("6.5  GDELT's rate limit arrives as HTTP 200")
    d.p(
        "When GDELT's rate limit is exceeded it does **not** return HTTP 429. It returns "
        "HTTP 200 with the body text 'Please limit requests to one every 5 seconds'. A "
        "naive client stores that string as if it were an article list — and because the "
        "cache is permanent, the poisoning is permanent too."
    )
    d.p(
        "The client therefore inspects the body **before** parsing, treats the message as a "
        "retryable error, never caches it, and spaces requests at least 5 seconds apart."
    )

    d.h2("6.6  Data vintage: publication date, not observation date")
    d.p(
        "CPI for a given month is published the following month. A macro reading dated "
        "mid-month must not see it. Every macro series therefore carries a publication lag "
        "and observations are filtered on `observation_date + lag ≤ as_of`. Filtering on the "
        "observation date alone is the subtle version of lookahead bias, and it is easy to "
        "ship by accident."
    )
    d.p(
        "Where a series is unusable it is documented rather than substituted: India CPI, IIP "
        "and the discount rate on FRED are stale or dead, so CPI is recorded as a stated "
        "limitation and the RBI repo rate comes from a hardcoded, auditable decision "
        "calendar that flags any date beyond its verified window."
    )

    d.h2("6.7  The reconciliation gate — the anti-hallucination layer")
    d.p(
        "Every numeric claim an agent makes is re-verified against the cached source data "
        "**before it propagates** to the next agent. This is Bloomberg's ASKB pattern."
    )
    d.callout(
        "A hallucinated adjective is embarrassing; a hallucinated **number** is invisible. "
        "'RSI is 28, deeply oversold' reads exactly like a correct reading when the true "
        "RSI is 61, and it propagates through the debate into the final price target where "
        "nobody can trace it."
    )
    d.table(
        ["Check class", "What it catches"],
        [
            ["**Value mismatch**", "A claimed figure disagreeing with the source value "
             "beyond a 2% tolerance."],
            ["**Magnitude error**", "A figure ~100× or ~10,000,000× off — the lakh/crore "
             "parse failure (see §6.9). Checked *first*, so it is never buried as an "
             "ordinary mismatch."],
            ["**Internal consistency**", "Support above resistance, target_low above "
             "target_high, confidence outside 0–100."],
            ["**Fabricated citation**", "An article link cited that was never supplied, or "
             "a metric asserted where the evidence pack contained none — the signature of "
             "recall leaking in through the model's weights."],
            ["**Implausible target**", "A price target beyond 3 sigma of the stock's own "
             "realised volatility over the horizon."],
        ],
        widths=[1.6, 5.3],
    )
    d.h3("Two design decisions worth defending")
    d.bullets([
        "**The gate flags; it does not silently repair.** Clamping a bad target would change "
        "the very quantity the evaluation measures (MAPE, target hit rate), turning a "
        "measurement of the model into a measurement of our clamp. A clamping mode exists "
        "for the live demo, is off in every scored run, and the record states which was used.",
        "**Checks that cannot be performed are recorded as 'unverifiable', not passed.** A "
        "gate reporting zero mismatches because it checked nothing is worse than no gate, "
        "because it buys false confidence.",
    ])
    d.p(
        "The gate is proven by attack, not by assertion: the test suite injects a fake RSI, "
        "a 100× crore target, an invented article URL, a fabricated P/E, an inverted support "
        "level and an impossible price move, and asserts each one is caught — plus a "
        "complement test that an honest report is **not** flagged, so a gate that flagged "
        "everything could not pass."
    )

    d.h2("6.8  Parallel agents in LangGraph")
    d.p(
        "The four specialists run as a genuine parallel fan-out. Two details are load-bearing:"
    )
    d.bullets([
        "**Distinct state keys per specialist.** If they wrote to one shared key, LangGraph "
        "would raise `INVALID_CONCURRENT_GRAPH_UPDATE` — two nodes returning a value for the "
        "same key in one superstep is ambiguous and the framework refuses to guess.",
        "**Reducers on accumulated lists.** The debate turns and the error log are written "
        "by more than one node, so they carry `operator.add`. Without the reducer the last "
        "writer wins and earlier entries silently disappear — worse than a crash, because "
        "the run still produces a forecast and the transcript is merely short.",
    ])
    d.p(
        "The evidence pack is built **once, before the graph starts**, so the four parallel "
        "specialists never race to fetch the same data and every network call is complete "
        "before any concurrency begins."
    )

    d.h2("6.9  Lakh and crore: a live 100× hallucination risk")
    d.p(
        "Indian sources write 1,00,000 for one lakh and report 'revenue of ₹2,500 crore', "
        "meaning 25,000,000,000. A model asked for a number will happily return 2500. The "
        "codebase rule is that **every monetary value crossing into a schema field is in "
        "plain INR units**, with a parser to convert and a magnitude check in the "
        "reconciliation gate to catch what slips through."
    )

    d.h2("6.10  NIFTY-relative scoring")
    d.p(
        "Indian indices have trended up strongly, so a model that says 'up' every time can "
        "post around 60% raw directional accuracy and look like a forecaster. Every result "
        "table therefore reports **NIFTY-relative accuracy beside raw accuracy**, and the "
        "'always up' naive baseline is run specifically to make the gap visible."
    )
    d.p(
        "The already-recorded naive baseline results demonstrate the effect precisely: "
        "'always up' scores **63.2% raw** directional accuracy but only **47.4% against "
        "NIFTY** — near chance. An examiner will ask about this, and the answer is already "
        "in the results files."
    )

    d.h2("6.11  The cache nonce, and why zero variance would be a lie")
    d.p(
        "Phase 4 repeats each configuration to report variance. Without a unique cache "
        "nonce per repeat, the second run is served entirely from the LLM cache, reports "
        "identical numbers, and the measured variance is exactly zero — an artifact that "
        "looks like a remarkably stable system. The nonce is the difference between "
        "reporting variance and fabricating its absence."
    )

    d.page_break()
    d.h1("7. Bugs found and fixed during this build")
    d.p(
        "Included because they are evidence of engineering rather than of typing, and "
        "because two of them were silently corrupting output that otherwise looked correct."
    )
    d.table(
        ["Bug", "Effect", "Fix"],
        [
            ["`pandas-ta-classic` was listed in requirements but **not installed** in the "
             "active interpreter.",
             "Every indicator function caught the ImportError and returned `None`, so the "
             "technical agent received 'unavailable' for RSI, MACD and every moving "
             "average — while the pipeline ran normally and reported no error.",
             "Installed and verified; the environment check now tests the import explicitly."],
            ["**MACD columns read by position.** pandas-ta returns "
             "[MACD, MACDh, MACDs], not [MACD, MACDs, MACDh].",
             "The signal line was being read as the histogram. The bullish/bearish bias was "
             "computed from the wrong series and was wrong for most inputs — verified: one "
             "test case flipped from 'Bullish' to 'Bearish' once fixed.",
             "Columns are now matched by **name prefix**, never by position."],
            ["**Bollinger bands read by position.** pandas-ta returns "
             "[BBL, BBM, BBU] — lower, middle, upper.",
             "Upper and lower bands were swapped, so the model was shown an upper band "
             "*below* the middle band.",
             "Same name-based fix; a test now asserts lower < middle < upper."],
            ["The rupee sign (U+20B9) crashed the CLI on a default Windows console (cp1252).",
             "`UnicodeEncodeError` killed any run that printed a price — which is every run. "
             "It would have failed on exactly the machine the demo runs on.",
             "CLI entry points reconfigure stdout/stderr to UTF-8."],
            ["The cost tally was mutated by four parallel threads without a lock.",
             "`calls += 1` is a load-add-store, not atomic. A lost update would "
             "under-report the token cost of exactly the configuration whose cost the "
             "research question is about.",
             "Added a lock around the shared tally."],
            ["`tests/test_env.py` called `sys.exit()` at import time.",
             "pytest aborted the **entire** collection run with an INTERNALERROR, taking "
             "every other test with it.",
             "Restructured so it works both as a script and as a collected test."],
        ],
        widths=[2.0, 2.6, 2.3],
    )

    d.h1("8. Testing")
    d.p(
        "**79 tests, all passing, none requiring an API key or a network connection.** A "
        "test that needs the internet to tell you your code is correct is not a test, it is "
        "a monitor."
    )
    d.table(
        ["Test file", "What it proves"],
        [
            ["`test_leakage.py`", "The forecasting side of the system never imports the "
             "realised-outcomes module; the evidence pack never contains a row after "
             "`as_of`; the SEBI rule hides unfiled quarters; every macro series has a "
             "publication lag; the archival news path cannot reach the live RSS path; every "
             "system prompt states the cutoff."],
            ["`test_reconciliation.py`", "The gate catches an injected fake indicator value, "
             "a crore magnitude error, a fabricated citation, a fabricated metric, an "
             "inverted range and an impossible price move — and does **not** flag an honest "
             "report."],
            ["`test_pipeline.py`", "The graph compiles with all seven nodes; specialists have "
             "distinct state keys; accumulated lists carry reducers; the full run makes "
             "exactly 9 model calls; the debate produces 4 turns in the right order; "
             "`--no-debate` removes exactly 4 calls; each leave-one-out drops its specialist "
             "and still produces a scoreable forecast; the output matches the contract the "
             "harness scores."],
            ["`test_env.py`", "Required packages import (including the "
             "`pandas_ta_classic` name); config loads; cache opens; every phase's files "
             "are present."],
        ],
        widths=[1.6, 5.3],
    )
    d.p(
        "The pipeline tests run against a **stubbed model** that returns schema-valid canned "
        "reports. That is not for speed — it is so that claims about the *graph* do not "
        "depend on what a model happened to say. A failure there is always a wiring failure. "
        "It also means the entire Phase 3 architecture is verifiable before any API key "
        "exists."
    )

    d.h1("9. How to run it")
    d.code(
        "# 1. environment check\n"
        "python -m tests.test_env\n"
        "python -m pytest tests/ -q               # 79 tests, no API key needed\n"
        "\n"
        "# 2. one forecast, evidence pack only (no model calls)\n"
        "python -m forecast RELIANCE.NS --as-of 2025-06-02 --data-only\n"
        "\n"
        "# 3. the India boundary, enforced by code\n"
        "python -m forecast AAPL --as-of 2025-06-02      # rejected, exit code 2\n"
        "\n"
        "# 4. full multi-agent forecast  (needs GEMINI_API_KEY)\n"
        "python -m forecast TCS.NS --as-of 2025-06-02 --system multiagent\n"
        "python -m forecast TCS.NS --as-of 2025-06-02 --system multiagent --no-debate\n"
        "python -m forecast TCS.NS --as-of 2025-06-02 --system multiagent --drop sentiment\n"
        "\n"
        "# 5. evaluation\n"
        "python -m evaluate run --system naive-momentum   # runs today, no key\n"
        "python -m evaluate recall-probe --start 2024-01-01 --end 2026-01-01\n"
        "python -m evaluate ablate --repeats 3            # Phase 4, one command\n"
    )

    d.h1("10. Current status and what remains")
    d.h2("Runs today, with no API key")
    d.bullets([
        "The complete data layer: prices, NSE calendar, indicators, fundamentals, news, macro.",
        "The frozen, point-in-time test set (20 cases, verified against the bhavcopy).",
        "Both naive baselines, fully scored, with results committed.",
        "The reconciliation gate and the entire agent graph, verified end to end.",
        "All 79 tests.",
        "The FastAPI backend and the Streamlit dashboard, including the evidence "
        "pack, the chart and the leakage controls.",
    ])
    d.h2("Waiting on the Gemini API key")
    d.bullets([
        "**The recall probe** — locating the training cutoff empirically. Until it runs, the "
        "test window's post-cutoff status is argued rather than demonstrated, and it is a "
        "figure the report needs.",
        "**Scored runs** for the single-LLM baseline and every multi-agent configuration.",
        "**The Phase 4 ablation tables** — the tooling is complete and the command is one line.",
    ])
    d.callout(
        "Nothing about the architecture changes when the key arrives. Add `GEMINI_API_KEY` "
        "to `.env` and the same commands run for real."
    )
    d.h2("Phase 5 deliverables, all built")
    d.bullets([
        "**FastAPI backend** with a WebSocket that streams each agent stage as it "
        "completes, plus REST endpoints for prices, the evidence pack and a forecast.",
        "**Streamlit dashboard** — evidence pack, candlestick chart, live agent log, "
        "Bull-vs-Bear split view, forecast card and the reconciliation gate.",
        "**Thesis report** (`docs/BTP_Thesis_Report.docx`), generated from the committed "
        "results so its tables cannot drift from the evidence.",
        "**Defence slides** (`docs/BTP_Defence_Slides.pptx`) — 20 slides with speaker notes.",
        "**Demo cache verifier** (`python -m scripts.warm_demo`) so no live API call can "
        "decide whether the defence succeeds.",
    ])

    d.h1("11. Honest limitations")
    d.bullets([
        "**Restatement leakage remains.** The 45-day SEBI rule fixes *timing* leakage. "
        "yfinance still serves restated financials, so if a company later restated a figure "
        "we see the restated version, not what the market saw. True point-in-time "
        "fundamentals are an institutional product and are out of scope for a free-data "
        "project. Saying so plainly is worth more than pretending otherwise.",
        "**India CPI is unavailable** from the free source (the FRED series is stale). It is "
        "documented as a limitation, not estimated or fabricated.",
        "**The RBI repo rate comes from a hardcoded decision calendar.** It is public and "
        "trivially auditable, and any date beyond the verified window is flagged in the "
        "output rather than quietly served.",
        "**GDELT provides headline metadata and tone, not full article text.** Adequate for "
        "sentiment; stated as a limitation. Coverage of smaller Indian outlets is uneven.",
        "**Bhavcopy prices are unadjusted** for splits and bonuses while yfinance prices are "
        "adjusted. Each frame records its source and the two are never mixed within one "
        "series.",
        "**The test set is small** (20 cases). Accuracy differences of a few points will sit "
        "inside sampling noise, which is exactly why repeat runs and standard deviations are "
        "reported alongside every headline number.",
    ])

    d.h1("12. References")
    d.bullets([
        "TradingAgents: Multi-Agents LLM Financial Trading Framework — **arXiv:2412.20138**",
        "Detecting Lookahead Bias in LLM Forecasts — **arXiv:2512.23847**",
        "Mitigating Look-Ahead Bias in Financial Backtesting with LLMs — **arXiv:2605.24564**",
        "SEBI LODR Regulation 33 — quarterly results within 45 days, annual within 60",
        "NSE daily bhavcopy archive — `nsearchives.nseindia.com/content/cm/` (UDiFF CSV, "
        "keyless, browser User-Agent required)",
        "RBI Database on Indian Economy (DBIE) — repo rate, CPI, G-sec yields",
        "FRED India series — `DEXINUS`, `INDIRLTLT01STM`, `IRSTCI01INM156N`",
        "The GDELT Project — gdeltproject.org",
        "LangGraph documentation — `INVALID_CONCURRENT_GRAPH_UPDATE`, state reducers",
    ])

    return d


def main() -> int:
    doc = build()
    path = doc.save(OUT)
    size_kb = path.stat().st_size / 1024
    print(f"Wrote {path}  ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
