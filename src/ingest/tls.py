"""Optional TLS trust configuration for machines behind an inspecting proxy.

Antivirus suites and corporate proxies re-sign HTTPS traffic with their own
root certificate. That root lives in the operating system trust store, which
``certifi`` — the bundle ``requests`` uses by default — knows nothing about, so
every call fails with ``CERTIFICATE_VERIFY_FAILED``.

``truststore`` makes Python verify against the OS store instead, exactly like a
browser does. Certificate verification stays fully enabled; only the list of
trusted roots changes. Entry points call :func:`enable_system_trust_store` once
at startup; it is a no-op wherever the default bundle already works.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def enable_system_trust_store() -> bool:
    """Verify TLS against the OS trust store when ``truststore`` is installed.

    Returns:
        True if the OS trust store is now in use, False if the default
        ``certifi`` bundle stays in charge.
    """
    try:
        import truststore
    except ImportError:
        logger.debug("truststore is not installed, keeping the certifi bundle")
        return False

    truststore.inject_into_ssl()
    logger.debug("TLS verification delegated to the OS trust store")
    return True
