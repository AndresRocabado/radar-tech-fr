"""Entrepôt synthétique pour les tests du dashboard.

Les offres passent par le ``models.sql`` livré et la vraie extraction des
compétences : requêtes et pages tournent sur les mêmes vues et la même table
qu'en production.
"""

from __future__ import annotations

import json
from typing import Any

import duckdb

from src.nlp.skills import build_offre_competences
from src.warehouse.load import apply_models


def offer(
    offer_id: str,
    created: str,
    place: str,
    text: str,
    salary: str | None = None,
    company: str | None = None,
    experience: str = "D",
) -> dict[str, Any]:
    """A minimal offer, shaped like the ones in ``data/raw/``."""
    result: dict[str, Any] = {
        "id": offer_id,
        "intitule": "Alternance data",
        "description": text,
        "dateCreation": created,
        "typeContrat": "CDD",
        "natureContrat": "Contrat apprentissage",
        "lieuTravail": {"libelle": place},
        "entreprise": {"nom": company} if company else {},
        "experienceExige": experience,
        "origineOffre": {"urlOrigine": f"https://candidat.francetravail.fr/offres/{offer_id}"},
    }
    if salary:
        result["salaire"] = {"libelle": salary}
    return result


OFFERS = [
    offer("A", "2026-06-01T10:00:00Z", "75 - Paris", "Python et Power Automate",
          "Annuel de 20000.0 Euros", "ACME"),
    offer("B", "2026-06-02T10:00:00Z", "75 - Paris", "Machine Learning avec Python",
          "Annuel de 30000.0 Euros", "ACME"),
    # Deux semaines sans offre séparent B de C.
    offer("C", "2026-06-24T10:00:00Z", "69 - Lyon", "Une démarche no-code", None, "Globex"),
    offer("D", "2026-08-10T10:00:00Z", "Bretagne", "Excel", None, None, experience="E"),
]


def make_warehouse(con: duckdb.DuckDBPyConnection) -> None:
    """Load :data:`OFFERS` into ``raw_offres``, then build views and skills."""
    con.execute(
        "CREATE TABLE raw_offres (id VARCHAR PRIMARY KEY, offre JSON NOT NULL, "
        "source_file VARCHAR, ingested_at TIMESTAMP)"
    )
    con.executemany(
        "INSERT INTO raw_offres VALUES (?, ?, 'synthetique', now())",
        [(o["id"], json.dumps(o, ensure_ascii=False)) for o in OFFERS],
    )
    apply_models(con)
    build_offre_competences(con)
