"""Phase 3 harness (spec §10.1, §10.2; Task 8): the `p3-typed` system, which answers the
`count_filter` items from the typed tables with the generated query and no answer or judge
call; the Q1 comparison with a baseline run; the `also_in` readings; and the check that the
query-generation cache inputs are byte-identical to the baseline's. A gov fixture store under
`tmp_path` (the Federal Register fixture documents, tables built and promoted, ACL synced);
nothing reads `data/` or `.cache/`, and no model is called."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from adr_eval import runner, systems
from adr_eval.answer._prompts import load_prompt
from adr_eval.cli import main
from adr_eval.corpora.gov import GovAdapter
from adr_eval.golden.records import exec_gold_query
from adr_eval.llm import Completion, StubClient
from adr_eval.models import Answer, Checks, GoldenItem, GoldQuery, Provenance, write_items
from adr_eval.phase3 import (
    QUERY_GEN_SHA256,
    SCHEMA_SHA256,
    also_in_readings,
    cache_inputs_unchanged,
    q1_compare,
)
from adr_eval.report import build_report
from adr_eval.runner import RunError
from adr_eval.scoring.stats import mcnemar_exact
from adr_store import acl
from tests.store.tables_fixtures import loaded_of
from tests.store.test_tables_tools import make

QUERY_PROMPT = load_prompt("query_gen")
BAD = "How many documents have a red colour?"  # its generated query names no column


def item(id_, question, gold: GoldQuery, answer: Answer, qtype="count_filter",
         split="test") -> GoldenItem:
    return GoldenItem(
        id=id_, corpus="gov", snapshot="0" * 64, qtype=qtype, question=question, as_of=None,
        answer=answer, evidence=[], gold_query=gold, rarity=None, split=split,
        provenance=Provenance(model="hand", prompt_hash="hand", seed=0,
                              created=datetime(2026, 11, 20, tzinfo=UTC)),
        checks=Checks(), status="auto_verified")


def count_item(id_, question, filters, op="count", records=None, **kw) -> GoldenItem:
    gold = GoldQuery(store="typed_db", op=op, filters=filters)
    value = exec_gold_query(gold, records)   # the records semantics are the oracle
    answer = Answer(kind="number", value=float(value)) if op == "count" \
        else Answer(kind="set", value=value)
    return item(id_, question, gold, answer, **kw)


class CachedStub:
    """A stub client with a reply cache: a repeated prompt is a cache hit (`is_cached`), which
    the budget does not count as a call; `calls` counts the replies it computed."""

    name = family = model = "stub"

    def __init__(self, fn):
        self.fn, self.cache, self.calls = fn, {}, 0

    def is_cached(self, system, user, *, max_tokens, repeat=0) -> bool:
        return (system, user, repeat) in self.cache

    def complete(self, system, user, *, max_tokens, repeat=0) -> Completion:
        key = (system, user, repeat)
        if key in self.cache:
            return Completion(self.cache[key], 0, 0, "stub", 0.0, True, provider="stub")
        self.calls += 1
        self.cache[key] = text = self.fn(system, user, repeat)
        return Completion(text, len(user) // 4, len(text) // 4, "stub", 0.0, False,
                          provider="stub")


def never(system, user, repeat):
    raise AssertionError("p3-typed made an answer or judge call")


@pytest.fixture
def tables_store_config(tmp_path, monkeypatch):
    """A gov fixture store at `<p2_store_dir>/gov` with its tables promoted and a fresh ACL
    sync; the runner reads its documents as the gov corpus and hand-written golden items
    (four count_filter test items, one factoid, one dev item) whose answers the records
    semantics give."""
    path = tmp_path / "store-p2" / "gov"
    store = make(path, rules=None)
    acl.sync(path)   # the shipped directory and policy, the real clock: fresh for an hour
    loaded = loaded_of(store)
    records = GovAdapter().records(loaded)
    items = [
        count_item("gov-c1", "How many Rule documents are there?", {"type": "Rule"},
                   records=records),
        count_item("gov-c2", "Which documents affect 33 CFR 117?",
                   {"cfr_parts__contains": "33 CFR 117"}, op="list", records=records),
        count_item("gov-c3", "How many Coast Guard documents were published in 2024?",
                   {"agency": "Coast Guard", "year": 2024}, records=records),
        count_item("gov-c4", BAD, {"type": "Proposed Rule"}, records=records),
        count_item("gov-c5", "How many Rule documents are there in the dev split?",
                   {"type": "Rule"}, records=records, split="dev"),
        item("gov-f1", "What does the Cape Fear rule do?", GoldQuery(store="raw", op="lookup"),
             Answer(kind="text", value="it changes the drawbridge schedule"), qtype="factoid"),
    ]
    golden = tmp_path / "golden.jsonl"
    write_items(golden, items)
    monkeypatch.setattr(runner, "load_checked_corpus", lambda corpus: loaded)
    monkeypatch.setattr(runner, "load_golden", lambda corpus, loaded_: items)
    monkeypatch.setattr(runner, "golden_items_path", lambda corpus: golden)
    config = {**runner.load_config(), "p2_store_dir": str(tmp_path / "store-p2"),
              "p2_caller": "user:auditor", "cache_dir": str(tmp_path / "llm"),
              "concurrency": 2}
    return {"config": config, "items": items, "records": records, "store": path,
            "out": tmp_path / "runs"}


def generator() -> CachedStub:
    """Replies to the query-generation prompt with the item's gold query (an unknown column for
    BAD); any other prompt is an answer call, which p3-typed must never make."""
    def fn(system, user, repeat):
        assert system == QUERY_PROMPT, "p3-typed made an answer call"
        question = user.rsplit("Question: ", 1)[1]
        if question == BAD:
            return json.dumps({"store": "typed_db", "op": "count", "filters": {"colour": "red"}})
        gold = {"How many Rule documents are there?": ("count", {"type": "Rule"}),
                "Which documents affect 33 CFR 117?":
                    ("list", {"cfr_parts__contains": "33 CFR 117"}),
                "How many Coast Guard documents were published in 2024?":
                    ("count", {"agency": "Coast Guard", "year": 2024})}[question]
        return json.dumps({"store": "typed_db", "op": gold[0], "filters": gold[1]})

    return CachedStub(fn)


def typed_run(env, gen, **kw) -> Path:
    run_id = runner.run("gov", "p3-typed", "test", 1, env["config"], out_root=env["out"],
                        qtypes=("count_filter",), generator=gen, judge=StubClient(never),
                        **kw)
    return env["out"] / run_id


def load_rows(run_dir: Path) -> list[dict]:
    return [json.loads(x) for x in (run_dir / "results.jsonl").read_text().splitlines()]


def config_json(run_dir: Path) -> dict:
    return json.loads((run_dir / "config.json").read_text())


# -- the cache inputs ----------------------------------------------------------------------------


def test_cache_inputs_are_byte_identical_to_the_baseline():
    assert cache_inputs_unchanged("gov") == [] and cache_inputs_unchanged("research") == []


def test_a_changed_prompt_or_schema_is_reported(monkeypatch):
    from adr_eval.answer import query_gen

    monkeypatch.setattr(query_gen, "load_prompt", lambda name: QUERY_PROMPT + " ")
    problems = cache_inputs_unchanged("gov")
    assert len(problems) == 1 and "prompt" in problems[0] and QUERY_GEN_SHA256[:12] in \
        problems[0]
    monkeypatch.undo()
    monkeypatch.setattr(GovAdapter, "record_schema", lambda self: {"id": "str: changed"})
    problems = cache_inputs_unchanged("gov")
    assert len(problems) == 1 and "schema" in problems[0] and SCHEMA_SHA256["gov"][:12] in \
        problems[0]
    assert cache_inputs_unchanged("mini") == ["mini: no recorded baseline schema"]


# -- p3-typed in the harness ---------------------------------------------------------------------


def test_p3_typed_is_registered_apart():
    assert systems.P3_NAMES == ("p3-typed",)
    assert systems.ALL_NAMES == (*systems.NAMES, *systems.P2_NAMES, *systems.P3_NAMES)


def test_p3_typed_needs_the_count_filter_qtype(tables_store_config):
    config = tables_store_config["config"]
    for qtypes in (None, ("count_filter", "factoid"), ("factoid",)):
        with pytest.raises(RunError, match="p3-typed answers count_filter items only; pass "
                                           "--qtype count_filter"):
            runner.run("mini", "p3-typed", "test", 1, config, qtypes=qtypes)


def test_p3_typed_answers_from_the_tables_with_no_answer_or_judge_call(tables_store_config):
    env = tables_store_config
    gen = generator()
    run_dir = typed_run(env, gen)
    rows = load_rows(run_dir)
    assert [r["item_id"] for r in rows] == ["gov-c1", "gov-c2", "gov-c3", "gov-c4"]
    assert {r["qtype"] for r in rows} == {"count_filter"} and gen.calls == len(rows)
    assert all(r["judge_check"] is None and r["metrics"] is None for r in rows)
    assert all(r["judge_label"] is None and r["retrieved"] == [] for r in rows)
    by_id = {r["item_id"]: r for r in rows}
    gold = {i.id: exec_gold_query(i.gold_query, env["records"]) for i in env["items"]
            if i.qtype == "count_filter"}
    for i in ("gov-c1", "gov-c2", "gov-c3"):   # the tables reproduce the records semantics
        r = by_id[i]
        assert r["outcome"] == "correct" and r["typed_error"] is None
        assert r["answer"]["value"] == gold[i] and r["query_exec_match"] is True
    assert gold["gov-c1"] > 0 and gold["gov-c2"] and gold["gov-c3"] > 0
    bad = by_id["gov-c4"]   # a refused query gives no value: wrong
    assert bad["outcome"] == "wrong" and bad["answer"]["value"] is None
    assert bad["typed_error"] == "unknown column 'colour' in table fr_documents"
    assert bad["error"] is None
    cfg = config_json(run_dir)
    assert cfg["status"] == "complete" and cfg["qtypes"] == ["count_filter"]
    assert cfg["n_items"] == 4
    tables_id = (env["store"] / "tables" / "HEAD").read_text().strip()
    assert cfg["fingerprint"] == tables_id
    rc = cfg["retrieval"]
    assert rc["tables"] == tables_id and rc["caller"] == "user:auditor"
    assert rc["store"].endswith("store-p2/gov") and len(rc["snapshot"]) == 64
    assert rc["acl"]["visible_docs"] == rc["acl"]["store_docs"]
    comp = json.loads((run_dir / "compile.json").read_text())
    assert set(comp) == {"tables", "manifest"} and comp["tables"] == tables_id
    manifest = next((env["store"] / "tables").glob(f"*/tables-{tables_id[:16]}.json"))
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == tables_id
    assert comp["manifest"] == json.loads(manifest.read_text())
    rep = build_report(run_dir)   # a typed run is reportable
    assert rep["end_to_end"]["accuracy"] == 0.75


def test_a_rerun_makes_no_call_under_max_calls_0(tables_store_config):
    env = tables_store_config
    gen = generator()
    first = typed_run(env, gen)
    rerun = typed_run(env, gen, max_calls=0)
    assert config_json(rerun)["status"] == "complete" and config_json(rerun)["calls"] == 0
    assert gen.calls == 4   # all from the first run
    strip = ("latency_s", "tokens")
    assert [{k: v for k, v in r.items() if k not in strip} for r in load_rows(rerun)] == \
        [{k: v for k, v in r.items() if k not in strip} for r in load_rows(first)]
    cold = typed_run(env, generator(), max_calls=0)   # nothing cached: it stops, no call
    assert config_json(cold)["status"] == "stopped_calls" and config_json(cold)["calls"] == 0


def test_a_dry_run_counts_the_query_calls_only(tables_store_config, capsys):
    env = tables_store_config
    gen = generator()
    typed_run(env, gen, dry_run=True)
    out = capsys.readouterr().out
    assert "generator stub: 4 calls" in out and "judge stub: 0 calls" in out
    assert gen.calls == 0 and not env["out"].exists()


def test_p3_typed_refuses_a_store_without_promoted_tables(tables_store_config):
    env = tables_store_config
    (env["store"] / "tables" / "HEAD").unlink()
    with pytest.raises(RunError, match=r"(?s)no promoted tables.*adr tables"):
        typed_run(env, generator())


def test_p3_typed_needs_a_caller(tables_store_config):
    env = tables_store_config
    env["config"]["p2_caller"] = None
    with pytest.raises(RunError, match="p2_caller"):
        typed_run(env, generator())


@pytest.mark.slow
def test_the_chunk_path_rows_are_unchanged(tmp_path):
    """baseline-linear on mini with the stub: the rows keep exactly the Phase 0 keys (no
    `typed_error`), carry retrieval metrics and judge checks, and a --qtype run gives the same
    rows for its items as the unfiltered run."""
    cfg = {**runner.load_config(), "index_dir": str(tmp_path / "index"),
           "cache_dir": str(tmp_path / "llm"), "stub": True, "concurrency": 2}
    full = tmp_path / "runs" / runner.run("mini", "baseline-linear", "test", 1, cfg,
                                          out_root=tmp_path / "runs")
    part = tmp_path / "runs" / runner.run("mini", "baseline-linear", "test", 1, cfg,
                                          out_root=tmp_path / "runs",
                                          qtypes=("count_filter",))
    keys = {"item_id", "repeat", "qtype", "rarity", "retrieved", "generated_query",
            "gold_query_field_hits", "query_exact", "query_exec_match", "route_ok",
            "entity_f1", "answer", "outcome", "judge_label", "judge_reason", "judge_check",
            "metrics", "citation", "tokens", "cost_usd", "notional_cost_usd",
            "served_models", "latency_s", "error", "json_recovered"}
    rows = load_rows(full)
    assert rows and all(set(r) == keys for r in rows)
    assert {r["outcome"] for r in rows} == {"correct"}
    assert all(r["retrieved"] and r["metrics"] is not None for r in rows
               if r["qtype"] != "insufficient")
    assert any(r["judge_check"] is not None for r in rows)
    strip = ("latency_s", "tokens")
    want = [{k: v for k, v in r.items() if k not in strip} for r in rows
            if r["qtype"] == "count_filter"]
    assert want and [{k: v for k, v in r.items() if k not in strip}
                     for r in load_rows(part)] == want
    assert config_json(full)["qtypes"] is None


# -- Q1 ------------------------------------------------------------------------------------------


def run_dir_of(root: Path, name: str, system: str, rows: list[dict]) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "config.json").write_text(json.dumps({"run_id": name, "corpus": "gov",
                                               "system": system, "split": "test"}))
    (d / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return d


def q1_row(item_id, outcome, *, qtype="count_filter", value=1, typed_error=None,
           exec_match=True, generated=True, repeat=0) -> dict:
    gq = {"store": "typed_db", "op": "count", "filters": {"type": "Rule"}, "entities": [],
          "as_of": None} if generated else None
    return {"item_id": item_id, "repeat": repeat, "qtype": qtype, "outcome": outcome,
            "generated_query": gq, "query_exec_match": exec_match if generated else False,
            "typed_error": typed_error, "error": None,
            "answer": {"value": value, "abstain": outcome == "abstained"}}


def test_q1_compare_counts_discordant_pairs_and_mcnemar(tmp_path):
    typed_dir = run_dir_of(tmp_path, "typed", "p3-typed",
                           [q1_row(i, "correct") for i in ("a", "b", "c")])
    base_dir = run_dir_of(tmp_path, "base", "baseline-linear", [
        q1_row("a", "correct"), q1_row("b", "wrong"), q1_row("c", "abstained"),
        q1_row("f", "correct", qtype="factoid")])   # not a count_filter item: not compared
    c = q1_compare(typed_dir, base_dir)      # 3 items: typed right on all, baseline on 1
    assert (c["b"], c["c"]) == (2, 0) and c["mcnemar_p"] == mcnemar_exact(2, 0)
    assert c["n"] == 3 and c["typed"]["correct"] == 3 and c["typed"]["accuracy"] == 1.0
    assert c["baseline"]["correct"] == 1 and c["baseline"]["accuracy"] == pytest.approx(1 / 3)
    assert c["misses"] == []
    assert [m["item_id"] for m in c["baseline_misses"]] == ["b", "c"]
    assert c["typed_run"] == "typed" and c["baseline_run"] == "base"


def test_q1_compare_lists_each_miss_with_its_cause(tmp_path):
    typed_dir = run_dir_of(tmp_path, "typed", "p3-typed", [
        q1_row("a", "wrong", value=None, typed_error="unknown column 'colour'"),
        q1_row("b", "wrong", value=[f"x{i}" for i in range(23)], exec_match=False),
        q1_row("c", "wrong", value=None, generated=False),
        q1_row("d", "wrong", value=3),
        q1_row("e", "correct")])
    base_dir = run_dir_of(tmp_path, "base", "baseline-linear",
                          [q1_row(i, "correct") for i in "abcd"] + [q1_row("e", "wrong")])
    c = q1_compare(typed_dir, base_dir)
    assert (c["b"], c["c"]) == (1, 4) and c["mcnemar_p"] == mcnemar_exact(1, 4)
    misses = {m["item_id"]: m for m in c["misses"]}
    assert list(misses) == ["a", "b", "c", "d"]
    assert misses["a"]["cause"] == "query refused: unknown column 'colour'"
    assert misses["b"]["cause"].startswith("the generated query's result differs")
    assert misses["b"]["value"] == {"n": 23}   # a list is reported by its length only
    assert misses["c"]["cause"] == "no generated query" and misses["c"]["generated_query"] is None
    assert misses["d"]["cause"].startswith("the tables differ from the records")
    assert misses["d"]["value"] == 3
    assert misses["a"]["generated_query"]["filters"] == {"type": "Rule"}
    assert [m["cause"] for m in c["baseline_misses"]] == ["the answer from retrieved chunks"]


def test_q1_compare_refuses_repeats_or_a_typed_run_that_is_not_one(tmp_path):
    typed_dir = run_dir_of(tmp_path, "typed", "baseline-linear", [q1_row("a", "correct")])
    base_dir = run_dir_of(tmp_path, "base", "baseline-linear", [q1_row("a", "correct")])
    with pytest.raises(RunError, match="not a p3-typed run"):
        q1_compare(typed_dir, base_dir)
    typed_dir = run_dir_of(tmp_path, "typed2", "p3-typed", [q1_row("a", "correct")])
    base_dir = run_dir_of(tmp_path, "base2", "baseline-linear",
                          [q1_row("a", "correct"), q1_row("a", "wrong", repeat=1)])
    with pytest.raises(RunError, match="repeat 0"):
        q1_compare(typed_dir, base_dir)


def test_p3_q1_cli_prints_and_writes_the_comparison(tmp_path, capsys):
    typed_dir = run_dir_of(tmp_path, "typed", "p3-typed",
                           [q1_row(i, "correct") for i in ("a", "b")])
    base_dir = run_dir_of(tmp_path, "base", "baseline-linear",
                          [q1_row("a", "correct"), q1_row("b", "wrong")])
    for d in (typed_dir, base_dir):   # the mini corpus: no also_in items
        cfg = json.loads((d / "config.json").read_text())
        (d / "config.json").write_text(json.dumps({**cfg, "corpus": "mini"}))
    assert main(["p3-q1", str(typed_dir), str(base_dir)]) == 0
    printed = json.loads(capsys.readouterr().out)
    written = json.loads((typed_dir / "q1-base.json").read_text())
    assert printed == written and (written["b"], written["c"]) == (1, 0)
    assert written["also_in"] == []


# -- also_in readings ----------------------------------------------------------------------------


def test_also_in_readings_report_both_counts():
    records = [
        {"id": "p1", "also_in": "t1", "venue": "arXiv"},
        {"id": "p2", "also_in": "t1;t2", "venue": "arXiv"},
        {"id": "p3", "also_in": "t2; t1", "venue": "ACL"},
        {"id": "p4", "also_in": "", "venue": "arXiv"},
        {"id": "p5", "also_in": "t1;t2", "venue": "ACL"},
    ]
    gq = lambda op, f: GoldQuery(store="typed_db", op=op, filters=f)  # noqa: E731
    items = [
        item("r1", "?", gq("count", {"also_in": "t1"}), Answer(kind="number", value=1.0)),
        item("r2", "?", gq("list", {"also_in": "t1", "venue": "arXiv"}),
             Answer(kind="set", value=["p1"]), split="dev"),
        item("r3", "?", gq("count", {"also_in": "t1;t2"}), Answer(kind="number", value=2.0)),
        item("r4", "?", gq("count", {"venue": "arXiv"}), Answer(kind="number", value=3.0)),
        item("r5", "?", gq("count", {"also_in": "t1"}), Answer(kind="number", value=1.0),
             qtype="factoid"),
    ]
    out = also_in_readings(items, records)
    assert out == [
        {"item_id": "r1", "split": "test", "op": "count", "also_in": "t1",
         "string": 1, "membership": 4, "differs": True},
        {"item_id": "r2", "split": "dev", "op": "list", "also_in": "t1",
         "string": 1, "membership": 2, "differs": True},
        {"item_id": "r3", "split": "test", "op": "count", "also_in": "t1;t2",
         "string": 2, "membership": 3, "differs": True},
    ]
