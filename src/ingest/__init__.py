"""Ingestion layer: France Travail API calls and raw payload storage."""

from .auth import ClientCredentialsAuth
from .france_travail import FranceTravailClient
from .rate_limit import FranceTravailAPIError, RateLimiter
from .storage import RunManifest, save_raw_page

__all__ = [
    "ClientCredentialsAuth",
    "FranceTravailAPIError",
    "FranceTravailClient",
    "RateLimiter",
    "RunManifest",
    "save_raw_page",
]
