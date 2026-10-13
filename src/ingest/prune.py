"""Which raw pages in ``data/raw/`` are redundant — a dry run, nothing is deleted.

``data/raw/`` is the only history of the collection: France Travail stops
returning an offer once it is withdrawn, so a lost page cannot be fetched
again. Repeated runs still pile up copies of the same offers, and only the
most recently updated copy of each id ever reaches the warehouse (see
``src/warehouse/load.py``).

A page is redundant when every offer it holds is already present, in the same
or a newer version, in a page that is kept. Pages are examined newest first, so
the latest runs are the ones kept. :func:`verify` then recomputes the result
from scratch: the kept pages must yield exactly the same offers, each at the
same latest version, as all the pages together.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.warehouse.load import raw_files

#: ``offres_<keywords>_<nature>_<start>_<YYYYmmddTHHMMSSZ>.json``, as written by
#: :func:`src.ingest.storage.raw_page_filename`.
_TIMESTAMP = re.compile(r"_(\d{8}T\d{6}Z)\.json$")

Versions = dict[str, str]


@dataclass(frozen=True)
class PrunePlan:
    """The pages to keep and the redundant ones, which nothing deletes yet."""

    keep: tuple[Path, ...]
    redundant: tuple[Path, ...]

    @property
    def redundant_bytes(self) -> int:
        """Disk space the redundant pages take up."""
        return sum(path.stat().st_size for path in self.redundant)


def _offers(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("resultats") or []


def page_versions(path: Path) -> Versions:
    """Latest ``dateActualisation`` of each offer id in one page.

    Offers without an id are skipped, as the loader skips them.
    """
    versions: Versions = {}
    for offer in _offers(path):
        offer_id = offer.get("id")
        if offer_id:
            version = str(offer.get("dateActualisation") or "")
            versions[offer_id] = max(version, versions.get(offer_id, ""))
    return versions


def latest_versions(pages: Iterable[Path]) -> Versions:
    """Latest ``dateActualisation`` of each offer id across ``pages``."""
    merged: Versions = {}
    for path in pages:
        for offer_id, version in page_versions(path).items():
            if version >= merged.get(offer_id, ""):
                merged[offer_id] = version
    return merged


def _newest_first(path: Path) -> tuple[str, str]:
    match = _TIMESTAMP.search(path.name)
    return (match.group(1) if match else "", path.name)


def plan_prune(raw_dir: Path) -> PrunePlan:
    """Split the pages of ``raw_dir`` into kept and redundant ones.

    A page whose name carries no timestamp is always kept: its age is unknown.
    """
    keep: list[Path] = []
    redundant: list[Path] = []
    covered: Versions = {}
    for path in sorted(raw_files(raw_dir), key=_newest_first, reverse=True):
        versions = page_versions(path)
        is_covered = all(
            offer_id in covered and covered[offer_id] >= version
            for offer_id, version in versions.items()
        )
        if is_covered and _TIMESTAMP.search(path.name):
            redundant.append(path)
            continue
        keep.append(path)
        for offer_id, version in versions.items():
            if version >= covered.get(offer_id, ""):
                covered[offer_id] = version
    return PrunePlan(tuple(sorted(keep)), tuple(sorted(redundant)))


def verify(plan: PrunePlan) -> list[str]:
    """Ids whose latest version the plan would lose; empty when the plan is safe.

    Independent of :func:`plan_prune`: both sides are recomputed from the files.
    """
    everything = latest_versions((*plan.keep, *plan.redundant))
    kept = latest_versions(plan.keep)
    return sorted(
        offer_id for offer_id, version in everything.items() if kept.get(offer_id) != version
    )
