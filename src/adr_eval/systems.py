"""System registry: a name maps to a builder of one retrieval system over one corpus.

A built system has `retrieve(question) -> [(chunk_id, score)]` (the top 10, best first; a
system with `accepts_as_of` takes `retrieve(question, as_of)`),
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

- `p2-identity`, `p2-appl`, `p2-dedup`, `p2-default`: the Phase 2 configurations (Phase 2
  spec §10.1). Each builds `p1-struct-bc` through this registry (its dev tuning gives `w_bc`
  and `w`), requires every committed `p1-struct-bc` retrieval summary of the corpus
  (`PHASE1_SUMMARIES`) to show the same `w`, `w_bc`, store snapshot and fingerprint, copies
  the Phase 1 store to `<p2_store_dir>/<corpus>` (default `.cache/store-p2`) when missing,
  derives the applicability and dedup overlays there when missing, activates `p1-struct-bc`
  with those weights through `adr_store.tools.Tools` (its fingerprint must be the Phase 1
  system's) and searches through `Tools.search` with the configuration's filters and dedup.
  They take `retrieve(question, as_of)`: the configurations with `as_of` search a dated item
  with `Filters(as_of=...)`. They are registered apart (`P2_NAMES`); `NAMES` stays the Phase
  0/1 systems and `ALL_NAMES` is both.

This module is the harness's only entry to `adr_store` for the Phase 0/1 harness modules
(plan, shared rules).
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
from adr_store.applicability import Filters

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


def _loaded_reranker(config: dict, name: str):
    """`make_reranker(config)` with its model loaded and hashed; a model that cannot be
    loaded is a `RunError` naming the fix."""
    from adr_store.retrieval.rerank import RerankerUnavailable

    reranker = make_reranker(config)
    try:
        reranker.load()
        reranker.model_hash  # noqa: B018 (hashes the model file now)
    except (RerankerUnavailable, FileNotFoundError) as e:
        raise runner.RunError(f"{e}\nfix: run once online or drop the reranked system "
                              f"({name})") from e
    return reranker


def store_dir(config: dict, corpus: str) -> Path:
    return runner.REPO_ROOT / config.get("store_dir", ".cache/store") / corpus


def _checked_store(path: Path, loaded: LoadedCorpus, again: str):
    """The store at `path` (None without HEAD), refused when another parser or extractor made
    it or a document's stored text differs from the corpus's (`again`: how the fix makes it
    anew, "ingested" or "copied")."""
    from adr_store.records import sha256_text
    from adr_store.store import EXTRACTOR, Store
    from adr_store.structure import PARSER

    if not (path / "HEAD").is_file():
        return None
    store = Store.open(path)
    snap = json.loads((path / "snapshots" / f"{store.snapshot_id}.json").read_bytes())
    if (snap["parser"], snap["extractor"]) != (PARSER, EXTRACTOR):
        raise runner.RunError(
            f"{path}: store made by {snap['parser']} / {snap['extractor']}, the code is "
            f"{PARSER} / {EXTRACTOR}\nfix: remove {path} so that it is {again} again")
    held = set(store.doc_ids())
    differ = [d for d in sorted(d.doc_id for d in loaded.manifest.documents) if d in held
              and store.source(d).text_sha256 != sha256_text(loaded.docs[d].text)]
    if differ:
        raise runner.RunError(
            f"{path}: the stored text of {len(differ)} document(s) differs from the "
            f"corpus's (e.g. {differ[0]}); the corpus's text extraction changed\nfix: "
            f"remove {path} so that it is {again} again")
    return store


def ensure_store(corpus: str, loaded: LoadedCorpus, config: dict):
    """The corpus's evidence store, ingested (through the `adr_store` API) when it is missing
    or its snapshot does not hold exactly the corpus's documents; returns (store, how).

    A store made by another parser or extractor, or holding a document whose text differs
    from the text the corpus gives it (text SHA-256; the store's files are addressed by doc
    id, so it cannot take the new text in place), is refused with the fix: remove it."""
    from adr_store.cli import UNKNOWN_LICENSES, compile_figures
    from adr_store.store import ConformanceError, Store, write_atomic

    path = store_dir(config, corpus)
    want = sorted(d.doc_id for d in loaded.manifest.documents)
    store = _checked_store(path, loaded, "ingested")
    if store is not None and store.doc_ids() == want:
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
        from adr_store.retrieval.rerank import RERANK_TOP

        s = self.index.settings
        lexical_only = self.index.dense is None
        return {"fusion": None if lexical_only else "linear", "rrf_k": None,
                "channel_k": _CHANNEL_K, "top_n": TOP_N, "linear_w": self.w,
                "w_bc": s.w_bc, "prefix": s.prefix, "rerank": s.rerank,
                "rerank_top": RERANK_TOP if s.rerank else None, "lexical_only": lexical_only,
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


def _saved_fingerprint(d: Path) -> str | None:
    """The fingerprint in `d/meta.json`, None when there is none (a save of `d` by another
    run can briefly leave no index there)."""
    try:
        return json.loads((d / "meta.json").read_text(encoding="utf-8"))["fingerprint"]
    except FileNotFoundError:
        return None


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
            saved = None if rebuild else _saved_fingerprint(d)
            if saved is not None:
                expected = StoreIndex.expected_fingerprint(store, base_settings, cache)
                if saved != expected:
                    raise runner.RunError(
                        f"{d}: saved index fingerprint {saved[:12]} differs from the current "
                        f"store and configuration ({expected[:12]})\nfix: rerun with --rebuild")
                try:
                    index, source = StoreIndex.load(d, cache=cache), "loaded"
                except ValueError as e:
                    raise runner.RunError(f"{e}\nfix: rerun with --rebuild") from e
                if index.fingerprint != expected:  # replaced by another run since the check
                    raise runner.RunError(
                        f"{d}: loaded index fingerprint {index.fingerprint[:12]} differs from "
                        f"the current store and configuration ({expected[:12]})\nfix: rerun "
                        f"with --rebuild")
            else:
                index, source = StoreIndex.build(store, base_settings, cache), "built"
                index.save(d)
        w_bc, w, tuning = tune_store(index, items, groups, name,
                                     W_BC_GRID if spec.tune_w_bc else (0,))
        reranker = _loaded_reranker(config, name) if spec.rerank and not lexical_only else None
        index = index.with_settings(w_bc=w_bc, rerank=reranker is not None, reranker=reranker)
        return StoreSystem(name, index, w, source, store.path, tuning)

    return build


# -- Phase 2 configurations (Phase 2 spec §10.1) ------------------------------------------

P2_REFERENCE = "p1-struct-bc"  # the Phase 1 system whose index and weights they reuse
PHASE1_SUMMARIES = runner.REPO_ROOT / "results" / "phase1" / "run-summaries"


@dataclass(frozen=True)
class P2Spec:
    """A Phase 2 configuration: the applicability filters of every search, whether a
    `policy_asof` item's own date replaces them (`Filters(as_of=item.as_of)`), and dedup."""

    filters: Filters
    as_of: bool
    dedup: bool


P2_SPECS = {
    "p2-identity": P2Spec(Filters(include_superseded=True), as_of=False, dedup=False),
    "p2-appl": P2Spec(Filters(), as_of=True, dedup=False),
    "p2-dedup": P2Spec(Filters(include_superseded=True), as_of=False, dedup=True),
    "p2-default": P2Spec(Filters(), as_of=True, dedup=True),
}


def p2_store_dir(config: dict, corpus: str) -> Path:
    """The scratch copy of the corpus's store the Phase 2 systems use (never the Phase 1
    store itself)."""
    return runner.REPO_ROOT / config.get("p2_store_dir", ".cache/store-p2") / corpus


@dataclass
class P2System:
    """A Phase 2 configuration over the p2 store: `p1-struct-bc`'s index and weights, searched
    through `adr_store.tools.Tools` with the configuration's filters and dedup."""

    name: str
    spec: P2Spec
    tools: object  # adr_store.tools.Tools over the p2 store, its active index p1-struct-bc's
    phase1: StoreSystem
    source: str
    applicability: str | None
    dedup: str | None
    recorded: list[str]
    caller: str | None = None
    accepts_as_of = True

    @property
    def w(self) -> float | None:
        return self.phase1.w

    @property
    def chunks(self) -> dict[str, Chunk]:
        return self.tools.active_index().chunks

    @property
    def fingerprint(self) -> str:
        return self.tools.active_index().fingerprint

    def filters_for(self, as_of=None) -> Filters:
        if self.spec.as_of and as_of is not None:
            return Filters(as_of=as_of)
        return self.spec.filters

    def retrieve(self, question: str, as_of=None) -> list[tuple[str, float]]:
        res = self.tools.search(question, top=TOP_N, filters=self.filters_for(as_of),
                                dedup=self.spec.dedup)
        return [(h.chunk_id, h.score) for h in res.hits]

    def run_config(self) -> dict:
        return {**self.phase1.run_config(),
                "store": runner._display_path(self.tools.store_path),
                "store_snapshot": self.tools.snapshot,
                "phase1_system": P2_REFERENCE,
                "phase1_store": runner._display_path(self.phase1.store_path),
                "phase1_recorded": self.recorded,
                "caller": self.caller, "acl": None,
                "filters": self.spec.filters.to_dict(), "as_of_from_item": self.spec.as_of,
                "applicability": self.applicability,
                "dedup": self.dedup if self.spec.dedup else None,
                "dedup_overlay": self.dedup}


def _check_recorded(corpus: str, p1: StoreSystem, lexical_only: bool) -> list[str]:
    """The committed `p1-struct-bc` retrieval summaries of `corpus` that the rebuilt system
    reproduces (`w`, `w_bc`, store snapshot, fingerprint); any other is a `RunError`. A
    lexical-only build is compared with none (the recorded runs are full ones)."""
    if lexical_only:
        return []
    got = {"w": p1.w, "w_bc": p1.index.settings.w_bc, "store_snapshot": p1.index.snapshot,
           "fingerprint": p1.fingerprint}
    checked = []
    for split in ("dev", "test"):
        for path in sorted(PHASE1_SUMMARIES.glob(
                f"{corpus}-{P2_REFERENCE}-{split}-retrieval-*/retrieval.json")):
            cfg = json.loads(path.read_text(encoding="utf-8"))["config"]
            want = {"w": cfg["w"], "w_bc": cfg["settings"]["w_bc"],
                    "store_snapshot": cfg["settings"]["store_snapshot"],
                    "fingerprint": cfg["fingerprint"]}
            differ = [f"{k} {want[k]!r} recorded, {got[k]!r} rebuilt" for k in want
                      if want[k] != got[k]]
            if differ:
                raise runner.RunError(
                    f"{path.parent.name}: the rebuilt {P2_REFERENCE} does not reproduce the "
                    f"recorded run: {'; '.join(differ)}\nfix: restore the Phase 1 store and "
                    f"index the run was made with")
            checked.append(path.parent.name)
    return checked


def _p2_store(corpus: str, loaded: LoadedCorpus, config: dict, p1: StoreSystem):
    """The p2 store, copied from the Phase 1 store when missing and checked as
    `ensure_store` checks a store; it must hold the corpus's documents at the snapshot of
    the Phase 1 index."""
    import shutil

    path = p2_store_dir(config, corpus)
    if not (path / "HEAD").is_file():
        if path.exists():
            raise runner.RunError(f"{path}: exists but holds no store (no HEAD)\nfix: remove "
                                  f"{path} so that it is copied again")
        shutil.copytree(p1.store_path, path, symlinks=True)
    store = _checked_store(path, loaded, "copied")
    want = sorted(d.doc_id for d in loaded.manifest.documents)
    if store.doc_ids() != want or store.snapshot_id != p1.index.snapshot:
        raise runner.RunError(
            f"{path}: holds other documents or another snapshot ({store.snapshot_id[:12]}) "
            f"than the Phase 1 store ({p1.index.snapshot[:12]})\nfix: remove {path} so "
            f"that it is copied again")
    return store


def _ensure_overlays(store, idx) -> tuple[str, str]:
    """(applicability overlay id, dedup overlay id) of the p2 store, derived and written
    when missing (write-once, as `adr applicability derive` and `adr dedup build`)."""
    from adr_store import applicability, dedup
    from adr_store.cli import GOV_CONFIG
    from adr_store.retrieval.index import chunk_content_sha256

    app = applicability.load_overlay(store.path, store.snapshot_id)
    if app is None:
        overlay, report = applicability.derive(
            store, json.loads(GOV_CONFIG.read_text(encoding="utf-8")))
        applicability.write_overlay(store.path, overlay)
        applicability.write_report(store.path, report)
        app = applicability.load_overlay(store.path, store.snapshot_id)
    content = chunk_content_sha256(idx.chunks.values())
    dd = dedup.load_overlay(store.path, store.snapshot_id, idx.chunker, content)
    if dd is None:
        dedup.write_overlay(store.path, dedup.build(list(idx.chunks.values()), idx.snapshot,
                                                    idx.chunker))
        dd = dedup.load_overlay(store.path, store.snapshot_id, idx.chunker, content)
    return app.overlay_id, dd.overlay_id


def _p2_system(name: str):
    spec = P2_SPECS[name]

    def build(corpus: str, loaded: LoadedCorpus, items: list[GoldenItem], groups: Groups,
              config: dict, *, rebuild: bool = False, lexical_only: bool = False) -> P2System:
        from adr_store.tools import ToolError, Tools

        p1 = REGISTRY[P2_REFERENCE](corpus, loaded, items, groups, config, rebuild=rebuild,
                                    lexical_only=lexical_only)
        recorded = _check_recorded(corpus, p1, lexical_only)
        store = _p2_store(corpus, loaded, config, p1)
        emb = runner.REPO_ROOT / config.get("embedding_cache_dir", ".cache/emb")
        try:
            tools = Tools(store.path, emb_cache=emb)
            info = tools.index(P2_REFERENCE, lexical_only=lexical_only,
                               w_bc=p1.index.settings.w_bc,
                               weight=None if lexical_only else p1.w)
        except ToolError as e:
            raise runner.RunError(f"{store.path}: {e}") from e
        if info.fingerprint != p1.fingerprint:
            raise runner.RunError(
                f"{store.path}: the index of {P2_REFERENCE} there has fingerprint "
                f"{info.fingerprint[:12]}, the Phase 1 system's is {p1.fingerprint[:12]}\n"
                f"fix: remove {store.path} so that it is copied again")
        app_id, dedup_id = _ensure_overlays(store, tools.active_index())
        return P2System(name, spec, tools, p1, info.source, app_id, dedup_id, recorded)

    return build


Builder = Callable[..., object]
REGISTRY: dict[str, Builder] = {
    "baseline-rrf": _baseline("baseline-rrf"),
    "baseline-linear": _baseline("baseline-linear"),
    **{name: _store_system(name) for name in SPECS},
}
NAMES = tuple(REGISTRY)  # the Phase 0 and Phase 1 systems
P2_REGISTRY: dict[str, Builder] = {name: _p2_system(name) for name in P2_SPECS}
P2_NAMES = tuple(P2_REGISTRY)
ALL_NAMES = (*NAMES, *P2_NAMES)


def build(name: str, corpus: str, loaded: LoadedCorpus, items: list[GoldenItem],
          groups: Groups, config: dict, *, rebuild: bool = False, lexical_only: bool = False):
    """Build the system `name` for `corpus`; `items` are all golden items (dev ones tune)."""
    builder = REGISTRY.get(name) or P2_REGISTRY.get(name)
    if builder is None:
        raise runner.RunError(f"unknown system {name!r}; expected one of "
                              f"{', '.join(ALL_NAMES)}")
    return builder(corpus, loaded, items, groups, config, rebuild=rebuild,
                   lexical_only=lexical_only)
