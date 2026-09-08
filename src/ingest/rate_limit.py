"""Rate limiting and retry policy for outbound France Travail API calls.

The Offres d'emploi v2 API is capped at 10 requests per second, so every HTTP
call in this package goes through :func:`request_with_retry`, which serialises
requests behind a :class:`RateLimiter` and retries transient failures.
"""

from __future__ import annotations

import logging
import random
import time
from collections import deque
from threading import Lock
from typing import Any

import requests

logger = logging.getLogger(__name__)

#: Statuses worth retrying: throttling plus transient server-side failures.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 0.5
MAX_BACKOFF_SECONDS = 60.0


class FranceTravailAPIError(RuntimeError):
    """Raised when a request fails and is not worth retrying (or ran out of attempts)."""

    def __init__(self, status_code: int, body: str, url: str) -> None:
        super().__init__(f"France Travail API returned {status_code} for {url}: {body[:500]}")
        self.status_code = status_code
        self.body = body
        self.url = url


class RateLimiter:
    """Sliding-window limiter allowing at most ``max_calls`` per ``period`` seconds.

    Defaults to 8 calls per second, a deliberate margin under the documented
    limit of 10, so that clock skew or retries never push us over the edge.
    """

    def __init__(self, max_calls: int = 8, period: float = 1.0) -> None:
        if max_calls < 1:
            raise ValueError("max_calls must be at least 1")
        self.max_calls = max_calls
        self.period = period
        self._calls: deque[float] = deque()
        self._lock = Lock()

    def acquire(self) -> None:
        """Block until another call is allowed, then record it."""
        with self._lock:
            now = time.monotonic()
            self._forget_calls_older_than(now - self.period)
            if len(self._calls) >= self.max_calls:
                wait_for = self.period - (now - self._calls[0])
                if wait_for > 0:
                    logger.debug("Rate limit reached, sleeping %.3fs", wait_for)
                    time.sleep(wait_for)
                    now = time.monotonic()
                    self._forget_calls_older_than(now - self.period)
            self._calls.append(now)

    def _forget_calls_older_than(self, cutoff: float) -> None:
        while self._calls and self._calls[0] <= cutoff:
            self._calls.popleft()


def parse_retry_after(value: str | None) -> float | None:
    """Return the ``Retry-After`` delay in seconds, or ``None`` if unusable.

    Only the delay-seconds form is honoured; the HTTP-date form falls back to
    the regular exponential backoff.
    """
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        logger.debug("Ignoring non-numeric Retry-After header: %r", value)
        return None


def backoff_delay(attempt: int) -> float:
    """Exponential backoff with full jitter for the given zero-based attempt."""
    ceiling = min(BACKOFF_BASE_SECONDS * (2**attempt), MAX_BACKOFF_SECONDS)
    return random.uniform(0.0, ceiling)


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    limiter: RateLimiter,
    *,
    max_attempts: int = MAX_ATTEMPTS,
    **kwargs: Any,
) -> requests.Response:
    """Perform a rate-limited HTTP request, retrying throttling and 5xx errors.

    Non-retryable client errors (400, 401, 403...) are returned to the caller
    untouched so that it can decide what to do — the client refreshes an
    expired token on 401, for instance.

    Raises:
        FranceTravailAPIError: every attempt failed with a retryable status.
    """
    last_response: requests.Response | None = None

    for attempt in range(max_attempts):
        limiter.acquire()
        try:
            response = session.request(method, url, **kwargs)
        except requests.RequestException as exc:
            if attempt == max_attempts - 1:
                raise FranceTravailAPIError(0, f"network failure: {exc}", url) from exc
            delay = backoff_delay(attempt)
            logger.warning(
                "Network failure on %s (attempt %d/%d), retrying in %.2fs: %s",
                url, attempt + 1, max_attempts, delay, exc,
            )
            time.sleep(delay)
            continue

        if response.status_code not in RETRYABLE_STATUSES:
            return response

        last_response = response
        if attempt == max_attempts - 1:
            break

        delay = parse_retry_after(response.headers.get("Retry-After"))
        if delay is None:
            delay = backoff_delay(attempt)
        logger.warning(
            "Got %d from %s (attempt %d/%d), retrying in %.2fs",
            response.status_code, url, attempt + 1, max_attempts, delay,
        )
        time.sleep(delay)

    assert last_response is not None  # only reachable after a retryable status
    raise FranceTravailAPIError(last_response.status_code, last_response.text, url)
