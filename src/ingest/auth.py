"""OAuth2 client-credentials authentication against France Travail.

Token endpoint and scope were checked against francetravail.io:
``POST https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire``
with the scope ``api_offresdemploiv2 o2dsoffre``.
"""

from __future__ import annotations

import logging
import time

import requests

from .rate_limit import FranceTravailAPIError, RateLimiter, request_with_retry

logger = logging.getLogger(__name__)

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
TOKEN_REALM = "/partenaire"
DEFAULT_SCOPE = "api_offresdemploiv2 o2dsoffre"

REQUEST_TIMEOUT = 30
#: Renew slightly before the real expiry so a long page never races the clock.
EXPIRY_MARGIN_SECONDS = 60
DEFAULT_LIFETIME_SECONDS = 1500


class ClientCredentialsAuth:
    """Fetches and caches an access token until shortly before it expires."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        scope: str = DEFAULT_SCOPE,
        session: requests.Session,
        limiter: RateLimiter,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self._session = session
        self._limiter = limiter
        self._access_token: str | None = None
        self._expires_at = 0.0

    @property
    def token(self) -> str:
        """Return a valid access token, fetching a new one only when needed."""
        if self._access_token and time.monotonic() < self._expires_at:
            return self._access_token
        self._fetch()
        assert self._access_token is not None
        return self._access_token

    def invalidate(self) -> None:
        """Drop the cached token so the next access forces a refresh."""
        self._access_token = None
        self._expires_at = 0.0

    def _scope_candidates(self) -> list[str]:
        """Current scope first, then the legacy ``application_{id}`` variant.

        France Travail dropped the ``application_{client_id}`` prefix that the
        old Pôle emploi portal required, but both forms are still in the wild,
        so an ``invalid_scope`` answer is worth one retry rather than a crash.
        """
        return [self.scope, f"application_{self.client_id} {self.scope}"]

    def _fetch(self) -> None:
        """Request a fresh token, trying each accepted scope form in turn."""
        for scope in self._scope_candidates():
            response = request_with_retry(
                self._session,
                "POST",
                TOKEN_URL,
                self._limiter,
                params={"realm": TOKEN_REALM},
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": scope,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=REQUEST_TIMEOUT,
            )
            if response.ok:
                self._store(response.json(), scope)
                return
            if response.status_code == 400 and "invalid_scope" in response.text:
                logger.warning("Scope %r rejected, trying the legacy form", scope)
                continue
            raise FranceTravailAPIError(response.status_code, response.text, TOKEN_URL)

        raise FranceTravailAPIError(400, "every scope variant was rejected", TOKEN_URL)

    def _store(self, payload: dict[str, object], scope: str) -> None:
        """Cache the granted token and remember which scope form worked."""
        self._access_token = str(payload["access_token"])
        lifetime = int(str(payload.get("expires_in", DEFAULT_LIFETIME_SECONDS)))
        self._expires_at = time.monotonic() + max(0, lifetime - EXPIRY_MARGIN_SECONDS)
        if scope != self.scope:
            logger.warning("Legacy scope form accepted, switching to %r", scope)
            self.scope = scope
        logger.info("Access token obtained, valid for %ds", lifetime)
