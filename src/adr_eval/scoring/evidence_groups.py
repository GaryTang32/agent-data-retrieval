"""Evidence groups: each golden evidence span plus its identical copies in other documents.

A copy is an occurrence, in another document, of the span's text together with up to
`CONTEXT_CHARS` characters on each side, compared after whitespace normalisation (the rule
`check_spans` uses). Items with an as-of date get no copies: only the dated copy is right.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable

from adr_eval.corpora.base import Document
from adr_eval.golden.verify import _normalize_with_map, normalize_ws
from adr_eval.models import Evidence, GoldenItem

CONTEXT_CHARS = 200


class _Corpus:
    """Every document's normalised text, computed once for all searches."""

    def __init__(self, docs: dict[str, Document]):
        self.docs = docs
        # kept per document: one joined string would be widened to its widest character
        self.norm = {doc_id: normalize_ws(docs[doc_id].text) for doc_id in sorted(docs)}
        self._maps: dict[str, list[int]] = {}

    def offsets(self, doc_id: str) -> list[int]:
        """Raw offset of each normalised character of `doc_id` (computed once, on demand)."""
        if doc_id not in self._maps:
            self._maps[doc_id] = _normalize_with_map(self.docs[doc_id].text)[1]
        return self._maps[doc_id]

    def occurrences(self, passage: str) -> Iterable[tuple[str, int]]:
        """(doc_id, normalised offset) of every occurrence of a normalised passage."""
        if not passage:
            return
        for doc_id, text in self.norm.items():
            pos = text.find(passage)
            while pos >= 0:
                yield doc_id, pos
                pos = text.find(passage, pos + 1)

    def copies(self, ev: Evidence) -> list[Evidence]:
        """Copies of `ev` in other documents, ordered by (doc_id, char_start)."""
        src = self.docs.get(ev.doc_id)
        if src is None:
            return []
        lo = max(0, ev.char_start - CONTEXT_CHARS)
        hi = min(len(src.text), ev.char_end + CONTEXT_CHARS)
        passage, idx = _normalize_with_map(src.text[lo:hi])
        # the evidence is the normalised characters whose raw offsets fall in its range
        # (offsets never decrease), less a leading space that joins it to the context
        k, k_end = bisect_left(idx, ev.char_start - lo), bisect_left(idx, ev.char_end - lo)
        if k < k_end and passage[k] == " ":
            k += 1
        quote = passage[k:k_end]
        if not quote:
            return []
        found: set[tuple[str, int, int]] = set()
        for doc_id, p in self.occurrences(passage):
            if doc_id == ev.doc_id:
                continue
            m = self.offsets(doc_id)
            start, end = m[p + k], m[p + k + len(quote) - 1] + 1
            # a match starting inside a character that NFKC expands does not re-slice
            if normalize_ws(self.docs[doc_id].text[start:end]) == quote:
                found.add((doc_id, start, end))
        return [Evidence(doc_id=d, char_start=s, char_end=e, quote=ev.quote)
                for d, s, e in sorted(found)]


def _groups(item: GoldenItem, corpus: _Corpus | None) -> list[list[Evidence]]:
    if item.as_of is not None or corpus is None:
        return [[ev] for ev in item.evidence]
    return [[ev, *corpus.copies(ev)] for ev in item.evidence]


def build_groups(item: GoldenItem, docs: dict[str, Document]) -> list[list[Evidence]]:
    """One group per evidence span: the original first, then its copies."""
    corpus = _Corpus(docs) if item.as_of is None and item.evidence else None
    return _groups(item, corpus)


def build_all(items: list[GoldenItem],
              docs: dict[str, Document]) -> dict[str, list[list[Evidence]]]:
    """`build_groups` for every item, keyed by item id; the corpus is normalised once."""
    corpus = _Corpus(docs) if any(i.as_of is None and i.evidence for i in items) else None
    return {i.id: _groups(i, corpus) for i in items}


def copy_stats(groups: Iterable[list[list[Evidence]]]) -> dict[str, int]:
    """Spans, spans with at least one copy, and copies, over the given items' groups."""
    spans = [g for item_groups in groups for g in item_groups]
    return {"spans": len(spans), "spans_with_copies": sum(len(g) > 1 for g in spans),
            "copies": sum(len(g) - 1 for g in spans)}
