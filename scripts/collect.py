"""Collect France Travail offers, every contract type, for each keyword in config/queries.yaml.

Collection is deliberately wide: alternance is not filtered here but flagged
later by the ``est_alternance`` column, and isolated in the dashboard.

Usage:
    python scripts/collect.py --dry-run
    python scripts/collect.py --limit 1 --max-results 150
    python scripts/collect.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.ingest.france_travail import FranceTravailClient  # noqa: E402
from src.ingest.rate_limit import FranceTravailAPIError  # noqa: E402
from src.ingest.storage import RunManifest  # noqa: E402
from src.ingest.tls import enable_system_trust_store  # noqa: E402

logger = logging.getLogger("collect")

DEFAULT_CONFIG = PROJECT_ROOT / "config" / "queries.yaml"


def load_config(path: Path) -> dict[str, Any]:
    """Read the collection settings from a YAML file."""
    with path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not config.get("keywords"):
        raise ValueError(f"{path} is missing the 'keywords' section")
    return config


def build_searches(config: dict[str, Any]) -> list[dict[str, str]]:
    """Return one search per keyword, with no contract filter."""
    return [{"motsCles": keyword} for keyword in config["keywords"]]


TOTAL_LABEL = "Total (avec doublons)"


def report(rows: list[tuple[str, int]], unique_ids: set[str]) -> None:
    """Print the per-search table and the headline unique-offer count."""
    width = max([len(row[0]) for row in rows] + [len(TOTAL_LABEL), len("Mots-clés")])
    rule = "-" * (width + 10)

    print(f"\n{'Mots-clés':<{width}}  Offres")
    print(rule)
    for keywords, count in rows:
        print(f"{keywords:<{width}}  {count:>6}")
    print(rule)
    print(f"{TOTAL_LABEL:<{width}}  {sum(row[1] for row in rows):>6}")
    print(f"\nOffres uniques collectées : {len(unique_ids)}")


def collect(args: argparse.Namespace) -> int:
    """Run the whole collection and return a shell exit code."""
    config = load_config(args.config)
    searches = build_searches(config)
    if args.limit:
        searches = searches[: args.limit]

    if args.dry_run:
        print(f"{len(searches)} recherches prévues :")
        for search in searches:
            print(f"  - {search['motsCles']}")
        return 0

    defaults = config.get("defaults", {})
    manifest = RunManifest()
    client = FranceTravailClient(manifest=manifest)

    max_results = args.max_results or defaults.get("max_results_per_search")
    rows: list[tuple[str, int]] = []
    unique_ids: set[str] = set()

    try:
        for index, search in enumerate(searches, start=1):
            logger.info("[%d/%d] %s", index, len(searches), search["motsCles"])
            offers = client.search_offers(
                max_results=max_results,
                page_size=defaults.get("page_size", 150),
                lookback_days=defaults.get("lookback_days", 365),
                **search,
            )
            unique_ids.update(str(offer.get("id")) for offer in offers if offer.get("id"))
            rows.append((search["motsCles"], len(offers)))
    except FranceTravailAPIError as error:
        logger.error("Collecte interrompue : %s", error)
        return 1
    finally:
        manifest.write()

    report(rows, unique_ids)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dry-run", action="store_true", help="lister les recherches, sans appel")
    parser.add_argument("--limit", type=int, help="ne traiter que les N premières recherches")
    parser.add_argument("--max-results", type=int, help="plafond d'offres par recherche")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    """Entry point."""
    # The Windows console defaults to cp1252 and mangles the French output.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    enable_system_trust_store()
    return collect(args)


if __name__ == "__main__":
    raise SystemExit(main())
