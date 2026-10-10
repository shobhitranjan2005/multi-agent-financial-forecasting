from backend.tools import tickers


def _fake(monkeypatch):
    monkeypatch.setattr(tickers, "load_nse_names", lambda: {"ZOMATO": "ZOMATO LTD", "INFY": "INFOSYS LTD", "IRCTC": "INDIAN RAILWAY CATERING AND TOURISM CORPORATION LTD"})
    monkeypatch.setattr(tickers, "load_nse_symbols", lambda *a, **k: {"ZOMATO", "INFY", "IRCTC"})


def test_finds_any_listed_company_by_name_or_symbol(monkeypatch):
    _fake(monkeypatch)
    assert tickers.search_companies("zom")[0] == {"symbol": "ZOMATO", "name": "Zomato"}
    assert tickers.search_companies("railway")[0]["symbol"] == "IRCTC"
    assert tickers.search_companies("irctc")[0]["symbol"] == "IRCTC"


def test_curated_friendly_name_wins_and_nonsense_returns_nothing(monkeypatch):
    _fake(monkeypatch)
    assert tickers.search_companies("infosys")[0] == {"symbol": "INFY", "name": "Infosys"}
    assert tickers.search_companies("qqqqzz") == [] and tickers.search_companies("  ") == []
