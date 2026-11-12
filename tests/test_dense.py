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
