"""Date plausibility: no future-dated expenses, nothing implausibly old."""

import datetime as dt

MAX_AGE_DAYS = 365


def date_problem(value: dt.date | None, today: dt.date) -> str | None:
    if value is None:
        return None
    if value > today + dt.timedelta(days=1):
        return "date is in the future (day and month may be swapped)"
    if (today - value).days > MAX_AGE_DAYS:
        return f"date is more than {MAX_AGE_DAYS} days old"
    return None
