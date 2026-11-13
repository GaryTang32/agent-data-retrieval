"""Structure-led chunks over one store snapshot, each with a breadcrumb (spec §7).

A chunk is a run of consecutive leaves of one section (the innermost section containing them,
or the region before a document's first heading). Leaves are packed in text order while the
chunk's token count, counted as the baseline chunker counts it, stays within `max_tokens`; a
leaf longer than that is cut with the baseline's recursive splitter and its pieces are packed
like leaves. A chunk's range runs from its first leaf (or piece) to its last, so it re-slices
the canonical text exactly; `chunk_id` is the baseline's. Deterministic, no model calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from adr_eval.retrieval.chunker import CHUNKER_CONFIG, Chunk, make_chunk_id
from adr_eval.retrieval.chunker import _count as count_tokens
from adr_eval.retrieval.chunker import _leaves as split_spans
from adr_store.records import Element, SourceRecord
from adr_store.store import Store
from adr_store.structure.text import collapse, trim

BREADCRUMB_SEP = " > "
BREADCRUMB_PART_CHARS = 80
_SEPARATORS = list(CHUNKER_CONFIG["separators"])


@dataclass(frozen=True)
class StoreChunk(Chunk):
    """A baseline `Chunk` plus where it sits: its breadcrumb and the leaves it covers."""

    breadcrumb: str
    element_ids: list[str]


def chunker_config(max_tokens: int = 400, min_tokens: int = 40) -> dict:
    """Every setting that shapes the chunks, for index fingerprints."""
    return {"kind": "structure", "max_tokens": max_tokens, "min_tokens": min_tokens,
            "separators": _SEPARATORS, "overlap": 0, "breadcrumb_sep": BREADCRUMB_SEP,
            "breadcrumb_part_chars": BREADCRUMB_PART_CHARS}


def document_title(source: SourceRecord, elements: list[Element], text: str) -> str:
    """The first top-level section's title when it comes from markup; otherwise a JSON
    record's own `title`; otherwise the file name of the URI's path.

    Heuristic sections (PDF, confidence below 1.0) are passed over: the first one is a heading
    such as "Abstract", not the document's title.
    """
    for e in sorted(elements, key=lambda e: e.order):
        if e.type == "section" and e.parent_id is None and e.confidence == 1.0 and e.title:
            return collapse(e.title)
    if source.format == "json":
        try:
            record = json.loads(text)
        except ValueError:
            record = None
        if isinstance(record, dict) and isinstance(record.get("title"), str):
            title = collapse(record["title"])
            if title:
                return title
    name = unquote(urlsplit(source.uri).path.rstrip("/").rsplit("/", 1)[-1])
    return collapse(name) or source.uri or source.doc_id


def breadcrumb(title: str, section_path: list[str]) -> str:
    """`title > section > subsection`, the title not repeated when the path starts with it;
    each part whitespace-collapsed and cut to `BREADCRUMB_PART_CHARS` characters."""
    parts = [collapse(p) for p in section_path]
    if not parts or parts[0] != title:
        parts.insert(0, title)
    return BREADCRUMB_SEP.join(p[:BREADCRUMB_PART_CHARS].rstrip() for p in parts)


@dataclass
class _Run:
    """Consecutive leaves with the same parent section (None: before the first heading)."""

    section_id: str | None
    leaves: list[Element]
    tokens: int


def _runs(leaves: list[Element], counts: dict[str, int]) -> list[_Run]:
    runs: list[_Run] = []
    for leaf in leaves:
        if runs and runs[-1].section_id == leaf.parent_id:
            runs[-1].leaves.append(leaf)
            runs[-1].tokens += counts[leaf.element_id]
        else:
            runs.append(_Run(leaf.parent_id, [leaf], counts[leaf.element_id]))
    return runs


def _pack(text: str, leaves: list[Element], counts: dict[str, int],
          max_tokens: int) -> list[tuple[int, int]]:
    """Greedy packing of leaves (an over-long leaf as the baseline's pieces) into ranges."""
    units: list[tuple[int, int, int]] = []
    for leaf in leaves:
        n = counts[leaf.element_id]
        if n <= max_tokens:
            units.append((leaf.char_start, leaf.char_end, n))
        else:
            units += split_spans(text, leaf.char_start, leaf.char_end, _SEPARATORS, max_tokens)
    spans: list[tuple[int, int]] = []
    cur_s = cur_e = cur_n = -1
    for s, e, n in units:
        if cur_n >= 0 and cur_n + n <= max_tokens:
            cur_e, cur_n = e, cur_n + n
            continue
        if cur_n >= 0:
            spans.append((cur_s, cur_e))
        cur_s, cur_e, cur_n = s, e, n
    if cur_n >= 0:
        spans.append((cur_s, cur_e))
    return [span for s, e in spans if (span := trim(text, s, e))]


def chunk_elements(source: SourceRecord, elements: list[Element], text: str,
                   max_tokens: int = 400, min_tokens: int = 40) -> list[StoreChunk]:
    """The chunks of one document, in text order."""
    leaves = sorted((e for e in elements if e.is_leaf), key=lambda e: e.char_start)
    counts = {e.element_id: count_tokens(text[e.char_start:e.char_end]) for e in leaves}
    title = document_title(source, elements, text)
    chunks = []
    for run in _runs(leaves, counts):
        for s, e in _pack(text, run.leaves, counts, max_tokens):
            covered = [x for x in run.leaves if x.char_start < e and s < x.char_end]
            chunks.append(StoreChunk(
                make_chunk_id(source.doc_id, s, e), source.doc_id, s, e, text[s:e],
                breadcrumb(title, covered[-1].section_path),
                [x.element_id for x in covered]))
    return chunks


def chunk_store(store: Store, max_tokens: int = 400, min_tokens: int = 40) -> list[StoreChunk]:
    """Every chunk of the store's snapshot, documents in `doc_id` order, sorted by `chunk_id`
    as the baseline index sorts its chunks."""
    chunks: list[StoreChunk] = []
    for doc_id in store.doc_ids():
        chunks += chunk_elements(store.source(doc_id), store.elements(doc_id),
                                 store.text(doc_id), max_tokens, min_tokens)
    chunks.sort(key=lambda c: c.chunk_id)
    return chunks
