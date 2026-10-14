"""Filtres de la barre latérale, communs aux deux pages."""

from __future__ import annotations

from datetime import date
from typing import Any

import streamlit as st

from src.dashboard import data
from src.dashboard.export import to_csv
from src.dashboard.filtering import BEGINNER, EXPERIENCED, Filters
from src.dashboard.ui import family_label, family_order

#: Libellé affiché → valeur transmise au filtre ``est_alternance``.
APPRENTICESHIP_CHOICES: dict[str, bool | None] = {
    "Toutes": None,
    "Alternance uniquement": True,
    "Hors alternance": False,
}

#: Libellé affiché → code ``experienceExige`` transmis au filtre.
EXPERIENCE_CHOICES: dict[str, str | None] = {
    "Toutes": None,
    "Débutant accepté": BEGINNER,
    "Expérience exigée": EXPERIENCED,
}


def _period(selection: Any, start: date, end: date) -> tuple[date | None, date | None]:
    """Réduire la saisie à ``(début, fin)`` ; l'étendue complète vaut « pas de filtre ».

    Pendant la saisie, ``st.date_input`` renvoie une seule date : la fin reste
    alors celle des données.
    """
    dates = tuple(selection) if isinstance(selection, (tuple, list)) else (selection,)
    chosen_start = dates[0] if dates else start
    chosen_end = dates[1] if len(dates) > 1 else end
    return (
        None if chosen_start <= start else chosen_start,
        None if chosen_end >= end else chosen_end,
    )


def render(options: dict[str, Any]) -> Filters:
    """Dessiner les filtres et retourner la sélection courante."""
    with st.sidebar:
        st.header("Filtres")
        regions = st.multiselect(
            "Région", options["regions"], placeholder="Toutes les régions", key="f_regions"
        )
        contracts = st.multiselect(
            "Type de contrat", options["contracts"],
            placeholder="Tous les contrats", key="f_contrats",
        )
        apprenticeship = st.radio(
            "Alternance", list(APPRENTICESHIP_CHOICES), horizontal=True, key="f_alternance",
            help="Apprentissage ou contrat de professionnalisation.",
        )
        experience = st.radio(
            "Expérience", list(EXPERIENCE_CHOICES), horizontal=True, key="f_experience",
            help="Niveau d'expérience indiqué par le recruteur sur France Travail.",
        )

        start, end = options["start"], options["end"]
        chosen_start = chosen_end = None
        if start is not None and end is not None:
            selection = st.date_input(
                "Période de publication", value=(start, end),
                min_value=start, max_value=end, format="DD/MM/YYYY", key="f_periode",
            )
            chosen_start, chosen_end = _period(selection, start, end)
        else:
            st.caption("Aucune date de publication dans l'entrepôt : pas de filtre de période.")

        families = st.multiselect(
            "Famille de compétences", family_order(options["families"]),
            format_func=family_label, placeholder="Toutes les familles", key="f_familles",
        )
        st.caption(
            "Choisir une famille restreint les offres à celles qui citent au moins "
            "une de ses compétences."
        )

    filters = Filters(
        regions=tuple(regions) or None,
        contracts=tuple(contracts) or None,
        start=chosen_start,
        end=chosen_end,
        families=tuple(families) or None,
        apprenticeship=APPRENTICESHIP_CHOICES[apprenticeship],
        experience=EXPERIENCE_CHOICES[experience],
    )
    with st.sidebar:
        st.divider()
        # Le CSV n'est produit qu'au clic : la requête ne tourne pas à chaque interaction.
        st.download_button(
            "Télécharger la sélection (CSV)",
            data=lambda: to_csv(data.load("offers_export", filters)),
            file_name="radar-tech-fr_offres.csv", mime="text/csv",
            on_click="ignore", icon=":material/download:", width="stretch",
        )
        if end is not None:
            st.caption(f"Offres publiées jusqu'au {end:%d/%m/%Y}.")
    return filters
