"""One collection run over every keyword of ``config/queries.yaml``.

Driven by the ``ingest`` command of ``src/cli.py``, the single entry point for
collection — the one n8n calls and the one documented in the README.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .france_travail import FranceTravailClient
from .storage import RunManifest

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "queries.yaml"


@dataclass
class CollectionResult:
    """Outcome of a collection run: offers per search, and distinct ids overall."""

    rows: list[tuple[str, int]] = field(default_factory=list)
    unique_ids: set[str] = field(default_factory=set)
    manifest_path: Path | None = None


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Read the collection settings from a YAML file."""
    with path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not config.get("keywords"):
        raise ValueError(f"{path} is missing the 'keywords' section")
    return config


def build_searches(config: dict[str, Any], limit: int | None = None) -> list[dict[str, str]]:
    """Return one search per keyword, with no contract filter, capped at ``limit``."""
    searches = [{"motsCles": keyword} for keyword in config["keywords"]]
    return searches[:limit] if limit else searches


def run_collection(
    config: dict[str, Any], limit: int | None = None, max_results: int | None = None
) -> CollectionResult:
    """Run every search and write the run manifest, even when a search fails.

    Raises:
        FranceTravailAPIError: when the API refuses a request for good.
    """
    searches = build_searches(config, limit)
    defaults = config.get("defaults", {})
    manifest = RunManifest()
    client = FranceTravailClient(manifest=manifest)
    result = CollectionResult()

    try:
        for index, search in enumerate(searches, start=1):
            logger.info("[%d/%d] %s", index, len(searches), search["motsCles"])
            offers = client.search_offers(
                max_results=max_results or defaults.get("max_results_per_search"),
                page_size=defaults.get("page_size", 150),
                lookback_days=defaults.get("lookback_days", 365),
                **search,
            )
            result.unique_ids.update(str(offer["id"]) for offer in offers if offer.get("id"))
            result.rows.append((search["motsCles"], len(offers)))
    finally:
        result.manifest_path = manifest.write()

    return result
