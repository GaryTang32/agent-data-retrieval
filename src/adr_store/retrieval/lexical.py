"""Field-weighted BM25 (spec §8 "Lexical", ruling 4).

A chunk's indexed tokens are its body tokens followed by its breadcrumb tokens repeated `w_bc`
times: BM25F with one shared length normalisation. It is the baseline's `BM25Index` (same
tokenizer, library, `k1` and `b`), built over copies of the chunks whose text is
`body + (" " + breadcrumb) * w_bc` and whose ids are the chunks' own. The stored chunks are not
changed, so ranked ids and the text a reader gets are the chunks' own; with `w_bc` 0 the index
is plain BM25 over the same chunks.
"""

from __future__ import annotations

from adr_eval.retrieval.chunker import Chunk
from adr_eval.retrieval.lexical import BM25Index
from adr_store.chunking import StoreChunk


def check_w_bc(w_bc: object) -> int:
    if isinstance(w_bc, bool) or not isinstance(w_bc, int) or w_bc < 0:
        raise ValueError(f"w_bc must be an integer >= 0, got {w_bc!r}")
    return w_bc


def indexed_text(chunk: StoreChunk, w_bc: int) -> str:
    """The text BM25 indexes for `chunk`: its body, then its breadcrumb `w_bc` times."""
    return chunk.text + (" " + chunk.breadcrumb) * w_bc


class FieldBM25:
    """`BM25Index` over body plus `w_bc` breadcrumb repetitions; `search` as the baseline's."""

    def __init__(self, w_bc: int = 0, k1: float = 1.2, b: float = 0.75):
        self.w_bc = check_w_bc(w_bc)
        self.bm25 = BM25Index(k1=k1, b=b)

    def build(self, chunks: list[StoreChunk]) -> None:
        self.bm25.build([Chunk(c.chunk_id, c.doc_id, c.char_start, c.char_end,
                               indexed_text(c, self.w_bc)) for c in chunks])

    def search(self, query: str, k: int = 100) -> list[tuple[str, float]]:
        return self.bm25.search(query, k=k)

    def config(self) -> dict:
        return {**self.bm25.config(), "field": "breadcrumb", "w_bc": self.w_bc}
