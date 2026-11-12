import hashlib
import json
import random
from datetime import UTC, date, datetime
from importlib import resources
from pathlib import Path

import pytest

from adr_eval.corpora.base import Document, LoadedCorpus, load_corpus
from adr_eval.corpora.registry import get_adapter
from adr_eval.golden.generate import (
    MAX_LIST_RESULTS,
    PROMPT_NAMES,
    DocFrequency,
    _sections,
    evidence_only_check,
    gen_count_filter,
    gen_extractive,
    gen_insufficient,
    gen_policy_asof,
    generate_corpus,
    load_prompt,
    native_to_items,
    prompt_hash,
)
from adr_eval.golden.records import exec_gold_query
from adr_eval.golden.verify import check_spans, doc_frequency
from adr_eval.llm import ModelOutputError, StubClient
from adr_eval.models import Answer, Evidence, Manifest, ManifestDoc
from adr_eval.scoring.judge import Judge

MINI = Path(__file__).parent / "fixtures" / "mini"
MINI_ADAPTER = get_adapter("mini")

REFUND_QUOTE = "A customer may request a refund within 30 days of the payment date."
GOOD = {
    "question": "Within how many days of the payment date may a customer request a refund?",
    "answer_kind": "text",
    "answer": "30 days",
    "accepted_variants": ["thirty days"],
    "quote": REFUND_QUOTE,
    "key_entity": "refund",
    "gold_query": {"store": "knowledge", "filters": {}, "entities": ["refund request"]},
}
# Occurs twice in refund_policy.md ("within 30 days", "after 30 days") and in procedure.html.
REPEATED_PHRASE = "30 days"
OLD_Q = "An applicant must file a complete claim within 60 days of the notice date."
NEW_Q = "An applicant must file a complete claim within 45 days of the notice date."
POLICY = {
    "question": "Within how many days must an applicant file a complete claim?",
    "answer_old": "60 days",
    "quote_old": OLD_Q,
    "answer_new": "45 days",
    "quote_new": NEW_Q,
}


@pytest.fixture(scope="module")
def mini_loaded():
    return load_corpus(MINI / "manifest.json", MINI)


def always_equal(gold, value):
    return True


def _evidence_answer(user: str) -> str:
    """Stub evidence-only answerer: echo the evidence, so any quoted answer is contained."""
    return json.dumps({"answer": user})


# Distinct questions per qtype and section, so dedup keeps one item of each.
QUESTIONS = {
    "factoid": ("Within how many days of the payment date may a customer request a refund?",
                "What must a customer sign in with on the portal?"),
    "id_lookup": ("Which section title covers refund eligibility?",
                  "Which page holds the Edit Address option?"),
    "procedure": ("What happens to approved refunds and in what time?",
                  "List the steps for filing a change of address."),
    "overview": ("What does the agency refund policy describe overall?",
                 "Summarise the purpose of the address change procedure."),
}
PORTAL_QUOTE = "Sign in to the customer portal with your account number."


def stub_for_all(system: str, user: str, repeat: int) -> str:
    if system == load_prompt("extractive"):
        qtype = user.split("\n", 1)[0].removeprefix("Question type: ")
        refund_q, portal_q = QUESTIONS[qtype]
        if "Agency Refund Policy" in user:
            return json.dumps({**GOOD, "question": refund_q})
        return json.dumps({**GOOD, "question": portal_q, "quote": PORTAL_QUOTE,
                           "answer": "your account number", "accepted_variants": [],
                           "key_entity": "customer portal"})
    if system == load_prompt("count_filter"):
        return json.dumps({"question": f"Records matching {user[-80:]}?"})
    if system == load_prompt("policy_asof"):
        return json.dumps(POLICY)
    if system == load_prompt("insufficient"):
        return json.dumps({"question": "Who chairs the Lunar Refund Tribunal?",
                           "absent_term": "Lunar Refund Tribunal"})
    if system == load_prompt("evidence_only"):
        return _evidence_answer(user)
    raise AssertionError("unknown prompt")


STUB = StubClient(stub_for_all)


def tiny_corpus(text: str, version: str = "2026-11-08") -> LoadedCorpus:
    doc = Document("d1", text, "txt", "1", "file://d1.txt")
    md = ManifestDoc(doc_id="d1", uri="file://d1.txt", format="txt", source_version="1",
                     bytes=len(text), license="x", path="d1.txt")
    m = Manifest(corpus="tiny", version=version, license_summary="x", documents=[md])
    return LoadedCorpus(manifest=m, docs={"d1": doc}, empty_docs=[])


# -- prompts -----------------------------------------------------------------------------


def test_prompts_ship_in_package_and_hash_file_bytes():
    for name in PROMPT_NAMES:
        data = resources.files("adr_eval.golden").joinpath(f"prompts/{name}.txt").read_bytes()
        assert prompt_hash(name) == hashlib.sha256(data).hexdigest()
        text = load_prompt(name)
        assert "JSON only" in text


@pytest.mark.parametrize(
    "name,keys",
    [
        ("extractive", ["question", "answer_kind", "answer", "accepted_variants", "quote",
                        "key_entity", "gold_query"]),
        ("count_filter", ["question"]),
        ("policy_asof", ["question", "answer_old", "quote_old", "answer_new", "quote_new"]),
        ("insufficient", ["question", "absent_term"]),
        ("evidence_only", ["answer"]),
    ],
)
def test_prompts_name_their_exact_keys(name, keys):
    text = load_prompt(name)
    for k in keys:
        assert f'"{k}"' in text


# -- extractive --------------------------------------------------------------------------


def test_extractive_locates_quote_and_records_span(mini_loaded):
    items = gen_extractive("factoid", mini_loaded, StubClient(lambda s, u, r: json.dumps(GOOD)),
                           3, random.Random(1))
    assert len(items) == 1  # only the refund section contains the quote
    item = items[0]
    ev = item.evidence[0]
    assert mini_loaded.docs[ev.doc_id].text[ev.char_start:ev.char_end] == REFUND_QUOTE
    assert check_spans(item, mini_loaded.docs)
    assert item.qtype == "factoid" and item.id == "mini-factoid-001"
    assert item.answer == Answer(kind="text", value="30 days", accepted_variants=["thirty days"])
    assert item.gold_query.op == "lookup" and item.gold_query.store == "knowledge"
    assert item.gold_query.entities[0] == "refund"  # key_entity first
    assert item.snapshot == mini_loaded.manifest.snapshot()
    assert item.provenance.model == "stub"
    assert item.provenance.prompt_hash == prompt_hash("extractive")
    assert item.checks.span_ok is True


def test_extractive_op_follows_qtype(mini_loaded):
    stub = StubClient(lambda s, u, r: json.dumps(GOOD))
    assert gen_extractive("procedure", mini_loaded, stub, 1, random.Random(1))[0].gold_query.op \
        == "procedure"
    assert gen_extractive("overview", mini_loaded, stub, 1, random.Random(1))[0].gold_query.op \
        == "explain"


def test_extractive_samples_sections_of_at_least_80_tokens(mini_loaded):
    seen = []

    def fn(s, u, r):
        seen.append(u)
        return json.dumps({**GOOD, "quote": "not in the text"})

    gen_extractive("factoid", mini_loaded, StubClient(fn), 10, random.Random(1))
    # Only refund_policy.md (88 tokens) and procedure.html (91) qualify in the fixture.
    assert len(seen) == 2
    assert any("Agency Refund Policy" in u for u in seen)
    assert any("Filing a Change of Address" in u for u in seen)


def test_extractive_rejects_unfound_quote(mini_loaded):
    stub = StubClient(lambda s, u, r: json.dumps({**GOOD, "quote": "not in the text"}))
    assert gen_extractive("factoid", mini_loaded, stub, 3, random.Random(1)) == []


def test_extractive_rejects_ambiguous_quote(mini_loaded):      # Review Focus 1
    stub = StubClient(lambda s, u, r: json.dumps({**GOOD, "quote": REPEATED_PHRASE}))
    assert gen_extractive("factoid", mini_loaded, stub, 3, random.Random(1)) == []


def test_extractive_rejects_span_that_fails_the_span_check():
    # find_quote matches "x f" inside the NFKC expansion of the ligature; the re-slice
    # "x ﬁ" does not normalize to the quote, so the candidate must be rejected.
    text = "x ﬁ y. " + " ".join(f"word{i}" for i in range(100))
    stub = StubClient(lambda s, u, r: json.dumps({**GOOD, "quote": "x f"}))
    assert gen_extractive("factoid", tiny_corpus(text), stub, 1, random.Random(1)) == []


def test_extractive_invalid_json_raises(mini_loaded):           # Review Focus 2
    stub = StubClient(lambda s, u, r: '{"question": "truncated')
    with pytest.raises(ModelOutputError):
        gen_extractive("factoid", mini_loaded, stub, 1, random.Random(1))


def test_extractive_missing_key_raises(mini_loaded):
    reply = {k: v for k, v in GOOD.items() if k != "quote"}
    with pytest.raises(ModelOutputError):
        gen_extractive("factoid", mini_loaded, StubClient(lambda s, u, r: json.dumps(reply)), 1,
                       random.Random(1))


def test_extractive_number_answer(mini_loaded):
    reply = {**GOOD, "answer_kind": "number", "answer": "30"}
    items = gen_extractive("factoid", mini_loaded, StubClient(lambda s, u, r: json.dumps(reply)),
                           1, random.Random(1))
    assert items[0].answer.kind == "number" and items[0].answer.value == 30.0


# -- extractive: section evidence for overview and procedure -----------------------------


def _section_of(corpus, needle: str):
    return next(c for c in _sections(corpus) if needle in c.text)


@pytest.mark.parametrize("qtype", ["overview", "procedure"])
def test_whole_section_qtypes_cite_the_generating_section(mini_loaded, qtype):
    items = gen_extractive(qtype, mini_loaded, StubClient(lambda s, u, r: json.dumps(GOOD)),
                           3, random.Random(1))
    assert len(items) == 1  # only the refund section contains the quote
    section = _section_of(mini_loaded, REFUND_QUOTE)
    text = mini_loaded.docs[section.doc_id].text
    assert items[0].evidence == [Evidence(doc_id=section.doc_id, char_start=section.char_start,
                                          char_end=section.char_end,
                                          quote=text[section.char_start:section.char_end])]
    assert check_spans(items[0], mini_loaded.docs)


@pytest.mark.parametrize("qtype", ["factoid", "id_lookup"])
def test_quote_qtypes_still_cite_the_quote(mini_loaded, qtype):
    items = gen_extractive(qtype, mini_loaded, StubClient(lambda s, u, r: json.dumps(GOOD)),
                           3, random.Random(1))
    [ev] = items[0].evidence
    assert ev.quote == REFUND_QUOTE
    assert mini_loaded.docs[ev.doc_id].text[ev.char_start:ev.char_end] == REFUND_QUOTE


def _two_section_corpus() -> LoadedCorpus:
    alpha = " ".join(f"alpha{i}" for i in range(250))
    beta = " ".join(f"beta{i}" for i in range(250))
    return tiny_corpus(f"{alpha}\n\n{beta}")


def test_two_section_corpus_has_two_sections():
    assert [c.text.split()[0] for c in _sections(_two_section_corpus())] == ["alpha0", "beta0"]


@pytest.mark.parametrize("qtype,kept", [("overview", 1), ("procedure", 1), ("factoid", 2)])
def test_whole_section_qtypes_skip_quotes_outside_the_section(qtype, kept):
    # Every section is answered with a quote from the beta section: overview and procedure
    # keep only the beta section's candidate; factoid keeps both (quote anywhere, unchanged).
    corpus = _two_section_corpus()
    stub = StubClient(lambda s, u, r: json.dumps({**GOOD, "quote": "beta10 beta11 beta12"}))
    items = gen_extractive(qtype, corpus, stub, 2, random.Random(1))
    assert len(items) == kept
    if qtype != "factoid":
        assert items[0].evidence[0].quote.startswith("beta0 ")


@pytest.mark.parametrize("qtype", ["overview", "procedure"])
@pytest.mark.parametrize("quote", ["not in the text", REPEATED_PHRASE])
def test_whole_section_qtypes_skip_unfound_or_ambiguous_quotes(mini_loaded, qtype, quote):
    stub = StubClient(lambda s, u, r: json.dumps({**GOOD, "quote": quote}))
    assert gen_extractive(qtype, mini_loaded, stub, 3, random.Random(1)) == []


@pytest.mark.parametrize("qtype", ["overview", "procedure"])
def test_whole_section_qtypes_skip_quotes_failing_the_span_check(qtype):
    text = "x ﬁ y. " + " ".join(f"word{i}" for i in range(100))
    stub = StubClient(lambda s, u, r: json.dumps({**GOOD, "quote": "x f"}))
    assert gen_extractive(qtype, tiny_corpus(text), stub, 1, random.Random(1)) == []


STEPS = [" Sign in to the portal ", "Open Edit Address", "Submit the form"]
NUMBERED = "1. Sign in to the portal\n2. Open Edit Address\n3. Submit the form"


@pytest.mark.parametrize("kind", ["set", "text"])
def test_procedure_list_answer_becomes_numbered_text(mini_loaded, kind):
    reply = {**GOOD, "answer_kind": kind, "answer": STEPS,
             "accepted_variants": [["Log in", "Change address"], "sign in, edit, submit"]}
    [item] = gen_extractive("procedure", mini_loaded,
                            StubClient(lambda s, u, r: json.dumps(reply)), 1, random.Random(1))
    assert item.answer == Answer(kind="text", value=NUMBERED, accepted_variants=[
        "1. Log in\n2. Change address", "sign in, edit, submit"])
    assert item.gold_query.op == "procedure"


def test_procedure_string_answer_is_kept_as_text(mini_loaded):
    reply = {**GOOD, "answer_kind": "set", "answer": "Sign in, then edit the address."}
    [item] = gen_extractive("procedure", mini_loaded,
                            StubClient(lambda s, u, r: json.dumps(reply)), 1, random.Random(1))
    assert item.answer == Answer(kind="text", value="Sign in, then edit the address.",
                                 accepted_variants=["thirty days"])


@pytest.mark.parametrize("answer", [[], ["ok", 3], 7])
def test_procedure_malformed_steps_raise(mini_loaded, answer):
    reply = {**GOOD, "answer_kind": "set", "answer": answer}
    with pytest.raises(ModelOutputError):
        gen_extractive("procedure", mini_loaded, StubClient(lambda s, u, r: json.dumps(reply)),
                       1, random.Random(1))


def test_factoid_set_answer_is_not_normalized(mini_loaded):
    reply = {**GOOD, "answer_kind": "set", "answer": ["a", "b"]}
    [item] = gen_extractive("factoid", mini_loaded, StubClient(lambda s, u, r: json.dumps(reply)),
                            1, random.Random(1))
    assert item.answer.kind == "set" and item.answer.value == ["a", "b"]


# Changing the extractive prompt invalidates ~1,700 cached generation calls: update this
# hash only on purpose.
EXTRACTIVE_PROMPT_SHA256 = "b7c16f4fd8279744efb343bad9bb84f75722193c62d0e0de42a1e41d427497bd"


@pytest.mark.parametrize("qtype", ["factoid", "overview", "procedure"])
def test_extractive_prompts_and_rng_use_are_cache_stable(mini_loaded, qtype):
    assert prompt_hash("extractive") == EXTRACTIVE_PROMPT_SHA256
    sent = []

    def fn(s, u, r):
        sent.append((s, u))
        return json.dumps({**GOOD, "quote": "not in the text"})

    rng = random.Random(7)
    gen_extractive(qtype, mini_loaded, StubClient(fn), 1, rng)
    expected_rng = random.Random(7)
    sections = _sections(mini_loaded)
    order = expected_rng.sample(sections, len(sections))[:3]
    assert sent == [(load_prompt("extractive"), f"Question type: {qtype}\n\nSection:\n{c.text}")
                    for c in order]
    assert rng.getstate() == expected_rng.getstate()  # one sample() call, nothing more


# -- count_filter ------------------------------------------------------------------------


def test_count_filter_answer_is_code_computed(mini_loaded):
    items = gen_count_filter(mini_loaded, MINI_ADAPTER, StubClient(lambda s, u, r: '{"question": "How many rules?"}'), 3, random.Random(1))  # noqa: E501
    assert items
    assert all(i.answer.value == exec_gold_query(i.gold_query, MINI_ADAPTER.records(mini_loaded)) for i in items)  # noqa: E501


def test_count_filter_items_are_well_formed(mini_loaded):
    rows = MINI_ADAPTER.records(mini_loaded)
    items = gen_count_filter(mini_loaded, MINI_ADAPTER,
                             StubClient(lambda s, u, r: '{"question": "How many?"}'), 6,
                             random.Random(3))
    assert len(items) == 6
    assert len({json.dumps([i.gold_query.op, i.gold_query.filters], sort_keys=True)
                for i in items}) == 6  # no repeated query
    for i in items:
        assert i.qtype == "count_filter" and i.gold_query.store == "typed_db"
        assert 1 <= len([k for k in i.gold_query.filters]) <= 2
        assert "id" not in i.gold_query.filters
        if i.gold_query.op == "count":
            assert i.answer.kind == "number"
        else:
            assert i.answer.kind == "set" and len(i.answer.value) <= MAX_LIST_RESULTS
        # no _span on mini rows: evidence is the whole records document, sliced exactly
        doc_id = rows[0]["_doc_id"]
        text = mini_loaded.docs[doc_id].text
        assert [(e.doc_id, e.char_start, e.char_end) for e in i.evidence] == \
            [(doc_id, 0, len(text))]
        assert i.evidence[0].quote == text
        assert i.gold_query.entities  # key entity for rarity


class _SpanAdapter:
    """Rows with `_span` and a duplicated id (as in bench/research)."""

    def __init__(self, rows):
        self.rows = rows

    def records(self, corpus):
        return self.rows

    def record_schema(self):
        return {"id": "str", "kind": "str"}


def test_count_filter_uses_row_spans_and_skips_non_unique_counts():
    text = "R1 alpha\nR2 alpha\nR2 alpha\nR3 beta\n"
    corpus = tiny_corpus(text)
    rows = [
        {"id": "R1", "kind": "alpha", "_doc_id": "d1", "_span": [0, 8]},
        {"id": "R2", "kind": "alpha", "_doc_id": "d1", "_span": [9, 17]},
        {"id": "R2", "kind": "alpha", "_doc_id": "d1", "_span": [18, 26]},
        {"id": "R3", "kind": "beta", "_doc_id": "d1", "_span": [27, 34]},
    ]
    items = gen_count_filter(corpus, _SpanAdapter(rows),
                             StubClient(lambda s, u, r: '{"question": "q?"}'), 10,
                             random.Random(0))
    by_key = {(i.gold_query.op, i.gold_query.filters["kind"]): i for i in items}
    # count over "alpha" would count a duplicated id twice: never sampled
    assert ("count", "alpha") not in by_key
    assert by_key[("list", "alpha")].answer.value == ["R1", "R2"]
    assert by_key[("count", "beta")].answer.value == 1
    alpha_ev = by_key[("list", "alpha")].evidence
    assert [(e.char_start, e.char_end, e.quote) for e in alpha_ev] == [
        (0, 8, "R1 alpha"), (9, 17, "R2 alpha"), (18, 26, "R2 alpha")]
    assert by_key[("count", "beta")].evidence[0].quote == "R3 beta"


def test_count_filter_list_only_up_to_25_results():
    rows = [{"id": f"R{i:03d}", "kind": "a" if i < 30 else "b", "_doc_id": "d1"}
            for i in range(40)]
    items = gen_count_filter(tiny_corpus("x " * 50), _SpanAdapter(rows),
                             StubClient(lambda s, u, r: '{"question": "q?"}'), 10,
                             random.Random(0))
    assert items
    for i in items:
        if i.gold_query.filters == {"kind": "a"}:
            assert i.gold_query.op == "count"  # 30 results: too many to list


# -- policy_asof -------------------------------------------------------------------------


def test_policy_asof_emits_pair_with_dates(mini_loaded):
    items = gen_policy_asof(mini_loaded, MINI_ADAPTER,
                            StubClient(lambda s, u, r: json.dumps(POLICY)), 2, random.Random(1))
    assert [i.id for i in items] == ["mini-policy_asof-001-a", "mini-policy_asof-001-b"]
    a, b = items
    assert a.as_of == date(2023, 1, 1) and b.as_of == date(2024, 1, 1)
    assert a.gold_query.as_of == a.as_of and b.gold_query.as_of == b.as_of
    assert a.answer.value == "60 days" and b.answer.value == "45 days"
    assert a.question == b.question
    assert a.evidence[0].quote == OLD_Q and b.evidence[0].quote == NEW_Q
    assert a.evidence[0].doc_id != b.evidence[0].doc_id
    assert check_spans(a, mini_loaded.docs) and check_spans(b, mini_loaded.docs)


def test_policy_asof_rejects_quote_found_in_other_version(mini_loaded):
    shared = "A late claim is accepted only with written justification."
    stub = StubClient(lambda s, u, r: json.dumps({**POLICY, "quote_old": shared}))
    assert gen_policy_asof(mini_loaded, MINI_ADAPTER, stub, 2, random.Random(1)) == []


def test_policy_asof_rejects_equal_answers(mini_loaded):
    stub = StubClient(lambda s, u, r: json.dumps({**POLICY, "answer_new": " 60  DAYS"}))
    assert gen_policy_asof(mini_loaded, MINI_ADAPTER, stub, 2, random.Random(1)) == []


def test_policy_asof_quote_must_be_in_own_version(mini_loaded):
    stub = StubClient(lambda s, u, r: json.dumps({**POLICY, "quote_old": NEW_Q}))
    assert gen_policy_asof(mini_loaded, MINI_ADAPTER, stub, 2, random.Random(1)) == []


def test_policy_asof_offsets_are_into_the_full_document():
    full = "Preamble text.\n§ 1 Title.\nWithin 10 days.\n§ 2 Other.\nKeep."
    old_sec = "§ 1 Title.\nWithin 10 days."
    new_sec = "§ 1 Title.\nWithin 20 days."
    corpus = tiny_corpus(full)
    newdoc = Document("d2", full.replace("10", "20"), "xml", "2024-01-01", "file://d2")
    corpus.docs["d2"] = newdoc

    class A:
        def version_pairs(self, c):
            return [(Document("d1", old_sec, "xml", "2023-01-01", "file://d1#1"),
                     Document("d2", new_sec, "xml", "2024-01-01", "file://d2#1"))]

    reply = {"question": "How many days?", "answer_old": "10 days", "quote_old": "Within 10 days.",
             "answer_new": "20 days", "quote_new": "Within 20 days."}
    a, b = gen_policy_asof(corpus, A(), StubClient(lambda s, u, r: json.dumps(reply)), 2,
                           random.Random(0))
    assert full[a.evidence[0].char_start:a.evidence[0].char_end] == "Within 10 days."
    assert a.evidence[0].char_start == full.index("Within 10 days.")
    assert check_spans(a, corpus.docs) and check_spans(b, corpus.docs)


# -- insufficient ------------------------------------------------------------------------


def test_insufficient_requires_zero_df(mini_loaded):
    present = StubClient(lambda s, u, r: json.dumps({"question": "What is the refund period?",
                                                     "absent_term": "refund"}))
    assert gen_insufficient(mini_loaded, present, 3, random.Random(1)) == []


def test_insufficient_keeps_absent_term(mini_loaded):
    stub = StubClient(lambda s, u, r: json.dumps({"question": "Who chairs the Lunar Tribunal?",
                                                  "absent_term": "Lunar Tribunal"}))
    items = gen_insufficient(mini_loaded, stub, 1, random.Random(1))
    assert len(items) == 1
    i = items[0]
    assert i.answer.kind == "abstain" and i.answer.value is None and i.evidence == []
    assert i.gold_query.op == "abstain" and i.gold_query.entities == ["Lunar Tribunal"]
    assert doc_frequency("Lunar Tribunal", mini_loaded.docs) == 0


def test_insufficient_rejects_term_without_tokens(mini_loaded):
    stub = StubClient(lambda s, u, r: json.dumps({"question": "?", "absent_term": "§ —"}))
    assert gen_insufficient(mini_loaded, stub, 2, random.Random(1)) == []


def test_doc_frequency_cache_matches_verify(mini_loaded):
    df = DocFrequency(mini_loaded.docs)
    for term in ["refund", "Refund Policy", "business days", "the", "Lunar Tribunal",
                 "REC-005", "within 45 days", "§"]:
        assert df(term) == doc_frequency(term, mini_loaded.docs), term


# -- evidence_only_check -----------------------------------------------------------------


def _item(mini_loaded, **kw):
    stub = StubClient(lambda s, u, r: json.dumps(GOOD))
    item = gen_extractive("factoid", mini_loaded, stub, 1, random.Random(1))[0]
    return item.model_copy(update=kw)


def test_evidence_only_text_uses_normalized_containment(mini_loaded):
    item = _item(mini_loaded)
    seen = []

    def fn(s, u, r):
        seen.append(u)
        return json.dumps({"answer": "Customers have  THIRTY days."})

    assert evidence_only_check(item, mini_loaded, StubClient(fn)) is True  # variant matches
    assert REFUND_QUOTE in seen[0] and item.question in seen[0]
    wrong = StubClient(lambda s, u, r: json.dumps({"answer": "14 days"}))
    assert evidence_only_check(item, mini_loaded, wrong) is False
    none = StubClient(lambda s, u, r: json.dumps({"answer": None}))
    assert evidence_only_check(item, mini_loaded, none) is False


def test_evidence_only_non_text_uses_compare(mini_loaded):
    item = _item(mini_loaded, answer=Answer(kind="number", value=30.0))
    calls = []

    def compare(gold, value):
        calls.append((gold, value))
        return value == 30.0

    assert evidence_only_check(item, mini_loaded, StubClient(lambda s, u, r: '{"answer": "30"}'),
                               compare=compare) is True
    assert calls == [(item.answer, 30.0)]  # numeric strings are coerced for number answers
    assert evidence_only_check(item, mini_loaded, StubClient(lambda s, u, r: '{"answer": 7}'),
                               compare=compare) is False


def test_evidence_only_rejects_abstain_items(mini_loaded):
    item = _item(mini_loaded, answer=Answer(kind="abstain", value=None), evidence=[])
    with pytest.raises(ValueError):
        evidence_only_check(item, mini_loaded, STUB, compare=always_equal)


def test_evidence_only_invalid_json_raises(mini_loaded):
    with pytest.raises(ModelOutputError):
        evidence_only_check(_item(mini_loaded), mini_loaded,
                            StubClient(lambda s, u, r: "not json"), compare=always_equal)


PARAPHRASE = "A refund may be requested up to a month after paying."


def _judge(label: str, calls: list | None = None) -> Judge:
    def fn(s, u, r):
        if calls is not None:
            calls.append(u)
        return json.dumps({"label": label, "reason": "stub"})

    return Judge(StubClient(fn))


def _reply(answer):
    return StubClient(lambda s, u, r: json.dumps({"answer": answer}))


def test_evidence_only_text_containment_hit_skips_the_judge(mini_loaded):
    calls = []
    assert evidence_only_check(_item(mini_loaded), mini_loaded, _reply("within 30 days"),
                               judge=_judge("incorrect", calls)) is True
    assert calls == []


@pytest.mark.parametrize("label, expected", [("correct", True), ("partial", False),
                                             ("incorrect", False)])
def test_evidence_only_text_containment_miss_asks_the_judge(mini_loaded, label, expected):
    item = _item(mini_loaded)
    calls = []
    assert evidence_only_check(item, mini_loaded, _reply(PARAPHRASE),
                               judge=_judge(label, calls)) is expected
    assert len(calls) == 1
    assert item.question in calls[0] and PARAPHRASE in calls[0] and "30 days" in calls[0]


def test_evidence_only_text_containment_miss_without_judge_fails(mini_loaded):
    assert evidence_only_check(_item(mini_loaded), mini_loaded, _reply(PARAPHRASE)) is False


def test_evidence_only_invalid_judge_label_raises(mini_loaded):
    with pytest.raises(ModelOutputError):
        evidence_only_check(_item(mini_loaded), mini_loaded, _reply(PARAPHRASE),
                            judge=_judge("maybe"))


def test_evidence_only_non_text_never_asks_the_judge(mini_loaded):
    calls = []
    for answer, reply in ((Answer(kind="number", value=30.0), "about a month"),
                          (Answer(kind="set", value=["a", "b"]), ["c"]),
                          (Answer(kind="id", value="SEC-1"), "SEC-2")):
        item = _item(mini_loaded, answer=answer)
        assert evidence_only_check(item, mini_loaded, _reply(reply),
                                   judge=_judge("correct", calls)) is False
    assert calls == []


# -- generate_corpus ---------------------------------------------------------------------


def test_generation_is_reproducible(mini_loaded):
    a = generate_corpus("mini", STUB, per_type=2, compare=always_equal)
    b = generate_corpus("mini", STUB, per_type=2, compare=always_equal)
    assert [i.model_dump() for i in a[0]] == [i.model_dump() for i in b[0]]  # created timestamp fixed from seed  # noqa: E501
    assert [i.model_dump() for i in a[1]] == [i.model_dump() for i in b[1]]


def test_generate_corpus_items_and_checks(mini_loaded):
    accepted, rejected = generate_corpus("mini", STUB, per_type=2, compare=always_equal)
    by_qtype = {}
    for i in accepted:
        by_qtype.setdefault(i.qtype, []).append(i)
    assert set(by_qtype) == {"factoid", "id_lookup", "procedure", "overview", "count_filter",
                             "policy_asof", "insufficient"}
    assert [i.id for i in by_qtype["policy_asof"]] == ["mini-policy_asof-001-a",
                                                       "mini-policy_asof-001-b"]
    snapshot = mini_loaded.manifest.snapshot()
    for i in accepted:
        assert i.status == "auto_verified" and i.reject_reason is None
        assert i.snapshot == snapshot and i.split in ("dev", "test")
        assert i.provenance.seed == 20261108
        # mini's manifest version "1" is not a date: the fixed fallback is the epoch
        assert i.provenance.created == datetime(1970, 1, 1, tzinfo=UTC)
        assert i.checks.dedup_ok is True and i.checks.span_ok is True
        if i.gold_query.store == "typed_db":
            assert i.checks.gold_query_exec_ok is True
        if i.qtype == "count_filter":
            assert i.checks.recompute_ok is True
        if i.answer.kind == "abstain":
            assert i.checks.evidence_only_ok is None and i.rarity is None
        else:
            assert i.checks.evidence_only_ok is True and i.rarity in ("head", "torso", "tail")
    assert len(accepted) + len(rejected) == len({i.id for i in accepted + rejected})
    for i in rejected:
        assert i.status == "rejected" and i.reject_reason


def test_generate_corpus_dedup_rejects_near_duplicates_but_keeps_policy_pairs():
    def fn(s, u, r):
        if s == load_prompt("extractive"):  # the same question for every extractive qtype
            return stub_for_all(s, u.replace(u.split("\n", 1)[0], "Question type: factoid"), r)
        return stub_for_all(s, u, r)

    accepted, rejected = generate_corpus("mini", StubClient(fn), per_type=2,
                                         compare=always_equal)
    dups = [i for i in rejected if i.reject_reason == "dedup"]
    # factoid ids sort first, so the id_lookup, overview and procedure copies are dropped
    # (the stub's repeated insufficient and similar count questions are dropped too)
    assert {"id_lookup", "overview", "procedure"} <= {i.qtype for i in dups}
    assert len([i for i in accepted if i.qtype == "factoid"]) == 2
    assert all(i.checks.dedup_ok is False for i in dups)
    # the two halves of a policy pair share their question by design and are both kept
    assert {i.id for i in accepted if i.qtype == "policy_asof"} == {
        "mini-policy_asof-001-a", "mini-policy_asof-001-b"}


def test_generate_corpus_rejects_evidence_only_mismatch():
    def fn(s, u, r):
        if s == load_prompt("evidence_only"):
            return json.dumps({"answer": "no idea"})
        return stub_for_all(s, u, r)

    accepted, rejected = generate_corpus("mini", StubClient(fn), per_type=2,
                                         compare=lambda gold, value: False)
    assert all(i.answer.kind == "abstain" for i in accepted)
    reasons = {i.reject_reason for i in rejected}
    assert "evidence_only" in reasons
    pair = [i for i in rejected if i.qtype == "policy_asof"]
    assert len(pair) == 2  # a pair is rejected together
    assert all(i.checks.evidence_only_ok is False for i in rejected
               if i.reject_reason == "evidence_only")


def test_generate_corpus_records_evidence_only_output_errors():
    def fn(s, u, r):
        if s == load_prompt("evidence_only"):
            return "truncated {"
        return stub_for_all(s, u, r)

    accepted, rejected = generate_corpus("mini", StubClient(fn), per_type=1,
                                         compare=always_equal)
    assert any(i.reject_reason == "evidence_only_output" for i in rejected)


def test_generate_corpus_created_from_manifest_date(tmp_path, monkeypatch):
    import adr_eval.golden.generate as g

    real = g._load

    def dated(name):
        corpus, adapter = real(name)
        m = corpus.manifest.model_copy(update={"version": "2026-11-08"})
        return LoadedCorpus(m, corpus.docs, corpus.empty_docs, corpus.root), adapter

    monkeypatch.setattr(g, "_load", dated)
    accepted, _ = generate_corpus("mini", STUB, per_type=1, compare=always_equal)
    assert {i.provenance.created for i in accepted} == {datetime(2026, 11, 8, tzinfo=UTC)}


# -- bench native items ------------------------------------------------------------------


def test_native_to_items(mini_loaded):
    refund_id = next(d for d, doc in mini_loaded.docs.items() if "Refund Policy" in doc.text)
    natives = [
        {"question_id": "qst_0001", "question_type": "basic", "qtype": "factoid",
         "question": "What is the refund window?", "gold_answer": "30 days",
         "answer_facts": ["30 days"], "manifest_doc_ids": [refund_id, refund_id]},
        {"question_id": "qst_0002", "question_type": "completeness", "qtype": "overview",
         "question": "What does the refund policy cover?", "gold_answer": "Refunds.",
         "answer_facts": [], "manifest_doc_ids": [refund_id]},
        {"question_id": "qst_0003", "question_type": "info_not_found", "qtype": "insufficient",
         "question": "Who is the CFO?", "gold_answer": "Not found.", "answer_facts": [],
         "manifest_doc_ids": []},
    ]
    items = native_to_items(natives, mini_loaded, seed=7)
    assert [i.id for i in items] == ["mini-factoid-qst_0001", "mini-overview-qst_0002",
                                     "mini-insufficient-qst_0003"]
    f, o, ins = items
    assert f.provenance.model == "native" and f.provenance.seed == 7
    assert f.answer == Answer(kind="text", value="30 days")
    text = mini_loaded.docs[refund_id].text
    assert f.evidence == [Evidence(doc_id=refund_id, char_start=0, char_end=len(text),
                                   quote=text)]  # whole gold documents, de-duplicated
    assert f.gold_query.op == "lookup" and o.gold_query.op == "explain"
    assert ins.answer.kind == "abstain" and ins.evidence == [] and ins.gold_query.op == "abstain"
    assert all(check_spans(i, mini_loaded.docs) for i in items)


def test_count_filter_skips_sparse_unique_string_fields():
    # "doi" is empty on most rows but unique where set: an id, not a category
    rows = [{"id": f"R{i}", "kind": "a" if i % 2 else "b", "doi": f"10.1/{i}" if i < 3 else "",
             "_doc_id": "d1"} for i in range(10)]
    items = gen_count_filter(tiny_corpus("x " * 50), _SpanAdapter(rows),
                             StubClient(lambda s, u, r: '{"question": "q?"}'), 10,
                             random.Random(0))
    assert items and all(set(i.gold_query.filters) == {"kind"} for i in items)


# -- generation errors (Ruling R6) -------------------------------------------------------


def test_generators_count_malformed_replies_in_an_error_sink(mini_loaded):
    from collections import Counter

    def fn(s, u, r):  # bad JSON for the procedure.html section only
        return '{"question": "trunc' if "Change of Address" in u else json.dumps(GOOD)

    errors = Counter()
    items = gen_extractive("factoid", mini_loaded, StubClient(fn), 2, random.Random(1),
                           errors=errors)
    assert len(items) == 1 and errors == Counter({"factoid": 1})
    errors = Counter()
    bad = StubClient(lambda s, u, r: "not json")
    assert gen_count_filter(mini_loaded, MINI_ADAPTER, bad, 1, random.Random(1),
                            errors=errors) == []
    assert gen_policy_asof(mini_loaded, MINI_ADAPTER, bad, 2, random.Random(1),
                           errors=errors) == []
    assert gen_insufficient(mini_loaded, bad, 1, random.Random(1), errors=errors) == []
    assert errors["count_filter"] > 0 and errors["policy_asof"] == 1 \
        and errors["insufficient"] > 0


def test_generators_without_a_sink_still_raise(mini_loaded):
    bad = StubClient(lambda s, u, r: "not json")
    for call in (
        lambda: gen_extractive("overview", mini_loaded, bad, 1, random.Random(1)),
        lambda: gen_count_filter(mini_loaded, MINI_ADAPTER, bad, 1, random.Random(1)),
        lambda: gen_policy_asof(mini_loaded, MINI_ADAPTER, bad, 2, random.Random(1)),
        lambda: gen_insufficient(mini_loaded, bad, 1, random.Random(1)),
    ):
        with pytest.raises(ModelOutputError):
            call()


def test_generate_corpus_survives_bad_json_and_logs_tally(caplog):
    import logging

    def fn(s, u, r):
        if s == load_prompt("extractive") and "Change of Address" in u \
                and u.startswith("Question type: procedure"):
            return '{"question": "truncated'
        return stub_for_all(s, u, r)

    with caplog.at_level(logging.INFO, logger="adr_eval.golden.generate"):
        accepted, rejected = generate_corpus("mini", StubClient(fn), per_type=2,
                                             compare=always_equal)
    procedure = [i for i in accepted if i.qtype == "procedure"]
    assert len(procedure) == 1  # the refund section still yields its item
    assert {i.qtype for i in accepted} >= {"factoid", "id_lookup", "overview", "count_filter",
                                           "policy_asof", "insufficient"}
    lines = {r.getMessage().split()[1].rstrip(":"): r.getMessage() for r in caplog.records
             if r.name == "adr_eval.golden.generate"}
    assert set(lines) == {"factoid", "id_lookup", "procedure", "overview", "count_filter",
                          "policy_asof", "insufficient"}
    assert lines["procedure"] == ("mini procedure: requested=2 accepted=1 rejected=0 "
                                  "generation_errors=1")
    assert lines["factoid"].endswith("generation_errors=0")


def _paraphrase_overviews(s, u, r):
    """`stub_for_all`, except that overview items are re-answered in other words."""
    if s == load_prompt("evidence_only") and any(q in u for q in QUESTIONS["overview"]):
        return json.dumps({"answer": "It explains the general purpose in other words."})
    return stub_for_all(s, u, r)


def test_generate_corpus_judge_accepts_paraphrased_overview():
    client = StubClient(_paraphrase_overviews)
    accepted, rejected = generate_corpus("mini", client, per_type=2, compare=always_equal)
    assert not any(i.qtype == "overview" for i in accepted)
    assert {i.reject_reason for i in rejected if i.qtype == "overview"} == {"evidence_only"}

    calls = []
    accepted, rejected = generate_corpus("mini", client, per_type=2, compare=always_equal,
                                         judge=_judge("correct", calls))
    overview = [i for i in accepted if i.qtype == "overview"]
    assert overview and all(i.checks.evidence_only_ok is True for i in overview)
    assert not any(i.qtype == "overview" for i in rejected)
    assert len(calls) == len(overview)  # only the containment misses reach the judge


def _procedure_steps(s, u, r):
    """`stub_for_all`, except procedure replies list steps and overview and procedure items
    are re-answered in other words (so only the judge can accept them)."""
    if s == load_prompt("extractive") and u.startswith("Question type: procedure"):
        reply = json.loads(stub_for_all(s, u, r))
        return json.dumps({**reply, "answer_kind": "set", "answer": STEPS})
    if s == load_prompt("evidence_only") and any(
            q in u for q in QUESTIONS["overview"] + QUESTIONS["procedure"]):
        return json.dumps({"answer": "In other words: it covers the whole section."})
    return stub_for_all(s, u, r)


def test_generate_corpus_accepts_whole_section_items_with_section_evidence(mini_loaded):
    accepted, rejected = generate_corpus("mini", StubClient(_procedure_steps), per_type=2,
                                         compare=always_equal, judge=_judge("correct"))
    sections = {(c.doc_id, c.char_start, c.char_end) for c in _sections(mini_loaded)}
    for qtype in ("overview", "procedure"):
        got = [i for i in accepted if i.qtype == qtype]
        assert len(got) == 2 and not any(i.qtype == qtype for i in rejected)
        for i in got:
            [ev] = i.evidence
            assert (ev.doc_id, ev.char_start, ev.char_end) in sections
            assert ev.quote == mini_loaded.docs[ev.doc_id].text[ev.char_start:ev.char_end]
            assert i.checks.evidence_only_ok is True and i.checks.span_ok is True
    assert {(i.answer.kind, i.answer.value) for i in accepted if i.qtype == "procedure"} \
        == {("text", NUMBERED)}


DOUBLE_JUDGE = '{"label": "incorrect"}\nOn reflection:\n{"label": "correct"}'


def test_golden_path_stays_strict_on_double_object_reply(mini_loaded):
    """Golden generation parses with `parse_json` and builds a default (strict) Judge."""
    double = StubClient(lambda s, u, r: '{"answer": "14 days"}\n{"answer": "30 days"}')
    with pytest.raises(ModelOutputError):
        evidence_only_check(_item(mini_loaded), mini_loaded, double, compare=always_equal)
    with pytest.raises(ModelOutputError):
        evidence_only_check(_item(mini_loaded), mini_loaded, _reply(PARAPHRASE),
                            judge=Judge(StubClient(lambda s, u, r: DOUBLE_JUDGE)))


# -- review exclusions -------------------------------------------------------------------


def test_review_exclusions_move_items_last_and_leave_others_identical(mini_loaded):
    base_acc, base_rej = generate_corpus("mini", STUB, per_type=2, compare=always_equal)
    victim = next(i for i in base_acc if i.qtype == "factoid")
    acc, rej = generate_corpus("mini", STUB, per_type=2, compare=always_equal,
                               exclusions={victim.id: "answerable after all"})
    assert victim.id not in {i.id for i in acc}
    assert [i.model_dump_json() for i in acc] == [
        i.model_dump_json() for i in base_acc if i.id != victim.id]
    moved = next(i for i in rej if i.id == victim.id)
    assert moved.status == "rejected" and moved.reject_reason == "review_excluded"
    assert moved.split is None and moved.rarity is None
    assert [i.model_dump_json() for i in rej if i.id != victim.id] == [
        i.model_dump_json() for i in base_rej]
    assert [i.id for i in rej] == sorted(i.id for i in rej)


def test_review_exclusion_of_one_policy_half_moves_the_pair(mini_loaded):
    acc, rej = generate_corpus("mini", STUB, per_type=2, compare=always_equal,
                               exclusions={"mini-policy_asof-001-a": "typography"})
    assert not [i for i in acc if i.qtype == "policy_asof"]
    assert {i.id for i in rej if i.reject_reason == "review_excluded"} == {
        "mini-policy_asof-001-a", "mini-policy_asof-001-b"}


def test_load_exclusions(tmp_path):
    from adr_eval.golden.verify import load_exclusions

    assert load_exclusions(tmp_path / "absent.json") == {}
    p = tmp_path / "x.json"
    p.write_text('{"a-1": "reason"}', encoding="utf-8")
    assert load_exclusions(p) == {"a-1": "reason"}
    p.write_text('["a-1"]', encoding="utf-8")
    with pytest.raises(ValueError, match="x.json"):
        load_exclusions(p)
