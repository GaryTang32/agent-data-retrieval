"""Fixture stores for the Phase 3 table tests: Federal Register documents in the forms the real
corpus has (an integer CFR part, the docket string forms, an upper-case agency name, a missing
title, drawbridge titles) and a papers manifest with a quoted multi-line field, a duplicated
paper id, an empty year, "et al.", the venue and licence spellings. Nothing reads `data/` or
`.cache/`."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from adr_eval.corpora.base import Document, LoadedCorpus
from adr_eval.corpora.extract import extract_text
from adr_eval.corpora.gov import fr_document_url
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
MANIFEST: tuple[Document, bytes] = _doc(MANIFEST_BYTES, "csv", "sha256:fixture",
                                         "file://papers/manifest.csv")


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
