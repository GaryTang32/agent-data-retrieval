"""Tool records, adapters, the tool catalog and the ACL sync of tools (Phase 2 spec §8.1, §8.3,
§5.3; §12 Tools: adapters on fixtures and on the pinned real sources, `tool_id` stable)."""

import hashlib
import json
import time
from pathlib import Path

import pytest

from adr_eval.retrieval.chunker import _count
from adr_store import acl, cli, records, tool_catalog, tool_records
from adr_store.store import Store, StoreError
from adr_store.tool_catalog import ToolCatalog
from adr_store.tool_records import ToolRecord

REPO = Path(__file__).parents[2]
FIX = REPO / "tests" / "fixtures" / "tools"
REF_SERVERS = ("mcp-server-time", "mcp-server-fetch", "mcp-server-git")
PINNED_TOOL_ID = "aff8714235311fa8d59a861c5aff97e7e0d6ca22b50012c8d117d42098d22f25"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def mcp_records(path: Path) -> list[ToolRecord]:
    cap = load(path)
    return tool_records.from_mcp(cap["tools_list"], cap["server"], cap["source_uri"],
                                 cap["version"], cap["license"])


def handmade_openapi() -> list[ToolRecord]:
    spec = load(FIX / "openapi" / "handmade.json")
    return tool_records.from_openapi(spec, "fixture:openapi/handmade", "1.2.0", "CC0-1.0")


def by_name(recs: list[ToolRecord]) -> dict[str, ToolRecord]:
    return {r.name: r for r in recs}


def sample_tools() -> list[dict]:
    rows = [json.loads(line) for line in
            (FIX / "toolret_sample.jsonl").read_text(encoding="utf-8").splitlines()]
    return [r["row"] for r in rows if r["table"] == "tools"]


def toolret_record(row: dict) -> ToolRecord:
    uri = tool_records.toolret_uri("mangopy/ToolRet-Tools", "rev0", "web", row["id"])
    return tool_records.from_toolret(json.loads(row["documentation"]), uri, "rev0",
                                     "Apache-2.0")


# -- the record ------------------------------------------------------------------------------

def test_tool_id_is_fixed_for_fixed_inputs():
    schema = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}
    inner = hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":"))
                           .encode()).hexdigest()
    want = hashlib.sha256(f"src:x\nsearch\n{inner}".encode()).hexdigest()
    assert tool_records.tool_id("src:x", "search", schema) == want
    # key order does not matter (canonical JSON); every input does
    reordered = {"required": ["q"], "properties": {"q": {"type": "string"}}, "type": "object"}
    assert tool_records.tool_id("src:x", "search", reordered) == want
    assert tool_records.tool_id("src:y", "search", schema) != want
    assert tool_records.tool_id("src:x", "find", schema) != want
    assert tool_records.tool_id("src:x", "search", {**schema, "required": []}) != want


def test_tool_id_pinned_value():
    want = hashlib.sha256(b"a\nb\n" + hashlib.sha256(b"{}").hexdigest().encode()).hexdigest()
    assert tool_records.tool_id("a", "b", {}) == want
    assert want == PINNED_TOOL_ID


def test_record_fields_are_those_of_the_spec():
    assert set(ToolRecord.model_fields) == {
        "tool_id", "name", "title", "description", "input_schema", "output_schema",
        "source_kind", "source_uri", "source_version", "operation", "license",
        "definition_tokens"}


def test_definition_and_definition_tokens():
    rec = by_name(mcp_records(FIX / "mcp" / "handmade.json"))["search_notes"]
    d = tool_records.definition(rec)
    assert d == {"name": "search_notes", "title": "Search notes",
                 "description": rec.description, "inputSchema": rec.input_schema,
                 "outputSchema": rec.output_schema}
    counted = {"name": rec.name, "description": rec.description,
               "inputSchema": rec.input_schema}
    text = json.dumps(counted, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert rec.definition_tokens == _count(text)
    bare = by_name(mcp_records(FIX / "mcp" / "handmade.json"))["list_notebooks"]
    assert set(tool_records.definition(bare)) == {"name", "description", "inputSchema"}


def test_conformance_is_structural():
    rec = by_name(mcp_records(FIX / "mcp" / "handmade.json"))["search_notes"]
    assert tool_records.conformance(rec) == []

    def broken(**upd):
        return tool_records.conformance(rec.model_copy(update=upd))

    assert broken(input_schema={"type": "string"})
    assert broken(input_schema={"type": "object"})  # no properties
    assert broken(input_schema={"type": "object", "properties": {"a": {}},
                                "required": ["b"]})
    assert broken(input_schema={"type": "object", "properties": []})
    assert broken(output_schema={"type": "array"})
    assert broken(definition_tokens=rec.definition_tokens + 1)
    assert broken(tool_id="0" * 64)
    assert broken(name="")


# -- MCP --------------------------------------------------------------------------------------

def test_mcp_adapter_on_the_handmade_fixture():
    recs = mcp_records(FIX / "mcp" / "handmade.json")
    assert [r.name for r in recs] == ["search_notes", "list_notebooks", "delete_note"]
    t = by_name(recs)
    assert all(r.source_kind == "mcp" and r.operation == {"server": "handmade-notes"}
               and r.source_uri == "fixture:mcp/handmade-notes" and r.source_version == "0.1.0"
               and r.license == "CC0-1.0" for r in recs)
    assert t["search_notes"].title == "Search notes"
    assert t["search_notes"].output_schema["required"] == ["ids"]
    assert t["delete_note"].title is None and t["delete_note"].output_schema is None
    # an MCP inputSchema without properties gets an empty one (MCP makes it optional)
    assert t["list_notebooks"].input_schema == {"type": "object", "properties": {}}
    assert all(tool_records.conformance(r) == [] for r in recs)


def test_mcp_adapter_refuses_duplicate_names():
    tl = {"tools": [{"name": "a", "inputSchema": {"type": "object"}}] * 2}
    with pytest.raises(ValueError, match="a"):
        tool_records.from_mcp(tl, "s", "fixture:s", "1", "MIT")


@pytest.mark.parametrize("server", REF_SERVERS)
def test_reference_server_snapshots_ingest_at_full_conformance(server):
    (path,) = sorted((FIX / "mcp").glob(f"{server}-*.json"))
    cap = load(path)
    assert cap["license"] == "MIT" and cap["version"] in path.name
    assert len(cap["wheel_sha256"]) == 64
    assert hashlib.sha256(tool_records.canonical(cap["tools_list"]).encode()).hexdigest() == \
        cap["tools_list_sha256"]
    recs = mcp_records(path)
    assert len(recs) == len(cap["tools_list"]["tools"]) > 0
    assert all(tool_records.conformance(r) == [] for r in recs)
    assert len({r.tool_id for r in recs}) == len(recs)


# -- OpenAPI ----------------------------------------------------------------------------------

def test_openapi_one_record_per_operation():
    t = by_name(handmade_openapi())
    assert sorted(t) == ["addNode", "delete_trees_treeId_nodes_id", "get_health", "listNodes"]
    assert t["listNodes"].operation == {"method": "GET", "path": "/trees/{treeId}/nodes",
                                        "operationId": "listNodes"}
    assert t["get_health"].operation["operationId"] is None
    assert all(r.source_kind == "openapi" and r.source_version == "1.2.0" for r in t.values())
    assert t["listNodes"].title == "List the nodes of a tree"
    assert t["listNodes"].description == "Returns the nodes of a tree, a page at a time."
    assert t["addNode"].description == "Add a node"  # no description: the summary
    assert t["get_health"].title is None and t["get_health"].description == ""


def test_openapi_path_query_and_header_parameters():
    s = by_name(handmade_openapi())["listNodes"].input_schema
    assert s["type"] == "object"
    assert s["properties"]["treeId"] == {"type": "string", "description": "The tree"}
    assert s["properties"]["limit"] == {"type": "integer", "minimum": 1,
                                        "description": "Page size"}  # a $ref parameter
    assert s["properties"]["id"]["description"] == "Only this node id"
    assert "X-Trace" in s["properties"]
    assert s["required"] == ["treeId"]  # a path parameter is always required


def test_openapi_same_name_in_two_locations():
    s = by_name(handmade_openapi())["delete_trees_treeId_nodes_id"].input_schema
    assert s["properties"]["id"] == {"type": "string"}
    assert s["properties"]["id__query"]["type"] == "boolean"
    assert s["required"] == ["treeId", "id"]


def test_openapi_request_body_prefers_json():
    s = by_name(handmade_openapi())["addNode"].input_schema
    body = s["properties"]["body"]
    assert body["type"] == "object" and body["description"] == "The node to add"
    assert body["required"] == ["name"]
    assert s["required"] == ["treeId", "body"]


def _depth(schema: dict) -> int:
    """How many Node levels a resolved Node schema has before the cut ({})."""
    n = 0
    while schema:
        n += 1
        schema = schema["properties"]["children"]["items"]
    return n


def test_openapi_ref_cycle_cut_at_the_first_repeat():
    t = by_name(handmade_openapi())
    body = t["addNode"].input_schema["properties"]["body"]
    assert _depth(body) == 1  # Node -> children[] -> Node is on the branch: cut to {}
    assert body["properties"]["children"] == {"type": "array", "items": {}}
    out = t["listNodes"].output_schema  # Page -> items[] -> Node -> children[] -> Node (cut)
    assert out["type"] == "object" and _depth(out["properties"]["items"]["items"]) == 1


def _openapi_body(schemas: dict, root: str) -> dict:
    return {"openapi": "3.0.0", "components": {"schemas": schemas},
            "paths": {"/a": {"post": {"requestBody": {"content": {"application/json": {
                "schema": {"$ref": f"#/components/schemas/{root}"}}}}, "responses": {}}}}}


@pytest.mark.parametrize("k", [4, 8])
def test_openapi_self_reference_fanout_stays_small(k):
    """The reviewer's reproduction: T = {properties: {p0..p(k-1): {$ref: T}}}."""
    props = {f"p{i}": {"$ref": "#/components/schemas/T"} for i in range(k)}
    t0 = time.perf_counter()
    (rec,) = tool_records.from_openapi(_openapi_body({"T": {"type": "object",
                                                            "properties": props}}, "T"),
                                       "u", "1", "x")
    assert time.perf_counter() - t0 < 2.0
    body = rec.input_schema["properties"]["body"]
    assert body == {"type": "object", "properties": {f"p{i}": {} for i in range(k)}}
    assert rec.definition_tokens < 100


def test_openapi_depth_8_bounds_a_chain_of_distinct_refs():
    schemas = {f"S{i}": {"type": "object", "properties": {"next": {
        "$ref": f"#/components/schemas/S{i + 1}"}}} for i in range(12)}
    (rec,) = tool_records.from_openapi(_openapi_body(schemas, "S0"), "u", "1", "x")
    node, levels = rec.input_schema["properties"]["body"], 0
    while node:
        levels += 1
        node = node["properties"]["next"]
    assert levels == tool_records.REF_DEPTH == 8


def test_openapi_node_budget_bounds_an_acyclic_fanout():
    """S0..S7, each with 6 properties referring to the next: 6**7 leaves without a budget."""
    schemas = {f"S{i}": {"type": "object", "properties": {
        f"p{j}": {"$ref": f"#/components/schemas/S{i + 1}"} for j in range(6)}}
        for i in range(7)}
    schemas["S7"] = {"type": "string"}
    stats: dict = {}
    t0 = time.perf_counter()
    (rec,) = tool_records.from_openapi(_openapi_body(schemas, "S0"), "u", "1", "x",
                                       stats=stats)
    assert time.perf_counter() - t0 < 5.0
    size = len(tool_records.canonical(rec.input_schema))
    assert size < 40 * tool_records.NODE_BUDGET  # bounded by the budget, not 6**7
    assert stats["budget_cuts"] > 0


def test_openapi_budget_is_per_operation():
    schemas = {f"S{i}": {"type": "object", "properties": {
        f"p{j}": {"$ref": f"#/components/schemas/S{i + 1}"} for j in range(6)}}
        for i in range(7)}
    schemas["S7"] = {"type": "string"}
    spec = _openapi_body(schemas, "S0")
    spec["paths"]["/b"] = spec["paths"]["/a"]
    a, b = tool_records.from_openapi(spec, "u", "1", "x")
    assert a.input_schema == b.input_schema


def test_openapi_output_schema_only_for_an_object():
    t = by_name(handmade_openapi())
    assert t["addNode"].output_schema["type"] == "object"
    assert t["get_health"].output_schema is None  # an array
    assert t["delete_trees_treeId_nodes_id"].output_schema is None  # no content


def test_openapi_refuses_swagger_2():
    with pytest.raises(ValueError, match="OpenAPI 3"):
        tool_records.from_openapi({"swagger": "2.0", "paths": {}}, "u", "1", "CC0-1.0")


def test_openapi_duplicate_names_are_numbered():
    op = {"operationId": "same", "responses": {}}
    spec = {"openapi": "3.0.0", "paths": {"/a": {"get": op}, "/b": {"get": op}}}
    names = [r.name for r in tool_records.from_openapi(spec, "u", "1", "CC0-1.0")]
    assert names == ["same", "same__2"]


def test_openapi_handmade_conforms():
    assert all(tool_records.conformance(r) == [] for r in handmade_openapi())


def test_the_twenty_pinned_openapi_specs_ingest_at_full_conformance():
    idx = load(FIX / "openapi" / "apisguru" / "index.json")
    assert idx["license"] == "CC0-1.0" and len(idx["commit"]) == 40
    assert len(idx["specs"]) == 20
    total = 0
    for s in idx["specs"]:
        data = (FIX / "openapi" / "apisguru" / s["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == s["sha256"] and len(data) < 200_000
        recs = tool_records.from_openapi(json.loads(data), s["source_uri"], s["version"],
                                         idx["license"])
        assert recs, s["file"]
        assert [p for r in recs for p in tool_records.conformance(r)] == [], s["file"]
        assert len({r.tool_id for r in recs}) == len(recs)
        total += len(recs)
    assert total > 20


# -- ToolRet ----------------------------------------------------------------------------------

def test_toolret_adapter_builds_an_object_schema():
    rows = {r["id"]: r for r in sample_tools()}
    rec = toolret_record(rows["toolbench_tool_0"])
    assert rec.source_kind == "toolret" and rec.name == "Skyline_Weather_Current"
    assert rec.source_uri == "toolret:mangopy/ToolRet-Tools@rev0/web#toolbench_tool_0"
    assert rec.operation == {"category": "Weather", "api_name": "Skyline_Weather_Current",
                             "method": "GET"}
    assert rec.title is None and rec.output_schema is None
    assert rec.input_schema == {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "City name",
                                "default": "Paris"},
                       "units": {"type": "string", "description": "metric or imperial",
                                 "default": "metric"}},
        "required": ["city"]}


def test_toolret_types_defaults_and_duplicates():
    rows = {r["id"]: r for r in sample_tools()}
    s = toolret_record(rows["toolbench_tool_2"]).input_schema
    assert s["properties"]["amount"] == {"type": "number", "default": 1.5}  # first wins
    assert s["properties"]["date"] == {"type": "string", "description": "Rate date"}
    assert s["required"] == ["amount", "from", "to"]
    s = toolret_record(rows["toolbench_tool_4"]).input_schema
    assert s["properties"]["sheet"] == {"description": "untyped parameter"}
    assert s["properties"]["columns"] == {"type": "array", "default": ["a", "b"]}
    assert s["properties"]["filter"] == {"type": "object"}
    assert s["required"] == ["sheet"]
    s = toolret_record(rows["toolbench_tool_3"]).input_schema
    assert s == {"type": "object", "properties": {}}  # no required key when none
    s = toolret_record(rows["toolbench_tool_1"]).input_schema
    assert s["properties"]["hourly"] == {"type": "boolean", "default": False}


def test_toolret_records_conform():
    for row in sample_tools():
        if row["id"].startswith("toolbench_tool_"):
            assert tool_records.conformance(toolret_record(row)) == []


# -- the catalog ------------------------------------------------------------------------------

def test_catalog_add_commit_open_get(tmp_path):
    recs = handmade_openapi()
    cat = ToolCatalog.create(tmp_path / "s")
    for r in recs:
        cat.add(r)
    sid = cat.commit()
    assert (tmp_path / "s" / "tools" / "HEAD").read_text().strip() == sid
    snap = tmp_path / "s" / "tools" / "snapshots" / f"{sid}.json"
    assert hashlib.sha256(snap.read_bytes()).hexdigest() == sid
    body = json.loads(snap.read_bytes())
    assert [e["tool_id"] for e in body["tools"]] == sorted(r.tool_id for r in recs)
    for r in recs:
        p = tmp_path / "s" / "tools" / "records" / r.tool_id[:2] / f"{r.tool_id}.json"
        assert p.read_bytes() == records.canonical_json(r)
    again = ToolCatalog.open(tmp_path / "s")
    assert again.snapshot_id == sid and again.ids() == sorted(r.tool_id for r in recs)
    assert again.get(recs[0].tool_id) == recs[0]
    assert len(again) == len(recs)
    with pytest.raises(KeyError):
        again.get("0" * 64)


def test_catalog_reingest_gives_the_same_snapshot(tmp_path):
    def ingest(path):
        cat = ToolCatalog.create(path)
        for r in reversed(handmade_openapi()):
            cat.add(r)
        return cat.commit()

    a = ingest(tmp_path / "a")
    assert ingest(tmp_path / "a") == a  # into the same store
    assert ingest(tmp_path / "b") == a  # into another store


def test_catalog_refuses_a_nonconforming_record(tmp_path):
    rec = handmade_openapi()[0]
    bad = rec.model_copy(update={"input_schema": {"type": "object"}})
    cat = ToolCatalog.create(tmp_path / "s")
    with pytest.raises(tool_catalog.ToolConformanceError, match="properties"):
        cat.add(bad)
    assert not (tmp_path / "s" / "tools" / "records").exists() or not any(
        (tmp_path / "s" / "tools" / "records").rglob("*.json"))


def test_catalog_is_write_once(tmp_path):
    rec = handmade_openapi()[0]
    cat = ToolCatalog.create(tmp_path / "s")
    cat.add(rec)
    other = rec.model_copy(update={"license": "other"})  # same id, other bytes
    with pytest.raises(StoreError):
        cat.add(other)


def test_catalog_open_checks_hashes(tmp_path):
    rec = handmade_openapi()[0]
    cat = ToolCatalog.create(tmp_path / "s")
    cat.add(rec)
    sid = cat.commit()
    with pytest.raises(StoreError, match="no tool catalog"):
        ToolCatalog.open(tmp_path / "other")
    with pytest.raises(StoreError, match="not found"):
        ToolCatalog.open(tmp_path / "s", "f" * 64)
    p = tmp_path / "s" / "tools" / "records" / rec.tool_id[:2] / f"{rec.tool_id}.json"
    p.write_bytes(p.read_bytes().replace(b"CC0-1.0", b"CC0-1.1"))
    with pytest.raises(StoreError, match="record hash"):
        ToolCatalog.open(tmp_path / "s", sid).get(rec.tool_id)
    snap = tmp_path / "s" / "tools" / "snapshots" / f"{sid}.json"
    snap.write_bytes(snap.read_bytes() + b" ")
    with pytest.raises(StoreError, match="does not hash"):
        ToolCatalog.open(tmp_path / "s", sid)


def test_tool_store_has_an_empty_content_snapshot(tmp_path):
    path = tool_catalog.ensure_store(tmp_path / "t")
    store = Store.open(path)
    assert store.doc_ids() == []
    sid = store.snapshot_id
    assert tool_catalog.ensure_store(path) == path
    assert Store.open(path).snapshot_id == sid  # kept, not re-made


# -- schemas ----------------------------------------------------------------------------------

def test_schemas_cover_the_tool_record_and_snapshot():
    s = records.schemas()
    assert s["tool-record.schema.json"]["title"] == "ToolRecord"
    assert s["tool-snapshot.schema.json"]["title"] == "ToolSnapshot"


# -- ACL sync covers the catalog --------------------------------------------------------------

@pytest.fixture
def config(tmp_path) -> tuple[Path, Path]:
    d = tmp_path / "config"
    d.mkdir()
    for name in ("directory.json", "policy.json"):
        (d / name).write_bytes((REPO / "config" / "acl" / name).read_bytes())
    return d / "directory.json", d / "policy.json"


def _tool_store(path: Path) -> tuple[Path, list[ToolRecord]]:
    tool_catalog.ensure_store(path)
    recs = handmade_openapi() + mcp_records(FIX / "mcp" / "handmade.json")
    cat = ToolCatalog.create(path)
    for r in recs:
        cat.add(r)
    cat.commit()
    return path, recs


def test_sync_writes_tool_snapshot_and_tools(tmp_path, config):
    path, recs = _tool_store(tmp_path / "t")
    res = acl.sync(path, *config)
    sid, snap = acl.read_head(path)
    head = (path / "tools" / "HEAD").read_text().strip()
    assert snap.tool_snapshot == head and res.tool_snapshot == head
    assert sorted(snap.tools) == sorted(r.tool_id for r in recs)
    policy = acl.parse_policy(config[1].read_bytes())
    directory = acl.parse_directory(config[0].read_bytes())
    for r in recs:  # keyed by tool_id through the same bucket rule
        assert snap.tools[r.tool_id] == acl.access_list(r.tool_id, {"uri": r.source_uri},
                                                         policy, directory)
    assert res.tools == len(recs) and sum(res.tool_kinds.values()) == len(recs)
    assert snap.docs == {} and res.documents == 0
    again = acl.sync(path, *config)
    assert again.entries_sha256 == res.entries_sha256 and again.changed is False


def test_sync_without_a_catalog_keeps_tools_empty(tmp_path, config):
    path = tool_catalog.ensure_store(tmp_path / "t")
    res = acl.sync(path, *config)
    _, snap = acl.read_head(path)
    assert snap.tool_snapshot is None and snap.tools == {} and res.tools == 0


def test_access_resolves_visible_tools(tmp_path, config):
    path, recs = _tool_store(tmp_path / "t")
    acl.sync(path, *config)
    content = Store.open(path).snapshot_id
    auditor = acl.resolve(path, "user:auditor", content)
    outsider = acl.resolve(path, "user:outsider", content)
    _, snap = acl.read_head(path)
    assert auditor.tools == frozenset(snap.tools)
    assert outsider.tools == frozenset(t for t, ps in snap.tools.items() if "public" in ps)


# -- adr tools ingest -------------------------------------------------------------------------

def test_cli_ingest_mcp_and_openapi(tmp_path, capsys):
    store = tmp_path / "s"
    code = cli.main(["tools", "ingest", "--mcp", str(FIX / "mcp" / "handmade.json"),
                     "--store", str(store)])
    out = capsys.readouterr().out
    assert code == 0 and "3 tools" in out and "conformance 100%" in out
    first = ToolCatalog.open(store).snapshot_id
    code = cli.main(["tools", "ingest", "--openapi", str(FIX / "openapi" / "handmade.json"),
                     "--source-uri", "fixture:openapi/handmade", "--license", "CC0-1.0",
                     "--store", str(store), "--json"])
    res = json.loads(capsys.readouterr().out)
    assert code == 0 and res["added"] == 4 and res["tools"] == 7
    assert res["tool_snapshot"] != first and res["conformance"] == 1.0
    assert ToolCatalog.open(store).get(by_name(handmade_openapi())["addNode"].tool_id)
    assert Store.open(store).doc_ids() == []


def test_cli_ingest_openapi_needs_source_and_license(tmp_path, capsys):
    code = cli.main(["tools", "ingest", "--openapi", str(FIX / "openapi" / "handmade.json"),
                     "--store", str(tmp_path / "s")])
    assert code == 2 and "--source-uri" in capsys.readouterr().err


def test_cli_ingest_refuses_nonconforming_tools(tmp_path, capsys):
    cap = load(FIX / "mcp" / "handmade.json")
    cap["tools_list"]["tools"][0]["inputSchema"] = {"type": "object", "properties": {},
                                                    "required": ["ghost"]}
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(cap))
    code = cli.main(["tools", "ingest", "--mcp", str(bad), "--store", str(tmp_path / "s")])
    err = capsys.readouterr().err
    assert code == 1 and "ghost" in err and "search_notes" in err
    assert not (tmp_path / "s" / "tools" / "HEAD").exists()
