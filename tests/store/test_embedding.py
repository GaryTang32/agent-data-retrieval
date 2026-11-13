"""The embedding cache (spec §8 "Embedding cache"): keyed by text and model hash."""

import hashlib

import numpy as np
import pytest

from adr_eval.retrieval.chunker import Chunk, make_chunk_id
from adr_eval.retrieval.dense import DenseIndex
from adr_store.embedding import EmbeddingCache


class FakeEmbedder:
    """Deterministic, not unit-length vectors from the text's hash; records every call."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, texts):
        self.calls.append(list(texts))
        for t in texts:
            seed = int(hashlib.sha256(t.encode()).hexdigest()[:8], 16)
            yield np.random.default_rng(seed).normal(size=8) * 3.0


def fake_cache(path, model_hash="a" * 64) -> tuple[EmbeddingCache, FakeEmbedder]:
    fake = FakeEmbedder()
    return EmbeddingCache(path, "fake/model", embedder=fake, model_hash=model_hash), fake


def test_vectors_are_unit_float32_rows_in_input_order(tmp_path):
    cache, _ = fake_cache(tmp_path)
    texts = ["alpha", "beta", "gamma"]
    vecs, n_new = cache.embed_texts(texts)
    assert n_new == 3 and vecs.dtype == np.float32 and vecs.shape == (3, 8)
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-6)
    alone = [cache.embed_texts([t])[0][0] for t in texts]
    assert all(np.array_equal(vecs[i], alone[i]) for i in range(3))


def test_a_rerun_computes_nothing_and_gives_the_same_vectors(tmp_path):
    first, _ = fake_cache(tmp_path)
    vecs, n_new = first.embed_texts(["alpha", "beta"])
    again, fake = fake_cache(tmp_path)
    vecs2, n_new2 = again.embed_texts(["beta", "alpha"])
    assert (n_new, n_new2) == (2, 0) and fake.calls == []
    assert np.array_equal(vecs2, vecs[::-1])


def test_only_new_texts_are_embedded_and_duplicates_once(tmp_path):
    cache, fake = fake_cache(tmp_path)
    cache.embed_texts(["alpha"])
    vecs, n_new = cache.embed_texts(["alpha", "beta", "beta", "gamma"])
    assert n_new == 2 and fake.calls[-1] == ["beta", "gamma"]
    assert np.array_equal(vecs[1], vecs[2])


def test_the_key_is_the_exact_text_and_the_model_hash(tmp_path):
    cache, _ = fake_cache(tmp_path)
    assert cache.embed_texts(["alpha", "alpha ", "Alpha"])[1] == 3
    other, fake = fake_cache(tmp_path, model_hash="b" * 64)
    assert other.embed_texts(["alpha"])[1] == 1 and fake.calls == [["alpha"]]
    files = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")
                   if p.is_file())
    key = hashlib.sha256(b"alpha").hexdigest()
    assert f"fake--model/{'a' * 64}/{key[:2]}/{key}.npy" in files
    assert f"fake--model/{'b' * 64}/{key[:2]}/{key}.npy" in files
    assert len(files) == 4 and not [f for f in files if "tmp" in f]


def test_empty_input(tmp_path):
    cache, fake = fake_cache(tmp_path)
    vecs, n_new = cache.embed_texts([])
    assert vecs.shape == (0, 0) and vecs.dtype == np.float32 and n_new == 0
    assert fake.calls == []


def test_the_embedder_must_return_one_vector_per_text(tmp_path):
    cache = EmbeddingCache(tmp_path, "fake/model", model_hash="a" * 64,
                           embedder=lambda texts: iter([np.ones(4)]))
    with pytest.raises(ValueError, match="2 texts"):
        cache.embed_texts(["alpha", "beta"])


@pytest.mark.slow
def test_vectors_equal_the_baseline_dense_index(tmp_path):
    texts = ["Customers may request a refund within thirty days of purchase.",
             "Doc > Refunds\nThe cafeteria serves lunch between noon and two.",
             "Shipping rates depend on the destination country. " * 40]
    chunks = [Chunk(make_chunk_id("d", i, i + 1), "d", i, i + 1, t) for i, t in enumerate(texts)]
    dense = DenseIndex(cache_dir=tmp_path / "dense")
    dense.build(chunks)
    cache = EmbeddingCache(tmp_path / "store-emb", dense.model_name)
    vecs, n_new = cache.embed_texts(texts)
    assert n_new == 3 and np.array_equal(vecs, dense.vectors)
    assert cache.model_hash == dense.model_hash()
    vecs2, n_new2 = EmbeddingCache(tmp_path / "store-emb", dense.model_name).embed_texts(texts)
    assert n_new2 == 0 and np.array_equal(vecs2, vecs)
