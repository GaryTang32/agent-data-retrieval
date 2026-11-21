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
from adr_eval.cache import Cache
from adr_eval.cli import main
from adr_eval.corpora.gov import GovAdapter
from adr_eval.golden.records import exec_gold_query
from adr_eval.llm import CachedStubClient, Completion, StubClient
from adr_eval.models import Answer, Checks, GoldenItem, GoldQuery, Provenance, write_items
from adr_eval.phase3 import (
    QUERY_GEN_SHA256,
    SCHEMA_SHA256,
    also_in_readings,
    cache_inputs_unchanged,
    q1_compare,
    q1_summary,
)
from adr_eval.report import build_report, render_markdown
from adr_eval.runner import RunError
from adr_eval.scoring.stats import mcnemar_exact
from adr_store import acl
from tests.store.tables_fixtures import loaded_of
from tests.store.test_tables_tools import make

QUERY_PROMPT = load_prompt("query_gen")
PRICED = "claude-sonnet-5-5"   # a model with a price: a profile-built client needs one
CHUNK_ROWS = json.loads((Path(__file__).parent / "fixtures" / "chunk_path_rows_mini.json")
                        .read_text(encoding="utf-8"))
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
    assert rep["qtypes"] == ["count_filter"] and rep["tables"] == tables_id
    assert rep["warnings"] == []   # no judge ran: no judge-family warning
    md = render_markdown(rep)
    assert f"tables `{tables_id}`" in md and "index fingerprint" not in md
    assert "G3 retrieval" not in md and "share a model family" not in md
    assert "Question types: count_filter only." in md
    assert "no answer or judge call" in md


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


def test_an_access_denial_stops_the_run_and_is_never_scored(tables_store_config, monkeypatch):
    """A fail-closed denial on the typed path (here a stale ACL after the build) is not a
    query refusal: it fails the run, as an ACL failure fails the chunk path, and no row
    scores it `wrong`."""
    from adr_store import tools
    from adr_store.tools import AccessDenied

    env = tables_store_config
    real = tools.Tools.query_table

    def denied(self, *a, **k):
        raise AccessDenied("F1", "access denied (F1): the ACL snapshot is stale")

    monkeypatch.setattr(tools.Tools, "query_table", denied)
    with pytest.raises(AccessDenied):
        typed_run(env, generator())
    monkeypatch.setattr(tools.Tools, "query_table", real)
    (run_dir,) = env["out"].iterdir()
    cfg = config_json(run_dir)
    assert cfg["status"] == "failed" and "access denied (F1)" in cfg["error"]
    assert all(r["outcome"] != "wrong" for r in load_rows(run_dir))


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


# -- the Q1 path budget (final review I1) --------------------------------------------------------


def cached_generator(tmp_path, fn=None, model="stub-gen", **kw) -> CachedStubClient:
    """`generator()`'s replies behind a real reply cache (a `_CachedClient`, as every real
    adapter is), so the budget can count its transport attempts."""
    return CachedStubClient(model, Cache(tmp_path / "llm-gen"), fn or generator().fn, **kw)


def test_a_typed_v0_1_run_counts_every_transport_attempt(tables_store_config, tmp_path,
                                                          monkeypatch):
    """P21 on the Q1 path: with a cached generator, each transport attempt (a retry included)
    takes a unit of --max-calls; no judge client is metered (a typed run calls none)."""
    from adr_eval import llm

    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    env = tables_store_config
    state = {"failed": 0}
    base = generator().fn

    def flaky(system, user, repeat):          # the first transport attempt fails, then replies
        if state["failed"] == 0:
            state["failed"] += 1
            raise llm._Retryable("overloaded")
        return base(system, user, repeat)

    gen = cached_generator(tmp_path, flaky, max_retries=5)
    stopped = typed_run(env, gen, max_calls=4)       # 1 retry + 4 replies > 4 units
    cfg = config_json(stopped)
    assert cfg["status"] == "stopped_calls" and cfg["calls"] == 4
    assert cfg["count_attempts"] is True and len(load_rows(stopped)) == 3
    done = typed_run(env, gen, max_calls=1)          # three replies cached: one attempt left
    cfg = config_json(done)
    assert cfg["status"] == "complete" and cfg["calls"] == 1 and gen.calls == 5
    assert len(load_rows(done)) == 4


def test_a_typed_v0_1_run_caches_input_rejections_only(tables_store_config, tmp_path):
    """P21: an input rejection is stored and replayed with no call; any other model failure
    is an error row of this run and is never stored, so a rerun calls again."""
    from adr_eval import llm

    env = tables_store_config
    base = generator().fn
    failing = {"How many Rule documents are there?": llm.InputRejected("HTTP 400: too long"),
               "Which documents affect 33 CFR 117?": llm.RetriesExhausted("usage limit")}
    mode = {"fail": True}

    def fn(system, user, repeat):
        question = user.rsplit("Question: ", 1)[1]
        if mode["fail"] and question in failing:
            raise failing[question]
        return base(system, user, repeat)

    gen = cached_generator(tmp_path, fn)
    rows = {r["item_id"]: r for r in load_rows(typed_run(env, gen, max_calls=10))}
    assert rows["gov-c1"]["outcome"] == "error" and "HTTP 400" in rows["gov-c1"]["error"]
    assert rows["gov-c2"]["outcome"] == "error" and "usage limit" in rows["gov-c2"]["error"]
    mode["fail"] = False
    before = gen.calls
    again = {r["item_id"]: r for r in load_rows(typed_run(env, gen, max_calls=10))}
    assert again["gov-c1"]["outcome"] == "error" and "HTTP 400" in again["gov-c1"]["error"]
    assert again["gov-c2"]["outcome"] == "correct"
    assert gen.calls - before == 1                   # only the failure that was not stored


def run_typed_cli(env, monkeypatch, capsys, *args) -> tuple[int, str, str]:
    monkeypatch.setattr(runner, "load_config", lambda path=runner.CONFIG_PATH: env["config"])
    code = main(["run", "gov", "--system", "p3-typed", "--qtype", "count_filter", "--split",
                 "test", "--repeats", "1", "--out", str(env["out"]), *map(str, args)])
    out, err = capsys.readouterr()
    return code, out, err


def test_adr_eval_run_p3_typed_needs_max_calls(tables_store_config, tmp_path, monkeypatch,
                                               capsys):
    env = tables_store_config
    made = []

    def make_client(name, profiles, cache, max_retries=5):
        made.append(name)
        return cached_generator(tmp_path / name, model=PRICED)

    monkeypatch.setattr(runner, "make_client", make_client)
    code, out, err = run_typed_cli(env, monkeypatch, capsys)
    assert code == 2 and "p3-typed run needs --max-calls" in err
    assert not env["out"].exists() and made == []
    code, out, err = run_typed_cli(env, monkeypatch, capsys, "--max-calls", 4)
    assert code == 0, err
    assert "status complete" in out and "4 rows" in out
    cfg = config_json(next(env["out"].iterdir()))
    assert cfg["max_calls"] == 4 and cfg["count_attempts"] is True and cfg["calls"] == 4
    # --stub and --dry-run call no model: no cap needed
    assert run_typed_cli(env, monkeypatch, capsys, "--dry-run")[0] == 0


def test_adr_eval_run_p3_typed_refuses_changed_cache_inputs(tables_store_config, monkeypatch,
                                                            capsys):
    """Q1 reuses the baseline's cached queries (spec §10.2): a query-generation prompt or
    record schema that is not byte-identical to the baseline's would make every call anew,
    so the run is refused before anything is built."""
    from adr_eval.answer import query_gen

    env = tables_store_config
    monkeypatch.setattr(runner, "make_client", lambda *a, **k: pytest.fail("a client was made"))
    monkeypatch.setattr(query_gen, "load_prompt", lambda name: QUERY_PROMPT + " ")
    code, out, err = run_typed_cli(env, monkeypatch, capsys, "--max-calls", 0)
    assert code == 2 and not env["out"].exists()
    assert "query-generation prompt has sha256" in err and QUERY_GEN_SHA256[:12] in err
    assert "Q1 reuses the baseline's cached queries" in err


@pytest.mark.slow
def test_the_chunk_path_rows_are_unchanged(tmp_path):
    """baseline-linear on mini with the stub gives the rows recorded with the code before
    Task 8 (tests/fixtures/chunk_path_rows_mini.json, recorded at abbaec3 with `latency_s`
    dropped): equal except retrieval scores, which are compared to 2e-3 as in
    `test_baselines_through_the_registry_give_the_recorded_ranked_lists` (ONNX on other CPUs
    differs in the fourth decimal). A --qtype run gives the same rows for its items, and its
    report states the filter."""
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

    def pinned(r):
        r = {k: v for k, v in r.items() if k != "latency_s"}
        return {**r, "retrieved": [c for c, _ in r["retrieved"]]}

    assert [pinned(r) for r in rows] == [pinned(r) for r in CHUNK_ROWS]
    for got, want in zip(rows, CHUNK_ROWS, strict=True):
        assert [x for _, x in got["retrieved"]] == pytest.approx(
            [x for _, x in want["retrieved"]], abs=2e-3)
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
    assert "Question types" not in render_markdown(build_report(full))
    assert "Question types: count_filter only." in render_markdown(build_report(part))


# -- Q1 ------------------------------------------------------------------------------------------


def run_dir_of(root: Path, name: str, system: str, rows: list[dict], **cfg) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "config.json").write_text(json.dumps({"run_id": name, "corpus": "gov",
                                               "system": system, "split": "test",
                                               "status": "complete", **cfg}))
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


def test_q1_compare_refuses_runs_that_are_not_comparable(tmp_path):
    typed_dir = run_dir_of(tmp_path, "typed", "p3-typed", [q1_row("a", "correct")])
    for name, cfg, what in (("c", {"corpus": "research"}, "corpus"),
                            ("s", {"split": "dev"}, "split"),
                            ("f", {"status": "stopped_calls"}, "status")):
        base_dir = run_dir_of(tmp_path, name, "baseline-linear", [q1_row("a", "correct")],
                              **cfg)
        with pytest.raises(RunError, match=what):
            q1_compare(typed_dir, base_dir)
    unfinished = run_dir_of(tmp_path, "t2", "p3-typed", [q1_row("a", "correct")],
                            status="failed")
    base_dir = run_dir_of(tmp_path, "b2", "baseline-linear", [q1_row("a", "correct")])
    with pytest.raises(RunError, match="status"):
        q1_compare(unfinished, base_dir)


def test_the_shared_run_refusals_name_the_comparison_that_refuses(tmp_path):
    """`_run` serves Q1 and Q2: each refusal names the caller's comparison, never the other."""
    from adr_eval.phase3 import q2_compare

    tables_cfg = {"golden_set": "gov-tables", "golden_sha256": "0" * 64}
    linear = run_dir_of(tmp_path, "linear", "baseline-linear", [q1_row("a", "correct")],
                        **tables_cfg)
    stopped = run_dir_of(tmp_path, "stopped", "p3-typed", [q1_row("a", "correct")],
                         status="stopped_calls", **tables_cfg)
    repeats = run_dir_of(tmp_path, "repeats", "p3-typed",
                         [q1_row("a", "correct"), q1_row("a", "correct", repeat=1)],
                         **tables_cfg)
    for run, what in ((stopped, "Q2 compares complete runs"),
                      (repeats, "Q2 compares repeat 0 of single-repeat runs")):
        with pytest.raises(RunError, match=what) as e:
            q2_compare(run, linear)
        assert "Q1" not in str(e.value)
    base = run_dir_of(tmp_path, "base", "baseline-linear", [q1_row("a", "correct")])
    for run, what in ((stopped, "Q1 compares complete runs"),
                      (repeats, "Q1 compares repeat 0 of single-repeat runs")):
        with pytest.raises(RunError, match=what) as e:
            q1_compare(run, base)
        assert "Q2" not in str(e.value)


def _keys_and_strings(x, keys, strings):
    if isinstance(x, dict):
        for k, v in x.items():
            keys.add(k)
            _keys_and_strings(v, keys, strings)
    elif isinstance(x, list):
        for v in x:
            _keys_and_strings(v, keys, strings)
    elif isinstance(x, str):
        strings.add(x)
    return keys, strings


def test_q1_summary_holds_no_item_id_and_no_filter_value(tmp_path):
    """The committed form of Q1: counts, accuracies, McNemar, each typed miss by its cause and
    the shape of its query, baseline misses as counts, also_in readings without ids or
    values. No item id and no filter value anywhere."""
    member = {"store": "typed_db", "op": "list", "entities": ["topic_x"], "as_of": None,
              "filters": {"also_in__contains": "topic_x", "status": "downloaded"}}
    typed_dir = run_dir_of(tmp_path, "typed", "p3-typed", [
        {**q1_row("item-a", "wrong", value=["p1", "p2", "p3"], exec_match=False),
         "generated_query": member},
        q1_row("item-b", "correct"), q1_row("item-c", "correct"),
        q1_row("item-only-typed", "correct")])
    base_dir = run_dir_of(tmp_path, "base", "baseline-linear", [
        q1_row("item-a", "wrong", exec_match=False), q1_row("item-b", "wrong"),
        q1_row("item-c", "abstained"), q1_row("item-only-base", "correct")])
    c = q1_compare(typed_dir, base_dir)
    c["also_in"] = [{"item_id": "item-a", "split": "test", "op": "list", "also_in": "topic_x",
                     "wording": "membership", "string": 2, "membership": 3, "differs": True}]
    s = q1_summary(c)
    keys, strings = _keys_and_strings(s, set(), set())
    assert "item_id" not in keys and "also_in" in keys
    assert not any(x.startswith("item-") for x in strings)
    assert not strings & {"topic_x", "downloaded", "Rule", "p1"}
    assert {k: s[k] for k in ("n", "b", "c", "mcnemar_p", "only_typed", "only_baseline")} == \
        {"n": 3, "b": 2, "c": 0, "mcnemar_p": mcnemar_exact(2, 0), "only_typed": 1,
         "only_baseline": 1}
    assert s["typed"] == c["typed"] and s["baseline"] == c["baseline"]
    assert s["misses"] == [{
        "outcome": "wrong", "cause": c["misses"][0]["cause"], "query_exec_match": False,
        "typed_error": None, "value": {"n": 3},
        "query": {"store": "typed_db", "op": "list",
                  "filter_keys": ["also_in__contains", "status"]}}]
    assert s["baseline_misses"] == [
        {"outcome": "abstained", "cause": "abstained", "query_exec_match": True, "n": 1},
        {"outcome": "wrong", "cause": "the answer from retrieved chunks",
         "query_exec_match": False, "n": 1},
        {"outcome": "wrong", "cause": "the answer from retrieved chunks",
         "query_exec_match": True, "n": 1}]
    assert s["also_in"] == [{"split": "test", "op": "list", "wording": "membership",
                             "string": 2, "membership": 3, "differs": True}]
    assert q1_summary({**c, "misses": [{**c["misses"][0], "generated_query": None}]})[
        "misses"][0]["query"] is None


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
    out = tmp_path / "committed" / "q1.json"
    assert main(["p3-q1", str(typed_dir), str(base_dir), "--summary", str(out)]) == 0
    capsys.readouterr()
    summary = json.loads(out.read_text())
    assert summary == q1_summary(written) and "item_id" not in out.read_text()


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
        item("r1", "How many are also cited by t1?", gq("count", {"also_in": "t1"}),
             Answer(kind="number", value=1.0)),
        item("r2", "?", gq("list", {"also_in": "t1", "venue": "arXiv"}),
             Answer(kind="set", value=["p1"]), split="dev"),
        item("r3", 'How many have an also_in value of exactly "t1;t2"?',
             gq("count", {"also_in": "t1;t2"}), Answer(kind="number", value=2.0)),
        item("r4", "?", gq("count", {"venue": "arXiv"}), Answer(kind="number", value=3.0)),
        item("r5", "?", gq("count", {"also_in": "t1"}), Answer(kind="number", value=1.0),
             qtype="factoid"),
    ]
    out = also_in_readings(items, records)
    assert out == [
        {"item_id": "r1", "split": "test", "op": "count", "also_in": "t1",
         "wording": "membership", "string": 1, "membership": 4, "differs": True},
        {"item_id": "r2", "split": "dev", "op": "list", "also_in": "t1",
         "wording": "membership", "string": 1, "membership": 2, "differs": True},
        {"item_id": "r3", "split": "test", "op": "count", "also_in": "t1;t2",
         "wording": "value", "string": 2, "membership": 3, "differs": True},
    ]
