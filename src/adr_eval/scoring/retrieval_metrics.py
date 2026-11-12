"""Span-overlap retrieval metrics."""

from __future__ import annotations

import math

from adr_eval.models import Evidence
from adr_eval.retrieval.chunker import Chunk


def overlap(chunk: Chunk, ev: Evidence) -> float:
    """|chunk ∩ ev| / |ev| on the same document, else 0."""
    if chunk.doc_id != ev.doc_id or ev.char_end <= ev.char_start:
        return 0.0
    inter = min(chunk.char_end, ev.char_end) - max(chunk.char_start, ev.char_start)
    return max(inter, 0) / (ev.char_end - ev.char_start)


def recall_at_k(ranked: list[Chunk], evidence: list[Evidence], k: int = 10) -> float:
    if not evidence:
        return 0.0
    top = ranked[:k]
    return sum(any(overlap(c, e) > 0 for c in top) for e in evidence) / len(evidence)


def mrr(ranked: list[Chunk], evidence: list[Evidence]) -> float:
    for i, c in enumerate(ranked, 1):
        if any(overlap(c, e) > 0 for e in evidence):
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: list[Chunk], evidence: list[Evidence], k: int = 10) -> float:
    """Gain = best overlap with a not-yet-credited span (each span credited once).

    Ideal = min(k, #spans) gains of 1.0. Duplicate chunk ids are skipped.
    """
    if not evidence:
        return 0.0
    dcg, seen, credited = 0.0, set(), set()
    for i, c in enumerate(ranked[:k], 1):
        if c.chunk_id in seen:
            continue
        seen.add(c.chunk_id)
        gains = [(overlap(c, e), j) for j, e in enumerate(evidence) if j not in credited]
        gain, j = max(gains, default=(0.0, -1))
        if gain > 0:
            credited.add(j)
            dcg += gain / math.log2(i + 1)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(k, len(evidence)) + 1))
    return dcg / ideal


def full_coverage(ranked: list[Chunk], evidence: list[Evidence], k: int = 10) -> bool:
    return bool(evidence) and recall_at_k(ranked, evidence, k) == 1.0


def citation_precision(cited: list[Chunk], evidence: list[Evidence]) -> float | None:
    """Share of cited chunks overlapping any evidence span; None if nothing cited."""
    if not cited:
        return None
    return sum(any(overlap(c, e) > 0 for e in evidence) for c in cited) / len(cited)


def evidence_cited(cited: list[Chunk], evidence: list[Evidence]) -> bool:
    """True when at least one cited chunk overlaps any evidence span."""
    return any(overlap(c, e) > 0 for c in cited for e in evidence)
