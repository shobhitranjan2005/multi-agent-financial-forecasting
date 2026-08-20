"""Indian macro context, vintage-aware (Task 2.7).

Sources, and why each one:

FRED (keyless CSV, or the API when FRED_API_KEY is set) — verified 2026-08-06:
    DEXINUS          USD/INR, daily      -> usable
    INDIRLTLT01STM   India 10Y G-sec     -> usable (monthly)
    IRSTCI01INM156N  call money rate     -> usable (monthly), policy-stance proxy
    INDCPIALLMINMEI  India CPI           -> STALE (last obs 2025-03). Not used.
    INDPROINDMISMEI  India IIP           -> DEAD (last obs 2023-01). Not used.
    INTDSRINM193N    discount rate       -> DEAD (last obs 2022-07). Not used.

yfinance — NIFTY 50, SENSEX, India VIX, USD/INR, Brent, NIFTY sectoral indices.

RBI repo rate — NOT reliably available on FRED, so it comes from the hardcoded
decision calendar below. See the warning on that table: it must be verified
against RBI before any number from it goes in the report.

DATA VINTAGE is enforced, not assumed. CPI for month M is published in month M+1;
a forecast dated mid-M must not see it. Every series therefore carries a
publication lag, and observations are filtered on `obs_date + lag <= as_of`
rather than on the observation date alone. Filtering on observation date is the
subtle version of lookahead bias and it is easy to ship by accident.
"""
from __future__ import annotations

import csv
import io
import warnings
from datetime import date, datetime, timedelta
from typing import Any, Optional

import httpx

from backend.cache import get_cache
from backend.config import Config
from backend.tools import market_data, tickers

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_API = "https://api.stlouisfed.org/fred/series/observations"

# series_id -> (label, publication lag in days)
# The lag is how long after the observation period the figure actually appears.
USABLE_SERIES: dict[str, tuple[str, int]] = {
    "DEXINUS": ("USD/INR (FRED, daily)", 3),
    "INDIRLTLT01STM": ("India 10Y government bond yield %", 40),
    "IRSTCI01INM156N": ("India call money rate % (policy-stance proxy)", 40),
}

# Series verified dead or stale on 2026-08-06. Kept documented so nobody
# re-adds them believing they work.
UNUSABLE_SERIES = {
    "INDCPIALLMINMEI": "India CPI - stale, last observation 2025-03",
    "INDPROINDMISMEI": "India IIP - dead, last observation 2023-01",
    "INTDSRINM193N": "India discount rate - dead, last observation 2022-07",
}

# ---------------------------------------------------------------------------
# RBI repo rate decision calendar.
#
# WARNING - VERIFY BEFORE CITING. This table is hardcoded because the repo rate
# is not reliably on FRED. It changes roughly six times a year, is public, and is
# trivially auditable at rbi.org.in. Entries are (effective_date, repo_rate_pct).
# Anything at or after RBI_VERIFIED_THROUGH is unverified: get_macro_data flags
# it in the returned payload rather than quietly serving a possibly-wrong rate.
# ---------------------------------------------------------------------------
RBI_REPO_RATE: list[tuple[date, float]] = [
    (date(2019, 8, 7), 5.40),
    (date(2019, 10, 4), 5.15),
    (date(2020, 3, 27), 4.40),
    (date(2020, 5, 22), 4.00),
    (date(2022, 5, 4), 4.40),
    (date(2022, 6, 8), 4.90),
    (date(2022, 8, 5), 5.40),
    (date(2022, 9, 30), 5.90),
    (date(2022, 12, 7), 6.25),
    (date(2023, 2, 8), 6.50),
    (date(2025, 2, 7), 6.25),
    (date(2025, 4, 9), 6.00),
    (date(2025, 6, 6), 5.50),
]
RBI_VERIFIED_THROUGH = date(2025, 8, 31)


def _as_date(d: str | date | datetime) -> date:
    if isinstance(d, str):
        return datetime.fromisoformat(d).date()
    if isinstance(d, datetime):
        return d.date()
    return d


def repo_rate_at(as_of: str | date | datetime) -> dict:
    """Repo rate in force at `as_of`, with an explicit verification flag."""
    d = _as_date(as_of)
    rate: Optional[float] = None
    effective: Optional[date] = None
    for eff, r in RBI_REPO_RATE:
        if eff <= d:
            rate, effective = r, eff
        else:
            break
    return {
        "repo_rate_pct": rate,
        "effective_from": effective.isoformat() if effective else None,
        "verified": d <= RBI_VERIFIED_THROUGH,
        "note": None if d <= RBI_VERIFIED_THROUGH else (
            f"as_of {d} is beyond the verified window (through {RBI_VERIFIED_THROUGH}); "
            "confirm the repo rate against rbi.org.in before using this in the report"
        ),
    }


def _fetch_fred_series(series_id: str) -> list[tuple[date, float]]:
    """Full observation history for a FRED series. Cached permanently per series
    and sliced locally, so the vintage filter is applied here rather than by the
    remote endpoint."""
    cache = get_cache()

    def loader() -> list[list]:
        params: dict[str, Any]
        if Config.FRED_API_KEY and Config.FRED_API_KEY != "your_fred_key_here":
            params = {
                "series_id": series_id,
                "api_key": Config.FRED_API_KEY,
                "file_type": "json",
            }
            with httpx.Client(timeout=45.0) as c:
                r = c.get(FRED_API, params=params)
                r.raise_for_status()
                obs = r.json().get("observations", [])
            rows = [(o["date"], o["value"]) for o in obs]
        else:
            # Keyless CSV path — works without registration.
            with httpx.Client(timeout=45.0, headers={"User-Agent": Config.BROWSER_UA}) as c:
                r = c.get(FRED_CSV, params={"id": series_id})
                r.raise_for_status()
                text = r.text
            reader = csv.reader(io.StringIO(text))
            header = next(reader, None)
            rows = [(row[0], row[1]) for row in reader if len(row) >= 2]

        out: list[list] = []
        for d_str, v_str in rows:
            if v_str in (".", "", None):
                continue  # FRED marks missing observations with a dot
            try:
                out.append([d_str, float(v_str)])
            except ValueError:
                continue
        return out

    raw = cache.historical("fred", series_id, "observations", "full", loader)
    return [(datetime.fromisoformat(d).date(), v) for d, v in raw]


def get_fred_value(series_id: str, as_of: str | date | datetime) -> Optional[dict]:
    """Latest observation of `series_id` that was PUBLISHED on or before `as_of`."""
    if series_id in UNUSABLE_SERIES:
        warnings.warn(f"{series_id}: {UNUSABLE_SERIES[series_id]}", RuntimeWarning)
        return None
    d = _as_date(as_of)
    label, lag = USABLE_SERIES.get(series_id, (series_id, 30))
    try:
        obs = _fetch_fred_series(series_id)
    except Exception as exc:
        warnings.warn(f"FRED {series_id} unavailable: {exc}", RuntimeWarning)
        return None

    # Vintage filter: the figure for obs_date only became public at obs_date+lag.
    visible = [(od, v) for od, v in obs if od + timedelta(days=lag) <= d]
    if not visible:
        return None
    obs_date, value = max(visible, key=lambda t: t[0])
    return {
        "series_id": series_id,
        "label": label,
        "value": value,
        "observation_date": obs_date.isoformat(),
        "published_by": (obs_date + timedelta(days=lag)).isoformat(),
    }


def _market_driver(symbol: str, as_of: date, label: str) -> Optional[dict]:
    """Level and trailing change for a market driver, capped at as_of."""
    try:
        start = date(as_of.year - 1, as_of.month, min(as_of.day, 28))
        df = market_data.get_raw_history(symbol, start=start, end=as_of, as_of=as_of)
        if df is None or df.empty:
            return None
        close = df["close"]
        out = {"label": label, "symbol": symbol, "last": round(float(close.iloc[-1]), 2)}
        for n, key in ((21, "change_21d_pct"), (252, "change_252d_pct")):
            out[key] = (
                round(float(close.iloc[-1] / close.iloc[-n - 1] - 1) * 100, 2)
                if len(close) > n else None
            )
        return out
    except Exception as exc:
        warnings.warn(f"{symbol} unavailable: {exc}", RuntimeWarning)
        return None


def get_sector_performance(
    sector: str, as_of: str | date | datetime
) -> Optional[dict]:
    """A NIFTY sectoral index versus NIFTY 50 — not a US sector ETF."""
    d = _as_date(as_of)
    key = (sector or "").upper()
    symbol = Config.SECTOR_INDICES.get(key)
    if symbol is None:
        return None
    idx = _market_driver(symbol, d, f"NIFTY {key}")
    nifty = _market_driver(Config.BENCHMARK, d, "NIFTY 50")
    if not idx or not nifty:
        return idx
    rel = None
    if idx.get("change_21d_pct") is not None and nifty.get("change_21d_pct") is not None:
        rel = round(idx["change_21d_pct"] - nifty["change_21d_pct"], 2)
    idx["relative_21d_vs_nifty_pct"] = rel
    idx["reading"] = (
        "outperforming NIFTY 50" if rel and rel > 1
        else "underperforming NIFTY 50" if rel and rel < -1
        else "broadly in line with NIFTY 50"
    )
    idx["name"] = f"NIFTY {key}"
    return idx


# Map yfinance sector names onto NIFTY sectoral indices.
_SECTOR_MAP = {
    "technology": "IT",
    "financial services": "BANK",
    "financial": "BANK",
    "consumer cyclical": "AUTO",
    "healthcare": "PHARMA",
    "consumer defensive": "FMCG",
    "basic materials": "METAL",
    "energy": "ENERGY",
    "real estate": "REALTY",
    "utilities": "ENERGY",
}


def get_macro_data(
    as_of: str | date | datetime, *, ticker: Optional[str] = None
) -> dict:
    """Indian macro regime at `as_of`, respecting publication vintage."""
    d = _as_date(as_of)
    notes: list[str] = []
    indicators: dict[str, Any] = {}

    repo = repo_rate_at(d)
    indicators["RBI repo rate %"] = repo["repo_rate_pct"]
    if repo.get("note"):
        notes.append(repo["note"])
    else:
        notes.append(f"repo rate effective from {repo['effective_from']} (hardcoded RBI calendar)")

    for series_id in USABLE_SERIES:
        got = get_fred_value(series_id, d)
        if got:
            indicators[got["label"]] = f"{got['value']} (obs {got['observation_date']})"
        else:
            indicators[USABLE_SERIES[series_id][0]] = None
            notes.append(f"{series_id} unavailable at this as_of")

    notes.append(
        "India CPI and IIP are not sourced from FRED: those series are stale/dead "
        "(verified 2026-08-06). CPI is a documented limitation, not a fabricated series."
    )

    drivers = {}
    for label, symbol in (
        ("NIFTY 50", Config.BENCHMARK),
        ("SENSEX", Config.BENCHMARK_ALT),
        ("India VIX", Config.VIX_SYMBOL),
        ("USD/INR", Config.USDINR_SYMBOL),
        ("Brent crude", Config.CRUDE_SYMBOL),
    ):
        got = _market_driver(symbol, d, label)
        if got:
            drivers[label] = got
            indicators[label] = (
                f"{got['last']} ({got.get('change_21d_pct')}% over 21 sessions)"
            )
        else:
            indicators[label] = None

    sector_block = None
    if ticker:
        try:
            from backend.tools.fundamentals import get_company_info
            sec = (get_company_info(tickers.resolve(ticker)).get("sector") or "").lower()
            mapped = _SECTOR_MAP.get(sec)
            if mapped:
                sector_block = get_sector_performance(mapped, d)
            else:
                notes.append(f"sector '{sec or 'unknown'}' has no NIFTY sectoral index mapping")
        except Exception as exc:
            notes.append(f"sector lookup failed: {exc}")

    return {
        "as_of": d.isoformat(),
        "indicators": indicators,
        "drivers": drivers,
        "repo_rate": repo,
        "sector": sector_block,
        "notes": notes,
        "limitations": [
            "India CPI unavailable from FRED (series stale). Documented, not estimated.",
            "RBI repo rate comes from a hardcoded decision calendar; verify against rbi.org.in.",
        ],
    }


def analyse_macro(
    macro: dict, ticker: str, as_of: str, *, temperature: float = 0.0, nonce: str = ""
):
    """Turn the macro payload into a MacroReport via Gemini."""
    from backend.agents.base import run_specialist
    from backend.agents.schemas import MacroReport
    from backend.prompts import MACRO_ROLE

    lines = [f"  {k}: {'unavailable' if v is None else v}" for k, v in macro["indicators"].items()]
    if macro.get("sector"):
        s = macro["sector"]
        lines.append(f"  {s.get('name')}: {s.get('reading')} "
                     f"(21d relative {s.get('relative_21d_vs_nifty_pct')}%)")
    evidence = "INDIAN MACRO INDICATORS\n" + "\n".join(lines)
    if macro.get("notes"):
        evidence += "\n\nNOTES\n" + "\n".join(f"  - {n}" for n in macro["notes"])

    task = f"""Judge the Indian macro backdrop for {ticker} as of {as_of}.

Rate the regime as Tailwind, Neutral or Headwind FOR THIS STOCK specifically -
not for the market in general. An IT exporter and a rate-sensitive bank face
opposite implications from the same USD/INR move, so say which way it cuts here.
Where an indicator is unavailable, say so rather than assuming a value."""

    return run_specialist(
        role=MACRO_ROLE,
        task=task,
        evidence=evidence,
        schema=MacroReport,
        as_of=as_of,
        temperature=temperature,
        nonce=nonce,
    )
