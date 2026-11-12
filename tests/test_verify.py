from pathlib import Path

import pytest

from adr_eval.corpora.base import load_corpus
from adr_eval.golden.verify import (
    assign_rarity,
    assign_split,
    check_spans,
    count_quote,
    dedup,
    doc_frequency,
    find_quote,
    jaccard,
    normalize_ws,
    verify_items,
)
from adr_eval.models import Evidence, load_items

MINI = Path(__file__).parent / "fixtures" / "mini"


@pytest.fixture(scope="module")
def mini_loaded():
    return load_corpus(MINI / "manifest.json", MINI)


def test_find_quote_with_nbsp_and_curly_quotes():
    text = "The “refund” period  is 30 days."
    s, e = find_quote(text, '"refund" period is 30 days')
    assert normalize_ws(text[s:e]) == normalize_ws('"refund" period is 30 days')


def test_find_quote_ligature_and_missing():
    text = "The ﬁne print"
    s, e = find_quote(text, "fine print")
    assert text[s:e] == "ﬁne print"
    assert find_quote(text, "absent") is None
    assert find_quote(text, "  ") is None


def test_find_quote_returns_first_of_duplicates():
    text = "X applies. Y. X applies."
    assert find_quote(text, "X applies") == (0, 9)
    assert count_quote(text, "X applies") == 2


def test_split_is_stable_and_about_20_percent():
    s = [assign_split(f"i{n}") for n in range(2000)]
    assert s == [assign_split(f"i{n}") for n in range(2000)]
    assert 0.17 < s.count("dev") / 2000 < 0.23


def test_dedup_drops_near_duplicates(make_item):
    a = make_item(id="a", question="What is the refund window?")
    b = make_item(id="b", question="What is the refund window ?")
    c = make_item(id="c", question="Who approves large refunds?")
    kept, dropped = dedup([b, a, c])
    assert [i.id for i in kept] == ["a", "c"] and [i.id for i in dropped] == ["b"]
    assert jaccard("", "") == 1.0


def test_doc_frequency(mini_loaded):
    docs = mini_loaded.docs
    assert doc_frequency("refund", docs) == 1
    assert doc_frequency("business days", docs) == 3
    assert doc_frequency("Tier 2", docs) == 1
    assert doc_frequency("zzzz", docs) == 0


def test_assign_rarity_tertiles(make_item):
    items = [make_item(id=f"i{n}") for n in range(6)]
    out = assign_rarity(items, {f"i{n}": d for n, d in enumerate([1, 1, 3, 4, 9, 9])})
    assert [i.rarity for i in out] == ["tail", "tail", "torso", "torso", "head", "head"]
    assert all(i.rarity is None for i in items)


def test_assign_rarity_few_items_all_torso(make_item):
    out = assign_rarity([make_item(id="a"), make_item(id="b")], {"a": 1, "b": 5})
    assert [i.rarity for i in out] == ["torso", "torso"]


def test_mini_golden_all_verify(mini_loaded):
    items = load_items(MINI / "golden.jsonl")
    assert {i.qtype for i in items} == {
        "factoid", "count_filter", "procedure", "policy_asof", "overview", "id_lookup",
        "insufficient",
    }
    ok, bad = verify_items(items, mini_loaded)
    assert bad == [] and all(i.checks.span_ok for i in ok)
    assert all(i.split == assign_split(i.id) for i in items)


def test_snapshot_mismatch_rejects(mini_loaded, make_item):
    item = make_item(snapshot="0" * 64, evidence=[])
    ok, bad = verify_items([item], mini_loaded)
    assert ok == [] and bad[0].status == "rejected" and bad[0].reject_reason == "snapshot"


def test_span_and_doc_missing_reject(mini_loaded, make_item):
    snap = mini_loaded.manifest.snapshot()
    doc_id = next(iter(mini_loaded.docs))
    wrong = Evidence(doc_id=doc_id, char_start=0, char_end=5, quote="nonsense")
    ghost = Evidence(doc_id="nope", char_start=0, char_end=5, quote="hello")
    ok, bad = verify_items(
        [make_item(id="s", snapshot=snap, evidence=[wrong], question="Which span?"),
         make_item(id="g", snapshot=snap, evidence=[ghost], question="Which document?")],
        mini_loaded,
    )
    assert ok == []
    assert {i.id: i.reject_reason for i in bad} == {"s": "span", "g": "doc_missing"}
    assert check_spans(make_item(evidence=[wrong]), mini_loaded.docs) is False


# -- whole-set checks --------------------------------------------------------------------


@pytest.fixture(scope="module")
def mini_records(mini_loaded):
    from adr_eval.corpora.registry import get_adapter

    return get_adapter("mini").records(mini_loaded)


def _full(items, mini_loaded, mini_records, **kw):
    return verify_items(items, mini_loaded, records=mini_records, seed=20261108, **kw)


def test_mini_golden_passes_whole_set_checks(mini_loaded, mini_records):
    ok, bad = _full(load_items(MINI / "golden.jsonl"), mini_loaded, mini_records)
    assert bad == [] and len(ok) == 8


def _reasons(bad):
    return {i.id: i.reject_reason for i in bad}


def test_duplicate_ids_fail(mini_loaded, mini_records):
    items = load_items(MINI / "golden.jsonl")
    _, bad = _full([*items, items[3]], mini_loaded, mini_records)
    assert set(_reasons(bad).values()) == {"duplicate_id"} and len(bad) == 2


def test_typed_db_query_must_reexecute(mini_loaded, mini_records):
    items = load_items(MINI / "golden.jsonl")
    count = next(i for i in items if i.id == "mini-count-1")
    wrong = count.model_copy(update={"answer": count.answer.model_copy(
        update={"value": count.answer.value + 1})})
    _, bad = _full([wrong], mini_loaded, mini_records)
    assert _reasons(bad) == {"mini-count-1": "gold_query_exec"}


def test_split_must_match_assign_split(mini_loaded, mini_records):
    item = load_items(MINI / "golden.jsonl")[3]
    flipped = item.model_copy(update={"split": "dev" if item.split == "test" else "test"})
    _, bad = _full([flipped], mini_loaded, mini_records)
    assert _reasons(bad) == {item.id: "split"}


def test_near_duplicate_questions_fail_later_id(mini_loaded, mini_records):
    items = load_items(MINI / "golden.jsonl")
    f = next(i for i in items if i.id == "mini-factoid-1")
    copy = f.model_copy(update={"id": "mini-factoid-2", "split": assign_split("mini-factoid-2"),
                                "question": f.question + " ?"})
    _, bad = _full([f, copy], mini_loaded, mini_records)
    assert _reasons(bad) == {"mini-factoid-2": "near_duplicate of mini-factoid-1"}


def _pair(make_item, snap):
    from datetime import date

    a = make_item(id="g-policy_asof-001-a", qtype="policy_asof", question="Q?",
                  as_of=date(2023, 1, 1), snapshot=snap, evidence=[],
                  split=assign_split("g-policy_asof-001-a"))
    b = a.model_copy(update={"id": "g-policy_asof-001-b", "as_of": date(2024, 1, 1),
                             "split": assign_split("g-policy_asof-001-b")})
    return a, b


def test_policy_pair_shares_its_question_and_is_checked(mini_loaded, mini_records, make_item):
    a, b = _pair(make_item, mini_loaded.manifest.snapshot())
    ok, bad = _full([a, b], mini_loaded, mini_records)
    assert bad == [] and len(ok) == 2  # equal questions in one pair are not near-duplicates
    _, bad = _full([a], mini_loaded, mini_records)
    assert _reasons(bad) == {a.id: "pair"}
    late = a.model_copy(update={"as_of": b.as_of})
    _, bad = _full([late, b], mini_loaded, mini_records)
    assert _reasons(bad) == {a.id: "pair", b.id: "pair"}


def test_excluded_items_fail(mini_loaded, mini_records):
    items = load_items(MINI / "golden.jsonl")
    _, bad = _full(items, mini_loaded, mini_records, exclusions={"mini-id-1": "answerable"})
    assert _reasons(bad) == {"mini-id-1": "review_excluded"}


def test_several_reasons_are_joined(mini_loaded, mini_records):
    item = load_items(MINI / "golden.jsonl")[3]
    bad_item = item.model_copy(update={"snapshot": "0" * 64,
                                       "split": "dev" if item.split == "test" else "test"})
    _, bad = _full([bad_item], mini_loaded, mini_records)
    assert _reasons(bad) == {item.id: "snapshot; split"}
