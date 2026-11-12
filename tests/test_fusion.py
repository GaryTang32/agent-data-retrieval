import pytest

from adr_eval.retrieval.fusion import linear, minmax, rank, rrf, tune_linear_weight


def test_rrf_known_values():
    out = rrf([[("a", 9), ("b", 1)], [("b", 5), ("c", 4)]], k=60, top=3)
    assert out[0][0] == "b"
    assert out[0][1] == round(1 / 62 + 1 / 61, 6)
    assert [c for c, _ in out] == ["b", "a", "c"]
    assert len(rrf([[("a", 1), ("b", 1)]], top=1)) == 1
    assert rrf([[], []]) == []


def test_linear_falls_back_to_dense_when_lexical_empty():
    assert [c for c, _ in linear([], [("x", 0.9), ("y", 0.1)], w=0.5)] == ["x", "y"]


def test_linear_union_and_weights():
    lex = [("a", 10.0), ("b", 0.0)]
    dense = [("b", 0.8), ("c", 0.2)]
    out = dict(linear(lex, dense, w=1.0))
    assert out["a"] == 1.0 and out["b"] == 0.0 and out["c"] == 0.0
    out = dict(linear(lex, dense, w=0.0))
    assert out["b"] == 1.0 and out["c"] == 0.0 and out["a"] == 0.0
    assert {c for c, _ in linear(lex, dense, w=0.5)} == {"a", "b", "c"}


def test_minmax_degenerate():
    assert minmax([]) == {}
    assert minmax([("a", 3.0), ("b", 3.0)]) == {"a": 0.0, "b": 0.0}
    assert minmax([("a", 1.0), ("b", 3.0)]) == {"a": 0.0, "b": 1.0}


def test_rank_tiebreak_by_chunk_id():
    assert [c for c, _ in rank({"b": 0.3333334, "a": 0.3333333}, 2)] == ["a", "b"]
    assert len(rank({"a": 1, "b": 2, "c": 3}, 2)) == 2


def test_tune_weight_picks_smallest_on_tie():
    assert tune_linear_weight([([("a", 1.0)], [("a", 1.0)], lambda ids: 0.5)]) == 0.0


def test_tune_weight_finds_best_and_validates():
    lex = [("l", 1.0), ("d", 0.0)]
    dense = [("d", 1.0), ("l", 0.0)]

    def ndcg(ids):  # rewards "l" ranked first
        return 1.0 if ids[0] == "l" else 0.0

    w = tune_linear_weight([(lex, dense, ndcg)])
    assert w > 0.5 and w == round(w, 2)
    with pytest.raises(ValueError):
        tune_linear_weight([])
