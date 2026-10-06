"""India-only boundary must not depend on network state."""
import pytest
from backend.tools import tickers


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(tickers, "load_nse_symbols", lambda *a, **k: set())
    monkeypatch.setattr(tickers, "_listed_on", lambda *a, **k: set())


def test_bare_foreign_symbol_rejected_when_master_unavailable(offline):
    with pytest.raises(tickers.UnsupportedMarketError):
        tickers.resolve("AAPL")


def test_explicit_suffix_still_accepted_offline(offline):
    assert tickers.resolve("RELIANCE.NS") == "RELIANCE.NS"


def test_foreign_suffix_always_rejected(offline):
    for s in ("BP.L", "AAPL.US", "7203.T", "SAP.DE"):
        with pytest.raises(tickers.UnsupportedMarketError):
            tickers.resolve(s)
