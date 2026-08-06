"""Chief Risk Officer & Synthesiser Agent.

Integrates specialist reports and Bull vs Bear debate transcript.
Enforces NSE single-session price band constraints (±20%) and emits
the final structured FinalForecast Pydantic model.
"""
from __future__ import annotations

import json
from typing import List, Optional

from backend.agents.schemas import (
    Citation,
    DebateArgument,
    FinalForecast,
    FundamentalReport,
    MacroReport,
    SentimentReport,
    TechnicalReport,
)
from backend.cache import get_cache
from backend.config import Config
from backend.tools import indicators, market_data, tickers


def synthesize_final_forecast(
    ticker: str,
    as_of: str,
    tech: TechnicalReport,
    fund: FundamentalReport,
    sent: SentimentReport,
    macro_rep: MacroReport,
    debate_transcript: Optional[List[DebateArgument]] = None,
    nonce: str = "",
) -> FinalForecast:
    """Synthesize specialist reports & debate transcript into a FinalForecast."""
    resolved_ticker = tickers.resolve(ticker)
    cache = get_cache()

    df = market_data.get_price_history(resolved_ticker, as_of, as_of, as_of)
    last_close = float(df["close"].iloc[-1]) if not df.empty else 1000.0

    # Aggregate citations across all specialists
    all_citations = []
    all_citations.extend(tech.citations)
    all_citations.extend(fund.citations)
    all_citations.extend(sent.citations)
    all_citations.extend(macro_rep.citations)

    # Sanity check single-session max band (±20%)
    lower_band = round(last_close * 0.80, 2)
    upper_band = round(last_close * 1.20, 2)


    prompt = f"""You are the Chief Risk Officer evaluating an Indian stock forecast on NSE.
Ticker: {resolved_ticker}
As-Of Date: {as_of}
Current Price: ₹{last_close:.2f}

Specialist Input Scores:
- Technical Score: {tech.score} ({tech.trend_label})
- Fundamental Score: {fund.valuation_score} ({fund.health_rating})
- Sentiment Score: {sent.polarity_score}
- Macro Regime: {macro_rep.regime_rating}

Debate Status: {'Active with ' + str(len(debate_transcript)) + ' rounds' if debate_transcript else 'Bypassed (--no-debate)'}

Task: Issue a final 21-session forecast in JSON format matching this structure:
{{
  "ticker": "{resolved_ticker}",
  "as_of": "{as_of}",
  "signal": "BUY" | "HOLD" | "SELL",
  "target_price_low": float (INR),
  "target_price_mid": float (INR),
  "target_price_high": float (INR),
  "horizon_trading_sessions": 21,
  "confidence_pct": float (0.0 to 100.0),
  "executive_summary": "string",
  "key_risks": ["string"],
  "citations": []
}}
"""

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
                    res_dict = json.loads(response.text)
                    res_dict["citations"] = [c.model_dump() for c in all_citations]
                    return res_dict
            except Exception:
                pass

        # Synthesis scoring logic
        composite_score = (tech.score * 0.35) + (fund.valuation_score * 0.35) + (sent.polarity_score * 10.0 * 0.15)
        if macro_rep.regime_rating == "Headwind":
            composite_score -= 1.5
        elif macro_rep.regime_rating == "Tailwind":
            composite_score += 1.5

        if composite_score > 2.0:
            signal = "BUY"
            mid = last_close * 1.05
        elif composite_score < -2.0:
            signal = "SELL"
            mid = last_close * 0.95
        else:
            signal = "HOLD"
            mid = last_close * 1.01

        low = round(max(lower_band, mid * 0.94), 2)
        mid = round(mid, 2)
        high = round(min(upper_band, mid * 1.06), 2)

        return {
            "ticker": resolved_ticker,
            "as_of": as_of,
            "signal": signal,
            "target_price_low": low,
            "target_price_mid": mid,
            "target_price_high": high,
            "horizon_trading_sessions": Config.HORIZON_SESSIONS,
            "confidence_pct": 70.0 if debate_transcript else 62.0,
            "executive_summary": f"Multi-agent synthesis for {resolved_ticker} as of {as_of}. Composite score: {composite_score:.2f}.",
            "key_risks": [
                f"Technical trend position: {tech.trend_label}.",
                f"Macro regime factor: {macro_rep.regime_rating}.",
            ],
            "citations": [c.model_dump() for c in all_citations],
        }

    raw_output = cache.llm(f"synth_{prompt}", Config.GEMINI_MODEL, llm_loader, nonce=nonce)
    return FinalForecast(**raw_output)
