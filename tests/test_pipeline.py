"""process_repeat with stub clients and a stand-in index (no embedding model)."""

import json
from pathlib import Path
from types import SimpleNamespace

from adr_eval.answer._prompts import load_prompt
from adr_eval.llm import StubClient
from adr_eval.models import load_items
from adr_eval.pipeline import Context, process_repeat
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
