"""The 3A loaders (Phase 3 spec §5.4): the Federal Register and research-papers tables built from
the metadata the corpora already carry. No model is called. Each document is read through
`store.text(doc_id)`; every value's span is located in that text, so the T3 check re-slices all
of them (`provenance.reslice`).

Federal Register documents (`FR_PREFIX` URIs) give `fr_documents`, `fr_cfr_refs`, `fr_agencies`
and `fr_dockets`; their spans come from `json_spans` over the stored JSON text. The papers
manifest (`PAPERS_URI`) gives `papers` and `paper_authors`; its spans are CSV records (a
column's span is its row's) and, for an author, the author's characters inside the row.

A value the document does not carry is null with reason `absent`; one it carries in a form the
column cannot hold (a CFR part like "117a", a year like "n.d.") is null with reason
`unparseable`. Values that are computed rather than read (an agency's position, the specific
flag, the applicability status) have no span. The rows reproduce the v0.1 records
(`GovAdapter.records`, `ResearchAdapter.records`) field for field.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from adr_eval.corpora.gov import FR_API, specific_agency
from adr_eval.corpora.research import _csv_rows_with_spans, _row_id
from adr_store.applicability import Applicability
from adr_store.store import Store
from adr_store.tables.parse import (
    author_key,
    author_tokens,
    parse_dockets,
    scan_dockets,
    split_authors,
)
from adr_store.tables.provenance import (
    MANIFEST_COLUMNS,
    RowRecord,
    json_spans,
    null_prov,
    value_prov,
)

__all__ = ["FR_PREFIX", "PAPERS_URI", "fr_tables", "papers_tables", "parse_dockets",
           "split_authors", "records_view"]

FR_PREFIX = f"{FR_API}/documents/"
PAPERS_URI = "file://papers/manifest.csv"


def records_view(rows: list[RowRecord], columns: Iterable[str]) -> list[dict]:
    """`columns` of each row, in the rows' order: the shape of a v0.1 record."""
    names = list(columns)
    return [{c: r.row[c] for c in names} for r in rows]


def _number(v) -> int | None:
    """An integer from a JSON integer or a string of digits, else None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.isascii() and v.isdigit():
        return int(v)
    return None


# -- Federal Register ----------------------------------------------------------------------------

def _offset(s: str, start: int, i: int) -> int:
    """Where character `i` of the string `s` stands in the stored text, when `s` is the JSON
    string that starts (at its opening quote) at `start`."""
    return start + len(json.dumps(s[:i], ensure_ascii=False)) - 1


class _FrDoc:
    """One Federal Register document: its fields, and where each stands in its text."""

    def __init__(self, store: Store, doc_id: str):
        self.doc_id = doc_id
        text = store.text(doc_id)
        self.fr = json.loads(text)
        self.spans = json_spans(text)

    def value(self, spec: str, key: str):
        """(the field's value, its provenance): a missing or null field is null `absent`."""
        v = self.fr.get(key)
        if v is None:
            return None, null_prov(self.doc_id, spec, "absent")
        return v, value_prov(self.doc_id, spec, self.spans.get((key,)))

    def at(self, spec: str, *path):
        return value_prov(self.doc_id, spec, self.spans.get(path))

    def part_span(self, k: int, start: int, end: int, whole: bool) -> tuple[int, int] | None:
        """The span of `start..end` of the `docket_ids` string number `k` (the string itself,
        quotes included, when `whole`)."""
        string = self.spans.get(("docket_ids", k))
        if string is None:
            return None
        if whole:
            return string
        s = self.fr["docket_ids"][k]
        return _offset(s, string[0], start), _offset(s, string[0], end)


def _fr_document(d: _FrDoc, status: str | None) -> RowRecord:
    fr, doc_id = d.fr, d.doc_id
    row: dict = {}
    prov: dict = {}
    for column, key in (("id", "document_number"), ("type", "type"),
                        ("publication_date", "publication_date"), ("title", "title"),
                        ("action", "action"), ("effective_on", "effective_on")):
        row[column], prov[column] = d.value(f"fr.{column}@1", key)
    date = fr.get("publication_date")
    year = _number(date[:4]) if isinstance(date, str) else None
    row["year"] = year
    prov["year"] = (d.at("fr.year@1", "publication_date") if year is not None else
                    null_prov(doc_id, "fr.year@1", "absent" if date is None else "unparseable"))
    agencies = fr.get("agencies") or []
    k = specific_agency(agencies)
    name = None if k is None else agencies[k].get("name")
    row["agency"] = name
    prov["agency"] = (d.at("fr.agency@1", "agencies", k, "name") if name is not None
                      else null_prov(doc_id, "fr.agency@1", "absent"))
    labels: dict[str, int] = {}
    for i, ref in enumerate(fr.get("cfr_references") or []):
        if isinstance(ref, dict) and ref.get("title") is not None and ref.get("part") is not None:
            labels.setdefault(f"{ref['title']} CFR {ref['part']}", i)
    row["cfr_parts"] = list(labels)
    prov["cfr_parts"] = [d.at("fr.cfr_parts@1", "cfr_references", i) for i in labels.values()]
    row["status"] = status
    prov["status"] = (value_prov(doc_id, "fr.status@1") if status is not None
                      else null_prov(doc_id, "fr.status@1", "absent"))
    others = _others(d)
    row["other_ids"] = [text for text, _ in others]
    prov["other_ids"] = [value_prov(doc_id, "fr.other_ids@1", span) for _, span in others]
    return RowRecord(doc_id=doc_id, row=row, prov=prov)


def _others(d: _FrDoc) -> list[tuple[str, tuple[int, int] | None]]:
    """The `docket_ids` parts that are no docket, as written, with their spans."""
    out = []
    for k, s in enumerate(d.fr.get("docket_ids") or []):
        if isinstance(s, str):
            for part in scan_dockets(s)[1]:
                out.append((part.text, d.part_span(
                    k, part.start, part.end, whole=(part.start, part.end) == (0, len(s)))))
    return out


def _fr_cfr_refs(d: _FrDoc) -> list[RowRecord]:
    doc_id, out, seen = d.doc_id, [], set()
    for i, ref in enumerate(d.fr.get("cfr_references") or []):
        if not isinstance(ref, dict) or ref.get("title") is None or ref.get("part") is None:
            continue
        label = f"{ref['title']} CFR {ref['part']}"
        if label in seen:
            continue
        seen.add(label)
        title, part = _number(ref["title"]), _number(ref["part"])
        row = {"id": d.fr.get("document_number"), "cfr_part": label, "title": title,
               "part": part}
        prov = {
            "id": d.at("fr.id@1", "document_number"),
            "cfr_part": d.at("fr.cfr_part@1", "cfr_references", i),
            "title": (d.at("fr.cfr_title@1", "cfr_references", i) if title is not None
                      else null_prov(doc_id, "fr.cfr_title@1", "unparseable")),
            "part": (d.at("fr.cfr_part_number@1", "cfr_references", i) if part is not None
                     else null_prov(doc_id, "fr.cfr_part_number@1", "unparseable")),
        }
        out.append(RowRecord(doc_id=doc_id, row=row, prov=prov))
    return out


def _fr_agencies(d: _FrDoc) -> list[RowRecord]:
    doc_id, out = d.doc_id, []
    agencies = d.fr.get("agencies") or []
    k = specific_agency(agencies)
    for i, a in enumerate(agencies):
        if not isinstance(a, dict):
            continue
        row = {"id": d.fr.get("document_number"), "position": i, "name": a.get("name"),
               "fr_agency_id": a.get("id"), "parent_id": a.get("parent_id"), "specific": i == k}
        prov: dict = {
            "id": d.at("fr.id@1", "document_number"),
            "position": value_prov(doc_id, "fr.agency_position@1"),
            "specific": value_prov(doc_id, "fr.agency_specific@1"),
        }
        for column, key, spec in (("name", "name", "fr.agency_name@1"),
                                  ("fr_agency_id", "id", "fr.fr_agency_id@1"),
                                  ("parent_id", "parent_id", "fr.agency_parent_id@1")):
            prov[column] = (d.at(spec, "agencies", i, key) if a.get(key) is not None
                            else null_prov(doc_id, spec, "absent"))
        out.append(RowRecord(doc_id=doc_id, row=row, prov=prov))
    return out


def _fr_dockets(d: _FrDoc) -> list[RowRecord]:
    doc_id, out, seen = d.doc_id, [], set()
    for k, s in enumerate(d.fr.get("docket_ids") or []):
        if not isinstance(s, str):
            continue
        for docket, number, _ in scan_dockets(s)[0]:
            if docket in seen:
                continue
            seen.add(docket)
            row = {"id": d.fr.get("document_number"), "docket": docket, "raw": s}
            prov = {
                "id": d.at("fr.id@1", "document_number"),
                "docket": value_prov(doc_id, "fr.docket@1",
                                     d.part_span(k, number.start, number.end, whole=False)),
                "raw": d.at("fr.docket_raw@1", "docket_ids", k),
            }
            out.append(RowRecord(doc_id=doc_id, row=row, prov=prov))
    return out


def fr_tables(store: Store, overlay: Applicability | None) -> dict[str, list[RowRecord]]:
    """The four Federal Register tables of the store's snapshot, rows in document-number order.
    `status` is the applicability overlay's (null `absent` without one)."""
    docs = []
    for doc_id in store.doc_ids():
        if store.source(doc_id).uri.startswith(FR_PREFIX):
            docs.append(_FrDoc(store, doc_id))
    docs.sort(key=lambda d: (str(d.fr.get("document_number")), d.doc_id))
    out: dict[str, list[RowRecord]] = {"fr_documents": [], "fr_cfr_refs": [], "fr_agencies": [],
                                       "fr_dockets": []}
    for d in docs:
        envelope = None if overlay is None else overlay.records.get(d.doc_id)
        out["fr_documents"].append(
            _fr_document(d, None if envelope is None else envelope.status))
        out["fr_cfr_refs"].extend(_fr_cfr_refs(d))
        out["fr_agencies"].extend(_fr_agencies(d))
        out["fr_dockets"].extend(_fr_dockets(d))
    return out


# -- papers manifest -----------------------------------------------------------------------------

def papers_tables(store: Store) -> dict[str, list[RowRecord]]:
    """`papers` (one row per manifest row, numbered from 1) and `paper_authors` of the papers
    manifest of the store's snapshot; both empty when it holds none."""
    out: dict[str, list[RowRecord]] = {"papers": [], "paper_authors": []}
    for doc_id in store.doc_ids():
        if store.source(doc_id).uri != PAPERS_URI:
            continue
        text = store.text(doc_id)
        for number, (row, (start, end)) in enumerate(_csv_rows_with_spans(text), 1):
            out["papers"].append(_paper(doc_id, number, row, (start, end)))
            out["paper_authors"].extend(_paper_authors(text, doc_id, number, row, (start, end)))
    return out


def _paper(doc_id: str, number: int, row: dict, span: tuple[int, int]) -> RowRecord:
    values: dict = {c: row.get(c, "") for c in MANIFEST_COLUMNS}
    prov: dict = {c: value_prov(doc_id, f"papers.{c}@1", span) for c in MANIFEST_COLUMNS}
    values["id"], prov["id"] = _row_id(row), value_prov(doc_id, "papers.id@1", span)
    values["row"], prov["row"] = number, value_prov(doc_id, "papers.row@1", span)
    year = values["year"]
    if year.isdigit():
        values["year"] = int(year)
    else:
        values["year"] = None
        prov["year"] = null_prov(doc_id, "papers.year@1", "unparseable" if year else "absent")
    topics = [t.strip() for t in values["also_in"].split(";") if t.strip()]
    values["also_in_list"] = topics
    prov["also_in_list"] = [value_prov(doc_id, "papers.also_in_list@1", span) for _ in topics]
    return RowRecord(doc_id=doc_id, row=values, prov=prov)


def _paper_authors(text: str, doc_id: str, number: int, row: dict, span: tuple[int, int]
                   ) -> list[RowRecord]:
    found = author_tokens(text, *span)
    if found is not None:
        tokens, et_al = found
        located = [(name, (s, e)) for name, s, e in tokens]
    else:     # the field could not be located in the row: the authors have no span of their own
        names, et_al = split_authors(row.get("authors", ""))
        located = [(name, None) for name in names]
    paper_id = _row_id(row)
    out = []
    for position, (name, at) in enumerate(located):
        values = {"id": paper_id, "row": number, "position": position, "raw": name,
                  "name_key": author_key(name), "et_al": et_al}
        prov = {
            "id": value_prov(doc_id, "papers.id@1", span),
            "row": value_prov(doc_id, "papers.row@1", span),
            "position": value_prov(doc_id, "papers.author_position@1", at),
            "raw": value_prov(doc_id, "papers.author_raw@1", at),
            "name_key": value_prov(doc_id, "papers.author_key@1", at),
            "et_al": value_prov(doc_id, "papers.author_et_al@1", span),
        }
        out.append(RowRecord(doc_id=doc_id, row=values, prov=prov))
    return out
