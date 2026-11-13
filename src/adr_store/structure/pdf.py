"""PDF text: heuristic sections, paragraphs, and the page each element starts on (spec §6).

The canonical text is pypdf's page texts joined by "\\n\\f\\n". There is no markup, so
headings are whole lines that look like one, kept conservative (rulings 7 and §6):

- a numbered heading, "3 Method" or "3.2. Dense Retrieval": at most two digits per part and
  four parts, a capitalised title of 3 to 80 characters with no comma, at most 12 words and
  no closing punctuation; its rank is the number of parts. Its number must follow the last
  accepted one (the next number at some depth, allowing one gap, or the first child), so
  affiliations, footnotes and table rows numbered out of sequence are not headings;
- a known unnumbered heading on a line of its own (Abstract, Introduction, ..., References,
  Appendix ...), once per document, rank 1.

Numbered lines before the first anchor (a known heading, or a numbered one whose title is a
known name such as "1 Introduction") are ignored: they are title-page affiliations.
Sections and heading lines get confidence 0.6. Paragraphs split at blank lines and always
at a form feed; each element's page is 1 + the number of form feeds before its start.
"""

from __future__ import annotations

import re

from adr_store.records import Element
from adr_store.structure.text import Heading, Parsed, assemble, blocks_between, paragraphs

HEURISTIC_CONFIDENCE = 0.6
MAX_TITLE_WORDS = 12

_NUMBERED = re.compile(r"(\d{1,2}(?:\.\d{1,2}){0,3})\.?[ \t]+([A-Z][^\n]{2,80})")
_KNOWN = re.compile(
    r"(?i:abstract|introduction|related work|background|methods?|experiments|results"
    r"|discussion|conclusions?|references|acknowledge?ments)")
_APPENDIX = re.compile(
    r"(?i:appendix|appendices)(?:[ \t]+[A-Z0-9]{1,2})?(?:[.:]?[ \t]+[A-Z][^\n]{1,60})?")


def _numbered(line: str) -> tuple[tuple[int, ...], str] | None:
    m = _NUMBERED.fullmatch(line)
    if m is None:
        return None
    title = m.group(2).strip()
    if title[-1] in ".,;:" or "," in title or len(title.split()) > MAX_TITLE_WORDS:
        return None
    return tuple(int(p) for p in m.group(1).split(".")), title


def _known(line: str) -> bool:
    return bool(_KNOWN.fullmatch(line) or _APPENDIX.fullmatch(line)) and line[-1] not in ".,;"


def _follows(prev: tuple[int, ...], num: tuple[int, ...]) -> bool:
    """Whether `num` can be the next numbered heading after `prev`."""
    if num == (*prev, 1):  # first child
        return True
    k = 0
    while k < min(len(prev), len(num)) and prev[k] == num[k]:
        k += 1
    if k >= len(num) or k >= len(prev):
        return False
    return num[k] in (prev[k] + 1, prev[k] + 2) and all(p == 1 for p in num[k + 1:])


def _lines(text: str):
    pos = 0
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped:
            start = pos + line.index(stripped[0])
            yield start, start + len(stripped), stripped
        pos += len(line) + 1


def find_headings(text: str) -> list[Heading]:
    """Heading lines of a PDF's text, in order."""
    found: list[tuple[int, int, int, str, tuple[int, ...] | None]] = []
    anchor = None
    for start, end, line in _lines(text):
        num = _numbered(line)
        if num:
            found.append((start, end, len(num[0]), line, num[0]))
        elif _known(line):
            found.append((start, end, 1, line, None))
        else:
            continue
        if anchor is None and (num is None or _known(num[1])):
            anchor = len(found) - 1
    return _filter(found[anchor or 0:])


def _filter(found) -> list[Heading]:
    out: list[Heading] = []
    prev: tuple[int, ...] = (0,)
    seen_known: set[str] = set()
    for start, end, rank, line, num in found:
        if num is None:
            key = " ".join(line.lower().split())
            if key in seen_known:
                continue
            seen_known.add(key)
        elif _follows(prev, num):
            prev = num
            seen_known.add(" ".join(line.split(maxsplit=1)[1].lower().split()))
        else:
            continue
        out.append(Heading(start, end, rank, " ".join(line.split())))
    return out


def _paragraphs(text: str, start: int, end: int):
    return paragraphs(text, start, end, page_breaks=True)


def parse_with_stats(raw: bytes, text: str, doc_id: str) -> Parsed:
    headings = find_headings(text)
    blocks = blocks_between(text, headings, _paragraphs)
    elements = assemble(doc_id, text, headings, blocks,
                        section_confidence=HEURISTIC_CONFIDENCE, pages=True)
    return Parsed(elements, len(headings), len(headings))


def parse(raw: bytes, text: str, doc_id: str) -> list[Element]:
    return parse_with_stats(raw, text, doc_id).elements
