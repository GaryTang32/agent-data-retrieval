"""The three table tools (Phase 3 spec §8, §9; Task 6): `describe_tables`, `query_table` and `sql`
in `adr_store.tools.Tools`, under the Phase 2 ACL layer, applicability filters and snapshot
handles. A gov fixture store (the Federal Register fixture documents and two versions of 33 CFR
117) with per-document access rules, a lexical index, its tables built and promoted through the
gate; reference stores hold one view's documents alone. Everything under `tmp_path`."""

import gc
import hashlib
import json
import re
import weakref
from datetime import timedelta

import pytest

from adr_store import acl, handles, tools
from adr_store import applicability as ap
from adr_store.store import Store
from adr_store.tables.build import build_tables
from adr_store.tables.engine import QUERY_LIMIT
from adr_store.tables.gate import gate
from adr_store.tables.overlay import TABLES_DIR, manifest_path, read_head
from adr_store.tables.semantic import ERR_UNKNOWN_TABLE
from adr_store.tables.sqlguard import ERR_DENIED, ERR_SYNTAX
from adr_store.tools import NO_HANDLE_TABLES, ToolError
from tests.store.tables_fixtures import (
    ECFR_NEW,
    ECFR_OLD,
    FR_DOCS,
    T0,
    ecfr_doc,
    fr_doc,
    make_tables_store,
)

FR_URI = "https://www.federalregister.gov/api/v1/documents/"


def fr(n: int, access: list[str]) -> dict:
    return {"match": {"uri_prefix": f"{FR_URI}2024-0000{n}."}, "access": access}


# every document matches a rule (no hash bucket can make one public)
RULES = [
    fr(1, ["tenant:acme", "tenant:globex"]),
    fr(2, ["group:acme/0"]),
    fr(3, ["tenant:globex"]),
    fr(4, ["group:acme/1"]),
    fr(5, ["tenant:acme"]),
    fr(6, []),
    fr(7, ["group:globex/0"]),
    {"match": {"uri_prefix": "https://www.ecfr.gov/"}, "access": ["tenant:acme"]},
]
DOCS = [*FR_DOCS, ecfr_doc(ECFR_OLD), ecfr_doc(ECFR_NEW)]
USERS = ["user:acme-0", "user:acme-1", "user:acme-4", "user:globex-0", "user:outsider",
         "user:auditor"]
NOW = T0 + timedelta(minutes=1)
FR = "fr_documents"


def promote(path, corpus: str = "gov") -> str:
    tables_id = build_tables(path, corpus).tables_id
    assert gate(path, tables_id, [], 0).promoted
    return tables_id


def make(path, docs=DOCS, *, rules=RULES, tables: bool = True, corpus: str = "gov") -> Store:
    s = make_tables_store(path, docs, rules=rules)
    tools.Tools(path).index("p1-struct", lexical_only=True)
    if tables:
        promote(path, corpus)
    return s


@pytest.fixture
def built(tmp_path):
    return make(tmp_path / "store")


def as_(store, caller: str = "user:auditor") -> tools.Tools:
    return tools.Tools(store.path, acl=True, caller=caller, clock=lambda: NOW)


def visible(store, caller) -> set[str]:
    snap = acl.read_head(store.path)[1]
    ps = set(snap.directory[caller])
    return {d for d, v in snap.docs.items() if ps & set(v)}


def number(store, doc_id: str) -> str | None:
    uri = store.source(doc_id).uri
    return uri[len(FR_URI):].split(".json")[0] if uri.startswith(FR_URI) else None


def log_lines(store) -> list[dict]:
    path = store.path / "log" / "retrieval.jsonl"
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]


STORE_SPECIFIC = ("snapshot", "tables", "applicability", "handle")


def strip(outcome):
    """A result as a dict without the fields naming store versions, or an error's text."""
    if isinstance(outcome, Exception):
        return ("error", str(outcome))
    return {k: v for k, v in outcome.to_dict().items() if k not in STORE_SPECIFIC}


def outcome(call, t):
    try:
        return call(t)
    except ToolError as e:
        return e


TABLE_CALLS = [
    lambda t: t.query_table(FR),
    lambda t: t.query_table(FR, {"type": "Rule"}, "count"),
    lambda t: t.query_table(FR, {"year": 2024}, "list"),
    lambda t: t.query_table(FR, {"id": "2024-00003"}, "lookup"),      # hidden from acme users
    lambda t: t.query_table(FR, {"id": "2024-00006"}, "lookup"),      # visible to no one
    lambda t: t.query_table(FR, {"id": "2099-99999"}, "lookup"),      # nonexistent
    lambda t: t.query_table(FR, op="count_by", fields=["type"]),
    lambda t: t.query_table(FR, op="lookup", fields=["id", "year"], order=["-id"], limit=3),
    lambda t: t.query_table("agencies", op="count_by", fields=["display_name"]),
    lambda t: t.query_table("waterways", op="list"),
    lambda t: t.query_table("waterways", op="list", applicability={"include_superseded": True}),
    lambda t: t.query_table(FR, op="list", applicability={"as_of": "2024-06-01"}),
    lambda t: t.query_table(FR, {"bogus": 1}),
    lambda t: t.query_table("no_such_table"),
    lambda t: t.sql("SELECT count(*), sum(year) FROM fr_documents"),
    lambda t: t.sql("SELECT type, count(*) FROM fr_documents GROUP BY type"),
    lambda t: t.sql("SELECT a.display_name, count(*) FROM agencies a JOIN fr_agencies f "
                    "ON f.agency_id = a.entity_id GROUP BY 1"),
    lambda t: t.sql("SELECT _doc_id, id, _prov_title FROM fr_documents WHERE id = '2024-00003'"),
    lambda t: t.sql("SELECT * FROM sqlite_master"),
    lambda t: t.sql("SELECT key, count(*) FROM waterways GROUP BY key",
                    applicability={"include_superseded": True}),
    lambda t: t.describe_tables(),
    lambda t: t.describe_tables(FR),
]


def reference(tmp_path, store, docs: set[str]) -> tools.Tools:
    """The tools (no ACL layer) of a store built from `docs` alone, its tables promoted."""
    path = tmp_path / f"ref-{acl.view_id(docs)[:12]}"
    if not path.exists():
        make_tables_store(path, [d for d in DOCS if d[0].doc_id in docs])
        promote(path)
    return tools.Tools(path)


# -- rows follow document access (hidden equals nonexistent) -----------------------------------

def test_rows_follow_document_access(built, tmp_path):
    views = set()
    for user in USERS:
        docs = visible(built, user)
        if not docs:
            continue   # the empty view: test_an_empty_view_counts_zero
        views.add(frozenset(docs))
        t, ref = as_(built, user), reference(tmp_path, built, docs)
        for i, call in enumerate(TABLE_CALLS):
            assert strip(outcome(call, t)) == strip(outcome(call, ref)), (user, i)
    assert len(views) >= 4


def test_a_hidden_id_lookup_equals_a_nonexistent_one(built):
    t = as_(built, "user:acme-0")
    hidden, missing = (t.query_table(FR, {"id": i}, "lookup") for i in ("2024-00003",
                                                                         "2099-99999"))
    assert strip(hidden) == {**strip(missing), "filters": {"id": "2024-00003"}}
    assert hidden.rows == [] and hidden.value is None and not hidden.truncated
    # the same for a count, an aggregate and an error naming the hidden id
    assert t.query_table(FR, {"id": "2024-00003"}).count == 0
    assert t.sql("SELECT count(*) FROM fr_documents WHERE id = '2024-00003'").rows == [[0]]
    a = outcome(lambda x: x.query_table(FR, {"id__bogus": "2024-00003"}), t)
    b = outcome(lambda x: x.query_table(FR, {"id__bogus": "2099-99999"}), t)
    assert str(a) == str(b) == "unknown operator 'bogus' in 'id__bogus'"
    # the auditor sees it
    assert [r["row"]["id"] for r in as_(built).query_table(
        FR, {"id": "2024-00003"}, "lookup").rows] == ["2024-00003"]


def test_the_view_shows_only_its_documents_rows(built):
    for user in USERS:
        t = as_(built, user)
        docs = visible(built, user)
        want = sorted(n for d in docs if (n := number(built, d)) is not None)
        got = t.query_table(FR, op="list", applicability={"include_superseded": True})
        assert got.ids == want
        rows = t.sql("SELECT DISTINCT _doc_id FROM waterways",
                     applicability={"include_superseded": True}).rows
        assert {r[0] for r in rows} <= docs


def test_as_of_drops_rows_of_documents_not_in_force(built):
    store = Store.open(built.path)
    overlay = ap.load_overlay(built.path, store.snapshot_id)
    for as_of in ("2024-03-02", "2024-06-01"):
        view = sorted(visible(built, "user:auditor"))   # all but 2024-00006 (no one's)
        admitted, excluded = overlay.allowed_docs(view, ap.Filters(as_of=as_of))
        want = {number(store, d) for d in admitted} - {None}
        r = as_(built).query_table(FR, op="list", applicability={"as_of": as_of})
        assert set(r.ids) == want
        assert r.excluded_by_filter == excluded
        assert r.applicability_filters["as_of"] == as_of
    r = as_(built).query_table(FR, op="list", applicability={"as_of": "2024-06-01"})
    assert r.ids and not {"2024-00002", "2024-00005"} & set(r.ids)   # proposals excluded
    statuses = as_(built).sql("SELECT DISTINCT status FROM fr_documents",
                              applicability={"as_of": "2024-06-01"}).rows
    assert statuses == [["final_rule"]]


def test_the_default_filters_drop_superseded_rows(built):
    store = Store.open(built.path)
    old = next(d for d in store.doc_ids() if ECFR_OLD in store.source(d).uri)
    t = as_(built)
    q = f"SELECT count(*) FROM waterways WHERE _doc_id = '{old}'"
    assert t.sql(q).rows == [[0]]
    assert t.sql(q, applicability={"include_superseded": True}).rows[0][0] > 0
    d, a = t.query_table("waterways"), t.query_table(
        "waterways", applicability={"include_superseded": True})
    assert d.count < a.count and d.excluded_by_filter == 1 and a.excluded_by_filter == 0


def test_bad_applicability_is_refused_with_the_phase2_message(built):
    with pytest.raises(ToolError, match=r"^bad filters: "):
        as_(built).query_table(FR, applicability={"as_of": "yesterday"})
    with pytest.raises(ToolError, match=r"^bad filters: "):
        as_(built).sql("SELECT 1", applicability={"bogus": True})


# -- results, caps and messages ------------------------------------------------------------------

def test_query_results_carry_their_arguments_and_versions(built):
    t = as_(built)
    r = t.query_table(FR, {"type": "Rule"}, "count")
    assert (r.table, r.op, r.filters, r.fields, r.order, r.limit) == (
        FR, "count", {"type": "Rule"}, None, None, QUERY_LIMIT)
    assert r.count == 4 and r.ids is None and r.rows is None and r.groups is None
    assert r.snapshot == Store.open(built.path).snapshot_id
    assert r.tables == read_head(built.path)
    assert r.applicability == handles.file_sha256(ap.overlay_path(built.path, r.snapshot))
    assert r.applicability_filters == ap.Filters().to_dict()
    lk = t.query_table(FR, {"id": "2024-00001"}, "lookup", fields=["year"])
    assert lk.value == 2024 and lk.rows[0]["doc_id"] and lk.rows[0]["prov"]["year"]
    assert t.query_table(FR, {"type": 1}).never_matches == [
        "type: an int value never matches a text column"]


def test_engine_errors_and_sql_refusals_are_tool_errors_with_the_fixed_text(built):
    t = as_(built)
    for call, text in [
        (lambda: t.query_table(FR, op="median"), "unknown op 'median'; known: count, list, "
                                                 "lookup, count_by"),
        (lambda: t.query_table(FR, limit=0), "limit must be an integer from 1 to 1000, got 0"),
        (lambda: t.query_table(FR, op="count_by"), "count_by takes exactly one field"),
        (lambda: t.sql("DELETE FROM fr_documents"), ERR_SYNTAX),
        (lambda: t.sql("SELECT 1; SELECT 2"), ERR_SYNTAX),
        (lambda: t.sql("SELECT name FROM sqlite_master"), ERR_DENIED),
        (lambda: t.describe_tables("no_such_table"), ERR_UNKNOWN_TABLE),
    ]:
        with pytest.raises(ToolError) as e:
            call()
        assert str(e.value) == text


def test_list_and_count_by_are_capped_with_a_truncation_flag(built, monkeypatch):
    t = as_(built)
    full = t.query_table(FR, op="list")
    groups = t.query_table(FR, op="count_by", fields=["id"])
    assert not full.truncated and not groups.truncated and len(full.ids) == 6
    monkeypatch.setattr(tools, "QUERY_ROW_CAP", 4)
    capped = t.query_table(FR, op="list")
    assert capped.ids == full.ids[:4] and capped.truncated
    cg = t.query_table(FR, op="count_by", fields=["id"])
    assert cg.groups == groups.groups[:4] and cg.truncated
    assert tools.QUERY_ROW_CAP == 4 and t.query_table(FR, op="list", limit=2).ids == capped.ids


def test_the_row_cap_is_the_sql_row_cap():
    from adr_store.tables.sqlguard import SQL_ROW_CAP

    assert tools.QUERY_ROW_CAP == SQL_ROW_CAP == 1000


def test_sql_results_are_ordered_and_hashed(built):
    stmt = "SELECT type, count(*) AS n FROM fr_documents GROUP BY type"
    r = as_(built).sql(stmt)
    assert r.statement_sha256 == hashlib.sha256(stmt.encode()).hexdigest()
    assert r.columns == ["type", "n"] and r.rows == [["Proposed Rule", 2], ["Rule", 4]]
    assert not r.truncated and r.tables == read_head(built.path)


def test_describe_tables_is_the_semantic_layer_of_the_build(built):
    r = as_(built).describe_tables()
    assert r.tables == read_head(built.path)
    names = [x["name"] for x in r.semantic["tables"]]
    assert names == sorted(names) and FR in names and "papers" not in names
    detail = as_(built).describe_tables(FR).semantic
    assert detail["name"] == FR and "columns" in detail
    for res in (r, as_(built).describe_tables(FR)):
        assert len(json.dumps(res.semantic, separators=(",", ":")).encode()) <= 8192


def test_no_report_is_served(built):
    """The `.report.json` files (entity samples, largest clusters, rejections) are operator-only:
    no table tool result names their content."""
    reports = list((built.path / TABLES_DIR).glob("*/*.report.json"))
    assert reports
    t = as_(built)
    blob = json.dumps([t.describe_tables().to_dict(), t.describe_tables("agencies").to_dict()])
    for key in ("samples", "largest", "rejected", "null_reasons"):
        assert f'"{key}"' not in blob


# -- the per-view database cache -----------------------------------------------------------------

def test_view_databases_are_cached_by_tables_view_and_filters(built, monkeypatch):
    assert tools.TABLE_DB_CACHE == 8
    t = as_(built, "user:acme-4")
    t.query_table(FR)
    t.sql("SELECT 1 FROM fr_documents")
    assert len(t._table_dbs) == 1
    (key, db), = t._table_dbs.items()
    access = t._access()
    assert key[:3] == (read_head(built.path), access.view,
                       json.dumps(ap.Filters().to_dict(), sort_keys=True))
    t.query_table(FR, applicability={"include_superseded": True})
    assert len(t._table_dbs) == 2
    other = list(t._table_dbs)[1]
    assert other[:2] == key[:2] and other[2] != key[2]
    t.query_table(FR, op="list")
    assert t._table_dbs[key] is db                       # reused for the same filters
    monkeypatch.setattr(tools, "TABLE_DB_CACHE", 2)
    t.query_table(FR, applicability={"as_of": "2024-06-01"})
    assert len(t._table_dbs) == 2 and other not in t._table_dbs   # least recently used out
    assert key in t._table_dbs
    # another caller's instance builds its own database: another view, another object
    mine = dict(t._table_dbs)
    g = as_(built, "user:globex-0")
    assert g.query_table(FR, op="list").ids != t.query_table(FR, op="list").ids
    (gkey, gdb), = g._table_dbs.items()
    assert gkey[1] == g._access().view != access.view and gkey[0] == key[0]
    assert all(gdb is not d for d in t._table_dbs.values())
    assert dict(t._table_dbs) == mine


def test_an_acl_resync_builds_a_new_view_database_without_the_revoked_rows(built):
    """One `Tools` instance across a re-sync that revokes a document: the next call resolves the
    new view, builds a new database without the revoked rows, and an old handle (which names no
    ACL) replays against the current ACL with the same reduced result."""
    wide = {"include_superseded": True}
    t = as_(built, "user:acme-0")
    before = t.query_table(FR, op="list", applicability=wide)
    counted = t.sql("SELECT count(*) FROM fr_documents", applicability=wide)
    assert "2024-00001" in before.ids
    (old_key, old_db), = t._table_dbs.items()
    config = built.path.parent / f"{built.path.name}-acl"
    policy = json.loads((config / "policy.json").read_text(encoding="utf-8"))
    assert policy["rules"][0] == fr(1, ["tenant:acme", "tenant:globex"])
    policy["rules"][0] = fr(1, ["tenant:globex"])
    (config / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
    acl.sync(built.path, config / "directory.json", config / "policy.json", clock=lambda: T0)
    after = t.query_table(FR, op="list", applicability=wide)
    assert after.ids == [i for i in before.ids if i != "2024-00001"]
    assert t.sql("SELECT count(*) FROM fr_documents", applicability=wide).rows == \
        [[counted.rows[0][0] - 1]]
    assert len(t._table_dbs) == 2
    new_key = next(k for k in t._table_dbs if k != old_key)
    assert new_key[0] == old_key[0] and new_key[1] != old_key[1]
    assert new_key[1] == t._access().view and t._table_dbs[new_key] is not old_db
    replay = t.query_table(FR, op="list", applicability=wide, handle=before.handle)
    assert replay == after and replay.handle == before.handle
    assert t.query_table(FR, {"id": "2024-00001"}, "lookup", applicability=wide,
                         handle=before.handle).rows == []


def test_views_with_the_same_rows_still_get_their_own_database(built):
    """Two filter sets that admit the same documents are two entries (never reused across
    filters), with equal answers."""
    t = as_(built, "user:globex-0")   # sees no superseded document: both filters admit the same
    a = t.query_table("waterways", op="list")
    b = t.query_table("waterways", op="list", applicability={"include_superseded": True})
    assert a.ids == b.ids and len(t._table_dbs) == 2


# -- handles ---------------------------------------------------------------------------------

def test_every_result_carries_a_handle_with_tables_and_replays(built):
    r = as_(built).query_table(FR, {"year": 2024}, "list")
    assert r.handle["tables"] == read_head(built.path)
    assert as_(built).query_table(FR, {"year": 2024}, "list", handle=r.handle) == r
    for res in (as_(built).describe_tables(), as_(built).sql("SELECT 1")):
        assert res.handle == r.handle
    s = as_(built).sql("SELECT id FROM fr_documents")
    assert as_(built).sql("SELECT id FROM fr_documents", handle=s.handle) == s
    d = as_(built).describe_tables(FR)
    assert as_(built).describe_tables(FR, handle=d.handle) == d
    manifest_path(built.path, r.handle["tables"]).unlink()
    with pytest.raises(ToolError, match="^handle no longer available: tables$"):
        as_(built).sql("SELECT 1", handle=r.handle)


def test_a_handle_keeps_its_tables_when_head_moves(built):
    r = as_(built).query_table(FR, op="count_by", fields=["type"])
    # a second build with one table changed, promoted (HEAD moves)
    from tests.store.test_tables_gate import derived, retype

    new = derived(built.path, r.tables, retype(2))
    assert gate(built.path, new, [], 0).promoted and read_head(built.path) == new
    now = as_(built).query_table(FR, op="count_by", fields=["type"])
    assert now.tables == new and now.groups != r.groups
    assert as_(built).query_table(FR, op="count_by", fields=["type"], handle=r.handle) == r


def test_a_phase2_handle_without_tables(built):
    current = as_(built).search("drawbridge").handle
    assert current["tables"] == read_head(built.path)
    old = {k: v for k, v in current.items() if k not in ("tables", "units")}
    assert as_(built).search("drawbridge", handle=old).hits
    assert as_(built).search("drawbridge", handle=old).handle == {**old, "tables": None,
                                                                  "units": None}
    for call in (lambda t: t.query_table(FR, handle=old), lambda t: t.sql("SELECT 1", handle=old),
                 lambda t: t.describe_tables(handle=old)):
        with pytest.raises(ToolError, match=re.escape(NO_HANDLE_TABLES)):
            call(as_(built))


def test_a_handle_naming_tables_of_another_snapshot_is_bad(built, tmp_path):
    other = make(tmp_path / "other", [*FR_DOCS])
    tid = read_head(other.path)
    m = manifest_path(other.path, tid)
    dst = built.path / TABLES_DIR / m.parent.name
    dst.mkdir(parents=True)
    for f in m.parent.iterdir():
        (dst / f.name).write_bytes(f.read_bytes())
    h = {**as_(built).query_table(FR).handle, "tables": tid}
    with pytest.raises(ToolError, match=rf"^bad handle: tables {tid[:12]} is for snapshot "
                                        rf"{m.parent.name[:12]}$"):
        as_(built).query_table(FR, handle=h)


def test_the_bad_handle_message_lists_the_phase2_components(built):
    with pytest.raises(ToolError) as e:
        as_(built).query_table(FR, handle="nope")
    assert str(e.value) == ("bad handle: expected an object with the fields snapshot, index, "
                            "applicability, dedup, tools, tool_index, got str")


# -- Phase 2 tools are unchanged -------------------------------------------------------------

def phase2_calls(store):
    doc = sorted(visible(store, "user:auditor"))[0]
    return [lambda t: t.search("vessel"), lambda t: t.search("drawbridge", top=3),
            lambda t: t.read(doc), lambda t: t.read(doc, 0, 40), lambda t: t.grep("Coast"),
            lambda t: t.grep("bridge", doc=doc), lambda t: t.search_tools("x"),
            lambda t: t.load_tool("abcdefgh"), lambda t: t.read("0" * 64)]


def test_the_five_phase2_tools_are_unchanged(tmp_path):
    store = make(tmp_path / "s", tables=False)

    def run():
        out = []
        for user in USERS:
            for call in phase2_calls(store):
                res = outcome(call, as_(store, user))
                if isinstance(res, Exception):
                    out.append(("error", str(res)))
                else:
                    d = res.to_dict()
                    out.append((d.pop("handle"), d))
        return out

    before = run()
    tid = promote(store.path)
    after = run()
    assert len(before) == len(after)
    for b, a in zip(before, after, strict=True):
        if b[0] == "error":
            assert a == b
        else:
            assert a[1] == b[1]
            assert b[0]["tables"] is None and a[0] == {**b[0], "tables": tid}


# -- the log ---------------------------------------------------------------------------------

def test_log_lines_carry_tables_and_the_sql_hash_not_its_text(built):
    t = as_(built, "user:acme-4")
    stmt = "SELECT id FROM fr_documents WHERE title LIKE '%Neuse River%'"
    t.describe_tables()
    t.query_table(FR, {"type": "Rule"}, applicability={"include_superseded": True})
    t.sql(stmt)
    with pytest.raises(ToolError):
        t.sql("SELECT * FROM sqlite_master WHERE name = 'Neuse River secret'")
    lines = log_lines(built)[-4:]
    tid = read_head(built.path)
    access = t._access()
    for ln in lines:
        assert ln["tables"] == tid and ln["caller"] == "user:acme-4"
        assert ln["acl_decision"] == "allowed" and ln["view"] == access.view
        assert ln["principals"] == list(access.principals)
        assert ln["acl_snapshot"] == access.acl_snapshot and ln["not_visible"] == []
    for ln in lines[:3]:
        assert ln["handle"]["tables"] == tid
    assert lines[3]["handle"] is None   # a failed call logs the handle it was given
    assert [ln["tool"] for ln in lines] == ["describe_tables", "query_table", "sql", "sql"]
    assert lines[1]["args"] == {"table": FR, "filters": {"type": "Rule"}, "op": "count",
                                "fields": None, "order": None, "limit": QUERY_LIMIT,
                                "applicability": {"include_superseded": True}}
    assert lines[1]["applicability_filters"]["include_superseded"] is True
    for ln in lines[2:]:
        assert set(ln["args"]) == {"statement_sha256", "applicability"}
        assert ln["sql_sha256"] == ln["args"]["statement_sha256"]
        assert "Neuse" not in json.dumps(ln)
    assert lines[2]["sql_sha256"] == hashlib.sha256(stmt.encode()).hexdigest()
    # no row value is logged for sql: the row count only
    assert lines[2]["results"] == [] and lines[2]["sql_rows"] == 1
    assert lines[3]["error"] == ERR_DENIED and lines[3]["sql_rows"] is None


# -- the empty view, older snapshots, denials ----------------------------------------------------

def test_an_empty_view_counts_zero(built):
    t = as_(built, "user:outsider")
    assert visible(built, "user:outsider") == set()
    assert t.describe_tables().semantic["tables"]
    assert t.query_table(FR).count == 0
    assert t.query_table(FR, op="list").ids == []
    assert t.query_table(FR, op="count_by", fields=["type"]).groups == []
    assert t.query_table("agencies", op="lookup").rows == []
    assert t.sql("SELECT count(*), sum(year) FROM fr_documents").rows == [[0, None]]


def test_tables_of_an_older_snapshot_are_refused(built, tmp_path):
    old = as_(built).query_table(FR)
    s = Store.open(built.path)
    s.add(*fr_doc("2024-00099"))
    s.commit()
    new = Store.open(built.path).snapshot_id
    config = built.path.parent / f"{built.path.name}-acl"
    acl.sync(built.path, config / "directory.json", config / "policy.json", clock=lambda: T0)
    with pytest.raises(ToolError, match=r"^no tables for snapshot ") as e:
        as_(built).query_table(FR)
    assert str(e.value) == (f"no tables for snapshot {new[:12]}…; run `adr tables build` and "
                            f"`adr tables gate`")
    for call in (lambda t: t.sql("SELECT 1"), lambda t: t.describe_tables()):
        with pytest.raises(ToolError, match=r"^no tables for snapshot "):
            call(as_(built))
    # the old handle still reads its own snapshot's tables
    assert as_(built).query_table(FR, handle=old.handle) == old


def test_a_store_without_tables_refuses_with_the_build_hint(tmp_path):
    store = make(tmp_path / "s", tables=False)
    with pytest.raises(ToolError, match=r"^no tables for snapshot \w{12}…; run `adr tables "
                                        r"build` and `adr tables gate`$"):
        as_(store).describe_tables()


def test_a_build_not_promoted_is_not_used(tmp_path):
    store = make(tmp_path / "s", tables=False)
    build_tables(store.path, "gov")
    with pytest.raises(ToolError, match=r"^no tables for snapshot "):
        as_(store).query_table(FR)


@pytest.mark.parametrize("caller,code", [("user:ghost", "F4"), (None, "F4"), ("acme", "F5")])
def test_denied_callers_get_nothing(built, caller, code):
    t = tools.Tools(built.path, acl=True, caller=caller, clock=lambda: NOW)
    calls = [lambda: t.describe_tables(), lambda: t.query_table(FR),
             lambda: t.sql("SELECT count(*) FROM fr_documents")]
    n = len(log_lines(built))
    for call in calls:
        with pytest.raises(tools.AccessDenied) as e:
            call()
        assert e.value.code == code and str(e.value).startswith(f"access denied ({code}): ")
    lines = log_lines(built)[n:]
    assert len(lines) == 3
    for ln in lines:
        assert ln["acl_decision"] == f"denied:{code}" and ln["results"] == []
        assert ln["view"] is None and ln["tables"] is None


def test_a_stale_acl_denies_f3(built):
    t = tools.Tools(built.path, acl=True, caller="user:auditor",
                    clock=lambda: NOW + timedelta(hours=2))
    with pytest.raises(tools.AccessDenied) as e:
        t.query_table(FR)
    assert e.value.code == "F3"


def test_without_the_acl_layer_every_row_is_seen(built):
    t = tools.Tools(built.path)
    assert t.query_table(FR, applicability={"include_superseded": True}).count == 7
    assert log_lines(built)[-1]["acl_decision"] == "off"


def test_a_research_store_has_its_own_tables(tmp_path):
    from tests.store.tables_fixtures import MANIFEST

    rules = [{"match": {"uri_prefix": "file://papers/"}, "access": ["tenant:acme"]}]
    store = make(tmp_path / "r", [MANIFEST], rules=rules, corpus="research")
    names = [x["name"] for x in as_(store).describe_tables().semantic["tables"]]
    assert "papers" in names and FR not in names
    n = as_(store).query_table("papers").count
    assert n > 0 and as_(store, "user:acme-0").query_table("papers").count == n
    assert as_(store, "user:globex-0").query_table("papers").count == 0   # all or nothing


def test_a_refusal_keeps_no_database_alive(built):
    """A refused statement's traceback holds the database (the guard's and the engine's frames)
    but no cycle (`run_sql` drops its refusal), so once the caller drops the error and the tools,
    a database is freed (and closed) by reference counting, not left to the cycle collector."""
    t = as_(built)
    t.sql("SELECT 1 FROM fr_documents")
    ref = weakref.ref(next(iter(t._table_dbs.values())))
    gc.collect()
    gc.disable()
    try:
        for stmt in ("SELECT * FROM sqlite_master", "SELECT nosuch FROM fr_documents",
                     "WITH RECURSIVE c(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM c) "
                     "SELECT count(*) FROM c"):
            with pytest.raises(ToolError):
                t.sql(stmt)
        for filters, op in (({"bogus": 1}, "count"), ({}, "median")):
            with pytest.raises(ToolError):
                t.query_table(FR, filters, op)
        del t
        assert ref() is None
    finally:
        gc.enable()
