"""Page « Recherche » : recherche sémantique en texte libre sur les offres."""

from __future__ import annotations

import streamlit as st

from src.dashboard import semantic
from src.dashboard.filtering import Filters
from src.dashboard.ui import NO_OFFER, explain_if_empty

EXAMPLE = "alternance data engineering avec du cloud en région lyonnaise"
RESULTS = 10


def render(filters: Filters) -> None:
    """Dessiner la page."""
    st.title("Recherche")
    st.caption(
        "Décrivez l'offre recherchée en une phrase : les offres sont classées par "
        "proximité de sens, pas par mots-clés exacts. Les filtres de la barre "
        "latérale s'appliquent aussi."
    )

    problem = semantic.index_problem()
    if problem:
        st.error(problem, icon=":material/error:")
        return

    text = st.text_input("Votre recherche", placeholder=EXAMPLE).strip()
    if not text:
        st.info(f"Par exemple : « {EXAMPLE} ».", icon=":material/info:")
        return

    results = semantic.search(text, filters, RESULTS)
    if explain_if_empty(results, NO_OFFER):
        return

    st.dataframe(
        results.drop(columns="id").fillna({"entreprise": "—", "lieu": "—", "type_contrat": "—"}),
        hide_index=True,
        width="stretch",
        column_config={
            "score": st.column_config.ProgressColumn(
                "Score", min_value=0.0, max_value=1.0, format="%.2f",
                help="Similitude cosinus entre votre phrase et l'offre.",
            ),
            "intitule": st.column_config.TextColumn("Offre"),
            "entreprise": st.column_config.TextColumn("Entreprise"),
            "lieu": st.column_config.TextColumn("Lieu"),
            "type_contrat": st.column_config.TextColumn("Contrat"),
            "est_alternance": st.column_config.CheckboxColumn("Alternance"),
            "url": st.column_config.LinkColumn("Lien", display_text="Voir l'offre"),
        },
    )
    st.caption(
        "Le score sert à classer les offres entre elles, pas à juger une offre isolée : "
        "1 signifie un sens identique, 0 aucun rapport."
    )

    missing = semantic.unindexed_count(filters)
    if missing:
        st.warning(
            f"{missing} offre(s) de la sélection ne sont pas encore indexées. "
            "Relancez `python -m src.nlp.embeddings`.",
            icon=":material/warning:",
        )
