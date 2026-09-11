"""Page « Vue d'ensemble » : volume, compétences, contrats et régions."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.dashboard import charts, data
from src.dashboard.filtering import Filters
from src.dashboard.queries import TOP_SKILLS_LIMIT
from src.dashboard.ui import (
    NO_OFFER, explain_if_empty, family_label, fmt_eur, fmt_int, fmt_pct, show_chart,
)


def _indicators(k: pd.Series) -> None:
    salaries = int(k["offres_avec_salaire"])
    salary_help = (
        f"Milieu de la fourchette annoncée, sur les {salaries} offres qui précisent "
        "un salaire exploitable." if salaries
        else "Aucune offre de la sélection ne précise de salaire exploitable."
    )
    cols = st.columns(4)
    cols[0].metric("Nombre d'offres", fmt_int(k["offres"]), border=True)
    cols[1].metric("Part en alternance", fmt_pct(k["part_alternance"]), border=True)
    cols[2].metric("Salaire médian annuel", fmt_eur(k["salaire_median"]),
                   help=salary_help, border=True)
    cols[3].metric(
        "Entreprises qui recrutent", fmt_int(k["entreprises"]), border=True,
        help=f"Entreprises nommées ; {int(k['offres_anonymes'])} offres n'affichent "
             "pas de nom d'entreprise.",
    )
    if float(k["part_alternance"]) == 1.0:
        st.caption(
            "Toutes les offres sont en alternance : la collecte ne cible que les "
            "contrats d'apprentissage et de professionnalisation."
        )


def _weekly(filters: Filters) -> None:
    st.subheader("Évolution hebdomadaire du nombre d'offres")
    weekly = data.load("weekly_offers", filters)
    if explain_if_empty(weekly, "Aucune offre datée dans la sélection : "
                                "l'évolution hebdomadaire ne peut pas être tracée."):
        return
    show_chart(charts.line(
        weekly["semaine"], [("Offres", weekly["offres"], charts.PRIMARY)],
        hovertemplate="Semaine du %{x|%d/%m/%Y} : %{y} offres<extra></extra>",
        xformat="%d/%m",
    ))


def _top_skills(filters: Filters) -> None:
    st.subheader(f"Top {TOP_SKILLS_LIMIT} des compétences demandées")
    skills = data.load("top_skills", filters)
    if explain_if_empty(skills, "Aucune compétence du dictionnaire n'est reconnue "
                                "dans les offres sélectionnées."):
        return
    details = pd.DataFrame({
        "famille": skills["famille"].map(family_label),
        "part": skills["part"] * 100,
    })
    show_chart(charts.hbar(
        skills["competence"], skills["offres"], customdata=details,
        hovertemplate="<b>%{y}</b><br>%{customdata[0]}<br>"
                      "%{x} offres, soit %{customdata[1]:.0f} % de la sélection",
    ))


def _distribution(filters: Filters, name: str, column: str, title: str) -> None:
    st.subheader(title)
    frame = data.load(name, filters)
    if explain_if_empty(frame, "Aucune offre à répartir dans la sélection."):
        return
    show_chart(charts.hbar(frame[column], frame["offres"],
                           hovertemplate="%{y} : %{x} offres"))
    if len(frame) == 1:
        st.caption(f"Une seule modalité dans la sélection : {frame[column].iloc[0]}.")


def render(filters: Filters) -> None:
    """Dessiner la page."""
    st.title("Vue d'ensemble")
    st.caption("Offres tech (data, IA, no-code) publiées sur France Travail.")

    kpis = data.load("kpis", filters)
    if kpis.empty or int(kpis.at[0, "offres"]) == 0:
        st.info(NO_OFFER, icon=":material/info:")
        return

    _indicators(kpis.iloc[0])
    _weekly(filters)
    _top_skills(filters)
    left, right = st.columns(2)
    with left:
        _distribution(filters, "by_contract", "type_contrat", "Par type de contrat")
    with right:
        _distribution(filters, "by_region", "region", "Par région")
