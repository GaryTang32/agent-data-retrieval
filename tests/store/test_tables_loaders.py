"""The 3A loaders and `build_tables` (Phase 3 spec §5.4): the Federal Register and papers tables
built from metadata the corpora carry, no model calls, every value's span located in the stored
text. Fixture stores under `tmp_path`; nothing reads `data/` or `.cache/`."""

import csv
import json

import pytest

from adr_eval.corpora.gov import GovAdapter
from adr_eval.corpora.research import ResearchAdapter
from adr_store import acl
from adr_store import applicability as ap
from adr_store.store import Store
from adr_store.tables import overlay as ov
from adr_store.tables.build import BuildResult, build_tables
from adr_store.tables.contracts import load_contracts
from adr_store.tables.loaders import (
    FR_PREFIX,
    PAPERS_URI,
    fr_tables,
    papers_tables,
    parse_dockets,
    records_view,
    split_authors,
)
from adr_store.tables.parse import author_tokens, csv_fields, scan_dockets
from adr_store.tables.provenance import MANIFEST_COLUMNS, RESLICERS, RowRecord, reslice
from tests.store.tables_fixtures import (
    FR_DOCS,
    MANIFEST,
    fr_doc,
    loaded_of,
    make_tables_store,
)

GOV_FIELDS = ["id", "type", "agency", "publication_date", "year", "title", "cfr_parts"]
RESEARCH_FIELDS = ["id", *MANIFEST_COLUMNS[:6], "year", *MANIFEST_COLUMNS[7:]]


@pytest.fixture
def tables_store(tmp_path) -> Store:
    return make_tables_store(tmp_path / "store")


@pytest.fixture
def fr(tables_store):
    return fr_tables(tables_store, ap.load_overlay(tables_store.path, tables_store.snapshot_id))


@pytest.fixture
def papers(tables_store):
    return papers_tables(tables_store)


def as_list(x):
    return x if isinstance(x, list) else [x]


def by_id(rows: list[RowRecord], number: str) -> list[RowRecord]:
    return [r for r in rows if r.row["id"] == number]


def doc_id_of(number: str) -> str:
    return next(d.doc_id for d, _ in FR_DOCS if json.loads(d.text)["document_number"] == number)


# -- the v0.1 records are reproduced -------------------------------------------------------------

def test_fr_documents_reproduce_the_gov_records(tables_store):
    rows = fr_tables(tables_store, ap.load_overlay(tables_store.path, tables_store.snapshot_id))
    want = [{k: v for k, v in r.items() if k != "_doc_id"}
            for r in GovAdapter().records(loaded_of(tables_store))]
    assert len(want) == len(FR_DOCS)
    assert records_view(rows["fr_documents"], GOV_FIELDS) == want


def test_papers_reproduce_the_research_records(tables_store):
    want = [{k: v for k, v in r.items() if not k.startswith("_")}
            for r in ResearchAdapter().records(loaded_of(tables_store))]
    assert len(want) == 5
    assert records_view(papers_tables(tables_store)["papers"], RESEARCH_FIELDS) == want


def test_records_view_keeps_the_rows_order_and_picks_the_columns(papers):
    rows = papers["papers"]
    assert records_view(rows, ["row", "id"])[:2] == [{"row": 1, "id": "2501.00001"},
                                                     {"row": 2, "id": "2501.00001"}]


def test_every_value_span_reslices(tables_store, fr, papers):
    checked = 0
    for rows in [*fr.values(), *papers.values()]:
        for r in rows:
            text = tables_store.text(r.doc_id)
            for col, p in r.prov.items():
                for one, v in zip(as_list(p), as_list(r.row[col]), strict=True):
                    if one.start is not None:
                        assert reslice(text, one, v), (col, one, v)
                        checked += 1
    assert checked > 200


def test_every_value_without_a_span_is_derived_or_null(fr, papers):
    """Only values computed from several places (positions, flags, the overlay's status, the
    entity ids) and nulls carry no span."""
    unlocated = set()
    for rows in [*fr.values(), *papers.values()]:
        for r in rows:
            for p in r.prov.values():
                for one in as_list(p):
                    if one.start is None and one.null_reason is None:
                        unlocated.add(one.spec_id)
    assert unlocated == {"fr.agency_position@1", "fr.agency_specific@1", "fr.status@1",
                         "fr.agency_id@1", "fr.cfr_part_id@1", "fr.docket_id@1",
                         "papers.venue_id@1", "papers.licence_id@1", "papers.author_id@1"}


def test_a_bare_continuation_number_is_located_and_reslices(tables_store, fr):
    """"MB Docket Nos. 17-317, 17-105": the second number stands in a part of its own, and its
    docket is read with the letters of the part before it."""
    rows = by_id(fr["fr_dockets"], "2024-00007")
    assert [r.row["docket"] for r in rows] == ["MB 17-317", "MB 17-105", "ET 99-1", "ET 99-2"]
    text = tables_store.text(rows[0].doc_id)
    spans = [text[slice(*r.prov["docket"].span)] for r in rows]
    assert spans == ["17-317", "17-105", "99-1", "99-2"]
    assert all(reslice(text, r.prov["docket"], r.row["docket"]) for r in rows)
    assert not reslice(text, rows[1].prov["docket"], "17-105")    # the letters matter


# -- dockets and authors -------------------------------------------------------------------------

@pytest.mark.parametrize("given,dockets,other", [
    (["Docket No. USCG-2024-0013"], ["USCG-2024-0013"], []),
    (["Docket Number USCG-2022-0895"], ["USCG-2022-0895"], []),
    (["MB Docket Nos. 17-317, 17-105"], ["MB 17-317", "MB 17-105"], []),
    (["MB Docket Nos. 17-105 and 14-127, MM Docket No. 00-168"],
     ["MB 17-105", "MB 14-127", "MM 00-168"], []),
    (["ET Docket Nos. 03-137 and 13-84, FCC 19-126"], ["ET 03-137", "ET 13-84"], ["FCC 19-126"]),
    (["Docket No. [USCG-2025-0464"], ["USCG-2025-0464"], []),
    (["USCG-2022-0709", "FR ID 343182"], [], ["USCG-2022-0709", "FR ID 343182"]),
    (["RM-12006, RM-12019"], [], ["RM-12006", "RM-12019"]),
    # a bare number keeps the letters of the docket part just before it, in its string only
    (["MB Docket No. 17-1", "17-2"], ["MB 17-1"], ["17-2"]),
    (["Docket Nos. 12-3, 13-4"], ["12-3", "13-4"], []),
    (["MB Docket No. 17-1, FCC 19-1, 17-2"], ["MB 17-1"], ["FCC 19-1", "17-2"]),
    ([], [], []),
])
def test_parse_dockets(given, dockets, other):
    found, others = parse_dockets(given)
    assert [d for d, _ in found] == dockets and others == other


def test_parse_dockets_names_the_part_each_docket_came_from():
    found, _ = parse_dockets(["MB Docket Nos. 17-105 and 14-127, MM Docket No. 00-168"])
    assert [p for _, p in found] == ["MB Docket Nos. 17-105 and 14-127"] * 2 + [
        "MM Docket No. 00-168"]


def test_scan_dockets_gives_the_offsets_of_numbers_and_parts():
    s = "MB Docket Nos. 17-105 and 14-127,  FCC 19-1"
    dockets, others = scan_dockets(s)
    assert [(d, s[n.start:n.end]) for d, n, _ in dockets] == [("MB 17-105", "17-105"),
                                                               ("MB 14-127", "14-127")]
    assert [(p.text, s[p.start:p.end]) for p in others] == [("FCC 19-1", "FCC 19-1")]


def test_split_authors():
    assert split_authors("A. Smith, B. Jones, et al.") == (["A. Smith", "B. Jones"], True)
    assert split_authors("Ann Lee,  Bo Chen.") == (["Ann Lee", "Bo Chen."], False)
    assert split_authors("A, ,B,ET AL") == (["A", "B"], True)
    assert split_authors("") == ([], False)
    assert split_authors("et al.") == ([], True)
    assert split_authors("Smith et al.") == (["Smith et al."], False)


def test_csv_fields_decode_as_the_csv_module_and_keep_offsets():
    record = 'a,"b, ""c""",,d"e,"f\ng"'
    fields = csv_fields(record, 10)
    assert [f.value for f in fields] == next(csv.reader([record]))
    quoted = fields[1]
    assert quoted.value == 'b, "c"'
    assert record[quoted.span(3, 4)[0] - 10:quoted.span(3, 4)[1] - 10] == '""'
    assert fields[2].value == "" and fields[2].starts == ()


def test_author_tokens_locate_each_author_in_a_quoted_field(tables_store):
    text = tables_store.text(MANIFEST[0].doc_id)
    rows = ResearchAdapter().records(loaded_of(tables_store))
    row = rows[2]
    start, end = row["_span"]
    tokens, et_al = author_tokens(text, start, end)
    assert [(n, text[s:e]) for n, s, e in tokens] == [('Dr "Bob" Smith', 'Dr ""Bob"" Smith'),
                                                      ("C. Doe", "C. Doe")]
    assert not et_al


# -- the Federal Register tables -----------------------------------------------------------------

def test_fr_documents_hold_the_other_metadata_fields(fr):
    first = by_id(fr["fr_documents"], "2024-00001")[0].row
    assert first["action"] == "Final rule." and first["effective_on"] == "2024-03-15"
    assert first["status"] == "final_rule"
    proposed = by_id(fr["fr_documents"], "2024-00002")[0].row
    assert proposed["status"] == "proposed_rule" and proposed["effective_on"] is None


def test_missing_and_unparseable_values_are_null_with_their_reason(fr):
    doc = by_id(fr["fr_documents"], "2024-00002")[0]
    assert doc.row["title"] is None and doc.prov["title"].null_reason == "absent"
    assert doc.row["effective_on"] is None and doc.prov["effective_on"].null_reason == "absent"
    none = by_id(fr["fr_documents"], "2024-00006")[0]
    assert none.row["agency"] is None and none.prov["agency"].null_reason == "absent"
    assert none.row["cfr_parts"] == [] and none.prov["cfr_parts"] == []
    refs = {r.row["cfr_part"]: r for r in by_id(fr["fr_cfr_refs"], "2024-00002")}
    ref = refs["33 CFR 117a"]
    assert ref.row["part"] is None and ref.prov["part"].null_reason == "unparseable"
    assert ref.row["title"] == 33 and ref.prov["cfr_part"].start is not None
    agency = by_id(fr["fr_agencies"], "2024-00002")[0]
    assert agency.row["parent_id"] is None and agency.prov["parent_id"].null_reason == "absent"


def test_a_part_given_as_an_integer_is_the_same_reference_as_its_text(fr):
    refs = by_id(fr["fr_cfr_refs"], "2024-00001")
    assert [(r.row["cfr_part"], r.row["title"], r.row["part"]) for r in refs] == [
        ("33 CFR 117", 33, 117), ("33 CFR 165", 33, 165)]
    assert by_id(fr["fr_documents"], "2024-00001")[0].row["cfr_parts"] == [
        "33 CFR 117", "33 CFR 165"]


def test_the_agency_is_the_most_specific_one_and_names_stay_raw(fr):
    assert by_id(fr["fr_documents"], "2024-00001")[0].row["agency"] == "Coast Guard"
    assert by_id(fr["fr_documents"], "2024-00002")[0].row["agency"] == "COAST GUARD"
    rows = by_id(fr["fr_agencies"], "2024-00001")
    assert [(r.row["position"], r.row["name"], r.row["fr_agency_id"], r.row["parent_id"],
             r.row["specific"]) for r in rows] == [
        (0, "Homeland Security Department", 1, None, False), (1, "Coast Guard", 2, 1, True)]


def test_dockets_other_ids_and_their_raw_strings(fr):
    dockets = [(r.row["docket"], r.row["raw"]) for r in by_id(fr["fr_dockets"], "2024-00003")]
    mb = "MB Docket Nos. 17-105 and 14-127, MM Docket No. 00-168"
    et = "ET Docket Nos. 03-137 and 13-84, FCC 19-126"
    assert dockets == [("MB 17-105", mb), ("MB 14-127", mb), ("MM 00-168", mb),
                       ("ET 03-137", et), ("ET 13-84", et)]
    assert by_id(fr["fr_documents"], "2024-00003")[0].row["other_ids"] == [
        "FCC 19-126", "FR ID 343182"]
    assert by_id(fr["fr_documents"], "2024-00005")[0].row["other_ids"] == [
        "RM-12006", "RM-12019", "USCG-2022-0709"]
    assert [r.row["docket"] for r in by_id(fr["fr_dockets"], "2024-00004")] == ["USCG-2025-0464"]
    # the same docket given twice in one document is one row
    assert [r.row["docket"] for r in by_id(fr["fr_dockets"], "2024-00001")] == ["USCG-2024-0001"]
    assert by_id(fr["fr_dockets"], "2024-00006") == []


def test_a_fragment_span_reslices_to_the_docket_with_the_letters_carried_over(tables_store, fr):
    row = next(r for r in by_id(fr["fr_dockets"], "2024-00003") if r.row["docket"] == "MB 14-127")
    text = tables_store.text(row.doc_id)
    p = row.prov["docket"]
    assert text[p.start:p.end] == "14-127"
    assert RESLICERS["fr.docket"](text, p.start, p.end) == "MB 14-127"
    assert not reslice(text, p, "MB 17-105") and not reslice(text, p, "14-127")


def test_other_ids_spans_are_the_part_or_the_whole_string(tables_store, fr):
    doc = by_id(fr["fr_documents"], "2024-00003")[0]
    text = tables_store.text(doc.doc_id)
    spans = [(text[p.start:p.end]) for p in doc.prov["other_ids"]]
    assert spans == ["FCC 19-126", '"FR ID 343182"']   # a part; a whole string
    five = by_id(fr["fr_documents"], "2024-00005")[0]
    assert [tables_store.text(five.doc_id)[p.start:p.end] for p in five.prov["other_ids"]] == [
        "RM-12006", "RM-12019", '"USCG-2022-0709"']


def test_docket_spans_survive_json_escapes_and_non_ascii(tmp_path):
    s = make_tables_store(tmp_path / "s", [fr_doc(
        "2024-00007", dockets=('MB Docket Nos. A"1 and B\\2, \u2603 x, "q" y, \u00e9 z',))])
    tables = fr_tables(s, None)
    assert [r.row["docket"] for r in tables["fr_dockets"]] == ['MB A"1', "MB B\\2"]
    assert tables["fr_documents"][0].row["other_ids"] == ["\u2603 x", '"q" y', "\u00e9 z"]
    text = s.text(tables["fr_documents"][0].doc_id)
    for rows in tables.values():
        for r in rows:
            for col, p in r.prov.items():
                for one, v in zip(as_list(p), as_list(r.row[col]), strict=True):
                    if one.start is not None:
                        assert reslice(text, one, v), (col, text[one.start:one.end], v)


def test_status_comes_from_the_applicability_overlay(tables_store, fr):
    overlay = ap.load_overlay(tables_store.path, tables_store.snapshot_id)
    for r in fr["fr_documents"]:
        assert r.row["status"] == overlay.records[r.doc_id].status
        assert r.prov["status"].status == "verified" and r.prov["status"].start is None
    without = fr_tables(tables_store, None)["fr_documents"]
    assert {r.row["status"] for r in without} == {None}
    assert {r.prov["status"].null_reason for r in without} == {"absent"}


def test_only_federal_register_documents_are_read(tables_store):
    assert all(d.uri.startswith(FR_PREFIX) for d, _ in FR_DOCS)
    assert {r.doc_id for r in fr_tables(tables_store, None)["fr_documents"]} == {
        d.doc_id for d, _ in FR_DOCS}
    assert PAPERS_URI == MANIFEST[0].uri
    empty = fr_tables(Store.open(tables_store.path), None)
    assert set(empty) == {"fr_documents", "fr_cfr_refs", "fr_agencies", "fr_dockets"}


# -- the papers tables ---------------------------------------------------------------------------

def test_papers_are_one_row_per_manifest_row_with_numbers_from_one(papers):
    rows = papers["papers"]
    assert [(r.row["row"], r.row["id"]) for r in rows] == [
        (1, "2501.00001"), (2, "2501.00001"), (3, "10.1000/x"),
        (4, rows[3].row["id"]), (5, "10.1000/y")]
    assert rows[3].row["id"].startswith("url:")
    assert [r.row["venue"] for r in rows] == ["arXiv preprint", "arXiv",
                                              "arXiv preprint (2026)", "arXiv 2026",
                                              "Journal of Things"]
    assert [r.row["license"] for r in rows][:2] == ["CC-BY-4.0", "CC BY 4.0"]
    assert rows[2].row["relevance"] == "Line one\nline two, with a comma."
    assert rows[2].row["title"] == 'He said "hi": a study'


def test_year_is_null_with_a_reason_when_empty_or_not_a_number(papers):
    rows = papers["papers"]
    assert [r.row["year"] for r in rows] == [2025, None, 2026, None, 2024]
    assert rows[1].prov["year"].null_reason == "absent"
    assert rows[3].prov["year"].null_reason == "unparseable"
    assert rows[0].prov["year"].null_reason is None


def test_also_in_list_splits_on_semicolons(papers):
    rows = papers["papers"]
    assert [r.row["also_in"] for r in rows][:2] == ["02_agents;03_data", ""]
    assert [r.row["also_in_list"] for r in rows] == [
        ["02_agents", "03_data"], [], ["01_surveys"], [], ["01_surveys", "03_data"]]
    assert [len(r.prov["also_in_list"]) for r in rows] == [2, 0, 1, 0, 2]


def test_paper_authors_one_row_per_author_with_et_al_as_a_flag(papers):
    rows = [(r.row["row"], r.row["position"], r.row["raw"], r.row["name_key"], r.row["et_al"])
            for r in papers["paper_authors"]]
    assert rows == [
        (1, 0, "A. Smith", "a. smith", True), (1, 1, "B. Jones", "b. jones", True),
        (2, 0, "Ann Lee", "ann lee", False), (2, 1, "Bo Chen.", "bo chen", False),
        (3, 0, 'Dr "Bob" Smith', 'dr "bob" smith', False), (3, 1, "C. Doe", "c. doe", False)]
    assert {r.row["id"] for r in papers["paper_authors"] if r.row["row"] in (1, 2)} == {
        "2501.00001"}


def test_an_author_span_is_the_author_as_written_in_the_row(tables_store, papers):
    row = next(r for r in papers["paper_authors"] if r.row["raw"] == 'Dr "Bob" Smith')
    text = tables_store.text(row.doc_id)
    p = row.prov["raw"]
    assert text[p.start:p.end] == 'Dr ""Bob"" Smith'      # the CSV source of the name
    assert RESLICERS["papers.author_raw"](text, p.start, p.end) == 'Dr "Bob" Smith'
    assert RESLICERS["papers.author_position"](text, p.start, p.end) == 0
    assert row.prov["position"].span == p.span == row.prov["name_key"].span
    assert row.prov["et_al"].span == row.prov["id"].span == row.prov["row"].span
    assert RESLICERS["papers.row"](text, *row.prov["row"].span) == 3
    assert RESLICERS["papers.author_et_al"](text, *row.prov["et_al"].span) is False
    other = row.prov["raw"].model_copy(update={"start": p.start + 1})
    assert not reslice(text, other, 'Dr "Bob" Smith')


def test_row_numbers_do_not_depend_on_the_text_object(tables_store, papers):
    row = papers["papers"][3]
    text = tables_store.text(row.doc_id)
    again = "".join(list(text))      # an equal string that is another object
    assert reslice(again, row.prov["row"], 4) and not reslice(again, row.prov["row"], 3)
    assert not reslice(text, row.prov["row"].model_copy(update={"end": row.prov["row"].end - 1}),
                       4)


def test_a_manifest_header_alone_gives_no_rows(tmp_path):
    from tests.store.test_chunking import doc
    header = ",".join(MANIFEST_COLUMNS) + "\r\n"
    s = make_tables_store(tmp_path / "s", [doc(header.encode(), "csv", PAPERS_URI)])
    assert papers_tables(s) == {"papers": [], "paper_authors": []}


# -- build_tables ---------------------------------------------------------------------------------

def test_build_writes_every_metadata_table_of_the_corpus(tmp_path):
    store = make_tables_store(tmp_path / "s")
    result = build_tables(store.path, "gov")
    assert isinstance(result, BuildResult)
    data = [t for t in result.tables if t.kind == "data"]
    assert [t.table for t in data] == ["fr_agencies", "fr_cfr_refs", "fr_dockets",
                                       "fr_documents"]
    assert {t.table: t.rows for t in data} == {
        "fr_agencies": 9, "fr_cfr_refs": 7, "fr_dockets": 12, "fr_documents": 7}
    assert all(t.rejected == 0 for t in result.tables)
    m = ov.load_manifest(store.path, result.tables_id)
    assert (m.snapshot, m.corpus, m.extraction) == (store.snapshot_id, "gov", None)
    assert m.applicability == ap.load_overlay(store.path, store.snapshot_id).overlay_id
    assert m.tables == result.tables and result.manifest_path.is_file()
    assert set(result.reports) == {t.table for t in result.tables}
    assert result.reports["fr_documents"]["null_reasons"]["title"] == {"absent": 1}
    assert result.reports["fr_documents"]["rejected"] == []


def test_build_writes_the_research_tables_without_an_overlay(tmp_path):
    store = make_tables_store(tmp_path / "s")
    result = build_tables(store.path, "research")
    assert {t.table: (t.rows, t.rejected) for t in result.tables if t.kind == "data"} == {
        "paper_authors": (6, 0), "papers": (5, 0)}
    assert ov.load_manifest(store.path, result.tables_id).applicability is None
    rows = ov.load_rows(store.path, ov.load_manifest(store.path, result.tables_id), "papers")
    assert [r.row["row"] for r in rows] == [1, 2, 3, 4, 5]     # the contract's order is row, id


def test_build_never_moves_head_and_a_second_build_changes_nothing(tmp_path):
    store = make_tables_store(tmp_path / "s")
    a = build_tables(store.path, "gov")
    assert ov.read_head(store.path) is None and not (store.path / "tables" / "HEAD").exists()
    files = sorted(p.name for p in (store.path / "tables").rglob("*") if p.is_file())
    b = build_tables(store.path, "gov")
    assert a.tables_id == b.tables_id
    assert sorted(p.name for p in (store.path / "tables").rglob("*") if p.is_file()) == files


def test_build_is_byte_identical_in_two_copies(tmp_path):
    a = build_tables(make_tables_store(tmp_path / "a").path, "gov")
    b = build_tables(make_tables_store(tmp_path / "b").path, "gov")
    assert a.tables_id == b.tables_id and [t.sha256 for t in a.tables] == [
        t.sha256 for t in b.tables]


def test_build_without_an_applicability_overlay_leaves_status_null(tmp_path):
    store = make_tables_store(tmp_path / "s")
    (store.path / "applicability" / store.snapshot_id / "envelope-1.json").unlink()
    result = build_tables(store.path, "gov")
    rows = ov.load_rows(store.path, ov.load_manifest(store.path, result.tables_id),
                        "fr_documents")
    assert {r.row["status"] for r in rows} == {None}
    assert ov.load_manifest(store.path, result.tables_id).applicability is None


def test_build_takes_the_generator_profile_and_call_cap_but_makes_no_call(tmp_path):
    class Client:
        def __getattr__(self, name):
            raise AssertionError("a 3A build makes no model call")

    store = make_tables_store(tmp_path / "s")
    a = build_tables(store.path, "gov", client=Client(), generator_profile="sonnet", max_calls=0)
    assert a.tables_id == build_tables(store.path, "gov").tables_id


def test_build_refuses_extraction_until_it_exists(tmp_path):
    with pytest.raises(NotImplementedError, match="extraction"):
        build_tables(make_tables_store(tmp_path / "s").path, "gov", with_extraction=True)


def test_build_counts_a_row_the_contract_rejects(tmp_path):
    store = make_tables_store(tmp_path / "s", [fr_doc("2024-00009", type_="Memorandum"),
                                               fr_doc("2024-00010", published="20240304")])
    result = build_tables(store.path, "gov")
    report = result.reports["fr_documents"]
    assert report["rows"] == 0 and [r["key"]["id"] for r in report["rejected"]] == [
        "2024-00009", "2024-00010"]
    assert any("type" in p for p in report["rejected"][0]["problems"])
    assert any("publication_date" in p for p in report["rejected"][1]["problems"])


def test_build_reads_the_contracts_of_the_directory_it_is_given(tmp_path):
    cdir = tmp_path / "contracts"
    cdir.mkdir()
    for c in load_contracts(corpus="gov").values():
        if c.table in ("fr_documents", "fr_agencies"):
            (cdir / f"{c.table}.json").write_text(c.model_dump_json(), encoding="utf-8")
    result = build_tables(make_tables_store(tmp_path / "s").path, "gov", contracts_dir=cdir)
    assert [t.table for t in result.tables] == ["fr_agencies", "fr_documents"]


def test_a_store_with_acl_rules_is_synced(tmp_path):
    store = make_tables_store(tmp_path / "s", rules=[
        {"match": {"uri_prefix": "https://"}, "access": ["public"]},
        {"match": {"uri_prefix": "file://"}, "access": ["tenant:acme"]}])
    assert acl.read_head(store.path)[1].content_snapshot == store.snapshot_id
