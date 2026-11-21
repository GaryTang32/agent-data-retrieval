"""The MCP server (Phase 2 spec §9, §12 MCP, criterion D1; Task 12): `adr mcp` started as a
subprocess and driven with `mcp.Client(StdioServerParameters(...))` (`adr_store.mcp_client`)
on the fixture store of `tests/store/test_handles.py` (the gov-shaped permissions fixture, the
mini corpus and the fixture tool catalog; lexical-only indexes; store, caches and the
servers' embedding cache under `tmp_path`): `tools/list` gives exactly the eight tools with
input and output schemas; 100 fixed calls equal the Python API's results; every result has a
handle and a replay with it is identical; a handle whose index directory was deleted fails
explicitly; a handle naming an older content snapshot is judged against the current ACL;
`load_tool` output validates as `mcp.types.Tool`; a fixture-derived leak subset passes
through MCP; ids of the wrong type, `top` > 50, unknown arguments and handles with extra
fields are refused; the operator calls are unreachable; a server without a caller, or without
the `[mcp]` extra, does not start. The revocation leg is in `test_revocation.py`. No model is
loaded (`HF_HUB_OFFLINE=1` in the servers' environment)."""

import dataclasses
import json
import subprocess
import sys

import pytest

pytest.importorskip("mcp")

from mcp import types as mcp_types  # noqa: E402

from adr_eval.probes import acl as probes_acl  # noqa: E402
from adr_eval.probes import equivalence as eq  # noqa: E402
from adr_store import acl, cli, mcp_server, tools  # noqa: E402
from adr_store.mcp_client import McpTools, server_parameters  # noqa: E402
from adr_store.mcp_server import as_json  # noqa: E402
from adr_store.store import Store  # noqa: E402
from tests.store.test_handles import _second_snapshot, build, mini_docs  # noqa: E402
from tests.store.test_permissions import (  # noqa: E402
    DOCS,
    GLOBEX,
    PUBLIC,
    REPO,
    T0,
    absent_like,
    did,
    fixed,
    log_lines,
)

CALLER = "user:acme-4"
ENV = {"HF_HUB_OFFLINE": "1"}


@pytest.fixture
def built(tmp_path):
    """The fixture store, synced with the real clock (the servers read the real clock)."""
    s, config = build(tmp_path / "store", tmp_path / "config", clock=acl.utc_now)
    return s, config


@pytest.fixture
def store(built):
    return built[0]


@pytest.fixture
def servers(tmp_path):
    """Start `adr mcp` servers (one per call); all are stopped at the end."""
    made = []

    def start(store, caller=CALLER, **kw):
        kw.setdefault("emb_cache", tmp_path / "emb")
        kw.setdefault("env", ENV)
        made.append(McpTools(store.path, caller, cwd=REPO, **kw))
        return made[-1]

    yield start
    for m in made:
        m.close()


def py(store, caller=CALLER) -> tools.Tools:
    return tools.Tools(store.path, acl=True, caller=caller)


def text(res) -> str:
    return "".join(c.text for c in res.content if c.type == "text")


# -- tools/list ---------------------------------------------------------------------------------

def test_tools_list_is_the_tools_with_input_and_output_schemas(store, servers):
    listed = {t.name: t for t in servers(store).list_tools().tools}
    assert set(listed) == set(mcp_server.TOOL_NAMES) and len(listed) == 8
    for name, t in listed.items():
        ins, outs = t.input_schema, t.output_schema
        assert ins["type"] == "object" and ins["additionalProperties"] is False
        assert "handle" in ins["properties"] and "caller" not in ins["properties"]
        assert not {"user", "principal", "as", "as_user"} & set(ins["properties"])
        # the output schema states every field of the result dataclass, and no other
        fields = {f.name for f in dataclasses.fields(mcp_server.RESULTS[name])}
        assert outs["type"] == "object" and set(outs["properties"]) == fields
        assert set(outs["required"]) == fields and outs["additionalProperties"] is False
        assert outs == mcp_server.OUTPUTS[name].model_json_schema() | {
            k: v for k, v in outs.items() if k == "$defs"}
        a = t.annotations
        assert (a.read_only_hint, a.idempotent_hint, a.open_world_hint) == (True, True, False)
        assert t.description
    for name in ("search", "search_tools"):
        top = listed[name].input_schema["properties"]["top"]
        assert (top["minimum"], top["maximum"], top["default"]) == (1, 50, 10)
    assert {"cursor", "filters", "dedup"} <= set(listed["search"].input_schema["properties"])
    assert {"cursor", "filters"} <= set(listed["grep"].input_schema["properties"])


def test_operator_calls_are_not_reachable(store, servers):
    m = servers(store)
    before = len(log_lines(store))
    for name in ("index", "tools_index", "active_index", "active_system", "active_tool_index",
                 "sync", "acl_sync", "ingest", "derive", "build", "_call", "__init__"):
        res = m.call(name, {})
        assert res.is_error and text(res) == f"Unknown tool: {name}"
    assert len(log_lines(store)) == before  # nothing ran


# -- 100 fixed calls equal the Python API -------------------------------------------------------

def fixed_calls(store) -> list[tuple[str, str, dict]]:
    """100 calls (caller, tool, arguments), fixed by the fixture: 50 each for acme-4 and
    globex-0, over all five tools, with filters, dedup, cursors, prefixes, chunks, elements,
    ranges, hidden and missing ids."""
    docs = Store.open(store.path).doc_ids()
    idx = tools.Tools(store.path).active_index()
    chunks = sorted(idx.chunks)
    el_doc = did(PUBLIC)
    element = Store.open(store.path).elements(el_doc)[0].element_id
    tool_ids = sorted(acl.read_head(store.path)[1].tools)
    queries = ["vessel harbour refund", "harbour levy moored craft", "zanzibarite ledger",
               "obsidianite memo", "twin note", "refund deadline", "regulation"]
    out = []
    for caller in (CALLER, "user:globex-0"):
        c = []
        c += [("search", {"query": q, "top": 3}) for q in queries]
        c += [("search", {"query": q, "filters": {"include_superseded": True}})
              for q in queries[:3]]
        c += [("search", {"query": q, "dedup": False}) for q in queries[:2]]
        c += [("search", {"query": q, "top": 3, "cursor": "3"}) for q in queries[:2]]
        c += [("read", {"doc_id": d}) for d in docs[:8]]
        c += [("read", {"doc_id": d[:8]}) for d in docs[8:11]]
        c += [("read", {"doc_id": d, "start": 0, "end": 20}) for d in docs[11:13]]
        c += [("read", {"doc_id": idx.chunks[ch].doc_id, "chunk": ch}) for ch in chunks[:2]]
        c += [("read", {"doc_id": el_doc, "element": element})]
        c += [("grep", {"pattern": p}) for p in ["vessel", "harbour", "levy", "[Tt]win note",
                                                 "quokkalith|zanzibarite", "refund"]]
        c += [("grep", {"pattern": "vessel", "doc": d}) for d in (did(PUBLIC), did(GLOBEX))]
        c += [("grep", {"pattern": "vessel", "max": 2, "cursor": f"{docs[3]}:0"}),
              ("grep", {"pattern": "VESSEL", "ignore_case": True, "max": 5})]
        c += [("search_tools", {"query": q}) for q in ["git", "time zone", "fetch url",
                                                       "weather", "repository status"]]
        c += [("search_tools", {"query": "git", "filters": {"source_kind": ["mcp"]}})]
        c += [("load_tool", {"tool_id": t}) for t in tool_ids[:4]]
        assert len(c) == 50
        out += [(caller, tool, args) for tool, args in c]
    return out


def test_one_hundred_fixed_calls_equal_the_python_api(store, servers):
    calls = fixed_calls(store)
    assert len(calls) == 100
    by_caller = {c: (servers(store, c), py(store, c)) for c in sorted({c for c, _, _ in calls})}
    outcomes = {"ok": 0, "error": 0}
    for caller, tool, args in calls:
        m, t = by_caller[caller]
        got = m.call(tool, args)
        try:
            want = as_json(getattr(t, tool)(**args))
        except tools.ToolError as e:
            assert got.is_error and text(got) == str(e), (tool, args)
            assert got.structured_content is None
            outcomes["error"] += 1
            continue
        assert not got.is_error, (tool, args, text(got))
        assert got.structured_content == want, (tool, args)
        assert text(got)  # a short text rendering
        outcomes["ok"] += 1
    assert outcomes["ok"] >= 70 and outcomes["error"] >= 5, outcomes  # both kinds exercised


# -- handles ------------------------------------------------------------------------------------

def five_calls(store, m) -> dict:
    tid = m.search_tools("git").hits[0].tool_id
    return {"search": ("search", {"query": "vessel harbour refund"}),
            "read": ("read", {"doc_id": did(PUBLIC)}),
            "grep": ("grep", {"pattern": "vessel", "max": 5}),
            "search_tools": ("search_tools", {"query": "git"}),
            "load_tool": ("load_tool", {"tool_id": tid})}


def test_every_result_has_a_handle_and_a_replay_with_it_is_identical(store, servers):
    m = servers(store)
    now = py(store).search("vessel").handle
    for name, (tool, args) in five_calls(store, m).items():
        first = m.call(tool, args)
        assert not first.is_error and first.structured_content["handle"] == now, name
        again = m.call(tool, {**args, "handle": first.structured_content["handle"]})
        assert not again.is_error and again.structured_content == first.structured_content
        assert "handle: " in text(first)


def test_a_handle_whose_index_directory_was_deleted_fails_explicitly(store, servers, tmp_path):
    import shutil

    m = servers(store)
    calls = five_calls(store, m)
    h = m.search("vessel").handle
    shutil.rmtree(store.path / "index" / h["index"].split(":")[0])
    for tool, args in calls.values():
        res = m.call(tool, {**args, "handle": h})
        assert res.is_error and text(res) == "handle no longer available: index"
    assert log_lines(store)[-1]["error"] == "handle no longer available: index"


def test_an_older_snapshot_handle_is_judged_against_the_current_acl(built, servers):
    """A server started at the first snapshot; GLOBEX is read with its handle; a new content
    snapshot without GLOBEX and a sync later, the same server and the same handle get "not
    found", byte for byte as an id that never existed (R15)."""
    store, config = built
    g = servers(store, "user:globex-0")
    old = g.read(did(GLOBEX))
    _second_snapshot(store, config, [d for d in [*DOCS, *mini_docs()] if d is not GLOBEX],
                     clock=acl.utc_now)
    none = absent_like(did(GLOBEX), [did(d) for d in DOCS])
    hidden = g.call("read", {"doc_id": did(GLOBEX), "handle": old.handle})
    missing = g.call("read", {"doc_id": none, "handle": old.handle})
    assert hidden.is_error and missing.is_error
    assert text(hidden) == text(missing).replace(none[:12], did(GLOBEX)[:12])
    grep = g.grep("globex", handle=old.handle)
    assert did(GLOBEX) not in {x.doc_id for x in grep.matches}
    assert grep.snapshot == old.snapshot  # the old snapshot, with the current ACL
    # the operator's view: the old snapshot still holds GLOBEX
    assert tools.Tools(store.path).read(did(GLOBEX), handle=old.handle).text == old.text


def test_a_handle_with_extra_fields_or_a_bad_shape_is_refused(store, servers):
    m = servers(store)
    h = m.search("vessel").handle
    for bad in ({**h, "extra": 1}, {k: v for k, v in h.items() if k != "tools"},
                {**h, "snapshot": 5}, "not a handle", {**h, "index": "nonsense"}):
        res = m.call("read", {"doc_id": did(PUBLIC), "handle": bad})
        assert res.is_error and "handle" in text(res), text(res)


# -- load_tool -----------------------------------------------------------------------------------

def test_load_tool_output_validates_as_an_mcp_tool(store, servers):
    m = servers(store, "user:auditor")  # sees every tool
    ids = sorted(acl.read_head(store.path)[1].tools)
    assert len(ids) > 10
    for tid in ids:
        res = m.call("load_tool", {"tool_id": tid})
        if res.is_error:  # a tool listed to no one
            assert text(res).startswith("no tool ")
            continue
        d = res.structured_content["definition"]
        tool = mcp_types.Tool.model_validate(d)
        assert tool.name == d["name"] and tool.input_schema == d["inputSchema"]
        assert tool.model_dump(by_alias=True, exclude_none=True, mode="json") == d


# -- the leak subset ----------------------------------------------------------------------------

SMALL = {"search-rare": 12, "search-title": 8, "grep-literal": 8, "grep-doc": 6, "read": 12}
TOOL_SMALL = {"tool-search": 15, "tool-load": 15}


def test_a_leak_probe_subset_passes_through_mcp(built, servers, tmp_path):
    """Leak probes of `adr_eval.probes.acl` derived from the fixture (content and tool
    families), each run through an `adr mcp` server of its caller and judged as the API
    probes are (the content probes against reference stores of each view)."""
    store, config = built
    made = {}

    def tools_for(caller):
        if caller not in made:
            made[caller] = servers(store, caller)
        return made[caller]

    ctx = probes_acl.context(store.path, tools.Tools(store.path).active_index())
    refs = {}
    for v in eq.views(acl.read_head(store.path)[1]):
        path = tmp_path / "views" / v.view[:12]
        eq.ensure_view_store(store, v.docs, path, emb_cache=tmp_path / "emb",
                             directory=config[0], policy=config[1], clock=fixed(T0))
        refs.update(dict.fromkeys(v.users, path))

    def reference_for(c):
        if c not in refs:
            return None
        return tools.Tools(refs[c], acl=True, caller=c, clock=fixed())

    probes = probes_acl.leak_probes(ctx, sizes=SMALL)
    results = [probes_acl.check(p, tools_for, reference_for, ctx) for p in probes]
    tctx = probes_acl.tool_context(store.path, tools.Tools(store.path).active_tool_index())
    tprobes = probes_acl.tool_leak_probes(tctx, sizes=TOOL_SMALL)
    results += [probes_acl.check_tool(p, tools_for, tctx) for p in tprobes]
    s = probes_acl.summarize(results)
    assert s["total"]["n"] == len(probes) + len(tprobes) >= 70
    assert s["total"]["leaks"] == 0 and s["total"]["invalid"] == 0, [
        r for r in results if r.leak or not r.valid][:3]
    assert all(s["total"]["checked_kinds"][k] > 0 for k in (
        "id_outside_view", "hidden_text", "not_found_differs", "score_differs",
        "count_includes_hidden"))
    assert {r.outcome for r in results if r.caller == probes_acl.GHOST} == {"denied:F4"}
    # every MCP call was logged with its caller and access decision (B5)
    lines = [ln for ln in log_lines(store) if ln["caller"] in made]
    assert lines and all(ln["acl_decision"] and "principals" in ln and "acl_snapshot" in ln
                         for ln in lines)


# -- refusals ------------------------------------------------------------------------------------

def test_ids_of_the_wrong_type_are_an_error_result_naming_the_argument(store, servers):
    m = servers(store)
    for tool, args, name in [("read", {"doc_id": 5}, "doc_id"),
                             ("read", {"doc_id": ["x"]}, "doc_id"),
                             ("read", {"doc_id": {"a": 1}}, "doc_id"),
                             ("read", {"doc_id": did(PUBLIC), "chunk": 7}, "chunk"),
                             ("read", {"doc_id": did(PUBLIC), "element": [1]}, "element"),
                             ("grep", {"pattern": "vessel", "doc": 5}, "doc"),
                             ("grep", {"pattern": 5}, "pattern"),
                             ("search", {"query": None}, "query"),
                             ("load_tool", {"tool_id": 5}, "tool_id"),
                             ("load_tool", {"tool_id": None}, "tool_id")]:
        res = m.call(tool, args)
        assert res.is_error and name in text(res) and "valid string" in text(res), text(res)
        assert "Traceback" not in text(res)
    # the same message for a hidden document's id and a missing one, given as a number
    assert text(m.call("read", {"doc_id": 1})) == text(m.call("read", {"doc_id": 2})).replace(
        "input_value=2", "input_value=1")


def test_top_above_fifty_and_unknown_arguments_are_refused(store, servers):
    m = servers(store)
    for tool, args, needle in [("search", {"query": "vessel", "top": 51}, "top"),
                               ("search_tools", {"query": "git", "top": 51}, "top"),
                               ("search", {"query": "vessel", "top": 0}, "top"),
                               ("grep", {"pattern": "vessel", "max": 101}, "max"),
                               ("search", {"query": "vessel", "hadle": {}}, "hadle"),
                               ("read", {"doc_id": did(PUBLIC), "caller": "user:auditor"},
                                "caller"),
                               ("search", {"query": "x", "filters": {"bogus": 1}}, "bogus")]:
        res = m.call(tool, args)
        assert res.is_error and needle in text(res), text(res)
    assert len(m.search("vessel", top=50).hits) <= 50


def test_tool_errors_are_error_results_with_the_message_exactly(store, servers):
    m = servers(store)
    t = py(store)
    none = absent_like(did(GLOBEX), [did(d) for d in DOCS])
    for tool, args in [("read", {"doc_id": none}), ("read", {"doc_id": did(GLOBEX)}),
                       ("grep", {"pattern": "a*"}), ("load_tool", {"tool_id": "0" * 64}),
                       ("search", {"query": "x", "cursor": "nope"})]:
        res = m.call(tool, args)
        with pytest.raises(tools.ToolError) as e:
            getattr(t, tool)(**args)
        assert res.is_error and text(res) == str(e.value)
    # an unknown caller starts (the server checks only that one is given) and is denied F4
    ghost = servers(store, "user:ghost")
    for tool, args in five_calls(store, m).values():
        res = ghost.call(tool, args)
        assert res.is_error and text(res).startswith("access denied (F4): ")


# -- starting the server ------------------------------------------------------------------------

def test_the_caller_can_come_from_adr_caller(store, servers):
    m = servers(store, None, env={**ENV, "ADR_CALLER": "user:globex-0"})
    m.read(did(GLOBEX))
    assert log_lines(store)[-1]["caller"] == "user:globex-0"


def test_a_server_without_a_caller_or_a_store_does_not_start(store, tmp_path):
    env = {k: v for k, v in __import__("os").environ.items() if k != "ADR_CALLER"}
    for argv, needle in [(["--store", str(store.path)], "no caller"),
                         (["--store", str(store.path), "--as", ""], "no caller"),
                         (["--store", str(tmp_path / "none"), "--as", CALLER], "no store")]:
        p = subprocess.run([sys.executable, "-m", "adr_store.cli", "mcp", *argv], cwd=REPO,
                           env=env, input="", capture_output=True, text=True, timeout=60)
        assert p.returncode == 2 and needle in p.stderr and p.stdout == "", p.stderr


def test_without_the_mcp_extra_adr_mcp_exits_2_and_the_rest_runs(store, capsys, monkeypatch):
    monkeypatch.setitem(sys.modules, "mcp", None)  # `import mcp...` raises ImportError
    monkeypatch.setitem(sys.modules, "mcp.server", None)
    assert cli.main(["mcp", "--store", str(store.path), "--as", CALLER]) == 2
    assert mcp_server.NO_MCP in capsys.readouterr().err
    code = ("import sys; sys.modules['mcp'] = None\n"
            "import adr_store.tools, adr_store.cli, adr_store.handles, adr_store.mcp_server\n"
            "from adr_store.cli import main\n"
            f"sys.exit(main(['read', {did(PUBLIC)!r}, '--store', {str(store.path)!r}, "
            "'--json']))")
    p = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True,
                       timeout=120)
    assert p.returncode == 0 and json.loads(p.stdout)["doc_id"] == did(PUBLIC), p.stderr


def test_server_parameters_run_adr_mcp(store, tmp_path):
    p = server_parameters(store.path, CALLER, emb_cache=tmp_path / "emb")
    assert p.command == sys.executable
    assert p.args == ["-m", "adr_store.cli", "mcp", "--store", str(store.path), "--as", CALLER,
                      "--emb-cache", str(tmp_path / "emb")]

