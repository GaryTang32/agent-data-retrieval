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
later tasks add their fixtures here and list them in their Files (Task 15: the rule enrichment
replies, `units_enrich_reply`; Task 17: the binding review replies, `review_reply`). Nothing
reads `data/` or `.cache/`.
"""

from __future__ import annotations

import json
import re
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
                   "span": [0, 21], "tool": None, "subprocedure_ref": None,
                   "args_schema": None, "condition": None,
                   "next": [{"to": "s2", "guard": None}], "risk": "unknown",
                   "requires_approval": False, "preconditions": []},
                  {"id": "s2", "type": "end", "text": "", "span": None, "tool": None,
                   "subprocedure_ref": None, "args_schema": None, "condition": None,
                   "next": [], "risk": "unknown",
                   "requires_approval": False, "preconditions": []}],
        "escalation": None, "success_criteria": None,
        "tests": [{"condition": None, "edge": None, "steps": ["s1", "s2"]}],
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


def rule_body(doc_id: str = D1, **changes) -> dict:
    """The sample rule card body with its closure entries on `doc_id` (closure stays in the
    card's document, P5/P31) and `changes` applied."""
    body = SAMPLE_BODIES["rule_card"]
    return {**body, "closure": [{**e, "doc_id": doc_id} for e in body["closure"]], **changes}


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
        aids=Aids(), body=(rule_body(doc_id) if type_ == "rule_card" else SAMPLE_BODIES[type_])
        if body is None else body)
    draft = Unit(**fields, hashes={"text": "", "meta": ""})
    return draft.model_copy(update={"hashes": {
        "text": text_sha256(text), "meta": meta_sha256(draft)}})



# -- a units store with its Phase 3 tables (Task 6) ---------------------------------------------

# Per section of `ecfr_117_units.xml`: section-level and per-draw facts, column -> (value, quote),
# as a model would extract them (the `tables_fixtures.ECFR_FACTS` form). A column left out is
# absent. The older version of 117.821 says "two hours notice" (`ecfr_117_doc`).
UNITS_ECFR_FACTS: dict[str, dict] = {
    "117.4": {"section": {}, "draws": []},
    "117.5": {"section": {}, "draws": []},
    "117.31": {"section": {}, "draws": []},
    "117.40": {"section": {}, "draws": []},
    "117.821": {"section": {"waterway": ("Smith River", "Smith River")}, "draws": [
        {"bridge": ("Main Street drawbridge", "Main Street drawbridge"),
         "mile": (3.4, "mile 3.4"), "opens_on_signal": (False, "need not open"),
         "closed_periods": (["7 a.m. to 9 a.m.", "4 p.m. to 6 p.m."],
                            "need not open from 7 a.m. to 9 a.m. and from 4 p.m. to 6 p.m.")},
        {"bridge": ("Smith River Railroad Bridge", "Smith River Railroad Bridge"),
         "mile": (5.1, "mile 5.1"), "notice_hours": (4, "four hours notice"),
         "opens_on_signal": (True, "shall open on signal")}]},
    "117.901": {"section": {"waterway": ("Harbor River", "Harbor River"),
                            "seasonal": (True, "From November 1 through March 31")}, "draws": [
        {"bridge": ("Harbor Avenue Bridge", "Harbor Avenue Bridge"), "mile": (0.8, "mile 0.8"),
         "notice_hours": (24, "24 hours notice"),
         "opens_on_signal": (True, "shall open on signal")}]},
    "117.1081": {"section": {"waterway": ("Coast Channel", "Coast Channel")}, "draws": [
        {"bridge": ("Coast Channel Bridge", "Coast Channel Bridge"), "mile": (2.2, "mile 2.2"),
         "closed_periods": (["6:30 a.m. to 8:30 a.m."],
                            "need not open from 6:30 a.m. to 8:30 a.m.")}]},
}


def units_ecfr_facts(section_text: str) -> dict:
    """The facts of one section text of `ecfr_117_units.xml` (the version is read from the
    text: the older one says "two hours notice")."""
    from tests.store.tables_fixtures import _SECTION_NUMBER

    facts = UNITS_ECFR_FACTS[_SECTION_NUMBER.match(section_text).group(1)]
    if "two hours notice" in section_text:
        draws = [{**d, "notice_hours": (2, "two hours notice")} if "notice_hours" in d else d
                 for d in facts["draws"]]
        facts = {**facts, "draws": draws}
    return facts


def units_fixture_reply(system: str, user: str, repeat: int, *, facts_of=None) -> str:
    """A first-pass reply to an extraction prompt over `ecfr_117_units.xml`, as
    `tables_fixtures.fixture_reply` gives for the Phase 3 fixture, from `facts_of(section_text)`
    (default `units_ecfr_facts`)."""
    from adr_store.tables.extract import DRAW_COLUMNS, SECTION_COLUMNS
    from tests.store.tables_fixtures import _cell, asked_columns

    asked = asked_columns(system)
    facts = (facts_of or units_ecfr_facts)(user)
    section = {c: _cell(facts["section"], c) for c in SECTION_COLUMNS if c in asked}
    draw_cols = [c for c in DRAW_COLUMNS if c in asked]
    if draw_cols and "bridge" not in draw_cols:
        draw_cols = ["bridge", "mile", *[c for c in draw_cols if c != "mile"]]
    draws = [{c: _cell(d, c) for c in draw_cols} for d in facts["draws"]] if draw_cols else []
    return json.dumps({"section": section, "draws": draws})


def units_fixture_numbered(system: str, user: str, repeat: int, *,
                           facts_of=None) -> str:
    """A second-pass reply (numbered answers) for a section of `ecfr_117_units.xml`, from
    `facts_of(section_text)` (default `units_ecfr_facts`; the simulation fixture gives its own,
    Task 19)."""
    from tests.store.tables_fixtures import _answer

    facts = (facts_of or units_ecfr_facts)(user)
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


# every fixture document is readable by tenant acme (the auditor's groups hold acme's)
UNITS_RULES = [{"match": {"uri_prefix": "https://"}, "access": ["tenant:acme"]}]


def make_units_store_with_tables(path: Path, reply=None) -> Store:
    """`UNITS_DOCS` and the Phase 3 Federal Register documents, with ACL state (`UNITS_RULES`,
    clock `T0`), a lexical index, and the Phase 3 tables built (metadata, entities and the
    33 CFR 117 extraction from `reply`, default `units_fixture_reply`, behind a cached stub whose
    cache sits beside the store) and promoted to `tables/HEAD` through the Phase 3 merge
    gate."""
    from adr_eval.cache import Cache
    from adr_eval.llm import CachedStubClient
    from adr_store import tools
    from adr_store.tables import extract as ex
    from adr_store.tables.build import build_tables
    from adr_store.tables.gate import gate
    from tests.store.tables_fixtures import FR_DOCS

    store = make_units_store(path, [*UNITS_DOCS, *FR_DOCS[:3]], rules=UNITS_RULES)
    tools.Tools(path).index("p1-struct", lexical_only=True)
    stub = CachedStubClient("stub-sonnet", Cache(Path(path).parent / f"{Path(path).name}-llm"),
                            reply or units_fixture_reply)
    tables_id = build_tables(path, "gov", with_extraction=True, client=stub,
                             max_calls=len(ex.units(store))).tables_id
    assert gate(path, tables_id, [], 0).promoted
    return store


@pytest.fixture
def units_store_with_tables(tmp_path) -> Store:
    return make_units_store_with_tables(tmp_path / "units-tables-store")


def as_auditor(store: Store):
    """The tools of `store` as the auditor (ACL on), one minute after the ACL sync."""
    from datetime import timedelta

    from adr_store import tools

    return tools.Tools(store.path, acl=True, caller="user:auditor",
                       clock=lambda: T0 + timedelta(minutes=1))


@pytest.fixture
def built_units(units_store_with_tables):
    """(store, the gov build of `units_store_with_tables`, and its bench build)."""
    from adr_store.units.build import build_units

    store = units_store_with_tables
    return store, build_units(store.path, "gov"), build_units(store.path, "bench")


# -- a promoted gov units build with per-document access (Task 8) --------------------------------

ECFR_165_URI = ecfr_url(33, "165", ECFR_NEW)
# the first rule that matches wins: 33 CFR 165 for group acme/0 only, both 33 CFR 117 versions
# (one chain, so one access list) and the bench documents for tenant acme, the IRM chapter for
# tenant globex. acme-0 sees 117, 165 and bench; acme-1 117 and bench; globex-0 the IRM only;
# the outsider nothing; the auditor everything.
UNITS_ACL_RULES = [
    {"match": {"uri_prefix": ECFR_165_URI}, "access": ["group:acme/0"]},
    {"match": {"uri_prefix": "https://www.ecfr.gov/"}, "access": ["tenant:acme"]},
    {"match": {"uri_prefix": "https://www.irs.gov/"}, "access": ["tenant:globex"]},
    {"match": {"uri_prefix": "https://huggingface.co/"}, "access": ["tenant:acme"]},
]
UNITS_USERS = ["user:acme-0", "user:acme-1", "user:globex-0", "user:outsider", "user:auditor"]


def promote_units(path: Path, corpus: str = "gov") -> str:
    """Build the units of `corpus` and promote them as the store's first units/HEAD (the units
    merge gate with no cases, builder note 8); the units id."""
    from adr_store.units.build import build_units
    from adr_store.units.gate import units_gate

    def no_case(store_path, units_id, case):  # a first promotion has no cases to hit
        raise AssertionError("no case is evaluated in a first promotion")

    units_id = build_units(path, corpus).units_id
    assert units_gate(path, units_id, [], 0, hit=no_case).promoted
    return units_id


def make_units_built(path: Path, docs=None, *, rules=None, corpus: str = "gov") -> Store:
    """`make_units_store` of `docs` (default `UNITS_DOCS`) with ACL state (`rules`, default
    `UNITS_ACL_RULES`, clock `T0`), a lexical Phase 2 index, and the `corpus` units built and
    promoted to units/HEAD."""
    from adr_store import tools

    store = make_units_store(path, docs, rules=UNITS_ACL_RULES if rules is None else rules)
    tools.Tools(path).index("p1-struct", lexical_only=True)
    promote_units(path, corpus)
    return store


@pytest.fixture
def units_built(tmp_path) -> Store:
    """`make_units_built` under `tmp_path`: the gov units of `UNITS_DOCS` built and promoted,
    with per-document access (`UNITS_ACL_RULES`)."""
    return make_units_built(tmp_path / "units-built")


# -- rule enrichment replies (Task 15, preflight C2) ---------------------------------------------
# A model's reply to `rule-enrich@1` for the sections of `ecfr_117_units.xml`: § 117.821 (two
# closed windows of the Main Street drawbridge, Monday to Friday except Federal holidays; the
# railroad bridge on four hours notice), § 117.901 (on signal, 24 hours notice from November 1
# through March 31), and every other section its cards with absent fields and no draw.

ENRICH_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
ENRICH_TIMES_A = "from 7 a.m. to 9 a.m."


def enrich_cell(value, quote=None, null_reason=None) -> dict:
    """A reply cell `{value, quote, null_reason}` (absent by default when `value` is None)."""
    if value is None:
        return {"value": None, "quote": None, "null_reason": null_reason or "absent"}
    return {"value": value, "quote": quote, "null_reason": None}


ENRICH_ABSENT = enrich_cell(None)


def enrich_closed_period(begin="7 a.m.", until="9 a.m.", times=ENRICH_TIMES_A,
                         **changes) -> dict:
    """A `need_not_open` period of § 117.821(a), Monday to Friday except Federal holidays;
    `changes` replace its cells."""
    c = enrich_cell
    p = {"effect": c("need_not_open", "need not open"), "start": c(begin, times),
         "end": c(until, times), "days": c(ENRICH_WEEKDAYS, "Monday through Friday"),
         "except_federal_holidays": c(True, "except Federal holidays"),
         "date_from": ENRICH_ABSENT, "date_to": ENRICH_ABSENT}
    return {**p, **changes}


def enrich_reply_821(**period_changes) -> dict:
    """A well-formed reply for § 117.821; `period_changes` replace cells of the first period of
    the first draw."""
    c, absent = enrich_cell, ENRICH_ABSENT
    return {
        "cards": {
            "33 CFR 117.821(a)": {
                "subject": c("the draw of the Main Street drawbridge",
                             "The draw of the Main Street drawbridge"),
                "conditions": c(["from 7 a.m. to 9 a.m.", "from 4 p.m. to 6 p.m.",
                                 "Monday through Friday except Federal holidays"],
                                "need not open from 7 a.m. to 9 a.m. and from 4 p.m. to 6 p.m. "
                                "Monday through Friday except Federal holidays"),
                "thresholds": absent,
                "exceptions": c(["Federal holidays"], "except Federal holidays")},
            "33 CFR 117.821(b)": {
                "subject": c("the draw of the Smith River Railroad Bridge",
                             "The draw of the Smith River Railroad Bridge"),
                "conditions": c(["at least four hours notice is given"],
                                "if at least four hours notice is given"),
                "thresholds": c(["4 hours notice"], "at least four hours notice"),
                "exceptions": absent}},
        "draws": [
            {"bridge": c("Main Street drawbridge", "Main Street drawbridge"),
             "mile": c(3.4, "mile 3.4"), "opening_basis": absent, "notice_hours": absent,
             "periods": [enrich_closed_period(**period_changes),
                         enrich_closed_period("4 p.m.", "6 p.m.", "from 4 p.m. to 6 p.m.")]},
            {"bridge": c("Smith River Railroad Bridge", "Smith River Railroad Bridge"),
             "mile": c(5.1, "mile 5.1"),
             "opening_basis": c("advance_notice", "shall open on signal if at least four hours "
                                                  "notice is given"),
             "notice_hours": c(4, "four hours notice"), "periods": []}]}


def enrich_reply_901() -> dict:
    """A well-formed reply for § 117.901 (no card fields: the cards come back absent)."""
    c, absent = enrich_cell, ENRICH_ABSENT
    season = "From November 1 through March 31"
    return {"cards": {}, "draws": [
        {"bridge": c("Harbor Avenue Bridge", "Harbor Avenue Bridge"), "mile": c(0.8, "mile 0.8"),
         "opening_basis": c("on_signal", "shall open on signal"),
         "notice_hours": c(24, "24 hours notice"),
         "periods": [{"effect": c("notice_required", "shall open on signal if at least 24 hours "
                                                     "notice is given"),
                      "start": absent, "end": absent, "days": absent,
                      "except_federal_holidays": absent,
                      "date_from": c("November 1", season), "date_to": c("March 31", season)}]}]}


def units_enrich_reply(system: str, user: str, repeat: int) -> str:
    """A reply for every section of `ecfr_117_units.xml` (the section is read from the heading
    the user message starts with; the card ids from its RULE CARDS lines)."""
    section = user.split(" ", 2)[1]
    if section == "117.821":
        return json.dumps(enrich_reply_821())
    if section == "117.901":
        return json.dumps(enrich_reply_901())
    ids = user.split("\n\nRULE CARDS:\n", 1)[1].splitlines()
    return json.dumps({"cards": {i: dict.fromkeys(
        ("subject", "conditions", "thresholds", "exceptions"), ENRICH_ABSENT) for i in ids},
        "draws": []})


# -- binding review replies (Task 17, preflight C2) ----------------------------------------------
# A model's reply to `binding-review@1`: one verdict per binding label of the review message
# (`[B<n>] binding <binding id>` lines), "approve" unless `verdicts` names the binding id.

REVIEW_LABEL = re.compile(r"^\[(B\d+)\] binding ([0-9a-f]{64})$", re.MULTILINE)


def review_reply(verdicts: dict[str, str] | None = None, default: str = "approve"):
    """A stub reply function `(system, user, repeat) -> str`: per binding of the message the
    verdict `verdicts[binding_id]` (default `default`) with a one-line reason."""
    verdicts = verdicts or {}

    def reply(system: str, user: str, repeat: int) -> str:
        out = []
        for label, bid in REVIEW_LABEL.findall(user):
            v = verdicts.get(bid, default)
            out.append({"binding": label, "verdict": v,
                        "reason": f"{v}: the binding states the rule as the card reads"})
        return json.dumps({"verdicts": out})

    return reply


# -- a promoted gov units build with promoted bindings (Task 18, preflight C2) -------------------
# The bindings of §§ 117.821 (two draws) and 117.901 (one draw) of the newest 33 CFR 117
# version, compiled from `units_enrich_reply` against the rule cards of the promoted units
# build, tested (the real tests), stamped analysed by the test helper (CI has no z3), approved
# by `review_reply` behind a cached stub, written and promoted to bindings/HEAD. Its known draws
# are those three and § 117.1081 draw 1, which has no binding.

def make_units_built_with_bindings(path: Path) -> Store:
    """`make_units_built` with signed-off bindings promoted (module comment above). The
    bindings manifest's tables id is the units build's, or zeros when it read no tables (the
    fixture's units have none; the gate never reads it)."""
    from adr_eval.cache import Cache
    from adr_eval.llm import CachedStubClient
    from adr_store.bindings.build import known_draws
    from adr_store.bindings.checks import mark_tested
    from adr_store.bindings.compile import compile_bindings
    from adr_store.bindings.enrich import enrich_section
    from adr_store.bindings.manifest import promote_bindings, write_bindings
    from adr_store.bindings.review import review_all
    from adr_store.units import overlay as units_overlay
    from tests.store.bindings_fixtures import stamp_analysed

    store = make_units_built(path)
    units_id = units_overlay.read_units_head(path)
    m = units_overlay.load_units_manifest(path, units_id)
    cards = [u for u in units_overlay.load_units(path, m, "rule_card")
             if u.doc_id == DOC_117_NEW]
    llm = Path(path).parent / f"{Path(path).name}-llm"
    enrich = CachedStubClient("stub-sonnet", Cache(llm / "enrich"), units_enrich_reply)
    items = [enrich_section(s, store, cards, enrich) for s in ("117.821", "117.901")]
    compiled, _ = compile_bindings(items, cards)
    candidates = stamp_analysed(mark_tested(compiled))
    review = CachedStubClient("stub-opus", Cache(llm / "review"), review_reply())
    reviewed, _ = review_all(None, candidates, review, cards=cards)
    # known draws (P49): the enriched draws, and § 117.1081 as a pool section whose reply gave
    # no draw (one draw by its table count): a known draw with no binding, which escalates
    known = known_draws(items, {"117.1081": 1}, DOC_117_NEW)
    bindings_id, _ = write_bindings(path, store.snapshot_id, units_id,
                                    m.tables_id or "0" * 64, reviewed, known_draws=known)
    promote_bindings(path, bindings_id)
    return store


@pytest.fixture
def units_built_with_bindings(tmp_path) -> Store:
    """`make_units_built_with_bindings` under `tmp_path`."""
    return make_units_built_with_bindings(tmp_path / "units-bindings")
