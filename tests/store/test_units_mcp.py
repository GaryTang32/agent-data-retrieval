"""The four unit tools over MCP (Phase 4 spec §11.2, constraint 8; Task 8; criterion D1 for
units): `adr mcp` started as a subprocess and driven with `adr_store.mcp_client.McpTools` on the
promoted units store of `units_fixtures.make_units_built` (re-synced with the real clock, which
the servers read). `tools/list` has the unit tools with input and output schemas and a handle;
fixed calls equal the Python API's results; hidden and unknown ids get one message; a handle
replay through MCP is identical; a Phase 3 handle is refused by the unit tools only. The unit
index is lexical-only (C8) and the servers run with `HF_HUB_OFFLINE=1`: no model is loaded."""

import dataclasses

import pytest

pytest.importorskip("mcp")

from adr_store import acl, mcp_server, tools  # noqa: E402
from adr_store.mcp_client import McpTools  # noqa: E402
from adr_store.units import overlay as units_overlay  # noqa: E402
from tests.store.units_fixtures import DOC_117_NEW, make_units_built  # noqa: E402

REPO = __import__("pathlib").Path(__file__).parents[2]
ENV = {"HF_HUB_OFFLINE": "1"}
UNIT_TOOLS = ("define", "rule_lookup", "procedure_lookup", "unit_search")
CALLER = "user:acme-0"
PROC = "procedure/IRM 21.4.1.3.1/6ab6c77c239d/d333d25deb8bef47"


@pytest.fixture
def store(tmp_path):
    s = make_units_built(tmp_path / "store")
    config = s.path.parent / f"{s.path.name}-acl"
    acl.sync(s.path, config / "directory.json", config / "policy.json", clock=acl.utc_now)
    return s


@pytest.fixture
def servers(tmp_path):
    made = []

    def start(store, caller=CALLER):
        made.append(McpTools(store.path, caller, cwd=REPO, env=ENV,
                             emb_cache=tmp_path / "emb"))
        return made[-1]

    yield start
    for m in made:
        m.close()


def py(store, caller=CALLER) -> tools.Tools:
    return tools.Tools(store.path, acl=True, caller=caller)


def outcome(fn, args, kwargs):
    """The result, or the error's class and text."""
    try:
        return fn(*args, **kwargs)
    except tools.ToolError as e:
        return type(e).__name__, str(e)


def text(res) -> str:
    return "".join(c.text for c in res.content if c.type == "text")


def test_tools_list_has_twelve_tools_with_output_schemas(store, servers):
    listed = {t.name: t for t in servers(store).list_tools().tools}
    # C10: every tool of TOOL_NAMES (Task 18 adds check_rules), the four unit tools among them
    assert set(listed) == set(mcp_server.TOOL_NAMES) and len(listed) == len(mcp_server.TOOL_NAMES)
    assert set(UNIT_TOOLS) <= set(listed)
    for name in UNIT_TOOLS:
        t = listed[name]
        ins, outs = t.input_schema, t.output_schema
        assert ins["additionalProperties"] is False and "handle" in ins["properties"]
        assert not {"caller", "user", "principal", "as_user"} & set(ins["properties"])
        fields = {f.name for f in dataclasses.fields(mcp_server.RESULTS[name])}
        assert set(outs["properties"]) == fields and set(outs["required"]) == fields
        assert outs["additionalProperties"] is False
        assert outs == mcp_server.OUTPUTS[name].model_json_schema() | {
            k: v for k, v in outs.items() if k == "$defs"}
        assert "handle" in outs["properties"] and "units" in outs["properties"] and t.description
        a = t.annotations
        assert (a.read_only_hint, a.idempotent_hint, a.open_world_hint) == (True, True, False)
        if name != "define":
            lim = ins["properties"]["limit"]
            assert (lim["minimum"], lim["maximum"]) == (1, tools.UNIT_LIMIT_MAX)
    assert listed["define"].input_schema["required"] == ["term"]
    assert listed["unit_search"].input_schema["required"] == ["query"]
    p = listed["procedure_lookup"].input_schema["properties"]
    assert p["view"]["enum"] == list(tools.PROCEDURE_VIEWS) and p["view"]["default"] == "catalog"
    assert listed["rule_lookup"].input_schema["properties"]["closure"]["default"] is True


FIXED = [
    ("define", ("designated representative",), {"context": "33 CFR 165.T01(b)"}),
    ("define", ("drawtendr",), {}),
    ("define", ("drawtenders",), {"include_superseded": True}),
    ("rule_lookup", (), {"rule_id": "§117.1081(a)(2)"}),
    ("rule_lookup", (), {"rule_id": "33 CFR 117.1081", "limit": 2}),
    ("rule_lookup", ("drawbridge open",), {"as_of": "2025-07-01"}),
    ("rule_lookup", ("regulated navigation area",), {"part": "165", "closure": False}),
    ("procedure_lookup", ("refund research",), {}),
    ("unit_search", ("drawbridge notice",), {"types": ["rule_card", "concept"], "limit": 4}),
    ("unit_search", ("RNA",), {}),
]


def test_fixed_calls_equal_the_python_api(store, servers):
    for caller in (CALLER, "user:globex-0"):
        m, p = servers(store, caller), py(store, caller)
        for name, args, kwargs in FIXED:
            assert outcome(getattr(m, name), args, kwargs) == outcome(
                getattr(p, name), args, kwargs), (caller, name, args)
        for view in tools.PROCEDURE_VIEWS:
            if caller == "user:globex-0":
                assert m.procedure_lookup(id=PROC, view=view) == p.procedure_lookup(id=PROC,
                                                                                    view=view)
    # hidden and unknown ids: one message, as an error result
    m = servers(store, "user:acme-1")
    for rid in ("33 CFR 165.13(a)", "33 CFR 117.9999(z)", "garbage"):
        with pytest.raises(tools.ToolError) as e:
            m.rule_lookup(rule_id=rid)
        assert str(e.value) == tools.UNKNOWN_RULE
    for pid in (PROC, "IRM 99.9"):
        with pytest.raises(tools.ToolError) as e:
            m.procedure_lookup(id=pid, view="skill")
        assert str(e.value) == tools.UNKNOWN_PROCEDURE
    with pytest.raises(tools.AccessDenied) as e:
        servers(store, "user:ghost").unit_search("refund")
    assert e.value.code == "F4"
    # the schema refuses what the method would: a limit over the cap, an unknown type or view
    raw = servers(store)
    for name, arguments in (("unit_search", {"query": "x", "limit": tools.UNIT_LIMIT_MAX + 1}),
                            ("unit_search", {"query": "x", "types": ["rules"]}),
                            ("procedure_lookup", {"id": PROC, "view": "pdf"}),
                            ("define", {"term": "x", "caller": "user:auditor"})):
        assert raw.call(name, arguments).is_error


def test_a_handle_replay_through_mcp_is_identical(store, servers):                  # D1
    m = servers(store)
    head = units_overlay.read_units_head(store.path)
    first = m.rule_lookup(rule_id="33 CFR 117.821(a)")
    assert first.units == head and first.handle["units"] == head
    assert m.rule_lookup(rule_id="33 CFR 117.821(a)", handle=first.handle) == first
    d = m.define("drawtender", handle=first.handle)
    assert d == py(store).define("drawtender", handle=first.handle)
    s = m.unit_search("drawbridge", handle=first.handle)
    assert m.unit_search("drawbridge", handle=s.handle) == s
    # a Phase 3 handle (no units part) validates, and is refused by the unit tools only
    old = {k: v for k, v in first.handle.items() if k != "units"}
    assert m.read(DOC_117_NEW, 0, 20, handle=old).handle == {**old, "units": None}
    with pytest.raises(tools.ToolError) as e:
        m.procedure_lookup("refund", handle=old)
    assert str(e.value) == tools.NO_HANDLE_UNITS
    units_overlay.units_manifest_path(store.path, head).unlink()
    with pytest.raises(tools.ToolError) as e:
        m.define("drawtender", handle=first.handle)
    assert str(e.value) == "handle no longer available: units"


def test_results_render_as_text(store, servers):
    m = servers(store)
    res = m.call("rule_lookup", {"rule_id": "117.1081(a)(2)"})
    assert not res.is_error
    lines = text(res).splitlines()
    assert lines[0].startswith("1 rule card(s), units ")
    assert lines[1].startswith("33 CFR 117.1081(a)(2) (exemption, version 943c774389f8)")
    assert any(ln.startswith("  exception_of 33 CFR 117.5(p1)") for ln in lines)
    assert lines[-1].startswith("handle: ")
    res = m.call("define", {"term": "drawtendr"})
    assert text(res).splitlines()[0] == (f"{tools.NO_DEFINITION} for 'drawtendr'; nearest "
                                         f"labels: Drawtender, Drawbridge, RNA, Regulated "
                                         f"navigation area, Designated representative")
    res = servers(store, "user:globex-0").call("procedure_lookup",
                                               {"id": PROC, "view": "skill"})
    assert text(res).startswith("---\nname: missing-refund-research-")
