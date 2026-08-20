"""Realised outcomes — the only place in the codebase allowed to look past `as_of`.

Everything else enforces the cutoff. Scoring cannot: to know whether a forecast
made on 2025-01-15 was right, you must read the price 21 sessions later. That is
legitimate, but it is also exactly the operation that becomes lookahead bias if it
ever runs during forecasting.

So it is quarantined here, in a module no agent, tool or prompt-builder imports.
If `backend/agents/*` or `backend/tools/*` ever imports this module, that is a bug.
test_leakage.py asserts it does not.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from backend.config import Config
from backend.tools import calendar_nse, market_data


def _as_date(d: str | date | datetime) -> date:
    if isinstance(d, str):
        return datetime.fromisoformat(d).date()
    if isinstance(d, datetime):
        return d.date()
    return d


def realised(
    ticker: str,
    as_of: str | date | datetime,
    *,
    horizon_sessions: int = Config.HORIZON_SESSIONS,
) -> dict:
    """What actually happened to `ticker` over the horizon starting at `as_of`.

    Returns start/end closes for the stock and for NIFTY 50, plus the excess
    return — the stock's return minus the index's. Excess return is what stops a
    permanently-bullish model looking skilful on a rising market.
    """
    as_of_d = calendar_nse.previous_trading_day(_as_date(as_of))
    target = calendar_nse.add_trading_days(as_of_d, horizon_sessions)

    out: dict = {
        "ticker": ticker,
        "as_of": as_of_d.isoformat(),
        "target_date": target.isoformat(),
        "horizon_sessions": horizon_sessions,
        "resolved": False,
    }

    today = date.today()
    if target > today:
        out["note"] = f"horizon ends {target}, which is in the future — not yet scoreable"
        return out

    # as_of=target here is the deliberate look-forward: we are scoring, not forecasting.
    try:
        px = market_data.get_price_history(
            ticker,
            start=(as_of_d.replace(year=as_of_d.year - 1)).isoformat(),
            end=target.isoformat(),
            as_of=target.isoformat(),
        )
    except Exception as exc:
        out["note"] = f"price lookup failed: {exc}"
        return out

    if px.empty:
        out["note"] = "no price data"
        return out

    at_start = px.loc[px.index <= str(as_of_d)]
    at_end = px.loc[px.index <= str(target)]
    if at_start.empty or at_end.empty:
        out["note"] = "insufficient price coverage over the horizon"
        return out

    start_px = float(at_start["close"].iloc[-1])
    end_px = float(at_end["close"].iloc[-1])
    out.update({
        "start_close": round(start_px, 2),
        "end_close": round(end_px, 2),
        "return_pct": round((end_px / start_px - 1) * 100, 3),
        "actual_direction": "up" if end_px >= start_px else "down",
        "resolved": True,
    })

    # NIFTY 50 over the same window, for excess-return scoring.
    try:
        bench = market_data.get_benchmark_history(
            start=(as_of_d.replace(year=as_of_d.year - 1)).isoformat(),
            end=target.isoformat(),
            as_of=target.isoformat(),
        )
        b_start = bench.loc[bench.index <= str(as_of_d)]
        b_end = bench.loc[bench.index <= str(target)]
        if not b_start.empty and not b_end.empty:
            bs = float(b_start["close"].iloc[-1])
            be = float(b_end["close"].iloc[-1])
            out["benchmark_return_pct"] = round((be / bs - 1) * 100, 3)
            out["excess_return_pct"] = round(out["return_pct"] - out["benchmark_return_pct"], 3)
            out["beat_benchmark"] = out["excess_return_pct"] > 0
    except Exception:
        pass

    return out
