"""The forecasting CLI — Phase 1 walking skeleton and the Phase 3 full system.

    python -m forecast RELIANCE.NS --as-of 2025-01-15
    python -m forecast TCS.NS --as-of 2025-06-01 --system multiagent
    python -m forecast TCS.NS --as-of 2025-06-01 --system multiagent --no-debate
    python -m forecast AAPL   --as-of 2025-01-15            # rejected at the boundary

--system phase1        baseline + technical specialist (the Phase 1 exit gate)
--system baseline      the single-LLM baseline alone
--system multiagent    four specialists -> reconciliation -> debate -> risk officer

Run any of them twice: the second run is served from cache with zero network calls.
A non-Indian ticker is rejected here rather than silently fetched — the boundary
lives in backend/tools/tickers.py and this is one of its entry points.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from backend import llm
from backend.agents import technical
from backend.agents.schemas import FinalForecast, TechnicalReport
from backend.config import Config, enable_utf8_console
from backend.context import build as build_context
from backend.money import format_inr
from backend.tools.tickers import UnsupportedMarketError

RULE = "=" * 74


def _print_context(ctx) -> None:
    print(RULE)
    print(f"  {ctx.ticker}   as of {ctx.as_of}   "
          f"horizon {ctx.horizon_sessions} sessions -> {ctx.target_date}")
    print(RULE)
    print(f"  Last close      {format_inr(ctx.last_close)}   (source: {ctx.source})")
    print(f"  Sessions loaded {len(ctx.prices)}")
    rsi = ctx.indicators.get("rsi_14")
    macd = ctx.indicators.get("macd")
    s50, s200 = ctx.indicators.get("sma_50"), ctx.indicators.get("sma_200")
    if rsi:
        print(f"  RSI(14)         {rsi['value']} ({rsi['reading']})")
    if macd:
        print(f"  MACD            hist {macd['histogram']} ({macd['bias']})")
    if s50:
        print(f"  SMA-50          {format_inr(s50['value'])} (price {s50['price_position']})")
    if s200:
        print(f"  SMA-200         {format_inr(s200['value'])} (price {s200['price_position']})")
    if ctx.benchmark:
        print(f"  NIFTY 50        {ctx.benchmark.get('last_close')} "
              f"(21d {ctx.benchmark.get('return_21d_pct')}%)")
    if ctx.fundamentals:
        f = ctx.fundamentals
        mode = "point-in-time" if f.get("point_in_time") else "WITHHELD (not point-in-time)"
        print(f"  Fundamentals    {mode}; "
              f"{len(f.get('quarters_visible') or [])} SEBI-visible quarter(s)")
    if ctx.news:
        print(f"  News            {len(ctx.news.get('headlines', []))} unique headlines")
    if ctx.macro:
        print(f"  Macro           repo "
              f"{(ctx.macro.get('repo_rate') or {}).get('repo_rate_pct')}%")
    for n in ctx.notes:
        print(f"  note: {n}")
    print()


def _print_technical(rep: TechnicalReport | None, err: str | None) -> None:
    print(RULE)
    print("  TECHNICAL SPECIALIST")
    print(RULE)
    if rep is None:
        print(f"  FAILED: {err}")
        return
    print(f"  Score       {rep.score:+.1f} / 10      Trend: {rep.trend}")
    print(f"  Support     {format_inr(rep.support_inr)}")
    print(f"  Resistance  {format_inr(rep.resistance_inr)}")
    for label, val in (("RSI", rep.rsi_reading), ("MACD", rep.macd_reading),
                       ("SMA", rep.sma_reading)):
        if val:
            print(f"  {label:<11} {val}")
    print(f"\n  {rep.reasoning}\n")
    if rep.citations:
        print("  Citations:")
        for c in rep.citations:
            print(f"    - {c}")
    print()


def _print_specialists(state: dict) -> None:
    """Render all four specialist reports from a completed graph run."""
    _print_technical(state.get("technical_report"), None)

    f = state.get("fundamental_report")
    print(RULE)
    print("  FUNDAMENTAL SPECIALIST")
    print(RULE)
    if f is None:
        print("  no report (dropped, or no admissible fundamental evidence)\n")
    else:
        print(f"  Valuation   {f.valuation_score:+.1f} / 10      Health: {f.health}")
        print(f"  Fair value  {format_inr(f.intrinsic_value_inr)}")
        print(f"  P/E {f.pe_ratio}   Rev growth {f.revenue_growth_pct}   D/E {f.debt_to_equity}")
        if f.unavailable_fields:
            print(f"  Unavailable: {', '.join(f.unavailable_fields)}")
        print(f"\n  {f.reasoning}\n")

    s = state.get("sentiment_report")
    print(RULE)
    print("  SENTIMENT SPECIALIST")
    print(RULE)
    if s is None:
        print("  no report (dropped, or no qualifying coverage)\n")
    else:
        print(f"  Polarity    {s.polarity:+.2f}   Relevance {s.relevance:.2f}   "
              f"Confidence {s.confidence:.2f}")
        print(f"  Headlines   {s.headline_count}")
        for c in s.catalysts:
            print(f"    catalyst: {c}")
        print(f"\n  {s.reasoning}\n")

    m = state.get("macro_report")
    print(RULE)
    print("  MACRO SPECIALIST")
    print(RULE)
    if m is None:
        print("  no report (dropped, or macro data unavailable)\n")
    else:
        print(f"  Regime      {m.regime}")
        for label, val in (("USD/INR", m.usdinr_reading), ("Crude", m.crude_reading),
                           ("Rates", m.rates_reading), ("Sector", m.sector_reading)):
            if val:
                print(f"  {label:<11} {val}")
        print(f"\n  {m.reasoning}\n")


def _print_debate(state: dict) -> None:
    turns = state.get("debate") or []
    print(RULE)
    print(f"  BULL vs BEAR DEBATE  ({len(turns)} turns)")
    print(RULE)
    if not turns:
        print("  no debate (disabled with --no-debate, or every turn failed to parse)\n")
        return
    from backend.agents.debate import format_turn

    for t in turns:
        print(format_turn(t))
        print()


def _print_reconciliation(state: dict) -> None:
    recon = state.get("reconciliation") or {}
    if not recon:
        return
    print(RULE)
    print("  RECONCILIATION GATE")
    print(RULE)
    print(f"  {recon.get('n_checked', 0)} claims verified against source data, "
          f"{recon.get('n_failed', 0)} failed "
          f"({recon.get('n_magnitude_errors', 0)} magnitude), "
          f"{recon.get('n_unverifiable', 0)} unverifiable")
    for fail in recon.get("failures", []):
        print(f"    [{fail['status'].upper()}] {fail['agent']}.{fail['field']}: {fail['note']}")
    fc = recon.get("forecast_checks") or {}
    if fc:
        print(f"  Final forecast: {fc.get('n_checked', 0)} checks, "
              f"{fc.get('n_failed', 0)} failed")
        for fail in fc.get("failures", []):
            print(f"    [{fail['status'].upper()}] {fail['agent']}.{fail['field']}: "
                  f"{fail['note']}")
    print()


def _print_forecast(rec) -> None:
    print(RULE)
    print(f"  {rec.system.upper()} FORECAST")
    print(RULE)
    f: FinalForecast | None = rec.forecast
    if f is None:
        print("  FAILED to produce a valid forecast.")
        for n in rec.notes:
            print(f"    {n}")
        return
    move = ""
    if rec.last_close_inr:
        mid = (f.target_low_inr + f.target_high_inr) / 2
        move = f"   ({(mid / rec.last_close_inr - 1) * 100:+.1f}% vs last close)"
    print(f"  Signal      {f.signal}   direction: {f.expected_direction}")
    print(f"  Target      {format_inr(f.target_low_inr)} - {format_inr(f.target_high_inr)}{move}")
    print(f"  Confidence  {f.confidence_pct:.0f}%")
    print(f"\n  {f.reasoning}\n")
    if f.key_risks:
        print("  Key risks:")
        for r in f.key_risks:
            print(f"    - {r}")
    if f.citations:
        print("  Citations:")
        for c in f.citations:
            print(f"    - {c}")
    print()


def _print_cost() -> None:
    u = llm.session_usage()
    print(RULE)
    print(f"  Cost: {u.calls} calls ({u.cached_calls} cached), "
          f"{u.total_tokens:,} tokens, {u.seconds:.1f}s, "
          f"{u.parse_failures} parse failures")
    print(RULE)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="forecast",
        description="Forecast one NSE/BSE ticker as of a past date, leakage-free.",
    )
    ap.add_argument("ticker", help="NSE/BSE ticker, e.g. RELIANCE.NS or TCS")
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD cutoff date")
    ap.add_argument("--system", default="phase1",
                    choices=["phase1", "baseline", "multiagent"],
                    help="which forecaster to run (default: phase1)")
    ap.add_argument("--no-debate", action="store_true",
                    help="multiagent only: skip the Bull/Bear stage (the ablation)")
    ap.add_argument("--drop", default="",
                    help="multiagent only: comma-separated specialists to leave out, "
                         "e.g. --drop sentiment,macro")
    ap.add_argument("--horizon", type=int, default=Config.HORIZON_SESSIONS,
                    help="forecast horizon in TRADING SESSIONS")
    ap.add_argument("--nonce", default="", help="cache-buster for variance runs")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    ap.add_argument("--data-only", action="store_true",
                    help="build and print the evidence pack without calling Gemini")
    args = ap.parse_args(argv)
    enable_utf8_console()

    dropped = tuple(d.strip() for d in args.drop.split(",") if d.strip())
    # The multi-agent system needs the Phase 2 evidence; the Phase 1 skeleton is
    # deliberately price-only so it stays fast.
    wants_extras = args.system == "multiagent"

    try:
        ctx = build_context(
            args.ticker, args.as_of,
            horizon_sessions=args.horizon,
            with_fundamentals=wants_extras and "fundamental" not in dropped,
            with_news=wants_extras and "sentiment" not in dropped,
            with_macro=wants_extras and "macro" not in dropped,
        )
    except UnsupportedMarketError as exc:
        print(f"\n  REJECTED: {exc}\n", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"\n  ERROR building evidence: {type(exc).__name__}: {exc}\n", file=sys.stderr)
        return 1

    if not args.json:
        _print_context(ctx)

    if args.data_only:
        return 0

    if not llm.is_configured():
        print("  GEMINI_API_KEY is not set in .env — cannot run the LLM stages.\n"
              "  The evidence pack above was built without it; add the key and re-run.\n",
              file=sys.stderr)
        return 3

    # ---- multi-agent path (Phase 3) ----
    if args.system == "multiagent":
        from backend.graph.pipeline import run as run_pipeline

        rec, state = run_pipeline(
            ctx.ticker, ctx.as_of,
            horizon_sessions=args.horizon,
            debate=not args.no_debate,
            drop=dropped,
            nonce=args.nonce,
            ctx=ctx,
            return_state=True,
        )
        if args.json:
            print(json.dumps({
                "context": {"ticker": ctx.ticker, "as_of": str(ctx.as_of),
                            "last_close": ctx.last_close, "source": ctx.source},
                "reports": {
                    k: (v.model_dump() if v is not None else None)
                    for k, v in (("technical", state.get("technical_report")),
                                 ("fundamental", state.get("fundamental_report")),
                                 ("sentiment", state.get("sentiment_report")),
                                 ("macro", state.get("macro_report")))
                },
                "debate": [t.model_dump() for t in (state.get("debate") or [])],
                "reconciliation": state.get("reconciliation"),
                "record": rec.model_dump(),
            }, indent=2, default=str))
            return 0

        _print_specialists(state)
        _print_debate(state)
        _print_reconciliation(state)
        _print_forecast(rec)
        _print_cost()
        return 0

    # ---- baseline / Phase 1 skeleton ----
    from backend import baseline  # imported here so --data-only needs no key

    rep, err = (technical.analyse(ctx, nonce=args.nonce)
                if args.system == "phase1" else (None, None))
    rec = baseline.forecast(
        ctx.ticker, ctx.as_of, horizon_sessions=args.horizon,
        nonce=args.nonce, ctx=ctx,
    )

    if args.json:
        print(json.dumps({
            "context": {
                "ticker": ctx.ticker, "as_of": str(ctx.as_of),
                "last_close": ctx.last_close, "source": ctx.source,
            },
            "technical": rep.model_dump() if rep else {"error": err},
            "baseline": rec.model_dump(),
        }, indent=2, default=str))
        return 0

    if args.system == "phase1":
        _print_technical(rep, err)
    _print_forecast(rec)
    _print_cost()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
