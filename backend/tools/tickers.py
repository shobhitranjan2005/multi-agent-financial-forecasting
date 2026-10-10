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
    if "FinInstrmNm" in eq.columns:   # keep company names for the search box (best effort)
        try:
            names = {str(r.TckrSymb).upper(): str(r.FinInstrmNm) for r in eq.itertuples()}
            Config.ensure_dirs()
            (Config.DATA_DIR / "nse_names.json").write_text(json.dumps(names), encoding="utf-8")
        except Exception:
            pass
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
def _listed_on(as_of: date) -> set[str]:
    """NSE equity symbols that actually traded on `as_of`, from that day's bhavcopy."""
    from backend.tools import market_data

    return {s.split(".")[0].upper() for s in market_data.get_traded_universe(as_of)}


def resolve(symbol: str, verify: bool = True, as_of: date | None = None) -> str:
    """Normalise to a Yahoo NSE/BSE ticker, or raise UnsupportedMarketError.

    verify=True checks NSE membership. Pass False only for offline/unit-test paths
    where a network fetch is unwanted; the syntax check alone cannot tell RELIANCE
    from AAPL.

    `as_of` matters more than it looks. Without it, membership is checked against
    TODAY's symbol master — which is survivorship bias inside the boundary itself.
    TATAMOTORS traded every session up to its 2025 demerger and is absent from a
    current bhavcopy, so a backtest dated mid-2025 would reject a ticker that was
    perfectly valid on the day being tested, and would quietly drop exactly the
    names whose fate the evaluation should include.

    So when a caller knows the date it is reasoning about, it passes `as_of` and
    membership is checked against that day's bhavcopy instead.
    """
    if not symbol or not symbol.strip():
        raise UnsupportedMarketError(f"Empty ticker. {_ERROR}")

    raw = symbol.strip().upper()
    inferred_suffix = False

    if "." in raw:
        base, _, suffix = raw.rpartition(".")
        suffix = f".{suffix}"
        if suffix not in Config.ALLOWED_SUFFIXES:
            hint = " That market is out of scope." if suffix in _KNOWN_FOREIGN_SUFFIXES else ""
            raise UnsupportedMarketError(f"Unsupported exchange suffix '{suffix}'.{hint} {_ERROR}")
    else:
        base, suffix = raw, Config.DEFAULT_SUFFIX
        inferred_suffix = True

    if not _SYMBOL_RE.match(base):
        raise UnsupportedMarketError(f"'{symbol}' is not a valid NSE/BSE symbol. {_ERROR}")

    # Membership check applies to NSE only — BSE scrip codes are not in the
    # NSE bhavcopy, and there is no free BSE master in scope.
    if verify and suffix == ".NS":
        listed: set = set()
        if as_of is not None:
            try:
                listed = _listed_on(as_of)
            except Exception:
                listed = set()  # archive unavailable — fall through to the master
            if listed:
                if base in listed:
                    return f"{base}{suffix}"
                raise UnsupportedMarketError(
                    f"'{base}' did not trade on NSE on {as_of}. {_ERROR}"
                )

        master = load_nse_symbols()
        if master:
            if base not in master:
                raise UnsupportedMarketError(
                    f"'{base}' is not listed on NSE. {_ERROR}"
                )
        elif inferred_suffix:
            # FAIL CLOSED: with no membership source available, a bare symbol
            # ("AAPL") must not be silently promoted to "AAPL.NS". Write the
            # suffix explicitly (RELIANCE.NS) to assert it is an NSE ticker.
            raise UnsupportedMarketError(
                f"Cannot verify '{base}' as an NSE symbol (symbol master unavailable). "
                f"Write it with its suffix, e.g. '{base}.NS'. {_ERROR}"
            )

    return f"{base}{suffix}"


def is_indian(symbol: str, verify: bool = True, as_of: date | None = None) -> bool:
    """True if `symbol` resolves to an NSE/BSE ticker. Never raises."""
    try:
        resolve(symbol, verify=verify, as_of=as_of)
    except UnsupportedMarketError:
        return False
    return True


def base_symbol(ticker: str) -> str:
    """'RELIANCE.NS' -> 'RELIANCE'. Used to match against NSE bhavcopy TckrSymb."""
    return resolve(ticker, verify=False).rsplit(".", 1)[0]


def exchange(ticker: str) -> str:
    """'NSE' or 'BSE'."""
    return "NSE" if resolve(ticker, verify=False).endswith(".NS") else "BSE"


# --------------------------------------------------------------------------
# Company search (powers the UI search box)
# --------------------------------------------------------------------------
import re as _re

_LEGAL = _re.compile(r"\s+(limited|ltd\.?)\s*$", _re.I)


def load_nse_names() -> dict[str, str]:
    """symbol -> company name from the NSE bhavcopy. {} if it cannot be obtained."""
    path = Config.DATA_DIR / "nse_names.json"
    if not path.exists():
        try:
            _build_symbol_master()      # writes nse_names.json as a side effect
        except Exception:
            return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _friendly(sym: str, raw: str) -> str:
    from backend.tools.news_sentiment import NEWS_ALIASES   # lazy: avoids an import cycle
    if sym in NEWS_ALIASES:
        return NEWS_ALIASES[sym][0]
    return _LEGAL.sub("", raw.title()) if raw else sym


def search_companies(q: str, limit: int = 8) -> list[dict]:
    """Match a typed company name or symbol against every listed NSE equity."""
    from backend.tools.news_sentiment import NEWS_ALIASES
    q = q.strip().lower()
    if not q:
        return []
    names = load_nse_names()
    syms = set(names) | set(load_nse_symbols()) | set(NEWS_ALIASES)
    ranked = []
    for sym in syms:
        raw = names.get(sym, "")
        nm = _friendly(sym, raw)
        sl, nl = sym.lower(), nm.lower()
        if sl == q:
            rank = 0
        elif nl.startswith(q):
            rank = 1
        elif sl.startswith(q):
            rank = 2
        elif q in nl or q in raw.lower():
            rank = 3
        else:
            continue
        ranked.append((rank, len(sym), sym, nm))
    ranked.sort()
    return [{"symbol": s_, "name": n_} for _, _, s_, n_ in ranked[:limit]]
