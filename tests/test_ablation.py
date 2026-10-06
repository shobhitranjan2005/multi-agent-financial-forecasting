import pytest
from backend.eval.ablation import aggregate, _pair_stats
from backend.eval.metrics import Scored

def test_ablation_ci_synthetic():
    def _s(t, d, sys, p, a):
        return Scored(ticker=t, as_of=d, system=sys, predicted_direction=p, actual_direction=a,
                      confidence_pct=60.0, target_low=100.0, target_high=110.0, actual_close=105.0,
                      return_pct=5.0, benchmark_return_pct=2.0, excess_return_pct=3.0)

    s1 = _s("A.NS", "2024-01-01", "sysA", "up", "up")
    s2 = _s("B.NS", "2024-01-02", "sysA", "up", "down")
    s3 = _s("C.NS", "2024-01-03", "sysA", "up", "down")
    
    # 2 repeats for sysA
    scored_a_1 = [s1, s2, s3]
    scored_a_2 = [s1, s2, s3] # same results for simplicity
    
    agg = aggregate([{"system": "sysA"}, {"system": "sysA"}])
    assert "scored_map" not in agg # Without passing scored_by_run, should just do nothing
    
    # But wait, aggregate takes summaries but our new code replaced it.
    # Ah, I modified ablation.py so run_suite does _make_map directly and modifies agg.
    
    # Let's test the pair_stats directly
    from backend.eval.ablation import _make_map
    map_a = _make_map([scored_a_1, scored_a_2])
    assert len(map_a) == 6 # 3 cases * 2 repeats
    
    # For sysB, let's say it gets them all wrong
    s1b = _s("A.NS", "2024-01-01", "sysB", "up", "down")
    s2b = _s("B.NS", "2024-01-02", "sysB", "up", "up") # one right
    s3b = _s("C.NS", "2024-01-03", "sysB", "up", "up")
    scored_b = [s1b, s2b, s3b]
    map_b = _make_map([scored_b, scored_b])
    
    results = {
        "sysA": {"scored_map": map_a},
        "sysB": {"scored_map": map_b},
    }
    
    pair_str = _pair_stats("sysA", "sysB", results)
    assert "p=" in pair_str
    assert "optimistic" in pair_str
