"""Hybrid (BM25 + dense) index over a corpus, with a fingerprint of everything that shapes it."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Literal

import numpy as np

from adr_eval.corpora.base import LoadedCorpus
from adr_eval.corpora.extract import EXTRACTOR_VERSION
from adr_eval.models import jsonl_lines
from adr_eval.retrieval.chunker import (
    CHUNKER_CONFIG,
    TOKENIZER_CONFIG,
    Chunk,
    chunk_document,
)
from adr_eval.retrieval.dense import DenseIndex
from adr_eval.retrieval.fusion import linear, rrf
from adr_eval.retrieval.lexical import BM25Index

_CHANNEL_K = 100  # candidates per channel (BM25, dense) before fusion
RRF_K = 60
TOP_N = 10


def _fingerprint(snapshot: str, bm25: BM25Index, dense: DenseIndex, chunk_ids: list[str]) -> str:
    payload = {
        "snapshot": snapshot,
        "extractor_version": EXTRACTOR_VERSION,
        "chunker": CHUNKER_CONFIG,
        "tokenizer": TOKENIZER_CONFIG,
        "bm25": bm25.config(),
        "dense_model_hash": dense.model_hash(),
        "chunk_ids": sorted(chunk_ids),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class HybridIndex:
    def __init__(
        self,
        snapshot: str,
        chunks: dict[str, Chunk],
        bm25: BM25Index,
        dense: DenseIndex,
    ):
        self.snapshot = snapshot
        self.chunks = chunks
        self.bm25 = bm25
        self.dense = dense
        self.fingerprint = _fingerprint(snapshot, bm25, dense, list(chunks))

    @classmethod
    def build(cls, corpus: LoadedCorpus) -> HybridIndex:
        chunk_list: list[Chunk] = []
        for doc_id in sorted(corpus.docs):
            chunk_list.extend(chunk_document(corpus.docs[doc_id]))
        chunk_list.sort(key=lambda c: c.chunk_id)
        bm25, dense = BM25Index(), DenseIndex()
        bm25.build(chunk_list)
        dense.build(chunk_list)
        return cls(corpus.manifest.snapshot(), {c.chunk_id: c for c in chunk_list}, bm25, dense)

    def retrieve(
        self,
        query: str,
        system: Literal["baseline-rrf", "baseline-linear"],
        w: float | None = None,
        top: int = TOP_N,
    ) -> list[tuple[str, float]]:
        if system not in ("baseline-rrf", "baseline-linear"):
            raise ValueError(f"unknown system: {system!r}")
        if system == "baseline-linear" and w is None:
            raise ValueError("baseline-linear requires a tuned weight w")
        lex = self.bm25.search(query, k=_CHANNEL_K)
        den = self.dense.search(query, k=_CHANNEL_K)
        if system == "baseline-rrf":
            return rrf([lex, den], k=RRF_K, top=top)
        return linear(lex, den, w, top=top)

    def save(self, dir: Path) -> None:
        dir = Path(dir)
        dir.mkdir(parents=True, exist_ok=True)
        with open(dir / "chunks.jsonl", "w", encoding="utf-8") as f:
            for c in self.chunks.values():
                f.write(json.dumps(asdict(c), ensure_ascii=False, sort_keys=True) + "\n")
        np.save(dir / "dense.npy", self.dense.vectors)
        meta = {"fingerprint": self.fingerprint, "snapshot": self.snapshot}
        (dir / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")

    @classmethod
    def load(cls, dir: Path) -> HybridIndex:
        dir = Path(dir)
        meta = json.loads((dir / "meta.json").read_text(encoding="utf-8"))
        chunk_list = [
            Chunk(**json.loads(line))
            for line in jsonl_lines((dir / "chunks.jsonl").read_text(encoding="utf-8"))
        ]
        vectors = np.load(dir / "dense.npy")
        if vectors.ndim != 2 or vectors.shape[0] != len(chunk_list):
            rows = vectors.shape[0] if vectors.ndim else 0
            raise ValueError(
                f"{dir}: dense.npy has {rows} rows but chunks.jsonl has {len(chunk_list)} "
                f"chunks (truncated or mismatched files); rebuild the index")
        bm25, dense = BM25Index(), DenseIndex()
        bm25.build(chunk_list)  # deterministic rebuild from the stored chunks
        dense.set_vectors([c.chunk_id for c in chunk_list], vectors)
        idx = cls(meta["snapshot"], {c.chunk_id: c for c in chunk_list}, bm25, dense)
        if idx.fingerprint != meta["fingerprint"]:
            raise ValueError(
                f"fingerprint mismatch: stored {meta['fingerprint']}, recomputed {idx.fingerprint}"
            )
        return idx
