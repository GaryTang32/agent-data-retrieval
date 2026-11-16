"""Record-shaped formats: a JSON document is one `record`; a CSV row is one `record`.

No sections. The CSV header row is a record of its own. A quoted field may hold line breaks,
so rows are found by quote parity rather than by line.
"""

from __future__ import annotations

from adr_store.records import Element
from adr_store.structure.text import Block, Parsed, assemble, trim


def json_records(text: str) -> list[Block]:
    """The whole document (the canonical, re-serialised JSON) as one record."""
    span = trim(text, 0, len(text))
    return [Block("record", *span)] if span else []


def csv_records(text: str) -> list[Block]:
    """One record per CSV row, a row ending at a line break outside double quotes."""
    blocks = []
    row_start = pos = 0
    in_quotes = False
    while pos < len(text):
        nl = text.find("\n", pos)
        stop = len(text) if nl < 0 else nl + 1
        if text.count('"', pos, stop) % 2:
            in_quotes = not in_quotes
        pos = stop
        if not in_quotes or pos == len(text):
            span = trim(text, row_start, pos)
            if span:
                blocks.append(Block("record", *span))
            row_start = pos
    return blocks


def parse_with_stats(raw: bytes, text: str, doc_id: str, fmt: str = "json") -> Parsed:
    blocks = csv_records(text) if fmt == "csv" else json_records(text)
    return Parsed(assemble(doc_id, text, [], blocks))


def parse(raw: bytes, text: str, doc_id: str, fmt: str = "json") -> list[Element]:
    return parse_with_stats(raw, text, doc_id, fmt).elements
