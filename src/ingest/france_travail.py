"""Client for the France Travail *Offres d'emploi v2* API.

Endpoints and limits checked against francetravail.io and data.gouv.fr:

* token   ``POST https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire``
* scope   ``api_offresdemploiv2 o2dsoffre``
* search  ``GET https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search``
* quota   10 requests per second

This module owns the transport: credentials, headers, retries. Token handling
lives in :mod:`src.ingest.auth` and the pagination strategy — including the
1150-offer ceiling of a single search — in :mod:`src.ingest.collector`.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from .auth import DEFAULT_SCOPE, REQUEST_TIMEOUT, ClientCredentialsAuth
from .collector import DEFAULT_LOOKBACK_DAYS, SearchSettings, collect_search
from .pagination import MAX_PAGE_SIZE
from .rate_limit import FranceTravailAPIError, RateLimiter, request_with_retry
from .storage import DEFAULT_RAW_DIR, RunManifest

logger = logging.getLogger(__name__)

API_BASE = "https://api.francetravail.io/partenaire/offresdemploi/v2"


class FranceTravailClient:
    """Authenticated, rate-limited access to the Offres d'emploi v2 API."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        scope: str = DEFAULT_SCOPE,
        raw_dir: Path = DEFAULT_RAW_DIR,
        manifest: RunManifest | None = None,
        limiter: RateLimiter | None = None,
        session: requests.Session | None = None,
    ) -> None:
        load_dotenv()
        resolved_id = client_id or os.getenv("FT_CLIENT_ID")
        resolved_secret = client_secret or os.getenv("FT_CLIENT_SECRET")
        if not resolved_id or not resolved_secret:
            raise ValueError(
                "Missing credentials: set FT_CLIENT_ID and FT_CLIENT_SECRET in .env"
            )

        self.raw_dir = raw_dir
        self.manifest = manifest
        self._limiter = limiter or RateLimiter()
        self._session = session or requests.Session()
        self.auth = ClientCredentialsAuth(
            resolved_id,
            resolved_secret,
            scope=scope,
            session=self._session,
            limiter=self._limiter,
        )

    def get(
        self, path: str, *, params: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        """GET an API path, refreshing the token once if it turns out to be stale.

        Raises:
            FranceTravailAPIError: the API answered with an error status.
        """
        url = f"{API_BASE}{path}"
        base_headers = {"Accept": "application/json", **(headers or {})}

        def send() -> requests.Response:
            return request_with_retry(
                self._session,
                "GET",
                url,
                self._limiter,
                params=params,
                headers={**base_headers, "Authorization": f"Bearer {self.auth.token}"},
                timeout=REQUEST_TIMEOUT,
            )

        response = send()
        if response.status_code == 401:
            logger.info("Token rejected, refreshing and retrying once")
            self.auth.invalidate()
            response = send()
        if response.status_code >= 400:
            raise FranceTravailAPIError(response.status_code, response.text, url)
        return response

    def get_referentiel(self, name: str) -> list[dict[str, Any]]:
        """Return one of the API reference lists, e.g. ``naturesContrats``.

        Lets callers validate contract codes against the live API instead of
        hardcoding values that may drift.
        """
        return self.get(f"/referentiel/{name}", params={}).json()

    def search_offers(
        self,
        *,
        max_results: int | None = None,
        page_size: int = MAX_PAGE_SIZE,
        save_raw: bool = True,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        **params: Any,
    ) -> list[dict[str, Any]]:
        """Run a search, paginating through it and returning unique offers.

        Any keyword argument other than the ones above goes straight to the API
        (``motsCles``, ``natureContrat``, ``departement``...). A search
        advertising more than 3150 results — the hard pagination ceiling — is
        split into narrower ``minCreationDate``/``maxCreationDate`` windows,
        each collected recursively. Every page is written to ``data/raw/``
        before being accumulated, so an interrupted run keeps what it fetched.

        Returns:
            Offers de-duplicated by ``id``, in the order they were seen.
        """
        settings = SearchSettings(
            max_results=max_results,
            page_size=page_size,
            save_raw=save_raw,
            lookback_days=lookback_days,
        )
        return collect_search(self, dict(params), settings)
