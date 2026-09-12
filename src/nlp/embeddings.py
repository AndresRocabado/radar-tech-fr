"""Embeddings des offres, calculés par lots avec sentence-transformers.

Chaque offre est représentée par le texte « intitulé, lieu, description ». Le
modèle ne lit que 128 tokens, quand une description en compte plusieurs
centaines : plutôt que de la tronquer, on la découpe en tranches de 128 tokens,
on encode chaque tranche, et le vecteur de l'offre est la moyenne normalisée de
ses tranches.

Usage :
    python -m src.nlp.embeddings                  # calcule et enregistre l'index
    python -m src.nlp.embeddings --benchmark 200  # mesure le débit, n'écrit rien
"""

from __future__ import annotations

import argparse
import itertools
import logging
import time
from pathlib import Path

import duckdb
import numpy as np

from src.nlp.model import Encoder, Tokenizer, load_model
from src.nlp.search import (
    DEFAULT_IDS_PATH, DEFAULT_VECTORS_PATH, VectorIndex, normalize, save_index,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "warehouse.duckdb"
BATCH_SIZE = 32

# Le libellé du lieu (« 69 - Lyon 3e ») n'existe que dans le brut ; la région
# vient de la vue, qui la déduit du département.
_OFFERS_SQL = """
SELECT o.id, o.intitule, r.offre->>'$.lieuTravail.libelle', o.region, o.description
FROM offres o
JOIN raw_offres r USING (id)
ORDER BY o.id
"""


def offer_text(
    title: str | None, place: str | None, region: str | None, description: str | None
) -> str:
    """Texte encodé pour une offre : intitulé, lieu puis description.

    Le lieu est ajouté parce qu'une recherche le cite souvent (« en région
    lyonnaise ») alors que la description ne le mentionne pas toujours.
    """
    location = " — ".join(part for part in (place, region) if part)
    head = ". ".join(part for part in (title, location) if part)
    return "\n".join(part for part in (head, description) if part)


def fetch_offer_texts(con: duckdb.DuckDBPyConnection) -> tuple[list[str], list[str]]:
    """Les ids des offres de l'entrepôt et leur texte, dans le même ordre."""
    rows = con.execute(_OFFERS_SQL).fetchall()
    return [row[0] for row in rows], [offer_text(*row[1:]) for row in rows]


def chunk_text(text: str, tokenizer: Tokenizer, max_tokens: int) -> list[str]:
    """Découper ``text`` en tranches d'au plus ``max_tokens`` tokens.

    Les tranches sont taillées dans le texte d'origine grâce aux positions que
    renvoie le tokenizer, plutôt que redécodées : le texte reste intact.
    """
    # verbose=False : le tokenizer avertirait que le texte dépasse 128 tokens,
    # ce qui est justement la raison du découpage.
    offsets = tokenizer(
        text, add_special_tokens=False, return_offsets_mapping=True, verbose=False
    )["offset_mapping"]
    if len(offsets) <= max_tokens:
        return [text]
    return [
        text[window[0][0] : window[-1][1]]
        for window in (
            offsets[start : start + max_tokens] for start in range(0, len(offsets), max_tokens)
        )
    ]


def embed_texts(texts: list[str], model: Encoder, batch_size: int = BATCH_SIZE) -> np.ndarray:
    """Un vecteur normalisé par texte : la moyenne des vecteurs de ses tranches.

    Les tranches de tous les textes sont encodées ensemble, ce qui remplit les
    lots même quand les textes sont courts.
    """
    if not texts:
        return np.zeros((0, model.get_sentence_embedding_dimension()), dtype=np.float32)
    budget = model.max_seq_length - model.tokenizer.num_special_tokens_to_add()
    chunks = [chunk_text(text, model.tokenizer, budget) for text in texts]
    owners = np.repeat(np.arange(len(texts)), [len(parts) for parts in chunks])
    encoded = model.encode(
        list(itertools.chain.from_iterable(chunks)),
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    sums = np.zeros((len(texts), encoded.shape[1]), dtype=np.float32)
    np.add.at(sums, owners, encoded)
    return normalize(sums)


def _read_texts(db_path: Path) -> tuple[list[str], list[str]]:
    with duckdb.connect(str(db_path), read_only=True) as con:
        return fetch_offer_texts(con)


def build_embeddings(
    db_path: Path = DEFAULT_DB_PATH,
    vectors_path: Path = DEFAULT_VECTORS_PATH,
    ids_path: Path = DEFAULT_IDS_PATH,
    model: Encoder | None = None,
) -> int:
    """Encoder toutes les offres de l'entrepôt et écrire l'index ; retourne leur nombre."""
    ids, texts = _read_texts(db_path)
    model = model or load_model()
    started = time.perf_counter()
    vectors = embed_texts(texts, model)
    logger.info("%d offres encodées en %.1f s", len(ids), time.perf_counter() - started)
    save_index(VectorIndex(tuple(ids), vectors), vectors_path, ids_path)
    return len(ids)


def benchmark(
    sample_size: int, db_path: Path = DEFAULT_DB_PATH, model: Encoder | None = None
) -> tuple[float, int]:
    """Mesurer le temps d'encodage par offre sur ``sample_size`` textes réels.

    Si l'entrepôt compte moins d'offres, ses textes sont repris en boucle : rien
    n'est mis en cache d'un texte à l'autre, le temps reste représentatif.

    Returns:
        Les secondes par offre, et le nombre d'offres de l'entrepôt.
    """
    _, texts = _read_texts(db_path)
    if not texts:
        raise ValueError(f"Aucune offre dans {db_path}")
    sample = list(itertools.islice(itertools.cycle(texts), sample_size))
    model = model or load_model()
    embed_texts(sample[:BATCH_SIZE], model)  # échauffement : le premier lot est plus lent
    started = time.perf_counter()
    embed_texts(sample, model)
    return (time.perf_counter() - started) / sample_size, len(texts)


def main() -> None:
    """Point d'entrée de ``python -m src.nlp.embeddings``."""
    parser = argparse.ArgumentParser(description="Calculer les embeddings des offres.")
    parser.add_argument("--benchmark", type=int, metavar="N",
                        help="mesurer le débit sur N offres, sans rien écrire")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # une ligne par fichier du modèle

    if args.benchmark:
        per_offer, total = benchmark(args.benchmark)
        logger.info("%.3f s par offre (%.1f offres/s) sur %d textes",
                    per_offer, 1 / per_offer, args.benchmark)
        for count in (total, 1_000, 10_000):
            logger.info("Estimation pour %6d offres : %7.1f s", count, count * per_offer)
        return

    written = build_embeddings()
    logger.info("Index prêt dans %s (%d offres)", DEFAULT_VECTORS_PATH.parent, written)


if __name__ == "__main__":
    main()
