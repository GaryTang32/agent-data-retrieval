"""`search_tools` and `load_tool` (Phase 2 spec §8.2, §5.4, §6.2, §12 Tools and Permissions):
hit and definition shapes, determinism, the `source_kind` filter, per-view equivalence with a
catalog of the view's tools, not-found byte equality, the fail-closed rules of the tool
catalog, the row-exact dense kernel and the log fields. A tools-only fixture store (the
hand-made, reference-server and ToolRet-shaped tools), lexical-only indexes or the fake
embedder; nothing reads `data/` or `.cache/`."""

import json
import subprocess
import sys

import pytest

from adr_store import acl, cli, tool_catalog, tool_records, tools
from adr_store.records import canonical_json
from adr_store.retrieval.tool_index import ToolIndex, tool_view_id
from adr_store.store import Store
from adr_store.tool_catalog import ToolCatalog
from tests.store.test_permissions import REPO, T0, absent_like, fixed, log_lines, write_config
from tests.store.test_retrieval import fake_cache
from tests.store.test_tool_index import QUERIES, fixture_records

TOOL_RULES = [
    {"match": {"uri_prefix": "fixture:mcp/handmade"}, "access": ["tenant:acme"]},
    {"match": {"uri_prefix": "fixture:openapi/handmade"}, "access": ["group:acme/0"]},
    {"match": {"uri_prefix": "pypi:mcp-server-git"}, "access": ["public"]},
    {"match": {"uri_prefix": "pypi:mcp-server-time"}, "access": ["tenant:globex"]},
    {"match": {"uri_prefix": "pypi:mcp-server-fetch"}, "access": []},
]
USERS = ["user:acme-0", "user:acme-1", "user:globex-0", "user:outsider", "user:auditor"]
HIT_KEYS = {"rank", "tool_id", "name", "summary", "source_kind", "source_uri", "score",
            "tools_snapshot"}
DEFINITION_KEYS = {"name", "title", "description", "inputSchema", "outputSchema"}


@pytest.fixture(autouse=True)
def _fresh_view_cache():
    tools._TOOL_VIEW_LEXICAL.clear()
    yield
    tools._TOOL_VIEW_LEXICAL.clear()


@pytest.fixture
def fake_models(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "make_embedding_cache",
                        lambda path=None, *, threads=1: fake_cache(tmp_path / "emb"))


@pytest.fixture
def config(tmp_path):
    return write_config(tmp_path / "config", TOOL_RULES)


def make(path, config, recs=None, *, dense=False, w_name=1, weight=0.5, sync=True):
    tool_catalog.ingest(path, fixture_records() if recs is None else recs)
    t = tools.Tools(path)
    if dense:
        t.tools_index(w_name, weight=weight)
    else:
        t.tools_index(w_name, lexical_only=True)
    if sync:
        acl.sync(path, *config, clock=fixed(T0))
    return path


@pytest.fixture
def store(tmp_path, config):
    return make(tmp_path / "store", config)


def as_(path, caller, clock=None) -> tools.Tools:
    return tools.Tools(path, acl=True, caller=caller, clock=clock or fixed())


def visible_tools(path, caller) -> set[str]:
    snap = acl.read_head(path)[1]
    ps = set(snap.directory[caller])
    return {t for t, v in snap.tools.items() if ps & set(v)}


def err(fn, *a, **kw) -> tools.ToolError:
    with pytest.raises(tools.ToolError) as e:
        fn(*a, **kw)
    return e.value


def records_by_id():
    return {r.tool_id: r for r in fixture_records()}


# -- shapes ------------------------------------------------------------------------------------

def test_search_tools_hits(store):
    res = tools.Tools(store).search_tools("git status of the working tree", top=5)
    d = res.to_dict()
    assert set(d) == {"query", "top", "tools_snapshot", "fingerprint", "lexical_only",
                      "w_name", "w", "hits", "filters", "excluded_by_filter"}
    head = (store / "tools" / "HEAD").read_text().strip()
    assert d["tools_snapshot"] == head and d["lexical_only"] and d["w"] is None
    assert 1 <= len(res.hits) <= 5 and [h.rank for h in res.hits] == list(
        range(1, len(res.hits) + 1))
    recs = records_by_id()
    for h in d["hits"]:
        assert set(h) == HIT_KEYS and h["tools_snapshot"] == head
        rec = recs[h["tool_id"]]
        assert (h["name"], h["source_kind"], h["source_uri"]) == (
            rec.name, rec.source_kind, rec.source_uri)
        assert len(h["summary"]) <= 200 and rec.description.startswith(h["summary"][:20])
    assert res.hits[0].name == "git_status"
    assert "inputSchema" not in json.dumps(d)  # search does not return schemas


def test_load_tool_is_structurally_an_mcp_tool(store):
    t = tools.Tools(store)
    head = (store / "tools" / "HEAD").read_text().strip()
    for tid, rec in records_by_id().items():
        res = t.load_tool(tid)
        d = res.to_dict()
        assert set(d) == {"tool_id", "definition", "source_kind", "source_uri",
                          "source_version", "operation", "license", "definition_tokens",
                          "tools_snapshot"}
        assert d["tools_snapshot"] == head and d["definition_tokens"] == rec.definition_tokens
        defn = d["definition"]
        assert defn == tool_records.definition(rec)
        assert {"name", "inputSchema"} <= set(defn) <= DEFINITION_KEYS
        assert isinstance(defn["name"], str) and defn["name"]
        schema = defn["inputSchema"]
        assert schema["type"] == "object" and isinstance(schema["properties"], dict)
        assert set(schema.get("required", [])) <= set(schema["properties"])
        if "outputSchema" in defn:
            assert defn["outputSchema"]["type"] == "object"


def test_load_tool_by_prefix_and_not_found(store):
    t = tools.Tools(store)
    tid = next(iter(records_by_id()))
    assert t.load_tool(tid[:10]).tool_id == tid
    head = (store / "tools" / "HEAD").read_text().strip()
    e = err(t.load_tool, absent_like(tid, set(records_by_id())))
    assert str(e) == f"no tool {tid[:12]}… in tool snapshot {head[:12]}…"
    assert "at least 8" in str(err(t.load_tool, "abc"))
    assert "string" in str(err(t.load_tool, 5))


def test_search_tools_refuses_bad_arguments(store):
    t = tools.Tools(store)
    for top in (0, 101, True, "3"):
        assert "top" in str(err(t.search_tools, "git", top=top))
    for filters in ({"kind": ["mcp"]}, {"source_kind": ["sql"]}, {"source_kind": "mcp"}, [1]):
        assert "filters" in str(err(t.search_tools, "git", filters=filters))


def test_without_a_catalog_or_tool_index(tmp_path, config):
    path = tool_catalog.ensure_store(tmp_path / "s")
    assert "adr tools ingest" in str(err(tools.Tools(path).search_tools, "git"))
    tool_catalog.ingest(path, fixture_records())
    assert "adr tools index" in str(err(tools.Tools(path).search_tools, "git"))


# -- determinism --------------------------------------------------------------------------------

def test_tool_search_is_deterministic(store, tmp_path):
    a = [tools.Tools(store).search_tools(q, top=20).to_dict() for q in QUERIES]
    b = [as_(store, "user:auditor").search_tools(q, top=20).to_dict() for q in QUERIES]
    tools._TOOL_VIEW_LEXICAL.clear()
    c = [tools.Tools(store).search_tools(q, top=20).to_dict() for q in QUERIES]
    d = [as_(store, "user:auditor").search_tools(q, top=20).to_dict() for q in QUERIES]
    assert a == c and b == d and a != b  # the auditor's view lacks the tools of no one
    out = subprocess.run(
        [sys.executable, "-m", "adr_store.cli", "search-tools", QUERIES[0], "--top", "20",
         "--store", str(store), "--emb-cache", str(tmp_path / "emb"), "--json"],
        cwd=REPO, capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == a[0]


# -- filters ------------------------------------------------------------------------------------

def test_source_kind_filter_masks_within_the_view(store):
    t = tools.Tools(store)
    every = t.search_tools("note node tree git weather", top=100)
    mcp = t.search_tools("note node tree git weather", top=100,
                         filters={"source_kind": ["mcp"]})
    assert mcp.filters == {"source_kind": ["mcp"]}
    assert every.filters == {"source_kind": None}
    assert {h.source_kind for h in mcp.hits} == {"mcp"}
    assert [h.tool_id for h in mcp.hits] == [h.tool_id for h in every.hits
                                             if h.source_kind == "mcp"]
    assert mcp.excluded_by_filter == sum(r.source_kind != "mcp" for r in fixture_records())
    u = as_(store, "user:outsider")
    seen = visible_tools(store, "user:outsider")
    res = u.search_tools("note node tree git weather", filters={"source_kind": ["toolret"]})
    assert res.excluded_by_filter == sum(records_by_id()[t].source_kind != "toolret"
                                         for t in seen)


# -- per-view statistics ------------------------------------------------------------------------

@pytest.mark.parametrize("dense", [False, True])
def test_per_view_search_equals_a_catalog_of_the_view_only(tmp_path, config, fake_models,
                                                           dense):
    store = make(tmp_path / "store", config, dense=dense, w_name=2, weight=0.4)
    recs = records_by_id()
    for i, caller in enumerate(USERS):
        seen = visible_tools(store, caller)
        assert seen
        small = make(tmp_path / f"view{i}", config, [recs[t] for t in sorted(seen)],
                     dense=dense, w_name=2, weight=0.4)
        assert visible_tools(small, caller) == seen  # the same rules over the same uris
        mine, ref = as_(store, caller), as_(small, caller)
        for q in QUERIES:
            got = [(h.tool_id, h.score) for h in mine.search_tools(q, top=20).hits]
            want = [(h.tool_id, h.score) for h in ref.search_tools(q, top=20).hits]
            assert got == want, (caller, q)
            assert all(t in seen for t, _ in got)


def test_one_document_view_with_two_tool_views_shares_no_statistics(store):
    a, g = as_(store, "user:acme-0"), as_(store, "user:globex-0")
    acc_a = acl.resolve(store, "user:acme-0", Store.open(store).snapshot_id, clock=fixed())
    acc_g = acl.resolve(store, "user:globex-0", Store.open(store).snapshot_id, clock=fixed())
    assert acc_a.view == acc_g.view and acc_a.tools != acc_g.tools  # same (empty) doc view
    a.search_tools("git note time")
    g.search_tools("git note time")
    fp = tools.Tools(store).active_tool_index().fingerprint
    assert set(tools._TOOL_VIEW_LEXICAL) == {(fp, tool_view_id(acc_a.tools)),
                                             (fp, tool_view_id(acc_g.tools))}
    lines = [ln for ln in log_lines(_S(store)) if ln["tool"] == "search_tools"]
    assert lines[-1]["view"] == lines[-2]["view"]
    assert lines[-1]["tool_view"] != lines[-2]["tool_view"]


class _S:
    def __init__(self, path):
        self.path = path


def test_the_auditor_sees_every_tool_but_the_ones_of_no_one(store):
    assert visible_tools(store, "user:auditor") == set(records_by_id()) - {
        r.tool_id for r in fixture_records() if r.source_uri.startswith("pypi:mcp-server-fetch")}


def test_dense_scores_are_row_exact_under_the_acl_layer(tmp_path, config, fake_models,
                                                        monkeypatch):
    store = make(tmp_path / "store", config, dense=True)
    seen = []
    real = ToolIndex.retrieve

    def spy(self, *a, **kw):
        seen.append(kw.get("exact", False))
        return real(self, *a, **kw)

    monkeypatch.setattr(ToolIndex, "retrieve", spy)
    tools.Tools(store).search_tools("git status")
    as_(store, "user:auditor").search_tools("git status")
    as_(store, "user:outsider").search_tools("git status")
    assert seen == [False, True, True]


# -- invisible tools do not exist ---------------------------------------------------------------

def test_an_invisible_tool_is_reported_as_a_nonexistent_one(store):
    recs = records_by_id()
    every = sorted(recs)
    for caller in USERS:
        seen = visible_tools(store, caller)
        t = as_(store, caller)
        for tid in sorted(set(every) - seen):
            hidden = str(err(t.load_tool, tid))
            assert hidden == str(err(t.load_tool, absent_like(tid, every)))
            rec = recs[tid]
            res = t.search_tools(f"{rec.name} {rec.description}", top=50)
            assert all(h.tool_id in seen for h in res.hits)
        for tid in sorted(seen)[:3]:
            assert t.load_tool(tid).tool_id == tid


def test_prefixes_resolve_among_visible_tools_only(store):
    every = sorted(records_by_id())
    caller = "user:outsider"
    seen = sorted(visible_tools(store, caller))
    hidden = [t for t in every if t not in seen]
    t = as_(store, caller)
    absent = next(f"{i:08x}" for i in range(10_000)
                  if not any(x.startswith(f"{i:08x}") for x in every))
    for tid in hidden[:5]:
        msg = str(err(t.load_tool, tid[:8]))
        assert msg.replace(tid[:8], "<p>") == str(err(t.load_tool, absent)).replace(
            absent, "<p>")
    lines = [ln for ln in log_lines(_S(store)) if ln["tool"] == "load_tool"]
    assert lines[0]["not_visible"] == [hidden[0]] and lines[0]["results"] == []


# -- fail closed: the tool catalog ---------------------------------------------------------------

def _denied(t, code="F2"):
    for call in (lambda: t.search_tools("git status"),
                 lambda: t.load_tool(next(iter(records_by_id())))):
        e = err(call)
        assert isinstance(e, tools.AccessDenied) and e.code == code, str(e)


def test_a_catalog_newer_than_the_acl_snapshot_denies_both_tools(store, config):
    extra = tool_records.from_mcp({"tools": [{"name": "late_tool", "description": "Late.",
                                              "inputSchema": {"type": "object"}}]},
                                  "late", "fixture:mcp/late", "1", "CC0-1.0")
    t = as_(store, "user:auditor")
    assert t.search_tools("git status").hits
    tool_catalog.ingest(store, extra)
    _denied(t)
    _denied(as_(store, "user:outsider"))
    assert "tools/HEAD" not in str(err(t.search_tools, "git"))  # a reason, no internals
    acl.sync(store, *config, clock=fixed(T0))
    assert "adr tools index" in str(err(t.search_tools, "git status"))  # allowed; index old
    assert t.load_tool(extra[0].tool_id).definition["name"] == "late_tool"
    lines = [ln for ln in log_lines(_S(store)) if ln["acl_decision"] == "denied:F2"]
    assert lines and all(ln["tool"] in ("search_tools", "load_tool") for ln in lines)


def test_an_acl_snapshot_without_a_tool_snapshot_denies_when_a_catalog_exists(tmp_path,
                                                                             config):
    path = tool_catalog.ensure_store(tmp_path / "s")
    acl.sync(path, *config, clock=fixed(T0))
    assert acl.read_head(path)[1].tool_snapshot is None
    t = as_(path, "user:auditor")
    assert "adr tools ingest" in str(err(t.search_tools, "git"))  # no catalog: nothing to see
    tool_catalog.ingest(path, fixture_records())
    tools.Tools(path).tools_index(1, lexical_only=True)
    _denied(t)
    acl.sync(path, *config, clock=fixed(T0))
    assert t.search_tools("git status").hits


@pytest.mark.parametrize("damage", ["garbage", "directory", "missing"])
def test_a_bad_tools_head_denies(store, damage):
    head = store / "tools" / "HEAD"
    if damage == "garbage":
        head.write_text("not a snapshot id\n")
    elif damage == "directory":
        head.unlink()
        head.mkdir()
    else:
        head.unlink()
    _denied(as_(store, "user:auditor"))
    e = err(tools.Tools(store).search_tools, "git")  # without the ACL layer: refused
    assert not isinstance(e, tools.AccessDenied) and "unexpected" not in str(e)


def test_a_damaged_tool_snapshot_file_denies(store):
    sid = (store / "tools" / "HEAD").read_text().strip()
    path = store / "tools" / "snapshots" / f"{sid}.json"
    path.write_bytes(path.read_bytes().replace(b'"tools"', b'"tools" ', 1))
    _denied(as_(store, "user:auditor"))


def _acl_with_phantom(store, phantom: str) -> None:
    sid, snap = acl.read_head(store)
    data = json.loads(acl.snapshot_path(store, sid).read_bytes())
    data["tools"][phantom] = ["public"]
    data["entries_sha256"] = acl.entries_sha256(data["directory"], data["docs"], data["tools"])
    blob = canonical_json(acl.AclSnapshot.model_validate(data))
    import hashlib

    new = hashlib.sha256(blob).hexdigest()
    acl.snapshot_path(store, new).write_bytes(blob)
    (acl.acl_dir(store) / "HEAD").write_text(f"{new}\n")


def test_a_tool_the_acl_lists_but_the_catalog_lacks_is_not_found(store):
    every = sorted(records_by_id())
    phantom = absent_like(every[0], every)
    _acl_with_phantom(store, phantom)
    t = as_(store, "user:outsider")
    other = absent_like(every[1], every)
    assert str(err(t.load_tool, phantom)).replace(phantom[:12], "<id>") == \
        str(err(t.load_tool, other)).replace(other[:12], "<id>")
    assert t.search_tools("git status").hits  # the rest works
    line = [ln for ln in log_lines(_S(store)) if ln["tool"] == "load_tool"][0]
    assert line["tool_error"].startswith("KeyError")


def test_a_damaged_tool_record_is_not_found(store):
    recs = records_by_id()
    tid = sorted(visible_tools(store, "user:outsider"))[0]
    path = store / "tools" / "records" / tid[:2] / f"{tid}.json"
    path.write_bytes(path.read_bytes().replace(b'"license"', b'"license" ', 1))
    for t in (as_(store, "user:outsider"), tools.Tools(store)):
        absent = absent_like(tid, sorted(recs))
        got = str(err(t.load_tool, tid))
        assert got.replace(tid[:12], "<id>") == str(err(t.load_tool, absent)).replace(
            absent[:12], "<id>")
    lines = [ln for ln in log_lines(_S(store)) if ln["tool"] == "load_tool"]
    assert "StoreError" in lines[0]["tool_error"]


@pytest.mark.parametrize("caller,code", [(None, "F4"), ("user:ghost", "F4"),
                                         ("group:acme/0", "F5")])
def test_f4_and_f5_deny_the_tool_tools(store, caller, code):
    _denied(as_(store, caller), code)


def test_stale_and_missing_acl_deny_the_tool_tools(store):
    from datetime import timedelta

    _denied(as_(store, "user:auditor", clock=fixed(T0 + timedelta(hours=2))), "F3")
    (acl.acl_dir(store) / "HEAD").unlink()
    _denied(as_(store, "user:auditor"), "F1")


def test_a_new_content_snapshot_denies_the_tool_tools(store, config):
    from tests.store.test_permissions import PUBLIC

    s = Store.open(store)
    s.add(*PUBLIC)
    s.commit()
    _denied(as_(store, "user:auditor"))


# -- operator calls -----------------------------------------------------------------------------

def test_tools_index_and_active_tool_index_are_operator_calls(store):
    t = as_(store, "user:auditor")
    assert "operator" in str(err(t.tools_index, 1, lexical_only=True))
    assert "operator" in str(err(t.active_tool_index))
    info = tools.Tools(store).tools_index(1, lexical_only=True)
    assert info.source == "loaded" and info.n_tools == len(fixture_records())
    active = json.loads((store / "tools" / "index" / "active.json").read_text())
    assert active["fingerprint"] == info.fingerprint and active["w_name"] == 1
    assert (store / "tools" / "index" / info.fingerprint / "meta.json").is_file()


def test_tools_index_needs_a_weight_for_a_dense_index(store, fake_models):
    t = tools.Tools(store)
    assert "weight" in str(err(t.tools_index, 1))
    assert "weight" in str(err(t.tools_index, 1, weight=0.5, lexical_only=True))
    assert "w_name" in str(err(t.tools_index, -1, lexical_only=True))
    info = t.tools_index(2, weight=0.3)
    assert (info.w, info.lexical_only, info.w_name) == (0.3, False, 2)
    assert t.search_tools("git status").w == 0.3


@pytest.mark.parametrize("dense,lie,where", [
    (True, {"lexical_only": True, "w": None}, "meta.json"),
    (False, {"lexical_only": False, "w": 0.5}, "meta.json"),
    (False, {"w_name": 3}, "meta.json"),
    (True, {"lexical_only": True}, "with w 0.5"),  # contradicts itself
])
def test_active_json_that_contradicts_the_index_metadata_is_damaged(tmp_path, config,
                                                                    fake_models, monkeypatch,
                                                                    dense, lie, where):
    store = make(tmp_path / "store", config, dense=dense)
    path = store / "tools" / "index" / "active.json"
    active = json.loads(path.read_text())
    path.write_text(json.dumps({**active, **lie}))

    def no_model(*a, **kw):
        raise AssertionError("an embedder was loaded for a damaged active.json")

    monkeypatch.setattr(tools, "make_embedding_cache", no_model)
    for t in (tools.Tools(store), as_(store, "user:auditor")):
        e = err(t.search_tools, "git status")
        assert "active tool index missing or damaged" in str(e) and where in str(e)
    assert "damaged" in str(err(tools.Tools(store).active_tool_index))


# -- log fields ---------------------------------------------------------------------------------

def test_log_fields_of_the_tool_tools(store):
    t = as_(store, "user:outsider")
    t.search_tools("git status", filters={"source_kind": ["mcp"]})
    hidden = sorted(set(records_by_id()) - visible_tools(store, "user:outsider"))[0]
    err(t.load_tool, hidden)
    seen = sorted(visible_tools(store, "user:outsider"))[0]
    t.load_tool(seen)
    _denied(as_(store, "user:ghost"), "F4")
    lines = [ln for ln in log_lines(_S(store)) if ln["tool"] in ("search_tools", "load_tool")]
    s, nf, ok, d1, d2 = lines
    snap = acl.read_head(store)[0]
    head = (store / "tools" / "HEAD").read_text().strip()
    fp = tools.Tools(store).active_tool_index().fingerprint
    for ln in (s, nf, ok):
        assert ln["caller"] == "user:outsider" and ln["acl_decision"] == "allowed"
        assert ln["acl_snapshot"] == snap and ln["principals"] and ln["view"]
        assert ln["tools_snapshot"] == head
        assert ln["tool_view"] == tool_view_id(visible_tools(store, "user:outsider"))
    assert s["args"] == {"query": "git status", "top": 10,
                         "filters": {"source_kind": ["mcp"]}}
    assert s["filters"] == {"source_kind": ["mcp"]} and s["tool_index"] == fp
    assert s["results"] == [h.tool_id for h in t.search_tools(
        "git status", filters={"source_kind": ["mcp"]}).hits]
    assert nf["args"] == {"tool_id": hidden} and nf["not_visible"] == [hidden]
    assert nf["results"] == [] and nf["error"].startswith("no tool ")
    assert ok["results"] == [seen] and ok["not_visible"] == []
    for ln in (d1, d2):
        assert ln["acl_decision"] == "denied:F4" and ln["caller"] == "user:ghost"
        assert ln["tools_snapshot"] is None and ln["results"] == []
    off = tools.Tools(store)
    off.search_tools("git")
    last = log_lines(_S(store))[-1]
    assert last["acl_decision"] == "off" and last["tool_view"] is None


# -- the command line --------------------------------------------------------------------------

def test_cli_tools_index_search_tools_and_load_tool(tmp_path, config, capsys):
    path = tmp_path / "s"
    tool_catalog.ingest(path, fixture_records())
    assert cli.main(["tools", "index", "--store", str(path), "--w-name", "2",
                     "--lexical-only"]) == 0
    out = capsys.readouterr().out
    assert "tool index" in out and "w_name 2" in out
    acl.sync(path, *config)
    assert cli.main(["search-tools", "git status", "--store", str(path), "--as",
                     "user:outsider"]) == 0
    out = capsys.readouterr().out
    assert "git_status" in out
    assert cli.main(["search-tools", "git status", "--store", str(path), "--json",
                     "--source-kind", "toolret"]) == 0
    res = json.loads(capsys.readouterr().out)
    assert {h["source_kind"] for h in res["hits"]} <= {"toolret"}
    tid = next(r.tool_id for r in fixture_records() if r.name == "git_status")
    assert cli.main(["load-tool", tid[:10], "--store", str(path), "--as", "user:outsider",
                     "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["definition"]["name"] == "git_status"
    hidden = next(r.tool_id for r in fixture_records()
                  if r.source_uri.startswith("pypi:mcp-server-fetch"))
    assert cli.main(["load-tool", hidden, "--store", str(path), "--as", "user:outsider"]) == 2
    assert capsys.readouterr().err.startswith("error: no tool ")
    assert cli.main(["load-tool", hidden, "--store", str(path), "--as", "user:ghost"]) == 2
    assert "(F4)" in capsys.readouterr().err
    assert ToolCatalog.open(path).snapshot_id == acl.read_head(path)[1].tool_snapshot
