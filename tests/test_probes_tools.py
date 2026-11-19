"""ACL probes for the tool tools (Phase 2 spec §10.2, B1, B4, B5; plan Task 10): the 200 tool
leak probes and their judge, the fail-closed probes (F1–F5 and "no entry" × 2 tools × 5
callers, plus the two tool-catalog conditions) and their log lines, on the tools-only fixture
store of `tests/store/test_tool_search.py`; `adr-eval tools-probes`."""

import dataclasses
import json

import pytest

from adr_eval import cli as eval_cli
from adr_eval import tools_eval
from adr_eval.probes import acl as probes
from adr_store import acl, tools
from tests.store.test_permissions import fixed, write_config
from tests.store.test_retrieval import fake_cache
from tests.store.test_tool_search import TOOL_RULES, make

PUBLIC_TOOLRET = {"match": {"uri_prefix": "toolret:mangopy/ToolRet-Tools@rev0/web#"
                                          "toolbench_tool_2"}, "access": ["public"]}
SMALL = {"tool-search": 30, "tool-load": 30}


@pytest.fixture(autouse=True)
def _fresh_view_cache():
    tools._TOOL_VIEW_LEXICAL.clear()
    yield
    tools._TOOL_VIEW_LEXICAL.clear()


@pytest.fixture
def config(tmp_path):
    return write_config(tmp_path / "config", [PUBLIC_TOOLRET, *TOOL_RULES])


@pytest.fixture(params=["lexical", "dense"])
def store(request, tmp_path, config, monkeypatch):
    if request.param == "dense":
        monkeypatch.setattr(tools, "make_embedding_cache",
                            lambda path=None, *, threads=1: fake_cache(tmp_path / "emb"))
    return make(tmp_path / "store", config, dense=request.param == "dense", w_name=2,
                weight=0.4)


def ctx_of(store):
    return probes.tool_context(store, tools.Tools(store).active_tool_index())


def make_tools(path, caller):
    return tools.Tools(path, acl=True, caller=caller, clock=fixed())


def test_tool_leak_probes_are_hidden_targets_and_deterministic(store):
    ctx = ctx_of(store)
    ps = probes.tool_leak_probes(ctx)
    assert [p.family for p in ps].count("tool-search") == 100
    assert [p.family for p in ps].count("tool-load") == 100
    assert ps == probes.tool_leak_probes(ctx_of(store))
    for p in ps:
        assert p.target["tool_id"] not in ctx.visible(p.caller)
    loads = [p for p in ps if p.family == "tool-load"]
    assert {p.target["given"] for p in loads} == {"id", "prefix"}
    assert all(p.control["tool_id"] not in ctx.ids() for p in loads)
    assert probes.GHOST in {p.caller for p in ps} and "user:outsider" in {p.caller for p in ps}


def test_tool_search_probes_split_unfiltered_and_filtered(store):
    ps = [p for p in probes.tool_leak_probes(ctx_of(store)) if p.family == "tool-search"]
    filters = [p.call.get("filters") for p in ps]
    assert len(ps) == 100 and filters.count(None) == 60
    assert filters.count({"source_kind": ["mcp"]}) == 20
    assert filters.count({"source_kind": ["mcp", "toolret"]}) == 20


def whole_index_count(t, store):
    """A variant of `search_tools` whose `excluded_by_filter` counts the exclusions over the
    whole index instead of the caller's view (a count that includes hidden tools)."""
    real = t.search_tools
    idx = tools.Tools(store).active_tool_index()

    def search_tools(query, top=10, *, filters=None):
        res = real(query, top, filters=filters)
        kinds = res.filters["source_kind"]
        if kinds is None:
            return res
        n = sum(r.source_kind in kinds for r in idx.rows.values())
        return dataclasses.replace(res, excluded_by_filter=len(idx.rows) - n)

    t.search_tools = search_tools
    return t


def test_the_probes_catch_a_whole_index_exclusion_count(store):
    ctx = ctx_of(store)
    ps = probes.tool_leak_probes(ctx)
    made: dict = {}

    def tools_for(caller):
        if caller not in made:
            made[caller] = whole_index_count(make_tools(store, caller), store)
        return made[caller]

    results = [probes.check_tool(p, tools_for, ctx) for p in ps]
    caught = [r for r in results if r.kinds["count_includes_hidden"]]
    assert caught and all(r.family == "tool-search" for r in caught)
    unfiltered = {p.probe_id for p in ps if p.call.get("filters") is None}
    assert not any(r.leak for r in results if r.probe_id in unfiltered)


def test_tool_leak_probes_find_no_leak(store):
    ctx = ctx_of(store)
    ps = probes.tool_leak_probes(ctx, sizes=SMALL)
    made: dict = {}

    def tools_for(caller):
        if caller not in made:
            made[caller] = make_tools(store, caller)
        return made[caller]

    results = [probes.check_tool(p, tools_for, ctx) for p in ps]
    s = probes.summarize(results)
    assert s["total"]["leaks"] == 0 and s["total"]["invalid"] == 0, [
        r for r in results if r.leak or not r.valid][:3]
    checked = s["total"]["checked_kinds"]
    assert checked["id_outside_view"] > 0 and checked["not_found_differs"] > 0
    assert checked["score_differs"] > 0 and checked["count_includes_hidden"] > 0


def test_the_judge_catches_a_leaky_tools(store):
    """Tools without the ACL layer leak: hidden ids, definitions and statistics."""
    ctx = ctx_of(store)
    ps = [p for p in probes.tool_leak_probes(ctx, sizes=SMALL) if p.caller != probes.GHOST]
    leaky = tools.Tools(store)
    results = [probes.check_tool(p, lambda c: leaky, ctx) for p in ps]
    kinds = probes.summarize(results)["total"]["leak_kinds"]
    assert kinds["id_outside_view"] > 0 and kinds["score_differs"] > 0
    assert all(r.leak for r in results if r.family == "tool-load")


def test_tool_failclosed_probes_pass(store, tmp_path, config):
    ctx = ctx_of(store)
    users = probes.failclosed_callers(ctx)
    ps = probes.tool_failclosed_probes(ctx, probes.tool_precheck(store, make_tools), users)
    assert len(ps) == 6 * 2 * 5 + 2 * 2 * 5
    assert {p.target["tool_id"] for p in ps} == {ps[0].target["tool_id"]}
    assert all(b["visible"] and b["rank"] <= 10 and b["load"]
               for b in ps[0].target["before"].values())
    results, logs = probes.run_tool_failclosed(
        ps, store, tmp_path / "clones", ctx, make_tools=make_tools, directory=config[0],
        policy=config[1], clock=fixed())
    bad = [r for r in results if not r["pass"]]
    assert not bad, bad[:3]
    assert sum(r["content"] for r in results) == 0
    fams = {r["family"] for r in results}
    assert fams == set(probes.TOOL_CONDITIONS)
    assert {r["outcome"] for r in results if r["family"] in ("F2-tools", "no-tool-snapshot")} \
        == {"denied:F2"}
    scan = probes.total_scan(logs)
    assert scan["complete"] and scan["lines"] >= len(ps)
    assert set(scan["tools"]) == {"search_tools", "load_tool"}
    assert not (tmp_path / "clones" / "tool-failclosed-F1").exists()
    # nothing is left under the clone root, the "no entry" policy included
    assert not (tmp_path / "clones").exists() or not any((tmp_path / "clones").iterdir())


def test_cli_tools_probes(store, tmp_path, config, capsys):
    acl.sync(store, *config)  # the command line reads the real clock
    out = tmp_path / "runs"
    fp = tools.Tools(store).active_tool_index().fingerprint
    code = eval_cli.main(["tools-probes", "--store", str(store), "--per-family", "10",
                          "--index", fp,
                          "--clones", str(tmp_path / "clones"), "--directory", str(config[0]),
                          "--policy", str(config[1]), "--out", str(out)])
    text = capsys.readouterr().out
    assert code == 0, text
    d = next(out.glob("probes-tools-*"))
    summary = json.loads((d / "summary.json").read_text())
    assert summary["config"]["tool_index"] == fp
    assert summary["leak"]["total"]["n"] == 20 and summary["leak"]["total"]["leaks"] == 0
    assert summary["failclosed"]["total"]["n"] == 80
    assert summary["failclosed"]["total"]["passed"] == 80
    assert summary["logs"]["total"]["complete"]
    assert (d / "probes.md").read_text().startswith("# ACL probes: tools")
    assert tools_eval.CALLER == "user:auditor"


def test_cli_tools_probes_refuses_another_index(store, tmp_path, capsys):
    fp = tools.Tools(store).active_tool_index().fingerprint
    other = ("0" if fp[0] != "0" else "1") + fp[1:]
    code = eval_cli.main(["tools-probes", "--store", str(store), "--index", other,
                          "--out", str(tmp_path / "runs")])
    err = capsys.readouterr().err
    assert code == 2 and fp[:12] in err and "adr tools index" in err
    assert not (tmp_path / "runs").exists()
    code = eval_cli.main(["tools-probes", "--store", str(store), "--index", fp[:6],
                          "--out", str(tmp_path / "runs")])
    assert code == 2 and "at least" in capsys.readouterr().err
