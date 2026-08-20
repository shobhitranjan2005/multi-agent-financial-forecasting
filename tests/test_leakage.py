"""Leakage protocol tests — the claims the whole project rests on.

If any of these fail, the evaluation is measuring memory rather than forecasting
and every number in the report is void. They are cheap, offline, and they are the
first thing to run after touching the data layer.
"""
from __future__ import annotations

import ast
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Modules that must never be able to see past `as_of`.
FORECAST_SIDE = [
    *sorted((ROOT / "backend" / "agents").glob("*.py")),
    *sorted((ROOT / "backend" / "tools").glob("*.py")),
    *sorted((ROOT / "backend" / "graph").glob("*.py")),
    ROOT / "backend" / "context.py",
    ROOT / "backend" / "baseline.py",
    ROOT / "backend" / "prompts.py",
]


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


@pytest.mark.parametrize("path", FORECAST_SIDE, ids=lambda p: p.name)
def test_forecast_side_never_imports_outcomes(path: Path):
    """The one module allowed to look past as_of must stay quarantined.

    backend/eval/outcomes.py reads prices AFTER the forecast date, which is
    legitimate for scoring and is lookahead bias anywhere else. This test is what
    outcomes.py's docstring promises exists.
    """
    imported = _imported_modules(path)
    offenders = {m for m in imported if "eval.outcomes" in m or m.endswith("outcomes")}
    assert not offenders, (
        f"{path.relative_to(ROOT)} imports {offenders}. Realised outcomes must never "
        f"be reachable from the forecasting side of the system."
    )


def test_price_history_is_capped_at_as_of(ctx):
    """No row in the evidence pack may post-date as_of."""
    assert not ctx.prices.empty
    last_row = ctx.prices.index[-1].date()
    assert last_row <= ctx.as_of, f"evidence contains {last_row}, after as_of {ctx.as_of}"


def test_sebi_filing_rule_hides_unfiled_quarters():
    """A quarter is invisible until 45 days after it ends (SEBI LODR Reg. 33)."""
    from backend.tools.fundamentals import filing_date, is_visible

    q_end = date(2024, 12, 31)
    assert filing_date(q_end) == q_end + timedelta(days=45)
    # 20 Jan 2025: Q3 numbers were not public yet.
    assert not is_visible(q_end, date(2025, 1, 20))
    # 20 Feb 2025: the filing window has elapsed.
    assert is_visible(q_end, date(2025, 2, 20))
    # Annual results get 60 days, not 45.
    assert not is_visible(q_end, q_end + timedelta(days=50), annual=True)


def test_macro_vintage_filter_uses_publication_date():
    """An observation is only visible once it was PUBLISHED, not once it occurred."""
    from backend.tools.macro import USABLE_SERIES

    # Every usable series carries a publication lag; a zero lag would mean we
    # believe a monthly figure is public on the last day of the month it measures.
    for series_id, (_label, lag) in USABLE_SERIES.items():
        assert lag > 0, f"{series_id} has no publication lag — vintage leakage"


def test_rss_is_not_reachable_from_the_backtest_path():
    """RSS carries no archive, so it must never be callable from get_news."""
    import inspect

    from backend.tools import news_sentiment

    src = inspect.getsource(news_sentiment.get_news)
    assert "get_live_rss" not in src and "feedparser" not in src, (
        "the archival news path must not touch the live RSS path — RSS has no "
        "usable archive and would inject present-day news into a past forecast"
    )


def test_every_system_prompt_states_the_cutoff():
    """Prompting is not a leakage control, but it must still state the cutoff."""
    from backend.prompts import system_prompt

    prompt = system_prompt("You are a test analyst.", "2025-06-02")
    assert "2025-06-02" in prompt
    assert "NSE" in prompt and "INR" in prompt
    assert "inadmissible" in prompt.lower()


def test_horizon_is_measured_in_sessions_not_calendar_days():
    from backend.config import Config

    assert Config.HORIZON_SESSIONS == 21
    # 21 sessions is about a calendar month; if anyone ever swaps in timedelta(21)
    # this constant is the thing they will have touched.
    assert isinstance(Config.HORIZON_SESSIONS, int)
