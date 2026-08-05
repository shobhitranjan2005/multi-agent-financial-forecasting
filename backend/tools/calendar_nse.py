"""NSE trading calendar, derived from bhavcopy availability.

A bhavcopy file exists for a date <=> NSE held a cash-market session that day.
That makes the archive itself the calendar oracle: no hardcoded holiday list to
go stale, no extra API, and it is self-verifying.

Verified 2026-08-06 (HEAD requests, browser UA required):
    2025-01-15 (Wed, normal session)  -> 200
    2025-03-14 (Holi, NSE holiday)    -> 404
    2025-01-18 (Saturday)             -> 404
    2025-10-21 (Diwali Muhurat, Tue)  -> 200

Why this module exists: NSE has ~15 holidays a year and they do not match NYSE.
An `as_of` that lands on a holiday, or a horizon measured in calendar days rather
than sessions, silently corrupts every score in Phase 4.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.config import Config

# Local, permanent record of probed dates: {"2025-01-15": true, ...}
_calendar: dict[str, bool] | None = None


def _load() -> dict[str, bool]:
    global _calendar
    if _calendar is None:
        path = Config.NSE_CALENDAR_FILE
        if path.exists():
            _calendar = json.loads(path.read_text(encoding="utf-8"))
        else:
            _calendar = {}
    return _calendar


def _save() -> None:
    Config.ensure_dirs()
    Config.NSE_CALENDAR_FILE.write_text(
        json.dumps(dict(sorted(_load().items())), indent=0), encoding="utf-8"
    )


def _as_date(d: str | date | datetime) -> date:
    if isinstance(d, str):
        return datetime.fromisoformat(d).date()
    if isinstance(d, datetime):
        return d.date()
    return d


@retry(wait=wait_exponential(multiplier=1, min=2, max=20), stop=stop_after_attempt(3), reraise=True)
def _probe(d: date) -> bool:
    """HEAD the bhavcopy for `d`. 200 = trading day, 404 = holiday/weekend."""
    url = Config.NSE_BHAVCOPY_URL.format(yyyymmdd=d.strftime("%Y%m%d"))
    r = httpx.head(url, headers={"User-Agent": Config.BROWSER_UA}, timeout=30.0,
                   follow_redirects=True)
    if r.status_code == 200:
        return True
    if r.status_code == 404:
        return False
    r.raise_for_status()
    return False


def is_trading_day(d: str | date | datetime, probe_weekends: bool = False) -> bool:
    """True if NSE held a cash session on `d`. Result is cached permanently.

    Weekends are assumed closed without a network call. Set probe_weekends=True
    to catch the rare special session (e.g. a Saturday Muhurat or a budget-day
    session) — NSE does occasionally trade on a weekend.
    """
    dt = _as_date(d)
    key = dt.isoformat()
    cal = _load()

    if key in cal:
        return cal[key]

    if dt.weekday() >= 5 and not probe_weekends:
        return False

    result = _probe(dt)
    cal[key] = result
    _save()
    return result


def previous_trading_day(d: str | date | datetime, inclusive: bool = True) -> date:
    """Snap `d` backwards onto a real NSE session.

    Every as_of must pass through this. A forecast dated on a holiday is not a
    forecast — it is an off-by-one bug waiting to be scored.
    """
    dt = _as_date(d)
    if not inclusive:
        dt -= timedelta(days=1)
    for _ in range(15):                      # longest NSE closure is well under 15 days
        if is_trading_day(dt):
            return dt
        dt -= timedelta(days=1)
    raise RuntimeError(f"No NSE trading day found within 15 days before {d}")


def next_trading_day(d: str | date | datetime, inclusive: bool = False) -> date:
    dt = _as_date(d)
    if not inclusive:
        dt += timedelta(days=1)
    for _ in range(15):
        if is_trading_day(dt):
            return dt
        dt += timedelta(days=1)
    raise RuntimeError(f"No NSE trading day found within 15 days after {d}")


def add_trading_days(d: str | date | datetime, n: int) -> date:
    """Advance `n` NSE sessions from `d`. The forecast horizon uses this.

    Config.HORIZON_SESSIONS is 21 SESSIONS, not 21 calendar days — roughly a
    month of trading, but the difference is what keeps the scoring honest.
    """
    if n < 0:
        raise ValueError("n must be >= 0; use previous_trading_day to go backwards")
    dt = previous_trading_day(d)
    for _ in range(n):
        dt = next_trading_day(dt)
    return dt


def trading_days_between(start: str | date | datetime, end: str | date | datetime) -> int:
    """Count NSE sessions in (start, end] — the realised horizon length."""
    a, b = _as_date(start), _as_date(end)
    if b < a:
        raise ValueError("end is before start")
    count, cur = 0, a + timedelta(days=1)
    while cur <= b:
        if is_trading_day(cur):
            count += 1
        cur += timedelta(days=1)
    return count
