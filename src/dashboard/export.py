"""Export CSV des offres filtrées, sans Streamlit pour rester testable.

La description est écartée : elle pèse l'essentiel du volume, et le lien vers
l'offre d'origine suffit pour la lire.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from src.dashboard.filtering import FILTERED_CTE, Filters

_EXPORT_SQL = """
SELECT
    f.id                                   AS id_offre,
    f.intitule,
    f.entreprise,
    f.region,
    f.departement,
    f.type_contrat,
    f.est_alternance,
    f.experience,
    f.salaire_min_annuel,
    f.salaire_max_annuel,
    f.date_creation::DATE                  AS date_publication,
    r.offre->>'$.origineOffre.urlOrigine'  AS url
FROM filtrees f
JOIN raw_offres r USING (id)
ORDER BY f.date_creation DESC NULLS LAST, f.id
"""


def offers_export(con: duckdb.DuckDBPyConnection, filters: Filters) -> pd.DataFrame:
    """Une ligne par offre filtrée, de la plus récente à la plus ancienne."""
    return con.execute(FILTERED_CTE + _EXPORT_SQL, filters.params()).df()


def to_csv(frame: pd.DataFrame) -> bytes:
    """CSV lisible par un Excel français : point-virgule, virgule décimale, BOM UTF-8."""
    return frame.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
