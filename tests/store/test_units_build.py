"""FAQ, KCS and table records, `build_units` and the units merge gate (Phase 4 Task 6; spec
§5.2-§5.4, §6.6, §10; criteria T3, T4, T6; preflight rulings C1, C7, C9, C16)."""

import json
import re
from pathlib import Path

import pytest

from adr_store.tables.contracts import load_contracts
from adr_store.tables.overlay import load_manifest, load_rows, read_head
from adr_store.units import build as build_mod
from adr_store.units.build import CORPUS_TYPES, build_units
from adr_store.units.closure import duplicate_provision_ids
from adr_store.units.contracts import load_unit_contracts, validate_unit
from adr_store.units.ecfr import ecfr_docs, provisions
from adr_store.units.envelope import COMPILER_VERSION, link_versions, make_unit
from adr_store.units.faq import faq_units, kcs_units
from adr_store.units.gate import UnitCase, units_gate
from adr_store.units.overlay import (
    UNITS_DIR,
    UnitsError,
    load_units,
    load_units_manifest,
    read_units_head,
    write_units,
    write_units_manifest,
)
from adr_store.units.table_records import (
    DESCRIPTION,
    DOC_DESCRIPTION,
    TABLE_GROUPS,
    document_tables,
    phase3_records,
)
from tests.store import units_fixtures as uf
from tests.store.tables_fixtures import _doc
from tests.store.units_fixtures import (
    BENCH_CONFIG,
    DOC_117_NEW,
    DOC_117_OLD,
    DOC_FAQ,
    DOC_IRM,
    DOC_KCS,
    as_auditor,
    make_units_store,
    overlay_of,
)

units_store = uf.units_store
units_store_with_tables = uf.units_store_with_tables
built_units = uf.built_units
CONTRACTS = load_unit_contracts()


def bench_md(name: str, text: str, row: int = 90) -> tuple:
    """A bench document `text` at the bench adapter's URI form."""
    uri = f"{BENCH_CONFIG['documents']['url']}#row={row}&doc_id=dsid_{name}"
    return _doc(text.encode("utf-8"), "md", BENCH_CONFIG["revision"], uri)


def resliced(text: str, span) -> str:
    return text[span[0]:span[1]]


# -- FAQ and KCS -----------------------------------------------------------------------------------

def test_faq_pairs_and_kcs_fields(units_store):
    f = faq_units(units_store, overlay_of(units_store))
    assert [u.body["question"]["text"] for u in f] == ["How do I rotate the key?", "Who approves?"]
    k = kcs_units(units_store, overlay_of(units_store))[0].body
    assert k["cause"] is not None and k["environment"] is None        # missing heading: absent
    faq_text, kcs_text = units_store.text(DOC_FAQ), units_store.text(DOC_KCS)
    first = f[0]
    assert first.body["answer"]["text"] == (
        "Open the credentials page in the admin console, create a new key, deploy it to every "
        "service that reads the old one, then revoke the old key.")
    assert [u.canonical_ref for u in f] == [f"bench:{DOC_FAQ} Q1", f"bench:{DOC_FAQ} Q2"]
    for u in f:
        assert u.doc_id == DOC_FAQ and validate_unit(CONTRACTS["faq"], u) == []
        for field in ("question", "answer"):
            assert resliced(faq_text, u.body[field]["span"]) == u.body[field]["text"]
        assert [r.spec_id for r in u.source_refs] == ["faq.question@1", "faq.answer@1"]
        assert all(u.body[x] is None for x in ("issue", "environment", "cause", "resolution"))
        assert u.governance.authority_tier == 4 and u.governance.owner == "slack"
    kcs, = kcs_units(units_store, overlay_of(units_store))
    assert kcs.canonical_ref == f"bench:{DOC_KCS} KCS" and kcs.doc_id == DOC_KCS
    assert kcs.title == "Batch inference jobs stuck in QUEUED"
    assert k["issue"]["text"] == ("Batch inference jobs stay in the QUEUED state for more than "
                                  "an hour and never start.")
    assert k["resolution"]["text"].startswith("Raise the per-tenant worker quota")
    assert k["resolution"]["text"].endswith("Queued jobs start within five minutes.")
    for field in ("issue", "cause", "resolution"):
        assert resliced(kcs_text, k[field]["span"]) == k[field]["text"]
    assert k["question"] is None and k["answer"] is None
    assert [r.spec_id for r in kcs.source_refs] == ["faq.issue@1", "faq.cause@1",
                                                     "faq.resolution@1"]
    assert validate_unit(CONTRACTS["faq"], kcs) == []


FAQ_FORMS = """# Security FAQ (working draft)

Source: confluence

- Q: Where is my data stored?
  - A (updated detail): In the region the customer picks.

**Q: Can Support post on the status page?**
A: Follow the comms guide.
It names who posts.

Question: Who signs off on promotions?

Answer: Manager and peer review.

Q: Why did tokens spike? A: Repeated prompts.
Q: What is not answered?

Leo: Question: wired LAN?
A: not a pair, the question line has a speaker.
"""


def test_faq_markup_forms(tmp_path):
    doc = bench_md("faq_forms", FAQ_FORMS)
    store = make_units_store(tmp_path / "s", [doc])
    units = faq_units(store, overlay_of(store))
    pairs = [(u.body["question"]["text"], u.body["answer"]["text"]) for u in units]
    assert pairs == [
        ("Where is my data stored?", "In the region the customer picks."),
        ("Can Support post on the status page?", "Follow the comms guide.\nIt names who posts."),
        ("Who signs off on promotions?", "Manager and peer review.")]
    text = store.text(doc[0].doc_id)
    for u in units:
        for field in ("question", "answer"):
            assert resliced(text, u.body[field]["span"]) == u.body[field]["text"]
    assert kcs_units(store, overlay_of(store)) == []


KCS_FORMS = """# Known issue: timeouts with structured output

Source: confluence

## 1. Symptoms:

Requests time out after 60 seconds.

## Customer environment

Hosted API.

## Root cause

A schema compiler stall.

### Details

The cache was cold.

## Workaround / mitigation

Retry with a smaller schema.

## Symptom-first triage

Not a KCS field.
"""

NOT_KCS = """# Runbook: private upgrade

Source: confluence

## Environment prerequisites (must be true)

Helm 3.

## Steps

1. Upgrade.
"""


def test_kcs_heading_rules(tmp_path):
    kcs_doc, other = bench_md("kcs_forms", KCS_FORMS, 91), bench_md("not_kcs", NOT_KCS, 92)
    store = make_units_store(tmp_path / "s", [kcs_doc, other])
    units = kcs_units(store, overlay_of(store))
    assert [u.doc_id for u in units] == [kcs_doc[0].doc_id]      # environment alone is no KCS
    b = units[0].body
    assert b["issue"]["text"] == "Requests time out after 60 seconds."
    assert b["environment"] is None      # "Customer environment" does not start with the word
    assert b["cause"]["text"] == "A schema compiler stall.\n\n### Details\n\nThe cache was cold."
    assert b["resolution"]["text"] == "Retry with a smaller schema."
    text = store.text(kcs_doc[0].doc_id)
    for f in ("issue", "cause", "resolution"):
        assert resliced(text, b[f]["span"]) == b[f]["text"]


# -- table records ---------------------------------------------------------------------------------

def test_phase3_table_records_point_to_query_table_filters(units_store_with_tables):
    store = units_store_with_tables
    recs = phase3_records(store.path, store, overlay_of(store), "gov")
    rec = next(r for r in recs if r.body["pointer"]["table"] == "drawbridge_bridges"
               and r.body["pointer"]["filters"]["section"] == "117.821"
               and r.body["pointer"]["filters"]["version"] == "2026-06-26")
    p = rec.body["pointer"]
    # the C7 pointer: the kind-specific fields of the other kind are null (Task 1 review)
    assert p == {"kind": "tables", "tables_id": read_head(store.path),
                 "table": "drawbridge_bridges",
                 "filters": {"section": "117.821", "version": "2026-06-26"},
                 "doc_id": None, "start": None, "end": None}
    assert as_auditor(store).query_table(p["table"], p["filters"], "count").count == \
        rec.body["row_count"] == 2
    assert rec.doc_id == DOC_117_NEW and rec.tables_id == read_head(store.path)
    assert rec.canonical_ref == "tables:drawbridge_bridges:section=117.821,version=2026-06-26"
    assert validate_unit(CONTRACTS["table_record"], rec) == []


def test_phase3_records_one_per_table_and_document_group(units_store_with_tables):
    store = units_store_with_tables
    tables_id = read_head(store.path)
    m = load_manifest(store.path, tables_id)
    recs = phase3_records(store.path, store, overlay_of(store), "gov")
    by_table: dict[str, list] = {}
    for r in recs:
        by_table.setdefault(r.body["pointer"]["table"], []).append(r)
    entity = {t.table for t in m.tables if t.kind == "entity"}
    assert entity and not entity & set(by_table)                 # builder note 23
    assert set(by_table) <= set(TABLE_GROUPS)
    for table, records in by_table.items():
        rows = load_rows(store.path, m, table)
        cols = TABLE_GROUPS[table]
        cols = () if cols is None else (cols,) if isinstance(cols, str) else cols
        groups = {(tuple(r.row[c] for c in cols), r.doc_id) for r in rows}
        assert len(records) == len(groups), table
        for rec in records:
            f = rec.body["pointer"]["filters"]
            assert list(f) == list(cols)
            mine = [r for r in rows if all(r.row[c] == f[c] for c in cols)
                    and r.doc_id == rec.doc_id]
            assert rec.body["row_count"] == len(mine) > 0
            assert rec.body["headers"] == [c.name for c in load_contracts(
                corpus="gov")[table].stored_columns]
    assert len(by_table["fr_documents"]) == 3                    # one per FR document
    # the newest 117 version: 7 sections, 3 of them with draws
    newest = [r for r in by_table["drawbridge_sections"] if r.doc_id == DOC_117_NEW]
    assert len(newest) == 7
    assert sorted(r.body["pointer"]["filters"]["section"] for r in by_table["drawbridge_bridges"]
                  if r.doc_id == DOC_117_NEW) == ["117.1081", "117.821", "117.901"]


def test_table_record_descriptions_are_the_template(units_store_with_tables):
    store = units_store_with_tables
    contracts = load_contracts(corpus="gov")
    recs = phase3_records(store.path, store, overlay_of(store), "gov")
    for r in recs:
        p = r.body["pointer"]
        source = build_mod_source(store, r.doc_id)
        assert r.body["description"] == DESCRIPTION.format(
            table=p["table"], description=contracts[p["table"]].description.rstrip("."),
            n=r.body["row_count"], source=source)
        assert r.body["caption"] == contracts[p["table"]].description
    bridges = next(r for r in recs if r.canonical_ref ==
                   "tables:drawbridge_bridges:section=117.821,version=2026-06-26")
    assert bridges.body["description"] == (
        "Rows of drawbridge_bridges: 33 CFR 117 draws: one row per section, eCFR version and "
        "draw, 2 rows from 33 CFR 117 as of 2026-06-26")
    fr = next(r for r in recs if r.body["pointer"]["table"] == "fr_documents")
    assert fr.body["description"].endswith("1 rows from Federal Register document "
                                           + store.source(fr.doc_id).source_version)
    docs = document_tables(store, overlay_of(store), "gov")
    assert docs and all(d.body["description"] == DOC_DESCRIPTION.format(
        k=int(d.canonical_ref.rsplit(" ", 1)[1]), where=d.canonical_ref.rsplit(" table ", 1)[0],
        n=d.body["row_count"], columns=", ".join(d.body["headers"])) for d in docs)


def build_mod_source(store, doc_id: str) -> str:
    src = store.source(doc_id)
    if src.uri.startswith("https://www.ecfr.gov/"):
        return f"33 CFR 117 as of {src.source_version}"
    if src.uri.startswith("https://www.federalregister.gov/"):
        return f"Federal Register document {src.source_version}"
    return src.uri


def test_irm_tables_are_located_in_their_sections(units_store):
    recs = document_tables(units_store, overlay_of(units_store), "gov")
    irm = [r for r in recs if r.doc_id == DOC_IRM]
    assert [r.canonical_ref for r in irm] == ["IRM 21.4.1.3 table 1", "IRM 21.4.1.3.1 table 1",
                                              "IRM 21.4.1.3.2 table 1"]
    text = units_store.text(DOC_IRM)
    first = irm[0].body
    assert first["headers"] == ["Acronym", "Definition"] and first["row_count"] == 3
    assert first["caption"] == "IRM 21.4.1.3 Refund Inquiry Research"   # no title: the section
    p = first["pointer"]
    assert (p["kind"], p["doc_id"], p["tables_id"], p["table"], p["filters"]) == (
        "span", DOC_IRM, None, None, None)
    span = text[p["start"]:p["end"]]
    assert span.startswith("Acronym | Definition") and span.endswith("Refund Inquiry Unit")
    assert irm[1].body["headers"] == ["If", "Then"] and irm[1].body["row_count"] == 2
    assert text[irm[2].body["pointer"]["start"]:irm[2].body["pointer"]["end"]].endswith(
        "will be issued within six weeks.")
    for r in irm:
        assert validate_unit(CONTRACTS["table_record"], r) == []
        ref, = r.source_refs
        assert (ref.start, ref.end) == (r.body["pointer"]["start"], r.body["pointer"]["end"])


ECFR_TABLES = """<?xml version="1.0" encoding="UTF-8"?>
<DIV5 N="165" TYPE="PART">
<HEAD>PART 165&#8212;REGULATED NAVIGATION AREAS</HEAD>
<DIV6 N="C" TYPE="SUBPART">
<HEAD>Subpart C&#8212;Safety Zones</HEAD>
<DIV8 N="165.151" TYPE="SECTION">
<HEAD>&#xA7; 165.151 Safety zones; fireworks displays.</HEAD>
<P>(a) The following areas are safety zones:</P>
<DIV><TABLE>
<CAPTION><P class="title">Table 1 to &#xA7; 165.151</P></CAPTION>
<THEAD><TR><TH>Event</TH><TH>Date</TH></TR></THEAD>
<TBODY>
<TR><TD>Bluefish Fireworks</TD><TD>April</TD></TR>
<TR><TD> </TD><TD>Time: to be determined.</TD></TR>
</TBODY>
</TABLE></DIV>
<P>(b) Vessels shall keep 100 yards from the launch site.</P>
<DIV><TABLE>
<THEAD><TR><TH>Latitude</TH><TH>Longitude</TH></TR></THEAD>
<TBODY><TR><TD>42&#xB0;21&#x2032; N</TD><TD>71&#xB0;02&#x2032; W</TD></TR></TBODY>
</TABLE></DIV>
</DIV8>
</DIV6>
<DIV9 N="Index" TYPE="APPENDIX">
<HEAD>Index</HEAD>
<DIV><TABLE>
<TR><TD>Term</TD><TD>Section</TD></TR>
<TR><TD>Fireworks</TD><TD>165.151</TD></TR>
</TABLE></DIV>
</DIV9>
</DIV5>
"""

MD_TABLES = """# Pricing sheet

Source: google_drive

## Tiers

| Tier | Price |
|---|---|
| Hosted | 10 |
| Dedicated | 20 |

|-> [warm pool] not a table
|-> [reserved pool]

| Region | Latency |
| :--- | ---: |
| eu | 80 |
"""


def test_ecfr_and_markdown_tables(tmp_path):
    from adr_eval.corpora.gov import ecfr_url

    ecfr = _doc(ECFR_TABLES.encode(), "xml", "2026-06-30", ecfr_url(33, "165", "2026-06-30"))
    md = bench_md("tables", MD_TABLES, 93)
    store = make_units_store(tmp_path / "s", [ecfr, md])
    gov = document_tables(store, overlay_of(store), "gov")
    assert [r.canonical_ref for r in gov] == ["33 CFR 165, Index table 1",
                                              "33 CFR 165.151 table 1", "33 CFR 165.151 table 2"]
    index = gov.pop(0)        # a table outside every section: an appendix
    assert (index.body["caption"], index.body["headers"], index.body["row_count"]) == (
        "Index", ["Term", "Section"], 1)
    assert index.heading_path == ["33 CFR 165", "Index", "Table 1"]
    text = store.text(ecfr[0].doc_id)
    one, two = (r.body for r in gov)
    assert one["caption"] == "Table 1 to § 165.151" and one["headers"] == ["Event", "Date"]
    assert one["row_count"] == 2
    assert text[one["pointer"]["start"]:one["pointer"]["end"]] == (
        "Table 1 to § 165.151\nEvent\nDate\nBluefish Fireworks\nApril\nTime: to be determined.")
    assert two["caption"] == "§ 165.151 Safety zones; fireworks displays."  # the section heading
    assert two["headers"] == ["Latitude", "Longitude"] and two["row_count"] == 1
    assert gov[0].heading_path == ["33 CFR 165", "Subpart C",
                                   "§ 165.151 Safety zones; fireworks displays.", "Table 1"]
    bench = document_tables(store, overlay_of(store), "bench")
    assert [r.canonical_ref for r in bench] == [f"bench:{md[0].doc_id} table 1",
                                                f"bench:{md[0].doc_id} table 2"]
    mtext = store.text(md[0].doc_id)
    a, b = (r.body for r in bench)
    assert (a["caption"], a["headers"], a["row_count"]) == ("Tiers", ["Tier", "Price"], 2)
    assert mtext[a["pointer"]["start"]:a["pointer"]["end"]].startswith("| Tier | Price |")
    assert (b["headers"], b["row_count"]) == (["Region", "Latency"], 1)
    assert b["description"] == DOC_DESCRIPTION.format(k=2, where="Pricing sheet", n=1,
                                                      columns="Region, Latency")
    for r in [index, *gov, *bench]:
        assert validate_unit(CONTRACTS["table_record"], r) == []
    itext = text[index.body["pointer"]["start"]:index.body["pointer"]["end"]]
    assert itext == "Term\nSection\nFireworks\n165.151"


# -- versions --------------------------------------------------------------------------------------

def test_link_versions_pairs_a_repeated_ref_by_occurrence_order(units_store):
    """Two paragraphs with the same canonical ref in one version (repeated markers): the k-th
    in document order is succeeded by the k-th in the successor (Task 2 carry)."""
    ov = overlay_of(units_store)

    def unit(doc: str, para: str, ref: str = "33 CFR 117.821(z)"):
        start = units_store.text(doc).index(para)
        return make_unit(type_="rule_card", title=ref, heading_path=[ref], canonical_ref=ref,
                         text=para, doc_id=doc, spans=[(start, start + len(para),
                                                        "rule_card.text@1")],
                         body=uf.rule_body(doc), store=units_store, overlay=ov, corpus="gov")

    c = "(c) The Main Street drawbridge, mile 3.4, is operated by the Smithfield Department"
    d = "(d) The Main Street drawbridge, mile 3.4, has a vertical clearance"
    old_c, old_d = unit(DOC_117_OLD, c), unit(DOC_117_OLD, d)
    new_c, new_d = unit(DOC_117_NEW, c), unit(DOC_117_NEW, d)
    # given in an order that is neither document nor unit-id order
    out = {u.unit_id: u for u in link_versions([new_d, old_d, new_c, old_c], ov)}
    assert out[old_c.unit_id].applicability.superseded_by == new_c.unit_id
    assert out[old_d.unit_id].applicability.superseded_by == new_d.unit_id
    assert out[new_c.unit_id].applicability.supersedes == old_c.unit_id
    assert out[new_d.unit_id].applicability.supersedes == old_d.unit_id
    # a second occurrence with no counterpart in the successor links nothing
    lone = {u.unit_id: u for u in link_versions([old_c, old_d, new_c], ov)}
    assert lone[old_d.unit_id].applicability.superseded_by is None
    assert lone[old_c.unit_id].applicability.superseded_by == new_c.unit_id


# -- the build -------------------------------------------------------------------------------------

def test_build_is_byte_identical_in_two_copies(tmp_path):
    a = build_units(make_units_store(tmp_path / "a").path, "gov")
    b = build_units(make_units_store(tmp_path / "b").path, "gov")
    assert a.units_id == b.units_id and [f.sha256 for f in a.files] == [f.sha256 for f in b.files]
    assert a.manifest_path.read_bytes() == b.manifest_path.read_bytes()
    for f in a.files:
        report = a.manifest_path.parent / f.file.replace(".jsonl", ".report.json")
        assert report.read_bytes() == (b.manifest_path.parent / report.name).read_bytes()


def test_build_writes_every_type_of_the_corpus_and_never_moves_head(units_store):
    ov = overlay_of(units_store)
    for corpus in ("gov", "research", "bench"):
        res = build_units(units_store.path, corpus)
        m = load_units_manifest(units_store.path, res.units_id)
        assert tuple(f.type for f in m.units) == CORPUS_TYPES[corpus]
        assert (m.corpus, m.snapshot, m.tables_id, m.applicability, m.passes) == (
            corpus, units_store.snapshot_id, None, ov.overlay_id, {})
        assert res.manifest_path.name == f"units-{res.units_id[:16]}.json"
        assert set(res.reports) == set(CORPUS_TYPES[corpus])
        assert read_units_head(units_store.path) is None
    assert CORPUS_TYPES == {"gov": ("concept", "procedure", "rule_card", "table_record"),
                            "research": ("concept", "table_record"),
                            "bench": ("concept", "faq", "procedure", "table_record")}
    bench = build_units(units_store.path, "bench")
    counts = {f.type: f.units for f in bench.files}
    assert counts["faq"] == 3 and counts["procedure"] == 1 and counts["table_record"] == 0
    gov = build_units(units_store.path, "gov")
    assert {f.type: f.units for f in gov.files}["table_record"] == 3     # the IRM tables


def test_rule_cards_carry_closure_defined_terms_and_versions(built_units):
    store, gov, _ = built_units
    m = load_units_manifest(store.path, gov.units_id)
    assert m.tables_id == read_head(store.path)
    cards = {(u.doc_id, u.canonical_ref): u for u in load_units(store.path, m, "rule_card")}
    concepts = {u.unit_id: u for u in load_units(store.path, m, "concept")}
    general = cards[(DOC_117_NEW, "33 CFR 117.5(p1)")]
    defines = [e for e in general.body["closure"] if e["relation"] == "defines"]
    assert general.body["defined_terms"] == [e["unit_id"] for e in defines]
    assert [concepts[i].body["pref_label"] for i in general.body["defined_terms"]] == [
        "Drawbridge"]
    window = cards[(DOC_117_NEW, "33 CFR 117.821(a)")]
    relations = [e["relation"] for e in window.body["closure"]]
    assert "exception_of" in relations and "context" in relations
    old = cards[(DOC_117_OLD, "33 CFR 117.821(a)")]
    assert old.applicability.status == "superseded"
    assert old.applicability.superseded_by == window.unit_id
    assert window.applicability.supersedes == old.unit_id
    for c in cards.values():
        assert c.body["defined_terms"] == [e["unit_id"] for e in c.body["closure"]
                                           if e["relation"] == "defines"]
    report = gov.reports["rule_card"]
    provs = [p for d in ecfr_docs(store) for p in provisions(store, d)]
    assert report["duplicate_provision_ids"] == duplicate_provision_ids(provs)
    assert report["cards"] == len(cards) and "unresolved" in report


def test_build_records_the_tables_id_and_table_records(built_units):
    store, gov, bench = built_units
    m = load_units_manifest(store.path, gov.units_id)
    recs = load_units(store.path, m, "table_record")
    phase3 = [r for r in recs if r.body["pointer"]["kind"] == "tables"]
    assert phase3 and all(r.tables_id == m.tables_id == read_head(store.path) for r in phase3)
    assert gov.reports["table_record"]["phase3"]["drawbridge_bridges"] >= 3
    assert load_units_manifest(store.path, bench.units_id).tables_id is None


def walk(value, path=""):
    if isinstance(value, dict):
        yield path, value
        for k, v in value.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from walk(v, f"{path}[{i}]")


def check_units(store, units) -> int:
    """T3 and T4 over `units`: exactly one document, the envelope and lineage, and every
    stored span inside its document and re-slicing to the text stored with it. Returns the
    number of spans checked."""
    contracts = load_unit_contracts()
    texts: dict[str, str] = {}
    docs = set(store.doc_ids())
    checked = 0
    for u in units:
        assert u.doc_id in docs
        text = texts.setdefault(u.doc_id, store.text(u.doc_id))
        assert u.source_refs and {r.doc_id for r in u.source_refs} == {u.doc_id}
        assert u.applicability.status in ("validated", "superseded")
        assert u.contract == f"{u.type}@{contracts[u.type].version}"
        assert u.lineage.compiler == COMPILER_VERSION
        assert validate_unit(contracts[u.type], u) == [], u.unit_id
        for r in u.source_refs:
            assert 0 <= r.start <= r.end <= len(text)
            checked += 1
        if u.type == "rule_card":
            r = u.source_refs[0]
            assert text[r.start:r.end] == u.body["text"]
        for where, d in walk(u.body):
            span = d.get("span")
            if isinstance(span, list):
                assert 0 <= span[0] <= span[1] <= len(text), (u.unit_id, where)
                checked += 1
                for key in ("text", "raw"):
                    if isinstance(d.get(key), str) and not where.endswith("pointer"):
                        assert text[span[0]:span[1]] == d[key], (u.unit_id, where)
            if "doc_id" in d and d.get("doc_id") is not None:
                assert d["doc_id"] == u.doc_id, (u.unit_id, where)
        p = u.body.get("pointer")
        if p is not None and p["kind"] == "span":
            assert p["doc_id"] == u.doc_id and 0 <= p["start"] <= p["end"] <= len(text)
            checked += 1
    return checked


def test_every_unit_has_one_doc_and_its_spans_reslice(built_units):               # T3, T4
    store, gov, bench = built_units
    for res in (gov, bench):
        m = load_units_manifest(store.path, res.units_id)
        units = load_units(store.path, m)
        assert len(units) == sum(f.units for f in m.units) > 0
        assert check_units(store, units) > len(units)
        assert all(f.rejected == 0 for f in m.units)


def test_per_file_reports_are_write_once_and_hold_no_run_counters(units_store):
    a = build_units(units_store.path, "bench")
    files = sorted(a.manifest_path.parent.glob("*.report.json"))
    before = {p.name: p.read_bytes() for p in files}
    b = build_units(units_store.path, "bench")
    assert b.units_id == a.units_id
    assert {p.name: p.read_bytes() for p in files} == before
    for data in before.values():
        assert not re.search(rb'"(calls|cached|made|elapsed|seconds|wall)"', data)


def test_a_span_that_does_not_reslice_is_rejected(units_store, monkeypatch):
    real = build_mod.faq_units

    def tampered(store, overlay, corpus="bench"):
        units = real(store, overlay, corpus)
        u = units[0]
        body = {**u.body, "question": {**u.body["question"], "text": "Something else?"}}
        return [u.model_copy(update={"body": body}), *units[1:]]

    monkeypatch.setattr(build_mod, "faq_units", tampered)
    res = build_units(units_store.path, "bench")
    faq = next(f for f in res.files if f.type == "faq")
    assert (faq.units, faq.rejected) == (2, 1)
    rejected, = res.reports["faq"]["rejected"]
    assert rejected["problems"] == ["body.question: span does not re-slice"]


def test_build_never_calls_a_model(monkeypatch, tmp_path):
    from adr_eval import llm, runner

    def no_cli(*a, **kw):
        raise AssertionError("the model CLI must never run in a test")

    monkeypatch.setattr(llm, "_run_subprocess", no_cli)
    monkeypatch.setattr(runner, "profile_status", lambda profile: None)   # CI has no model CLI

    def no_client(*a, **kw):
        raise AssertionError("a metadata build makes no model client")

    monkeypatch.setattr(build_mod.ex, "metered_client", no_client)        # C9
    store = make_units_store(tmp_path / "s")
    for corpus in ("gov", "research", "bench"):
        assert build_units(store.path, corpus).units_id
    # a client is made only when a model pass is asked for
    with pytest.raises(AssertionError, match="no model client"):
        build_units(store.path, "bench", passes=("procedure",))
    with pytest.raises(ValueError, match="unknown model pass"):
        build_units(store.path, "bench", passes=("summaries",))
    with pytest.raises(NotImplementedError, match="procedure"):
        build_units(store.path, "bench", passes=("procedure",), client=object())


def test_unknown_corpus_is_refused(units_store):
    with pytest.raises(ValueError, match="corpus"):
        build_units(units_store.path, "tools")


# -- the units merge gate --------------------------------------------------------------------------

CASES = [UnitCase("c1", "rule", {"ref": "33 CFR 117.5(p1)"}),
         UnitCase("c2", "rule", {"ref": "33 CFR 117.821(a)"}),
         UnitCase("c3", "procedure", {"ref": "IRM 21.4.1.3.1"})]


def fixture_hit(store_path: Path, units_id: str, case: UnitCase) -> bool:
    """A case is a hit when the build holds a unit of its kind with its canonical ref."""
    m = load_units_manifest(store_path, units_id)
    type_ = "rule_card" if case.kind == "rule" else "procedure"
    return case.payload["ref"] in {u.canonical_ref for u in load_units(store_path, m, type_)}


def derived(store_path: Path, units_id: str, drop_ref: str) -> str:
    """A candidate equal to `units_id` without the rule cards of `drop_ref`."""
    m = load_units_manifest(store_path, units_id)
    kept = [u for u in load_units(store_path, m, "rule_card") if u.canonical_ref != drop_ref]
    new = write_units(store_path, m.snapshot, CONTRACTS["rule_card"], kept, {})
    files = [new if f.type == "rule_card" else f for f in m.units]
    return write_units_manifest(store_path, m.model_copy(update={"units": files}))[0]


def test_first_promotion_without_head_needs_no_cases(tmp_path):
    store = make_units_store(tmp_path / "s")
    cand = build_units(store.path, "gov").units_id
    r = units_gate(store.path, cand, [], 0, hit=fixture_hit)
    assert (r.promoted, r.candidate, r.current, r.flips, r.gains, r.n) == (
        True, cand, None, [], [], 0)
    assert read_units_head(store.path) == cand
    assert (store.path / UNITS_DIR / "HEAD").read_text() == f"{cand}\n"


def test_gate_refuses_too_many_flips_and_keeps_head(tmp_path):                        # T6
    store = make_units_store(tmp_path / "s")
    first = build_units(store.path, "gov").units_id
    assert units_gate(store.path, first, [], 0, hit=fixture_hit).promoted
    worse = derived(store.path, first, "33 CFR 117.821(a)")
    before = read_units_head(store.path)
    r = units_gate(store.path, worse, CASES, 0, hit=fixture_hit)
    assert not r.promoted and r.flips == ["c2"] and read_units_head(store.path) == before
    assert (r.current, r.gains, r.n) == (first, [], 3)
    # one flip allowed: promoted, and the gain of a better candidate is reported
    r = units_gate(store.path, worse, CASES, 1, hit=fixture_hit)
    assert r.promoted and read_units_head(store.path) == worse
    r = units_gate(store.path, first, CASES, 0, hit=fixture_hit)
    assert r.promoted and r.gains == ["c2"] and read_units_head(store.path) == first


def test_gate_with_head_refuses_an_empty_case_list(tmp_path):
    store = make_units_store(tmp_path / "s")
    first = build_units(store.path, "gov").units_id
    assert units_gate(store.path, first, [], 0, hit=fixture_hit).promoted
    other = build_units(store.path, "bench").units_id
    with pytest.raises(UnitsError, match="empty"):
        units_gate(store.path, other, [], 5, hit=fixture_hit)
    assert read_units_head(store.path) == first


def test_gate_refusals(tmp_path):
    store = make_units_store(tmp_path / "s")
    cand = build_units(store.path, "gov").units_id
    with pytest.raises(ValueError, match="negative"):
        units_gate(store.path, cand, [], -1, hit=fixture_hit)
    with pytest.raises(ValueError, match="distinct"):
        units_gate(store.path, cand, [CASES[0], CASES[0]], 0, hit=fixture_hit)
    with pytest.raises(UnitsError):
        units_gate(store.path, "0" * 64, [], 0, hit=fixture_hit)
    # a HEAD that names a build that does not load blocks the gate (no silent first promotion)
    (store.path / UNITS_DIR / "HEAD").write_text("f" * 64 + "\n")
    with pytest.raises(UnitsError, match="does not load"):
        units_gate(store.path, cand, [], 0, hit=fixture_hit)
    assert (store.path / UNITS_DIR / "HEAD").read_text() == "f" * 64 + "\n"


def test_only_the_gate_moves_units_head():
    src = Path(__file__).parents[2] / "src"
    movers = {p.relative_to(src).as_posix() for p in src.rglob("*.py")
              if "_set_units_head(" in p.read_text(encoding="utf-8")}
    assert movers == {"adr_store/units/overlay.py", "adr_store/units/gate.py"}


def test_unit_reports_are_readable(units_store):
    res = build_units(units_store.path, "bench")
    reports = build_mod.unit_reports(units_store.path, res.units_id)
    assert set(reports) == set(CORPUS_TYPES["bench"])
    assert reports["faq"] == res.reports["faq"]
    assert json.loads(json.dumps(reports)) == reports
