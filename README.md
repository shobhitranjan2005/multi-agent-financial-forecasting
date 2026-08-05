# Financial Forecasting by Multi-AI Agent System

> **B.Tech Capstone Project (BTP)**

## 📌 Project Overview
This project implements an autonomous **Multi-AI Agent System** for stock market trend prediction, fundamental valuation, sentiment analysis, and risk-managed financial forecasting.

For the full detailed project breakdown, system architecture, agent roles, and step-by-step implementation plan, please see:
👉 **[PROJECT_IDEA_AND_ROADMAP.md](file:///c:/Users/frien/OneDrive/Desktop/BTP/PROJECT_IDEA_AND_ROADMAP.md)**

---

## 🤖 System Architecture Highlights
- **Technical Analysis Agent**: Price trends & momentum indicators (RSI, MACD, Moving Averages).
- **Fundamental Analysis Agent**: Company health metrics, earnings, financial statements.
- **Sentiment & News Agent**: Scrapes financial news headlines & SEC filings.
- **Macroeconomic Agent**: Evaluates interest rates, inflation, sector trends.
- **Bull vs. Bear Debate Engine**: Adversarial reasoning between optimistic & cautious perspectives.
- **Chief Risk Officer & Synthesizer**: Final financial forecast signal, target price range, and confidence score.

---

## 🛠️ Planned Stack
- **Language**: Python 3.10+
- **Agent Orchestration**: `LangGraph` / `CrewAI`
- **LLM Engine**: Gemini API (`gemini-flash-latest` — Gemini 3.5 / 3.6 Flash class)
- **Data APIs**: `yfinance` (primary — **must be cached**, see roadmap), Stooq (keyless fallback), Finnhub
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
- [ ] **Phase 1:** Foundation & walking skeleton (+ single-LLM baseline)
- [ ] **Phase 2:** Evaluation harness & leakage-free protocol
- [ ] **Phase 3:** Multi-agent system (specialists → debate → synthesiser)
- [ ] **Phase 4:** Experiments & ablation
- [ ] **Phase 5:** Dashboard, report & defence
