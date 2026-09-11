"""Accès à l'entrepôt DuckDB, en lecture seule et mis en cache.

Une connexion est ouverte par requête plutôt que partagée : une connexion
DuckDB ne se partage pas entre les threads de Streamlit, et les résultats sont
de toute façon mis en cache. La date de modification du fichier fait partie de
la clé du cache, si bien qu'un entrepôt reconstruit est relu sans redémarrage.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import streamlit as st

from src.dashboard import queries
from src.dashboard.filtering import Filters
from src.dashboard.filtering import filter_options as _query_options

PROJECT_ROOT = Path(__file__).resolve().parents[2]
#: Variable d'environnement qui permet de pointer vers un autre entrepôt.
DB_PATH_ENV = "RADAR_DB_PATH"
REQUIRED_TABLES = ("offres", "offre_competences")

_BUILD_HINT = (
    "Construisez-le avec `python -m src.warehouse.load` puis `python -m src.nlp.skills`."
)


def db_path() -> Path:
    """Chemin de l'entrepôt : ``RADAR_DB_PATH`` s'il est défini, sinon ``data/``."""
    override = os.getenv(DB_PATH_ENV)
    return Path(override) if override else PROJECT_ROOT / "data" / "warehouse.duckdb"


def _connect(path: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(path), read_only=True)


def warehouse_problem() -> str | None:
    """Expliquer en français pourquoi l'entrepôt est inutilisable, ou ``None``."""
    path = db_path()
    if not path.is_file():
        return f"L'entrepôt `{path.name}` est introuvable. {_BUILD_HINT}"
    try:
        with _connect(path) as con:
            present = {
                row[0]
                for row in con.execute(
                    "SELECT table_name FROM information_schema.tables"
                ).fetchall()
            }
    except duckdb.Error as exc:
        return f"L'entrepôt ne peut pas être ouvert en lecture ({exc})."
    missing = [table for table in REQUIRED_TABLES if table not in present]
    if missing:
        return f"Tables absentes de l'entrepôt : {', '.join(missing)}. {_BUILD_HINT}"
    return None


@st.cache_data(show_spinner=False)
def _load(name: str, filters: Filters, path: str, version: float) -> pd.DataFrame:
    with _connect(Path(path)) as con:
        return queries.QUERIES[name](con, filters)


def load(name: str, filters: Filters) -> pd.DataFrame:
    """Exécuter la requête ``name`` de :data:`queries.QUERIES`, avec cache."""
    path = db_path()
    return _load(name, filters, str(path), path.stat().st_mtime)


@st.cache_data(show_spinner=False)
def _options(path: str, version: float) -> dict[str, Any]:
    with _connect(Path(path)) as con:
        return _query_options(con)


def filter_options() -> dict[str, Any]:
    """Valeurs proposées dans la barre latérale, avec cache."""
    path = db_path()
    return _options(str(path), path.stat().st_mtime)
