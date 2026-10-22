"""Tests for the dashboard queries, on the synthetic warehouse of ``dashboard_data``."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dashboard_data import make_warehouse, offer  # noqa: E402

from src.dashboard import export, queries  # noqa: E402
from src.dashboard import queries_market as market  # noqa: E402
from src.dashboard import queries_nocode as nocode  # noqa: E402
from src.dashboard.filtering import (  # noqa: E402
    BEGINNER,
    EXPERIENCED,
    Filters,
    filter_options,
)


@pytest.fixture()
def con() -> duckdb.DuckDBPyConnection:
    """An in-memory warehouse over :data:`dashboard_data.OFFERS`."""
    connection = duckdb.connect()
    make_warehouse(connection)
    yield connection
    connection.close()


def test_indicateurs(con: duckdb.DuckDBPyConnection) -> None:
    k = market.kpis(con, Filters()).iloc[0]
    assert k["offres"] == 4
    assert k["part_alternance"] == 1.0
    assert k["salaire_median"] == 25000.0
    assert k["offres_avec_salaire"] == 2
    assert k["entreprises"] == 2
    assert k["offres_anonymes"] == 1


def test_filtre_region(con: duckdb.DuckDBPyConnection) -> None:
    regions = market.by_region(con, Filters(regions=("Île-de-France",)))
    assert regions.to_dict("records") == [{"region": "Île-de-France", "offres": 2}]


def test_filtre_periode(con: duckdb.DuckDBPyConnection) -> None:
    filters = Filters(start=date(2026, 6, 2), end=date(2026, 6, 30))
    assert market.kpis(con, filters).at[0, "offres"] == 2


def test_filtre_famille_restreint_offres_et_competences(con: duckdb.DuckDBPyConnection) -> None:
    filters = Filters(families=("ia_ml",))
    assert market.kpis(con, filters).at[0, "offres"] == 1
    assert set(market.top_skills(con, filters)["famille"]) == {"ia_ml"}


def test_filtre_alternance(con: duckdb.DuckDBPyConnection) -> None:
    """La collecte est large : le filtre isole ou exclut l'alternance."""
    cdi = {**offer("E", "2026-06-03T10:00:00Z", "75 - Paris", "SQL"),
           "typeContrat": "CDI", "natureContrat": "Contrat travail"}
    con.execute(
        "INSERT INTO raw_offres VALUES (?, ?, 'synthetique', now())",
        ["E", json.dumps(cdi, ensure_ascii=False)],
    )
    assert market.kpis(con, Filters()).at[0, "offres"] == 5
    assert market.kpis(con, Filters(apprenticeship=True)).at[0, "offres"] == 4
    hors = market.kpis(con, Filters(apprenticeship=False)).iloc[0]
    assert (hors["offres"], hors["part_alternance"]) == (1, 0.0)


def test_filtre_experience(con: duckdb.DuckDBPyConnection) -> None:
    """Le code ``experienceExige`` sépare débutants acceptés et expérience exigée."""
    assert market.kpis(con, Filters(experience=BEGINNER)).at[0, "offres"] == 3
    assert market.kpis(con, Filters(experience=EXPERIENCED)).at[0, "offres"] == 1


def test_export_suit_les_filtres_sans_description(con: duckdb.DuckDBPyConnection) -> None:
    frame = export.offers_export(con, Filters(regions=("Île-de-France",)))
    assert frame["id_offre"].tolist() == ["B", "A"]  # la plus récente d'abord
    assert "description" not in frame.columns
    assert frame.at[0, "url"] == "https://candidat.francetravail.fr/offres/B"
    assert frame.at[0, "salaire_min_annuel"] == 30000.0


def test_export_csv_lisible_par_excel(con: duckdb.DuckDBPyConnection) -> None:
    payload = export.to_csv(export.offers_export(con, Filters(regions=("Bretagne",))))
    assert payload.startswith("﻿".encode())
    header, row = payload.decode("utf-8-sig").splitlines()
    assert header.startswith("id_offre;intitule;entreprise;region")
    assert row.startswith("D;Alternance data;;Bretagne")


def test_les_semaines_vides_valent_zero(con: duckdb.DuckDBPyConnection) -> None:
    weekly = market.weekly_offers(con, Filters(end=date(2026, 6, 30)))
    assert weekly["offres"].tolist() == [2, 0, 0, 1]


def test_part_nocode_distingue_outils_et_termes_generiques(
    con: duckdb.DuckDBPyConnection,
) -> None:
    share = nocode.nocode_share(con, Filters()).iloc[0]
    assert (share["offres"], share["offres_outil"], share["offres_famille"]) == (4, 1, 2)


def test_part_nocode_ignore_le_filtre_de_famille(con: duckdb.DuckDBPyConnection) -> None:
    """Filtrer sur les langages ne doit pas masquer le Power Automate de l'offre A."""
    share = nocode.nocode_share(con, Filters(families=("langages",))).iloc[0]
    assert (share["offres"], share["offres_outil"]) == (2, 1)


def test_un_mois_sans_offre_reste_vide(con: duckdb.DuckDBPyConnection) -> None:
    monthly = nocode.nocode_monthly(con, Filters())
    assert monthly["offres"].tolist() == [3, 0, 1]
    assert pd.isna(monthly.at[1, "part_outil"])


def test_top_outils_exclut_les_termes_generiques(con: duckdb.DuckDBPyConnection) -> None:
    tools = nocode.top_tools_by_family(con, Filters())
    assert not tools["competence"].str.contains("terme générique").any()
    assert tools.groupby("famille").size().max() <= nocode.TOOLS_PER_FAMILY


def test_toutes_les_requetes_survivent_a_une_selection_vide(
    con: duckdb.DuckDBPyConnection,
) -> None:
    filters = Filters(regions=("Corse",))
    for name, query in queries.QUERIES.items():
        frame = query(con, filters)
        assert isinstance(frame, pd.DataFrame), name
    assert market.kpis(con, filters).at[0, "offres"] == 0
    assert market.weekly_offers(con, filters).empty
    assert nocode.nocode_monthly(con, filters).empty


def salaries(with_ai: tuple[int, float], without_ai: tuple[int, float]) -> pd.DataFrame:
    return pd.DataFrame({
        "avec_ia": [True, False],
        "offres_avec_salaire": [with_ai[0], without_ai[0]],
        "salaire_median": [with_ai[1], without_ai[1]],
    })


def test_ecart_salarial_calcule_au_dela_du_seuil() -> None:
    assert nocode.salary_gap(salaries((5, 33000.0), (8, 30000.0))) == pytest.approx(0.10)


def test_ecart_salarial_refuse_sous_le_seuil() -> None:
    assert nocode.salary_gap(salaries((2, 33000.0), (8, 30000.0))) is None


def test_ecart_salarial_sans_groupe_ia() -> None:
    frame = salaries((5, 1.0), (8, 30000.0)).iloc[[1]]
    assert nocode.salary_gap(frame) is None


def test_options_des_filtres(con: duckdb.DuckDBPyConnection) -> None:
    options = filter_options(con)
    assert "Bretagne" in options["regions"]
    assert options["contracts"] == ["CDD"]
    assert (options["start"], options["end"]) == (date(2026, 6, 1), date(2026, 8, 10))
