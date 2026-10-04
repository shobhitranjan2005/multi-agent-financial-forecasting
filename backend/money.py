"""Indian money formatting and magnitude parsing.

The trap this exists to prevent: Indian sources write amounts as "1,00,000"
(one lakh) and "1,00,00,000" (one crore), and copy reads "revenue of Rs 2,500
crore". A model asked for a number will happily return 2500 where 25_000_000_000
was meant. A 100x error is invisible until somebody reads the target price and
believes it.

Rule for the whole codebase: every monetary value crossing into a schema field is
in PLAIN INR UNITS. Convert here first.
"""
from __future__ import annotations

import math
import re
from typing import Optional

LAKH = 100_000
CRORE = 10_000_000

# Recognised multiplier words, longest first so "crore" wins before "cr".
_MULTIPLIERS: list[tuple[str, int]] = [
    ("thousand", 1_000),
    ("lakhs", LAKH),
    ("lacs", LAKH),
    ("lakh", LAKH),
    ("lac", LAKH),
    ("crores", CRORE),
    ("crore", CRORE),
    ("cr", CRORE),
    ("bn", 1_000_000_000),
    ("billion", 1_000_000_000),
    ("mn", 1_000_000),
    ("million", 1_000_000),
    ("k", 1_000),
]

_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def parse_indian_amount(text: str | float | int | None) -> Optional[float]:
    """Parse an Indian monetary string into plain INR units.

    >>> parse_indian_amount("Rs 2,500 crore")
    25000000000.0
    >>> parse_indian_amount("1,00,000")        # lakh-grouped digits
    100000.0
    >>> parse_indian_amount("12.5 lakh")
    1250000.0
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)

    s = str(text).strip().lower()
    s = s.replace("₹", " ").replace("rs.", " ").replace("rs", " ").replace("inr", " ")

    m = _NUM.search(s)
    if not m:
        return None
    # Indian digit grouping is 2,2,3 rather than 3,3,3, but stripping commas
    # handles both -- the grouping never changes the value.
    try:
        value = float(m.group(0).replace(",", ""))
    except ValueError:
        return None

    tail = s[m.end():]
    for word, mult in _MULTIPLIERS:
        # \b so "cr" does not match inside "credit"
        if re.search(rf"\b{re.escape(word)}\b", tail):
            return value * mult
    return value


def format_inr(amount: float | int | None, *, decimals: int = 2) -> str:
    """Format in Indian digit grouping with the rupee sign.

    >>> format_inr(1234567.5)
    '₹12,34,567.50'
    """
    if amount is None or (isinstance(amount, float) and math.isnan(amount)):
        return "unavailable"
    neg = amount < 0
    amount = abs(float(amount))

    whole = int(amount)
    frac = amount - whole
    s = str(whole)

    # Last three digits, then groups of two -- the Indian convention.
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])

    out = f"₹{s}"
    if decimals:
        out += f"{frac:.{decimals}f}"[1:]
    return ("-" + out) if neg else out


def humanize_inr(amount: float | int | None) -> str:
    """Render large amounts the way Indian financial press does.

    >>> humanize_inr(25_000_000_000)
    '₹2,500.00 crore'
    """
    if amount is None or (isinstance(amount, float) and math.isnan(amount)):
        return "unavailable"
    a = abs(float(amount))
    if a >= CRORE:
        return f"{format_inr(amount / CRORE)} crore"
    if a >= LAKH:
        return f"{format_inr(amount / LAKH)} lakh"
    return format_inr(amount)


def magnitude_ratio(value: float, reference: float) -> float:
    """How many multiples apart two numbers are, order-insensitive.

    The reconciliation gate uses this to catch the lakh/crore parse failure:
    a ratio near 100, 10_000_000 or 1/100 is a magnitude error, not a difference
    of opinion.
    """
    if reference == 0 or value == 0:
        return float("inf")
    hi, lo = max(abs(value), abs(reference)), min(abs(value), abs(reference))
    return hi / lo
