"""Window-walking strategy for a single search against the offers endpoint.

Kept apart from the transport layer in :mod:`src.ingest.france_travail` because
the interesting logic here is not "how do I call the API" but "how do I get
around the 3150-offer ceiling of a single search". Fetching one page is
:mod:`src.ingest.page`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .page import Page, fetch_page
from .pagination import (
    MAX_OFFERS_PER_SEARCH,
    MAX_PAGE_SIZE,
    MAX_RANGE_START,
    MAX_SPLIT_DEPTH,
    default_window,
    page_bounds,
    split_window,
)

if TYPE_CHECKING:  # pragma: no cover - the import cycle only matters to type checkers
    from .france_travail import FranceTravailClient

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 365


@dataclass(frozen=True)
class SearchSettings:
    """Caller-controlled knobs for one search."""

    max_results: int | None = None
    page_size: int = MAX_PAGE_SIZE
    save_raw: bool = True
    lookback_days: int = DEFAULT_LOOKBACK_DAYS


@dataclass
class _Run:
    """State shared by every date window explored for one search."""

    client: FranceTravailClient
    settings: SearchSettings
    #: Offers seen so far, keyed by id so overlapping windows cannot duplicate.
    offers: dict[str, dict[str, Any]] = field(default_factory=dict)

    def keep(self, page: Page, params: dict[str, Any]) -> None:
        """Add a page's offers, ignoring ones already collected."""
        for offer in page.offers:
            key = str(offer.get("id") or f"{params.get('motsCles')}:{len(self.offers)}")
            self.offers.setdefault(key, offer)

    def is_full(self) -> bool:
        """True once the caller's ``max_results`` has been reached."""
        cap = self.settings.max_results
        return cap is not None and len(self.offers) >= cap

    def needs_narrowing(self, total: int | None) -> bool:
        """True when the search holds more offers than one window can ever return."""
        if not total or total <= MAX_OFFERS_PER_SEARCH:
            return False
        cap = self.settings.max_results
        return cap is None or cap > MAX_OFFERS_PER_SEARCH


def collect_search(
    client: FranceTravailClient, params: dict[str, Any], settings: SearchSettings
) -> list[dict[str, Any]]:
    """Collect every reachable offer for ``params``, de-duplicated by ``id``."""
    run = _Run(client, settings)
    _collect_window(run, params, depth=0)
    return list(run.offers.values())


def _collect_window(run: _Run, params: dict[str, Any], depth: int) -> None:
    """Paginate one creation-date window, splitting it when it is too large."""
    start = 0
    while not run.is_full():
        start, end = page_bounds(start, run.settings.page_size)
        page = fetch_page(run.client, params, start, end, run.settings.save_raw)
        run.keep(page, params)

        if not page.honoured:
            logger.error(
                "The API ignored the window %d-%d for %r; stopping this search to avoid "
                "collecting the same page over and over", start, end, params,
            )
            return

        if start == 0 and run.needs_narrowing(page.total):
            if _split_and_collect(run, params, depth, page.total or 0):
                return
            logger.warning(
                "Search %r advertises %s offers but cannot be narrowed further; keeping "
                "the first %d at most", params, page.total, MAX_OFFERS_PER_SEARCH,
            )

        if not page.offers or len(page.offers) < (end - start + 1):
            return
        start = end + 1
        if page.total is not None and start >= page.total:
            return
        if start > MAX_RANGE_START:
            logger.warning(
                "Reached the pagination ceiling for %r after %d offers", params, len(run.offers)
            )
            return


def _split_and_collect(run: _Run, params: dict[str, Any], depth: int, total: int) -> bool:
    """Halve the creation-date window and collect both halves.

    Returns:
        False when the window cannot be narrowed any further, so that the
        caller falls back to paginating up to the ceiling.
    """
    if depth >= MAX_SPLIT_DEPTH:
        return False
    min_date = params.get("minCreationDate")
    max_date = params.get("maxCreationDate")
    if not (min_date and max_date):
        min_date, max_date = default_window(run.settings.lookback_days)
    halves = split_window(min_date, max_date)
    if halves is None:
        return False

    logger.info(
        "Search %r has %d offers, above the %d ceiling: splitting %s..%s",
        params.get("motsCles"), total, MAX_OFFERS_PER_SEARCH, min_date, max_date,
    )
    for window_min, window_max in halves:
        _collect_window(
            run,
            {**params, "minCreationDate": window_min, "maxCreationDate": window_max},
            depth + 1,
        )
    return True
