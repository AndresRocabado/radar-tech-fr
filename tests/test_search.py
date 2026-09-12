"""Tests de l'index vectoriel et du calcul des embeddings.

Le vrai modèle n'est jamais chargé : un encodeur factice et déterministe le
remplace. Ce qui est éprouvé ici, c'est la mécanique — découpage, moyenne des
tranches, alignement des ids, classement — pas la qualité sémantique du modèle.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.nlp import embeddings  # noqa: E402
from src.nlp.search import VectorIndex, load_index, normalize, save_index, top_k  # noqa: E402
from src.warehouse.load import apply_models  # noqa: E402

VOCAB = ("python", "cloud", "lyon", "excel")


class FakeTokenizer:
    """Un token par mot, avec ses positions, comme un tokenizer rapide."""

    def __call__(self, text: str, **kwargs: Any) -> dict[str, list[tuple[int, int]]]:
        return {"offset_mapping": [m.span() for m in re.finditer(r"\S+", text)]}

    def num_special_tokens_to_add(self) -> int:
        return 2


class FakeEncoder:
    """Encode un texte en comptant les mots de :data:`VOCAB` qu'il contient.

    Avec ``max_seq_length=6`` et deux tokens spéciaux, une tranche fait 4 mots.
    """

    def __init__(self) -> None:
        self.tokenizer = FakeTokenizer()
        self.max_seq_length = 6
        self.encoded: list[str] = []

    def get_sentence_embedding_dimension(self) -> int:
        return len(VOCAB)

    def encode(self, sentences: list[str], **kwargs: Any) -> np.ndarray:
        self.encoded.extend(sentences)
        words = [re.findall(r"\w+", s.lower()) for s in sentences]
        vectors = np.array([[w.count(v) for v in VOCAB] for w in words], dtype=np.float32)
        return normalize(vectors) if kwargs.get("normalize_embeddings") else vectors


# ------------------------------------------------------------- découpage


def test_un_texte_court_reste_entier() -> None:
    assert embeddings.chunk_text("python et cloud", FakeTokenizer(), 4) == ["python et cloud"]


def test_un_texte_long_est_decoupe_sans_perte() -> None:
    text = "un deux trois quatre cinq six sept huit neuf dix"
    chunks = embeddings.chunk_text(text, FakeTokenizer(), 4)
    assert chunks == ["un deux trois quatre", "cinq six sept huit", "neuf dix"]
    assert " ".join(chunks) == text


# ------------------------------------------------------------ embeddings


def test_un_vecteur_norme_par_texte() -> None:
    vectors = embeddings.embed_texts(["python", "cloud cloud", "excel " * 20], FakeEncoder())
    assert vectors.shape == (3, len(VOCAB))
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)


def test_la_fin_d_une_longue_description_compte_autant_que_le_debut() -> None:
    model = FakeEncoder()
    vector = embeddings.embed_texts(["python python python python cloud cloud cloud cloud"],
                                    model)[0]
    assert model.encoded == ["python python python python", "cloud cloud cloud cloud"]
    assert np.allclose(vector, [np.sqrt(0.5), np.sqrt(0.5), 0.0, 0.0])


def test_aucun_texte_donne_une_matrice_vide() -> None:
    assert embeddings.embed_texts([], FakeEncoder()).shape == (0, len(VOCAB))


def test_texte_d_une_offre() -> None:
    text = embeddings.offer_text("Data engineer", "69 - Lyon", "Auvergne-Rhône-Alpes", "Du cloud")
    assert text == "Data engineer. 69 - Lyon — Auvergne-Rhône-Alpes\nDu cloud"
    assert embeddings.offer_text(None, None, None, "Du cloud") == "Du cloud"


# ------------------------------------------------------------- recherche


@pytest.fixture()
def index() -> VectorIndex:
    return VectorIndex(("a", "b", "c"), normalize(np.array([[1, 0], [1, 1], [0, 1]])))


def test_les_offres_sont_classees_par_similitude(index: VectorIndex) -> None:
    hits = top_k(index, np.array([2.0, 0.0]), k=2)
    assert [offer_id for offer_id, _ in hits] == ["a", "b"]
    assert hits[0][1] == pytest.approx(1.0)
    assert hits[1][1] == pytest.approx(np.sqrt(0.5))


def test_la_recherche_respecte_les_offres_autorisees(index: VectorIndex) -> None:
    assert [i for i, _ in top_k(index, np.array([1.0, 0.0]), allowed={"c", "b"})] == ["b", "c"]
    assert top_k(index, np.array([1.0, 0.0]), allowed=[]) == []


def test_k_plus_grand_que_l_index(index: VectorIndex) -> None:
    assert len(top_k(index, np.array([1.0, 0.0]), k=10)) == 3


def test_l_index_survit_a_l_aller_retour_sur_disque(index: VectorIndex, tmp_path: Path) -> None:
    save_index(index, tmp_path / "v.npy", tmp_path / "ids.json")
    reloaded = load_index(tmp_path / "v.npy", tmp_path / "ids.json")
    assert reloaded.ids == index.ids
    assert np.array_equal(reloaded.vectors, index.vectors)


def test_un_index_desaligne_est_refuse() -> None:
    with pytest.raises(ValueError, match="désaligné"):
        VectorIndex(("a",), np.zeros((2, 3)))


# ----------------------------------------------------------- de bout en bout


def raw_offer(offer_id: str, title: str, place: str, text: str) -> dict[str, Any]:
    """Une offre minimale, au format de ``data/raw/``."""
    return {"id": offer_id, "intitule": title, "description": text,
            "lieuTravail": {"libelle": place},
            "origineOffre": {"urlOrigine": f"https://example.test/{offer_id}"}}


@pytest.fixture()
def warehouse(tmp_path: Path) -> Path:
    path = tmp_path / "warehouse.duckdb"
    offers = [
        raw_offer("B", "Data analyst", "75 - Paris", "Tableaux Excel"),
        raw_offer("A", "Data engineer", "69 - Lyon 3e", "Pipelines Python dans le cloud"),
    ]
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE TABLE raw_offres (id VARCHAR PRIMARY KEY, offre JSON NOT NULL, "
                    "source_file VARCHAR, ingested_at TIMESTAMP)")
        con.executemany("INSERT INTO raw_offres VALUES (?, ?, 'synthetique', now())",
                        [(o["id"], json.dumps(o, ensure_ascii=False)) for o in offers])
        apply_models(con)
    return path


def test_les_textes_viennent_de_l_entrepot(warehouse: Path) -> None:
    with duckdb.connect(str(warehouse), read_only=True) as con:
        ids, texts = embeddings.fetch_offer_texts(con)
    assert ids == ["A", "B"]
    assert texts[0] == ("Data engineer. 69 - Lyon 3e — Auvergne-Rhône-Alpes\n"
                        "Pipelines Python dans le cloud")


def test_index_construit_et_interroge(warehouse: Path, tmp_path: Path) -> None:
    model = FakeEncoder()
    written = embeddings.build_embeddings(
        warehouse, tmp_path / "v.npy", tmp_path / "ids.json", model=model
    )
    index = load_index(tmp_path / "v.npy", tmp_path / "ids.json")
    query = embeddings.embed_texts(["cloud à Lyon"], model)[0]
    assert written == 2
    assert [offer_id for offer_id, _ in top_k(index, query)] == ["A", "B"]
