"""Page « Assistant » : questions en langage naturel sur le jeu de données."""

from __future__ import annotations

import streamlit as st

from src.dashboard import assistant
from src.dashboard.filtering import Filters
from src.dashboard.ui import NO_OFFER
from src.nlp import llm, rag

#: Clé partagée par le champ de saisie et les boutons d'exemple : un bouton
#: écrit la question dans l'état avant que le champ ne soit redessiné.
QUESTION_KEY = "assistant_question"

EXAMPLES = [
    "Quelles compétences reviennent le plus dans les offres d'alternance ?",
    "Le no-code est-il vraiment demandé dans les offres data ?",
    "Quelles régions recrutent le plus en data engineering ?",
]


def _use_example(question: str) -> None:
    st.session_state[QUESTION_KEY] = question


def _examples() -> None:
    """Trois questions prêtes à poser, une par bouton."""
    for column, example in zip(st.columns(len(EXAMPLES)), EXAMPLES):
        column.button(example, on_click=_use_example, args=(example,), width="stretch")


def _mode(config: llm.Config, reply: assistant.Reply) -> str:
    """La phrase qui dit d'où vient la réponse affichée."""
    offline = config.problem() or config.provider == llm.MOCK or reply.warning
    if offline:
        return (
            f"Réponse hors ligne : les {len(reply.context.offers)} offres les plus "
            "proches sont résumées à partir des seuls comptages SQL, sans modèle "
            "de langue."
        )
    return (
        f"Réponse rédigée par `{config.model}` à partir des "
        f"{len(reply.context.offers)} offres les plus proches et de leurs comptages SQL."
    )


def _sources(context: rag.Context) -> None:
    """Les offres qui ont servi de contexte, dans l'ordre de pertinence."""
    with st.expander(f"Les {len(context.offers)} offres utilisées pour répondre"):
        for rank, offer in enumerate(context.offers, start=1):
            place = offer.place or "lieu non renseigné"
            company = offer.company or "entreprise non nommée"
            st.markdown(
                f"{rank}. **{offer.title or 'Intitulé inconnu'}** — {company}, {place}"
            )
        st.caption(
            "Les chiffres de la réponse sont comptés en SQL sur ces offres, pas "
            "relus dans leurs descriptions."
        )


def render(filters: Filters) -> None:
    """Dessiner la page."""
    st.title("Assistant")
    st.caption(
        "Posez une question en français sur les offres collectées. La question "
        "sert d'abord à retrouver les offres qui s'en rapprochent, puis la réponse "
        "est construite sur ces offres et sur leurs statistiques. Les filtres de "
        "la barre latérale s'appliquent aussi."
    )

    problem = assistant.index_problem()
    if problem:
        st.error(problem, icon=":material/error:")
        return

    config = llm.Config.from_env()
    setup = config.problem()
    if setup:
        st.info(
            f"{setup} La page reste utilisable : la réponse se limite alors au "
            "récapitulatif statistique du mode hors ligne.",
            icon=":material/info:",
        )

    st.session_state.setdefault(QUESTION_KEY, "")
    _examples()
    question = st.text_area(
        "Votre question", key=QUESTION_KEY, height=80,
        placeholder=EXAMPLES[0],
    ).strip()
    st.caption("Ctrl + Entrée pour valider votre question.")
    if not question:
        return

    context = assistant.context(question, filters)
    if context.stats.offers == 0:
        st.info(NO_OFFER, icon=":material/info:")
        return

    reply = assistant.reply(question, filters)
    if reply.warning:
        st.warning(
            f"{reply.warning} La réponse ci-dessous se limite au récapitulatif "
            "statistique.",
            icon=":material/warning:",
        )
    st.markdown(reply.text)
    st.caption(_mode(config, reply))
    _sources(reply.context)
