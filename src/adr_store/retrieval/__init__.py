"""Retrieval over structure-led chunks (spec §8): field-weighted BM25, dense search with an
optional breadcrumb prefix, linear or RRF fusion, and an optional cross-encoder reranker.

`StoreIndex` puts them together over one store snapshot; the harness reaches it only through
its system registry (`adr_eval.systems`).
"""

from adr_store.retrieval.index import Settings, StoreIndex

__all__ = ["Settings", "StoreIndex"]
