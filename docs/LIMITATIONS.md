# Critical Limitations and Future Work

This document outlines three critical limitations of the current codebase that could serve as a starting point for a Master's thesis or future research.

## 1. Reliance on Brittle, Public Data Sources
The system relies entirely on free, public APIs (e.g., `yfinance` for OHLCV and fundamentals, GDELT for news). These sources are heavily rate-limited and often suffer from missing or messy data (e.g., missing index components like `^CNXAUTO` or spotty mid-cap coverage).
- **Future Work**: Integrate institutional-grade financial data feeds (like Bloomberg, Refinitiv, or AlphaVantage) to ensure robust, highly available data, and expand coverage beyond just the NIFTY 50.

## 2. Naive Trading Strategy and Benchmarking
The evaluation harness strictly measures 21-session "directional accuracy" and evaluates a simple long/short assumption against the benchmark (NIFTY 50). It completely ignores real-world trading frictions such as slippage, liquidity, taxes, and short-selling constraints.
- **Future Work**: Replace the static directional accuracy metric with a fully-fledged backtesting engine (e.g., `Backtrader` or `Zipline`) that simulates real portfolio construction, capital allocation, and risk management over continuous overlapping horizons.

## 3. Lack of Memory or Cross-Session State
Currently, the multi-agent system treats every forecast as a completely isolated event (a zero-shot DAG execution). The agents have no memory of their past predictions or mistakes, meaning they cannot iteratively learn from poor forecasts or adjust their internal biases.
- **Future Work**: Implement a memory bank or retrieval-augmented generation (RAG) system where the Risk Officer can retrieve past forecasts for the same ticker, evaluate why they failed, and actively penalize or reward specialists based on their historical reliability.
