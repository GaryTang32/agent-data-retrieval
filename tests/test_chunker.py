from importlib import resources

from adr_eval.corpora.base import Document
from adr_eval.retrieval.chunker import CHUNKER_CONFIG, TOKENIZER_CONFIG, chunk_document, tokenize

PARA = " ".join(f"word{i}" for i in range(120))
LONG_TEXT = "\n\n".join(PARA + ". Tail sentence here." for _ in range(12))
LONG_DOC = Document("d", LONG_TEXT, "html", "v", "u")


def test_chunks_cover_text_exactly_without_overlap():
    cs = chunk_document(LONG_DOC)
    assert len(cs) > 1
    assert all(LONG_DOC.text[c.char_start : c.char_end] == c.text for c in cs)
    assert all(a.char_end <= b.char_start for a, b in zip(cs, cs[1:], strict=False))
    assert all(len(tokenize(c.text, drop_stopwords=False)) <= 400 for c in cs)
    assert len({c.chunk_id for c in cs}) == len(cs)


def test_small_doc_is_one_chunk_and_trimmed():
    cs = chunk_document(Document("d", "  hello world.\n", "html", "v", "u"))
    assert [c.text for c in cs] == ["hello world."]


def test_whitespace_doc_has_no_chunks():
    assert chunk_document(Document("d", " \n\f\n ", "pdf", "v", "u")) == []
    assert chunk_document(Document("d", "", "pdf", "v", "u")) == []


def test_oversized_unseparated_run_is_split_within_limit():
    text = "-".join(f"t{i}" for i in range(1000))
    doc = Document("d", text, "html", "v", "u")
    cs = chunk_document(doc)
    assert len(cs) >= 3
    assert all(doc.text[c.char_start : c.char_end] == c.text for c in cs)
    assert all(len(tokenize(c.text, drop_stopwords=False)) <= 400 for c in cs)


def test_custom_max_tokens_and_config():
    cs = chunk_document(LONG_DOC, max_tokens=50)
    assert all(len(tokenize(c.text, drop_stopwords=False)) <= 50 for c in cs)
    assert CHUNKER_CONFIG["max_tokens"] == 400


def test_tokenizer_applies_nfkc_and_ligatures():
    assert tokenize("Speciﬁc § 1026.18 Rules") == ["specific", "1026", "18", "rules"]


def test_tokenizer_stopwords_optional_and_packaged():
    assert tokenize("The refund of the fee") == ["refund", "fee"]
    assert tokenize("The fee", drop_stopwords=False) == ["the", "fee"]
    res = resources.files("adr_eval.retrieval").joinpath("stopwords_en.txt")
    assert res.is_file() and TOKENIZER_CONFIG["stopwords"].endswith("stopwords_en.txt")


def _assert_within_limit(doc, limit=400):
    cs = chunk_document(doc, max_tokens=limit)
    assert cs
    assert all(doc.text[c.char_start : c.char_end] == c.text for c in cs)
    assert all(a.char_end <= b.char_start for a, b in zip(cs, cs[1:], strict=False))
    assert all(len(tokenize(c.text, drop_stopwords=False)) <= limit for c in cs)
    return cs


def test_uppercase_separator_free_run_respects_limit():
    doc = Document("d", "-".join("ABC" for _ in range(1000)), "html", "v", "u")
    assert len(_assert_within_limit(doc)) >= 3


def test_nfkc_expanding_separator_free_run_respects_limit():
    # "x²" -> "x2" (one token each); "Ⅻ" -> "XII"; "ﬁ" -> "fi"
    for unit in ("x²-", "Ⅻ-", "ﬁ²Ⅻ-"):
        doc = Document("d", unit * 900, "html", "v", "u")
        assert len(_assert_within_limit(doc)) >= 2
    doc = Document("d", "".join(f"A²{i}-" for i in range(900)), "html", "v", "u")
    _assert_within_limit(doc, limit=50)
