"""Palette, gabarit Plotly et constructeurs de graphiques.

Une seule teinte porte les données — le bleu — et un gris neutre sert de
repère de comparaison ; texte, grille et axes restent en retrait. Les couleurs
viennent d'une palette validée pour le contraste et le daltonisme.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
import plotly.graph_objects as go

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
PRIMARY = "#2a78d6"
COMPARISON = MUTED

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

TEMPLATE = go.layout.Template(
    layout=go.Layout(
        font={"family": FONT, "size": 13, "color": INK_SECONDARY},
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        colorway=[PRIMARY, COMPARISON],
        margin={"l": 8, "r": 24, "t": 16, "b": 8},
        xaxis={"showgrid": False, "zeroline": False, "linecolor": AXIS,
               "ticks": "outside", "tickcolor": AXIS, "title": {"text": None}},
        yaxis={"gridcolor": GRID, "zeroline": False, "title": {"text": None}},
        hoverlabel={"bgcolor": "#ffffff", "bordercolor": GRID, "font": {"color": INK}},
        legend={"orientation": "h", "x": 0, "y": 1.02, "yanchor": "bottom",
                "title": {"text": None}},
        barcornerradius=4,
        bargap=0.35,
    )
)


def hbar(
    labels: Sequence[str],
    values: Sequence[float],
    *,
    hovertemplate: str,
    customdata: pd.DataFrame | None = None,
    color: str = PRIMARY,
) -> go.Figure:
    """Barres horizontales dans l'ordre reçu, la première en haut.

    La valeur est écrite au bout de chaque barre : l'axe des x devient inutile.
    """
    fig = go.Figure(
        go.Bar(
            x=list(values),
            y=list(labels),
            orientation="h",
            marker={"color": color},
            text=list(values),
            textposition="outside",
            textfont={"color": INK_SECONDARY},
            cliponaxis=False,
            customdata=None if customdata is None else customdata.to_numpy(),
            hovertemplate=hovertemplate + "<extra></extra>",
        )
    )
    fig.update_layout(
        template=TEMPLATE,
        height=max(140, 30 * len(labels) + 40),
        xaxis={"visible": False},
        yaxis={"autorange": "reversed", "showgrid": False, "ticks": ""},
    )
    return fig


def line(
    x: Sequence[object],
    series: Sequence[tuple[str, Sequence[float], str]],
    *,
    hovertemplate: str,
    xformat: str,
    yformat: str = "",
) -> go.Figure:
    """Courbes sur un axe unique ; ``series`` liste ``(nom, valeurs, couleur)``.

    Une valeur manquante coupe la courbe au lieu d'être interpolée.
    """
    fig = go.Figure()
    for name, values, color in series:
        fig.add_trace(
            go.Scatter(
                x=list(x),
                y=list(values),
                name=name,
                mode="lines+markers",
                line={"color": color, "width": 2},
                marker={"size": 8, "color": color, "line": {"color": SURFACE, "width": 2}},
                hovertemplate=hovertemplate,
            )
        )
    fig.update_layout(
        template=TEMPLATE,
        height=320,
        showlegend=len(series) > 1,
        hovermode="x unified",
        xaxis={"tickformat": xformat},
        yaxis={"tickformat": yformat, "rangemode": "tozero"},
    )
    return fig
