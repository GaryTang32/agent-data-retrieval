"""Concepts from definition statements, IRM acronym tables and long forms, and concept linking
(Phase 4 spec §5.3, §7, §8.3 `defines`, P9, P31; preflight ruling C1, note N18). Fixture stores
under `tmp_path`; nothing reads `data/` or `.cache/`."""

import pytest

from adr_eval.corpora.gov import ecfr_url
from adr_store.tables.parse import base_key
from adr_store.units.closure import RELATIONS, ClosureEntry, closure
from adr_store.units.concepts import (
    DEFINING,
    Definition,
    concepts,
    ecfr_definitions,
    hidden_labels,
    irm_acronyms,
    link_concepts,
    long_forms,
    scope_contains,
)
from adr_store.units.contracts import load_unit_contracts, validate_unit
from adr_store.units.ecfr import rule_cards
from tests.store import units_fixtures as uf
from tests.store.tables_fixtures import ECFR_NEW, _doc
from tests.store.units_fixtures import (
    DOC_117_NEW,
    DOC_117_OLD,
    DOC_165,
    DOC_FAQ,
    DOC_IRM,
    overlay_of,
)

units_store = uf.units_store


# -- helpers ---------------------------------------------------------------------------------

def gov_concepts(store):
    return concepts(store, "gov", overlay_of(store))


def senses(store, term_key: str, doc_id: str = DOC_165):
    """The concept units of `term_key` in `doc_id`, broadest scope first."""
    rank = {"part": 0, "subpart": 1, "section": 2, "paragraph": 3, "document": -1}
    found = [u for u in gov_concepts(store)
             if u.doc_id == doc_id and u.canonical_ref.endswith(":" + term_key)]
    return sorted(found, key=lambda u: rank[u.body["scope"]["kind"]])


def cards_and_closures(store, docs=(DOC_117_NEW, DOC_165)):
    cards, provs = [], []
    for d in docs:
        c, p = rule_cards(store, d, overlay_of(store))
        cards += c
        provs += p
    return cards, provs, closure(cards, provs)


def card(cards, ref: str, doc_id: str):
    (c,) = [c for c in cards if c.canonical_ref == ref and c.doc_id == doc_id]
    return c


SCOPES_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<DIV5 N="165" TYPE="PART">
<HEAD>PART 165&#8212;REGULATED NAVIGATION AREAS</HEAD>
<DIV6 N="C" TYPE="SUBPART">
<HEAD>Subpart C&#8212;Safety Zones</HEAD>
<DIV8 N="165.20" TYPE="SECTION">
<HEAD>&#xA7; 165.20 Safety zones.</HEAD>
<P>For the purposes of this subpart, a <I>safety zone</I> means a closed water area.</P>
<P>(a) Vessels shall not enter a safety zone.</P>
</DIV8>
<DIV8 N="165.21" TYPE="SECTION">
<HEAD>&#xA7; 165.21 Escorts.</HEAD>
<P>(a) <I>Definitions.</I> For the purposes of this paragraph (a):</P>
<P>(1) <I>Escort vessel</I> means a vessel assigned to accompany another.</P>
<P>(2) "Escorted vessel" refers to the one led and "escort zone" shall mean the water.</P>
<P>(b) An escort vessel shall keep the safety zone clear.</P>
<P>(c) <I>Master</I> includes a person in charge of a vessel.</P>
<P>(d) The term <I>pilot</I> means a licensed pilot.</P>
<P>(e) <I>Escort vessel</I> means any Coast Guard vessel.</P>
<P>(f) <I>Escort vessel</I> means any Coast Guard vessel on patrol.</P>
<P>(g) The term <I>vessel</I>, as used in this section, means any watercraft.</P>
</DIV8>
</DIV6>
</DIV5>
"""


def scopes_store(tmp_path):
    doc = _doc(SCOPES_XML, "xml", ECFR_NEW, ecfr_url(33, "165", ECFR_NEW))
    store = uf.make_units_store(tmp_path / "scopes", docs=[doc])
    return store, doc[0].doc_id


# -- eCFR definition statements --------------------------------------------------------------

def test_ecfr_definition_statement_and_scope(units_store):
    ds = {(d.term_key, d.scope_ref) for d in ecfr_definitions(units_store, DOC_165)}
    assert ("designated representative", "33 CFR 165.T01") in ds   # section-scoped boilerplate
    assert ("designated representative", "33 CFR part 165") in ds  # "For the purposes of this part"


def test_ecfr_definitions_on_the_165_fixture_in_full(units_store):
    full = units_store.text(DOC_165)
    ds = ecfr_definitions(units_store, DOC_165)
    assert [(d.term, d.term_key, d.scope_kind, d.scope_ref, d.alt_labels) for d in ds] == [
        ("Designated representative", "designated representative", "part", "33 CFR part 165",
         ()),
        ("Regulated navigation area", "regulated navigation area", "part", "33 CFR part 165",
         ("RNA",)),
        ("designated representative", "designated representative", "section",
         "33 CFR 165.T01", ())]
    for d in ds:
        assert d.doc_id == DOC_165 and full[d.start:d.end] == d.text
    # the definition runs from the term through the end of its paragraph
    assert ds[1].text.startswith("Regulated navigation area (RNA) means a water area")
    assert ds[1].text.endswith("established under this part.")
    assert ds[2].text.startswith("designated representative means a Coast Guard Patrol")


def test_117_4_definitions_take_the_part(units_store):
    assert {d.scope_ref for d in ecfr_definitions(units_store, DOC_117_NEW)} == {"33 CFR part 117"}
    assert {d.scope_kind for d in ecfr_definitions(units_store, DOC_117_NEW)} == {"part"}
    assert [d.term_key for d in ecfr_definitions(units_store, DOC_117_NEW)] == [
        "drawbridge", "drawtender"]


def test_curly_quoted_and_italic_terms_with_trailing_punctuation(units_store):
    # “Drawtender,” means … (older version) and <I>Drawtender.</I> means … (newest) both give
    # term_key "drawtender" and the term without its punctuation
    for doc, opening in ((DOC_117_OLD, "“Drawtender,” means the person"),
                         (DOC_117_NEW, "Drawtender. means the person")):
        (d,) = [d for d in ecfr_definitions(units_store, doc) if d.term_key == "drawtender"]
        assert (d.term, d.term_key) == ("Drawtender", "drawtender")
        assert d.text == opening + " who operates a drawbridge."
        assert units_store.text(doc)[d.start:d.end] == d.text
    (u_old,) = [u for u in gov_concepts(units_store) if u.doc_id == DOC_117_OLD
                and u.canonical_ref == "concept:33 CFR part 117:drawtender"]
    assert u_old.body["pref_label"] == "Drawtender"


def test_scope_words_subpart_paragraph_lead_in_and_defining_phrases(tmp_path):
    store, doc = scopes_store(tmp_path)
    got = [(d.term, d.scope_kind, d.scope_ref) for d in ecfr_definitions(store, doc)]
    assert got == [
        ("safety zone", "subpart", "33 CFR part 165, subpart C"),      # words in its paragraph
        ("Escort vessel", "paragraph", "33 CFR 165.21(a)"),            # the ancestor's words
        ("Escorted vessel", "paragraph", "33 CFR 165.21(a)"),          # "refers to"
        ("escort zone", "paragraph", "33 CFR 165.21(a)"),              # "shall mean"
        ("Master", "section", "33 CFR 165.21"),                        # "includes"; no words
        ("pilot", "section", "33 CFR 165.21"),                         # italic, then "means"
        ("Escort vessel", "section", "33 CFR 165.21"),
        ("Escort vessel", "section", "33 CFR 165.21")]
    two =[d for d in ecfr_definitions(store, doc) if d.term in ("Escorted vessel",
                                                                  "escort zone")]
    # a definition runs through the next defined term of its paragraph
    assert two[0].text == '"Escorted vessel" refers to the one led'
    assert two[1].text == '"escort zone" shall mean the water.'
    assert set(DEFINING) == {"means", "includes", "is defined", "refers to", "shall mean"}


# -- concept units ---------------------------------------------------------------------------

def test_concept_units_are_valid_one_per_term_scope_and_document(units_store):
    contracts = load_unit_contracts()
    units = gov_concepts(units_store)
    assert [u.unit_id for u in units] == sorted(u.unit_id for u in units)
    assert len({u.unit_id for u in units}) == len(units)
    for u in units:
        assert validate_unit(contracts[u.type], u) == [], u.unit_id
        b = u.body
        assert u.canonical_ref == f"concept:{b['scope']['ref']}:{base_key(b['pref_label'])}"
        assert u.title == b["pref_label"]
        start, end = b["definition"]["span"]
        assert units_store.text(u.doc_id)[start:end] == b["definition"]["text"]
        assert (u.source_refs[0].start, u.source_refs[0].end) == (start, end)
        assert u.source_refs[0].spec_id == "concept.definition@1"
        assert b["related"] == [] and b["exact_match"] == []
    keys = sorted((u.doc_id, u.canonical_ref) for u in units)
    assert len(keys) == len(set(keys))
    # each 117 version has its own units (P31): drawbridge and drawtender per version
    for doc in (DOC_117_OLD, DOC_117_NEW):
        assert sorted(u.canonical_ref for u in units if u.doc_id == doc) == [
            "concept:33 CFR part 117:drawbridge", "concept:33 CFR part 117:drawtender"]
    (rna,) = [u for u in units if u.canonical_ref.endswith(":regulated navigation area")]
    assert rna.body["pref_label"] == "Regulated navigation area"
    assert rna.body["alt_labels"] == ["RNA"]
    assert {"rna", "rnas", "regulated navigation area", "regulated navigation areas",
            "regulated-navigation-area"} <= set(rna.body["hidden_labels"])
    assert rna.applicability.status == "validated"
    assert rna.governance.owner == "Coast Guard" and rna.governance.authority_tier == 1
    old = [u for u in units if u.doc_id == DOC_117_OLD]
    assert {u.applicability.status for u in old} == {"superseded"}


def test_repeated_definitions_in_one_scope_make_one_concept(tmp_path):
    store, doc = scopes_store(tmp_path)
    units = concepts(store, "gov", overlay_of(store))
    escort = [u for u in units if u.canonical_ref.endswith(":escort vessel")]
    by_scope = {u.body["scope"]["ref"]: u for u in escort}
    assert sorted(by_scope) == ["33 CFR 165.21", "33 CFR 165.21(a)"]
    sec = by_scope["33 CFR 165.21"]
    # (e) and (f) define it twice in the section: one unit, the first definition, both spans
    assert sec.body["definition"]["text"] == "Escort vessel means any Coast Guard vessel."
    assert len(sec.source_refs) == 2
    full = store.text(doc)
    assert [full[r.start:r.end] for r in sec.source_refs] == [
        "Escort vessel means any Coast Guard vessel.",
        "Escort vessel means any Coast Guard vessel on patrol."]


def test_part_sense_is_broader_than_section_redefinition(units_store):
    part, sec = senses(units_store, "designated representative")
    assert sec.unit_id in part.body["narrower"] and part.unit_id in sec.body["broader"]
    assert part.body["broader"] == [] and sec.body["narrower"] == []
    # a term defined in one scope only has neither
    (rna,) = senses(units_store, "regulated navigation area")
    assert rna.body["broader"] == rna.body["narrower"] == []


def test_broader_links_the_nearest_enclosing_sense_only(tmp_path):
    store, _ = scopes_store(tmp_path)
    units = concepts(store, "gov", overlay_of(store))
    escort = {u.body["scope"]["kind"]: u for u in units
              if u.canonical_ref.endswith(":escort vessel")}
    assert escort["paragraph"].body["broader"] == [escort["section"].unit_id]
    assert escort["section"].body["narrower"] == [escort["paragraph"].unit_id]
    # senses of different terms are never linked
    (zone,) = [u for u in units if u.canonical_ref.endswith(":safety zone")]
    assert zone.body["broader"] == zone.body["narrower"] == []


# -- IRM acronym tables ----------------------------------------------------------------------

def test_irm_acronym_rows_become_concepts(units_store):
    full = units_store.text(DOC_IRM)
    ds = irm_acronyms(units_store, DOC_IRM)
    assert [(d.term, d.alt_labels, d.scope_kind, d.scope_ref) for d in ds] == [
        ("Direct Deposit Indicator Account", ("DDIA",), "document", "IRM 21.4.1"),
        ("Routing Transit Number", ("RTN",), "document", "IRM 21.4.1"),
        ("Refund Inquiry Unit", ("RIU",), "document", "IRM 21.4.1")]
    for d in ds:
        assert full[d.start:d.end] == d.text and d.text.startswith(d.alt_labels[0])
        assert d.term in d.text and d.term_key == base_key(d.term)
    units = [u for u in gov_concepts(units_store) if u.doc_id == DOC_IRM]
    (rtn,) = [u for u in units if u.body["alt_labels"] == ["RTN"]]
    assert rtn.body["pref_label"] == "Routing Transit Number"             # expansion
    assert rtn.canonical_ref == "concept:IRM 21.4.1:routing transit number"
    assert {"rtn", "rtns", "routing transit number"} <= set(rtn.body["hidden_labels"])
    assert rtn.heading_path == ["IRM 21.4.1", "21.4.1.3 Refund Inquiry Research",
                                "Routing Transit Number"]
    assert rtn.governance.owner == "Internal Revenue Service"
    assert len(units) == 3


IRM_TABLES = b"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>5.19.1</title></head>
<body><div class="col-md-8"><div class="section" id="s1">
<h2 class="title">5.19.1 Balance Due</h2>
<p>(1) This section covers balance due accounts and the work of each unit in detail.</p>
<div class="section" id="s2">
<div class="sectioninfo"><strong>5.19.1.1.6 (12-26-2017)</strong></div>
<div class="titlepage"><div><div><h4 class="title">Acronyms</h4></div></div></div>
<div class="informaltable"><table class="table">
<thead><tr><th>ABBREVIATIONS</th><th>DEFINITION</th></tr></thead>
<tbody>
<tr><td>ACS</td><td>Automated Collection System: Allows taxpayers to resolve tax debts.</td></tr>
<tr><td>AAB</td><td>Aggregate Assessed Balance (CC SUMRY)
<p>Reminder: consider projected balances.</p></td></tr>
<tr><td>ZZZ</td><td>A row the text does not hold</td></tr>
</tbody></table></div>
<p>(1) Use these acronyms when you read the account transcripts of a balance due case.</p>
</div>
<div class="section" id="s3">
<div class="sectioninfo"><strong>5.19.1.2 (12-26-2017)</strong></div>
<div class="titlepage"><div><div><h4 class="title">Contacts</h4></div></div></div>
<div class="informaltable"><table class="table">
<thead><tr><th>Name</th><th>Phone</th></tr></thead>
<tbody><tr><td>ACS</td><td>800-829-0922</td></tr></tbody></table></div>
<p>(1) Call the number above when the taxpayer asks to talk to a collection employee.</p>
</div>
</div></div></body></html>
"""


def test_irm_acronym_tables_by_section_title_or_header(tmp_path, monkeypatch):
    doc = _doc(IRM_TABLES, "html", "2026-02-03", "https://www.irs.gov/irm/part5/irm_05-019-001r")
    store = uf.make_units_store(tmp_path / "irm", docs=[doc])
    d = doc[0].doc_id
    full = store.text(d)
    assert "| ZZZ |" in full
    # the extractor keeps every row here; drop one from the text to see it left out
    full = full.replace("| ZZZ | A row the text does not hold | \n", "")
    monkeypatch.setattr(type(store), "text", lambda self, doc_id: full)
    ds = irm_acronyms(store, d)
    # a table under an "Acronyms" section title counts whatever its header ("ABBREVIATIONS");
    # the expansion is its first line, cut at ": "; a row the text lacks is left out; the
    # "Name | Phone" table of another section is not an acronyms table
    assert [(x.term, x.alt_labels, x.scope_ref) for x in ds] == [
        ("Automated Collection System", ("ACS",), "IRM 5.19.1"),
        ("Aggregate Assessed Balance (CC SUMRY)", ("AAB",), "IRM 5.19.1")]
    for x in ds:
        assert full[x.start:x.end] == x.text
    assert ds[0].text.startswith("ACS") and "Allows taxpayers" in ds[0].text


# -- long forms and labels ---------------------------------------------------------------------

@pytest.mark.parametrize("text,found", [
    ("a Regulated Navigation Area (RNA) is", [("Regulated Navigation Area", "RNA")]),
    ("Retrieval-Augmented Generation (RAG)", [("Retrieval-Augmented Generation", "RAG")]),
    ("Department of Homeland Security (DHS)", [("Department of Homeland Security", "DHS")]),
    ("the big model (GPT)", []),
])
def test_long_forms(text, found):
    assert [(a, b) for a, b, _, _ in long_forms(text)] == found


@pytest.mark.parametrize("text,found", [
    ("Bureau of the Fiscal Service (BFS) pays", [("Bureau of the Fiscal Service", "BFS")]),
    ("the Internet of Things (IoT) grows", [("Internet of Things", "IoT")]),
    ("large language models (LLMs) and", [("large language models", "LLMs")]),
    ("we use the state-of-the-art (SOTA) model", [("state-of-the-art", "SOTA")]),
    ("Natural Language Processing (NLP) and Information Retrieval (IR)",
     [("Natural Language Processing", "NLP"), ("Information Retrieval", "IR")]),
    ("services of Homeland (DHS)", []),                   # the initials must cover every letter
    ("the Department of Homeland Security, (DHS)", []),   # a comma ends the long form
    ("Homeland Security in (HS)", []),                    # the word before must be used
    ("see the table (A)", []),                            # one letter is no abbreviation
    ("Regulated\nNavigation Area (RNA)", [("Regulated\nNavigation Area", "RNA")]),
])
def test_long_form_rules(text, found):
    assert [(a, b) for a, b, _, _ in long_forms(text)] == found


def test_long_form_offsets_cover_the_statement():
    text = "We study Retrieval-Augmented Generation (RAG) here."
    ((long, abbr, start, end),) = long_forms(text)
    assert text[start:end] == "Retrieval-Augmented Generation (RAG)"
    assert text[start:start + len(long)] == long and abbr == "RAG"


def test_hidden_labels_cover_case_hyphen_space_plural():
    assert hidden_labels("Draw-bridge") == ["draw bridge", "draw bridges", "draw-bridge",
                                            "draw-bridges", "drawbridge", "drawbridges"]


def test_hidden_labels_of_words_acronyms_and_plurals():
    assert hidden_labels("Designated  Representative") == [
        "designated representative", "designated representatives",
        "designated-representative", "designated-representatives"]
    assert hidden_labels("RNA") == ["rna", "rnas"]
    assert hidden_labels("Vessels.") == ["vessels"]       # base key; no "vesselss"
    assert hidden_labels("") == []


# -- research and bench: long forms, scope the document --------------------------------------

BENCH_GLOSSARY = b"""# Platform glossary

Source: confluence

The Inference Gateway (IG) routes requests. A Service Level Objective (SLO) is a target.
The Inference Gateway (IG) again: one concept per term, scope and document.
"""


def test_research_and_bench_concepts_come_from_long_forms(tmp_path):
    doc = uf.bench_doc("faq", 2)
    glossary = _doc(BENCH_GLOSSARY, "md", doc[0].source_version,
                    doc[0].uri.replace("dsid_fixture_faq", "dsid_fixture_glossary"))
    store = uf.make_units_store(tmp_path / "bench", docs=[doc, glossary])
    g = glossary[0].doc_id
    units = concepts(store, "bench", overlay_of(store))
    assert [(u.doc_id, u.canonical_ref) for u in units] == sorted(
        [(g, f"concept:bench:{g}:inference gateway"),
         (g, f"concept:bench:{g}:service level objective")], key=lambda x: x)
    contracts = load_unit_contracts()
    for u in units:
        assert validate_unit(contracts[u.type], u) == []
        assert u.body["scope"] == {"kind": "document", "ref": f"bench:{g}"}
        assert u.governance.authority_tier == 2 and u.governance.owner == "confluence"
    (ig,) = [u for u in units if u.canonical_ref.endswith("inference gateway")]
    assert ig.body["pref_label"] == "Inference Gateway" and ig.body["alt_labels"] == ["IG"]
    assert ig.body["definition"]["text"] == "Inference Gateway (IG)"
    assert ig.heading_path == ["# Platform glossary", "Inference Gateway"]
    assert len(ig.source_refs) == 2                         # the second statement, merged
    assert DOC_FAQ != g and not [u for u in units if u.doc_id == doc[0].doc_id]
    # gov stores give no long-form concepts; research uses the same rule as bench
    assert [u.canonical_ref for u in concepts(store, "research", overlay_of(store))] == [
        u.canonical_ref.replace("concept:bench:", "concept:research:") for u in units]


# -- scopes --------------------------------------------------------------------------------

@pytest.mark.parametrize("scope,ref,inside", [
    ("33 CFR part 165", "33 CFR 165.13(b)", True),
    ("33 CFR part 165", "33 CFR 165.T01", True),
    ("33 CFR part 165", "33 CFR part 165", True),
    ("33 CFR part 165", "33 CFR part 165, subpart C", True),
    ("33 CFR part 165", "33 CFR 1651.2", False),
    ("33 CFR part 165", "47 CFR 165.2", False),
    ("33 CFR part 117", "33 CFR 117.4", True),
    ("33 CFR 117.4", "33 CFR 117.40(a)", False),
    ("33 CFR 117.4", "33 CFR 117.4(p2)", True),
    ("33 CFR 165.T01", "33 CFR 165.T01(c)", True),
    ("33 CFR 165.T01", "33 CFR 165.T01-0149(c)", False),
    ("33 CFR 165.T01(b)", "33 CFR 165.T01", False),
    ("33 CFR 165.21(a)", "33 CFR 165.21(a)(2)", True),
    ("33 CFR 165.21(a)", "33 CFR 165.21(b)", False),
    ("33 CFR part 165, subpart C", "33 CFR 165.21", False),       # the subpart is unknown
    ("IRM 21.4.1", "IRM 21.4.1.3.2", True),
    ("IRM 21.4.1", "IRM 21.4.10.1", False),
    ("bench:" + "a" * 64, "bench:" + "a" * 64, True),
    ("bench:" + "a" * 64, "bench:" + "b" * 64, False),
    ("33 CFR 165.T01", "rule_card/33 CFR 165.T01(c)/0123456789ab/0123456789abcdef", True),
])
def test_scope_contains(scope, ref, inside):
    assert scope_contains(scope, ref) is inside


def test_a_subpart_scope_contains_the_sections_of_its_subpart():
    assert scope_contains("33 CFR part 165, subpart C", "33 CFR 165.21(b)", subpart="C")
    assert not scope_contains("33 CFR part 165, subpart C", "33 CFR 165.21(b)", subpart="B")
    assert not scope_contains("33 CFR part 165, subpart C", "33 CFR part 165", subpart="C")


# -- concept linking -------------------------------------------------------------------------

def test_link_concepts_fills_defined_terms_and_defines(units_store):
    cards, provs, closures = cards_and_closures(units_store)
    units = gov_concepts(units_store)
    linked, cl = link_concepts(cards, units, closures)
    assert [c.unit_id for c in linked] == [c.unit_id for c in cards]
    by_ref = {(u.doc_id, u.canonical_ref): u.unit_id for u in units}
    rna = by_ref[(DOC_165, "concept:33 CFR part 165:regulated navigation area")]
    dr_part = by_ref[(DOC_165, "concept:33 CFR part 165:designated representative")]
    dr_sec = by_ref[(DOC_165, "concept:33 CFR 165.T01:designated representative")]
    drawbridge = by_ref[(DOC_117_NEW, "concept:33 CFR part 117:drawbridge")]
    drawtender = by_ref[(DOC_117_NEW, "concept:33 CFR part 117:drawtender")]

    def terms(ref, doc):
        return card(linked, ref, doc).body["defined_terms"]

    # labels in the paragraph (any case, plural) whose scope contains it, in order of first
    # mention, the narrowest scope first
    assert terms("33 CFR 165.13(a)", DOC_165) == [rna]
    assert terms("33 CFR 165.13(b)", DOC_165) == [rna, dr_part]
    assert terms("33 CFR 165.T01(c)", DOC_165) == [dr_sec, dr_part]
    assert terms("33 CFR 117.5(p1)", DOC_117_NEW) == [drawbridge]          # "drawbridges"
    assert terms("33 CFR 117.31(a)", DOC_117_NEW) == [drawtender]
    assert terms("33 CFR 117.40(a)", DOC_117_NEW) == [drawbridge, drawtender]
    assert terms("33 CFR 117.901(a)", DOC_117_NEW) == []
    # the old version's concepts never reach the newest version's cards
    assert not {u.unit_id for u in units if u.doc_id == DOC_117_OLD} & {
        t for c in linked for t in c.body["defined_terms"]}
    full = {d: units_store.text(d) for d in (DOC_117_NEW, DOC_165)}
    concept_of = {u.unit_id: u for u in units}
    for c in linked:
        entries = cl[c.unit_id]
        defines = [e for e in entries if e.relation == "defines"]
        assert [e.unit_id for e in defines] == c.body["defined_terms"]
        # relations stay in RELATIONS order: defines between cites and exception_of
        order = [RELATIONS.index(e.relation) for e in entries]
        assert order == sorted(order)
        for e in defines:
            u = concept_of[e.unit_id]
            assert e.doc_id == c.doc_id == u.doc_id and e.ref == u.canonical_ref
            assert list(e.span) == u.body["definition"]["span"]
            assert full[c.doc_id][e.span[0]:e.span[1]] == u.body["definition"]["text"]
        # nothing else moved
        assert [e for e in entries if e.relation != "defines"] == closures[c.unit_id]


def test_defines_sits_between_cites_and_exception_of(units_store):
    cards, _, _ = cards_and_closures(units_store, docs=(DOC_117_NEW,))
    # 117.31(b) names "drawtender"; give it one entry of each other relation
    entries = [ClosureEntry(relation="cites", ref="33 CFR 117.5(p1)", unit_id=None,
                            doc_id=DOC_117_NEW, span=(0, 1)),
               ClosureEntry(relation="exception_of", ref="33 CFR 117.5(p1)", unit_id=None,
                            doc_id=DOC_117_NEW, span=(0, 1)),
               ClosureEntry(relation="context", ref="33 CFR 117.5(p1)", unit_id=None,
                            doc_id=DOC_117_NEW, span=(0, 1))]
    b = card(cards, "33 CFR 117.31(b)", DOC_117_NEW)
    _, cl2 = link_concepts([b], gov_concepts(units_store), {b.unit_id: entries})
    assert [e.relation for e in cl2[b.unit_id]] == ["cites", "defines", "exception_of",
                                                    "context"]
    # linking twice replaces the defines entries instead of adding them again (dedup within
    # the relation; the same provision under two relations stays under both)
    _, cl3 = link_concepts([b], gov_concepts(units_store), cl2)
    assert cl3 == cl2


def test_closure_reads_concepts_and_agrees_with_link_concepts(units_store):
    cards, provs, closures = cards_and_closures(units_store)
    units = gov_concepts(units_store)
    _, linked = link_concepts(cards, units, closures)
    assert closure(cards, provs, units) == linked
    assert closure(cards, provs) == closures                    # no concepts, no defines
    assert any(e.relation == "defines" for es in linked.values() for e in es)


def test_linked_cards_validate_with_their_closure(units_store):
    contracts = load_unit_contracts()
    cards, provs, closures = cards_and_closures(units_store)
    linked, cl = link_concepts(cards, gov_concepts(units_store), closures)
    for c in linked:
        body = {**c.body, "closure": [e.model_dump(mode="json") for e in cl[c.unit_id]]}
        assert validate_unit(contracts["rule_card"], c.model_copy(update={"body": body})) == []
    # ids and hashes do not move: the body is not hashed
    for a, b in zip(cards, linked, strict=True):
        assert (a.unit_id, a.hashes) == (b.unit_id, b.hashes)


def test_a_concept_build_twice_is_identical(units_store):
    a = [u.model_dump(mode="json") for u in gov_concepts(units_store)]
    b = [u.model_dump(mode="json") for u in gov_concepts(units_store)]
    assert a == b and a


def test_definition_is_a_frozen_record():
    d = Definition(doc_id="1" * 64, term="Drawtender", term_key="drawtender",
                   text="Drawtender means the person.", start=0, end=28,
                   scope_kind="part", scope_ref="33 CFR part 117")
    assert d.alt_labels == ()
    with pytest.raises(AttributeError):
        d.term = "x"


LEAD_IN_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<DIV5 N="165" TYPE="PART">
<HEAD>PART 165&#8212;REGULATED NAVIGATION AREAS</HEAD>
<DIV6 N="A" TYPE="SUBPART">
<HEAD>Subpart A&#8212;General</HEAD>
<DIV8 N="165.3" TYPE="SECTION">
<HEAD>&#xA7; 165.3 Definitions.</HEAD>
<P>The following definitions apply to this part:</P>
<P><I>Credential</I> means any or all of the following:</P>
<P>(1) Merchant mariner's document.</P>
<P>(2) Merchant mariner credential.</P>
<P><I>Merchant mariner credential or MMC</I> means the credential issued by the Coast Guard.</P>
<P><I>Certain Dangerous Cargo</I> or (<I>CDC</I>) includes any of the following:</P>
<P><I>Reporting Unit</I> or (<I>(D9 CDCRU)</I>) means the office that collects reports.</P>
</DIV8>
<DIV8 N="165.30" TYPE="SECTION">
<HEAD>&#xA7; 165.30 Security zones.</HEAD>
<P>(a) <I>Credential</I> means a card issued by the Captain of the Port.</P>
<P>(b) No person may enter a security zone without a credential.</P>
</DIV8>
</DIV6>
</DIV5>
"""


def test_a_lead_in_scopes_the_section_and_or_forms_give_alternate_labels(tmp_path):
    doc = _doc(LEAD_IN_XML, "xml", ECFR_NEW, ecfr_url(33, "165", ECFR_NEW))
    store = uf.make_units_store(tmp_path / "lead", docs=[doc])
    d = doc[0].doc_id
    full = store.text(d)
    ds = ecfr_definitions(store, d)
    # "The following definitions apply to this part:" scopes every definition after it in
    # the section, also past the list items under "Credential"
    assert [(x.term, x.alt_labels, x.scope_ref) for x in ds] == [
        ("Credential", (), "33 CFR part 165"),
        ("Merchant mariner credential", ("MMC",), "33 CFR part 165"),
        ("Certain Dangerous Cargo", ("CDC",), "33 CFR part 165"),
        ("Reporting Unit", ("D9 CDCRU",), "33 CFR part 165"),
        ("Credential", (), "33 CFR 165.30")]
    for x in ds:
        assert full[x.start:x.end] == x.text
    assert ds[2].text == "Certain Dangerous Cargo or (CDC) includes any of the following:"
    assert ds[3].text.startswith("Reporting Unit or ((D9 CDCRU)) means the office")
    units = concepts(store, "gov", overlay_of(store))
    cred = {u.body["scope"]["kind"]: u for u in units if u.canonical_ref.endswith(":credential")}
    assert cred["section"].body["broader"] == [cred["part"].unit_id]
    assert cred["part"].body["narrower"] == [cred["section"].unit_id]
    # the card of 165.30(b) gets both senses, the section's first ("credential" lower-case)
    cards, provs = rule_cards(store, d, overlay_of(store))
    linked, _ = link_concepts(cards, units, closure(cards, provs))
    b = card(linked, "33 CFR 165.30(b)", d)
    assert b.body["defined_terms"] == [cred["section"].unit_id, cred["part"].unit_id]
