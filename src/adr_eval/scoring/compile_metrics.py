"""Corpus-compilation health metrics (chunk containment, text fidelity)."""

from __future__ import annotations

from adr_eval.corpora.base import LoadedCorpus
from adr_eval.models import GoldenItem
from adr_eval.retrieval.chunker import Chunk

_CHECKABLE = {"md", "txt", "csv"}


def span_containment(items: list[GoldenItem], chunks_by_doc: dict[str, list[Chunk]]) -> float:
    """Share of evidence spans that lie fully inside a single chunk."""
    total = inside = 0
    for item in items:
        for ev in item.evidence:
            total += 1
            inside += any(c.char_start <= ev.char_start and ev.char_end <= c.char_end
                          for c in chunks_by_doc.get(ev.doc_id, []))
    return inside / total if total else 0.0


def text_fidelity(corpus: LoadedCorpus) -> dict:
    """For md/txt/csv, share of documents whose extracted text equals the decoded bytes."""
    checked = matching = 0
    na: set[str] = set()
    for d in corpus.manifest.documents:
        if d.format not in _CHECKABLE or corpus.root is None:
            na.add(d.format)
            continue
        raw = (corpus.root / d.path).read_bytes().decode("utf-8", errors="replace")
        checked += 1
        matching += corpus.docs[d.doc_id].text == raw
    return {"checked": checked, "matching": matching,
            "share": matching / checked if checked else None, "formats_na": sorted(na)}
