"""Point-in-time fundamentals for NSE/BSE companies (Task 2.5).

The leakage control here is the SEBI filing lag. Under SEBI LODR Reg. 33 a listed
company files quarterly results within 45 days of quarter end (60 for annual). So
Q3 FY25 numbers, for a quarter ending 31 Dec 2024, were NOT public until roughly
14 Feb 2025. A backtest dated 20 Jan 2025 that can see them is reading the future.

Rule: a quarter is visible only if `as_of` >= quarter_end + 45 days.

DOCUMENTED LIMITATION — state this in the report. yfinance serves TODAY's
financials, which are restated figures. The 45-day rule fixes *timing* leakage;
it does not fix *restatement* leakage. If a company later restated a number, we
see the restated version, not what the market saw at the time. True point-in-time
fundamentals are an institutional product (CapIQ, Refinitiv) and are out of scope
for a free-data BTP. Saying so plainly is worth more marks than pretending
otherwise.

Null handling: yfinance coverage of .NS fundamentals is patchier than for US
tickers — EV/EBITDA and several margin fields are frequently missing on mid- and
small-caps. Every missing field is recorded rather than filled. The per-field null
rate is a table in the report and feeds the Phase 4 large-cap vs mid-cap analysis.
"""
from __future__ import annotations

import math
import warnings
from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd
import yfinance as yf

from backend.cache import get_cache
from backend.config import Config
from backend.tools import tickers

# Fields we attempt, and the yfinance `.info` keys they map to.
_INFO_FIELDS: dict[str, str] = {
    "market_cap": "marketCap",
    "pe_trailing": "trailingPE",
    "pe_forward": "forwardPE",
    "price_to_book": "priceToBook",
    "ev_to_ebitda": "enterpriseToEbitda",
    "profit_margin_pct": "profitMargins",
    "operating_margin_pct": "operatingMargins",
    "return_on_equity_pct": "returnOnEquity",
    "debt_to_equity": "debtToEquity",
    "revenue_growth_pct": "revenueGrowth",
    "earnings_growth_pct": "earningsGrowth",
    "dividend_yield_pct": "dividendYield",
    "beta": "beta",
    "book_value_per_share": "bookValue",
}

# Fields yfinance expresses as fractions but which read naturally as percentages.
_FRACTION_FIELDS = {
    "profit_margin_pct", "operating_margin_pct", "return_on_equity_pct",
    "revenue_growth_pct", "earnings_growth_pct", "dividend_yield_pct",
}


def _as_date(d: str | date | datetime) -> date:
    if isinstance(d, str):
        return datetime.fromisoformat(d).date()
    if isinstance(d, datetime):
        return d.date()
    return d


def _clean(value: Any) -> Optional[float]:
    """yfinance returns None, NaN, or occasionally a string. Normalise to float|None."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def filing_date(quarter_end: date, *, annual: bool = False) -> date:
    """Earliest date a quarter's numbers can be assumed public (SEBI LODR Reg. 33)."""
    lag = Config.SEBI_ANNUAL_FILING_LAG_DAYS if annual else Config.SEBI_QUARTERLY_FILING_LAG_DAYS
    return quarter_end + timedelta(days=lag)


def is_visible(quarter_end: date, as_of: date, *, annual: bool = False) -> bool:
    """Was this quarter's result public at `as_of`?"""
    return as_of >= filing_date(quarter_end, annual=annual)


def get_fundamentals(
    ticker: str,
    as_of: str | date | datetime,
    *,
    strict_point_in_time: bool = True,
) -> dict:
    """Valuation and health metrics, with the SEBI visibility rule applied.

    STRICT POINT-IN-TIME MODE (default, and required for any backtest)
    -----------------------------------------------------------------
    yfinance `.info` is a CURRENT snapshot. Its trailing P/E, market cap and
    margins describe the company today, not at `as_of`. Feeding them into a
    forecast dated in the past is lookahead bias of the most direct kind — the
    model would be told today's valuation while predicting the past.

    So when `as_of` is in the past and strict_point_in_time is True, those fields
    are WITHHELD: they appear in `current_snapshot` (clearly labelled, for the
    live demo and for the report's null-rate table) but never in `metrics`, which
    is what the evidence pack renders.

    What survives the strict filter:
      - sector / industry / name  (static; not a tradable signal)
      - quarterly results whose SEBI filing date had passed at `as_of`

    That is a small amount of evidence, and saying so is the honest result. The
    alternative — quietly serving today's P/E — would invalidate every number in
    the evaluation.

    Returns:
        metrics                -- admissible at as_of (empty in strict past mode)
        current_snapshot       -- today's values, labelled, never admissible
        point_in_time          -- whether `metrics` is safe for a backtest
        unavailable            -- fields the source did not provide
        null_rate              -- fraction of attempted fields that came back None
        latest_visible_quarter
        hidden_quarters        -- quarters excluded because they were not yet filed
        limitations            -- text destined for the report
    """
    ticker = tickers.resolve(ticker)
    as_of_d = _as_date(as_of)
    cache = get_cache()
    # "Today" tolerance: a run dated within a couple of days of now is a live
    # demo, where the current snapshot genuinely is the point-in-time value.
    is_live = (date.today() - as_of_d).days <= 2
    withhold = strict_point_in_time and not is_live

    def loader() -> dict:
        t = yf.Ticker(ticker)
        try:
            info = t.info or {}
        except Exception as exc:
            warnings.warn(f"{ticker}: yfinance .info failed: {exc}", RuntimeWarning)
            info = {}

        metrics: dict[str, Optional[float]] = {}
        unavailable: list[str] = []
        for field, key in _INFO_FIELDS.items():
            val = _clean(info.get(key))
            if val is not None and field in _FRACTION_FIELDS:
                val = round(val * 100.0, 2)
            if val is None:
                unavailable.append(field)
            metrics[field] = val

        # Quarterly income statement, filtered by the SEBI filing rule.
        visible_quarters: list[dict] = []
        hidden_quarters: list[str] = []
        try:
            qf = t.quarterly_financials
            if isinstance(qf, pd.DataFrame) and not qf.empty:
                for col in qf.columns:
                    q_end = pd.Timestamp(col).date()
                    row = qf[col]
                    entry = {
                        "quarter_end": q_end.isoformat(),
                        "filing_date_earliest": filing_date(q_end).isoformat(),
                        "total_revenue": _clean(row.get("Total Revenue")),
                        "net_income": _clean(row.get("Net Income")),
                        "operating_income": _clean(row.get("Operating Income")),
                    }
                    if is_visible(q_end, as_of_d):
                        visible_quarters.append(entry)
                    else:
                        hidden_quarters.append(q_end.isoformat())
        except Exception as exc:
            warnings.warn(f"{ticker}: quarterly financials failed: {exc}", RuntimeWarning)

        visible_quarters.sort(key=lambda q: q["quarter_end"], reverse=True)

        limitations = [
            "yfinance serves restated financials, not originally-reported figures. "
            "The 45-day SEBI rule removes timing leakage but not restatement leakage.",
            f"{len(unavailable)}/{len(_INFO_FIELDS)} fields unavailable from the source.",
        ]
        if withhold:
            limitations.append(
                "Valuation metrics (P/E, market cap, margins, D/E) are a CURRENT yfinance "
                "snapshot and are NOT point-in-time, so they are withheld from this "
                f"backtest dated {as_of_d}. Only SEBI-visible quarterly results and static "
                "company attributes are admissible."
            )
        if not visible_quarters:
            limitations.append(
                "yfinance exposes only the last ~5 quarters, all of which post-date this "
                f"as_of once the SEBI filing lag is applied. Fundamental evidence at "
                f"{as_of_d} is therefore empty — a coverage limit of free data, not a bug."
            )

        return {
            "ticker": ticker,
            "as_of": as_of_d.isoformat(),
            # Admissible evidence only. Empty in strict past mode by design.
            "metrics": {} if withhold else metrics,
            # Always recorded, never admissible in a backtest — feeds the report's
            # null-rate table and the live demo.
            "current_snapshot": metrics,
            "point_in_time": not withhold,
            "unavailable": unavailable,
            "null_rate": round(len(unavailable) / max(1, len(_INFO_FIELDS)), 3),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "name": info.get("longName") or info.get("shortName"),
            "quarters_visible": visible_quarters[:4],
            "latest_visible_quarter": visible_quarters[0]["quarter_end"] if visible_quarters else None,
            "hidden_quarters": hidden_quarters,
            "limitations": limitations,
        }

    # `withhold` changes the payload, so it must be part of the key — otherwise a
    # live-mode call and a backtest call for the same date share an entry and one
    # of them gets the wrong answer.
    field = f"snapshot_v2_{'strict' if withhold else 'full'}"
    return cache.historical("fundamentals", ticker, field, as_of_d.isoformat(), loader)


def get_earnings(ticker: str, as_of: str | date | datetime) -> dict:
    """Last four quarters visible at `as_of`, with QoQ/YoY growth where computable."""
    data = get_fundamentals(ticker, as_of)
    quarters = data.get("quarters_visible", [])
    out = {
        "ticker": data["ticker"],
        "as_of": data["as_of"],
        "quarters": quarters,
        "hidden_by_sebi_rule": data.get("hidden_quarters", []),
    }
    if len(quarters) >= 2:
        cur, prev = quarters[0], quarters[1]
        if cur.get("total_revenue") and prev.get("total_revenue"):
            out["revenue_qoq_pct"] = round(
                (cur["total_revenue"] / prev["total_revenue"] - 1) * 100, 2
            )
    if len(quarters) >= 4:
        cur, yr = quarters[0], quarters[3]
        if cur.get("total_revenue") and yr.get("total_revenue"):
            out["revenue_yoy_pct"] = round(
                (cur["total_revenue"] / yr["total_revenue"] - 1) * 100, 2
            )
    return out


def get_company_info(ticker: str) -> dict:
    """Sector/industry/name. Not point-in-time — a company's sector rarely changes,
    and when it does it is not a tradable signal."""
    ticker = tickers.resolve(ticker)
    cache = get_cache()

    def loader() -> dict:
        try:
            info = yf.Ticker(ticker).info or {}
        except Exception:
            info = {}
        return {
            "ticker": ticker,
            "name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "summary": (info.get("longBusinessSummary") or "")[:1200] or None,
            "currency": info.get("currency"),
            "exchange": info.get("exchange"),
        }

    return cache.historical("fundamentals", ticker, "company_info", "static", loader)
