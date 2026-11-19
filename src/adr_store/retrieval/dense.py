"""Dense search over store chunks (spec §8 "Dense").

The embedded text is the breadcrumb, a newline and the chunk body (the breadcrumb prefix), or
the body alone. Vectors come from the `EmbeddingCache`; search is the baseline's
`DenseIndex.search` itself (exact cosine on unit vectors, scores rounded to six decimals, ties
by chunk id), with queries embedded by the cache's model. `search(query, k, mask)` drops the
rows a boolean mask leaves out before the top-k cut (as `FieldBM25.search`); cosine scores do
not depend on other rows, so a masked search equals a search over the kept rows alone.

Row-exact scores (`exact=True`, Phase 2 spec §6.2, B2). The matrix product `vectors @ q` is
BLAS's: its float32 result for one row can differ in the last bits with the number of rows
(blocking), so a search over a view's rows and one over a view-only store could differ in
the 6th decimal. `row_scores` computes each row's cosine as `(row * q).sum()` (numpy's
pairwise sum over the contiguous row), a function of (row, query) alone, bit for bit, however
many other rows there are. The ACL layer uses it (`exact=True`) on every search, a full view
included; without the ACL layer `search` stays the baseline's matrix product (Phase 1), so
the two may differ in the last float32 bits.
"""

from __future__ import annotations

import numpy as np

from adr_eval.retrieval.dense import DenseIndex, _unit
from adr_store.chunking import StoreChunk
from adr_store.embedding import EmbeddingCache
from adr_store.retrieval.lexical import check_mask, masked_hits


def row_scores(vectors: np.ndarray, q: np.ndarray) -> np.ndarray:
    """The cosine of each row of `vectors` (unit float32 rows) with the unit query `q`,
    each a function of that row and `q` alone, bit for bit (module docstring)."""
    v = np.ascontiguousarray(vectors, dtype=np.float32)
    return (v * np.asarray(q, dtype=np.float32)).sum(axis=1)


def embedded_text(chunk: StoreChunk, prefix: bool) -> str:
    return f"{chunk.breadcrumb}\n{chunk.text}" if prefix else chunk.text


class CachedDense(DenseIndex):
    """A `DenseIndex` whose vectors come from an `EmbeddingCache` and whose queries are
    embedded by the cache's model."""

    def __init__(self, cache: EmbeddingCache):
        super().__init__(cache.model_name, cache_dir=cache.cache_dir)
        self.cache = cache
        self.n_new = 0

    def _get_model(self):
        return self.cache.model()

    def model_hash(self) -> str:
        return self.cache.model_hash

    @property
    def chunk_ids(self) -> list[str]:
        """The ids of the rows, in order."""
        return self._ids

    def search(self, query: str, k: int = 100, mask: np.ndarray | None = None, *,
               exact: bool = False) -> list[tuple[str, float]]:
        """The baseline's ranking of the rows `mask` keeps (all when None); `exact` scores
        with `row_scores` instead of the matrix product (module docstring)."""
        if mask is None and not exact:
            return super().search(query, k=k)
        if mask is None:
            mask = np.ones(len(self._ids), dtype=bool)
        mask = check_mask(mask, len(self._ids))
        if not mask.any() or k <= 0:
            return []
        scores = self.exact_scores(query) if exact else self.scores(query)
        return masked_hits(self._ids, scores, mask, k, positive=False)

    def exact_scores(self, query: str) -> np.ndarray | None:
        """`scores` computed by `row_scores` (None for an empty index)."""
        if not self._ids:
            return None
        q = _unit(next(iter(self._get_model().query_embed([query]))))
        return row_scores(self.vectors, q)

    def build_texts(self, ids: list[str], texts: list[str]) -> None:
        """Vectors for `texts` (one per id) from the cache; `n_new` counts new embeddings."""
        vectors, self.n_new = self.cache.embed_texts(texts)
        self.set_vectors(ids, vectors if len(ids) else np.zeros((0, 0), dtype=np.float32))
