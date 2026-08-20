"""Reconciliation gate (Task 3.3) — every number re-checked against its source.

The pattern is Bloomberg's ASKB: an LLM's numeric claims are re-verified against
the data they were supposedly drawn from BEFORE they propagate to the next agent.
A mismatch raises a recorded warning, never a silent pass.

Why this is the highest-value module in the system: a hallucinated adjective is
embarrassing, but a hallucinated NUMBER is invisible. "RSI is 28, deeply
oversold" reads exactly like a correct reading when the true RSI is 61, and it
propagates through the debate into the final target, where nobody can trace it.

Four classes of check, in descending order of how often they fire:

1. VALUE MISMATCH   — a claimed figure disagrees with the cached source value.
2. MAGNITUDE ERROR  — a claimed figure is ~100x or ~10,000,000x off. This is the
                      lakh/crore parse failure and it is India-specific: "Rs 2,500
                      crore" is 25,000,000,000, and a model that returns 2500 is
                      wrong by seven orders of magnitude while looking plausible.
3. INTERNAL         — support above resistance, target_low above target_high,
                      confidence outside 0-100. Cheap, and they do occur.
4. FABRICATED CITE  — an article link cited that was never supplied, or a metric
                      asserted where the evidence pack contained none. Both mean
                      the number came from the model's weights, not from our data.

Design decisions worth defending in a viva:

- The gate FLAGS, it does not silently repair. Clamping a bad target would change
  the very quantity the evaluation measures (MAPE, target hit rate), turning a
  measurement of the model into a measurement of our clamp. clamp_targets=True
  exists for the live demo, is off in every scored run, and the record says which.
- Checks that cannot be performed are recorded as "unverifiable" rather than
  passed. A gate reporting "0 mismatches" because it checked nothing is worse than
  no gate at all, because it buys false confidence.
- The horizon plausibility test uses the stock's own realised volatility, not the
  NSE daily price band. Over 21 sessions the +/-20% daily band compounds to a
  bound so loose it never binds; 3 sigma of that stock's actual volatility is the
  test with teeth. The daily band is applied when the horizon is one session,
  where it genuinely is the binding constraint.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.money import magnitude_ratio

# A claimed value this many multiples from its source is a magnitude error
# (lakh/crore), not a difference of opinion. 100x is the lakh slip; 50 catches it
# with margin while staying clear of any honest disagreement.
MAGNITUDE_THRESHOLD = 50.0

# Relative tolerance for a figure the model was handed directly. Rounding to one
# decimal place is normal; 2% allows that and still catches an invented number.
VALUE_TOLERANCE_PCT = 2.0

# Sigma multiple beyond which a horizon target is called implausible.
SIGMA_LIMIT = 3.0

OK = "ok"
MISMATCH = "mismatch"
MAGNITUDE = "magnitude"
IMPLAUSIBLE = "implausible"
FABRICATED = "fabricated"
UNVERIFIABLE = "unverifiable"

_FAILING = (MISMATCH, MAGNITUDE, IMPLAUSIBLE, FABRICATED)

_MARKS = {
    OK: "ok        ",
    MISMATCH: "MISMATCH  ",
    MAGNITUDE: "MAGNITUDE ",
    IMPLAUSIBLE: "IMPLAUSIBLE",
    FABRICATED: "FABRICATED",
    UNVERIFIABLE: "unverified",
}


@dataclass
class Check:
    """One verification of one claim."""

    agent: str
    field_name: str
    claimed: Any
    source: Any
    status: str
    note: str = ""

    @property
    def failed(self) -> bool:
        return self.status in _FAILING

    def line(self) -> str:
        return f"  {_MARKS[self.status]} {self.agent}.{self.field_name}: {self.note}"


@dataclass
class ReconciliationReport:
    checks: list[Check] = field(default_factory=list)
    clamped: list[str] = field(default_factory=list)

    def add(self, check: Check) -> None:
        self.checks.append(check)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.failed]

    @property
    def n_checked(self) -> int:
        return sum(1 for c in self.checks if c.status != UNVERIFIABLE)

    @property
    def n_unverifiable(self) -> int:
        return sum(1 for c in self.checks if c.status == UNVERIFIABLE)

    @property
    def n_magnitude_errors(self) -> int:
        return sum(1 for c in self.checks if c.status == MAGNITUDE)

    @property
    def passed(self) -> bool:
        return not self.failures

    def warnings(self) -> list[str]:
        return [f"{c.agent}.{c.field_name}: {c.note}" for c in self.failures]

    def summary(self) -> str:
        return (
            f"{self.n_checked} claims verified, {len(self.failures)} failed "
            f"({self.n_magnitude_errors} magnitude), {self.n_unverifiable} unverifiable"
        )

    def as_dict(self) -> dict:
        return {
            "n_checked": self.n_checked,
            "n_failed": len(self.failures),
            "n_magnitude_errors": self.n_magnitude_errors,
            "n_unverifiable": self.n_unverifiable,
            "passed": self.passed,
            "clamped": self.clamped,
            "failures": [
                {"agent": c.agent, "field": c.field_name, "claimed": str(c.claimed),
                 "source": str(c.source), "status": c.status, "note": c.note}
                for c in self.failures
            ],
        }


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------
def _num(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(f) or math.isinf(f)) else f


def _first_number(text: Optional[str]) -> Optional[float]:
    """First numeric literal in a plain-English reading string."""
    if not text:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    return float(m.group(0)) if m else None


def check_value(
    agent: str,
    field_name: str,
    claimed: Any,
    source: Any,
    *,
    tolerance_pct: float = VALUE_TOLERANCE_PCT,
    unit: str = "",
) -> Check:
    """Compare one claimed figure to its cached source value.

    Order matters: the magnitude test runs first, because a 100x error also fails
    the tolerance test, and reporting it as an ordinary mismatch would bury the
    one class of error most likely to reach the report unnoticed.
    """
    c, s = _num(claimed), _num(source)
    if c is None or s is None:
        return Check(agent, field_name, claimed, source, UNVERIFIABLE,
                     "no source value to check against" if s is None else "nothing claimed")

    if s != 0 and c != 0 and magnitude_ratio(c, s) >= MAGNITUDE_THRESHOLD:
        return Check(agent, field_name, claimed, source, MAGNITUDE,
                     f"claimed {c:,.4g}{unit} vs source {s:,.4g}{unit} - "
                     f"{magnitude_ratio(c, s):,.0f}x apart (lakh/crore magnitude error)")

    denom = abs(s) if s else 1.0
    diff_pct = abs(c - s) / denom * 100.0
    if diff_pct > tolerance_pct:
        return Check(agent, field_name, claimed, source, MISMATCH,
                     f"claimed {c:,.4g}{unit} vs source {s:,.4g}{unit} "
                     f"({diff_pct:.1f}% apart, tolerance {tolerance_pct:.0f}%)")
    return Check(agent, field_name, claimed, source, OK,
                 f"claimed {c:,.4g}{unit} matches source {s:,.4g}{unit}")


# ---------------------------------------------------------------------------
# per-agent reconciliation
# ---------------------------------------------------------------------------
def reconcile_technical(rep, ctx, out: ReconciliationReport) -> None:
    """Technical claims against the indicator values we computed ourselves."""
    if rep is None:
        return
    ind = ctx.indicators or {}

    rsi = (ind.get("rsi_14") or {}).get("value")
    out.add(check_value("technical", "rsi_reading", _first_number(rep.rsi_reading), rsi))

    # The MACD bias is a claim about a sign, so it is checked as a sign, not as a
    # number. This is the class of check that catches a swapped-column bug.
    macd = ind.get("macd") or {}
    if rep.macd_reading and macd.get("bias"):
        low = rep.macd_reading.lower()
        claimed_bull, claimed_bear = "bull" in low, "bear" in low
        if claimed_bull or claimed_bear:
            agrees = ((claimed_bull and macd["bias"] == "Bullish")
                      or (claimed_bear and macd["bias"] == "Bearish"))
            out.add(Check("technical", "macd_reading", rep.macd_reading, macd["bias"],
                          OK if agrees else MISMATCH,
                          f"claimed {'bullish' if claimed_bull else 'bearish'}, "
                          f"histogram says {macd['bias']}"))
        else:
            out.add(Check("technical", "macd_reading", rep.macd_reading, macd["bias"],
                          UNVERIFIABLE, "reading states no directional bias"))

    sma50 = ind.get("sma_50") or {}
    if rep.sma_reading and sma50.get("price_position"):
        low = rep.sma_reading.lower()
        if "above" in low or "below" in low:
            claimed_above = "above" in low
            agrees = claimed_above == (sma50["price_position"] == "above")
            out.add(Check("technical", "sma_reading", rep.sma_reading,
                          f"price {sma50['price_position']} SMA-50",
                          OK if agrees else MISMATCH,
                          f"claimed price {'above' if claimed_above else 'below'} its "
                          f"moving average; source says {sma50['price_position']} SMA-50"))

    # Support and resistance must bracket reality: a level outside the observed
    # range is not a level, it is a number.
    if not ctx.prices.empty:
        window = ctx.prices.tail(252)
        lo, hi = float(window["low"].min()), float(window["high"].max())
        for name, val in (("support_inr", rep.support_inr),
                          ("resistance_inr", rep.resistance_inr)):
            v = _num(val)
            if v is None:
                out.add(Check("technical", name, None, f"{lo:.2f}-{hi:.2f}",
                              UNVERIFIABLE, "no level supplied"))
                continue
            if ctx.last_close and magnitude_ratio(v, ctx.last_close) >= MAGNITUDE_THRESHOLD:
                out.add(Check("technical", name, v, ctx.last_close, MAGNITUDE,
                              f"level {v:,.2f} is {magnitude_ratio(v, ctx.last_close):,.0f}x "
                              f"the last close {ctx.last_close:,.2f}"))
            elif not (lo * 0.8 <= v <= hi * 1.2):
                out.add(Check("technical", name, v, f"{lo:,.2f}-{hi:,.2f}", IMPLAUSIBLE,
                              f"level {v:,.2f} sits outside the 52-week range "
                              f"{lo:,.2f}-{hi:,.2f} (+/-20%)"))
            else:
                out.add(Check("technical", name, v, f"{lo:,.2f}-{hi:,.2f}", OK,
                              f"level {v:,.2f} lies within the observed range"))

    s, r = _num(rep.support_inr), _num(rep.resistance_inr)
    if s is not None and r is not None:
        out.add(Check("technical", "support_vs_resistance", f"{s:,.2f}/{r:,.2f}", None,
                      OK if s <= r else MISMATCH,
                      "support below resistance" if s <= r
                      else f"support {s:,.2f} is ABOVE resistance {r:,.2f}"))


def reconcile_fundamental(rep, ctx, out: ReconciliationReport) -> None:
    """Fundamental claims against admissible source metrics.

    In strict point-in-time mode `metrics` is empty by design, so a NUMBER
    reported here came from somewhere other than the evidence. That is recorded as
    FABRICATED: it is recall leaking in through the weights, which is precisely
    the leakage the data layer cannot stop on its own.
    """
    if rep is None:
        return
    metrics = ((ctx.fundamentals or {}).get("metrics")) or {}
    admissible = bool(metrics)

    for field_name, source_key, unit in (
        ("pe_ratio", "pe_trailing", ""),
        ("revenue_growth_pct", "revenue_growth_pct", "%"),
        ("debt_to_equity", "debt_to_equity", ""),
    ):
        claimed = getattr(rep, field_name, None)
        if claimed is None:
            out.add(Check("fundamental", field_name, None, metrics.get(source_key),
                          OK, "correctly reported as unavailable"))
            continue
        if not admissible:
            out.add(Check("fundamental", field_name, claimed, None, FABRICATED,
                          f"reported {claimed} but no point-in-time value was supplied at "
                          f"{ctx.as_of} - the model sourced this from outside the evidence"))
            continue
        out.add(check_value("fundamental", field_name, claimed,
                            metrics.get(source_key), unit=unit))

    iv = _num(rep.intrinsic_value_inr)
    if iv is not None and ctx.last_close:
        if magnitude_ratio(iv, ctx.last_close) >= MAGNITUDE_THRESHOLD:
            out.add(Check("fundamental", "intrinsic_value_inr", iv, ctx.last_close, MAGNITUDE,
                          f"fair value {iv:,.2f} is {magnitude_ratio(iv, ctx.last_close):,.0f}x "
                          f"the last close {ctx.last_close:,.2f} - check lakh/crore units"))
        else:
            out.add(Check("fundamental", "intrinsic_value_inr", iv, ctx.last_close, OK,
                          f"fair value {iv:,.2f} is the same order as the price"))


def reconcile_sentiment(rep, ctx, out: ReconciliationReport) -> None:
    """Sentiment claims against the headlines we actually supplied."""
    if rep is None:
        return
    heads = ((ctx.news or {}).get("headlines")) or []
    supplied_urls = {(h.get("url") or "").strip() for h in heads if h.get("url")}

    out.add(check_value("sentiment", "headline_count", rep.headline_count, len(heads),
                        tolerance_pct=0.0))

    # A cited link we never supplied was invented. This is the cheapest and most
    # damning hallucination test available: the ground truth is a set we own.
    if rep.article_links:
        invented = [u for u in rep.article_links
                    if u.strip() and u.strip() not in supplied_urls]
        if invented:
            out.add(Check("sentiment", "article_links", invented,
                          f"{len(supplied_urls)} supplied", FABRICATED,
                          f"{len(invented)} of {len(rep.article_links)} cited links were "
                          f"never supplied to the model, e.g. {invented[0][:80]}"))
        else:
            out.add(Check("sentiment", "article_links", len(rep.article_links),
                          len(supplied_urls), OK, "every cited link was supplied"))
    else:
        out.add(Check("sentiment", "article_links", [], len(supplied_urls),
                      UNVERIFIABLE, "no links cited"))

    for name, lo, hi in (("polarity", -1.0, 1.0), ("relevance", 0.0, 1.0),
                         ("confidence", 0.0, 1.0)):
        v = _num(getattr(rep, name, None))
        if v is None:
            continue
        out.add(Check("sentiment", name, v, f"[{lo}, {hi}]",
                      OK if lo <= v <= hi else IMPLAUSIBLE,
                      f"{v} within [{lo}, {hi}]" if lo <= v <= hi
                      else f"{v} is outside the declared range [{lo}, {hi}]"))


def reconcile_macro(rep, ctx, out: ReconciliationReport) -> None:
    """Macro claims against the indicator payload.

    The macro report is mostly prose, so the verifiable surface is small: we check
    that the model has not asserted a repo rate other than the one it was given.
    Recording the rest as unverifiable is deliberate - see the module docstring on
    gates that pass by checking nothing.
    """
    if rep is None:
        return
    macro = ctx.macro or {}
    repo = (macro.get("repo_rate") or {}).get("repo_rate_pct")

    text = " ".join(filter(None, [rep.rates_reading, rep.reasoning] + list(rep.key_indicators)))
    m = re.search(r"repo[^0-9%]{0,30}(\d+(?:\.\d+)?)\s*%", text, re.IGNORECASE)
    if m and repo is not None:
        out.add(check_value("macro", "repo_rate_pct", float(m.group(1)), repo,
                            tolerance_pct=1.0, unit="%"))
    else:
        out.add(Check("macro", "repo_rate_pct", m.group(1) if m else None, repo,
                      UNVERIFIABLE, "no repo rate stated in the report"))


def _plausible_move_pct(ctx) -> float:
    """How far this stock could plausibly move over the horizon, from its own vol.

    Falls back to a wide default when volatility is unavailable, because a gate
    that fires on missing data trains everyone to ignore it.
    """
    vol = (ctx.indicators or {}).get("realised_vol_21") or {}
    ann = _num(vol.get("annualised_vol"))
    if ann is None or ann <= 0:
        return 35.0
    sigma_h = ann * math.sqrt(max(1, ctx.horizon_sessions) / 252.0) * 100.0
    return max(SIGMA_LIMIT * sigma_h, 10.0)


def reconcile_forecast(forecast, ctx, out: ReconciliationReport,
                       *, clamp_targets: bool = False) -> None:
    """The final target range - the number a reader will actually act on."""
    if forecast is None:
        return
    f = forecast
    lo, hi = _num(f.target_low_inr), _num(f.target_high_inr)
    last = _num(ctx.last_close)

    if lo is not None and hi is not None:
        out.add(Check("forecast", "target_range", f"{lo:,.2f}-{hi:,.2f}", None,
                      OK if lo <= hi else MISMATCH,
                      "range is ordered" if lo <= hi
                      else f"target_low {lo:,.2f} exceeds target_high {hi:,.2f}"))

    conf = _num(f.confidence_pct)
    if conf is not None:
        out.add(Check("forecast", "confidence_pct", conf, "[0, 100]",
                      OK if 0 <= conf <= 100 else IMPLAUSIBLE,
                      f"{conf}% in range" if 0 <= conf <= 100
                      else f"{conf}% is outside 0-100"))

    if last is None or lo is None or hi is None:
        out.add(Check("forecast", "target_plausibility", None, None, UNVERIFIABLE,
                      "no last close or no target range to test"))
        return

    mid = (lo + hi) / 2.0
    if magnitude_ratio(mid, last) >= MAGNITUDE_THRESHOLD:
        out.add(Check("forecast", "target_magnitude", mid, last, MAGNITUDE,
                      f"target midpoint {mid:,.2f} is {magnitude_ratio(mid, last):,.0f}x the "
                      f"last close {last:,.2f} - lakh/crore magnitude error"))
        return

    implied_pct = (mid / last - 1) * 100.0
    limit = _plausible_move_pct(ctx)
    if abs(implied_pct) > limit:
        note = (f"target implies {implied_pct:+.1f}% over {ctx.horizon_sessions} sessions; "
                f"{SIGMA_LIMIT:.0f}-sigma of this stock's realised volatility is "
                f"+/-{limit:.1f}%")
        if clamp_targets:
            scale = limit / abs(implied_pct)
            f.target_low_inr = round(last * (1 + (lo / last - 1) * scale), 2)
            f.target_high_inr = round(last * (1 + (hi / last - 1) * scale), 2)
            out.clamped.append(f"target range clamped to +/-{limit:.1f}%")
            note += " - CLAMPED (demo mode; never enabled in a scored run)"
        out.add(Check("forecast", "target_plausibility", round(implied_pct, 2),
                      f"+/-{limit:.1f}%", IMPLAUSIBLE, note))
    else:
        out.add(Check("forecast", "target_plausibility", round(implied_pct, 2),
                      f"+/-{limit:.1f}%", OK,
                      f"target implies {implied_pct:+.1f}%, within the volatility bound"))

    # The NSE daily price band is the binding constraint only for a one-session
    # horizon; over 21 sessions it compounds to a bound that never binds.
    if ctx.horizon_sessions == 1:
        from backend.tools.indicators import price_band_check

        band = price_band_check(last, mid)
        out.add(Check("forecast", "nse_price_band", mid, last,
                      OK if band.get("within_band") else IMPLAUSIBLE,
                      band.get("note") or "within the NSE daily price band"))


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def reconcile(
    ctx,
    *,
    technical=None,
    fundamental=None,
    sentiment=None,
    macro=None,
    forecast=None,
    clamp_targets: bool = False,
) -> ReconciliationReport:
    """Verify every checkable numeric claim against the cached source data.

    Called twice in the pipeline: once after the specialists, so a bad number
    cannot enter the debate, and once after the synthesiser, so a bad number
    cannot leave the system. Never raises - the report is data, and a run that
    aborted on a mismatch could not be scored.
    """
    out = ReconciliationReport()
    reconcile_technical(technical, ctx, out)
    reconcile_fundamental(fundamental, ctx, out)
    reconcile_sentiment(sentiment, ctx, out)
    reconcile_macro(macro, ctx, out)
    reconcile_forecast(forecast, ctx, out, clamp_targets=clamp_targets)
    return out
