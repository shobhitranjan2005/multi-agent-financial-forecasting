"""Technical Analyst Agent.

Specialist agent for technical indicators, trend momentum, and price levels.
Returns a structured TechnicalReport Pydantic model.
"""
from __future__ import annotations

import json
from datetime import datetime

from backend.agents.schemas import Citation, TechnicalReport
from backend.cache import get_cache
from backend.config import Config
from backend.tools import calendar_nse, indicators, market_data, tickers


def analyze_technical(
    ticker: str,
    as_of: str | datetime,
    nonce: str = "",
) -> TechnicalReport:
    """Run technical analysis for a given ticker up to as_of date."""
    resolved_ticker = tickers.resolve(ticker)
    if isinstance(as_of, str):
        as_of_dt = datetime.fromisoformat(as_of)
    else:
        as_of_dt = as_of

    as_of_session = calendar_nse.previous_trading_day(as_of_dt)
    as_of_str = as_of_session.isoformat()

    start_dt = datetime.combine(as_of_session, datetime.min.time())
    df = market_data.get_price_history(resolved_ticker, start_dt, start_dt, as_of_str)

    if df.empty:
        raise ValueError(f"No price data available for {resolved_ticker} as of {as_of_str}")

    last_close = float(df["close"].iloc[-1])
    all_ind = indicators.compute_all(df)

    rsi_info = all_ind.get("rsi_14") or {}
    macd_info = all_ind.get("macd") or {}
    sma50_info = all_ind.get("sma_50") or {}
    sma200_info = all_ind.get("sma_200") or {}
    bb_info = all_ind.get("bollinger_20") or {}
    vol_info = all_ind.get("realised_vol_21") or {}

    prompt = f"""You are a Technical Analyst evaluating an Indian stock listed on NSE.
Ticker: {resolved_ticker}
As-Of Date: {as_of_str}
Closing Price (INR): ₹{last_close:.2f}

Computed Indicators:
{json.dumps(all_ind, indent=2)}

Task: Analyze these technical signals and output a JSON matching this exact structure:
{{
  "ticker": "{resolved_ticker}",
  "as_of": "{as_of_str}",
  "score": float (-10.0 extremely bearish to +10.0 extremely bullish),
  "trend_label": "Bullish" | "Bearish" | "Neutral",
  "support_price": float (INR),
  "resistance_price": float (INR),
  "rsi_14": {rsi_info.get("value", "null")},
  "macd_bias": "{macd_info.get("bias", "Neutral")}",
  "sma_50_position": "{sma50_info.get("price_position", "neutral")}",
  "sma_200_position": "{sma200_info.get("price_position", "neutral")}",
  "realised_vol_21": {vol_info.get("annualised_vol", "null")},
  "key_observations": ["string"],
  "citations": [
    {{"source": "yfinance", "metric": "RSI(14)", "value": "{rsi_info.get('value', 'N/A')}", "date_or_period": "{as_of_str}"}}
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

        rsi_val = rsi_info.get("value", 50.0) or 50.0
        score = round((rsi_val - 50.0) / 2.5, 1)
        score = max(-10.0, min(10.0, score))

        trend = "Bullish" if score > 2.0 else "Bearish" if score < -2.0 else "Neutral"
        support = round(last_close * 0.95, 2)
        resistance = round(last_close * 1.05, 2)

        return {
            "ticker": resolved_ticker,
            "as_of": as_of_str,
            "score": score,
            "trend_label": trend,
            "support_price": support,
            "resistance_price": resistance,
            "rsi_14": rsi_info.get("value"),
            "macd_bias": macd_info.get("bias", "Neutral"),
            "sma_50_position": sma50_info.get("price_position", "neutral"),
            "sma_200_position": sma200_info.get("price_position", "neutral"),
            "realised_vol_21": vol_info.get("annualised_vol"),
            "key_observations": [
                f"RSI(14) is {rsi_val} ({rsi_info.get('reading', 'Neutral')}).",
                f"Current close ₹{last_close:.2f} relative to SMA50: {sma50_info.get('price_position', 'N/A')}.",
            ],
            "citations": [
                Citation(
                    source="indicators",
                    metric="RSI(14)",
                    value=str(rsi_val),
                    date_or_period=as_of_str,
                ).model_dump()
            ],
        }

    raw_output = cache.llm(f"technical_{prompt}", Config.GEMINI_MODEL, llm_loader, nonce=nonce)

    return TechnicalReport(**raw_output)


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    symbol = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE.NS"
    as_of_val = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--as-of" else "2025-01-15"
    report = analyze_technical(symbol, as_of_val)
    print("Technical Analyst Report Produced Successfully:")
    print(report.model_dump_json(indent=2))

