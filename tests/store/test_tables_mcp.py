"""The three table tools over MCP (Phase 3 spec §8; Task 6; criterion D1 for tables): `adr mcp`
started as a subprocess and driven with `adr_store.mcp_client.McpTools` on the gov table fixture
store of `test_tables_tools.py` (synced with the real clock, which the servers read): `tools/list`
has `describe_tables`, `query_table` and `sql` with input and output schemas and a handle; thirty
fixed calls equal the Python API's results; sql refusals are error results with the guard's
fixed messages; a handle replay through MCP is identical. No model is loaded."""

import dataclasses
import json

import pytest

pytest.importorskip("mcp")

from adr_store import acl, mcp_server, tools  # noqa: E402
from adr_store.mcp_client import McpTools  # noqa: E402
from adr_store.tables.engine import OPS, QUERY_LIMIT, QUERY_LIMIT_MAX  # noqa: E402
from adr_store.tables.overlay import manifest_path, read_head  # noqa: E402
from adr_store.tables.semantic import ERR_UNKNOWN_TABLE  # noqa: E402
from adr_store.tables.sqlguard import ERR_BUDGET, ERR_DENIED, ERR_SYNTAX  # noqa: E402
from tests.store.test_tables_tools import FR, make  # noqa: E402

REPO = __import__("pathlib").Path(__file__).parents[2]
ENV = {"HF_HUB_OFFLINE": "1"}
TABLE_TOOLS = ("describe_tables", "query_table", "sql")


@pytest.fixture
def store(tmp_path):
    s = make(tmp_path / "store")
    config = s.path.parent / f"{s.path.name}-acl"
    acl.sync(s.path, config / "directory.json", config / "policy.json", clock=acl.utc_now)
    return s


@pytest.fixture
def servers(tmp_path):
    made = []

    def start(store, caller="user:acme-4"):
        made.append(McpTools(store.path, caller, cwd=REPO, env=ENV,
                             emb_cache=tmp_path / "emb"))
        return made[-1]

    yield start
    for m in made:
        m.close()


def py(store, caller="user:acme-4") -> tools.Tools:
    return tools.Tools(store.path, acl=True, caller=caller)


def text(res) -> str:
    return "".join(c.text for c in res.content if c.type == "text")


def test_tools_list_has_the_three_table_tools_with_handles(store, servers):
    listed = {t.name: t for t in servers(store).list_tools().tools}
    assert set(TABLE_TOOLS) <= set(listed) and len(listed) == 8
    for name in TABLE_TOOLS:
        t = listed[name]
        ins, outs = t.input_schema, t.output_schema
        assert ins["additionalProperties"] is False and "handle" in ins["properties"]
        assert not {"caller", "user", "principal", "as_user"} & set(ins["properties"])
        fields = {f.name for f in dataclasses.fields(mcp_server.RESULTS[name])}
        assert set(outs["properties"]) == fields and set(outs["required"]) == fields
        assert outs["additionalProperties"] is False
        assert outs == mcp_server.OUTPUTS[name].model_json_schema() | {
            k: v for k, v in outs.items() if k == "$defs"}
        assert "handle" in outs["properties"] and t.description
        a = t.annotations
        assert (a.read_only_hint, a.idempotent_hint, a.open_world_hint) == (True, True, False)
    q = listed["query_table"].input_schema["properties"]
    assert q["op"]["enum"] == list(OPS) and q["op"]["default"] == "count"
    assert (q["limit"]["minimum"], q["limit"]["maximum"], q["limit"]["default"]) == (
        1, QUERY_LIMIT_MAX, QUERY_LIMIT)
    assert {"applicability", "filters", "fields", "order"} <= set(q)
    assert listed["sql"].input_schema["required"] == ["statement"]
    assert "applicability" in listed["sql"].input_schema["properties"]


def fixed_calls() -> list[tuple[str, tuple, dict]]:
    """Thirty calls (tool, positional, keyword) over the three tools: hidden, visible and
    missing ids, every op, applicability filters, refusals."""
    q, s = "query_table", "sql"
    return [
        ("describe_tables", (), {}),
        ("describe_tables", (FR,), {}),
        ("describe_tables", ("agencies",), {}),
        ("describe_tables", ("no_such_table",), {}),
        (q, (FR,), {}),
        (q, (FR, {"type": "Rule"}, "count"), {}),
        (q, (FR, {"year": 2024}, "list"), {}),
        (q, (FR, {"id": "2024-00003"}, "lookup"), {}),
        (q, (FR, {"id": "2024-00002"}, "lookup"), {}),
        (q, (FR, {"id": "2099-99999"}, "lookup"), {}),
        (q, (FR, None, "lookup"), {"fields": ["id", "year"], "order": ["-id"], "limit": 2}),
        (q, (FR, {"id": "2024-00005"}, "lookup"), {"fields": ["title"]}),
        (q, (FR, None, "count_by"), {"fields": ["type"]}),
        (q, ("agencies", None, "count_by"), {"fields": ["display_name"]}),
        (q, ("waterways", None, "list"), {}),
        (q, ("waterways", None, "list"), {"applicability": {"include_superseded": True}}),
        (q, (FR, None, "list"), {"applicability": {"as_of": "2024-06-01"}}),
        (q, (FR, {"cfr_parts__contains": "117"}, "count"), {}),
        (q, (FR, {"type": 1}, "count"), {}),
        (q, (FR, {"bogus": 1}), {}),
        (q, ("no_such_table",), {}),
        (q, (FR, None, "count_by"), {}),
        (s, ("SELECT count(*), sum(year) FROM fr_documents",), {}),
        (s, ("SELECT type, count(*) FROM fr_documents GROUP BY type",), {}),
        (s, ("SELECT _doc_id, id, _prov_year FROM fr_documents ORDER BY id DESC",), {}),
        (s, ("SELECT key FROM waterways",), {"applicability": {"include_superseded": True}}),
        (s, ("SELECT 1.5, NULL, 'x'",), {}),
        (s, ("SELECT * FROM sqlite_master",), {}),
        (s, ("SELECT 1; SELECT 2",), {}),
        (s, ("WITH RECURSIVE c(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM c) "
             "SELECT count(*) FROM c",), {}),
    ]


def outcome(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except tools.ToolError as e:
        return (type(e).__name__, str(e))


def test_thirty_fixed_calls_equal_the_python_api(store, servers):
    calls = fixed_calls()
    assert len(calls) == 30
    for caller in ("user:acme-4", "user:globex-0"):
        m, p = servers(store, caller), py(store, caller)
        for name, args, kw in calls:
            got = outcome(getattr(m, name), *args, **kw)
            want = outcome(getattr(p, name), *args, **kw)
            assert got == want, (caller, name, args, kw)
    # the refusals are among them
    p = py(store)
    errors = {o[1] for name, args, kw in calls
              if isinstance(o := outcome(getattr(p, name), *args, **kw), tuple)}
    assert {ERR_UNKNOWN_TABLE, ERR_DENIED, ERR_SYNTAX, ERR_BUDGET} <= errors


def test_sql_refusals_are_error_results_with_the_fixed_messages(store, servers):
    m = servers(store)
    for statement, message in [("DELETE FROM fr_documents", ERR_SYNTAX),
                               ("SELECT 1; SELECT 2", ERR_SYNTAX),
                               ("SELECT * FROM sqlite_master", ERR_DENIED),
                               ("PRAGMA table_info(fr_documents)", ERR_SYNTAX),
                               ("SELECT a.id FROM fr_documents a NATURAL JOIN fr_agencies",
                                ERR_DENIED)]:
        res = m.call("sql", {"statement": statement})
        assert res.is_error and text(res) == message == outcome(py(store).sql, statement)[1]
    res = m.call("query_table", {"table": FR, "op": "median"})
    assert res.is_error and "op" in text(res)           # the schema refuses an unknown op
    res = m.call("sql", {"statement": "SELECT 1", "caller": "user:auditor"})
    assert res.is_error                                  # no argument names a principal
    with pytest.raises(tools.AccessDenied) as e:
        servers(store, "user:ghost").query_table(FR)
    assert e.value.code == "F4"


def test_a_handle_replay_through_mcp_is_identical(store, servers):
    m = servers(store)
    first = m.query_table(FR, op="count_by", fields=["type"])
    assert first.handle["tables"] == read_head(store.path)
    assert m.query_table(FR, op="count_by", fields=["type"], handle=first.handle) == first
    s = m.sql("SELECT id FROM fr_documents")
    assert m.sql("SELECT id FROM fr_documents", handle=s.handle) == s
    d = m.describe_tables(handle=first.handle)
    assert d == py(store).describe_tables(handle=first.handle)
    # a Phase 2 handle (no tables part) validates and is refused by the table tools only
    old = {k: v for k, v in first.handle.items() if k != "tables"}
    assert m.search("drawbridge", handle=old).handle == {**old, "tables": None}
    with pytest.raises(tools.ToolError) as e:
        m.query_table(FR, handle=old)
    assert str(e.value) == tools.NO_HANDLE_TABLES
    manifest_path(store.path, first.handle["tables"]).unlink()
    with pytest.raises(tools.ToolError) as e:
        m.sql("SELECT 1", handle=first.handle)
    assert str(e.value) == "handle no longer available: tables"


def test_results_render_as_text(store, servers):
    m = servers(store)
    res = m.call("query_table", {"table": FR, "op": "list"})
    assert not res.is_error and res.structured_content["ids"]
    assert json.loads(text(res).splitlines()[1])["ids"] == res.structured_content["ids"]
    res = m.call("sql", {"statement": "SELECT count(*) FROM fr_documents"})
    n = len(m.query_table(FR, op="list").ids)
    assert text(res).splitlines()[1:3] == ['["count(*)"]', f"[{n}]"]
