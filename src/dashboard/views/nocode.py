"""Page « No-code & IA » : diffusion du no-code et prime salariale de l'IA."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.dashboard import charts, data
from src.dashboard.filtering import Filters
from src.dashboard.queries import MIN_SALARY_SAMPLE, salary_gap
from src.dashboard.ui import (
    NO_OFFER, explain_if_empty, family_label, family_order, fmt_eur, fmt_pct, show_chart,
)


def _share(share: pd.Series) -> None:
    total = int(share["offres"])
    tools, family = int(share["offres_outil"]), int(share["offres_famille"])
    cols = st.columns(2)
    cols[0].metric(
        "Offres citant au moins un outil no-code / low-code", fmt_pct(tools / total),
        help=f"{tools} offres sur {total} nomment un outil (Power Automate, n8n, Airtable…).",
        border=True,
    )
    cols[1].metric(
        "Outil nommé ou simple mention « no-code / low-code »", fmt_pct(family / total),
        help=f"{family} offres sur {total}, en comptant celles qui évoquent la pratique "
             "sans nommer d'outil.",
        border=True,
    )


def _monthly(filters: Filters) -> None:
    st.subheader("Évolution mensuelle de la part no-code")
    monthly = data.load("nocode_monthly", filters)
    if explain_if_empty(monthly, "Aucune offre datée dans la sélection : "
                                 "l'évolution ne peut pas être tracée."):
        return
    show_chart(charts.line(
        monthly["mois"],
        [("Outil nommé", monthly["part_outil"], charts.PRIMARY),
         ("Outil ou mention générique", monthly["part_famille"], charts.COMPARISON)],
        hovertemplate="%{y:.0%}", xformat="%m/%Y", yformat=".0%",
    ))
    st.caption("Part des offres publiées chaque mois ; un mois sans offre laisse un trou.")


def _salary(filters: Filters) -> None:
    st.subheader("Salaire médian avec et sans compétences IA")
    salaries = data.load("salary_by_ai", filters)
    if explain_if_empty(salaries, "Aucune offre à comparer dans la sélection."):
        return
    groups = salaries.set_index("avec_ia")

    def sample(flag: bool) -> int:
        return int(groups.at[flag, "offres_avec_salaire"]) if flag in groups.index else 0

    def median(flag: bool) -> object:
        return groups.at[flag, "salaire_median"] if flag in groups.index else None

    gap = salary_gap(salaries)
    cols = st.columns(3)
    cols[0].metric("Avec compétences IA", fmt_eur(median(True)), border=True,
                   help=f"Calculé sur {sample(True)} offres avec salaire.")
    cols[1].metric("Sans compétence IA", fmt_eur(median(False)), border=True,
                   help=f"Calculé sur {sample(False)} offres avec salaire.")
    cols[2].metric("Écart", fmt_pct(gap, signed=True), border=True,
                   help="Salaire médian avec IA rapporté à celui sans IA.")
    if gap is None:
        st.caption(
            f"Écart non calculé : il faut au moins {MIN_SALARY_SAMPLE} salaires dans "
            f"chaque groupe, la sélection en compte {sample(True)} avec IA et "
            f"{sample(False)} sans. Peu d'offres affichent un salaire chiffré."
        )


def _tools(filters: Filters) -> None:
    st.subheader("Top outils par famille")
    tools = data.load("top_tools_by_family", filters)
    if explain_if_empty(tools, "Aucun outil nommé n'est reconnu dans les offres sélectionnées."):
        return
    cols = st.columns(2)
    for i, family in enumerate(family_order(tools["famille"].unique().tolist())):
        subset = tools[tools["famille"] == family]
        with cols[i % 2]:
            st.markdown(f"**{family_label(family)}**")
            show_chart(charts.hbar(subset["competence"], subset["offres"],
                                   hovertemplate="%{y} : %{x} offres"))


def render(filters: Filters) -> None:
    """Dessiner la page."""
    st.title("No-code & IA")
    st.caption("Place des outils no-code / low-code et effet des compétences IA sur le salaire.")

    share = data.load("nocode_share", filters)
    if share.empty or int(share.at[0, "offres"]) == 0:
        st.info(NO_OFFER, icon=":material/info:")
        return

    _share(share.iloc[0])
    _monthly(filters)
    _salary(filters)
    _tools(filters)
