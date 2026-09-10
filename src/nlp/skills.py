"""Extraction des compétences techniques de chaque offre, en deux couches.

Couche 1 — le texte libre : l'intitulé et la description passent au crible du
dictionnaire contrôlé (``data/skills_taxonomy.yaml``).

Couche 2 — les champs déjà structurés par l'API : ``competences`` et
``qualitesProfessionnelles``. Leurs libellés sont normalisés contre le même
dictionnaire, ce qui les rend comparables au reste plutôt que de les empiler
tels quels. Attention : ces deux champs sont rares — sur la collecte du
2026-09-08, 5 offres sur 55 portent ``competences`` et 2 ``qualitesProfessionnelles``.
Le texte libre reste donc la source principale.

Le résultat est écrit dans ``offre_competences``, reconstruite intégralement à
chaque exécution : comme ``raw_offres``, elle est une projection du brut.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import duckdb

from src.nlp.taxonomy import DEFAULT_TAXONOMY_PATH, Taxonomy

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "warehouse.duckdb"
DEFAULT_MODELS_PATH = Path(__file__).with_name("skills.sql")

#: Provenance de chaque ligne. Une même compétence peut être détectée par
#: plusieurs couches ; les lignes coexistent, ce qui permet de mesurer après
#: coup ce que chaque source apporte.
SOURCE_TEXT = "texte"
SOURCE_API_COMPETENCES = "api_competences"
SOURCE_API_QUALITES = "api_qualites"

#: Champs API de la couche 2, avec leur source. Les libellés sont dans
#: ``libelle`` pour l'un comme pour l'autre (vérifié dans data/raw/).
_API_FIELDS = {
    "competences": SOURCE_API_COMPETENCES,
    "qualitesProfessionnelles": SOURCE_API_QUALITES,
}

_CREATE_TABLE = """
CREATE OR REPLACE TABLE offre_competences (
    offre_id   VARCHAR NOT NULL,
    competence VARCHAR NOT NULL,
    famille    VARCHAR NOT NULL,
    source     VARCHAR NOT NULL,
    PRIMARY KEY (offre_id, competence, source)
)
"""

Row = tuple[str, str, str, str]


def extract_from_offer(offer: dict[str, Any], taxonomy: Taxonomy) -> list[Row]:
    """Extraire les compétences d'une offre, couches 1 et 2 confondues.

    Args:
        offer: l'offre telle que l'API l'a renvoyée.
        taxonomy: le dictionnaire contrôlé compilé.

    Returns:
        Des lignes ``(offre_id, competence, famille, source)``, dédoublonnées.
    """
    offer_id = offer.get("id")
    if not offer_id:
        return []

    rows: dict[tuple[str, str], Row] = {}

    def collect(text: str | None, source: str) -> None:
        for skill in taxonomy.find(text):
            rows.setdefault(
                (skill.label, source), (offer_id, skill.label, skill.family, source)
            )

    # L'intitulé et la description sont concaténés : une technologie citée deux
    # fois ne compte de toute façon qu'une, et cela évite un second parcours du
    # dictionnaire.
    collect(f"{offer.get('intitule') or ''}\n{offer.get('description') or ''}", SOURCE_TEXT)

    for field, source in _API_FIELDS.items():
        for item in offer.get(field) or []:
            collect(item.get("libelle"), source)

    return list(rows.values())


def build_offre_competences(
    con: duckdb.DuckDBPyConnection, taxonomy: Taxonomy | None = None
) -> int:
    """Reconstruire ``offre_competences`` à partir de ``raw_offres``.

    Le parcours se fait en Python plutôt qu'en SQL : le dictionnaire vit dans
    un YAML et ses motifs — limites de mot, insensibilité aux accents — ne se
    transposent pas en ``regexp_matches`` sans le réécrire.

    Returns:
        Le nombre de lignes écrites.
    """
    taxonomy = taxonomy or Taxonomy.load()
    con.execute(_CREATE_TABLE)

    offers = con.execute("SELECT offre FROM raw_offres").fetchall()
    rows = [
        row
        for (payload,) in offers
        for row in extract_from_offer(json.loads(payload), taxonomy)
    ]

    if rows:
        con.executemany("INSERT INTO offre_competences VALUES (?, ?, ?, ?)", rows)
    logger.info("%d compétences extraites de %d offres", len(rows), len(offers))
    return len(rows)


def apply_models(
    con: duckdb.DuckDBPyConnection, sql_path: Path = DEFAULT_MODELS_PATH
) -> None:
    """Créer la vue d'agrégation par famille et par mois."""
    con.execute(sql_path.read_text(encoding="utf-8"))
    logger.info("Vue d'agrégation appliquée depuis %s", sql_path)


def build_skills(
    db_path: Path = DEFAULT_DB_PATH,
    taxonomy_path: Path = DEFAULT_TAXONOMY_PATH,
    sql_path: Path = DEFAULT_MODELS_PATH,
) -> int:
    """Construire la table et la vue, et retourner le nombre de lignes écrites."""
    taxonomy = Taxonomy.load(taxonomy_path)
    with duckdb.connect(str(db_path)) as con:
        written = build_offre_competences(con, taxonomy)
        apply_models(con, sql_path)
    return written


def main() -> None:
    """Point d'entrée de ``python -m src.nlp.skills``."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    written = build_skills()
    logger.info("offre_competences prête dans %s (%d lignes)", DEFAULT_DB_PATH, written)


if __name__ == "__main__":
    main()
