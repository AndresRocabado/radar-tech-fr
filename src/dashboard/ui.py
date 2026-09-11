"""Éléments d'interface partagés : libellés, formats français et messages."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

#: Familles de ``data/skills_taxonomy.yaml``, dans l'ordre du dictionnaire.
FAMILY_LABELS = {
    "langages": "Langages",
    "cloud": "Cloud",
    "data_engineering": "Data engineering",
    "bi_viz": "BI et visualisation",
    "nocode_lowcode": "No-code / low-code",
    "ia_ml": "IA et machine learning",
    "devops": "DevOps",
}

NO_OFFER = (
    "Aucune offre ne correspond aux filtres sélectionnés. Élargissez la région, "
    "le type de contrat, la période ou la famille de compétences."
)

_NARROW_SPACE = " "


def family_label(code: str) -> str:
    """Libellé affiché d'une famille de compétences."""
    return FAMILY_LABELS.get(code, code)


def family_order(codes: list[str]) -> list[str]:
    """Trier des familles dans l'ordre du dictionnaire, les inconnues à la fin."""
    rank = {code: i for i, code in enumerate(FAMILY_LABELS)}
    return sorted(codes, key=lambda code: (rank.get(code, len(rank)), code))


def _missing(value: object) -> bool:
    return value is None or bool(pd.isna(value))


def fmt_int(value: object) -> str:
    """``1234`` -> ``1 234``."""
    return "—" if _missing(value) else f"{int(value):,}".replace(",", _NARROW_SPACE)


def fmt_pct(value: object, signed: bool = False) -> str:
    """``0.123`` -> ``12 %`` (ou ``+12 %`` si ``signed``)."""
    if _missing(value):
        return "—"
    sign = "+" if signed and float(value) > 0 else ""
    return f"{sign}{100 * float(value):.0f}{_NARROW_SPACE}%"


def fmt_eur(value: object) -> str:
    """``35000.0`` -> ``35 000 €``."""
    if _missing(value):
        return "—"
    return f"{float(value):,.0f}{_NARROW_SPACE}€".replace(",", _NARROW_SPACE)


def explain_if_empty(frame: pd.DataFrame, message: str) -> bool:
    """Afficher ``message`` si ``frame`` est vide ; retourner ``True`` dans ce cas."""
    if frame.empty:
        st.info(message, icon=":material/info:")
        return True
    return False


def show_chart(fig: go.Figure) -> None:
    """Afficher un graphique avec le gabarit du projet plutôt que celui de Streamlit."""
    st.plotly_chart(fig, width="stretch", theme=None, config={"displayModeBar": False})
