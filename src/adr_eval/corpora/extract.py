"""Deterministic text extraction. Evidence offsets index into this output."""

from __future__ import annotations

import io
import json

from lxml import etree

# Bump whenever extraction output can change; part of the index fingerprint.
EXTRACTOR_VERSION = "2"

# Inline markup (eCFR emphasis, superscripts, fractions, footnote refs; HTML-style emphasis)
# sits inside a sentence or even a word, so it must not start a new line.
INLINE_TAGS = frozenset(
    {"E", "I", "B", "SU", "FR", "FTREF", "sup", "sub", "strong", "em", "b", "i"}
)


def _xml_text(data: bytes) -> str:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    root = etree.fromstring(data, parser)
    parts: list[str] = []

    def walk(el: etree._Element) -> None:
        if not isinstance(el.tag, str):  # comment or processing instruction
            return
        block = el.tag not in INLINE_TAGS
        if block:
            parts.append("\n")
        if el.text:
            parts.append(el.text)
        for child in el:
            walk(child)
            if child.tail:
                parts.append(child.tail)
        if block:
            parts.append("\n")

    walk(root)
    lines = (" ".join(line.split()) for line in "".join(parts).split("\n"))
    return "\n".join(line for line in lines if line)


def _html_text(data: bytes) -> str:
    import trafilatura

    return (
        trafilatura.extract(
            data.decode("utf-8"),
            output_format="txt",
            include_comments=False,
            favor_precision=True,
        )
        or ""
    )


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n\f\n".join(page.extract_text() or "" for page in reader.pages)


def extract_text(data: bytes, fmt: str) -> str:
    if fmt in ("md", "txt", "csv"):
        return data.decode("utf-8", errors="strict")
    if fmt == "html":
        return _html_text(data)
    if fmt == "pdf":
        return _pdf_text(data)
    if fmt == "xml":
        return _xml_text(data)
    if fmt == "json":
        return json.dumps(json.loads(data), sort_keys=True, indent=2, ensure_ascii=False)
    raise ValueError(f"unsupported format: {fmt}")
