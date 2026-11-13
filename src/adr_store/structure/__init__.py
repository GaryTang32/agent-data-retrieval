"""Structure parsers, one per format (spec §6), and the dispatcher by format.

Each format module has `parse(raw, text, doc_id) -> list[Element]` and
`parse_with_stats(raw, text, doc_id) -> Parsed`, which also counts the headings found in the
source and the ones aligned to the canonical text. A parser never changes the canonical text.
"""

from __future__ import annotations

from importlib import import_module

from adr_store.structure.text import Parsed

# Bump whenever parser output can change; recorded in every source record and snapshot.
PARSER_VERSION = "1"
PARSER = f"adr_store.structure/{PARSER_VERSION}"

_MODULES = {
    "md": "markdown",
    "txt": "text",
    "xml": "xml",
    "html": "html",
    "pdf": "pdf",
    "json": "records",
    "csv": "records",
}


def parse_document(fmt: str, raw: bytes, text: str, doc_id: str) -> Parsed:
    """Parse one document with the parser for its format."""
    if fmt not in _MODULES:
        raise ValueError(f"no structure parser for format {fmt!r}")
    module = import_module(f"adr_store.structure.{_MODULES[fmt]}")
    if fmt in ("json", "csv"):
        return module.parse_with_stats(raw, text, doc_id, fmt=fmt)
    return module.parse_with_stats(raw, text, doc_id)
