"""The tool-retrieval harness (Phase 2 spec §8.4, §10.1; plan Task 10): per-query metrics on
hand-made rankings, tuning ties, the raw-documentation baseline, tool context and the runs of
`adr-eval tools-retrieval` on a tools-only store built from the synthetic ToolRet sample
(lexical-only, or the fake embedder); nothing reads `data/` or `.cache/`."""

import json
import math

import pytest

from adr_eval import cli as eval_cli
from adr_eval import tools_eval
from adr_eval.corpora import toolret
from adr_eval.retrieval.chunker import Chunk, _count
from adr_eval.retrieval.lexical import BM25Index
from adr_store import acl, cli, tool_records, tools
from adr_store.tool_catalog import ToolCatalog
from tests.store.test_retrieval import fake_cache
from tests.test_toolret import blobs, config_path, root  # noqa: F401  (fixtures)


@pytest.fixture
def store(tmp_path, root, config_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(toolret, "CONFIG_PATH", config_path)
    path = tmp_path / "toolret"
    assert cli.main(["tools", "ingest", "--toolret", "--root", str(root), "--store",
                     str(path)]) == 0
    acl.sync(path)
    return path


@pytest.fixture
def fake_models(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "make_embedding_cache",
                        lambda path=None, *, threads=1: fake_cache(tmp_path / "emb"))


# -- metrics -------------------------------------------------------------------------------------

def test_metrics_on_hand_made_rankings():
    gold = ["a", "b"]
    assert tools_eval.completeness(["a", "x", "b"], gold) == 1.0
    assert tools_eval.completeness(["a", "x"], gold) == 0.0
    assert tools_eval.completeness(["x"] * 9 + ["b", "a"], gold) == 0.0  # a is 11th
    assert tools_eval.recall(["a", "x"], gold) == 0.5
    assert tools_eval.recall([f"x{i}" for i in range(10)] + ["a"], gold) == 0.0
    ideal = 1 + 1 / math.log2(3)
    assert tools_eval.ndcg(["a", "b"], gold) == pytest.approx(1.0)
    assert tools_eval.ndcg(["x", "a"], gold) == pytest.approx((1 / math.log2(3)) / ideal)
    assert tools_eval.ndcg(["x", "b", "x2", "a"], gold) == pytest.approx(
        (1 / math.log2(3) + 1 / math.log2(5)) / ideal)
    assert tools_eval.ndcg(["a"], ["a"]) == 1.0 and tools_eval.ndcg([], ["a"]) == 0.0
    many = [f"g{i}" for i in range(12)]  # ideal counts at most 10 gains
    assert tools_eval.ndcg(many[:10], many) == pytest.approx(1.0)
    assert tools_eval.recall(many[:10], many) == pytest.approx(10 / 12)


def test_metrics_of_an_empty_gold_list_are_refused():
    with pytest.raises(ValueError):
        tools_eval.recall(["a"], [])


def test_tuning_picks_the_best_and_ties_go_to_the_smallest_values():
    table = [{"w_name": 0, "w": 0.0, "ndcg@10": 0.5}, {"w_name": 0, "w": 0.3, "ndcg@10": 0.7},
             {"w_name": 1, "w": 0.1, "ndcg@10": 0.7}, {"w_name": 2, "w": 0.05, "ndcg@10": 0.6}]
    assert tools_eval.best(table) == {"w_name": 0, "w": 0.3, "ndcg@10": 0.7}
    table.append({"w_name": 0, "w": 0.2, "ndcg@10": 0.7 + 1e-15})  # within float noise: a tie
    assert tools_eval.best(table)["w"] == 0.2
    assert tools_eval.W_GRID[0] == 0.0 and tools_eval.W_GRID[-1] == 1.0
    assert len(tools_eval.W_GRID) == 21 and tools_eval.W_NAMES == (0, 1, 2, 3)


def test_toolret_id_of_a_source_uri():
    uri = tool_records.toolret_uri("mangopy/ToolRet-Tools", "abc", "web", "toolbench_tool_7")
    assert tools_eval.toolret_id(uri) == "toolbench_tool_7"
    with pytest.raises(ValueError):
        tools_eval.toolret_id("pypi:mcp-server-git@1")


# -- the raw-documentation baseline ---------------------------------------------------------------

def test_raw_bm25_is_bm25_over_the_documentation_strings(root, config_path):  # noqa: F811
    rows = toolret.tools(root, config_path)
    raw = tools_eval.RawBM25(rows)
    ref = BM25Index()
    ref.build([Chunk(r["id"], r["id"], 0, 0, r["documentation"]) for r in rows])
    for q in toolret.queries(root, config_path):
        assert raw.search(q.query, 10) == ref.search(q.query, k=10)
    assert raw.catalog_tokens == sum(_count(r["documentation"]) for r in rows)


# -- tool context -------------------------------------------------------------------------------

def test_tool_context_counts_the_page_and_the_definitions(store):
    t = tools.Tools(store)
    t.tools_index(1, lexical_only=True)
    res = t.search_tools("weather in Paris")
    loads = [t.load_tool(h.tool_id) for h in res.hits]
    gold = {res.hits[0].tool_id}
    cat = ToolCatalog.open(store)
    catalog = sum(cat.get(x).definition_tokens for x in cat.ids())
    ctx = tools_eval.tool_context(res, loads, gold, catalog)
    page = _count(tool_records.canonical(res.to_dict()))
    defs = [_count(tool_records.canonical(x.definition)) for x in loads]
    assert ctx["page"] == page and ctx["definitions"] == sum(defs)
    assert ctx["loaded"] == page + sum(defs) and ctx["catalog"] == catalog
    assert ctx["reduction"] == pytest.approx(1 - ctx["loaded"] / catalog)
    assert ctx["gold_share"] == pytest.approx(defs[0] / ctx["loaded"])
    assert ctx["gold_loaded"] == 1


# -- runs ---------------------------------------------------------------------------------------

def _run(system, split, store, root, *extra) -> dict:  # noqa: F811
    code = eval_cli.main(["tools-retrieval", "--system", system, "--split", split, "--store",
                          str(store), "--root", str(root), *extra])
    assert code == 0
    runs = sorted(tools_eval.OUT_ROOT.glob(f"tools-{system}-{split}-*"))
    rec = json.loads((runs[-1] / "tools.json").read_text())
    assert (runs[-1] / "tools.md").read_text().startswith("# Tool retrieval")
    return rec


def test_bm25_raw_run(store, root):  # noqa: F811
    rec = _run("tools-bm25-raw", "test", store, root)
    qs = [q for q in toolret.queries(root) if q.split == "test"]
    assert rec["config"]["system"] == "tools-bm25-raw" and len(rec["rows"]) == len(qs)
    raw = tools_eval.RawBM25(toolret.tools(root))
    for row, q in zip(rec["rows"], qs, strict=True):
        ranked = [i for i, _ in raw.search(q.query, 10)]
        assert row["id"] == q.id and row["ranked"] == ranked
        assert row["completeness@10"] == tools_eval.completeness(ranked, q.gold)
        assert row["recall@10"] == tools_eval.recall(ranked, q.gold)
        assert row["ndcg@10"] == tools_eval.ndcg(ranked, q.gold)
    s = rec["summary"]
    assert s["n"] == len(qs)
    assert s["completeness@10"] == pytest.approx(
        sum(r["completeness@10"] for r in rec["rows"]) / len(qs))


def test_bm25f_run_searches_as_the_auditor_through_search_tools(store, root):  # noqa: F811
    rec = _run("tools-bm25f", "test", store, root)
    cfg = rec["config"]
    assert cfg["caller"] == "user:auditor" and cfg["lexical_only"] is True
    assert cfg["w_name"] in tools_eval.W_NAMES and cfg["w"] is None
    assert [r["w_name"] for r in rec["tuning"]["table"]] == list(tools_eval.W_NAMES)
    assert cfg["acl_snapshot"] == acl.read_head(store)[0]
    assert cfg["tools_snapshot"] == ToolCatalog.open(store).snapshot_id
    assert cfg["active_tool_index"] == {"before": None, "after": cfg["fingerprint"]}
    runs = sorted(tools_eval.OUT_ROOT.glob("tools-tools-bm25f-test-*"))
    md = (runs[-1] / "tools.md").read_text()
    assert f"active tool index: none → {cfg['fingerprint'][:12]}" in md
    t = tools.Tools(store, acl=True, caller="user:auditor")
    qs = [q for q in toolret.queries(root) if q.split == "test"]
    for row, q in zip(rec["rows"], qs, strict=True):
        res = t.search_tools(q.query)
        assert row["tool_ids"] == [h.tool_id for h in res.hits]
        assert row["scores"] == [h.score for h in res.hits]
        assert row["ranked"] == [tools_eval.toolret_id(h.source_uri) for h in res.hits]
        c = row["context"]  # 8 tools: the page can outweigh the catalog (reduction < 0)
        assert c["loaded"] > 0 and c["reduction"] == pytest.approx(1 - c["loaded"] / c["catalog"])
    log = [json.loads(x) for x in (store / "log" / "retrieval.jsonl").read_text().splitlines()]
    assert {x["caller"] for x in log if x["tool"] in ("search_tools", "load_tool")} == {
        "user:auditor"}


def test_hybrid_run_tunes_both_weights_with_the_fake_embedder(store, root, fake_models):  # noqa: F811
    rec = _run("tools-hybrid", "dev", store, root)
    cfg = rec["config"]
    assert cfg["lexical_only"] is False and cfg["w"] in tools_eval.W_GRID
    assert len(rec["tuning"]["table"]) == len(tools_eval.W_NAMES) * len(tools_eval.W_GRID)
    best = tools_eval.best(rec["tuning"]["table"])
    assert (cfg["w_name"], cfg["w"]) == (best["w_name"], best["w"])
    assert tools.Tools(store).active_tool_index().fingerprint == cfg["fingerprint"]


def test_runs_are_identical_apart_from_their_start_time(store, root, capsys):  # noqa: F811
    a = _run("tools-bm25f", "dev", store, root)
    b = _run("tools-bm25f", "dev", store, root)
    fp = a["config"]["fingerprint"]
    assert b["config"]["active_tool_index"] == {"before": fp, "after": fp}
    assert f"active tool index: {fp[:12]} → {fp[:12]} (unchanged)" in capsys.readouterr().out
    assert a["rows"] == b["rows"] and a["summary"] == b["summary"]
    assert a["tuning"] == b["tuning"]


def test_a_denied_caller_is_an_error_naming_the_sync(store, root, capsys):  # noqa: F811
    (store / "acl" / "HEAD").unlink()
    code = eval_cli.main(["tools-retrieval", "--system", "tools-bm25f", "--split", "dev",
                          "--store", str(store), "--root", str(root)])
    assert code == 2 and "adr acl sync" in capsys.readouterr().err
    code = eval_cli.main(["tools-retrieval", "--system", "tools-bm25f", "--split", "dev",
                          "--store", str(store), "--root", str(root), "--sync"])
    assert code == 0


def test_the_markdown_defines_the_gold_share(store, root):  # noqa: F811
    _run("tools-bm25f", "dev", store, root)
    md = sorted(tools_eval.OUT_ROOT.glob("tools-tools-bm25f-dev-*"))[-1] / "tools.md"
    assert "mean over queries of the loaded gold definition tokens / loaded tokens" in \
        md.read_text()
    assert "page entries are not counted as gold" in " ".join(tools_eval.__doc__.split())


def test_out_root_is_redirected_in_tests():
    from pathlib import Path

    repo = Path(__file__).parents[1]
    assert repo not in Path(tools_eval.OUT_ROOT).resolve().parents
