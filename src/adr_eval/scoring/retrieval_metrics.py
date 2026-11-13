"""Retrieval and citation metrics over evidence groups (spec §4 of the metric definitions).

A group is an evidence span plus its identical copies (`scoring.evidence_groups`). A chunk
touches a group when it overlaps any member; each group is credited at most once.
"""

from __future__ import annotations

import math

from adr_eval.models import Evidence
from adr_eval.retrieval.chunker import Chunk, tokenize

Groups = list[list[Evidence]]


def overlap(chunk: Chunk, ev: Evidence) -> float:
    """|chunk ∩ ev| / |ev| on the same document, else 0."""
    if chunk.doc_id != ev.doc_id or ev.char_end <= ev.char_start:
        return 0.0
    inter = min(chunk.char_end, ev.char_end) - max(chunk.char_start, ev.char_start)
    return max(inter, 0) / (ev.char_end - ev.char_start)


def touches(chunk: Chunk, group: list[Evidence]) -> bool:
    """Whether `chunk` overlaps any member of `group`."""
    return any(overlap(chunk, e) > 0 for e in group)


def _touches_any(chunk: Chunk, groups: Groups) -> bool:
    return any(touches(chunk, g) for g in groups)


def recall_at_k(ranked: list[Chunk], groups: Groups, k: int = 10) -> float:
    """Share of groups touched by at least one of the top k chunks."""
    if not groups:
        return 0.0
    top = ranked[:k]
    return sum(any(touches(c, g) for c in top) for g in groups) / len(groups)


def mrr(ranked: list[Chunk], groups: Groups) -> float:
    """1 / rank of the first chunk that touches any group; 0 if none."""
    for i, c in enumerate(ranked, 1):
        if _touches_any(c, groups):
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: list[Chunk], groups: Groups, k: int = 10) -> float:
    """Binary gain: a chunk touching a not-yet-credited group earns 1 and credits the first
    such group. Ideal = min(k, #groups) gains of 1. Duplicate chunk ids are skipped."""
    if not groups:
        return 0.0
    dcg, seen, credited = 0.0, set(), set()
    for i, c in enumerate(ranked[:k], 1):
        if c.chunk_id in seen:
            continue
        seen.add(c.chunk_id)
        j = next((j for j, g in enumerate(groups) if j not in credited and touches(c, g)), None)
        if j is not None:
            credited.add(j)
            dcg += 1.0 / math.log2(i + 1)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(k, len(groups)) + 1))
    return dcg / ideal


def full_coverage(ranked: list[Chunk], groups: Groups, k: int = 10) -> bool:
    """Every group touched by the top k."""
    return bool(groups) and recall_at_k(ranked, groups, k) == 1.0


def _union(chunks: list[Chunk]) -> dict[str, list[tuple[int, int]]]:
    """Merged character ranges covered by `chunks`, per document."""
    by_doc: dict[str, list[tuple[int, int]]] = {}
    for c in sorted(chunks, key=lambda c: (c.doc_id, c.char_start)):
        spans = by_doc.setdefault(c.doc_id, [])
        if spans and c.char_start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], c.char_end))
        else:
            spans.append((c.char_start, c.char_end))
    return by_doc


def _covered(ev: Evidence, union: dict[str, list[tuple[int, int]]]) -> float:
    """Share of `ev`'s characters inside `union`."""
    if ev.char_end <= ev.char_start:
        return 0.0
    inside = sum(max(0, min(e, ev.char_end) - max(s, ev.char_start))
                 for s, e in union.get(ev.doc_id, []))
    return inside / (ev.char_end - ev.char_start)


def coverage_at_k(ranked: list[Chunk], groups: Groups, k: int = 10) -> float:
    """Mean over groups of the best member's share of characters inside the top k chunks."""
    if not groups:
        return 0.0
    union = _union(ranked[:k])
    return sum(max(_covered(e, union) for e in g) for g in groups) / len(groups)


def tokens_at_k(ranked: list[Chunk], k: int = 10) -> int:
    """Total tokens of the top k chunks (harness tokenizer, stop words kept)."""
    return sum(len(tokenize(c.text, drop_stopwords=False)) for c in ranked[:k])


def citation_precision(cited: list[Chunk], groups: Groups) -> float | None:
    """Share of cited chunks touching any group; None if nothing cited."""
    if not cited:
        return None
    return sum(_touches_any(c, groups) for c in cited) / len(cited)


def evidence_cited(cited: list[Chunk], groups: Groups) -> bool:
    """True when at least one cited chunk touches any group."""
    return any(_touches_any(c, groups) for c in cited)
