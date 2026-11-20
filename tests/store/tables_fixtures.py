"""Fixture stores for the Phase 3 table tests: Federal Register documents in the forms the real
corpus has (an integer CFR part, the docket string forms, an upper-case agency name, a missing
title, drawbridge titles) and a papers manifest with a quoted multi-line field, a duplicated
paper id, an empty year, "et al.", the venue and licence spellings. Nothing reads `data/` or
`.cache/`."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from adr_eval.corpora.base import Document, LoadedCorpus
from adr_eval.corpora.extract import extract_text
from adr_eval.corpora.gov import ecfr_url, fr_document_url
from adr_eval.models import Manifest, ManifestDoc
from adr_store import acl
from adr_store import applicability as ap
from adr_store.store import Store

REPO = Path(__file__).parents[2]
FR_FIELDS = ["document_number", "type", "title", "action", "dates", "publication_date",
             "effective_on", "agencies", "cfr_references", "docket_ids"]
GOV_CONFIG = {"corpus": "gov", "parts": []}
DHS = {"id": 1, "name": "Homeland Security Department", "parent_id": None}
COAST_GUARD = {"id": 2, "name": "Coast Guard", "parent_id": 1}
FCC = {"id": 3, "name": "Federal Communications Commission", "parent_id": None}
AGENCIES = [DHS, COAST_GUARD]
TITLE = "Drawbridge Operation Regulation; Cape Fear River, Wilmington, NC"
T0 = datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)
MANIFEST_BYTES = (Path(__file__).parents[1] / "fixtures" / "tables" / "manifest.csv").read_bytes()


def _doc(raw: bytes, fmt: str, version: str, uri: str) -> tuple[Document, bytes]:
    doc_id = hashlib.sha256(raw).hexdigest()
    return Document(doc_id, extract_text(raw, fmt), fmt, version, uri), raw


def fr_doc(number: str, *, type_: str = "Rule", title: str | None = TITLE,
           published: str = "2024-03-04", effective: str | None = None,
           agencies: list[dict] = AGENCIES,
           cfr: tuple[dict, ...] = ({"title": 33, "part": "117"},),
           dockets: tuple[str, ...] = ("Docket No. USCG-2024-0001",),
           action: str = "Final rule.") -> tuple[Document, bytes]:
    """A Federal Register API document; `title=None` leaves the title out."""
    body = {"document_number": number, "type": type_, "action": action,
            "dates": "This rule is effective March 15, 2024.", "publication_date": published,
            "effective_on": effective, "agencies": list(agencies),
            "cfr_references": list(cfr), "docket_ids": list(dockets)}
    if title is not None:
        body["title"] = title
    return _doc(json.dumps(body).encode("utf-8"), "json", number,
                fr_document_url(number, FR_FIELDS))


FR_DOCS: list[tuple[Document, bytes]] = [
    # an integer part beside the same part as text (one reference), a docket given twice
    fr_doc("2024-00001", effective="2024-03-15",
           cfr=({"title": 33, "part": 117}, {"title": 33, "part": "117"},
                {"title": 33, "part": "165"}),
           dockets=("Docket No. USCG-2024-0001", "Docket No. USCG-2024-0001")),
    # a missing title, a part that is no number, an upper-case agency name
    fr_doc("2024-00002", type_="Proposed Rule", title=None, action="Notice of proposed rulemaking.",
           agencies=[{"id": 9, "name": "COAST GUARD", "parent_id": None}],
           cfr=({"title": 33, "part": "117a"},), dockets=("Docket Number USCG-2022-0895",)),
    # the FCC docket forms: letters carried over, "and", a second docket part, other ids
    fr_doc("2024-00003", agencies=[FCC], cfr=({"title": 47, "part": "73"},),
           title="Television Broadcasting Services",
           dockets=("MB Docket Nos. 17-105 and 14-127, MM Docket No. 00-168",
                    "ET Docket Nos. 03-137 and 13-84, FCC 19-126", "FR ID 343182")),
    # two drawbridge titles, a bracketed docket, bare identifiers
    fr_doc("2024-00004", effective="2024-05-01", title="Drawbridge Operation Regulation; "
           "Atlantic Intracoastal Waterway, Myrtle Beach, SC",
           dockets=("Docket No. [USCG-2025-0464",)),
    fr_doc("2024-00005", type_="Proposed Rule", title="Drawbridge Operation Regulation; "
           "Neuse River, New Bern, NC", dockets=("RM-12006, RM-12019", "USCG-2022-0709"),
           action="Notice of proposed rulemaking."),
    # no agencies, no references, no docket ids
    fr_doc("2024-00006", agencies=[], cfr=(), dockets=(), title="Temporary change – \"x\""),
]
# a bare continuation number: "17-105" carries the letters of the docket part before it
FR_DOCS.append(fr_doc(
    "2024-00007", agencies=[FCC], cfr=({"title": 47, "part": "73"},),
    title="Television Broadcasting Services; Fixture",
    dockets=("MB Docket Nos. 17-317, 17-105", "ET Docket No. 99-1, 99-2")))
MANIFEST: tuple[Document, bytes] = _doc(MANIFEST_BYTES, "csv", "sha256:fixture",
                                         "file://papers/manifest.csv")


ECFR_117 = (Path(__file__).parents[1] / "fixtures" / "tables" / "ecfr_117.xml").read_bytes()
ECFR_OLD, ECFR_NEW = "2025-06-27", "2026-06-26"


def ecfr_doc(date: str, raw: bytes = ECFR_117) -> tuple[Document, bytes]:
    """33 CFR 117 as of `date`; the older version differs from the newest in one section."""
    if date != ECFR_NEW:
        raw = raw.replace(b"four hours notice", b"two hours notice")
    return _doc(raw, "xml", date, ecfr_url(33, "117", date))


def make_tables_store(path: Path, docs=None, *, rules=None) -> Store:
    """A store of `docs` (default: FR_DOCS and MANIFEST) with its applicability overlay
    written; with `rules` (ACL policy rules) the access-control state is synced too."""
    docs = [*FR_DOCS, MANIFEST] if docs is None else docs
    s = Store.create(path)
    for document, raw in docs:
        s.add(document, raw)
    s.commit()
    store = Store.open(path)
    overlay, _ = ap.derive(store, GOV_CONFIG)
    ap.write_overlay(path, overlay)
    if rules is not None:
        config = Path(path).parent / f"{Path(path).name}-acl"
        config.mkdir(parents=True, exist_ok=True)
        (config / "directory.json").write_bytes((REPO / "config/acl/directory.json").read_bytes())
        policy = json.loads((REPO / "config/acl/policy.json").read_text(encoding="utf-8"))
        policy["rules"] = rules
        (config / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
        acl.sync(path, config / "directory.json", config / "policy.json", clock=lambda: T0)
    return store


def loaded_of(store: Store, catalog: str = "papers/manifest.csv") -> LoadedCorpus:
    """The store's documents as a loaded corpus, for the v0.1 adapters' `records()`: the
    manifest document sits at `catalog`, the others at their URI."""
    entries, docs = [], {}
    for doc_id in store.doc_ids():
        src = store.source(doc_id)
        path = catalog if src.uri == f"file://{catalog}" else src.uri
        entries.append(ManifestDoc(doc_id=doc_id, uri=src.uri, format=src.format,
                                   source_version=src.source_version, bytes=src.byte_length,
                                   license=src.license or "unknown", path=path))
        docs[doc_id] = Document(doc_id, store.text(doc_id), src.format, src.source_version,
                                src.uri)
    manifest = Manifest(corpus="fixture", version="0", license_summary="fixture",
                        documents=entries)
    return LoadedCorpus(manifest=manifest, docs=docs, empty_docs=[], root=store.path)


# -- 33 CFR 117 facts, as a model would extract them (Phase 3 task 9) ----------------------------

# Per fixture section (ecfr_117.xml): section-level and per-draw facts, column -> (value, quote).
# A column left out is absent. The older version of 117.821 says "two hours notice" (`ecfr_doc`).
ECFR_SECTIONS = 7          # sections per version; the two versions differ in 117.821 only
ECFR_FACTS: dict[str, dict] = {
    "117.1": {"section": {}, "draws": []},
    "117.821": {"section": {"waterway": ("Cape Fear River", "Cape Fear River")}, "draws": [
        {"bridge": ("Cape Fear Memorial Bridge", "Cape Fear Memorial Bridge"),
         "mile": (26.8, "mile 26.8"), "notice_hours": (4, "four hours notice"),
         "opens_on_signal": (True, "shall open on signal")}]},
    "117.823": {"section": {"waterway": ("Neuse River", "Neuse River")}, "draws": [
        {"bridge": ("US 17 Bridge", "US 17 Bridge"), "mile": (2.0, "mile 2.0"),
         "opens_on_signal": (True, "shall open on signal")},
        {"bridge": ("Norfolk Southern Railroad Bridge", "Norfolk Southern Railroad Bridge"),
         "mile": (3.1, "mile 3.1"), "opens_on_signal": (False, "need not open"),
         "closed_periods": (["7 a.m. to 9 a.m."], "need not open from 7 a.m. to 9 a.m.")},
        {"bridge": ("NC 55 Bridge", "NC 55 Bridge"), "mile": (4.5, "mile 4.5"),
         "notice_hours": (12, "12 hours notice"),
         "opens_on_signal": (True, "shall open on signal if at least 12 hours notice")}]},
    "117.827": {"section": {"waterway": ("Atlantic Intracoastal Waterway",
                                         "Atlantic Intracoastal Waterway")}, "draws": [
        {"bridge": ("Surf City Bridge", "Surf City Bridge"), "mile": (260.7, "mile 260.7"),
         "opens_on_signal": (True, "shall open on signal")}]},
    "117.829": {"section": {}, "draws": []},
    "117.261": {"section": {"waterway": ("Atlantic Intracoastal Waterway",
                                         "Atlantic Intracoastal Waterway"),
                            "seasonal": (True, "From November 1 through April 30")}, "draws": [
        {"bridge": ("Lake Worth Bridge", "Lake Worth Bridge"),
         "mile": (1014.0, "mile 1014.0"), "opens_on_signal": (False, "need not open"),
         "closed_periods": (["8 a.m. to 6 p.m. on weekends"],
                            "need not open from 8 a.m. to 6 p.m. on weekends")}]},
    "117.263": {"section": {"waterway": ("Atlantic Intracoastal Waterway",
                                         "Atlantic Intracoastal Waterway"),
                            "owner_or_agency": ("The bridge tender", "The bridge tender"),
                            "vhf_channel": (9, "VHF-FM channel 9")}, "draws": [
        {"bridge": ("Venetian Causeway Bridge", "Venetian Causeway Bridge"),
         "mile": (1088.5, "mile 1088.5"), "opens_on_signal": (True, "shall open on signal")}]},
}
_SECTION_NUMBER = re.compile(r"^§ (\S+)")


def ecfr_facts(section_text: str) -> dict:
    """The facts of one fixture section text (the version is read from the text)."""
    facts = ECFR_FACTS[_SECTION_NUMBER.match(section_text).group(1)]
    if "two hours notice" in section_text:
        draw = {**facts["draws"][0], "notice_hours": (2, "two hours notice")}
        facts = {**facts, "draws": [draw]}
    return facts


def _cell(facts: dict, column: str) -> dict:
    if column not in facts:
        return {"value": None, "quote": None, "null_reason": "absent"}
    value, quote = facts[column]
    return {"value": value, "quote": quote, "null_reason": None}


def asked_columns(system: str) -> list[str]:
    """The model columns an extraction prompt asks for: those its "Specs:" line names."""
    line = next(x for x in system.splitlines() if x.startswith("Specs: "))
    return [spec.split(".", 1)[1].split("@")[0] for spec in line[len("Specs: "):].split(", ")]


def fixture_reply(system: str, user: str, repeat: int) -> str:
    """A first-pass reply to an extraction prompt: the fixture facts of the columns it asks
    for, with the bridge name (and mile) of each draw when the prompt asks for draw columns."""
    from adr_store.tables.extract import DRAW_COLUMNS, SECTION_COLUMNS

    asked = asked_columns(system)
    facts = ecfr_facts(user)
    section = {c: _cell(facts["section"], c) for c in SECTION_COLUMNS if c in asked}
    draw_cols = [c for c in DRAW_COLUMNS if c in asked]
    if draw_cols and "bridge" not in draw_cols:
        draw_cols = ["bridge", "mile", *[c for c in draw_cols if c != "mile"]]
    draws = [{c: _cell(d, c) for c in draw_cols} for d in facts["draws"]] if draw_cols else []
    return json.dumps({"section": section, "draws": draws})


def _answer(facts: dict, column: str, kind: str = "text") -> str:
    if column not in facts:
        return "NONE"
    value, quote = facts[column]
    if kind == "bool":
        shown = "YES" if value else "NO"
    elif kind == "list":
        shown = "; ".join(value)
    elif isinstance(value, float) and value.is_integer() and column != "mile":
        shown = str(int(value))
    else:
        shown = str(value)
    return f'{shown} | "{quote}"'


def fixture_numbered(system: str, user: str, repeat: int) -> str:
    """A second-pass reply (numbered answers) with the fixture facts of a section text."""
    facts = ecfr_facts(user)
    s = facts["section"]
    lines = [f"1. WATERWAY: {_answer(s, 'waterway')}",
             f"2. SEASONAL: {_answer(s, 'seasonal', 'bool')}",
             f"3. OWNER: {_answer(s, 'owner_or_agency')}",
             f"4. VHF CHANNEL: {_answer(s, 'vhf_channel')}",
             f"5. DRAWS: {len(facts['draws'])}"]
    for k, d in enumerate(facts["draws"], 1):
        lines += [f"5.{k}.a BRIDGE: {_answer(d, 'bridge')}",
                  f"5.{k}.b MILE: {_answer(d, 'mile')}",
                  f"5.{k}.c NOTICE HOURS: {_answer(d, 'notice_hours')}",
                  f"5.{k}.d OPENS ON SIGNAL: {_answer(d, 'opens_on_signal', 'bool')}",
                  f"5.{k}.e CLOSED PERIODS: {_answer(d, 'closed_periods', 'list')}"]
    return "\n".join(lines) + "\n"


def ecfr_store_at(path: Path) -> Store:
    """A store of both fixture versions of 33 CFR 117 and the Federal Register documents."""
    return make_tables_store(path, [ecfr_doc(ECFR_NEW), ecfr_doc(ECFR_OLD), *FR_DOCS])
