# Results Map

**Status**: Verified experimental evaluation over the frozen, point-in-time, leakage-free test set (`data/testset.json`, 68 post-cutoff cases, SHA-256 `0af68ccb2dc9de18b7b000422374bc25105c58ae41f021cd0a71a464b37e6e41`). All LLM experiments evaluated against `gemini-3.1-flash-lite` with `git_dirty: false`.

---

## 1. Thesis Research Questions & Evidence Mapping

| Research Question | Evidence Files | Commit | Sample Size | Primary Metric / Finding | Confirmatory Test & Pre-Registered Verdict |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **Q1: Primary Comparison**<br/>Does multi-agent forecasting beat a single-LLM baseline? | [`results/multiagent_20261017_125750.json`](../results/multiagent_20261017_125750.json)<br/>[`results/baseline_20261017_025259.json`](../results/baseline_20261017_025259.json) | `dad6c42`<br/>`4944455` | $N=68$ | Multi-agent: **50.00%**<br/>Baseline: **41.18%**<br/>Point Delta: **+8.82 pts** | **95% Date-Block Clustered CI: [-4.41, +22.06] pts** (includes 0).<br/>McNemar exact $p=0.2863$.<br/>**Verdict: No supported difference** (pre-registered decision rule: CI includes 0; point differences are not described as improvements). |
| **Q2: Debate Ablation**<br/>Does the debate stage earn its cost vs no-debate? | [`results/multiagent_20261017_125750.json`](../results/multiagent_20261017_125750.json)<br/>[`results/multiagent-nodebate_20261017_160219.json`](../results/multiagent-nodebate_20261017_160219.json) | `dad6c42`<br/>`e907b7e` | $N=68$ | With debate: **50.00%**<br/>Without debate: **45.59%**<br/>Point Delta: **+4.41 pts**<br/>Token cost ratio: **2.14x** (19,696 vs 9,186) | **95% Date-Block Clustered CI: [-2.94, +13.24] pts** (includes 0).<br/>McNemar exact $p=0.5488$.<br/>**Verdict: No supported difference** in accuracy attributable to debate stage, despite 2.14x token overhead. |
| **Q3: Leave-One-Out Ablations**<br/>Which specialists contribute to accuracy? | `results/multiagent-no-*.json` | _stopped_ | — | — | **Not completed**: Halted due to daily Gemini request quota exhaustion on Google AI Studio Free Tier (recorded in `results/runner_progress.json`). |
| **Benchmark vs Naive Baselines**<br/>Does either system beat simple non-LLM rules? | [`results/naive-momentum_20261017_013505.json`](../results/naive-momentum_20261017_013505.json)<br/>[`results/naive-alwaysup_20261017_022717.json`](../results/naive-alwaysup_20261017_022717.json) | `a812b6f`<br/>`4bf044d` | $N=68$ | Momentum: **48.53%**<br/>Always-Up: **41.18%** | Multi-agent vs Momentum: $\Delta = +1.47$ pts (95% CI [-8.82, +10.29] pts, **no supported difference**).<br/>Multi-agent vs Always-Up: $\Delta = +8.82$ pts (95% CI [-4.41, +22.06] pts, **no supported difference**). |

---

## 2. Descriptive Findings: Base Rates, Bias & Calibration

- **Market Base Rate**: Over the 68 post-cutoff cases, **40 of 68 outcomes (58.82%) were "down"** and 28 of 68 (41.18%) were "up". An uninformative **always-down rule would score 58.82% directional accuracy**, outperforming all evaluated models.
- **Single-LLM Bullish Bias**: The baseline predicted **"up" on 66 of 68 cases (97.06%)**, predicting "down" only twice. Its 41.18% accuracy directly reflects the 41.18% "up" base rate of the market period.
- **Multi-Agent Bias Moderation**: The multi-agent debate and risk synthesis moderated this bias to **44 "up" calls and 24 "down" calls (64.71% up)**, while `multiagent-nodebate` produced 55 "up" calls (80.88% up).
- **Brier No-Skill Reference Floor**: An uncalibrated 50/50 probability forecast yields a Brier score of **0.2500**. Realised Brier scores:
  - `multiagent`: **0.2593** (overconfidence gap: 10.69 pts)
  - `naive-momentum`: **0.2601** (overconfidence gap: 5.66 pts)
  - `naive-alwaysup`: **0.2776** (overconfidence gap: 18.82 pts)
  - `baseline`: **0.2787** (overconfidence gap: 18.23 pts)
  - `multiagent-nodebate`: **0.2880** (overconfidence gap: 19.48 pts)
- **Paired Brier differences** (date-clustered 95% CI, 10,000 resamples): `multiagent` − `baseline` = −0.0194 [−0.0471, +0.0085] (no supported difference); `multiagent` − `multiagent-nodebate` = −0.0287 [−0.0533, −0.0057] (excludes 0, but a secondary, exploratory comparison not corrected for multiple testing: suggestive only). The `multiagent` Brier 95% CI [0.234, 0.282] includes the 0.2500 no-skill reference.

---

## 3. Computational Cost and Latency Accounting

| System | Tokens / Forecast | LLM Calls / Forecast | Sec / Forecast | Tokens vs Baseline | Wall Time vs Baseline |
| :--- | ---: | ---: | ---: | ---: | ---: |
| `naive-momentum` | 0.0 | 0.0 | 0.06s | 0.00x | 0.01x |
| `naive-alwaysup` | 0.0 | 0.0 | 0.04s | 0.00x | 0.01x |
| `baseline` | 4,068.4 | 1.0 | 6.49s | 1.00x | 1.00x |
| `multiagent-nodebate` | 9,185.6 | 4.9 | 7.46s | 2.26x | 1.15x |
| `multiagent` | 19,696.2 | 9.0 | 53.63s | 4.84x | 8.26x |

---

## 4. Methodological Compliance & Evidence Integrity

- **Leakage Prevention**: All features constructed strictly as of session close $t$; news queried through the end of the `as_of` date (inclusive; articles first seen after that date are dropped); prices queried through the `as_of` session close.
- **Model Training Cutoff**: Pinned snapshot `gemini-3.1-flash-lite` evaluated on test cases from 2025-04-01 to 2026-08-12 (17 `as_of` dates), all at least two months after the documented January 2025 training cutoff.
- **Date Clustering**: All confidence intervals computed via date-block bootstrap (resampling entire dates, not individual stocks) to respect cross-ticker market correlations.
- **Reproducibility**: All runs logged in `results/*.csv`, `results/*.json`, and `results/*.md`, with test set LF SHA-256 and git commit hash embedded in the provenance metadata.
