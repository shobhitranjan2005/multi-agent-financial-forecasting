# Critical Limitations and Future Work

This document outlines three critical limitations of the current codebase that could serve as a starting point for a Master's thesis or future research.

## 1. Reliance on Brittle, Public Data Sources
The system relies entirely on free, public APIs (e.g., `yfinance` for OHLCV and fundamentals, GDELT for news). These sources are heavily rate-limited and often suffer from missing or messy data (e.g., missing index components like `^CNXAUTO` or spotty mid-cap coverage).

### News Evidence and Protocol Disclosure
- **Archival Coverage**: GDELT DOC API provides point-in-time archival Indian financial press headlines (e.g., ~10–25 articles per 30-day lookback for liquid NSE constituents).
- **Protocol Configuration**: Remote host `api.gdeltproject.org:443` forcibly closes TLS connections on Windows (`[WinError 10054]` / `curl (35)` TLS handshake reset). News retrieval operates via `GDELT_ALLOW_HTTP=1` to connect via HTTP/1.1 port 80.
- **Operator Syntax & Cache Invalidation**: Query syntax uses FIPS 10-4 country code `sourcecountry:IN` (replacing the literal string `sourcecountry:india`). Cache keys were bumped to `news_v3` to ensure no stale empty responses from previous queries are reused.
- **Integrity Safeguards**:
  - *No Credentials*: Communication is keyless with standard browser user-agent headers.
  - *Prompt Injection Guard*: All retrieved headlines are treated as untrusted text, enclosed within `<headlines>` tags, and subjected to prompt-level injection defense rules.
  - *Data Provenance*: Evaluation results record the SHA-256 hash of all cached news payloads in their provenance block.
- **Future Work**: Evaluate dedicated paid enterprise financial news feeds (e.g., Bloomberg, Refinitiv, Cogencis) to eliminate public API rate-limiting constraints.

## 2. Naive Trading Strategy and Benchmarking
The evaluation harness strictly measures 21-session "directional accuracy" and evaluates a simple long/short assumption against the benchmark (NIFTY 50). It completely ignores real-world trading frictions such as slippage, liquidity, taxes, and short-selling constraints.
- **Future Work**: Replace the static directional accuracy metric with a fully-fledged backtesting engine (e.g., `Backtrader` or `Zipline`) that simulates real portfolio construction, capital allocation, and risk management over continuous overlapping horizons.

## 3. Lack of Memory or Cross-Session State
Currently, the multi-agent system treats every forecast as a completely isolated event (a zero-shot DAG execution). The agents have no memory of their past predictions or mistakes, meaning they cannot iteratively learn from poor forecasts or adjust their internal biases.
- **Future Work**: Implement a memory bank or retrieval-augmented generation (RAG) system where the Risk Officer can retrieve past forecasts for the same ticker, evaluate why they failed, and actively penalize or reward specialists based on their historical reliability.
