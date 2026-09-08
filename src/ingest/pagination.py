"""Pagination arithmetic for the Offres d'emploi v2 search endpoint.

Limits measured against the live API on 2026-09-08, not taken from folklore:

* the window travels in the ``range`` **query parameter**; a ``Range`` header
  is silently ignored and the API answers with page one;
* a page of 200 is rejected with HTTP 400, so 150 is the maximum;
* a start index above 3000 is rejected with *"La position de début doit être
  inférieure ou égale à 3000"*.

A single search therefore yields **3150 offers at most**, however many the
``Content-Range`` header advertises. Reaching further means splitting the
search into narrower creation-date windows, which is what :func:`split_window`
does. (Older wrappers document a ceiling of 1150; that limit is obsolete —
``range=3000-3149`` returns offers today.)
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

#: Largest number of offers the API will put in a single page.
MAX_PAGE_SIZE = 150
#: Largest accepted value for the first index of a range window.
MAX_RANGE_START = 3000
#: Largest reachable last index, implied by the two limits above.
MAX_RANGE_END = MAX_RANGE_START + MAX_PAGE_SIZE - 1
#: Ceiling of offers reachable by paginating one search.
MAX_OFFERS_PER_SEARCH = MAX_RANGE_END + 1

#: Narrowest window we bother splitting into; below this, splitting is futile.
MIN_WINDOW = timedelta(hours=12)
#: Guard against unbounded recursion when a window stays saturated.
MAX_SPLIT_DEPTH = 12

API_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

_CONTENT_RANGE = re.compile(
    r"offres\s+(?P<first>\d+)\s*-\s*(?P<last>\d+)\s*/\s*(?P<total>\d+)", re.IGNORECASE
)


def parse_content_range(value: str | None) -> tuple[int | None, int | None, int | None]:
    """Parse ``Content-Range: offres 0-149/287543`` into ``(first, last, total)``.

    Returns a triple of ``None`` when the header is missing or unparseable, as
    happens on an empty result set.
    """
    if not value:
        return (None, None, None)
    match = _CONTENT_RANGE.search(value)
    if not match:
        return (None, None, None)
    return (
        int(match.group("first")),
        int(match.group("last")),
        int(match.group("total")),
    )


def format_api_datetime(moment: datetime) -> str:
    """Render a datetime the way the API expects it (UTC, ``...T...Z``)."""
    return moment.astimezone(timezone.utc).strftime(API_DATETIME_FORMAT)


def parse_api_datetime(value: str) -> datetime:
    """Parse an API-formatted datetime string back into an aware datetime."""
    return datetime.strptime(value, API_DATETIME_FORMAT).replace(tzinfo=timezone.utc)


def default_window(lookback_days: int, now: datetime | None = None) -> tuple[str, str]:
    """Return the ``(minCreationDate, maxCreationDate)`` pair covering the lookback."""
    end = now or datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    return (format_api_datetime(start), format_api_datetime(end))


def split_window(min_date: str, max_date: str) -> tuple[tuple[str, str], tuple[str, str]] | None:
    """Halve a creation-date window, or return ``None`` if it is already too narrow.

    The two halves do not overlap on the wire, but callers should still
    de-duplicate offers: an offer created exactly on the boundary can be
    returned by both requests.
    """
    start = parse_api_datetime(min_date)
    end = parse_api_datetime(max_date)
    if end - start <= MIN_WINDOW:
        return None
    midpoint = start + (end - start) / 2
    middle = format_api_datetime(midpoint)
    return ((min_date, middle), (middle, max_date))


def page_bounds(start: int, page_size: int) -> tuple[int, int]:
    """Return the inclusive ``(start, end)`` Range window, clamped to API limits."""
    size = min(page_size, MAX_PAGE_SIZE)
    return (start, min(start + size - 1, MAX_RANGE_END))
