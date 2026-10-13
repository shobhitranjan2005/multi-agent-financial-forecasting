# Critical Limitations and Future Work

This document outlines three critical limitations of the current codebase that could serve as a starting point for a Master's thesis or future research.

## 1. Reliance on Brittle, Public Data Sources
The system relies entirely on free, public APIs (e.g., `yfinance` for OHLCV and fundamentals, GDELT for news). These sources are heavily rate-limited and often suffer from missing or messy data (e.g., missing index components like `^CNXAUTO` or spotty mid-cap coverage).

### News Sparsity and Vacuous Sentiment Ablation
- In preflight data auditing across all 136 candidate test cases (2025-04-01 to 2026-08-12), archival GDELT news headlines were empty (0 news items) for 100% of cases.
- Consequently, the Sentiment Specialist receives an empty headline corpus and defaults to neutral/uninformative sentiment signals across the test set.
- **Experimental Implication**: The leave-one-out ablation `multiagent-no-sentiment` is expected to be uninformative / vacuous by construction: dropping a specialist that received zero external evidence cannot meaningfully alter the pipeline's forecasts.
- **Future Work**: Integrate paid or archival Indian financial news feeds (e.g., Bloomberg, Refinitiv, Cogencis, or local newspaper archives with point-in-time publication timestamps).

## 2. Naive Trading Strategy and Benchmarking
The evaluation harness strictly measures 21-session "directional accuracy" and evaluates a simple long/short assumption against the benchmark (NIFTY 50). It completely ignores real-world trading frictions such as slippage, liquidity, taxes, and short-selling constraints.
- **Future Work**: Replace the static directional accuracy metric with a fully-fledged backtesting engine (e.g., `Backtrader` or `Zipline`) that simulates real portfolio construction, capital allocation, and risk management over continuous overlapping horizons.

## 3. Lack of Memory or Cross-Session State
Currently, the multi-agent system treats every forecast as a completely isolated event (a zero-shot DAG execution). The agents have no memory of their past predictions or mistakes, meaning they cannot iteratively learn from poor forecasts or adjust their internal biases.
- **Future Work**: Implement a memory bank or retrieval-augmented generation (RAG) system where the Risk Officer can retrieve past forecasts for the same ticker, evaluate why they failed, and actively penalize or reward specialists based on their historical reliability.
