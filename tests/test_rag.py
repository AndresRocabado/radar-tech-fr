"""Tests du contexte envoyé au modèle et du choix du fournisseur.

Aucun appel réseau : le mode ``mock`` est le défaut, et le fournisseur
``anthropic`` n'est éprouvé que sur sa configuration — clé absente, nom inconnu
— et sur sa lecture d'une réponse, jamais sur un vrai échange. Les comptages
SQL, eux, sont testés dans ``test_assistant.py``.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.nlp import llm, rag  # noqa: E402

NARROW = " "


def stats(**changes: Any) -> rag.Stats:
    """Des statistiques plausibles, que chaque test ajuste à son besoin."""
    base: dict[str, Any] = {
        "offers": 20,
        "filtered_offers": 342,
        "apprenticeships": 12,
        "with_salary": 7,
        "median_salary": 32000.0,
        "first_day": date(2026, 6, 1),
        "last_day": date(2026, 8, 10),
        "regions": (("Île-de-France", 9), ("Auvergne-Rhône-Alpes", 6)),
        "contracts": (("CDD", 11), ("CDI", 9)),
        "skills": (("Python", 14), ("SQL", 11)),
    }
    return rag.Stats(**{**base, **changes})


def offer(**changes: Any) -> rag.Offer:
    """Une offre complète, que chaque test ajuste à son besoin."""
    base: dict[str, Any] = {
        "id": "A",
        "title": "Data engineer",
        "company": "ACME",
        "place": "69 - Lyon 3e",
        "contract": "CDD",
        "apprenticeship": True,
        "salary_min": 30000.0,
        "salary_max": 35000.0,
        "created": date(2026, 6, 2),
        "description": "Pipelines Python dans le cloud.",
    }
    return rag.Offer(**{**base, **changes})


# --------------------------------------------------------------- contexte


def test_les_statistiques_portent_les_deux_volumes_et_la_mediane() -> None:
    text = stats().as_text()
    assert text.startswith("STATISTIQUES\n")
    assert "- Offres de ce sous-ensemble : 20" in text
    assert "filtres de la barre latérale) : 342" in text
    assert f"12 (60{NARROW}%" in text
    assert f"32{NARROW}000{NARROW}€ (médiane calculée sur les 7 offres" in text
    assert "Publiées entre le 01/06/2026 et le 10/08/2026" in text
    assert "Python (14), SQL (11)" in text


def test_sans_salaire_la_mediane_n_est_pas_inventee() -> None:
    text = stats(with_salary=0, median_salary=None).as_text()
    assert "aucune offre du sous-ensemble n'affiche de salaire" in text
    assert "€" not in text


def test_une_offre_tient_sur_deux_lignes() -> None:
    head, body = offer().as_text(3).split("\n")
    assert head.startswith("[3] Data engineer | ACME | 69 - Lyon 3e | CDD, alternance | ")
    assert f"30{NARROW}000{NARROW}€ à 35{NARROW}000{NARROW}€ par an" in head
    assert "publiée le 02/06/2026" in head
    assert body.strip() == "Pipelines Python dans le cloud."


def test_une_offre_sans_rien_reste_lisible() -> None:
    head, body = offer(
        title=None, company=None, place=None, contract=None, apprenticeship=False,
        salary_min=None, salary_max=None, created=None, description=None,
    ).as_text(1).split("\n")
    assert head == ("[1] intitulé inconnu | entreprise non nommée | lieu non renseigné | "
                    "non renseigné | salaire non renseigné | publiée le non renseigné")
    assert body.strip() == ""


def test_une_description_longue_est_coupee() -> None:
    body = offer(description="mot " * 500).as_text(1).split("\n")[1].strip()
    assert len(body) <= rag.MAX_EXCERPT + 1  # le signe « … » de la coupe
    assert body.endswith("mot…")


def test_le_contexte_enchaine_statistiques_offres_et_question() -> None:
    prompt = rag.user_prompt(rag.Context("Où recrute-t-on ?", stats(), (offer(),)))
    assert prompt.index("STATISTIQUES") < prompt.index("OFFRES") < prompt.index("QUESTION")
    assert prompt.rstrip().endswith("Où recrute-t-on ?")
    assert "[1] Data engineer" in prompt


def test_le_contexte_sans_offre_le_dit_au_modele() -> None:
    prompt = rag.user_prompt(rag.Context("Et alors ?", stats(offers=0)))
    assert "Aucune offre ne correspond" in prompt


def test_le_system_prompt_impose_le_francais_le_decompte_et_l_aveu_d_ignorance() -> None:
    assert "Réponds en français" in rag.SYSTEM_PROMPT
    assert "sur combien d'offres ta réponse se fonde" in rag.SYSTEM_PROMPT
    assert rag.NO_ANSWER in rag.SYSTEM_PROMPT
    assert "Ne cite que des chiffres présents dans le bloc STATISTIQUES" in rag.SYSTEM_PROMPT


# ------------------------------------------------------- réponse hors ligne


def test_la_reponse_hors_ligne_ne_dit_que_les_statistiques() -> None:
    text = rag.mock_answer(rag.Context("Quelles compétences ?", stats(), (offer(),)))
    assert "20 offres les plus proches" in text
    assert "342 offres de la sélection" in text
    assert "Python (14), SQL (11)" in text
    # Rien n'est repris des descriptions : le mode ne lit pas les offres.
    assert "Pipelines" not in text
    assert rag.NO_ANSWER.rstrip(".") in text


def test_la_reponse_hors_ligne_sans_offre_avoue_son_ignorance() -> None:
    text = rag.mock_answer(rag.Context("Et alors ?", stats(offers=0)))
    assert text.startswith(rag.NO_ANSWER)
    assert "élargissez les filtres" in text


# ------------------------------------------------------------ fournisseur


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Isoler les tests du ``.env`` de la machine."""
    monkeypatch.setattr(llm, "load_dotenv", lambda *args, **kwargs: False)
    for name in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_sans_configuration_le_mode_mock_s_applique(env: pytest.MonkeyPatch) -> None:
    config = llm.Config.from_env()
    assert (config.provider, config.api_key) == (llm.MOCK, None)
    assert config.model == llm.DEFAULT_MODEL
    assert config.problem() is None


def test_une_cle_absente_est_expliquee_et_non_levee(env: pytest.MonkeyPatch) -> None:
    env.setenv("LLM_PROVIDER", "Anthropic")  # la casse ne doit pas compter
    config = llm.Config.from_env()
    assert config.provider == llm.ANTHROPIC
    assert "LLM_API_KEY" in (config.problem() or "")
    context = rag.Context("Quelles compétences ?", stats())
    assert llm.answer(context, config) == rag.mock_answer(context)


def test_un_fournisseur_inconnu_est_explique(env: pytest.MonkeyPatch) -> None:
    env.setenv("LLM_PROVIDER", "gpt-maison")
    env.setenv("LLM_API_KEY", "peu-importe")
    assert "gpt-maison" in (llm.Config.from_env().problem() or "")


def test_le_mode_mock_n_appelle_aucun_fournisseur(env: pytest.MonkeyPatch) -> None:
    env.setenv("LLM_API_KEY", "ne-doit-pas-servir")
    context = rag.Context("Quelles compétences ?", stats())
    assert llm.answer(context) == rag.mock_answer(context)


class FakeBlock:
    """Un bloc de contenu, comme en renvoie le SDK."""

    def __init__(self, block_type: str, text: str = "") -> None:
        self.type = block_type
        self.text = text


class FakeMessage:
    """Une réponse du SDK, réduite à ce que lit :func:`llm._message_text`."""

    def __init__(self, stop_reason: str, *blocks: FakeBlock) -> None:
        self.stop_reason = stop_reason
        self.content = list(blocks)


def test_seul_le_texte_de_la_reponse_est_retenu() -> None:
    message = FakeMessage(
        "end_turn", FakeBlock("thinking", "raisonnement"), FakeBlock("text", "  Réponse.  ")
    )
    assert llm._message_text(message) == "Réponse."


def test_un_refus_du_modele_devient_un_message_francais() -> None:
    with pytest.raises(llm.LLMError, match="refusé"):
        llm._message_text(FakeMessage("refusal", FakeBlock("text", "non")))


def test_une_reponse_vide_est_signalee() -> None:
    with pytest.raises(llm.LLMError, match="vide"):
        llm._message_text(FakeMessage("end_turn"))


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "clé d'API"), (429, "quota"), (503, "indisponible"), (400, "code 400")],
)
def test_les_erreurs_du_fournisseur_sont_traduites(status: int, expected: str) -> None:
    assert expected in llm._status_message(status)
