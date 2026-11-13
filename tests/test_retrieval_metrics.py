import math

import pytest

from adr_eval.models import Evidence
from adr_eval.retrieval.chunker import Chunk
from adr_eval.scoring.retrieval_metrics import (
    citation_precision,
    coverage_at_k,
    evidence_cited,
    full_coverage,
    mrr,
    ndcg_at_k,
    recall_at_k,
    tokens_at_k,
)


def ch(cid, start, end, doc="a", text=None):
    return Chunk(chunk_id=cid, doc_id=doc, char_start=start, char_end=end,
                 text=text if text is not None else "x" * (end - start))


def ev(start, end, doc="a"):
    return Evidence(doc_id=doc, char_start=start, char_end=end, quote="q")


LONG = ev(0, 300)  # spans three chunks of 100 characters
THIRDS = [ch("c0", 0, 100), ch("c1", 100, 200), ch("c2", 200, 300)]


def test_perfect_ranking_over_evidence_spanning_several_chunks_is_one():
    assert ndcg_at_k(THIRDS, [[LONG]], 10) == pytest.approx(1.0)
    # two long spans, each split over chunks: one touching chunk per span first is perfect
    other = ev(1000, 1300)
    ranked = [ch("d0", 1000, 1100), THIRDS[0], ch("d1", 1100, 1200), THIRDS[1]]
    assert ndcg_at_k(ranked, [[LONG], [other]], 10) == pytest.approx(1.0)


def test_ndcg_rank_discount_ideal_and_duplicates():
    groups = [[ev(0, 10)], [ev(100, 110)]]
    miss = ch("m", 500, 510)
    assert ndcg_at_k([miss, ch("p", 0, 10)], [[ev(0, 10)]], 10) == pytest.approx(1 / math.log2(3))
    ideal = 1 + 1 / math.log2(3)
    assert ndcg_at_k([ch("p", 0, 10)], groups, 10) == pytest.approx(1 / ideal)
    assert ndcg_at_k([ch("p", 0, 10), ch("p", 0, 10), ch("q", 100, 110)], groups, 10) \
        == pytest.approx((1 + 1 / math.log2(4)) / ideal)  # the duplicate id keeps its rank
    assert ndcg_at_k([], groups, 10) == 0.0 and ndcg_at_k([miss], [], 10) == 0.0
    # ideal is over min(k, #groups) ranks
    assert ndcg_at_k([ch("p", 0, 10)], groups, 1) == pytest.approx(1.0)


def test_chunk_credits_first_uncredited_group_in_group_order():
    g1, g2 = [ev(0, 50)], [ev(40, 100)]
    both = ch("b", 30, 60)  # touches both groups
    only2 = ch("o", 80, 90)
    ideal = 1 + 1 / math.log2(3)
    assert ndcg_at_k([both, only2], [g1, g2], 10) == pytest.approx(1.0)
    assert ndcg_at_k([both, both], [g1, g2], 10) == pytest.approx(1 / ideal)


def test_a_copy_earns_the_same_as_the_original_and_is_credited_once():
    original, copy = ev(0, 10, doc="a"), ev(500, 510, doc="b")
    group = [[original, copy]]
    on_original, on_copy = ch("o", 0, 20, doc="a"), ch("c", 495, 520, doc="b")
    for name, f in (("ndcg", ndcg_at_k), ("recall", recall_at_k)):
        assert f([on_copy], group, 10) == f([on_original], group, 10) == 1.0, name
    assert mrr([on_copy], group) == 1.0
    assert coverage_at_k([on_copy], group, 10) == coverage_at_k([on_original], group, 10) == 1.0
    # retrieving both the original and the copy counts the group once
    second = [ev(900, 910)]
    ideal = 1 + 1 / math.log2(3)
    assert ndcg_at_k([on_original, on_copy], [*group, second], 10) == pytest.approx(1 / ideal)
    assert recall_at_k([on_original, on_copy], [*group, second], 10) == 0.5


def test_recall_mrr_full_coverage_respect_k():
    target = [[ev(0, 10)]]
    ranked = [ch("x", 500, 510), ch("y", 600, 610), ch("p", 0, 20)]
    assert recall_at_k(ranked, target, k=2) == 0.0 and recall_at_k(ranked, target, k=3) == 1.0
    assert mrr(ranked, target) == pytest.approx(1 / 3) and mrr(ranked[:1], target) == 0.0
    assert recall_at_k(ranked, [], 10) == 0.0
    two = [[ev(0, 10)], [ev(100, 110)]]
    assert full_coverage([ch("p", 0, 10), ch("q", 100, 110)], two, 10) is True
    assert full_coverage([ch("p", 0, 10)], two, 10) is False
    assert full_coverage([ch("p", 0, 10), ch("q", 100, 110)], two, 1) is False
    assert full_coverage([], [], 10) is False


@pytest.mark.parametrize("n,expected", [(0, 0.0), (1, 1 / 3), (2, 2 / 3), (3, 1.0)])
def test_coverage_of_span_split_across_three_chunks(n, expected):
    assert coverage_at_k(THIRDS[:n], [[LONG]], 10) == pytest.approx(expected)


def test_coverage_union_best_member_mean_and_k():
    # overlapping chunks are not double counted
    assert coverage_at_k([ch("a", 0, 150), ch("b", 100, 200)], [[LONG]], 10) \
        == pytest.approx(2 / 3)
    # best member of the group; mean over groups
    copy = ev(0, 300, doc="b")
    ranked = [ch("a", 0, 100), ch("b", 0, 300, doc="b")]
    assert coverage_at_k(ranked, [[LONG, copy]], 10) == pytest.approx(1.0)
    assert coverage_at_k(ranked, [[LONG], [ev(1000, 1010)]], 10) == pytest.approx(1 / 6)
    assert coverage_at_k(THIRDS, [[LONG]], 1) == pytest.approx(1 / 3)
    assert coverage_at_k(THIRDS, [], 10) == 0.0


def test_tokens_at_k_counts_stop_words_in_the_top_k():
    ranked = [ch("a", 0, 1, text="The cat sat on the mat."), ch("b", 0, 1, text="A dog"),
              ch("c", 0, 1, text="ignored beyond k")]
    assert tokens_at_k(ranked, 2) == 8
    assert tokens_at_k([], 10) == 0


def test_citation_precision_and_evidence_cited_use_groups():
    groups = [[ev(0, 10), ev(0, 10, doc="b")], [ev(100, 110)]]
    hit_copy, miss = ch("c", 0, 5, doc="b"), ch("m", 500, 510)
    assert citation_precision([], groups) is None
    assert citation_precision([hit_copy, miss], groups) == 0.5
    assert evidence_cited([hit_copy], groups) is True
    assert evidence_cited([miss], groups) is False and evidence_cited([], groups) is False
