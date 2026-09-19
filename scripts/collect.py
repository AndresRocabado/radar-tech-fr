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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.ingest.rate_limit import FranceTravailAPIError  # noqa: E402
from src.ingest.run import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    build_searches,
    load_config,
    run_collection,
)
from src.ingest.tls import enable_system_trust_store  # noqa: E402

logger = logging.getLogger("collect")

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

    if args.dry_run:
        searches = build_searches(config, args.limit)
        print(f"{len(searches)} recherches prévues :")
        for search in searches:
            print(f"  - {search['motsCles']}")
        return 0

    try:
        result = run_collection(config, args.limit, args.max_results)
    except FranceTravailAPIError as error:
        logger.error("Collecte interrompue : %s", error)
        return 1

    report(result.rows, result.unique_ids)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
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
