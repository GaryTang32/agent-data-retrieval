"""Retrieval over store chunks (spec §8, §12 fourth bullet), with fake models."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from adr_eval.corpora.base import load_corpus
from adr_eval.retrieval.fusion import linear, rrf
from adr_eval.retrieval.lexical import BM25Index
from adr_store.chunking import chunk_store, chunker_config
from adr_store.embedding import EmbeddingCache
from adr_store.retrieval import Settings, StoreIndex
from adr_store.retrieval.index import CHANNEL_K, fingerprint
from adr_store.retrieval.lexical import FieldBM25, indexed_text
from adr_store.retrieval.rerank import RERANK_TOP, CrossEncoderReranker
from adr_store.store import Store

FIXTURES = Path(__file__).parents[1] / "fixtures"
MINI = FIXTURES / "mini"
GUIDE = (FIXTURES / "store" / "guide.md").read_bytes()
QUERIES = ["refund deadline", "escalation steps for a complaint", "field guide",
           "the of and", "permit", "zzz-unknown-word"]


def fake_vector(text: str) -> np.ndarray:
    seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
    return np.random.default_rng(seed).normal(size=8)


class Recorder:
    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, texts):
        self.calls.append(list(texts))
        return [fake_vector(t) for t in texts]


def fake_cache(path: Path, model_hash: str = "a" * 64) -> EmbeddingCache:
    return EmbeddingCache(path, "fake/model", embedder=Recorder(), model_hash=model_hash, dim=8)


class FakeScorer:
    """Score = number of query words in the text, so ties are common; records every call."""

    def __init__(self):
        self.calls: list[tuple[str, list[str]]] = []

    def __call__(self, query: str, texts: list[str]):
        self.calls.append((query, list(texts)))
        words = set(query.lower().split())
        return [sum(w in words for w in t.lower().split()) / 3 for t in texts]


def fake_reranker(model_hash: str = "c" * 64) -> CrossEncoderReranker:
    return CrossEncoderReranker(scorer=FakeScorer(), model_hash=model_hash)


@pytest.fixture(scope="module")
def mini_store(tmp_path_factory) -> Store:
    corpus = load_corpus(MINI / "manifest.json", MINI)
    path = tmp_path_factory.mktemp("mini") / "store"
    s = Store.create(path)
    for d in sorted(corpus.manifest.documents, key=lambda d: d.doc_id):
        s.add(corpus.docs[d.doc_id], (corpus.root / d.path).read_bytes())
    s.commit()
    return Store.open(path)


def build(store, tmp_path, settings: Settings | None = None, **kw) -> StoreIndex:
    settings = settings or Settings()
    kw.setdefault("cache", fake_cache(tmp_path / "emb"))
    if settings.rerank:
        kw.setdefault("reranker", fake_reranker())
    return StoreIndex.build(store, settings, **kw)


# --- lexical -------------------------------------------------------------------------------


def test_field_weight_zero_equals_plain_bm25_on_the_same_chunks(mini_store, tmp_path):
    chunks = chunk_store(mini_store)
    plain = BM25Index()
    plain.build(chunks)
    field = FieldBM25(0)
    field.build(chunks)
    idx = build(mini_store, tmp_path)
    for q in QUERIES:
        assert field.search(q) == plain.search(q) == idx.lexical_hits(q, k=100)


def test_breadcrumb_tokens_are_repeated_w_bc_times_without_changing_chunk_text(mini_store,
                                                                               tmp_path):
    chunks = chunk_store(mini_store)
    c = next(c for c in chunks if " > " in c.breadcrumb)
    assert indexed_text(c, 0) == c.text
    assert indexed_text(c, 2) == f"{c.text} {c.breadcrumb} {c.breadcrumb}"
    idx = build(mini_store, tmp_path, Settings(w_bc=2))
    assert idx.chunks[c.chunk_id] == c
    assert idx.lexical.config()["w_bc"] == 2


def test_breadcrumb_weight_makes_section_titles_findable(tmp_path):
    from tests.store.test_chunking import doc, make_store

    s = make_store(tmp_path / "s", doc(GUIDE, "md"))
    in_body = {cid for cid, _ in build(s, tmp_path).lexical_hits("field guide")}
    weighted = build(s, tmp_path, Settings(w_bc=1)).lexical_hits("field guide")
    assert in_body < {cid for cid, _ in weighted}


@pytest.mark.parametrize("bad", [-1, 1.0, True, "2", None])
def test_settings_are_validated(bad):
    with pytest.raises(ValueError):
        Settings(w_bc=bad)
    with pytest.raises(ValueError):
        Settings(prefix=1)


# --- dense, fusion, rerank -------------------------------------------------------------------


def test_dense_search_is_exact_cosine_rounded_with_ties_by_chunk_id(mini_store, tmp_path):
    idx = build(mini_store, tmp_path)
    ids = list(idx.chunks)
    vecs = np.stack([fake_vector(idx.chunks[i].text) for i in ids])
    vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
    q = fake_vector("refund deadline")
    q = q / np.linalg.norm(q)
    want = sorted(((i, round(float(v @ q), 6)) for i, v in zip(ids, vecs, strict=True)),
                  key=lambda h: (-h[1], h[0]))
    assert idx.dense_hits("refund deadline") == want[:CHANNEL_K]


def test_the_prefix_setting_embeds_breadcrumb_newline_body(mini_store, tmp_path):
    cache = fake_cache(tmp_path / "emb")
    build(mini_store, tmp_path, Settings(prefix=True), cache=cache)
    chunks = sorted(chunk_store(mini_store), key=lambda c: c.chunk_id)
    assert cache._embedder.calls[0] == [f"{c.breadcrumb}\n{c.text}" for c in chunks]
    plain = fake_cache(tmp_path / "emb")
    build(mini_store, tmp_path, Settings(), cache=plain)
    assert plain._embedder.calls[0] == [c.text for c in chunks]


def test_retrieve_is_the_baselines_fusion_of_both_channels(mini_store, tmp_path):
    idx = build(mini_store, tmp_path, Settings(w_bc=1, prefix=True))
    for q in QUERIES:
        lex, den = idx.lexical_hits(q), idx.dense_hits(q)
        assert idx.retrieve(q, w=0.35) == linear(lex, den, 0.35, top=10)
        assert idx.retrieve(q, fusion="rrf") == rrf([lex, den], k=60, top=10)
    with pytest.raises(ValueError, match="weight"):
        idx.retrieve("refund")
    with pytest.raises(ValueError, match="fusion"):
        idx.retrieve("refund", fusion="max")


def test_a_lexical_only_index_embeds_nothing_and_ranks_by_bm25(mini_store, tmp_path):
    cache = fake_cache(tmp_path / "emb")
    idx = build(mini_store, tmp_path, Settings(w_bc=1), cache=cache, dense=False)
    assert cache._embedder.calls == [] and idx.dense is None and idx.embedding is None
    for q in QUERIES:
        assert idx.retrieve(q) == idx.lexical_hits(q)[:10]
    with pytest.raises(ValueError, match="dense"):
        idx.dense_hits("refund")


def test_rerank_scores_the_top_fused_candidates_and_breaks_ties_by_chunk_id(mini_store,
                                                                            tmp_path):
    idx = build(mini_store, tmp_path, Settings(prefix=True, rerank=True))
    scorer = idx.reranker._scorer
    q = "refund within thirty days"
    fused = linear(idx.lexical_hits(q), idx.dense_hits(q), 0.5, top=RERANK_TOP)
    hits = idx.retrieve(q, w=0.5)
    query, texts = scorer.calls[-1]
    ids = sorted(cid for cid, _ in fused)
    assert query == q and texts == [f"{idx.chunks[i].breadcrumb}\n{idx.chunks[i].text}"
                                    for i in ids]
    assert len(hits) == min(10, len(ids))
    assert hits == sorted(hits, key=lambda h: (-h[1], h[0]))
    assert all(s == round(s, 6) for _, s in hits)


def test_the_reranker_is_a_pure_function_of_its_inputs():
    cands = [(f"{i:064x}", t) for i, t in enumerate(
        ["refund policy text", "shipping rates", "refund deadline thirty days", "other",
         "refund"])]
    a, b = fake_reranker(), fake_reranker()
    first = a.rerank("refund deadline", cands)
    assert first == a.rerank("refund deadline", cands) == b.rerank("refund deadline",
                                                                   cands[::-1])
    assert a._scorer.calls[0] == a._scorer.calls[1] == b._scorer.calls[0]  # chunk-id order
    assert [cid for cid, _ in first][:2] == [cands[2][0], cands[0][0]]
    tied = [cid for cid, s in first if s == first[-1][1]]
    assert tied == sorted(tied)
    assert a.rerank("refund deadline", cands, top=2) == first[:2]
    assert a.rerank("q", []) == []
    with pytest.raises(ValueError, match="2 candidates"):
        CrossEncoderReranker(scorer=lambda q, t: [1.0], model_hash="c" * 64).rerank(
            "q", cands[:2])


# --- fingerprint, save and load ------------------------------------------------------------


def test_fingerprint_changes_when_any_input_changes(mini_store, tmp_path):
    chunks = [c.chunk_id for c in chunk_store(mini_store)]
    base = dict(snapshot="s" * 64, chunker=chunker_config(), settings=Settings(),
                lexical=FieldBM25(0), embedding=("fake/model", "a" * 64), reranker=None,
                chunk_ids=chunks)
    variants = [
        dict(snapshot="t" * 64),
        dict(chunker=chunker_config(max_tokens=300)),
        dict(chunker=chunker_config(min_tokens=0)),
        dict(settings=Settings(w_bc=1), lexical=FieldBM25(1)),
        dict(settings=Settings(prefix=True)),
        dict(settings=Settings(rerank=True), reranker=fake_reranker()),
        dict(lexical=FieldBM25(0, k1=1.5)),
        dict(lexical=FieldBM25(0, b=0.5)),
        dict(embedding=("fake/model", "b" * 64)),
        dict(embedding=("other/model", "a" * 64)),
        dict(embedding=None),
        dict(chunk_ids=chunks[:-1]),
    ]
    prints = {fingerprint(**base)} | {fingerprint(**{**base, **v}) for v in variants}
    assert len(prints) == 1 + len(variants)
    reranked = {**base, "settings": Settings(rerank=True)}
    a = fingerprint(**{**reranked, "reranker": fake_reranker("c" * 64)})
    b = fingerprint(**{**reranked, "reranker": fake_reranker("d" * 64)})
    assert a != b
    assert fingerprint(**{**base, "chunk_ids": chunks[::-1]}) == fingerprint(**base)


def test_index_fingerprint_follows_the_store_snapshot_and_settings(mini_store, tmp_path):
    from tests.store.test_chunking import doc, make_store

    idx = build(mini_store, tmp_path)
    assert len(idx.fingerprint) == 64 and idx.fingerprint == build(mini_store, tmp_path).fingerprint
    other = make_store(tmp_path / "other", doc(GUIDE, "md"))
    assert build(other, tmp_path).fingerprint != idx.fingerprint
    assert idx.with_w_bc(2).fingerprint == build(mini_store, tmp_path,
                                                 Settings(w_bc=2)).fingerprint
    assert build(mini_store, tmp_path, max_tokens=50).fingerprint != idx.fingerprint
    assert build(mini_store, tmp_path, cache=fake_cache(tmp_path / "e2", "b" * 64)
                 ).fingerprint != idx.fingerprint


def test_expected_fingerprint_needs_no_embedding(mini_store, tmp_path):
    for settings in (Settings(), Settings(w_bc=3, prefix=True, rerank=True)):
        cache = fake_cache(tmp_path / "emb")
        rr = fake_reranker()
        expected = StoreIndex.expected_fingerprint(mini_store, settings, cache, rr)
        assert cache._embedder.calls == [] and rr._scorer.calls == []
        assert expected == build(mini_store, tmp_path, settings, cache=cache,
                                 reranker=rr).fingerprint
    assert StoreIndex.expected_fingerprint(mini_store, Settings(), dense=False) == build(
        mini_store, tmp_path, dense=False).fingerprint


@pytest.mark.parametrize("settings,dense", [(Settings(), True),
                                            (Settings(w_bc=2, prefix=True, rerank=True), True),
                                            (Settings(w_bc=1), False)])
def test_save_and_load_give_identical_ranked_lists(mini_store, tmp_path, settings, dense):
    idx = build(mini_store, tmp_path, settings, dense=dense)
    idx.save(tmp_path / "idx")
    loaded = StoreIndex.load(tmp_path / "idx", cache=fake_cache(tmp_path / "other-emb"),
                             reranker=fake_reranker())
    assert loaded.fingerprint == idx.fingerprint and loaded.chunks == idx.chunks
    for q in QUERIES:
        if dense:
            assert loaded.retrieve(q, w=0.4) == idx.retrieve(q, w=0.4)
            assert loaded.retrieve(q, fusion="rrf") == idx.retrieve(q, fusion="rrf")
        else:
            assert loaded.retrieve(q) == idx.retrieve(q)


def test_load_refuses_a_tampered_or_truncated_index(mini_store, tmp_path):
    idx = build(mini_store, tmp_path)
    idx.save(tmp_path / "idx")
    meta_p = tmp_path / "idx" / "meta.json"
    meta = json.loads(meta_p.read_text())
    meta_p.write_text(json.dumps({**meta, "fingerprint": "0" * 64}))
    with pytest.raises(ValueError, match="fingerprint"):
        StoreIndex.load(tmp_path / "idx", cache=fake_cache(tmp_path / "emb"))
    idx.save(tmp_path / "idx")
    np.save(tmp_path / "idx" / "dense.npy", idx.dense.vectors[:-1])
    with pytest.raises(ValueError, match="rows"):
        StoreIndex.load(tmp_path / "idx", cache=fake_cache(tmp_path / "emb"))
    idx.save(tmp_path / "idx")
    with pytest.raises(ValueError, match="fingerprint"):  # another embedding model
        StoreIndex.load(tmp_path / "idx", cache=fake_cache(tmp_path / "emb", "b" * 64))


def test_saved_chunks_keep_their_breadcrumbs_and_element_ids(mini_store, tmp_path):
    """Including text with Unicode line separators (PDF text can hold them)."""
    idx = build(mini_store, tmp_path)
    first = next(iter(idx.chunks))
    idx.chunks[first] = replace(idx.chunks[first], text="a\u2028b", breadcrumb="x\u2029y")
    idx.save(tmp_path / "idx")
    loaded = StoreIndex.load(tmp_path / "idx", cache=fake_cache(tmp_path / "emb"))
    assert loaded.chunks == idx.chunks and isinstance(loaded.chunks[first].element_ids, tuple)


@pytest.mark.slow
def test_the_real_cross_encoder_is_a_pure_function_of_its_inputs():
    texts = ["Customers may request a refund within thirty days of purchase.",
             "The cafeteria serves lunch between noon and two.",
             "Shipping rates depend on the destination country."]
    cands = [(hashlib.sha256(t.encode()).hexdigest(), t) for t in texts]
    rr = CrossEncoderReranker()
    first = rr.rerank("How long do I have to ask for a refund?", cands)
    again = CrossEncoderReranker().rerank("How long do I have to ask for a refund?",
                                          cands[::-1])
    assert first == again and first[0][0] == cands[0][0]
    assert len(rr.model_hash) == 64 and rr.config()["model"] == "Xenova/ms-marco-MiniLM-L-6-v2"
