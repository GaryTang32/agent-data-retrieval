"""Rank fusion of lexical and dense result lists (RRF and min-max linear)."""

from __future__ import annotations

from collections.abc import Callable

Hits = list[tuple[str, float]]

_GRID = [round(i * 0.05, 2) for i in range(21)]


def rank(scores: dict[str, float], top: int) -> Hits:
    """Round to 6 dp, then order by (-score, chunk_id) so ties are deterministic."""
    hits = [(cid, round(float(s), 6)) for cid, s in scores.items()]
    hits.sort(key=lambda h: (-h[1], h[0]))
    return hits[:top]


def rrf(lists: list[Hits], k: int = 60, top: int = 10) -> Hits:
    scores: dict[str, float] = {}
    for lst in lists:
        for pos, (cid, _) in enumerate(lst, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + pos)
    return rank(scores, top)


def minmax(lst: Hits) -> dict[str, float]:
    if not lst:
        return {}
    vals = [s for _, s in lst]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return {cid: 0.0 for cid, _ in lst}
    return {cid: (s - lo) / (hi - lo) for cid, s in lst}


def linear(lex: Hits, dense: Hits, w: float, top: int = 10) -> Hits:
    a, b = minmax(lex), minmax(dense)
    scores = {cid: w * a.get(cid, 0.0) + (1.0 - w) * b.get(cid, 0.0) for cid in a.keys() | b.keys()}
    return rank(scores, top)


def tune_linear_weight(queries: list[tuple[Hits, Hits, Callable[[list[str]], float]]]) -> float:
    """Grid-search w in 0.00..1.00 (step 0.05) maximising mean nDCG@10; ties keep the smallest w."""
    if not queries:
        raise ValueError("tune_linear_weight needs at least one query")
    best_w, best = _GRID[0], float("-inf")
    for w in _GRID:
        mean = sum(
            ndcg([cid for cid, _ in linear(lex, dense, w, top=10)]) for lex, dense, ndcg in queries
        ) / len(queries)
        if mean > best + 1e-12:
            best_w, best = w, mean
    return best_w
