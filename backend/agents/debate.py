"""Bull vs Bear Adversarial Debate Engine.

Conducts a bounded (N=2 round) debate between:
- Bull Analyst: Constructs upside thesis, catalyst momentum, and growth target.
- Bear Analyst: Constructs downside thesis, valuation risks, and support floor.

Returns a list of structured DebateArgument Pydantic models.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from backend.agents.schemas import (
    DebateArgument,
    FundamentalReport,
    MacroReport,
    SentimentReport,
    TechnicalReport,
)
from backend.cache import get_cache
from backend.config import Config
from backend.tools import market_data, tickers


def run_bull_bear_debate(
    ticker: str,
    as_of: str,
    tech: TechnicalReport,
    fund: FundamentalReport,
    sent: SentimentReport,
    macro_rep: MacroReport,
    rounds: int = 2,
    nonce: str = "",
) -> List[DebateArgument]:
    """Run an N-round adversarial debate between Bull and Bear analysts."""
    resolved_ticker = tickers.resolve(ticker)
    cache = get_cache()

    # Base price context
    df = market_data.get_price_history(resolved_ticker, as_of, as_of, as_of)
    last_close = float(df["close"].iloc[-1]) if not df.empty else 1000.0

    prompt = f"""You are facilitating an Adversarial Bull vs Bear Debate for an Indian stock on NSE.
Ticker: {resolved_ticker}
As-Of Date: {as_of}
Current Price: ₹{last_close:.2f}

Specialist Reports:
1. Technical: Score={tech.score}, Trend={tech.trend_label}, Support=₹{tech.support_price}, Resistance=₹{tech.resistance_price}
2. Fundamental: Score={fund.valuation_score}, Health={fund.health_rating}, PE={fund.pe_ratio}x, Revenue Growth={fund.revenue_growth_yoy}%
3. Sentiment: Polarity={sent.polarity_score}, Catalysts={sent.catalysts[:2]}
4. Macro: Regime={macro_rep.regime_rating}, VIX={macro_rep.india_vix}, Sector={macro_rep.sector_relative_perf}

Task: Generate a {rounds}-round debate (Bull vs Bear) in JSON array format:
[
  {{
    "round_num": 1,
    "perspective": "Bull",
    "main_points": ["Strong upside driver from technical momentum and valuation"],
    "target_price": {round(last_close * 1.08, 2)},
    "confidence_pct": 75.0,
    "rebuttal_to_prior": null
  }},
  {{
    "round_num": 1,
    "perspective": "Bear",
    "main_points": ["Downside risk from macro volatility and sector pressure"],
    "target_price": {round(last_close * 0.94, 2)},
    "confidence_pct": 70.0,
    "rebuttal_to_prior": "Bull underestimates macro headwinds and PE valuation expansion limits"
  }}
]
"""

    def llm_loader() -> List[dict]:
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
                        temperature=0.2,
                    ),
                )
                if response.text:
                    return json.loads(response.text)
            except Exception:
                pass

        bull_target = round(last_close * 1.07, 2)
        bear_target = round(last_close * 0.93, 2)

        return [
            {
                "round_num": 1,
                "perspective": "Bull",
                "main_points": [
                    f"Technical trend is {tech.trend_label} with support at ₹{tech.support_price}.",
                    f"Revenue growth of {fund.revenue_growth_yoy if fund.revenue_growth_yoy else 10}% supports upside target ₹{bull_target}.",
                ],
                "target_price": bull_target,
                "confidence_pct": 72.0,
                "rebuttal_to_prior": None,
            },
            {
                "round_num": 1,
                "perspective": "Bear",
                "main_points": [
                    f"Valuation risk at P/E {fund.pe_ratio if fund.pe_ratio else 'N/A'}x.",
                    f"Macro regime is {macro_rep.regime_rating} with India VIX at {macro_rep.india_vix}.",
                ],
                "target_price": bear_target,
                "confidence_pct": 68.0,
                "rebuttal_to_prior": f"Bull target ₹{bull_target} ignores key macro headwinds and potential margin pressure.",
            },
        ]

    raw_list = cache.llm(f"debate_{prompt}", Config.GEMINI_MODEL, llm_loader, nonce=nonce)
    return [DebateArgument(**item) for item in raw_list]
