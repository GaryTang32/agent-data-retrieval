"""Plain text, and the layer every structure parser ends with.

A parser finds headings and blocks, either directly in the canonical text (markdown, PDF) or
in the source's own markup and then aligned to the canonical text (XML, HTML). `assemble`
turns those into element records: sections run from their heading to the next heading of the
same or a higher rank, leaves are the heading lines and the blocks between them, and every
range is a range of the unchanged canonical text (spec §3, §6).
"""

from __future__ import annotations

import bisect
import re
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from adr_store.records import Element, element_id, sha256_text

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Heading:
    """A heading located in the canonical text; [start, end) is its `heading` leaf.

    `rank` is the source's own depth (h3 is 3, "###" is 3, "3.2" is 2): smaller is outer.
    """

    start: int
    end: int
    rank: int
    title: str


@dataclass(frozen=True)
class Block:
    """A leaf other than a heading: [start, end) of the canonical text, no outer whitespace."""

    type: str
    start: int
    end: int


@dataclass(frozen=True)
class Candidate:
    """A heading read from the source markup, to be aligned: its text as whitespace-collapsed
    lines of the canonical text, its rank and its title."""

    lines: tuple[str, ...]
    rank: int
    title: str


@dataclass(frozen=True)
class Parsed:
    """A parser's result: the elements and how many headings it found and could place."""

    elements: list[Element]
    headings_found: int = 0
    headings_aligned: int = 0


Splitter = Callable[[str, int, int], list[Block]]


def collapse(s: str) -> str:
    """Whitespace runs to one space, ends stripped: how headings are compared."""
    return " ".join(s.split())


def trim(text: str, start: int, end: int) -> tuple[int, int] | None:
    """[start, end) without leading and trailing whitespace; None if nothing is left."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def paragraphs(text: str, start: int, end: int, page_breaks: bool = False) -> list[Block]:
    """`paragraph` blocks of [start, end), split at blank lines (and at form feeds when
    `page_breaks`, for PDF text, where a page break always ends a paragraph)."""
    blocks = []
    pos = start
    for m in _WS.finditer(text, start, end):
        run = m.group()
        if run.count("\n") >= 2 or (page_breaks and "\f" in run):
            blocks += _block("paragraph", text, pos, m.start())
            pos = m.end()
    return blocks + _block("paragraph", text, pos, end)


def _block(type_: str, text: str, start: int, end: int) -> list[Block]:
    span = trim(text, start, end)
    return [Block(type_, *span)] if span else []


def line_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """The non-blank lines of [start, end), each without outer whitespace."""
    out = []
    pos = start
    while pos < end:
        nl = text.find("\n", pos, end)
        stop = end if nl < 0 else nl
        span = trim(text, pos, stop)
        if span:
            out.append(span)
        pos = stop + 1
    return out


def blocks_between(text: str, headings: Sequence[Heading], split: Splitter) -> list[Block]:
    """Apply `split` to the text before, between and after the heading lines."""
    blocks = []
    pos = 0
    for h in headings:
        blocks += split(text, pos, h.start)
        pos = h.end
    return blocks + split(text, pos, len(text))


class _Lines:
    """The canonical text's lines with their offsets, indexed by their collapsed content."""

    def __init__(self, text: str):
        self.starts: list[int] = []
        self.ends: list[int] = []
        self.keys: list[str] = []
        pos = 0
        for line in text.split("\n"):
            self.starts.append(pos)
            self.ends.append(pos + len(line))
            self.keys.append(collapse(line))
            pos += len(line) + 1
        self.where: dict[str, list[int]] = defaultdict(list)
        for i, key in enumerate(self.keys):
            if key:
                self.where[key].append(i)

    def find(self, lines: tuple[str, ...], first: int) -> int | None:
        """The first line index >= `first` where `lines` occur as consecutive whole lines."""
        hits = self.where.get(lines[0], [])
        for i in hits[bisect.bisect_left(hits, first):]:
            if tuple(self.keys[i:i + len(lines)]) == lines:
                return i
        return None


def align(text: str, candidates: Sequence[Candidate]) -> tuple[list[Heading], int]:
    """Place each candidate at the first whole-line match after the previous placed heading.

    Lines are compared after collapsing whitespace; the returned ranges are raw offsets.
    A candidate that is not found is dropped; returns (headings, number dropped).
    """
    index = _Lines(text)
    found: list[Heading] = []
    dropped = 0
    cursor = 0
    for c in candidates:
        i = index.find(c.lines, cursor) if c.lines and all(c.lines) else None
        if i is None:
            dropped += 1
            continue
        last = i + len(c.lines) - 1
        span = trim(text, index.starts[i], index.ends[last])
        if span is None:  # unreachable: a matched line has content
            dropped += 1
            continue
        found.append(Heading(span[0], span[1], c.rank, c.title))
        cursor = last + 1
    return found, dropped


@dataclass
class _Section:
    heading: Heading
    end: int  # trimmed end
    raw_end: int  # start of the next heading of the same or a higher rank, or the text's end
    element_id: str = ""
    path: tuple[str, ...] = ()
    level: int = 1


def _sections(text: str, headings: Sequence[Heading]) -> list[_Section]:
    raw_ends = [len(text)] * len(headings)
    open_: list[int] = []
    for j, h in enumerate(headings):
        while open_ and headings[open_[-1]].rank >= h.rank:
            raw_ends[open_.pop()] = h.start
        open_.append(j)
    out = []
    for h, raw_end in zip(headings, raw_ends, strict=True):
        end = raw_end
        while end > h.end and text[end - 1].isspace():
            end -= 1
        out.append(_Section(h, end, raw_end))
    return out


def assemble(doc_id: str, text: str, headings: Sequence[Heading], blocks: Sequence[Block], *,
             confidence: float = 1.0, section_confidence: float | None = None,
             pages: bool = False) -> list[Element]:
    """Element records for one document from its headings (in text order) and its blocks.

    Sections and heading leaves get `section_confidence` (default `confidence`); `pages` sets
    each element's page to 1 + the number of form feeds before its start.
    """
    sec_conf = confidence if section_confidence is None else section_confidence
    sections = _sections(text, headings)
    # (start, -end, kind, payload): containers before the leaves they start with
    items: list[tuple[int, int, int, object]] = [(s.heading.start, -s.end, 0, s)
                                                 for s in sections]
    items += [(h.start, -h.end, 1, Block("heading", h.start, h.end)) for h in headings]
    items += [(b.start, -b.end, 1, b) for b in blocks]
    items.sort(key=lambda it: it[:3])
    feeds = [m.start() for m in re.finditer("\f", text)] if pages else []
    stack: list[_Section] = []
    elements = []
    for order, (start, neg_end, kind, payload) in enumerate(items):
        while stack and stack[-1].raw_end <= start:
            stack.pop()
        parent = stack[-1] if stack else None
        path = (*parent.path, parent.heading.title) if parent else ()
        end = -neg_end
        if kind == 0:
            sec: _Section = payload  # type: ignore[assignment]
            sec.path, sec.level = path, len(path) + 1
            sec.element_id = element_id(doc_id, "section", start, end)
            stack.append(sec)
            type_, level, title, conf = "section", sec.level, sec.heading.title, sec_conf
        else:
            block: Block = payload  # type: ignore[assignment]
            type_, title = block.type, None
            level = parent.level if (parent and type_ == "heading") else None
            conf = sec_conf if type_ == "heading" else confidence
        elements.append(Element(
            element_id=element_id(doc_id, type_, start, end), doc_id=doc_id, type=type_,
            char_start=start, char_end=end, parent_id=parent.element_id if parent else None,
            order=order, level=level, title=title, section_path=list(path),
            page=1 + bisect.bisect_left(feeds, start) if pages else None,
            confidence=conf, text_sha256=sha256_text(text[start:end])))
    return elements


def parse_with_stats(raw: bytes, text: str, doc_id: str) -> Parsed:
    """Plain text: `paragraph` leaves split at blank lines, no sections."""
    return Parsed(assemble(doc_id, text, [], paragraphs(text, 0, len(text))))


def parse(raw: bytes, text: str, doc_id: str) -> list[Element]:
    return parse_with_stats(raw, text, doc_id).elements
