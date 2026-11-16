"""Dense search over store chunks (spec §8 "Dense").

The embedded text is the breadcrumb, a newline and the chunk body (the breadcrumb prefix), or
the body alone. Vectors come from the `EmbeddingCache`; search is the baseline's
`DenseIndex.search` itself (exact cosine on unit vectors, scores rounded to six decimals, ties
by chunk id), with queries embedded by the cache's model. `search(query, k, mask)` drops the
rows a boolean mask leaves out before the top-k cut (as `FieldBM25.search`); cosine scores do
not depend on other rows, so a masked search equals a search over the kept rows alone.
"""

from __future__ import annotations

import numpy as np

from adr_eval.retrieval.dense import DenseIndex
from adr_store.chunking import StoreChunk
from adr_store.embedding import EmbeddingCache
from adr_store.retrieval.lexical import check_mask, masked_hits


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

    def search(self, query: str, k: int = 100,
               mask: np.ndarray | None = None) -> list[tuple[str, float]]:
        if mask is None:
            return super().search(query, k=k)
        mask = check_mask(mask, len(self._ids))
        if not mask.any() or k <= 0:
            return []
        return masked_hits(self._ids, self.scores(query), mask, k, positive=False)

    def build_texts(self, ids: list[str], texts: list[str]) -> None:
        """Vectors for `texts` (one per id) from the cache; `n_new` counts new embeddings."""
        vectors, self.n_new = self.cache.embed_texts(texts)
        self.set_vectors(ids, vectors if len(ids) else np.zeros((0, 0), dtype=np.float32))
