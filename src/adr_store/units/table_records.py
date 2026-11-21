"""Table records: one `table_record` unit per Phase 3 table slice and per in-document table
(Phase 4 spec §5.3, §10; preflight ruling C7). No table record has a model-written
description (P26): every description is a fixed template.

**Phase 3 slices** (`phase3_records`). The tables of `tables/HEAD` named in `TABLE_GROUPS`
(entity tables get none, builder note 23) give one record per (group, source document): the
rows that share the values of the group's columns (`None`: one record for the whole table, the
papers manifest). The pointer is `{kind: "tables", tables_id, table, filters}` with the span
fields null, `filters` the group's column values, which `query_table` takes as they are;
`row_count` is the group's row count. Caption and headers come from the contract (its
description and stored columns), the description is `DESCRIPTION` with the contract
description (no final period) and the source document's name ("33 CFR 117 as of
2026-06-26", "Federal Register document 2024-00001", else its URI). The unit's source span
runs from the first to the last provenance span of the group's values (the whole document
when none has a span); `canonical_ref` is `tables:<table>[:<column>=<value>,…]`.

**In-document tables** (`document_tables`), each with a span pointer `{kind: "span", doc_id,
start, end}` (the other fields null), headers from the table's first row and `row_count` the
rows after it; the description is `DOC_DESCRIPTION`:
- eCFR (gov, every version): each `TABLE` of a `DIV8` section; its extracted text is found in
  the section's text by `find` from the end of the previous table, as sections are located.
  (as whole lines). Caption: the `CAPTION` element, else the section heading. `canonical_ref`
  `<title> CFR <section> table <k>`, k counting the section's tables.
- IRM (gov): each `table` of a located IRM section (with the sections merged into it,
  `procedures.irm_sections`). Its rows are placed in the section's text by the joint anchor
  placement of the procedure skeletons (each row's cells read in order, whitespace, pipes and
  dashes between them ignored); the table runs from its first placed row to its last. A table
  none of whose rows is in the text is unlocated and reported. Caption: the `p.title` of the
  enclosing `div.table`, else the section heading. `canonical_ref` `IRM <number> table <k>`.
- Markdown (research, bench): each pipe table (a `table` element of the document's structure)
  whose second line is a delimiter row (`|---|---|`). Caption: the nearest heading above it.
  `canonical_ref` `<corpus>:<doc id> table <k>`.

`report`, when given, is filled with deterministic counts: records per Phase 3 table, and per
family the tables found, located and the unlocated ones with their reason.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from lxml import etree

from adr_eval.corpora.extract import extract_text
from adr_store import applicability as ap
from adr_store.applicability import Applicability
from adr_store.store import Store
from adr_store.tables.contracts import CONTRACT_DIR, Contract, load_contracts
from adr_store.tables.ecfr import located_div8
from adr_store.tables.overlay import load_manifest, load_rows, read_head
from adr_store.tables.provenance import RowRecord
from adr_store.units import ecfr as units_ecfr
from adr_store.units import procedures as proc
from adr_store.units.envelope import Unit, make_unit

DESCRIPTION = "Rows of {table}: {description}, {n} rows from {source}"
DOC_DESCRIPTION = "Table {k} of {where}: {n} rows under the columns {columns}"
TABLE_GROUPS: dict[str, str | tuple[str, ...] | None] = {
    "fr_documents": "id", "fr_cfr_refs": "id", "fr_agencies": "id", "fr_dockets": "id",
    "drawbridge_sections": ("section", "version"), "drawbridge_bridges": ("section", "version"),
    "papers": None, "paper_authors": None}       # None: one record for the manifest
SPEC_ID = "table_record.pointer@1"
_DELIMITER = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")


def _columns(group: str | tuple[str, ...] | None) -> tuple[str, ...]:
    return () if group is None else (group,) if isinstance(group, str) else tuple(group)


def source_name(store: Store, doc_id: str) -> str:
    """How a description names a source document: an eCFR part and version, a Federal
    Register document number, else the document's URI."""
    src = store.source(doc_id)
    family = ap.family_of(src.uri)
    if family == "ecfr":
        _, title, part = (ap.chain_of(src) or "::").split(":")
        return f"{title} CFR {part} as of {src.source_version}"
    if family == "fr":
        return f"Federal Register document {src.source_version}"
    return src.uri


def _pointer(**given) -> dict:
    return {"kind": None, "tables_id": None, "table": None, "filters": None, "doc_id": None,
            "start": None, "end": None, **given}


def _row_span(rows: list[RowRecord], length: int) -> tuple[int, int]:
    spans = [(p.start, p.end) for r in rows for v in r.prov.values()
             for p in (v if isinstance(v, list) else [v]) if p.start is not None]
    if not spans:
        return 0, length
    return min(a for a, _ in spans), max(b for _, b in spans)


def _value_key(values: tuple) -> str:
    return json.dumps(values, sort_keys=True, ensure_ascii=False)


def phase3_records(store_path: Path, store: Store, overlay: Applicability | None, corpus: str,
                   *, contracts_dir: Path = CONTRACT_DIR, report: dict | None = None
                   ) -> list[Unit]:
    """The table records of the Phase 3 tables of `tables/HEAD`, sorted by unit id: none
    without a HEAD or when its tables are another corpus's (`report["tables_id"]` is then
    null)."""
    tables_id = read_head(store_path)
    m = load_manifest(store_path, tables_id) if tables_id is not None else None
    if m is None or m.corpus != corpus:
        tables_id = m = None             # no Phase 3 tables of this corpus (bench has none)
    counts: dict[str, int] = {}
    units: list[Unit] = []
    if m is not None:
        contracts = load_contracts(contracts_dir, corpus)
        texts: dict[str, str] = {}
        for t in m.tables:
            if t.table not in TABLE_GROUPS or t.table not in contracts:
                continue
            c = contracts[t.table]
            cols = _columns(TABLE_GROUPS[t.table])
            groups: dict[tuple[str, str], tuple[tuple, list[RowRecord]]] = {}
            for r in load_rows(store_path, m, t.table):
                values = tuple(r.row[col] for col in cols)
                key = (_value_key(values), r.doc_id)
                groups.setdefault(key, (values, []))[1].append(r)
            for (_, doc_id), (values, rows) in sorted(groups.items()):
                if doc_id not in texts:
                    texts[doc_id] = store.text(doc_id)
                text = texts[doc_id]
                units.append(_phase3_unit(store, overlay, corpus, tables_id, c, cols, values,
                                          rows, doc_id, text))
            counts[t.table] = len(groups)
    if report is not None:
        report["tables_id"] = tables_id
        report["phase3"] = dict(sorted(counts.items()))
    return sorted(units, key=lambda u: u.unit_id)


def _phase3_unit(store: Store, overlay: Applicability | None, corpus: str, tables_id: str,
                 c: Contract, cols: tuple[str, ...], values: tuple, rows: list[RowRecord],
                 doc_id: str, text: str) -> Unit:
    filters = dict(zip(cols, values, strict=True))
    ref = f"tables:{c.table}" + (":" + ",".join(f"{k}={v}" for k, v in filters.items())
                                 if filters else "")
    source = source_name(store, doc_id)
    start, end = _row_span(rows, len(text))
    body = {"caption": c.description, "headers": [col.name for col in c.stored_columns],
            "description": DESCRIPTION.format(table=c.table, description=c.description.rstrip("."),
                                              n=len(rows), source=source),
            "pointer": _pointer(kind="tables", tables_id=tables_id, table=c.table,
                                filters=filters),
            "row_count": len(rows)}
    title = " ".join([c.table, *(str(v) for v in values)])
    return make_unit(type_="table_record", title=title, heading_path=[source, c.table],
                     canonical_ref=ref, text=text[start:end], doc_id=doc_id,
                     spans=[(start, end, SPEC_ID)], body=body, store=store, overlay=overlay,
                     corpus=corpus, tables_id=tables_id)


# -- in-document tables ------------------------------------------------------------------------

def _doc_unit(store: Store, overlay: Applicability | None, corpus: str, doc_id: str,
              text: str, span: tuple[int, int], *, ref: str, k: int, where: str,
              caption: str | None, headers: list[str], n: int, path: list[str]) -> Unit:
    start, end = span
    body = {"caption": caption, "headers": headers,
            "description": DOC_DESCRIPTION.format(k=k, where=where, n=n,
                                                  columns=", ".join(headers)),
            "pointer": _pointer(kind="span", doc_id=doc_id, start=start, end=end),
            "row_count": n}
    return make_unit(type_="table_record", title=caption or f"Table {k} of {where}",
                     heading_path=[*path, f"Table {k}"], canonical_ref=ref,
                     text=text[start:end], doc_id=doc_id, spans=[(start, end, SPEC_ID)],
                     body=body, store=store, overlay=overlay, corpus=corpus)


def _collapse(s: str) -> str:
    return " ".join(s.split())


def _find_lines(text: str, block: str, cursor: int) -> int:
    """Where `block` stands as whole lines of `text` from `cursor` on, or -1."""
    i = text.find(block, cursor)
    while i >= 0:
        j = i + len(block)
        if (i == 0 or text[i - 1] == "\n") and (j == len(text) or text[j] == "\n"):
            return i
        i = text.find(block, i + 1)
    return -1


def _ecfr_table(store: Store, overlay: Applicability | None, corpus: str, doc_id: str,
                full: str, tbl, at: int, *, ref: str, k: int, where: str, heading: str,
                path: list[str]) -> Unit:
    """The record of eCFR table `tbl`, whose text starts at `at` of the document's text."""
    ttext = extract_text(etree.tostring(tbl, with_tail=False), "xml")
    rows = [[_collapse("".join(c.itertext())) for c in tr if c.tag in ("TH", "TD")]
            for tr in tbl.iter("TR")]
    cap = tbl.find("CAPTION")
    caption = _collapse("".join(cap.itertext())) if cap is not None else ""
    return _doc_unit(store, overlay, corpus, doc_id, full, (at, at + len(ttext)), ref=ref,
                     k=k, where=where, caption=caption or heading,
                     headers=rows[0] if rows else [], n=max(len(rows) - 1, 0), path=path)


def _ecfr_tables(store: Store, overlay: Applicability | None, corpus: str, doc_id: str,
                 stats: dict) -> list[Unit]:
    full, divs = located_div8(store, doc_id)
    title, part = units_ecfr._part_of(store, doc_id)
    out: list[Unit] = []
    counts: dict[str, int] = {}
    in_sections = set()

    def unlocated(where: str, k: int, ttext: str) -> None:
        stats["unlocated"].append({"doc_id": doc_id, "where": where, "k": k,
                                   "reason": "empty" if not ttext else "not_in_text"})

    for div, at, text, _ in divs:
        number = div.get("N") or ""
        heading = text.split("\n", 1)[0]
        subpart = units_ecfr._subpart_of(div)
        path = [f"{title} CFR {part}", *([f"Subpart {subpart}"] if subpart else []), heading]
        where = f"{title} CFR {number}"
        cursor = 0
        for tbl in div.iter("TABLE"):
            in_sections.add(tbl)
            stats["tables"] += 1
            k = counts[where] = counts.get(where, 0) + 1
            ttext = extract_text(etree.tostring(tbl, with_tail=False), "xml")
            i = _find_lines(text, ttext, cursor) if ttext else -1
            if i < 0:
                unlocated(where, k, ttext)
                continue
            cursor = i + len(ttext)
            out.append(_ecfr_table(store, overlay, corpus, doc_id, full, tbl, at + i,
                                   ref=f"{where} table {k}", k=k, where=where,
                                   heading=heading, path=path))
    # tables outside every section (an appendix such as 47 CFR 73's alphabetical index):
    # found as whole lines after the last section
    cursor = max((at + len(text) for _, at, text, _ in divs), default=0)
    root = divs[0][0].getroottree() if divs else None
    for tbl in root.iter("TABLE") if root is not None else ():
        if tbl in in_sections:
            continue
        stats["tables"] += 1
        box = next((a for a in tbl.iterancestors() if a.find("HEAD") is not None), None)
        heading = _collapse("".join(box.find("HEAD").itertext())) if box is not None else ""
        where = f"{title} CFR {part}, {box.get('N') or heading}" if box is not None \
            else f"{title} CFR {part}"
        k = counts[where] = counts.get(where, 0) + 1
        ttext = extract_text(etree.tostring(tbl, with_tail=False), "xml")
        i = _find_lines(full, ttext, cursor) if ttext else -1
        if i < 0:
            unlocated(where, k, ttext)
            continue
        cursor = i + len(ttext)
        out.append(_ecfr_table(store, overlay, corpus, doc_id, full, tbl, i,
                               ref=f"{where} table {k}", k=k, where=where,
                               heading=heading or where,
                               path=[f"{title} CFR {part}", *([heading] if heading else [])]))
    return out


def _own_rows(table) -> list:
    return [tr for tr in table.iter("tr")
            if next(tr.iterancestors("table"), None) is table]


def _irm_caption(table) -> str | None:
    for up in table.iterancestors("div"):
        if "table" in (up.get("class") or "").split():
            titles = up.xpath('./p[contains(concat(" ", normalize-space(@class), " "), '
                              '" title ")]')
            if titles:
                return _collapse(titles[0].text_content()) or None
            return None
    return None


def _irm_tables(store: Store, overlay: Applicability | None, corpus: str, doc_id: str,
                stats: dict) -> list[Unit]:
    text = store.text(doc_id)
    chapter, raws = proc._irm_raw(store, doc_id)
    secs, _ = proc._segment(text, doc_id, raws)
    out: list[Unit] = []
    for s in secs:
        cursor = s.start
        where = f"IRM {s.number}"
        heading = f"IRM {s.number} {s.title}"
        for k, table in enumerate(proc._group(s).iter("table"), 1):
            stats["tables"] += 1
            rows = [[_collapse(" ".join(proc._lines(c))) for c in tr.xpath("./th | ./td")]
                    for tr in _own_rows(table)]
            anchors = [proc._Anchor("paragraph", tuple(c for c in row if c))
                       for row in rows if any(row)]
            proc._locate(anchors, text, cursor, s.end)
            placed = [a.found for a in anchors if a.found is not None]
            if not placed:
                stats["unlocated"].append({"doc_id": doc_id, "where": where, "k": k,
                                           "reason": "not_in_text"})
                continue
            span = (placed[0][0], placed[-1][1])
            cursor = span[1]
            out.append(_doc_unit(store, overlay, corpus, doc_id, text, span,
                                 ref=f"{where} table {k}", k=k, where=where,
                                 caption=_irm_caption(table) or heading,
                                 headers=rows[0] if rows else [], n=max(len(rows) - 1, 0),
                                 path=[f"IRM {chapter}", heading]))
    return out


def _cells(line: str) -> list[str]:
    line = line.strip()
    line = line[1:] if line.startswith("|") else line
    line = line[:-1] if line.endswith("|") else line
    return [c.strip() for c in line.split("|")]


def _md_tables(store: Store, overlay: Applicability | None, corpus: str, doc_id: str,
               stats: dict) -> list[Unit]:
    text = store.text(doc_id)
    title = text.split("\n", 1)[0].lstrip("#").strip()
    out: list[Unit] = []
    k = 0
    for e in store.elements(doc_id):
        if e.type != "table":
            continue
        lines = text[e.char_start:e.char_end].split("\n")
        if len(lines) < 2 or not _DELIMITER.match(lines[1]):
            continue
        k += 1
        stats["tables"] += 1
        caption = e.section_path[-1] if e.section_path else None
        out.append(_doc_unit(store, overlay, corpus, doc_id, text, (e.char_start, e.char_end),
                             ref=f"{corpus}:{doc_id} table {k}", k=k, where=title,
                             caption=caption, headers=_cells(lines[0]), n=len(lines) - 2,
                             path=list(e.section_path) or [title]))
    return out


def document_tables(store: Store, overlay: Applicability | None, corpus: str, *,
                    report: dict | None = None) -> list[Unit]:
    """The table records of the in-document tables of `corpus` in `store`, sorted by unit
    id: eCFR and IRM tables for gov, markdown pipe tables otherwise."""
    families: dict[str, dict] = {}
    units: list[Unit] = []

    def run(family: str, fn, docs: list[str]) -> None:
        stats = families.setdefault(family, {"tables": 0, "located": 0, "unlocated": []})
        for d in docs:
            found = fn(store, overlay, corpus, d, stats)
            stats["located"] += len(found)
            units.extend(found)

    if corpus == "gov":
        run("ecfr", _ecfr_tables, units_ecfr.ecfr_docs(store))
        run("irm", _irm_tables, sorted(d for d in store.doc_ids()
                                       if ap.family_of(store.source(d).uri) == "irm"))
    else:
        run("markdown", _md_tables, [d for d in store.doc_ids()
                                     if store.source(d).format == "md"])
    if report is not None:
        report["documents"] = families
    return sorted(units, key=lambda u: u.unit_id)
