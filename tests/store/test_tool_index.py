"""The tool index (Phase 2 spec §8.2): fielded BM25 and dense texts, linear fusion, per-view
statistics, persistence and determinism. A fixture catalog of the hand-made, reference-server
and ToolRet-shaped tools; the fake embedder for dense; nothing reads `data/` or `.cache/`."""

import json
import math

import pytest

from adr_eval.retrieval.dense import _unit
from adr_eval.retrieval.fusion import linear
from adr_store import tool_catalog
from adr_store.retrieval.dense import row_scores
from adr_store.retrieval.index import CHANNEL_K
from adr_store.retrieval.lexical import FieldBM25
from adr_store.retrieval.tool_index import (
    ToolIndex,
    bm25_texts,
    dense_text,
    split_name,
    summary,
    tool_view_id,
)
from adr_store.tool_catalog import ToolCatalog
from tests.store.test_retrieval import fake_cache
from tests.store.test_tool_records import (
    FIX,
    REF_SERVERS,
    by_name,
    handmade_openapi,
    mcp_records,
    sample_tools,
    toolret_record,
)

QUERIES = ["git status of the working tree", "weather forecast for a city", "delete a note",
           "convert currency amount", "add a node to a tree", "current time in a timezone",
           "fetch a url", "zzz-nothing", "the of and"]


def fixture_records():
    recs = mcp_records(FIX / "mcp" / "handmade.json") + handmade_openapi()
    for server in REF_SERVERS:
        recs += mcp_records(next((FIX / "mcp").glob(f"{server}-*.json")))
    recs += [toolret_record(r) for r in sample_tools()]
    return recs


def make_catalog(path, recs=None) -> ToolCatalog:
    tool_catalog.ensure_store(path)
    cat = ToolCatalog.create(path)
    for r in fixture_records() if recs is None else recs:
        cat.add(r)
    cat.commit()
    return ToolCatalog.open(path)


@pytest.fixture
def catalog(tmp_path):
    return make_catalog(tmp_path / "store")


@pytest.fixture
def cache(tmp_path):
    return fake_cache(tmp_path / "emb")


# -- texts -------------------------------------------------------------------------------------

@pytest.mark.parametrize("name,split", [
    ("Skyline_Weather_Current", "Skyline Weather Current"),
    ("getCurrentTime", "get Current Time"),
    ("HTTPServerList", "HTTP Server List"),
    ("git_diff_unstaged", "git diff unstaged"),
    ("delete_trees_treeId_nodes_id", "delete trees tree Id nodes id"),
    ("plain", "plain"),
    ("__x__", "x"),
])
def test_split_name_on_case_and_underscores(name, split):
    assert split_name(name) == split


def test_bm25_and_dense_texts():
    recs = by_name(mcp_records(FIX / "mcp" / "handmade.json"))
    rec = recs["search_notes"]
    name_text, body = bm25_texts(rec)
    assert name_text == "search notes"
    props = rec.input_schema["properties"]
    assert body.startswith(rec.description)
    for p, schema in props.items():
        assert p in body and schema.get("description", "") in body
    d = dense_text(rec)
    assert d.startswith(f"search_notes: {rec.description}")
    assert "Parameters: query" in d and d.count("(") == sum(
        1 for s in props.values() if s.get("description"))
    bare = recs["list_notebooks"]  # no parameters
    assert dense_text(bare) == f"list_notebooks: {bare.description}"
    empty = by_name(handmade_openapi())["get_health"]  # no description, no parameters
    assert dense_text(empty) == "get_health:" and bm25_texts(empty) == ("get health", "")


@pytest.mark.parametrize("text,expected", [
    ("Find notes. Returns ids.", "Find notes."),
    ("No full stop here", "No full stop here"),
    ("  Spaces\n and   lines.  Next one.", "Spaces and lines."),
    ("Version 1.5 is out! Yes.", "Version 1.5 is out!"),
    ("", ""),
    ("x" * 300, "x" * 199 + "…"),
])
def test_summary_is_the_first_sentence_at_most_200_characters(text, expected):
    assert summary(text) == expected and len(summary(text)) <= 200


def test_tool_view_id_hashes_sorted_ids():
    assert tool_view_id(["b", "a"]) == tool_view_id({"a", "b"}) != tool_view_id(["a"])


# -- building, fingerprint ---------------------------------------------------------------------

def test_build_is_deterministic_and_the_fingerprint_is_expected(catalog, cache):
    a = ToolIndex.build(catalog, 2, cache)
    b = ToolIndex.build(catalog, 2, cache)
    assert a.fingerprint == b.fingerprint == ToolIndex.expected_fingerprint(catalog, 2, cache)
    assert list(a.rows) == sorted(catalog.ids()) and a.tool_snapshot == catalog.snapshot_id
    assert ToolIndex.build(catalog, 1, cache).fingerprint != a.fingerprint
    lex = ToolIndex.build(catalog, 2, None, dense=False)
    assert lex.dense is None and lex.fingerprint != a.fingerprint
    assert lex.fingerprint == ToolIndex.expected_fingerprint(catalog, 2, None, dense=False)
    for q in QUERIES:
        assert a.retrieve(q, 0.4) == b.retrieve(q, 0.4)


def test_with_w_name_equals_a_build_with_it(catalog, cache):
    base = ToolIndex.build(catalog, 0, cache)
    for w_name in (1, 3):
        other = base.with_w_name(w_name)
        built = ToolIndex.build(catalog, w_name, cache)
        assert other.fingerprint == built.fingerprint
        assert [other.retrieve(q, 0.3) for q in QUERIES] == [built.retrieve(q, 0.3)
                                                            for q in QUERIES]


def test_bad_arguments_are_refused(catalog, cache):
    with pytest.raises(ValueError):
        ToolIndex.build(catalog, -1, cache)
    idx = ToolIndex.build(catalog, 1, cache)
    with pytest.raises(ValueError, match="weight"):
        idx.retrieve("git", None)
    with pytest.raises(ValueError, match="allowed"):
        idx.retrieve("git", 0.5, lexical=idx.view_lexical(idx.rows))


# -- ranking equals the fused channels ---------------------------------------------------------

def _reference_lexical(catalog, w_name) -> FieldBM25:
    lex = FieldBM25(w_name)
    lex.build([_Row(catalog.get(t), w_name) for t in catalog.ids()])
    return lex


class _Row:
    """What FieldBM25 reads of a tool: its BM25 texts from the module's functions."""

    def __init__(self, rec, w_name):
        self.chunk_id = self.doc_id = rec.tool_id
        self.char_start = self.char_end = 0
        self.breadcrumb, self.text = bm25_texts(rec)


def test_lexical_ranking_is_bm25_over_the_fielded_text(catalog):
    for w_name in (0, 1, 3):
        idx = ToolIndex.build(catalog, w_name, None, dense=False)
        ref = _reference_lexical(catalog, w_name)
        for q in QUERIES:
            assert idx.retrieve(q, None, top=10) == ref.search(q, k=CHANNEL_K)[:10]
            assert idx.retrieve(q, None, top=150) == ref.search(q, k=150)


def test_name_weight_changes_the_name_field_only(catalog):
    recs = {r.name: r for r in (catalog.get(t) for t in catalog.ids())}
    rec = recs["git_status"]
    zero = ToolIndex.build(catalog, 0, None, dense=False).rows[rec.tool_id]
    three = ToolIndex.build(catalog, 3, None, dense=False)
    assert three.lexical_text(rec.tool_id) == zero.body_text + " git status" * 3
    assert ToolIndex.build(catalog, 0, None, dense=False).lexical_text(rec.tool_id) == \
        zero.body_text


def test_hybrid_ranking_is_linear_fusion_of_the_two_channels(catalog, cache):
    idx = ToolIndex.build(catalog, 1, cache)
    ids = list(idx.rows)
    vectors, _ = cache.embed_texts([dense_text(catalog.get(t)) for t in ids])
    ref = _reference_lexical(catalog, 1)
    for q in QUERIES:
        qv = _unit(cache.model().query_embed([q])[0])
        cos = vectors @ qv
        dense = sorted(((ids[i], round(float(cos[i]), 6)) for i in range(len(ids))),
                       key=lambda h: (-h[1], h[0]))[:CHANNEL_K]
        lex = ref.search(q, k=CHANNEL_K)
        for w in (0.0, 0.35, 1.0):
            assert idx.retrieve(q, w) == linear(lex, dense, w, top=10)
        exact = row_scores(vectors, qv)
        dense_exact = sorted(((ids[i], round(float(exact[i]), 6)) for i in range(len(ids))),
                             key=lambda h: (-h[1], h[0]))[:CHANNEL_K]
        assert idx.retrieve(q, 0.35, exact=True) == linear(lex, dense_exact, 0.35, top=10)


# -- per-view statistics -----------------------------------------------------------------------

def _views(idx):
    ids = list(idx.rows)
    return [frozenset(ids[::2]), frozenset(ids[1::3]), frozenset(ids[:5]), frozenset(ids)]


def test_a_view_equals_an_index_of_the_view_only(catalog, cache):
    idx = ToolIndex.build(catalog, 2, cache)
    for view in _views(idx):
        sub = idx.subset(view)
        assert list(sub.rows) == sorted(view)
        lex = idx.view_lexical(view)
        for q in QUERIES:
            for w in (0.0, 0.5, 1.0):
                assert idx.retrieve(q, w, allowed=view, lexical=lex, exact=True) == \
                    sub.retrieve(q, w, exact=True)


def test_a_view_equals_a_catalog_of_the_view_only(tmp_path, catalog, cache):
    idx = ToolIndex.build(catalog, 1, cache)
    view = _views(idx)[0]
    small = make_catalog(tmp_path / "small", [catalog.get(t) for t in sorted(view)])
    other = ToolIndex.build(small, 1, cache)
    lex = idx.view_lexical(view)
    for q in QUERIES:
        assert idx.retrieve(q, 0.6, allowed=view, lexical=lex, exact=True) == \
            other.retrieve(q, 0.6, exact=True)


def test_global_statistics_with_a_mask_differ_from_the_view(catalog):
    """The reason for per-view BM25 (§6.2): a mask alone keeps the hidden tools' IDF."""
    idx = ToolIndex.build(catalog, 1, None, dense=False)
    view = _views(idx)[0]
    masked = [idx.retrieve(q, None, allowed=view) for q in QUERIES]
    per_view = [idx.retrieve(q, None, allowed=view, lexical=idx.view_lexical(view))
                for q in QUERIES]
    assert masked != per_view
    for hits in masked + per_view:
        assert all(t in view for t, _ in hits)


# -- persistence -------------------------------------------------------------------------------

def test_save_and_load(tmp_path, catalog, cache):
    idx = ToolIndex.build(catalog, 2, cache)
    idx.save(tmp_path / "idx")
    back = ToolIndex.load(tmp_path / "idx", cache)
    assert back.fingerprint == idx.fingerprint and back.w_name == 2
    assert [back.retrieve(q, 0.5) for q in QUERIES] == [idx.retrieve(q, 0.5) for q in QUERIES]
    lex = ToolIndex.build(catalog, 0, None, dense=False)
    lex.save(tmp_path / "lex")
    assert ToolIndex.load(tmp_path / "lex", None).dense is None


def test_load_refuses_a_tampered_index(tmp_path, catalog):
    idx = ToolIndex.build(catalog, 1, None, dense=False)
    idx.save(tmp_path / "idx")
    rows = (tmp_path / "idx" / "tools.jsonl").read_text().splitlines()
    first = json.loads(rows[0])
    first["body_text"] += " extra"
    rows[0] = json.dumps(first, sort_keys=True)
    (tmp_path / "idx" / "tools.jsonl").write_text("\n".join(rows) + "\n")
    with pytest.raises(ValueError, match="fingerprint"):
        ToolIndex.load(tmp_path / "idx", None)


def test_scores_are_finite_and_rounded(catalog, cache):
    idx = ToolIndex.build(catalog, 1, cache)
    for q in QUERIES:
        for _, s in idx.retrieve(q, 0.5, top=20):
            assert math.isfinite(s) and round(s, 6) == s
