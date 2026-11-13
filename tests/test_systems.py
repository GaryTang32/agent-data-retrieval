"""The system registry, the Phase 1 systems in the harness, and the retrieval track."""

import json
from pathlib import Path

import pytest

from adr_eval import runner, systems
from adr_eval.cli import main
from adr_eval.retrieval.fusion import _GRID, linear
from adr_eval.scoring import evidence_groups
from adr_eval.scoring.retrieval_metrics import ndcg_at_k
from tests.store.test_retrieval import fake_cache, fake_reranker

FIXTURES = Path(__file__).parent / "fixtures"
RECORDED = json.loads((FIXTURES / "baseline_rankings_mini.json").read_text())
P1 = ("p1-struct", "p1-struct-bc", "p1-struct-bc-rr")


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    """Fake embedding model and cross-encoder for the Phase 1 systems; records calls."""
    made = {"caches": [], "rerankers": []}

    def cache(config):
        c = fake_cache(Path(config["embedding_cache_dir"]))
        made["caches"].append(c)
        return c

    def reranker(config):
        r = fake_reranker()
        made["rerankers"].append(r)
        return r

    monkeypatch.setattr(systems, "make_embedding_cache", cache)
    monkeypatch.setattr(systems, "make_reranker", reranker)
    return made


@pytest.fixture
def config(tmp_path):
    cfg = runner.load_config()
    cfg.update(index_dir=str(tmp_path / "index"), store_dir=str(tmp_path / "store"),
               embedding_cache_dir=str(tmp_path / "emb"), cache_dir=str(tmp_path / "llm"))
    return cfg


@pytest.fixture(scope="module")
def mini():
    loaded = runner.load_checked_corpus("mini")
    items = runner.load_golden("mini", loaded)
    return loaded, items, evidence_groups.build_all(items, loaded.docs)


def build(name, mini, config, **kw):
    loaded, items, groups = mini
    return systems.build(name, "mini", loaded, items, groups, config, **kw)


def test_the_registry_names_every_system():
    assert systems.NAMES == ("baseline-rrf", "baseline-linear", *P1)
    with pytest.raises(runner.RunError, match="unknown system"):
        systems.build("nope", "mini", None, [], {}, {})


# -- baselines behind the registry ------------------------------------------------------


@pytest.mark.slow
@pytest.mark.parametrize("name", ["baseline-rrf", "baseline-linear"])
def test_baselines_through_the_registry_give_the_recorded_ranked_lists(name, mini, config):
    """Recorded with the code before the registry (tests/fixtures/baseline_rankings_mini.json)."""
    s = build(name, mini, config)
    assert s.fingerprint == RECORDED["fingerprint"]
    assert s.fingerprint == runner.expected_fingerprint(mini[0])
    assert s.w == (RECORDED["linear_w"] if name == "baseline-linear" else None)
    for item in mini[1]:
        got = [[c, sc] for c, sc in s.retrieve(item.question)]
        assert got == RECORDED["rankings"][item.id][name], item.id
    assert set(s.chunks) >= {c for r in RECORDED["rankings"].values() for c, _ in r[name]}


@pytest.mark.slow
def test_baseline_run_config_is_unchanged(mini, config):
    rrf_ = build("baseline-rrf", mini, config)
    lin = build("baseline-linear", mini, config)
    assert rrf_.source in ("built", "loaded") and lin.source == "loaded"
    assert rrf_.run_config() == {"fusion": "rrf", "rrf_k": 60, "channel_k": 100, "top_n": 10,
                                 "linear_w": None}
    assert lin.run_config() == {"fusion": "linear", "rrf_k": None, "channel_k": 100,
                                "top_n": 10, "linear_w": lin.w}


def test_a_lexical_only_baseline_is_bm25_over_the_baseline_chunks(mini, config, monkeypatch):
    from adr_eval.retrieval.dense import DenseIndex

    monkeypatch.setattr(DenseIndex, "build", lambda *a: pytest.fail("embedded"))
    monkeypatch.setattr(DenseIndex, "model_hash", lambda self: "f" * 64)
    s = build("baseline-linear", mini, config, lexical_only=True)
    assert s.run_config()["lexical_only"] is True and s.w is None
    assert s.fingerprint != runner.expected_fingerprint(mini[0])
    for item in mini[1]:
        assert s.retrieve(item.question) == s.bm25.search(item.question, k=10)


# -- Phase 1 systems --------------------------------------------------------------------


@pytest.mark.parametrize("name", P1)
def test_phase1_systems_have_their_settings(name, mini, config, fakes):
    s = build(name, mini, config)
    rc = s.run_config()
    want = {"p1-struct": (False, False), "p1-struct-bc": (True, False),
            "p1-struct-bc-rr": (True, True)}[name]
    assert (rc["prefix"], rc["rerank"]) == want
    assert rc["fusion"] == "linear" and rc["linear_w"] in _GRID and rc["lexical_only"] is False
    assert rc["w_bc"] == 0 if name == "p1-struct" else rc["w_bc"] in systems.W_BC_GRID
    assert rc["tuning"]["grid_w_bc"] == ([0] if name == "p1-struct" else [0, 1, 2, 3])
    assert rc["store_snapshot"] == s.index.snapshot and len(s.fingerprint) == 64
    for item in mini[1]:
        hits = s.retrieve(item.question)
        assert 0 < len(hits) <= 10 and all(c in s.chunks for c, _ in hits)
    if name == "p1-struct-bc-rr":
        assert fakes["rerankers"][-1]._scorer.calls


def test_the_three_phase1_fingerprints_differ(mini, config, fakes):
    prints = {build(n, mini, config).fingerprint for n in P1}
    assert len(prints) == 3


def test_tuning_takes_the_best_grid_point_with_ties_to_the_smallest(mini, config, fakes):
    s = build("p1-struct-bc", mini, config)
    loaded, items, groups = mini
    dev = [i for i in items if i.split == "dev" and i.evidence and i.qtype != "insufficient"]
    base = s.index.with_settings(w_bc=0)
    best = None
    for w_bc in (0, 1, 2, 3):
        idx = base.with_settings(w_bc=w_bc)
        for w in _GRID:
            score = sum(ndcg_at_k([idx.chunks[c] for c, _ in linear(
                idx.lexical_hits(i.question), idx.dense_hits(i.question), w, top=10)],
                groups[i.id], 10) for i in dev) / len(dev)
            if best is None or score > best[2] + 1e-12:
                best = (w_bc, w, score)
    assert (s.index.settings.w_bc, s.w) == best[:2]
    assert s.run_config()["tuning"]["best_ndcg@10"] == pytest.approx(best[2])


def test_tune_store_tie_rule(monkeypatch):
    """Every grid point scores the same: the smallest w_bc and the smallest w win."""

    class Flat:
        settings = type("S", (), {"w_bc": 0})()
        chunks: dict = {}
        dense = object()

        def with_settings(self, w_bc):
            return self

        def lexical_hits(self, q):
            return []

        def dense_hits(self, q):
            return []

    from adr_eval.models import Evidence

    items = [type("I", (), {"id": "x", "split": "dev", "qtype": "factoid", "question": "q",
                            "evidence": [Evidence(doc_id="d", char_start=0, char_end=1,
                                                  quote="a")]})()]
    w_bc, w, record = systems.tune_store(Flat(), items, {}, "t", (1, 2, 3))
    assert (w_bc, w) == (1, 0.0) and record["best_ndcg@10"] == 0.0


def test_the_store_is_ingested_once_like_adr_ingest(mini, config, fakes, tmp_path):
    from adr_store.cli import main as adr_main

    s = build("p1-struct", mini, config)
    path = Path(config["store_dir"]) / "mini"
    assert (path / "HEAD").is_file() and s.store_path == path
    assert adr_main(["ingest", "mini", "--store", str(tmp_path / "by-cli")]) == 0
    head = (path / "HEAD").read_text()
    assert head == (tmp_path / "by-cli" / "HEAD").read_text()
    assert (path / "compile" / f"{head.strip()}.json").is_file()
    store, how = systems.ensure_store("mini", mini[0], config)
    assert how == "loaded" and store.snapshot_id == head.strip()


def test_a_stale_store_is_ingested_again(mini, config, fakes):
    from adr_store.store import Store

    systems.ensure_store("mini", mini[0], config)
    path = Path(config["store_dir"]) / "mini"
    full = Store.open(path)
    partial = Store(path, None, {d: full._records[d] for d in full.doc_ids()[:2]})
    partial.commit()  # HEAD now names a snapshot with two documents
    store, how = systems.ensure_store("mini", mini[0], config)
    assert how == "ingested" and store.snapshot_id == full.snapshot_id


def test_a_store_whose_text_differs_from_the_corpus_is_refused(mini, config, fakes):
    """Same documents (doc ids are the raw bytes' hashes) but text extracted otherwise, as
    after a change to a corpus adapter: the store is stale, and as its files are addressed by
    doc id it cannot take the new text in place, so it is refused like a store from another
    parser (remove it and it is ingested again)."""
    import shutil
    from dataclasses import replace

    loaded = mini[0]
    first, _ = systems.ensure_store("mini", loaded, config)
    doc_id = first.doc_ids()[0]
    changed = replace(loaded, docs={**loaded.docs, doc_id: replace(
        loaded.docs[doc_id], text=loaded.docs[doc_id].text + "\n")})
    with pytest.raises(runner.RunError, match=f"(?s)1 document.*{doc_id[:12]}.*remove"):
        systems.ensure_store("mini", changed, config)
    shutil.rmtree(first.path)
    store, how = systems.ensure_store("mini", changed, config)
    assert how == "ingested" and store.snapshot_id != first.snapshot_id
    assert store.text(doc_id) == changed.docs[doc_id].text
    assert systems.ensure_store("mini", changed, config)[1] == "loaded"


def test_a_store_from_another_parser_is_refused(mini, config, fakes, monkeypatch):
    systems.ensure_store("mini", mini[0], config)
    monkeypatch.setattr("adr_store.structure.PARSER", "adr_store.structure/0")
    with pytest.raises(runner.RunError, match="remove"):
        systems.ensure_store("mini", mini[0], config)


def test_the_saved_store_index_is_loaded_and_checked(mini, config, fakes):
    first = build("p1-struct-bc", mini, config)
    again = build("p1-struct-bc", mini, config)
    assert (first.source, again.source) == ("built", "loaded")
    assert again.fingerprint == first.fingerprint
    for item in mini[1]:
        assert again.retrieve(item.question) == first.retrieve(item.question)
    meta = Path(config["index_dir"]) / "mini-store-prefix" / "meta.json"
    data = json.loads(meta.read_text())
    meta.write_text(json.dumps({**data, "fingerprint": "0" * 64}))
    with pytest.raises(runner.RunError, match="--rebuild"):
        build("p1-struct-bc", mini, config)
    assert build("p1-struct-bc", mini, config, rebuild=True).source == "built"


def test_a_saved_index_that_load_refuses_is_a_run_error_through_the_cli(
        tmp_path, fakes, monkeypatch, capsys):
    """An edited chunk text keeps meta.json's fingerprint (so the quick staleness check
    passes) but fails load's recomputation: exit 2 with the fix, no traceback."""
    conftest_config = runner.load_config
    index_dir = tmp_path / "index"
    monkeypatch.setattr(runner, "load_config", lambda *a: {**conftest_config(*a),
                                                           "index_dir": str(index_dir)})
    args = ["retrieval", "mini", "--system", "p1-struct-bc", "--split", "test", "--out",
            str(tmp_path / "runs")]
    assert main(args) == 0
    chunks = index_dir / "mini-store-prefix" / "chunks.jsonl"
    rows = [json.loads(line) for line in chunks.read_text().splitlines()]
    rows[0]["text"] += " edited"
    chunks.write_text("".join(json.dumps(r) + "\n" for r in rows))
    capsys.readouterr()
    assert main(args) == 2
    err = capsys.readouterr().err
    assert "fingerprint mismatch" in err and "fix: rerun with --rebuild" in err
    assert "Traceback" not in err
    assert main([*args, "--rebuild"]) == 0


def test_an_index_replaced_between_check_and_load_is_a_run_error(mini, config, fakes,
                                                                 monkeypatch):
    """Another run may save a different index after the staleness check; the loaded index
    must still be the expected one."""
    from adr_store.retrieval import StoreIndex

    build("p1-struct-bc", mini, config)
    real = StoreIndex.load.__func__

    def load(cls, dir, **kw):
        idx = real(cls, dir, **kw)
        idx.fingerprint = "f" * 64
        return idx

    monkeypatch.setattr(StoreIndex, "load", classmethod(load))
    with pytest.raises(runner.RunError, match="--rebuild"):
        build("p1-struct-bc", mini, config)


@pytest.mark.parametrize("change", ["breadcrumb", "version"])
def test_an_index_saved_before_a_chunker_change_is_refused_then_rebuilt_from_the_cache(
        change, mini, config, fakes, monkeypatch):
    """The fingerprint covers what the chunks hold: a saved index from before a breadcrumb
    change (or a CHUNKER_VERSION bump) is stale; rebuilding it embeds nothing new when the
    embedded texts are unchanged (p1-struct embeds the body alone)."""
    from adr_store import chunking

    first = build("p1-struct", mini, config)
    assert first.source == "built" and first.index.dense.n_new > 0
    if change == "breadcrumb":
        real = chunking.breadcrumb
        monkeypatch.setattr(chunking, "breadcrumb",
                            lambda title, path: "Z > " + real(title, path))
    else:
        monkeypatch.setattr(chunking, "CHUNKER_VERSION", chunking.CHUNKER_VERSION + 1)
    with pytest.raises(runner.RunError, match="--rebuild"):
        build("p1-struct", mini, config)
    again = build("p1-struct", mini, config, rebuild=True)
    assert again.source == "built" and again.fingerprint != first.fingerprint
    assert again.index.dense.n_new == 0
    assert build("p1-struct", mini, config).source == "loaded"


def test_a_lexical_only_phase1_system_embeds_nothing(mini, config, fakes):
    full = build("p1-struct", mini, config)
    n_calls = sum(len(c._model.passage.calls) for c in fakes["caches"])
    lex = build("p1-struct", mini, config, lexical_only=True)
    assert sum(len(c._model.passage.calls) for c in fakes["caches"]) == n_calls
    assert lex.fingerprint != full.fingerprint and lex.run_config()["lexical_only"] is True
    assert lex.run_config()["fusion"] is None and lex.w is None
    for item in mini[1]:
        assert lex.retrieve(item.question) == lex.index.lexical_hits(item.question)[:10]


def test_rerank_top_comes_from_the_reranker_module(mini, config, fakes, monkeypatch):
    monkeypatch.setattr("adr_store.retrieval.rerank.RERANK_TOP", 7)
    assert build("p1-struct-bc-rr", mini, config).run_config()["rerank_top"] == 7
    assert build("p1-struct-bc", mini, config).run_config()["rerank_top"] is None


def test_a_reranker_model_that_cannot_be_loaded_is_a_run_error(tmp_path, fakes, monkeypatch,
                                                               capsys):
    from adr_store.retrieval import rerank

    def offline(model_name, cache_dir):
        raise ValueError("Could not load model from any source")

    monkeypatch.setattr(rerank, "load_cross_encoder", offline)
    monkeypatch.setattr(systems, "make_reranker", lambda config: rerank.CrossEncoderReranker(
        model_cache_dir=tmp_path / "no-models"))
    assert main(["retrieval", "mini", "--system", "p1-struct-bc-rr", "--split", "test",
                 "--out", str(tmp_path / "runs")]) == 2
    err = capsys.readouterr().err
    assert "Xenova/ms-marco-MiniLM-L-6-v2" in err and "not available offline" in err
    assert "run once online or drop the reranked system" in err
    assert "Traceback" not in err


# -- `adr-eval run` and the retrieval track ---------------------------------------------


def _forbid_model_clients(monkeypatch):
    import adr_eval.llm as llm

    def boom(*a, **kw):
        raise AssertionError("a model client was created")

    for name in ("AnthropicClient", "ClaudeCodeClient", "OpenAICompatibleClient",
                 "StubClient"):
        monkeypatch.setattr(getattr(llm, name), "__init__", boom)
    for name in ("make_client", "_role_clients", "stub_clients"):
        monkeypatch.setattr(runner, name, boom)


@pytest.mark.parametrize("name", P1)
def test_run_accepts_every_phase1_system(name, tmp_path, fakes, capsys):
    assert main(["run", "mini", "--system", name, "--split", "test", "--dry-run",
                 "--repeats", "1"]) == 0
    assert "dry run" in capsys.readouterr().out
    assert main(["run", "mini", "--system", name, "--split", "test", "--stub", "--repeats",
                 "1", "--out", str(tmp_path / "runs")]) == 0
    run_dir = next((tmp_path / "runs").iterdir())
    cfg = json.loads((run_dir / "config.json").read_text())
    assert cfg["system"] == name and cfg["retrieval"]["w_bc"] in systems.W_BC_GRID
    assert cfg["retrieval"]["prefix"] is (name != "p1-struct")
    assert cfg["w"] == cfg["retrieval"]["linear_w"] and len(cfg["fingerprint"]) == 64
    assert json.loads((run_dir / "compile.json").read_text())["fingerprint"] == cfg["fingerprint"]


def _retrieval(tmp_path, name, split="test", *extra) -> dict:
    out = tmp_path / "runs"
    assert main(["retrieval", "mini", "--system", name, "--split", split, "--out", str(out),
                 *extra]) == 0
    run_dir = sorted(out.iterdir(), key=lambda d: d.stat().st_mtime)[-1]
    assert (run_dir / "retrieval.md").read_text().startswith("# Retrieval: ")
    return json.loads((run_dir / "retrieval.json").read_text()) | {"dir": run_dir}


def test_the_retrieval_track_makes_no_model_client_and_writes_its_files(tmp_path, fakes,
                                                                        monkeypatch, capsys):
    _forbid_model_clients(monkeypatch)
    data = _retrieval(tmp_path, "p1-struct-bc-rr")
    assert "nDCG@10" in capsys.readouterr().out
    cfg = data["config"]
    assert cfg["system"] == "p1-struct-bc-rr" and cfg["metrics_version"] == 2
    assert cfg["track"] == "retrieval" and cfg["split"] == "test" and cfg["n_items"] == 7
    assert cfg["settings"]["rerank"] is True and len(cfg["fingerprint"]) == 64
    assert cfg["snapshot"] == runner.load_checked_corpus("mini").manifest.snapshot()
    assert cfg["settings"]["store_snapshot"] and cfg["wall_clock_s"] >= 0
    rows = {r["item_id"]: r for r in data["rows"]}
    assert set(rows) == {i.id for i in runner.load_golden(
        "mini", runner.load_checked_corpus("mini")) if i.split == "test"}
    assert rows["mini-insufficient-1"]["metrics"] is None
    r = rows["mini-factoid-1"]
    assert {"item_id", "qtype", "rarity", "ranked", "metrics"} <= set(r)
    assert {"recall@10", "ndcg@10", "mrr", "coverage@10", "tokens@10"} <= set(r["metrics"])
    pooled = data["summary"]["pooled"]
    assert pooled["n"] == 6 and pooled["ci"]["ndcg@10"]["n"] == 6
    tokens = pooled["ci"]["tokens@10"]
    assert tokens["n"] == 6 and tokens["mean"] == pytest.approx(pooled["tokens@10"])
    assert tokens["ci95"][0] <= pooled["tokens@10"] <= tokens["ci95"][1]
    for stratum in (*data["summary"]["by_rarity"].values(),
                    *data["summary"]["by_qtype"].values()):
        assert set(stratum["ci"]) == {"recall@10", "ndcg@10", "mrr", "coverage@10",
                                      "tokens@10"}
    md = (data["dir"] / "retrieval.md").read_text()
    pooled_row = next(line for line in md.splitlines() if line.startswith("| pooled |"))
    lo, hi = tokens["ci95"]
    assert f"{pooled['tokens@10']:.1f} [{lo:.1f}, {hi:.1f}]" in pooled_row
    assert set(data["summary"]) == {"pooled", "by_rarity", "by_qtype", "by_rarity_qtype"}


@pytest.mark.slow
def test_the_retrieval_track_of_a_baseline_makes_no_model_client(tmp_path, monkeypatch):
    _forbid_model_clients(monkeypatch)
    data = _retrieval(tmp_path, "baseline-linear")
    assert data["config"]["settings"]["fusion"] == "linear"
    assert data["config"]["fingerprint"] == RECORDED["fingerprint"]
    rows = {r["item_id"]: r for r in data["rows"]}
    for item_id, row in rows.items():
        assert row["ranked"] == [c for c, _ in RECORDED["rankings"][item_id]["baseline-linear"]]


def test_retrieval_compare_gives_paired_holm_corrected_differences(tmp_path, fakes, capsys):
    a = _retrieval(tmp_path, "p1-struct")
    b = _retrieval(tmp_path, "p1-struct-bc")
    capsys.readouterr()
    assert main(["retrieval-compare", a["dir"].name, b["dir"].name,
                 "--out", str(tmp_path / "runs")]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Retrieval comparison: p1-struct-bc minus p1-struct\n")
    assert "Warning" not in out
    c = json.loads((a["dir"] / f"compare-{b['dir'].name}.json").read_text())
    assert set(c["metrics"]) == {"recall@10", "ndcg@10", "mrr", "coverage@10"}
    assert c["n_pairs"] == 6 and c["difference"] == "run_b - run_a"
    assert (c["lexical_only_a"], c["lexical_only_b"]) == (False, False)
    for m in c["metrics"].values():
        assert m["p_holm"] >= m["p"] and m["mean_diff"] == pytest.approx(m["b"] - m["a"])


def test_retrieval_compare_carries_lexical_only_and_refuses_mixed_runs(tmp_path, fakes,
                                                                        capsys):
    a = _retrieval(tmp_path, "p1-struct")
    b = _retrieval(tmp_path, "p1-struct-bc", "test", "--lexical-only")
    c = _retrieval(tmp_path, "p1-struct", "test", "--lexical-only")
    out = str(tmp_path / "runs")
    capsys.readouterr()
    assert main(["retrieval-compare", a["dir"].name, b["dir"].name, "--out", out]) == 2
    err = capsys.readouterr().err
    assert "lexical-only" in err and "--allow-mixed" in err
    assert not (a["dir"] / f"compare-{b['dir'].name}.json").exists()
    assert main(["retrieval-compare", a["dir"].name, b["dir"].name, "--out", out,
                 "--allow-mixed"]) == 0
    md = capsys.readouterr().out
    first, heading = [line for line in md.splitlines() if line][:2]
    assert first.startswith("> **Warning:**") and "lexical-only" in first
    assert heading == "# Retrieval comparison: p1-struct-bc (lexical only) minus p1-struct"
    data = json.loads((a["dir"] / f"compare-{b['dir'].name}.json").read_text())
    assert (data["lexical_only_a"], data["lexical_only_b"]) == (False, True)
    assert data["allow_mixed"] is True
    assert main(["retrieval-compare", c["dir"].name, b["dir"].name, "--out", out]) == 0
    md = capsys.readouterr().out
    assert md.startswith("# Retrieval comparison: p1-struct-bc (lexical only) minus "
                         "p1-struct (lexical only)\n") and "Warning" not in md


def test_retrieval_compare_refuses_runs_on_other_golden_sets(tmp_path, fakes, capsys):
    a = _retrieval(tmp_path, "p1-struct")
    b = _retrieval(tmp_path, "p1-struct-bc")
    path = b["dir"] / "retrieval.json"
    data = json.loads(path.read_text())
    data["config"]["golden_sha256"] = "0" * 64
    path.write_text(json.dumps(data))
    capsys.readouterr()
    assert main(["retrieval-compare", a["dir"].name, b["dir"].name,
                 "--out", str(tmp_path / "runs")]) == 2
    assert "golden" in capsys.readouterr().err


def test_retrieval_compare_refuses_other_metrics_versions_and_splits(tmp_path, fakes, capsys):
    a = _retrieval(tmp_path, "p1-struct")
    b = _retrieval(tmp_path, "p1-struct", "dev")
    out = str(tmp_path / "runs")
    assert main(["retrieval-compare", a["dir"].name, b["dir"].name, "--out", out]) == 2
    assert "different splits" in capsys.readouterr().err
    c = _retrieval(tmp_path, "p1-struct")
    path = c["dir"] / "retrieval.json"
    data = json.loads(path.read_text())
    data["config"]["metrics_version"] = 1
    path.write_text(json.dumps(data))
    assert main(["retrieval-compare", a["dir"].name, c["dir"].name, "--out", out]) == 2
    assert "different metrics versions" in capsys.readouterr().err
    assert main(["retrieval-compare", a["dir"].name, "nope", "--out", out]) == 2
