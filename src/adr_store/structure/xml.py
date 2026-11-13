"""XML: the division hierarchy gives sections, every line of the canonical text is a paragraph.

An element with a direct heading child (`HEAD` in eCFR divisions such as PART, SUBPART,
SUBJGRP, SECTION and APPENDIX; `heading` in simpler documents) is a section; its rank is its
depth among such elements. Each heading's canonical lines are made by the harness's own
extractor, so they match the canonical text exactly, and are then aligned to it (spec §6).
"""

from __future__ import annotations

from lxml import etree

from adr_eval.corpora.extract import extract_text
from adr_store.records import Element
from adr_store.structure.text import (
    Block,
    Candidate,
    Parsed,
    align,
    assemble,
    blocks_between,
    collapse,
    line_spans,
)

HEADING_TAGS = frozenset({"HEAD", "heading"})


def _root(raw: bytes) -> etree._Element:
    """Parsed as the extractor parses it: no entity resolution, no network."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    return etree.fromstring(raw, parser)


def _heading_child(el: etree._Element) -> etree._Element | None:
    for child in el:
        if isinstance(child.tag, str) and child.tag in HEADING_TAGS:
            return child
    return None


def _candidate(head: etree._Element, rank: int) -> Candidate:
    text = extract_text(etree.tostring(head, with_tail=False), "xml")
    lines = tuple(collapse(line) for line in text.split("\n") if line.strip())
    return Candidate(lines, rank, " ".join(lines))


def candidates(raw: bytes) -> list[Candidate]:
    """Every section heading in document order, ranked by section depth."""
    out: list[Candidate] = []
    stack = [(_root(raw), 1)]
    while stack:
        el, depth = stack.pop()
        if not isinstance(el.tag, str):
            continue
        head = _heading_child(el)
        if head is not None:
            out.append(_candidate(head, depth))
            depth += 1
        stack.extend((child, depth) for child in reversed(el))
    return out


def _lines_as_paragraphs(text: str, start: int, end: int) -> list[Block]:
    return [Block("paragraph", a, b) for a, b in line_spans(text, start, end)]


def parse_with_stats(raw: bytes, text: str, doc_id: str) -> Parsed:
    found = candidates(raw) if text.strip() else []
    headings, dropped = align(text, found)
    blocks = blocks_between(text, headings, _lines_as_paragraphs)
    return Parsed(assemble(doc_id, text, headings, blocks), len(found), len(found) - dropped)


def parse(raw: bytes, text: str, doc_id: str) -> list[Element]:
    return parse_with_stats(raw, text, doc_id).elements
