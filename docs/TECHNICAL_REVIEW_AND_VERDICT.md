# Technical Review & Build Verdict
## Financial Forecasting by Multi-AI Agent System — B.Tech Capstone

**Reviewer role:** Finance-AI research review
**Review date:** 23 July 2026
**Scope:** `BTP_All_Phases_Work_Breakdown.pdf` (5 phases), existing repository state, and the underlying research premise
**Method:** Every factual claim below was checked against a primary source or reproduced on this machine. Claims that could **not** be verified are marked ⚠️ **UNVERIFIED** and listed separately in §9 — they are not presented as findings.

---

## 1. Verdict

> ### ✅ **BUILD — but do not build the plan as written.**

The architecture is sound and the engineering instincts are good. The project does **not** need a restart.

However, **as currently planned, the project would pass its demo and fail its evaluation chapter.** Three things must be fixed *before* Phase 2 code is written, because retrofitting them later means touching every tool and every agent:

| # | Must fix before building | Why it cannot wait |
| :-- | :--- | :--- |
| 1 | **Add `as_of` to every data function** | Retrofitting means rewriting all 6 tools *and* re-running all experiments |
| 2 | **Move evaluation before the build; define a post-cutoff test window** | A within-training-window backtest is invalid; discovering this in Phase 5 leaves no time |
| 3 | **Reposition the novelty claim against TradingAgents** | Affects the report's framing, the research question, and what you measure |

Everything else in this review is fix-as-you-go.

**Estimated cost of these three fixes: ~1 day of planning. Cost of not fixing them: the results chapter.**

---

## 2. What Was Verified, and How

| # | Claim under test | Method | Result |
| :-- | :--- | :--- | :--- |
| 1 | `pandas-ta-classic` import name | PyPI package page | ❌ **Bug confirmed** — imports as `pandas_ta_classic` |
| 2 | Project venv state | Direct `site-packages` inspection | ❌ **0 packages installed** |
| 3 | `tests/test_env.py` runs | Executed on this machine | ❌ **All 5 checks fail** |
| 4 | yfinance rate ceiling "~2,000/hr" | Maintainer issue tracker | ❌ **False** — ~360/hr; 429s reported from ~950 |
| 5 | LangGraph parallel state writes | LangChain error docs | ✅ Confirmed — needs `Annotated` reducer |
| 6 | Gemini nested-Pydantic reliability | google-genai + pydantic-ai issue trackers | ⚠️ **New risk found** (see §4.4) |
| 7 | Gemini free-tier RPM/RPD | Official rate-limit docs | ⚠️ **Not publishable** — Google no longer lists numbers |
| 8 | Lookahead bias is real & measurable | arXiv:2512.23847 | ✅ Confirmed |
| 9 | Architecture already published | arXiv:2412.20138 + GitHub | ✅ Confirmed |
| 10 | NewsAPI free-tier viability | Vendor pricing pages | ✅ Confirmed unusable for backtest |
| 11 | GDELT global + free | gdeltproject.org | ✅ Confirmed — 100+ languages, 1979→present |
| 12 | yfinance NSE/BSE coverage | Live probe 2026-08-06 | ✅ Confirmed — `RELIANCE.NS`, INR, Asia/Kolkata, from 1996 |
| 13 | FRED needs its own key | FRED API docs | ✅ Confirmed — separate registration |
| 14 | Recharts candlestick support | Library docs | ✅ Confirmed — no native candlestick |
| 15 | Stooq keyless CSV fallback | Live probe 2026-08-06 | ❌ **Refuted — now a JS proof-of-work page. Fallback replaced (§6.1)** |
| 16 | NSE bhavcopy archive keyless | Live probe 2026-08-06 | ✅ Confirmed — 200 OK w/ browser UA; 404 on holidays |
| 17 | FRED India macro series | Live probe 2026-08-06 | ⚠️ **Partial — FX/10Y/call-rate live; CPI, IIP, discount rate stale or dead (§6.3)** |
| 18 | GDELT rate-limit behaviour | Live probe 2026-08-06 | ⚠️ **Returns the limit message as HTTP 200 body — cacheable as fake data (§6.2)** |

---

## 3. 🔴 Blocking Bugs — Reproduced on This Machine

These are not opinions. They were executed.

### 3.1 The environment is empty
```
venv/Lib/site-packages → 0 non-pip packages
```
The virtualenv exists; `pip install` never completed. **Phase 1 Task 1.2 is not done**, despite the folder structure suggesting otherwise.

### 3.2 Every import fails
```
❌ yfinance   ❌ pandas_ta   ❌ google-genai   ❌ langgraph
❌ config error: No module named 'backend'
```

### 3.3 `import pandas_ta` will fail *even after installing correctly* ⚠️ **Highest-value catch**

`tests/test_env.py:14` reads `import pandas_ta as ta`.

But **`pandas-ta-classic` v0.6.52 imports as `pandas_ta_classic`** — verified on PyPI:
```python
import pandas_ta_classic as ta      # ✅ correct
import pandas_ta as ta              # ❌ ModuleNotFoundError
```
Without this fix, the test reports failure forever and you conclude the install is broken when it isn't. Also note: **requires Python ≥ 3.10.**

**Fix:**
```python
import pandas_ta_classic as ta
```

### 3.4 `No module named 'backend'`
Two causes: `backend/` has no `__init__.py`, and running `python tests/test_env.py` puts `tests/` on `sys.path`, not the project root.

**Fix:** add `backend/__init__.py` and run as a module from the project root:
```bash
python -m tests.test_env
```

---

## 4. 🔴 Design & Correctness Problems

### 4.1 The data layer leaks the future by construction

Phase 2 specifies:
```python
get_price_history(ticker, period)
get_fundamentals(ticker)
get_news(ticker)
get_macro_data()
```
**None accept a date.** They always return *now*. Phase 5 then asks you to "pretend today is 3 months in the past."

The result: your sentiment agent reads **this week's** headlines — which already contain the outcome — while claiming to forecast from three months ago. That is not forecasting; it is hindsight. A panel finds this in under a minute.

**Fix — build into Phase 2, not Phase 5:**
```python
get_price_history(ticker, start, end, as_of)
get_fundamentals(ticker, as_of)       # filter to filings published <= as_of
get_news(ticker, as_of)               # filter to published_date <= as_of
get_macro_data(as_of)                 # FRED series respecting vintage
```
Enforce the cutoff **in the data layer**, never by prompting the model.

### 4.2 The backtest is invalid even after 4.1 is fixed 🔴 **Most important finding**

This is the point most reviewers stop one step short of.

Fixing `as_of` removes leakage from the **pipeline**. It does nothing about leakage inside the **model's weights**. Gemini has already read what happened to these stocks. Per **arXiv:2512.23847**, *Lookahead Propensity* is materially positive throughout the training window and **collapses to ≈0 immediately after the training cutoff**.

**So a point-in-time-correct backtest over a within-training-window period is still meaningless.**

**Fix (both are required, not either/or):**
1. `as_of` plumbing everywhere (§4.1), **and**
2. Test window placed **strictly after the model's training cutoff**, confirmed with a recall probe: ask the model about outcomes it should not know and verify it cannot recall them. Publish that probe as a figure — it is a genuine methodological contribution.

### 4.3 Cache design defeats its own purpose

The plan says: *cache is fresh if `< 15 min old`.*

For historical evaluation data keyed by an as-of date, **the value never changes**. A 15-minute TTL forces constant re-fetching during ablation sweeps — causing exactly the 429s the cache exists to prevent.

**Fix — two cache classes:**

| Class | Key | TTL |
| :--- | :--- | :--- |
| Historical / point-in-time | `(ticker, field, as_of)` | **Permanent** |
| Live quote (demo only) | `(ticker, field)` | 15 min |

Cache **LLM responses** too, keyed by a prompt hash. Debugging re-runs must not consume fresh quota.

### 4.4 ⚠️ Gemini structured output will fight your nested schemas — **new risk, not previously flagged**

Task 3.1 defines `FinalForecast` with nested sub-objects. Verified issues in Google's own tracker:

- **Gemini rejects Pydantic schemas that use `Field(default=...)`** (googleapis/python-genai #699). Your schemas will almost certainly use defaults.
- **Nested Pydantic models can be misread as tool calls**, producing `Unknown tool name: 'NestedModel'` or `MALFORMED_FUNCTION_CALL`.
- **`propertyOrdering`** improves output quality by up to ~15% on complex schemas — and models do *not* respect your declared field order without it.

**Fix:**
1. Test `FinalForecast` — your most complex schema — against the API in **Phase 1**, not at integration time.
2. Avoid `Field(default=...)` in response schemas; use `Optional[...]` and post-process.
3. Set `propertyOrdering` explicitly.
4. Keep nesting shallow — prefer flat schemas with prefixed field names over deep object trees.
5. Count parse failures as a **reported metric**, not a silent retry.

### 4.5 Parallel agents will crash LangGraph without a reducer

Task 3.5 fans out 4 specialists in parallel. If two nodes write the same state key in one step, LangGraph raises `INVALID_CONCURRENT_GRAPH_UPDATE` — *"Can receive only one value per step."*

**Fix — either:**
```python
# (a) distinct keys per agent  ← simplest, recommended
class AgentState(TypedDict):
    technical_report:   TechnicalReport | None
    fundamental_report: FundamentalReport | None
    sentiment_report:   SentimentReport | None
    macro_report:       MacroReport | None

# (b) or a reducer, if they share a key
from typing import Annotated
import operator
reports: Annotated[list, operator.add]
```

### 4.6 Smaller confirmed defects

| Issue | Impact | Fix |
| :--- | :--- | :--- |
| **SMA-200 on a 1M window** | Silent `NaN` | Always fetch ≥ 2 years regardless of chart range |
| **Bhavcopy ≠ yfinance schema** | Fallback breaks during the outage it exists for | Normalise columns **and adjustment basis** at the boundary (bhavcopy is unadjusted); record the source on every frame; unit-test the fallback path |
| **yfinance nulls on `.NS` fundamentals** | Agent crashes or invents a number | Explicit null handling; agents must say "unavailable", never guess. Log the null rate per field — it is a results table, and it explains any large-cap vs mid-cap accuracy gap |
| **No news dedup** | Same story double-counts, skewing polarity | Dedup by URL + title similarity |
| **No version pinning** | LangGraph breaking changes | `pip freeze > requirements.txt` after first good install |
| **FRED key not provisioned** | Blocks Task 2.6 mid-Phase 2 | Register in Phase 1 alongside Gemini |
| **Recharts has no candlestick** | Fighting the library | Use TradingView Lightweight Charts |
| **POST vs WebSocket unowned** | 30–90 s request times out on proxies | WebSocket owns the live flow; POST only for cached results |
| **Non-deterministic runs** | Reported numbers shift before demo day | temperature≈0 on synthesis; cache the actual scored run |

---

## 5. 🔬 The Research Problem

### 5.1 The architecture is already published

> **TradingAgents: Multi-Agents LLM Financial Trading Framework** — arXiv:2412.20138
> Technical / fundamental / sentiment analysts, **Bull and Bear researchers that debate**, a **risk management team**, a synthesising trader. Public repo: `github.com/TauricResearch/TradingAgents`.

That is this project's design. **"Our contribution is the Bull vs. Bear debate" will not survive a literature review.**

This is *not* fatal. Replication-plus-extension is legitimate and often stronger than a weak novelty claim. But it must be cited and positioned deliberately, in Chapter 2.

### 5.2 "Proving multi-agent > single LLM" is the wrong goal

The Phase 5 deliverable reads: *"Backtest results **proving** multi-agent > single LLM."*

You cannot set out to prove a conclusion. If the debate layer doesn't help, that is a **result**, not a failure — and a well-measured negative result defends better than a vague positive one.

### 5.3 Where the real contribution lives

| Axis | Why it is defensible |
| :--- | :--- |
| **Leakage-free evaluation** | Most published multi-agent finance results do not control for it |
| **Debate ablation** | Does the debate earn its ~2× token cost? Almost nobody measures this |
| **Confidence calibration** | When it says 80%, is it right 80% of the time? Rarely reported |
| **Indian-market focus** | The literature is overwhelmingly US-large-cap; NSE is under-studied (see §6) |

**Proposed research question:**
> Under an evaluation protocol that provably excludes lookahead bias, does adversarial multi-agent debate improve forecast accuracy and confidence calibration over (a) a single-LLM baseline and (b) the same specialists without debate — and is any gain justified by its token cost?

Answerable either way. That is what makes it a research project.

---

## 6. 🇮🇳 Indian-Market Free Data Strategy

**Scope decision (revised 2026-08-06): NSE/BSE only.** The earlier "worldwide coverage" plan is
withdrawn. Narrowing is not a retreat — a single market gives one trading calendar, one currency and
one regulator, which is what makes the leakage-free `as_of` protocol *provable* rather than
approximate. It also buys three India-specific mechanisms (point-in-time universe, SEBI filing lag,
NIFTY-relative scoring) that a worldwide build cannot have.

### 6.1 Price data — yfinance `.NS` / `.BO`, with an India-native fallback

*Verified 2026-08-06:* `RELIANCE.NS` returns `currency: INR`, `exchange: NSE`,
`timezone: Asia/Kolkata`, history from **1996**.

**The Stooq fallback in the previous version of this review is dead.** *Verified 2026-08-06:*
`stooq.com/q/d/l/` now answers scripted clients with a **JavaScript proof-of-work challenge page**,
not CSV — so the documented fallback would have silently returned nothing on the exact day it was
needed. It is replaced by:

| | NSE daily bhavcopy archive |
| :--- | :--- |
| URL | `nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip` |
| Key | None — but a **browser `User-Agent` is required** |
| Verified | HTTP 200, ~170 KB/day (2025-01-15); 404 on holidays (2025-03-14 Holi) and weekends |
| Contents | Every NSE cash-market instrument for that day, UDiFF CSV |
| Caveat | Prices are **unadjusted** for splits/bonuses — never mix with yfinance auto-adjust rows |

It pays for itself three times: **fallback prices**, **the trading calendar** (file exists ⟺ NSE
traded), and **a survivorship-bias-free universe** (what actually traded on a given date).
Cross-check performed: yfinance and bhavcopy agree exactly on RELIANCE 2025-01-15
(1244.95 / 1257.00 / 1241.85 / **1252.20**).

### 6.2 News — GDELT, scoped to India

Verified: **100+ languages, archive from 1 Jan 1979, updates every 15 minutes, 100% free.** Scope
queries with `sourcecountry:india` and the company's registered name.

This solves what NewsAPI cannot: NewsAPI's free tier is **100 req/day, 1-month archive, 24-hour delay,
localhost-only** — unusable for any historical evaluation.

**⚠️ Rate-limit trap (verified 2026-08-06):** back-to-back GDELT requests return
`"Please limit requests to one every 5 seconds"` **as the response body with HTTP 200**. It does not
raise, and a naive cache will store that sentence as if it were news. Detect the string explicitly,
treat it as retryable, and space requests ≥ 5 s.

**Trade-offs to document:** GDELT gives tone/theme/metadata, **not full article text**. Indian outlets
syndicate PTI/ANI copy heavily, so dedup by URL + title similarity is mandatory or polarity skews.

### 6.3 Macro — FRED's India coverage is thinner than assumed

*Verified 2026-08-06 by keyless CSV probe (`fred.stlouisfed.org/graph/fredgraph.csv?id=…`):*

| Indicator | Series ID | Last observation | Verdict |
| :--- | :--- | :--- | :--- |
| USD/INR (daily) | `DEXINUS` | 2026-07-31 | ✅ Use |
| India 10Y G-sec yield | `INDIRLTLT01STM` | 2026-05 | ✅ Use |
| India call-money rate | `IRSTCI01INM156N` | 2026-05 | ✅ Use (policy-stance proxy) |
| India CPI | `INDCPIALLMINMEI` | **2025-03** | ⚠️ Stale |
| India IIP | `INDPROINDMISMEI` | **2023-01** | ❌ Dead |
| India discount rate | `INTDSRINM193N` | **2022-07** | ❌ Dead |

**This would have blocked Phase 2 mid-build.** CPI and the RBI repo rate must come from RBI DBIE /
MoSPI, or — the honest BTP answer — hardcode the published repo-rate decision calendar and document
CPI as a limitation. Do not fabricate a series.

### 6.4 Recommended stack

| Layer | Source | Cost | Status |
| :--- | :--- | :--- | :--- |
| Price / OHLCV | yfinance `.NS`/`.BO` (cached) → **NSE bhavcopy** fallback | Free | ✅ Verified |
| Trading calendar | NSE bhavcopy availability | Free | ✅ Verified |
| Point-in-time universe | NSE bhavcopy daily snapshot | Free | ✅ Verified |
| Indicators | Computed locally | Free | ✅ |
| Fundamentals | yfinance ⚠️ *not point-in-time, patchier on `.NS`* | Free | Partial |
| News | **GDELT**, `sourcecountry:india` | Free | ✅ (rate-limit handling required) |
| Macro | FRED (FX, 10Y, call rate) + RBI/MoSPI for CPI & repo | Free | Partial — see §6.3 |
| Benchmark / regime | `^NSEI`, `^BSESN`, `^INDIAVIX`, `INR=X`, `BZ=F`, NIFTY sectoral | Free | ✅ Verified |

**Total data cost: zero.**

### 6.5 The one gap money cannot close

**Point-in-time fundamentals.** yfinance returns *today's* restated financials, not what was public on
your as-of date. True PIT databases (Compustat PIT, FactSet) are institution-priced.

**Mitigation, not purchase:** apply the **SEBI LODR Reg. 33 filing rule** — a quarter is visible only
once `as_of` ≥ quarter_end + 45 days (annual: 60) — restrict to slow-moving ratios, and **document the
limitation explicitly.** The filing rule fixes *timing* leakage; it does not fix *restatement*
leakage. A stated limitation earns credit; a hidden one loses it.

---

## 7. 🔐 Security Review

Relevant because this is a project *about* AI agents — examiners will ask.

| Risk | Severity | Fix |
| :--- | :--- | :--- |
| **Prompt injection via headlines** — untrusted web text goes straight into the LLM | Medium | Treat headlines as data, not instructions: delimit clearly, instruct the model to ignore embedded directives, validate output against the schema. Discuss in the report — it shows awareness of the risk class. |
| **No auth / rate limit on FastAPI** | High *if deployed* | Per-IP rate limit before any public exposure; otherwise anyone can drain your quota |
| **`NEXT_PUBLIC_` key leak** | Critical | Never prefix secrets with `NEXT_PUBLIC_` — it ships them into the client bundle. All provider calls stay server-side. |
| **CORS `allow_origins=["*"]`** | Medium | Pin to your frontend origin explicitly |
| **WebSocket has no timeout/connection cap** | Low | Idle timeout + max connections |
| **`.env` committed** | Critical | `.gitignore` exists — **verify the key was never committed** before pushing |
| **No dependency audit** | Low | `pip audit` before submission |

---

## 8. ✅ Corrected Phase Plan

The count is not the issue — **the order is.** Build the ruler before the thing it measures.

### Phase 1 — Foundation & Walking Skeleton
Environment (fixing §3), **all** API keys including **FRED**, `cache.py` first, `tickers.py` (the India boundary), `market_data.py` with `as_of` + **NSE bhavcopy fallback**, `calendar_nse.py`, indicators, **the single-LLM baseline**, one specialist end-to-end, **and a `FinalForecast` schema smoke-test against Gemini** (§4.4).

> **Gate:** `python -m forecast <TICKER> --as-of <DATE>` returns a valid schema-conformant forecast twice; the second run makes **zero** network calls. `pip freeze > requirements.txt` committed.

### Phase 2 — Evaluation Harness & Leakage-Free Protocol
Determine the training cutoff, run the recall probe, **freeze and commit the test set**, implement metrics (directional accuracy, MAE, **calibration/Brier**, **cost per forecast**), add a naive baseline, record baseline results.

> **Gate:** any forecaster can be scored by one command, reproducibly; probe result documented.

### Phase 3 — Multi-Agent System
Remaining specialists, LangGraph `StateGraph` with **distinct state keys** (§4.5) and checkpointing, **reconciliation gate**, bounded Bull/Bear debate, risk synthesiser, and the **`--no-debate` switch wired from the start**.

> **Gate:** full system scores end-to-end; reconciliation catches a deliberately injected fake number.

### Phase 4 — Experiments & Ablation ← *where the marks are*
Multi-agent vs single-LLM vs naive; **debate ablation** (accuracy Δ **and** cost Δ); specialist leave-one-out; calibration curves; ≥3 repeats for variance; qualitative failure analysis on 5–10 wrong forecasts.

> **Gate:** every claim destined for the report traces to a committed results file.

### Phase 5 — Dashboard, Report & Defence
FastAPI + **Streamlit first** (React only if time genuinely remains), live agent log, debate view, forecast card with citations. Report with **TradingAgents positioned in Chapter 2**. Slides + **a cached known-good demo run**.

> **Gate:** clean clone runs the demo; every number traces to a results file.

---

## 9. ⚠️ What I Could NOT Verify

Listed explicitly so the next reviewer can close them.

| Item | Status | Action |
| :--- | :--- | :--- |
| **Gemini free-tier RPM/RPD** | Google's official rate-limit page **no longer publishes per-model numbers**; it directs users to AI Studio | **Check `aistudio.google.com` directly before designing around any figure.** Treat all quoted numbers — mine or anyone's — as unverified. |
| **Gemini training cutoff date** | Not reliably published per model | Determine **empirically** via the §4.2 recall probe. This is more defensible than citing a date anyway. |
| **Exact yfinance ban threshold** | Undocumented by design (unofficial scraper); community reports vary | Assume it is *lower* than any number you read. Cache-first makes it moot. |
| **TradingAgents' exact datasets/results** | Abstract lacks detail | Read the full PDF before writing Chapter 2 |

**Design consequence:** because the two most load-bearing numbers (LLM quota, training cutoff) are not reliably published, the architecture must be **quota-adaptive** (backoff + caching + Flash-class models) and the evaluation must be **empirically probed**, not documentation-driven.

---

## 10. Bottom Line

**Should you start building? Yes — today.**

- The architecture is validated by both industry practice and published research.
- The engineering plan is largely sound; most defects here are fix-as-you-go.
- Nothing requires a restart.

**But do these three things first, in this order:**

1. **Fix the environment** (§3) — ~10 minutes. `import pandas_ta_classic`, `backend/__init__.py`, `pip install`, `pip freeze`.
2. **Add `as_of` to every tool signature** (§4.1) — before writing any Phase 2 body. Cheap now, expensive later.
3. **Fix the evaluation protocol and novelty framing** (§4.2, §5) — ~1 day. This is what stands between a working demo and a defensible thesis.

**The honest summary:** the previous plan builds a system that *works* but cannot be *evaluated*. The demo would impress; Chapter 5 would not survive questioning. The corrected plan produces both — and the extra cost is roughly one day of planning, paid now instead of a lost results chapter paid later.

---

### References
- TradingAgents: Multi-Agents LLM Financial Trading Framework — **arXiv:2412.20138**
- Detecting Lookahead Bias in LLM Forecasts — **arXiv:2512.23847**
- Summoning the Oracle to Slay It: Mitigating Look-Ahead Bias in Financial Backtesting with LLMs — **arXiv:2605.24564**
- LangGraph — `INVALID_CONCURRENT_GRAPH_UPDATE` error reference, LangChain docs
- Gemini structured output — googleapis/python-genai issue #699; pydantic-ai issue #3483
- pandas-ta-classic — PyPI, v0.6.52
- GDELT Project — gdeltproject.org
- Yahoo Finance exchange & suffix list — help.yahoo.com

---

*Prepared for independent expert review. Findings marked ✅ were verified against primary sources or reproduced locally; items in §9 are explicitly open.*
