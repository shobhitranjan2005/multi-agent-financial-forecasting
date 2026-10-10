# PRD compliance audit (against `BTP_All_Phases_Work_Breakdown.pdf`)

Scope deviation accepted by the author: **India-only (NSE)** instead of worldwide. Reasons are in `BTP_All_Phases_Work_Breakdown.md`; confirm with the supervisor.

| PRD item | Status | Evidence / gap |
| :--- | :--- | :--- |
| Phase 1: structure, `__init__.py`, config, `.env` ignored, baseline, one specialist | Met | files present; `git check-ignore .env` |
| `requirements.txt` pinned | **Gap** | still a polluted `pip freeze` (torch, Django, celery, ...). Replace with the project's real dependencies |
| Cache: historical permanent, live 15 min, LLM sha256(prompt+model) | Met | `backend/cache.py` |
| `as_of` on every data tool; `as_of` leakage tests | Met | `tests/test_leakage.py` (30 tests) |
| Stooq fallback | Deviation (documented) | Stooq is dead; fallback is NSE bhavcopy archive |
| >= 2 years of history | Met | `PRICE_FETCH_DAYS` |
| Fundamentals point-in-time lag; strict nulls | Met | SEBI 45-day rule; `yfinance.info` withheld in past mode |
| News: GDELT, dedup, injection guard, `as_of` filter | Met (query bug fixed) | `NEWS_ALIASES`, cache key `news_v2` |
| Recall probe run and documented; test window AFTER cutoff | **NOT MET** | probe ran but cannot clear contamination; model card cutoff is March 2026 and the test set reaches back to 2024-01 |
| Frozen test set committed, never edited after results | Partial | `testset-frozen-v2` commit exists but **no git tag**, and it must be re-frozen after the contamination fix |
| Metrics: accuracy, MAE/MAPE, Brier, cost, naive baseline | Met (code) | `backend/eval/`; cost accounting must count cached calls |
| Phase 3 schemas (no `Field(default)`, propertyOrdering, parse failures counted) | Met | `schemas.py`, `llm.py` |
| 4 specialists, parallel; reconciliation gate with injected-fake test | Met | `tests/test_reconciliation.py` |
| Debate N=2 bounded; risk officer temp 0; `--no-debate` | Met | `debate.py`, `risk_officer.py`, `pipeline.py` |
| LangGraph distinct keys, reducer, SQLite checkpointer | Met | `pipeline.py` |
| Exit gate `python main.py <ticker> --as-of ...` | Met (added) | `main.py` delegates to `forecast.py` |
| Phase 4 experiments, ablations, calibration, repeats >= 3, failure analysis | **NOT MET** | only 5-case pilot runs, quarantined in `results/pilot_contaminated/` |
| Phase 4 exit gate: every report claim backed by a committed results file | **NOT MET** | no valid results exist |
| API: POST forecast, WS stream, GET price | Met | `backend/api/main.py` |
| Security: per-IP rate limit, explicit CORS, no secrets in frontend | Met | middleware + allowlist |
| Security: `pip audit` | **Not done** | run before submission |
| Dashboard: search, candlestick, live log, Bull-vs-Bear, forecast card + citations | Met (with deviations) | React instead of Streamlit; Plotly instead of TradingView Lightweight Charts |
| Demo: cached known-good run | Met | `results/demo/sample.json` (real recorded run) |
| Report (7 sections) and slides | **Stale** | generated from the old 20-case set; results sections correctly say PENDING; regenerate after final results |
| Phase 5 exit gate (clean clone runs; every number traces to a result file) | **NOT MET** | depends on Phase 4 |
