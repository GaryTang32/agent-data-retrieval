"""Exact dense retrieval: bge-small via fastembed (ONNX, CPU), cosine on unit vectors."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from adr_eval.retrieval.chunker import Chunk

_BATCH = 32


def _unit(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, np.float32(1e-12))


class DenseIndex:
    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        cache_dir: Path = Path(".cache/emb"),
        model_cache_dir: Path = Path(".cache/fastembed"),
    ):
        self.model_name = model_name
        self.cache_dir = Path(cache_dir)
        self.model_cache_dir = Path(model_cache_dir)
        self._model = None
        self._ids: list[str] = []
        self.vectors = np.zeros((0, 0), dtype=np.float32)

    def _get_model(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(
                self.model_name, cache_dir=str(self.model_cache_dir), threads=1
            )
        return self._model

    def _emb_path(self, text: str) -> Path:
        slug = self.model_name.replace("/", "--")
        return self.cache_dir / slug / f"{hashlib.sha256(text.encode('utf-8')).hexdigest()}.npy"

    def build(self, chunks: list[Chunk]) -> None:
        self._ids = [c.chunk_id for c in chunks]
        rows: list[np.ndarray | None] = []
        missing: list[int] = []
        for i, c in enumerate(chunks):
            p = self._emb_path(c.text)
            if p.exists():
                rows.append(np.load(p))
            else:
                rows.append(None)
                missing.append(i)
        if missing:
            model = self._get_model()
            embs = list(model.passage_embed([chunks[i].text for i in missing], batch_size=_BATCH))
            for i, e in zip(missing, embs, strict=True):
                v = _unit(e)
                p = self._emb_path(chunks[i].text)
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_suffix(".tmp.npy")
                np.save(tmp, v)
                tmp.replace(p)
                rows[i] = v
        self.vectors = (
            np.stack(rows).astype(np.float32) if rows else np.zeros((0, 0), dtype=np.float32)
        )

    def set_vectors(self, ids: list[str], vectors: np.ndarray) -> None:
        """Restore a saved index (rows already L2-normalized)."""
        self._ids = list(ids)
        self.vectors = np.asarray(vectors, dtype=np.float32)

    def search(self, query: str, k: int = 100) -> list[tuple[str, float]]:
        if not self._ids or k <= 0:
            return []
        q = _unit(next(iter(self._get_model().query_embed([query]))))
        scores = self.vectors @ q
        hits = [(cid, round(float(s), 6)) for cid, s in zip(self._ids, scores, strict=True)]
        hits.sort(key=lambda h: (-h[1], h[0]))
        return hits[:k]

    def model_hash(self) -> str:
        """SHA-256 of the model's ONNX file in the fastembed cache (downloads it if absent)."""
        from fastembed import TextEmbedding

        desc = next(
            m for m in TextEmbedding.list_supported_models() if m["model"] == self.model_name
        )
        repo = desc["sources"]["hf"].replace("/", "--")
        pattern = f"models--{repo}/snapshots/*/{desc['model_file']}"
        found = sorted(self.model_cache_dir.glob(pattern))
        if not found:
            self._get_model()
            found = sorted(self.model_cache_dir.glob(pattern))
        if not found:
            raise FileNotFoundError(
                f"ONNX file for {self.model_name} not in {self.model_cache_dir}"
            )
        h = hashlib.sha256()
        with open(found[0], "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
