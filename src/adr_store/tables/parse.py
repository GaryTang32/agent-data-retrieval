"""String parsing shared by the 3A loaders and the T3 re-slicers (Phase 3 spec §5.3, §5.4, §6):
the docket strings of a Federal Register document, the authors string of a manifest row, the
drawbridge titles, the base normalisation key, and the character offsets of the pieces in the
text they were read from. Pure functions of their
arguments; nothing here reads a store.

`scan_dockets` and `author_parts` return each piece with its offsets in the string, so a loader
can point a span at it; `csv_fields` does the same for the fields of one CSV record (a quoted
field's `""` is one decoded character with a two-character source range).
"""

from __future__ import annotations

import csv
import re
import string
import unicodedata
from dataclasses import dataclass

_DOCKET = re.compile(r"^(?:([A-Z]{2,3}) )?Docket (?:Nos?\.|Numbers?) ?\[?(.+)$")
_BARE_NUMBER = re.compile(r"^\d{2}-\d+$")
_AND = re.compile(r" and ")
_ET_AL = ("et al", "et al.")


@dataclass(frozen=True)
class Piece:
    """A piece of a string: its text and its [start, end) offsets in that string."""

    text: str
    start: int
    end: int


def _comma_parts(s: str) -> list[Piece]:
    """The non-empty, stripped parts of `s` split on commas, with their offsets."""
    out, pos = [], 0
    for chunk in s.split(","):
        lead = len(chunk) - len(chunk.lstrip())
        part = chunk.strip()
        if part:
            out.append(Piece(part, pos + lead, pos + lead + len(part)))
        pos += len(chunk) + 1
    return out


def scan_dockets(s: str) -> tuple[list[tuple[str, Piece, Piece]], list[Piece]]:
    """Dockets and other identifiers of one `docket_ids` string, with offsets in it.

    Returns ([(docket, number, part)], others): `number` is where the docket's number stands,
    `part` the comma part it came from, and `others` the parts that are no docket."""
    dockets: list[tuple[str, Piece, Piece]] = []
    others: list[Piece] = []
    prefix: str | None = None   # the letters of the docket part just before, if there was one
    for part in _comma_parts(s):
        if m := _DOCKET.match(part.text):
            prefix = m.group(1)
            rest = m.group(2)
            base = part.start + m.start(2)
            pos = 0
            for chunk in _AND.split(rest):
                lead = len(chunk) - len(chunk.lstrip())
                number = chunk.strip()
                if number:
                    at = base + pos + lead
                    dockets.append((f"{prefix} {number}" if prefix else number,
                                    Piece(number, at, at + len(number)), part))
                pos += len(chunk) + len(" and ")
        elif prefix is not None and _BARE_NUMBER.match(part.text):
            dockets.append((f"{prefix} {part.text}" if prefix else part.text, part, part))
        else:
            others.append(part)
            prefix = None
            continue
        if prefix is None:
            prefix = ""   # a docket part without letters: a bare number after it has none
    return dockets, others


def parse_dockets(docket_ids: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """([(docket, the comma part it was read from)], other identifiers as written) over the
    strings of a document's `docket_ids`. A part like "MB Docket Nos. 17-105 and 14-127"
    gives "MB 17-105" and "MB 14-127", a following bare number keeps the letters, and every
    other part is an other identifier."""
    found: list[tuple[str, str]] = []
    other: list[str] = []
    for s in docket_ids:
        dockets, others = scan_dockets(s)
        found.extend((d, part.text) for d, _, part in dockets)
        other.extend(p.text for p in others)
    return found, other


def author_parts(authors: str) -> tuple[list[Piece], bool]:
    """(the authors, with offsets in the string; whether the list ends "et al")."""
    names: list[Piece] = []
    et_al = False
    for part in _comma_parts(authors):
        if part.text.casefold() in _ET_AL:
            et_al = True
        else:
            names.append(part)
    return names, et_al


def split_authors(authors: str) -> tuple[list[str], bool]:
    """(the authors split on commas and stripped, empty parts dropped; whether "et al" or
    "et al." (any case) was one of the parts, which is then no author)."""
    names, et_al = author_parts(authors)
    return [n.text for n in names], et_al


def base_key(raw: str) -> str:
    """The base normalisation key (§6): Unicode NFKC, case-folded, whitespace collapsed to
    single spaces, surrounding punctuation and spaces stripped."""
    s = " ".join(unicodedata.normalize("NFKC", raw).casefold().split())
    return s.strip(string.punctuation + " ")


def author_key(raw: str) -> str:
    """The normalised name key of an author as written: the base key. The one definition of the
    authors key: the loader and the re-slicer both call it."""
    return base_key(raw)


def waterway_key(raw: str) -> str:
    """The key of a waterway as written: the base key without a leading "the "."""
    return re.sub(r"^the\s+", "", base_key(raw))


# -- drawbridge titles ---------------------------------------------------------------------------

STATES: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
    "PR": "Puerto Rico", "VI": "Virgin Islands", "GU": "Guam", "AS": "American Samoa",
    "MP": "Northern Mariana Islands",
}
_DRAWBRIDGE_TITLE = re.compile(r"^Drawbridge Operation Regulations?(?:\s*[;:]\s*|\s*$)")


def drawbridge_title(title: str) -> tuple[list[Piece], Piece | None] | None:
    """The comma parts of a drawbridge title with their offsets in it, and the state code that
    ends it (a part of two capital letters that is a USPS code, not among the parts), or None
    when the title is no drawbridge title: it starts "Drawbridge Operation Regulation" or
    "Regulations" and goes on with `;` or `:` (or ends). Empty parts are dropped."""
    m = _DRAWBRIDGE_TITLE.match(title)
    if m is None:
        return None
    parts = [Piece(p.text, p.start + m.end(), p.end + m.end())
             for p in _comma_parts(title[m.end():])]
    state = None
    if parts and parts[-1].text in STATES:
        state = parts.pop()
    return parts, state


# -- CSV fields with their offsets -------------------------------------------------------------

@dataclass(frozen=True)
class CsvField:
    """One field of a CSV record: its decoded `value`, and for each decoded character its
    [start, stop) offsets in the record's text."""

    value: str
    starts: tuple[int, ...]
    stops: tuple[int, ...]

    def span(self, i: int, j: int) -> tuple[int, int]:
        """Offsets in the record's text of the decoded characters [i, j) (j > i)."""
        return self.starts[i], self.stops[j - 1]


def _field_bounds(record: str) -> list[tuple[int, int]]:
    """The [begin, end) of each field's source text in one CSV record (a quote opens a quoted
    field only at its start, `""` inside one is a quote, characters after the closing quote
    belong to the field)."""
    out: list[tuple[int, int]] = []
    i, n = 0, len(record)
    while True:
        begin = i
        if i < n and record[i] == '"':
            j = i + 1
            while True:
                q = record.find('"', j)
                if q < 0:
                    j = n
                    break
                if q + 1 < n and record[q + 1] == '"':
                    j = q + 2
                    continue
                j = q + 1
                break
            i = j
        comma = record.find(",", i)
        i = n if comma < 0 else comma
        out.append((begin, i))
        if i >= n:
            return out
        i += 1


def _decode(record: str, begin: int, end: int, base: int) -> CsvField:
    chars: list[str] = []
    starts: list[int] = []
    stops: list[int] = []
    i = begin
    if i < end and record[i] == '"':
        i += 1
        while i < end:
            if record[i] == '"':
                if i + 1 < end and record[i + 1] == '"':
                    chars.append('"')
                    starts.append(base + i)
                    stops.append(base + i + 2)
                    i += 2
                    continue
                i += 1
                break
            chars.append(record[i])
            starts.append(base + i)
            stops.append(base + i + 1)
            i += 1
    for j in range(i, end):
        chars.append(record[j])
        starts.append(base + j)
        stops.append(base + j + 1)
    return CsvField("".join(chars), tuple(starts), tuple(stops))


def csv_fields(record: str, base: int = 0) -> list[CsvField]:
    """The fields of one CSV record (no terminator), decoded as the csv module decodes them,
    with offsets shifted by `base`."""
    return [_decode(record, b, e, base) for b, e in _field_bounds(record)]


def header_line(text: str) -> str:
    """The first line of a manifest CSV text, without its terminator. (Slices up to the first
    newline: `str.partition` would copy the rest of the manifest on every call.)"""
    i = text.find("\n")
    return (text if i < 0 else text[:i]).rstrip("\r")


def manifest_header(text: str) -> list[str]:
    """The column names of a manifest CSV text."""
    return next(csv.reader([header_line(text)]))


def manifest_field(text: str, start: int, end: int, column: str) -> CsvField | None:
    """The field `column` of the manifest record `text[start:end]`, with offsets in `text`;
    None when the record has no such field or its decoding disagrees with the csv module."""
    header = manifest_header(text)
    if column not in header:
        return None
    record = text[start:end]
    bounds = _field_bounds(record)
    k = header.index(column)
    if k >= len(bounds):
        return None
    field = _decode(record, *bounds[k], start)
    values = next(csv.reader(record.splitlines(keepends=True)), [])
    return field if k < len(values) and field.value == values[k] else None


def author_tokens(text: str, start: int, end: int) -> tuple[list[tuple[str, int, int]], bool
                                                              ] | None:
    """([(author, start, end)] with offsets in `text`, et al) of the manifest record
    `text[start:end]`; None when its authors field cannot be located."""
    field = manifest_field(text, start, end, "authors")
    if field is None:
        return None
    names, et_al = author_parts(field.value)
    return [(n.text, *field.span(n.start, n.end)) for n in names], et_al
