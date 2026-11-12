from pathlib import Path

from adr_eval.corpora.base import load_corpus
from adr_eval.corpora.registry import get_adapter
from adr_eval.golden.records import exec_gold_query, filter_records
from adr_eval.models import GoldQuery, load_items

MINI = Path(__file__).parent / "fixtures" / "mini"

ROWS = [
    {"id": "a", "year": 2024, "type": "Rule", "parts": ["33 CFR 117"], "title": "Bridge Rule"},
    {"id": "b", "year": 2025, "type": "Rule", "parts": ["47 CFR 73"], "title": "Radio rule"},
    {"id": "c", "year": None, "type": "Notice", "parts": [], "title": "Bridge notice"},
]


def q(op, **filters):
    return GoldQuery(store="typed_db", op=op, filters=filters)


def test_exec_count_and_list():
    rows = [{"id": "a", "year": 2024, "type": "Rule"}, {"id": "b", "year": 2025, "type": "Rule"}]
    assert exec_gold_query(GoldQuery(store="typed_db", op="count", filters={"type": "Rule", "year__gte": 2025}), rows) == 1  # noqa: E501
    assert exec_gold_query(GoldQuery(store="typed_db", op="list", filters={"type": "Rule"}), rows) == ["a", "b"]  # noqa: E501


def test_filter_grammar():
    ids = lambda f: [r["id"] for r in filter_records(ROWS, f)]  # noqa: E731
    assert ids({"type": "Rule"}) == ["a", "b"]
    assert ids({"type": "rule"}) == []  # equality is exact
    assert ids({"type__in": ["Notice", "Other"]}) == ["c"]
    assert ids({"year__gte": 2025}) == ["b"]
    assert ids({"year__lte": 2024}) == ["a"]  # None never satisfies a range
    assert ids({"title__contains": "BRIDGE"}) == ["a", "c"]  # case-insensitive substring
    assert ids({"parts__contains": "33 cfr 117"}) == ["a"]  # list field: membership
    assert ids({"parts__contains": "33"}) == []  # membership, not substring of an element
    assert ids({"type": "Rule", "year__lte": 2024}) == ["a"]  # filters are ANDed
    assert ids({}) == ["a", "b", "c"]
    assert ids({"_field": "title"}) == ["a", "b", "c"]  # keys starting with "_" are not filters


def test_list_is_sorted_unique_ids():
    rows = [{"id": "b", "t": 1}, {"id": "a", "t": 1}, {"id": "b", "t": 1}]
    assert exec_gold_query(q("list", t=1), rows) == ["a", "b"]
    assert exec_gold_query(q("count", t=1), rows) == 3  # count counts rows


def test_lookup_single_match_only():
    assert exec_gold_query(q("lookup", id="b", _field="title"), ROWS) == "Radio rule"
    assert exec_gold_query(q("lookup", type="Rule", _field="title"), ROWS) is None  # 2 matches
    assert exec_gold_query(q("lookup", id="zzz", _field="title"), ROWS) is None  # 0 matches
    assert exec_gold_query(q("lookup", id="b"), ROWS) is None  # no _field
    assert exec_gold_query(q("lookup", id="b", _field="missing"), ROWS) is None


def test_other_ops_return_none():
    for op in ("explain", "procedure", "abstain"):
        assert exec_gold_query(q(op, type="Rule"), ROWS) is None


def test_mini_golden_typed_db_items_execute_to_their_answers():
    corpus = load_corpus(MINI / "manifest.json", MINI)
    rows = get_adapter("mini").records(corpus)
    typed = [i for i in load_items(MINI / "golden.jsonl") if i.gold_query.store == "typed_db"]
    assert len(typed) == 2
    for item in typed:
        got = exec_gold_query(item.gold_query, rows)
        expected = item.answer.value
        assert (float(got) if item.gold_query.op == "count" else got) == expected, item.id
