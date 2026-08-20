"""Reconciliation gate tests — the Phase 3 exit gate.

The gate's whole claim is that it catches a number an agent made up. So the tests
inject made-up numbers deliberately and assert the gate finds them, including the
India-specific crore magnitude error. A gate nobody has tried to fool is a gate
nobody should trust.
"""
from __future__ import annotations

import pytest

from backend.agents import reconciliation as R
from backend.agents.schemas import (
    FinalForecast,
    FundamentalReport,
    SentimentReport,
    TechnicalReport,
)


def _technical(**overrides) -> TechnicalReport:
    """An honest technical report; overrides inject the lie under test."""
    base = dict(
        score=3.0,
        trend="Uptrend",
        support_inr=1350.0,
        resistance_inr=1450.0,
        rsi_reading="RSI 55.0 - Neutral",
        macd_reading="MACD histogram positive - Bullish",
        sma_reading="Price above SMA-50",
        reasoning="Test report.",
        citations=["RSI(14)=55.0"],
    )
    base.update(overrides)
    return TechnicalReport(**base)


def _forecast(**overrides) -> FinalForecast:
    base = dict(
        signal="Buy",
        target_low_inr=1400.0,
        target_high_inr=1460.0,
        confidence_pct=62.0,
        expected_direction="up",
        risk_report="Test.",
        key_risks=["test risk"],
        reasoning="Test.",
        citations=["last close"],
    )
    base.update(overrides)
    return FinalForecast(**base)


# ---------------------------------------------------------------------------
# the headline requirement: an injected fake number is caught
# ---------------------------------------------------------------------------
def test_injected_fake_rsi_is_caught(ctx):
    """The Phase 3 exit gate: inject a fake number, confirm the gate catches it."""
    true_rsi = ctx.indicators["rsi_14"]["value"]
    liar = _technical(rsi_reading=f"RSI {true_rsi + 30:.1f} - Overbought")

    report = R.reconcile(ctx, technical=liar)

    failures = [c for c in report.failures if c.field_name == "rsi_reading"]
    assert failures, "the gate did not catch a fabricated RSI value"
    assert failures[0].status == R.MISMATCH
    assert not report.passed


def test_honest_report_passes_cleanly(ctx):
    """The complement: a report that agrees with source data must not be flagged.

    Without this, a gate that flagged everything would pass the test above.
    """
    true_rsi = ctx.indicators["rsi_14"]["value"]
    bias = ctx.indicators["macd"]["bias"]
    position = ctx.indicators["sma_50"]["price_position"]
    honest = _technical(
        rsi_reading=f"RSI {true_rsi} - Neutral",
        macd_reading=f"MACD histogram - {bias}",
        sma_reading=f"Price {position} SMA-50",
    )

    report = R.reconcile(ctx, technical=honest)

    assert report.passed, f"honest report was flagged: {report.warnings()}"
    assert report.n_checked > 0, "gate reported success without checking anything"


# ---------------------------------------------------------------------------
# the India-specific requirement: a crore magnitude error is caught
# ---------------------------------------------------------------------------
def test_crore_magnitude_error_is_caught(ctx):
    """A target 100x the share price is the lakh/crore parse failure."""
    report = R.reconcile(
        ctx,
        forecast=_forecast(target_low_inr=140_000.0, target_high_inr=146_000.0),
    )

    assert report.n_magnitude_errors >= 1, "a 100x target was not flagged as a magnitude error"
    note = " ".join(w.lower() for w in report.warnings())
    assert "magnitude" in note or "lakh" in note


def test_magnitude_error_is_not_reported_as_a_mere_mismatch(ctx):
    """A 100x error also fails the tolerance test; it must be classed as MAGNITUDE.

    Burying it as an ordinary mismatch is how the one error most likely to reach
    a reader unnoticed would reach a reader unnoticed.
    """
    check = R.check_value("fundamental", "intrinsic_value_inr", 2_500.0, 25_000_000_000.0)
    assert check.status == R.MAGNITUDE


def test_crore_string_parses_to_plain_inr():
    """The conversion the magnitude check exists to police."""
    from backend.money import parse_indian_amount

    assert parse_indian_amount("Rs 2,500 crore") == 25_000_000_000.0
    assert parse_indian_amount("12.5 lakh") == 1_250_000.0
    assert parse_indian_amount("1,00,000") == 100_000.0


# ---------------------------------------------------------------------------
# fabrication: numbers and citations that were never supplied
# ---------------------------------------------------------------------------
def test_metric_asserted_without_evidence_is_flagged_as_fabricated(ctx):
    """In strict point-in-time mode no P/E is supplied, so any P/E is invented.

    This is recall leaking in through the model's weights — the one leakage path
    the data layer cannot close on its own.
    """
    rep = FundamentalReport(
        valuation_score=4.0,
        intrinsic_value_inr=1500.0,
        health="Strong",
        pe_ratio=24.3,          # never supplied: ctx.fundamentals["metrics"] is empty
        revenue_growth_pct=None,
        debt_to_equity=None,
        unavailable_fields=[],
        reasoning="Test.",
        citations=[],
    )

    report = R.reconcile(ctx, fundamental=rep)

    pe = [c for c in report.failures if c.field_name == "pe_ratio"]
    assert pe and pe[0].status == R.FABRICATED


def test_invented_article_link_is_caught(ctx):
    """A citation to a URL we never supplied was invented."""
    rep = SentimentReport(
        polarity=0.4,
        relevance=0.8,
        confidence=0.6,
        catalysts=["quarterly results"],
        article_links=["https://example.in/a", "https://fabricated.example/never-supplied"],
        headline_count=2,
        reasoning="Test.",
    )

    report = R.reconcile(ctx, sentiment=rep)

    links = [c for c in report.failures if c.field_name == "article_links"]
    assert links and links[0].status == R.FABRICATED


def test_headline_count_must_match_exactly(ctx):
    rep = SentimentReport(
        polarity=0.1, relevance=0.5, confidence=0.5, catalysts=[],
        article_links=["https://example.in/a"], headline_count=47,   # actually 2
        reasoning="Test.",
    )
    report = R.reconcile(ctx, sentiment=rep)
    assert any(c.field_name == "headline_count" for c in report.failures)


# ---------------------------------------------------------------------------
# internal consistency
# ---------------------------------------------------------------------------
def test_support_above_resistance_is_caught(ctx):
    report = R.reconcile(ctx, technical=_technical(support_inr=1500.0, resistance_inr=1300.0))
    assert any(c.field_name == "support_vs_resistance" for c in report.failures)


def test_inverted_target_range_is_caught(ctx):
    report = R.reconcile(ctx, forecast=_forecast(target_low_inr=1500.0, target_high_inr=1400.0))
    assert any(c.field_name == "target_range" for c in report.failures)


def test_support_outside_the_52_week_range_is_implausible(ctx):
    report = R.reconcile(ctx, technical=_technical(support_inr=10.0))
    levels = [c for c in report.failures if c.field_name == "support_inr"]
    assert levels and levels[0].status in (R.IMPLAUSIBLE, R.MAGNITUDE)


def test_absurd_horizon_move_is_flagged_against_realised_volatility(ctx):
    """A +60% call over 21 sessions is outside what this stock's vol can deliver."""
    last = ctx.last_close
    report = R.reconcile(
        ctx, forecast=_forecast(target_low_inr=last * 1.55, target_high_inr=last * 1.65)
    )
    plaus = [c for c in report.failures if c.field_name == "target_plausibility"]
    assert plaus and plaus[0].status == R.IMPLAUSIBLE


def test_reasonable_target_is_not_flagged(ctx):
    last = ctx.last_close
    report = R.reconcile(
        ctx, forecast=_forecast(target_low_inr=last * 1.01, target_high_inr=last * 1.04)
    )
    assert not [c for c in report.failures if c.field_name == "target_plausibility"]


# ---------------------------------------------------------------------------
# the gate must not be able to pass by doing nothing
# ---------------------------------------------------------------------------
def test_unverifiable_claims_are_recorded_not_passed(ctx):
    """Checks that could not be performed must be visible as unverifiable."""
    report = R.reconcile(ctx, technical=_technical(rsi_reading=None))
    assert report.n_unverifiable >= 1
    assert "unverifiable" in report.summary()


def test_clamping_is_off_by_default(ctx):
    """A scored run must never silently rewrite the model's target."""
    last = ctx.last_close
    f = _forecast(target_low_inr=last * 1.55, target_high_inr=last * 1.65)
    original = (f.target_low_inr, f.target_high_inr)

    report = R.reconcile(ctx, forecast=f)

    assert (f.target_low_inr, f.target_high_inr) == original
    assert not report.clamped

    # ...but demo mode may clamp, and must say that it did.
    f2 = _forecast(target_low_inr=last * 1.55, target_high_inr=last * 1.65)
    report2 = R.reconcile(ctx, forecast=f2, clamp_targets=True)
    assert report2.clamped
    assert f2.target_high_inr < last * 1.65
