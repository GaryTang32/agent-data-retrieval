"""Deterministic BM25 over chunks (bm25s, pre-tokenized input)."""

from __future__ import annotations

from importlib import metadata

import bm25s

from adr_eval.retrieval.chunker import Chunk, tokenize

_METHOD = "lucene"


class BM25Index:
    def __init__(self, k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        self._ids: list[str] = []
        self._bm25: bm25s.BM25 | None = None

    def build(self, chunks: list[Chunk]) -> None:
        self._ids = [c.chunk_id for c in chunks]
        self._bm25 = None
        corpus = [tokenize(c.text) for c in chunks]
        if not any(corpus):
            return  # nothing indexable; search() returns []
        bm = bm25s.BM25(method=_METHOD, k1=self.k1, b=self.b)
        bm.index(corpus, show_progress=False)
        self._bm25 = bm

    def search(self, query: str, k: int = 100) -> list[tuple[str, float]]:
        q = tokenize(query)
        if self._bm25 is None or not q or k <= 0:
            return []
        scores = self._bm25.get_scores(q)
        hits = [(cid, round(float(s), 6)) for cid, s in zip(self._ids, scores, strict=True)]
        hits = [h for h in hits if h[1] > 0]
        hits.sort(key=lambda h: (-h[1], h[0]))
        return hits[:k]

    def config(self) -> dict:
        return {
            "library": "bm25s",
            "version": metadata.version("bm25s"),
            "method": _METHOD,
            "k1": self.k1,
            "b": self.b,
        }
