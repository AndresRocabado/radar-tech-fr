"""Index vectoriel des offres et recherche par similitude cosinus.

L'index tient en deux fichiers : ``embeddings.npy`` (une ligne par offre,
vecteurs normalisés) et ``embeddings_ids.json`` (l'id de chaque ligne, dans le
même ordre). Les vecteurs étant de norme 1, la similitude cosinus se réduit à
un produit scalaire, et un parcours exhaustif en numpy suffit largement à
l'échelle du projet (voir ``docs/adr/0001-recherche-vectorielle-numpy.md``).
"""

from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VECTORS_PATH = PROJECT_ROOT / "data" / "embeddings.npy"
DEFAULT_IDS_PATH = PROJECT_ROOT / "data" / "embeddings_ids.json"


@dataclass(frozen=True)
class VectorIndex:
    """Vecteurs normalisés des offres, alignés ligne à ligne sur ``ids``."""

    ids: tuple[str, ...]
    vectors: np.ndarray

    def __post_init__(self) -> None:
        if self.vectors.ndim != 2 or self.vectors.shape[0] != len(self.ids):
            raise ValueError(
                f"Index désaligné : {len(self.ids)} ids pour une matrice {self.vectors.shape}"
            )


def normalize(vectors: np.ndarray) -> np.ndarray:
    """Ramener chaque vecteur (chaque ligne) à une norme 1 ; un vecteur nul reste nul."""
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return np.divide(vectors, norms, out=np.zeros_like(vectors), where=norms > 0)


def save_index(
    index: VectorIndex,
    vectors_path: Path = DEFAULT_VECTORS_PATH,
    ids_path: Path = DEFAULT_IDS_PATH,
) -> None:
    """Écrire l'index sur disque : la matrice en ``.npy``, les ids en JSON."""
    vectors_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(vectors_path, index.vectors.astype(np.float32))
    ids_path.write_text(json.dumps(list(index.ids)), encoding="utf-8")


def load_index(
    vectors_path: Path = DEFAULT_VECTORS_PATH, ids_path: Path = DEFAULT_IDS_PATH
) -> VectorIndex:
    """Relire l'index ; lève ``ValueError`` si les deux fichiers ne concordent pas."""
    ids = json.loads(ids_path.read_text(encoding="utf-8"))
    return VectorIndex(tuple(ids), np.load(vectors_path))


def top_k(
    index: VectorIndex,
    query: np.ndarray,
    k: int = 10,
    allowed: Collection[str] | None = None,
) -> list[tuple[str, float]]:
    """Les ``k`` offres les plus proches de ``query``, par score décroissant.

    Args:
        index: l'index des offres.
        query: le vecteur de la requête, normalisé ou non.
        k: nombre maximal de résultats.
        allowed: si fourni, seules ces offres sont candidates (filtres du dashboard).

    Returns:
        Des couples ``(id, score)``, le score étant la similitude cosinus.
    """
    scores = index.vectors @ normalize(query)
    if allowed is None:
        candidates = np.arange(len(index.ids))
    else:
        keep = set(allowed)
        candidates = np.array(
            [i for i, offer_id in enumerate(index.ids) if offer_id in keep], dtype=int
        )
    if k <= 0 or candidates.size == 0:
        return []
    best = candidates[np.argsort(-scores[candidates], kind="stable")[:k]]
    return [(index.ids[i], float(scores[i])) for i in best]
