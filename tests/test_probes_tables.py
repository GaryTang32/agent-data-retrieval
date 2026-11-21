"""Table probes (Phase 3 spec §10.4, criteria S1–S3, D1): leak probes of the three table tools
against reference stores of each view, the SQL guard cases, table equivalence, the 90
fail-closed probes, applicability and the log scan, on the gov fixture store of
`tests/store/test_tables_tools.py` (FR documents and two eCFR versions with per-document access
rules, a lexical index, tables built and promoted). Nothing reads `data/` or `.cache/`."""

import json
from collections import Counter
from pathlib import Path

import pytest

from adr_eval.cli import main
from adr_eval.probes import tables as tp
from adr_eval.probes.acl import CONDITIONS
from adr_store import acl, tools
from adr_store.store import Store
from adr_store.tables.engine import ViewDB
from adr_store.tables.sqlguard import ERR_BUDGET, ERR_DENIED, ERR_ROWS, ERR_SYNTAX
from tests.store.tables_fixtures import make_tables_store
from tests.store.test_tables_tools import FR, NOW, RULES, fr, make

REPO = Path(__file__).parents[1]
GOLD = REPO / "golden" / "gov" / "v0.1" / "items.jsonl"
SMALL = dict.fromkeys(tp.LEAK_SIZES["gov"], 4)
FIXED = {ERR_SYNTAX, ERR_DENIED, ERR_BUDGET, ERR_ROWS}
# document 1 is public: every directory user sees it (the fail-closed target needs that)
PUBLIC_RULES = [fr(1, ["public"]), *RULES[1:]]


def config_of(store) -> tuple[Path, Path]:
    d = store.path.parent / f"{store.path.name}-acl"
    return d / "directory.json", d / "policy.json"


def kw(store, tmp_path, clock=lambda: NOW) -> dict:
    directory, policy = config_of(store)
    return {"directory": directory, "policy": policy, "clock": clock,
            "emb_cache": tmp_path / "emb"}


@pytest.fixture
def built(tmp_path):
    return make(tmp_path / "store")


@pytest.fixture
def public(tmp_path):
    return make(tmp_path / "public", rules=PUBLIC_RULES)


@pytest.fixture
def three_b(tmp_path, monkeypatch):
    """`built` with the extraction (3B) tables too: built through the model profile "gen"
    (a cached stub of the fixture's first-pass replies, `runner.make_client` patched for every
    profile) and promoted. (store, the replies the stub computed: one per uncached call)."""
    from adr_eval import runner
    from adr_eval.cache import Cache
    from adr_eval.llm import CachedStubClient
    from adr_store.tables.build import build_tables
    from adr_store.tables.gate import gate
    from tests.store.tables_fixtures import fixture_reply

    replies: list[str] = []

    def reply(system, user, repeat):
        replies.append(user)
        return fixture_reply(system, user, repeat)

    def make_client(name, profiles, cache, max_retries=5):
        return CachedStubClient(f"stub-{name}", Cache(tmp_path / "llm"), reply)

    monkeypatch.setattr(runner, "make_client", make_client)
    store = make(tmp_path / "store3b", tables=False)
    tables_id = build_tables(store.path, "gov", with_extraction=True, generator_profile="gen",
                             max_calls=100).tables_id
    assert gate(store.path, tables_id, [], 0).promoted
    assert replies   # the store's own build made the calls; later builds must read the cache
    return store, replies


def leaking_view_databases(monkeypatch):
    """`ViewDB.build` ignoring the admitted documents: every caller's database holds every
    row (a planted leak)."""
    real = ViewDB.build.__func__

    def build(cls, store_path, manifest, tables_id, admitted, **k):
        return real(cls, store_path, manifest, tables_id, None, **k)

    monkeypatch.setattr(ViewDB, "build", classmethod(build))


# -- leak probes -------------------------------------------------------------------------------


def test_leak_probes_cover_every_family_and_find_no_leak(built, tmp_path):
    probes = tp.leak_probes(built.path, "gov", sizes=SMALL)
    assert {p.family for p in probes} == set(tp.LEAK_SIZES["gov"])
    assert Counter(p.family for p in probes) == Counter(SMALL)
    assert probes == tp.leak_probes(built.path, "gov", sizes=SMALL)   # deterministic
    snap = acl.read_head(built.path)[1]
    for p in probes:   # the target's value is held by documents the caller cannot see only
        seen = {d for d, v in snap.docs.items()
                if set(snap.directory.get(p.caller, ())) & set(v)}
        assert p.target["doc_id"] not in seen
        assert p.target["in_directory"] == (p.caller in snap.directory)
    results = tp.run_leaks(probes, built.path, tmp_path / "views", **kw(built, tmp_path))
    assert len(results) == len(probes)
    assert all(r.valid for r in results), [r.note for r in results if not r.valid]
    assert all(not any(r.kinds.values()) for r in results)
    checked = {k for r in results for k, v in r.kinds.items() if v is not None}
    assert checked == set(tp.LEAK_KINDS)
    # a directory user has a hidden row, so every probe compares against a reference store
    assert "user:outsider" in {r.caller for r in results}
    assert not any(p.caller == "user:ghost" for p in probes)
    summary = tp.summarize_leaks(results)
    assert summary["total"]["n"] == 20 and summary["total"]["leaks"] == 0
    assert summary["total"]["compared"] == 20 and summary["total"]["ghost"] == 0


def test_ghost_is_drawn_only_when_no_user_has_a_hidden_row(tmp_path):
    """The research manifest is public: no directory user has a hidden row, so the probes
    fall back to `user:ghost`, who must be denied F4."""
    from tests.store.tables_fixtures import MANIFEST

    rules = [{"match": {"uri_prefix": "file://papers/"}, "access": ["public"]}]
    store = make(tmp_path / "r", [MANIFEST], rules=rules, corpus="research")
    sizes = dict.fromkeys(tp.LEAK_SIZES["research"], 2)
    probes = tp.leak_probes(store.path, "research", sizes=sizes)
    assert {p.caller for p in probes} == {"user:ghost"} and len(probes) == 10
    results = tp.run_leaks(probes, store.path, tmp_path / "views", **kw(store, tmp_path))
    assert all(r.valid and not r.leak and r.outcome.startswith("denied:F4") for r in results)
    total = tp.summarize_leaks(results)["total"]
    assert total["ghost"] == 10 and total["compared"] == 0


def test_by_error_probes_mention_the_hidden_value(built):
    probes = [p for p in tp.leak_probes(built.path, "gov", sizes=SMALL)
              if p.family == "by-error"]
    for p in probes:
        tools_called = [c["tool"] for c in p.call["calls"]]
        assert tools_called == ["query_table", "sql", "sql"]
        secret = p.target["secret"]
        assert secret in json.dumps(p.call["calls"][0]["args"]["filters"], ensure_ascii=False)
        assert all(tp.sql_literal(p.target["value"]) in c["args"]["statement"]
                   for c in p.call["calls"][1:])


def test_a_planted_leak_is_caught(built, monkeypatch, tmp_path):
    probes = tp.leak_probes(built.path, "gov", sizes=SMALL)
    leaking_view_databases(monkeypatch)
    results = tp.run_leaks(probes, built.path, tmp_path / "views", **kw(built, tmp_path))
    found = Counter(k for r in results for k, v in r.kinds.items() if v)
    assert found["count_differs"] and found["rows_differ"]
    assert found["id_outside_view"] and found["hidden_value"]
    assert any(r.leak for r in results if r.family == "by-key")
    assert tp.summarize_leaks(results)["total"]["leaks"] > 0


def test_a_leaking_error_is_caught(built, monkeypatch, tmp_path):
    """The data-dependent statement of `by-error` fails only where the hidden row is present."""
    probes = [p for p in tp.leak_probes(built.path, "gov", sizes=SMALL)
              if p.family == "by-error" and p.caller != "user:ghost"]
    assert probes
    leaking_view_databases(monkeypatch)
    results = tp.run_leaks(probes, built.path, tmp_path / "views", **kw(built, tmp_path))
    assert all(r.kinds["error_differs"] for r in results)


# -- reference stores of a store with extraction (3B) tables ------------------------------------

DRAWBRIDGE = ("drawbridge_sections", "drawbridge_bridges")


def test_reference_stores_read_the_extraction_tables_from_the_cache(three_b, tmp_path):
    """A reference store holds the view's documents alone, so its extraction tables come from
    the same cached replies (the cache key covers the section text, not the store): the leak
    probes on hidden drawbridge rows find no leak, and building the references calls nothing."""
    from adr_store import handles
    from adr_store.tables.overlay import load_manifest

    store, replies = three_b
    made = len(replies)
    ctx = tp.table_context(store.path)
    assert ctx.manifest.extraction is not None and set(DRAWBRIDGE) <= set(ctx.contracts)
    probes = tp.leak_probes(store.path, "gov", sizes=SMALL)
    assert {p.target["table"] for p in probes} & set(DRAWBRIDGE)   # hidden drawbridge rows
    refs = tp.References(ctx, tmp_path / "views", generator="gen", **kw(store, tmp_path))
    results = tp.run_leaks(probes, store.path, tmp_path / "views", refs=refs,
                           **kw(store, tmp_path))
    assert all(r.valid for r in results), [r.note for r in results if not r.valid]
    assert not any(r.leak for r in results), [(r.probe_id, r.kinds) for r in results if r.leak]
    for v in refs.views:   # every view's reference, with and without eCFR documents
        refs.path_of(v)
    assert len(replies) == made   # zero calls: every reference read the cache
    ecfr = {d for d in store.doc_ids() if store.source(d).format == "xml"}
    with_ecfr = 0
    for info in refs.info:
        path = tmp_path / "views" / info["path"]
        m = load_manifest(path, handles.tables_head(path, Store.open(path).snapshot_id))
        assert m.extraction == ctx.manifest.extraction
        assert set(DRAWBRIDGE) <= {t.table for t in m.tables}
        assert "extraction from the cache" in info["how"]
        with_ecfr += bool(ecfr & set(Store.open(path).doc_ids()))
    assert 0 < with_ecfr < len(refs.info)


def test_equivalence_on_extraction_tables_compares_drawbridge_calls(three_b, tmp_path):
    store, replies = three_b
    made = len(replies)
    rows = tp.equivalence(store.path, "gov", tmp_path / "views", gold=GOLD, generator="gen",
                          **kw(store, tmp_path))
    assert rows and all(r["identical"] for r in rows), [r for r in rows if not r["identical"]]
    assert any(r["query_id"].startswith("count_by:drawbridge_") for r in rows)
    assert len(replies) == made


def test_a_reference_cache_miss_stops_the_run_without_a_call(three_b, tmp_path):
    """Ruling P21 with `max_calls=0`: a reply missing from the cache (here: another profile,
    so other cache keys) stops the reference build with BudgetExceeded and calls nothing."""
    from adr_eval.pipeline import BudgetExceeded

    store, replies = three_b
    made = len(replies)
    ctx = tp.table_context(store.path)
    refs = tp.References(ctx, tmp_path / "views", generator="other", **kw(store, tmp_path))
    ecfr = {d for d in store.doc_ids() if store.source(d).format == "xml"}
    view = next(v for v in refs.views if ecfr <= v.docs)
    with pytest.raises(BudgetExceeded):
        refs.path_of(view)
    assert len(replies) == made
    # a view without eCFR documents needs no reply, but its tables would record another
    # model than the store's: refused, never compared
    other = next(v for v in refs.views if not ecfr & v.docs)
    with pytest.raises(ValueError, match="extraction"):
        refs.path_of(other)
    assert len(replies) == made


def test_reference_stores_of_a_store_without_extraction_resolve_no_generator(
        built, tmp_path, monkeypatch):
    from adr_eval import runner

    def no_client(*a, **k):
        raise AssertionError("a metadata-only reference must not build a model client")

    monkeypatch.setattr(runner, "make_client", no_client)
    refs = tp.References(tp.table_context(built.path), tmp_path / "views",
                         **kw(built, tmp_path))
    path = refs.path_of(refs.views[0])
    assert "extraction" not in refs.info[0]["how"]
    assert not any(t.table in DRAWBRIDGE for t in tp.table_context(path).manifest.tables)


# -- the SQL guard -------------------------------------------------------------------------------


def test_sql_guard_cases_are_120_in_their_categories():
    assert Counter(c for c, _ in tp.SQL_GUARD_CASES) == tp.GUARD_CATEGORIES
    assert len(tp.SQL_GUARD_CASES) == sum(tp.GUARD_CATEGORIES.values()) == 120
    statements = [s for _, s in tp.SQL_GUARD_CASES]
    assert len(set(statements)) == 120
    assert tp.HARMLESS <= set(statements)
    assert all(c == "trick" for c, s in tp.SQL_GUARD_CASES if s in tp.HARMLESS)


def test_every_guard_case_is_refused_or_bounded(built, monkeypatch):
    from adr_store.tables import sqlguard

    monkeypatch.setattr(sqlguard, "SQL_STEP_BUDGET", 300_000)   # the same refusals, faster
    log = built.path / "log" / "retrieval.jsonl"
    offset = log.stat().st_size if log.exists() else 0
    rows = tp.sql_guard(built.path, clock=lambda: NOW)
    assert len(rows) == 120
    assert all(r["pass"] for r in rows), [r for r in rows if not r["pass"]]
    assert all(r["intact"] for r in rows)
    for r in rows:
        if r["category"] in tp.MUST_REFUSE and not r["harmless"]:
            assert r["outcome"].startswith("refused:") and r["message"] in FIXED
    classes = {r["outcome"] for r in rows}
    assert {"refused:syntax", "refused:denied", "refused:budget", "refused:rows"} <= classes
    assert "ok" in classes   # a bounded statement runs
    scan = tp.scan_table_log(log, offset, statements=[r["statement"] for r in rows])
    assert scan["lines"] == scan["table_lines"] >= 120 and scan["complete"]
    assert scan["sql_text_lines"] == 0


def test_a_guard_case_that_runs_where_it_must_refuse_fails(built, monkeypatch):
    from adr_store.tables import sqlguard

    monkeypatch.setattr(sqlguard, "SQL_STEP_BUDGET", 300_000)
    monkeypatch.setattr(sqlguard, "_names_reserved", lambda body: False)
    monkeypatch.setattr(sqlguard._Guard, "authorize", lambda self, *a: 0)   # allow everything
    rows = tp.sql_guard(built.path, clock=lambda: NOW)
    assert not all(r["pass"] for r in rows)


# -- equivalence ---------------------------------------------------------------------------------


def test_equivalence_on_fixture_views(built, tmp_path):
    rows = tp.equivalence(built.path, "gov", tmp_path / "views", gold=GOLD,
                          **kw(built, tmp_path))
    views = {r["view"] for r in rows}
    assert len(views) >= 4 and len(rows) == 25 * len(views)
    assert all(r["counted"] for r in rows)
    assert all(r["identical"] for r in rows), [r for r in rows if not r["identical"]]
    for v in views:
        mine = [r for r in rows if r["view"] == v]
        assert Counter(r["tool"] for r in mine) == {"query_table": 15, "sql": 10}
    assert {r["query_id"].split(":")[0] for r in rows} == {"gold", "count_by", "sql"}
    assert {json.dumps(r["applicability"]) for r in rows} == {"{}",
                                                              '{"include_superseded": true}'}
    again = tp.equivalence(built.path, "gov", tmp_path / "views", gold=GOLD,
                           **kw(built, tmp_path))
    assert again == rows


def test_equivalence_detects_a_view_database_with_hidden_rows(built, monkeypatch, tmp_path):
    leaking_view_databases(monkeypatch)
    rows = tp.equivalence(built.path, "gov", tmp_path / "views", gold=GOLD,
                          **kw(built, tmp_path))
    assert any(not r["identical"] for r in rows)
    assert tp.summarize_equivalence(rows)["differing"] > 0


def test_stores_without_tables_refuse_alike_and_are_not_counted(tmp_path):
    bench = make(tmp_path / "bench", tables=False)
    empty = make_tables_store(tmp_path / "toolsonly", [], rules=RULES)
    for store, corpus in ((bench, "bench"), (empty, "tools")):
        rows = tp.equivalence(store.path, corpus, tmp_path / f"views-{corpus}",
                              **kw(store, tmp_path))
        n_views = len({r["view"] for r in rows})
        assert n_views >= 1 and len(rows) == 3 * n_views
        assert {r["tool"] for r in rows} == set(tp.TABLE_TOOLS)
        assert all(r["identical"] and not r["counted"] for r in rows)
        assert all(r["outcome"] == "refused" for r in rows)
        assert tp.summarize_equivalence(rows)["n"] == 0


# -- fail closed ---------------------------------------------------------------------------------


def test_failclosed_90_on_the_fixture(public, tmp_path):
    logs: dict = {}
    rows = tp.failclosed(public.path, tmp_path / "clones", "gov", logs=logs,
                         **kw(public, tmp_path))
    assert len(rows) == 90 and all(r["pass"] for r in rows), [r for r in rows if not r["pass"]]
    assert Counter(r["family"] for r in rows) == dict.fromkeys(CONDITIONS, 15)
    assert Counter(r["tool"] for r in rows) == dict.fromkeys(tp.TABLE_TOOLS, 30)
    assert not any(r["content"] for r in rows)
    entry = [r for r in rows if r["family"] == "no_entry"]
    assert all(r["visible_before"] for r in entry)
    assert all(r["outcome"] == "ok" for r in entry)   # "no entry" returns nothing, not a refusal
    assert not any((tmp_path / "clones").glob("*/HEAD"))   # clones removed
    target = rows[0]["target"]   # the target is recorded on every row
    assert all(r["target"] == target for r in rows)
    assert target["doc_id"] in public.doc_ids() and target["table"] == FR
    assert target["key"] == "id"
    total = tp.total_table_scan(logs)
    assert total["complete"] and total["lines"] >= 90
    assert rows == tp.failclosed(public.path, tmp_path / "clones", "gov",
                                 **kw(public, tmp_path))


def test_a_failclosed_target_that_no_caller_sees_is_refused(built, tmp_path):
    """In `built` no document is visible to every fail-closed caller (`user:outsider` sees
    none), so "no entry" has no target."""
    with pytest.raises(ValueError, match="no document meets"):
        tp.failclosed(built.path, tmp_path / "clones", "gov", **kw(built, tmp_path))


def test_a_tool_that_fails_open_is_caught(public, monkeypatch, tmp_path):
    monkeypatch.setattr(tools.Tools, "_enter", lambda self, acl_fields, *a, **k: setattr(
        self, "_access_now", None) or acl_fields.update(acl_decision="allowed"))
    rows = tp.failclosed(public.path, tmp_path / "clones", "gov", **kw(public, tmp_path))
    assert not all(r["pass"] for r in rows)
    assert any(r["content"] for r in rows if r["family"] == "F4")


# -- applicability -------------------------------------------------------------------------------


def test_applicability_probes_pass(built):
    rows = tp.applicability_probes(built.path, clock=lambda: NOW)
    assert len(rows) == 51 and all(r["pass"] for r in rows), [r for r in rows if not r["pass"]]
    assert sum(r["as_of"] is not None for r in rows) == 50
    assert all(r["table"] == FR for r in rows)
    assert any(r["excluded"] > 0 for r in rows if r["as_of"] is not None)
    store = Store.open(built.path)
    dates = {json.loads(store.text(d)).get("publication_date") for d in store.doc_ids()
             if store.source(d).format == "json"}
    assert {r["as_of"] for r in rows if r["as_of"]} <= dates


def test_applicability_probes_on_the_drawbridge_tables(three_b):
    """Default and `as_of` queries on the drawbridge tables return rows of the version in force
    only: every version's first day and the day before it are among the dates, so each
    version is selected by `as_of` and none before the first."""
    from datetime import date, timedelta

    from adr_store import applicability as ap

    store, _ = three_b
    rows = tp.applicability_probes(store.path, tables=(FR, *DRAWBRIDGE), clock=lambda: NOW)
    assert len(rows) == 3 * 51 and all(r["pass"] for r in rows), \
        [r for r in rows if not r["pass"]]
    assert rows[:51] == tp.applicability_probes(store.path, clock=lambda: NOW)   # FR unchanged
    ctx = tp.table_context(store.path)
    overlay = ap.load_overlay(store.path, ctx.store.snapshot_id, ctx.manifest.applicability)
    ecfr = sorted((d for d in store.doc_ids() if store.source(d).format == "xml"),
                  key=lambda d: overlay.records[d].valid_from)
    starts = [overlay.records[d].valid_from for d in ecfr]
    for t in DRAWBRIDGE:
        mine = [r for r in rows if r["table"] == t]
        assert len(mine) == 51 and sum(r["as_of"] is None for r in mine) == 1
        assert all(r["versions"] <= 1 for r in mine)
        dates = {r["as_of"] for r in mine if r["as_of"]}
        for s in starts:
            assert s.isoformat() in dates and (s - timedelta(days=1)).isoformat() in dates
        by_date = {r["as_of"]: r for r in mine}
        assert by_date[(starts[0] - timedelta(days=1)).isoformat()]["rows"] == 0
        for d, s in zip(ecfr, starts, strict=True):   # each version alone, on its first day
            r = by_date[s.isoformat()]
            assert r["rows"] == sum(x.doc_id == d for x in ctx.rows[t]) > 0
        default = by_date[None]   # the version in force now: the newest
        assert default["rows"] == sum(x.doc_id == ecfr[-1] for x in ctx.rows[t])
        assert all(date.fromisoformat(r["as_of"]) for r in mine if r["as_of"])


def test_applicability_probes_catch_drawbridge_rows_of_superseded_versions(three_b,
                                                                           monkeypatch):
    store, _ = three_b
    leaking_view_databases(monkeypatch)
    rows = tp.applicability_probes(store.path, tables=DRAWBRIDGE, clock=lambda: NOW)
    assert not all(r["pass"] for r in rows)
    assert any(r["versions"] > 1 for r in rows)


def test_applicability_probes_catch_two_versions_on_one_date(three_b, monkeypatch):
    """The `versions <= 1` term alone: an overlay that keeps the oldest eCFR version in force
    after its successor starts admits two versions of one chain on one date. The tools and
    the probe's expectation read the same overlay, so the rows returned equal those expected
    and none is outside the admitted documents; only the version count fails the probe."""
    from adr_store import applicability as ap
    from adr_store import tools

    store, _ = three_b
    real = ap.load_overlay

    def planted(store_path, snapshot, overlay_id=None):
        overlay = real(store_path, snapshot, overlay_id)
        if overlay is None:
            return None
        chained = sorted((e for e in overlay.records.values()
                          if e.chain_id is not None and e.valid_from is not None),
                         key=lambda e: e.valid_from)
        oldest = chained[0]
        assert oldest.valid_to is not None
        records = {**overlay.records, oldest.doc_id: oldest.model_copy(update={"valid_to": None})}
        return ap.Applicability(overlay.overlay_id, overlay.snapshot, records)

    monkeypatch.setattr(ap, "load_overlay", planted)
    monkeypatch.setattr(tools, "load_overlay", planted)
    rows = tp.applicability_probes(store.path, tables=DRAWBRIDGE, clock=lambda: NOW)
    failed = [r for r in rows if not r["pass"]]
    assert failed and all(r["versions"] == 2 for r in failed)
    assert all(r["outside"] == 0 and r["rows"] == r["expected"] for r in failed)
    assert all(r["pass"] for r in rows if r["versions"] <= 1)


def test_applicability_probes_catch_rows_of_documents_not_in_force(built, monkeypatch):
    leaking_view_databases(monkeypatch)
    rows = tp.applicability_probes(built.path, clock=lambda: NOW)
    assert not all(r["pass"] for r in rows)


# -- the log scan --------------------------------------------------------------------------------


def _line(**kw) -> dict:
    base = {"tool": "query_table", "caller": "user:a", "principals": ["user:a"],
            "acl_snapshot": "s", "acl_decision": "allowed", "view": "v", "tables": "t",
            "args": {}}
    return {**base, **kw}


def test_scan_table_log_requires_tables_on_allowed_lines(tmp_path):
    log = tmp_path / "log.jsonl"
    stmt = "SELECT title FROM fr_documents WHERE id = 'x'"
    lines = [
        _line(),                                                            # complete
        _line(tables=None),                                                 # allowed, no tables
        _line(acl_decision="denied:F4", principals=None, view=None, tables=None),   # fine
        _line(tables=None, error="no tables for snapshot abc…; run `adr tables build` and "
                                 "`adr tables gate`"),                      # fine
        {k: v for k, v in _line().items() if k != "tables"},                # tables missing
        _line(tool="sql", args={"statement_sha256": "h", "applicability": None},
              sql_sha256="h"),                                              # complete
        _line(tool="sql", args={"statement": stmt}, sql_sha256="h"),        # statement logged
        _line(tool="sql", args={"statement_sha256": "h", "applicability": None},
              sql_sha256="h", error=stmt),                                  # text in a line
        {k: v for k, v in _line().items() if k != "caller"},                # caller missing
    ]
    log.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    scan = tp.scan_table_log(log, statements=[stmt])
    assert scan["lines"] == 9 and scan["table_lines"] == 9
    assert scan["missing"]["caller"] == 1 and scan["complete_lines"] == 8
    assert scan["tables_missing"] == 1
    assert scan["allowed_unresolved"] == 3   # null or no tables, and the caller-less line
    assert scan["sql_lines"] == 3 and scan["sql_text_lines"] == 2
    assert not scan["complete"]
    first = log.read_bytes().index(b"\n") + 1   # the offset of the second line
    assert tp.scan_table_log(log, len(log.read_bytes()))["lines"] == 0
    after = tp.scan_table_log(log, first, statements=[stmt])
    assert after["lines"] == 8 and after["allowed_unresolved"] == 3
    assert tp.scan_table_log(log, 0, statements=[stmt])["lines"] == 9
    ok = tmp_path / "ok.jsonl"
    ok.write_text("".join(json.dumps(x) + "\n" for x in (lines[0], lines[2], lines[3],
                                                          lines[5])), encoding="utf-8")
    assert tp.scan_table_log(ok, statements=[stmt])["complete"]


# -- the MCP leg (D1) ----------------------------------------------------------------------------


def test_the_mcp_leg_finds_no_leak_and_replays_handles(built, tmp_path):
    pytest.importorskip("mcp")
    from adr_store.mcp_client import McpTools

    directory, policy = config_of(built)
    acl.sync(built.path, directory, policy)   # the real clock: the servers read it
    probes = tp.leak_probes(built.path, "gov", sizes=SMALL)
    selected = tp.select_mcp([("gov", p) for p in probes], 6)
    assert len(selected) == 6 and selected == tp.select_mcp([("gov", p) for p in probes], 6)
    refs = tp.References(tp.table_context(built.path), tmp_path / "views", directory=directory,
                         policy=policy, emb_cache=tmp_path / "emb")

    def reference_for(label, caller):
        path = refs.path_for(caller)
        return None if path is None else tools.Tools(path, acl=True, caller=caller)

    def make_server(label, caller):
        return McpTools(built.path, caller, cwd=REPO, env={"HF_HUB_OFFLINE": "1"},
                        emb_cache=tmp_path / "emb")

    results, replays, calls = tp.run_mcp(selected, contexts={"gov": tp.table_context(
        built.path)}, reference_for=reference_for, make_server=make_server)
    assert len(results) == 6 and all(r.valid and not r.leak for _, r in results)
    assert replays and all(r["identical"] and r["handle_tables"] for r in replays)
    assert sum(calls["gov"].values()) >= 6


# -- the command line ----------------------------------------------------------------------------


def test_the_cli_runs_the_table_probe_kinds(public, tmp_path, capsys, monkeypatch):
    from adr_store.tables import sqlguard

    directory, policy = config_of(public)
    acl.sync(public.path, directory, policy)   # the real clock: the CLI's tools read it
    out = tmp_path / "runs"
    common = ["--store", str(public.path), "--directory", str(directory), "--policy",
              str(policy), "--views", str(tmp_path / "views"), "--out", str(out)]
    assert main(["probes", "tables-leak", "gov", *common, "--per-family", "2",
                 "--keep-views"]) == 0
    kept = sorted((tmp_path / "views").iterdir())
    assert kept
    assert main(["probes", "tables-failclosed", "gov", *common,
                 "--clones", str(tmp_path / "clones")]) == 0
    assert main(["probes", "tables-applicability", "gov", *common]) == 0
    with monkeypatch.context() as m:
        m.setattr(sqlguard, "SQL_STEP_BUDGET", 300_000)
        assert main(["probes", "tables-sql", "gov", *common]) == 0
    assert sorted((tmp_path / "views").iterdir()) == kept   # untouched by kinds without views
    assert main(["probes", "tables-equivalence", "gov", *common, "--gold", str(GOLD)]) == 0
    capsys.readouterr()
    for kind, total in (("leak", 10), ("failclosed", 90), ("applicability", 51),
                        ("sql", 120)):
        (d,) = out.glob(f"probes-tables-{kind}-gov-*")
        summary = json.loads((d / "summary.json").read_text())
        assert summary["summary"]["total"]["n"] == total, kind
        assert summary["logs"]["total"]["complete"], kind
        assert (d / "summary.md").exists() and (d / "results.json").exists()
    (d,) = out.glob("probes-tables-applicability-gov-*")
    summary = json.loads((d / "summary.json").read_text())
    assert summary["logs"]["statements_checked"] == 1   # the GROUP BY _doc_id statement
    assert summary["config"]["tables_probed"] == [FR]   # no drawbridge tables in this store
    (d,) = out.glob("probes-tables-failclosed-gov-*")
    target = json.loads((d / "probes.json").read_text())["target"]
    rows = json.loads((d / "results.json").read_text())["results"]
    assert target["doc_id"] in public.doc_ids() and all(r["target"] == target for r in rows)
    (d,) = out.glob("probes-tables-leak-gov-*")
    assert json.loads((d / "summary.json").read_text())["summary"]["total"]["compared"] == 10
    (d,) = out.glob("probes-tables-equivalence-gov-*")
    summary = json.loads((d / "summary.json").read_text())
    assert summary["summary"]["differing"] == 0 and summary["summary"]["n"] > 0
    assert any("reused" in v["how"] for v in summary["config"]["views"])
    assert not (tmp_path / "views").exists()   # reference stores removed without --keep-views
    assert main(["probes", "tables-leak", "tools", *common]) == 2


def test_the_cli_probes_the_drawbridge_tables_with_the_generator(three_b, tmp_path, capsys):
    store, replies = three_b
    made = len(replies)
    directory, policy = config_of(store)
    acl.sync(store.path, directory, policy)   # the real clock: the CLI's tools read it
    out = tmp_path / "runs"
    common = ["--store", str(store.path), "--directory", str(directory), "--policy",
              str(policy), "--views", str(tmp_path / "views"), "--out", str(out)]
    assert main(["probes", "tables-applicability", "gov", *common, "--tables", FR,
                 *DRAWBRIDGE]) == 0
    assert main(["probes", "tables-leak", "gov", *common, "--per-family", "2",
                 "--generator", "gen"]) == 0
    assert main(["probes", "tables-equivalence", "gov", *common, "--gold", str(GOLD),
                 "--generator", "gen"]) == 0
    capsys.readouterr()
    assert len(replies) == made
    (d,) = out.glob("probes-tables-applicability-gov-*")
    summary = json.loads((d / "summary.json").read_text())
    assert summary["summary"]["total"]["n"] == 153
    assert summary["summary"]["tables"] == sorted([FR, *DRAWBRIDGE])
    assert set(summary["summary"]["by_table"]) == {FR, *DRAWBRIDGE}
    assert summary["logs"]["statements_checked"] == 3 and summary["logs"]["total"]["complete"]
    for kind in ("leak", "equivalence"):
        (d,) = out.glob(f"probes-tables-{kind}-gov-*")
        summary = json.loads((d / "summary.json").read_text())
        assert summary["config"]["generator"] == "gen", kind
        assert all("extraction from the cache" in v["how"] for v in summary["config"]["views"])
    (d,) = out.glob("probes-tables-leak-gov-*")
    summary = json.loads((d / "summary.json").read_text())
    assert summary["summary"]["total"]["leaks"] == 0
    assert set(summary["summary"]["targets_by_table"]) & set(DRAWBRIDGE)
    # an unknown table is refused before any probe runs
    assert main(["probes", "tables-applicability", "gov", *common, "--tables", "nope"]) == 2
    # without --tables: fr_documents and the drawbridge tables the store holds
    plain = tmp_path / "plain"
    assert main(["probes", "tables-applicability", "gov", *common[:-1], str(plain)]) == 0
    capsys.readouterr()
    (d,) = plain.glob("probes-tables-applicability-gov-*")
    summary = json.loads((d / "summary.json").read_text())
    assert summary["summary"]["total"]["n"] == 153
    assert summary["config"]["tables_probed"] == [FR, *DRAWBRIDGE]


def test_tables_mcp_records_the_generator_on_a_store_with_extraction_tables(three_b, tmp_path,
                                                                            capfd):
    """Like tables-leak and tables-equivalence, the MCP leg's reference stores build their
    extraction tables from a profile's cached replies, so its config names that profile."""
    pytest.importorskip("mcp")
    store, replies = three_b
    made = len(replies)
    directory, policy = config_of(store)
    acl.sync(store.path, directory, policy)   # the real clock: the servers read it
    out = tmp_path / "runs"
    assert main(["probes", "tables-mcp", "gov", "--store", str(store.path), "--directory",
                 str(directory), "--policy", str(policy), "--views", str(tmp_path / "views"),
                 "--out", str(out), "--n", "2", "--generator", "gen"]) == 0
    capfd.readouterr()
    assert len(replies) == made                   # the references read the cache only
    (d,) = out.glob("probes-tables-mcp-gov-*")
    cfg = json.loads((d / "summary.json").read_text())["config"]
    assert cfg["generator"] == "gen"
