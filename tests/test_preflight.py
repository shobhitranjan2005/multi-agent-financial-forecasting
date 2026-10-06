"""Verdict logic on SYNTHETIC inputs (checks the rules, not any result)."""
from backend.eval import preflight as pf

PROBE = {"latest_recalled_date": "2025-08-01", "recommended_testset_start": "2025-08-31"}


def test_contamination_flagged_and_rebuild_allowed_before_llm_results():
    v = pf.verdict(PROBE, [], ["2025-06-02", "2025-09-12"], llm_results_exist=False)
    assert "CONTAMINATED: 1/2" in v[0] and "legitimate" in v[0]


def test_rebuild_after_llm_results_requires_disclosure():
    v = pf.verdict(PROBE, [], ["2025-06-02"], llm_results_exist=True)
    assert "disclosed" in v[0]


def test_vacuous_ablation_detected():
    audit = [{"news_items": 0, "fundamental_values": 5}] * 4
    v = pf.verdict({"latest_recalled_date": None}, audit, ["2026-01-05"], False)
    assert any("Sentiment" in x and "VACUOUS" in x for x in v)
    assert not any("Fundamental evidence" in x for x in v)


def test_non_null_counts_nested_leaves():
    assert pf.non_null({"a": 1, "b": [None, 2, {"c": ""}], "d": None}) == 2
