"""process_repeat with stub clients and a stand-in index (no embedding model)."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from adr_eval.answer._prompts import load_prompt
from adr_eval.llm import StubClient
from adr_eval.models import load_items
from adr_eval.pipeline import Context, entity_f1, process_repeat, route, route_ok
from adr_eval.scoring.judge import Judge

MINI = Path(__file__).parent / "fixtures" / "mini"
ITEMS = {i.id: i for i in load_items(MINI / "golden.jsonl")}


def _twice(first: dict, second: dict) -> str:
    """A self-correcting reply: two JSON objects, the second one meant."""
    return f"{json.dumps(first)}\nCorrection:\n{json.dumps(second)}"


def _generator(double_query: bool, double_answer: bool, value) -> StubClient:
    query_prompt = load_prompt("query_gen")
    q = {"store": "knowledge", "op": "explain", "filters": {}, "entities": [], "as_of": None}
    a = {"answer": value, "kind": "number" if isinstance(value, float) else "text",
         "citations": [], "abstain": False, "confidence": 0.5}

    def fn(system, user, repeat):
        if system == query_prompt:
            return _twice({**q, "op": "lookup"}, q) if double_query else json.dumps(q)
        return _twice({**a, "answer": "draft"}, a) if double_answer else json.dumps(a)

    return StubClient(fn)


def _ctx(generator, judge_reply: str, recover: bool = True) -> Context:
    judge = Judge(StubClient(lambda s, u, r: judge_reply), recover=recover)
    return Context(SimpleNamespace(chunks={}), [], {}, generator, judge)


def test_row_lists_recovered_stages_sorted():
    item = ITEMS["mini-factoid-1"]  # text: judged, plus a self-consistency check at repeat 0
    judge = _twice({"label": "incorrect"}, {"label": "correct", "reason": "ok"})
    row = process_repeat(item, 0, [], _ctx(_generator(True, True, "30 days"), judge))
    assert row["outcome"] == "correct" and row["judge_label"] == "correct"
    assert row["generated_query"]["op"] == "explain" and row["answer"]["value"] == "30 days"
    assert row["judge_check"]["label"] == "correct"
    assert row["json_recovered"] == ["answer", "judge", "judge_check", "query"]


def test_row_json_recovered_empty_for_clean_replies():
    item = ITEMS["mini-count-1"]  # number: exact-scored, proxy judge check at repeat 0
    row = process_repeat(item, 0, [], _ctx(_generator(False, False, 2.0),
                                           json.dumps({"label": "correct"})))
    assert row["outcome"] == "correct" and row["judge_check"]["label"] == "correct"
    assert row["json_recovered"] == []


def test_row_keeps_recovered_stages_before_an_error():
    item = ITEMS["mini-factoid-1"]
    row = process_repeat(item, 1, [], _ctx(_generator(True, False, "30 days"), "not json"))
    assert row["outcome"] == "error" and row["error"].startswith("judge:")
    assert row["json_recovered"] == ["query"]


def test_row_metrics_and_citations_use_the_items_groups():
    from adr_eval.models import Evidence
    from adr_eval.retrieval.chunker import Chunk

    item = ITEMS["mini-factoid-1"]
    copy = Evidence(doc_id="elsewhere", char_start=10, char_end=20, quote="q")
    chunk = Chunk(chunk_id="k", doc_id="elsewhere", char_start=0, char_end=30,
                  text="one two three")
    gen = _generator(False, False, "30 days")
    cited = StubClient(lambda s, u, r: gen.fn(s, u, r).replace('"citations": []',
                                                                '"citations": ["k"]'))
    judge = Judge(StubClient(lambda s, u, r: json.dumps({"label": "correct"})), recover=True)
    groups = {item.id: [[*item.evidence[:1], copy], *([e] for e in item.evidence[1:])]}
    ctx = Context(SimpleNamespace(chunks={"k": chunk}), [], {}, cited, judge, groups)
    row = process_repeat(item, 0, [("k", 1.0)], ctx)
    m = row["metrics"]
    assert m["mrr"] == 1.0 and m["recall@10"] == 1 / len(item.evidence)
    assert m["coverage@10"] == 1 / len(item.evidence) and m["tokens@10"] == 3
    assert row["citation"] == {"precision": 1.0, "evidence_cited": True}
    # without groups on the context, each span is its own group: the copy earns nothing
    plain = process_repeat(item, 0, [("k", 1.0)],
                           Context(SimpleNamespace(chunks={"k": chunk}), [], {}, cited, judge))
    assert plain["metrics"]["mrr"] == 0.0 and plain["citation"]["evidence_cited"] is False


# -- query-understanding scores (route, entities) ---------------------------------------


def _q(store="knowledge", op="lookup", entities=()):
    from adr_eval.models import GoldQuery

    return GoldQuery(store=store, op=op, entities=list(entities))


@pytest.mark.parametrize("store,op,expected", [
    ("typed_db", "lookup", "records:lookup"), ("typed_db", "count", "records:count"),
    ("typed_db", "list", "records:list"), ("typed_db", "explain", "records:explain"),
    ("typed_db", "abstain", "records:abstain"),
    ("knowledge", "lookup", "prose:fact"), ("knowledge", "explain", "prose:fact"),
    ("raw", "lookup", "prose:fact"), ("raw", "explain", "prose:fact"),
    ("knowledge", "procedure", "prose:procedure"), ("raw", "procedure", "prose:procedure"),
    ("knowledge", "abstain", "abstain"), ("raw", "abstain", "abstain"),
    ("knowledge", "count", "prose:count"), ("raw", "list", "prose:list"),
])
def test_route_table(store, op, expected):
    assert route(_q(store, op)) == expected


def test_route_ok_compares_routes_and_leaves_out_abstain_gold():
    assert route_ok(_q("knowledge", "lookup"), _q("raw", "explain")) is True
    assert route_ok(_q("typed_db", "count"), _q("typed_db", "list")) is False
    assert route_ok(_q("typed_db", "count"), _q("knowledge", "count")) is False
    assert route_ok(_q("knowledge", "lookup"), None) is False
    assert route_ok(_q("raw", "abstain"), _q("raw", "abstain")) is None
    assert route_ok(_q("typed_db", "abstain"), None) is None


@pytest.mark.parametrize("gold,gen,expected", [
    (["refund"], ["refund policy"], 1.0),                    # gold words within generated
    (["section 12 filing deadline"], ["Section 12"], 1.0),   # generated words within gold
    (["REC-005"], ["rec 005"], 1.0),                         # punctuation and case ignored
    (["refund"], ["deadline"], 0.0),
    (["refund"], [], 0.0),                                   # nothing generated
    (["refund"], ["--"], 0.0),                               # no words: matches nothing
    (["a b", "c"], ["a b", "d"], 0.5),                       # P 1/2, R 1/2
    (["a", "b"], ["a"], 2 * 1.0 * 0.5 / 1.5),                # P 1, R 1/2
    (["a"], ["a", "x", "y"], 2 * (1 / 3) * 1.0 / (4 / 3)),   # P 1/3, R 1
    (["a b"], ["a", "b"], 1.0),                              # both generated match the gold
])
def test_entity_f1(gold, gen, expected):
    assert entity_f1(_q(entities=gold), _q(entities=gen)) == pytest.approx(expected)


def test_entity_f1_left_out_and_missing_query():
    assert entity_f1(_q(entities=[]), _q(entities=["x"])) is None   # no gold entities
    assert entity_f1(_q(op="abstain", entities=["x"]), _q(entities=["x"])) is None
    assert entity_f1(_q(entities=["x"]), None) == 0.0


def _query_generator(query: dict | str) -> StubClient:
    query_prompt = load_prompt("query_gen")
    a = {"answer": "30 days", "kind": "text", "citations": [], "abstain": False,
         "confidence": 0.5}
    reply = query if isinstance(query, str) else json.dumps(query)
    return StubClient(lambda s, u, r: reply if s == query_prompt else json.dumps(a))


def _q_row(item_id: str, query: dict | str) -> dict:
    ctx = _ctx(_query_generator(query), json.dumps({"label": "correct"}))
    return process_repeat(ITEMS[item_id], 0, [], ctx)


def test_row_route_ok_and_entity_f1():
    q = {"store": "raw", "op": "explain", "filters": {}, "entities": ["refund rules"],
         "as_of": None}
    row = _q_row("mini-factoid-1", q)  # gold knowledge/lookup, entities ["refund"]
    assert row["route_ok"] is True and row["entity_f1"] == 1.0
    row = _q_row("mini-factoid-1", {**q, "op": "procedure", "entities": []})
    assert row["route_ok"] is False and row["entity_f1"] == 0.0
    row = _q_row("mini-count-1", q)  # typed_db count, no gold entities
    assert row["route_ok"] is False and row["entity_f1"] is None
    row = _q_row("mini-insufficient-1", q)  # gold op abstain: both left out
    assert row["route_ok"] is None and row["entity_f1"] is None


def test_row_with_no_generated_query_scores_wrong():
    row = _q_row("mini-factoid-1", "not json")
    assert row["generated_query"] is None
    assert row["route_ok"] is False and row["entity_f1"] == 0.0
    row = _q_row("mini-count-1", "not json")
    assert row["route_ok"] is False and row["entity_f1"] is None
