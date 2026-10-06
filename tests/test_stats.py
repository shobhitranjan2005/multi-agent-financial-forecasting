"""Unit tests on SYNTHETIC data only -- these check the maths, not any result."""
import pytest
from backend.eval import stats, provenance


def _cases(vals_by_date):
    return {(f"T{i}", d): v for d, vs in vals_by_date.items() for i, v in enumerate(vs)}


def test_ci_brackets_mean_and_is_wider_than_naive_for_clustered_data():
    data = _cases({"d1": [1, 1, 1, 1], "d2": [0, 0, 0, 0], "d3": [1, 1, 1, 1], "d4": [0, 0, 0, 0]})
    r = stats.mean_ci(data, seed=1)
    assert r["mean"] == 0.5 and r["n_dates"] == 4
    assert r["ci_low"] < 0.5 < r["ci_high"]
    assert r["ci_high"] - r["ci_low"] > 0.4   # 16 cases but ~4 independent dates


def test_paired_diff_excludes_zero_only_for_a_consistent_gap():
    a = _cases({f"d{i}": [1, 1] for i in range(8)})
    b = _cases({f"d{i}": [0, 0] for i in range(8)})
    assert stats.paired_diff_ci(a, b, seed=2)["excludes_zero"]
    assert not stats.paired_diff_ci(a, a, seed=2)["excludes_zero"]


def test_mcnemar_exact_known_value():
    r = stats.mcnemar_exact([True] * 8 + [False] * 2, [False] * 8 + [True] * 2)
    assert (r["a_only"], r["b_only"]) == (8, 2)
    assert r["p_value"] == pytest.approx(0.109375)   # 2 * P(X<=2 | n=10, p=.5)


def test_single_date_is_rejected():
    with pytest.raises(ValueError):
        stats.mean_ci(_cases({"d1": [1, 0, 1]}))


def test_moving_alias_is_refused(monkeypatch):
    monkeypatch.setattr(provenance.Config, "GEMINI_MODEL", "gemini-flash-latest")
    monkeypatch.delenv("ALLOW_MODEL_ALIAS", raising=False)
    with pytest.raises(provenance.UnpinnedModelError):
        provenance.require_pinned_model()
