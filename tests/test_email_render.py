"""Tests du corps HTML de l'e-mail hebdomadaire.

Ce qui est éprouvé ici n'est pas l'apparence mais ce dont elle dépend : des
styles en ligne — un client de messagerie retire les feuilles de style —, des
libellés échappés, et les chiffres à la française.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import duckdb
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.report.email import to_html  # noqa: E402
from src.report.format import decimal, family_label, signed, variation_pct  # noqa: E402
from src.report.render import write_report  # noqa: E402
from src.report.weekly import ReportSettings, build_weekly_report  # noqa: E402
from weekly_data import PREVIOUS, WEEK, make_warehouse  # noqa: E402


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    yield connection
    connection.close()


def report_with(con: duckdb.DuckDBPyConnection, citations: dict) -> object:
    make_warehouse(con, {PREVIOUS: 100, WEEK: 100}, citations)
    return build_weekly_report(con, WEEK, ReportSettings())


# ------------------------------------------------------------- formatage


def test_les_chiffres_suivent_la_convention_francaise() -> None:
    assert decimal(6.04) == "6,0"
    assert signed(80.4) == "+80,4 %"
    assert signed(-12.5) == "-12,5 %"
    assert signed(None) == "n/a"


def test_une_variation_sans_base_ne_vaut_rien() -> None:
    assert variation_pct(0, 42) is None
    assert variation_pct(50, 100) == 100.0


def test_les_familles_sont_nommees_en_clair() -> None:
    """« nocode_lowcode » est un identifiant de la taxonomie, pas un libellé."""
    assert family_label("nocode_lowcode") == "No-code / low-code"
    assert family_label("ia_ml") == "IA & machine learning"
    assert family_label("famille_inconnue") == "famille inconnue"


def test_toutes_les_familles_de_la_taxonomie_ont_un_libelle() -> None:
    from src.nlp.taxonomy import Taxonomy
    from src.report.format import FAMILY_LABELS

    assert set(Taxonomy.load().families) <= set(FAMILY_LABELS)


# ------------------------------------------------------------- HTML


def test_aucune_feuille_de_style_seulement_des_styles_en_ligne(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """Un bloc <style> serait retiré par plusieurs clients, dont Outlook."""
    html = to_html(report_with(con, {"dbt": {PREVIOUS: 10, WEEK: 15}}))

    assert "<style" not in html
    assert "class=" not in html
    assert html.count("style=") > 10


def test_le_tableau_des_alertes_tient_en_quatre_colonnes(
    con: duckdb.DuckDBPyConnection,
) -> None:
    html = to_html(report_with(con, {"dbt": {PREVIOUS: 10, WEEK: 15}}))

    assert len(re.findall(r"<th[ >]", html)) == 4
    assert "Croissance" in html
    assert "+50,0 %" in html
    assert "10 &rarr; 15" in html


def test_une_compétence_émergente_apparait_en_liste(con: duckdb.DuckDBPyConnection) -> None:
    html = to_html(report_with(con, {"n8n": {PREVIOUS: 1, WEEK: 8}}))

    assert "<li" in html
    assert "<table" not in html  # aucune alerte : pas de tableau
    assert "8 offres" in html


def test_une_semaine_sans_rien_le_dit_au_lieu_de_laisser_un_vide(
    con: duckdb.DuckDBPyConnection,
) -> None:
    html = to_html(report_with(con, {}))

    assert "Aucune alerte cette semaine." in html
    assert "Aucune compétence émergente cette semaine." in html


def test_un_libelle_est_echappe(con: duckdb.DuckDBPyConnection) -> None:
    """Une compétence nommée « C++ » ou « <b> » ne doit pas casser le corps."""
    html = to_html(report_with(con, {"<script>alert(1)</script>": {PREVIOUS: 10, WEEK: 15}}))

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_les_totaux_de_la_semaine_sont_annonces(con: duckdb.DuckDBPyConnection) -> None:
    html = to_html(report_with(con, {}))

    assert "100 offres publiées" in html
    assert "50" in html  # une offre sur deux est en alternance


# ------------------------------------------------------------- écriture


def test_write_report_ecrit_les_trois_fichiers(
    con: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    report = report_with(con, {"dbt": {PREVIOUS: 10, WEEK: 15}})

    markdown_path, json_path, html_path = write_report(report, tmp_path)

    assert {p.suffix for p in (markdown_path, json_path, html_path)} == {".md", ".json", ".html"}
    assert all(p.exists() for p in (markdown_path, json_path, html_path))
    assert html_path.read_text(encoding="utf-8").startswith("<div style=")
