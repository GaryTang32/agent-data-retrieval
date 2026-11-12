from pathlib import Path

import pytest

from adr_eval.corpora.base import load_corpus
from adr_eval.retrieval.index import HybridIndex

MINI = Path(__file__).parent / "fixtures" / "mini"


@pytest.fixture(scope="module")
def mini_loaded():
    return load_corpus(MINI / "manifest.json", MINI)


@pytest.fixture(scope="module")
def built(mini_loaded):
    return HybridIndex.build(mini_loaded)


@pytest.mark.slow
def test_hybrid_rebuild_same_fingerprint_and_results(mini_loaded, built):
    b = HybridIndex.build(mini_loaded)
    assert built.fingerprint == b.fingerprint and len(built.fingerprint) == 64
    q = "refund deadline"
    assert built.retrieve(q, "baseline-rrf") == b.retrieve(q, "baseline-rrf")
    assert built.chunks and set(built.chunks) == set(b.chunks)


@pytest.mark.slow
def test_retrieve_modes(built):
    rrf_res = built.retrieve("refund deadline", "baseline-rrf", top=5)
    assert 0 < len(rrf_res) <= 5
    assert all(cid in built.chunks for cid, _ in rrf_res)
    lin = built.retrieve("refund deadline", "baseline-linear", w=0.5)
    assert lin
    with pytest.raises(ValueError):
        built.retrieve("refund", "baseline-linear")
    with pytest.raises(ValueError):
        built.retrieve("refund", "nope")
    # all-stopword query: lexical empty, fusion still returns dense results
    assert built.retrieve("the of and", "baseline-rrf")


@pytest.mark.slow
def test_save_load_roundtrip(tmp_path, built):
    built.save(tmp_path / "idx")
    loaded = HybridIndex.load(tmp_path / "idx")
    assert loaded.fingerprint == built.fingerprint and loaded.chunks == built.chunks
    for q in ("refund deadline", "shipping"):
        assert loaded.retrieve(q, "baseline-rrf") == built.retrieve(q, "baseline-rrf")
        assert loaded.retrieve(q, "baseline-linear", w=0.3) == built.retrieve(
            q, "baseline-linear", w=0.3
        )


@pytest.mark.slow
def test_load_rejects_tampered_index(tmp_path, built):
    import json

    built.save(tmp_path / "idx")
    meta_p = tmp_path / "idx" / "meta.json"
    meta = json.loads(meta_p.read_text())
    meta["fingerprint"] = "0" * 64
    meta_p.write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="fingerprint"):
        HybridIndex.load(tmp_path / "idx")


@pytest.mark.slow
def test_save_load_keeps_unicode_line_separators_in_chunk_text(tmp_path, built):
    """PDF text can hold U+2028; a saved chunk containing it must load as one line."""
    from dataclasses import replace

    first = next(iter(built.chunks))
    chunks = {**built.chunks, first: replace(built.chunks[first], text="a\u2028b\u2029c\x85d")}
    HybridIndex(built.snapshot, chunks, built.bm25, built.dense).save(tmp_path / "idx")
    assert HybridIndex.load(tmp_path / "idx").chunks == chunks


@pytest.mark.slow
def test_load_rejects_dense_rows_that_do_not_match_the_chunks(tmp_path, built):
    import numpy as np

    built.save(tmp_path / "idx")
    vectors = np.load(tmp_path / "idx" / "dense.npy")
    np.save(tmp_path / "idx" / "dense.npy", vectors[:-1])  # a truncated file
    with pytest.raises(ValueError, match=r"dense\.npy has 6 rows.*7 chunks"):
        HybridIndex.load(tmp_path / "idx")
