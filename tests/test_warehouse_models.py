"""Unit tests for the transformations in ``models.sql``.

The offers are hand-written but they go through the shipped ``models.sql``
unchanged, so these tests exercise the real view rather than a copy of its
expressions. Synthetic data is unavoidable here: the salary labels actually
present in ``data/raw/`` cover neither hourly rates nor a monthly amount without
an explicit number of months.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import duckdb
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.warehouse.load import apply_models  # noqa: E402


def synthetic_warehouse(offers: list[dict[str, Any]]) -> duckdb.DuckDBPyConnection:
    """Build an in-memory warehouse over hand-written offers."""
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE raw_offres (id VARCHAR PRIMARY KEY, offre JSON NOT NULL, "
        "source_file VARCHAR, ingested_at TIMESTAMP)"
    )
    con.executemany(
        "INSERT INTO raw_offres VALUES (?, ?, 'synthetique', now())",
        [(offer["id"], json.dumps(offer, ensure_ascii=False)) for offer in offers],
    )
    apply_models(con)
    return con


# --------------------------------------------------------- parser de salaire


@pytest.mark.parametrize(
    ("libelle", "attendu"),
    [
        ("Annuel de 35000.0 Euros à 45000.0 Euros", (35000.0, 45000.0)),
        ("Annuel de 21000.0 Euros", (21000.0, 21000.0)),
        # Suffixe parasite relevé tel quel dans data/raw/.
        ("Annuel de 10000.0 Euros à 15000.0 Euros - -", (10000.0, 15000.0)),
        # L'espace sépare les milliers.
        ("Annuel de 35 000.00 Euros", (35000.0, 35000.0)),
        ("Mensuel de 3000.0 Euros", (36000.0, 36000.0)),
        ("Mensuel de 2000.0 Euros sur 13.0 mois", (26000.0, 26000.0)),
        ("Mensuel de 506.0 Euros à 600.0 Euros sur 12 mois", (6072.0, 7200.0)),
        # Sans mention d'horaire, la base légale de 35h par semaine s'applique.
        ("Horaire de 11.88 Euros", (21621.6, 21621.6)),
        # La virgule est décimale.
        ("Horaire de 11,65 Euros à 13.00 Euros", (21203.0, 23660.0)),
        ("Horaire de 12.0 Euros sur 39.0 heures", (24336.0, 24336.0)),
        # Sans période de référence, rien à annualiser.
        ("Cachet de 500.0 Euros", (None, None)),
        ("Autre", (None, None)),
        (None, (None, None)),
    ],
)
def test_annualisation_du_salaire(
    libelle: str | None, attendu: tuple[float | None, float | None]
) -> None:
    offre: dict[str, Any] = {"id": "TEST1", "intitule": "Poste de test"}
    if libelle is not None:
        offre["salaire"] = {"libelle": libelle}

    # Le parser se vérifie sur le brut : plusieurs montants ci-dessus sont sous
    # le SMIC exprès, et seraient écartés des colonnes filtrées.
    with synthetic_warehouse([offre]) as con:
        obtenu = con.execute(
            "SELECT salaire_min_brut, salaire_max_brut FROM offres"
        ).fetchone()

    assert obtenu == pytest.approx(attendu)


@pytest.mark.parametrize(
    ("libelle", "alternance", "attendu"),
    [
        ("Annuel de 45000.0 Euros", False, (45000.0, 45000.0, False)),
        # Annuel saisi en mensuel : 32 000 x 12 dépasse le plafond.
        ("Mensuel de 32000.0 Euros", False, (None, None, True)),
        ("Horaire de 70000.0 Euros", False, (None, None, True)),
        ("Annuel de 40.0 Euros à 50.0 Euros", False, (None, None, True)),
        # Sous le SMIC mais au-dessus du plancher apprenti : légal en alternance.
        ("Mensuel de 1000.0 Euros", True, (12000.0, 12000.0, False)),
        ("Mensuel de 1000.0 Euros", False, (None, None, True)),
        # Sans salaire, rien à écarter.
        (None, False, (None, None, False)),
    ],
)
def test_salaire_hors_bornes_ecarte(
    libelle: str | None, alternance: bool, attendu: tuple[Any, Any, bool]
) -> None:
    offre: dict[str, Any] = {"id": "TEST1", "alternance": alternance}
    if libelle is not None:
        offre["salaire"] = {"libelle": libelle}

    with synthetic_warehouse([offre]) as con:
        obtenu = con.execute(
            "SELECT salaire_min_annuel, salaire_max_annuel, salaire_hors_bornes FROM offres"
        ).fetchone()

    assert obtenu == attendu


# ---------------------------------------------------- localisation et région


@pytest.mark.parametrize(
    ("lieu", "departement", "region"),
    [
        ({"libelle": "75 - Paris"}, "75", "Île-de-France"),
        ({"libelle": "69 - Lyon"}, "69", "Auvergne-Rhône-Alpes"),
        ({"libelle": "974 - LA POSSESSION"}, "974", "La Réunion"),
        ({"libelle": "2A - Ajaccio"}, "2A", "Corse"),
        # Cas réel : collectivité d'outre-mer à trois chiffres.
        ({"libelle": "988 - Nouméa", "commune": "98818", "codePostal": "98800"},
         "988", "Nouvelle-Calédonie"),
        # Cas réel : « 99999 » veut dire « lieu non précisé », pas département 99.
        ({"libelle": "France", "codePostal": "99999"}, None, None),
        # Le code INSEE prend le relais quand le libellé n'a pas de préfixe.
        ({"libelle": "Meylan", "commune": "38229"}, "38", "Auvergne-Rhône-Alpes"),
        # Puis le code postal.
        ({"libelle": "Nantes", "codePostal": "44000"}, "44", "Pays de la Loire"),
        # Cas réel : une région seule, sans commune ni code postal.
        ({"libelle": "Île-de-France"}, None, "Île-de-France"),
        ({}, None, None),
    ],
)
def test_departement_et_region(
    lieu: dict[str, str], departement: str | None, region: str | None
) -> None:
    offre = {"id": "TEST1", "intitule": "Poste de test", "lieuTravail": lieu}

    with synthetic_warehouse([offre]) as con:
        assert con.execute("SELECT departement, region FROM offres").fetchone() == (
            departement,
            region,
        )


def test_un_code_insee_ne_se_lit_pas_comme_un_departement_doutre_mer() -> None:
    """« 91272 » est en Essonne, pas dans un DOM : la branche 97x doit être bornée."""
    offre = {"id": "TEST1", "lieuTravail": {"libelle": "Gometz", "commune": "91272"}}

    with synthetic_warehouse([offre]) as con:
        assert con.execute("SELECT departement FROM offres").fetchone() == ("91",)


# ------------------------------------------------------------ autres colonnes


def test_est_alternance_suit_la_nature_du_contrat() -> None:
    offres = [
        {"id": "A", "alternance": True, "natureContrat": "Contrat travail"},
        {"id": "B", "alternance": False, "natureContrat": "Contrat apprentissage"},
        {"id": "C", "alternance": False, "natureContrat": "Cont. professionnalisation"},
        {"id": "D", "alternance": False, "natureContrat": "Contrat travail"},
    ]

    with synthetic_warehouse(offres) as con:
        resultat = dict(
            con.execute("SELECT id, est_alternance FROM offres ORDER BY id").fetchall()
        )

    assert resultat == {"A": True, "B": True, "C": True, "D": False}


def test_les_champs_imbriques_sont_remontes() -> None:
    offre = {
        "id": "TEST1",
        "intitule": "Data Engineer (H/F)",
        "entreprise": {"nom": "ACME"},
        "typeContrat": "CDI",
        "dateCreation": "2026-08-25T13:18:16.053Z",
        "romeCode": "M1811",
        "experienceLibelle": "Débutant accepté",
        "description": "Une description.",
    }

    with synthetic_warehouse([offre]) as con:
        ligne = con.execute(
            "SELECT intitule, entreprise, type_contrat, code_rome, experience, "
            "description, date_creation FROM offres"
        ).fetchone()

    assert ligne[:6] == (
        "Data Engineer (H/F)",
        "ACME",
        "CDI",
        "M1811",
        "Débutant accepté",
        "Une description.",
    )
    assert ligne[6].year == 2026


def test_une_entreprise_anonyme_ne_casse_pas_la_vue() -> None:
    """Près de la moitié des offres réelles n'ont pas de nom d'entreprise."""
    with synthetic_warehouse([{"id": "TEST1", "entreprise": {}}]) as con:
        assert con.execute("SELECT entreprise FROM offres").fetchone() == (None,)
