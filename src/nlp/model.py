"""Chargement du modèle d'embeddings, et interfaces attendues de lui.

Les interfaces sont des ``Protocol`` : le reste du code — et les tests, avec un
encodeur factice — est typé sans avoir à importer torch.
"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np

from src.ingest.tls import enable_system_trust_store

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


class Tokenizer(Protocol):
    """Ce que le projet attend du tokenizer d'un ``SentenceTransformer``."""

    def __call__(self, text: str, **kwargs: Any) -> Any: ...

    def num_special_tokens_to_add(self) -> int: ...


class Encoder(Protocol):
    """Ce que le projet attend d'un ``SentenceTransformer``."""

    tokenizer: Tokenizer
    max_seq_length: int

    def encode(self, sentences: list[str], **kwargs: Any) -> np.ndarray: ...

    def get_sentence_embedding_dimension(self) -> int: ...


def load_model(name: str = MODEL_NAME) -> Encoder:
    """Charger le modèle sur CPU (téléchargé au premier appel, ~470 Mo)."""
    # Derrière un antivirus qui inspecte le HTTPS, huggingface.co n'est
    # joignable qu'avec le magasin de certificats du système.
    enable_system_trust_store()
    from sentence_transformers import SentenceTransformer  # import lourd : différé

    return SentenceTransformer(name, device="cpu")
