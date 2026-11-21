"""The eCFR structure of 33 CFR part 117 and its links to the Federal Register (Phase 3 spec
§4.3, §5.5, §6): sections with their heading and state, read from the document's structure
(no model), and the report of which drawbridge titles link to which sections.

`ecfr_sections` reads the stored XML (`<store>/blobs/`) and locates every `DIV8` section text in
the document's canonical text exactly as `GovAdapter.section_spans` does (the section's extracted
text, found by `find` from the end of the previous one); the heading is the section's first line
and the state is the head of the enclosing `DIV7` subject group, found by `find` from the end of
the previous section. A section outside any state group has no state.

A drawbridge title is "Drawbridge Operation Regulation(s)" followed by `;` or `:`. Its comma
parts after that are the waterway candidates; a last part that is a USPS code is the state. A
link holds when a part's key equals a section heading's key and the states are equal; a title
with no state links only when exactly one state has a section with that key. Nothing is matched
more loosely (no fuzzy match, no full state names).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from adr_eval.corpora.extract import extract_text
from adr_store import applicability as ap
from adr_store.store import Store
from adr_store.tables.entities import normalise_key
from adr_store.tables.parse import STATES, drawbridge_title, waterway_key
from adr_store.tables.provenance import RowRecord

__all__ = ["STATES", "SectionUnit", "chain_docs", "ecfr_sections", "heading_waterway_key",
           "heading_waterway_text", "link_summary", "title_parts", "waterway_links"]

_HEADING_PREFIX = re.compile(r"^§\s*\S+\s*")


@dataclass(frozen=True)
class SectionUnit:
    doc_id: str
    version: str
    section: str
    heading: str
    state: str | None
    start: int
    end: int
    heading_span: tuple[int, int]
    state_span: tuple[int, int] | None
    text: str


def chain_docs(store: Store, chain: str = "ecfr:33:117") -> list[str]:
    """The documents of an applicability chain, oldest version first (ties by document id)."""
    docs = [(store.source(d).source_version, d) for d in store.doc_ids()
            if ap.chain_of(store.source(d)) == chain]
    return [d for _, d in sorted(docs)]


def _locate_line(text: str, line: str, lo: int, hi: int) -> tuple[int, int] | None:
    """Where `line` stands as a whole line of `text` inside [lo, hi), or None."""
    i = text.find(line, lo, hi)
    while i >= 0:
        j = i + len(line)
        if (i == 0 or text[i - 1] == "\n") and (j == len(text) or text[j] == "\n"):
            return i, j
        i = text.find(line, i + 1, hi)
    return None


def _group_state(div: etree._Element) -> str | None:
    """The state a section sits under: the head of its enclosing subject group when that is
    a state or territory name."""
    for up in div.iterancestors():
        if up.tag == "DIV7" and up.get("TYPE") == "SUBJGRP":
            head = up.find("HEAD")
            name = " ".join("".join(head.itertext()).split()) if head is not None else ""
            return name if name in STATES.values() else None
    return None


def _group_of(div: etree._Element) -> etree._Element | None:
    for up in div.iterancestors():
        if up.tag == "DIV7" and up.get("TYPE") == "SUBJGRP":
            return up
    return None


def located_div8(store: Store, doc_id: str
                 ) -> tuple[str, list[tuple[etree._Element, int, str, int]]]:
    """(the canonical text of eCFR document `doc_id`, every `DIV8` with text as (element,
    start, extracted text, end of the previous section) in document order). Each section's
    extracted text is found by `find` from the end of the previous one; ValueError when the
    stored bytes are not the document's or a section is not found. Shared by `ecfr_sections`
    and the Phase 4 provision reader (`units.ecfr`)."""
    raw = (Path(store.path) / "blobs" / doc_id[:2] / doc_id).read_bytes()
    if hashlib.sha256(raw).hexdigest() != doc_id:
        raise ValueError(f"{doc_id[:12]}: the stored bytes are not the document's bytes")
    full = store.text(doc_id)
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    root = etree.fromstring(raw, parser)
    out = []
    cursor = 0
    for div in root.iter("DIV8"):
        text = extract_text(etree.tostring(div, with_tail=False), "xml")
        if not text:
            continue
        at = full.find(text, cursor)
        if at < 0:
            raise ValueError(f"{doc_id[:12]}: section {div.get('N')} not found in extracted text")
        out.append((div, at, text, cursor))
        cursor = at + len(text)
    return full, out


def ecfr_sections(store: Store, doc_id: str) -> list[SectionUnit]:
    """The sections of one stored eCFR document in document order; a section number seen twice
    is kept once (the first), and a section with no text is dropped."""
    source = store.source(doc_id)
    full, divs = located_div8(store, doc_id)
    out: list[SectionUnit] = []
    seen: set[str] = set()
    state_spans: dict[etree._Element, tuple[int, int] | None] = {}
    for div, at, text, cursor in divs:
        number = div.get("N") or ""
        group = _group_of(div)
        state = _group_state(div)
        if group is not None and group not in state_spans:
            state_spans[group] = (None if state is None else _locate_line(full, state, cursor, at))
        if number and number not in seen:
            seen.add(number)
            heading = text.split("\n", 1)[0]
            out.append(SectionUnit(
                doc_id=doc_id, version=source.source_version, section=number, heading=heading,
                state=state, start=at, end=at + len(text), heading_span=(at, at + len(heading)),
                state_span=None if group is None else state_spans[group], text=text))
    return out


# -- titles and headings -------------------------------------------------------------------------

def title_parts(title: str | None) -> tuple[list[str], str | None] | None:
    """(the waterway keys of a drawbridge title's comma parts, its state name or None), or None
    for a title that is no drawbridge title."""
    found = drawbridge_title(title) if isinstance(title, str) else None
    if found is None:
        return None
    parts, state = found
    keys = [k for p in parts if (k := waterway_key(p.text))]
    return keys, None if state is None else STATES[state.text]


def heading_waterway_text(heading: str) -> str:
    """The waterway of a section heading as written: the text after "§ <number> " up to the
    first comma, or else without the final period."""
    rest = _HEADING_PREFIX.sub("", heading.strip())
    if "," in rest:
        return rest.split(",", 1)[0].strip()
    return rest.removesuffix(".").strip()


def heading_waterway_key(heading: str) -> str:
    return normalise_key("waterways", heading_waterway_text(heading))


# -- links -----------------------------------------------------------------------------------------

def _section_order(section: str) -> tuple:
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in section.split("."))


def waterway_links(fr_rows: list[RowRecord], sections: list[SectionUnit]) -> dict:
    """Link each drawbridge title among `fr_rows` (rows of `fr_documents`: `id`, `title`) to
    the sections of `sections` by (waterway key, state), one title to many sections. Returns
    {"linked": [{"id", "title", "sections"}], "unlinked": [{"id", "title", "reason"}]}, each
    in document-number order; `sections` of a link are the distinct section numbers in
    section order. Reasons: `no_matching_heading` (no part is a heading's key), `state_mismatch`
    (a part is a heading's key in other states only), `ambiguous_state` (no state in the title
    and the key is in several states). Titles that are no drawbridge titles are not listed."""
    index: dict[tuple[str, str], set[str]] = {}
    for u in sections:
        if u.state is not None:
            index.setdefault((heading_waterway_key(u.heading), u.state), set()).add(u.section)
    linked: list[dict] = []
    unlinked: list[dict] = []
    for rec in sorted(fr_rows, key=lambda r: (str(r.row["id"]), r.doc_id)):
        title = rec.row.get("title")
        parsed = title_parts(title)
        if parsed is None:
            continue
        keys, state = parsed
        entry = {"id": rec.row["id"], "title": title}
        by_state: dict[str, set[str]] = {}
        for (key, st), numbers in index.items():
            if key in keys:
                by_state.setdefault(st, set()).update(numbers)
        if state is not None:
            hit = by_state.get(state)
            reason = "state_mismatch" if by_state else "no_matching_heading"
        elif len(by_state) == 1:
            hit, reason = next(iter(by_state.values())), ""
        else:
            hit, reason = None, "ambiguous_state" if by_state else "no_matching_heading"
        if hit:
            linked.append({**entry, "sections": sorted(hit, key=_section_order)})
        else:
            unlinked.append({**entry, "reason": reason})
    return {"linked": linked, "unlinked": unlinked}


def link_summary(links: dict) -> dict:
    """Counts of a `waterway_links` result: drawbridge titles, linked, unlinked by reason."""
    reasons: dict[str, int] = {}
    for u in links["unlinked"]:
        reasons[u["reason"]] = reasons.get(u["reason"], 0) + 1
    return {"titles": len(links["linked"]) + len(links["unlinked"]),
            "linked": len(links["linked"]), "unlinked": len(links["unlinked"]),
            "unlinked_by_reason": dict(sorted(reasons.items()))}
