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



