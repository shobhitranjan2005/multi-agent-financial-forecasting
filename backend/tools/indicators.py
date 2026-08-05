"""Technical indicators. Returns numeric values + plain-English readings.

All functions accept a price DataFrame with columns: open, high, low, close, volume.
Short-series safety: returns None with a note, never a wrong number.
"""
from __future__ import annotations

import pandas as pd

try:
    import pandas_ta_classic as ta
except ImportError:
    ta = None  # type: ignore


def _safe(fn, df: pd.DataFrame, min_rows: int, **kwargs):
    if ta is None:
        return None
    if len(df) < min_rows:
        return None
    try:
        out = fn(**kwargs)
        if out is None:
            return None
        if isinstance(out, pd.DataFrame):
            return out.iloc[-1].to_dict()
        return float(out.iloc[-1]) if hasattr(out, "iloc") else float(out)
    except Exception:
        return None


def rsi(df: pd.DataFrame, period: int = 14) -> dict | None:
    val = _safe(lambda: ta.rsi(df["close"], length=period), df, period + 1)
    if val is None:
        return None
    reading = "Overbought" if val > 70 else "Oversold" if val < 30 else "Neutral"
    return {"value": round(val, 2), "reading": reading, "period": period}


def macd(df: pd.DataFrame) -> dict | None:
    if ta is None or len(df) < 26:
        return None
    try:
        m = ta.macd(df["close"], fast=12, slow=26, signal=9)
        if m is None or m.empty:
            return None
        last = m.iloc[-1]
        macd_line = float(last.iloc[0])
        hist = float(last.iloc[2])
        bias = "Bullish" if hist > 0 else "Bearish"
        return {
            "macd": round(macd_line, 4),
            "signal": round(float(last.iloc[1]), 4),
            "histogram": round(hist, 4),
            "bias": bias,
        }
    except Exception:
        return None


def sma(df: pd.DataFrame, period: int) -> dict | None:
    if ta is None or len(df) < period:
        return None
    try:
        s = ta.sma(df["close"], length=period)
        if s is None or s.empty:
            return None
        v = float(s.iloc[-1])
        last_close = float(df["close"].iloc[-1])
        position = "above" if last_close > v else "below"
        return {"value": round(v, 2), "period": period, "price_position": position}
    except Exception:
        return None


def bollinger(df: pd.DataFrame, period: int = 20) -> dict | None:
    if ta is None or len(df) < period:
        return None
    try:
        b = ta.bbands(df["close"], length=period)
        if b is None or b.empty:
            return None
        last = b.iloc[-1]
        return {
            "upper": round(float(last.iloc[0]), 2),
            "middle": round(float(last.iloc[1]), 2),
            "lower": round(float(last.iloc[2]), 2),
        }
    except Exception:
        return None


def atr(df: pd.DataFrame, period: int = 14) -> dict | None:
    if ta is None or len(df) < period:
        return None
    try:
        a = ta.atr(df["high"], df["low"], df["close"], length=period)
        if a is None or a.empty:
            return None
        return {"value": round(float(a.iloc[-1]), 4), "period": period}
    except Exception:
        return None


def realised_volatility(df: pd.DataFrame, window: int = 21) -> dict | None:
    """Annualised realised vol from log returns. window in trading days."""
    if len(df) < window + 1:
        return None
    try:
        rets = (df["close"] / df["close"].shift(1)).dropna().tail(window)
        log_rets = (rets.apply(lambda x: 0 if x <= 0 else __import__("math").log(x))).dropna()
        vol = float(log_rets.std(ddof=0) * (252 ** 0.5))
        return {"annualised_vol": round(vol, 4), "window_days": window}
    except Exception:
        return None


def price_band_check(last_close: float, target: float, band_pct: float = 20.0) -> dict:
    """NSE price-band sanity check on a single-session move.

    NSE caps most scrips at +/-20% a day, and 10%/5%/2% for many mid- and
    small-caps (5% under F&O ban / surveillance). A one-session target outside
    the applicable band is arithmetically impossible, not merely optimistic —
    so flag it before it reaches a report.
    """
    if last_close <= 0:
        return {"within_band": None, "note": "invalid last close"}
    move_pct = (target - last_close) / last_close * 100.0
    within = abs(move_pct) <= band_pct
    return {
        "within_band": within,
        "implied_move_pct": round(move_pct, 2),
        "band_pct": band_pct,
        "note": None if within else (
            f"target implies {move_pct:+.1f}% in one session; NSE band is +/-{band_pct:.0f}%"
        ),
    }


def compute_all(df: pd.DataFrame) -> dict:
    """One-shot computation for the Technical agent."""
    return {
        "rsi_14": rsi(df),
        "macd": macd(df),
        "sma_50": sma(df, 50),
        "sma_200": sma(df, 200),
        "bollinger_20": bollinger(df, 20),
        "atr_14": atr(df, 14),
        "realised_vol_21": realised_volatility(df, 21),
    }
