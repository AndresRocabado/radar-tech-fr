"""Entrepôt minimal pour les tests du rapport hebdomadaire.

Deux tables, ``offres`` et ``offre_competences``, avec les seules colonnes que
le rapport lit : chaque cas fixe exactement les comptages qu'il éprouve.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import duckdb

WEEK = date(2026, 9, 7)  # un lundi
PREVIOUS = WEEK - timedelta(weeks=1)


def make_warehouse(
    con: duckdb.DuckDBPyConnection,
    totals: dict[date, int],
    citations: dict[str, dict[date, int]],
) -> None:
    """Créer ``totals[semaine]`` offres par semaine, dont ``citations[compétence][semaine]``
    citent la compétence. Les offres citantes sont les premières de la semaine, et
    une offre sur deux est en alternance."""
    con.execute(
        "CREATE TABLE offres (id VARCHAR, date_creation TIMESTAMP, est_alternance BOOLEAN)"
    )
    con.execute(
        "CREATE TABLE offre_competences "
        "(offre_id VARCHAR, competence VARCHAR, famille VARCHAR, source VARCHAR)"
    )
    for monday, total in totals.items():
        # Mercredi midi : bien à l'intérieur de la semaine.
        created = datetime.combine(monday + timedelta(days=2), datetime.min.time()).replace(hour=12)
        for i in range(total):
            con.execute("INSERT INTO offres VALUES (?, ?, ?)", [f"{monday}-{i}", created, i % 2 == 0])
    for competence, per_week in citations.items():
        for monday, count in per_week.items():
            for i in range(count):
                con.execute(
                    "INSERT INTO offre_competences VALUES (?, ?, 'test', 'texte')",
                    [f"{monday}-{i}", competence],
                )
