"""Modèle, index vectoriel et requêtes de la page « Recherche », mis en cache.

Le modèle et l'index passent par ``st.cache_resource`` : chargés une fois par
processus et partagés entre les sessions, sans copie à chaque interaction. Les
dates de modification des fichiers font partie de la clé de l'index, si bien
qu'un index recalculé est relu sans redémarrage.
"""

from __future__ import annotations

import duckdb
import pandas as pd
import streamlit as st

from src.dashboard import data
from src.dashboard.filtering import FILTERED_CTE, Filters
from src.nlp import embeddings
from src.nlp.model import Encoder, load_model
from src.nlp.search import DEFAULT_IDS_PATH, DEFAULT_VECTORS_PATH, VectorIndex, load_index, top_k

RESULT_COLUMNS = [
    "id", "score", "intitule", "entreprise", "lieu", "type_contrat", "est_alternance", "url",
]

_DETAILS_SQL = """
SELECT
    o.id, o.intitule, o.entreprise,
    r.offre->>'$.lieuTravail.libelle'      AS lieu,
    o.type_contrat, o.est_alternance,
    r.offre->>'$.origineOffre.urlOrigine'  AS url
FROM offres o
JOIN raw_offres r USING (id)
WHERE list_contains($ids::VARCHAR[], o.id)
"""


def index_problem() -> str | None:
    """Expliquer en français pourquoi l'index est inutilisable, ou ``None``."""
    missing = [p.name for p in (DEFAULT_VECTORS_PATH, DEFAULT_IDS_PATH) if not p.is_file()]
    if missing:
        return (f"L'index de recherche est introuvable ({', '.join(missing)}). "
                "Construisez-le avec `python -m src.nlp.embeddings`.")
    return None


@st.cache_resource(show_spinner="Chargement du modèle de langue…")
def model() -> Encoder:
    """Le modèle sentence-transformers, chargé une seule fois par processus."""
    return load_model()


@st.cache_resource(show_spinner=False, max_entries=1)
def _index(vectors_version: float, ids_version: float) -> VectorIndex:
    return load_index()


def index() -> VectorIndex:
    """L'index vectoriel, relu seulement quand ses fichiers changent."""
    return _index(DEFAULT_VECTORS_PATH.stat().st_mtime, DEFAULT_IDS_PATH.stat().st_mtime)


@st.cache_data(show_spinner=False)
def _filtered_ids(filters: Filters, path: str, version: float) -> list[str]:
    with duckdb.connect(path, read_only=True) as con:
        rows = con.execute(FILTERED_CTE + "SELECT id FROM filtrees", filters.params())
        return [row[0] for row in rows.fetchall()]


def filtered_ids(filters: Filters) -> list[str]:
    """Les ids des offres retenues par les filtres de la barre latérale."""
    path = data.db_path()
    return _filtered_ids(filters, str(path), path.stat().st_mtime)


def unindexed_count(filters: Filters) -> int:
    """Nombre d'offres filtrées absentes de l'index (entrepôt plus récent que lui)."""
    return len(set(filtered_ids(filters)) - set(index().ids))


def search(text: str, filters: Filters, k: int = 10) -> pd.DataFrame:
    """Les ``k`` offres filtrées les plus proches de ``text``, score décroissant."""
    query = embeddings.embed_texts([text], model())[0]
    hits = top_k(index(), query, k, allowed=filtered_ids(filters))
    if not hits:
        return pd.DataFrame(columns=RESULT_COLUMNS)
    scores = pd.DataFrame(hits, columns=["id", "score"])
    with duckdb.connect(str(data.db_path()), read_only=True) as con:
        details = con.execute(_DETAILS_SQL, {"ids": scores["id"].tolist()}).df()
    # Une jointure interne garde l'ordre de la table de gauche : celui des scores.
    return scores.merge(details, on="id", how="inner")[RESULT_COLUMNS]
