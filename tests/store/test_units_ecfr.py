"""eCFR provisions, rule cards, cross-references and citation closure (Phase 4 spec §4.1, §6.1,
§8, P3, P4, P8, P31; preflight rulings C1, C14). Fixture stores under `tmp_path`; nothing reads
`data/` or `.cache/`."""

import pytest

from adr_eval.corpora.gov import ecfr_url
from adr_store.units import ecfr
from adr_store.units.closure import (
    CITES_PER_REF,
    CLOSURE_PATH,
    CONTEXT_MAX,
    RELATIONS,
    ClosureEntry,
    closure,
    closure_census,
    draw_keys,
    load_structural_rules,
)
from adr_store.units.contracts import load_unit_contracts, validate_unit
from adr_store.units.ecfr import (
    PARTS,
    Provision,
    cross_refs,
    ecfr_docs,
    marker_path,
    modality,
    normalise_rule_id,
    provisions,
    rule_cards,
)
from tests.store import units_fixtures as uf
from tests.store.tables_fixtures import ECFR_NEW, _doc
from tests.store.units_fixtures import (
    D1,
    D2,
    DOC_117_NEW,
    DOC_117_OLD,
    DOC_165,
    overlay_of,
    sample_unit,
)

units_store = uf.units_store


# -- helpers ---------------------------------------------------------------------------------

def run_markers(texts: list[str]) -> list[tuple[str, ...]]:
    """The marker path of each paragraph of `texts`, read in order from an empty path."""
    paths, prev = [], ()
    for t in texts:
        prev = marker_path(prev, t)
        paths.append(prev)
    return paths


def all_cards(store) -> tuple[list, list[Provision]]:
    cards, provs = [], []
    for d in ecfr_docs(store):
        c, p = rule_cards(store, d, overlay_of(store))
        cards += c
        provs += p
    return cards, provs


def closure_of(store) -> dict[str, list[ClosureEntry]]:
    cards, provs = all_cards(store)
    return closure(cards, provs)


def provision_of(provs: list[Provision], card) -> Provision:
    r = card.source_refs[0]
    return next(p for p in provs if (p.doc_id, p.start, p.end) == (card.doc_id, r.start, r.end))


def subpart_b_cards(store) -> list:
    cards, provs = all_cards(store)
    return [c for c in cards
            if (p := provision_of(provs, c)).part == "33 CFR 117" and p.subpart == "B"]


def card_of(cards, doc_id: str, ref: str):
    return next(c for c in cards if c.doc_id == doc_id and c.canonical_ref == ref)


def synthetic(text: str, section: str = "117.901", part: str = "33 CFR 117") -> Provision:
    """A provision of `section` holding `text`, starting at offset 100 of its document."""
    mod, spans = modality(text)
    return Provision(doc_id=D1, part=part, section=section, subpart="B",
                     heading=f"§ {section} Harbor River.", path=("c",),
                     provision_id=f"{part.split(' CFR ')[0]} CFR {section}(c)", start=100,
                     end=100 + len(text), text=text, modality=mod,
                     modal_spans=tuple((100 + a, 100 + b, ph) for a, b, ph in spans))


def sections_of(store, doc_id: str) -> set[str]:
    return {p.section for p in provisions(store, doc_id)}


# -- modality ----------------------------------------------------------------------------------

@pytest.mark.parametrize("text,mod", [
    ("The draw shall open on signal.", "obligation"),
    ("The draw need not be opened from 7 a.m. to 9 a.m.", "exemption"),
    ("No vessel may anchor in the zone.", "prohibition"),
    ("The owner shall not operate the draw; it need not open.", "prohibition"),   # leftmost-longest
    ("The bridge is at mile 3.4.", None),
])
def test_modality(text, mod):
    assert modality(text)[0] == mod


def test_modal_spans_hold_every_match_word_bounded():
    text = "Vessels MUST signal. The draw shall not open; it need not, and anchoring is prohibited."
    mod, spans = modality(text)
    assert mod == "obligation"
    assert [ph for _, _, ph in spans] == ["must", "shall not", "need not", "is prohibited"]
    for a, b, ph in spans:
        assert text[a:b].lower() == ph
    # word-bounded: "marshall", "mustard" and "shallow" hold no modal word
    assert modality("The marshall put mustard on a shallow plate.") == (None, [])


def test_provision_modal_spans_are_document_offsets(units_store):
    text = units_store.text(DOC_117_NEW)
    provs = provisions(units_store, DOC_117_NEW)
    assert sum(bool(p.modal_spans) for p in provs) == 14
    for p in provs:
        assert text[p.start:p.end] == p.text
        assert bool(p.modal_spans) == (p.modality is not None)
        for a, b, ph in p.modal_spans:
            assert p.start <= a < b <= p.end
            assert text[a:b].lower() == ph


# -- marker paths and provisions ---------------------------------------------------------------

def test_marker_paths_track_levels_and_roman_ambiguity():
    paths = run_markers(["(a) A", "(1) B", "(i) C", "(ii) D", "(2) E", "(h) F", "(i) G", "text"])
    assert paths == [("a",), ("a", "1"), ("a", "1", "i"), ("a", "1", "ii"), ("a", "2"),
                     ("h",), ("i",), ("i", "p1")]


def test_marker_paths_multiple_markers_unmarked_ordinals_and_level_four():
    paths = run_markers(["intro", "more", "(a)(1) A", "(i) B", "(A) C", "(B) D", "text",
                         "text", "(2) E", "(v) F", "(b) G", "(c) H", "(v) I"])
    assert paths == [("p1",), ("p2",), ("a", "1"), ("a", "1", "i"), ("a", "1", "i", "A"),
                     ("a", "1", "i", "B"), ("a", "1", "i", "B", "p1"),
                     ("a", "1", "i", "B", "p2"), ("a", "2"), ("a", "2", "v"), ("b",), ("c",),
                     ("v",)]
    # "(x)" at level 1 is a letter; at level 2 it is roman unless it follows "(w)"
    assert run_markers(["(w) A", "(x) B"]) == [("w",), ("x",)]
    assert run_markers(["(w) A", "(1) B", "(x) C"]) == [("w",), ("w", "1"), ("x",)]
    assert run_markers(["(a) A", "(1) B", "(x) C"]) == [("a",), ("a", "1"), ("a", "1", "x")]
    # a parenthesis that is no marker leaves the paragraph unmarked
    assert run_markers(["(a) A", "(Approved by OMB) B"]) == [("a",), ("a", "p1")]


def test_marker_paths_italic_levels_and_roman_lookahead():
    # "(i)" right after "(h)" is a letter, unless the next paragraph starts "(ii)"
    assert marker_path(("h", "1"), "(i) A") == ("i",)
    assert marker_path(("h", "1"), "(i) A", following="(ii) B") == ("h", "1", "i")
    assert marker_path(("h",), "(i) A", following="(ii) B") == ("h", "i")
    assert marker_path(("h",), "(i) A", following="(j) B") == ("i",)
    assert marker_path(("u",), "(v) A", following="(vi) B") == ("u", "v")
    # italic markers are levels 5 and 6: "(<I>1</I>)" under "(C)"
    path = ("e", "3", "iv", "C")
    path = marker_path(path, "(1) X", italic=True)
    assert path == ("e", "3", "iv", "C", "1")
    path = marker_path(path, "(i) X", italic=True)
    assert path == ("e", "3", "iv", "C", "1", "i")
    assert marker_path(path, "(2) Y", italic=True) == ("e", "3", "iv", "C", "2")
    path = marker_path(path, "(D) Y")
    assert path == ("e", "3", "iv", "D")
    assert marker_path(marker_path(path, "(1) Z", italic=True), "(4) W") == ("e", "4")


LEVELS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<DIV5 N="73" TYPE="PART">
<HEAD>PART 73&#8212;RADIO BROADCAST SERVICES</HEAD>
<DIV8 N="73.682" TYPE="SECTION">
<HEAD>&#xA7; 73.682 TV transmission standards.</HEAD>
<P>(h) <I>Sharing.</I></P>
<P>(1) A sharing agreement shall include provisions on:</P>
<P>(i) Access to facilities;</P>
<P>(ii) Allocation of bandwidth.</P>
<P>(i) <I>Checks.</I></P>
<P>(1) A station shall check:</P>
<P>(A) Its own equipment;</P>
<P>(<I>1</I>) Once a year;</P>
<P>(<I>2</I>) After a complaint.</P>
<P>(B) Its programming.</P>
<P>(2) A station must keep records.</P>
</DIV8>
</DIV5>
"""


def test_provision_ids_follow_italic_markers_and_roman_lookahead(tmp_path):
    doc = _doc(LEVELS_XML, "xml", ECFR_NEW, ecfr_url(47, "73", ECFR_NEW))
    store = uf.make_units_store(tmp_path / "s", docs=[doc])
    (d,) = ecfr_docs(store)
    assert [p.provision_id for p in provisions(store, d)] == [
        "47 CFR 73.682(h)", "47 CFR 73.682(h)(1)", "47 CFR 73.682(h)(1)(i)",
        "47 CFR 73.682(h)(1)(ii)", "47 CFR 73.682(i)", "47 CFR 73.682(i)(1)",
        "47 CFR 73.682(i)(1)(A)", "47 CFR 73.682(i)(1)(A)(1)",
        "47 CFR 73.682(i)(1)(A)(2)", "47 CFR 73.682(i)(1)(B)", "47 CFR 73.682(i)(2)"]


def test_117_5_is_one_unmarked_paragraph_and_its_card_is_p1(units_store):
    cards, provs = rule_cards(units_store, DOC_117_NEW, overlay_of(units_store))
    in_5 = [p for p in provs if p.section == "117.5"]
    assert [p.provision_id for p in in_5] == ["33 CFR 117.5(p1)"]
    assert card_of(cards, DOC_117_NEW, "33 CFR 117.5(p1)").body["modality"] == "obligation"
    assert [p.provision_id for p in provs if p.section == "117.4"] == [
        "33 CFR 117.4(p1)", "33 CFR 117.4(p2)", "33 CFR 117.4(p3)"]


def test_provisions_carry_section_subpart_heading_and_path(units_store):
    provs = provisions(units_store, DOC_117_NEW)
    by_id = {p.provision_id: p for p in provs}
    p = by_id["33 CFR 117.821(a)"]
    assert (p.doc_id, p.part, p.section, p.subpart, p.heading, p.path) == (
        DOC_117_NEW, "33 CFR 117", "117.821", "B", "§ 117.821 Smith River.", ("a",))
    assert p.modality == "exemption"
    assert by_id["33 CFR 117.31(b)(4)"].subpart == "A"
    assert by_id["33 CFR 117.31(b)(4)"].modality is None
    assert [q.provision_id for q in provs if q.section == "117.1081"] == [
        "33 CFR 117.1081(a)", "33 CFR 117.1081(a)(1)", "33 CFR 117.1081(a)(2)",
        "33 CFR 117.1081(b)", "33 CFR 117.1081(c)"]
    assert len(provs) == 24 and len({q.provision_id for q in provs}) == 24
    assert [q.start for q in provs] == sorted(q.start for q in provs)
    assert {q.part for q in provisions(units_store, DOC_165)} == {"33 CFR 165"}
    assert {q.provision_id for q in provisions(units_store, DOC_165)} >= {
        "33 CFR 165.5(p1)", "33 CFR 165.13(b)", "33 CFR 165.T01(c)"}


def test_ecfr_docs_are_every_version_of_the_three_parts(units_store):
    assert PARTS == ("ecfr:33:117", "ecfr:33:165", "ecfr:47:73")
    assert ecfr_docs(units_store) == [DOC_117_OLD, DOC_117_NEW, DOC_165]


def test_a_paragraph_that_cannot_be_located_is_rejected(units_store, monkeypatch):
    real = ecfr.extract_text

    def mangled(data, fmt):
        out = real(data, fmt)
        if data.startswith(b"<P") and b"vertical clearance" in data:
            return out.replace("12 feet", "twelve feet")
        return out

    monkeypatch.setattr(ecfr, "extract_text", mangled)
    misses: list = []
    provs = provisions(units_store, DOC_117_NEW, misses)
    assert "33 CFR 117.821(d)" not in {p.provision_id for p in provs}
    assert len(provs) == 23
    assert misses == [("117.821", "33 CFR 117.821(d)")]
    text = units_store.text(DOC_117_NEW)
    assert all(text[p.start:p.end] == p.text for p in provs)


# -- rule cards --------------------------------------------------------------------------------

def test_one_card_per_modal_paragraph_per_version_and_spans_reslice(units_store):
    for d in ecfr_docs(units_store):
        cards, provs = rule_cards(units_store, d, overlay_of(units_store))
        assert {c.body["provision_id"] for c in cards} == \
            {p.provision_id for p in provs if p.modality}
        for c in cards:
            r = c.source_refs[0]
            assert units_store.text(d)[r.start:r.end] == c.body["text"]


def test_rule_cards_are_valid_units_with_unextracted_model_fields(units_store):
    contract = load_unit_contracts()["rule_card"]
    cards, _ = all_cards(units_store)
    assert len(cards) == 14 + 14 + 3
    not_extracted = {"value": None, "quotes": [], "status": None, "null_reason": "not_extracted"}
    for c in cards:
        assert validate_unit(contract, c) == []
        assert c.type == "rule_card" and c.canonical_ref == c.body["provision_id"]
        assert c.unit_id.startswith(f"rule_card/{c.canonical_ref}/")
        for f in ("subject", "conditions", "thresholds", "exceptions"):
            assert c.body[f] == not_extracted
        assert c.body["closure"] == [] and c.body["bindings"] == []
        assert c.body["defined_terms"] == []
        text = units_store.text(c.doc_id)
        for m in c.body["modal_spans"]:
            a, b = m["span"]
            assert text[a:b].lower() == m["phrase"]
        for x in c.body["cross_refs"]:
            a, b = x["span"]
            assert text[a:b] == x["raw"]
    old = card_of(cards, DOC_117_OLD, "33 CFR 117.821(b)")
    new = card_of(cards, DOC_117_NEW, "33 CFR 117.821(b)")
    assert old.version != new.version and old.applicability.status == "superseded"
    same_old = card_of(cards, DOC_117_OLD, "33 CFR 117.821(a)")
    same_new = card_of(cards, DOC_117_NEW, "33 CFR 117.821(a)")
    assert same_old.version == same_new.version and same_old.unit_id != same_new.unit_id


def test_card_cross_refs_name_card_targets(units_store):
    cards, _ = rule_cards(units_store, DOC_117_NEW, overlay_of(units_store))
    c = card_of(cards, DOC_117_NEW, "33 CFR 117.901(c)")
    (x,) = c.body["cross_refs"]
    b = card_of(cards, DOC_117_NEW, "33 CFR 117.901(b)")
    assert (x["raw"], x["target_ref"], x["resolution"], x["target_unit"]) == (
        "paragraph (b) of this section", "33 CFR 117.901(b)", "resolved", b.unit_id)
    d = card_of(cards, DOC_117_NEW, "33 CFR 117.1081(a)(1)")
    # a section target is no card (its card is 33 CFR 117.5(p1)), so target_unit is null
    assert [(x["target_ref"], x["target_unit"]) for x in d.body["cross_refs"]] == [
        ("33 CFR 117.5", None), ("33 CFR 117.31", None)]


# -- cross-references --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,target,res", [
    ("§ 117.5", "33 CFR 117.5", "resolved"),
    ("paragraph (b) of this section", "33 CFR 117.901(b)", "resolved"),
    ("33 CFR part 165", "33 CFR part 165", "external"),
    ("§ 117.999", "33 CFR 117.999", "dangling"),
])
def test_cross_references(units_store, raw, target, res):
    p = synthetic(f"The owner shall act as required by {raw} at all times.")
    (x,) = cross_refs(p, sections_of(units_store, DOC_117_NEW))
    assert (x.raw, x.target_ref, x.resolution) == (raw, target, res)
    assert p.text[x.start - p.start:x.end - p.start] == raw


@pytest.mark.parametrize("raw,targets", [
    ("§ 117.31(b)", [("33 CFR 117.31(b)", "resolved")]),
    ("§ 117.31 (b)(1)", [("33 CFR 117.31(b)(1)", "resolved")]),
    ("33 CFR 117.5", [("33 CFR 117.5", "resolved")]),
    ("33 CFR § 117.40(a)", [("33 CFR 117.40(a)", "resolved")]),
    ("33 CFR 165.13", [("33 CFR 165.13", "external")]),
    ("§ 1.05-1 of this chapter", [("33 CFR 1.05-1", "external")]),
    ("33 CFR part 117", [("33 CFR part 117", "resolved")]),
    ("paragraph (b)(1) of this section", [("33 CFR 117.901(b)(1)", "resolved")]),
    ("paragraphs (a) and (c) of this section", [("33 CFR 117.901(a)", "resolved"),
                                                ("33 CFR 117.901(c)", "resolved")]),
    ("paragraphs (b)(1), (2), or (3) of this section", [
        ("33 CFR 117.901(b)(1)", "resolved"), ("33 CFR 117.901(b)(2)", "resolved"),
        ("33 CFR 117.901(b)(3)", "resolved")]),
    ("§§ 117.4, 117.40, and 117.999", [("33 CFR 117.4", "resolved"),
                                       ("33 CFR 117.40", "resolved"),
                                       ("33 CFR 117.999", "dangling")]),
    ("§ 165.766-165.768", [("33 CFR 165.766", "external")]),
    ("§§ 117.4-117", [("33 CFR 117.4", "resolved")]),
    ("§ 165.T01-0149.", [("33 CFR 165.T01-0149", "external")]),
    ("§ 1.05-1.", [("33 CFR 1.05-1", "external")]),
    ("§ 117.162T", [("33 CFR 117.162T", "dangling")]),
    ("the paragraph above", []),
])
def test_cross_reference_forms(units_store, raw, targets):
    p = synthetic(f"The owner shall act as required by {raw}; then stop.")
    refs = cross_refs(p, sections_of(units_store, DOC_117_NEW))
    assert [(x.target_ref, x.resolution) for x in refs] == targets
    for x in refs:
        assert p.text[x.start - p.start:x.end - p.start] == x.raw
    assert [x.start for x in refs] == sorted(x.start for x in refs)


def test_section_sign_refs_take_the_provisions_title():
    p = synthetic("A station shall comply with § 73.1212, § 1.1307 and §§ 73.3587-3589.",
                  section="73.1201", part="47 CFR 73")
    refs = cross_refs(p, {"73.1201", "73.1212", "73.3587"})
    assert [(x.raw, x.target_ref, x.resolution) for x in refs] == [
        ("§ 73.1212", "47 CFR 73.1212", "resolved"), ("§ 1.1307", "47 CFR 1.1307", "external"),
        ("§§ 73.3587", "47 CFR 73.3587", "resolved")]


def test_double_section_sign_gives_two_references(units_store):
    provs = provisions(units_store, DOC_117_NEW)
    p = next(q for q in provs if q.provision_id == "33 CFR 117.1081(a)(1)")
    refs = cross_refs(p, {q.section for q in provs})
    assert [(x.raw, x.target_ref, x.resolution) for x in refs] == [
        ("§§ 117.5", "33 CFR 117.5", "resolved"), ("117.31", "33 CFR 117.31", "resolved")]
    text = units_store.text(DOC_117_NEW)
    assert [text[x.start:x.end] for x in refs] == ["§§ 117.5", "117.31"]


@pytest.mark.parametrize("raw", ["§117.1081(a)(2)", "33 CFR 117.1081 (a)(2)", "117.1081(a)(2)",
                                 "33 C.F.R. § 117.1081(a)(2)"])
def test_normalise_rule_id(raw):
    assert normalise_rule_id(raw) == "33 CFR 117.1081(a)(2)"
    assert normalise_rule_id("117.") is None


@pytest.mark.parametrize("raw,want", [
    ("165.T01(c)", "33 CFR 165.T01(c)"),
    ("73.3526(e)(1)", "47 CFR 73.3526(e)(1)"),
    (" 33 CFR 117.5(p1) ", "33 CFR 117.5(p1)"),
    ("47 CFR § 73.1201", "47 CFR 73.1201"),
    ("1.05", None),
    ("33 CFR part 117", None),
    ("see 117.5", None),
    ("", None),
])
def test_normalise_rule_id_titles_and_refusals(raw, want):
    assert normalise_rule_id(raw) == want


# -- closure -----------------------------------------------------------------------------------

def test_structural_rule_is_committed():
    assert CLOSURE_PATH.name == "closure.json"
    assert load_structural_rules() == [
        {"part": "33 CFR 117", "subpart": "B", "targets": ["33 CFR 117.5", "33 CFR 117.31(b)"]}]
    assert RELATIONS == ("cites", "defines", "exception_of", "context")
    assert (CITES_PER_REF, CONTEXT_MAX) == (5, 3)


def test_draw_keys():
    assert draw_keys("The Main Street drawbridge, mile 3.4, and the bridge at Mile 12.") == \
        frozenset({"mile 3.4", "mile 12"})
    assert draw_keys("No bridge here; smiles 4.") == frozenset()


def test_subpart_b_cards_are_exceptions_of_117_5_and_117_31b(units_store):
    cl = closure_of(units_store)
    cards = subpart_b_cards(units_store)
    assert len(cards) == 2 * 10
    for c in cards:
        entries = [e for e in cl[c.unit_id] if e.relation == "exception_of"]
        # C14: the targets are reached as their cards, so § 117.5 is its card 33 CFR 117.5(p1)
        assert {e.ref for e in entries} == {"33 CFR 117.5(p1)", "33 CFR 117.31(b)"}
        assert all(e.unit_id is not None and e.doc_id == c.doc_id for e in entries)
    # subpart A cards get no exception_of
    all_c, _ = all_cards(units_store)
    a = card_of(all_c, DOC_117_NEW, "33 CFR 117.40(a)")
    assert not [e for e in cl[a.unit_id] if e.relation == "exception_of"]


def test_closure_order_and_context_by_mile_key(units_store):
    cards, provs = all_cards(units_store)
    cl = closure(cards, provs)
    text = units_store.text(DOC_117_NEW)
    order = {r: i for i, r in enumerate(RELATIONS)}
    for c in cards:
        ranks = [order[e.relation] for e in cl[c.unit_id]]
        assert ranks == sorted(ranks)
        for e in cl[c.unit_id]:
            assert e.doc_id == c.doc_id
            assert units_store.text(e.doc_id)[e.span[0]:e.span[1]] == next(
                p.text for p in provs if (p.doc_id, p.start, p.end) == (e.doc_id, *e.span))
    c = card_of(cards, DOC_117_NEW, "33 CFR 117.821(a)")
    context = [e for e in cl[c.unit_id] if e.relation == "context"]
    assert [e.ref for e in context] == ["33 CFR 117.821(c)", "33 CFR 117.821(d)"]
    for e in context:
        assert e.unit_id is None
        assert "mile 3.4" in draw_keys(text[e.span[0]:e.span[1]])
    # (b) is at mile 5.1: no non-modal paragraph shares its key
    b = card_of(cards, DOC_117_NEW, "33 CFR 117.821(b)")
    assert not [e for e in cl[b.unit_id] if e.relation == "context"]
    # cites: § 117.5 gives its card; § 117.31 gives what is at or under it, capped, a
    # non-modal provision with unit_id None and its span
    d = card_of(cards, DOC_117_NEW, "33 CFR 117.1081(a)(1)")
    cites = [e for e in cl[d.unit_id] if e.relation == "cites"]
    assert [e.ref for e in cites] == [
        "33 CFR 117.5(p1)", "33 CFR 117.31(a)", "33 CFR 117.31(b)", "33 CFR 117.31(b)(1)",
        "33 CFR 117.31(b)(2)", "33 CFR 117.31(b)(3)"]
    assert len([e for e in cites if e.ref.startswith("33 CFR 117.31")]) == CITES_PER_REF
    assert cites[0].unit_id == card_of(cards, DOC_117_NEW, "33 CFR 117.5(p1)").unit_id
    assert cites[3].unit_id is None
    one_b_1 = next(p for p in provs if p.doc_id == DOC_117_NEW
                   and p.provision_id == "33 CFR 117.31(b)(1)")
    assert cites[3].span == (one_b_1.start, one_b_1.end)
    # the same target under another relation is kept; within a relation it is not repeated
    assert [e.ref for e in cl[d.unit_id] if e.relation == "exception_of"] == [
        "33 CFR 117.5(p1)", "33 CFR 117.31(b)"]
    for c in cards:
        keys = [(e.relation, e.doc_id, e.span) for e in cl[c.unit_id]]
        assert len(keys) == len(set(keys))
        assert c.unit_id not in {e.unit_id for e in cl[c.unit_id]}
    # a dangling or external reference reaches nothing
    e1081c = card_of(cards, DOC_117_NEW, "33 CFR 117.1081(c)")
    assert not [e for e in cl[e1081c.unit_id] if e.relation == "cites"]
    # closure stays in the card's document: the old version's card reaches old provisions
    old = card_of(cards, DOC_117_OLD, "33 CFR 117.1081(a)(1)")
    assert {e.doc_id for e in cl[old.unit_id]} == {DOC_117_OLD}


def test_closure_entries_dump_to_the_contract_shape(units_store):
    cl = closure_of(units_store)
    e = next(e for es in cl.values() for e in es if e.unit_id is None)
    assert e.model_dump(mode="json") == {"relation": e.relation, "ref": e.ref, "unit_id": None,
                                         "doc_id": e.doc_id, "span": list(e.span)}
    cards, _ = all_cards(units_store)
    contract = load_unit_contracts()["rule_card"]
    for c in cards:
        body = {**c.body, "closure": [x.model_dump(mode="json") for x in cl[c.unit_id]]}
        assert validate_unit(contract, c.model_copy(update={"body": body})) == []


NEAREST_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<DIV5 N="73" TYPE="PART">
<HEAD>PART 73&#8212;RADIO BROADCAST SERVICES</HEAD>
<DIV6 N="H" TYPE="SUBPART">
<HEAD>Subpart H&#8212;Rules Applicable to All Broadcast Stations</HEAD>
<DIV8 N="73.1201" TYPE="SECTION">
<HEAD>&#xA7; 73.1201 Station identification.</HEAD>
<P>(a) <I>When regularly required.</I> Broadcast station identification announcements are
made at the beginning and ending of each time of operation.</P>
<P>(b) <I>Content.</I> Official station identification consists of the call letters.</P>
<P>(c) <I>Channel.</I> The channel number appears in the announcement.</P>
<P>(d) <I>Duty.</I> Each licensee shall make station identification announcements hourly.</P>
<P>(e) <I>Format.</I> The announcement is visual or aural.</P>
<P>(f) <I>Language.</I> The announcement is in English or the language of the program.</P>
<P>(g) <I>Records.</I> A record of announcements is kept with the station log.</P>
</DIV8>
</DIV6>
</DIV5>
"""


def test_context_outside_117_is_the_nearest_non_modal_provisions(tmp_path):
    doc = _doc(NEAREST_XML, "xml", ECFR_NEW, ecfr_url(47, "73", ECFR_NEW))
    store = uf.make_units_store(tmp_path / "s", docs=[doc])
    (d,) = ecfr_docs(store)
    cards, provs = rule_cards(store, d, overlay_of(store))
    assert [c.canonical_ref for c in cards] == ["47 CFR 73.1201(d)"]
    assert cards[0].governance.owner == "Federal Communications Commission"
    cl = closure(cards, provs)
    context = [e for e in cl[cards[0].unit_id] if e.relation == "context"]
    # (c) and (e) are nearest, then (b) before (f) at equal distance; listed in document order
    assert [e.ref for e in context] == ["47 CFR 73.1201(b)", "47 CFR 73.1201(c)",
                                        "47 CFR 73.1201(e)"]
    assert len(context) == CONTEXT_MAX


def test_closure_census_lists_unresolved_in_part_references(units_store):
    cards, _ = all_cards(units_store)
    census = closure_census(cards)
    # per version: 117.901(c) -> (b); 117.1081(a)(1) -> 117.5, 117.31; 117.1081(c) -> 117.999
    assert census["in_part"] == 2 * 4
    assert census["resolution"] == {"resolved": 2 * 3, "dangling": 2 * 1, "external": 2 * 1}
    assert census["resolved_rate"] == 0.75
    assert census["unresolved"] == sorted(census["unresolved"],
                                          key=lambda u: (u["unit_id"], u["span"]))
    assert [(u["canonical_ref"], u["raw"], u["target_ref"], u["reason"])
            for u in census["unresolved"]] == [
        ("33 CFR 117.1081(c)", "§ 117.999", "33 CFR 117.999",
         "section 117.999 is not in this version")] * 2
    assert {u["doc_id"] for u in census["unresolved"]} == {DOC_117_OLD, DOC_117_NEW}
    assert closure_census([]) == {"cards": 0, "in_part": 0, "resolution": {
        "resolved": 0, "dangling": 0, "external": 0}, "resolved_rate": None, "unresolved": []}


# -- the validator keeps closure in the card's document (P5, P31) -------------------------------

def test_validator_refuses_closure_entries_of_another_document():
    contract = load_unit_contracts()["rule_card"]
    assert validate_unit(contract, sample_unit()) == []
    body = {**uf.SAMPLE_BODIES["rule_card"]}
    body["closure"] = [{**body["closure"][0]}, {**body["closure"][1], "doc_id": D2}]
    problems = validate_unit(contract, sample_unit(body=body, doc_id=D1))
    assert problems == [f"body.closure[1].doc_id: {D2[:12]}… is not the unit's document "
                        f"{D1[:12]}…"]
