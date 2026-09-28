"""Tests du worker HTTP appelé par n8n.

Les commandes elles-mêmes sont éprouvées par test_cli.py : ici, seul le
transport est en jeu — traduction des options en options de commande, lecture
de la ligne JSON, et code HTTP rendu quand la commande échoue. Le sous-processus
est donc simulé.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.worker import api  # noqa: E402
from src.worker.api import IngestOptions, ReportOptions, app, build_flags  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_command(monkeypatch: pytest.MonkeyPatch):
    """Remplacer subprocess.run et retenir l'argv reçu."""
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, fake_run.code, fake_run.stdout, fake_run.stderr)

    fake_run.code = 0
    fake_run.stdout = '{"offres": 42}\n'
    fake_run.stderr = ""
    monkeypatch.setattr(api.subprocess, "run", fake_run)
    fake_run.calls = calls
    return fake_run


# ------------------------------------------------------- options -> commande


def test_un_booleen_vrai_devient_un_drapeau_sans_valeur() -> None:
    """Les drapeaux sortent dans l'ordre de déclaration du modèle."""
    assert build_flags(IngestOptions(dry_run=True, limit=2)) == ["--limit", "2", "--dry-run"]


def test_un_booleen_faux_et_une_option_absente_sont_omis() -> None:
    """La commande garde alors ses propres valeurs par défaut."""
    assert build_flags(IngestOptions()) == []


def test_les_options_du_rapport_sont_traduites() -> None:
    flags = build_flags(ReportOptions(week=date(2026, 9, 7), threshold=30, min_previous=10))

    assert flags == ["--week", "2026-09-07", "--threshold", "30.0", "--min-previous", "10"]


# ------------------------------------------------------- routes


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"statut": "ok"}


def test_ingest_retourne_la_ligne_json_de_la_commande(client: TestClient, fake_command) -> None:
    fake_command.stdout = '{"offres_uniques": 2789}\n'

    response = client.post("/ingest", json={"limit": 2})

    assert response.status_code == 200
    assert response.json() == {"offres_uniques": 2789}
    assert fake_command.calls[0][1:] == ["-m", "src.cli", "ingest", "--limit", "2"]


def test_ingest_sans_corps_appelle_la_commande_nue(client: TestClient, fake_command) -> None:
    assert client.post("/ingest").status_code == 200
    assert fake_command.calls[0][1:] == ["-m", "src.cli", "ingest"]


def test_load_transmet_embeddings(client: TestClient, fake_command) -> None:
    client.post("/load", json={"embeddings": True})

    assert fake_command.calls[0][1:] == ["-m", "src.cli", "load", "--embeddings"]


def test_report_joint_le_contenu_du_markdown(
    client: TestClient, fake_command, tmp_path: Path
) -> None:
    rapport = tmp_path / "rapport_2026-W37.md"
    rapport.write_text("# Radar Tech FR\n", encoding="utf-8")
    fake_command.stdout = json.dumps({"alertes": 3, "markdown": str(rapport)})

    document = client.post("/report").json()

    assert document["alertes"] == 3
    assert document["contenu_markdown"] == "# Radar Tech FR\n"


# ------------------------------------------------------- échecs


def test_une_commande_en_echec_donne_un_500_avec_le_journal(
    client: TestClient, fake_command
) -> None:
    fake_command.code = 1
    fake_command.stderr = "ERROR data/raw/ est vide\n"

    response = client.post("/load")

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["code_sortie"] == 1
    assert detail["journal"] == ["ERROR data/raw/ est vide"]


def test_une_option_refusee_donne_un_400(client: TestClient, fake_command) -> None:
    """Typer sort avec 2 : la requête est fautive, pas le pipeline."""
    fake_command.code = 2

    assert client.post("/report", json={"measure": "moyenne"}).status_code == 400


def test_une_sortie_illisible_donne_un_500(client: TestClient, fake_command) -> None:
    fake_command.stdout = "Traceback (most recent call last):\n"

    response = client.post("/load")

    assert response.status_code == 500
    assert response.json()["detail"]["erreur"] == "sortie JSON illisible"


def test_un_depassement_de_delai_donne_un_504(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, api.COMMAND_TIMEOUT_S)

    monkeypatch.setattr(api.subprocess, "run", timeout)

    assert client.post("/ingest").status_code == 504
