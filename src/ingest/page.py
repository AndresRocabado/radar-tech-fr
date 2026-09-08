"""Fetching and persisting a single page of search results."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .pagination import parse_content_range
from .storage import save_raw_page, utc_timestamp

if TYPE_CHECKING:  # pragma: no cover - the import cycle only matters to type checkers
    from .france_travail import FranceTravailClient

logger = logging.getLogger(__name__)

SEARCH_PATH = "/offres/search"


@dataclass(frozen=True)
class Page:
    """One page of search results, plus what the API said about it."""

    offers: list[dict[str, Any]]
    total: int | None
    #: False when the API returned a window other than the one we asked for.
    honoured: bool = True


def fetch_page(
    client: FranceTravailClient,
    params: dict[str, Any],
    start: int,
    end: int,
    save_raw: bool,
) -> Page:
    """Fetch one page, persist it verbatim, and report what came back.

    The window goes in the ``range`` query parameter: a ``Range`` request header
    is silently ignored by this API, which then answers with page one.
    """
    request_params = {**params, "range": f"{start}-{end}"}
    response = client.get(SEARCH_PATH, params=request_params)

    content_range = response.headers.get("Content-Range")
    first, _, total = parse_content_range(content_range)

    payload = response.json() if response.status_code != 204 and response.content else {}
    results: list[dict[str, Any]] = payload.get("resultats") or []
    # Guard against an API that stops honouring the window: without it, the
    # caller would page forever over the same first 150 offers.
    honoured = not (results and first is not None and first != start)

    path = None
    if save_raw and results:
        path = save_raw_page(
            payload,
            keywords=params.get("motsCles"),
            nature_contrat=params.get("natureContrat"),
            start=start,
            raw_dir=client.raw_dir,
            timestamp=utc_timestamp(),
        )
    if client.manifest is not None:
        client.manifest.record(
            params=request_params,
            status_code=response.status_code,
            content_range=content_range,
            path=path,
            offers=len(results),
        )
    logger.debug(
        "Fetched %d offers (%s) for %r", len(results), content_range, params.get("motsCles")
    )
    return Page(offers=results, total=total, honoured=honoured)
