import json
from pathlib import Path

import pytest

from adr_eval.cli import main
from adr_eval.llm import StubClient
from adr_eval.report import build_report, compare, render_markdown
from adr_eval.runner import RunError, load_config, run

MINI = Path(__file__).parent / "fixtures" / "mini"
ROW_KEYS = {
    "item_id", "repeat", "qtype", "rarity", "retrieved", "generated_query",
    "gold_query_field_hits", "query_exact", "query_exec_match", "answer", "outcome",
    "judge_label", "judge_reason", "tokens", "cost_usd", "latency_s", "error",
}


def _config(tmp_path: Path) -> dict:
    cfg = load_config()
    cfg.update(index_dir=str(tmp_path / "index"), cache_dir=str(tmp_path / "llm"),
               stub=True, concurrency=2)
    return cfg


def run_with_stub(tmp_path, fn=None, max_dollars=None, priced=False, system="baseline-rrf",
                  repeats=1, concurrency=2, **kw) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    cfg = {**_config(tmp_path), "concurrency": concurrency}
    if fn is not None:
        kw.update(generator=StubClient(fn), judge=StubClient(fn))
    if priced:
        prices = tmp_path / "prices.json"
        prices.write_text(json.dumps(
            {"stub": {"input_per_mtok": 1.0, "output_per_mtok": 1.0, "as_of": "2026-11-08"}}))
        cfg["prices"] = str(prices)
    run_id = run("mini", system, "test", repeats, cfg, out_root=tmp_path / "runs",
                 max_dollars=max_dollars, **kw)
    return tmp_path / "runs" / run_id


def _rows(run_dir: Path) -> list[dict]:
    return [json.loads(line) for line in (run_dir / "results.jsonl").read_text().splitlines()]


def _test_items() -> list[dict]:
    items = [json.loads(line) for line in (MINI / "golden.jsonl").read_text().splitlines()]
    return [i for i in items if i["split"] == "test"]


# -- runs with the embedding model ------------------------------------------------------


@pytest.mark.slow
def test_model_error_becomes_error_row(tmp_path):  # Review Focus 2
    run_dir = run_with_stub(tmp_path, fn=lambda s, u, r: "not json")
    rows = _rows(run_dir)
    assert rows and all(r["outcome"] == "error" for r in rows)
    assert all(r["error"] and r["answer"] is None for r in rows)
    assert json.loads((run_dir / "config.json").read_text())["status"] == "complete"


@pytest.mark.slow
def test_budget_stop_writes_status(tmp_path):
    run_dir = run_with_stub(tmp_path, max_dollars=0.0, priced=True)
    cfg = json.loads((run_dir / "config.json").read_text())
    assert cfg["status"] == "stopped_budget"
    assert _rows(run_dir) == []


@pytest.mark.slow
def test_unpriced_stub_costs_nothing_and_fits_zero_budget(tmp_path):
    run_dir = run_with_stub(tmp_path, max_dollars=0.0)
    cfg = json.loads((run_dir / "config.json").read_text())
    rows = _rows(run_dir)
    assert cfg["status"] == "complete" and rows
    assert all(r["cost_usd"] == 0.0 for r in rows)


@pytest.mark.slow
def test_stub_run_rows_sorted_complete_and_correct(tmp_path):
    run_dir = run_with_stub(tmp_path, repeats=2)
    rows = _rows(run_dir)
    items = _test_items()
    assert len(rows) == 2 * len(items)
    assert [(r["item_id"], r["repeat"]) for r in rows] == sorted(
        (i["id"], rep) for i in items for rep in range(2))
    assert all(ROW_KEYS <= set(r) for r in rows)
    assert {r["outcome"] for r in rows} == {"correct"}
    assert all(r["query_exact"] for r in rows)
    by_id = {r["item_id"]: r for r in rows if r["repeat"] == 0}
    assert by_id["mini-count-1"]["query_exec_match"] is True
    assert by_id["mini-factoid-1"]["query_exec_match"] is None
    assert by_id["mini-factoid-1"]["judge_label"] == "correct"
    assert by_id["mini-count-1"]["judge_label"] is None  # exact-scored
    assert all(len(r["retrieved"]) == 7 for r in rows)  # the mini corpus has 7 chunks
    cfg = json.loads((run_dir / "config.json").read_text())
    assert cfg["stub"] is True and cfg["status"] == "complete" and cfg["w"] is None
    assert cfg["same_family_judge"] is True and len(cfg["fingerprint"]) == 64
    assert set(cfg["prompt_hashes"]) == {"answer", "query_gen", "judge"}
    assert cfg["seed"] == 20261108
    assert cfg["golden"] == "tests/fixtures/mini/golden.jsonl"  # relative to the repo root
    import hashlib
    assert cfg["golden_sha256"] == hashlib.sha256(
        (MINI / "golden.jsonl").read_bytes()).hexdigest()
    assert cfg["retrieval"] == {"fusion": "rrf", "rrf_k": 60, "channel_k": 100, "top_n": 10,
                                "linear_w": None}


@pytest.mark.slow
def test_linear_tunes_and_records_w(tmp_path):
    run_dir = run_with_stub(tmp_path, system="baseline-linear")
    cfg = json.loads((run_dir / "config.json").read_text())
    w = cfg["w"]
    assert isinstance(w, float) and 0.0 <= w <= 1.0
    assert cfg["retrieval"] == {"fusion": "linear", "rrf_k": None, "channel_k": 100,
                                "top_n": 10, "linear_w": w}


@pytest.mark.slow
def test_judge_error_marks_text_rows_only(tmp_path):
    run_dir = run_with_stub(tmp_path, judge=StubClient(lambda s, u, r: "not json"),
                            generator=_stub_generator())
    rows = {r["item_id"]: r for r in _rows(run_dir)}
    assert rows["mini-factoid-1"]["outcome"] == "error"  # text: judged
    assert rows["mini-count-1"]["outcome"] == "correct"  # number: exact
    assert rows["mini-count-1"]["judge_check"]["error"]  # proxy judgment failed, row kept


def _stub_generator():
    from adr_eval.corpora.base import load_corpus
    from adr_eval.models import load_items
    from adr_eval.retrieval.chunker import chunk_document
    from adr_eval.runner import stub_clients

    corpus = load_corpus(MINI / "manifest.json", MINI)
    chunks = {c.chunk_id: c for d in corpus.docs.values() for c in chunk_document(d)}
    return stub_clients(load_items(MINI / "golden.jsonl"), chunks)[0]


@pytest.mark.slow
def test_report_from_stub_run(tmp_path):
    run_dir = run_with_stub(tmp_path, repeats=2)
    rep = build_report(run_dir)
    assert rep["determinism"]["retrieval_identity_rate"] == 1.0
    assert rep["determinism_violation"] is False
    assert rep["end_to_end"]["accuracy"] == 1.0
    assert rep["end_to_end"]["penalised"] == {"0.5": 1.0, "0.75": 1.0, "0.9": 1.0}
    assert rep["judge"]["proxy_kappa"] == 1.0 and rep["judge"]["self_consistency"] == 1.0
    assert rep["judge"]["human_kappa"] is None and rep["judge"]["same_family_judge"] is True
    assert rep["g2"]["exact"] == 1.0 and rep["g2"]["exec_match"] == 1.0
    assert "insufficient" not in rep["g3"]["by_qtype"]
    assert 0.0 <= rep["g1"]["span_containment"] <= 1.0
    md = render_markdown(rep)
    assert "share a model family" in md and "proxy, not human" in md


@pytest.mark.slow
def test_compare_reports_ci_and_mcnemar(tmp_path):
    a = run_with_stub(tmp_path)
    b = run_with_stub(tmp_path, system="baseline-linear")
    c = compare(a, b)
    assert c["n_pairs"] == len(_test_items())
    for key in ("penalised@0.75", "ndcg@10", "recall@10"):
        m = c["metrics"][key]
        assert m["ci95"][0] <= m["mean_diff"] <= m["ci95"][1]
        assert 0.0 <= m["p"] <= 1.0 and 0.0 <= m["p_holm"] <= 1.0
    assert 0.0 <= c["mcnemar"]["p"] <= 1.0 and 0.0 <= c["mcnemar"]["p_holm"] <= 1.0


@pytest.mark.slow
def test_same_second_runs_get_distinct_dirs(tmp_path):
    a = run_with_stub(tmp_path)
    b = run_with_stub(tmp_path)
    assert a != b and a.is_dir() and b.is_dir()


@pytest.mark.slow
def test_dry_run_makes_no_calls(tmp_path, capsys):
    def boom(s, u, r):
        raise AssertionError("model called during dry run")

    cfg = _config(tmp_path)
    run_id = run("mini", "baseline-rrf", "test", 2, cfg, out_root=tmp_path / "runs",
                 dry_run=True, generator=StubClient(boom), judge=StubClient(boom))
    out = capsys.readouterr().out
    assert run_id.startswith("mini-baseline-rrf-test-")
    assert not (tmp_path / "runs").exists()
    assert "calls" in out and "tokens" in out and "$" in out
    assert "calls are an upper bound" in out and "token counts and cost are estimates" in out


@pytest.mark.slow
def test_fingerprint_mismatch_refuses_without_rebuild(tmp_path):
    run_with_stub(tmp_path)
    meta = tmp_path / "index" / "mini" / "meta.json"
    data = json.loads(meta.read_text())
    meta.write_text(json.dumps({**data, "fingerprint": "0" * 64}))
    with pytest.raises(RunError, match="--rebuild"):
        run_with_stub(tmp_path)
    assert run_with_stub(tmp_path, rebuild=True).is_dir()
    assert json.loads(meta.read_text())["fingerprint"] == data["fingerprint"]


def test_snapshot_mismatch_refuses(tmp_path, monkeypatch, capsys):
    lines = (MINI / "golden.jsonl").read_text().splitlines()
    first = json.loads(lines[0])
    first["snapshot"] = "f" * 64
    altered = tmp_path / "items.jsonl"
    altered.write_text("\n".join([json.dumps(first), *lines[1:]]) + "\n")
    monkeypatch.setattr("adr_eval.runner.golden_items_path", lambda corpus: altered)
    rc = main(["run", "mini", "--system", "baseline-rrf", "--split", "test", "--repeats", "1",
               "--out", str(tmp_path / "runs"), "--stub"])
    err = capsys.readouterr().err
    assert rc != 0 and str(altered) in err and "snapshot" in err
    assert not (tmp_path / "runs").exists()


# -- clients ----------------------------------------------------------------------------


def test_shipped_config_values():
    cfg = load_config()
    assert cfg["generator"] == "claude_code_sonnet" and cfg["judge"] == "claude_code_opus"
    assert cfg["repeats"] == 5 and cfg["t_values"] == [0.5, 0.75, 0.9]
    assert cfg["seed"] == 20261108 and cfg["concurrency"] == 4


# -- call cap, billing and Claude Code runs ---------------------------------------------


def _envelope(text: str, served: str) -> str:
    return json.dumps({"type": "result", "is_error": False, "result": text,
                       "usage": {"input_tokens": 3, "output_tokens": 4,
                                 "cache_creation_input_tokens": 0,
                                 "cache_read_input_tokens": 0},
                       "total_cost_usd": 0.5, "modelUsage": {served: {}}})


def _fake_claude(fn, counter: list, served: str | None = None):
    """A `runner` for ClaudeCodeClient that answers with `fn(system, user, 0)`, reporting
    `served` (default: the requested model) as the model that answered."""
    import subprocess

    def run_(argv, stdin, timeout):
        counter.append(1)
        system = argv[argv.index("--system-prompt") + 1]
        model = served or argv[argv.index("--model") + 1]
        return subprocess.CompletedProcess(argv, 0, _envelope(fn(system, stdin, 0), model), "")

    return run_


def test_metered_client_caps_calls_and_skips_cache_hits(tmp_path):
    from adr_eval.cache import Cache
    from adr_eval.llm import ClaudeCodeClient
    from adr_eval.pipeline import Budget, BudgetExceeded, MeteredClient

    calls = []
    inner = ClaudeCodeClient("haiku", Cache(tmp_path), runner=_fake_claude(
        lambda s, u, r: "x", calls))
    prices = {"claude_code:*": {"billing": "subscription"}}
    budget = Budget(max_dollars=0.0, max_calls=1)  # subscription calls cost nothing
    mc = MeteredClient(inner, budget, prices)
    assert mc.complete("s", "u", max_tokens=5).text == "x"
    assert mc.complete("s", "u", max_tokens=5).cached  # a hit is not a call
    with pytest.raises(BudgetExceeded):
        mc.complete("s", "other", max_tokens=5)
    assert len(calls) == 1 and budget.calls == 1
    assert budget.stopped and budget.stop_reason == "calls" and budget.spent == 0.0


@pytest.mark.slow
def test_max_calls_stop_writes_status(tmp_path):
    full = run_with_stub(tmp_path / "full", concurrency=1)
    total = json.loads((full / "config.json").read_text())["calls"]  # stub calls: no cache
    run_dir = run_with_stub(tmp_path / "half", max_calls=total // 2, concurrency=1)
    cfg = json.loads((run_dir / "config.json").read_text())
    assert cfg["status"] == "stopped_calls" and cfg["max_calls"] == total // 2
    assert cfg["calls"] == total // 2
    assert 0 < len(_rows(run_dir)) < len(_test_items())
    assert "--max-calls" in " ".join(build_report(run_dir)["warnings"])


@pytest.mark.slow
def test_config_records_profiles_billing_and_families(tmp_path):
    run_dir = run_with_stub(tmp_path)
    cfg = json.loads((run_dir / "config.json").read_text())
    for role in ("generator", "judge"):
        info = cfg[role]
        assert info["profile"] == "stub" and info["adapter"] == "stub"
        assert info["family"] == "stub" and info["billing"] == "api"
    assert cfg["same_family_judge"] is True


@pytest.mark.slow
def _claude_code_run(tmp_path, monkeypatch, calls, judge_served=None, **kw) -> Path:
    """A mini run through the claude_code profiles with a fake `claude` (no real binary)."""
    import adr_eval.runner as runner_mod

    stub_gen, stub_judge = _stub_generator(), _stub_judge()
    real_make_client = runner_mod.make_client

    def make_client_(name, profiles, cache, max_retries=5):
        c = real_make_client(name, profiles, cache, max_retries)
        gen = name == "claude_code_sonnet"
        c._runner = _fake_claude(stub_gen.fn if gen else stub_judge.fn, calls,
                                 None if gen else judge_served)
        return c

    monkeypatch.setattr(runner_mod.shutil, "which", lambda b: f"/fake/bin/{b}")
    monkeypatch.setattr(runner_mod, "make_client", make_client_)
    cfg = {**_config(tmp_path), "stub": False}
    return tmp_path / "runs" / run("mini", "baseline-rrf", "test", 1, cfg,
                                   out_root=tmp_path / "runs", **kw)


@pytest.mark.slow
def test_served_model_mismatch_is_recorded_and_warned(tmp_path, monkeypatch):
    run_dir = _claude_code_run(tmp_path, monkeypatch, [], judge_served="claude-haiku-5-5")
    cfg = json.loads((run_dir / "config.json").read_text())
    assert cfg["generator"]["served_models"] == ["claude-sonnet-5-5"]
    assert cfg["judge"]["served_models"] == ["claude-haiku-5-5"]
    assert cfg["served_model_mismatch"] is True
    assert all("claude-sonnet-5-5" in r["served_models"] for r in _rows(run_dir))
    rep = build_report(run_dir)
    assert any("served model" in w for w in rep["warnings"])
    assert "served model" in render_markdown(rep)


@pytest.mark.slow
def test_claude_code_profile_run_is_subscription_billed_and_resumable(tmp_path, monkeypatch):
    calls = []
    first = _claude_code_run(tmp_path, monkeypatch, calls, max_dollars=0.0)
    c1 = json.loads((first / "config.json").read_text())
    assert c1["status"] == "complete" and c1["spent_usd"] == 0.0
    assert c1["generator"] == {"profile": "claude_code_sonnet", "adapter": "claude_code",
                               "name": "claude_code", "model": "claude-sonnet-5-5",
                               "family": "anthropic", "billing": "subscription",
                               "sampling": "cli-default (temperature not pinned)",
                               "served_models": ["claude-sonnet-5-5"]}
    assert c1["judge"]["profile"] == "claude_code_opus"
    assert c1["judge"]["model"] == "claude-opus-5-5"
    assert c1["same_family_judge"] is True and c1["served_model_mismatch"] is False
    assert not any("served model" in w for w in build_report(first)["warnings"])
    rows = _rows(first)
    assert {r["outcome"] for r in rows} == {"correct"}
    assert all(r["cost_usd"] == 0.0 and r["notional_cost_usd"] > 0 for r in rows)
    n_first = len(calls)
    # every call is now cached: a rerun capped at zero calls still completes
    second = _claude_code_run(tmp_path, monkeypatch, calls, max_calls=0)
    c2 = json.loads((second / "config.json").read_text())
    assert c2["status"] == "complete" and len(calls) == n_first and c2["calls"] == 0
    assert all(r["notional_cost_usd"] == 0.0 for r in _rows(second))


def _stub_judge():
    from adr_eval.corpora.base import load_corpus
    from adr_eval.models import load_items
    from adr_eval.retrieval.chunker import chunk_document
    from adr_eval.runner import stub_clients

    corpus = load_corpus(MINI / "manifest.json", MINI)
    chunks = {c.chunk_id: c for d in corpus.docs.values() for c in chunk_document(d)}
    return stub_clients(load_items(MINI / "golden.jsonl"), chunks)[1]


# -- reports from synthetic rows (no embedding model) -----------------------------------


def _row(item_id, repeat, retrieved, outcome="correct", latency=1.0, qtype="factoid"):
    return {
        "item_id": item_id, "repeat": repeat, "qtype": qtype, "rarity": "tail",
        "retrieved": [[c, 1.0] for c in retrieved], "generated_query": None,
        "gold_query_field_hits": {"store": True, "op": False, "filters": True,
                                  "entities": True, "as_of": True},
        "query_exact": False, "query_exec_match": None,
        "answer": None if outcome == "error" else
        {"value": "x", "kind": "text", "citations": [], "abstain": outcome == "abstained",
         "confidence": 1.0},
        "outcome": outcome, "judge_label": None, "judge_reason": None, "judge_check": None,
        "metrics": {"recall@10": 1.0, "ndcg@10": 0.5, "mrr": 1.0, "full_coverage": True,
                    "n_spans": 1},
        "citation": None, "tokens": {"in": 10, "out": 5}, "cost_usd": 0.01,
        "latency_s": latency, "error": "boom" if outcome == "error" else None,
    }


def _synthetic_run(tmp_path, rows, repeats=2, metrics_version=None, name="run") -> Path:
    d = tmp_path / name
    d.mkdir()
    version = {} if metrics_version is None else {"metrics_version": metrics_version}
    (d / "config.json").write_text(json.dumps({
        "run_id": name, "corpus": "mini", "system": "baseline-rrf", "split": "test",
        "repeats": repeats, "t_values": [0.5, 0.75, 0.9], "status": "complete", "stub": False,
        "same_family_judge": False, "judge": {"model": "j", "family": "x"},
        "generator": {"model": "g", "family": "y"}, "fingerprint": "f" * 64, **version,
    }))
    (d / "compile.json").write_text(json.dumps({
        "span_containment": 1.0, "text_fidelity": {"share": 1.0}, "empty_docs": [],
        "fingerprint": "f" * 64}))
    (d / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return d


def test_report_flags_determinism_violation(tmp_path):
    rows = [_row("a", 0, ["c1", "c2"]), _row("a", 1, ["c2", "c1"]),
            _row("b", 0, ["c1"], outcome="error", latency=None), _row("b", 1, ["c1"])]
    rep = build_report(_synthetic_run(tmp_path, rows))
    assert rep["determinism"]["retrieval_identity_rate"] == 0.5
    assert rep["determinism_violation"] is True
    assert "determinism" in render_markdown(rep).lower()
    e2e = rep["end_to_end"]
    assert e2e["error_count"] == 1 and e2e["error_rate"] == 0.25 and e2e["accuracy"] == 0.75
    assert e2e["latency_p50_s"] == 1.0  # the cached (None) latency is skipped
    assert e2e["tokens"] == {"in": 40, "out": 20}
    assert rep["g2"]["per_field"]["op"] == 0.0 and rep["g2"]["per_field"]["store"] == 1.0
    assert rep["judge"]["proxy_kappa"] is None and rep["judge"]["human_kappa"] is None


def test_report_handles_empty_run(tmp_path):
    rep = build_report(_synthetic_run(tmp_path, []))
    assert rep["end_to_end"]["n"] == 0 and rep["end_to_end"]["accuracy"] is None
    assert render_markdown(rep)


def test_report_penalised_hand_computed_with_cis(tmp_path):
    outcomes = ["correct", "wrong", "abstained", "partial", "error"]
    rows = [_row(f"i{n}", 0, ["c1"], outcome=o, latency=None if o == "error" else 1.0)
            for n, o in enumerate(outcomes)]
    rep = build_report(_synthetic_run(tmp_path, rows))
    e2e = rep["end_to_end"]
    # scored: correct 1, wrong -t/(1-t), abstained 0, partial -t/(1-t); error excluded
    expected = {"0.5": -0.25, "0.75": -1.25, "0.9": -4.25}
    assert e2e["penalised"] == pytest.approx(expected)
    for t, value in expected.items():
        ci = e2e["ci"]["penalised"][t]
        assert ci["n"] == 4 and ci["mean"] == pytest.approx(value)
        assert ci["ci95"][0] <= value <= ci["ci95"][1] and ci["ci95"][0] < ci["ci95"][1]
    acc = e2e["ci"]["accuracy"]
    assert e2e["accuracy"] == pytest.approx(0.2) and acc["n"] == 5
    assert acc["ci95"][0] <= 0.2 <= acc["ci95"][1]
    pooled = rep["g3"]["pooled"]["ci"]
    assert set(pooled) == {"recall@10", "ndcg@10", "mrr", "coverage@10"}
    assert pooled["coverage@10"] is None  # rows written before the metric existed
    assert pooled["ndcg@10"]["ci95"] == [0.5, 0.5]  # every synthetic row has nDCG 0.5
    stratum = e2e["by_rarity_qtype"]["tail/factoid"]
    assert stratum["ci"]["accuracy"]["n"] == 5
    md = render_markdown(rep)
    assert "-0.250 [" in md and "95% CI" in md


def test_report_ci_null_below_two_items(tmp_path):
    rep = build_report(_synthetic_run(tmp_path, [_row("a", 0, ["c1"])]))
    assert rep["end_to_end"]["ci"]["accuracy"] is None
    assert rep["end_to_end"]["ci"]["penalised"]["0.75"] is None
    assert rep["g3"]["pooled"]["ci"]["recall@10"] is None


def test_report_cis_cluster_over_items_using_every_repeat(tmp_path):
    from adr_eval.scoring.outcomes import penalised_score
    from adr_eval.scoring.stats import bootstrap_mean_ci

    plan = {"a": ["correct", "wrong", "wrong"],  # right on repeat 0 only
            "b": ["correct", "correct", "correct"],
            "c": ["abstained", "abstained", "correct"],
            "d": ["error", "error", "error"]}  # no non-error row: out of the penalised CI
    rows = [_row(i, rep, ["c1"], outcome=o, latency=None if o == "error" else 1.0)
            for i, os_ in plan.items() for rep, o in enumerate(os_)]
    rep = build_report(_synthetic_run(tmp_path, rows))
    e2e = rep["end_to_end"]
    assert e2e["n"] == 12
    first = [os_[0] for os_ in plan.values()]
    acc, acc_ci = e2e["accuracy"], e2e["ci"]["accuracy"]
    assert acc == pytest.approx(5 / 12)
    assert acc_ci["n"] == 4  # items, not rows; the all-error item counts for accuracy
    assert acc_ci["mean"] == pytest.approx(acc)
    assert acc_ci["ci95"][0] <= acc <= acc_ci["ci95"][1]
    old = bootstrap_mean_ci([float(o == "correct") for o in first])  # the repeat-0 CI
    assert old[0] != pytest.approx(acc)
    all_outcomes = [o for os_ in plan.values() for o in os_]
    for t in ("0.5", "0.75", "0.9"):
        shown, ci = e2e["penalised"][t], e2e["ci"]["penalised"][t]
        assert shown == pytest.approx(penalised_score(all_outcomes, float(t)))
        assert ci["n"] == 3 and ci["mean"] == pytest.approx(shown)
        assert ci["ci95"][0] <= shown <= ci["ci95"][1]
        old = bootstrap_mean_ci([penalised_score([o], float(t)) for o in first if o != "error"])
        assert old[0] != pytest.approx(shown)
    stratum = e2e["by_rarity_qtype"]["tail/factoid"]["ci"]
    assert stratum["accuracy"] == acc_ci and stratum["penalised"]["0.75"]["n"] == 3


def test_report_cis_none_when_fewer_than_two_items_contribute(tmp_path):
    rows = [_row("a", 0, ["c1"]), _row("a", 1, ["c1"], outcome="wrong"),
            _row("b", 0, ["c1"], outcome="error", latency=None),
            _row("b", 1, ["c1"], outcome="error", latency=None)]
    e2e = build_report(_synthetic_run(tmp_path, rows))["end_to_end"]
    assert e2e["ci"]["accuracy"]["n"] == 2
    assert all(ci is None for ci in e2e["ci"]["penalised"].values())  # only item a scores
    (tmp_path / "one").mkdir()
    single = build_report(_synthetic_run(tmp_path / "one", rows[:2]))["end_to_end"]
    assert single["ci"]["accuracy"] is None  # two rows, but one item


def test_report_one_repeat_cis_unchanged(tmp_path):
    from adr_eval.scoring.outcomes import penalised_score
    from adr_eval.scoring.stats import bootstrap_mean_ci

    outcomes = ["correct", "wrong", "abstained", "partial", "error", "correct", "wrong"]
    rows = [_row(f"i{n}", 0, ["c1"], outcome=o, latency=None if o == "error" else 1.0,
                 qtype="factoid" if n % 2 else "procedure")
            for n, o in enumerate(outcomes)]
    e2e = build_report(_synthetic_run(tmp_path, rows))["end_to_end"]

    def expected(os_):
        mean, lo, hi = bootstrap_mean_ci([float(o == "correct") for o in os_])
        acc = {"mean": mean, "ci95": [lo, hi], "n": len(os_)}
        pen = {}
        for t in (0.5, 0.75, 0.9):
            vals = [penalised_score([o], t) for o in os_ if o != "error"]
            mean, lo, hi = bootstrap_mean_ci(vals)
            pen[str(t)] = {"mean": mean, "ci95": [lo, hi], "n": len(vals)}
        return {"accuracy": acc, "penalised": pen}

    assert e2e["ci"] == expected(outcomes)  # exact, not approx
    for qtype, block in e2e["by_qtype"].items():
        sub = [o for n, o in enumerate(outcomes)
               if (qtype == "factoid") == bool(n % 2)]
        assert block["ci"] == expected(sub)


def test_report_markdown_describes_cluster_bootstrap(tmp_path):
    rows = [_row("a", 0, ["c1"]), _row("a", 1, ["c1"], outcome="wrong"),
            _row("b", 0, ["c1"]), _row("b", 1, ["c1"])]
    md = render_markdown(build_report(_synthetic_run(tmp_path, rows)))
    assert "cluster bootstrap over items" in md and "every repeat" in md
    assert "fewer than 2 items contribute" in md
    assert "mean over items at repeat 0, 10,000 resamples; none where n < 2)" not in md
    end_to_end_clause = md.split("End to end:", 1)[1].split("G3 retrieval:", 1)[0]
    assert "repeat 0" not in end_to_end_clause


@pytest.mark.slow
def test_budget_stop_keeps_complete_rows_and_reports_true_spend(tmp_path):
    full = run_with_stub(tmp_path / "full", priced=True, concurrency=1)
    total = json.loads((full / "config.json").read_text())["spent_usd"]
    run_dir = run_with_stub(tmp_path / "half", priced=True, concurrency=1,
                            max_dollars=total / 2)
    cfg = json.loads((run_dir / "config.json").read_text())
    rows = _rows(run_dir)
    assert cfg["status"] == "stopped_budget"
    assert 0 < len(rows) < len(_test_items())
    assert [(r["item_id"], r["repeat"]) for r in rows] == sorted(
        (r["item_id"], r["repeat"]) for r in rows)
    assert all(ROW_KEYS <= set(r) and r["outcome"] == "correct" for r in rows)
    row_sum = sum(r["cost_usd"] for r in rows)
    assert cfg["spent_usd"] >= row_sum > 0
    rep = build_report(run_dir)
    assert rep["end_to_end"]["spent_usd"] == cfg["spent_usd"]
    assert rep["end_to_end"]["cost_usd"] == pytest.approx(row_sum)
    assert "spent" in render_markdown(rep).lower()


def test_load_rows_reads_unicode_line_separators(tmp_path):
    from adr_eval.report import load_rows

    rows = [{"item_id": "a", "answer": {"value": "x\u2028y"}}, {"item_id": "b"}]
    (tmp_path / "results.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    assert load_rows(tmp_path) == rows


def test_report_counts_json_recovered_rows_and_tolerates_old_rows(tmp_path):
    rows = [_row("a", 0, ["c1"]), _row("b", 0, ["c1"]), _row("c", 0, ["c1"])]
    rows[0]["json_recovered"] = ["answer", "judge"]
    rows[1]["json_recovered"] = []  # rows[2] has no field: a run from before it existed
    rep = build_report(_synthetic_run(tmp_path, rows))
    e2e = rep["end_to_end"]
    assert e2e["json_recovered_rows"] == 1
    assert e2e["json_recovered_by_stage"] == {"query": 0, "answer": 1, "judge": 1,
                                              "judge_check": 0}
    assert "recovered" in render_markdown(rep)
    (tmp_path / "old").mkdir()
    old = build_report(_synthetic_run(tmp_path / "old", rows[2:]))
    assert old["end_to_end"]["json_recovered_rows"] == 0
    assert "recovered" not in render_markdown(old)


def test_report_one_repeat_determinism_not_measured(tmp_path):
    rows = [_row("a", 0, ["c1"]), _row("b", 0, ["c2"], outcome="wrong")]
    rep = build_report(_synthetic_run(tmp_path, rows, repeats=1))
    det = rep["determinism"]
    assert det["retrieval_identity_rate"] is None and det["answer_agreement"] is None
    assert det["pass^k"] == 0.5 and det["k"] == 1
    assert rep["determinism_violation"] is False
    md = render_markdown(rep)
    assert "Retrieval identity: not measured (1 repeat)" in md and "pass^1 0.500" in md


def _judged(item_id, outcome, label):
    row = _row(item_id, 0, ["c1"], outcome=outcome)
    row["judge_check"] = {"purpose": "proxy", "label": label, "reason": "", "error": None}
    return row


def test_report_judge_agreement_maps_partial_to_incorrect(tmp_path):
    rows = [_judged("a", "correct", "correct"), _judged("b", "wrong", "partial"),
            _judged("c", "wrong", "incorrect"), _judged("d", "correct", "partial")]
    j = build_report(_synthetic_run(tmp_path, rows))["judge"]
    assert j["proxy_kappa_n"] == 4
    assert j["proxy_agreement"] == 0.75
    # 2x2 after mapping: exact (C, I, I, C) vs judge (C, I, I, I); p_o 0.75, p_e 0.5
    assert j["proxy_kappa_binary"] == pytest.approx(0.5)
    md = render_markdown(build_report(tmp_path / "run"))
    assert "agreement 0.750" in md and "binary κ 0.500" in md


def test_report_judge_binary_kappa_none_when_degenerate(tmp_path):
    rows = [_judged("a", "correct", "correct"), _judged("b", "correct", "correct")]
    j = build_report(_synthetic_run(tmp_path, rows))["judge"]
    assert j["proxy_agreement"] == 1.0 and j["proxy_kappa_binary"] is None
    assert j["proxy_kappa"] is not None  # unchanged


def test_report_all_error_stratum_has_no_penalised_score(tmp_path):
    rows = [_row("a", 0, ["c1"]),
            _row("b", 0, ["c1"], outcome="error", latency=None, qtype="procedure"),
            _row("c", 0, ["c1"], outcome="error", latency=None, qtype="procedure")]
    rep = build_report(_synthetic_run(tmp_path, rows))
    proc = rep["end_to_end"]["by_qtype"]["procedure"]
    assert proc["n"] == 2 and proc["accuracy"] == 0.0
    assert all(v is None for v in proc["penalised"].values())
    assert rep["end_to_end"]["by_qtype"]["factoid"]["penalised"]["0.75"] == 1.0
    assert render_markdown(rep)


def test_compare_markdown_bounds_zero_bootstrap_p():
    from adr_eval.report import render_compare_markdown

    c = {"run_a": "a", "run_b": "b", "n_pairs": 30, "difference": "run_b - run_a",
         "n_resamples": 10_000,
         "metrics": {"ndcg@10": {"n": 30, "mean_diff": 0.2, "ci95": [0.1, 0.3], "p": 0.0,
                                 "p_holm": 0.0},
                     "recall@10": {"n": 30, "mean_diff": 0.0, "ci95": [-0.1, 0.1],
                                   "p": 0.5, "p_holm": 0.5}},
         "mcnemar": {"n": 30, "only_a_correct": 1, "only_b_correct": 2, "p": 1.0,
                     "p_holm": 1.0}}
    md = render_compare_markdown(c)
    ndcg = next(line for line in md.splitlines() if line.startswith("| ndcg@10"))
    assert ndcg.endswith("| < 0.0002 | < 0.0006 |")  # Holm: up to 3 tests x 2/n
    assert "| 0.500 | 0.500 |" in md


@pytest.mark.slow
def test_worker_exception_marks_run_failed_and_keeps_finished_rows(tmp_path):
    gen = _stub_generator()
    target = next(i["question"] for i in _test_items() if i["id"] == "mini-procedure-1")

    def fn(system, user, repeat):
        if target in user:
            raise RuntimeError("worker blew up")
        return gen.fn(system, user, repeat)

    with pytest.raises(RuntimeError, match="worker blew up"):
        run_with_stub(tmp_path, generator=StubClient(fn), judge=_stub_judge(), concurrency=1)
    (run_dir,) = (tmp_path / "runs").iterdir()
    cfg = json.loads((run_dir / "config.json").read_text())
    assert cfg["status"] == "failed" and "worker blew up" in cfg["error"]
    rows = _rows(run_dir)
    assert cfg["n_rows"] == len(rows) and 0 < len(rows) < len(_test_items())
    assert "mini-procedure-1" not in {r["item_id"] for r in rows}
    assert [r["item_id"] for r in rows] == sorted(r["item_id"] for r in rows)


@pytest.mark.slow
def test_judge_double_object_reply_is_recovered_in_runs(tmp_path):
    judge = _stub_judge()

    def fn(system, user, repeat):
        return '{"label": "incorrect", "reason": "draft"}\n' + judge.fn(system, user, repeat)

    run_dir = run_with_stub(tmp_path, generator=_stub_generator(), judge=StubClient(fn))
    rows = {r["item_id"]: r for r in _rows(run_dir)}
    assert rows["mini-factoid-1"]["outcome"] == "correct"
    assert rows["mini-factoid-1"]["json_recovered"] == ["judge", "judge_check"]
    assert rows["mini-insufficient-1"]["json_recovered"] == []
    rep = build_report(run_dir)
    assert rep["end_to_end"]["json_recovered_rows"] > 0


def _priced_cached_client(cache, fn, calls):
    from adr_eval.llm import Completion, _CachedClient

    class Priced(_CachedClient):
        name, family, model, max_retries = "priced", "stub", "priced-model", 0

        def _call(self, system, user, max_tokens):
            calls.append(1)
            return Completion(fn(system, user, 0), 10, 10, self.model, 0.0, False)

    return Priced(cache)


@pytest.mark.slow
def test_fully_cached_run_completes_under_tiny_budget(tmp_path):
    from adr_eval.cache import Cache

    prices = tmp_path / "prices.json"
    prices.write_text(json.dumps({"priced-model": {"input_per_mtok": 3.0,
                                                   "output_per_mtok": 15.0}}))
    cfg = {**_config(tmp_path), "prices": str(prices)}
    calls, cache = [], Cache(tmp_path / "llm")
    gen, judge = _stub_generator(), _stub_judge()

    def go(max_dollars):
        run_id = run("mini", "baseline-rrf", "test", 1, cfg, out_root=tmp_path / "runs",
                     max_dollars=max_dollars,
                     generator=_priced_cached_client(cache, gen.fn, calls),
                     judge=_priced_cached_client(cache, judge.fn, calls))
        return json.loads((tmp_path / "runs" / run_id / "config.json").read_text())

    first = go(None)
    assert first["status"] == "complete" and first["spent_usd"] > 0
    n_calls = len(calls)
    second = go(1e-9)  # every call is a cache hit: nothing to spend
    assert second["status"] == "complete" and second["spent_usd"] == 0.0
    assert len(calls) == n_calls and second["n_rows"] == first["n_rows"]


def test_cli_exits_4_on_determinism_violation(tmp_path, capsys):
    rows = [_row("a", 0, ["c1", "c2"]), _row("a", 1, ["c2", "c1"])]
    run_dir = _synthetic_run(tmp_path, rows)
    assert main(["report", str(run_dir)]) == 4
    assert "determinism check failed" in capsys.readouterr().out
    (tmp_path / "ok").mkdir()
    fine = _synthetic_run(tmp_path / "ok", [_row("a", 0, ["c1"]), _row("a", 1, ["c1"])])
    assert main(["report", str(fine)]) == 0


def test_cli_run_exits_4_on_determinism_violation(tmp_path, monkeypatch, capsys):
    import adr_eval.cli as cli

    rows = [_row("a", 0, ["c1", "c2"]), _row("a", 1, ["c2", "c1"])]
    run_dir = _synthetic_run(tmp_path, rows)
    monkeypatch.setattr(cli.runner, "run", lambda *a, **kw: run_dir.name)
    assert main(["run", "mini", "--system", "baseline-rrf", "--stub",
                 "--out", str(tmp_path)]) == 4
    assert "warning: determinism check failed" in capsys.readouterr().out


# -- metrics version 2 ------------------------------------------------------------------


@pytest.mark.slow
def test_stub_run_stamps_metrics_version_and_new_row_metrics(tmp_path):
    from adr_eval.scoring import METRICS_VERSION

    assert METRICS_VERSION == 2
    run_dir = run_with_stub(tmp_path)
    assert json.loads((run_dir / "config.json").read_text())["metrics_version"] == 2
    copies = json.loads((run_dir / "compile.json").read_text())["evidence_copies"]
    n_spans = sum(len(i["evidence"]) for i in _test_items())
    assert copies == {"spans": n_spans, "spans_with_copies": 0, "copies": 0}
    scored = [r for r in _rows(run_dir) if r["metrics"] is not None]
    assert scored and all(0.0 <= r["metrics"]["coverage@10"] <= 1.0 for r in scored)
    assert all(isinstance(r["metrics"]["tokens@10"], int) and r["metrics"]["tokens@10"] > 0
               for r in scored)
    rep = build_report(run_dir)
    assert rep["metrics_version"] == 2 and "Metrics version 2" in render_markdown(rep)
    assert rep["g3"]["pooled"]["coverage@10"] is not None
    assert rep["g3"]["pooled"]["tokens@10"] > 0


def _v2_row(item_id, coverage, tokens):
    row = _row(item_id, 0, ["c1"])
    row["metrics"] = {**row["metrics"], "coverage@10": coverage, "tokens@10": tokens}
    return row


def test_report_g3_coverage_with_ci_and_mean_tokens(tmp_path):
    rows = [_v2_row("a", 0.5, 100), _v2_row("b", 1.0, 300)]
    rep = build_report(_synthetic_run(tmp_path, rows, repeats=1, metrics_version=2))
    pooled = rep["g3"]["pooled"]
    assert pooled["coverage@10"] == 0.75 and pooled["tokens@10"] == 200
    assert pooled["ci"]["coverage@10"]["n"] == 2
    assert rep["g3"]["by_rarity"]["tail"]["coverage@10"] == 0.75
    md = render_markdown(rep)
    assert "coverage@10" in md and "tokens@10" in md and "0.750 [" in md


def test_report_without_version_field_is_version_1_and_builds(tmp_path):
    rep = build_report(_synthetic_run(tmp_path, [_row("a", 0, ["c1"]), _row("b", 0, ["c1"])],
                                      repeats=1))
    assert rep["metrics_version"] == 1
    assert rep["g3"]["pooled"]["coverage@10"] is None
    assert rep["g3"]["pooled"]["tokens@10"] is None
    md = render_markdown(rep)
    assert "Metrics version 1" in md and "| – | – |" in md


def test_compare_refuses_different_metrics_versions(tmp_path, capsys):
    rows = [_v2_row("a", 0.5, 100), _v2_row("b", 1.0, 300)]
    v1 = _synthetic_run(tmp_path, rows, repeats=1, name="old")
    v2 = _synthetic_run(tmp_path, rows, repeats=1, metrics_version=2, name="new")
    with pytest.raises(RunError, match="version 2.*version 1"):
        compare(v2, v1)
    capsys.readouterr()
    assert main(["report", str(v2), "--compare", str(v1)]) == 2
    err = capsys.readouterr().err.strip()
    assert len(err.splitlines()) == 1 and "2" in err and "1" in err and "metrics version" in err
    c = compare(v2, _synthetic_run(tmp_path, rows, repeats=1, metrics_version=2, name="new2"))
    assert c["metrics"]["coverage@10"]["n"] == 2 and c["metrics"]["coverage@10"]["mean_diff"] == 0


def _g2_row(item_id, route_ok, entity_f1, exec_match=None):
    row = _row(item_id, 0, ["c1"])
    row.update(route_ok=route_ok, entity_f1=entity_f1, query_exec_match=exec_match)
    return row


def test_report_g2_route_accuracy_entity_f1_and_record_match(tmp_path):
    rows = [_g2_row("a", True, 1.0, True), _g2_row("b", False, 0.5, False),
            _g2_row("c", True, None), _g2_row("d", None, None)]
    rep = build_report(_synthetic_run(tmp_path, rows, repeats=1, metrics_version=2))
    g2 = rep["g2"]
    assert g2["route_accuracy"] == pytest.approx(2 / 3) and g2["route_n"] == 3
    assert g2["entity_f1"] == 0.75 and g2["entity_n"] == 2
    assert g2["exec_match"] == 0.5 and g2["exec_n"] == 2
    assert g2["exact"] == 0.0 and g2["per_field"]["store"] == 1.0  # kept in report.json
    md = render_markdown(rep).split("## G2 query understanding")[1].split("## G1")[0]
    assert "route accuracy" in md and "record match" in md and "entity F1" in md
    assert "| 0.667 | 3 | 0.500 | 2 | 0.750 | 2 |" in md
    assert "store" not in md and "exact" not in md  # per-field table and whole-query match


def test_report_g2_for_rows_without_query_scores(tmp_path):
    rep = build_report(_synthetic_run(tmp_path, [_row("a", 0, ["c1"]), _row("b", 0, ["c1"])],
                                      repeats=1))
    g2 = rep["g2"]
    assert g2["route_accuracy"] is None and g2["route_n"] == 0
    assert g2["entity_f1"] is None and g2["entity_n"] == 0
    md = render_markdown(rep).split("## G2 query understanding")[1].split("## G1")[0]
    assert "| – | 0 | – | 0 | – | 0 |" in md
