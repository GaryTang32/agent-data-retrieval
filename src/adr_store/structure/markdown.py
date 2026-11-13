"""Markdown: headings give sections; paragraphs, list items, tables and fenced code are
leaves (spec §6). The canonical text is the file itself, so nothing needs aligning.

A deliberately small block reader, line by line: ATX headings (`## Title`), setext headings,
fences of three or more backticks or tildes, pipe tables (lines starting with `|`), and list
items (one leaf per marker line, with its continuation lines). Anything else is a paragraph,
ended by a blank line or by the start of another block.

A setext heading, CommonMark style, is a line of text underlined by a line of `=` (level 1)
or of at least three `-` (level 2), each indented at most three spaces. The text line follows
a blank line or starts the document, and is not a list item, table row, ATX heading or fence;
the heading leaf covers both lines. A paragraph of several lines is never a setext heading.
A `-` underline is a thematic break instead when the text line is a block quote (`> ...`, as
in CommonMark), ends in ":" (an intro to unfenced YAML) or has more than 12 words (a
paragraph); real setext headings in the bench corpus have 1 to 12 words.
"""

from __future__ import annotations

import re

from adr_store.records import Element
from adr_store.structure.text import Block, Heading, Parsed, assemble, collapse, trim

_ATX = re.compile(r" {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*")
_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
_TABLE = re.compile(r"[ \t]*\|")
_LIST = re.compile(r"[ \t]*(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)")
_UNDERLINE = re.compile(r" {0,3}(=+|-{3,})[ \t]*")
_SETEXT_TEXT = re.compile(r" {0,3}\S.*")  # at most three spaces of indent, as for ATX
_QUOTE = re.compile(r" {0,3}>")
MAX_DASH_SETEXT_WORDS = 12


def _lines(text: str) -> list[tuple[int, int, str]]:
    """(start, end, line) for every line, `end` before the newline."""
    out = []
    pos = 0
    for line in text.split("\n"):
        out.append((pos, pos + len(line), line))
        pos += len(line) + 1
    return out


def _setext(lines: list[tuple[int, int, str]], i: int) -> int | None:
    """The level of a setext heading whose text is line i, or None."""
    line = lines[i][2].rstrip()
    if (i + 1 >= len(lines) or (i > 0 and lines[i - 1][2].strip())
            or not _SETEXT_TEXT.fullmatch(line) or _UNDERLINE.fullmatch(line)
            or _LIST.match(line) or _TABLE.match(line) or _FENCE.match(line)
            or _heading(line)):
        return None
    m = _UNDERLINE.fullmatch(lines[i + 1][2].rstrip())
    if m is None:
        return None
    if m.group(1)[0] == "=":
        return 1
    if (_QUOTE.match(line) or line.endswith(":")
            or len(line.split()) > MAX_DASH_SETEXT_WORDS):
        return None  # a thematic break, not a heading
    return 2


def _heading(line: str) -> tuple[int, str] | None:
    m = _ATX.fullmatch(line.rstrip())
    if m is None or not (m.group(2) or "").strip():
        return None
    return len(m.group(1)), collapse(m.group(2))


class _Reader:
    """Collects blocks; `open` is the block being extended: [type, start, end]."""

    def __init__(self, text: str):
        self.text = text
        self.blocks: list[Block] = []
        self.open: list | None = None

    def flush(self) -> None:
        if self.open:
            span = trim(self.text, self.open[1], self.open[2])
            if span:
                self.blocks.append(Block(self.open[0], *span))
        self.open = None

    def start(self, type_: str, start: int, end: int) -> None:
        self.flush()
        self.open = [type_, start, end]

    def extend(self, end: int) -> None:
        self.open[2] = end


def _read(text: str) -> tuple[list[Heading], list[Block]]:
    headings: list[Heading] = []
    r = _Reader(text)
    fence: tuple[str, int] | None = None  # (marker run, start offset of the fence)
    lines = _lines(text)
    skip = -1  # the underline of a setext heading, already part of its heading leaf
    for i, (start, end, line) in enumerate(lines):
        if i == skip:
            continue
        if fence is not None:
            marker, fence_start = fence
            closing = re.fullmatch(rf" {{0,3}}{marker[0]}{{{len(marker)},}}[ \t]*", line.rstrip())
            if closing:
                r.blocks += [Block("code", *trim(text, fence_start, end))]
                fence = None
            continue
        if not line.strip():
            r.flush()
        elif m := _FENCE.match(line):
            r.flush()
            fence = (m.group(1), start)
        elif h := _heading(line):
            r.flush()
            headings.append(Heading(*trim(text, start, end), h[0], h[1]))
        elif level := _setext(lines, i):
            r.flush()
            headings.append(Heading(*trim(text, start, lines[i + 1][1]), level, collapse(line)))
            skip = i + 1
        elif _TABLE.match(line):
            if r.open and r.open[0] == "table":
                r.extend(end)
            else:
                r.start("table", start, end)
        elif _LIST.match(line):
            r.start("list_item", start, end)
        elif r.open and r.open[0] in ("paragraph", "list_item"):
            r.extend(end)
        else:
            r.start("paragraph", start, end)
    if fence is not None:  # an unclosed fence runs to the end of the document
        r.blocks += [Block("code", *trim(text, fence[1], len(text)))]
    r.flush()
    return headings, r.blocks


def parse_with_stats(raw: bytes, text: str, doc_id: str) -> Parsed:
    headings, blocks = _read(text)
    return Parsed(assemble(doc_id, text, headings, blocks), len(headings), len(headings))


def parse(raw: bytes, text: str, doc_id: str) -> list[Element]:
    return parse_with_stats(raw, text, doc_id).elements
