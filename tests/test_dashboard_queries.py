"""Tests for the dashboard queries, on a synthetic warehouse.

The offers go through the shipped ``models.sql`` and the real skill extraction,
so the queries run against the same views and table as in production.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.dashboard import queries  # noqa: E402
from src.dashboard.filtering import Filters, filter_options  # noqa: E402
from src.nlp.skills import build_offre_competences  # noqa: E402
from src.warehouse.load import apply_models  # noqa: E402


def offer(
    offer_id: str,
    created: str,
    place: str,
    text: str,
    salary: str | None = None,
    company: str | None = None,
) -> dict[str, Any]:
    """A minimal offer, shaped like the ones in ``data/raw/``."""
    result: dict[str, Any] = {
        "id": offer_id,
        "intitule": "Alternance data",
        "description": text,
        "dateCreation": created,
        "typeContrat": "CDD",
        "natureContrat": "Contrat apprentissage",
        "lieuTravail": {"libelle": place},
        "entreprise": {"nom": company} if company else {},
    }
    if salary:
        result["salaire"] = {"libelle": salary}
    return result


OFFERS = [
    offer("A", "2026-06-01T10:00:00Z", "75 - Paris", "Python et Power Automate",
          "Annuel de 20000.0 Euros", "ACME"),
    offer("B", "2026-06-02T10:00:00Z", "75 - Paris", "Machine Learning avec Python",
          "Annuel de 30000.0 Euros", "ACME"),
    # Deux semaines sans offre séparent B de C.
    offer("C", "2026-06-24T10:00:00Z", "69 - Lyon", "Une démarche no-code", None, "Globex"),
    offer("D", "2026-08-10T10:00:00Z", "Bretagne", "Excel", None, None),
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


def test_indicateurs(con: duckdb.DuckDBPyConnection) -> None:
    k = queries.kpis(con, Filters()).iloc[0]
    assert k["offres"] == 4
    assert k["part_alternance"] == 1.0
    assert k["salaire_median"] == 25000.0
    assert k["offres_avec_salaire"] == 2
    assert k["entreprises"] == 2
    assert k["offres_anonymes"] == 1


def test_filtre_region(con: duckdb.DuckDBPyConnection) -> None:
    regions = queries.by_region(con, Filters(regions=("Île-de-France",)))
    assert regions.to_dict("records") == [{"region": "Île-de-France", "offres": 2}]


def test_filtre_periode(con: duckdb.DuckDBPyConnection) -> None:
    filters = Filters(start=date(2026, 6, 2), end=date(2026, 6, 30))
    assert queries.kpis(con, filters).at[0, "offres"] == 2


def test_filtre_famille_restreint_offres_et_competences(con: duckdb.DuckDBPyConnection) -> None:
    filters = Filters(families=("ia_ml",))
    assert queries.kpis(con, filters).at[0, "offres"] == 1
    assert set(queries.top_skills(con, filters)["famille"]) == {"ia_ml"}


def test_filtre_alternance(con: duckdb.DuckDBPyConnection) -> None:
    """La collecte est large : le filtre isole ou exclut l'alternance."""
    cdi = {**offer("E", "2026-06-03T10:00:00Z", "75 - Paris", "SQL"),
           "typeContrat": "CDI", "natureContrat": "Contrat travail"}
    con.execute(
        "INSERT INTO raw_offres VALUES (?, ?, 'synthetique', now())",
        ["E", json.dumps(cdi, ensure_ascii=False)],
    )
    assert queries.kpis(con, Filters()).at[0, "offres"] == 5
    assert queries.kpis(con, Filters(apprenticeship=True)).at[0, "offres"] == 4
    hors = queries.kpis(con, Filters(apprenticeship=False)).iloc[0]
    assert (hors["offres"], hors["part_alternance"]) == (1, 0.0)


def test_les_semaines_vides_valent_zero(con: duckdb.DuckDBPyConnection) -> None:
    weekly = queries.weekly_offers(con, Filters(end=date(2026, 6, 30)))
    assert weekly["offres"].tolist() == [2, 0, 0, 1]


def test_part_nocode_distingue_outils_et_termes_generiques(
    con: duckdb.DuckDBPyConnection,
) -> None:
    share = queries.nocode_share(con, Filters()).iloc[0]
    assert (share["offres"], share["offres_outil"], share["offres_famille"]) == (4, 1, 2)


def test_part_nocode_ignore_le_filtre_de_famille(con: duckdb.DuckDBPyConnection) -> None:
    """Filtrer sur les langages ne doit pas masquer le Power Automate de l'offre A."""
    share = queries.nocode_share(con, Filters(families=("langages",))).iloc[0]
    assert (share["offres"], share["offres_outil"]) == (2, 1)


def test_un_mois_sans_offre_reste_vide(con: duckdb.DuckDBPyConnection) -> None:
    monthly = queries.nocode_monthly(con, Filters())
    assert monthly["offres"].tolist() == [3, 0, 1]
    assert pd.isna(monthly.at[1, "part_outil"])


def test_top_outils_exclut_les_termes_generiques(con: duckdb.DuckDBPyConnection) -> None:
    tools = queries.top_tools_by_family(con, Filters())
    assert not tools["competence"].str.contains("terme générique").any()
    assert tools.groupby("famille").size().max() <= queries.TOOLS_PER_FAMILY


def test_toutes_les_requetes_survivent_a_une_selection_vide(
    con: duckdb.DuckDBPyConnection,
) -> None:
    filters = Filters(regions=("Corse",))
    for name, query in queries.QUERIES.items():
        frame = query(con, filters)
        assert isinstance(frame, pd.DataFrame), name
    assert queries.kpis(con, filters).at[0, "offres"] == 0
    assert queries.weekly_offers(con, filters).empty
    assert queries.nocode_monthly(con, filters).empty


def salaries(with_ai: tuple[int, float], without_ai: tuple[int, float]) -> pd.DataFrame:
    return pd.DataFrame({
        "avec_ia": [True, False],
        "offres_avec_salaire": [with_ai[0], without_ai[0]],
        "salaire_median": [with_ai[1], without_ai[1]],
    })


def test_ecart_salarial_calcule_au_dela_du_seuil() -> None:
    assert queries.salary_gap(salaries((5, 33000.0), (8, 30000.0))) == pytest.approx(0.10)


def test_ecart_salarial_refuse_sous_le_seuil() -> None:
    assert queries.salary_gap(salaries((2, 33000.0), (8, 30000.0))) is None


def test_ecart_salarial_sans_groupe_ia() -> None:
    frame = salaries((5, 1.0), (8, 30000.0)).iloc[[1]]
    assert queries.salary_gap(frame) is None


def test_options_des_filtres(con: duckdb.DuckDBPyConnection) -> None:
    options = filter_options(con)
    assert "Bretagne" in options["regions"]
    assert options["contracts"] == ["CDD"]
    assert (options["start"], options["end"]) == (date(2026, 6, 1), date(2026, 8, 10))
