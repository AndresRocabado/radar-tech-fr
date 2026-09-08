"""Persistence of raw API pages under ``data/raw/``.

Response bodies are written verbatim, exactly as the API returned them, so that
downstream modules can read real field names instead of guessing. Request
context (parameters, Content-Range, status) is kept apart in a run manifest so
it never pollutes the raw payloads.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"
RUNS_DIRNAME = "_runs"

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Return a lowercase, accent-free, filesystem-safe version of ``text``."""
    normalised = unicodedata.normalize("NFKD", text)
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii")
    return _NON_ALNUM.sub("-", ascii_only.lower()).strip("-") or "sans-mots-cles"


def utc_timestamp(moment: datetime | None = None) -> str:
    """Return a compact UTC timestamp suitable for a filename."""
    moment = moment or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def raw_page_filename(
    keywords: str | None,
    nature_contrat: str | None,
    start: int,
    timestamp: str,
) -> str:
    """Build the filename for one raw page.

    The keyword and timestamp alone would collide, since the same keyword is
    searched once per contract nature and yields several pages, so the contract
    nature and the page offset are part of the name too.
    """
    return (
        f"offres_{slugify(keywords or '')}"
        f"_{slugify(nature_contrat or 'tous')}"
        f"_{start:04d}_{timestamp}.json"
    )


def save_raw_page(
    payload: Any,
    *,
    keywords: str | None,
    nature_contrat: str | None,
    start: int,
    raw_dir: Path = DEFAULT_RAW_DIR,
    timestamp: str | None = None,
) -> Path:
    """Write one API page verbatim to ``data/raw/`` and return its path."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / raw_page_filename(
        keywords, nature_contrat, start, timestamp or utc_timestamp()
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.debug("Saved raw page to %s", path)
    return path


class RunManifest:
    """Collects per-request metadata for one collection run.

    Keeps the raw payload files clean while still recording what was asked for,
    which page came back, and where it landed on disk.
    """

    def __init__(self, run_id: str | None = None, raw_dir: Path = DEFAULT_RAW_DIR) -> None:
        self.run_id = run_id or utc_timestamp()
        self.raw_dir = raw_dir
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.entries: list[dict[str, Any]] = []

    def record(
        self,
        *,
        params: dict[str, Any],
        status_code: int,
        content_range: str | None,
        path: Path | None,
        offers: int,
    ) -> None:
        """Append one request outcome to the manifest."""
        self.entries.append(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "params": params,
                "status_code": status_code,
                "content_range": content_range,
                "file": path.name if path else None,
                "offers": offers,
            }
        )

    def write(self) -> Path:
        """Persist the manifest to ``data/raw/_runs/{run_id}.json``."""
        runs_dir = self.raw_dir / RUNS_DIRNAME
        runs_dir.mkdir(parents=True, exist_ok=True)
        path = runs_dir / f"{self.run_id}.json"
        document = {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "requests": self.entries,
        }
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Wrote run manifest to %s", path)
        return path
