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
    assert {r.caller for r in results} >= {"user:ghost", "user:outsider"}
    summary = tp.summarize_leaks(results)
    assert summary["total"]["n"] == 20 and summary["total"]["leaks"] == 0


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
    first = log.read_bytes().index(b"\n") + 1
    assert tp.scan_table_log(log, len(log.read_bytes()))["lines"] == 0
    assert tp.scan_table_log(log, 0, statements=[stmt])["lines"] == 9
    ok = tmp_path / "ok.jsonl"
    ok.write_text("".join(json.dumps(x) + "\n" for x in (lines[0], lines[2], lines[3],
                                                          lines[5])), encoding="utf-8")
    assert tp.scan_table_log(ok, statements=[stmt])["complete"]
    assert first > 0


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


def test_the_cli_runs_the_table_probe_kinds(public, tmp_path, capsys):
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
    old = sqlguard.SQL_STEP_BUDGET
    sqlguard.SQL_STEP_BUDGET = 300_000
    try:
        assert main(["probes", "tables-sql", "gov", *common]) == 0
    finally:
        sqlguard.SQL_STEP_BUDGET = old
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
    (d,) = out.glob("probes-tables-equivalence-gov-*")
    summary = json.loads((d / "summary.json").read_text())
    assert summary["summary"]["differing"] == 0 and summary["summary"]["n"] > 0
    assert any("reused" in v["how"] for v in summary["config"]["views"])
    assert not (tmp_path / "views").exists()   # reference stores removed without --keep-views
    assert main(["probes", "tables-leak", "tools", *common]) == 2
