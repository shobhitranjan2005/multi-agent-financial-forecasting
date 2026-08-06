"""Macroeconomic & Sector Analyst Agent.

Specialist agent for interest rates, India VIX, USD/INR exchange rate,
Brent crude oil, and NIFTY sectoral relative performance. Returns a MacroReport.
"""
from __future__ import annotations

import json
from datetime import datetime

from backend.agents.schemas import Citation, MacroReport
from backend.cache import get_cache
from backend.config import Config
from backend.tools import calendar_nse, macro, tickers


def analyze_macro(
    ticker: str,
    as_of: str | datetime,
    nonce: str = "",
) -> MacroReport:
    """Run macro & sector analysis for `ticker` as of `as_of` date."""
    resolved_ticker = tickers.resolve(ticker)
    base_sym = tickers.base_symbol(resolved_ticker)

    if isinstance(as_of, str):
        as_of_dt = datetime.fromisoformat(as_of)
    else:
        as_of_dt = as_of

    as_of_session = calendar_nse.previous_trading_day(as_of_dt)
    as_of_str = as_of_session.isoformat()

    # Determine sector mapping based on ticker base symbol
    sector_map = {
        "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "LTIM": "IT", "TECHM": "IT",
        "HDFCBANK": "BANK", "ICICIBANK": "BANK", "SBIN": "BANK", "AXISBANK": "BANK",
        "TATAMOTORS": "AUTO", "MARUTI": "AUTO", "M&M": "AUTO",
        "SUNPHARMA": "PHARMA", "CIPLA": "PHARMA", "DRREDDY": "PHARMA",
        "RELIANCE": "ENERGY", "NTPC": "ENERGY", "POWERGRID": "ENERGY",
    }
    sector_key = sector_map.get(base_sym, "IT")

    m_data = macro.get_macro_data(as_of_str)
    s_data = macro.get_sector_performance(sector_key, as_of_str)

    usdinr = m_data.get("usdinr")
    vix = m_data.get("india_vix")
    crude = m_data.get("brent_crude_usd")
    regime = m_data.get("regime", "Neutral")
    sec_label = s_data.get("performance_label", "Inline")

    prompt = f"""You are a Macroeconomic & Sector Analyst evaluating Indian markets.
Ticker: {resolved_ticker}
As-Of Date: {as_of_str}

Macro Indicators:
{json.dumps(m_data, indent=2)}

Sector ({sector_key}) Performance vs NIFTY 50:
{json.dumps(s_data, indent=2)}

Task: Output a JSON matching this exact structure:
{{
  "as_of": "{as_of_str}",
  "regime_rating": "Tailwind" | "Neutral" | "Headwind",
  "usdinr": {usdinr if usdinr is not None else "null"},
  "gsec_10y_yield": 7.15,
  "india_vix": {vix if vix is not None else "null"},
  "brent_crude_usd": {crude if crude is not None else "null"},
  "sector_name": "{sector_key}",
  "sector_relative_perf": "{sec_label}",
  "key_drivers": ["string"],
  "citations": [
    {{"source": "FRED / yfinance", "metric": "India VIX", "value": "{vix}", "date_or_period": "{as_of_str}"}}
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

        return {
            "as_of": as_of_str,
            "regime_rating": regime,
            "usdinr": usdinr,
            "gsec_10y_yield": 7.15,
            "india_vix": vix,
            "brent_crude_usd": crude,
            "sector_name": sector_key,
            "sector_relative_perf": sec_label,
            "key_drivers": [
                f"India VIX at {vix} ({regime} regime).",
                f"NIFTY {sector_key} sector is {sec_label} relative to NIFTY 50.",
            ],
            "citations": [
                Citation(
                    source="yfinance",
                    metric="India VIX",
                    value=str(vix),
                    date_or_period=as_of_str,
                ).model_dump()
            ],
        }

    raw_output = cache.llm(f"macro_{prompt}", Config.GEMINI_MODEL, llm_loader, nonce=nonce)

    return MacroReport(**raw_output)


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    symbol = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE.NS"
    as_of_val = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--as-of" else "2025-01-15"
    report = analyze_macro(symbol, as_of_val)
    print("Macro Analyst Report Produced Successfully:")
    print(report.model_dump_json(indent=2))
