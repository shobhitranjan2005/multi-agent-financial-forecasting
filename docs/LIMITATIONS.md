# Critical Limitations and Future Work

This document outlines key methodological and engineering limitations of the current codebase that serve as a starting point for future research and academic scrutiny.

---

## 1. Reliance on Brittle, Public Data Sources
The system relies entirely on free, public APIs (e.g., `yfinance` for OHLCV and fundamentals, GDELT for news). These sources are heavily rate-limited and often suffer from missing or messy data (e.g., missing index components like `^CNXAUTO` or spotty mid-cap coverage).

### News Evidence and Protocol Disclosure
- **Archival Coverage**: GDELT DOC API provides point-in-time archival Indian financial press headlines (e.g., ~10–25 articles per 30-day lookback for liquid NSE constituents).
- **Protocol Configuration & Sequence**: Remote host `api.gdeltproject.org:443` forcibly closes TLS connections on Windows (`[WinError 10054]` / `curl (35)` TLS handshake reset). Consequently, news is fetched over plain HTTP because HTTPS handshakes were reset on this machine; data is public and keyless; each payload is SHA-256 hashed. The fallback is controlled by `GDELT_ALLOW_HTTP=1` (defaulting to HTTPS when unset).
- **Operator Syntax & Cache Invalidation**: Query syntax uses FIPS 10-4 country code `sourcecountry:IN` and `sourcelang:eng`. Cache keys are bumped (to `news_v5`) to ensure no stale or unfiltered responses are ever reused.
- **Headline Relevance & Entity Matching Rules**:
  - *Title-Only Relevance Rule*: The deterministic relevance filter evaluates article titles only; articles that mention a target firm only in the body text or lead paragraph are discarded by construction to avoid associative false positives.
  - *Larsen & Toubro Disambiguation*: The L&T query strictly matches the phrase "Larsen and Toubro" (and title relevance filters enforce explicit "l&t", "larsen & toubro", or "larsen and toubro"), rejecting collisions with military/administrative titles ("Lt Governor", "Lt Gen").
- **Integrity Safeguards**:
  - *No Credentials*: Communication is keyless with standard browser user-agent headers.
  - *Prompt Injection Guard*: All retrieved headlines are treated as untrusted text, enclosed within `<headlines>` tags, and subjected to prompt-level injection defense rules.
  - *Data Provenance*: Evaluation results record the SHA-256 hash of all cached news payloads in their provenance block.
- **Future Work**: Evaluate dedicated paid enterprise financial news feeds (e.g., Bloomberg, Refinitiv, Cogencis) to eliminate public API rate-limiting constraints.

---

## 2. Naive Trading Strategy and Benchmarking
The evaluation harness strictly measures 21-session "directional accuracy" and evaluates a simple long/short assumption against the benchmark (NIFTY 50). It completely ignores real-world trading frictions such as slippage, liquidity, taxes, and short-selling constraints.
- **Future Work**: Replace the static directional accuracy metric with a fully-fledged backtesting engine (e.g., `Backtrader` or `Zipline`) that simulates real portfolio construction, capital allocation, and risk management over continuous overlapping horizons.

---

## 3. Lack of Memory or Cross-Session State
Currently, the multi-agent system treats every forecast as a completely isolated event (a zero-shot DAG execution). The agents have no memory of their past predictions or mistakes, meaning they cannot iteratively learn from poor forecasts or adjust their internal biases.
- **Future Work**: Implement a memory bank or retrieval-augmented generation (RAG) system where the Risk Officer can retrieve past forecasts for the same ticker, evaluate why they failed, and actively penalize or reward specialists based on their historical reliability.

---

## 4. Sample Size, Clustered Variance, and Statistical Power
The evaluation suite evaluates 68 post-cutoff cases distributed across 17 distinct `as_of` dates (4 tickers per date). Because equities sharing an `as_of` date experience common macroeconomic shocks and market regimes, individual cases are statistically dependent.
- **Clustered Uncertainty**: Resampling entire date blocks via date-block bootstrap reveals wide 95% confidence intervals (e.g., $\Delta = +8.82$ percentage points between multi-agent and baseline has a 95% CI of `[-4.41, +22.06]` pts).
- **Pre-Registered Decision Rule**: Because the date-clustered confidence interval spans zero, the pre-registered protocol mandates that this finding be reported as **"no supported difference"**; point differences cannot be claimed as improvements.
- **Future Work**: Expand evaluation to several hundred dates across multi-year cycles to narrow the date-clustered confidence intervals and test whether multi-agent systems demonstrate statistically significant separation from single models.

---

## 5. Descriptive Findings: Base Rates, Bias, and Reference Floors
- **Market Base Rate**: Over the 68 frozen test cases, **40 of 68 outcomes (58.82%) were "down"** and 28 of 68 (41.18%) were "up". Consequently, an uninformative **always-down rule would score 58.82% directional accuracy**, outperforming both the single-LLM baseline (41.18%) and the multi-agent system (50.00%).
- **Baseline Bullish Bias**: The single-LLM baseline (`baseline`) predicted **"up" on 66 of 68 cases (97.06%)**, predicting "down" only twice. Its 41.18% directional accuracy was entirely an artifact of the market's 41.18% "up" base rate.
- **Multi-Agent Moderation**: The multi-agent debate and risk officer moderated this bias to **44 "up" calls and 24 "down" calls (64.71% up)**.
- **Brier No-Skill Reference Floor**: An uncalibrated 50/50 probability forecast yields an expected **Brier score of exactly 0.2500**. Realised Brier scores were:
  - `multiagent`: **0.2593** (overconfidence gap: 10.69 pts)
  - `naive-momentum`: **0.2601** (overconfidence gap: 5.66 pts)
  - `naive-alwaysup`: **0.2776** (overconfidence gap: 18.82 pts)
  - `baseline`: **0.2787** (overconfidence gap: 18.23 pts)
  - `multiagent-nodebate`: **0.2880** (overconfidence gap: 19.48 pts)

---

## 6. Free-Tier Quota Constraints & Execution Scope
The research protocol was executed strictly under Google AI Studio Free Tier (no billing).
- **Daily Quota Ceiling**: With free-tier request quotas, multi-agent systems with debate (which require ~11 calls per forecast) consumed substantial quota, requiring automated 30-minute sleep pauses until midnight Pacific resets.
- **Ablation Scope**: Round 1 completed `naive-momentum`, `naive-alwaysup`, `baseline`, `multiagent`, and `multiagent-nodebate`. Leave-one-out specialist ablations (`multiagent-no-technical`, `multiagent-no-fundamental`, `multiagent-no-sentiment`, `multiagent-no-macro`) were halted due to daily quota exhaustion.
