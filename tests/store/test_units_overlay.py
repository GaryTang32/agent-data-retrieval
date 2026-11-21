"""Unit contracts, the unit envelope, ids and versions, and the write-once unit overlay (Phase 4
spec §5.1-§5.4, P31; preflight rulings C1, C2, C7, C15). Fixture stores under `tmp_path`;
nothing reads `data/` or `.cache/`."""

import hashlib
import json
from datetime import date
from typing import get_args

import pytest
from pydantic import ValidationError

from adr_store.applicability import JURISDICTION
from adr_store.records import canonical_json
from adr_store.store import StoreError
from adr_store.tables.contracts import MAX_VALUE_BYTES, contract_sha256, load_contracts
from adr_store.tables.provenance import NullReason
from adr_store.units.contracts import (
    UNIT_TYPES,
    UnitContract,
    UnitField,
    load_unit_contracts,
    unit_contract_sha256,
    validate_unit,
)
from adr_store.units.envelope import (
    doc_envelope,
    link_versions,
    make_unit,
    meta_sha256,
    text_sha12,
    unit_id,
)
from adr_store.units.overlay import (
    UNITS_DIR,
    UnitsError,
    UnitsManifest,
    _set_units_head,
    load_units,
    load_units_manifest,
    read_units_head,
    units_manifest_path,
    write_units,
    write_units_manifest,
)
from tests.store import units_fixtures as uf
from tests.store.units_fixtures import (
    D1,
    D2,
    DOC_117_NEW,
    DOC_117_OLD,
    DOC_FAQ,
    DOC_IRM,
    DOC_RUNBOOK,
    SAMPLE_BODIES,
    overlay_of,
    sample_unit,
)

units_store = uf.units_store  # the shared fixture (C2)

PHASE3_CONTRACTS = {"agencies": "15cff9c34ecbf816", "authors": "dba12b9c7a80b7bd",
    "cfr_parts": "9acc077e1638ef99", "dockets": "44a4c6525c7d2244",
    "drawbridge_bridges": "9d818d27d1773527", "drawbridge_sections": "b33810c67890a01d",
    "fr_agencies": "fe83edc0ea496aae", "fr_cfr_refs": "2628a8c939bee9a3",
    "fr_dockets": "1aaccae81c8a73c5", "fr_documents": "5d832ea69c5a79f3",
    "licences": "f6d05fd223dd444c", "paper_authors": "f30f70b5aa0ea0ff",
    "papers": "a85744ab89450ac0", "venues": "24d8350d2d29ddd7", "waterways": "aab90a46e42e8b22"}

SNAP = "5" * 64
CONTRACTS = load_unit_contracts()
RULE_CONTRACT = CONTRACTS["rule_card"]
UNITS = [sample_unit(ref=f"33 CFR 117.821({m})", text=f"The draw ({m}) need not open.")
         for m in "abc"] + [sample_unit(doc_id=D2)]
BAD = sample_unit(ref="33 CFR 117.821(z)", text="The draw (z) need not open.",
                  body={**SAMPLE_BODIES["rule_card"], "modality": "advice"})
PARA_A = ("(a) The draw of the Main Street drawbridge, mile 3.4, at Smithfield, need not open "
          "from 7 a.m. to 9 a.m. and from 4 p.m. to 6 p.m. Monday through Friday except "
          "Federal holidays.")
# the body field a patch touches -> the unit type that has it
_TYPE_OF = {"modality": "rule_card", "steps": "procedure", "definition": "concept"}


def _type(patch: dict) -> str:
    return _TYPE_OF[next(iter(patch))]


def with_body(unit, patch: dict):
    return unit.model_copy(update={"body": {**unit.body, **patch}})


def same_paragraph_units(store):
    """The unit of § 117.821(a) in the older and the newest 33 CFR 117 version (same text)."""
    out = []
    for doc in (DOC_117_OLD, DOC_117_NEW):
        start = store.text(doc).index(PARA_A)
        out.append(make_unit(
            type_="rule_card", title="33 CFR 117.821(a)",
            heading_path=["33 CFR part 117", "Subpart B", "§ 117.821 Smith River."],
            canonical_ref="33 CFR 117.821(a)", text=PARA_A, doc_id=doc,
            spans=[(start, start + len(PARA_A), "rule_card.text@1")],
            body={**SAMPLE_BODIES["rule_card"], "provision_id": "33 CFR 117.821(a)",
                  "text": PARA_A},
            store=store, overlay=overlay_of(store), corpus="gov"))
    return out


# -- the shared fixture documents (C1) -------------------------------------------------------------

def test_units_fixture_documents(units_store):
    assert units_store.doc_ids() == sorted(d.doc_id for d, _ in uf.UNITS_DOCS)
    old, new = units_store.text(DOC_117_OLD), units_store.text(DOC_117_NEW)
    changed = {(a, b) for a, b in zip(old.splitlines(), new.splitlines(), strict=True) if a != b}
    rule_b = ("(b) The draw of the Smith River Railroad Bridge, mile 5.1, at Smithfield, shall "
              "open on signal if at least {} hours notice is given.")
    assert changed == {
        ("“Drawtender,” means the person who operates a drawbridge.",
         "Drawtender. means the person who operates a drawbridge."),
        (rule_b.format("two"), rule_b.format("four"))}
    assert old.count(PARA_A) == new.count(PARA_A) == 1
    for cited in ("§§ 117.5 and 117.31", "paragraph (b) of this section", "33 CFR part 165",
                  "§ 117.999"):
        assert cited in new
    # IRM: § 21.4.1.3.3's first own line repeats § 21.4.1.3.1's, and the canonical text keeps
    # only the first occurrence, so it is absent after § 21.4.1.3.2 begins
    irm = units_store.text(DOC_IRM)
    repeated = "Research the account with Command Code IMFOLT to find the refund transaction."
    assert irm.count(repeated) == 1
    assert irm.index(repeated) < irm.index("Research the direct deposit reject")
    assert "Command Code REQ77" in irm and "| Acronym | Definition |" in irm
    assert [units_store.text(d).split("\n")[2] for d in (uf.DOC_RUNBOOK, DOC_FAQ, uf.DOC_KCS)] \
        == ["Source: confluence", "Source: slack", "Source: confluence"]


# -- contracts -----------------------------------------------------------------------------------

def test_phase3_table_contracts_are_unchanged():
    assert {t: contract_sha256(c)[:16] for t, c in load_contracts().items()} == PHASE3_CONTRACTS


def test_committed_unit_contracts_load():
    cs = load_unit_contracts()
    assert set(cs) == set(UNIT_TYPES) and all(c.version == 1 for c in cs.values())
    for t, c in cs.items():
        assert c.type == t
        for f in c.fields:  # top-level spec ids are <type>.<field>@1 (§5.3)
            assert f.spec_id == f"{t}.{f.name}@1"
            if f.fields and {g.name for g in f.fields} == {"value", "quotes", "null_reason"}:
                reasons = next(g for g in f.fields if g.name == "null_reason").allowed
                assert set(reasons) == set(get_args(NullReason)) | {"not_extracted"}, f.name


def test_sample_units_of_every_type_are_valid():
    for t in UNIT_TYPES:
        assert validate_unit(CONTRACTS[t], sample_unit(t)) == [], t


@pytest.mark.parametrize("patch,problem", [
    ({"modality": "advice"}, "body.modality: 'advice' is not an allowed value"),
    ({"steps": "s1"}, "body.steps: expected object[], got str"),
    ({"steps": [{"id": "s1"}]}, "body.steps[0].type: missing"),
    ({"definition": {"text": 3, "span": [0, 1]}}, "body.definition.text: expected text, got int"),
])
def test_validate_unit_reports_nested_problems(patch, problem):
    t = _type(patch)
    assert problem in validate_unit(CONTRACTS[t], with_body(sample_unit(t), patch))


@pytest.mark.parametrize("type_,patch,problem", [
    ("rule_card", {"colour": "red"}, "body.colour: not a field of the contract"),
    ("rule_card", {"text": None}, "body.text: null in a non-nullable field"),
    ("rule_card", {"defined_terms": [1]},
     "body.defined_terms: expected text[], got a list holding int"),
    ("rule_card", {"modal_spans": [{"span": ["9", 17], "phrase": "need not"}]},
     "body.modal_spans[0].span: expected int[], got a list holding str"),
    ("rule_card", {"cross_refs": [{"raw": "x", "target_ref": "y", "target_unit": None,
                                   "resolution": "maybe"}]},
     "body.cross_refs[0].resolution: 'maybe' is not an allowed value"),
    ("rule_card", {"conditions": {"value": {1, 2}, "quotes": [], "null_reason": None}},
     "body.conditions.value: not a JSON value"),
    ("rule_card", {"conditions": {"value": "x" * MAX_VALUE_BYTES, "quotes": [],
                                  "null_reason": None}},
     f"body.conditions.value: value over {MAX_VALUE_BYTES} bytes"),
    ("rule_card", {"subject": {"value": None, "quotes": [], "null_reason": "forgotten"}},
     "body.subject.null_reason: 'forgotten' is not an allowed value"),
    ("procedure", {"steps": ["s1"]}, "body.steps[0]: expected object, got str"),
    ("procedure", {"steps": [{**SAMPLE_BODIES["procedure"]["steps"][0], "next": [{"to": 2}]}]},
     "body.steps[0].next[0].to: expected text, got int"),
    ("concept", {"scope": "33 CFR part 117"}, "body.scope: expected object, got str"),
    ("table_record", {"row_count": True}, "body.row_count: expected int, got bool"),
])
def test_validate_unit_types_every_field_kind(type_, patch, problem):
    assert problem in validate_unit(CONTRACTS[type_], with_body(sample_unit(type_), patch))


def test_validate_unit_checks_the_envelope():
    u = sample_unit()
    elsewhere = u.model_copy(update={"source_refs": [
        u.source_refs[0].model_copy(update={"doc_id": D2})]})
    assert f"source_refs[0].doc_id: {D2[:12]}… is not the unit's document {D1[:12]}…" in \
        validate_unit(RULE_CONTRACT, elsewhere)
    assert "source_refs: a unit needs at least one source span" in validate_unit(
        RULE_CONTRACT, u.model_copy(update={"source_refs": []}))
    assert "contract: 'rule_card@2' is not 'rule_card@1'" in validate_unit(
        RULE_CONTRACT, u.model_copy(update={"contract": "rule_card@2"}))
    assert "type: 'procedure' is not the contract's type 'rule_card'" in validate_unit(
        RULE_CONTRACT, sample_unit("procedure"))
    renamed = u.model_copy(update={"canonical_ref": "33 CFR 117.5"})
    assert any(p.startswith("unit_id: ") for p in validate_unit(RULE_CONTRACT, renamed))
    stale = u.model_copy(update={"title": "another title"})  # meta hash no longer matches
    assert "hashes.meta: not the SHA-256 of the envelope" in validate_unit(RULE_CONTRACT, stale)
    texted = u.model_copy(update={"hashes": {**u.hashes, "text": "0" * 64}})
    assert "version: not the first 12 digits of hashes.text" in validate_unit(
        RULE_CONTRACT, texted)
    selfish = u.model_copy(update={"applicability": u.applicability.model_copy(
        update={"superseded_by": u.unit_id})})
    selfish = selfish.model_copy(update={"hashes": {**u.hashes, "meta": meta_sha256(selfish)}})
    assert validate_unit(RULE_CONTRACT, selfish) == [
        "applicability.superseded_by: a unit never names itself"]


@pytest.mark.parametrize("field,message", [
    ({"name": "x", "type": "object", "nullable": False, "description": "d",
      "spec_id": "rule_card.x@1"}, "needs its nested fields"),
    ({"name": "x", "type": "text", "nullable": False, "description": "d",
      "spec_id": "rule_card.x@1", "fields": []}, "only an object field has nested fields"),
    ({"name": "x", "type": "int", "nullable": False, "description": "d",
      "spec_id": "rule_card.x@1", "allowed": ["1"]}, "allowed values need a text field"),
    ({"name": "x", "type": "object[]", "nullable": False, "description": "d",
      "spec_id": "rule_card.x@1", "fields": [
          {"name": "y", "type": "text", "nullable": False, "description": "d",
           "spec_id": "rule_card.x@1"},
          {"name": "y", "type": "int", "nullable": False, "description": "d",
           "spec_id": "rule_card.x@1"}]}, "duplicate field names"),
    ({"name": "x", "type": "uuid", "nullable": False, "description": "d",
      "spec_id": "rule_card.x@1"}, "Input should be"),
])
def test_unit_fields_are_consistent(field, message):
    with pytest.raises(ValidationError, match=message):
        UnitField.model_validate(field)


def test_unit_contract_hash_and_loading(tmp_path):
    c = RULE_CONTRACT
    assert unit_contract_sha256(c) == hashlib.sha256(canonical_json(c)).hexdigest()
    bumped = UnitContract.model_validate({**c.model_dump(), "version": 2})
    assert unit_contract_sha256(bumped) != unit_contract_sha256(c)
    (tmp_path / "concept.json").write_bytes(canonical_json(c))  # a rule_card contract
    (tmp_path / "governance.json").write_text("{}", encoding="utf-8")  # not a contract
    with pytest.raises(ValueError, match="the contract is for type 'rule_card'"):
        load_unit_contracts(tmp_path)
    (tmp_path / "concept.json").unlink()
    (tmp_path / "rule_card.json").write_bytes(canonical_json(c))
    assert list(load_unit_contracts(tmp_path)) == ["rule_card"]


# -- ids, versions and the envelope ----------------------------------------------------------------

def test_ids_and_versions():
    assert text_sha12("The draw  shall\nopen.") == text_sha12("The draw shall open.")
    assert unit_id("rule_card", "33 CFR 117.1081(a)(2)", "0123456789ab", "f" * 64) == \
        "rule_card/33 CFR 117.1081(a)(2)/0123456789ab/" + "f" * 16
    assert len(text_sha12("x")) == 12 and text_sha12("x") != text_sha12("y")
    with pytest.raises(ValueError):
        unit_id("rule_card", "33 CFR 117.5", "0123", "f" * 64)
    with pytest.raises(ValueError):
        unit_id("rule_card", "33 CFR 117.5", "0123456789ab", "f" * 16)


def test_identical_text_in_two_versions_gives_two_units(units_store):     # P31
    a, b = same_paragraph_units(units_store)          # 117 versions 2025-06-27 and 2026-06-26
    assert a.version == b.version and a.unit_id != b.unit_id and a.doc_id != b.doc_id
    assert (a.doc_id, b.doc_id) == (DOC_117_OLD, DOC_117_NEW)
    for u in (a, b):
        assert validate_unit(RULE_CONTRACT, u) == []
        r = u.source_refs[0]
        assert units_store.text(u.doc_id)[r.start:r.end] == PARA_A


def test_superseded_by_names_the_successor_never_itself(units_store):
    before = same_paragraph_units(units_store)
    old, new = link_versions(before, overlay_of(units_store))
    assert old.applicability.status == "superseded"
    assert old.applicability.superseded_by == new.unit_id != old.unit_id
    assert new.applicability.supersedes == old.unit_id
    assert new.applicability.status == "validated" and new.applicability.superseded_by is None
    assert old.hashes["meta"] != before[0].hashes["meta"]          # the envelope changed
    assert validate_unit(RULE_CONTRACT, old) == [] == validate_unit(RULE_CONTRACT, new)
    assert link_versions(before, None) == before
    # a successor document without a unit of the same canonical ref links nothing
    lone, = link_versions(before[:1], overlay_of(units_store))
    assert lone.applicability.superseded_by is None and lone.applicability.status == "superseded"


def test_envelope_from_phase2(units_store):
    ov = overlay_of(units_store)
    new_a, new_g = doc_envelope(units_store, ov, DOC_117_NEW, "gov")
    assert (new_a.status, new_a.jurisdiction, new_a.chain) == ("validated", JURISDICTION,
                                                               "ecfr:33:117")
    assert JURISDICTION == "US-federal"
    assert (new_a.effective_from, new_a.effective_to) == (date(2026, 6, 26), None)
    assert (new_g.owner, new_g.authority_tier, new_g.verifier) == ("Coast Guard", 1, None)
    old_a, _ = doc_envelope(units_store, ov, DOC_117_OLD, "gov")
    assert (old_a.status, old_a.effective_from, old_a.effective_to) == (
        "superseded", date(2025, 6, 27), date(2026, 6, 26))
    irm_a, irm_g = doc_envelope(units_store, ov, DOC_IRM, "gov")
    assert (irm_a.jurisdiction, irm_a.chain, irm_g.owner, irm_g.authority_tier) == (
        JURISDICTION, "irm:21.4.1", "Internal Revenue Service", 1)
    slack_a, slack_g = doc_envelope(units_store, ov, DOC_FAQ, "bench")
    assert (slack_g.authority_tier, slack_a.jurisdiction, slack_g.owner) == (
        4, "Redwood Inference", "slack")
    assert (slack_a.status, slack_a.chain, slack_a.effective_from) == ("validated", None, None)
    wiki_a, wiki_g = doc_envelope(units_store, ov, DOC_RUNBOOK, "bench")
    assert (wiki_g.authority_tier, wiki_g.owner) == (2, "confluence")
    for a, g in ((new_a, new_g), (slack_a, slack_g), (wiki_a, wiki_g), (irm_a, irm_g)):
        assert g.review_due is None and g.last_verified_at is None and a.audience is None
    bare_a, bare_g = doc_envelope(units_store, None, DOC_117_NEW, "gov")  # no overlay
    assert (bare_a.status, bare_a.jurisdiction, bare_g.owner, bare_g.authority_tier) == (
        "validated", None, None, 1)


def test_make_unit_refuses_a_span_outside_the_document(units_store):
    n = len(units_store.text(DOC_117_NEW))
    with pytest.raises(ValueError, match="outside"):
        make_unit(type_="rule_card", title="t", heading_path=[], canonical_ref="33 CFR 117.5",
                  text="x", doc_id=DOC_117_NEW, spans=[(n - 1, n + 1, "rule_card.text@1")],
                  body=SAMPLE_BODIES["rule_card"], store=units_store, overlay=None,
                  corpus="gov")


# -- the overlay ---------------------------------------------------------------------------------

def test_write_units_is_write_once_named_by_id_and_sorted(tmp_path):
    uf_ = write_units(tmp_path, SNAP, RULE_CONTRACT, [*reversed(UNITS)], {})
    path = tmp_path / "units" / SNAP / uf_.file
    assert uf_.file == f"rule_card-v1-{uf_.sha256[:16]}.jsonl"
    assert uf_.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert [json.loads(x)["unit_id"] for x in path.read_text().splitlines()] == \
        sorted(u.unit_id for u in UNITS)
    assert path.read_bytes() == b"".join(canonical_json(u) for u in
                                         sorted(UNITS, key=lambda u: u.unit_id))
    assert write_units(tmp_path, SNAP, RULE_CONTRACT, UNITS, {}) == uf_   # same bytes: a no-op
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(UnitsError):
        write_units(tmp_path, SNAP, RULE_CONTRACT, UNITS, {})
    assert issubclass(UnitsError, StoreError)


def test_invalid_units_are_rejected_and_counted(tmp_path):
    uf_ = write_units(tmp_path, SNAP, RULE_CONTRACT, [*UNITS, BAD], report := {})
    assert uf_.rejected == 1 and report["rejected"][0]["problems"]
    assert report["rejected"][0]["unit_id"] == BAD.unit_id and uf_.units == len(UNITS)
    stored = json.loads((tmp_path / "units" / SNAP / uf_.file.replace(
        ".jsonl", ".report.json")).read_text())
    assert stored["rejected"] == report["rejected"] and stored["units"] == len(UNITS)
    assert report["null_reasons"]["subject"] == {"not_extracted": len(UNITS)}


def test_a_repeated_unit_id_is_rejected_not_stored_twice(tmp_path):      # N15
    uf_ = write_units(tmp_path, SNAP, RULE_CONTRACT, [*UNITS, UNITS[0]], report := {})
    assert (uf_.units, uf_.rejected) == (len(UNITS), 1)
    assert report["rejected"][0]["problems"] == ["duplicate unit id"]


def _manifest(tmp_path, *files) -> UnitsManifest:
    return UnitsManifest(format_version="0.1", snapshot=SNAP, corpus="gov", tables_id=None,
                         applicability=None, passes={}, units=list(files))


def test_manifest_id_is_its_sha256_and_load_checks_files(tmp_path):
    rules = write_units(tmp_path, SNAP, RULE_CONTRACT, UNITS, {})
    faq = write_units(tmp_path, SNAP, CONTRACTS["faq"], [sample_unit("faq")], {})
    units_id, path = write_units_manifest(tmp_path, _manifest(tmp_path, faq, rules))
    assert units_id == hashlib.sha256(path.read_bytes()).hexdigest()
    assert path == tmp_path / UNITS_DIR / SNAP / f"units-{units_id[:16]}.json"
    assert units_manifest_path(tmp_path, units_id) == path
    assert units_manifest_path(tmp_path, "0" * 64) is None
    m = load_units_manifest(tmp_path, units_id)
    assert [f.type for f in m.units] == ["faq", "rule_card"]
    assert load_units(tmp_path, m, "rule_card") == sorted(UNITS, key=lambda u: u.unit_id)
    assert [u.type for u in load_units(tmp_path, m)] == ["faq"] + ["rule_card"] * len(UNITS)
    with pytest.raises(UnitsError, match="no unit file of type 'concept'"):
        load_units(tmp_path, m, "concept")
    with pytest.raises(ValidationError, match="sorted by type"):
        _manifest(tmp_path, rules, faq)
    unit_file = tmp_path / UNITS_DIR / SNAP / rules.file
    unit_file.write_bytes(unit_file.read_bytes()[:-1])
    with pytest.raises(UnitsError, match="rule_card"):
        load_units_manifest(tmp_path, units_id)
    path.write_bytes(path.read_bytes().replace(b'"gov"', b'"bench"'))
    with pytest.raises(UnitsError, match="not the units id"):
        load_units_manifest(tmp_path, units_id)
    with pytest.raises(UnitsError, match="no units manifest"):
        load_units_manifest(tmp_path, "0" * 64)


def test_units_head_names_a_loadable_manifest_or_nothing(tmp_path):
    assert read_units_head(tmp_path) is None
    rules = write_units(tmp_path, SNAP, RULE_CONTRACT, UNITS, {})
    units_id, _ = write_units_manifest(tmp_path, _manifest(tmp_path, rules))
    with pytest.raises(UnitsError):
        _set_units_head(tmp_path, "0" * 64)
    assert read_units_head(tmp_path) is None
    _set_units_head(tmp_path, units_id)
    assert (tmp_path / UNITS_DIR / "HEAD").read_text() == f"{units_id}\n"
    assert read_units_head(tmp_path) == units_id
    (tmp_path / UNITS_DIR / SNAP / rules.file).unlink()   # a file of the manifest is gone
    assert read_units_head(tmp_path) is None
    (tmp_path / UNITS_DIR / "HEAD").write_text("not an id\n")
    assert read_units_head(tmp_path) is None
