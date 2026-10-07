"""Pydantic schemas for every agent output. Shared by the multi-agent system,
the single-LLM baseline, and the evaluation harness — so the harness can score
any forecaster without knowing which one produced the forecast.

Two Gemini constraints shape everything here (verified, see Task 3.1):

1. Gemini rejects schemas carrying `Field(default=...)`. Fields are therefore
   declared `Optional[...]` with NO default and are allowed to come back null;
   callers post-process. This is why constructing one of these by hand requires
   passing every field.
2. Deeply nested models are sometimes misread as tool calls ("Unknown tool name").
   Schemas stay FLAT — lists of primitives, prefixed field names, never a tree of
   sub-models.

`propertyOrdering` is set explicitly on each schema: Gemini quality on complex
schemas improves measurably when the field order is pinned rather than inferred.

All monetary values are plain INR units — never lakh, never crore. Convert with
backend.money.parse_indian_amount before a number reaches any field here.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


def _ordered(*names: str) -> ConfigDict:
    """Pin field order in the generated JSON schema."""
    return ConfigDict(json_schema_extra={"propertyOrdering": list(names)})


Signal = Literal["Buy", "Hold", "Sell"]
Trend = Literal["Uptrend", "Downtrend", "Sideways"]
Regime = Literal["Tailwind", "Neutral", "Headwind"]
Health = Literal["Strong", "Stable", "Weak", "Distressed"]
Position = Literal["bull", "bear"]


class TechnicalReport(BaseModel):
    """Price action, momentum and levels. Produced from indicators.py output."""

    model_config = _ordered(
        "score", "trend", "support_inr", "resistance_inr",
        "rsi_reading", "macd_reading", "sma_reading",
        "reasoning", "citations",
    )

    score: float = Field(description="Bullishness from -10 (max bearish) to +10 (max bullish)")
    trend: Trend
    support_inr: Optional[float] = Field(description="Nearest support level in plain INR")
    resistance_inr: Optional[float] = Field(description="Nearest resistance level in plain INR")
    rsi_reading: Optional[str] = Field(description="e.g. 'RSI 72 - Overbought'")
    macd_reading: Optional[str]
    sma_reading: Optional[str] = Field(description="Price vs SMA-50 / SMA-200")
    reasoning: str
    citations: list[str] = Field(description="Indicator values actually used, e.g. 'RSI(14)=72.4 on 2025-01-15'")


class FundamentalReport(BaseModel):
    """Valuation and financial health. Nulls are expected and must be preserved —
    yfinance .NS coverage is patchy, especially on mid- and small-caps."""

    model_config = _ordered(
        "valuation_score", "intrinsic_value_inr", "health",
        "pe_ratio", "revenue_growth_pct", "debt_to_equity",
        "unavailable_fields", "reasoning", "citations",
    )

    valuation_score: float = Field(description="-10 (badly overvalued) to +10 (badly undervalued)")
    intrinsic_value_inr: Optional[float] = Field(description="Per-share fair value in plain INR")
    health: Health
    pe_ratio: Optional[float]
    revenue_growth_pct: Optional[float]
    debt_to_equity: Optional[float]
    unavailable_fields: list[str] = Field(
        description="Fields that were missing from the source. Say 'unavailable' - never invent a number."
    )
    reasoning: str
    citations: list[str]


class SentimentReport(BaseModel):
    """Mood from the Indian financial press. Headlines are untrusted web text."""

    model_config = _ordered(
        "polarity", "relevance", "confidence",
        "catalysts", "article_links", "headline_count", "reasoning",
    )

    polarity: float = Field(description="-1.0 (very negative) to +1.0 (very positive)")
    relevance: float = Field(description="0.0-1.0: how much of the coverage is actually about this company")
    confidence: float = Field(description="0.0-1.0")
    catalysts: list[str] = Field(description="Specific events driving the mood")
    article_links: list[str]
    headline_count: Optional[int]
    reasoning: str


class MacroReport(BaseModel):
    """Indian macro regime: RBI stance, CPI, USD/INR, crude, sector rotation."""

    model_config = _ordered(
        "regime", "usdinr_reading", "crude_reading", "rates_reading",
        "sector_reading", "key_indicators", "reasoning",
    )

    regime: Regime
    usdinr_reading: Optional[str]
    crude_reading: Optional[str] = Field(description="India imports ~85% of its crude - first-order driver")
    rates_reading: Optional[str]
    sector_reading: Optional[str] = Field(description="This stock's NIFTY sectoral index vs NIFTY 50")
    key_indicators: list[str]
    reasoning: str


class DebateArgument(BaseModel):
    """One turn in the Bull/Bear exchange."""

    model_config = _ordered("position", "round_number", "points", "target_inr", "confidence", "rebuttal")

    position: Position
    round_number: int
    points: list[str] = Field(description="Distinct arguments, strongest first")
    target_inr: Optional[float] = Field(description="This side's price target in plain INR")
    confidence: float = Field(description="0.0-1.0")
    rebuttal: Optional[str] = Field(description="Direct response to the other side's previous turn")


class FinalForecast(BaseModel):
    """The deliverable. Baseline and multi-agent both produce this, so the harness
    can score them identically."""

    model_config = _ordered(
        "signal", "target_low_inr", "target_high_inr", "confidence_pct",
        "expected_direction", "risk_report", "key_risks", "reasoning", "citations",
    )

    signal: Signal
    target_low_inr: float = Field(description="Low end of the target range, plain INR")
    target_high_inr: float = Field(description="High end of the target range, plain INR")
    confidence_pct: float = Field(description="0-100. Calibration is measured, so do not default to 80.")
    expected_direction: Literal["up", "down"] = Field(
        description="Direction over the horizon vs the last close. Scored directly."
    )
    risk_report: str
    key_risks: list[str]
    reasoning: str
    citations: list[str]


class ForecastRecord(BaseModel):
    """A forecast plus everything needed to score and reproduce it.

    This is what gets written to results files. It carries the run metadata that
    Phase 4 needs (cost, config, cache nonce) so every table traces back to a run.
    """

    model_config = _ordered(
        "ticker", "as_of", "system", "last_close_inr", "forecast",
        "horizon_sessions", "target_date", "llm_calls", "total_tokens",
        "seconds", "parse_failures", "nonce", "notes", "transcript",
        "specialist_signals", "evidence_flags"
    )

    ticker: str
    as_of: str
    system: str = Field(description="Which forecaster: baseline | multiagent | multiagent-nodebate | naive")
    last_close_inr: Optional[float]
    forecast: Optional[FinalForecast]
    horizon_sessions: int
    target_date: Optional[str]
    llm_calls: int
    total_tokens: int
    seconds: float
    parse_failures: int
    nonce: str
    notes: list[str]
    transcript: Optional[str] = None
    specialist_signals: Optional[dict] = None
    evidence_flags: Optional[dict] = None
