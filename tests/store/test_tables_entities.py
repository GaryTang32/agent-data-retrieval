"""Entity resolution, the eCFR sections of 33 CFR 117 and the waterway links (Phase 3 spec §6,
§4.3): normalisation keys, equal-key clusters, override files, per-view display names, entity
tables in the build manifest, and the report of linked drawbridge titles. Fixture stores under
`tmp_path`; nothing reads `data/` or `.cache/`."""

import hashlib
import json

import pytest

from adr_store.store import Store
from adr_store.tables import overlay as ov
from adr_store.tables.build import build_tables
from adr_store.tables.contracts import load_contracts, validate_row
from adr_store.tables.ecfr import (
    STATES,
    SectionUnit,
    chain_docs,
    ecfr_sections,
    heading_waterway_key,
    title_parts,
    waterway_links,
)
from adr_store.tables.entities import (
    ENTITY_DIR,
    ENTITY_TYPES,
    Overrides,
    display_names,
    entity_id,
    entity_report,
    entity_rows,
    load_overrides,
    normalise_key,
    resolve,
)
from adr_store.tables.loaders import fr_tables, papers_tables
from adr_store.tables.parse import author_key
from adr_store.tables.provenance import RowRecord, reslice
from tests.store.tables_fixtures import (
    ECFR_NEW,
    ECFR_OLD,
    FR_DOCS,
    MANIFEST,
    ecfr_doc,
    fr_doc,
    make_tables_store,
)

DRAW = "Drawbridge Operation Regulation; "


def row(doc: str, **values) -> RowRecord:
    return RowRecord(doc_id=doc, row=values, prov={})


# -- keys ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("etype,raw,key", [
    ("venues", "arXiv preprint", "arxiv"), ("venues", "arXiv preprint (2026)", "arxiv"),
    ("venues", "arXiv 2026", "arxiv"), ("licences", "CC BY 4.0", "cc-by-4.0"),
    ("licences", "CC-BY-4.0", "cc-by-4.0"), ("agencies", "COAST GUARD", "coast guard"),
    ("cfr_parts", "33 CFR 117", "33 cfr 117"), ("authors", "Ａnn  Lee,", "ann lee"),
    ("waterways", "The Alpha River", "alpha river"),
    # more of each rule
    ("venues", "NeurIPS 2023", "neurips"), ("venues", "  Nature. ", "nature"),
    ("licences", "cc_by sa 4.0", "cc-by-sa-4.0"), ("cfr_parts", "33 CFR 0117", "33 cfr 117"),
    ("cfr_parts", "33 CFR 117a", "33 cfr 117a"), ("cfr_parts", " 47  cfr 73 ", "47 cfr 73"),
    ("dockets", "MB 17-105", "mb 17-105"), ("dockets", "USCG-2024-0001.", "uscg-2024-0001"),
    ("waterways", "Gulf  Intracoastal Waterway", "gulf intracoastal waterway"),
    ("waterways", "Theodore Roosevelt Lake", "theodore roosevelt lake"),
])
def test_normalise_key(etype, raw, key):
    assert normalise_key(etype, raw) == key


def test_the_authors_key_is_the_one_the_paper_authors_table_stores():
    assert author_key("Ａnn  Lee,") == normalise_key("authors", "Ａnn  Lee,") == "ann lee"


def test_an_unknown_entity_type_is_refused():
    with pytest.raises(ValueError, match="entity type"):
        normalise_key("planets", "Mars")


def test_entity_id_is_the_sha256_of_the_key():
    assert entity_id("arxiv") == hashlib.sha256(b"arxiv").hexdigest()


def test_the_committed_override_files_exist_and_start_empty():
    assert ENTITY_TYPES == ("agencies", "cfr_parts", "dockets", "venues", "licences",
                            "waterways", "authors")
    for etype in ENTITY_TYPES:
        text = (ENTITY_DIR / f"{etype}.json").read_text(encoding="utf-8")
        assert json.loads(text) == {"merge": [], "split": {}}
        assert load_overrides(etype) == Overrides()


# -- clusters and overrides ----------------------------------------------------------------------

def test_only_equal_keys_merge():
    assert len(set(resolve("agencies", ["A B", "A-B", "AB"], Overrides()).values())) == 3
    keys = resolve("agencies", ["COAST GUARD", "Coast Guard", " coast  guard."], Overrides())
    assert set(keys.values()) == {"coast guard"}


def test_overrides_merge_split_and_are_reported():
    ovr = Overrides(merge=[["uscg", "coast guard", "u.s. coast guard"]],
                    split={"smith": [["Smith", "SMITH"], ["smith."]]})
    raws = ["Coast Guard", "USCG", "U.S. Coast Guard", "Smith", "SMITH", "smith.", "Smith, "]
    got = resolve("agencies", raws, ovr)
    # a merge group maps every listed key to its smallest key
    assert {got[r] for r in raws[:3]} == {"coast guard"}
    # a split turns the listed raw-form groups into key#1, key#2; an unlisted raw form stays
    assert (got["Smith"], got["SMITH"], got["smith."], got["Smith, "]) == (
        "smith#1", "smith#1", "smith#2", "smith")
    rows = entity_rows("agencies", [("fr_agencies", "name", row("d", name=r)) for r in raws],
                       ovr)
    report = entity_report("agencies", rows, ovr)
    assert report["overrides"]["merge"] == [["uscg", "coast guard", "u.s. coast guard"]]
    assert report["overrides"]["split"] == {"smith": [["Smith", "SMITH"], ["smith."]]}
    assert report["overrides"]["unmatched"] == []
    assert report["clusters"] == 4      # coast guard, smith#1, smith#2, smith


def test_an_override_naming_no_key_is_reported_unmatched():
    ovr = Overrides(merge=[["nowhere", "coast guard"]], split={"ghost": [["Ghost"]]})
    rows = entity_rows("agencies", [("fr_agencies", "name", row("d", name="Coast Guard"))], ovr)
    report = entity_report("agencies", rows, ovr)
    assert report["overrides"]["unmatched"] == ["ghost", "nowhere"]
    assert [r.row["key"] for r in rows] == ["coast guard"]


def test_override_files_load_from_a_directory(tmp_path):
    (tmp_path / "venues.json").write_text(json.dumps(
        {"merge": [["arxiv", "arxiv.org"]], "split": {}}), encoding="utf-8")
    assert load_overrides("venues", tmp_path).merge == [["arxiv", "arxiv.org"]]
    assert load_overrides("agencies", tmp_path) == Overrides()    # no file: no overrides


# -- entity rows, display names and the report ---------------------------------------------------

def test_entity_rows_are_one_per_entity_raw_source_and_document():
    sources = [("papers", "venue", row("d1", venue="arXiv preprint")),
               ("papers", "venue", row("d1", venue="arXiv preprint")),
               ("papers", "venue", row("d1", venue="arXiv")),
               ("papers", "venue", row("d2", venue="arXiv preprint (2026)")),
               ("papers", "venue", row("d2", venue="")),            # no key: no entity
               ("papers", "venue", row("d2", venue=None))]
    rows = entity_rows("venues", sources, Overrides())
    assert {r.row["entity_id"] for r in rows} == {entity_id("arxiv")}
    assert [(r.row["raw"], r.row["doc_id"], r.row["rows"]) for r in rows] == [
        ("arXiv", "d1", 1), ("arXiv preprint", "d1", 2), ("arXiv preprint (2026)", "d2", 1)]
    assert all(r.doc_id == r.row["doc_id"] and r.row["key"] == "arxiv"
               and (r.row["source_table"], r.row["source_column"]) == ("papers", "venue")
               for r in rows)


def test_entity_rows_read_list_columns_element_by_element():
    sources = [("fr_documents", "title_waterway_keys",
                row("d", title_waterway_keys=["fox river", "green bay"])),
               ("fr_documents", "title_waterway_keys",
                row("d", title_waterway_keys=["fox river", "fox river"]))]
    rows = entity_rows("waterways", sources, Overrides())
    assert sorted((r.row["raw"], r.row["rows"]) for r in rows) == [("fox river", 2),
                                                                  ("green bay", 1)]


def test_entity_rows_are_valid_rows_of_the_contract():
    c = load_contracts()["venues"]
    rows = entity_rows("venues", [("papers", "venue", row("d1", venue="arXiv"))], Overrides())
    assert validate_row(c, rows[0]) == []
    assert c.kind == "entity" and "display_name" in [x.name for x in c.columns]
    assert "display_name" not in rows[0].row     # filled per view, never stored


def test_display_name_is_the_byte_smallest_visible_raw():
    rows = [{"entity_id": "e", "raw": "arXiv preprint", "doc_id": "d2"},
            {"entity_id": "e", "raw": "arXiv", "doc_id": "d1"}]
    assert display_names(rows) == {"e": "arXiv"}
    assert display_names([rows[0]]) == {"e": "arXiv preprint"}


def test_display_name_orders_by_utf8_bytes():
    rows = [{"entity_id": "e", "raw": "é"}, {"entity_id": "e", "raw": "z"},
            {"entity_id": "f", "raw": "ab"}, {"entity_id": "f", "raw": "Ab"}]
    assert display_names(rows) == {"e": "z", "f": "Ab"}
    assert display_names([]) == {}


def test_entity_report_counts_clusters_singletons_and_samples_by_seed():
    sources = []
    for i in range(70):
        sources.append(("papers", "venue", row(f"d{i}", venue=f"Venue {i:02d}")))
    sources += [("papers", "venue", row("x", venue=v))
                for v in ("arXiv", "arXiv preprint", "arXiv 2026", "arXiv")]
    rows = entity_rows("venues", sources, Overrides())
    report = entity_report("venues", rows, Overrides())
    assert report["etype"] == "venues" and report["clusters"] == 71
    assert report["singletons"] == 70 and report["merged"] == 1
    top = report["largest"][0]
    assert top["key"] == "arxiv" and top["forms"] == 3 and top["rows"] == 4
    assert top["raws"] == ["arXiv", "arXiv 2026", "arXiv preprint"]
    assert len(report["largest"]) == 10 and len(report["sample"]) == 50
    again = entity_report("venues", rows, Overrides())
    assert again == report
    other = entity_report("venues", rows, Overrides(), seed=1)
    assert other["sample"] != report["sample"] and other["clusters"] == 71
    assert len({s["key"] for s in report["sample"]}) == 50


# -- the build manifest ----------------------------------------------------------------------------

def test_entity_tables_are_listed_in_the_manifest(tmp_path):
    result = build_tables(make_tables_store(tmp_path / "s").path, "gov")
    tables = {t.table for t in result.tables}
    assert {"agencies", "cfr_parts", "dockets", "waterways"} <= tables
    assert not {"venues", "licences", "authors"} & tables
    assert all(t.kind == "entity" for t in result.tables
               if t.table in ("agencies", "cfr_parts", "dockets", "waterways"))
    assert all(r["rejected"] == [] for r in result.reports.values())


def test_research_build_has_venues_licences_and_authors(tmp_path):
    result = build_tables(make_tables_store(tmp_path / "s").path, "research")
    assert {"venues", "licences", "authors"} <= {t.table for t in result.tables}
    m = ov.load_manifest(tmp_path / "s", result.tables_id)
    venues = ov.load_rows(tmp_path / "s", m, "venues")
    assert {r.row["key"] for r in venues} == {"arxiv", "journal of things"}
    assert {r.row["raw"] for r in venues if r.row["key"] == "arxiv"} == {
        "arXiv preprint", "arXiv", "arXiv preprint (2026)", "arXiv 2026"}
    licences = ov.load_rows(tmp_path / "s", m, "licences")
    assert {r.row["key"] for r in licences} == {"cc-by-4.0", "unknown", "mit"}
    assert {r.row["raw"] for r in licences if r.row["key"] == "cc-by-4.0"} == {
        "CC-BY-4.0", "CC BY 4.0"}
    assert result.reports["venues"]["entities"]["clusters"] == 2


def test_gov_entities_cover_agencies_cfr_parts_and_dockets(tmp_path):
    store = make_tables_store(tmp_path / "s")
    result = build_tables(store.path, "gov")
    m = ov.load_manifest(store.path, result.tables_id)
    agencies = ov.load_rows(store.path, m, "agencies")
    coast = [r for r in agencies if r.row["key"] == "coast guard"]
    assert {r.row["raw"] for r in coast} == {"Coast Guard", "COAST GUARD"}
    parts = {r.row["key"] for r in ov.load_rows(store.path, m, "cfr_parts")}
    assert {"33 cfr 117", "33 cfr 165", "33 cfr 117a", "47 cfr 73"} <= parts
    dockets = {r.row["key"] for r in ov.load_rows(store.path, m, "dockets")}
    assert {"uscg-2024-0001", "mb 17-105"} <= dockets


def test_entity_id_columns_of_the_data_tables_name_their_cluster(tmp_path):
    store = make_tables_store(tmp_path / "s")
    fr = fr_tables(store, None)
    ids = {r.row["name"]: r.row["agency_id"] for r in fr["fr_agencies"]}
    assert ids["COAST GUARD"] == ids["Coast Guard"] == entity_id("coast guard")
    assert {r.row["cfr_part_id"] for r in fr["fr_cfr_refs"]
            if r.row["cfr_part"] == "33 CFR 117"} == {entity_id("33 cfr 117")}
    assert {r.row["docket_id"] for r in fr["fr_dockets"] if r.row["docket"] == "MB 17-105"} == {
        entity_id("mb 17-105")}
    papers = papers_tables(store)
    assert {r.row["venue_id"] for r in papers["papers"][:3]} == {entity_id("arxiv")}
    assert {r.row["licence_id"] for r in papers["papers"][:3]} == {entity_id("cc-by-4.0")}
    authors = papers["paper_authors"]
    assert all(r.row["author_id"] == entity_id(r.row["name_key"]) for r in authors)
    assert "ann lee" in {r.row["name_key"] for r in authors}


def test_overrides_reach_the_data_tables_ids(tmp_path):
    store = make_tables_store(tmp_path / "s")
    fr = fr_tables(store, None, {"agencies": Overrides(merge=[["coast guard", "zzz"]])})
    assert {r.row["agency_id"] for r in fr["fr_agencies"] if r.row["name"] == "Coast Guard"} == {
        entity_id("coast guard")}
    fr = fr_tables(store, None, {"agencies": Overrides(merge=[["aaa", "coast guard"]])})
    assert {r.row["agency_id"] for r in fr["fr_agencies"] if r.row["name"] == "Coast Guard"} == {
        entity_id("aaa")}


# -- eCFR sections ---------------------------------------------------------------------------------

@pytest.fixture
def ecfr_store(tmp_path) -> Store:
    docs = [ecfr_doc(ECFR_NEW), ecfr_doc(ECFR_OLD), *FR_DOCS]
    return make_tables_store(tmp_path / "ecfr", docs)


@pytest.fixture
def newest(ecfr_store) -> str:
    return chain_docs(ecfr_store)[-1]


def test_chain_docs_are_ordered_by_version(ecfr_store):
    docs = chain_docs(ecfr_store)
    assert [ecfr_store.source(d).source_version for d in docs] == [ECFR_OLD, ECFR_NEW]
    assert chain_docs(ecfr_store, "ecfr:33:99") == []


def test_ecfr_sections_carry_heading_state_and_spans(ecfr_store, newest):
    units = ecfr_sections(ecfr_store, newest)
    u = next(x for x in units if x.section == "117.821")
    text = ecfr_store.text(newest)
    assert u.state == "North Carolina" and text[u.start:u.end] == u.text
    assert text[slice(*u.heading_span)] == u.heading == "§ 117.821 Cape Fear River."
    assert text[slice(*u.state_span)] == "North Carolina"
    assert u.doc_id == newest and u.version == ECFR_NEW


def test_ecfr_sections_in_document_order_with_states(ecfr_store, newest):
    units = ecfr_sections(ecfr_store, newest)
    assert [(u.section, u.state) for u in units] == [
        ("117.1", None), ("117.821", "North Carolina"), ("117.823", "North Carolina"),
        ("117.827", "North Carolina"), ("117.261", "Florida"), ("117.263", "Florida")]
    general = units[0]
    assert general.state_span is None
    text = ecfr_store.text(newest)
    for a, b in zip(units, units[1:], strict=False):
        assert a.end <= b.start
    assert all(text[u.start:u.end] == u.text and u.text.startswith(u.heading) for u in units)
    florida = units[-1]
    assert text[slice(*florida.state_span)] == "Florida"
    assert florida.state_span[1] < florida.heading_span[0]


def test_two_versions_differ_in_one_section_only(ecfr_store):
    old, new = (ecfr_sections(ecfr_store, d) for d in chain_docs(ecfr_store))
    changed = [a.section for a, b in zip(old, new, strict=True) if a.text != b.text]
    assert changed == ["117.821"] and [u.section for u in old] == [u.section for u in new]
    assert "two hours notice" in old[1].text and "four hours notice" in new[1].text


def test_ecfr_sections_skip_a_repeated_section_number(tmp_path):
    raw = ecfr_doc(ECFR_NEW)[1].replace(b'N="117.827"', b'N="117.823"')
    store = make_tables_store(tmp_path / "s", [ecfr_doc(ECFR_NEW, raw), *FR_DOCS])
    doc = chain_docs(store)[0]
    assert [u.section for u in ecfr_sections(store, doc)].count("117.823") == 1


def test_ecfr_sections_refuse_a_document_that_is_no_stored_blob(tmp_path):
    store = make_tables_store(tmp_path / "s", [ecfr_doc(ECFR_NEW), *FR_DOCS])
    doc = chain_docs(store)[0]
    blob = store.path / "blobs" / doc[:2] / doc
    blob.write_bytes(blob.read_bytes() + b"<!-- changed -->")
    with pytest.raises(ValueError, match="bytes"):
        ecfr_sections(store, doc)


def test_states_hold_the_states_and_territories():
    assert len(STATES) == 56
    assert STATES["NC"] == "North Carolina" and STATES["DC"] == "District of Columbia"
    assert {"PR", "VI", "GU", "AS", "MP"} <= set(STATES)


# -- titles and headings -------------------------------------------------------------------------

def test_title_parts():
    assert title_parts("Drawbridge Operation Regulation; Gulf Intracoastal Waterway, Osprey, FL") \
        == (["gulf intracoastal waterway", "osprey"], "Florida")
    assert title_parts("Drawbridge Operation Regulations; Fox River, Green Bay, WI")[1] == (
        "Wisconsin")
    assert title_parts("Safety Zone; Fireworks, Miami, FL") is None


@pytest.mark.parametrize("title,want", [
    ("Drawbridge Operation Regulation: Housatonic River, Stratford, CT",
     (["housatonic river", "stratford"], "Connecticut")),
    ("Drawbridge Operation Regulation; Tchefuncta River", (["tchefuncta river"], None)),
    ("Drawbridge Operation Regulation; Technical Amendment; Removal of Obsolete Drawbridge "
     "Operating Regulations",
     (["technical amendment; removal of obsolete drawbridge operating regulations"], None)),
    ("Drawbridge Operation Regulation; Inside Thorofare, Ventnor City, New Jersey",
     (["inside thorofare", "ventnor city", "new jersey"], None)),
    ("Drawbridge Operation Regulations; Old Fort Bayou, MS", (["old fort bayou"], "Mississippi")),
    ("Drawbridge Operation Regulation; The Alpha River, , Z, ZZ",
     (["alpha river", "z", "zz"], None)),
    ("Drawbridge Operation Regulation", ([], None)),
])
def test_drawbridge_titles_of_the_real_forms(title, want):
    assert title_parts(title) == want


@pytest.mark.parametrize("title", [
    None, "", "Drawbridge Operations Regulation; A", "drawbridge operation regulation; A",
    "Temporary Drawbridge Operation Regulation; A", "Drawbridge Operation Regulation for A"])
def test_other_titles_are_no_drawbridge_titles(title):
    assert title_parts(title) is None


@pytest.mark.parametrize("heading,key", [
    ("§ 117.821 Cape Fear River.", "cape fear river"),
    ("§ 117.261 Atlantic Intracoastal Waterway, Palm Beach County.",
     "atlantic intracoastal waterway"),
    ("§ 117.5 The Alpha River.", "alpha river"),
    ("§ 117.7", ""),
])
def test_heading_waterway_key(heading, key):
    assert heading_waterway_key(heading) == key


# -- waterway links ------------------------------------------------------------------------------

def fr_row(number: str, title: str) -> RowRecord:
    return row("doc-" + number, id=number, title=title)


def sections_of(store) -> list:
    return [u for d in chain_docs(store) for u in ecfr_sections(store, d)]


def test_waterway_links_are_one_to_many_on_key_and_state(ecfr_store):
    rows = [fr_row("a", DRAW + "Atlantic Intracoastal Waterway, Jupiter, FL"),
            fr_row("b", DRAW + "Cape Fear River, Wilmington, FL"),     # wrong state
            fr_row("c", DRAW + "Cape Fear River, Wilmington, NC"),
            fr_row("d", DRAW + "Cape Fear River"),                     # one state has it
            fr_row("e", DRAW + "Atlantic Intracoastal Waterway"),      # two states have it
            fr_row("f", DRAW + "Missing River, Nowhere, FL"),
            fr_row("g", "Safety Zone; Fireworks, Miami, FL"),
            fr_row("h", "Drawbridge Operation Regulation; Technical Amendment; Removal"),
            row("doc-i", id="i", title=None)]
    links = waterway_links(rows, sections_of(ecfr_store))
    by = {x["id"]: x for x in links["linked"]}
    assert by["a"]["sections"] == ["117.261", "117.263"]   # two sections of one waterway and state
    assert by["a"]["title"] == DRAW + "Atlantic Intracoastal Waterway, Jupiter, FL"
    assert by["c"]["sections"] == ["117.821"] and by["d"]["sections"] == ["117.821"]
    assert [x["id"] for x in links["linked"]] == ["a", "c", "d"]
    unlinked = {x["id"]: x["reason"] for x in links["unlinked"]}
    assert unlinked == {"b": "state_mismatch", "e": "ambiguous_state",
                        "f": "no_matching_heading", "h": "no_matching_heading"}
    assert set(links) == {"linked", "unlinked"}
    assert not {"g", "i"} & (set(by) | set(unlinked))     # no drawbridge titles: not counted


def test_a_part_of_the_title_other_than_the_first_can_link(ecfr_store):
    rows = [fr_row("a", DRAW + "Port of Wilmington, Neuse River, NC")]
    assert waterway_links(rows, sections_of(ecfr_store))["linked"][0]["sections"] == ["117.823"]


def test_linking_a_title_lists_each_section_once_across_versions(ecfr_store):
    links = waterway_links([fr_row("c", DRAW + "Cape Fear River, Wilmington, NC")],
                           sections_of(ecfr_store))
    assert links["linked"][0]["sections"] == ["117.821"]       # in both versions, listed once


def test_a_section_outside_every_state_group_links_nothing():
    s = SectionUnit("d", "v", "117.9", "§ 117.9 Fox River.", None, 0, 5, (0, 5), None, "x")
    links = waterway_links([fr_row("a", DRAW + "Fox River, Green Bay, WI"),
                            fr_row("b", DRAW + "Fox River")], [s])
    assert [x["reason"] for x in links["unlinked"]] == ["no_matching_heading"] * 2


# -- the title columns of fr_documents -------------------------------------------------------

def test_fr_documents_carry_the_title_state_and_waterway_keys(tmp_path):
    store = make_tables_store(tmp_path / "s")
    docs = {r.row["id"]: r for r in fr_tables(store, None)["fr_documents"]}
    myrtle = docs["2024-00004"]
    assert myrtle.row["title_state"] == "South Carolina"
    assert myrtle.row["title_waterway_keys"] == ["atlantic intracoastal waterway",
                                                 "myrtle beach"]
    other = docs["2024-00003"]
    assert other.row["title_state"] is None and other.row["title_waterway_keys"] == []
    assert other.prov["title_state"].null_reason == "not_applicable"
    assert docs["2024-00002"].prov["title_state"].null_reason == "absent"      # no title
    assert docs["2024-00002"].row["title_waterway_keys"] == []


def test_a_drawbridge_title_without_a_state_has_a_null_state(tmp_path):
    store = make_tables_store(tmp_path / "s",
                              [fr_doc("2024-00020", title=DRAW + "Tchefuncta River")])
    row_ = fr_tables(store, None)["fr_documents"][0]
    assert row_.row["title_state"] is None and row_.prov["title_state"].null_reason == "absent"
    assert row_.row["title_waterway_keys"] == ["tchefuncta river"]


def test_title_values_are_located_in_the_title_and_reslice(tmp_path):
    store = make_tables_store(tmp_path / "s")
    rec = next(r for r in fr_tables(store, None)["fr_documents"] if r.row["id"] == "2024-00004")
    text = store.text(rec.doc_id)
    state = rec.prov["title_state"]
    assert text[slice(*state.span)] == "SC" and reslice(text, state, "South Carolina")
    assert not reslice(text, state, "North Carolina")
    spans = [text[slice(*p.span)] for p in rec.prov["title_waterway_keys"]]
    assert spans == ["Atlantic Intracoastal Waterway", "Myrtle Beach"]
    for p, key in zip(rec.prov["title_waterway_keys"], rec.row["title_waterway_keys"],
                      strict=True):
        assert reslice(text, p, key)
        assert not reslice(text, p, "other")


def test_a_title_with_an_escaped_character_still_locates_its_state(tmp_path):
    store = make_tables_store(tmp_path / "s", [fr_doc(
        "2024-00021", title=DRAW + 'Fox "Big" River, Éire, WI')])
    rec = fr_tables(store, None)["fr_documents"][0]
    text = store.text(rec.doc_id)
    assert reslice(text, rec.prov["title_state"], "Wisconsin")
    assert [reslice(text, p, k) for p, k in zip(
        rec.prov["title_waterway_keys"], rec.row["title_waterway_keys"], strict=True)] == [
        True, True]


# -- waterway entities -----------------------------------------------------------------------

def test_waterways_come_from_titles_and_ecfr_headings(tmp_path):
    docs = [ecfr_doc(ECFR_NEW), ecfr_doc(ECFR_OLD), *FR_DOCS]
    store = make_tables_store(tmp_path / "s", docs)
    result = build_tables(store.path, "gov")
    m = ov.load_manifest(store.path, result.tables_id)
    rows = ov.load_rows(store.path, m, "waterways")
    sources = {(r.row["source_table"], r.row["source_column"]) for r in rows}
    assert sources == {("fr_documents", "title_waterway_keys"), ("ecfr_headings", "heading")}
    heading_rows = [r for r in rows if r.row["source_table"] == "ecfr_headings"]
    assert {r.row["doc_id"] for r in heading_rows} == set(chain_docs(store))
    aiw = [r for r in heading_rows if r.row["key"] == "atlantic intracoastal waterway"]
    assert {r.row["raw"] for r in aiw} == {"Atlantic Intracoastal Waterway"}
    assert sorted(r.row["rows"] for r in aiw) == [3, 3]    # three headings in each of two versions
    title_rows = [r for r in rows if r.row["source_table"] == "fr_documents"]
    assert "neuse river" in {r.row["key"] for r in title_rows}
    assert result.reports["waterways"]["rejected"] == []


def test_the_waterways_of_a_store_without_ecfr_come_from_titles_only(tmp_path):
    result = build_tables(make_tables_store(tmp_path / "s").path, "gov")
    m = ov.load_manifest(tmp_path / "s", result.tables_id)
    rows = ov.load_rows(tmp_path / "s", m, "waterways")
    assert {r.row["source_table"] for r in rows} == {"fr_documents"}


def test_entity_builds_are_deterministic(tmp_path):
    store = make_tables_store(tmp_path / "s", [ecfr_doc(ECFR_NEW), *FR_DOCS, MANIFEST])
    assert build_tables(store.path, "gov").tables_id == build_tables(store.path, "gov").tables_id
    assert (build_tables(store.path, "research").tables_id
            == build_tables(store.path, "research").tables_id)
