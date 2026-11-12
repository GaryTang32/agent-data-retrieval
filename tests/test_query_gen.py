from datetime import date

from adr_eval.answer.query_gen import generate_query, prompt_hash
from adr_eval.llm import StubClient


def test_query_gen_returns_none_on_bad_schema():
    q, c = generate_query("How many?", None, {"type": "str"},
                          StubClient(lambda s, u, r: '{"store": "nosuch"}'))
    assert q is None and c.output_tokens >= 0


def test_query_gen_returns_none_on_invalid_json():
    q, c = generate_query("q", None, {}, StubClient(lambda s, u, r: "not json"))
    assert q is None and c.text == "not json"


def test_query_gen_valid():
    seen = {}

    def fn(s, u, r):
        seen.update(s=s, u=u)
        return ('```json\n{"store": "typed_db", "op": "count", '
                '"filters": {"type__in": ["a", "b"]}, "entities": []}\n```')

    q, c = generate_query("How many?", date(2024, 1, 2), {"type": "kind of thing"}, StubClient(fn))
    assert q is not None and q.op == "count" and q.filters == {"type__in": ["a", "b"]}
    assert "- type: kind of thing" in seen["u"] and "Answer as of: 2024-01-02" in seen["u"]
    for tok in ("field__in", "field__gte", "field__lte", "field__contains", "_field", "typed_db"):
        assert tok in seen["s"]


def test_prompt_hash_stable():
    assert prompt_hash("query_gen") == prompt_hash("query_gen")


def test_query_gen_recovers_only_when_asked():
    reply = ('{"store": "raw", "op": "explain"}\nBetter:\n'
             '{"store": "typed_db", "op": "count", "filters": {}, "entities": [], "as_of": null}')
    q, _ = generate_query("q", None, {}, StubClient(lambda s, u, r: reply))
    assert q is None
    q, _ = generate_query("q", None, {}, StubClient(lambda s, u, r: reply), recover=True)
    assert q is not None and q.store == "typed_db" and q.op == "count"
