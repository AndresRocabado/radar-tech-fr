"""Page « Mon profil » : compétences d'un candidat face aux offres filtrées.

Fonctions pures ``(connexion, filtres, profil) -> DataFrame``, sans Streamlit.
Le profil est la liste des compétences du dictionnaire reconnues dans le texte
du candidat, par la même :class:`~src.nlp.taxonomy.Taxonomy` que les offres :
les deux côtés se comparent donc label à label.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import duckdb
import pandas as pd

from src.dashboard.filtering import FILTERED_CTE, Filters
from src.nlp.taxonomy import Taxonomy

MARKET_SKILLS_LIMIT = 20
MATCHES_LIMIT = 10
#: Part des compétences d'une offre que le candidat doit posséder pour qu'elle
#: compte comme compatible.
COVERAGE_THRESHOLD = 0.5

ProfileQuery = Callable[[duckdb.DuckDBPyConnection, Filters, Sequence[str]], pd.DataFrame]


def detect_skills(text: str, taxonomy: Taxonomy) -> list[str]:
    """Labels du dictionnaire cités dans ``text``, dans l'ordre du dictionnaire."""
    return [skill.label for skill in taxonomy.find(text)]


def _run(
    con: duckdb.DuckDBPyConnection,
    body: str,
    filters: Filters,
    profile: Sequence[str],
    **extra: Any,
) -> pd.DataFrame:
    """Exécuter ``body`` à la suite des CTE de filtrage et de couverture."""
    params = {**filters.params(), "profil": list(profile), **extra}
    return con.execute(FILTERED_CTE + _COVERAGE_CTE + body, params).df()


# La couverture porte sur toutes les compétences de l'offre, pas seulement sur
# celles des familles filtrées : une offre exige ce qu'elle exige. Une compétence
# détectée par plusieurs sources ne compte qu'une fois.
_COVERAGE_CTE = """
, competences_offre AS (
    SELECT DISTINCT c.offre_id, c.competence
    FROM offre_competences c
    JOIN filtrees f ON f.id = c.offre_id
),
couverture AS (
    SELECT
        offre_id,
        count(*) AS demandees,
        count(*) FILTER (WHERE list_contains($profil::VARCHAR[], competence)) AS couvertes,
        list(competence ORDER BY competence)
            FILTER (WHERE NOT list_contains($profil::VARCHAR[], competence)) AS manquantes
    FROM competences_offre
    GROUP BY offre_id
)
"""


def coverage_summary(
    con: duckdb.DuckDBPyConnection, filters: Filters, profile: Sequence[str]
) -> pd.DataFrame:
    """Offres filtrées, offres à compétences reconnues et offres compatibles."""
    return _run(con, """
SELECT
    (SELECT count(*) FROM filtrees)                          AS offres,
    count(*)                                                 AS offres_avec_competences,
    count(*) FILTER (WHERE couvertes >= $seuil * demandees)  AS offres_compatibles
FROM couverture
""", filters, profile, seuil=COVERAGE_THRESHOLD)


def market_gap(
    con: duckdb.DuckDBPyConnection, filters: Filters, profile: Sequence[str]
) -> pd.DataFrame:
    """Les compétences les plus demandées, marquées possédées ou non."""
    return _run(con, """
SELECT
    competence,
    famille,
    count(DISTINCT offre_id)                                    AS offres,
    count(DISTINCT offre_id) / (SELECT count(*) FROM filtrees)  AS part,
    list_contains($profil::VARCHAR[], competence)               AS possedee
FROM competences_filtrees
GROUP BY competence, famille
ORDER BY offres DESC, competence
LIMIT $limite
""", filters, profile, limite=MARKET_SKILLS_LIMIT)


def best_matches(
    con: duckdb.DuckDBPyConnection, filters: Filters, profile: Sequence[str]
) -> pd.DataFrame:
    """Les offres dont le candidat couvre la plus grande part des compétences.

    À couverture égale, l'offre qui demande le plus de compétences passe
    devant : couvrir 4 compétences sur 4 dit plus que 1 sur 1.
    """
    return _run(con, """
SELECT
    f.id,
    f.intitule,
    f.entreprise,
    r.offre->>'$.lieuTravail.libelle'      AS lieu,
    f.type_contrat,
    c.couvertes / c.demandees              AS couverture,
    c.couvertes,
    c.demandees,
    array_to_string(c.manquantes, ', ')    AS manquantes,
    r.offre->>'$.origineOffre.urlOrigine'  AS url
FROM couverture c
JOIN filtrees f ON f.id = c.offre_id
JOIN raw_offres r ON r.id = c.offre_id
WHERE c.couvertes > 0
ORDER BY couverture DESC, c.demandees DESC, f.date_creation DESC NULLS LAST, f.id
LIMIT $limite
""", filters, profile, limite=MATCHES_LIMIT)


PROFILE_QUERIES: dict[str, ProfileQuery] = {
    "coverage_summary": coverage_summary,
    "market_gap": market_gap,
    "best_matches": best_matches,
}
