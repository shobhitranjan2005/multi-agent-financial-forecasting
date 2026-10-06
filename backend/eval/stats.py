"""Inference for the headline comparison, clustered by as_of date.

Cases that share an as_of date share a market regime, so they are NOT independent.
Resampling individual cases would understate uncertainty. These routines resample
whole DATES (a block bootstrap), which is the honest unit of independence here.
Pure stdlib: no new dependencies.
"""
from __future__ import annotations

import random
from collections import defaultdict
from math import comb
from typing import Iterable, Mapping, Sequence

Key = tuple[str, str]  # (ticker, as_of)


def _by_date(values: Mapping[Key, float]) -> dict[str, list[float]]:
    d: dict[str, list[float]] = defaultdict(list)
    for (_, as_of), v in values.items():
        d[as_of].append(float(v))
    return d


def _boot(groups: Sequence[Sequence[float]], n: int, seed: int) -> list[float]:
    rng, k, out = random.Random(seed), len(groups), []
    for _ in range(n):
        picked = [groups[rng.randrange(k)] for _ in range(k)]
        flat = [x for g in picked for x in g]
        out.append(sum(flat) / len(flat))
    return out


def _ci(samples: list[float], alpha: float) -> tuple[float, float]:
    s = sorted(samples)
    return s[int((alpha / 2) * len(s))], s[min(len(s) - 1, int((1 - alpha / 2) * len(s)))]


def mean_ci(values: Mapping[Key, float], *, n: int = 10_000, seed: int = 0, alpha: float = 0.05) -> dict:
    """Mean of a per-case metric with a date-block bootstrap CI."""
    g = list(_by_date(values).values())
    if len(g) < 2:
        raise ValueError("need >= 2 distinct as_of dates for a clustered CI")
    flat = [x for grp in g for x in grp]
    lo, hi = _ci(_boot(g, n, seed), alpha)
    return {"mean": sum(flat) / len(flat), "ci_low": lo, "ci_high": hi,
            "n_cases": len(flat), "n_dates": len(g)}


def paired_diff_ci(a: Mapping[Key, float], b: Mapping[Key, float], *,
                   n: int = 10_000, seed: int = 0, alpha: float = 0.05) -> dict:
    """mean(a - b) over cases both systems scored, date-block bootstrap.

    If the interval contains 0, the data do not support a difference.
    """
    keys = sorted(set(a) & set(b))
    diff = {k: float(a[k]) - float(b[k]) for k in keys}
    r = mean_ci(diff, n=n, seed=seed, alpha=alpha)
    r["excludes_zero"] = r["ci_low"] > 0 or r["ci_high"] < 0
    return r


def mcnemar_exact(a_correct: Iterable[bool], b_correct: Iterable[bool]) -> dict:
    """Exact two-sided McNemar on paired correct/incorrect calls.

    Treats cases as independent, so it is OPTIMISTIC under date clustering. Report
    it beside paired_diff_ci, never instead of it.
    """
    a_only = b_only = 0
    for x, y in zip(a_correct, b_correct):
        a_only += bool(x) and not y
        b_only += bool(y) and not x
    m = a_only + b_only
    if m == 0:
        return {"a_only": 0, "b_only": 0, "p_value": 1.0}
    tail = sum(comb(m, i) for i in range(min(a_only, b_only) + 1)) / 2**m
    return {"a_only": a_only, "b_only": b_only, "p_value": min(1.0, 2 * tail)}
