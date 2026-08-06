"""The India-only boundary. Every entry point resolves its ticker here first.

Scope is enforced by code, not by convention:
    resolve("RELIANCE")    -> "RELIANCE.NS"      (bare symbols default to NSE)
    resolve("TCS.NS")      -> "TCS.NS"
    resolve("500325.BO")   -> "500325.BO"
    resolve("AAPL")        -> UnsupportedMarketError   (not NSE-listed)
    resolve("BP.L")        -> UnsupportedMarketError   (foreign suffix)

A regex alone cannot do this job: "AAPL" is a syntactically valid NSE symbol, so
a pattern check would happily hand back "AAPL.NS" and fetch nothing. Membership
is therefore checked against the real NSE symbol master, built from one day's
bhavcopy and cached in data/nse_symbols.json.

Keeping this here means no downstream module ever has to detect a market.
"""
from __future__ import annotations

import io
import json
import re
import warnings
import zipfile
from datetime import date, timedelta

from backend.config import Config

# Yahoo suffixes for markets this project deliberately does not cover.
_KNOWN_FOREIGN_SUFFIXES = (
    ".L", ".T", ".DE", ".HK", ".AX", ".PA", ".SW", ".TO", ".SS", ".SZ",
    ".KS", ".TW", ".SI", ".MI", ".AS", ".BR", ".MC", ".ST", ".OL", ".HE",
)

# NSE/BSE symbols: letters, digits, & and -. BSE also uses 6-digit scrip codes.
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9&\-]{0,19}$")

_ERROR = (
    "This system covers NSE/BSE-listed Indian equities only. "
    "Use a bare symbol (RELIANCE), an NSE symbol (RELIANCE.NS) or a BSE symbol (500325.BO)."
)

_nse_symbols: set[str] | None = None


class UnsupportedMarketError(ValueError):
    """Raised for any ticker that is not NSE- or BSE-listed."""


# --------------------------------------------------------------------------
# NSE symbol master
# --------------------------------------------------------------------------
def _build_symbol_master() -> set[str]:
    """Fetch one recent bhavcopy and extract every listed EQ symbol."""
    import httpx
    import pandas as pd

    from backend.tools import calendar_nse

    d = calendar_nse.previous_trading_day(date.today() - timedelta(days=1))
    url = Config.NSE_BHAVCOPY_URL.format(yyyymmdd=d.strftime("%Y%m%d"))
    r = httpx.get(url, headers={"User-Agent": Config.BROWSER_UA}, timeout=60.0,
                  follow_redirects=True)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        with z.open(z.namelist()[0]) as fh:
            df = pd.read_csv(fh)
    eq = df[(df["SctySrs"] == "EQ") & (df["FinInstrmTp"] == "STK")]
    return {str(s).upper() for s in eq["TckrSymb"].unique()}


def load_nse_symbols(refresh: bool = False) -> set[str]:
    """Listed NSE equity symbols. Cached to disk; empty set if unavailable."""
    global _nse_symbols
    if _nse_symbols is not None and not refresh:
        return _nse_symbols

    path = Config.DATA_DIR / "nse_symbols.json"
    if path.exists() and not refresh:
        _nse_symbols = set(json.loads(path.read_text(encoding="utf-8")))
        return _nse_symbols

    try:
        _nse_symbols = _build_symbol_master()
        Config.ensure_dirs()
        path.write_text(json.dumps(sorted(_nse_symbols)), encoding="utf-8")
    except Exception as e:  # offline / NSE down — degrade loudly, never silently
        warnings.warn(
            f"NSE symbol master unavailable ({e}); falling back to syntax-only "
            "ticker validation. A non-Indian bare symbol may slip through until "
            "the master can be built.",
            RuntimeWarning,
            stacklevel=2,
        )
        _nse_symbols = set()
    return _nse_symbols


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------
def resolve(symbol: str, verify: bool = True) -> str:
    """Normalise to a Yahoo NSE/BSE ticker, or raise UnsupportedMarketError.

    verify=True checks NSE membership against the symbol master. Pass False only
    for offline/unit-test paths where a network fetch is unwanted; the syntax
    check alone cannot tell RELIANCE from AAPL.
    """
    if not symbol or not symbol.strip():
        raise UnsupportedMarketError(f"Empty ticker. {_ERROR}")

    raw = symbol.strip().upper()

    # Pass through macro & benchmark index symbols cleanly
    if raw.startswith("^") or "=X" in raw or "=F" in raw or raw in ("DEXINUS", "INDIRLTLT01STM"):
        return raw

    if "." in raw:
        base, _, suffix = raw.rpartition(".")
        suffix = f".{suffix}"
        if suffix not in Config.ALLOWED_SUFFIXES:
            hint = " That market is out of scope." if suffix in _KNOWN_FOREIGN_SUFFIXES else ""
            raise UnsupportedMarketError(f"Unsupported exchange suffix '{suffix}'.{hint} {_ERROR}")
    else:
        base, suffix = raw, Config.DEFAULT_SUFFIX

    if not _SYMBOL_RE.match(base):
        raise UnsupportedMarketError(f"'{symbol}' is not a valid NSE/BSE symbol. {_ERROR}")

    # Membership check applies to NSE only — BSE scrip codes are not in the
    # NSE bhavcopy, and there is no free BSE master in scope.
    if verify and suffix == ".NS":
        master = load_nse_symbols()
        if master and base not in master:
            raise UnsupportedMarketError(
                f"'{base}' is not listed on NSE. {_ERROR}"
            )

    return f"{base}{suffix}"



def is_indian(symbol: str, verify: bool = True) -> bool:
    """True if `symbol` resolves to an NSE/BSE ticker. Never raises."""
    try:
        resolve(symbol, verify=verify)
    except UnsupportedMarketError:
        return False
    return True


def base_symbol(ticker: str) -> str:
    """'RELIANCE.NS' -> 'RELIANCE'. Used to match against NSE bhavcopy TckrSymb."""
    return resolve(ticker, verify=False).rsplit(".", 1)[0]


def exchange(ticker: str) -> str:
    """'NSE' or 'BSE'."""
    return "NSE" if resolve(ticker, verify=False).endswith(".NS") else "BSE"
