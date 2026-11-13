"""System registry: a name maps to a builder of one retrieval system over one corpus.

A built system has `retrieve(question) -> [(chunk_id, score)]` (the top 10, best first),
`chunks` (chunk id -> `Chunk`), `fingerprint`, `w` (the tuned linear weight, or None),
`source` ("loaded" or "built": where its index came from) and `run_config()` (the
"retrieval" block of a run's config).

- `baseline-rrf`, `baseline-linear`: the Phase 0 hybrid index (`HybridIndex`), unchanged.
- `p1-struct`, `p1-struct-bc`, `p1-struct-bc-rr`: the Phase 1 systems of spec §8.1 over the
  structure-led chunks of an evidence store (`adr_store`). The store is ingested into
  `<store_dir>/<corpus>` when it is missing or stale; the index over it is saved under
  `<index_dir>/<corpus>-store-<body|prefix>` and checked by fingerprint like the baseline's.

Tuning (dev split, nDCG@10 of metrics version 2 over evidence groups): `baseline-linear` and
`p1-struct` tune the fusion weight; `p1-struct-bc` tunes `w_bc` in {0, 1, 2, 3} with the
fusion weight; `p1-struct-bc-rr` is tuned exactly as `p1-struct-bc` (without the reranker) and
then reranks. Ties keep the smallest `w_bc`, then the smallest weight.

With `lexical_only=True` a system keeps only its BM25 channel (no embedding, no reranker; a
Phase 1 system still tunes `w_bc` on BM25 alone): a cheap diagnostic, recorded as such in the
run config; its fingerprint differs from the full system's.

This module is the harness's only entry to `adr_store` (plan, shared rules).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from adr_eval import runner
from adr_eval.corpora.base import LoadedCorpus
from adr_eval.models import Evidence, GoldenItem
from adr_eval.retrieval.chunker import Chunk
from adr_eval.retrieval.fusion import _GRID, linear
from adr_eval.retrieval.index import _CHANNEL_K, RRF_K, TOP_N, HybridIndex
from adr_eval.retrieval.lexical import BM25Index
from adr_eval.scoring.retrieval_metrics import ndcg_at_k

W_BC_GRID = (0, 1, 2, 3)
Groups = dict[str, list[list[Evidence]]]


def _lexical_only_print(fingerprint: str) -> str:
    blob = json.dumps({"index": fingerprint, "channels": ["bm25"]}, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _dev_items(items: list[GoldenItem], name: str) -> list[GoldenItem]:
    dev = [i for i in items if i.split == "dev" and i.evidence and i.qtype != "insufficient"]
    if not dev:
        raise runner.RunError(f"{name} needs dev-split items with evidence to tune its weights")
    return sorted(dev, key=lambda i: i.id)


def _ndcg(item: GoldenItem, groups: Groups, chunks: dict[str, Chunk]):
    g = groups.get(item.id) or [[e] for e in item.evidence]
    return lambda ids: ndcg_at_k([chunks[c] for c in ids], g, 10)


# -- baselines --------------------------------------------------------------------------


@dataclass
class BaselineSystem:
    """`baseline-rrf` or `baseline-linear` over the saved Phase 0 index."""

    name: str
    chunks: dict[str, Chunk]
    fingerprint: str
    source: str
    w: float | None = None
    index: HybridIndex | None = None
    bm25: BM25Index | None = None  # lexical-only

    def retrieve(self, question: str) -> list[tuple[str, float]]:
        if self.bm25 is not None:
            return self.bm25.search(question, k=TOP_N)
        return self.index.retrieve(question, self.name, w=self.w)

    def run_config(self) -> dict:
        rrf_ = self.name == "baseline-rrf"
        if self.bm25 is not None:
            return {"fusion": None, "rrf_k": None, "channel_k": _CHANNEL_K, "top_n": TOP_N,
                    "linear_w": None, "lexical_only": True}
        return {"fusion": "rrf" if rrf_ else "linear", "rrf_k": RRF_K if rrf_ else None,
                "channel_k": _CHANNEL_K, "top_n": TOP_N, "linear_w": self.w}


def _baseline(name: str):
    def build(corpus: str, loaded: LoadedCorpus, items: list[GoldenItem], groups: Groups,
              config: dict, *, rebuild: bool = False,
              lexical_only: bool = False) -> BaselineSystem:
        if lexical_only:
            chunk_list = sorted(runner._all_chunks(loaded), key=lambda c: c.chunk_id)
            bm25 = BM25Index()
            bm25.build(chunk_list)
            return BaselineSystem(name, {c.chunk_id: c for c in chunk_list},
                                  _lexical_only_print(runner.expected_fingerprint(loaded)),
                                  "built", bm25=bm25)
        index, source = runner.ensure_index(corpus, loaded, config, rebuild)
        w = runner.tune_w(index, items, groups) if name == "baseline-linear" else None
        return BaselineSystem(name, index.chunks, index.fingerprint, source, w=w, index=index)

    return build


# -- Phase 1 systems --------------------------------------------------------------------


def make_embedding_cache(config: dict):
    """The embedding cache the Phase 1 systems use (tests replace this function)."""
    from adr_store.embedding import EmbeddingCache

    return EmbeddingCache(runner.REPO_ROOT / config.get("embedding_cache_dir", ".cache/emb"))


def make_reranker(config: dict):
    """The cross-encoder of `p1-struct-bc-rr` (tests replace this function)."""
    from adr_store.retrieval.rerank import CrossEncoderReranker

    return CrossEncoderReranker()


def store_dir(config: dict, corpus: str) -> Path:
    return runner.REPO_ROOT / config.get("store_dir", ".cache/store") / corpus


def ensure_store(corpus: str, loaded: LoadedCorpus, config: dict):
    """The corpus's evidence store, ingested (through the `adr_store` API) when it is missing
    or its snapshot does not hold exactly the corpus's documents; returns (store, how)."""
    from adr_store.cli import UNKNOWN_LICENSES, compile_figures
    from adr_store.store import EXTRACTOR, ConformanceError, Store, write_atomic
    from adr_store.structure import PARSER

    path = store_dir(config, corpus)
    want = sorted(d.doc_id for d in loaded.manifest.documents)
    if (path / "HEAD").is_file():
        store = Store.open(path)
        snap = json.loads((path / "snapshots" / f"{store.snapshot_id}.json").read_bytes())
        if (snap["parser"], snap["extractor"]) != (PARSER, EXTRACTOR):
            raise runner.RunError(
                f"{path}: store made by {snap['parser']} / {snap['extractor']}, the code is "
                f"{PARSER} / {EXTRACTOR}\nfix: remove {path} so that it is ingested again")
        if store.doc_ids() == want:
            return store, "loaded"
    store = Store.create(path)
    added, failures = [], []
    for d in sorted(loaded.manifest.documents, key=lambda d: d.doc_id):
        raw = (loaded.root / d.path).read_bytes()
        license = None if d.license.strip().lower() in UNKNOWN_LICENSES else d.license
        try:
            added.append(store.add(loaded.docs[d.doc_id], raw, license=license))
        except ConformanceError as e:
            failures.append(f"{d.path}: {e}")
    if failures:
        raise runner.RunError(f"{path}: {len(failures)} document(s) fail conformance; no "
                              f"snapshot written: {'; '.join(failures[:3])}")
    snapshot = store.commit()
    figures = compile_figures(corpus, snapshot, added, len(want), 0)
    write_atomic(path / "compile" / f"{snapshot}.json",
                 (json.dumps(figures, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return Store.open(path), "ingested"


@dataclass(frozen=True)
class StoreSpec:
    """How a Phase 1 system is set up: the breadcrumb prefix, whether `w_bc` is tuned (else
    0), and the reranker."""

    prefix: bool
    tune_w_bc: bool
    rerank: bool


SPECS = {
    "p1-struct": StoreSpec(prefix=False, tune_w_bc=False, rerank=False),
    "p1-struct-bc": StoreSpec(prefix=True, tune_w_bc=True, rerank=False),
    "p1-struct-bc-rr": StoreSpec(prefix=True, tune_w_bc=True, rerank=True),
}


@dataclass
class StoreSystem:
    name: str
    index: object  # adr_store.retrieval.StoreIndex
    w: float | None
    source: str
    store_path: Path
    tuning: dict = field(default_factory=dict)

    @property
    def chunks(self) -> dict[str, Chunk]:
        return self.index.chunks

    @property
    def fingerprint(self) -> str:
        return self.index.fingerprint

    def retrieve(self, question: str) -> list[tuple[str, float]]:
        return self.index.retrieve(question, fusion="linear", w=self.w)

    def run_config(self) -> dict:
        s = self.index.settings
        lexical_only = self.index.dense is None
        return {"fusion": None if lexical_only else "linear", "rrf_k": None,
                "channel_k": _CHANNEL_K, "top_n": TOP_N, "linear_w": self.w,
                "w_bc": s.w_bc, "prefix": s.prefix, "rerank": s.rerank,
                "rerank_top": 50 if s.rerank else None, "lexical_only": lexical_only,
                "chunker": self.index.chunker, "store": runner._display_path(self.store_path),
                "store_snapshot": self.index.snapshot, "tuning": self.tuning}


def tune_store(index, items: list[GoldenItem], groups: Groups, name: str,
               w_bcs: tuple[int, ...]) -> tuple[int, float | None, dict]:
    """(w_bc, w, record): the grid point maximising mean nDCG@10 (metrics version 2, evidence
    groups) over the dev items; ties keep the smallest `w_bc`, then the smallest `w`. A
    lexical-only index tunes `w_bc` alone (w is None)."""
    dev = _dev_items(items, name)
    ndcgs = [_ndcg(i, groups, index.chunks) for i in dev]
    dense = None if index.dense is None else [index.dense_hits(i.question) for i in dev]
    weights = [None] if dense is None else _GRID
    best = (w_bcs[0], weights[0], float("-inf"))
    for w_bc in w_bcs:
        variant = index.with_settings(w_bc=w_bc) if w_bc != index.settings.w_bc else index
        lex = [variant.lexical_hits(i.question) for i in dev]
        for w in weights:
            if dense is None:
                ranked = [[c for c, _ in hits[:TOP_N]] for hits in lex]
            else:
                ranked = [[c for c, _ in linear(lx, dn, w, top=TOP_N)]
                          for lx, dn in zip(lex, dense, strict=True)]
            mean = sum(f(r) for f, r in zip(ndcgs, ranked, strict=True)) / len(dev)
            if mean > best[2] + 1e-12:
                best = (w_bc, w, mean)
    record = {"split": "dev", "n_items": len(dev), "metric": "ndcg@10", "metrics_version": 2,
              "grid_w_bc": list(w_bcs),
              "grid_w": None if dense is None else {"from": _GRID[0], "to": _GRID[-1],
                                                    "step": 0.05},
              "best_w_bc": best[0], "best_w": best[1], "best_ndcg@10": best[2]}
    return best[0], best[1], record


def _store_system(name: str):
    spec = SPECS[name]

    def build(corpus: str, loaded: LoadedCorpus, items: list[GoldenItem], groups: Groups,
              config: dict, *, rebuild: bool = False, lexical_only: bool = False) -> StoreSystem:
        from adr_store.retrieval import Settings, StoreIndex

        store, _ = ensure_store(corpus, loaded, config)
        base_settings = Settings(w_bc=0, prefix=spec.prefix)
        if lexical_only:
            index, source = StoreIndex.build(store, base_settings, dense=False), "built"
        else:
            cache = make_embedding_cache(config)
            d = runner.REPO_ROOT / config.get("index_dir", ".cache/index") / (
                f"{corpus}-store-{'prefix' if spec.prefix else 'body'}")
            meta = d / "meta.json"
            if meta.is_file() and not rebuild:
                saved = json.loads(meta.read_text(encoding="utf-8"))["fingerprint"]
                expected = StoreIndex.expected_fingerprint(store, base_settings, cache)
                if saved != expected:
                    raise runner.RunError(
                        f"{d}: saved index fingerprint {saved[:12]} differs from the current "
                        f"store and configuration ({expected[:12]})\nfix: rerun with --rebuild")
                index, source = StoreIndex.load(d, cache=cache), "loaded"
            else:
                index, source = StoreIndex.build(store, base_settings, cache), "built"
                index.save(d)
        w_bc, w, tuning = tune_store(index, items, groups, name,
                                     W_BC_GRID if spec.tune_w_bc else (0,))
        reranker = make_reranker(config) if spec.rerank and not lexical_only else None
        index = index.with_settings(w_bc=w_bc, rerank=reranker is not None, reranker=reranker)
        return StoreSystem(name, index, w, source, store.path, tuning)

    return build


Builder = Callable[..., object]
REGISTRY: dict[str, Builder] = {
    "baseline-rrf": _baseline("baseline-rrf"),
    "baseline-linear": _baseline("baseline-linear"),
    **{name: _store_system(name) for name in SPECS},
}
NAMES = tuple(REGISTRY)


def build(name: str, corpus: str, loaded: LoadedCorpus, items: list[GoldenItem],
          groups: Groups, config: dict, *, rebuild: bool = False, lexical_only: bool = False):
    """Build the system `name` for `corpus`; `items` are all golden items (dev ones tune)."""
    if name not in REGISTRY:
        raise runner.RunError(f"unknown system {name!r}; expected one of {', '.join(NAMES)}")
    return REGISTRY[name](corpus, loaded, items, groups, config, rebuild=rebuild,
                          lexical_only=lexical_only)
