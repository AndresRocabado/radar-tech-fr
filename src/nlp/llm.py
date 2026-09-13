"""Appel au fournisseur de modèle de langue, choisi dans ``.env``.

``LLM_PROVIDER=mock`` — le défaut — ne sort pas du processus : la réponse est
construite par :func:`src.nlp.rag.mock_answer` à partir des seules statistiques
SQL. La démonstration publique tourne ainsi sans clé, sans crédits et sans
qu'aucun secret n'ait à exister. ``LLM_PROVIDER=anthropic`` appelle l'API
Claude avec ``LLM_API_KEY``.

Un fournisseur mal configuré n'est pas une panne : :func:`answer` retombe sur
la réponse hors ligne, et :meth:`Config.problem` fournit la phrase que la page
affiche pour l'expliquer.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dotenv import load_dotenv

from src.nlp import rag

if TYPE_CHECKING:  # pragma: no cover - importé seulement pour les annotations
    from anthropic.types import Message

logger = logging.getLogger(__name__)

MOCK = "mock"
ANTHROPIC = "anthropic"

DEFAULT_MODEL = "claude-opus-5"
#: Plafond de génération. La réponse tient en quelques phrases, mais le budget
#: couvre aussi le raisonnement adaptatif du modèle, qui se compte dedans.
MAX_TOKENS = 16_000
#: Un dashboard ne peut pas attendre les dix minutes du délai par défaut.
TIMEOUT = 120.0


class LLMError(RuntimeError):
    """Échec d'un appel au fournisseur, porteur d'un message affichable."""


@dataclass(frozen=True)
class Config:
    """Fournisseur, clé et modèle lus dans l'environnement."""

    provider: str = MOCK
    api_key: str | None = None
    model: str = DEFAULT_MODEL

    @classmethod
    def from_env(cls) -> Config:
        """Lire ``LLM_PROVIDER``, ``LLM_API_KEY`` et ``LLM_MODEL`` dans ``.env``."""
        load_dotenv()
        provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
        return cls(
            provider=provider or MOCK,
            api_key=(os.getenv("LLM_API_KEY") or "").strip() or None,
            model=(os.getenv("LLM_MODEL") or "").strip() or DEFAULT_MODEL,
        )

    def problem(self) -> str | None:
        """Expliquer en français pourquoi le fournisseur est inutilisable, ou ``None``.

        Un problème n'empêche pas de répondre : il fait basculer :func:`answer`
        sur le récapitulatif statistique.
        """
        if self.provider == MOCK:
            return None
        if self.provider not in _PROVIDERS:
            return (
                f"Le fournisseur « {self.provider} » est inconnu : `LLM_PROVIDER` "
                f"accepte `{MOCK}` ou `{ANTHROPIC}`."
            )
        if not self.api_key:
            return (
                "Aucune clé d'API n'est configurée : renseignez `LLM_API_KEY` dans "
                "votre fichier `.env`."
            )
        return None


def _mock_answer(context: rag.Context, config: Config) -> str:
    return rag.mock_answer(context)


def _status_message(status_code: int) -> str:
    """Traduire un code HTTP en une phrase affichable."""
    if status_code in (401, 403):
        return "La clé d'API a été refusée par le fournisseur."
    if status_code == 429:
        return "Le quota du fournisseur est atteint : réessayez dans un instant."
    if status_code >= 500:
        return "Le service du fournisseur est momentanément indisponible."
    return f"Le fournisseur a refusé la requête (code {status_code})."


def _message_text(message: Message) -> str:
    """Extraire le texte de la réponse ; lever si le modèle n'a rien rédigé."""
    if message.stop_reason == "refusal":
        raise LLMError("Le modèle a refusé de répondre à cette question.")
    text = "\n".join(
        block.text for block in message.content if block.type == "text"
    ).strip()
    if not text:
        raise LLMError("Le modèle a renvoyé une réponse vide.")
    return text


def _anthropic_answer(context: rag.Context, config: Config) -> str:
    """Interroger l'API Claude et retourner la réponse rédigée.

    L'appel est diffusé en flux : le raisonnement adaptatif rend la durée
    variable, et un flux ne bute pas sur le délai d'une requête unique.
    """
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - dépend de l'installation
        raise LLMError(
            "Le paquet `anthropic` n'est pas installé : `pip install -r requirements.txt`."
        ) from exc

    client = anthropic.Anthropic(api_key=config.api_key, timeout=TIMEOUT, max_retries=1)
    try:
        with client.messages.stream(
            model=config.model,
            max_tokens=MAX_TOKENS,
            system=rag.SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": rag.user_prompt(context)}],
        ) as stream:
            message = stream.get_final_message()
    except anthropic.APIStatusError as exc:
        raise LLMError(_status_message(exc.status_code)) from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError("Le fournisseur est injoignable : vérifiez la connexion.") from exc
    except anthropic.APIError as exc:
        raise LLMError(f"L'appel au modèle a échoué ({type(exc).__name__}).") from exc

    logger.info(
        "%s : %d jetons en entrée, %d en sortie",
        message.model, message.usage.input_tokens, message.usage.output_tokens,
    )
    return _message_text(message)


#: Les fournisseurs acceptés par ``LLM_PROVIDER``.
_PROVIDERS = {MOCK: _mock_answer, ANTHROPIC: _anthropic_answer}


def answer(context: rag.Context, config: Config | None = None) -> str:
    """Répondre à ``context.question`` avec le fournisseur configuré.

    Raises:
        LLMError: si l'appel au fournisseur échoue. Un fournisseur simplement
            mal configuré ne lève pas : la réponse hors ligne prend le relais.
    """
    config = config or Config.from_env()
    if config.problem():
        return rag.mock_answer(context)
    return _PROVIDERS[config.provider](context, config)
