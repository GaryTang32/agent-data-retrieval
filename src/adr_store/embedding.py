"""Embedding cache keyed by the exact embedded text and the model's hash (spec §8).

    <cache_dir>/<model name, "/" as "--">/<model hash>/<text sha256[:2]>/<text sha256>.npy

Each file holds one L2-normalised float32 vector. The model, its thread setting, its batch
size and the normalisation are the baseline's (`adr_eval.retrieval.dense.DenseIndex`), so a
text gets the same vector here as there. Vectors are written one by one as they are computed,
each through its own temporary file (`tempfile.mkstemp`) and then `os.replace`, so an
interrupted run keeps what it finished and concurrent writers of the same key do not collide;
re-embedding an unchanged text set computes nothing. A cached file that does not hold a valid
vector (unreadable, not 1-D float32 of the model's dimension, not finite, norm not within 1e-3
of 1) is deleted and its text embedded again, counted as new.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

import numpy as np

from adr_eval.retrieval.dense import _BATCH, DenseIndex
from adr_eval.retrieval.dense import _unit as unit

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

Embedder = Callable[[list[str]], Iterable[np.ndarray]]
NORM_TOLERANCE = 1e-3


class EmbeddingCache:
    """`embed_texts(texts) -> (vectors, n_new)` over an on-disk cache.

    `embedder`, `model_hash` and `dim` replace the fastembed model, the hash of its ONNX file
    and its vector dimension (for tests); by default they come from a `DenseIndex` with the
    same model name and fastembed's model list, so the model is loaded only when a text is
    missing from the cache.
    """

    def __init__(self, cache_dir: Path, model_name: str = DEFAULT_MODEL,
                 model_cache_dir: Path = Path(".cache/fastembed"),
                 embedder: Embedder | None = None, model_hash: str | None = None,
                 dim: int | None = None):
        self.cache_dir = Path(cache_dir)
        self.model_name = model_name
        self._dense = DenseIndex(model_name, cache_dir=self.cache_dir,
                                 model_cache_dir=Path(model_cache_dir))
        self._embedder = embedder
        self._model_hash = model_hash
        self._dim = dim

    @property
    def dim(self) -> int:
        """The model's vector dimension, from fastembed's model list unless given."""
        if self._dim is None:
            from fastembed import TextEmbedding

            desc = next(m for m in TextEmbedding.list_supported_models()
                        if m["model"] == self.model_name)
            self._dim = int(desc["dim"])
        return self._dim

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
            v = self._load(p) if p.is_file() else None
            if v is None:
                missing.append(t)
            else:
                found[t] = v
        if missing:
            try:
                for t, v in zip(missing, self._embed(missing), strict=True):
                    found[t] = self._save(t, unit(v))
            except ValueError as e:  # from zip: not one vector per text
                raise ValueError(f"the embedder did not return one vector for each of "
                                 f"{len(missing)} texts") from e
        return np.stack([found[t] for t in texts]).astype(np.float32), len(missing)

    def _load(self, path: Path) -> np.ndarray | None:
        """The vector in `path`, or None (and the file deleted) when it is not a valid one."""
        try:
            v = np.load(path, allow_pickle=False)
            ok = (isinstance(v, np.ndarray) and v.dtype == np.float32 and v.ndim == 1
                  and v.shape[0] == self.dim and bool(np.isfinite(v).all())
                  and abs(float(np.linalg.norm(v)) - 1.0) <= NORM_TOLERANCE)
        except (OSError, ValueError, EOFError):
            ok = False
        if ok:
            return v
        path.unlink(missing_ok=True)
        return None

    def _save(self, text: str, vector: np.ndarray) -> np.ndarray:
        p = self.path(text)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.stem}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                np.save(f, vector)
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return vector
