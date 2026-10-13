"""Atomic rebuild of the warehouse file.

Rebuilding in place has two flaws. DuckDB never shrinks a file: every
``CREATE OR REPLACE TABLE`` leaves the old table's blocks free but allocated,
so the versioned warehouse grows with each load. And a reader opening the file
mid-rebuild may see ``raw_offres`` already new but ``offre_competences`` still
old.

Building into a fresh sibling file, then renaming it over the real one, fixes
both: the file holds no dead blocks, readers see either the old warehouse or
the new one, and a failed build leaves the current warehouse untouched.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

STAGING_SUFFIX = ".tmp"
#: DuckDB's write-ahead log sits next to the database, under this suffix.
WAL_SUFFIX = ".wal"
#: Windows refuses to replace a file another process holds open, which the
#: dashboard does for a few milliseconds per query: a short retry outlasts it.
REPLACE_ATTEMPTS = 5
REPLACE_DELAY_SECONDS = 0.2


def staging_path(db_path: Path) -> Path:
    """The sibling file a rebuild of ``db_path`` is written to."""
    return db_path.with_name(db_path.name + STAGING_SUFFIX)


def _wal(path: Path) -> Path:
    return path.with_name(path.name + WAL_SUFFIX)


def _remove(path: Path) -> None:
    """Delete a database file and its write-ahead log, if present."""
    for candidate in (path, _wal(path)):
        candidate.unlink(missing_ok=True)


def _replace(source: Path, target: Path) -> None:
    """Rename ``source`` over ``target``, retrying while the target is held open."""
    for attempt in range(1, REPLACE_ATTEMPTS + 1):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS:
                raise
            logger.warning("%s is in use, retrying the swap (%d/%d)",
                           target, attempt, REPLACE_ATTEMPTS)
            time.sleep(REPLACE_DELAY_SECONDS * attempt)


@contextmanager
def staged_rebuild(db_path: Path) -> Iterator[Path]:
    """Yield a fresh path to build into, swapped over ``db_path`` on success.

    Every connection to the yielded path must be closed before the block ends:
    closing checkpoints the database, so the swapped file is complete on its
    own. If the block raises, the staging file is deleted and ``db_path`` is
    left exactly as it was.
    """
    staging = staging_path(db_path)
    staging.parent.mkdir(parents=True, exist_ok=True)
    _remove(staging)  # leftover of a crashed run
    try:
        yield staging
    except BaseException:
        _remove(staging)
        raise
    # A log left by the old file would be replayed onto the new one.
    _wal(db_path).unlink(missing_ok=True)
    _replace(staging, db_path)
    logger.info("Warehouse swapped into %s", db_path)
