"""The gov-tables v0.1 golden generator (Phase 3 spec §10.3, ruling P9; Task 10): queries drawn by
code from the second-pass facts (bool, range and `__isnull` clauses beside v0.1's), answered by
code over the facts of the version in force, phrased by a model (one call per item, a malformed
reply redraws), evidence re-sliced; the `adr-eval golden tables --gen` command under its call
cap; and the merge gate reading the gov-tables items. Fixture stores under `tmp_path`, cached
stub clients; no model is called and nothing is written under `golden/`."""

import json
import random

import pytest

from adr_eval import llm, runner
from adr_eval.cache import Cache
from adr_eval.cli import main
from adr_eval.golden import tables
from adr_eval.golden.tables import (
    MAX_COUNT,
    MAX_LIST,
    N_ITEMS,
    PROMPT_VERSION,
    SEED,
    TableQuery,
    TablesItem,
    answer_of,
    draw_table_filter,
    fact_fields,
    facts_db,
    generate,
    generate_all,
    load_items,
    phrasing_message,
)
from adr_eval.golden.verify import assign_split
from adr_eval.llm import CachedStubClient
from adr_eval.models import Answer, GoldQuery, write_items
from adr_eval.pipeline import Budget, BudgetExceeded, MeteredClient
from adr_store.tables.build import build_tables
from adr_store.tables.engine import run_query
from adr_store.tables.extract import load_facts, units
from adr_store.tables.gate import gate, gold_cases
from tests.store.tables_fixtures import (
    ECFR_NEW,
    facts_store_at,
    fixture_reply,
    phrase_reply,
)

# rows as the drawbridge_bridges table holds them (structure columns, model columns, nulls)
FACT_ROWS = [
    {"section": "117.821", "version": "2026-06-26", "draw": 1, "state": "North Carolina",
     "waterway": "Cape Fear River", "waterway_key": "cape fear river", "bridge": "Memorial",
     "mile": 26.8, "notice_hours": 4, "opens_on_signal": True, "closed_periods": []},
    {"section": "117.823", "version": "2026-06-26", "draw": 1, "state": "North Carolina",
     "waterway": "Neuse River", "waterway_key": "neuse river", "bridge": "US 17",
     "mile": 2.0, "notice_hours": None, "opens_on_signal": True, "closed_periods": []},
    {"section": "117.823", "version": "2026-06-26", "draw": 2, "state": "North Carolina",
     "waterway": "Neuse River", "waterway_key": "neuse river", "bridge": "Norfolk Southern",
     "mile": 3.1, "notice_hours": None, "opens_on_signal": False,
     "closed_periods": ["7 a.m. to 9 a.m."]},
    {"section": "117.823", "version": "2026-06-26", "draw": 3, "state": "North Carolina",
     "waterway": "Neuse River", "waterway_key": "neuse river", "bridge": "NC 55",
     "mile": 4.5, "notice_hours": 12, "opens_on_signal": True, "closed_periods": []},
    {"section": "117.827", "version": "2026-06-26", "draw": 1, "state": "North Carolina",
     "waterway": "Atlantic Intracoastal Waterway", "waterway_key": "aiww", "bridge": "Surf City",
     "mile": 260.7, "notice_hours": None, "opens_on_signal": True, "closed_periods": []},
    {"section": "117.261", "version": "2026-06-26", "draw": 1, "state": "Florida",
     "waterway": "Atlantic Intracoastal Waterway", "waterway_key": "aiww", "bridge": "Lake Worth",
     "mile": 1014.0, "notice_hours": None, "opens_on_signal": False,
     "closed_periods": ["8 a.m. to 6 p.m. on weekends"]},
    {"section": "117.263", "version": "2026-06-26", "draw": 1, "state": "Florida",
     "waterway": "Atlantic Intracoastal Waterway", "waterway_key": "aiww", "bridge": "Venetian",
     "mile": 1088.5, "notice_hours": 2, "opens_on_signal": None, "closed_periods": []},
]
N = 10   # items in the stub runs: ids 005 and 007 are dev, the other eight test


def clause_kinds(filters: dict) -> set[str]:
    """The kind of each clause: "isnull", "range" (`__gte` and `__lte` on one column), "bound"
    (one of them alone), "contains", "bool" (equality with true or false) or "eq"."""
    kinds = set()
    for key, value in filters.items():
        column, _, op = key.rpartition("__") if "__" in key else (key, "", "")
        if op == "isnull":
            kinds.add("isnull")
        elif op in ("gte", "lte"):
            other = f"{column}__{'lte' if op == 'gte' else 'gte'}"
            kinds.add("range" if other in filters else "bound")
        elif op == "contains":
            kinds.add("contains")
        elif isinstance(value, bool):
            kinds.add("bool")
        else:
            kinds.add("eq")
    return kinds


def stub_of(tmp_path, fn=phrase_reply, name="llm", model="stub-phrase", **kw):
    return CachedStubClient(model, Cache(tmp_path / name), fn, **kw)


@pytest.fixture
def facts_env(tmp_path):
    store, facts_id = facts_store_at(tmp_path / "store")
    return {"store": store, "facts_id": facts_id,
            "db": facts_db(store.path, load_facts(store.path, facts_id), units(store))}


@pytest.fixture
def facts_db_fixture(facts_env):
    return facts_env["db"]


def key_of(item: TablesItem) -> str:
    q = item.query
    return json.dumps([q.table, q.op, q.filters, q.field], sort_keys=True)


# -- the drawer --------------------------------------------------------------------------------


def test_fact_fields_add_bool_real_and_nullable_and_skip_structure_columns():
    fields = fact_fields(FACT_ROWS)
    assert ("mile", "real") in fields and ("opens_on_signal", "bool") in fields
    assert ("notice_hours", "int") in fields and ("notice_hours", "nullable") in fields
    assert ("opens_on_signal", "nullable") in fields and ("state", "str") in fields
    assert ("closed_periods", "list") in fields
    assert ("mile", "nullable") not in fields          # never null here
    assert not {f for f, _ in fields} & {"section", "version", "draw", "waterway_key", "bridge"}


def test_draws_cover_bool_range_and_isnull_clauses():
    rng = random.Random(SEED)
    kinds: set[str] = set()
    fields = fact_fields(FACT_ROWS)
    for _ in range(300):
        d = draw_table_filter(FACT_ROWS, fields, rng)
        if d:
            kinds |= clause_kinds(d[0])
    assert {"bool", "range", "isnull"} <= kinds


def test_each_draw_comes_from_one_row_and_a_lookup_names_a_numeric_or_bool_field():
    rng = random.Random(SEED)
    fields = fact_fields(FACT_ROWS)
    ops = set()
    for _ in range(300):
        d = draw_table_filter(FACT_ROWS, fields, rng)
        if d is None:
            continue
        filters, op, field = d
        ops.add(op)
        # one or two clauses (a range is one clause with two keys), on distinct columns
        assert 1 <= len({k.split("__")[0] for k in filters}) <= 2 and len(filters) <= 3
        assert list(filters) == sorted(filters)
        assert (field is not None) == (op == "lookup")
        if op == "lookup":
            assert {k for f, k in fields if f == field} & {"int", "real", "bool"}
            assert all(not k.startswith(field) for k in filters)
        for key, value in filters.items():   # the values are a row's (a range spans two rows)
            column, _, how = key.partition("__")
            seen = {r[column] for r in FACT_ROWS if not isinstance(r[column], list)}
            if how == "isnull":
                assert value in (True, False)
            elif how == "contains":
                assert any(value in r[column] for r in FACT_ROWS)
            else:
                assert value in seen
    assert ops == {"count", "list", "lookup"}


def test_draws_are_deterministic_for_a_seed():
    fields = fact_fields(FACT_ROWS)
    a, b = random.Random(7), random.Random(7)
    assert [draw_table_filter(FACT_ROWS, fields, a) for _ in range(50)] == \
        [draw_table_filter(FACT_ROWS, fields, b) for _ in range(50)]


# -- answers -----------------------------------------------------------------------------------


def test_answers_are_computed_by_code_over_the_facts(facts_db_fixture):
    q = TableQuery(table="drawbridge_bridges", op="count",
                   filters={"state": "North Carolina", "notice_hours__isnull": False})
    assert answer_of(q, facts_db_fixture) == Answer(kind="number", value=2.0)
    q = TableQuery(table="drawbridge_sections", op="list", filters={"state": "Florida"})
    assert answer_of(q, facts_db_fixture) == Answer(kind="set", value=["117.261", "117.263"])
    q = TableQuery(table="drawbridge_bridges", op="lookup", filters={"mile": 26.8},
                   field="notice_hours")    # the version in force says four hours, not two
    assert answer_of(q, facts_db_fixture) == Answer(kind="number", value=4.0)


def test_the_facts_db_holds_the_version_in_force_only(facts_db_fixture):
    for table, n in (("drawbridge_sections", 7), ("drawbridge_bridges", 7)):
        rows = facts_db_fixture.execute(f"SELECT version FROM {table}")
        assert len(rows) == n and {v for (v,) in rows} == {ECFR_NEW}


def test_bool_lookups_are_yes_no_ids(facts_db_fixture):
    q = TableQuery(table="drawbridge_bridges", op="lookup", filters={"mile": 3.1},
                   field="opens_on_signal")
    assert answer_of(q, facts_db_fixture) == Answer(kind="id", value="no",
                                                    accepted_variants=["false"])
    q = TableQuery(table="drawbridge_bridges", op="lookup", filters={"mile": 26.8},
                   field="opens_on_signal")
    assert answer_of(q, facts_db_fixture) == Answer(kind="id", value="yes",
                                                    accepted_variants=["true"])
    q = TableQuery(table="drawbridge_sections", op="lookup", filters={"section": "117.261"},
                   field="seasonal")
    assert answer_of(q, facts_db_fixture).value == "yes"
    two = TableQuery(table="drawbridge_bridges", op="lookup", filters={"waterway": "Neuse River"},
                     field="opens_on_signal")       # three draws: no single row
    with pytest.raises(ValueError, match="3 rows"):
        answer_of(two, facts_db_fixture)


def test_a_table_query_maps_its_field_to_fields():
    q = TableQuery(table="drawbridge_bridges", op="lookup", filters={"mile": 3.1},
                   field="opens_on_signal")
    assert q.to_kwargs() == {"table": "drawbridge_bridges", "filters": {"mile": 3.1},
                             "op": "lookup", "fields": ["opens_on_signal"]}
    c = TableQuery(table="drawbridge_sections", op="count", filters={"seasonal": True})
    assert c.to_kwargs() == {"table": "drawbridge_sections", "filters": {"seasonal": True},
                             "op": "count"}
    again = TableQuery.model_validate_json(c.model_dump_json())   # a bool stays a bool
    assert again.filters["seasonal"] is True
    n = TableQuery.model_validate_json(q.model_dump_json())
    assert type(n.filters["mile"]) is float


# -- generation --------------------------------------------------------------------------------


def test_generate_with_a_stub_phrases_splits_and_reslices(tmp_path, facts_env):
    store, facts_id, db = facts_env["store"], facts_env["facts_id"], facts_env["db"]
    stub = stub_of(tmp_path)
    items = generate(store.path, facts_id, stub, n=N)
    assert [i.id for i in items] == [f"gov-tables-{k:03d}" for k in range(1, N + 1)]
    assert stub.calls == N                       # one phrasing call per item, no check call
    assert len({key_of(i) for i in items}) == N  # no duplicates
    assert {i.query.table for i in items} == {"drawbridge_sections", "drawbridge_bridges"}
    for i in items:
        assert i.split == assign_split(i.id)
        assert (i.corpus, i.snapshot, i.facts) == ("gov-tables", store.snapshot_id, facts_id)
        assert i.qtype == i.query.op and i.status == "auto_verified"
        assert i.answer == answer_of(i.query, db)  # computed by code over the facts
        if i.query.op == "count":
            assert 0 < i.answer.value <= MAX_COUNT
        if i.query.op == "list":
            assert 0 < len(i.answer.value) <= MAX_LIST
        assert i.question == "Phrase: " + " | ".join(
            line for line in phrasing_message(i.query).splitlines()
            if line.startswith(("Table:", "Operation:", "Filters:", "Field:")))
        assert i.evidence
        for ev in i.evidence:                  # every quote re-slices the document text
            assert store.text(ev.doc_id)[ev.char_start:ev.char_end] == ev.quote
        assert i.provenance.model == "stub-phrase" and i.provenance.seed == SEED
        assert i.provenance.prompt_hash == tables.prompt_hash()
        g = i.as_golden()
        assert g.qtype == "count_filter" and g.corpus == "gov-tables" and g.id == i.id
        assert g.gold_query == GoldQuery(store="typed_db", op=i.query.op)
        assert (g.answer, g.evidence, g.split, g.question) == \
            (i.answer, i.evidence, i.split, i.question)
    assert [i.split for i in items].count("dev") == 2
    again = generate(store.path, facts_id, stub, n=N)   # cached: the same items, no call
    assert again == items and stub.calls == N


def test_the_prompt_names_its_version_and_the_message_its_query():
    assert PROMPT_VERSION in tables.load_prompt() and N_ITEMS == 120
    q = TableQuery(table="drawbridge_bridges", op="lookup", filters={"mile": 3.1},
                   field="opens_on_signal")
    msg = phrasing_message(q)
    assert "Table: drawbridge_bridges" in msg and "Operation: lookup" in msg
    assert 'Filters: {"mile": 3.1}' in msg and "Field: opens_on_signal" in msg
    assert "- mile (real): Waterway mile of the bridge" in msg
    assert "- opens_on_signal (bool):" in msg


def test_a_malformed_phrasing_is_redrawn(tmp_path, facts_env):
    store, facts_id = facts_env["store"], facts_env["facts_id"]
    bad: list[str] = []

    def fn(system, user, repeat):
        if not bad or user == bad[0]:
            bad.append(user)
            return "Sure! Here is the question: how many bridges?"
        return phrase_reply(system, user, repeat)

    stub = stub_of(tmp_path, fn)
    res = generate_all(store.path, facts_id, stub, n=5)
    assert len(res.items) == 5 and stub.calls == 6
    assert bad[0] not in {phrasing_message(i.query) for i in res.items}   # not phrased later
    assert [r["reason"] for r in res.rejected].count("malformed phrasing") == 1
    assert res.counts["calls"] == {"made": 6, "cached": 0, "failed": 0}
    rerun = generate_all(store.path, facts_id, stub, n=5)   # the cached reply redraws again
    assert rerun.items == res.items and rerun.rejected == res.rejected and stub.calls == 6
    assert rerun.counts["calls"] == {"made": 0, "cached": 6, "failed": 0}


def test_a_reply_without_a_question_is_malformed(tmp_path, facts_env):
    replies = iter(['{"question": ""}', '{"q": "x"}'])

    def fn(system, user, repeat):
        return next(replies, None) or phrase_reply(system, user, repeat)

    res = generate_all(facts_env["store"].path, facts_env["facts_id"], stub_of(tmp_path, fn),
                       n=3)
    assert len(res.items) == 3
    assert [r["reason"] for r in res.rejected].count("malformed phrasing") == 2


def test_rejected_draws_are_named_with_their_reason(tmp_path, facts_env, monkeypatch):
    monkeypatch.setattr(tables, "MAX_COUNT", 1)    # every count of two or more is rejected
    res = generate_all(facts_env["store"].path, facts_env["facts_id"], stub_of(tmp_path), n=N)
    reasons = {r["reason"] for r in res.rejected}
    assert f"count over {1}" in reasons and "lookup matches more than one row" in reasons
    assert all(i.answer.value <= 1 for i in res.items if i.query.op == "count")
    assert all(set(r) == {"table", "op", "filters", "field", "reason"} for r in res.rejected)
    c = res.counts                             # every draw is accounted for
    assert (c["items"], c["rejected"]) == (len(res.items), len(res.rejected))
    assert c["draws"] == c["unusable"] + c["duplicates"] + c["rejected"] + c["items"]


def test_an_input_rejection_is_cached_and_redrawn(tmp_path, facts_env):
    rejected: list[str] = []

    def fn(system, user, repeat):
        if not rejected:
            rejected.append(user)
            raise llm.InputRejected("HTTP 400: bad input")
        return phrase_reply(system, user, repeat)

    stub = stub_of(tmp_path, fn)
    res = generate_all(facts_env["store"].path, facts_env["facts_id"], stub, n=4)
    assert len(res.items) == 4 and stub.calls == 5
    assert [r["reason"] for r in res.rejected].count("input rejected") == 1
    rerun = generate_all(facts_env["store"].path, facts_env["facts_id"], stub, n=4)
    assert rerun.items == res.items and stub.calls == 5      # the failure is cached
    assert rerun.counts["calls"]["failed"] == 1


@pytest.mark.parametrize("error", [llm.RetriesExhausted("giving up after 5 retries: limit"),
                                   llm.ModelError("cannot run 'claude'")])
def test_a_failure_that_is_no_input_rejection_stops_generation(tmp_path, facts_env, error):
    def fn(system, user, repeat):
        raise error

    stub = stub_of(tmp_path, fn)
    with pytest.raises(type(error)):
        generate_all(facts_env["store"].path, facts_env["facts_id"], stub, n=3)
    stub.fn = phrase_reply      # nothing was cached: the next run calls again and completes
    assert len(generate_all(facts_env["store"].path, facts_env["facts_id"], stub, n=3).items) == 3


def test_generation_stops_at_its_cap_and_resumes_from_the_cache(tmp_path, facts_env):
    store, facts_id = facts_env["store"], facts_env["facts_id"]
    stub = stub_of(tmp_path)

    def metered(cap):
        return MeteredClient(stub, Budget(None, cap, count_attempts=True), {})

    with pytest.raises(BudgetExceeded):
        generate_all(store.path, facts_id, metered(4), n=N)
    assert stub.calls == 4
    full = generate_all(store.path, facts_id, metered(N - 4), n=N)   # resumes: 4 cached
    assert len(full.items) == N and stub.calls == N
    again = generate_all(store.path, facts_id, metered(0), n=N)      # all cached: no call
    assert again.items == full.items and stub.calls == N


def test_retries_count_against_the_cap(tmp_path, facts_env):
    fails = {"n": 0}

    def flaky(system, user, repeat):
        if fails["n"] < 2:
            fails["n"] += 1
            raise llm._Retryable("overloaded")
        return phrase_reply(system, user, repeat)

    stub = stub_of(tmp_path, flaky, max_retries=5)
    budget = Budget(None, 3, count_attempts=True)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(llm.time, "sleep", lambda s: None)
        with pytest.raises(BudgetExceeded):
            generate_all(facts_env["store"].path, facts_env["facts_id"],
                         MeteredClient(stub, budget, {}), n=3)
    assert budget.calls == 3 and stub.calls == 3   # two failed attempts and one reply


def test_load_items_reads_what_write_items_wrote(tmp_path, facts_env):
    items = generate(facts_env["store"].path, facts_env["facts_id"], stub_of(tmp_path), n=4)
    tables.write_items(tmp_path / "out", items, [{"table": "t", "op": "count", "filters": {},
                                                  "field": None, "reason": "count over 50"}])
    assert load_items(tmp_path / "out" / "items.jsonl") == items
    lines = (tmp_path / "out" / "items.jsonl").read_text().splitlines()
    assert [json.loads(x)["id"] for x in lines] == [i.id for i in items]
    assert json.loads((tmp_path / "out" / "rejected.jsonl").read_text())["reason"] == \
        "count over 50"


# -- the command ---------------------------------------------------------------------------------


def _stub_profiles(monkeypatch, tmp_path, fn):
    made = []

    def make_client(name, profiles, cache, max_retries=5):
        made.append(name)
        return CachedStubClient(f"stub-{name}", Cache(tmp_path / "llm"), fn)

    monkeypatch.setattr(runner, "make_client", make_client)
    return made


def golden(capsys, *args) -> tuple[int, str, str]:
    code = main(["golden", "tables", *map(str, args)])
    out, err = capsys.readouterr()
    return code, out, err


def test_golden_tables_gen_stops_at_its_cap_then_writes(tmp_path, facts_env, monkeypatch,
                                                        capsys):
    monkeypatch.setattr(tables, "N_ITEMS", 6)
    made = _stub_profiles(monkeypatch, tmp_path, phrase_reply)
    store, facts_id = facts_env["store"], facts_env["facts_id"]
    out_dir = tables.GOLDEN_DIR                # a fresh directory per test (conftest)
    assert out_dir != runner.REPO_ROOT / "golden" / "gov-tables" / "v0.1"
    args = ("--gen", "--store", store.path, "--facts", facts_id, "--generator",
            "claude_code_sonnet")
    code, out, err = golden(capsys, *args, "--max-calls", 4)
    assert code == 1, err
    assert "stopped at --max-calls 4 (4 budget unit(s) used); nothing written" in out
    assert not out_dir.exists() and made == ["claude_code_sonnet"]
    code, out, err = golden(capsys, *args, "--max-calls", 2)
    assert code == 0, err
    assert "6 items (1 dev, 5 test)" in out and "2 model call(s) made, 4 cached" in out
    items = load_items(out_dir / "items.jsonl")
    assert len(items) == 6 and all(i.facts == facts_id for i in items)
    assert (out_dir / "rejected.jsonl").is_file()
    data = (out_dir / "items.jsonl").read_bytes()
    code, out, err = golden(capsys, *args, "--max-calls", 0)   # frozen
    assert code == 2 and "--overwrite" in err
    code, out, err = golden(capsys, *args, "--max-calls", 0, "--overwrite")
    assert code == 0, err
    assert "0 model call(s) made, 6 cached" in out
    assert (out_dir / "items.jsonl").read_bytes() == data         # byte-identical rebuild


def test_golden_tables_gen_stops_on_a_failure_that_is_no_input_rejection(
        tmp_path, facts_env, monkeypatch, capsys):
    def fn(system, user, repeat):
        raise llm.RetriesExhausted("giving up after 5 retries: usage limit")

    _stub_profiles(monkeypatch, tmp_path, fn)
    code, out, err = golden(capsys, "--gen", "--store", facts_env["store"].path, "--facts",
                            facts_env["facts_id"], "--generator", "claude_code_sonnet",
                            "--max-calls", 10)
    assert code == 1, err
    assert "status: stopped: giving up after 5 retries: usage limit (" in out
    assert "budget unit(s) used); nothing written" in out
    assert not tables.GOLDEN_DIR.exists()


def test_golden_tables_gen_refuses_an_unknown_facts_id(tmp_path, facts_env, monkeypatch,
                                                       capsys):
    _stub_profiles(monkeypatch, tmp_path, phrase_reply)
    code, out, err = golden(capsys, "--gen", "--store", facts_env["store"].path, "--facts",
                            "0" * 64, "--generator", "claude_code_sonnet", "--max-calls", 1)
    assert code == 2 and "no second-pass file" in err


@pytest.mark.parametrize("argv", [
    ["golden", "tables", "--gen", "--facts", "f", "--generator", "g", "--max-calls", "1"],
    ["golden", "tables", "--gen", "--store", "s", "--generator", "g", "--max-calls", "1"],
    ["golden", "tables", "--gen", "--store", "s", "--facts", "f", "--max-calls", "1"],
    ["golden", "tables", "--gen", "--store", "s", "--facts", "f", "--generator", "g"],
    ["golden", "tables", "--gen", "--store", "s", "--facts", "f", "--generator", "g",
     "--max-calls", "1", "--judge", "j"],
    ["golden", "tables", "--verify"],
    ["golden", "gov", "--gen", "--store", "s"],
    ["golden", "gov", "--gen", "--facts", "f"],
])
def test_golden_tables_takes_its_own_arguments(argv, capsys):
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code == 2


# -- the merge gate reads gov-tables items ----------------------------------------------------


def test_gold_cases_read_gov_tables_items_and_the_gate_scores_them(tmp_path, facts_env):
    store, facts_id, db = facts_env["store"], facts_env["facts_id"], facts_env["db"]
    items = generate(store.path, facts_id, stub_of(tmp_path), n=N)
    yes = TableQuery(table="drawbridge_bridges", op="lookup", filters={"mile": 26.8},
                     field="opens_on_signal")
    lookup = items[0].model_copy(update={"id": "gov-tables-900", "qtype": "lookup",
                                         "query": yes, "answer": answer_of(yes, db)})
    path = tmp_path / "gold" / "items.jsonl"
    path.parent.mkdir()
    tables.write_items(path.parent, [*items, lookup], [])
    cases = gold_cases(path, "gov")
    assert [c[0] for c in cases] == [i.id for i in [*items, lookup]]
    for (_, kwargs, expected), i in zip(cases, [*items, lookup], strict=True):
        assert kwargs == i.query.to_kwargs()
        if i.answer.kind == "id":
            assert expected is (i.answer.value == "yes")
        else:
            assert expected == i.answer.value
    assert cases[-1][2] is True
    assert gold_cases(path, "research") == []
    # the first pass extracted the same facts, so its build answers every case
    stub = CachedStubClient("stub-sonnet", Cache(tmp_path / "llm-first"), fixture_reply)
    tables_id = build_tables(store.path, "gov", with_extraction=True, client=stub,
                             max_calls=100).tables_id
    r = gate(store.path, tables_id, cases, 0)
    assert r.promoted and r.right_candidate == len(cases) == N + 1


def test_gold_cases_read_a_file_mixing_v01_and_gov_tables_items(tmp_path, facts_env,
                                                                 make_item):
    items = generate(facts_env["store"].path, facts_env["facts_id"], stub_of(tmp_path), n=2)
    v01 = make_item(id="gov-count_filter-001", corpus="gov", qtype="count_filter",
                    answer=Answer(kind="number", value=3.0), evidence=[],
                    gold_query=GoldQuery(store="typed_db", op="count", filters={"type": "Rule"}))
    path = tmp_path / "mixed.jsonl"
    write_items(path, [v01])
    with path.open("a", encoding="utf-8") as f:
        for i in items:
            f.write(i.model_dump_json() + "\n")
    cases = gold_cases(path, "gov")
    assert [c[0] for c in cases] == ["gov-count_filter-001", *(i.id for i in items)]
    assert cases[0][1] == {"table": "fr_documents", "filters": {"type": "Rule"}, "op": "count"}


# -- fix round 1 ---------------------------------------------------------------------------------


def test_a_single_match_lookup_is_generated_end_to_end(tmp_path, facts_env):
    """Generation yields lookups (numeric and yes / no) whose one matching row is the sampled
    row: the answer is that row's field, its quote is in the evidence, and the gate case
    expects the value `query_table` returns."""
    store, db = facts_env["store"], facts_env["db"]
    items = generate(store.path, facts_env["facts_id"], stub_of(tmp_path), n=40)
    lookups = [i for i in items if i.qtype == "lookup"]
    assert {i.answer.kind for i in lookups} == {"number", "id"}
    for i in lookups:
        q = i.query
        rows = db.execute(f"SELECT count(*) FROM {q.table}")   # the table is not empty
        assert rows[0][0] > 1
        assert answer_of(q, db) == i.answer and q.field not in {
            k.split("__")[0] for k in q.filters}
        out = run_query(db, q.table, q.filters, "lookup", fields=[q.field])
        assert len(out.rows) == 1                 # exactly one row matches
        prov = out.rows[0]["prov"][q.field]
        assert {(e.char_start, e.char_end) for e in i.evidence} >= {(prov["start"], prov["end"])}
        assert out.value == tables.expected_value(i)
    path = tmp_path / "gold.jsonl"
    path.write_text("".join(i.model_dump_json() + "\n" for i in lookups))
    assert [c[2] for c in gold_cases(path, "gov")] == [tables.expected_value(i) for i in lookups]


def test_facts_without_an_applicability_overlay_are_refused(tmp_path):
    from adr_store import applicability as ap
    from adr_store.tables.overlay import TablesError

    store, facts_id = facts_store_at(tmp_path / "store")
    ap.overlay_path(store.path, store.snapshot_id).unlink()
    with pytest.raises(TablesError, match="no applicability overlay"):
        facts_db(store.path, load_facts(store.path, facts_id), units(store))
    with pytest.raises(TablesError, match="no applicability overlay"):
        generate(store.path, facts_id, stub_of(tmp_path), n=1)
