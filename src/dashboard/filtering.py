"""Filtres du dashboard et sous-ensemble SQL commun à toutes les requêtes.

Chaque requête part des mêmes offres filtrées, définies une seule fois ici sous
la forme de deux CTE : ``filtrees`` (les offres) et ``competences_filtrees``
(leurs compétences, restreintes aux familles choisies). Les valeurs choisies
dans la barre latérale passent en paramètres nommés, jamais concaténées au SQL.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import duckdb

#: Libellés des offres sans région ni type de contrat : elles restent ainsi
#: sélectionnables au lieu de disparaître dès qu'un filtre est posé.
UNKNOWN_REGION = "Non renseignée"
UNKNOWN_CONTRACT = "Non renseigné"


def _as_list(values: Sequence[str] | None) -> list[str] | None:
    """Une sélection vide veut dire « pas de filtre », pas « rien »."""
    return list(values) if values else None


@dataclass(frozen=True)
class Filters:
    """Sélection de la barre latérale. ``None`` signifie « pas de filtre ».

    Poser une période exclut les offres sans date de création : la barre
    latérale ne la transmet donc que si elle diffère de l'étendue complète.
    """

    regions: tuple[str, ...] | None = None
    contracts: tuple[str, ...] | None = None
    start: date | None = None
    end: date | None = None
    families: tuple[str, ...] | None = None
    #: ``True`` : alternance seule ; ``False`` : hors alternance ; ``None`` : toutes.
    apprenticeship: bool | None = None

    def params(self) -> dict[str, Any]:
        """Paramètres nommés attendus par :data:`FILTERED_CTE`."""
        return {
            "regions": _as_list(self.regions),
            "contrats": _as_list(self.contracts),
            "debut": self.start,
            "fin": self.end,
            "familles": _as_list(self.families),
            "alternance": self.apprenticeship,
        }


def filter_options(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Valeurs proposées dans la barre latérale, sur l'ensemble des offres."""
    def values(sql: str) -> list[str]:
        return [row[0] for row in con.execute(sql).fetchall()]

    start, end = con.execute(
        "SELECT min(date_creation)::DATE, max(date_creation)::DATE FROM offres"
    ).fetchone()
    return {
        "regions": values(
            f"SELECT DISTINCT coalesce(region, '{UNKNOWN_REGION}') FROM offres ORDER BY 1"
        ),
        "contracts": values(
            f"SELECT DISTINCT coalesce(type_contrat, '{UNKNOWN_CONTRACT}') FROM offres ORDER BY 1"
        ),
        "families": values("SELECT DISTINCT famille FROM offre_competences ORDER BY 1"),
        "start": start,
        "end": end,
    }


# Une famille choisie restreint les offres à celles qui en citent au moins une
# compétence ; les compétences affichées se limitent ensuite à ces familles.
FILTERED_CTE = f"""
WITH filtrees AS (
    SELECT
        o.*,
        -- Le milieu de la fourchette annoncée, une valeur par offre.
        (o.salaire_min_annuel + o.salaire_max_annuel) / 2 AS salaire_offre
    FROM offres o
    WHERE ($regions::VARCHAR[] IS NULL
           OR list_contains($regions::VARCHAR[], coalesce(o.region, '{UNKNOWN_REGION}')))
      AND ($contrats::VARCHAR[] IS NULL
           OR list_contains($contrats::VARCHAR[], coalesce(o.type_contrat, '{UNKNOWN_CONTRACT}')))
      AND ($debut::DATE IS NULL OR o.date_creation::DATE >= $debut::DATE)
      AND ($fin::DATE IS NULL OR o.date_creation::DATE <= $fin::DATE)
      AND ($alternance::BOOLEAN IS NULL OR o.est_alternance = $alternance::BOOLEAN)
      AND ($familles::VARCHAR[] IS NULL OR o.id IN (
            SELECT c.offre_id
            FROM offre_competences c
            WHERE list_contains($familles::VARCHAR[], c.famille)))
),
competences_filtrees AS (
    SELECT c.*
    FROM offre_competences c
    JOIN filtrees f ON f.id = c.offre_id
    WHERE $familles::VARCHAR[] IS NULL
       OR list_contains($familles::VARCHAR[], c.famille)
)
"""
