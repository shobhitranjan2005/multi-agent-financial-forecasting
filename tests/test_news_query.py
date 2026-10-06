"""News query construction. Hermetic: no network."""
from backend.eval.testset import SEED_UNIVERSE
from backend.tools import tickers
from backend.tools.news_sentiment import NEWS_ALIASES, _company_query, _strip_legal


def test_legal_suffix_is_not_used_as_an_exact_phrase():
    assert _company_query("AXISBANK.NS", None) == '"Axis Bank" sourcecountry:india'
    assert _strip_legal("Bharti Airtel Limited") == "Bharti Airtel"
    assert _strip_legal("Foo Ltd.") == "Foo"


def test_multiple_aliases_are_ORed():
    q = _company_query("TCS.NS", None)
    assert q.startswith('("Tata Consultancy Services" OR TCS)')


def test_unknown_ticker_falls_back_to_cleaned_name_then_symbol():
    assert _company_query("NEWCO.NS", "New Co Limited") == '"New Co" sourcecountry:india'
    assert _company_query("NEWCO.NS", None) == "NEWCO sourcecountry:india"


def test_every_seed_stock_has_a_curated_alias():
    missing = [s for s in SEED_UNIVERSE if tickers.base_symbol(s) not in NEWS_ALIASES]
    assert not missing, missing
