"""Fundamental Analyst Agent.

Specialist agent for valuation metrics, quarterly growth, financial health,
and SEBI filing lag verification. Returns a FundamentalReport Pydantic model.
"""
from __future__ import annotations

import json
from datetime import datetime

from backend.agents.schemas import Citation, FundamentalReport
from backend.cache import get_cache
from backend.config import Config
from backend.tools import calendar_nse, fundamentals, tickers


def analyze_fundamental(
    ticker: str,
    as_of: str | datetime,
    nonce: str = "",
) -> FundamentalReport:
    """Run fundamental analysis for `ticker` as of `as_of` date."""
    resolved_ticker = tickers.resolve(ticker)
    if isinstance(as_of, str):
        as_of_dt = datetime.fromisoformat(as_of)
    else:
        as_of_dt = as_of

    as_of_session = calendar_nse.previous_trading_day(as_of_dt)
    as_of_str = as_of_session.isoformat()

    f_data = fundamentals.get_fundamentals(resolved_ticker, as_of_str)

    pe = f_data.get("pe_ratio")
    pb = f_data.get("pb_ratio")
    ev_ebitda = f_data.get("ev_ebitda")
    roe = f_data.get("roe_pct")
    de = f_data.get("debt_to_equity")
    rev_growth = f_data.get("revenue_growth_yoy")
    margin = f_data.get("net_margin_pct")

    prompt = f"""You are a Fundamental Equity Analyst evaluating an Indian listed company on NSE.
Ticker: {resolved_ticker}
As-Of Date: {as_of_str}

Point-in-Time Fundamentals (SEBI LODR 45-day filing lag rule applied):
{json.dumps(f_data, indent=2)}

Task: Analyze valuation and health metrics, and output a JSON matching this exact structure:
{{
  "ticker": "{resolved_ticker}",
  "as_of": "{as_of_str}",
  "valuation_score": float (-10.0 extremely overvalued to +10.0 extremely undervalued),
  "health_rating": "Strong" | "Moderate" | "Weak",
  "pe_ratio": {pe if pe is not None else "null"},
  "pb_ratio": {pb if pb is not None else "null"},
  "ev_ebitda": {ev_ebitda if ev_ebitda is not None else "null"},
  "roe_pct": {roe if roe is not None else "null"},
  "debt_to_equity": {de if de is not None else "null"},
  "revenue_growth_yoy": {rev_growth if rev_growth is not None else "null"},
  "net_margin_pct": {margin if margin is not None else "null"},
  "valuation_summary": "string summary",
  "citations": [
    {{"source": "fundamentals", "metric": "P/E Ratio", "value": "{pe if pe is not None else 'N/A'}", "date_or_period": "{as_of_str}"}}
  ]
}}
"""

    cache = get_cache()

    def llm_loader() -> dict:
        api_key = Config.GEMINI_API_KEY
        if api_key and api_key != "your_gemini_key_here":
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model=Config.GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.1,
                    ),
                )
                if response.text:
                    return json.loads(response.text)
            except Exception:
                pass

        score = 2.0 if pe and pe < 25.0 else -2.0 if pe and pe > 40.0 else 0.0
        health = "Strong" if de and de < 50.0 else "Moderate"

        return {
            "ticker": resolved_ticker,
            "as_of": as_of_str,
            "valuation_score": score,
            "health_rating": health,
            "pe_ratio": pe,
            "pb_ratio": pb,
            "ev_ebitda": ev_ebitda,
            "roe_pct": roe,
            "debt_to_equity": de,
            "revenue_growth_yoy": rev_growth,
            "net_margin_pct": margin,
            "valuation_summary": f"P/E ratio at {pe if pe else 'N/A'}x with debt-to-equity {de if de else 'N/A'} as of {as_of_str}.",
            "citations": [
                Citation(
                    source="fundamentals",
                    metric="P/E Ratio",
                    value=str(pe if pe is not None else "N/A"),
                    date_or_period=as_of_str,
                ).model_dump()
            ],
        }

    raw_output = cache.llm(f"fundamental_{prompt}", Config.GEMINI_MODEL, llm_loader, nonce=nonce)

    return FundamentalReport(**raw_output)


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    symbol = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE.NS"
    as_of_val = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--as-of" else "2025-01-15"
    report = analyze_fundamental(symbol, as_of_val)
    print("Fundamental Analyst Report Produced Successfully:")
    print(report.model_dump_json(indent=2))
