"""Loading of the raw API pages into DuckDB.

The whole warehouse is rebuilt from whatever sits in ``data/raw/`` at the time,
so running this twice is a no-op rather than a duplication: the raw pages are
the single source of truth, and the database is just a projection of them.

Reading goes through DuckDB's ``read_json`` rather than pandas: the JSON never
has to be materialised in Python, and the offers keep the exact field names the
API sent.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import yaml

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "warehouse.duckdb"
DEFAULT_MODELS_PATH = Path(__file__).with_name("models.sql")
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "queries.yaml"

#: Only the offer pages. ``data/raw/_runs/`` holds run manifests, whose shape is
#: entirely different, and the prefix keeps them out without a second filter.
RAW_GLOB = "offres_*.json"

_CREATE_RAW_TABLE = """
CREATE OR REPLACE TABLE raw_offres (
    id VARCHAR PRIMARY KEY,
    offre JSON NOT NULL,
    source_file VARCHAR,
    ingested_at TIMESTAMP
)
"""

# ``columns`` pins the schema instead of letting DuckDB infer one, which also
# discards ``filtresPossibles`` — the other key of every page. Keeping the offer
# as JSON means this table's schema never moves, however many optional fields
# the API adds.
_INSERT_RAW_OFFERS = """
INSERT INTO raw_offres
SELECT
    offre->>'$.id',
    offre,
    filename,
    now()
FROM (
    SELECT unnest(resultats) AS offre, filename
    FROM read_json(?, columns = {'resultats': 'JSON[]'}, filename = true)
)
WHERE offre->>'$.id' IS NOT NULL
QUALIFY row_number() OVER (
    PARTITION BY offre->>'$.id'
    ORDER BY offre->>'$.dateActualisation' DESC
) = 1
"""


def raw_files(raw_dir: Path = DEFAULT_RAW_DIR) -> list[Path]:
    """Return the raw offer pages available under ``raw_dir``, sorted."""
    return sorted(raw_dir.glob(RAW_GLOB))


def load_raw_offres(
    con: duckdb.DuckDBPyConnection, raw_dir: Path = DEFAULT_RAW_DIR
) -> int:
    """Rebuild ``raw_offres`` from every page in ``raw_dir``.

    The same offer is collected several times over, because the search matrix
    crosses every keyword with every contract nature, so only the most recently
    updated copy of each id is kept.

    Returns:
        The number of distinct offers loaded.
    """
    con.execute(_CREATE_RAW_TABLE)

    files = raw_files(raw_dir)
    if not files:
        logger.warning("No raw page matching %s in %s", RAW_GLOB, raw_dir)
        return 0

    con.execute(_INSERT_RAW_OFFERS, [str(raw_dir / RAW_GLOB)])
    loaded = con.execute("SELECT count(*) FROM raw_offres").fetchone()[0]
    logger.info("Loaded %d distinct offers from %d raw pages", loaded, len(files))
    return loaded


def load_salary_bounds(
    con: duckdb.DuckDBPyConnection, config_path: Path = DEFAULT_CONFIG_PATH
) -> None:
    """Create the one-row ``ref_bornes_salaire`` table from ``config/queries.yaml``.

    The ``offres`` view reads its plausibility bounds from this table, so the
    YAML stays their single source, shared with the data-quality tests.
    """
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    bounds = config["salaire"]
    con.execute(
        "CREATE OR REPLACE TABLE ref_bornes_salaire AS "
        "SELECT ?::DOUBLE AS smic_annuel, ?::DOUBLE AS ratio_plancher_alternance, "
        "?::DOUBLE AS plafond_annuel",
        [bounds["smic_annuel"], bounds["ratio_plancher_alternance"], bounds["plafond_annuel"]],
    )


def apply_models(
    con: duckdb.DuckDBPyConnection,
    sql_path: Path = DEFAULT_MODELS_PATH,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> None:
    """Run the SQL models, which create ``ref_regions`` and the ``offres`` view."""
    load_salary_bounds(con, config_path)
    con.execute(sql_path.read_text(encoding="utf-8"))
    logger.info("Applied the SQL models from %s", sql_path)


def build_warehouse(
    db_path: Path = DEFAULT_DB_PATH,
    raw_dir: Path = DEFAULT_RAW_DIR,
    sql_path: Path = DEFAULT_MODELS_PATH,
) -> int:
    """Build the whole warehouse and return the number of offers loaded."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as con:
        loaded = load_raw_offres(con, raw_dir)
        apply_models(con, sql_path)
    return loaded


def main() -> None:
    """Entry point for ``python -m src.warehouse.load``."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    loaded = build_warehouse()
    logger.info("Warehouse ready in %s with %d offers", DEFAULT_DB_PATH, loaded)


if __name__ == "__main__":
    main()
