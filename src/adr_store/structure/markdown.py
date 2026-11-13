"""Markdown: `#` headings give sections; paragraphs, list items, tables and fenced code are
leaves (spec §6). The canonical text is the file itself, so nothing needs aligning.

A deliberately small block reader, line by line: ATX headings (not setext), fences of three or
more backticks or tildes, pipe tables (lines starting with `|`), and list items (one leaf per
marker line, with its continuation lines). Anything else is a paragraph, ended by a blank line
or by the start of another block.
"""

from __future__ import annotations

import re

from adr_store.records import Element
from adr_store.structure.text import Block, Heading, Parsed, assemble, collapse, trim

_ATX = re.compile(r" {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*")
_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
_TABLE = re.compile(r"[ \t]*\|")
_LIST = re.compile(r"[ \t]*(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)")


def _lines(text: str):
    """(start, end, line) for every line, `end` before the newline."""
    pos = 0
    for line in text.split("\n"):
        yield pos, pos + len(line), line
        pos += len(line) + 1


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
    for start, end, line in _lines(text):
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
