"""Permissions in the tools (Phase 2 spec §5.3–§5.6, §6.2, §12 Permissions): the projection,
per-view BM25, equivalence with an allowed-only store (B2), the fail-closed rules F1–F5 and
"no entry", not-found byte equality, prefixes and counts within the view, duplicates across
views, per-call reloading and the log fields. Gov-shaped fixture stores with markdown
documents whose access an attribute rule fixes, lexical-only indexes or the fake embedder;
nothing reads `data/` or `.cache/`."""

import hashlib
import json
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from adr_store import acl, dedup, records, tools
from adr_store import applicability as ap
from adr_store.retrieval.index import chunk_content_sha256
from adr_store.retrieval.lexical import FieldBM25
from adr_store.store import Store
from tests.store.test_applicability import ALL, GOV_CONFIG, V2024, V2025, V2026, doc_id
from tests.store.test_applicability import make_store as make_gov_store
from tests.store.test_chunking import doc
from tests.store.test_retrieval import fake_cache

REPO = Path(__file__).parents[2]
T0 = datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)
NOW = T0 + timedelta(minutes=1)


def fixed(t: datetime = NOW):
    return lambda: t


def md(path: str, title: str, body: str) -> tuple:
    return doc(f"# {title}\n\n{body}\n".encode(), "md", f"file://acl/{path}")


def words(tag: str, n: int = 50) -> str:
    return " ".join(f"{tag}{i}" for i in range(n))


PUBLIC = md("public/notice.md", "Public notice",
            "Every vessel must file the harbour form and the refund deadline is thirty days.")
ACME = md("acme/plan.md", "Acme plan", "The acme vessel plan names the harbour refund steps.")
ACME0 = md("acme-0/secret.md", "Acme zero secret",
           "The zanzibarite vessel ledger lists the harbour refund of group zero.")
ACME1 = md("acme-1/memo.md", "Acme one memo",
           "The obsidianite memo covers vessel inspections and the harbour refund window.")
GLOBEX = md("globex/brief.md", "Globex brief",
            "The globex brief covers vessel registration and harbour fees.")
SHARED = md("shared/joint.md", "Joint note",
            "The joint note of acme and globex covers the vessel refund appeal.")
NOBODY = md("nobody/orphan.md", "Orphan", "The quokkalith vessel record is visible to no one.")
# two documents whose ids share the 8-character prefix 0913e881 (found by a birthday search
# over the byte strings below; the 9th characters differ), one public, one for group:acme/0
TWIN_BYTES = [f"# Prefix twin\n\nA twin note about vessels, number {i}.\n".encode()
              for i in (59427, 104484)]
TWIN_PREFIX = "0913e881"
TWIN_A = doc(TWIN_BYTES[0], "md", "file://acl/public/twin-a.md")
TWIN_B = doc(TWIN_BYTES[1], "md", "file://acl/acme-0/twin-b.md")
# an exact duplicate chunk (the levy section) in a public and a restricted document
LEVY = f"# Harbour levy\n\nThe harbour levy applies to every moored craft. {words('levy')}\n"
DUP_PUBLIC = doc(f"{LEVY}\n## Public annex\n\n{words('pubannex')}\n".encode(), "md",
                 "file://acl/public/levy.md")
DUP_ACME0 = doc(f"{LEVY}\n## Restricted annex\n\n{words('secannex')}\n".encode(), "md",
                "file://acl/acme-0/levy.md")
ACL_DOCS = [PUBLIC, ACME, ACME0, ACME1, GLOBEX, SHARED, NOBODY, TWIN_A, TWIN_B, DUP_PUBLIC,
            DUP_ACME0]
DOCS = [*ALL, *ACL_DOCS]
RULES = [
    {"match": {"uri_prefix": "file://acl/public/"}, "access": ["public"]},
    {"match": {"uri_prefix": "file://acl/acme/"}, "access": ["tenant:acme"]},
    {"match": {"uri_prefix": "file://acl/acme-0/"}, "access": ["group:acme/0"]},
    {"match": {"uri_prefix": "file://acl/acme-1/"}, "access": ["group:acme/1"]},
    {"match": {"uri_prefix": "file://acl/globex/"}, "access": ["tenant:globex"]},
    {"match": {"uri_prefix": "file://acl/shared/"}, "access": ["tenant:acme", "tenant:globex"]},
    {"match": {"uri_prefix": "file://acl/nobody/"}, "access": []},
    {"match": {"uri_prefix": "https://www.ecfr.gov/"}, "access": ["group:acme/1"]},
]
USERS = ["user:acme-0", "user:acme-1", "user:acme-4", "user:globex-0", "user:outsider",
         "user:auditor"]
QUERIES = ["vessel harbour refund", "harbour levy moored craft", "zanzibarite ledger",
           "obsidianite memo", "twin note", "vessels", "quokkalith"]
PATTERNS = ["vessel", "harbour", "levy", "[Tt]win note", "quokkalith|zanzibarite"]


def did(d) -> str:
    return d[0].doc_id


def write_config(dir_: Path, rules=RULES) -> tuple[Path, Path]:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / "directory.json").write_bytes((REPO / "config/acl/directory.json").read_bytes())
    policy = json.loads((REPO / "config/acl/policy.json").read_text())
    policy["rules"] = rules
    (dir_ / "policy.json").write_text(json.dumps(policy))
    return dir_ / "directory.json", dir_ / "policy.json"


def derive(store) -> None:
    overlay, _ = ap.derive(store, GOV_CONFIG)
    ap.write_overlay(store.path, overlay)


def build_dedup(store) -> str:
    idx = tools.Tools(store.path).active_index()
    ov = dedup.build(list(idx.chunks.values()), idx.snapshot, idx.chunker)
    return dedup.write_overlay(store.path, ov)[0]


@pytest.fixture(autouse=True)
def _fresh_view_cache():
    tools._VIEW_LEXICAL.clear()
    yield
    tools._VIEW_LEXICAL.clear()


@pytest.fixture
def fake_models(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "make_embedding_cache",
                        lambda path=None, *, threads=1: fake_cache(tmp_path / "emb"))


@pytest.fixture
def config(tmp_path):
    return write_config(tmp_path / "config")


def make(path: Path, config, docs=DOCS, *, dense: bool = False, with_dedup: bool = False,
         sync: bool = True) -> Store:
    s = make_gov_store(path, docs)
    derive(s)
    if dense:
        tools.Tools(s.path).index("p1-struct", weight=0.5)
    else:
        tools.Tools(s.path).index("p1-struct", lexical_only=True)
    if with_dedup:
        build_dedup(s)
    if sync:
        acl.sync(s.path, *config, clock=fixed(T0))
    return s


@pytest.fixture
def store(tmp_path, config):
    return make(tmp_path / "store", config, with_dedup=True)


def as_(store, caller, clock=None) -> tools.Tools:
    return tools.Tools(store.path, acl=True, caller=caller, clock=clock or fixed())


def snapshot_of(store) -> acl.AclSnapshot:
    return acl.read_head(store.path)[1]


def visible(store, caller) -> set[str]:
    snap = snapshot_of(store)
    ps = set(snap.directory[caller])
    return {d for d, v in snap.docs.items() if ps & set(v)}


def log_lines(store) -> list[dict]:
    path = store.path / "log" / "retrieval.jsonl"
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]


def err(fn, *a, **kw) -> str:
    with pytest.raises(tools.ToolError) as e:
        fn(*a, **kw)
    return str(e.value)


def absent_like(x: str, taken) -> str:
    """An id of the same first 12 characters (so the same short form) that names nothing."""
    for c in "0123456789abcdef":
        y = x[:12] + c + x[13:]
        if y != x and y not in taken:
            return y
    raise AssertionError(x)


def result_ids(res) -> set[str]:
    """Every document id a search or grep result shows: hits, their alternates and their
    scoring chunks, or matches."""
    if isinstance(res, tools.SearchResult):
        out = set()
        for h in res.hits:
            out.add(h.doc_id)
            out.update(a.doc_id for a in h.alternates)
        return out
    return {m.doc_id for m in res.matches}


# -- the fixture -----------------------------------------------------------------------------

def test_the_fixture_has_prefix_twins_and_a_shared_duplicate(store):
    a, b = did(TWIN_A), did(TWIN_B)
    assert a[:8] == b[:8] == TWIN_PREFIX and a[8] != b[8]
    assert hashlib.sha256(TWIN_BYTES[0]).hexdigest() == a
    snap = snapshot_of(store)
    assert snap.docs[a] == ["public"] and snap.docs[b] == ["group:acme/0"]
    assert snap.docs[did(NOBODY)] == []
    idx = tools.Tools(store.path).active_index()
    dd = dedup.load_overlay(store.path, store.snapshot_id, idx.chunker,
                            chunk_content_sha256(idx.chunks.values()))
    pairs = [{idx.chunks[m].doc_id for m in c.members} for c in dd.overlay.clusters]
    assert {did(DUP_PUBLIC), did(DUP_ACME0)} in pairs


# -- the projection and per-view BM25 ----------------------------------------------------------

@pytest.mark.parametrize("caller", USERS)
def test_the_projection_equals_the_snapshot_lists_for_every_chunk(tmp_path, config,
                                                                  fake_models, monkeypatch,
                                                                  caller):
    s = make(tmp_path / "dense", config, dense=True)
    t = as_(s, caller)
    idx = tools.Tools(s.path).active_index()
    snap = snapshot_of(s)
    ps = set(snap.directory[caller])
    want = [bool(ps & set(snap.docs.get(c.doc_id, []))) for c in idx.chunks.values()]
    assert t._projection().tolist() == want
    # the masks the channels use in a search are that projection (no filter excludes)
    from adr_store.retrieval.dense import CachedDense
    seen = {}
    real_dense, real_lex = CachedDense.search, FieldBM25.search

    def dense_search(self, q, k=100, mask=None, **kw):
        seen["dense"] = None if mask is None else mask.copy()
        seen["exact"] = kw.get("exact")
        return real_dense(self, q, k=k, mask=mask, **kw)

    def lex_search(self, q, k=100, mask=None):
        seen["lex"] = (list(self.chunk_ids), None if mask is None else mask.copy())
        return real_lex(self, q, k=k, mask=mask)

    monkeypatch.setattr(CachedDense, "search", dense_search)
    monkeypatch.setattr(FieldBM25, "search", lex_search)
    t.search("vessel", filters={"include_superseded": True}, dedup=False)
    by_row = {c.chunk_id: w for c, w in zip(idx.chunks.values(), want, strict=True)}
    dense_want = [by_row[cid] for cid in idx.dense.chunk_ids]
    assert seen["exact"] is True  # the row-exact kernel under the ACL layer
    if all(want):
        assert seen["dense"] is None or seen["dense"].all()
    else:
        assert seen["dense"].tolist() == dense_want
        lex_ids, lex_mask = seen["lex"]
        assert lex_ids == [cid for cid, w in by_row.items() if w]
        assert lex_mask.all()


def test_per_view_bm25_equals_bm25_over_the_view_s_chunks(store):
    t = as_(store, "user:acme-0")
    idx = tools.Tools(store.path).active_index()
    access = t._access()
    view = t._view_lexical(idx, access)
    chunks = [c for c in idx.chunks.values() if c.doc_id in access.docs]
    ref = FieldBM25(idx.lexical.w_bc, idx.lexical.bm25.k1, idx.lexical.bm25.b)
    ref.build(chunks)
    assert view.chunk_ids == ref.chunk_ids and view.config() == ref.config()
    for q in QUERIES:
        a, b = view.bm25.scores(q), ref.bm25.scores(q)
        assert (a is None and b is None) or np.array_equal(a, b)
        assert view.search(q, k=1000) == ref.search(q, k=1000)
    assert t._view_lexical(idx, access) is view  # cached by (fingerprint, view)
    auditor = as_(store, "user:auditor")  # sees all but the document with an empty list
    assert auditor._view_lexical(idx, auditor._access()).chunk_ids == [
        c.chunk_id for c in idx.chunks.values() if c.doc_id != did(NOBODY)]


def test_the_view_cache_is_an_lru_of_32_by_fingerprint_and_view(store, monkeypatch):
    assert tools.VIEW_CACHE == 32
    monkeypatch.setattr(tools, "VIEW_CACHE", 2)
    idx = tools.Tools(store.path).active_index()
    got = {}
    for u in ("user:acme-0", "user:globex-0", "user:outsider"):
        t = as_(store, u)
        got[u] = t._view_lexical(idx, t._access())
    assert len(tools._VIEW_LEXICAL) == 2
    assert (idx.fingerprint, as_(store, "user:acme-0")._access().view) not in tools._VIEW_LEXICAL
    t = as_(store, "user:outsider")
    assert t._view_lexical(idx, t._access()) is got["user:outsider"]
    # users with one view share it
    a, b = as_(store, "user:acme-0")._access(), as_(store, "user:acme-2")._access()
    assert (a.view == b.view) == (a.docs == b.docs)


# -- B2: search and grep equal an allowed-only store ---------------------------------------------

def _hits(res):
    return ([(h.rank, h.chunk_id, h.doc_id, h.char_start, h.char_end, h.breadcrumb,
              h.score, h.scored_by, [(a.chunk_id, a.doc_id, a.kind, a.jaccard)
                                               for a in h.alternates]) for h in res.hits],
            res.excluded_by_filter, res.short_by, res.dedup is None)


def _matches(res):
    return ([(m.doc_id, m.char_start, m.char_end, m.line, m.match, m.context)
             for m in res.matches], res.truncated, res.excluded_by_filter)


def more_queries(n: int = 40) -> list[str]:
    """Seeded queries of 1 to 4 words of the fixture texts (the reviewer's B2 check)."""
    import random

    vocab = sorted({w.lower() for d in DOCS for w in d[0].text.split() if w.isalpha()})
    rng = random.Random(1)
    return [" ".join(rng.sample(vocab, rng.randint(1, 4))) for _ in range(n)]


ALL_USERS = sorted(json.loads((REPO / "config/acl/directory.json").read_text())["users"])


@pytest.mark.parametrize("dense", [False, True])
def test_search_and_grep_equal_a_store_of_the_callers_documents(tmp_path, config, fake_models,
                                                                dense):
    """Every user of the directory: ids and scores bit for bit (not only to 6 decimals);
    the reference store is called as the same user, who sees all of it."""
    s = make(tmp_path / "full", config, dense=dense, with_dedup=True)
    refs = {}
    queries = QUERIES + more_queries()
    for caller in ALL_USERS:
        mine = frozenset(visible(s, caller))
        if mine not in refs:
            refs[mine] = make(tmp_path / f"ref-{len(refs)}", config,
                              [d for d in DOCS if did(d) in mine], dense=dense,
                              with_dedup=True)
        assert visible(refs[mine], caller) == set(mine)
        t, ref = as_(s, caller), as_(refs[mine], caller)
        for q in queries:
            for kw in ({}, {"filters": {"include_superseded": True}, "dedup": False},
                       {"top": 30}):
                assert _hits(t.search(q, **kw)) == _hits(ref.search(q, **kw)), (caller, q, kw)
        for p in PATTERNS:
            for kw in ({}, {"max": 2}, {"filters": {"include_superseded": True}}):
                assert _matches(t.grep(p, **kw)) == _matches(ref.grep(p, **kw)), (caller, p)


# -- nothing outside the view, counts within it -------------------------------------------------

@pytest.mark.parametrize("caller", USERS)
def test_no_result_names_a_document_outside_the_view(store, caller):
    t = as_(store, caller)
    mine = visible(store, caller)
    for q in QUERIES:
        for kw in ({}, {"filters": {"include_superseded": True}}, {"dedup": False}):
            res = t.search(q, **kw)
            assert result_ids(res) <= mine
            assert {h.scored_by for h in res.hits} <= {
                c for c, ch in tools.Tools(store.path).active_index().chunks.items()
                if ch.doc_id in mine}
    for p in PATTERNS:
        assert result_ids(t.grep(p, filters={"include_superseded": True})) <= mine


def test_a_restricted_duplicate_is_never_listed_to_a_caller_who_cannot_see_it(store):
    q = "harbour levy moored craft"
    out = as_(store, "user:outsider").search(q)
    [hit] = [h for h in out.hits if h.doc_id in (did(DUP_PUBLIC), did(DUP_ACME0))]
    assert hit.doc_id == did(DUP_PUBLIC) and hit.alternates == []
    inside = as_(store, "user:acme-0").search(q)
    [hit] = [h for h in inside.hits if h.doc_id in (did(DUP_PUBLIC), did(DUP_ACME0))]
    assert {hit.doc_id, *(a.doc_id for a in hit.alternates)} == {did(DUP_PUBLIC),
                                                                 did(DUP_ACME0)}
    assert [a.kind for a in hit.alternates] == ["exact"]


def test_counts_cover_the_view_only(store):
    superseded = {doc_id(V2024), doc_id(V2025)}
    for caller in USERS:
        mine = visible(store, caller)
        res = as_(store, caller).search("vessels")
        assert res.excluded_by_filter == len(superseded & mine), caller
        assert as_(store, caller).grep("vessel").excluded_by_filter == len(superseded & mine)
    # truncated counts the caller's matches only
    t = as_(store, "user:outsider")
    n = len(t.grep("vessel", filters={"include_superseded": True}).matches)
    assert not t.grep("vessel", max=n, filters={"include_superseded": True}).truncated
    assert as_(store, "user:auditor").grep("vessel", max=n,
                                           filters={"include_superseded": True}).truncated


# -- not found, byte for byte; prefixes within the view -------------------------------------------

def test_an_invisible_document_reads_as_a_nonexistent_one(store):
    t = as_(store, "user:acme-0")
    everything = store.doc_ids()
    for hidden in (did(ACME1), did(NOBODY), doc_id(V2026), doc_id(V2024)):
        assert hidden in everything and hidden not in visible(store, "user:acme-0")
        none = absent_like(hidden, everything)
        assert err(t.read, hidden) == err(t.read, none)
        assert err(t.read, hidden, 0, 5) == err(t.read, none, 0, 5)
        assert err(t.read, hidden, element="e" * 64) == err(t.read, none, element="e" * 64)
        assert err(t.grep, "vessel", doc=hidden) == err(t.grep, "vessel", doc=none)
        assert err(t.read, hidden[:10]) == err(t.read, none[:10])  # same 10 characters
    # V2024 is superseded too: hidden wins over the filter message
    assert "excluded by the filters" not in err(t.read, doc_id(V2024))
    assert "excluded by the filters" in err(as_(store, "user:acme-1").read, doc_id(V2024))


def test_an_invisible_chunk_or_element_reads_as_a_nonexistent_one(store):
    t = as_(store, "user:acme-0")
    idx = tools.Tools(store.path).active_index()
    mine = visible(store, "user:acme-0")
    hidden_chunk = next(c for c in idx.chunks.values() if c.doc_id == did(ACME1))
    none = absent_like(hidden_chunk.chunk_id, idx.chunks)
    for d in (did(PUBLIC), did(ACME1)):
        assert err(t.read, d, chunk=hidden_chunk.chunk_id) == err(t.read, d, chunk=none)
    assert did(PUBLIC) in mine
    el = store.elements(did(ACME1))[0].element_id
    assert err(t.read, did(ACME1), element=el) == err(t.read, absent_like(did(ACME1),
                                                                          store.doc_ids()),
                                                      element=el)


def test_prefixes_resolve_among_visible_ids_only(store):
    a, b = did(TWIN_A), did(TWIN_B)
    # outsider sees only the public twin: the shared prefix names it, not the hidden one
    for caller in ("user:outsider", "user:globex-0", "user:acme-1"):
        assert as_(store, caller).read(TWIN_PREFIX).doc_id == a
        assert as_(store, caller).grep("twin", doc=TWIN_PREFIX).doc == a
    # a caller who sees both is told the prefix is ambiguous
    assert "ambiguous" in err(as_(store, "user:acme-0").read, TWIN_PREFIX)
    # the hidden twin's longer prefix reads as nothing at all
    t = as_(store, "user:outsider")
    longer = b[:9]
    nothing = next(p for p in (b[:8] + c for c in "0123456789abcdef")
                   if not any(d.startswith(p) for d in store.doc_ids()))
    assert err(t.read, longer).replace(longer, "<id>") == \
        err(t.read, nothing).replace(nothing, "<id>")
    assert longer in err(t.read, longer)


def test_a_document_with_no_entry_is_invisible(tmp_path, config):
    s = make(tmp_path / "s", config)
    snap = snapshot_of(s)
    target = did(PUBLIC)
    docs = {d: v for d, v in snap.docs.items() if d != target}
    put_snapshot(s, snap.model_copy(update={"docs": docs}))
    for caller in USERS:
        t = as_(s, caller)
        assert target not in result_ids(t.search("vessel harbour refund"))
        assert target not in result_ids(t.grep("refund deadline"))
        none = absent_like(target, s.doc_ids())
        assert err(t.read, target) == err(t.read, none)
    assert did(NOBODY) not in result_ids(as_(s, "user:auditor").search("quokkalith"))
    assert as_(s, "user:auditor").grep("quokkalith").matches == []


# -- fail closed: F1–F5 -----------------------------------------------------------------------

def put_snapshot(store, snap: acl.AclSnapshot) -> str:
    """Write a snapshot (entries hash recomputed) under its id and point acl/HEAD at it."""
    snap = snap.model_copy(update={"entries_sha256": acl.entries_sha256(
        snap.directory, snap.docs, snap.tools)})
    return put_bytes(store, records.canonical_json(snap))


def put_bytes(store, data: bytes) -> str:
    sid = hashlib.sha256(data).hexdigest()
    path = store.path / "acl" / "snapshots" / f"{sid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    (store.path / "acl" / "HEAD").write_text(sid + "\n")
    return sid


def calls(t: tools.Tools, d: str):
    return [lambda: t.search("vessel"), lambda: t.grep("vessel"), lambda: t.read(d),
            lambda: t.read(d[:8]), lambda: t.grep("vessel", doc=d)]


def assert_denied(store, t, code: str):
    before = len(log_lines(store))
    for call in calls(t, did(PUBLIC)):
        with pytest.raises(tools.AccessDenied) as e:
            call()
        assert e.value.code == code and str(e.value).startswith(f"access denied ({code}): ")
    lines = log_lines(store)[before:]
    assert len(lines) == 5
    for ln in lines:
        assert ln["acl_decision"] == f"denied:{code}" and ln["results"] == []
        assert ln["principals"] is None and ln["view"] is None
        assert ln["error"].startswith(f"access denied ({code})")


def _snap_file(store) -> Path:
    sid = (store.path / "acl" / "HEAD").read_text().strip()
    return store.path / "acl" / "snapshots" / f"{sid}.json"


F1_DAMAGE = {
    "missing": lambda s: (s.path / "acl" / "HEAD").unlink(),
    "unreadable": lambda s: ((s.path / "acl" / "HEAD").unlink(),
                             (s.path / "acl" / "HEAD").mkdir()),
    "unparsable": lambda s: put_bytes(s, b"{not json\n"),
    "schema-invalid": lambda s: put_bytes(s, json.dumps(
        {**json.loads(_snap_file(s).read_bytes()), "sequence": 0}).encode()),
    "hash is not the id": lambda s: _snap_file(s).write_bytes(
        _snap_file(s).read_bytes().replace(b'"sequence":1', b'"sequence":7')),
    "deeply nested": lambda s: put_bytes(s, b"[" * 100_000 + b"]" * 100_000),
}


@pytest.mark.parametrize("damage", sorted(F1_DAMAGE))
def test_f1_denies_every_tool(store, damage):
    F1_DAMAGE[damage](store)
    assert_denied(store, as_(store, "user:auditor"), "F1")


def test_f2_a_new_content_snapshot_denies_until_a_sync(store, config):
    t = as_(store, "user:acme-0")
    t.search("vessel")
    s = Store.open(store.path)
    s.add(*md("public/later.md", "Later", "A later vessel note."))
    s.commit()
    assert_denied(store, t, "F2")
    assert_denied(store, as_(store, "user:acme-0"), "F2")
    acl.sync(store.path, *config, clock=fixed(T0))
    with pytest.raises(tools.ToolError, match="adr index"):  # allowed now; the index is old
        t.search("vessel")
    assert log_lines(store)[-1]["acl_decision"] == "allowed"


@pytest.mark.parametrize("when", [T0 + timedelta(seconds=3601), T0 - timedelta(seconds=301)])
def test_f3_a_stale_or_future_snapshot_denies(store, when):
    assert_denied(store, as_(store, "user:auditor", clock=fixed(when)), "F3")


@pytest.mark.parametrize("clock", [lambda: datetime(2026, 11, 16, 12, 1),
                                   lambda: (_ for _ in ()).throw(OSError("no clock"))])
def test_f3_a_naive_or_failing_clock_denies(store, clock):
    assert_denied(store, tools.Tools(store.path, acl=True, caller="user:auditor",
                                     clock=clock), "F3")


@pytest.mark.parametrize("caller", [None, "user:ghost", "user:nobody"])
def test_f4_an_unknown_or_missing_caller_denies(store, caller):
    assert_denied(store, as_(store, caller), "F4")


@pytest.mark.parametrize("caller", ["user:Ghost", "group:acme/0", "public", "user:",
                                    "tenant:acme", 7])
def test_f5_a_malformed_caller_denies(store, caller):
    assert_denied(store, as_(store, caller), "F5")


def test_f5_an_off_grammar_principal_in_the_snapshot_denies(store):
    snap = snapshot_of(store)
    put_snapshot(store, snap.model_copy(update={"docs": {**snap.docs,
                                                         did(ACME): ["tenant:Acme"]}}))
    assert_denied(store, as_(store, "user:auditor"), "F5")


def test_acl_off_is_the_phase1_behaviour(store):
    off = tools.Tools(store.path)
    (store.path / "acl" / "HEAD").unlink()  # no ACL at all: acl=False does not look
    res = off.search("quokkalith")
    assert did(NOBODY) in result_ids(res)
    assert log_lines(store)[-1]["acl_decision"] == "off"


def test_the_full_view_is_the_unfiltered_ranking(tmp_path):
    """A caller who sees every document (the auditor, once no document has an empty list)
    gets exactly the results of the tools without ACLs."""
    config = write_config(tmp_path / "config", [r for r in RULES if r["access"]])
    s = make(tmp_path / "s", config, with_dedup=True)
    assert visible(s, "user:auditor") == set(s.doc_ids())
    off, auditor = tools.Tools(s.path), as_(s, "user:auditor")
    idx = off.active_index()
    assert auditor._view_lexical(idx, auditor._access()) is idx.lexical
    for q in QUERIES:
        for kw in ({}, {"filters": {"include_superseded": True}, "dedup": False}):
            assert auditor.search(q, **kw).to_dict() == off.search(q, **kw).to_dict()
    for p in PATTERNS:
        assert auditor.grep(p).to_dict() == off.grep(p).to_dict()


# -- per-call reloading ------------------------------------------------------------------------

def test_a_long_lived_tools_sees_new_overlays_heads_and_indexes(tmp_path, config):
    s = make_gov_store(tmp_path / "s", DOCS)
    t = tools.Tools(s.path)
    t2 = tools.Tools(s.path)
    t2.index("p1-struct", lexical_only=True)
    first = t.search("vessels")  # the index t2 made active
    assert first.applicability is None and first.dedup is None
    derive(s)
    second = t.search("vessels")
    assert second.applicability is not None and second.excluded_by_filter == 2
    oid = build_dedup(s)
    assert t.search("vessels").dedup == oid
    t2.index("p1-struct-bc", lexical_only=True, w_bc=1)
    assert t.search("vessels").system == "p1-struct-bc"
    s2 = Store.open(s.path)
    s2.add(*md("public/later.md", "Later", "A later vessel note."))
    new = s2.commit()
    with pytest.raises(tools.ToolError, match="adr index"):
        t.search("vessels")
    assert t.snapshot == new and log_lines(s)[-1]["snapshot"] == new


def test_a_long_lived_tools_sees_a_new_acl_snapshot(store, config):
    t = as_(store, "user:acme-4")
    assert did(ACME1) in result_ids(t.search("obsidianite memo"))
    d = json.loads(config[0].read_text())
    d["users"]["user:acme-4"] = ["group:acme/0"]
    config[0].write_text(json.dumps(d))
    assert did(ACME1) in result_ids(t.search("obsidianite memo"))  # before the sync
    acl.sync(store.path, *config, clock=fixed(T0))
    assert did(ACME1) not in result_ids(t.search("obsidianite memo"))


def test_overlays_are_parsed_once_per_file(store, monkeypatch):
    t = as_(store, "user:acme-0")
    t.search("vessel")
    loads = []
    real_app, real_dd = tools.load_overlay, tools.dedup_mod.load_overlay
    monkeypatch.setattr(tools, "load_overlay", lambda *a, **k: loads.append("app") or
                        real_app(*a, **k))
    monkeypatch.setattr(tools.dedup_mod, "load_overlay", lambda *a, **k: loads.append("dd") or
                        real_dd(*a, **k))
    t.search("vessel")
    t.grep("vessel")
    assert loads == []


# -- the log ------------------------------------------------------------------------------------

ACL_FIELDS = {"caller", "principals", "acl_snapshot", "acl_decision", "view", "not_visible"}


def test_log_fields_on_allowed_denied_failed_and_off_calls(store):
    sid = (store.path / "acl" / "HEAD").read_text().strip()
    t = as_(store, "user:acme-0")
    access = t._access()
    before = len(log_lines(store))
    t.search("vessel")
    with pytest.raises(tools.ToolError):
        t.grep("(")
    hidden = did(ACME1)
    with pytest.raises(tools.ToolError):
        t.read(hidden)
    with pytest.raises(tools.ToolError):
        t.read(hidden[:10], chunk="f" * 64)
    with pytest.raises(tools.AccessDenied):
        as_(store, "user:ghost").read(hidden)
    tools.Tools(store.path).search("vessel")
    allowed, failed, invisible, prefix, denied, off = log_lines(store)[before:]
    for ln in (allowed, failed, invisible, prefix, denied, off):
        assert set(ln) >= ACL_FIELDS
    assert allowed["caller"] == "user:acme-0" and allowed["acl_decision"] == "allowed"
    assert allowed["principals"] == list(access.principals)
    assert allowed["acl_snapshot"] == sid and allowed["view"] == access.view
    assert allowed["not_visible"] == [] and "error" not in allowed
    assert failed["acl_decision"] == "allowed" and failed["error"]
    assert invisible["not_visible"] == [hidden] and invisible["results"] == []
    assert prefix["not_visible"] == [hidden]
    assert denied["acl_decision"] == "denied:F4" and denied["caller"] == "user:ghost"
    assert denied["acl_snapshot"] == sid and denied["principals"] is None
    assert denied["not_visible"] is None
    assert off["acl_decision"] == "off" and off["caller"] is None
    assert off["principals"] is off["acl_snapshot"] is off["view"] is None


def test_the_index_tool_is_refused_with_acls(store):
    """Access is resolved first (F-codes apply); an allowed caller is then refused: the line
    says acl_decision "allowed" with the refusal as its error."""
    with pytest.raises(tools.ToolError, match="acl") as e:
        as_(store, "user:auditor").index("p1-struct", lexical_only=True)
    assert not isinstance(e.value, tools.AccessDenied)
    line = log_lines(store)[-1]
    assert set(line) >= ACL_FIELDS and line["acl_decision"] == "allowed"
    assert line["error"] == tools.INDEX_UNDER_ACL and line["results"] == []
    with pytest.raises(tools.AccessDenied):
        as_(store, "user:ghost").index("p1-struct", lexical_only=True)
    assert log_lines(store)[-1]["acl_decision"] == "denied:F4"


def test_operator_methods_are_refused_with_acls(store):
    """Only the tool methods serve a caller: the index and its global counts do not."""
    t = as_(store, "user:auditor")
    for fn in (t.active_index, t.active_system):
        with pytest.raises(tools.ToolError, match="operator"):
            fn()
    assert not hasattr(t, "projection")
    assert tools.Tools(store.path).active_system() == "p1-struct"


# -- the command line ---------------------------------------------------------------------------

def test_cli_as_enforces_the_acl(store, capsys, monkeypatch):
    from adr_store.cli import main

    monkeypatch.setattr(acl, "utc_now", fixed())
    monkeypatch.setattr(tools.Tools.__init__, "__kwdefaults__",
                        {**tools.Tools.__init__.__kwdefaults__, "clock": fixed()})
    s = str(store.path)
    code = main(["search", "quokkalith", "--store", s, "--as", "user:auditor", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and did(NOBODY) not in {h["doc_id"] for h in out["hits"]}
    code = main(["read", did(ACME1), "--store", s, "--as", "user:acme-0"])
    _, e = capsys.readouterr()
    assert code == 2 and e.startswith("error: no document")
    code = main(["grep", "vessel", "--store", s, "--as", "user:ghost"])
    _, e = capsys.readouterr()
    assert code == 2 and "access denied (F4)" in e
    code = main(["search", "quokkalith", "--store", s, "--json"])  # no --as: no ACL
    out = json.loads(capsys.readouterr().out)
    assert did(NOBODY) in {h["doc_id"] for h in out["hits"]}


@pytest.mark.parametrize("argv", [["--help"], ["search", "--help"], ["read", "--help"],
                                  ["grep", "--help"]])
def test_cli_help_says_adr_is_not_a_security_boundary(capsys, argv):
    from adr_store.cli import main

    with pytest.raises(SystemExit):
        main(argv)
    out = " ".join(capsys.readouterr().out.split())
    assert "not a security boundary" in out
    if argv != ["--help"]:
        assert "--as USER" in out


def test_access_cache_is_bounded(store):
    t = as_(store, "user:acme-0")
    t.search("vessel")
    assert isinstance(t._acl_cache, OrderedDict) and len(t._acl_cache) == 1


# -- the chain invariant: all versions of a source share access (spec §5.2) --------------------

SPLIT_RULES = [{"match": {"uri_prefix": "https://www.ecfr.gov/api/versioner/v1/full/2026-"},
                "access": ["group:acme/0"]},
               {"match": {"uri_prefix": "https://www.ecfr.gov/"}, "access": ["public"]},
               *RULES[:-1]]


def test_sync_refuses_a_policy_that_splits_a_chain(tmp_path):
    good = write_config(tmp_path / "good")
    s = make(tmp_path / "s", good)
    before = (s.path / "acl" / "HEAD").read_bytes()
    bad = write_config(tmp_path / "bad", SPLIT_RULES)
    with pytest.raises(acl.SyncError) as e:
        acl.sync(s.path, *bad, clock=fixed(T0))
    msg = str(e.value)
    assert "unchanged" in msg and not e.value.head_moved
    assert "ecfr:33:99" in msg
    for d in (V2024, V2025, V2026):
        assert doc_id(d) in msg
    assert (s.path / "acl" / "HEAD").read_bytes() == before
    last = json.loads((s.path / "acl" / "sync.jsonl").read_text().splitlines()[-1])
    assert last["outcome"] == "error" and "ecfr:33:99" in last["error"]


def test_a_rule_over_a_whole_chain_or_one_document_syncs(tmp_path):
    rules = [{"match": {"uri_prefix": "https://www.ecfr.gov/"}, "access": ["public"]},
             {"match": {"uri_prefix": "file://acl/acme/plan.md"}, "access": ["group:globex/1"]},
             *RULES]
    s = make(tmp_path / "s", write_config(tmp_path / "c", rules))
    snap = snapshot_of(s)
    assert {tuple(snap.docs[doc_id(d)]) for d in (V2024, V2025, V2026)} == {("public",)}
    assert snap.docs[did(ACME)] == ["group:globex/1"]
    t = as_(s, "user:outsider")
    assert "superseded by" in err(t.read, doc_id(V2025))  # its own chain: not secret
    assert t.read(doc_id(V2026)).doc_id == doc_id(V2026)


@pytest.mark.parametrize("caller,code", [("user:acme-1", "F1"), ("user:acme-4", None),
                                         ("user:outsider", None)])
def test_a_snapshot_that_splits_a_chain_denies_f1_to_a_view_it_splits(store, caller, code):
    """A hand-written snapshot gives the 2026 version another list: a view that holds some
    but not all versions is denied (no superseded_by or valid_to of a hidden version)."""
    snap = snapshot_of(store)
    put_snapshot(store, snap.model_copy(update={"docs": {**snap.docs,
                                                         doc_id(V2026): ["group:acme/0"]}}))
    t = as_(store, caller)
    if code is None:
        t.search("vessels")
        assert log_lines(store)[-1]["acl_decision"] == "allowed"
        return
    assert_denied(store, t, code)
    assert "chain" in err(t.read, doc_id(V2025))
    assert doc_id(V2026)[:8] not in err(t.read, doc_id(V2025))


# -- dense scores under the ACL layer: a function of (row, query) alone --------------------------

def test_the_dense_kernel_is_bit_exact_whatever_the_other_rows():
    from adr_store.retrieval.dense import row_scores

    rng = np.random.default_rng(20261116)
    for dim in (8, 384):
        big = rng.standard_normal((5000, dim)).astype(np.float32)
        big /= np.linalg.norm(big, axis=1, keepdims=True)
        q = rng.standard_normal(dim).astype(np.float32)
        q /= np.linalg.norm(q)
        whole = row_scores(big, q)
        assert whole.dtype == np.float32 and whole.shape == (5000,)
        for rows in (np.arange(16), np.arange(38), rng.choice(5000, 38, replace=False)):
            sub = big[rows]
            assert np.array_equal(row_scores(sub, q), whole[rows])
            buf = np.empty(sub.size + 1, dtype=np.float32)  # a misaligned copy
            mis = buf[1:].reshape(sub.shape)
            mis[:] = sub
            assert np.array_equal(row_scores(mis, q), whole[rows])
            for i, r in enumerate(rows):
                assert row_scores(sub[i:i + 1], q)[0] == whole[r]


def test_acl_searches_use_the_row_exact_kernel_and_acl_off_the_phase1_one(tmp_path, config,
                                                                         fake_models,
                                                                         monkeypatch):
    from adr_store.retrieval import dense as dense_mod

    s = make(tmp_path / "s", write_config(tmp_path / "c", [r for r in RULES if r["access"]]),
             dense=True)
    used = []
    real = dense_mod.row_scores
    monkeypatch.setattr(dense_mod, "row_scores", lambda v, q: used.append(len(v)) or real(v, q))
    tools.Tools(s.path).search("vessel")
    assert used == []  # acl=False: the Phase 1 matrix product, unchanged
    n = len(tools.Tools(s.path).active_index().chunks)
    as_(s, "user:auditor").search("vessel")  # sees every chunk: the fast path
    as_(s, "user:outsider").search("vessel")
    assert used and all(u == n for u in used)


# -- no applicability overlay; the overlay cache follows the file -------------------------------

def test_the_view_applies_on_a_store_without_an_overlay(tmp_path, config):
    s = make_gov_store(tmp_path / "s", DOCS)
    tools.Tools(s.path).index("p1-struct", lexical_only=True)
    acl.sync(s.path, *config, clock=fixed(T0))
    for caller in USERS:
        t, mine = as_(s, caller), visible(s, caller)
        res = t.search("vessel harbour refund", top=50)
        assert res.applicability is None and res.excluded_by_filter == 0
        assert result_ids(res) <= mine
        assert result_ids(t.grep("vessel")) <= mine
        hidden = sorted(set(s.doc_ids()) - mine)
        if hidden:
            assert err(t.read, hidden[0]) == err(t.read, absent_like(hidden[0], s.doc_ids()))
    assert did(NOBODY) not in result_ids(as_(s, "user:auditor").grep("quokkalith"))


def test_a_rewritten_overlay_is_read_again_on_the_next_call(store):
    t = as_(store, "user:acme-1")
    t.search("vessels")
    app = ap.overlay_path(store.path, store.snapshot_id)
    data = app.read_bytes()
    app.unlink()
    app.write_bytes(data[:-2] + b"x\n")  # another file under the name: a new stat
    with pytest.raises(tools.ToolError, match="not a valid overlay|canonical"):
        t.search("vessels")
    app.unlink()
    app.write_bytes(data)
    assert t.search("vessels").applicability is not None
    idx = tools.Tools(store.path).active_index()
    dd = dedup.overlay_path(store.path, store.snapshot_id, idx.chunker,
                            chunk_content_sha256(idx.chunks.values()))
    data = dd.read_bytes()
    dd.unlink()
    dd.write_bytes(data.replace(b'"format_version":"0.1"', b'"format_version":"9.9"'))
    with pytest.raises(tools.ToolError, match="dedup overlay"):
        t.search("vessels")
