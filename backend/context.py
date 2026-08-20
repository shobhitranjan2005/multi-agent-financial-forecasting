"""Evidence pack assembly.

The single-LLM baseline and the multi-agent system must see EXACTLY the same
evidence, or the comparison between them measures data access rather than
reasoning architecture — and the whole research question collapses. So both build
their evidence from here.

Everything is assembled at `as_of`. No function in this module can see past it,
because every underlying tool enforces the cutoff itself.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

import pandas as pd

from backend.config import Config
from backend.money import format_inr
from backend.tools import calendar_nse, indicators, market_data, tickers


def _as_date(d: str | date | datetime) -> date:
    if isinstance(d, str):
        return datetime.fromisoformat(d).date()
    if isinstance(d, datetime):
        return d.date()
    return d


@dataclass
class MarketContext:
    """Everything a forecaster is allowed to know at `as_of`."""

    ticker: str
    as_of: date
    last_close: Optional[float]
    prices: pd.DataFrame
    indicators: dict[str, Any]
    benchmark: dict[str, Any]
    horizon_sessions: int
    target_date: Optional[date]
    source: str
    # Phase 2 additions — absent in the Phase 1 walking skeleton.
    fundamentals: Optional[dict] = None
    news: Optional[dict] = None
    macro: Optional[dict] = None
    notes: list[str] = field(default_factory=list)

    # ---- prompt rendering ----

    def price_block(self) -> str:
        if self.prices.empty:
            return "PRICE DATA: unavailable."
        tail = self.prices.tail(20)
        rows = [
            f"  {d.date()}  O {r.open:>9.2f}  H {r.high:>9.2f}  "
            f"L {r.low:>9.2f}  C {r.close:>9.2f}  Vol {int(r.volume):>12,}"
            for d, r in tail.iterrows()
        ]
        window = self.prices.tail(252)
        return (
            f"PRICE HISTORY for {self.ticker} (source: {self.source}, INR)\n"
            f"Last close on {self.as_of}: {format_inr(self.last_close)}\n"
            f"52-week range: {format_inr(float(window['low'].min()))} - "
            f"{format_inr(float(window['high'].max()))}\n"
            f"Rows available: {len(self.prices)} sessions ending {self.prices.index[-1].date()}\n"
            "Last 20 sessions:\n" + "\n".join(rows)
        )

    def indicator_block(self) -> str:
        if not self.indicators:
            return "INDICATORS: unavailable."
        lines = []
        for name, val in self.indicators.items():
            if val is None:
                lines.append(f"  {name}: unavailable (insufficient history)")
            elif isinstance(val, dict):
                inner = ", ".join(f"{k}={v}" for k, v in val.items())
                lines.append(f"  {name}: {inner}")
            else:
                lines.append(f"  {name}: {val}")
        return "TECHNICAL INDICATORS (as of " + str(self.as_of) + ")\n" + "\n".join(lines)

    def benchmark_block(self) -> str:
        if not self.benchmark:
            return "BENCHMARK: unavailable."
        b = self.benchmark
        return (
            f"BENCHMARK — NIFTY 50 ({Config.BENCHMARK})\n"
            f"  Last close: {b.get('last_close')}\n"
            f"  Return over last 21 sessions: {b.get('return_21d_pct')}%\n"
            f"  Return over last 252 sessions: {b.get('return_252d_pct')}%\n"
            "  Note: the stock is scored on direction AND on whether it beat this index."
        )

    def extras_block(self) -> str:
        """Phase 2 evidence, rendered only when present."""
        out = []
        if self.fundamentals:
            out.append(_render_fundamentals(self.fundamentals))
        if self.news:
            out.append(_render_news(self.news))
        if self.macro:
            out.append(_render_macro(self.macro))
        return "\n\n".join(out)

    def to_prompt(self, *, include_extras: bool = True) -> str:
        blocks = [
            f"TICKER: {self.ticker}   AS OF: {self.as_of}   "
            f"HORIZON: {self.horizon_sessions} trading sessions "
            f"(target date {self.target_date})",
            self.price_block(),
            self.indicator_block(),
            self.benchmark_block(),
        ]
        if include_extras:
            extra = self.extras_block()
            if extra:
                blocks.append(extra)
        if self.notes:
            blocks.append("DATA NOTES:\n" + "\n".join(f"  - {n}" for n in self.notes))
        return "\n\n".join(blocks)


def _render_fundamentals(f: dict) -> str:
    """Render ONLY admissible fundamentals.

    Reads f["metrics"], never f["current_snapshot"]. The snapshot holds today's
    valuation figures, which are recorded for the report's null-rate table but
    must never reach a prompt dated in the past — that would be the lookahead
    bias this project claims to remove.
    """
    lines = ["FUNDAMENTALS (point-in-time; SEBI filing lag applied)"]
    metrics = f.get("metrics") or {}
    if metrics:
        for k, v in metrics.items():
            lines.append(f"  {k}: {'unavailable' if v is None else v}")
    else:
        lines.append("  No point-in-time valuation metrics are admissible at this as_of.")
        lines.append("  Do not assume a valuation. Treat fundamentals as UNKNOWN here.")

    quarters = f.get("quarters_visible") or []
    if quarters:
        lines.append("  Quarterly results public at as_of:")
        for q in quarters:
            lines.append(
                f"    {q['quarter_end']}: revenue={q.get('total_revenue')} "
                f"net_income={q.get('net_income')} (filed by {q.get('filing_date_earliest')})"
            )
    else:
        lines.append("  No quarterly results were public at as_of under the SEBI 45-day rule.")

    if f.get("hidden_quarters"):
        lines.append("  Withheld as not-yet-filed: " + ", ".join(f["hidden_quarters"]))
    if f.get("sector"):
        lines.append(f"  Sector: {f['sector']} / {f.get('industry')}")
    return "\n".join(lines)


def _render_news(n: dict) -> str:
    heads = n.get("headlines", [])
    if not heads:
        return "NEWS: no qualifying Indian-press coverage found at or before as_of."
    lines = [f"NEWS — {len(heads)} unique Indian-press headlines at or before as_of",
             "<headlines>"]
    for h in heads[:40]:
        lines.append(f"  [{h.get('date', '?')}] {h.get('title', '')} ({h.get('domain', '')})")
    lines.append("</headlines>")
    return "\n".join(lines)


def _render_macro(m: dict) -> str:
    lines = ["INDIAN MACRO CONTEXT"]
    for k, v in m.get("indicators", {}).items():
        lines.append(f"  {k}: {'unavailable' if v is None else v}")
    if m.get("sector"):
        lines.append(f"  Sector index ({m['sector'].get('name')}): {m['sector'].get('reading')}")
    if m.get("notes"):
        lines.extend(f"  note: {n}" for n in m["notes"])
    return "\n".join(lines)


def _benchmark_summary(as_of: date) -> dict:
    """NIFTY 50 levels and trailing returns — needed for relative scoring."""
    try:
        start = date(as_of.year - 3, as_of.month, min(as_of.day, 28))
        bench = market_data.get_benchmark_history(
            start=start.isoformat(), end=as_of.isoformat(), as_of=as_of.isoformat()
        )
        if bench.empty:
            return {}
        close = bench["close"]
        out = {"last_close": round(float(close.iloc[-1]), 2)}
        for n, label in ((21, "return_21d_pct"), (252, "return_252d_pct")):
            if len(close) > n:
                out[label] = round(float(close.iloc[-1] / close.iloc[-n - 1] - 1) * 100, 2)
            else:
                out[label] = None
        return out
    except Exception as exc:  # benchmark is useful, not essential
        warnings.warn(f"benchmark unavailable: {exc}", RuntimeWarning)
        return {}


def build(
    ticker: str,
    as_of: str | date | datetime,
    *,
    horizon_sessions: int = Config.HORIZON_SESSIONS,
    with_fundamentals: bool = False,
    with_news: bool = False,
    with_macro: bool = False,
) -> MarketContext:
    """Assemble the evidence pack for one (ticker, as_of).

    The Phase 2 tools are opt-in so the Phase 1 skeleton stays fast and so the
    leave-one-out ablation in Phase 4 can drop a specialist's evidence cleanly.
    """
    as_of_d = _as_date(as_of)
    # Resolve against the universe as it stood at as_of, not today's — otherwise a
    # since-delisted or demerged name (TATAMOTORS after its 2025 split) is rejected
    # on dates when it was trading normally, silently dropping the very cases a
    # survivorship-aware evaluation needs.
    ticker = tickers.resolve(ticker, as_of=as_of_d)

    # Snap onto a real NSE session. An as_of on Diwali is a bug, not a forecast.
    snapped = calendar_nse.previous_trading_day(as_of_d)
    notes: list[str] = []
    if snapped != as_of_d:
        notes.append(f"as_of {as_of_d} was not an NSE trading day; snapped back to {snapped}")
    as_of_d = snapped

    start = date(as_of_d.year - 3, as_of_d.month, min(as_of_d.day, 28))
    prices = market_data.get_price_history(
        ticker, start=start.isoformat(), end=as_of_d.isoformat(), as_of=as_of_d.isoformat()
    )

    last_close = float(prices["close"].iloc[-1]) if not prices.empty else None
    if prices.empty:
        notes.append("no price rows returned for this ticker at this as_of")

    ind = indicators.compute_all(prices) if not prices.empty else {}
    for name, val in ind.items():
        if val is None:
            notes.append(f"{name} unavailable (insufficient history)")

    try:
        target_date = calendar_nse.add_trading_days(as_of_d, horizon_sessions)
    except Exception:
        target_date = None

    ctx = MarketContext(
        ticker=ticker,
        as_of=as_of_d,
        last_close=last_close,
        prices=prices,
        indicators=ind,
        benchmark=_benchmark_summary(as_of_d),
        horizon_sessions=horizon_sessions,
        target_date=target_date,
        source=prices.attrs.get("source", "unknown") if not prices.empty else "none",
        notes=notes,
    )

    # Phase 2 evidence. Imported lazily so Phase 1 does not depend on them.
    if with_fundamentals:
        from backend.tools import fundamentals as _f
        try:
            ctx.fundamentals = _f.get_fundamentals(ticker, as_of_d)
        except Exception as exc:
            ctx.notes.append(f"fundamentals unavailable: {exc}")
    if with_news:
        from backend.tools import news_sentiment as _n
        try:
            ctx.news = _n.get_news(ticker, as_of_d)
        except Exception as exc:
            ctx.notes.append(f"news unavailable: {exc}")
    if with_macro:
        from backend.tools import macro as _m
        try:
            ctx.macro = _m.get_macro_data(as_of_d, ticker=ticker)
        except Exception as exc:
            ctx.notes.append(f"macro unavailable: {exc}")

    return ctx
