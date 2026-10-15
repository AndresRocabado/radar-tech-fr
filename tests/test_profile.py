"""Tests for the « Mon profil » queries, on a synthetic warehouse.

As in ``test_dashboard_queries.py``, the offers go through the shipped
``models.sql`` and the real skill extraction.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import duckdb
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.dashboard import profile  # noqa: E402
from src.dashboard.filtering import Filters  # noqa: E402
from src.nlp.skills import build_offre_competences  # noqa: E402
from src.nlp.taxonomy import Taxonomy  # noqa: E402
from src.warehouse.load import apply_models  # noqa: E402

PROFILE = ("Python", "SQL")


def offer(offer_id: str, created: str, place: str, text: str) -> dict[str, Any]:
    """A minimal offer, shaped like the ones in ``data/raw/``."""
    return {
        "id": offer_id,
        "intitule": "Offre data",
        "description": text,
        "dateCreation": created,
        "typeContrat": "CDI",
        "lieuTravail": {"libelle": place},
        "origineOffre": {"urlOrigine": f"https://candidat.francetravail.fr/offres/{offer_id}"},
    }


OFFERS = [
    offer("A", "2026-06-01T10:00:00Z", "75 - Paris", "Python, SQL et Power BI"),
    offer("B", "2026-06-02T10:00:00Z", "75 - Paris", "Machine Learning avec Python et SQL"),
    offer("C", "2026-06-03T10:00:00Z", "69 - Lyon", "Power BI et Excel"),
    offer("D", "2026-06-04T10:00:00Z", "69 - Lyon", "Docker"),
    offer("E", "2026-06-05T10:00:00Z", "Bretagne", "Rien de technique"),
]


@pytest.fixture()
def con() -> duckdb.DuckDBPyConnection:
    """An in-memory warehouse over :data:`OFFERS`."""
    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE raw_offres (id VARCHAR PRIMARY KEY, offre JSON NOT NULL, "
        "source_file VARCHAR, ingested_at TIMESTAMP)"
    )
    connection.executemany(
        "INSERT INTO raw_offres VALUES (?, ?, 'synthetique', now())",
        [(o["id"], json.dumps(o, ensure_ascii=False)) for o in OFFERS],
    )
    apply_models(connection)
    build_offre_competences(connection)
    yield connection
    connection.close()


def test_detection_des_competences_du_profil() -> None:
    text = "Python, SQL, Power BI, Excel, notions de dbt et d'Airflow. Rigoureux et motivé."
    assert profile.detect_skills(text, Taxonomy.load()) == [
        "Python", "SQL", "Apache Airflow", "dbt", "Power BI", "Excel",
    ]


def test_couverture(con: duckdb.DuckDBPyConnection) -> None:
    """A et B demandent 3 compétences dont 2 du profil ; C et D aucune."""
    summary = profile.coverage_summary(con, Filters(), PROFILE).iloc[0]
    assert summary["offres"] == 5
    assert summary["offres_avec_competences"] == 4
    assert summary["offres_compatibles"] == 2


def test_competences_du_marche_marquees(con: duckdb.DuckDBPyConnection) -> None:
    gap = profile.market_gap(con, Filters(), PROFILE)
    assert gap["competence"].tolist()[:3] == ["Power BI", "Python", "SQL"]
    assert dict(zip(gap["competence"], gap["possedee"], strict=True)) == {
        "Power BI": False, "Python": True, "SQL": True,
        "Docker": False, "Excel": False, "Machine Learning": False,
    }


def test_meilleures_offres(con: duckdb.DuckDBPyConnection) -> None:
    """À couverture égale, la plus récente d'abord ; sans compétence commune, exclue."""
    matches = profile.best_matches(con, Filters(), PROFILE)
    assert matches["id"].tolist() == ["B", "A"]
    assert matches["couverture"].tolist() == pytest.approx([2 / 3, 2 / 3])
    assert matches["manquantes"].tolist() == ["Machine Learning", "Power BI"]
    assert matches.at[0, "url"] == "https://candidat.francetravail.fr/offres/B"


def test_la_couverture_ignore_le_filtre_de_famille(con: duckdb.DuckDBPyConnection) -> None:
    """Filtrer sur l'IA garde B, dont Python et SQL comptent toujours."""
    filters = Filters(families=("ia_ml",))
    assert profile.coverage_summary(con, filters, PROFILE).at[0, "offres_compatibles"] == 1
    gap = profile.market_gap(con, filters, PROFILE)
    assert gap["competence"].tolist() == ["Machine Learning"]


def test_profil_sans_competence_commune(con: duckdb.DuckDBPyConnection) -> None:
    assert profile.coverage_summary(con, Filters(), ("Kubernetes",)).at[
        0, "offres_compatibles"
    ] == 0
    assert profile.best_matches(con, Filters(), ("Kubernetes",)).empty


def test_toutes_les_requetes_survivent_a_une_selection_vide(
    con: duckdb.DuckDBPyConnection,
) -> None:
    filters = Filters(regions=("Corse",))
    for name, query in profile.PROFILE_QUERIES.items():
        assert query(con, filters, PROFILE) is not None, name
    assert profile.coverage_summary(con, filters, PROFILE).at[0, "offres"] == 0
