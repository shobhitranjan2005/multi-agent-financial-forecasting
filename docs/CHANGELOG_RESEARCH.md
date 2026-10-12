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
  - Secondary empirical signal 2: dated RBI monetary policy repo rate decisions. Note: verified against official RBI decisions through `2025-08-31` (`macro.RBI_VERIFIED_THROUGH`); dates beyond this are left unverified against official sources and rely on the documented cutoff.
- **Seed Universe**: Liquid NSE large-caps point-in-time verified against daily bhavcopy (`TATAMOTORS.NS` excluded due to historical Yahoo Finance data gap).


