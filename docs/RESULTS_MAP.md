# Multi-Agent Financial Forecasting: Results Map

This document summarizes the outcomes of the ablation study comparing the multi-agent system against single-LLM and naive baselines for the Bachelor's thesis. Note: The current numbers reflect a 5-case pre-run evaluation.

## 1. Did the Multi-Agent System beat the Single-LLM Baseline?
- **Accuracy**: Both the `multiagent` system and the single-LLM `baseline` achieved a directional accuracy of **60.0%**.
- **Cost**: The `multiagent` system consumed **~17,092 tokens/forecast** and took **~42.5s** per forecast, compared to the `baseline` which used **~3,580 tokens** and took **~8.6s**.
- **Conclusion**: The multi-agent architecture did not yield an improvement in directional accuracy over the single-LLM baseline in this limited run, despite consuming nearly 5x the computational resources.

## 2. Did the Bull/Bear Debate Help?
- **Delta**: Comparing `multiagent` (with debate) to `multiagent-nodebate`, the directional accuracy moved by **+0.00 points** (both at 60%). 
- **Cost**: The debate stage was highly expensive. The full system required **17,092 tokens** and **42.5s**, while skipping the debate (`multiagent-nodebate`) required only **2,379 tokens** and **6.99s**.
- **Conclusion**: The debate costs **~7.1x more tokens** and **~6.1x more wall time** without any measurable benefit in predictive power. The debate does not earn its cost.

## 3. Which Specialist was Most Important?
Using a leave-one-out (LOO) ablation approach:
- Removing the **macro** specialist (`multiagent-no-macro`) resulted in a significant accuracy drop of **-20.0 points** (down to 40%).
- Removing **technical**, **fundamental**, or **sentiment** specialists yielded a **0.0 point delta**, meaning they contributed no additional predictive value over the other agents combined.
- **Conclusion**: The **macro analyst** (assessing RBI stance, crude oil, USD/INR, sector rotation) was the sole specialist that provided a measurable lift to the system's accuracy. The others paid for tokens without earning them.
