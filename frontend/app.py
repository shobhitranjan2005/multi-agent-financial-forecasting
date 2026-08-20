"""Streamlit dashboard (Task 5.2).

    streamlit run frontend/app.py

Five panels, in the order a demo should walk through them:

    1. Evidence pack      what the system is allowed to know at as_of
    2. Price chart        candlesticks, capped at as_of, with SMA overlays
    3. Live agent log     each stage as it completes
    4. Bull vs Bear       the debate, side by side
    5. Forecast card      signal, target, confidence, citations, reconciliation

It calls the pipeline in-process rather than through the FastAPI server. That is
a deliberate simplification for a single-machine demo: one process to start, one
thing to fail. The API exists and is tested, and pointing this at it is a
one-function change -- but a defence is not the moment to discover that you
forgot to start the backend.

Money is formatted with Indian digit grouping throughout (Rs 12,34,567.50, not
Rs 1,234,567.50). It is a one-function detail and it is what makes the demo look
native rather than like a US dashboard with the currency symbol swapped.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import streamlit as st

# Streamlit runs this file as a script, so the project root is not on sys.path.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import llm                                    # noqa: E402
from backend.config import Config                          # noqa: E402
from backend.money import format_inr                       # noqa: E402
from backend.tools.tickers import UnsupportedMarketError    # noqa: E402

st.set_page_config(
    page_title="Multi-Agent Forecasting — NSE",
    page_icon="📈",
    layout="wide",
)

NAVY = "#1F3864"
GREEN = "#0F7B3E"
RED = "#B3261E"
AMBER = "#B26B00"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_symbols() -> list[str]:
    """NSE symbol master for the search box, from the cached bhavcopy extract."""
    import json

    path = Config.DATA_DIR / "nse_symbols.json"
    if path.exists():
        return sorted(json.loads(path.read_text(encoding="utf-8")))
    return ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]


@st.cache_data(show_spinner=False)
def build_evidence(ticker: str, as_of: str, extras: bool):
    """Cached evidence pack. Streamlit reruns the whole script on every widget
    change, so without this the data layer would be hit on every keystroke."""
    from backend.context import build as build_context

    ctx = build_context(ticker, as_of, with_fundamentals=extras,
                        with_news=extras, with_macro=extras)
    return {
        "ticker": ctx.ticker,
        "as_of": str(ctx.as_of),
        "last_close": ctx.last_close,
        "sessions": len(ctx.prices),
        "source": ctx.source,
        "target_date": str(ctx.target_date) if ctx.target_date else None,
        "indicators": ctx.indicators,
        "benchmark": ctx.benchmark,
        "fundamentals": ctx.fundamentals,
        "news": ctx.news,
        "macro": ctx.macro,
        "notes": ctx.notes,
        "prices": ctx.prices.reset_index().to_dict("records"),
    }


def price_chart(rows: list[dict], ticker: str, indicators: dict):
    """Candlesticks with SMA overlays.

    Candlesticks specifically: a line chart of closes throws away the intraday
    range, which is most of what a technical analyst reads. Plotly is used
    because it has a native candlestick trace -- several popular charting
    libraries do not, and drawing one by hand out of rectangles is a waste of an
    afternoon.
    """
    import pandas as pd
    import plotly.graph_objects as go

    df = pd.DataFrame(rows)
    if df.empty:
        return None
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.tail(180)

    fig = go.Figure(
        go.Candlestick(
            x=df[date_col], open=df["open"], high=df["high"],
            low=df["low"], close=df["close"], name=ticker,
            increasing_line_color=GREEN, decreasing_line_color=RED,
        )
    )
    for period, colour in ((50, "#2E5C8A"), (200, "#B26B00")):
        key = f"sma_{period}"
        if indicators.get(key):
            fig.add_hline(
                y=indicators[key]["value"], line_dash="dot", line_color=colour,
                annotation_text=f"SMA-{period} {format_inr(indicators[key]['value'])}",
                annotation_position="right",
            )
    fig.update_layout(
        height=420, margin=dict(l=10, r=10, t=30, b=10),
        xaxis_rangeslider_visible=False,
        yaxis_title="INR", template="plotly_white",
        title=f"{ticker} — last 180 sessions to {df[date_col].iloc[-1]:%Y-%m-%d}",
    )
    return fig


def signal_colour(signal: str) -> str:
    return {"Buy": GREEN, "Sell": RED}.get(signal, AMBER)


# ---------------------------------------------------------------------------
# sidebar
# ---------------------------------------------------------------------------
st.sidebar.title("Forecast setup")

symbols = load_symbols()
default_index = symbols.index("RELIANCE") if "RELIANCE" in symbols else 0
symbol = st.sidebar.selectbox("NSE symbol", symbols, index=default_index,
                              help="Indian equities only — NSE primary, BSE secondary")
ticker = f"{symbol}.NS"

as_of = st.sidebar.date_input(
    "As-of date (the cutoff)",
    value=date(2025, 6, 2),
    min_value=date(2015, 1, 1),
    max_value=date.today(),
    help="The system cannot see any data after this date. Enforced in the data "
         "layer, not by prompting.",
)

st.sidebar.markdown("---")
st.sidebar.subheader("System")
run_debate = st.sidebar.toggle("Bull vs Bear debate", value=True,
                               help="Off = the --no-debate ablation")
dropped = st.sidebar.multiselect(
    "Drop specialists (ablation)",
    ["technical", "fundamental", "sentiment", "macro"],
    help="Leave-one-out: removes the analyst AND its evidence",
)
horizon = st.sidebar.number_input("Horizon (NSE sessions)", 1, 60,
                                  Config.HORIZON_SESSIONS)

st.sidebar.markdown("---")
if llm.is_configured():
    st.sidebar.success(f"Gemini configured — {Config.GEMINI_MODEL}")
else:
    st.sidebar.warning(
        "GEMINI_API_KEY not set. The evidence pack, the chart and the leakage "
        "controls all work; the agent stages need a key."
    )

run_clicked = st.sidebar.button("Run forecast", type="primary",
                                use_container_width=True,
                                disabled=not llm.is_configured())

# ---------------------------------------------------------------------------
# header
# ---------------------------------------------------------------------------
st.title("Financial Forecasting by a Multi-Agent AI System")
st.caption(
    f"NSE/BSE equities · INR · Asia/Kolkata · benchmark {Config.BENCHMARK} (NIFTY 50) · "
    f"horizon {horizon} trading sessions · leakage-free `as_of` protocol"
)

# ---------------------------------------------------------------------------
# 1 + 2. evidence and chart
# ---------------------------------------------------------------------------
try:
    with st.spinner(f"Building the evidence pack for {ticker} as of {as_of}…"):
        pack = build_evidence(ticker, as_of.isoformat(), bool(llm.is_configured()))
except UnsupportedMarketError as exc:
    st.error(f"Rejected at the boundary: {exc}")
    st.stop()
except Exception as exc:
    st.error(f"Could not build the evidence pack: {type(exc).__name__}: {exc}")
    st.stop()

cols = st.columns([1, 1, 1, 1, 1])
cols[0].metric("Last close", format_inr(pack["last_close"]))
rsi = pack["indicators"].get("rsi_14")
cols[1].metric("RSI (14)", f"{rsi['value']}" if rsi else "—",
               rsi["reading"] if rsi else None)
macd = pack["indicators"].get("macd")
cols[2].metric("MACD bias", macd["bias"] if macd else "—")
cols[3].metric("Sessions loaded", pack["sessions"])
cols[4].metric("NIFTY 50 (21d)",
               f"{pack['benchmark'].get('return_21d_pct', '—')}%"
               if pack["benchmark"] else "—")

if pack["notes"]:
    with st.expander(f"Data notes ({len(pack['notes'])})"):
        for note in pack["notes"]:
            st.write(f"• {note}")

chart = price_chart(pack["prices"], pack["ticker"], pack["indicators"])
if chart is not None:
    st.plotly_chart(chart, use_container_width=True)

with st.expander("Evidence pack — exactly what the agents may see"):
    ev1, ev2 = st.columns(2)
    with ev1:
        st.markdown("**Technical indicators**")
        st.json(pack["indicators"], expanded=False)
        st.markdown("**Fundamentals (point-in-time)**")
        f = pack["fundamentals"]
        if not f:
            st.caption("Not loaded for this run.")
        else:
            admissible = f.get("metrics") or {}
            if admissible:
                st.json(admissible, expanded=False)
            else:
                st.info(
                    "No point-in-time valuation metrics are admissible at this date. "
                    "yfinance serves *today's* P/E and market cap, which were not "
                    "knowable then, so they are withheld from the prompt. This is a "
                    "free-data coverage limit, reported rather than papered over."
                )
            if f.get("hidden_quarters"):
                st.caption("Withheld by the SEBI 45-day filing rule: "
                           + ", ".join(f["hidden_quarters"]))
    with ev2:
        st.markdown("**Indian-press headlines**")
        news = pack["news"] or {}
        heads = news.get("headlines", [])
        if not heads:
            st.caption("No qualifying coverage at or before the cutoff.")
        for h in heads[:8]:
            st.write(f"`{h.get('date')}` {h.get('title')}")
        st.markdown("**Macro**")
        macro = pack["macro"] or {}
        if macro.get("indicators"):
            st.json(macro["indicators"], expanded=False)
        else:
            st.caption("Not loaded for this run.")

# ---------------------------------------------------------------------------
# 3, 4, 5. the run
# ---------------------------------------------------------------------------
st.markdown("---")

if not run_clicked:
    st.info(
        "Set the ticker and cutoff date in the sidebar, then **Run forecast**. "
        "Everything above was produced without a single model call — the data "
        "layer, the NSE trading calendar and the leakage controls stand on their own."
    )
    st.stop()

from backend.graph.pipeline import stream as stream_pipeline   # noqa: E402

log_box = st.container()
log_box.subheader("Live agent log")
progress = log_box.progress(0.0)
log_lines: list[str] = []
log_area = log_box.empty()

total_stages = 7 if run_debate else 6
done_stages = 0
result: dict | None = None

try:
    for event in stream_pipeline(
        ticker, as_of.isoformat(),
        horizon_sessions=int(horizon),
        debate=run_debate,
        drop=tuple(dropped),
    ):
        kind = event.get("event")
        if kind == "stage":
            label = event.get("label", event.get("stage"))
            detail = event.get("detail", "")
            if event.get("status") == "done":
                done_stages += 1
                log_lines.append(
                    f"✓ {label} — {detail}  ({event.get('elapsed', 0)}s)"
                )
            else:
                log_lines.append(f"… {label}")
            progress.progress(min(done_stages / total_stages, 1.0))
            log_area.code("\n".join(log_lines), language=None)
        elif kind == "done":
            result = event
        elif kind == "error":
            st.error(event.get("detail", "unknown error"))
            st.stop()
except Exception as exc:
    st.error(f"Run failed: {type(exc).__name__}: {exc}")
    st.stop()

if result is None:
    st.error("The pipeline finished without producing a result.")
    st.stop()

progress.progress(1.0)
record = result["record"]
forecast = record.get("forecast")

# ---- 4. Bull vs Bear ----
turns = result.get("debate") or []
if turns:
    st.markdown("---")
    st.subheader("Bull vs Bear")
    bull_col, bear_col = st.columns(2)
    for turn in turns:
        target = bull_col if turn["position"] == "bull" else bear_col
        with target:
            st.markdown(
                f"**Round {turn['round_number']} — "
                f"{'🐂 Bull' if turn['position'] == 'bull' else '🐻 Bear'}** · "
                f"target {format_inr(turn.get('target_inr'))} · "
                f"confidence {turn.get('confidence', 0):.0%}"
            )
            if turn.get("rebuttal"):
                st.caption(f"Rebuttal: {turn['rebuttal']}")
            for point in turn.get("points", []):
                st.write(f"• {point}")
            st.markdown("")
elif run_debate:
    st.warning("The debate stage produced no parseable turns.")

# ---- 5. forecast card ----
st.markdown("---")
st.subheader("Final forecast")

if not forecast:
    st.error("The system did not produce a valid forecast.")
    for note in record.get("notes", []):
        st.write(f"• {note}")
    st.stop()

sig_col, tgt_col, conf_col, cost_col = st.columns([1, 1.4, 1, 1.2])
sig_col.markdown(
    f"<div style='font-size:2.2rem;font-weight:700;color:{signal_colour(forecast['signal'])}'>"
    f"{forecast['signal']}</div><div style='color:#6B7280'>direction: "
    f"{forecast['expected_direction']}</div>",
    unsafe_allow_html=True,
)
mid = (forecast["target_low_inr"] + forecast["target_high_inr"]) / 2
move = ((mid / record["last_close_inr"] - 1) * 100) if record.get("last_close_inr") else 0
tgt_col.metric(
    f"Target range ({horizon} sessions)",
    f"{format_inr(forecast['target_low_inr'])} – {format_inr(forecast['target_high_inr'])}",
    f"{move:+.1f}% vs last close",
)
conf_col.metric("Confidence", f"{forecast['confidence_pct']:.0f}%")
cost_col.metric(
    "Cost",
    f"{record['total_tokens']:,} tokens",
    f"{record['llm_calls']} calls · {record['seconds']}s",
)

st.markdown("**Reasoning**")
st.write(forecast["reasoning"])

risk_col, cite_col = st.columns(2)
with risk_col:
    st.markdown("**Risk report**")
    st.write(forecast["risk_report"])
    for risk in forecast.get("key_risks", []):
        st.write(f"• {risk}")
with cite_col:
    st.markdown("**Citations**")
    for citation in forecast.get("citations", []):
        st.write(f"• {citation}")

# ---- the reconciliation gate, shown deliberately ----
recon = result.get("reconciliation") or {}
if recon:
    st.markdown("---")
    st.subheader("Reconciliation gate")
    checked = recon.get("n_checked", 0)
    failed = recon.get("n_failed", 0)
    fc = recon.get("forecast_checks") or {}
    r1, r2, r3 = st.columns(3)
    r1.metric("Claims verified against source", checked)
    r2.metric("Failed", failed, delta_color="inverse")
    r3.metric("Magnitude errors (lakh/crore)", recon.get("n_magnitude_errors", 0),
              delta_color="inverse")

    failures = list(recon.get("failures", [])) + list(fc.get("failures", []))
    if failures:
        for fail in failures:
            st.warning(f"**{fail['status'].upper()}** · {fail['agent']}.{fail['field']} "
                       f"— {fail['note']}")
    else:
        st.success(
            "Every numeric claim the agents made was re-checked against the cached "
            "source data and agreed with it."
        )

with st.expander("Specialist reports"):
    for name, report in (result.get("reports") or {}).items():
        st.markdown(f"**{name.title()}**")
        if report is None:
            st.caption("no report (dropped, or evidence unavailable)")
        else:
            st.json(report, expanded=False)

with st.expander("Run record (what the harness scores)"):
    st.json(record, expanded=False)
