"""B1 through MCP (Phase 2 spec §10.2, §12 MCP; plan Task 13 step 1): the seeded selection of
the leak probes (`adr_eval.probes.mcp`), the run through `adr mcp` servers of each caller on
the fixture store of `tests/store/test_handles.py` (content and tool catalog in one store,
lexical-only indexes), and `adr-eval mcp-probes`. No model is loaded (`HF_HUB_OFFLINE=1`)."""

import hashlib
import json

import pytest

pytest.importorskip("mcp")

from adr_eval.cli import main  # noqa: E402
from adr_eval.probes import SEED  # noqa: E402
from adr_eval.probes import acl as probes_acl  # noqa: E402
from adr_eval.probes import equivalence as eq  # noqa: E402
from adr_eval.probes import mcp as probes_mcp  # noqa: E402
from adr_store import acl, tools  # noqa: E402
from adr_store.mcp_client import McpTools  # noqa: E402
from tests.store.test_handles import build  # noqa: E402
from tests.store.test_permissions import REPO, fixed  # noqa: E402

ENV = {"HF_HUB_OFFLINE": "1"}
SMALL = {"search-rare": 6, "search-title": 4, "grep-literal": 4, "grep-doc": 4, "read": 8}
TOOL_SMALL = {"tool-search": 8, "tool-load": 8}


def probe(pid: str, family: str = "read") -> probes_acl.Probe:
    return probes_acl.Probe(pid, family, "read", "user:a", {}, {"doc_id": "x"})


# -- selection -----------------------------------------------------------------------------------


def test_the_selection_is_the_lowest_seeded_hashes_of_the_global_ids():
    universe = [(label, probe(f"read:{k:03d}")) for label in ("gov", "bench")
                for k in range(50)]
    chosen = probes_mcp.select(universe, 10)
    keys = sorted(hashlib.sha256(f"{SEED}:{lb}/{p.probe_id}".encode()).hexdigest()
                  for lb, p in universe)
    assert [probes_mcp.sample_key(lb, p.probe_id) for lb, p in chosen] == keys[:10]
    assert chosen == probes_mcp.select(list(reversed(universe)), 10)  # order-free
    assert probes_mcp.select(universe, 10, seed=1) != chosen
    with pytest.raises(ValueError, match="global id"):
        probes_mcp.select(universe + universe[:1], 10)


def test_family_counts_and_short_families_are_reported_not_forced():
    universe = [("gov", probe(f"read:{k:03d}")) for k in range(30)] + \
        [("tools", probe(f"tool-load:{k:03d}", "tool-load")) for k in range(5)] + \
        [("gov", probe(f"grep-doc:{k:03d}", "grep-doc")) for k in range(25)]
    counts = probes_mcp.family_counts(universe)
    assert counts["families"] == {"grep-doc": 25, "read": 30, "tool-load": 5}
    assert counts["spec_families"] == {"search": 0, "grep": 25, "read": 30,
                                       "search_tools/load_tool": 5}
    assert counts["stores"] == {"gov": 55, "tools": 5}
    assert probes_mcp.short_families(counts) == {"search": 0, "search_tools/load_tool": 5}


# -- through MCP ---------------------------------------------------------------------------------


@pytest.fixture
def built(tmp_path):
    return build(tmp_path / "store", tmp_path / "config", clock=acl.utc_now)


def test_the_selected_probes_pass_through_mcp_and_every_call_is_logged(built, tmp_path):
    store, config = built
    ctx = probes_acl.context(store.path, tools.Tools(store.path).active_index())
    tctx = probes_acl.tool_context(store.path, tools.Tools(store.path).active_tool_index())
    universe = [("gov", p) for p in probes_acl.leak_probes(ctx, sizes=SMALL)] + \
        [("tools", p) for p in probes_acl.tool_leak_probes(tctx, sizes=TOOL_SMALL)]
    selected = probes_mcp.select(universe, 30)
    assert {lb for lb, _ in selected} == {"gov", "tools"}
    refs = {}
    for v in eq.views(acl.read_head(store.path)[1]):
        path = tmp_path / "views" / v.view[:12]
        eq.ensure_view_store(store, v.docs, path, emb_cache=tmp_path / "emb",
                             directory=config[0], policy=config[1], clock=fixed())
        refs.update(dict.fromkeys(v.users, path))
    log = probes_acl.log_path(store.path)
    offset = probes_acl.log_size(log)
    started = []

    def make_server(label, caller):
        started.append((label, caller))
        return McpTools(store.path, caller, emb_cache=tmp_path / "emb", env=ENV, cwd=REPO)

    def reference_for(label, caller):
        assert label == "gov"
        return None if caller not in refs else tools.Tools(refs[caller], acl=True,
                                                           caller=caller, clock=fixed())

    results, calls = probes_mcp.run_subset(selected, contexts={"gov": ctx, "tools": tctx},
                                           reference_for=reference_for,
                                           make_server=make_server)
    assert [r.probe_id for _, r in results] == [p.probe_id for _, p in selected]
    assert len(started) == len(set(started)) == len({(lb, p.caller) for lb, p in selected})
    s = probes_mcp.summarize(results)
    assert s["total"]["n"] == 30 and s["total"]["leaks"] == 0 and s["total"]["invalid"] == 0, \
        [r for _, r in results if r.leak or not r.valid][:3]
    assert s["stores"]["gov"]["n"] + s["stores"]["tools"]["n"] == 30
    scan = probes_acl.scan_log(log, offset)
    n_calls = sum(sum(c.values()) for c in calls.values())
    assert scan["lines"] == n_calls >= 30  # every MCP call reached Tools and was logged
    assert probes_acl.total_scan({"s": scan})["complete"]


def test_the_cli_writes_the_subset_run_and_its_selection_is_stable(built, tmp_path, capsys):
    store, config = built
    fp = tools.Tools(store.path).active_tool_index().fingerprint
    out = tmp_path / "runs"
    args = ["mcp-probes", "--store", f"gov={store.path}", "--store", f"tools={store.path}",
            "--tool-index", fp[:12], "--allow-other-index", "--per-family", "4", "--n", "12",
            "--directory", str(config[0]), "--policy", str(config[1]),
            "--views", str(tmp_path / "views"), "--emb-cache", str(tmp_path / "emb"),
            "--out", str(out)]
    assert main(args) == 0
    assert "Total: 12 probes, 0 leaks, 0 invalid" in capsys.readouterr().out
    assert not (tmp_path / "views" / "gov").exists()  # reference stores removed
    (d,) = out.glob("probes-mcp-*")
    summary = json.loads((d / "summary.json").read_text())
    assert summary["config"]["universe"] == 4 * 5 + 4 * 2 + summary["config"]["counts"][
        "universe"]["families"].get("alternate-cross-view", 0)
    assert summary["logs"]["mcp"]["total"]["complete"]
    assert summary["logs"]["mcp"]["total"]["lines"] == summary["logs"]["mcp"]["calls_total"]
    sel = json.loads((d / "probes.json").read_text())["selected"]
    assert [x["key"] for x in sel] == sorted(x["key"] for x in sel) and len(sel) == 12
    assert main(["mcp-probes", "--store", f"gov={store.path}", "--allow-other-index",
                 "--store", f"tools={store.path}", "--tool-index", "deadbeefdead",
                 "--out", str(out)]) == 2
    assert "active tool index" in capsys.readouterr().err
