"""Field-weighted BM25 (spec §8 "Lexical", ruling 4).

A chunk's indexed tokens are its body tokens followed by its breadcrumb tokens repeated `w_bc`
times: BM25F with one shared length normalisation. It is the baseline's `BM25Index` (same
tokenizer, library, `k1` and `b`), built over copies of the chunks whose text is
`body + (" " + breadcrumb) * w_bc` and whose ids are the chunks' own. The stored chunks are not
changed, so ranked ids and the text a reader gets are the chunks' own; with `w_bc` 0 the index
is plain BM25 over the same chunks.

`search(query, k, mask)` takes an optional boolean mask over the index's rows (build order,
`chunk_ids`; `doc_ids` holds each row's document): masked-out rows are dropped before the
top-k cut, with the baseline's rounding, zero-score exclusion and tie-break, so a mask never
starves the result and an all-true mask gives the unmasked ranking. Without a mask, `search`
is the baseline's call itself. A mask changes no BM25 statistic (Phase 2 spec §6.2).
"""

from __future__ import annotations

import numpy as np

from adr_eval.retrieval.chunker import Chunk
from adr_eval.retrieval.lexical import BM25Index
from adr_store.chunking import StoreChunk


def check_w_bc(w_bc: object) -> int:
    if isinstance(w_bc, bool) or not isinstance(w_bc, int) or w_bc < 0:
        raise ValueError(f"w_bc must be an integer >= 0, got {w_bc!r}")
    return w_bc


def check_mask(mask: object, n: int) -> np.ndarray:
    """`mask` as a boolean array of one value per row of a channel of `n` rows."""
    if not isinstance(mask, np.ndarray) or mask.dtype != np.bool_ or mask.shape != (n,):
        raise ValueError(f"mask must be a boolean numpy array of shape ({n},), got "
                         f"{type(mask).__name__} "
                         f"{getattr(mask, 'dtype', '')}{getattr(mask, 'shape', '')}")
    return mask


def doc_mask(doc_ids: np.ndarray, allowed_docs: frozenset[str]) -> np.ndarray:
    """True for the rows of `doc_ids` (one document id per row) that are in `allowed_docs`."""
    return np.isin(doc_ids, np.array(sorted(allowed_docs), dtype=str))


def masked_hits(ids: list[str], scores, mask: np.ndarray, k: int,
                positive: bool) -> list[tuple[str, float]]:
    """The baseline's ranking of `scores` (rounded to 6 decimals, best first, ties by id;
    only positive rounded scores when `positive`) over the rows `mask` keeps, cut at `k`."""
    if scores is None or k <= 0:
        return []
    keep = mask & (np.asarray(scores) > 0) if positive else mask
    hits = [(ids[i], round(float(scores[i]), 6)) for i in np.flatnonzero(keep)]
    if positive:
        hits = [h for h in hits if h[1] > 0]
    hits.sort(key=lambda h: (-h[1], h[0]))
    return hits[:k]


def indexed_text(chunk: StoreChunk, w_bc: int) -> str:
    """The text BM25 indexes for `chunk`: its body, then its breadcrumb `w_bc` times."""
    return chunk.text + (" " + chunk.breadcrumb) * w_bc


class FieldBM25:
    """`BM25Index` over body plus `w_bc` breadcrumb repetitions; `search` as the baseline's."""

    def __init__(self, w_bc: int = 0, k1: float = 1.2, b: float = 0.75):
        self.w_bc = check_w_bc(w_bc)
        self.bm25 = BM25Index(k1=k1, b=b)
        self.chunk_ids: list[str] = []
        self.doc_ids = np.zeros(0, dtype=str)

    def build(self, chunks: list[StoreChunk]) -> None:
        self.chunk_ids = [c.chunk_id for c in chunks]
        self.doc_ids = np.array([c.doc_id for c in chunks], dtype=str)
        self.bm25.build([Chunk(c.chunk_id, c.doc_id, c.char_start, c.char_end,
                               indexed_text(c, self.w_bc)) for c in chunks])

    def search(self, query: str, k: int = 100,
               mask: np.ndarray | None = None) -> list[tuple[str, float]]:
        if mask is None:
            return self.bm25.search(query, k=k)
        mask = check_mask(mask, len(self.chunk_ids))
        if not mask.any() or k <= 0:
            return []
        return masked_hits(self.chunk_ids, self.bm25.scores(query), mask, k, positive=True)

    def mask(self, allowed_docs: frozenset[str]) -> np.ndarray:
        """True for the rows whose document is in `allowed_docs`."""
        return doc_mask(self.doc_ids, allowed_docs)

    def config(self) -> dict:
        return {**self.bm25.config(), "field": "breadcrumb", "w_bc": self.w_bc}
