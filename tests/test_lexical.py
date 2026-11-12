from adr_eval.corpora.base import Document
from adr_eval.retrieval.chunker import Chunk, chunk_document, make_chunk_id
from adr_eval.retrieval.lexical import BM25Index


def _chunk(doc_id, text):
    return Chunk(make_chunk_id(doc_id, 0, len(text)), doc_id, 0, len(text), text)


TWO_IDENTICAL = [_chunk("a", "refund policy applies"), _chunk("b", "refund policy applies")]
SOME = [_chunk("a", "refund policy"), _chunk("b", "shipping rates table"), _chunk("c", "x")]


def test_bm25_deterministic_and_tiebreak():
    idx = BM25Index()
    idx.build(TWO_IDENTICAL)
    r = idx.search("refund policy", k=10)
    assert len(r) == 2 and r[0][1] == r[1][1]
    assert r == idx.search("refund policy", k=10)
    assert [c for c, _ in r] == sorted(c for c, _ in r)


def test_bm25_all_stopwords_returns_empty():
    idx = BM25Index()
    idx.build(SOME)
    assert idx.search("the of and", k=10) == []


def test_bm25_ranking_oov_zero_exclusion_and_rounding():
    idx = BM25Index()
    idx.build(SOME)
    r = idx.search("refund zzzunknown", k=10)
    assert [c for c, _ in r] == [SOME[0].chunk_id]
    assert r[0][1] == round(r[0][1], 6) > 0
    assert idx.search("zzzunknown") == []
    assert len(idx.search("refund shipping", k=1)) == 1


def test_bm25_tiny_and_empty_corpora():
    idx = BM25Index()
    idx.build([])
    assert idx.search("refund") == []
    idx.build([_chunk("a", "the of")])  # no indexable tokens
    assert idx.search("refund") == []
    idx.build([_chunk("a", "refund")])
    assert [c for c, _ in idx.search("refund", k=100)] == [make_chunk_id("a", 0, 6)]


def test_bm25_config_and_chunk_pipeline():
    cfg = BM25Index().config()
    assert cfg["library"] == "bm25s" and cfg["version"] and cfg["k1"] == 1.2 and cfg["b"] == 0.75
    doc = Document("d", "Alpha beta.\n\nGamma delta.", "html", "v", "u")
    idx = BM25Index()
    idx.build(chunk_document(doc))
    assert idx.search("gamma")
