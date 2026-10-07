# Multi-Agent Financial Forecasting: Results Map

This document serves as the central directory mapping the key claims of the thesis to the exact artifacts, commits, and reproduction commands that validate them.

| Thesis Claim | Result File | Git Commit | Command to Reproduce |
| :--- | :--- | :--- | :--- |
| **Claim 1: The Multi-Agent System performs similarly to a Single-LLM baseline** | `results/ablation_*.md` | `HEAD` | `python -m evaluate ablate` |
| **Claim 2: The Bull/Bear debate stage does not justify its cost** | `results/ablation_*.md` | `HEAD` | `python -m evaluate ablate` |
| **Claim 3: The Macro Specialist is the only agent contributing unique predictive value** | `results/ablation_*.md` | `HEAD` | `python -m evaluate ablate` |
| **Claim 4: Qualitative Failures are driven by data availability and fundamental bias** | `results/failures_*.md` | `HEAD` | `python backend/eval/failures.py` |

*Note: Due to API rate limiting and compute constraints, final 160-case runs must be executed by the researcher prior to submitting the thesis.*
