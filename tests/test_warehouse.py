"""Data-quality tests running against the real pages in ``data/raw/``.

These guard the invariants the dashboard depends on: no duplicated offer, a
usable location on almost every row, and no implausible salary. The SQL
transformations themselves are tested on synthetic offers in
:mod:`tests.test_warehouse_models`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.warehouse.load import build_warehouse, load_raw_offres, raw_files  # noqa: E402

RAW_DIR = PROJECT_ROOT / "data" / "raw"
CONFIG_PATH = PROJECT_ROOT / "config" / "queries.yaml"


@pytest.fixture(scope="session")
def bornes() -> dict[str, float]:
    """The salary plausibility bounds declared in ``config/queries.yaml``."""
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return config["salaire"]


@pytest.fixture(scope="session")
def warehouse(tmp_path_factory: pytest.TempPathFactory) -> duckdb.DuckDBPyConnection:
    """A warehouse built from the real raw pages.

    ``data/raw/`` is gitignored, so a fresh clone has nothing to load: the tests
    that depend on real data are skipped rather than failing.
    """
    if not raw_files(RAW_DIR):
        pytest.skip(f"aucune page brute dans {RAW_DIR}")
    db_path = tmp_path_factory.mktemp("warehouse") / "test.duckdb"
    build_warehouse(db_path=db_path, raw_dir=RAW_DIR)
    con = duckdb.connect(str(db_path), read_only=True)
    yield con
    con.close()


def test_aucun_id_duplique(warehouse: duckdb.DuckDBPyConnection) -> None:
    for table in ("raw_offres", "offres"):
        total, distincts = warehouse.execute(
            f"SELECT count(*), count(DISTINCT id) FROM {table}"
        ).fetchone()
        assert total == distincts, f"{table} contient des ids en double"
        assert total > 0


def test_rechargement_idempotent(tmp_path: Path) -> None:
    if not raw_files(RAW_DIR):
        pytest.skip(f"aucune page brute dans {RAW_DIR}")
    db_path = tmp_path / "idempotence.duckdb"

    premier = build_warehouse(db_path=db_path, raw_dir=RAW_DIR)
    second = build_warehouse(db_path=db_path, raw_dir=RAW_DIR)

    assert premier == second
    with duckdb.connect(str(db_path)) as con:
        total, distincts = con.execute(
            "SELECT count(*), count(DISTINCT id) FROM offres"
        ).fetchone()
    assert total == distincts == second


def test_les_pages_brutes_contiennent_des_doublons() -> None:
    """Le garde-fou de l'idempotence n'a de sens que s'il y a bien des doublons.

    Sans cette vérification, le test ci-dessus passerait aussi sur un jeu de
    données sans le moindre recoupement, sans rien démontrer.
    """
    files = raw_files(RAW_DIR)
    if not files:
        pytest.skip(f"aucune page brute dans {RAW_DIR}")
    lignes = sum(
        len(json.loads(path.read_text(encoding="utf-8"))["resultats"]) for path in files
    )
    with duckdb.connect() as con:
        charges = load_raw_offres(con, RAW_DIR)
    assert lignes > charges, "les pages brutes ne se recoupent pas, test à revoir"


def test_couverture_departement(warehouse: duckdb.DuckDBPyConnection) -> None:
    total, avec_departement = warehouse.execute(
        "SELECT count(*), count(departement) FROM offres"
    ).fetchone()
    couverture = avec_departement / total
    assert couverture >= 0.80, f"seulement {couverture:.1%} des offres localisées"


def test_toute_region_derivee_est_connue(warehouse: duckdb.DuckDBPyConnection) -> None:
    inconnues = warehouse.execute(
        "SELECT DISTINCT departement FROM offres "
        "WHERE departement IS NOT NULL AND region IS NULL"
    ).fetchall()
    assert inconnues == [], f"départements sans région : {inconnues}"


def test_salaires_dans_des_bornes_vraisemblables(
    warehouse: duckdb.DuckDBPyConnection, bornes: dict[str, float]
) -> None:
    """Aucun salaire annualisé sous le minimum légal ni au-dessus du plafond.

    Le plancher suit le contrat : un apprenti est payé de 27 % à 100 % du SMIC,
    donc appliquer le SMIC plein aux offres d'alternance signalerait des données
    parfaitement légales. Ce test attrape ce qu'il doit attraper, une erreur du
    parser : un montant mensuel pris pour un annuel, un taux horaire non
    annualisé.
    """
    plancher_alternance = bornes["smic_annuel"] * bornes["ratio_plancher_alternance"]
    suspectes = warehouse.execute(
        """
        SELECT id, est_alternance, salaire_min_annuel, salaire_max_annuel
        FROM offres
        WHERE salaire_min_annuel IS NOT NULL
          AND (
              salaire_min_annuel < CASE WHEN est_alternance THEN ? ELSE ? END
              OR salaire_max_annuel > ?
              OR salaire_min_annuel > salaire_max_annuel
          )
        """,
        [plancher_alternance, bornes["smic_annuel"], bornes["plafond_annuel"]],
    ).fetchall()
    assert suspectes == [], f"salaires hors bornes : {suspectes}"
