"""The tables mode of the harness (Phase 3 spec §10.3, §11, rulings P16, P21; Task 10): gov-tables
runs of `p3-typed` (the generated table query through `query_table`) and `baseline-linear`
(answers from retrieved chunks), one shared query-generation prompt so one query call serves
both, no judge, proxy or self-consistency call, exact scoring; every transport attempt counted
against `--max-calls`, and a stop at the cap or on a failure that is no input rejection writes
nothing. A gov fixture store under `tmp_path` (33 CFR 117 fixture versions and Federal Register
documents, extraction tables promoted, ACL synced, second-pass facts written), gov-tables items
generated with a stub; nothing reads `data/` or `.cache/`, and no model is called."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from adr_eval import llm, runner
from adr_eval.answer._prompts import load_prompt
from adr_eval.answer.query_gen import generate_table_query
from adr_eval.cache import Cache
from adr_eval.cli import main
from adr_eval.golden import tables
from adr_eval.golden.tables import TableQuery, describe_text, generate
from adr_eval.llm import CachedStubClient, StubClient
from adr_eval.models import Answer
from adr_eval.pipeline import BudgetExceeded
from adr_eval.report import build_report
from adr_eval.runner import RunError
from adr_eval.scoring.exact import exact_outcome
from adr_store import acl, tools
from adr_store.tables.build import build_tables
from adr_store.tables.gate import gate
from tests.store.tables_fixtures import facts_store_at, fixture_reply, loaded_of, phrase_reply

N = 10   # items: 005 and 007 are dev, the other eight test
N_TEST = 8
QUERY_PROMPT = load_prompt("query_gen_tables")
ANSWER_PROMPT = load_prompt("answer")


def never(system, user, repeat):
    raise AssertionError("a tables run called the judge")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A gov store at `<p2_store_dir>/gov` with extraction tables promoted and a fresh ACL sync;
    the runner reads its documents as the gov corpus and N gov-tables items generated from its
    second-pass facts."""
    path = tmp_path / "store-p2" / "gov"
    store, facts_id = facts_store_at(path)
    tools.Tools(path).index("p1-struct", lexical_only=True)
    first = CachedStubClient("stub-sonnet", Cache(tmp_path / "llm-first"), fixture_reply)
    tables_id = build_tables(path, "gov", with_extraction=True, client=first,
                             max_calls=100).tables_id
    assert gate(path, tables_id, [], 0).promoted
    acl.sync(path)   # the shipped directory and policy, the real clock: fresh for an hour
    items = generate(path, facts_id, CachedStubClient("stub-phrase", Cache(tmp_path / "llm-p"),
                                                      phrase_reply), n=N)
    tables.write_items(tables.GOLDEN_DIR, items, [])
    loaded = loaded_of(store)
    monkeypatch.setattr(runner, "load_checked_corpus", lambda corpus: loaded)
    config = {**runner.load_config(), "p2_store_dir": str(tmp_path / "store-p2"),
              "p2_caller": "user:auditor", "cache_dir": str(tmp_path / "llm"),
              "index_dir": str(tmp_path / "index"), "concurrency": 2}
    return {"config": config, "items": items, "store": path, "tables_id": tables_id,
            "facts_id": facts_id, "out": tmp_path / "runs", "tmp": tmp_path}


def harness_fn(items, queries=None, answers=None, fail=None):
    """Replies to the tables query prompt with the item's gold query (or `queries[id]`) and to
    the answer prompt with its gold answer (or `answers[id]`); `fail(item)` may raise."""
    by_q = {i.question: i for i in items}

    def fn(system, user, repeat):
        question, _ = runner._question_key(user)
        item = by_q[question]
        if fail is not None:
            fail(item, system)
        if system == QUERY_PROMPT:
            q = (queries or {}).get(item.id, item.query)
            return q if isinstance(q, str) else q.model_dump_json()
        assert system == ANSWER_PROMPT, "an unexpected prompt"
        value = (answers or {}).get(item.id, item.answer.value)
        return json.dumps({"answer": value, "kind": item.answer.kind, "citations": [],
                           "abstain": False, "confidence": 1.0})

    return fn


def stub(env, fn, name="llm-gen", model="stub-gen", **kw) -> CachedStubClient:
    return CachedStubClient(model, Cache(env["tmp"] / name), fn, **kw)


PRICED = "claude-sonnet-5-5"   # a model with a price: a profile-built client needs one


def tables_run(env, system, gen, split="test", **kw) -> Path:
    run_id = runner.run("gov", system, split, 1, env["config"], out_root=env["out"],
                        qtypes=("count_filter",), golden="gov-tables", generator=gen,
                        judge=StubClient(never), **kw)
    return env["out"] / run_id


def load_rows(run_dir: Path) -> list[dict]:
    return [json.loads(x) for x in (run_dir / "results.jsonl").read_text().splitlines()]


def config_json(run_dir: Path) -> dict:
    return json.loads((run_dir / "config.json").read_text())


def test_the_query_message_is_the_describe_text_and_the_question():
    calls = []

    class Capture:
        name = family = model = "capture"

        def complete(self, system, user, *, max_tokens, repeat=0):
            calls.append((system, user, max_tokens, repeat))
            return llm.Completion('{"table": "drawbridge_bridges", "op": "count", '
                                  '"filters": {"state": "Florida"}}', 0, 0, "m", 0.0, False)

    q, _ = generate_table_query("How many?", describe_text(), Capture())
    assert q == TableQuery(table="drawbridge_bridges", op="count", filters={"state": "Florida"})
    system, user, max_tokens, repeat = calls[0]
    assert system == QUERY_PROMPT and user == f"Tables:\n{describe_text()}\n\nQuestion: How many?"
    assert (max_tokens, repeat) == (400, 0)
    text = describe_text()     # the semantic layer's detail of the two drawbridge tables
    assert "drawbridge_sections" in text and "drawbridge_bridges" in text
    assert "Hours of advance notice required to open" in text and "fr_documents" not in text


@pytest.mark.parametrize("reply", ["not json", '{"table": "papers", "op": "count"}',
                                   '{"op": "count"}', '{"table": "drawbridge_bridges", '
                                   '"op": "count_by", "filters": {}}'])
def test_a_malformed_or_invalid_table_query_is_none(reply):
    class Fixed:
        name = family = model = "fixed"

        def complete(self, system, user, *, max_tokens, repeat=0):
            return llm.Completion(reply, 0, 0, "m", 0.0, False)

    assert generate_table_query("Q?", describe_text(), Fixed(), recover=True)[0] is None


def test_one_query_call_serves_both_systems(env):
    gen = stub(env, harness_fn(env["items"]))
    typed = tables_run(env, "p3-typed", gen)
    n = gen.calls
    assert n == N_TEST
    linear = tables_run(env, "baseline-linear", gen)
    assert gen.calls - n == N_TEST          # answers only; the queries were cached
    t_rows, l_rows = load_rows(typed), load_rows(linear)
    assert [r["item_id"] for r in t_rows] == [r["item_id"] for r in l_rows]
    assert [r["generated_query"] for r in t_rows] == [r["generated_query"] for r in l_rows]
    assert all(r["outcome"] == "correct" for r in t_rows + l_rows)
    assert all(r["query_exact"] for r in t_rows)
    for run_dir in (typed, linear):
        cfg = config_json(run_dir)
        assert cfg["golden"].endswith("items.jsonl") and cfg["golden_set"] == "gov-tables"
        assert cfg["facts"] == [env["facts_id"]] and cfg["judge_enabled"] is False
        assert cfg["prompt_hashes"]["query_gen_tables"] == runner.answer_prompt_hash(
            "query_gen_tables")
        assert cfg["status"] == "complete" and cfg["n_items"] == N_TEST
        assert run_dir.name.startswith(f"gov-tables-{cfg['system']}-test-")
        rep = build_report(run_dir)          # a tables run is reportable
        assert rep["end_to_end"]["accuracy"] == 1.0
    assert config_json(typed)["fingerprint"] == env["tables_id"]


def test_tables_runs_never_call_the_judge(env):
    """A wrong number, a right set and right yes/no answers on the chunk path are scored
    exactly: no judge, proxy or self-consistency call, and no judge client is built."""
    items = env["items"]
    test_items = [i for i in items if i.split == "test"]
    wrong = next(i for i in test_items if i.answer.kind == "number")
    gen = stub(env, harness_fn(items, answers={wrong.id: wrong.answer.value + 1}))
    run_dir = tables_run(env, "baseline-linear", gen)
    rows = {r["item_id"]: r for r in load_rows(run_dir)}
    assert len(rows) == N_TEST and gen.calls == 2 * N_TEST     # one query and one answer each
    assert all(r["judge_label"] is None and r["judge_check"] is None for r in rows.values())
    assert rows[wrong.id]["outcome"] == "wrong"
    assert all(r["outcome"] == "correct" for k, r in rows.items() if k != wrong.id)
    cfg = config_json(run_dir)
    assert cfg["judge"] == {"enabled": False} and cfg["same_family_judge"] is None
    rep = build_report(run_dir)
    assert rep["end_to_end"]["accuracy"] == (N_TEST - 1) / N_TEST


def test_tables_runs_build_no_judge_from_the_config(env, monkeypatch):
    made = []

    def make_client(name, profiles, cache, max_retries=5):
        made.append(name)
        return stub(env, harness_fn(env["items"]), model=PRICED)

    monkeypatch.setattr(runner, "make_client", make_client)
    run_id = runner.run("gov", "p3-typed", "test", 1, env["config"], out_root=env["out"],
                        qtypes=("count_filter",), golden="gov-tables")
    assert made == [env["config"]["generator"]]
    assert config_json(env["out"] / run_id)["status"] == "complete"


def test_p3_typed_scores_table_queries_exactly(env):
    items = env["items"]
    tests_ = [i for i in items if i.split == "test"]
    other_op, unknown, garbage = tests_[0], tests_[1], tests_[2]
    flip = "list" if other_op.query.op != "list" else "count"
    queries = {
        other_op.id: other_op.query.model_copy(update={"op": flip, "field": None}),
        unknown.id: TableQuery(table=unknown.query.table, op="count",
                               filters={"colour": "red"}),
        garbage.id: "I cannot answer that.",
    }
    gen = stub(env, harness_fn(items, queries=queries))
    rows = {r["item_id"]: r for r in load_rows(tables_run(env, "p3-typed", gen))}
    assert gen.calls == N_TEST     # query calls only: no answer call
    for i in tests_[3:]:           # the gold query gives the gold answer
        r = rows[i.id]
        assert r["outcome"] == "correct" and r["typed_error"] is None and r["query_exact"]
        assert r["gold_query_field_hits"] == {"table": True, "op": True, "filters": True,
                                              "field": True}
        expected = tables.expected_value(i)    # true / false for a yes / no lookup
        assert r["answer"]["value"] == expected
        assert r["metrics"] is None and r["retrieved"] == []
    r = rows[other_op.id]
    assert r["outcome"] == "wrong" and r["query_exact"] is False
    assert r["gold_query_field_hits"]["op"] is False
    assert r["gold_query_field_hits"]["filters"] is True
    r = rows[unknown.id]
    assert r["outcome"] == "wrong" and r["answer"]["value"] is None
    assert r["typed_error"] == f"unknown column 'colour' in table {unknown.query.table}"
    r = rows[garbage.id]
    assert r["generated_query"] is None and r["outcome"] == "wrong"
    assert r["query_exact"] is False and r["error"] is None


def test_a_bool_lookup_is_scored_as_yes_or_no(env):
    yes = TableQuery(table="drawbridge_bridges", op="lookup", filters={"mile": 26.8},
                     field="opens_on_signal")
    no = TableQuery(table="drawbridge_bridges", op="lookup", filters={"mile": 3.1},
                    field="opens_on_signal")
    test_items = [i for i in env["items"] if i.split == "test"]
    a, b = test_items[0], test_items[1]
    gen = stub(env, harness_fn(env["items"], queries={a.id: yes, b.id: no}))
    rows = {r["item_id"]: r for r in load_rows(tables_run(env, "p3-typed", gen))}
    assert rows[a.id]["answer"]["value"] is True and rows[b.id]["answer"]["value"] is False
    gold_yes = Answer(kind="id", value="yes", accepted_variants=["true"])
    assert exact_outcome(gold_yes, SimpleNamespace(value=True, abstain=False)) == "correct"
    assert exact_outcome(gold_yes, SimpleNamespace(value=False, abstain=False)) == "wrong"


def test_a_tables_run_stops_at_its_cap_and_writes_nothing(env):
    gen = stub(env, harness_fn(env["items"]))
    with pytest.raises(BudgetExceeded, match=r"--max-calls 3 \(3 budget unit"):
        tables_run(env, "p3-typed", gen, max_calls=3)
    assert gen.calls == 3 and not env["out"].exists()       # nothing written
    run_dir = tables_run(env, "p3-typed", gen, max_calls=N_TEST - 3)   # resumes from the cache
    assert gen.calls == N_TEST and config_json(run_dir)["calls"] == N_TEST - 3
    again = tables_run(env, "p3-typed", gen, max_calls=0)    # all cached: no call
    assert gen.calls == N_TEST and config_json(again)["calls"] == 0
    assert config_json(again)["status"] == "complete"
    strip = ("latency_s", "tokens")
    assert [{k: v for k, v in r.items() if k not in strip} for r in load_rows(again)] == \
        [{k: v for k, v in r.items() if k not in strip} for r in load_rows(run_dir)]


def test_retries_count_against_a_tables_run_cap(env, monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    state = {"failed": 0}

    def fail(item, system):
        if state["failed"] < 2:
            state["failed"] += 1
            raise llm._Retryable("overloaded")

    gen = stub(env, harness_fn(env["items"], fail=fail), max_retries=5)
    with pytest.raises(BudgetExceeded):
        tables_run(env, "p3-typed", gen, max_calls=N_TEST)      # 2 retries + 8 replies > 8
    run_dir = tables_run(env, "p3-typed", gen, max_calls=2)
    assert config_json(run_dir)["status"] == "complete"


def test_a_failure_that_is_no_input_rejection_stops_a_tables_run(env):
    def fail(item, system):
        raise llm.RetriesExhausted("giving up after 5 retries: usage limit")

    gen = stub(env, harness_fn(env["items"], fail=fail))
    with pytest.raises(llm.RetriesExhausted):
        tables_run(env, "p3-typed", gen)
    assert not env["out"].exists()
    before = gen.calls
    gen.fn = harness_fn(env["items"])            # nothing was cached: the rerun calls again
    assert config_json(tables_run(env, "p3-typed", gen))["status"] == "complete"
    assert gen.calls - before == N_TEST


def test_an_input_rejection_is_cached_as_an_error_row(env):
    target = next(i for i in env["items"] if i.split == "test")

    def fail(item, system):
        if item.id == target.id:
            raise llm.InputRejected("HTTP 400: prompt too long")

    gen = stub(env, harness_fn(env["items"], fail=fail))
    rows = {r["item_id"]: r for r in load_rows(tables_run(env, "p3-typed", gen))}
    assert rows[target.id]["outcome"] == "error"
    assert rows[target.id]["error"].startswith("query_gen: HTTP 400")
    assert sum(r["outcome"] == "correct" for r in rows.values()) == N_TEST - 1
    again = {r["item_id"]: r for r in load_rows(tables_run(env, "p3-typed", gen, max_calls=0))}
    assert again[target.id]["outcome"] == "error" and gen.calls == N_TEST  # replayed, no call


def test_a_malformed_answer_reply_is_an_error_row_not_a_stop(env):
    target = next(i for i in env["items"] if i.split == "test")
    base = harness_fn(env["items"])

    def fn(system, user, repeat):
        if system == ANSWER_PROMPT and runner._question_key(user)[0] == target.question:
            return "The answer is probably four."
        return base(system, user, repeat)

    rows = {r["item_id"]: r for r in load_rows(tables_run(env, "baseline-linear",
                                                           stub(env, fn)))}
    assert rows[target.id]["outcome"] == "error" and rows[target.id]["error"].startswith(
        "answer:")
    assert sum(r["outcome"] == "correct" for r in rows.values()) == N_TEST - 1


def test_the_dev_split_runs_too(env):
    gen = stub(env, harness_fn(env["items"]))
    rows = load_rows(tables_run(env, "p3-typed", gen, split="dev"))
    assert [r["item_id"] for r in rows] == ["gov-tables-005", "gov-tables-007"]
    assert gen.calls == 2


def test_a_dry_run_counts_the_query_and_answer_calls(env, capsys):
    gen = stub(env, harness_fn(env["items"]))
    tables_run(env, "p3-typed", gen, dry_run=True)
    out = capsys.readouterr().out
    assert f"generator stub-gen: {N_TEST} calls" in out and "judge" not in out
    tables_run(env, "baseline-linear", gen, dry_run=True)
    out = capsys.readouterr().out
    assert f"generator stub-gen: {2 * N_TEST} calls" in out and "judge" not in out
    assert gen.calls == 0 and not env["out"].exists()


def test_gov_tables_runs_refuse_what_they_cannot_run(env, monkeypatch):
    gen = stub(env, harness_fn(env["items"]))
    with pytest.raises(RunError, match="p3-typed answers count_filter items only"):
        runner.run("gov", "p3-typed", "test", 1, env["config"], out_root=env["out"],
                   golden="gov-tables", generator=gen, judge=StubClient(never))
    with pytest.raises(RunError, match="gov-tables is a golden set of the gov corpus"):
        runner.run("research", "baseline-linear", "test", 1, env["config"],
                   out_root=env["out"], golden="gov-tables", generator=gen)
    items_path = tables.GOLDEN_DIR / "items.jsonl"
    text = items_path.read_text()
    first = json.loads(text.splitlines()[0])
    first["evidence"][0]["quote"] = "not in the document"
    items_path.write_text("\n".join([json.dumps(first), *text.splitlines()[1:]]) + "\n")
    with pytest.raises(RunError, match=r"(?s)1 item\(s\).*does not re-slice.*golden tables --gen"):
        tables_run(env, "p3-typed", gen)
    items_path.unlink()
    with pytest.raises(RunError, match="golden tables --gen"):
        tables_run(env, "p3-typed", gen)


def test_p3_typed_refuses_tables_without_the_drawbridge_tables(env):
    tables_id = build_tables(env["store"], "gov").tables_id     # a metadata build only
    assert gate(env["store"], tables_id, [], 10).promoted
    with pytest.raises(RunError, match="drawbridge"):
        tables_run(env, "p3-typed", stub(env, harness_fn(env["items"])))


# -- the command ---------------------------------------------------------------------------------


def run_cli(env, monkeypatch, capsys, *args) -> tuple[int, str, str]:
    monkeypatch.setattr(runner, "load_config", lambda path=runner.CONFIG_PATH: env["config"])
    code = main(["run", "gov", "--golden", "gov-tables", "--qtype", "count_filter",
                 *map(str, args)])
    out, err = capsys.readouterr()
    return code, out, err


def test_adr_eval_run_gov_tables_stops_at_the_cap_then_completes(env, monkeypatch, capsys):
    made = []

    def make_client(name, profiles, cache, max_retries=5):
        made.append(name)
        return stub(env, harness_fn(env["items"]), model=PRICED)

    monkeypatch.setattr(runner, "make_client", make_client)
    code, out, err = run_cli(env, monkeypatch, capsys, "--system", "p3-typed", "--split",
                             "test", "--generator", "claude_code_sonnet", "--max-calls", 5,
                             "--out", env["out"])
    assert code == 1, err
    assert "status: stopped at --max-calls 5 (5 budget unit(s) used); nothing written" in out
    assert not env["out"].exists() and made == ["claude_code_sonnet"]
    code, out, err = run_cli(env, monkeypatch, capsys, "--system", "p3-typed", "--split",
                             "test", "--generator", "claude_code_sonnet", "--max-calls", 3,
                             "--out", env["out"])
    assert code == 0, err
    assert "status complete" in out and f"{N_TEST} rows" in out and "accuracy 1.0" in out
    code, out, err = run_cli(env, monkeypatch, capsys, "--system", "baseline-linear",
                             "--split", "test", "--generator", "claude_code_sonnet",
                             "--max-calls", N_TEST, "--out", env["out"])
    assert code == 0, err
    assert "status complete" in out and "accuracy 1.0" in out


def test_adr_eval_run_gov_tables_stops_on_a_model_failure(env, monkeypatch, capsys):
    def fail(item, system):
        raise llm.RetriesExhausted("giving up after 5 retries: usage limit")

    monkeypatch.setattr(runner, "make_client", lambda name, profiles, cache, max_retries=5:
                        stub(env, harness_fn(env["items"], fail=fail), model=PRICED))
    code, out, err = run_cli(env, monkeypatch, capsys, "--system", "p3-typed", "--generator",
                             "claude_code_sonnet", "--max-calls", 10, "--out", env["out"])
    assert code == 1, err
    assert "status: stopped: giving up after 5 retries" in out and "nothing written" in out
    assert not env["out"].exists()


def test_the_golden_flag_is_parsed(capsys):
    with pytest.raises(SystemExit):
        main(["run", "gov", "--system", "p3-typed", "--golden", "gov-tables-v2"])


def test_a_stub_run_replies_with_the_gold_table_queries(env):
    """`--stub` (tests and demos): the stub generator replies to the table prompt with the
    item's gold query and to the answer prompt with its gold answer."""
    config = {**env["config"], "stub": True}
    for system in ("p3-typed", "baseline-linear"):
        run_id = runner.run("gov", system, "test", 1, config, out_root=env["out"],
                            qtypes=("count_filter",), golden="gov-tables")
        rows = load_rows(env["out"] / run_id)
        assert len(rows) == N_TEST and all(r["outcome"] == "correct" for r in rows), system
        assert config_json(env["out"] / run_id)["count_attempts"] is False
