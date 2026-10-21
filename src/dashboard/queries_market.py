"""Requêtes de la page « Vue d'ensemble » : volumes, compétences, contrats, régions.

Fonctions pures ``(connexion, filtres) -> DataFrame``, sans Streamlit, toutes
appliquées au sous-ensemble filtré.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from src.dashboard.filtering import UNKNOWN_CONTRACT, UNKNOWN_REGION, Filters, run_filtered

TOP_SKILLS_LIMIT = 15


def kpis(con: duckdb.DuckDBPyConnection, filters: Filters) -> pd.DataFrame:
    """Les quatre indicateurs de la vue d'ensemble, sur une ligne."""
    return run_filtered(con, """
SELECT
    count(*)                                   AS offres,
    avg(CASE WHEN est_alternance THEN 1.0 ELSE 0.0 END) AS part_alternance,
    median(salaire_offre)                      AS salaire_median,
    count(salaire_offre)                       AS offres_avec_salaire,
    count(DISTINCT entreprise)                 AS entreprises,
    count(*) FILTER (WHERE entreprise IS NULL) AS offres_anonymes
FROM filtrees
""", filters)


def weekly_offers(con: duckdb.DuckDBPyConnection, filters: Filters) -> pd.DataFrame:
    """Offres publiées par semaine ; une semaine sans offre vaut 0, pas un trou."""
    return run_filtered(con, """
, bornes AS (
    SELECT min(date_trunc('week', date_creation)) AS debut,
           max(date_trunc('week', date_creation)) AS fin
    FROM filtrees
),
semaines AS (
    SELECT unnest(generate_series(debut, fin, INTERVAL 7 DAY)) AS semaine
    FROM bornes
    WHERE debut IS NOT NULL
)
SELECT s.semaine, count(f.id) AS offres
FROM semaines s
LEFT JOIN filtrees f ON date_trunc('week', f.date_creation) = s.semaine
GROUP BY s.semaine
ORDER BY s.semaine
""", filters)


def top_skills(con: duckdb.DuckDBPyConnection, filters: Filters) -> pd.DataFrame:
    """Les compétences les plus citées, en offres distinctes."""
    return run_filtered(con, """
SELECT
    competence,
    famille,
    count(DISTINCT offre_id) AS offres,
    count(DISTINCT offre_id) / (SELECT count(*) FROM filtrees) AS part
FROM competences_filtrees
GROUP BY competence, famille
ORDER BY offres DESC, competence
LIMIT $limite
""", filters, limite=TOP_SKILLS_LIMIT)


def by_contract(con: duckdb.DuckDBPyConnection, filters: Filters) -> pd.DataFrame:
    """Répartition des offres par type de contrat."""
    return run_filtered(con, f"""
SELECT coalesce(type_contrat, '{UNKNOWN_CONTRACT}') AS type_contrat, count(*) AS offres
FROM filtrees
GROUP BY 1
ORDER BY offres DESC, 1
""", filters)


def by_region(con: duckdb.DuckDBPyConnection, filters: Filters) -> pd.DataFrame:
    """Répartition des offres par région."""
    return run_filtered(con, f"""
SELECT coalesce(region, '{UNKNOWN_REGION}') AS region, count(*) AS offres
FROM filtrees
GROUP BY 1
ORDER BY offres DESC, 1
""", filters)
