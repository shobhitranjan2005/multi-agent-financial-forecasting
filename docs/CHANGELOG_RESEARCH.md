# Research Changelog

This document tracks changes that could affect the validity or comparability of experimental results in the multi-agent equity forecasting thesis.

## Disclosure: Pilot Runs and Test Set Re-freezing

### Quarantined Pilot Runs
- Previous runs consisted exclusively of exploratory 5-case pilot executions on 2024 dates (`2024-01-15` to `2024-02-12`).
- These pilot runs were inside the model's training window, run on uncommitted exploratory code, and had cache-distorted cost numbers.
- They have been strictly quarantined in `results/pilot_contaminated/` and are not cited in the thesis or results.

### Invalidation of `testset-frozen-v2`
- **Date Generated**: 2026-10-07
- **SHA-256 Hash**: `293615BBF52DF35A983A8C2367C826EEFB201C66F095DEE13130E3EDCA280527`
- **Invalidation Reason**: The entry previously claimed the window was "post-cutoff", but the test set covered `2024-01-01` through `2026-06-23`. Because model knowledge cutoffs extend to at least January 2025 (and up to March 2026 for 3.5 models), dates prior to the cutoff were contaminated. No git tag was ever created for v2.
- **Legitimacy of Re-Freezing**: No valid completed experiment exists on the v2 set, and no model or agent prompt was tuned on test results. Therefore, establishing a clean, untuned, post-cutoff test set is fully legitimate and essential to thesis validity.

### Forthcoming `testset-frozen-v3`
- **Model**: `gemini-3.1-flash-lite` (GA, released May 7, 2026; documented knowledge cutoff January 2025; deprecation May 7, 2027).
- **Window**: `2025-04-01` to `2026-09-09` (strictly $\ge$ January 2025 cutoff + 2 months, up to today − 21 trading sessions).
- **Spacing**: 17 dates spaced by $\ge 21$ trading sessions (approximately 4 calendar weeks apart). This ensures **non-overlapping 21-session evaluation horizons**, eliminating cross-date return autocorrelation in evaluation metrics.
- **Dual Contamination Probes**:
  - Primary criterion: documented model cutoff (January 2025).
  - Secondary empirical signal 1: exact NIFTY 50 index close tolerance ($\le 0.5\%$).
  - Secondary empirical signal 2: dated RBI monetary policy repo rate decisions. Note: verified against official RBI decisions through `2025-08-31` (`macro.RBI_VERIFIED_THROUGH`), which covers 5 of the 17 test dates; dates beyond `2025-08-31` (12 dates) are unverified against official sources, and the documented knowledge cutoff remains the primary criterion.
- **Seed Universe**: Liquid NSE large-caps point-in-time verified against daily bhavcopy (`TATAMOTORS.NS` excluded due to historical Yahoo Finance data gap).
- **Candidate Test Set Draft Build**:
  - **Draft Path**: `data/testset_draft_v3.json` (`status: "UNFROZEN_DRAFT"`). Stale `FROZEN` line removed; pending user review prior to freezing.
  - **Exact Build Command**:
    ```bash
    python -m evaluate build-testset --start 2025-04-01 --end 2026-09-09 --dates 17 --tickers 8 --seed 20260806 --out data/testset_draft_v3.json --overwrite
    ```
  - **Inclusion Rules**:
    1. Date window: `2025-04-01` to `2026-09-09` (strictly $\ge$ model cutoff + 2 months, up to today − 21 trading sessions).
    2. Spacing: strictly $\ge 21$ NSE trading sessions apart (completely non-overlapping evaluation windows).
    3. Point-in-time universe: checked against official NSE Cash Market Bhavcopy for each session.
    4. Sufficient history: $\ge 200$ trading sessions prior price history verified for every candidate ticker (about 10 months, needed for SMA-200, RSI, MACD) without NaN.
  - **Exclusion Rules**:
    1. `TATAMOTORS.NS` excluded due to corporate demerger causing missing Yahoo Finance historical records.
    2. Any constituent not actively traded on NSE on that specific session is excluded.
    3. Strictly zero conditioning on forecasts, predictions, volatility, or realized returns.

### GDELT Data Protocol, Relevance Filtering & news_v4 Bump
- **Sequence & Transport Disclosure**: Preliminary testing ran plain HTTP over port 80 prior to explicit user sign-off due to persistent Windows TLS handshake resets on port 443 (`[WinError 10054]`). Retroactively approved strictly for GDELT under the mandated safeguards: default off (`GDELT_ALLOW_HTTP=0`), public and keyless, untrusted headline containment under prompt injection guard, and payload SHA-256 provenance hashing ("news fetched over plain HTTP because HTTPS handshakes were reset on this machine; data is public and keyless; each payload SHA-256 hashed").
- **FIPS Country and Language Operator**: Updated GDELT DOC API operator syntax from literal `sourcecountry:india` to standard FIPS 10-4 country code `sourcecountry:IN` and added `sourcelang:eng` with `maxrecords=250` (GDELT maximum).
- **Deterministic Headline Relevance Rule**:
  - Implemented strict title-level filtering to eliminate broad market roundups ("Sensex crashes") and incidental mentions (e.g. sports partnerships).
  - Audited all candidate stock aliases for common-word collisions. Disallowed bare `"reliance"` (requires `"reliance industries"`, `"ril"`, `"reliance jio"`, `"jio platforms"`, `"reliance retail"`). Disallowed bare `"power grid"` (requires `"power grid corporation"`, `"pgcil"`, `"powergrid"`). Required `"nestle india"` instead of bare `"nestle"`. Enforced financial context for bank acronyms (`sbi`, `hdfc`, `icici`, `kotak`) and ambiguous tickers (`itc`, `lt`, `titan`).
  - Unit tests enforce positive matches and negative rejections (including "India's reliance on Russian oil" and "US power grid collapses").
  - Post-filter deduplication: deterministically retains top 15 newest headlines.
- **Cache Key Bump to `news_v4`**: Bumped news cache key to `news_v4_{lookback}d` so all backtest cases strictly reflect the audited relevance rules.
- **Pacing & Resumable Worker**: Paced prefetch worker (`backend/eval/prefetch.py`) with $\ge 18$s spacing, 90s sleep on HTTP 429, skipping cached cases, and never caching failures.

### Pre-Registration: Sentiment Ablation Informativeness Criterion & news_v5 Bump
- **Pre-Registration Statement**:
  > “The sentiment leave-one-out ablation is called informative only if at least 70% of test cases have at least 5 relevant headlines; otherwise it is reported as uninformative by construction. Relevant means passing the committed title rule.”
- **Rule Tightening & Collision Audits**:
  - **Larsen & Toubro (`LT.NS`)**: Removed bare `lt` conditional alias completely. L&T must strictly match `l&t`, `larsen & toubro`, or `larsen and toubro`. Added negative test verifying `"Lt Governor approves construction contract"` is rejected. GDELT query updated to clean phrase without bare ampersands.
  - **JSW Steel (`JSWSTEEL.NS`)**: Stricter matching requiring `jsw steel` or `jsw` plus `steel` within 3 words, with explicit exclusion of sister entities and project divisions (`jsw infrastructure`, `jsw infra`, `jsw utkal steel`, `jsw energy`, etc.). Added negative test verifying `"JSW Infrastructure completes slurry pipeline business from JSW Utkal Steel for around Rs 1 , 617 crore"` is rejected.
  - **Banking Sister-Company Exclusions**:
    - `HDFCBANK.NS`: Rejects `HDFC Life`, `HDFC AMC`, `HDFC ERGO`, `HDFC Securities` unless `HDFC Bank` is explicitly present.
    - `SBIN.NS`: Rejects `SBI Card`, `SBI Life`, `SBI Mutual Fund`, `SBI General Insurance` unless `State Bank of India` is explicitly present.
    - `ICICIBANK.NS`: Rejects `ICICI Prudential`, `ICICI Lombard`, `ICICI Securities` unless `ICICI Bank` is explicitly present.
    - `KOTAKBANK.NS`: Rejects `Kotak Life`, `Kotak AMC` unless `Kotak Mahindra Bank` or `Kotak Bank` is explicitly present.
    - `AXISBANK.NS`: Removed bare `axis` conditional; strictly requires `Axis Bank`, eliminating collisions with geometry, geography, or `Axis Mutual Fund`.
  - **Conglomerates & Group Sister Companies**:
    - `BAJFINANCE.NS`: Rejects `Bajaj Auto`, `Bajaj Electricals`, `Bajaj Consumer` unless `Bajaj Finance` or `Bajaj Finserv` is explicitly present.
    - `TATASTEEL.NS`: Rejects `Tata Motors`, `Tata Power`, `Tata Chemicals`, `TCS` unless `Tata Steel` is explicitly present.
    - `RELIANCE.NS`: Rejects ADAG sister companies (`Reliance Power`, `Reliance Infrastructure`, `Reliance Capital`) unless `Reliance Industries`, `RIL`, `Reliance Jio`, or `Reliance Retail` is explicitly present.
  - **Common-Word & Acronym Disambiguations**:
    - `TITAN.NS`: Rejects idioms (`tech titan`, `industry titan`, `global titan`, `clash of the titans`, `titan submersible`) unless `Titan Company` or jewellery/watch brands (`Tanishq`, `Fastrack`, `CaratLane`) are present.
    - `ITC.NS`: Rejects GST Input Tax Credit claims ("fake ITC", "ITC claims under GST rules") unless company context is present.
    - `MARUTI.NS`: Rejects religious/temple contexts ("Maruti temple on Hanuman Jayanti").
    - `NESTLEIND.NS`: Rejects global Swiss/European corporate stories without Indian context.
    - `TCS.NS`: Rejects Tax Collected at Source under Income Tax/LRS ("20% TCS on overseas tour packages under LRS") unless IT services / Tata context is present.
    - `NTPC.NS`: Rejects Indian Railway Recruitment Board exam headlines ("RRB NTPC admit card").
    - `POWERGRID.NS`: Rejects foreign power grids ("US power grid collapses", "Texas power grid").
    - `SUNPHARMA.NS`: Rejects weather ("bright sun") and `Sun Life Financial`.
    - `ASIANPAINT.NS`: Rejects "Asian markets".
- **Cache Key Bump to `news_v5`**:
  - Bumped news cache key to `news_v5_{lookback_days}d` (`news_v5_30d`) across `backend/tools/news_sentiment.py`, `backend/eval/provenance.py`, and `backend/eval/prefetch.py`. Any previously cached entries under `news_v4` are discarded, ensuring all downstream backtest data strictly obeys the committed, audited rules.
