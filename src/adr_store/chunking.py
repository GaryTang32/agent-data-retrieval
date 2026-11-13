"""Structure-led chunks over one store snapshot, each with a breadcrumb (spec §7).

A chunk is a run of consecutive leaves of one section (the innermost section containing them,
or the region before a document's first heading). Leaves are packed in text order while the
chunk's token count, counted as the baseline chunker counts it, stays within `max_tokens`; a
leaf longer than that is cut with the baseline's recursive splitter and its pieces are packed
like leaves. A chunk's range runs from its first leaf (or piece) to its last, so it re-slices
the canonical text exactly; `chunk_id` is the baseline's. Deterministic, no model calls.

Short sections. A section whose own leaves total fewer than `min_tokens` is carried forward
into the first chunk of the section that follows it, when that one is its next sibling (same
parent; the region before the first heading counts as a top-level sibling) or its own first
subsection (a heading with no text of its own). The carried leaves are packed ahead of the
next section's leaves under the same `max_tokens` limit, and carrying continues while the
carried leaves still total fewer than `min_tokens`. A merged chunk therefore never leaves the
parent of the first short section, and its breadcrumb is that of its last leaf's section. A
group that reaches `min_tokens` on a heading-only section also takes that section's first
subsection, so the heading is not cut off from what it heads.

Headings. A chunk never ends on a heading leaf whose section goes on in the same group: the
heading (with any headings directly under it) moves to the next chunk together with the first
unit of its body. When the headings plus that unit exceed `max_tokens`, the unit is cut with the
baseline splitter at `max_tokens` minus the headings' tokens, so the headings travel with the
start of their body.

Breadcrumbs. Each part is cut at a word boundary to at most 80 characters, ending in "…" when
cut. When the title is the document's first top-level section, a chunk inside a different
top-level section has no title prefix: sibling top-level sections do not read as nested.
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
    element_ids: tuple[str, ...]


def chunker_config(max_tokens: int = 400, min_tokens: int = 40) -> dict:
    """Every setting that shapes the chunks, for index fingerprints."""
    return {"kind": "structure", "max_tokens": max_tokens, "min_tokens": min_tokens,
            "separators": _SEPARATORS, "overlap": 0, "breadcrumb_sep": BREADCRUMB_SEP,
            "breadcrumb_part_chars": BREADCRUMB_PART_CHARS}


def _title_section(elements: list[Element]) -> Element | None:
    """The first top-level section, when it comes from markup and has a title."""
    for e in sorted(elements, key=lambda e: e.order):
        if e.type == "section" and e.parent_id is None and e.confidence == 1.0 and e.title:
            return e
    return None


def document_title(source: SourceRecord, elements: list[Element], text: str) -> str:
    """The first top-level section's title when it comes from markup; otherwise a JSON
    record's own `title`; otherwise the file name of the URI's path.

    Heuristic sections (PDF, confidence below 1.0) are passed over: the first one is a heading
    such as "Abstract", not the document's title.
    """
    section = _title_section(elements)
    if section is not None:
        return collapse(section.title)
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


def _cut(part: str, limit: int = BREADCRUMB_PART_CHARS) -> str:
    """`part` itself when it has at most `limit` characters; otherwise its longest prefix
    ending at a word boundary, followed by "…", within `limit` (a hard cut when the first
    word alone is too long)."""
    if len(part) <= limit:
        return part
    cut = part.rfind(" ", 0, limit)
    head = part[:cut].rstrip() if cut > 0 else ""
    return (head or part[:limit - 1]) + "…"


def breadcrumb(title: str | None, section_path: list[str]) -> str:
    """`title > section > subsection`, the title not repeated when the path starts with it
    and left out when None; each part whitespace-collapsed and cut by `_cut`."""
    parts = [collapse(p) for p in section_path]
    if title is not None and (not parts or parts[0] != title):
        parts.insert(0, title)
    return BREADCRUMB_SEP.join(_cut(p) for p in parts)


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


def _carries_into(short: str | None, nxt: str | None, sections: dict[str, Element]) -> bool:
    """May a short run in section `short` merge into the run that follows, in `nxt`: its next
    sibling, or a section inside it?"""
    if nxt is None:  # the region before the first heading follows nothing
        return False
    parent = sections[short].parent_id if short is not None else None
    if sections[nxt].parent_id == parent:
        return True
    up = sections[nxt].parent_id
    while up is not None and short is not None:
        if up == short:
            return True
        up = sections[up].parent_id
    return False


def _inside(section_id: str | None, container: str | None,
            sections: dict[str, Element]) -> bool:
    """Is `section_id` the section `container` or one inside it?"""
    while section_id is not None:
        if section_id == container:
            return True
        section_id = sections[section_id].parent_id
    return False


def _groups(runs: list[_Run], sections: dict[str, Element], min_tokens: int) -> list[list[_Run]]:
    """Runs to be packed together: a short run joins the run after it, and a heading-only
    section takes its first subsection (see the module doc)."""
    groups: list[list[_Run]] = []
    total = 0
    for run in runs:
        prev = groups[-1][-1] if groups else None
        # a heading-only section that a carried group reached min_tokens on
        heading_only = (prev is not None and len(groups[-1]) > 1
                        and all(x.type == "heading" for x in prev.leaves))
        if prev is not None and (
                (total < min_tokens and _carries_into(prev.section_id, run.section_id, sections))
                or (heading_only and prev.section_id is not None
                    and run.section_id != prev.section_id
                    and _inside(run.section_id, prev.section_id, sections))):
            groups[-1].append(run)
            total += run.tokens
        else:
            groups.append([run])
            total = run.tokens
    return groups


_Unit = tuple[int, int, int, Element]  # (start, end, tokens, the leaf it comes from)


def _split(text: str, s: int, e: int, max_tokens: int, leaf: Element) -> list[_Unit]:
    return [(a, b, n, leaf) for a, b, n in split_spans(text, s, e, _SEPARATORS, max_tokens)]


def _pack(text: str, leaves: list[Element], counts: dict[str, int], max_tokens: int,
          sections: dict[str, Element]) -> list[tuple[int, int]]:
    """Greedy packing of leaves (an over-long leaf as the baseline's pieces) into ranges; a
    heading whose section goes on is packed as one block with what follows it (module doc)."""
    units: list[_Unit] = []
    for leaf in leaves:
        n = counts[leaf.element_id]
        if n <= max_tokens:
            units.append((leaf.char_start, leaf.char_end, n, leaf))
        else:
            units += _split(text, leaf.char_start, leaf.char_end, max_tokens, leaf)
    spans: list[tuple[int, int]] = []
    cur_s = cur_e = cur_n = -1
    i = 0
    while i < len(units):
        j = i  # extend over headings whose section continues with the next unit
        while (units[j][3].type == "heading" and j + 1 < len(units)
               and _inside(units[j + 1][3].parent_id, units[j][3].parent_id, sections)):
            j += 1
        heads = sum(u[2] for u in units[i:j])
        if j > i and heads + units[j][2] > max_tokens:
            if units[j][3].type == "heading" or heads >= max_tokens:
                j = i  # no room: this heading alone, and the chain is retried from the next
            else:  # cut the body unit so that its start fits with the headings
                s, e, _, leaf = units[j]
                first, *rest = _split(text, s, e, max_tokens - heads, leaf)
                tail = []
                if rest and text[first[1]:e].strip():
                    tail = _split(text, first[1], e, max_tokens, leaf)
                units[j:j + 1] = [first, *tail]
        block = units[i:j + 1]
        n = sum(u[2] for u in block)
        if cur_n >= 0 and cur_n + n <= max_tokens:
            cur_e, cur_n = block[-1][1], cur_n + n
        else:
            if cur_n >= 0:
                spans.append((cur_s, cur_e))
            cur_s, cur_e, cur_n = block[0][0], block[-1][1], n
        i = j + 1
    if cur_n >= 0:
        spans.append((cur_s, cur_e))
    return [span for s, e in spans if (span := trim(text, s, e))]


def chunk_elements(source: SourceRecord, elements: list[Element], text: str,
                   max_tokens: int = 400, min_tokens: int = 40) -> list[StoreChunk]:
    """The chunks of one document, in text order."""
    leaves = sorted((e for e in elements if e.is_leaf), key=lambda e: e.char_start)
    counts = {e.element_id: count_tokens(text[e.char_start:e.char_end]) for e in leaves}
    sections = {e.element_id: e for e in elements if e.type == "section"}
    title = document_title(source, elements, text)
    title_section = _title_section(elements)

    def crumb(leaf: Element) -> str:
        if (title_section is not None and leaf.parent_id is not None
                and not title_section.char_start <= leaf.char_start < title_section.char_end):
            return breadcrumb(None, leaf.section_path)  # another top-level section
        return breadcrumb(title, leaf.section_path)

    chunks = []
    for group in _groups(_runs(leaves, counts), sections, min_tokens):
        members = [leaf for run in group for leaf in run.leaves]
        for s, e in _pack(text, members, counts, max_tokens, sections):
            covered = [x for x in members if x.char_start < e and s < x.char_end]
            chunks.append(StoreChunk(
                make_chunk_id(source.doc_id, s, e), source.doc_id, s, e, text[s:e],
                crumb(covered[-1]), tuple(x.element_id for x in covered)))
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
