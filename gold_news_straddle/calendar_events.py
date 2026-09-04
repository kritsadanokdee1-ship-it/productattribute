"""US NFP release calendar (the event the EA in the clip trades).

NFP is published by the BLS at 08:30 America/New_York on the first Friday of
the month, which is 12:30 UTC during US daylight saving time and 13:30 UTC
outside it.  A handful of releases moved; every override below was confirmed
against the price data itself (a >10 USD one-minute range on the XAUUSD bar
stamped at the release minute, and no such bar on the rule-based date).
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc

# rule-based first Friday -> actual release date
OVERRIDES: dict[dt.date, dt.date | None] = {
    # July 4th observed on the first Friday -> BLS releases the Thursday before
    dt.date(2020, 7, 3): dt.date(2020, 7, 2),
    dt.date(2025, 7, 4): dt.date(2025, 7, 3),
    dt.date(2026, 7, 3): dt.date(2026, 7, 2),
    # New Year's Day on the first Friday -> released the following Friday
    dt.date(2021, 1, 1): dt.date(2021, 1, 8),
    # 2025 US government shutdown: BLS suspended, then caught up out of schedule
    dt.date(2025, 10, 3): None,             # never published as a standalone report
    dt.date(2025, 11, 7): dt.date(2025, 11, 20),
    dt.date(2025, 12, 5): dt.date(2025, 12, 18),
    dt.date(2026, 1, 2): dt.date(2026, 1, 9),
}


def first_fridays(start: dt.date, end: dt.date) -> list[dt.date]:
    out = []
    y, m = start.year, start.month
    while dt.date(y, m, 1) <= end:
        d = dt.date(y, m, 1)
        while d.weekday() != 4:
            d += dt.timedelta(days=1)
        if start <= d <= end:
            out.append(d)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def release_datetimes(start: dt.date, end: dt.date) -> list[dt.datetime]:
    """UTC timestamps of the 08:30 New York NFP releases in [start, end]."""
    stamps = []
    for d in first_fridays(start, end):
        actual = OVERRIDES.get(d, d)
        if actual is None:
            continue
        local = dt.datetime(actual.year, actual.month, actual.day, 8, 30, tzinfo=NY)
        stamps.append(local.astimezone(UTC))
    return stamps


if __name__ == "__main__":
    for t in release_datetimes(dt.date(2017, 5, 1), dt.date(2026, 8, 31)):
        print(t.isoformat())
