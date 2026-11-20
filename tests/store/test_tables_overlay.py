"""Table contracts, the row validator, value provenance and the write-once table overlay
(Phase 3 spec §5.1-§5.3). Fixture documents and stores under `tmp_path`; nothing reads `data/`
or `.cache/`."""

import copy
import hashlib
import json
import sqlite3

import pytest
from pydantic import ValidationError

from adr_eval.corpora.extract import extract_text
from adr_store import records
from adr_store.records import canonical_json
from adr_store.store import StoreError
from adr_store.tables import overlay as ov
from adr_store.tables.contracts import (
    CONTRACT_DIR,
    Contract,
    contract_sha256,
    load_contracts,
    validate_row,
)
from adr_store.tables.overlay import Manifest, TablesError, write_manifest, write_table
from adr_store.tables.provenance import (
    RESLICERS,
    RowRecord,
    ValueProv,
    json_spans,
    null_prov,
    reslice,
    sort_key,
    value_prov,
)

D = "d" * 64
SNAP = "5" * 64
CONTRACTS = load_contracts()
CONTRACT = CONTRACTS["fr_documents"]
FR_CONTRACT = json.loads((CONTRACT_DIR / "fr_documents.json").read_text(encoding="utf-8"))

FR_BODY = {
    "document_number": "2024-01234",
    "type": "Rule",
    "title": "Drawbridge Operation – Café \"Creek\"",
    "action": "Final rule.\nSee \\ below",
    "publication_date": "2024-01-17",
    "effective_on": None,
    "dates": "Effective 2024-02-01; ☃ emoji \U0001f600",
    "agencies": [{"id": 5, "name": "Homeland Security Department", "parent_id": None},
                 {"id": 9, "name": "Coast Guard", "parent_id": 5}],
    "cfr_references": [{"title": 33, "part": 117}, {"title": 46, "part": "2"}],
    "docket_ids": ["USCG-2024-0001", "FCC 19-123"],
    "nested": [[1, [2.5, None]], {"k": []}],
}
FR_TEXT = extract_text(json.dumps(FR_BODY).encode(), "json")


def value_at(obj, path):
    for step in path:
        obj = obj[step]
    return obj


def fr_row(doc_id: str, number: str, **over) -> RowRecord:
    """A valid `fr_documents` row of FR_BODY with provenance located in FR_TEXT."""
    spans = json_spans(FR_TEXT)

    def at(*path):
        return spans[path]

    row = {
        "id": number, "type": "Rule", "agency": "Coast Guard",
        "publication_date": "2024-01-17", "year": 2024, "title": FR_BODY["title"],
        "cfr_parts": ["33 CFR 117", "46 CFR 2"], "action": FR_BODY["action"],
        "effective_on": None, "status": "final_rule", "other_ids": ["FCC 19-123"],
    }
    prov = {
        "id": value_prov(doc_id, "fr.id@1", at("document_number")),
        "type": value_prov(doc_id, "fr.type@1", at("type")),
        "agency": value_prov(doc_id, "fr.agency@1", at("agencies", 1, "name")),
        "publication_date": value_prov(doc_id, "fr.publication_date@1",
                                       at("publication_date")),
        "year": value_prov(doc_id, "fr.year@1", at("publication_date")),
        "title": value_prov(doc_id, "fr.title@1", at("title")),
        "cfr_parts": [value_prov(doc_id, "fr.cfr_parts@1", at("cfr_references", 0)),
                      value_prov(doc_id, "fr.cfr_parts@1", at("cfr_references", 1))],
        "action": value_prov(doc_id, "fr.action@1", at("action")),
        "effective_on": null_prov(doc_id, "fr.effective_on@1", "absent"),
        "status": value_prov(doc_id, "fr.status@1"),
        "other_ids": [value_prov(doc_id, "fr.other_ids@1", at("docket_ids", 1))],
    }
    row.update({k: v for k, v in over.items() if k in row})
    return RowRecord(doc_id=doc_id, row=row, prov=prov)


GOOD = fr_row(D, "2024-01234")


def with_row(rec: RowRecord, changes: dict, prov: dict | None = None) -> RowRecord:
    return RowRecord(doc_id=rec.doc_id, row={**rec.row, **changes},
                     prov={**rec.prov, **(prov or {})})


ROWS = [fr_row(D, "2024-00003"), fr_row(D, "2024-00001"), fr_row(D, "2024-00002")]
BAD_ROW = with_row(GOOD, {"year": "2020"})


# -- contracts ---------------------------------------------------------------------------------

def test_committed_contracts_load_and_reference_their_own_columns():
    cs = load_contracts()
    assert set(cs) >= {"fr_documents", "fr_cfr_refs", "fr_agencies", "fr_dockets",
                       "papers", "paper_authors"}
    for c in cs.values():
        names = {col.name for col in c.columns}
        assert set(c.key) <= set(c.order) <= names and c.list_column in names


def test_contracts_load_by_corpus():
    assert set(load_contracts(corpus="gov")) == {"fr_documents", "fr_cfr_refs", "fr_agencies",
                                                 "fr_dockets"}
    assert set(load_contracts(corpus="research")) == {"papers", "paper_authors"}


def test_committed_fr_documents_contract_has_the_brief_columns():
    cols = {c.name: c for c in CONTRACT.columns}
    assert list(cols) == ["id", "type", "agency", "publication_date", "year", "title",
                          "cfr_parts", "action", "effective_on", "status", "other_ids"]
    assert cols["type"].allowed == ["Rule", "Proposed Rule", "Notice", "Presidential Document"]
    assert cols["status"].allowed == ["codified", "final_rule", "temporary_rule",
                                      "proposed_rule", "notice", "guidance", "unknown"]
    assert cols["cfr_parts"].type == "text[]" and cols["year"].type == "int"
    assert cols["publication_date"].spec_id == "fr.publication_date@1"
    assert (CONTRACT.key, CONTRACT.order, CONTRACT.list_column) == (["id"], ["id"], "id")


@pytest.mark.parametrize("change", [
    {"key": ["nosuch"]},
    {"order": ["nosuch"]},
    {"key": ["id", "year"], "order": ["id"]},
    {"list_column": "nosuch"},
    {"entities": {"nosuch": "agencies"}},
    {"key": ["title"]},  # nullable columns cannot identify a row
    {"columns": [*FR_CONTRACT["columns"], FR_CONTRACT["columns"][0]]},  # duplicate column
])
def test_a_contract_with_a_broken_reference_is_refused(change):
    with pytest.raises(ValidationError):
        Contract(**{**FR_CONTRACT, **change})


def test_a_contract_refuses_a_bad_column():
    bad = copy.deepcopy(FR_CONTRACT)
    bad["columns"][0]["spec_id"] = "fr.id"  # no version
    with pytest.raises(ValidationError):
        Contract(**bad)
    bad = copy.deepcopy(FR_CONTRACT)
    bad["columns"][0]["name"] = "Id"
    with pytest.raises(ValidationError):
        Contract(**bad)
    bad = copy.deepcopy(FR_CONTRACT)
    bad["columns"][0]["description"] = "x" * 121
    with pytest.raises(ValidationError):
        Contract(**bad)


def test_contract_sha256_is_stable_and_changes_with_the_contract():
    assert contract_sha256(CONTRACT) == contract_sha256(Contract(**FR_CONTRACT))
    bumped = Contract(**{**FR_CONTRACT, "version": 2})
    assert contract_sha256(bumped) != contract_sha256(CONTRACT)


# -- the validator -----------------------------------------------------------------------------

@pytest.mark.parametrize("row,problem", [
    ({"year": "2020"}, "year: expected int, got str"),
    ({"year": True}, "year: expected int, got bool"),
    ({"publication_date": "2024-13-01"}, "publication_date: not an ISO date"),
    ({"publication_date": "2024-1-1"}, "publication_date: not an ISO date"),
    ({"type": "Bulletin"}, "type: 'Bulletin' is not an allowed value"),
    ({"cfr_parts": "33 CFR 117"}, "cfr_parts: expected text[], got str"),
    ({"cfr_parts": ["33 CFR 117", 5]}, "cfr_parts: expected text[], got a list holding int"),
    ({"id": None}, "id: null in a non-nullable column"),
])
def test_validate_row_reports_the_problem(row, problem):
    assert problem in validate_row(CONTRACT, with_row(GOOD, row))


def test_a_null_needs_a_null_reason_and_a_list_one_prov_per_element():
    assert validate_row(CONTRACT, GOOD) == []
    null_without_reason = with_row(
        GOOD, {"title": None}, {"title": value_prov(D, "fr.title@1")})
    assert "title: null without a null reason" in validate_row(CONTRACT, null_without_reason)
    short_prov = with_row(GOOD, {}, {"cfr_parts": [GOOD.prov["cfr_parts"][0]]})
    assert "cfr_parts: 2 values, 1 provenance entries" in validate_row(CONTRACT, short_prov)


def test_validate_row_checks_the_shape_of_row_and_prov():
    extra = with_row(GOOD, {"bogus": 1})
    assert "bogus: not a column of the contract" in validate_row(CONTRACT, extra)
    missing = RowRecord(doc_id=D, row={k: v for k, v in GOOD.row.items() if k != "title"},
                        prov=GOOD.prov)
    assert "title: missing" in validate_row(CONTRACT, missing)
    no_prov = RowRecord(doc_id=D, row=GOOD.row,
                        prov={k: v for k, v in GOOD.prov.items() if k != "title"})
    assert "title: no provenance" in validate_row(CONTRACT, no_prov)
    wrong_spec = with_row(GOOD, {}, {"title": value_prov(D, "fr.action@1")})
    assert "title: provenance spec fr.action@1, contract says fr.title@1" in validate_row(
        CONTRACT, wrong_spec)
    scalar_list = with_row(GOOD, {}, {"title": [GOOD.prov["title"]]})
    assert "title: a scalar column needs one provenance entry, got a list" in validate_row(
        CONTRACT, scalar_list)
    rejected_value = with_row(GOOD, {}, {"title": null_prov(D, "fr.title@1", "ungrounded",
                                                            rejected=True)})
    assert "title: a value with a null reason" in validate_row(CONTRACT, rejected_value)
    reasoned_null = with_row(GOOD, {"title": None},
                             {"title": null_prov(D, "fr.title@1", "ungrounded", rejected=True)})
    assert validate_row(CONTRACT, reasoned_null) == []


def test_validate_row_checks_numeric_and_bool_types():
    agencies = CONTRACTS["fr_agencies"]
    row = {"id": "a", "position": 0, "name": "Coast Guard", "fr_agency_id": 1.5,
           "parent_id": None, "specific": 1}
    prov = {c.name: value_prov(D, c.spec_id) for c in agencies.columns}
    prov["parent_id"] = null_prov(D, "fr.agency_parent_id@1", "absent")
    problems = validate_row(agencies, RowRecord(doc_id=D, row=row, prov=prov))
    assert "fr_agency_id: expected int, got float" in problems
    assert "specific: expected bool, got int" in problems


def test_value_prov_invariants():
    with pytest.raises(ValidationError):
        ValueProv(doc_id=D, spec_id="fr.title@1", status="verified", null_reason="absent")
    with pytest.raises(ValidationError):   # no status and no reason
        ValueProv(doc_id=D, spec_id="fr.title@1", status=None)
    with pytest.raises(ValidationError):   # rejected values are null with a reason
        ValueProv(doc_id=D, spec_id="fr.title@1", status="rejected")
    with pytest.raises(ValidationError):   # one end of a span
        ValueProv(doc_id=D, spec_id="fr.title@1", status="verified", start=1)
    with pytest.raises(ValidationError):   # reversed span
        ValueProv(doc_id=D, spec_id="fr.title@1", status="verified", start=5, end=2)
    with pytest.raises(ValidationError):   # a verified value passed every check
        ValueProv(doc_id=D, spec_id="fr.title@1", status="verified",
                  checks_failed=["unit"])
    with pytest.raises(ValidationError):
        ValueProv(doc_id=D, spec_id="title", status="verified")
    ok = ValueProv(doc_id=D, spec_id="fr.title@1", status="auto-accepted", start=1, end=3,
                   checks_failed=["unit"], regex_agrees=False)
    assert ok.checks_failed == ["unit"]


def test_value_and_null_prov_constructors():
    v = value_prov(D, "fr.title@1", (3, 9), quote="abc")
    assert (v.status, v.start, v.end, v.quote, v.null_reason) == ("verified", 3, 9, "abc", None)
    assert value_prov(D, "fr.status@1").start is None
    n = null_prov(D, "fr.title@1", "absent")
    assert (n.status, n.null_reason, n.start) == (None, "absent", None)
    r = null_prov(D, "fr.title@1", "ungrounded", rejected=True)
    assert (r.status, r.null_reason) == ("rejected", "ungrounded")


# -- spans and re-slicing ----------------------------------------------------------------------

def test_json_spans_slice_back_to_every_value():   # nested lists, unicode, escapes, null
    text = extract_text(json.dumps(FR_BODY).encode(), "json")
    spans = json_spans(text)
    assert () in spans and ("nested", 0, 1, 1) in spans and ("effective_on",) in spans
    for path, (s, e) in spans.items():
        assert json.loads(text[s:e]) == value_at(FR_BODY, path)
    assert text[slice(*spans[("effective_on",)])] == "null"


def test_json_spans_of_scalars_and_empty_containers():
    for obj in (5, "xé", None, [], {}, [[]], {"a": {}}):
        text = json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False)
        for path, (s, e) in json_spans(text).items():
            assert json.loads(text[s:e]) == value_at(obj, path)


def test_reslice_fr_values():
    spans = json_spans(FR_TEXT)

    def check(spec, path, value):
        return reslice(FR_TEXT, value_prov(D, spec, spans[path]), value)

    assert check("fr.title@1", ("title",), FR_BODY["title"])
    assert not check("fr.title@1", ("title",), "another title")
    assert check("fr.year@1", ("publication_date",), 2024)
    assert not check("fr.year@1", ("publication_date",), "2024")
    assert check("fr.cfr_parts@1", ("cfr_references", 0), "33 CFR 117")
    assert check("fr.cfr_parts@1", ("cfr_references", 1), "46 CFR 2")   # part as a string
    assert check("fr.other_ids@1", ("docket_ids", 1), "FCC 19-123")
    assert check("fr.effective_on@1", ("effective_on",), None)
    assert not check("fr.title@1", ("action",), FR_BODY["title"])
    assert not check("fr.unknown_spec@1", ("title",), FR_BODY["title"])
    assert not reslice(FR_TEXT, value_prov(D, "fr.title@1"), "x")   # no span to re-slice
    assert not reslice(FR_TEXT, value_prov(D, "fr.title@1", (0, len(FR_TEXT) + 5)), "x")
    quoted = value_prov(D, "fr.title@1", spans[("title",)], quote="not the slice")
    assert not reslice(FR_TEXT, quoted, FR_BODY["title"])


def test_reslice_manifest_rows():
    header = ("research,topic,also_in,type,title,authors,year,venue,url,pdf_url,arxiv_id,"
              "doi,license,status,local_file,relevance")
    line1 = ("r,t,x;y,paper,\"A, B\nline\",\"Ann, Bob, et al.\",2025,arXiv,u,p,2505.1,,"
             "CC-BY-4.0,downloaded,f.pdf,note")
    line2 = "r,t,,web,T2,Cy,,V,https://u/2,,,10.1/x,MIT,no_pdf_link,,n"
    text = f"{header}\n{line1}\n{line2}\n"
    s1 = len(header) + 1
    e1 = s1 + len(line1)
    s2, e2 = e1 + 1, e1 + 1 + len(line2)
    assert RESLICERS["papers.title"](text, s1, e1) == "A, B\nline"
    assert RESLICERS["papers.year"](text, s1, e1) == 2025
    assert RESLICERS["papers.year"](text, s2, e2) is None
    assert RESLICERS["papers.also_in_list"](text, s1, e1) == ["x", "y"]
    assert RESLICERS["papers.also_in_list"](text, s2, e2) == []
    assert RESLICERS["papers.id"](text, s1, e1) == "2505.1"
    assert RESLICERS["papers.id"](text, s2, e2) == "10.1/x"
    assert reslice(text, value_prov(D, "papers.doi@1", (s2, e2)), "10.1/x")
    assert not reslice(text, value_prov(D, "papers.doi@1", (s1, e1)), "10.1/x")


def test_the_sort_key_orders_like_sqlite():
    c = Contract(**{**FR_CONTRACT, "key": ["id"], "order": ["id", "year"]})
    values = [None, False, True, -3, 0, 2, 2.5, "", "A", "a", "b", "é", "\U0001f600"]
    rows = [{"id": v, "year": 1} for v in values]
    conn = sqlite3.connect(":memory:")
    conn.execute("create table t (v)")
    conn.executemany("insert into t values (?)", [(v,) for v in values])
    in_sql = [r[0] for r in conn.execute("select v from t order by v")]
    conn.close()
    in_py = [r["id"] for r in sorted(reversed(rows), key=lambda r: sort_key(c, r))]
    assert in_py == in_sql
    assert sort_key(c, {"id": True, "year": 1}) == sort_key(c, {"id": 1, "year": 1})
    # lists compare by their stored canonical JSON text
    lc = Contract(**{**FR_CONTRACT, "order": ["id", "cfr_parts"]})
    a = sort_key(lc, {"id": "x", "cfr_parts": ["a", "b"]})
    b = sort_key(lc, {"id": "x", "cfr_parts": ["a", "c"]})
    assert a < b
    assert sort_key(lc, {"id": "x", "cfr_parts": []}) > b   # '[]' follows '["' as text does


def test_sort_key_breaks_ties_on_later_order_columns():
    c = CONTRACTS["fr_agencies"]
    r1, r2 = {"id": "a", "position": 1}, {"id": "a", "position": 0}
    assert sort_key(c, r2) < sort_key(c, r1)


# -- the overlay -------------------------------------------------------------------------------

def test_write_table_is_write_once_and_named_by_its_id(tmp_path):
    tf = write_table(tmp_path, SNAP, CONTRACT, ROWS, {})
    path = tmp_path / "tables" / SNAP / tf.file
    assert tf.file == f"fr_documents-v1-{tf.sha256[:16]}.jsonl"
    assert tf.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert (tf.table, tf.kind, tf.contract_version, tf.rows, tf.rejected) == (
        "fr_documents", "data", 1, 3, 0)
    assert tf.contract_sha256 == contract_sha256(CONTRACT)
    assert write_table(tmp_path, SNAP, CONTRACT, ROWS, {}) == tf
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(TablesError):
        write_table(tmp_path, SNAP, CONTRACT, ROWS, {})


def test_tables_error_is_a_store_error():
    assert issubclass(TablesError, StoreError)


def test_rows_are_stored_in_contract_order_and_rejected_rows_counted(tmp_path):
    tf = write_table(tmp_path, SNAP, CONTRACT, [*reversed(ROWS), BAD_ROW], report := {})
    lines = (tmp_path / "tables" / SNAP / tf.file).read_text().splitlines()
    assert [json.loads(x)["row"]["id"] for x in lines] == sorted(r.row["id"] for r in ROWS)
    assert tf.rejected == 1 and report["rejected"][0]["problems"]
    assert report["rejected"][0]["key"] == {"id": "2024-01234"}
    assert "year: expected int, got str" in report["rejected"][0]["problems"]


def test_lines_are_canonical_row_records_and_the_bytes_do_not_depend_on_input_order(tmp_path):
    a = write_table(tmp_path / "a", SNAP, CONTRACT, ROWS, {})
    b = write_table(tmp_path / "b", SNAP, CONTRACT, list(reversed(ROWS)), {})
    assert a == b
    data = (tmp_path / "a" / "tables" / SNAP / a.file).read_bytes()
    first = data.split(b"\n")[0] + b"\n"
    assert canonical_json(RowRecord.model_validate_json(first)) == first
    assert data.endswith(b"\n") and b"\n\n" not in data


def test_a_second_row_with_the_same_key_is_rejected(tmp_path):
    twin = with_row(ROWS[0], {"title": "Another title"})
    tf = write_table(tmp_path, SNAP, CONTRACT, [ROWS[0], twin], report := {})
    assert tf.rows == 1 and tf.rejected == 1
    assert report["rejected"][0]["problems"] == ["duplicate key"]
    # which of the two survives does not depend on the order they came in
    tf2 = write_table(tmp_path / "x", SNAP, CONTRACT, [twin, ROWS[0]], {})
    assert tf2 == tf


def test_the_report_counts_rows_and_null_reasons_by_column(tmp_path):
    tf = write_table(tmp_path, SNAP, CONTRACT, ROWS, report := {})
    assert report["rows"] == 3 and report["table"] == "fr_documents"
    assert report["null_reasons"] == {"effective_on": {"absent": 3}}
    rp = tmp_path / "tables" / SNAP / tf.file.replace(".jsonl", ".report.json")
    assert json.loads(rp.read_text(encoding="utf-8")) == report
    assert rp.name != tf.file and rp.read_bytes() != (tmp_path / "tables" / SNAP / tf.file
                                                      ).read_bytes()


def test_an_empty_table_is_written(tmp_path):
    tf = write_table(tmp_path, SNAP, CONTRACT, [], {})
    assert tf.rows == 0 and tf.sha256 == hashlib.sha256(b"").hexdigest()


def manifest_of(tmp_path, tables, **kw) -> Manifest:
    return Manifest(format_version="0.1", snapshot=SNAP, corpus="gov", applicability=None,
                    extraction=None, tables=sorted(tables, key=lambda t: t.table), **kw)


def build(tmp_path):
    t1 = write_table(tmp_path, SNAP, CONTRACT, ROWS, {})
    refs = CONTRACTS["fr_cfr_refs"]
    t2 = write_table(tmp_path, SNAP, refs, [], {})
    m = manifest_of(tmp_path, [t1, t2])
    tid, path = write_manifest(tmp_path, m)
    return m, tid, path, t1, t2


def test_manifest_id_is_its_sha256_and_load_checks_every_file(tmp_path):
    m, tid, path, t1, t2 = build(tmp_path)
    assert tid == hashlib.sha256(path.read_bytes()).hexdigest()
    assert path == tmp_path / "tables" / SNAP / f"tables-{tid[:16]}.json"
    assert path.read_bytes() == canonical_json(m)
    assert ov.manifest_path(tmp_path, tid) == path
    assert ov.load_manifest(tmp_path, tid) == m
    assert write_manifest(tmp_path, m) == (tid, path)   # the same bytes again: a no-op
    rows = ov.load_rows(tmp_path, m, "fr_documents")
    assert [r.row["id"] for r in rows] == sorted(r.row["id"] for r in ROWS)
    assert ov.load_rows(tmp_path, m, "fr_cfr_refs") == []
    with pytest.raises(TablesError, match="nosuch"):
        ov.load_rows(tmp_path, m, "nosuch")
    victim = tmp_path / "tables" / SNAP / t1.file
    victim.write_bytes(victim.read_bytes().replace(b"Rule", b"Rulz", 1))
    with pytest.raises(TablesError, match="fr_documents"):
        ov.load_manifest(tmp_path, tid)
    with pytest.raises(TablesError, match="fr_documents"):
        ov.load_rows(tmp_path, m, "fr_documents")


def test_a_missing_table_file_is_named(tmp_path):
    m, tid, _, t1, t2 = build(tmp_path)
    (tmp_path / "tables" / SNAP / t2.file).unlink()
    with pytest.raises(TablesError, match="fr_cfr_refs"):
        ov.load_manifest(tmp_path, tid)


def test_manifest_path_refuses_an_unknown_or_altered_manifest(tmp_path):
    m, tid, path, *_ = build(tmp_path)
    assert ov.manifest_path(tmp_path, "0" * 64) is None
    path.write_bytes(path.read_bytes().replace(b"gov", b"xyz", 1))
    assert ov.manifest_path(tmp_path, tid) is None
    with pytest.raises(TablesError):
        ov.load_manifest(tmp_path, tid)


def test_write_manifest_refuses_other_bytes_under_the_same_name(tmp_path):
    m, tid, path, *_ = build(tmp_path)
    path.write_bytes(b"{}")
    with pytest.raises(TablesError):
        write_manifest(tmp_path, m)


def test_manifest_tables_must_be_sorted_and_distinct():
    t = ov.TableFile(table="b", kind="data", contract_version=1, contract_sha256="0" * 64,
                     file="b-v1-" + "1" * 16 + ".jsonl", sha256="1" * 64, rows=0, rejected=0)
    a = t.model_copy(update={"table": "a", "file": "a-v1-" + "1" * 16 + ".jsonl"})
    with pytest.raises(ValidationError):
        Manifest(format_version="0.1", snapshot=SNAP, corpus="gov", applicability=None,
                 extraction=None, tables=[t, a])
    with pytest.raises(ValidationError):
        Manifest(format_version="0.1", snapshot=SNAP, corpus="gov", applicability=None,
                 extraction=None, tables=[t, t])
    with pytest.raises(ValidationError):   # the file name is its table, version and id
        ov.TableFile(table="b", kind="data", contract_version=1, contract_sha256="0" * 64,
                     file="../x.jsonl", sha256="1" * 64, rows=0, rejected=0)


def test_head_names_a_loadable_manifest_or_nothing(tmp_path):
    assert ov.read_head(tmp_path) is None
    m, tid, path, t1, _ = build(tmp_path)
    assert ov.read_head(tmp_path) is None            # nothing moved HEAD yet
    ov._set_head(tmp_path, tid)
    assert (tmp_path / "tables" / "HEAD").read_text() == tid + "\n"
    assert ov.read_head(tmp_path) == tid
    (tmp_path / "tables" / "HEAD").write_text("0" * 64 + "\n")      # a missing manifest
    assert ov.read_head(tmp_path) is None
    (tmp_path / "tables" / "HEAD").write_text("not a hash\n")
    assert ov.read_head(tmp_path) is None
    ov._set_head(tmp_path, tid)
    victim = tmp_path / "tables" / SNAP / t1.file                    # a tampered table
    victim.write_bytes(victim.read_bytes() + b"\n")
    assert ov.read_head(tmp_path) is None
    victim.write_bytes(victim.read_bytes()[:-1])
    assert ov.read_head(tmp_path) == tid
    path.write_bytes(b"{}")                                         # a tampered manifest
    assert ov.read_head(tmp_path) is None


def test_set_head_refuses_a_manifest_that_does_not_load(tmp_path):
    with pytest.raises(TablesError):
        ov._set_head(tmp_path, "0" * 64)
    assert ov.read_head(tmp_path) is None


# -- schemas -----------------------------------------------------------------------------------

def test_the_three_table_schemas_are_registered():
    names = records.schemas()
    assert {"table-contract.schema.json", "table-row.schema.json",
            "table-manifest.schema.json"} <= set(names)


# -- Task 2 follow-ups to Task 1 ---------------------------------------------------------------

def test_manifest_row_reads_only_the_header_line_of_the_manifest():
    class Guarded(str):
        def splitlines(self, *a, **k):
            raise AssertionError("manifest_row must not split the whole manifest into lines")

    from adr_store.tables.provenance import manifest_row
    header = "a,b\r"      # a CRLF manifest
    text = Guarded(f"{header}\n1,2\r\n3,4\r\n")
    assert manifest_row(text, len(header) + 1, len(header) + 4) == {"a": "1", "b": "2"}


def test_a_real_beyond_float_range_is_a_problem_not_an_exception():
    from adr_store.tables.contracts import _type_problem
    assert _type_problem("real", 10**400) == "real outside float range"
    assert _type_problem("real", 10**300) is None
    assert _type_problem("real", float("inf")) == "real is not finite"


@pytest.mark.parametrize("name", ["Fr", "1x", "a-b", "", "a b"])
def test_a_table_file_names_a_valid_table(name):
    with pytest.raises(ValidationError):
        ov.TableFile(table=name, kind="data", contract_version=1, contract_sha256="a" * 64,
                     file=f"{name}-v1-{'b' * 16}.jsonl", sha256="b" * 64, rows=0, rejected=0)


def test_the_federal_register_agency_id_spec_is_fr_agency_id():
    col = {c.name: c for c in CONTRACTS["fr_agencies"].columns}["fr_agency_id"]
    assert col.spec_id == "fr.fr_agency_id@1"
    assert "fr.fr_agency_id" in RESLICERS and "fr.agency_id" not in RESLICERS
