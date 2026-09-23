"""Requêtes du dashboard, toutes appliquées au sous-ensemble filtré.

Ce sont des fonctions pures ``(connexion, filtres) -> DataFrame``, sans
Streamlit : elles se testent sur un entrepôt synthétique. Le cache vit dans
:mod:`src.dashboard.data`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import duckdb
import pandas as pd

from src.dashboard.filtering import FILTERED_CTE, UNKNOWN_CONTRACT, UNKNOWN_REGION, Filters
from src.nlp.nocode import GENERIC_TERM, NOCODE_FAMILY

AI_FAMILY = "ia_ml"
TOP_SKILLS_LIMIT = 15
TOOLS_PER_FAMILY = 5
#: En dessous, un salaire médian ne dit rien et l'écart n'est pas calculé.
MIN_SALARY_SAMPLE = 5

Query = Callable[[duckdb.DuckDBPyConnection, Filters], pd.DataFrame]


def _run(
    con: duckdb.DuckDBPyConnection, body: str, filters: Filters, **extra: Any
) -> pd.DataFrame:
    """Exécuter ``body`` à la suite des CTE de filtrage."""
    return con.execute(FILTERED_CTE + body, {**filters.params(), **extra}).df()


def kpis(con: duckdb.DuckDBPyConnection, filters: Filters) -> pd.DataFrame:
    """Les quatre indicateurs de la vue d'ensemble, sur une ligne."""
    return _run(con, """
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
    return _run(con, """
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
    return _run(con, """
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
    return _run(con, f"""
SELECT coalesce(type_contrat, '{UNKNOWN_CONTRACT}') AS type_contrat, count(*) AS offres
FROM filtrees
GROUP BY 1
ORDER BY offres DESC, 1
""", filters)


def by_region(con: duckdb.DuckDBPyConnection, filters: Filters) -> pd.DataFrame:
    """Répartition des offres par région."""
    return _run(con, f"""
SELECT coalesce(region, '{UNKNOWN_REGION}') AS region, count(*) AS offres
FROM filtrees
GROUP BY 1
ORDER BY offres DESC, 1
""", filters)


# Détection no-code sur toutes les compétences de l'offre, pas seulement celles
# des familles filtrées : sinon choisir « IA » ferait tomber la part à zéro.
_NOCODE_CTE = """
, nocode AS (
    SELECT c.offre_id, bool_or(c.competence NOT LIKE $generique) AS outil_nomme
    FROM offre_competences c
    JOIN filtrees f ON f.id = c.offre_id
    WHERE c.famille = $nocode
    GROUP BY c.offre_id
)
"""


def nocode_share(con: duckdb.DuckDBPyConnection, filters: Filters) -> pd.DataFrame:
    """Offres citant un outil no-code nommé, ou au moins un terme générique."""
    return _run(con, _NOCODE_CTE + """
SELECT
    count(*)                                  AS offres,
    count(*) FILTER (WHERE n.outil_nomme)     AS offres_outil,
    count(n.offre_id)                         AS offres_famille
FROM filtrees f
LEFT JOIN nocode n ON n.offre_id = f.id
""", filters, generique=GENERIC_TERM, nocode=NOCODE_FAMILY)


def nocode_monthly(con: duckdb.DuckDBPyConnection, filters: Filters) -> pd.DataFrame:
    """Part mensuelle des offres no-code ; un mois sans offre reste NULL."""
    return _run(con, _NOCODE_CTE + """
, par_mois AS (
    SELECT
        date_trunc('month', f.date_creation)  AS mois,
        count(*)                              AS offres,
        count(*) FILTER (WHERE n.outil_nomme) AS offres_outil,
        count(n.offre_id)                     AS offres_famille
    FROM filtrees f
    LEFT JOIN nocode n ON n.offre_id = f.id
    WHERE f.date_creation IS NOT NULL
    GROUP BY 1
),
mois AS (
    SELECT unnest(generate_series(min(mois), max(mois), INTERVAL 1 MONTH)) AS mois
    FROM par_mois
    HAVING min(mois) IS NOT NULL
)
SELECT
    m.mois,
    coalesce(p.offres, 0)                  AS offres,
    p.offres_outil / nullif(p.offres, 0)   AS part_outil,
    p.offres_famille / nullif(p.offres, 0) AS part_famille
FROM mois m
LEFT JOIN par_mois p USING (mois)
ORDER BY m.mois
""", filters, generique=GENERIC_TERM, nocode=NOCODE_FAMILY)


def salary_by_ai(con: duckdb.DuckDBPyConnection, filters: Filters) -> pd.DataFrame:
    """Salaire médian des offres avec et sans compétence de la famille IA."""
    return _run(con, """
, ia AS (
    SELECT DISTINCT offre_id FROM offre_competences WHERE famille = $ia
)
SELECT
    ia.offre_id IS NOT NULL AS avec_ia,
    count(*)                AS offres,
    count(f.salaire_offre)  AS offres_avec_salaire,
    median(f.salaire_offre) AS salaire_median
FROM filtrees f
LEFT JOIN ia ON ia.offre_id = f.id
GROUP BY 1
ORDER BY 1 DESC
""", filters, ia=AI_FAMILY)


def top_tools_by_family(con: duckdb.DuckDBPyConnection, filters: Filters) -> pd.DataFrame:
    """Les outils nommés les plus cités dans chaque famille."""
    return _run(con, """
, classement AS (
    SELECT famille, competence, count(DISTINCT offre_id) AS offres
    FROM competences_filtrees
    WHERE competence NOT LIKE $generique
    GROUP BY famille, competence
)
SELECT famille, competence, offres
FROM classement
QUALIFY row_number() OVER (PARTITION BY famille ORDER BY offres DESC, competence) <= $par_famille
ORDER BY famille, offres DESC, competence
""", filters, generique=GENERIC_TERM, par_famille=TOOLS_PER_FAMILY)


def salary_gap(salaries: pd.DataFrame, min_sample: int = MIN_SALARY_SAMPLE) -> float | None:
    """Écart relatif du salaire médian avec IA par rapport à sans IA.

    Returns:
        L'écart (0.12 pour +12 %), ou ``None`` si l'un des deux groupes compte
        moins de ``min_sample`` salaires.
    """
    groups = salaries.set_index("avec_ia")
    if not {True, False} <= set(groups.index):
        return None
    with_ai, without_ai = groups.loc[True], groups.loc[False]
    if min(with_ai["offres_avec_salaire"], without_ai["offres_avec_salaire"]) < min_sample:
        return None
    return float(with_ai["salaire_median"] / without_ai["salaire_median"] - 1)


QUERIES: dict[str, Query] = {
    "kpis": kpis,
    "weekly_offers": weekly_offers,
    "top_skills": top_skills,
    "by_contract": by_contract,
    "by_region": by_region,
    "nocode_share": nocode_share,
    "nocode_monthly": nocode_monthly,
    "salary_by_ai": salary_by_ai,
    "top_tools_by_family": top_tools_by_family,
}
