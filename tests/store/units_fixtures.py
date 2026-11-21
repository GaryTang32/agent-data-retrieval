"""Shared fixtures for the Phase 4 unit tests (preflight rulings C1, C2, C15).

The fixture documents under `tests/fixtures/units/`: two versions of a 33 CFR 117 excerpt
(subpart A §§ 117.4, 117.5, 117.31, 117.40; subpart B §§ 117.821, 117.901, 117.1081 with a
closed window, a seasonal notice rule, "paragraph (b) of this section", "§§ 117.5 and
117.31", "33 CFR part 165" and the absent § 117.999), a 33 CFR 165 excerpt ("designated
representative" defined for the part and again for § 165.T01; "regulated navigation area
(RNA)"), an IRM chapter excerpt (four `div.section`: an "Acronyms" table, two If/Then
sections, and a last section, § 21.4.1.3.3, that the canonical text drops whole: the HTML
extractor's `favor_precision` trims the trailing block, so its first own line, which also
repeats § 21.4.1.3.1's, cannot be located after § 21.4.1.3.2 and none of its text survives to
be merged; unlike the real IRM text, the fixture's canonical text keeps no table of
contents), and three bench documents: a runbook (Confluence), an FAQ (Slack) and a KCS
article (Confluence). The older 117 version differs from the newest in § 117.821(b) ("two
hours notice") and in how § 117.4 marks "Drawtender"; § 117.821(a) is the same in both.

`make_units_store` writes the store with its applicability overlay derived under a gov config
that lists 33/117 and 33/165 (Coast Guard) and 47/73 (FCC), so eCFR issuers are known (C15).
Tests import the pytest fixtures explicitly, as Phase 3 tests import `tables_fixtures` (C2):
later tasks add their fixtures here and list them in their Files. Nothing reads `data/` or
`.cache/`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adr_eval.corpora.base import Document
from adr_eval.corpora.gov import ecfr_url
from adr_store import acl
from adr_store import applicability as ap
from adr_store.store import Store
from adr_store.units.envelope import (
    COMPILER_VERSION,
    Aids,
    Governance,
    Lineage,
    SourceRef,
    Unit,
    UnitApplicability,
    meta_sha256,
    text_sha12,
    text_sha256,
    unit_id,
)
from tests.store.tables_fixtures import ECFR_NEW, ECFR_OLD, REPO, T0, _doc

FIXTURES = Path(__file__).parents[1] / "fixtures" / "units"
UNITS_GOV_CONFIG = {"corpus": "gov", "parts": [
    {"title": 33, "part": "117", "agency": "coast-guard"},
    {"title": 33, "part": "165", "agency": "coast-guard"},
    {"title": 47, "part": "73", "agency": "federal-communications-commission"}]}
ECFR_117_UNITS = (FIXTURES / "ecfr_117_units.xml").read_bytes()
ECFR_165_UNITS = (FIXTURES / "ecfr_165_units.xml").read_bytes()
IRM_HTML = (FIXTURES / "irm_procedures.html").read_bytes()
IRM_VERSION = "2026-09-02"
IRM_URI = "https://www.irs.gov/irm/part21/irm_21-004-001r"
BENCH_CONFIG = json.loads((REPO / "corpora" / "bench" / "config.json").read_text("utf-8"))


def ecfr_117_doc(date: str) -> tuple[Document, bytes]:
    """The 33 CFR 117 excerpt as of `date`: the newest (`ECFR_NEW`) as committed; any other
    date says "two hours notice" in § 117.821(b) and quotes “Drawtender,” in § 117.4."""
    raw = ECFR_117_UNITS
    if date != ECFR_NEW:
        raw = raw.replace(b"four hours notice", b"two hours notice").replace(
            b"<I>Drawtender.</I> means", "“Drawtender,” means".encode())
    return _doc(raw, "xml", date, ecfr_url(33, "117", date))


def ecfr_165_doc(date: str = ECFR_NEW) -> tuple[Document, bytes]:
    return _doc(ECFR_165_UNITS, "xml", date, ecfr_url(33, "165", date))


def irm_doc() -> tuple[Document, bytes]:
    return _doc(IRM_HTML, "html", IRM_VERSION, IRM_URI)


def bench_doc(name: str, row: int) -> tuple[Document, bytes]:
    """A bench fixture document at the URI form of the bench adapter (row, benchmark id)."""
    raw = (FIXTURES / f"bench_{name}.md").read_bytes()
    uri = f"{BENCH_CONFIG['documents']['url']}#row={row}&doc_id=dsid_fixture_{name}"
    return _doc(raw, "md", BENCH_CONFIG["revision"], uri)


UNITS_DOCS: list[tuple[Document, bytes]] = [
    ecfr_117_doc(ECFR_OLD), ecfr_117_doc(ECFR_NEW), ecfr_165_doc(), irm_doc(),
    bench_doc("runbook", 1), bench_doc("faq", 2), bench_doc("kcs", 3)]
DOC_117_OLD, DOC_117_NEW, DOC_165, DOC_IRM, DOC_RUNBOOK, DOC_FAQ, DOC_KCS = (
    d.doc_id for d, _ in UNITS_DOCS)


def make_units_store(path: Path, docs=None, *, rules=None) -> Store:
    """A store of `docs` (default `UNITS_DOCS`) with its applicability overlay derived under
    `UNITS_GOV_CONFIG`; with `rules` (ACL policy rules) the access-control state is synced
    too, at the fixed clock `T0` (as `tables_fixtures.make_tables_store`)."""
    docs = UNITS_DOCS if docs is None else docs
    s = Store.create(path)
    for document, raw in docs:
        s.add(document, raw)
    s.commit()
    store = Store.open(path)
    overlay, _ = ap.derive(store, UNITS_GOV_CONFIG)
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


def overlay_of(store: Store) -> ap.Applicability | None:
    """The store's applicability overlay (as written by `make_units_store`)."""
    return ap.load_overlay(store.path, store.snapshot_id)


@pytest.fixture
def units_store(tmp_path) -> Store:
    """`make_units_store` of `UNITS_DOCS` under `tmp_path`, without ACL state."""
    return make_units_store(tmp_path / "units-store")


# -- store-free units, for the validator and the overlay -----------------------------------------

D1, D2 = "1" * 64, "2" * 64


def model_field(value=None, *, quotes=(), status: str = "verified",
                null_reason: str = "not_extracted") -> dict:
    """A model-written body field `{value, quotes[], status, null_reason}`: with a value, its
    `status` and no null reason; without one, no status and `null_reason` (by default the
    canonical not-extracted form of §5.3)."""
    given = value is not None
    return {"value": value, "quotes": [{"text": t, "span": [a, b]} for t, a, b in quotes],
            "status": status if given else None, "null_reason": None if given else null_reason}


SAMPLE_BODIES: dict[str, dict] = {
    "rule_card": {
        "provision_id": "33 CFR 117.821(a)", "text": "The draw need not open.",
        "modality": "exemption", "modal_spans": [{"span": [109, 117], "phrase": "need not"}],
        "subject": model_field(), "conditions": model_field(), "thresholds": model_field(),
        "exceptions": model_field(), "defined_terms": [],
        "cross_refs": [{"raw": "§ 117.5", "target_ref": "33 CFR 117.5", "target_unit": None,
                        "resolution": "resolved", "span": [130, 137]}],
        "closure": [{"relation": "exception_of", "ref": "33 CFR 117.5(p1)",
                     "unit_id": "rule_card/33 CFR 117.5(p1)/0123456789ab/" + "1" * 16,
                     "doc_id": D1, "span": [40, 90]},
                    {"relation": "context", "ref": "33 CFR 117.821(c)", "unit_id": None,
                     "doc_id": D1, "span": [300, 380]}],
        "bindings": []},
    "concept": {
        "pref_label": "drawtender", "alt_labels": [], "hidden_labels": ["drawtender",
                                                                      "drawtenders"],
        "definition": {"text": "Drawtender means the person who operates a drawbridge.",
                       "span": [0, 55]},
        "scope": {"kind": "part", "ref": "33 CFR part 117"}, "scope_note": None,
        "broader": [], "narrower": [], "related": [], "exact_match": []},
    "procedure": {
        "when_to_use": model_field("Use when a refund is missing.",
                                   quotes=[("refund was not received", 10, 33)]),
        "not_for": model_field(null_reason="absent"), "trigger_examples": model_field(),
        "problem_abstractions": model_field(), "inputs": [], "preconditions": [],
        "steps": [{"id": "s1", "type": "instruction", "text": "Research the account.",
                   "span": [0, 21], "tool": None, "args_schema": None, "condition": None,
                   "next": [{"to": "s2", "guard": None}], "risk": "unknown",
                   "requires_approval": False, "preconditions": []},
                  {"id": "s2", "type": "end", "text": "", "span": None, "tool": None,
                   "args_schema": None, "condition": None, "next": [], "risk": "unknown",
                   "requires_approval": False, "preconditions": []}],
        "escalation": None, "success_criteria": None, "tests": [["s1", "s2"]],
        "ambiguity_flags": ["coarse"], "source_kind": "irm"},
    "faq": {
        "question": {"text": "Who approves?", "span": [0, 13]},
        "answer": {"text": "The service owner.", "span": [17, 35]},
        "issue": None, "environment": None, "cause": None, "resolution": None},
    "table_record": {
        "caption": None, "headers": ["section", "version"],
        "description": "Rows of drawbridge_bridges: draws, 2 rows from 33 CFR 117",
        "pointer": {"kind": "tables", "tables_id": "4" * 64, "table": "drawbridge_bridges",
                    "filters": {"section": "117.821", "version": "2026-06-26"},
                    "doc_id": None, "start": None, "end": None},
        "row_count": 2},
}


def sample_unit(type_: str = "rule_card", *, ref: str = "33 CFR 117.821(a)",
                text: str = "The draw need not open.", doc_id: str = D1,
                body: dict | None = None) -> Unit:
    """A valid unit of `type_` built without a store: ids, hashes and its one source ref are
    consistent; the envelope is that of a document with no Phase 2 record."""
    sha12 = text_sha12(text)
    fields = dict(
        unit_id=unit_id(type_, ref, sha12, doc_id), type=type_, title=ref, heading_path=[ref],
        canonical_ref=ref, version=sha12, doc_id=doc_id, contract=f"{type_}@1",
        source_refs=[SourceRef(doc_id=doc_id, start=0, end=len(text),
                               spec_id=f"{type_}.text@1")],
        lineage=Lineage(compiler=COMPILER_VERSION, prompt_version=None, served_model=None,
                        cache_key_sha256=None),
        tables_id=None,
        applicability=UnitApplicability(status="validated", effective_from=None,
                                        effective_to=None, supersedes=None,
                                        superseded_by=None, chain=None, jurisdiction=None),
        governance=Governance(owner=None, verifier=None, authority_tier=None),
        aids=Aids(), body=SAMPLE_BODIES[type_] if body is None else body)
    draft = Unit(**fields, hashes={"text": "", "meta": ""})
    return draft.model_copy(update={"hashes": {
        "text": text_sha256(text), "meta": meta_sha256(draft)}})

