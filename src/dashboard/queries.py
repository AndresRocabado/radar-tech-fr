"""Registre des requêtes du dashboard, appelées par leur nom.

Les requêtes elles-mêmes vivent dans un module par page
(:mod:`src.dashboard.queries_market`, :mod:`src.dashboard.queries_nocode`) :
ce sont des fonctions pures ``(connexion, filtres) -> DataFrame``, sans
Streamlit, qui se testent sur un entrepôt synthétique. Le cache vit dans
:mod:`src.dashboard.data`.
"""

from __future__ import annotations

from collections.abc import Callable

import duckdb
import pandas as pd

from src.dashboard import queries_market as market
from src.dashboard import queries_nocode as nocode
from src.dashboard.export import offers_export
from src.dashboard.filtering import Filters

Query = Callable[[duckdb.DuckDBPyConnection, Filters], pd.DataFrame]

QUERIES: dict[str, Query] = {
    "kpis": market.kpis,
    "weekly_offers": market.weekly_offers,
    "top_skills": market.top_skills,
    "by_contract": market.by_contract,
    "by_region": market.by_region,
    "nocode_share": nocode.nocode_share,
    "nocode_monthly": nocode.nocode_monthly,
    "salary_by_ai": nocode.salary_by_ai,
    "top_tools_by_family": nocode.top_tools_by_family,
    "offers_export": offers_export,
}
