# PRD compliance audit (against `BTP_All_Phases_Work_Breakdown.pdf`)

Scope deviation accepted by the author: **India-only (NSE)** instead of worldwide (reasons in `BTP_All_Phases_Work_Breakdown.md`; confirm with the supervisor).
Model: `gemini-3.1-flash-lite` (documented knowledge cutoff January 2025). Frozen test set: tag `testset-frozen-v3`, 68 cases, 17 `as_of` dates (2025-04-01 to 2026-08-12), SHA-256 `0af68ccb2dc9de18b7b000422374bc25105c58ae41f021cd0a71a464b37e6e41`.

| PRD item | Status | Evidence / gap |
| :--- | :--- | :--- |
| Phase 1: structure, `__init__.py`, config, `.env` ignored, baseline, one specialist | Met | files present; `git check-ignore .env` |
| `requirements.txt` pinned | Met | rebuilt from the project's real imports (direct dependencies pinned); old full freeze archived in `docs/archive/`; `pip-audit` on the pinned lines: no known vulnerabilities (transitive dependencies not audited with `--no-deps`) |
| Cache: historical permanent, live 15 min, LLM sha256(prompt+model); cached calls keep original token/latency cost | Met | `backend/cache.py`, `backend/llm.py`, `tests/test_cost_accounting.py` |
| `as_of` on every data tool; leakage tests | Met | `tests/test_leakage.py` |
| Stooq fallback | Deviation (documented) | Stooq is dead; fallback is the NSE bhavcopy archive |
| Fundamentals point-in-time (SEBI 45-day lag) | Met (restatement leakage remains) | documented in `LIMITATIONS.md` |
| News: GDELT, dedup, injection guard, `as_of` filter, relevance rule | Met | `news_v5` cache key; fetched over plain HTTP because HTTPS handshakes reset on the author's machine (documented) |
| Recall probe run and documented; test window after cutoff | Met with documented limits | price probe uninformative (model declined every date); repo-rate event probe covers 5 of 17 test dates; the documented cutoff is the primary criterion; residual uncertainty stated in `LIMITATIONS.md` |
| Frozen test set committed, tagged, never edited after results | Met | tag `testset-frozen-v3`; draft-to-frozen subset rule recorded in `CHANGELOG_RESEARCH.md` |
| Pre-registered analysis plan, written before any LLM run | Met | `CHANGELOG_RESEARCH.md` |
| Metrics: accuracy, MAE/MAPE, Brier, cost, naive baselines, date-clustered CIs | Met | `backend/eval/`, `results/ablation_20261018_011029.md` |
| Phase 3 schemas, 4 specialists in parallel, reconciliation gate, bounded debate, risk officer, LangGraph + SQLite checkpointer | Met | `tests/test_reconciliation.py`, `tests/test_pipeline.py` |
| Exit gate `python main.py <ticker> --as-of ...` | Met | `main.py` delegates to `forecast.py` |
| Phase 4: primary comparison and debate ablation | Met (1 run per system, 68 cases) | `results/multiagent_*`, `baseline_*`, `multiagent-nodebate_*`, `naive-*`; verdict "no supported difference" |
| Phase 4: leave-one-out ablations | **Not completed** | halted by the free-tier daily quota (about 500 requests per day); `multiagent-no-technical` stopped at 48 of 68 cases |
| Phase 4: repeats >= 3 | **Not done** | LLM sampling variation is not quantified |
| Phase 4: calibration | Met | Brier, overconfidence gap, reliability table in the result files |
| Phase 4: qualitative failure analysis | Tabulated; interpretation pending | `scripts/make_failures.py`, `results/failures_*.md`; the author writes the interpretation |
| Phase 4 exit gate: every report claim traces to a committed result file | Met for completed runs | `docs/RESULTS_MAP.md` |
| API (POST forecast, WS stream, GET price); per-IP rate limit; explicit CORS; no secrets in the frontend | Met | `backend/api/main.py` |
| Security: `pip-audit`, `npm audit` | Met | pinned requirements: none known; `npm audit`: 0 vulnerabilities |
| Dashboard: search, candlestick, live log, Bull-vs-Bear, forecast card with citations | Met (with deviations) | React instead of Streamlit; Plotly instead of TradingView Lightweight Charts; screenshots in `docs/screenshots/` |
| Demo: cached known-good run | Met | `results/demo/sample.json` |
| Report and slides generated from committed results | Met | `scripts/make_thesis.py`, `scripts/make_slides.py` (regenerate after any new results) |
| Phase 5 exit gate: clean clone runs; every number traces to a result file | Met except one test | `pip install -r requirements.txt`, then `pytest`: one runner test needs internet access (realised outcomes) |
