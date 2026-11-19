import numpy as np
import pytest

from adr_eval.retrieval.chunker import Chunk, make_chunk_id
from adr_eval.retrieval.dense import DenseIndex


def _c(doc, text):
    return Chunk(make_chunk_id(doc, 0, len(text)), doc, 0, len(text), text)


CHUNKS = [
    _c("a", "Customers may request a refund within thirty days of purchase."),
    _c("b", "The cafeteria serves lunch between noon and two."),
    _c("c", "Shipping rates depend on the destination country."),
]


@pytest.mark.slow
def test_dense_search_semantic_cache_and_hash(tmp_path):
    idx = DenseIndex(cache_dir=tmp_path / "emb")
    idx.build(CHUNKS)
    r = idx.search("how long do I have to get my money back", k=2)
    assert len(r) == 2 and r[0][0] == CHUNKS[0].chunk_id
    assert r == sorted(r, key=lambda h: (-h[1], h[0]))
    assert all(s == round(s, 6) and -1.0 <= s <= 1.0 for _, s in r)
    assert len(list((tmp_path / "emb").rglob("*.npy"))) == 3
    idx2 = DenseIndex(cache_dir=tmp_path / "emb")
    idx2.build(CHUNKS)  # served from the cache
    assert idx2.search("refund", k=3) == idx.search("refund", k=3)
    assert len(idx.model_hash()) == 64 and idx.model_hash() == idx2.model_hash()
    assert np.allclose(np.linalg.norm(idx.vectors, axis=1), 1.0, atol=1e-5)


@pytest.mark.slow
def test_dense_empty(tmp_path):
    idx = DenseIndex(cache_dir=tmp_path / "emb")
    idx.build([])
    assert idx.search("anything") == []


class _FakeModel:
    def query_embed(self, texts):
        return [np.array([1.0, 2.0, 0.0], dtype=np.float32) for _ in texts]


def test_dense_scores_are_the_raw_cosines_search_ranks():
    idx = DenseIndex()
    assert idx.scores("refund") is None
    idx._model = _FakeModel()
    vecs = np.eye(3, dtype=np.float32)
    idx.set_vectors([c.chunk_id for c in CHUNKS], vecs)
    s = idx.scores("refund")
    q = np.array([1.0, 2.0, 0.0]) / np.sqrt(5.0)
    assert s.shape == (3,) and np.allclose(s, vecs @ q)
    want = sorted(((c.chunk_id, round(float(v), 6)) for c, v in zip(CHUNKS, s, strict=True)),
                  key=lambda h: (-h[1], h[0]))
    assert idx.search("refund", k=3) == want
