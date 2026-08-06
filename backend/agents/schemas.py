"""Pydantic v2 schemas for agent outputs and structured LLM forecasts.

Scope: Indian equities (NSE/BSE). Currency: INR (₹).

Design rules (per Technical Review §4.4):
- Avoid Field(default=...) in schemas targeted for Gemini structured output;
  use Optional[...] and post-process defaults.
- Prefer flat/shallow schemas to avoid Gemini tool-call confusion.
- Every monetary value is in plain INR units (not lakhs or crores).
"""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel


class Citation(BaseModel):
    source: str          # e.g., "yfinance OHLCV", "NSE Bhavcopy", "GDELT", "FRED"
    metric: str          # e.g., "RSI(14)", "P/E Ratio", "Headline"
    value: str           # e.g., "72.4", "24.5x", "Quarterly profit up 15%"
    date_or_period: str  # e.g., "2025-01-15", "Q3 FY25"


class TechnicalReport(BaseModel):
    ticker: str
    as_of: str
    score: float                         # -10.0 (extremely bearish) to +10.0 (extremely bullish)
    trend_label: str                     # "Bullish", "Bearish", "Neutral"
    support_price: Optional[float]       # INR
    resistance_price: Optional[float]    # INR
    rsi_14: Optional[float]
    macd_bias: Optional[str]             # "Bullish", "Bearish"
    sma_50_position: Optional[str]       # "above", "below"
    sma_200_position: Optional[str]      # "above", "below"
    realised_vol_21: Optional[float]     # Annualised volatility
    key_observations: List[str]
    citations: List[Citation]


class FundamentalReport(BaseModel):
    ticker: str
    as_of: str
    valuation_score: float               # -10.0 to +10.0
    health_rating: str                   # "Strong", "Moderate", "Weak"
    pe_ratio: Optional[float]
    pb_ratio: Optional[float]
    ev_ebitda: Optional[float]
    roe_pct: Optional[float]
    debt_to_equity: Optional[float]
    revenue_growth_yoy: Optional[float]
    net_margin_pct: Optional[float]
    valuation_summary: str
    citations: List[Citation]


class SentimentReport(BaseModel):
    ticker: str
    as_of: str
    polarity_score: float                # -1.0 (negative) to +1.0 (positive)
    relevance_score: float               # 0.0 to 1.0
    confidence_score: float              # 0.0 to 1.0
    catalysts: List[str]
    risk_factors: List[str]
    article_links: List[str]
    citations: List[Citation]


class MacroReport(BaseModel):
    as_of: str
    regime_rating: str                   # "Tailwind", "Neutral", "Headwind"
    usdinr: Optional[float]
    gsec_10y_yield: Optional[float]
    india_vix: Optional[float]
    brent_crude_usd: Optional[float]
    sector_name: Optional[str]
    sector_relative_perf: Optional[str]  # "Outperforming", "Inline", "Underperforming"
    key_drivers: List[str]
    citations: List[Citation]


class DebateArgument(BaseModel):
    round_num: int
    perspective: str                     # "Bull" or "Bear"
    main_points: List[str]
    target_price: float                  # INR
    confidence_pct: float                # 0-100
    rebuttal_to_prior: Optional[str]


class FinalForecast(BaseModel):
    ticker: str
    as_of: str
    signal: str                          # "BUY", "HOLD", "SELL"
    target_price_low: float              # INR
    target_price_mid: float              # INR
    target_price_high: float             # INR
    horizon_trading_sessions: int        # Standard 21 sessions
    confidence_pct: float                # 0-100% calibration score
    executive_summary: str
    key_risks: List[str]
    citations: List[Citation]
