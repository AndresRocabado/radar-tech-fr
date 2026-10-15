"""Page « Mon profil » : comparer ses compétences à celles des offres filtrées."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.dashboard import charts, data
from src.dashboard.filtering import Filters
from src.dashboard.profile import COVERAGE_THRESHOLD, MARKET_SKILLS_LIMIT, detect_skills
from src.dashboard.ui import NO_OFFER, explain_if_empty, family_label, fmt_int, fmt_pct, show_chart
from src.nlp.taxonomy import Taxonomy

EXAMPLE = "Python, SQL, Power BI, Excel, notions de dbt et d'Airflow"


@st.cache_resource(show_spinner=False)
def _taxonomy() -> Taxonomy:
    """Le dictionnaire compilé une fois par processus, comme pour les offres."""
    return Taxonomy.load()


def _summary(summary: pd.Series, skills: tuple[str, ...], gap: pd.DataFrame) -> None:
    offers, compatible = int(summary["offres"]), int(summary["offres_compatibles"])
    missing = gap.loc[~gap["possedee"], "competence"]
    cols = st.columns(3)
    cols[0].metric("Compétences reconnues", fmt_int(len(skills)), border=True)
    cols[1].metric(
        "Offres compatibles", fmt_pct(compatible / offers if offers else None), border=True,
        help=f"{compatible} offres sur {offers} dont vous possédez au moins "
             f"{COVERAGE_THRESHOLD:.0%} des compétences reconnues.",
    )
    cols[2].metric(
        "Compétence à acquérir en priorité",
        missing.iloc[0] if not missing.empty else "—", border=True,
        help="La plus demandée de la sélection parmi celles absentes de votre profil.",
    )


def _gap(gap: pd.DataFrame) -> None:
    st.subheader(f"Les {MARKET_SKILLS_LIMIT} compétences les plus demandées")
    st.caption("En bleu, celles de votre profil ; en gris, celles à acquérir.")
    details = pd.DataFrame({
        "famille": gap["famille"].map(family_label),
        "part": gap["part"] * 100,
        "statut": gap["possedee"].map({True: "Dans votre profil", False: "À acquérir"}),
    })
    show_chart(charts.hbar(
        gap["competence"], gap["offres"], customdata=details,
        color=[charts.PRIMARY if has else charts.COMPARISON for has in gap["possedee"]],
        hovertemplate="<b>%{y}</b> · %{customdata[2]}<br>%{customdata[0]}<br>"
                      "%{x} offres, soit %{customdata[1]:.0f} % de la sélection",
    ))


def _matches(matches: pd.DataFrame) -> None:
    st.subheader("Les offres qui correspondent le mieux à votre profil")
    if explain_if_empty(matches, "Aucune offre de la sélection ne demande l'une de vos "
                                 "compétences reconnues."):
        return
    st.dataframe(
        matches.drop(columns=["id", "couvertes", "demandees"])
               .fillna({"entreprise": "—", "lieu": "—", "type_contrat": "—", "manquantes": ""}),
        hide_index=True,
        width="stretch",
        column_config={
            "intitule": st.column_config.TextColumn("Offre"),
            "entreprise": st.column_config.TextColumn("Entreprise"),
            "lieu": st.column_config.TextColumn("Lieu"),
            "type_contrat": st.column_config.TextColumn("Contrat"),
            "couverture": st.column_config.ProgressColumn(
                "Couverture", min_value=0.0, max_value=1.0, format="percent",
                help="Part des compétences reconnues dans l'offre que vous possédez.",
            ),
            "manquantes": st.column_config.TextColumn("Il vous manque"),
            "url": st.column_config.LinkColumn("Lien", display_text="Voir l'offre"),
        },
    )


def render(filters: Filters) -> None:
    """Dessiner la page."""
    st.title("Mon profil")
    st.caption(
        "Collez votre CV ou la liste de vos compétences : elles sont comparées à celles "
        "des offres de la sélection. Le texte n'est pas enregistré."
    )

    text = st.text_area("Votre profil", placeholder=EXAMPLE, height=150).strip()
    if not text:
        st.info(f"Par exemple : « {EXAMPLE} ».", icon=":material/info:")
        return

    skills = tuple(detect_skills(text, _taxonomy()))
    if not skills:
        st.warning(
            "Aucune compétence du dictionnaire n'est reconnue dans ce texte. Seules les "
            "technologies suivies par l'observatoire (langages, cloud, data, BI, no-code, "
            "IA, DevOps) sont prises en compte, pas les savoir-être.",
            icon=":material/warning:",
        )
        return
    st.markdown(" ".join(f":blue-badge[{skill}]" for skill in skills))

    summary = data.load_profile("coverage_summary", filters, skills)
    if int(summary.at[0, "offres"]) == 0:
        st.info(NO_OFFER, icon=":material/info:")
        return
    gap = data.load_profile("market_gap", filters, skills)

    _summary(summary.iloc[0], skills, gap)
    if not explain_if_empty(gap, "Aucune compétence du dictionnaire n'est reconnue "
                                 "dans les offres sélectionnées."):
        _gap(gap)
    _matches(data.load_profile("best_matches", filters, skills))
    st.caption(
        f"Seules les {len(_taxonomy().skills)} compétences du dictionnaire de l'observatoire "
        "sont comparées : une technologie absente de la liste n'apparaît ni dans votre "
        "profil ni dans les offres."
    )
