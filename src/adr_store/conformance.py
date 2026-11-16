"""Conformance rules 1 to 4 of spec §4.3, checked for every document before it is stored,
and the field rules of the element record (spec §4.2).

Rule 5 (determinism: parsing the same bytes twice gives identical records) is a test, since it
needs two parses rather than one set of records.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict

from adr_store.records import Element, SourceRecord, element_id, sha256_text

MAX_PROBLEMS_PER_RULE = 20  # enough to diagnose; a broken parser would otherwise flood


def _short(e: Element) -> str:
    return f"{e.type} {e.element_id[:12]} [{e.char_start},{e.char_end})"


def _lossless(elements: list[Element], text: str) -> list[str]:
    """Rule 1: leaves do not overlap and, with whitespace-only gaps, tile the text."""
    problems = []
    pos = 0
    leaves = sorted((e for e in elements if e.is_leaf), key=lambda e: (e.char_start, e.char_end))
    for e in leaves:
        if e.char_end > len(text):
            problems.append(f"rule 1: {_short(e)} ends past the text ({len(text)} chars)")
            continue
        if e.char_end == e.char_start:
            problems.append(f"rule 1: {_short(e)} is empty")
        if e.char_start < pos:
            problems.append(f"rule 1: {_short(e)} overlaps the previous leaf ending at {pos}")
        else:
            problems += _gap(text, pos, e.char_start)
        pos = max(pos, e.char_end)
    problems += _gap(text, pos, len(text))
    return problems


def _gap(text: str, start: int, end: int) -> list[str]:
    gap = text[start:end]
    if gap and not gap.isspace():
        return [f"rule 1: text not covered by any leaf at [{start},{end}): {gap[:60]!r}"]
    return []


def _reslice(source: SourceRecord, elements: list[Element], text: str) -> list[str]:
    """Rule 2: every element (and the source) hashes its own slice of the text."""
    problems = []
    if source.text_sha256 != sha256_text(text):
        problems.append("rule 2: source text_sha256 does not match the canonical text")
    if source.text_length != len(text):
        problems.append(f"rule 2: source text_length {source.text_length} != {len(text)}")
    for e in elements:
        if not 0 <= e.char_start <= e.char_end <= len(text):
            problems.append(f"rule 2: {_short(e)} range lies outside the text "
                            f"({len(text)} chars)")
        elif e.text_sha256 != sha256_text(text[e.char_start:e.char_end]):
            problems.append(f"rule 2: {_short(e)} text_sha256 does not match its slice")
    return problems


def _nesting(elements: list[Element]) -> list[str]:
    """Rule 3: parents exist and are sections that contain their children; siblings do not
    overlap; `section_path` is the titles of the ancestors; a section's level is its depth
    and a heading has the level of the section it heads."""
    problems = []
    by_id = {e.element_id: e for e in elements}
    children: dict[str | None, list[Element]] = defaultdict(list)
    for e in elements:
        parent = by_id.get(e.parent_id) if e.parent_id is not None else None
        if e.parent_id is not None and parent is None:
            problems.append(f"rule 3: {_short(e)} has a parent_id that does not exist")
            continue
        if parent is not None and parent.type != "section":
            problems.append(f"rule 3: {_short(e)} has a parent that is not a section")
        if parent is not None and not (parent.char_start <= e.char_start
                                       and e.char_end <= parent.char_end):
            problems.append(f"rule 3: {_short(e)} lies outside its parent {_short(parent)}")
        children[e.parent_id].append(e)
        path = _ancestor_titles(e, by_id)
        if path is None:
            problems.append(f"rule 3: {_short(e)} has a cycle in its parent chain")
        else:
            if e.section_path != path:
                problems.append(f"rule 3: {_short(e)} section_path {e.section_path} != {path}")
            problems += _levels(e, parent, len(path) + 1)
    for siblings in children.values():
        siblings.sort(key=lambda e: (e.char_start, e.char_end))
        for a, b in zip(siblings, siblings[1:], strict=False):
            if b.char_start < a.char_end:
                problems.append(f"rule 3: siblings {_short(a)} and {_short(b)} overlap")
    return problems


def _levels(e: Element, parent: Element | None, depth: int) -> list[str]:
    if e.type == "section" and e.level != depth:
        return [f"rule 3: {_short(e)} has level {e.level} at depth {depth}"]
    if e.type == "heading":
        if parent is None or parent.type != "section":
            return [f"rule 3: {_short(e)} is not inside a section"]
        if e.level != parent.level:
            return [f"rule 3: {_short(e)} has level {e.level}, its section level "
                    f"{parent.level}"]
    return []


def _fields(source: SourceRecord, elements: list[Element]) -> list[str]:
    """Spec §4.2: only sections and headings have a level, only sections a title (headings
    may carry one), and only PDF text has pages."""
    problems = []
    for e in elements:
        if e.type not in ("section", "heading") and (e.level is not None
                                                      or e.title is not None):
            problems.append(f"record: {_short(e)} is a leaf with a level or a title")
        if source.format != "pdf" and e.page is not None:
            problems.append(f"record: {_short(e)} has a page in a {source.format} source")
    return problems


def _ancestor_titles(e: Element, by_id: dict[str, Element]) -> list[str] | None:
    """Titles of the ancestors, outermost first; None on a cycle."""
    titles: list[str] = []
    seen = {e.element_id}
    p = by_id.get(e.parent_id) if e.parent_id else None
    while p is not None:
        if p.element_id in seen:
            return None
        seen.add(p.element_id)
        titles.append(p.title or "")
        p = by_id.get(p.parent_id) if p.parent_id else None
    return titles[::-1]


def _identity(source: SourceRecord, elements: list[Element], raw: bytes) -> list[str]:
    """Rule 4: ids follow the spec and are unique; `order` follows (char_start, -char_end)."""
    problems = []
    if source.doc_id != hashlib.sha256(raw).hexdigest():
        problems.append("rule 4: doc_id is not the SHA-256 of the stored bytes")
    if source.byte_length != len(raw):
        problems.append(f"rule 4: byte_length {source.byte_length} != {len(raw)}")
    seen: set[str] = set()
    for e in elements:
        if e.doc_id != source.doc_id:
            problems.append(f"rule 4: {_short(e)} belongs to another doc_id")
        if e.element_id != element_id(e.doc_id, e.type, e.char_start, e.char_end):
            problems.append(f"rule 4: {_short(e)} element_id does not follow spec 4.2")
        if e.element_id in seen:
            problems.append(f"rule 4: {_short(e)} element_id is not unique")
        seen.add(e.element_id)
    problems += _order(elements)
    return problems


def _order(elements: list[Element]) -> list[str]:
    orders = sorted(e.order for e in elements)
    if orders != list(range(len(elements))):
        return ["rule 4: order values are not 0..n-1 without repeats"]
    ranked = sorted(elements, key=lambda e: e.order)
    for a, b in zip(ranked, ranked[1:], strict=False):
        if (a.char_start, -a.char_end) > (b.char_start, -b.char_end):
            return [f"rule 4: order puts {_short(a)} before {_short(b)}"]
    return []


def _capped(problems: list[str]) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    out = []
    for p in problems:
        rule = p.split(":", 1)[0]
        counts[rule] += 1
        if counts[rule] <= MAX_PROBLEMS_PER_RULE:
            out.append(p)
    for rule, n in sorted(counts.items()):
        if n > MAX_PROBLEMS_PER_RULE:
            out.append(f"{rule}: {n - MAX_PROBLEMS_PER_RULE} more problem(s) not shown")
    return out


def check(source: SourceRecord, elements: list[Element], text: str, raw: bytes) -> list[str]:
    """Every violation of rules 1 to 4 for one document, each prefixed `rule N:`, and of the
    element fields, prefixed `record:`; [] if none."""
    problems = _lossless(elements, text)
    problems += _reslice(source, elements, text)
    problems += _nesting(elements)
    problems += _identity(source, elements, raw)
    problems += _fields(source, elements)
    return _capped(problems)
