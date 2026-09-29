"""French formatting of the report figures, shared by every rendering.

Kept apart so the Markdown file and the HTML e-mail never drift on a decimal
comma or a rounding rule.
"""

from __future__ import annotations

from datetime import date

#: Les familles de ``data/skills_taxonomy.yaml`` sont des identifiants ; un
#: lecteur du rapport n'a pas à déchiffrer « nocode_lowcode ».
FAMILY_LABELS = {
    "langages": "Langages",
    "cloud": "Cloud",
    "data_engineering": "Data engineering",
    "bi_viz": "BI & visualisation",
    "nocode_lowcode": "No-code / low-code",
    "ia_ml": "IA & machine learning",
    "devops": "DevOps",
}


def family_label(family: str) -> str:
    """Return the readable name of a taxonomy family."""
    return FAMILY_LABELS.get(family, family.replace("_", " "))


def fr_date(day: date) -> str:
    """Return ``21/09/2026``."""
    return day.strftime("%d/%m/%Y")


def decimal(value: float) -> str:
    """French decimal comma, applied to the number only (never to a label like .NET)."""
    return f"{value:.1f}".replace(".", ",")


def signed(value: float | None) -> str:
    """Return ``+80,4 %``, ``-3,2 %`` or ``n/a`` when the figure has no meaning."""
    if value is None:
        return "n/a"
    return ("+" if value >= 0 else "") + decimal(value) + " %"


def variation_pct(previous: int, current: int) -> float | None:
    """Growth from ``previous`` to ``current``, or ``None`` when there was nothing."""
    return round(100.0 * (current - previous) / previous, 1) if previous else None


def iso_week_label(day: date) -> str:
    """Return ``2026-W37`` for any day of ISO week 37 of 2026."""
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"
