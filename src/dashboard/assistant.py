"""Contexte RAG de la page « Assistant » : récupération puis comptage SQL.

Deux étapes, dans cet ordre. L'index vectoriel de la page « Recherche » ramène
les offres les plus proches de la question ; DuckDB compte ensuite ce que
contient ce sous-ensemble. Le modèle de langue ne reçoit donc que des chiffres
calculés, ce qui lui retire l'occasion d'en inventer.

Les deux appels passent par ``st.cache_data`` : Streamlit rejoue le script à
chaque interaction, et sans cache la même question serait facturée plusieurs
fois.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb
import streamlit as st

from src.dashboard import data, semantic
from src.dashboard.filtering import FILTERED_CTE, UNKNOWN_CONTRACT, UNKNOWN_REGION, Filters
from src.nlp import embeddings, llm, rag
from src.nlp.search import top_k

#: Nombre d'offres retenues par la recherche vectorielle et montrées au modèle.
TOP_K = 20
TOP_SKILLS = 10
TOP_BREAKDOWN = 5

# Le sous-ensemble se découpe dans ``filtrees`` : les filtres de la barre
# latérale s'appliquent donc aussi aux statistiques, pas seulement aux offres.
_SUBSET_CTE = """
, sous_ensemble AS (
    SELECT * FROM filtrees WHERE list_contains($ids::VARCHAR[], id)
)
"""

_STATS_SQL = """
SELECT
    count(*)                               AS offres,
    (SELECT count(*) FROM filtrees)        AS offres_filtrees,
    count(*) FILTER (WHERE est_alternance) AS alternances,
    count(salaire_offre)                   AS offres_avec_salaire,
    median(salaire_offre)                  AS salaire_median,
    min(date_creation)::DATE               AS debut,
    max(date_creation)::DATE               AS fin
FROM sous_ensemble
"""

# Le nom de colonne est une constante du module, jamais une saisie : les
# valeurs, elles, restent des paramètres nommés.
_BREAKDOWN_SQL = """
SELECT coalesce({column}, '{unknown}') AS valeur, count(*) AS offres
FROM sous_ensemble
GROUP BY 1
ORDER BY offres DESC, 1
LIMIT {limit}
"""

_SKILLS_SQL = f"""
SELECT competence, count(DISTINCT offre_id) AS offres
FROM competences_filtrees
WHERE list_contains($ids::VARCHAR[], offre_id)
GROUP BY 1
ORDER BY offres DESC, competence
LIMIT {TOP_SKILLS}
"""

# Le libellé du lieu (« 69 - Lyon 3e ») n'existe que dans le brut, comme pour
# les embeddings : la vue n'en garde que la région.
_OFFERS_SQL = """
SELECT
    s.id, s.intitule, s.entreprise,
    r.offre->>'$.lieuTravail.libelle' AS lieu,
    s.type_contrat, s.est_alternance,
    s.salaire_min_annuel, s.salaire_max_annuel,
    s.date_creation::DATE AS date_creation,
    s.description
FROM sous_ensemble s
JOIN raw_offres r USING (id)
"""


@dataclass(frozen=True)
class Reply:
    """Réponse affichée, avec le contexte qui l'a produite."""

    context: rag.Context
    text: str
    #: Message français si l'appel au fournisseur a échoué ; le texte est alors
    #: le récapitulatif statistique.
    warning: str | None = None


def index_problem() -> str | None:
    """Expliquer en français pourquoi l'index est inutilisable, ou ``None``."""
    return semantic.index_problem()


def _retrieve(question: str, filters: Filters) -> list[str]:
    """Les ids des offres filtrées les plus proches de ``question``."""
    query = embeddings.embed_texts([question], semantic.model())[0]
    hits = top_k(semantic.index(), query, TOP_K, allowed=semantic.filtered_ids(filters))
    return [offer_id for offer_id, _ in hits]


def _pairs(
    con: duckdb.DuckDBPyConnection, body: str, params: dict[str, object]
) -> tuple[tuple[str, int], ...]:
    rows = con.execute(FILTERED_CTE + _SUBSET_CTE + body, params).fetchall()
    return tuple((str(name), int(count)) for name, count in rows)


def _stats(con: duckdb.DuckDBPyConnection, params: dict[str, object]) -> rag.Stats:
    """Compter le sous-ensemble : volumes, salaire médian, période, répartitions."""
    row = con.execute(FILTERED_CTE + _SUBSET_CTE + _STATS_SQL, params).fetchone()
    offers, filtered, apprenticeships, with_salary, median, first_day, last_day = row
    return rag.Stats(
        offers=int(offers),
        filtered_offers=int(filtered),
        apprenticeships=int(apprenticeships),
        with_salary=int(with_salary),
        median_salary=None if median is None else float(median),
        first_day=first_day,
        last_day=last_day,
        regions=_pairs(con, _BREAKDOWN_SQL.format(
            column="region", unknown=UNKNOWN_REGION, limit=TOP_BREAKDOWN), params),
        contracts=_pairs(con, _BREAKDOWN_SQL.format(
            column="type_contrat", unknown=UNKNOWN_CONTRACT, limit=TOP_BREAKDOWN), params),
        skills=_pairs(con, _SKILLS_SQL, params),
    )


def _offers(
    con: duckdb.DuckDBPyConnection, params: dict[str, object], ids: list[str]
) -> tuple[rag.Offer, ...]:
    """Les offres du sous-ensemble, remises dans l'ordre de pertinence."""
    rows = con.execute(FILTERED_CTE + _SUBSET_CTE + _OFFERS_SQL, params).fetchall()
    by_id = {
        row[0]: rag.Offer(
            id=row[0],
            title=row[1],
            company=row[2],
            place=row[3],
            contract=row[4],
            apprenticeship=bool(row[5]),
            salary_min=None if row[6] is None else float(row[6]),
            salary_max=None if row[7] is None else float(row[7]),
            created=row[8] if isinstance(row[8], date) else None,
            description=row[9],
        )
        for row in rows
    }
    return tuple(by_id[offer_id] for offer_id in ids if offer_id in by_id)


def build_context(
    con: duckdb.DuckDBPyConnection, question: str, filters: Filters, ids: list[str]
) -> rag.Context:
    """Rassembler statistiques et offres pour ``ids``, sans Streamlit ni cache."""
    params = {**filters.params(), "ids": ids}
    return rag.Context(
        question=question, stats=_stats(con, params), offers=_offers(con, params, ids)
    )


@st.cache_data(show_spinner="Recherche des offres pertinentes…")
def _context(question: str, filters: Filters, path: str, version: float) -> rag.Context:
    ids = _retrieve(question, filters)
    with duckdb.connect(path, read_only=True) as con:
        return build_context(con, question, filters, ids)


def context(question: str, filters: Filters) -> rag.Context:
    """Le contexte RAG de ``question``, recalculé quand l'entrepôt change."""
    path = data.db_path()
    return _context(question, filters, str(path), path.stat().st_mtime)


@st.cache_data(show_spinner="Rédaction de la réponse…")
def _answer(question: str, filters: Filters, _context: rag.Context) -> str:
    # ``_context`` est ignoré par la clé du cache — il découle déjà de la
    # question et des filtres —, ce qui évite d'avoir à le rendre hachable.
    return llm.answer(_context)


def reply(question: str, filters: Filters) -> Reply:
    """Répondre à ``question``, en retombant sur les statistiques si l'appel échoue."""
    found = context(question, filters)
    try:
        return Reply(found, _answer(question, filters, found))
    except llm.LLMError as exc:
        return Reply(found, rag.mock_answer(found), str(exc))
