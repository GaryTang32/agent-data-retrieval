import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from adr_eval.corpora.base import Document, LoadedCorpus, load_corpus
from adr_eval.golden.generate import evidence_only_check
from adr_eval.llm import StubClient
from adr_eval.models import Answer, Evidence, GoldenItem, Manifest, ManifestDoc
from adr_eval.retrieval.chunker import Chunk
from adr_eval.scoring.compile_metrics import span_containment, text_fidelity
from adr_eval.scoring.determinism import answer_agreement, pass_hat_k, retrieval_identity_rate
from adr_eval.scoring.exact import exact_outcome, normalize_value, parse_number, set_prf
from adr_eval.scoring.outcomes import penalised_score
from adr_eval.scoring.retrieval_metrics import (
    citation_precision,
    evidence_cited,
    full_coverage,
    mrr,
    ndcg_at_k,
    overlap,
    recall_at_k,
)

MINI = Path(__file__).parent / "fixtures" / "mini"


def sa(value=None, kind="text", abstain=False):
    return SimpleNamespace(value=value, kind=kind, citations=[], abstain=abstain,
                           confidence=1.0, completion=None)


def ch(cid, start, end, doc="a"):
    return Chunk(chunk_id=cid, doc_id=doc, char_start=start, char_end=end, text="x" * (end - start))


EV = Evidence(doc_id="a", char_start=0, char_end=10, quote="q")
EV_OTHER = Evidence(doc_id="a", char_start=100, char_end=110, quote="r")
C_FULL = ch("c1", 0, 20)


# -- outcomes ----------------------------------------------------------------------------


@pytest.mark.parametrize("t,expected", [(0.5, (1 + 0 - 1) / 3), (0.75, (1 + 0 - 3) / 3),
                                        (0.9, (1 + 0 - 9) / 3)])
def test_penalised_score(t, expected):
    assert penalised_score(["correct", "abstained", "wrong"], t) == pytest.approx(expected)


def test_partial_counts_as_wrong_and_error_excluded():
    assert penalised_score(["correct", "partial", "error"], 0.5) == pytest.approx(0.0)


def test_penalised_score_all_errors_or_empty_is_zero():
    assert penalised_score(["error"], 0.5) == 0.0
    assert penalised_score([], 0.5) == 0.0


# -- exact -------------------------------------------------------------------------------


def test_number_parse_with_units():
    assert parse_number("1,234 days") == 1234.0 and parse_number("12.5%") == 12.5
    assert parse_number("$3,000") == 3000.0 and parse_number("2 years") == 2.0
    assert parse_number(4) == 4.0 and parse_number("abc") is None


def test_normalize_value():
    assert normalize_value("  “Hello,  World.” ") == "hello, world"
    assert normalize_value("ﬁle   A") == "file a"


def test_set_exact_and_prf():
    assert set_prf({"a", "b"}, {"a"}) == (1.0, 0.5, pytest.approx(2 / 3))
    assert set_prf(set(), set()) == (1.0, 1.0, 1.0)
    assert set_prf({"a"}, set()) == (0.0, 0.0, 0.0)


def test_abstain_gold_requires_abstention():
    assert exact_outcome(Answer(kind="abstain", value=None), sa(abstain=True)) == "correct"
    assert exact_outcome(Answer(kind="abstain", value=None), sa(value="x")) == "wrong"


def test_abstaining_on_answerable_is_abstained():
    assert exact_outcome(Answer(kind="id", value="A-1"), sa(abstain=True)) == "abstained"


def test_text_needs_judge():
    assert exact_outcome(Answer(kind="text", value="x"), sa("x")) is None
    assert exact_outcome(Answer(kind="text", value="x"), sa(abstain=True)) == "abstained"


def test_id_matches_value_or_variant_normalized():
    gold = Answer(kind="id", value="REC-001", accepted_variants=["Record 1"])
    assert exact_outcome(gold, sa(" rec-001. ", "id")) == "correct"
    assert exact_outcome(gold, sa("record 1")) == "correct"
    assert exact_outcome(gold, sa("REC-002")) == "wrong"
    assert exact_outcome(gold, sa(None)) == "wrong"


def test_number_tolerance_and_unparseable():
    gold = Answer(kind="number", value=2.0)
    assert exact_outcome(gold, sa("2", "number")) == "correct"
    assert exact_outcome(gold, sa(2.0000000001)) == "correct"
    assert exact_outcome(gold, sa(2.1)) == "wrong"
    assert exact_outcome(gold, sa("two")) == "wrong"
    assert exact_outcome(Answer(kind="number", value=0.0), sa(0.0)) == "correct"
    assert exact_outcome(Answer(kind="number", value=0.0), sa(0.001)) == "wrong"
    assert exact_outcome(Answer(kind="number", value=1234.0), sa("1,234 days")) == "correct"


def test_set_correct_only_on_exact_match():
    gold = Answer(kind="set", value=["A.", "b"])
    assert exact_outcome(gold, sa(["B", "a"], "set")) == "correct"
    assert exact_outcome(gold, sa(["a"])) == "wrong"
    assert exact_outcome(gold, sa(["a", "b", "c"])) == "wrong"
    assert exact_outcome(gold, sa("a")) == "wrong"


def test_pred_kind_mismatch_scored_by_gold_kind():
    assert exact_outcome(Answer(kind="id", value="x"), sa("x", kind="text")) == "correct"


def test_evidence_only_check_default_compare_uses_exact_outcome():
    corpus = load_corpus(MINI / "manifest.json", MINI)
    items = [GoldenItem.model_validate_json(line)
             for line in (MINI / "golden.jsonl").read_text().splitlines()]
    item = next(i for i in items if i.id == "mini-count-1")
    right = StubClient(lambda s, u, r: json.dumps({"answer": "2"}))
    wrong = StubClient(lambda s, u, r: json.dumps({"answer": "3"}))
    assert evidence_only_check(item, corpus, right, compare=None) is True
    assert evidence_only_check(item, corpus, wrong, compare=None) is False
    proc = next(i for i in items if i.id == "mini-procedure-1")
    got = StubClient(lambda s, u, r: json.dumps({"answer": list(proc.answer.value)}))
    assert evidence_only_check(proc, corpus, got, compare=None) is True


# -- retrieval ---------------------------------------------------------------------------


def test_overlap():
    assert overlap(ch("c", 5, 20), EV) == 0.5
    assert overlap(ch("c", 0, 20, doc="b"), EV) == 0.0
    assert overlap(ch("c", 10, 20), EV) == 0.0


def test_ndcg_perfect_is_one_and_recall_partial():
    assert ndcg_at_k([C_FULL], [[EV]], 10) == pytest.approx(1.0)
    assert recall_at_k([C_FULL], [[EV], [EV_OTHER]], 10) == 0.5


def test_ndcg_discounts_rank_and_empty_is_zero():
    import math
    assert ndcg_at_k([ch("x", 500, 510), C_FULL], [[EV]], 10) == pytest.approx(1 / math.log2(3))
    assert ndcg_at_k([C_FULL], [], 10) == 0.0
    assert ndcg_at_k([], [[EV]], 10) == 0.0


def test_ndcg_two_spans_one_chunk_is_below_one():
    # ideal DCG has two gains of 1.0; one chunk can only deliver one.
    assert ndcg_at_k([C_FULL], [[EV], [EV_OTHER]], 10) < 1.0


def test_recall_and_mrr_respect_k():
    ranked = [ch("x", 500, 510), ch("y", 600, 610), C_FULL]
    assert recall_at_k(ranked, [[EV]], k=2) == 0.0
    assert recall_at_k(ranked, [[EV]], k=3) == 1.0
    assert mrr(ranked, [[EV]]) == pytest.approx(1 / 3)
    assert mrr([ch("x", 500, 510)], [[EV]]) == 0.0
    assert recall_at_k(ranked, [], 10) == 0.0


def test_full_coverage():
    both = [ch("p", 0, 10), ch("q", 100, 110)]
    assert full_coverage(both, [[EV], [EV_OTHER]], 10) is True
    assert full_coverage(both[:1], [[EV], [EV_OTHER]], 10) is False
    assert full_coverage(both, [[EV], [EV_OTHER]], 1) is False


def test_citation_precision_and_evidence_cited():
    assert citation_precision([], [[EV]]) is None
    assert citation_precision([C_FULL, ch("x", 500, 510)], [[EV]]) == 0.5
    assert evidence_cited([C_FULL], [[EV], [EV_OTHER]]) is True  # any span, not all
    assert evidence_cited([], [[EV]]) is False
    assert evidence_cited([ch("x", 500, 510)], [[EV]]) is False


# -- compile metrics ---------------------------------------------------------------------


def test_span_containment(make_item):
    items = [make_item(evidence=[EV, EV_OTHER])]
    chunks = {"a": [ch("c1", 0, 50), ch("c2", 50, 105)]}
    assert span_containment(items, chunks) == 0.5
    assert span_containment([], chunks) == 0.0


def _corpus(tmp_path, files):
    docs, mdocs = {}, []
    for i, (fmt, raw, text) in enumerate(files):
        p = tmp_path / f"f{i}.{fmt}"
        p.write_bytes(raw)
        mdocs.append(ManifestDoc(doc_id=f"d{i}", uri="u", format=fmt, source_version="1",
                                 bytes=len(raw), license="pd", path=p.name))
        docs[f"d{i}"] = Document(f"d{i}", text, fmt, "1", "u")
    m = Manifest(corpus="t", version="1", license_summary="x", documents=mdocs)
    return LoadedCorpus(manifest=m, docs=docs, empty_docs=[], root=tmp_path)


def test_text_fidelity(tmp_path):
    corpus = _corpus(tmp_path, [("md", b"hello", "hello"), ("txt", b"abc", "abd"),
                                ("pdf", b"%PDF", "x"), ("html", b"<p>", "x")])
    r = text_fidelity(corpus)
    assert r == {"checked": 2, "matching": 1, "share": 0.5, "formats_na": ["html", "pdf"]}


def test_text_fidelity_nothing_checkable(tmp_path):
    r = text_fidelity(_corpus(tmp_path, [("pdf", b"%PDF", "x")]))
    assert r == {"checked": 0, "matching": 0, "share": None, "formats_na": ["pdf"]}


# -- determinism -------------------------------------------------------------------------


def test_retrieval_identity_rate():
    assert retrieval_identity_rate(
        {"i": [["a", "b"]] * 5, "j": [["a"], ["b"], ["a"], ["a"], ["a"]]}) == 0.5
    assert retrieval_identity_rate({}) == 0.0


def test_answer_agreement():
    runs = {"i": ["A", "a.", "a"], "j": ["x", "y"], "k": ["only one"]}
    # i: 3 of 3 pairs agree; j: 0 of 1; k skipped
    assert answer_agreement(runs) == pytest.approx(0.5)
    assert answer_agreement({"k": ["z"]}) is None
    assert answer_agreement({}) is None
    assert answer_agreement({"i": ["a", "a", "b"]}) == pytest.approx(1 / 3)


def test_pass_hat_k():
    runs = {"i": ["correct"] * 5, "j": ["correct", "wrong"], "k": []}
    assert pass_hat_k(runs) == pytest.approx(1 / 3)
    assert pass_hat_k({}) == 0.0


# -- review fix round 1 ------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("−5", -5.0), ("–5", -5.0), ("‒5", -5.0), ("-$5", -5.0), ("-3.5", -3.5),
    ("1,234.5", 1234.5), ("", None), ("abc", None), ("3 days", 3.0),
])
def test_parse_number_signs_and_edges(raw, expected):
    assert parse_number(raw) == expected


def test_ndcg_duplicate_chunk_not_double_counted():
    assert ndcg_at_k([C_FULL, C_FULL], [[EV]], 10) == pytest.approx(1.0)
    assert ndcg_at_k([C_FULL, ch("c2", 0, 30)], [[EV]], 10) == pytest.approx(1.0)


def test_ndcg_partial_chunks_over_one_span_at_most_one():
    assert ndcg_at_k([ch("p", 0, 5), ch("q", 5, 10)], [[EV]], 10) <= 1.0


def test_ndcg_never_exceeds_one_and_other_metrics_unaffected():
    ranked = [C_FULL, C_FULL, ch("c2", 0, 30)]
    assert ndcg_at_k(ranked, [[EV]], 10) <= 1.0
    assert recall_at_k(ranked, [[EV]], 10) == 1.0
    assert mrr(ranked, [[EV]]) == 1.0
    assert full_coverage(ranked, [[EV]], 10) is True


def test_number_accepts_variants():
    gold = Answer(kind="number", value=13.0, accepted_variants=["13 pages"])
    assert exact_outcome(gold, sa("13 pages", "number")) == "correct"  # the variant as written
    pct = Answer(kind="number", value=0.31, accepted_variants=["31%", "not a number"])
    assert exact_outcome(pct, sa("31 %", "number")) == "correct"  # parsed, compared with _close
    assert exact_outcome(pct, sa(31.0, "number")) == "correct"
    assert exact_outcome(pct, sa(0.31, "number")) == "correct"
    assert exact_outcome(pct, sa(32.0, "number")) == "wrong"
    assert exact_outcome(pct, sa("14 pages", "number")) == "wrong"


def test_set_accepts_list_like_variants():
    gold = Answer(kind="set", value=["a", "b"],
                  accepted_variants=['["alpha", "Beta"]', "a and b", "{bad json"])
    assert exact_outcome(gold, sa(["beta", "ALPHA."], "set")) == "correct"
    assert exact_outcome(gold, sa(["b", "a"], "set")) == "correct"
    assert exact_outcome(gold, sa(["alpha"], "set")) == "wrong"
    assert exact_outcome(gold, sa("A and B", "set")) == "correct"  # the variant as written
    assert exact_outcome(gold, sa("a", "set")) == "wrong"
