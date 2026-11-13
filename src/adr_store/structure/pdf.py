"""PDF text: heuristic sections, paragraphs, and the page each element starts on (spec §6).

The canonical text is pypdf's page texts joined by "\\n\\f\\n". There is no markup, so
headings are whole lines that look like one, kept conservative (rulings 7 and §6):

- a numbered heading, "3 Method" or "3.2. Dense Retrieval": at most two digits per part and
  four parts, a capitalised title of 3 to 80 characters with no comma, at most 12 words, at
  most one number among them, and no closing punctuation or hyphen; its rank is the number
  of parts. Its number must follow the last accepted one (the next number at some depth,
  allowing one gap, or the first child), so affiliations, footnotes and table rows numbered
  out of sequence are not headings. Top-level numbers keep the style of the first one ("2"
  or "2."), which tells sections from numbered list items; none are taken after References;
- a known unnumbered heading on a line of its own (Abstract, Introduction, ..., References,
  Appendix ...), once per document, rank 1.

Numbered lines before the first anchor (a known heading, or a numbered one whose title is a
known name such as "1 Introduction") are ignored: they are title-page affiliations.
Sections and heading lines get confidence 0.6. Paragraphs split at blank lines and always
at a form feed; each element's page is 1 + the number of form feeds before its start.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from adr_store.records import Element
from adr_store.structure.text import Heading, Parsed, assemble, blocks_between, paragraphs

HEURISTIC_CONFIDENCE = 0.6
MAX_TITLE_WORDS = 12

_NUMBERED = re.compile(r"(\d{1,2}(?:\.\d{1,2}){0,3})(\.?)[ \t]+([A-Z][^\n]{2,80})")
_NUMBER = re.compile(r"[\d.,%]*\d[\d.,%]*")
_KNOWN = re.compile(
    r"(?i:abstract|introduction|related work|background|methods?|experiments|results"
    r"|discussion|conclusions?|references|acknowledge?ments)")
_APPENDIX = re.compile(
    r"(?i:appendix|appendices)(?:[ \t]+[A-Z0-9]{1,2})?(?:[.:]?[ \t]+[A-Z][^\n]{1,60})?")


@dataclass(frozen=True)
class _Line:
    """A line that may be a heading: its number (None for a known unnumbered heading) and
    whether a single-part number is written with a dot ("3." rather than "3")."""

    start: int
    end: int
    text: str
    number: tuple[int, ...] | None = None
    title: str = ""
    dotted: bool = False


def _numbered(start: int, end: int, line: str) -> _Line | None:
    m = _NUMBERED.fullmatch(line)
    if m is None:
        return None
    title = m.group(3).strip()
    words = title.split()
    if (title[-1] in ".,;:-/" or "," in title or len(words) > MAX_TITLE_WORDS
            or sum(1 for w in words if _NUMBER.fullmatch(w)) >= 2):
        return None
    number = tuple(int(p) for p in m.group(1).split("."))
    return _Line(start, end, line, number, title, bool(m.group(2)))


def _known(line: str) -> bool:
    return bool(_KNOWN.fullmatch(line) or _APPENDIX.fullmatch(line)) and line[-1] not in ".,;"


def _key(s: str) -> str:
    return " ".join(s.lower().split())


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
    found: list[_Line] = []
    anchor = None
    for start, end, line in _lines(text):
        cand = _numbered(start, end, line) or (_Line(start, end, line) if _known(line) else None)
        if cand is None:
            continue
        found.append(cand)
        if anchor is None and (cand.number is None or _known(cand.title)):
            anchor = len(found) - 1
    return [Heading(c.start, c.end, len(c.number or (1,)), " ".join(c.text.split()))
            for c in _filter(found[anchor or 0:])]


def _filter(found: list[_Line]) -> list[_Line]:
    """Keep known headings once each, and numbered ones that continue the numbering in the
    document's own style (top-level numbers with or without a dot), until the references."""
    out: list[_Line] = []
    prev: tuple[int, ...] = (0,)
    top_dotted: bool | None = None
    seen: set[str] = set()
    for c in found:
        if c.number is None:
            if _key(c.text) in seen:
                continue
            seen.add(_key(c.text))
        else:
            single = len(c.number) == 1
            if "references" in seen or not _follows(prev, c.number):
                continue  # after the references, numbered lines are list entries
            if single and top_dotted is not None and c.dotted != top_dotted:
                continue  # "2. Do this" inside a paper whose sections read "2 Method"
            if single:
                top_dotted = c.dotted
            prev = c.number
            seen.add(_key(c.title))
        out.append(c)
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
