# Financial Forecasting by Multi-AI Agent System

> **B.Tech Capstone Project (BTP)**

## 📌 Project Overview
This project implements an autonomous **Multi-AI Agent System** for stock market trend prediction, fundamental valuation, sentiment analysis, and risk-managed financial forecasting.

> **Scope: Indian equities only — NSE (`.NS`) primary, BSE (`.BO`) secondary.** All prices in **INR**,
> all timestamps in **Asia/Kolkata**, benchmark **NIFTY 50**. This is a deliberate design decision, not
> a limitation: the published literature is overwhelmingly US-large-cap, and a single market means a
> single trading calendar, currency and regulator — which is what makes the leakage-free `as_of`
> protocol *provable*. Non-Indian tickers are rejected at the boundary by `backend/tools/tickers.py`.

For the full detailed project breakdown, system architecture, agent roles, and step-by-step implementation plan, please see:
👉 **[PROJECT_IDEA_AND_ROADMAP.md](file:///c:/Users/frien/OneDrive/Desktop/BTP/PROJECT_IDEA_AND_ROADMAP.md)**

---

## 🤖 System Architecture Highlights
- **Technical Analysis Agent**: Price trends & momentum indicators (RSI, MACD, Moving Averages).
- **Fundamental Analysis Agent**: Company health metrics, earnings, financial statements.
- **Sentiment & News Agent**: Indian financial press headlines (GDELT, India-scoped) & exchange filings.
- **Macroeconomic Agent**: RBI policy stance, CPI, USD/INR, crude, NIFTY sectoral indices.
- **Bull vs. Bear Debate Engine**: Adversarial reasoning between optimistic & cautious perspectives.
- **Chief Risk Officer & Synthesizer**: Final financial forecast signal, target price range, and confidence score.

---

## 🛠️ Planned Stack
- **Language**: Python 3.10+
- **Agent Orchestration**: `LangGraph` / `CrewAI`
- **LLM Engine**: Gemini API (`gemini-flash-latest` — Gemini 3.5 / 3.6 Flash class)
- **Data APIs**: `yfinance` `.NS`/`.BO` (primary — **must be cached**), **NSE bhavcopy archive** (keyless fallback + trading calendar + point-in-time universe), GDELT (news), FRED (USD/INR, 10Y G-sec)
  - *Stooq was dropped: as of 2026-08-06 it serves a JS proof-of-work page to scripted clients, so the fallback never worked.*
- **Backend API**: `FastAPI`
- **Frontend Dashboard**: React / Next.js / Streamlit

---

## 🔬 Research Question
> Under an evaluation protocol that provably excludes **lookahead bias**, does adversarial
> multi-agent debate produce measurably better forecasts than (a) a single-LLM baseline and
> (b) the same agents without debate — and is any gain worth its token cost?

The architecture itself is **not** the contribution: specialist agents + Bull/Bear debate +
risk synthesis is already published as **TradingAgents (arXiv:2412.20138)**. This project's
contribution is **leakage-free measurement, ablation, and NSE focus**. See the roadmap.

## 📅 Status
- [x] Project concept & architecture defined
- [x] Industry analysis (11 companies) — verified
- [x] Roadmap restructured around leakage-free evaluation
- [x] **Phase 1:** Foundation & walking skeleton (+ single-LLM baseline)
- [x] **Phase 2:** Evaluation harness & leakage-free protocol
- [x] **Phase 3:** Multi-agent system (specialists → reconciliation → debate → synthesiser)
- [x] **Phase 4:** Experiment tooling (`evaluate ablate`)
- [x] **Phase 5:** FastAPI + Streamlit dashboard, thesis report, defence slides

**All five phases are built and tested (79 tests, no API key required).**
The remaining work is *running the experiments*, which needs a Gemini key.

### Run it
```bash
python -m pytest tests/ -q                                     # 79 tests, offline
python -m tests.test_env                                       # environment report

# no API key needed
python -m forecast RELIANCE.NS --as-of 2025-06-02 --data-only  # evidence pack
python -m forecast AAPL --as-of 2025-06-02                     # rejected at the boundary
python -m evaluate run --system naive-momentum

# needs GEMINI_API_KEY in .env
python -m forecast TCS.NS --as-of 2025-06-02 --system multiagent
python -m evaluate recall-probe --start 2024-01-01 --end 2026-01-01
python -m evaluate ablate --repeats 3

# demo
uvicorn backend.api.main:app --reload      # API + WebSocket agent stream
cd web && npm install && npm run dev         # dashboard (API: uvicorn backend.api.main:app)
python -m scripts.warm_demo                # verify the demo replays from cache
```

### Documents (regenerated from code and results)
| Document | Command |
| :--- | :--- |
| `docs/BTP_Engineering_Report.docx` | `python -m scripts.make_docx` |
| `docs/BTP_Thesis_Report.docx` | `python -m scripts.make_thesis` |
| `docs/BTP_Defence_Slides.pptx` | `python -m scripts.make_slides` |

The thesis and slides read `results/` directly: anything not yet run is marked
**PENDING** rather than filled with a placeholder number. Run the experiments,
regenerate, and the tables fill themselves.

### When the API key arrives
```bash
# 1. locate the training cutoff — do this FIRST, it underpins every other claim
python -m evaluate recall-probe --start 2024-01-01 --end 2026-01-01
# 2. run every configuration
python -m evaluate ablate --repeats 3
# 3. regenerate the report and slides with real numbers
python -m scripts.make_thesis && python -m scripts.make_slides
# 4. the day before the defence
python -m scripts.warm_demo
```
