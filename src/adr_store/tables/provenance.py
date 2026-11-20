"""Value provenance (Phase 3 spec §5.3): where every stored value came from, how far it was
checked, and why a null is null.

A `RowRecord` is one table row, `row` (column -> value), with `prov` (column -> `ValueProv`,
or a list of them, one per element, for a list column). A `ValueProv` names the document, the
character span of the value in the document's canonical text (when it has one), the extraction
`spec_id` (`fr.publication_date@1`) and a status. A null value has a null reason instead of a
verified span; a value no span can locate (the Phase 2 envelope status) carries its `spec_id`
with `start` and `end` null.

`reslice` is the T3 check of one span: it cuts the span out of the document's canonical text,
applies the column's derivation (`RESLICERS`) and compares the result with the stored value. An
FR span is the JSON-encoded value (`json_spans` locates it in the text the store keeps, the
document re-serialised with sorted keys and indent 2); a manifest span is the row's CSV lines.

`sort_key` is SQLite's total order, so rows stored in Python order sort the same in SQL: NULL <
numbers (a bool as 0 or 1) < text (code-point order, which is UTF-8 byte order); a list column
compares by its stored canonical JSON text.
"""

from __future__ import annotations

import bisect
import csv
import functools
import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from adr_eval.corpora.research import _csv_rows_with_spans, _row_id
from adr_store.tables.parse import author_key, author_tokens, header_line, scan_dockets

if TYPE_CHECKING:
    from adr_store.tables.contracts import Contract

Status = Literal["verified", "auto-accepted", "rejected", "review-pending"]
NullReason = Literal["absent", "not_applicable", "unparseable", "ungrounded", "model_error"]
SPEC_ID = r"^[a-z_]+\.[a-z_]+@\d+$"


class ValueProv(BaseModel):
    """The provenance of one stored value (or one element of a list value)."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="ValueProv")

    doc_id: str = Field(min_length=1)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    spec_id: str = Field(pattern=SPEC_ID)
    status: Status | None
    null_reason: NullReason | None = None
    quote: str | None = None  # extraction values: the exact re-sliced text
    checks_failed: list[str] = []
    regex_agrees: bool | None = None

    @model_validator(mode="after")
    def _consistent(self) -> ValueProv:
        if (self.start is None) != (self.end is None):
            raise ValueError("start and end are both set or both null")
        if self.start is not None and self.end < self.start:
            raise ValueError(f"end {self.end} < start {self.start}")
        if self.quote is not None and self.start is None:
            raise ValueError("a quote needs the span it was re-sliced from")
        if self.null_reason is None and self.status in (None, "rejected"):
            raise ValueError(f"status {self.status!r} is a null and needs a null reason")
        if self.null_reason is not None and self.status not in (None, "rejected"):
            raise ValueError(f"a null reason goes with no status or 'rejected', not "
                             f"{self.status!r}")
        if self.status == "verified" and self.checks_failed:
            raise ValueError("a verified value has no failed checks")
        return self

    @property
    def span(self) -> tuple[int, int] | None:
        return None if self.start is None else (self.start, self.end)


class RowRecord(BaseModel):
    """One table row with the provenance of each of its values."""

    model_config = ConfigDict(extra="forbid", title="RowRecord")

    doc_id: str
    row: dict[str, Any]
    prov: dict[str, ValueProv | list[ValueProv]]


def value_prov(doc_id: str, spec_id: str, span: tuple[int, int] | None = None, *,
               quote: str | None = None) -> ValueProv:
    """The provenance of a value found at `span` (none: a value no text span locates)."""
    start, end = (None, None) if span is None else span
    return ValueProv(doc_id=doc_id, start=start, end=end, spec_id=spec_id, status="verified",
                     quote=quote)


def null_prov(doc_id: str, spec_id: str, reason: NullReason, *,
              rejected: bool = False) -> ValueProv:
    """The provenance of a null: why it is null; `rejected` for a value that was found and
    refused (status "rejected")."""
    return ValueProv(doc_id=doc_id, spec_id=spec_id, null_reason=reason,
                     status="rejected" if rejected else None)


# -- spans in the canonical JSON text ----------------------------------------------------------

_DECODER = json.JSONDecoder()
_SPACE = " \t\n\r"


def json_spans(text: str) -> dict[tuple, tuple[int, int]]:
    """Path -> (start, end) of the encoded value in `text`, which is
    `json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False)`: the root is `()`, an
    object member `path + (key,)`, a list element `path + (index,)`. Every value, containers
    included, has a span, and `json.loads(text[start:end])` is the value."""
    out: dict[tuple, tuple[int, int]] = {}

    def skip(i: int) -> int:
        while text[i] in _SPACE:
            i += 1
        return i

    def value(i: int, path: tuple) -> int:
        i = skip(i)
        if text[i] in "{[":
            closing, keyed = ("}", True) if text[i] == "{" else ("]", False)
            j, n = skip(i + 1), 0
            if text[j] == closing:
                end = j + 1
            else:
                while True:
                    if keyed:
                        key, j = _DECODER.raw_decode(text, skip(j))
                        j = skip(j)
                        if text[j] != ":":
                            raise ValueError(f"expected ':' at {j}")
                        j += 1
                    else:
                        key, n = n, n + 1
                    j = skip(value(j, (*path, key)))
                    if text[j] == ",":
                        j += 1
                    elif text[j] == closing:
                        end = j + 1
                        break
                    else:
                        raise ValueError(f"expected ',' or {closing!r} at {j}")
        else:
            _, end = _DECODER.raw_decode(text, i)
        out[path] = (i, end)
        return end

    try:
        value(0, ())
    except IndexError as e:
        raise ValueError("truncated JSON text") from e
    return out


# -- re-slicing --------------------------------------------------------------------------------

def _loads(text: str, start: int, end: int) -> Any:
    return json.loads(text[start:end])


def _cfr_label(text: str, start: int, end: int) -> str:
    ref = _loads(text, start, end)
    return f"{ref['title']} CFR {ref['part']}"


def _int_of(key: str) -> Callable[[str, int, int], int]:
    def get(text: str, start: int, end: int) -> int:
        return int(_loads(text, start, end)[key])
    return get


def _year(text: str, start: int, end: int) -> int:
    return int(_loads(text, start, end)[:4])


def _string_before(text: str, end: int) -> str:
    """The decoded JSON string that holds position `end`, from its opening quote up to `end`."""
    i = end
    while i > 0:
        i -= 1
        if text[i] == '"':
            backslashes = 0
            while i - 1 - backslashes >= 0 and text[i - 1 - backslashes] == "\\":
                backslashes += 1
            if backslashes % 2 == 0:
                return json.loads('"' + text[i + 1:end] + '"')
    raise ValueError("no JSON string before the span")


def _string_part(text: str, start: int, end: int) -> str:
    """The text a span names inside a JSON string: the whole encoded string (with its quotes),
    or a fragment of one (the encoded characters between the quotes), decoded."""
    if text[start] == '"':
        return _loads(text, start, end)
    return json.loads('"' + text[start:end] + '"')


def _docket(text: str, start: int, end: int) -> str:
    """A docket: the span is its number inside one `docket_ids` string, and the docket is the
    last one found in the string read up to the end of the span (so letters given by an
    earlier part carry over)."""
    dockets, _ = scan_dockets(_string_before(text, end))
    docket, number, _ = dockets[-1]
    if number.text != json.loads('"' + text[start:end] + '"'):
        raise ValueError("the span is not the last docket number of its string")
    return docket


# Federal Register columns: the span is the JSON-encoded value (the identity), except where the
# stored value is derived from it.
RESLICERS: dict[str, Callable[[str, int, int], Any]] = {
    f"fr.{name}": _loads for name in (
        "id", "type", "agency", "publication_date", "title", "action", "effective_on",
        "agency_name", "fr_agency_id", "agency_parent_id", "docket_raw")
}
RESLICERS.update({
    "fr.other_ids": _string_part,   # a whole `docket_ids` string, or a part of one
    "fr.docket": _docket,
    "fr.year": _year,
    "fr.cfr_parts": _cfr_label,    # an element of `cfr_references`: "<title> CFR <part>"
    "fr.cfr_part": _cfr_label,
    "fr.cfr_title": _int_of("title"),
    "fr.cfr_part_number": _int_of("part"),
})

MANIFEST_COLUMNS = ("research", "topic", "also_in", "type", "title", "authors", "year", "venue",
                    "url", "pdf_url", "arxiv_id", "doi", "license", "status", "local_file",
                    "relevance")


def manifest_row(text: str, start: int, end: int) -> dict[str, str]:
    """The manifest row whose CSV lines are `text[start:end]`, read with the header line."""
    header = header_line(text)
    rows = list(csv.reader((header + "\n" + text[start:end]).splitlines(keepends=True)))
    if len(rows) != 2:
        raise ValueError("the span is not one CSV row")
    return dict(zip(rows[0], rows[1], strict=False))


@functools.lru_cache(maxsize=2)
def _record_spans(text: str) -> tuple[tuple[int, int], ...]:
    return tuple(span for _, span in _csv_rows_with_spans(text))


def _record_at(text: str, start: int, end: int) -> int:
    """The index of the manifest record that holds `text[start:end]`."""
    spans = _record_spans(text)
    i = bisect.bisect_right(spans, (start, len(text) + 1)) - 1
    if i < 0 or not spans[i][0] <= start <= end <= spans[i][1]:
        raise ValueError("the span is not inside one manifest record")
    return i


def _row_number(text: str, start: int, end: int) -> int:
    """The number of the manifest record `text[start:end]` (the header is not a record)."""
    i = _record_at(text, start, end)
    if _record_spans(text)[i] != (start, end):
        raise ValueError("the span is not one manifest record")
    return i + 1


def _author_at(text: str, start: int, end: int) -> tuple[int, str]:
    """(position, name as written) of the author whose characters are `text[start:end]`."""
    i = _record_at(text, start, end)
    found = author_tokens(text, *_record_spans(text)[i])
    if found is not None:
        for position, (name, s, e) in enumerate(found[0]):
            if (s, e) == (start, end):
                return position, name
    raise ValueError("the span is not an author of its record")


def _authors_et_al(text: str, start: int, end: int) -> bool:
    i = _record_at(text, start, end)
    found = author_tokens(text, *_record_spans(text)[i])
    if found is None or _record_spans(text)[i] != (start, end):
        raise ValueError("the span is not one manifest record")
    return found[1]


def _manifest_value(column: str) -> Callable[[str, int, int], Any]:
    def get(text: str, start: int, end: int) -> Any:
        return manifest_row(text, start, end)[column]
    return get


def _manifest_year(text: str, start: int, end: int) -> int | None:
    year = manifest_row(text, start, end)["year"]
    return int(year) if year.isdigit() else None


def _also_in_list(text: str, start: int, end: int) -> list[str]:
    return [t.strip() for t in manifest_row(text, start, end)["also_in"].split(";")
            if t.strip()]


def _paper_id(text: str, start: int, end: int) -> str:
    return _row_id(manifest_row(text, start, end))


RESLICERS.update({f"papers.{c}": _manifest_value(c) for c in MANIFEST_COLUMNS})
RESLICERS.update({"papers.year": _manifest_year, "papers.also_in_list": _also_in_list,
                  "papers.id": _paper_id, "papers.row": _row_number,
                  "papers.author_position": lambda t, s, e: _author_at(t, s, e)[0],
                  "papers.author_raw": lambda t, s, e: _author_at(t, s, e)[1],
                  "papers.author_key": lambda t, s, e: author_key(_author_at(t, s, e)[1]),
                  "papers.author_et_al": _authors_et_al})


def _same(a: Any, b: Any) -> bool:
    numbers = (int, float)
    if isinstance(a, numbers) and isinstance(b, numbers) \
            and not isinstance(a, bool) and not isinstance(b, bool):
        return a == b
    return type(a) is type(b) and a == b


def reslice(text: str, prov: ValueProv, value: Any) -> bool:
    """T3 for one span: does `text[start:end]`, through the column's derivation, give exactly
    `value` (an element of a list column when the derivation gives a list and `value` is no
    list), and, when the provenance holds a quote, is the quote that very slice? False for
    a span outside the text, a spec with no derivation, or provenance without a span."""
    if prov.span is None:
        return False
    start, end = prov.span
    if end > len(text):
        return False
    if prov.quote is not None and text[start:end] != prov.quote:
        return False
    derive = RESLICERS.get(prov.spec_id.split("@")[0])
    if derive is None:
        return False
    try:
        got = derive(text, start, end)
        if isinstance(got, list) and not isinstance(value, list):
            return any(_same(one, value) for one in got)   # one element of a list column
        return _same(got, value)
    except (ValueError, KeyError, TypeError, IndexError):
        return False


# -- SQLite's order ----------------------------------------------------------------------------

def _value_key(v: Any) -> tuple:
    if v is None:
        return (0,)
    if isinstance(v, (bool, int, float)):
        return (1, int(v) if isinstance(v, bool) else v)
    if isinstance(v, str):
        return (2, v)
    return (2, json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def sort_key(c: Contract, row: dict) -> tuple:
    """The sort key of `row` over the contract's `order` (SQLite's total order)."""
    return tuple(_value_key(row.get(name)) for name in c.order)
