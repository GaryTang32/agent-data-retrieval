from datetime import date, datetime

from adr_eval.corpora.base import Document
from adr_eval.golden.verify import normalize_ws
from adr_eval.models import Answer, Checks, Evidence, GoldenItem, GoldQuery, Provenance
from adr_eval.scoring.evidence_groups import CONTEXT_CHARS, build_all, build_groups, copy_stats

QUOTE = "The applicant must file Form 12 within thirty days."
BEFORE = "Section 4. Filing requirements for new applicants are set out below. " * 4
AFTER = " Late filings are refused unless the agency grants an extension in writing. " * 4


def doc(doc_id: str, text: str) -> Document:
    return Document(doc_id=doc_id, text=text, format="txt", source_version="1", uri="u")


def ev_in(d: Document, quote: str = QUOTE) -> Evidence:
    start = d.text.index(quote)
    return Evidence(doc_id=d.doc_id, char_start=start, char_end=start + len(quote), quote=quote)


def item(evidence: list[Evidence], as_of: date | None = None, iid: str = "i1") -> GoldenItem:
    return GoldenItem(
        id=iid, corpus="t", snapshot="s", qtype="factoid", question="q?", as_of=as_of,
        answer=Answer(kind="text", value="v"), evidence=evidence,
        gold_query=GoldQuery(store="knowledge", op="lookup"), rarity="tail", split="test",
        provenance=Provenance(model="m", prompt_hash="h", seed=0, created=datetime(2026, 1, 1)),
        checks=Checks(), status="auto_verified")


def assert_reslices(group: list[Evidence], docs: dict[str, Document]) -> None:
    want = normalize_ws(docs[group[0].doc_id].text[group[0].char_start:group[0].char_end])
    for e in group:
        assert normalize_ws(docs[e.doc_id].text[e.char_start:e.char_end]) == want


def test_copy_with_matching_context_is_found_and_reslices():
    a = doc("a", BEFORE + QUOTE + AFTER)
    # same passage, different whitespace and a different prefix far outside the window
    b = doc("b", "Other preamble. " * 30 + (BEFORE + QUOTE + AFTER).replace(" ", "  \n"))
    docs = {"a": a, "b": b}
    groups = build_groups(item([ev_in(a)]), docs)
    assert len(groups) == 1 and len(groups[0]) == 2
    assert groups[0][0] == ev_in(a)  # original first
    assert groups[0][1].doc_id == "b"
    assert_reslices(groups[0], docs)


def test_quote_only_coincidence_is_not_a_copy():
    a = doc("a", BEFORE + QUOTE + AFTER)
    b = doc("b", "Unrelated text about something else entirely. " * 6 + QUOTE + " The end." * 30)
    groups = build_groups(item([ev_in(a)]), {"a": a, "b": b})
    assert groups == [[ev_in(a)]]


def test_context_is_clipped_at_document_ends():
    a = doc("a", QUOTE + " short tail.")  # no text before, less than 200 after
    b = doc("b", "x" * 500 + " " + QUOTE + " short tail." + "y" * 500)
    groups = build_groups(item([ev_in(a)]), {"a": a, "b": b})
    assert [e.doc_id for e in groups[0]] == ["a", "b"]
    assert_reslices(groups[0], {"a": a, "b": b})


def test_context_window_is_two_hundred_chars():
    assert CONTEXT_CHARS == 200
    a = doc("a", "Z" * 50 + BEFORE + QUOTE + AFTER)
    # differs only at a character more than 200 before the quote: still a copy
    b = doc("b", "Q" * 50 + BEFORE + QUOTE + AFTER)
    assert len(build_groups(item([ev_in(a)]), {"a": a, "b": b})[0]) == 2
    # differs 150 characters before the quote: not a copy
    text = BEFORE + QUOTE + AFTER
    pos = len(BEFORE) - 150
    c = doc("c", text[:pos] + "#" + text[pos + 1:])
    a2 = doc("a2", text)
    assert len(build_groups(item([ev_in(a2)]), {"a2": a2, "c": c})[0]) == 1


def test_item_with_as_of_gets_no_copies():
    a = doc("a", BEFORE + QUOTE + AFTER)
    b = doc("b", BEFORE + QUOTE + AFTER)
    groups = build_groups(item([ev_in(a)], as_of=date(2025, 1, 1)), {"a": a, "b": b})
    assert groups == [[ev_in(a)]]


def test_several_occurrences_in_one_document_are_all_copies_in_order():
    passage = BEFORE + QUOTE + AFTER
    a = doc("a", passage)
    b = doc("b", passage + "\n\n----\n\n" + passage)
    c = doc("c", passage)
    docs = {"a": a, "b": b, "c": c}
    group = build_groups(item([ev_in(a)]), docs)[0]
    assert [(e.doc_id, e.char_start) for e in group[1:]] == sorted(
        (e.doc_id, e.char_start) for e in group[1:])
    assert [e.doc_id for e in group] == ["a", "b", "b", "c"]
    assert group[1].char_start < group[2].char_start
    assert_reslices(group, docs)


def test_no_copies_in_the_source_document_itself():
    passage = BEFORE + QUOTE + AFTER
    a = doc("a", passage + "\n" + passage)
    assert build_groups(item([ev_in(a)]), {"a": a}) == [[ev_in(a)]]


def test_build_all_keys_by_item_and_copy_stats():
    a = doc("a", BEFORE + QUOTE + AFTER)
    b = doc("b", BEFORE + QUOTE + AFTER)
    docs = {"a": a, "b": b}
    other = Evidence(doc_id="a", char_start=0, char_end=10, quote=a.text[:10])
    items = [item([ev_in(a)], iid="x"), item([other], iid="y", as_of=date(2025, 1, 1))]
    groups = build_all(items, docs)
    assert set(groups) == {"x", "y"}
    assert groups["x"] == build_groups(items[0], docs)
    assert groups["y"] == [[other]]
    assert copy_stats(groups.values()) == {"spans": 2, "spans_with_copies": 1, "copies": 1}


def test_evidence_with_edge_whitespace_and_compatibility_chars_reslices():
    quote = "  “Quoted” ﬁling rule:\tfile   Form 12.\n"
    a = doc("a", BEFORE + quote + AFTER)
    b = doc("b", "Header. " + (BEFORE + quote + AFTER).replace("\t", " ").replace("  ", " \n "))
    start = a.text.index(quote)
    ev = Evidence(doc_id="a", char_start=start, char_end=start + len(quote), quote=quote)
    group = build_groups(item([ev]), {"a": a, "b": b})[0]
    assert len(group) == 2
    assert_reslices(group, {"a": a, "b": b})
    copy = group[1]
    assert not b.text[copy.char_start].isspace() and not b.text[copy.char_end - 1].isspace()
