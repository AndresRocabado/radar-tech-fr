"""Tests du rapport hebdomadaire : semaines, alertes, paramètres et rendu."""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.report.render import email_subject, iso_week_label, report_to_dict, to_markdown  # noqa: E402
from src.report.weekly import (  # noqa: E402
    ReportSettings,
    build_weekly_report,
    last_complete_week,
    week_start,
)
from weekly_data import PREVIOUS, WEEK, make_warehouse  # noqa: E402


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    yield connection
    connection.close()


# ------------------------------------------------------------- semaines


def test_week_start_ramene_au_lundi() -> None:
    assert week_start(date(2026, 9, 13)) == date(2026, 9, 7)  # dimanche
    assert week_start(date(2026, 9, 7)) == date(2026, 9, 7)


def test_la_derniere_semaine_complete_exclut_la_semaine_en_cours() -> None:
    # Samedi 19/09 : la semaine du 14/09 n'est pas finie.
    assert last_complete_week(date(2026, 9, 19)) == date(2026, 9, 7)
    # Lundi 14/09 : celle du 07/09 vient de se terminer.
    assert last_complete_week(date(2026, 9, 14)) == date(2026, 9, 7)


def test_libelle_de_semaine_iso() -> None:
    assert iso_week_label(date(2026, 9, 7)) == "2026-W37"


# ------------------------------------------------------------- alertes


def test_alerte_au_dela_du_seuil(con: duckdb.DuckDBPyConnection) -> None:
    make_warehouse(con, {PREVIOUS: 100, WEEK: 100}, {"dbt": {PREVIOUS: 10, WEEK: 13}})

    report = build_weekly_report(con, WEEK, ReportSettings())

    assert [a.competence for a in report.alerts] == ["dbt"]
    assert report.alerts[0].growth_pct == pytest.approx(30.0)


def test_le_seuil_est_strict(con: duckdb.DuckDBPyConnection) -> None:
    make_warehouse(con, {PREVIOUS: 100, WEEK: 100}, {"dbt": {PREVIOUS: 10, WEEK: 12}})

    assert build_weekly_report(con, WEEK, ReportSettings()).alerts == []


def test_sous_le_minimum_pas_d_alerte_mais_emergente(con: duckdb.DuckDBPyConnection) -> None:
    """1 -> 4 fait +300 %, mais sur une base trop maigre pour alerter."""
    make_warehouse(con, {PREVIOUS: 100, WEEK: 100}, {"n8n": {PREVIOUS: 1, WEEK: 4}})

    report = build_weekly_report(con, WEEK, ReportSettings())

    assert report.alerts == []
    assert [e.competence for e in report.emerging] == ["n8n"]


def test_la_part_neutralise_la_hausse_du_volume(con: duckdb.DuckDBPyConnection) -> None:
    """Deux fois plus d'offres, deux fois plus de citations : part stable, pas d'alerte."""
    make_warehouse(con, {PREVIOUS: 50, WEEK: 100}, {"Python": {PREVIOUS: 10, WEEK: 20}})

    assert build_weekly_report(con, WEEK, ReportSettings(measure="part")).alerts == []
    en_volume = build_weekly_report(con, WEEK, ReportSettings(measure="volume"))
    assert en_volume.alerts[0].growth_pct == pytest.approx(100.0)


def test_totaux_de_la_semaine(con: duckdb.DuckDBPyConnection) -> None:
    make_warehouse(con, {PREVIOUS - timedelta(weeks=1): 7, PREVIOUS: 40, WEEK: 60}, {})

    report = build_weekly_report(con, WEEK, ReportSettings())

    assert (report.offers, report.previous_offers, report.alternance_offers) == (60, 40, 30)


# ------------------------------------------------------------- paramètres


def test_les_parametres_sont_lus_dans_le_yaml(tmp_path: Path) -> None:
    fichier = tmp_path / "config.yaml"
    fichier.write_text(
        "rapport:\n  seuil_croissance_pct: 35\n  min_offres_semaine_precedente: 8\n",
        encoding="utf-8",
    )

    settings = ReportSettings.from_config(fichier)

    assert (settings.growth_threshold_pct, settings.min_previous_offers) == (35, 8)
    assert settings.measure == "part"  # valeur par défaut conservée


def test_la_configuration_livree_fixe_le_minimum_a_cinq() -> None:
    assert ReportSettings.from_config().min_previous_offers == 5


def test_une_surcharge_none_garde_la_valeur_configuree() -> None:
    settings = ReportSettings(growth_threshold_pct=20).override(
        growth_threshold_pct=None, min_previous_offers=9
    )
    assert (settings.growth_threshold_pct, settings.min_previous_offers) == (20, 9)


def test_une_mesure_inconnue_est_refusee() -> None:
    with pytest.raises(ValueError, match="measure"):
        ReportSettings(measure="moyenne")


# ------------------------------------------------------------- rendu


def test_rendu_markdown_et_json(con: duckdb.DuckDBPyConnection) -> None:
    make_warehouse(con, {PREVIOUS: 100, WEEK: 100}, {".NET": {PREVIOUS: 10, WEEK: 15}})
    report = build_weekly_report(con, WEEK, ReportSettings())

    markdown = to_markdown(report)
    assert "| .NET |" in markdown  # la virgule décimale ne touche pas les libellés
    assert "+50,0 %" in markdown
    assert email_subject(report).startswith("[ALERTE x1]")
    document = json.loads(json.dumps(report_to_dict(report), default=str))
    assert document["semaine"] == "2026-W37"
    assert document["alertes"][0]["competence"] == ".NET"
