"""`StoreIndex`: hybrid retrieval over the structure-led chunks of one store snapshot (spec §8).

Settings: `w_bc` (breadcrumb repetitions in the BM25 field), `prefix` (embed "breadcrumb\\nbody"
instead of the body) and `rerank` (cross-encoder over the top `RERANK_TOP` fused candidates).
Fusion is the baseline's: min-max linear with a weight tuned on dev, or RRF. An index built
with `dense=False` has the lexical channel only (no embedding); its ranking is BM25's.

The fingerprint covers the store snapshot id, the chunker configuration, the settings, the
tokenizer and BM25 configuration, the embedding and reranker model hashes, the per-channel
candidate counts and the sorted chunk ids. `save(dir)` / `load(dir)` round-trip an index and
refuse a stored fingerprint that does not match the one recomputed on load.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from adr_eval.models import jsonl_lines
from adr_eval.retrieval.chunker import TOKENIZER_CONFIG
from adr_eval.retrieval.fusion import linear, rrf
from adr_store.chunking import StoreChunk, chunk_store, chunker_config
from adr_store.embedding import EmbeddingCache
from adr_store.retrieval.dense import CachedDense, embedded_text
from adr_store.retrieval.lexical import FieldBM25, check_w_bc
from adr_store.retrieval.rerank import RERANK_TOP, CrossEncoderReranker
from adr_store.store import Store

CHANNEL_K = 100  # candidates per channel before fusion, as the baseline
RRF_K = 60
TOP_N = 10
Hits = list[tuple[str, float]]


@dataclass(frozen=True)
class Settings:
    """What distinguishes the Phase 1 systems (spec §8.1)."""

    w_bc: int = 0
    prefix: bool = False
    rerank: bool = False

    def __post_init__(self):
        check_w_bc(self.w_bc)
        for name in ("prefix", "rerank"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a bool, got {getattr(self, name)!r}")


def fingerprint(snapshot: str, chunker: dict, settings: Settings, lexical: FieldBM25,
                embedding: tuple[str, str] | None, reranker: CrossEncoderReranker | None,
                chunk_ids: list[str]) -> str:
    """`embedding` is (model name, model hash), None for a lexical-only index."""
    payload = {
        "snapshot": snapshot,
        "chunker": chunker,
        "settings": asdict(settings),
        "tokenizer": TOKENIZER_CONFIG,
        "bm25": lexical.config(),
        "embedding": None if embedding is None else {"model": embedding[0],
                                                     "model_hash": embedding[1]},
        "reranker": reranker.config() if reranker is not None else None,
        "channel_k": CHANNEL_K,
        "chunk_ids": sorted(chunk_ids),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _default_cache() -> EmbeddingCache:
    return EmbeddingCache(Path(".cache/emb"))


class StoreIndex:
    """Build with `StoreIndex.build(store, settings, cache=..., reranker=...)`."""

    def __init__(self, snapshot: str, chunks: list[StoreChunk], settings: Settings,
                 chunker: dict, lexical: FieldBM25, dense: CachedDense | None,
                 reranker: CrossEncoderReranker | None, embedding: tuple[str, str] | None):
        if settings.rerank and reranker is None:
            raise ValueError("settings.rerank needs a reranker")
        if lexical.w_bc != settings.w_bc:
            raise ValueError(f"lexical w_bc {lexical.w_bc} differs from settings {settings}")
        self.snapshot = snapshot
        self.chunks: dict[str, StoreChunk] = {c.chunk_id: c for c in
                                              sorted(chunks, key=lambda c: c.chunk_id)}
        self.settings = settings
        self.chunker = chunker
        self.lexical = lexical
        self.dense = dense
        self.reranker = reranker if settings.rerank else None
        self.embedding = embedding
        self.fingerprint = fingerprint(snapshot, chunker, settings, lexical, embedding,
                                       self.reranker, list(self.chunks))

    # -- building --------------------------------------------------------------------

    @staticmethod
    def _parts(settings: Settings, cache: EmbeddingCache | None,
               reranker: CrossEncoderReranker | None, dense: bool):
        cache = cache if cache is not None or not dense else _default_cache()
        if settings.rerank and reranker is None:
            reranker = CrossEncoderReranker()
        embedding = (cache.model_name, cache.model_hash) if dense else None
        return cache, reranker, embedding

    @classmethod
    def build(cls, store: Store, settings: Settings, cache: EmbeddingCache | None = None,
              reranker: CrossEncoderReranker | None = None, *, dense: bool = True,
              max_tokens: int = 400, min_tokens: int = 40) -> StoreIndex:
        """Chunk the store's snapshot, index the chunks, embed what the cache lacks."""
        cache, reranker, embedding = cls._parts(settings, cache, reranker, dense)
        chunks = chunk_store(store, max_tokens=max_tokens, min_tokens=min_tokens)
        chunks.sort(key=lambda c: c.chunk_id)
        lexical = FieldBM25(settings.w_bc)
        lexical.build(chunks)
        dense_index = None
        if dense:
            dense_index = CachedDense(cache)
            dense_index.build_texts([c.chunk_id for c in chunks],
                                    [embedded_text(c, settings.prefix) for c in chunks])
        return cls(store.snapshot_id, chunks, settings, chunker_config(max_tokens, min_tokens),
                   lexical, dense_index, reranker, embedding)

    @classmethod
    def expected_fingerprint(cls, store: Store, settings: Settings,
                             cache: EmbeddingCache | None = None,
                             reranker: CrossEncoderReranker | None = None, *,
                             dense: bool = True, max_tokens: int = 400,
                             min_tokens: int = 40) -> str:
        """The fingerprint `build` would give, without building BM25 or embedding."""
        cache, reranker, embedding = cls._parts(settings, cache, reranker, dense)
        chunks = chunk_store(store, max_tokens=max_tokens, min_tokens=min_tokens)
        return fingerprint(store.snapshot_id, chunker_config(max_tokens, min_tokens), settings,
                           FieldBM25(settings.w_bc), embedding,
                           reranker if settings.rerank else None, [c.chunk_id for c in chunks])

    def with_settings(self, *, w_bc: int | None = None, rerank: bool | None = None,
                      reranker: CrossEncoderReranker | None = None) -> StoreIndex:
        """The same chunks and dense vectors with another breadcrumb weight or reranker
        setting (the prefix is fixed by the vectors)."""
        settings = Settings(self.settings.w_bc if w_bc is None else w_bc, self.settings.prefix,
                            self.settings.rerank if rerank is None else rerank)
        lexical = self.lexical
        if settings.w_bc != self.settings.w_bc:
            lexical = FieldBM25(settings.w_bc, self.lexical.bm25.k1, self.lexical.bm25.b)
            lexical.build(list(self.chunks.values()))
        reranker = reranker or self.reranker
        if settings.rerank and reranker is None:
            reranker = CrossEncoderReranker()
        return StoreIndex(self.snapshot, list(self.chunks.values()), settings, self.chunker,
                          lexical, self.dense, reranker, self.embedding)

    # -- searching -------------------------------------------------------------------

    def lexical_hits(self, query: str, k: int = CHANNEL_K) -> Hits:
        return self.lexical.search(query, k=k)

    def dense_hits(self, query: str, k: int = CHANNEL_K) -> Hits:
        if self.dense is None:
            raise ValueError("this index has no dense channel (built with dense=False)")
        return self.dense.search(query, k=k)

    def retrieve(self, query: str, fusion: Literal["linear", "rrf"] = "linear",
                 w: float | None = None, top: int = TOP_N) -> Hits:
        """The top chunks for `query`: fused (or BM25's, without a dense channel), then
        reranked when the settings say so."""
        if fusion not in ("linear", "rrf"):
            raise ValueError(f"unknown fusion {fusion!r}")
        n = RERANK_TOP if self.reranker is not None else top
        lex = self.lexical_hits(query)
        if self.dense is None:
            fused = lex[:n]
        elif fusion == "rrf":
            fused = rrf([lex, self.dense_hits(query)], k=RRF_K, top=n)
        else:
            if w is None:
                raise ValueError("linear fusion needs a tuned weight w")
            fused = linear(lex, self.dense_hits(query), w, top=n)
        if self.reranker is None:
            return fused
        return self.reranker.rerank(
            query, [(cid, embedded_text(self.chunks[cid], self.settings.prefix))
                    for cid, _ in fused], top=top)

    # -- persistence -----------------------------------------------------------------

    def save(self, dir: Path) -> None:
        dir = Path(dir)
        dir.mkdir(parents=True, exist_ok=True)
        with open(dir / "chunks.jsonl", "w", encoding="utf-8") as f:
            for c in self.chunks.values():
                f.write(json.dumps(asdict(c), ensure_ascii=False, sort_keys=True) + "\n")
        if self.dense is not None:
            np.save(dir / "dense.npy", self.dense.vectors)
        meta = {"fingerprint": self.fingerprint, "snapshot": self.snapshot,
                "settings": asdict(self.settings), "chunker": self.chunker,
                "dense": self.dense is not None,
                "bm25": {"k1": self.lexical.bm25.k1, "b": self.lexical.bm25.b}}
        (dir / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n",
                                       encoding="utf-8")

    @classmethod
    def load(cls, dir: Path, cache: EmbeddingCache | None = None,
             reranker: CrossEncoderReranker | None = None) -> StoreIndex:
        """Read a saved index; BM25 is rebuilt from the stored chunks, vectors are read back,
        and the recomputed fingerprint must equal the stored one."""
        dir = Path(dir)
        meta = json.loads((dir / "meta.json").read_text(encoding="utf-8"))
        settings = Settings(**meta["settings"])
        cache, reranker, embedding = cls._parts(settings, cache, reranker, meta["dense"])
        chunks = []
        for line in jsonl_lines((dir / "chunks.jsonl").read_text(encoding="utf-8")):
            row = json.loads(line)
            chunks.append(StoreChunk(**{**row, "element_ids": tuple(row["element_ids"])}))
        lexical = FieldBM25(settings.w_bc, **meta["bm25"])
        lexical.build(chunks)
        dense = None
        if meta["dense"]:
            vectors = np.load(dir / "dense.npy")
            if vectors.ndim != 2 or vectors.shape[0] != len(chunks):
                rows = vectors.shape[0] if vectors.ndim else 0
                raise ValueError(f"{dir}: dense.npy has {rows} rows but chunks.jsonl has "
                                 f"{len(chunks)} chunks; rebuild the index")
            dense = CachedDense(cache)
            dense.set_vectors([c.chunk_id for c in chunks], vectors)
        idx = cls(meta["snapshot"], chunks, settings, meta["chunker"], lexical, dense, reranker,
                  embedding)
        if idx.fingerprint != meta["fingerprint"]:
            raise ValueError(f"{dir}: fingerprint mismatch: stored {meta['fingerprint']}, "
                             f"recomputed {idx.fingerprint}")
        return idx
