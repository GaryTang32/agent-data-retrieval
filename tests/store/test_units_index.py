"""The unit index (Phase 4 Task 7, spec §11.1, preflight C8 and C13).

Fixture stores are built under `tmp_path` from `units_fixtures.UNITS_DOCS`; dense tests use the
fake embedding cache of `test_retrieval`, lexical-only tests (`emb=None`, C8) load no model.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from adr_store.units import index as ui
from adr_store.units.build import build_units
from adr_store.units.index import (
    FIELDS,
    INDEX_DIR,
    VIEW_CACHE,
    W_GRID,
    WEIGHT_GRID,
    UnitDoc,
    UnitIndex,
    expand_query,
    load_tuning,
    unit_docs,
)
from adr_store.units.overlay import load_units, load_units_manifest
from tests.store import units_fixtures as uf
from tests.store.test_retrieval import fake_cache
from tests.store.units_fixtures import (
    DOC_117_NEW,
    DOC_117_OLD,
    DOC_165,
    DOC_IRM,
    UNITS_DOCS,
    make_units_store,
)

units_store = uf.units_store

# The 165.13 cards say "regulated navigation area", never "RNA". BM25 does not stem, so
# "anchoring" matches neither card's "anchor": "RNA anchoring" finds 165.13(a) first (it says
# "area" twice), and "RNA anchor" finds the anchoring card 165.13(b) first.
RNA_CARD = "rule_card/33 CFR 165.13(a)/8f62ccff1056/8ea393bf3a592f40"
ANCHOR_CARD = "rule_card/33 CFR 165.13(b)/54488057c88d/8ea393bf3a592f40"
VIEW_DOCS = frozenset({DOC_117_NEW, DOC_IRM})     # 165 (the RNA concept) and old 117 hidden
QUERIES = ["RNA vessel area", "RNA anchoring", "drawbridge notice", "refund inquiry research",
           "designated representative", "Drawtender", "open on signal", "the of and",
           "zzz-unknown-word", ""]


def gov_build(store) -> tuple[str, list]:
    b = build_units(store.path, "gov")
    return b.units_id, load_units(store.path, load_units_manifest(store.path, b.units_id))


def docs_of(units) -> list[UnitDoc]:
    return unit_docs(units, [u for u in units if u.type == "concept"])


def index_of(store, emb=None, tuning=None) -> UnitIndex:
    units_id, units = gov_build(store)
    return UnitIndex.build(store.path, units_id, docs_of(units), emb,
                           tuning or load_tuning("gov"))


def view_store(store, docs: frozenset[str], tmp_path: Path):
    """A store of the documents `docs` of `store` alone (same documents, same unit ids)."""
    return make_units_store(tmp_path / "view-store",
                            [(d, raw) for d, raw in UNITS_DOCS if d.doc_id in docs])


@pytest.fixture(scope="module")
def gov(tmp_path_factory):
    """(store, units id, units) of the gov build of `UNITS_DOCS`."""
    store = make_units_store(tmp_path_factory.mktemp("units-index") / "store")
    units_id, units = gov_build(store)
    return store, units_id, units


def by_id(units) -> dict:
    return {u.unit_id: u for u in units}


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file()}


# -- the plan's tests ----------------------------------------------------------------------------

@pytest.mark.parametrize("dense", [False, True], ids=["lexical-only", "dense"])
def test_ranking_equals_an_index_of_the_view_alone(units_store, tmp_path, dense):
    emb = fake_cache(tmp_path / "emb") if dense else None
    full = index_of(units_store, emb)
    view = index_of(view_store(units_store, VIEW_DOCS, tmp_path), emb)
    assert {u for u, _ in full.search("drawbridge", types=None, admitted=None, k=1000)} > \
        {u for u, _ in view.search("drawbridge", types=None, admitted=None, k=1000)}
    for q in QUERIES:
        for k in (10, 1000):
            got = full.search(q, types=None, admitted=VIEW_DOCS, k=k)
            assert got == view.search(q, types=None, admitted=None, k=k), q
            assert all(u.split("/")[-1] in {d[:16] for d in VIEW_DOCS} for u, _ in got)
    # a hidden concept expands nothing: "RNA" names the 165 concept, which the view cannot see
    assert full.lexical_query("RNA vessel area", VIEW_DOCS) == "RNA vessel area"
    assert full.lexical_query("RNA vessel area", VIEW_DOCS | {DOC_165}) == \
        "RNA vessel area Regulated navigation area"


def test_alternate_labels_expand_the_query(units_store):
    idx = index_of(units_store)
    hits = idx.search("RNA anchoring", types=("rule_card",), admitted=None)
    assert hits[0][0] == RNA_CARD      # card text says "regulated navigation area", never "RNA"
    assert hits[1][0] == ANCHOR_CARD
    assert idx.search("RNA anchor", types=("rule_card",), admitted=None)[0][0] == ANCHOR_CARD
    _, units = gov_build(units_store)
    for card_id, labels in ((RNA_CARD, ["Regulated navigation area", "RNA"]),
                            (ANCHOR_CARD, ["Regulated navigation area", "RNA",
                                           "Designated representative"])):  # mention order
        card = by_id(units)[card_id]
        assert "RNA" not in card.body["text"] and "regulated navigation area" in card.body["text"]
        doc = next(d for d in docs_of(units) if d.unit_id == card_id)
        assert "RNA" not in doc.fields["body"] and "RNA" not in doc.dense_text
        assert doc.fields["labels"].split("\n") == labels
    # the expansion itself: the 165 concept maps "RNA" to its preferred label and back
    labels = idx.label_map(None)
    assert labels["rna"] == ("Regulated navigation area",)
    assert labels["regulated navigation area"] == ("RNA",)
    assert idx.lexical_query("RNA anchoring", None) == "RNA anchoring Regulated navigation area"
    # without the labels field and the expansion, no 165.13 card matches the query at all
    bare = [UnitDoc(d.unit_id, d.type, d.doc_id, {**d.fields, "labels": ""}, d.dense_text,
                    d.aids) for d in docs_of(units)]
    plain = UnitIndex.build(units_store.path, "0" * 64, bare, None, load_tuning("gov"))
    assert not [u for u, _ in plain.search("RNA anchoring", types=("rule_card",),
                                           admitted=None) if "165.13" in u]


def test_aids_are_indexed_but_not_in_reader_text(gov, tmp_path):
    store, units_id, units = gov
    proc = next(u for u in units if u.type == "procedure")
    aid = "zebrafish quokka reconciliation"
    tagged = proc.model_copy(update={
        "aids": proc.aids.model_copy(update={"trigger_examples": [aid]}),
        "body": {**proc.body, "problem_abstractions": {
            **proc.body["problem_abstractions"], "value": ["capybara ledger mismatch"],
            "status": "verified", "null_reason": None}}})
    units2 = [tagged if u.unit_id == proc.unit_id else u for u in units]
    docs = docs_of(units2)
    doc = next(d for d in docs if d.unit_id == proc.unit_id)
    assert doc.aids == (aid, "capybara ledger mismatch")
    assert doc.fields["aids"] == f"{aid}\ncapybara ledger mismatch"
    for name in FIELDS[:-1]:
        assert "zebrafish" not in doc.fields[name] and "capybara" not in doc.fields[name]
    assert "zebrafish" not in doc.dense_text and "capybara" not in doc.dense_text
    lex = UnitIndex.build(tmp_path / "s-lex", units_id, docs, None, load_tuning("gov"))
    assert [u for u, _ in lex.search("zebrafish quokka", types=None, admitted=None)] == \
        [proc.unit_id]
    assert [u for u, _ in lex.search("capybara", types=None, admitted=None)] == [proc.unit_id]
    # dense: one vector per aid, mapped to its parent at the parent's best score
    idx = UnitIndex.build(tmp_path / "s-dense", units_id, docs, fake_cache(tmp_path / "e2"),
                          {**load_tuning("gov"), "w": 0.5})
    hits = idx.search(aid, types=None, admitted=None, k=10_000)
    assert hits[0][0] == proc.unit_id and len({u for u, _ in hits}) == len(hits) == len(docs)
    assert {u for u, _ in hits} == {d.unit_id for d in docs}     # never an aid row
    rows = [json.loads(line) for line in
            (idx.directory / "rows.jsonl").read_text("utf-8").splitlines()]
    assert len(rows) == len(docs) + 2
    assert [r["unit_id"] for r in rows if r["aid"] is not None] == [proc.unit_id] * 2
    q = "zebrafish quokka reconciliation"     # the aid text itself: cosine 1 on its own row
    dense = dict(idx.dense_scores(q, admitted=None, types=None))
    assert dense[proc.unit_id] == 1.0
    assert max(dense.values()) == 1.0


def test_type_filter_and_total_order(gov, tmp_path):
    store, units_id, units = gov
    idx = UnitIndex.build(store.path, units_id, docs_of(units), fake_cache(tmp_path / "emb"),
                          {**load_tuning("gov"), "w": 0.5})
    types = {u.unit_id: u.type for u in units}
    every = idx.search("drawbridge open notice", types=None, admitted=None, k=10_000)
    assert len(every) == len(units)                 # dense reaches every unit: the full tail
    for t in ("concept", "rule_card", "procedure", "table_record"):
        hits = idx.search("drawbridge open notice", types=(t,), admitted=None, k=10_000)
        assert hits and {types[u] for u, _ in hits} == {t}
        assert hits == sorted(hits, key=lambda h: (-h[1], h[0]))
        assert len(hits) == sum(v == t for v in types.values())
    assert every == sorted(every, key=lambda h: (-h[1], h[0]))
    assert idx.search("drawbridge open notice", types=None, admitted=None, k=7) == every[:7]
    assert idx.search("drawbridge open notice", types=None, admitted=None, k=0) == []
    # § 117.821(a) is the same text in both versions: equal scores, broken by unit id
    lex = UnitIndex.build(store.path, units_id, docs_of(units), None, load_tuning("gov"))
    hits = lex.search("117.821 drawbridge open signal", types=("rule_card",), admitted=None,
                      k=100)
    twins = [h for h in hits if h[0].startswith("rule_card/33 CFR 117.821(a)/")]
    assert len(twins) == 2 and twins[0][1] == twins[1][1] and twins[0][0] < twins[1][0]
    assert hits.index(twins[1]) == hits.index(twins[0]) + 1
    assert {u.split("/")[-1] for u, _ in twins} == {DOC_117_OLD[:16], DOC_117_NEW[:16]}
    # the lexical-only ranking is BM25's: only positive scores, every one of them
    assert all(s > 0 for _, s in hits)
    with pytest.raises(ValueError, match="unknown unit type"):
        idx.search("x", types=("rule",), admitted=None)
    with pytest.raises(ValueError, match="non-empty"):
        idx.search("x", types=(), admitted=None)
    with pytest.raises(ValueError, match="k must be"):
        idx.search("x", types=None, admitted=None, k=-1)
    with pytest.raises(ValueError, match="admitted"):
        idx.search("x", types=None, admitted=[DOC_IRM])


def test_index_build_is_byte_stable(units_store, tmp_path):
    other = make_units_store(tmp_path / "copy")
    a_id, a_units = gov_build(units_store)
    b_id, b_units = gov_build(other)
    assert a_id == b_id
    trees = []
    for store, units in ((units_store, a_units), (other, b_units)):
        for emb in (None, fake_cache(tmp_path / f"emb-{store.path.name}")):
            idx = UnitIndex.build(store.path, a_id, docs_of(units), emb, load_tuning("gov"))
            assert idx.directory.parent == store.path / INDEX_DIR / a_id
        trees.append(tree_bytes(store.path / INDEX_DIR))
    assert trees[0] == trees[1] and len(trees[0]) == 4    # lexical index.json; dense 3 files
    lexical = json.loads(trees[0][f"{a_id}/lexical/index.json"])
    assert lexical["lexical_only"] is True and lexical["embedding"] is None
    dense_dir = next(k.split("/")[1] for k in trees[0] if "/dense-" in k)
    meta = json.loads(trees[0][f"{a_id}/{dense_dir}/index.json"])
    assert meta["lexical_only"] is False and meta["embedding"]["model"] == "fake/model"
    vectors = trees[0][f"{a_id}/{dense_dir}/vectors.npy"]
    assert meta["vectors_sha256"] == hashlib.sha256(vectors).hexdigest()
    # a rebuild reuses the stored vectors (no new embedding) and gives the same rankings
    emb = fake_cache(tmp_path / "emb-again")
    first = UnitIndex.build(units_store.path, a_id, docs_of(a_units), emb, load_tuning("gov"))
    calls = len(emb.model().passage.calls)
    again = UnitIndex.build(units_store.path, a_id, docs_of(a_units), emb, load_tuning("gov"))
    assert len(emb.model().passage.calls) == calls == 0
    assert tree_bytes(units_store.path / INDEX_DIR) == trees[0]
    for q in QUERIES:
        assert first.search(q, types=None, admitted=None) == \
            again.search(q, types=None, admitted=None)


# -- C8: lexical-only needs no embedding model ---------------------------------------------------

def test_lexical_only_build_and_search_load_no_model(units_store, monkeypatch):
    from adr_eval.retrieval.dense import DenseIndex
    from adr_store.embedding import EmbeddingCache

    def refuse(*a, **k):
        raise AssertionError("the embedding model was loaded")

    monkeypatch.setattr(EmbeddingCache, "model", refuse)
    monkeypatch.setattr(EmbeddingCache, "embed_texts", refuse)
    monkeypatch.setattr(DenseIndex, "_get_model", refuse)
    import fastembed

    monkeypatch.setattr(fastembed, "TextEmbedding", refuse)
    idx = index_of(units_store)
    assert idx.lexical_only
    hits = idx.search("drawbridge notice", types=None, admitted=None)
    assert hits and hits == sorted(hits, key=lambda h: (-h[1], h[0]))
    assert idx.search("RNA anchoring", types=("rule_card",), admitted=None)[0][0] == RNA_CARD
    meta = json.loads((idx.directory / "index.json").read_text("utf-8"))
    assert meta["lexical_only"] is True and sorted(p.name for p in idx.directory.iterdir()) \
        == ["index.json"]
    with pytest.raises(ValueError, match="lexical-only"):
        idx.dense_scores("drawbridge", admitted=None, types=None)


# -- fields, BM25F, expansion, tuning ------------------------------------------------------------

def test_unit_doc_fields(gov):
    store, units_id, units = gov
    docs = docs_of(units)
    assert [d.unit_id for d in docs] == sorted(u.unit_id for u in units)
    assert all(set(d.fields) == set(FIELDS) for d in docs)
    units_by = by_id(units)
    card = next(d for d in docs if d.unit_id.startswith("rule_card/33 CFR 117.5(p1)/")
                and d.doc_id == DOC_117_NEW)
    u = units_by[card.unit_id]
    assert card.fields["ref"].split("\n")[0] == u.canonical_ref
    assert u.body["provision_id"] in card.fields["ref"]
    assert card.fields["body"].startswith(u.body["text"])
    assert card.dense_text == " > ".join(u.heading_path) + "\n" + card.fields["body"]
    assert "Drawbridge" in card.fields["labels"].split("\n")     # it defines the term
    # closure headings: the cited units' headings, after the rule text
    cites = next(d for d in docs if d.unit_id.startswith("rule_card/33 CFR 117.1081(b)/")
                 and d.doc_id == DOC_117_NEW)
    cu = units_by[cites.unit_id]
    targets = [units_by[e["unit_id"]] for e in cu.body["closure"]
               if e["unit_id"] in units_by and e["relation"] != "defines"]
    assert targets and all(t.heading_path[-2] in cites.fields["body"] for t in targets
                           if t.type == "rule_card")
    proc = next(d for d in docs if d.type == "procedure")
    pu = units_by[proc.unit_id]
    for s in pu.body["steps"]:
        assert s["text"] in proc.fields["body"]
    concept = next(d for d in docs if d.unit_id.startswith(
        "concept/concept:33 CFR part 165:regulated navigation area/"))
    assert concept.fields["labels"].split("\n") == ["Regulated navigation area", "RNA"]
    assert concept.fields["body"].startswith("Regulated navigation area (RNA) means")
    table = next(d for d in docs if d.type == "table_record")
    tu = units_by[table.unit_id]
    assert tu.body["description"] in table.fields["body"]
    assert all(h in table.fields["body"] for h in tu.body["headers"])
    assert all(d.fields["aids"] == "" and d.aids == () for d in docs)


def test_bm25f_is_field_repetition(gov, tmp_path):
    store, units_id, units = gov
    docs = docs_of(units)
    weights = {f: 1 for f in FIELDS} | {"title": 3, "labels": 2}
    d = docs[0]
    assert ui.indexed_text(d, weights) == " ".join(
        [d.fields["title"]] * 3 + [d.fields["ref"]] + [d.fields["labels"]] * 2
        + [d.fields["body"]] + [d.fields["aids"]])
    base = load_tuning("gov")
    heavy = {**base, "weights": {**base["weights"], "rule_card": weights}}
    a = UnitIndex.build(store.path, units_id, docs, None, base)
    b = UnitIndex.build(store.path, units_id, docs, None, heavy)
    assert a.fingerprint != b.fingerprint
    qa = a.search("Coast Channel", types=("rule_card",), admitted=None)
    qb = b.search("Coast Channel", types=("rule_card",), admitted=None)
    assert {u for u, _ in qa} == {u for u, _ in qb} and qa != qb   # same matches, new scores


def test_expand_query():
    labels = {"rna": ("Regulated navigation area",), "regulated navigation area": ("RNA",),
              "tc": ("Transaction code",), "transaction code": ("TC",)}
    assert expand_query("RNA anchoring", labels) == "RNA anchoring Regulated navigation area"
    assert expand_query("anchoring in a regulated  navigation-area?", labels) == \
        "anchoring in a regulated  navigation-area? RNA"
    assert expand_query("TC 846 and RNA", labels) == \
        "TC 846 and RNA Transaction code Regulated navigation area"
    assert expand_query("rnas tcx", labels) == "rnas tcx"          # whole words only
    assert expand_query("RNA regulated navigation area", labels) == \
        "RNA regulated navigation area"                            # nothing new to add
    assert expand_query("", labels) == "" and expand_query("RNA", {}) == "RNA"


def test_load_tuning_defaults_and_checks(tmp_path):
    assert WEIGHT_GRID == (1, 2, 3)
    assert W_GRID == (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0)
    assert VIEW_CACHE == 16 and INDEX_DIR == "units-index"
    from adr_store.units.build import CORPUS_TYPES

    for corpus, types in CORPUS_TYPES.items():
        t = load_tuning(corpus)
        assert t == {"weights": {ty: {f: 1 for f in FIELDS} for ty in types}, "w": 1.0}
    with pytest.raises(ValueError, match="no tuning"):
        load_tuning("tools")
    good = json.loads((ui.UNIT_CONTRACT_DIR / "tuning.json").read_text("utf-8"))
    for bad, msg in (
            ({"weights": {**good["gov"]["weights"], "concept": {f: 4 for f in FIELDS}}},
             "weight"),
            ({"w": 0.45}, "w must be"),
            ({"w": True}, "w must be"),
            ({"weights": {**good["gov"]["weights"], "rule_card": {"title": 1}}}, "fields"),
            ({"weights": {k: v for k, v in good["gov"]["weights"].items()
                          if k != "procedure"}}, "types")):
        p = tmp_path / "tuning.json"
        p.write_text(json.dumps({**good, "gov": {**good["gov"], **bad}}), "utf-8")
        with pytest.raises(ValueError, match=msg):
            load_tuning("gov", p)


def test_build_refuses_a_type_without_weights(gov):
    store, units_id, units = gov
    tuning = load_tuning("research")          # concept and table_record only
    with pytest.raises(ValueError, match="procedure"):
        UnitIndex.build(store.path, units_id, docs_of(units), None, tuning)


# -- large units ---------------------------------------------------------------------------------

def test_a_50_kb_unit_is_indexed_whole(gov, tmp_path):
    store, units_id, units = gov
    docs = docs_of(units)
    big = docs[0]
    filler = " ".join(f"step{i} reconcile the account" for i in range(10_000))
    tail = "ultimately escalate to the platypus desk"
    huge = UnitDoc(big.unit_id, big.type, big.doc_id,
                   {**big.fields, "body": filler + " " + tail},
                   big.dense_text.split("\n")[0] + "\n" + filler + " " + tail, big.aids)
    assert len(huge.fields["body"].encode()) > 45_000
    docs2 = [huge if d.unit_id == big.unit_id else d for d in docs]
    for emb in (None, fake_cache(tmp_path / "emb")):
        idx = UnitIndex.build(tmp_path / f"s-{emb is None}", units_id, docs2, emb,
                              load_tuning("gov"))
        assert idx.search("platypus", types=None, admitted=None)[0][0] == big.unit_id
    emb = fake_cache(tmp_path / "emb2")
    UnitIndex.build(tmp_path / "s3", units_id, docs2, emb, load_tuning("gov"))
    assert any(huge.dense_text in batch for batch in emb.model().passage.calls)


def test_view_lexical_indexes_are_cached_per_view(gov, monkeypatch):
    store, units_id, units = gov
    monkeypatch.setattr(ui, "_VIEW_LEXICAL", type(ui._VIEW_LEXICAL)())
    idx = UnitIndex.build(store.path, units_id, docs_of(units), None, load_tuning("gov"))
    built = []
    real = ui._ViewLexical.__init__

    def counting(self, *a, **k):
        built.append(1)
        real(self, *a, **k)

    monkeypatch.setattr(ui._ViewLexical, "__init__", counting)
    for _ in range(3):
        idx.search("drawbridge", types=None, admitted=VIEW_DOCS)
        idx.search("drawbridge", types=None, admitted=VIEW_DOCS | {"f" * 64})  # no units there
    assert len(built) == 1
    every = frozenset(u.doc_id for u in units)
    assert idx.search("drawbridge", types=None, admitted=every) == \
        idx.search("drawbridge", types=None, admitted=None)
    # the LRU keeps VIEW_CACHE views (here 2) and drops the least recently used
    monkeypatch.setattr(ui, "VIEW_CACHE", 2)
    views = [frozenset({DOC_IRM, DOC_117_OLD}), frozenset({DOC_IRM, DOC_165}),
             frozenset({DOC_165, DOC_117_NEW})]
    built.clear()
    for v in views:
        idx.search("drawbridge", types=None, admitted=v)
    assert len(built) == 3 and len(ui._VIEW_LEXICAL) == 2
    idx.search("drawbridge", types=None, admitted=views[2])        # still cached
    idx.search("drawbridge", types=None, admitted=views[0])        # evicted: built again
    assert len(built) == 4 and len(ui._VIEW_LEXICAL) == 2
    assert idx.search("drawbridge", types=None, admitted=frozenset()) == []
    refund = idx.search("refund", types=None, admitted=frozenset({DOC_IRM}), k=100)
    assert refund and {u.split("/")[-1] for u, _ in refund} == {DOC_IRM[:16]}
