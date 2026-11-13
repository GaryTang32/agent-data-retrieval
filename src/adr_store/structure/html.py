"""HTML: `h1` to `h6` give sections, aligned to the extractor's plain text (spec §6).

The canonical text is trafilatura's output, which drops boilerplate and sometimes headings, so
a heading that cannot be found is dropped and counted; where none aligns the document is
paragraphs only. Headings inside `nav`, `aside` or `footer`, and callout labels ending in a
colon ("Note:", "Example:"), are not section headings and are not candidates. A `<br>`
inside a heading is a line break, as it is in the extracted text.

Leaves follow the extracted text, one block per line: `- ` lines are list items, runs of
`|` lines are tables, other lines are paragraphs.
"""

from __future__ import annotations

from lxml import etree
from lxml import html as lxml_html

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

HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
NOT_CONTENT = frozenset({"nav", "aside", "footer"})


def _lines_of(el: etree._Element) -> tuple[str, ...]:
    """The element's text as collapsed lines, `<br>` breaking a line."""
    parts: list[str] = []

    def walk(node: etree._Element) -> None:
        if node.tag == "br":
            parts.append("\n")
        elif isinstance(node.tag, str) and node.text:
            parts.append(node.text)
        if isinstance(node.tag, str):
            for child in node:
                walk(child)
                if child.tail:
                    parts.append(child.tail)

    walk(el)
    return tuple(c for c in (collapse(line) for line in "".join(parts).split("\n")) if c)


def candidates(raw: bytes) -> list[Candidate]:
    """Section headings in document order, ranked by their tag number."""
    root = lxml_html.fromstring(raw, parser=lxml_html.HTMLParser(encoding="utf-8"))
    out = []
    for h in root.iter(*HEADING_TAGS):
        if any(a.tag in NOT_CONTENT for a in h.iterancestors()):
            continue
        lines = _lines_of(h)
        title = " ".join(lines)
        if not title or title.endswith(":"):
            continue
        out.append(Candidate(lines, int(h.tag[1]), title))
    return out


def _blocks(text: str, start: int, end: int) -> list[Block]:
    blocks: list[Block] = []
    for a, b in line_spans(text, start, end):
        line = text[a:b]
        if line.startswith("|") and blocks and blocks[-1].type == "table" \
                and text[blocks[-1].end:a].count("\n") == 1:
            blocks[-1] = Block("table", blocks[-1].start, b)
        elif line.startswith("|"):
            blocks.append(Block("table", a, b))
        elif line.startswith("- "):
            blocks.append(Block("list_item", a, b))
        else:
            blocks.append(Block("paragraph", a, b))
    return blocks


def parse_with_stats(raw: bytes, text: str, doc_id: str) -> Parsed:
    found = candidates(raw) if text.strip() else []
    headings, dropped = align(text, found)
    blocks = blocks_between(text, headings, _blocks)
    return Parsed(assemble(doc_id, text, headings, blocks), len(found), len(found) - dropped)


def parse(raw: bytes, text: str, doc_id: str) -> list[Element]:
    return parse_with_stats(raw, text, doc_id).elements
