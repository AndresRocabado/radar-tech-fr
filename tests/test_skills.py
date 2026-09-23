"""Tests du dictionnaire contrôlé et de l'extraction des compétences.

Le dictionnaire livré est chargé tel quel : ce sont ses motifs réels qui sont
éprouvés, pas une taxonomie de test qui ne prouverait rien sur la production.
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

from src.nlp import skills, taxonomy as taxonomy_module  # noqa: E402
from src.nlp.nocode import GENERIC_MARKER, GENERIC_TERM, NOCODE_FAMILY  # noqa: E402
from src.nlp.report import nocode_share, top_skills  # noqa: E402
from src.nlp.taxonomy import Taxonomy  # noqa: E402
from src.warehouse.load import apply_models as apply_warehouse_models  # noqa: E402


@pytest.fixture(scope="module")
def taxo() -> Taxonomy:
    return Taxonomy.load()


def labels(taxo: Taxonomy, text: str) -> set[str]:
    return {skill.label for skill in taxo.find(text)}


# ------------------------------------------------------ intégrité du fichier


def test_les_sept_familles_sont_presentes(taxo: Taxonomy) -> None:
    assert taxo.families == [
        "langages",
        "cloud",
        "data_engineering",
        "bi_viz",
        "nocode_lowcode",
        "ia_ml",
        "devops",
    ]


def test_le_dictionnaire_couvre_environ_cent_vingt_technologies(taxo: Taxonomy) -> None:
    assert 110 <= len(taxo.skills) <= 140


def test_un_label_en_double_est_refuse(tmp_path: Path) -> None:
    """Le label est la clé d'agrégation : un doublon éclaterait les comptages."""
    fichier = tmp_path / "doublon.yaml"
    fichier.write_text(
        "familles:\n  langages: [Python]\n  ia_ml: [Python]\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Python"):
        Taxonomy.load(fichier)


def test_les_constantes_nocode_collent_au_dictionnaire(taxo: Taxonomy) -> None:
    """``src/nlp/nocode.py`` doit décrire le YAML tel qu'il est vraiment.

    Ces deux chaînes voyagent jusqu'à un ``LIKE`` SQL dans le rapport et dans
    le dashboard. Un ``LIKE`` qui ne correspond plus ne lève pas : il compte
    zéro. Sans ce test, renommer la famille ou le suffixe « (terme générique) »
    dans le dictionnaire viderait silencieusement la page « No-code & IA ».
    """
    assert NOCODE_FAMILY in taxo.families

    generiques = [
        skill.label
        for skill in taxo.skills
        if skill.family == NOCODE_FAMILY and GENERIC_MARKER in skill.label
    ]
    assert generiques, (
        f"aucun label de la famille {NOCODE_FAMILY} ne porte « {GENERIC_MARKER} » : "
        "les requêtes qui séparent outils nommés et termes génériques comptent zéro"
    )
    # Le motif LIKE doit retrouver exactement ces labels-là.
    assert GENERIC_TERM == f"%{GENERIC_MARKER}%"


def test_les_quinze_outils_nocode_demandes_sont_couverts(taxo: Taxonomy) -> None:
    attendus = [
        ("Power Apps", "Nous cherchons un profil Power Apps."),
        ("Power Automate", "Automatisation via Power Automate."),
        ("Power Platform", "Expérience Power Platform exigée."),
        ("n8n", "Orchestration avec n8n."),
        ("Make (Integromat)", "Scénarios integromat à reprendre."),
        ("Zapier", "Connecteurs Zapier."),
        ("Bubble", "Application développée sous Bubble."),
        ("Airtable", "Base Airtable à structurer."),
        ("Retool", "Back-office Retool."),
        ("Appian", "Processus Appian."),
        ("Mendix", "Développement Mendix."),
        ("OutSystems", "Plateforme OutSystems."),
        ("Notion", "Documentation dans Notion."),
        ("Webflow", "Site Webflow."),
    ]
    for label, phrase in attendus:
        trouves = taxo.find(phrase)
        assert [s.label for s in trouves] == [label], phrase
        assert trouves[0].family == "nocode_lowcode"


# ------------------------------------------------------------- le matching


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [
        # L'alias demandé explicitement : une seule écriture dans le YAML.
        ("Maîtrise de Power BI", "Power BI"),
        ("Maîtrise de PowerBI", "Power BI"),
        ("Maîtrise de power-bi", "Power BI"),
        ("MAITRISE DE POWER BI", "Power BI"),
        # Accents et casse indifférents des deux côtés.
        ("Notions de Machine Learning", "Machine Learning"),
        ("apprentissage automatique", "Machine Learning"),
        ("Traitement du langage naturel", "NLP"),
        # Les caractères non alphanumériques du nom sont préservés.
        ("Développement C++ embarqué", "C++"),
        ("Stack .NET", ".NET"),
        ("no code", "No-code (terme générique)"),
        ("nocode", "No-code (terme générique)"),
    ],
)
def test_alias_accents_et_separateurs(taxo: Taxonomy, texte: str, attendu: str) -> None:
    assert attendu in labels(taxo, texte)


@pytest.mark.parametrize(
    ("texte", "absent"),
    [
        # Limites de mot : le nom ne doit pas se lire au milieu d'un autre mot.
        ("Le poste est en Javascriptique", "JavaScript"),
        ("Rythme de croisière", "R (langage)"),
        ("Nous avons un budget R&D important", "R (langage)"),
        # « notion » est un mot français courant, d'où le matching sensible à
        # la casse sur cette entrée.
        ("Avoir une notion de gestion de projet", "Notion"),
        # « Go » seul est trop ambigu : seuls « Golang » et « langage Go »
        # déclenchent la détection.
        ("Le feu est au vert, go !", "Go (Golang)"),
        # « C » ne doit pas mordre sur le « C » de « C# ».
        ("Développement C# .NET", "C (langage)"),
        # ASP.NET est bien .NET, mais via son propre alias, pas par troncature.
        ("Migration ASP.NET", "C#"),
    ],
)
def test_pas_de_faux_positif(taxo: Taxonomy, texte: str, absent: str) -> None:
    assert absent not in labels(taxo, texte)


def test_les_variantes_capitalisees_restent_detectees(taxo: Taxonomy) -> None:
    """La sensibilité à la casse ne doit pas rendre l'outil introuvable."""
    assert "Notion" in labels(taxo, "Documentation technique tenue dans Notion.")
    assert "Go (Golang)" in labels(taxo, "Microservices en Golang.")


def test_make_ne_se_cherche_que_capitalise(taxo: Taxonomy) -> None:
    """Cas réel : « (Make, n8n, Power Automate...) » dans l'offre 5726965."""
    trouves = labels(taxo, "outils d'automatisation (Make, n8n, Power Automate...)")
    assert {"Make (Integromat)", "n8n", "Power Automate"} <= trouves
    # L'anglais courant en minuscules ne doit rien déclencher.
    assert "Make (Integromat)" not in labels(taxo, "You have to make it work.")
    # ... et l'alias insensible à la casse reste, lui, insensible.
    assert "Make (Integromat)" in labels(taxo, "reprise des scénarios integromat")


# ------------------------------------------------- extraction d'une offre


def test_les_deux_couches_alimentent_la_meme_offre(taxo: Taxonomy) -> None:
    """Texte libre et champs API remontent avec des sources distinctes."""
    offre = {
        "id": "A1",
        "intitule": "Data Analyst Power BI (H/F)",
        "description": "Automatisation des flux avec Power Automate et n8n.",
        # Libellé relevé tel quel dans data/raw/.
        "competences": [
            {
                "code": "113255",
                "libelle": "Utilisation d'outils Business Intelligence (BI) - "
                "Informatique décisionnelle",
                "exigence": "S",
            }
        ],
        "qualitesProfessionnelles": [{"libelle": "Faire preuve d'autonomie"}],
    }

    lignes = skills.extract_from_offer(offre, taxo)

    par_source: dict[str, set[str]] = {}
    for _, competence, _, source in lignes:
        par_source.setdefault(source, set()).add(competence)

    assert par_source[skills.SOURCE_TEXT] == {"Power BI", "Power Automate", "n8n"}
    assert par_source[skills.SOURCE_API_COMPETENCES] == {"Business Intelligence"}
    # Les qualités professionnelles sont des savoir-être : rien à normaliser
    # contre un dictionnaire technique, et donc aucune ligne.
    assert skills.SOURCE_API_QUALITES not in par_source
    assert all(ligne[0] == "A1" for ligne in lignes)


def test_une_offre_sans_identifiant_est_ignoree(taxo: Taxonomy) -> None:
    assert skills.extract_from_offer({"description": "Python"}, taxo) == []


def test_une_offre_sans_texte_ne_casse_pas(taxo: Taxonomy) -> None:
    assert skills.extract_from_offer({"id": "A1", "description": None}, taxo) == []


# --------------------------------------------------- table, vue et rapport


@pytest.fixture
def entrepot() -> duckdb.DuckDBPyConnection:
    """Un entrepôt en mémoire, monté sur des offres écrites à la main."""
    offres: list[dict[str, Any]] = [
        {
            "id": "A",
            "intitule": "Data Engineer",
            "description": "Python, Spark et Airflow sur AWS.",
            "dateCreation": "2026-07-14T10:00:00.000Z",
        },
        {
            "id": "B",
            "intitule": "Chargé d'automatisation",
            "description": "Power Automate, Power Apps et Python.",
            "dateCreation": "2026-08-02T10:00:00.000Z",
        },
        {
            "id": "C",
            "intitule": "Assistant administratif",
            "description": "Accueil téléphonique et classement.",
            "dateCreation": "2026-08-20T10:00:00.000Z",
        },
    ]

    con = duckdb.connect()
    con.execute(
        "CREATE TABLE raw_offres (id VARCHAR PRIMARY KEY, offre JSON NOT NULL, "
        "source_file VARCHAR, ingested_at TIMESTAMP)"
    )
    con.executemany(
        "INSERT INTO raw_offres VALUES (?, ?, 'synthetique', now())",
        [(o["id"], json.dumps(o, ensure_ascii=False)) for o in offres],
    )
    apply_warehouse_models(con)
    skills.build_offre_competences(con)
    skills.apply_models(con)
    return con


def test_la_table_porte_les_quatre_colonnes(entrepot: duckdb.DuckDBPyConnection) -> None:
    with entrepot as con:
        lignes = con.execute(
            "SELECT offre_id, competence, famille, source FROM offre_competences "
            "WHERE offre_id = 'B' ORDER BY competence"
        ).fetchall()

    assert lignes == [
        ("B", "Power Apps", "nocode_lowcode", "texte"),
        ("B", "Power Automate", "nocode_lowcode", "texte"),
        ("B", "Python", "langages", "texte"),
    ]


def test_la_vue_agrege_par_famille_et_par_mois(
    entrepot: duckdb.DuckDBPyConnection,
) -> None:
    with entrepot as con:
        aout = con.execute(
            "SELECT famille, offres_citantes, offres_publiees, part_offres_pct "
            "FROM agg_competences_famille_mois "
            "WHERE mois = DATE '2026-08-01' ORDER BY famille"
        ).fetchall()

    # Deux offres publiées en août, dont une seule cite du no-code : le
    # dénominateur est bien l'ensemble des offres du mois, pas les seules
    # offres reconnues par le dictionnaire.
    assert aout == [
        ("langages", 1, 2, 50.0),
        ("nocode_lowcode", 1, 2, 50.0),
    ]


def test_le_rapport_compte_en_offres_distinctes(
    entrepot: duckdb.DuckDBPyConnection,
) -> None:
    with entrepot as con:
        classement = dict((c, offres) for c, _, offres, _ in top_skills(con, limit=30))
        total, outil, famille = nocode_share(con)

    assert classement["Python"] == 2
    assert (total, outil, famille) == (3, 1, 1)


def test_la_table_est_reconstruite_a_chaque_execution(
    entrepot: duckdb.DuckDBPyConnection,
) -> None:
    """Deux exécutions de suite ne doivent pas dupliquer les lignes."""
    with entrepot as con:
        avant = con.execute("SELECT count(*) FROM offre_competences").fetchone()[0]
        skills.build_offre_competences(con)
        apres = con.execute("SELECT count(*) FROM offre_competences").fetchone()[0]

    assert avant == apres
