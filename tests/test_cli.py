"""Tests de la ligne de commande appelée par n8n : une ligne JSON sur stdout."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
from typer.testing import CliRunner

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.cli import app  # noqa: E402
from weekly_data import PREVIOUS, WEEK, make_warehouse  # noqa: E402


def last_json_line(output: str) -> dict:
    return json.loads(output.strip().splitlines()[-1])


def build_db(tmp_path: Path) -> Path:
    db = tmp_path / "entrepot.duckdb"
    with duckdb.connect(str(db)) as con:
        make_warehouse(con, {PREVIOUS: 100, WEEK: 100}, {"dbt": {PREVIOUS: 10, WEEK: 13}})
    return db


def test_report_ecrit_les_fichiers_et_une_ligne_json(tmp_path: Path) -> None:
    db = build_db(tmp_path)

    result = CliRunner().invoke(
        app, ["report", "--week", "2026-09-09", "--db", str(db), "--out-dir", str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    sortie = last_json_line(result.stdout)
    assert sortie["alertes"] == 1
    assert sortie["objet"].startswith("[ALERTE x1]")
    assert Path(sortie["markdown"]).read_text(encoding="utf-8").startswith("# Radar Tech FR")
    assert Path(sortie["json"]).exists()


def test_report_threshold_surcharge_la_configuration(tmp_path: Path) -> None:
    db = build_db(tmp_path)

    result = CliRunner().invoke(
        app,
        ["report", "--week", "2026-09-07", "--threshold", "40", "--db", str(db), "--out-dir", str(tmp_path)],
    )

    assert last_json_line(result.stdout)["alertes"] == 0


def test_report_refuse_une_mesure_inconnue(tmp_path: Path) -> None:
    db = build_db(tmp_path)

    result = CliRunner().invoke(app, ["report", "--measure", "moyenne", "--db", str(db)])

    assert result.exit_code != 0


def test_ingest_dry_run_sans_appel_reseau() -> None:
    result = CliRunner().invoke(app, ["ingest", "--dry-run", "--limit", "2"])

    assert result.exit_code == 0, result.output
    assert last_json_line(result.stdout)["recherches"] == ["data engineer", "data analyst"]
