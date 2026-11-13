"""The embedding cache (spec §8 "Embedding cache"): keyed by text and model hash."""

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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


class FakeModel:
    """The two fastembed methods the dense path calls, over given embedder functions
    (`query` defaults to `passage`)."""

    def __init__(self, passage, query=None):
        self.passage, self.query = passage, query or passage

    def passage_embed(self, texts, batch_size: int = 32):
        return self.passage(list(texts))

    def query_embed(self, texts):
        return self.query(list(texts))


def fake_cache(path, model_hash="a" * 64) -> tuple[EmbeddingCache, FakeEmbedder]:
    fake = FakeEmbedder()
    return EmbeddingCache(path, "fake/model", model=FakeModel(fake), model_hash=model_hash,
                          dim=8), fake


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
    cache = EmbeddingCache(tmp_path, "fake/model", model_hash="a" * 64, dim=4,
                           model=FakeModel(lambda texts: iter([np.ones(4)])))
    with pytest.raises(ValueError, match="2 texts"):
        cache.embed_texts(["alpha", "beta"])


def test_a_leftover_temporary_name_does_not_block_a_write(tmp_path):
    """Each write goes through its own temporary file: a directory squatting on a fixed
    temporary name (what a concurrent writer's file would be) is not in the way."""
    cache, _ = fake_cache(tmp_path)
    p = cache.path("alpha")
    p.parent.mkdir(parents=True)
    (p.parent / f".{p.stem}.tmp.npy").mkdir()
    vecs, n_new = cache.embed_texts(["alpha"])
    assert n_new == 1 and np.array_equal(np.load(p), vecs[0])
    assert sorted(x.name for x in p.parent.iterdir()) == sorted([p.name, f".{p.stem}.tmp.npy"])


def test_concurrent_writers_of_the_same_keys_do_not_crash(tmp_path):
    texts = [f"text {i}" for i in range(40)]
    barrier = threading.Barrier(8)

    def work(_):
        cache, _ = fake_cache(tmp_path)
        barrier.wait()
        return cache.embed_texts(texts)[0]

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(work, range(8)))
    assert all(np.array_equal(r, results[0]) for r in results)
    assert not [p for p in tmp_path.rglob("*") if p.is_file() and "tmp" in p.name]


def _bad_files(path: Path) -> dict[str, bytes | np.ndarray]:
    good = np.ones(8, dtype=np.float32) / np.sqrt(8)
    return {
        "truncated": path.read_bytes()[:-5],
        "empty": b"",
        "wrong shape": good.reshape(2, 4),
        "wrong dimension": np.ones(4, dtype=np.float32) / 2,
        "float64": good.astype(np.float64),
        "not unit": good * 2,
        "not finite": np.full(8, np.nan, dtype=np.float32),
    }


@pytest.mark.parametrize("kind", ["truncated", "empty", "wrong shape", "wrong dimension",
                                  "float64", "not unit", "not finite"])
def test_a_bad_cache_file_is_deleted_re_embedded_and_counted_as_new(tmp_path, kind):
    cache, fake = fake_cache(tmp_path)
    good, _ = cache.embed_texts(["alpha", "beta"])
    p = cache.path("alpha")
    bad = _bad_files(p)[kind]
    if isinstance(bad, bytes):
        p.write_bytes(bad)
    else:
        np.save(p, bad)
    vecs, n_new = cache.embed_texts(["alpha", "beta"])
    assert n_new == 1 and fake.calls[-1] == ["alpha"]
    assert np.array_equal(vecs, good) and np.array_equal(np.load(p), good[0])


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


# -- threads (`adr index --threads`) -------------------------------------------------------


class RecordingTextEmbedding:
    """Stands in for fastembed's TextEmbedding: records how it was made."""

    made: list[dict] = []

    def __init__(self, model_name, cache_dir=None, threads=None):
        RecordingTextEmbedding.made.append({"model": model_name, "cache_dir": cache_dir,
                                            "threads": threads})


@pytest.mark.parametrize(("threads", "passed"), [(2, 2), (4, 4), (0, None)])
def test_threads_other_than_one_load_a_model_with_that_setting(tmp_path, monkeypatch,
                                                               threads, passed):
    import fastembed

    RecordingTextEmbedding.made = []
    monkeypatch.setattr(fastembed, "TextEmbedding", RecordingTextEmbedding)
    cache = EmbeddingCache(tmp_path, "BAAI/bge-small-en-v1.5", model_cache_dir=tmp_path / "m",
                           threads=threads)
    m = cache.model()
    assert cache.model() is m  # loaded once
    assert RecordingTextEmbedding.made == [{"model": "BAAI/bge-small-en-v1.5",
                                            "cache_dir": str(tmp_path / "m"),
                                            "threads": passed}]


def test_one_thread_uses_the_baseline_model(tmp_path, monkeypatch):
    sentinel = object()
    monkeypatch.setattr(DenseIndex, "_get_model", lambda self: sentinel)
    assert EmbeddingCache(tmp_path, "BAAI/bge-small-en-v1.5").model() is sentinel
    assert EmbeddingCache(tmp_path, "BAAI/bge-small-en-v1.5", threads=1).model() is sentinel


def test_threads_do_not_change_the_cache_key(tmp_path):
    one = EmbeddingCache(tmp_path, "fake/model", model_hash="a" * 64, dim=8, threads=1)
    four = EmbeddingCache(tmp_path, "fake/model", model_hash="a" * 64, dim=8, threads=4)
    assert one.path("some text") == four.path("some text")


def test_a_negative_thread_count_is_refused(tmp_path):
    with pytest.raises(ValueError, match="threads"):
        EmbeddingCache(tmp_path, threads=-1)


@pytest.mark.slow
@pytest.mark.parametrize("threads", [2, 0])
def test_other_thread_counts_give_the_same_vectors_as_one(tmp_path, threads):
    """The model is fetched as for `test_vectors_equal_the_baseline_dense_index` (the default
    model store, downloaded when it is not there)."""
    texts = ["Customers may request a refund within thirty days of purchase.",
             "Doc > Refunds\nThe cafeteria serves lunch between noon and two.",
             "Shipping rates depend on the destination country. " * 40,
             "x"]
    one, n1 = EmbeddingCache(tmp_path / "one", threads=1).embed_texts(texts)
    other, n2 = EmbeddingCache(tmp_path / "other", threads=threads).embed_texts(texts)
    assert n1 == n2 == 4 and one.dtype == other.dtype == np.float32
    assert np.array_equal(one, other)
