from types import SimpleNamespace as NS
from backend.graph.pipeline import _evidence_flags


def test_flags_read_dict_contexts_correctly():
    ctx = NS(news={"headlines": [{"title": "x"}]}, fundamentals={"a": {"b": 3}})
    assert _evidence_flags(ctx) == {"has_news": True, "has_fundamentals": True}


def test_flags_false_when_empty_or_none():
    assert _evidence_flags(NS(news={"headlines": []}, fundamentals={"a": None})) == {"has_news": False, "has_fundamentals": False}
    assert _evidence_flags(NS(news=None, fundamentals=None))["has_news"] is False
