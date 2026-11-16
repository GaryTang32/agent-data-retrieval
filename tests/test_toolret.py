"""The ToolRet `toolbench` corpus: download at pinned revisions, tools, queries, splits and
the tools-only store (Phase 2 spec §8.3; §12 Tools). Built from the synthetic
`tests/fixtures/tools/toolret_sample.jsonl` (ToolRet's shape, no ToolRet text)."""

import hashlib
import json
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from adr_eval import cli as eval_cli
from adr_eval.corpora import toolret
from adr_eval.corpora.base import HashMismatch
from adr_eval.corpora.http import PoliteFetcher
from adr_eval.retrieval.chunker import _count
from adr_store import cli, tool_records
from adr_store.store import Store
from adr_store.tool_catalog import ToolCatalog

REPO = Path(__file__).parents[1]
SAMPLE = REPO / "tests" / "fixtures" / "tools" / "toolret_sample.jsonl"
TOOL_IDS = ["toolbench_tool_0", "toolbench_tool_1", "toolbench_tool_10", "toolbench_tool_2",
            "toolbench_tool_3", "toolbench_tool_4"]


def _rows(table: str) -> list[dict]:
    lines = [json.loads(x) for x in SAMPLE.read_text(encoding="utf-8").splitlines()]
    return [x["row"] for x in lines if x["table"] == table]


def _parquet(rows: list[dict]) -> bytes:
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist(rows), sink)
    return sink.getvalue().to_pybytes()


@pytest.fixture
def blobs() -> dict[str, bytes]:
    return {"tools": _parquet(_rows("tools")), "queries": _parquet(_rows("queries"))}


def _config(blobs: dict[str, bytes]) -> dict:
    cfg = json.loads((REPO / "corpora" / "tools" / "config.json").read_text(encoding="utf-8"))
    for key, data in blobs.items():
        cfg["files"][key]["sha256"] = hashlib.sha256(data).hexdigest()
        cfg["files"][key]["bytes"] = len(data)
    return cfg


@pytest.fixture
def config_path(tmp_path, blobs) -> Path:
    p = tmp_path / "config.json"
    p.write_text(json.dumps(_config(blobs)))
    return p


@pytest.fixture
def root(tmp_path, blobs, config_path) -> Path:
    cfg = json.loads(config_path.read_text())
    r = tmp_path / "data-tools"
    for key, data in blobs.items():
        dest = r / cfg["files"][key]["local"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    return r


def _mock_fetcher(blobs, calls):
    cfg = _config(blobs)
    by_url = {toolret.file_url(cfg["files"][k]): data for k, data in blobs.items()}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url) not in by_url:
            return httpx.Response(404)
        return httpx.Response(200, content=by_url[str(request.url)])

    return PoliteFetcher(transport=httpx.MockTransport(handler), sleep=lambda s: None)


# -- the committed config -------------------------------------------------------------------

def test_committed_config_pins_the_spec_revisions():
    cfg = toolret.load_config()
    t, q = cfg["files"]["tools"], cfg["files"]["queries"]
    assert t["repo"] == "mangopy/ToolRet-Tools" and t["config"] == "web"
    assert t["revision"] == "e06c38c75612b6536bd959e08cdd345894aba6a7"
    assert q["repo"] == "mangopy/ToolRet-Queries" and q["config"] == "toolbench"
    assert q["revision"] == "b8c76ad3349ff17497b6bdb28bb5b8f61a0f6445"
    assert toolret.file_url(t) == (
        "https://huggingface.co/datasets/mangopy/ToolRet-Tools/resolve/"
        "e06c38c75612b6536bd959e08cdd345894aba6a7/" + t["path"])
    assert all(len(f["sha256"]) == 64 for f in cfg["files"].values())
    assert cfg["tool_prefix"] == "toolbench_tool_"


# -- splits -----------------------------------------------------------------------------------

def test_split_assignment_is_fixed():
    for qid in ("toolbench_query_1", "toolbench_query_808", "toolbench_query_18"):
        want = "dev" if int(hashlib.sha256(qid.encode()).hexdigest(), 16) % 5 == 0 else "test"
        assert toolret.split_of(qid) == want
    assert toolret.split_of("toolbench_query_18") == "dev"
    assert toolret.split_of("toolbench_query_1") == "test"


# -- reading ----------------------------------------------------------------------------------

def test_tools_keeps_the_toolbench_tools_sorted(root, config_path):
    rows = toolret.tools(root, config_path)
    assert [r["id"] for r in rows] == TOOL_IDS
    assert all(isinstance(r["documentation"], str) for r in rows)


def test_queries_gold_and_split(root, config_path):
    qs = toolret.queries(root, config_path)
    assert [q.id for q in qs] == sorted(q["id"] for q in _rows("queries"))
    q3 = next(q for q in qs if q.id == "toolbench_query_3")
    assert q3.gold == ("toolbench_tool_10", "toolbench_tool_3")  # label order, deduplicated
    assert q3.query.startswith("Which stations")
    assert {q.id: q.split for q in qs}["toolbench_query_18"] == "dev"
    assert all(q.split == toolret.split_of(q.id) for q in qs)


def test_reading_verifies_the_pinned_hashes(root, config_path):
    cfg = json.loads(config_path.read_text())
    (root / cfg["files"]["tools"]["local"]).write_bytes(b"not parquet")
    with pytest.raises(HashMismatch):
        toolret.tools(root, config_path)


def test_missing_files_name_the_fetch_command(tmp_path, config_path):
    with pytest.raises(toolret.ToolRetMissing, match="adr-eval tools-fetch"):
        toolret.queries(tmp_path / "empty", config_path)


def test_stats(root, config_path):
    s = toolret.stats(root, config_path)
    toks = [_count(r["documentation"]) for r in _rows("tools") if r["id"] in TOOL_IDS]
    assert s["tools"] == 6 and s["queries"] == 6
    assert s["gold_total"] == 2 + 1 + 2 + 1 + 1 + 2 and s["gold_missing"] == 0
    assert s["doc_tokens"] == sum(toks)
    assert s["dev"] == 1 and s["test"] == 5


# -- fetching ---------------------------------------------------------------------------------

def test_fetch_downloads_verifies_and_writes_the_manifest(tmp_path, blobs, config_path):
    calls: list[str] = []
    manifest = tmp_path / "manifest.json"
    out = toolret.fetch(tmp_path / "d", config_path, manifest,
                        fetcher=_mock_fetcher(blobs, calls))
    assert len(calls) == 2
    written = json.loads(manifest.read_text())
    assert written == out
    files = {f["name"]: f for f in written["files"]}
    assert files["tools"]["sha256"] == hashlib.sha256(blobs["tools"]).hexdigest()
    assert files["queries"]["bytes"] == len(blobs["queries"])
    assert written["counts"]["tools"] == 6
    first = manifest.read_bytes()
    toolret.fetch(tmp_path / "d", config_path, manifest, fetcher=_mock_fetcher(blobs, calls))
    assert len(calls) == 2  # present and verified: no request
    assert manifest.read_bytes() == first  # deterministic, no timestamps


def test_fetch_refuses_a_hash_mismatch(tmp_path, blobs, config_path):
    cfg = json.loads(config_path.read_text())
    cfg["files"]["queries"]["sha256"] = "0" * 64
    config_path.write_text(json.dumps(cfg))
    with pytest.raises(HashMismatch):
        toolret.fetch(tmp_path / "d", config_path, tmp_path / "m.json",
                      fetcher=_mock_fetcher(blobs, []))
    assert not (tmp_path / "m.json").exists()


def test_cli_tools_fetch(tmp_path, blobs, config_path, monkeypatch, capsys):
    calls: list[str] = []
    monkeypatch.setattr(toolret, "CONFIG_PATH", config_path)
    monkeypatch.setattr(toolret, "MANIFEST_PATH", tmp_path / "manifest.json")
    monkeypatch.setattr(toolret, "make_fetcher", lambda: _mock_fetcher(blobs, calls))
    code = eval_cli.main(["tools-fetch"])
    out = capsys.readouterr().out
    assert code == 0 and "6 tools" in out and "6 queries" in out
    assert (toolret.DATA_DIR / json.loads(config_path.read_text())["files"]["tools"]["local"]
            ).is_file()
    assert (tmp_path / "manifest.json").is_file()


def test_default_data_dir_is_redirected_in_tests():
    assert REPO not in Path(toolret.DATA_DIR).resolve().parents


# -- the tools-only store ---------------------------------------------------------------------

def test_cli_ingest_toolret_twice_gives_the_same_snapshot(root, config_path, monkeypatch,
                                                         capsys, tmp_path):
    monkeypatch.setattr(toolret, "CONFIG_PATH", config_path)
    store = tmp_path / "toolret"
    args = ["tools", "ingest", "--toolret", "--root", str(root), "--store", str(store),
            "--json"]
    assert cli.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["tools"] == 6 and first["conformance"] == 1.0
    assert cli.main(args) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["tool_snapshot"] == first["tool_snapshot"]
    assert Store.open(store).doc_ids() == []
    cat = ToolCatalog.open(store)
    rev = json.loads(config_path.read_text())["files"]["tools"]["revision"]
    uri = tool_records.toolret_uri("mangopy/ToolRet-Tools", rev, "web", "toolbench_tool_2")
    rec = next(cat.get(t) for t in cat.ids() if cat.get(t).source_uri == uri)
    assert rec.name == "Ledgerly_Convert_Currency" and rec.source_version == rev
    assert rec.license == json.loads(config_path.read_text())["license"]


def test_default_tool_store_is_redirected_in_tests():
    assert REPO not in Path(cli.TOOL_STORE).resolve().parents


def test_cli_ingest_toolret_malformed_row_is_an_error(tmp_path, blobs, monkeypatch, capsys):
    bad = _rows("tools") + [{"id": "toolbench_tool_99",
                             "documentation": json.dumps({"name": None, "description": "d"})}]
    blobs = {**blobs, "tools": _parquet(bad)}
    cfg = _config(blobs)
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg))
    root = tmp_path / "bad-root"
    for key, data in blobs.items():
        (root / cfg["files"][key]["local"]).parent.mkdir(parents=True, exist_ok=True)
        (root / cfg["files"][key]["local"]).write_bytes(data)
    monkeypatch.setattr(toolret, "CONFIG_PATH", cfg_path)
    code = cli.main(["tools", "ingest", "--toolret", "--root", str(root), "--store",
                     str(tmp_path / "s")])
    err = capsys.readouterr().err
    assert code == 2 and "toolbench_tool_99" in err and "unexpected" not in err
    assert not (tmp_path / "s" / "tools" / "HEAD").exists()
