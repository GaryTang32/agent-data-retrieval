"""Embedding cache keyed by the exact embedded text and the model's hash (spec §8).

    <cache_dir>/<model name, "/" as "--">/<model hash>/<text sha256[:2]>/<text sha256>.npy

Each file holds one L2-normalised float32 vector. The model, its thread setting, its batch
size and the normalisation are the baseline's (`adr_eval.retrieval.dense.DenseIndex`), so a
text gets the same vector here as there. Vectors are written one by one as they are computed
(temporary file, then rename), so an interrupted run keeps what it finished; re-embedding an
unchanged text set computes nothing.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

import numpy as np

from adr_eval.retrieval.dense import _BATCH, DenseIndex
from adr_eval.retrieval.dense import _unit as unit

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

Embedder = Callable[[list[str]], Iterable[np.ndarray]]


class EmbeddingCache:
    """`embed_texts(texts) -> (vectors, n_new)` over an on-disk cache.

    `embedder` and `model_hash` replace the fastembed model and the hash of its ONNX file
    (for tests); by default both come from a `DenseIndex` with the same model name, so the
    model is loaded only when a text is missing from the cache.
    """

    def __init__(self, cache_dir: Path, model_name: str = DEFAULT_MODEL,
                 model_cache_dir: Path = Path(".cache/fastembed"),
                 embedder: Embedder | None = None, model_hash: str | None = None):
        self.cache_dir = Path(cache_dir)
        self.model_name = model_name
        self._dense = DenseIndex(model_name, cache_dir=self.cache_dir,
                                 model_cache_dir=Path(model_cache_dir))
        self._embedder = embedder
        self._model_hash = model_hash

    @property
    def model_hash(self) -> str:
        """SHA-256 of the model file, as `DenseIndex.model_hash` computes it."""
        if self._model_hash is None:
            self._model_hash = self._dense.model_hash()
        return self._model_hash

    def _embed(self, texts: list[str]) -> Iterable[np.ndarray]:
        if self._embedder is not None:
            return self._embedder(texts)
        return self._dense._get_model().passage_embed(texts, batch_size=_BATCH)

    def path(self, text: str) -> Path:
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        slug = self.model_name.replace("/", "--")
        return self.cache_dir / slug / self.model_hash / key[:2] / f"{key}.npy"

    def embed_texts(self, texts: Sequence[str]) -> tuple[np.ndarray, int]:
        """One unit vector per text, in input order, and how many texts were newly embedded
        (each distinct missing text once)."""
        texts = list(texts)
        if not texts:
            return np.zeros((0, 0), dtype=np.float32), 0
        found: dict[str, np.ndarray] = {}
        missing: list[str] = []
        for t in dict.fromkeys(texts):
            p = self.path(t)
            if p.is_file():
                found[t] = np.load(p)
            else:
                missing.append(t)
        if missing:
            try:
                for t, v in zip(missing, self._embed(missing), strict=True):
                    found[t] = self._save(t, unit(v))
            except ValueError as e:  # from zip: not one vector per text
                raise ValueError(f"the embedder did not return one vector for each of "
                                 f"{len(missing)} texts") from e
        return np.stack([found[t] for t in texts]).astype(np.float32), len(missing)

    def _save(self, text: str, vector: np.ndarray) -> np.ndarray:
        p = self.path(text)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.stem}.tmp.npy")
        np.save(tmp, vector)
        tmp.replace(p)
        return vector
