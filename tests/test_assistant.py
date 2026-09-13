"""Tests des comptages SQL de la page « Assistant », sur un entrepôt synthétique.

Les offres passent par le ``models.sql`` livré et par la vraie extraction de
compétences : les statistiques données au modèle sont donc produites par le SQL
qui tourne en production, pas par une requête écrite pour le test.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.dashboard import assistant  # noqa: E402
from src.dashboard.filtering import Filters  # noqa: E402
from src.nlp import rag  # noqa: E402
from src.nlp.skills import build_offre_competences  # noqa: E402
from src.warehouse.load import apply_models  # noqa: E402


def raw_offer(
    offer_id: str, created: str, place: str, text: str, salary: str | None = None
) -> dict[str, Any]:
    """Une offre minimale, au format de ``data/raw/``."""
    result: dict[str, Any] = {
        "id": offer_id,
        "intitule": f"Data {offer_id}",
        "description": text,
        "dateCreation": created,
        "typeContrat": "CDD",
        "natureContrat": "Contrat apprentissage",
        "lieuTravail": {"libelle": place},
        "entreprise": {"nom": "ACME"},
    }
    if salary:
        result["salaire"] = {"libelle": salary}
    return result


OFFERS = [
    raw_offer("A", "2026-06-01T10:00:00Z", "75 - Paris", "Python et Power Automate",
              "Annuel de 20000.0 Euros"),
    raw_offer("B", "2026-06-02T10:00:00Z", "75 - Paris", "Machine Learning avec Python",
              "Annuel de 30000.0 Euros"),
    raw_offer("C", "2026-06-24T10:00:00Z", "69 - Lyon", "Une démarche no-code"),
    raw_offer("D", "2026-08-10T10:00:00Z", "69 - Lyon", "Excel"),
]


@pytest.fixture()
def con() -> duckdb.DuckDBPyConnection:
    """Un entrepôt en mémoire sur :data:`OFFERS`."""
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


def build(
    con: duckdb.DuckDBPyConnection, ids: list[str], filters: Filters | None = None
) -> rag.Context:
    """Le contexte qu'obtiendrait la page pour ces offres et ces filtres."""
    return assistant.build_context(con, "Quelles compétences ?", filters or Filters(), ids)


def test_les_chiffres_portent_sur_le_sous_ensemble_pas_sur_tout(
    con: duckdb.DuckDBPyConnection,
) -> None:
    result = build(con, ["A", "B"]).stats
    assert (result.offers, result.filtered_offers) == (2, 4)
    assert result.apprenticeships == 2
    assert (result.with_salary, result.median_salary) == (2, 25000.0)
    assert (result.first_day, result.last_day) == (date(2026, 6, 1), date(2026, 6, 2))
    assert result.regions == (("Île-de-France", 2),)
    assert result.contracts == (("CDD", 2),)


def test_les_competences_sont_comptees_sur_le_sous_ensemble(
    con: duckdb.DuckDBPyConnection,
) -> None:
    assert dict(build(con, ["A", "B"]).stats.skills)["Python"] == 2
    assert "Python" not in dict(build(con, ["C", "D"]).stats.skills)


def test_les_offres_gardent_l_ordre_de_pertinence(con: duckdb.DuckDBPyConnection) -> None:
    context = build(con, ["C", "A"])
    assert [o.id for o in context.offers] == ["C", "A"]
    assert context.offers[1].place == "75 - Paris"
    assert (context.offers[1].salary_min, context.offers[1].salary_max) == (20000.0, 20000.0)
    assert context.offers[0].salary_min is None


def test_les_filtres_de_la_barre_laterale_s_appliquent_aussi(
    con: duckdb.DuckDBPyConnection,
) -> None:
    context = build(con, ["A", "B", "C"], Filters(regions=("Île-de-France",)))
    assert context.stats.offers == 2
    assert context.stats.filtered_offers == 2
    assert [o.id for o in context.offers] == ["A", "B"]


def test_un_sous_ensemble_vide_ne_casse_pas(con: duckdb.DuckDBPyConnection) -> None:
    context = build(con, [])
    assert (context.stats.offers, context.stats.filtered_offers) == (0, 4)
    assert context.stats.median_salary is None
    assert context.offers == ()
    assert rag.NO_ANSWER in rag.mock_answer(context)
