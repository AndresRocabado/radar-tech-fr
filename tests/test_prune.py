"""Tests de la simulation de nettoyage de data/raw/ (src/ingest/prune.py).

Les pages sont synthétiques : chaque test écrit dans un dossier temporaire, et
le vrai data/raw/ n'est jamais touché.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.cli import app  # noqa: E402
from src.ingest.prune import PrunePlan, plan_prune, verify  # noqa: E402


def page(raw_dir: Path, timestamp: str, offers: dict[str, str], name: str = "data") -> Path:
    """Écrire une page brute : ``offers`` associe un id à sa dateActualisation."""
    path = raw_dir / f"offres_{name}_tous_0000_{timestamp}.json"
    resultats = [{"id": i, "dateActualisation": d} for i, d in offers.items()]
    path.write_text(json.dumps({"resultats": resultats}), encoding="utf-8")
    return path


def test_une_copie_plus_ancienne_et_identique_est_redondante(tmp_path: Path) -> None:
    old = page(tmp_path, "20260901T100000Z", {"1": "2026-09-01", "2": "2026-09-01"})
    new = page(tmp_path, "20260902T100000Z", {"1": "2026-09-01", "2": "2026-09-01"})

    plan = plan_prune(tmp_path)

    assert plan.redundant == (old,)
    assert plan.keep == (new,)
    assert verify(plan) == []


def test_une_page_ancienne_qui_porte_une_offre_unique_est_conservee(tmp_path: Path) -> None:
    """L'offre 3 a disparu de l'API : sa page ancienne est sa seule trace."""
    old = page(tmp_path, "20260901T100000Z", {"1": "2026-09-01", "3": "2026-08-20"})
    page(tmp_path, "20260902T100000Z", {"1": "2026-09-01"})

    plan = plan_prune(tmp_path)

    assert old in plan.keep
    assert plan.redundant == ()


def test_une_version_plus_recente_dans_une_page_ancienne_est_conservee(tmp_path: Path) -> None:
    """Une offre peut changer de page d'une collecte à l'autre."""
    old = page(tmp_path, "20260901T100000Z", {"1": "2026-09-05"}, name="a")
    page(tmp_path, "20260902T100000Z", {"1": "2026-09-01"}, name="b")

    assert old in plan_prune(tmp_path).keep


def test_une_page_sans_horodatage_est_toujours_conservee(tmp_path: Path) -> None:
    page(tmp_path, "20260902T100000Z", {"1": "2026-09-01"})
    odd = tmp_path / "offres_manuel.json"
    odd.write_text(json.dumps({"resultats": [{"id": "1", "dateActualisation": "2026-09-01"}]}))

    assert odd in plan_prune(tmp_path).keep


def test_la_verification_detecte_un_plan_qui_perdrait_une_offre(tmp_path: Path) -> None:
    a = page(tmp_path, "20260901T100000Z", {"1": "2026-09-01"}, name="a")
    b = page(tmp_path, "20260902T100000Z", {"2": "2026-09-01"}, name="b")

    assert verify(PrunePlan(keep=(b,), redundant=(a,))) == ["1"]


def test_la_commande_ne_supprime_rien(tmp_path: Path) -> None:
    page(tmp_path, "20260901T100000Z", {"1": "2026-09-01"})
    page(tmp_path, "20260902T100000Z", {"1": "2026-09-01"})
    before = sorted(p.name for p in tmp_path.iterdir())

    result = CliRunner().invoke(app, ["prune", "--raw-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    sortie = json.loads(result.stdout.strip().splitlines()[-1])
    assert sortie["simulation"] is True
    assert sortie["pages_redondantes"] == 1
    assert sortie["offres_perdues"] == []
    assert sorted(p.name for p in tmp_path.iterdir()) == before
