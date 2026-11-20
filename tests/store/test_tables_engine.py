"""The query engine (Phase 3 spec §5.4): `query_table` compiled with the semantics of
`golden/records.py`, over in-memory databases built from table overlays. Fixture stores under
`tmp_path`; nothing reads `data/` or `.cache/`."""

import json
import random
import sqlite3
from types import SimpleNamespace

import pytest

from adr_eval.corpora.gov import GovAdapter
from adr_eval.corpora.research import ResearchAdapter
from adr_eval.golden.records import exec_gold_query
from adr_eval.models import GoldQuery
from adr_store.tables import overlay as ov
from adr_store.tables.build import build_tables
from adr_store.tables.contracts import load_contracts
from adr_store.tables.engine import (
    DEFAULT_TABLE,
    OPERATORS,
    OPS,
    QUERY_LIMIT_MAX,
    QueryError,
    ViewDB,
    compile_query,
    from_gold_query,
    run_query,
)
from adr_store.tables.loaders import fr_tables
from adr_store.tables.overlay import TablesError
from tests.store.tables_fixtures import (
    FCC,
    FR_DOCS,
    MANIFEST,
    fr_doc,
    loaded_of,
    make_tables_store,
)

EXTRA_DOCS = [
    fr_doc("2019-00008", title="Straße der Brücke Regulation", published="2019-05-06"),
    fr_doc("2021-00009", type_="Proposed Rule", published="2021-01-02", agencies=[FCC],
           cfr=({"title": 47, "part": "73"}, {"title": 33, "part": "117"})),
]
N_2024 = len(FR_DOCS)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    path = tmp_path_factory.mktemp("engine") / "store"
    store = make_tables_store(path, [*FR_DOCS, *EXTRA_DOCS, MANIFEST])
    out = SimpleNamespace(store=store, db={}, records={}, manifest={})
    loaded = loaded_of(store)
    out.records["gov"] = GovAdapter().records(loaded)
    out.records["research"] = ResearchAdapter().records(loaded)
    for corpus in ("gov", "research"):
        result = build_tables(path, corpus)
        m = ov.load_manifest(path, result.tables_id)
        out.manifest[corpus] = (m, result.tables_id)
        out.db[corpus] = ViewDB.build(path, m, result.tables_id, None)
    return out


@pytest.fixture
def gov_db(world):
    return world.db["gov"]


@pytest.fixture
def research_db(world):
    return world.db["research"]


def count(db, filters, table="fr_documents"):
    return run_query(db, table, filters, "count").count


# -- the oracle: records.py ------------------------------------------------------------------

def _filter_fields(rows):
    return sorted(k for k in rows[0] if not k.startswith("_"))


def _perturbed(v, rng):
    """A filter value built from a record value: the value itself, or a wrong-typed, shifted
    or re-cased variant of it (JSON-expressible values only)."""
    if isinstance(v, bool) or v is None:
        return rng.choice([0, "x"])
    if isinstance(v, int):
        return rng.choice([v, v, v + 1, v - 1, float(v), str(v)])
    if isinstance(v, str):
        return rng.choice([v, v, v.upper(), v.lower(), v[: len(v) // 2], v + "x", 7, ""])
    if isinstance(v, list):
        return rng.choice([v, v, [x.lower() for x in v], v[:1], ["nope"]])
    return v


def _draw_filter(rows, fields, rng):
    filters = {}
    for _ in range(rng.randint(1, 3)):
        field = rng.choice(fields)
        v = rng.choice(rows)[field]
        op = rng.choice(["", "", "in", "gte", "lte", "contains"])
        if op in ("gte", "lte") and isinstance(v, list):
            op = ""   # records.py orders lists lexicographically; the typed engine never matches
        if op == "in":
            val = rng.choice([[_perturbed(v, rng), _perturbed(rng.choice(rows)[field], rng)],
                              [], _perturbed(v, rng)])
        elif op == "contains":
            if isinstance(v, list):
                val = rng.choice(v + ["x"]) if v else "x"
            elif isinstance(v, str):
                a = rng.randint(0, len(v))
                val = rng.choice([v[a:a + 4], v[a:a + 4].upper(), v[a:a + 4].swapcase()])
            else:
                val = rng.choice(["20", 2, "none"])
        else:
            val = _perturbed(v, rng)
        filters[field if op == "" else f"{field}__{op}"] = val
    op = rng.choice(["count", "list", "lookup"])
    if op == "lookup":
        filters["_field"] = rng.choice(fields)
    return filters, op


def _oracle(db, corpus, rows, filters, op):
    # a gold query with values the pydantic model would refuse (a float list, ...) is built
    # unvalidated: exec_gold_query reads only `op` and `filters`
    gq = GoldQuery.model_construct(store="typed_db", op=op, filters=filters)
    out = run_query(db, DEFAULT_TABLE[corpus], {k: v for k, v in filters.items()
                                                 if not k.startswith("_")}, op,
                    fields=[filters["_field"]] if op == "lookup" else None)
    got = {"count": out.count, "list": out.ids, "lookup": out.value}[op]
    return got, exec_gold_query(gq, rows)


@pytest.mark.parametrize("corpus", ["gov", "research"])
def test_query_table_equals_records_on_drawn_filters(world, corpus):
    rng = random.Random(20261120)
    rows = world.records[corpus]
    fields = _filter_fields(rows)
    seen = {"count": 0, "list": 0, "lookup": 0}
    nonzero = 0
    for _ in range(500):
        filters, op = _draw_filter(rows, fields, rng)
        got, want = _oracle(world.db[corpus], corpus, rows, filters, op)
        assert got == want, (filters, op)
        seen[op] += 1
        nonzero += bool(want)
    assert min(seen.values()) > 100 and nonzero > 100   # the draws exercise real matches


# -- semantics -------------------------------------------------------------------------------

def test_text_equality_is_exact_and_contains_is_casefolded(gov_db):
    assert count(gov_db, {"type": "rule"}) == 0
    assert count(gov_db, {"type": "Rule"}) == N_2024 - 2 + 1
    assert count(gov_db, {"title__contains": "STRASSE"}) == 1        # "Straße"
    assert count(gov_db, {"title__contains": "straße"}) == 1
    assert count(gov_db, {"title__contains": "drawbridge"}) == 4
    assert count(gov_db, {"cfr_parts__contains": "33 cfr 117"}) == 5


def test_a_null_cell_never_matches_a_text_comparison(gov_db):
    # records.py: a missing title is not a string; str(None) is never what is searched
    assert count(gov_db, {"title__contains": "none"}) == 0
    assert count(gov_db, {"title__contains": ""}) == len(FR_DOCS) + 2 - 1
    assert count(gov_db, {"title": "None"}) == 0
    assert count(gov_db, {"title__ne": "x"}) == len(FR_DOCS) + 2 - 1
    assert count(gov_db, {"title__isnull": True}) == 1


def test_casefold_function_returns_null_for_null(gov_db):
    assert gov_db.execute("SELECT casefold(NULL), casefold('Straße'), casefold(5)") == [
        (None, "strasse", "5")]


def test_no_type_coercion_and_the_clause_is_named(gov_db):
    out = run_query(gov_db, "fr_documents", {"year": "2024"}, "count")
    assert out.count == 0 and out.never_matches == [
        "year: a text value never matches an int column"]
    assert count(gov_db, {"year": 2024.0}) == N_2024
    assert count(gov_db, {"year": 2024}) == N_2024
    assert count(gov_db, {"year": True}) == 0            # a bool is no number
    out = run_query(gov_db, "fr_documents", {"title__gte": 5}, "count")
    assert out.count == 0 and out.never_matches == [
        "title__gte: an int value never matches a text column"]
    out = run_query(gov_db, "fr_documents", {"year__contains": 20}, "count")
    assert out.count == 0 and out.never_matches == [
        "year__contains: contains never matches an int column"]


def test_comparisons_follow_the_column_type(gov_db):
    assert count(gov_db, {"year__gte": 2021}) == N_2024 + 1
    assert count(gov_db, {"year__lte": 2020}) == 1
    assert count(gov_db, {"publication_date__gte": "2021-01-02"}) == N_2024 + 1
    assert count(gov_db, {"year__lte": "2020"}) == 0
    assert count(gov_db, {"cfr_parts__gte": ["33 CFR 117"]}) == 0
    assert count(gov_db, {"year__gte": 10**30}) == 0     # beyond 64 bits: no overflow error
    assert count(gov_db, {"year__lte": 10**30}) == N_2024 + 2
    assert count(gov_db, {"year__gte": -(10**30)}) == N_2024 + 2


def test_nulls_never_match_comparisons(research_db):
    t = "papers"
    total = run_query(research_db, t, {}, "count").count
    assert total == 5
    assert count(research_db, {"year__isnull": True}, t) == 2
    assert count(research_db, {"year__gte": 0}, t) == 3
    assert count(research_db, {"year__lte": 9999}, t) == 3
    assert count(research_db, {"year__ne": 2025}, t) == 2     # null rows are not "not 2025"
    assert count(research_db, {"year__in": [2025, 2024]}, t) == 2
    assert count(research_db, {"year": 2025}, t) == 1


def test_isnull_and_contains_any(gov_db):
    assert count(gov_db, {"agency__isnull": True}) == 1
    assert count(gov_db, {"agency__isnull": False}) == len(FR_DOCS) + 2 - 1
    with pytest.raises(QueryError, match=r"^agency__isnull: isnull takes true or false"):
        run_query(gov_db, "fr_documents", {"agency__isnull": "yes"}, "count")
    assert count(gov_db, {"cfr_parts__contains_any": ["33 cfr 165", "47 CFR 73"]}) == 4
    assert count(gov_db, {"title__contains_any": ["straße", "TELEVISION"]}) == 3
    assert count(gov_db, {"title__contains_any": []}) == 0
    out = run_query(gov_db, "fr_documents", {"year__contains_any": ["20"]}, "count")
    assert out.count == 0 and out.never_matches == [
        "year__contains_any: contains never matches an int column"]
    with pytest.raises(QueryError, match=r"^type__contains_any: contains_any takes a list"):
        run_query(gov_db, "fr_documents", {"type__contains_any": "Rule"}, "count")


def test_ne_needs_a_compatible_non_null_cell(gov_db):
    assert count(gov_db, {"type__ne": "Rule"}) == 3
    assert count(gov_db, {"agency__ne": "Coast Guard"}) == 4   # the null agency is not counted
    out = run_query(gov_db, "fr_documents", {"type__ne": 5}, "count")
    assert out.count == 0 and out.never_matches


def test_in_with_a_non_list_never_matches(gov_db):
    out = run_query(gov_db, "fr_documents", {"type__in": "Rule"}, "count")
    assert out.count == 0 and out.never_matches == [
        "type__in: a non-list value never matches an in clause"]
    assert count(gov_db, {"type__in": ["Rule", "Proposed Rule", 5]}) == N_2024 + 2
    assert count(gov_db, {"type__in": []}) == 0
    out = run_query(gov_db, "fr_documents", {"type__in": [1, 2]}, "count")
    assert out.count == 0 and out.never_matches


def test_list_columns_equal_whole_lists(gov_db):
    assert count(gov_db, {"cfr_parts": ["33 CFR 117", "33 CFR 165"]}) == 1
    assert count(gov_db, {"cfr_parts": []}) == 1
    assert count(gov_db, {"cfr_parts": "33 CFR 117"}) == 0


def test_unknown_column_and_operator_are_errors_naming_them(gov_db):
    with pytest.raises(QueryError, match=r"^unknown column 'yeer' in table fr_documents$"):
        run_query(gov_db, "fr_documents", {"yeer": 1}, "count")
    with pytest.raises(QueryError, match=r"^unknown column 'yeer' in table fr_documents$"):
        run_query(gov_db, "fr_documents", {"yeer__gte": 1}, "count")
    with pytest.raises(QueryError, match=r"^unknown operator 'between' in 'year__between'$"):
        run_query(gov_db, "fr_documents", {"year__between": 1}, "count")
    with pytest.raises(QueryError, match=r"^unknown column '_doc_id' in table fr_documents$"):
        run_query(gov_db, "fr_documents", {"_doc_id": "x"}, "count")
    with pytest.raises(QueryError, match=r"^unknown table 'nope'$"):
        run_query(gov_db, "nope", {}, "count")
    with pytest.raises(QueryError, match=r"^unknown op 'sum'"):
        run_query(gov_db, "fr_documents", {}, "sum")
    with pytest.raises(QueryError, match=r"^unknown column 'nope' in table fr_documents$"):
        run_query(gov_db, "fr_documents", {}, "lookup", fields=["nope"])
    with pytest.raises(QueryError, match=r"^unknown column 'nope' in table fr_documents$"):
        run_query(gov_db, "fr_documents", {}, "lookup", order=["-nope"])


def test_a_clause_after_a_never_clause_is_still_checked(gov_db):
    with pytest.raises(QueryError, match="unknown column 'yeer'"):
        run_query(gov_db, "fr_documents", {"year": "x", "yeer": 1}, "count")


def test_limit_and_count_by_arguments_are_checked(gov_db):
    for bad in (0, -1, QUERY_LIMIT_MAX + 1, True, "5"):
        with pytest.raises(QueryError, match="^limit must be an integer from 1 to 1000"):
            run_query(gov_db, "fr_documents", {}, "lookup", limit=bad)
    with pytest.raises(QueryError, match="^count_by takes exactly one field"):
        run_query(gov_db, "fr_documents", {}, "count_by")
    with pytest.raises(QueryError, match="^count_by takes exactly one field"):
        run_query(gov_db, "fr_documents", {}, "count_by", fields=["type", "year"])


def test_the_operator_and_op_vocabulary():
    assert OPS == ("count", "list", "lookup", "count_by")
    assert OPERATORS == ("", "in", "gte", "lte", "contains", "ne", "isnull", "contains_any")


def test_values_are_parameters_not_sql(world):
    c = world.db["gov"].contracts["fr_documents"]
    hostile = "x'; DROP TABLE fr_documents; --"
    compiled = compile_query(c, {"title__contains": hostile, "type": hostile}, "count")
    assert hostile.casefold() not in compiled.sql and hostile not in compiled.sql
    assert hostile in compiled.params and compiled.sql.count(";") == 0
    assert run_query(world.db["gov"], "fr_documents", {"type": hostile}, "count").count == 0


def test_the_database_is_read_only(gov_db):
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        gov_db.conn.execute("DELETE FROM fr_documents")


def test_no_declared_types_so_no_affinity(gov_db):
    rows = gov_db.execute("SELECT typeof(year), typeof(cfr_parts), typeof(_prov_year) "
                          "FROM fr_documents LIMIT 1")
    assert rows == [("integer", "text", "text")]


# -- the ops ---------------------------------------------------------------------------------

def test_list_returns_sorted_unique_ids(research_db):
    out = run_query(research_db, "papers", {"type": "paper"}, "list")
    assert out.ids == ["10.1000/x", "10.1000/y", "2501.00001"]   # the duplicated id once
    assert out.count is None and out.rows is None
    assert run_query(research_db, "papers", {"type": "none"}, "list").ids == []


def test_lookup_value_follows_the_records_rule(gov_db):
    one = run_query(gov_db, "fr_documents", {"id": "2024-00001"}, "lookup", fields=["year"])
    assert one.value == 2024 and len(one.rows) == 1 and not one.truncated
    assert one.rows[0]["row"] == {"year": 2024}
    two = run_query(gov_db, "fr_documents", {"type": "Proposed Rule"}, "lookup",
                    fields=["year"])
    assert two.value is None and len(two.rows) == 3
    none = run_query(gov_db, "fr_documents", {"id": "nope"}, "lookup", fields=["year"])
    assert none.value is None and none.rows == []
    nofield = run_query(gov_db, "fr_documents", {"id": "2024-00001"}, "lookup")
    assert nofield.value is None and nofield.rows[0]["row"]["id"] == "2024-00001"
    assert run_query(gov_db, "fr_documents", {"id": "2024-00002"}, "lookup",
                     fields=["title"]).value is None            # a null field is None
    assert run_query(gov_db, "fr_documents", {"id": "2024-00001"}, "lookup",
                     fields=["cfr_parts"]).value == ["33 CFR 117", "33 CFR 165"]


def test_lookup_orders_limits_and_truncates(gov_db):
    out = run_query(gov_db, "fr_documents", {}, "lookup", fields=["id"], order=["-year", "id"])
    ids = [r["row"]["id"] for r in out.rows]
    assert ids[:2] == ["2024-00001", "2024-00002"] and ids[-2:] == ["2021-00009", "2019-00008"]
    cut = run_query(gov_db, "fr_documents", {}, "lookup", fields=["id"], limit=3)
    assert [r["row"]["id"] for r in cut.rows] == ["2019-00008", "2021-00009", "2024-00001"]
    assert cut.truncated
    exact = run_query(gov_db, "fr_documents", {}, "lookup", fields=["id"], limit=N_2024 + 2)
    assert not exact.truncated and len(exact.rows) == N_2024 + 2


def test_count_by_groups_list_elements_and_nulls_first(gov_db, research_db):
    by_agency = run_query(gov_db, "fr_documents", {}, "count_by", fields=["agency"]).groups
    assert by_agency[0] == {"value": None, "count": 1}
    assert [g["value"] for g in by_agency[1:]] == sorted(g["value"] for g in by_agency[1:])
    assert {g["value"]: g["count"] for g in by_agency} == {
        None: 1, "COAST GUARD": 1, "Coast Guard": 4, "Federal Communications Commission": 3}
    by_part = run_query(gov_db, "fr_documents", {}, "count_by", fields=["cfr_parts"]).groups
    assert by_part == [{"value": "33 CFR 117", "count": 5},
                       {"value": "33 CFR 117a", "count": 1},
                       {"value": "33 CFR 165", "count": 1},
                       {"value": "47 CFR 73", "count": 3}]
    by_year = run_query(research_db, "papers", {}, "count_by", fields=["year"]).groups
    assert by_year == [{"value": None, "count": 2}, {"value": 2024, "count": 1},
                       {"value": 2025, "count": 1}, {"value": 2026, "count": 1}]
    filtered = run_query(gov_db, "fr_documents", {"type": "Rule"}, "count_by",
                         fields=["year"]).groups
    assert filtered == [{"value": 2019, "count": 1}, {"value": 2024, "count": 5}]


def test_rows_carry_provenance_in_a_total_order(gov_db):
    out = run_query(gov_db, "fr_documents", {}, "lookup")
    keys = [r["row"]["id"] for r in out.rows]
    assert keys == sorted(keys) and len(keys) == len(set(keys))
    first = out.rows[0]
    assert set(first["prov"]) == {c.name for c in gov_db.contracts["fr_documents"]
                                  .stored_columns}
    assert first["doc_id"] and first["prov"]["year"]["spec_id"].startswith("fr.")
    assert isinstance(first["prov"]["cfr_parts"], list)          # one entry per element
    # a null value carries its reason
    nulls = run_query(gov_db, "fr_documents", {"id": "2024-00002"}, "lookup",
                      fields=["title"]).rows[0]
    assert nulls["prov"]["title"]["null_reason"] == "absent"
    # the same query twice gives the same rows
    assert run_query(gov_db, "fr_documents", {}, "lookup").rows == out.rows


def test_every_table_orders_by_the_contract_order(world):
    for corpus in ("gov", "research"):
        db = world.db[corpus]
        for name, c in db.contracts.items():
            out = run_query(db, name, {}, "lookup", limit=QUERY_LIMIT_MAX)
            keys = [tuple(_sqlite_key(r["row"][k]) for k in c.order) for r in out.rows]
            assert keys == sorted(keys), name


def _sqlite_key(v):
    if v is None:
        return (0,)
    if isinstance(v, (bool, int, float)):
        return (1, v)
    if isinstance(v, str):
        return (2, v)
    return (2, json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


# -- views -----------------------------------------------------------------------------------

def _docs_of(world, ids):
    rows = {r["id"]: r["_doc_id"] for r in world.records["gov"]}
    return frozenset(rows[i] for i in ids)


def test_view_db_holds_only_admitted_rows_and_per_view_display_names(world):
    path = world.store.path
    m, tables_id = world.manifest["gov"]
    full = world.db["gov"]
    assert b"COAST GUARD" < b"Coast Guard"         # the byte-smallest spelling wins
    coast = {r[0]: r[1] for r in full.execute(
        "SELECT raw, display_name FROM agencies WHERE key = 'coast guard'")}
    assert set(coast.values()) == {"COAST GUARD"} and set(coast) == {"COAST GUARD", "Coast Guard"}

    only_title_case = ViewDB.build(path, m, tables_id, _docs_of(world, ["2024-00001"]))
    assert run_query(only_title_case, "fr_documents", {}, "count").count == 1
    assert only_title_case.execute(
        "SELECT DISTINCT raw, display_name FROM agencies WHERE key = 'coast guard'") == [
        ("Coast Guard", "Coast Guard")]
    only_upper = ViewDB.build(path, m, tables_id, _docs_of(world, ["2024-00002"]))
    assert only_upper.execute(
        "SELECT DISTINCT raw, display_name FROM agencies WHERE key = 'coast guard'") == [
        ("COAST GUARD", "COAST GUARD")]
    both = ViewDB.build(path, m, tables_id, _docs_of(world, ["2024-00001", "2024-00002"]))
    assert both.execute(
        "SELECT DISTINCT display_name FROM agencies WHERE key = 'coast guard'") == [
        ("COAST GUARD",)]
    # a view that sees neither has no such entity at all
    other = ViewDB.build(path, m, tables_id, _docs_of(world, ["2024-00003"]))
    assert other.execute("SELECT count(*) FROM agencies WHERE key = 'coast guard'") == [(0,)]
    # display_name is a column like any other
    out = run_query(only_title_case, "agencies", {"display_name": "Coast Guard"}, "list")
    assert out.ids == run_query(only_title_case, "agencies", {"key": "coast guard"},
                                "list").ids and out.ids


def test_an_empty_view_has_empty_tables(world):
    m, tables_id = world.manifest["gov"]
    empty = ViewDB.build(world.store.path, m, tables_id, frozenset())
    assert all(run_query(empty, name, {}, "count").count == 0 for name in empty.contracts)
    assert run_query(empty, "fr_documents", {"year": 2024}, "list").ids == []


def test_a_build_under_another_contract_is_refused(world, tmp_path):
    m, tables_id = world.manifest["gov"]
    other = tmp_path / "contracts"
    other.mkdir()
    for name, c in load_contracts(corpus="gov").items():
        if name == "fr_documents":
            c = c.model_copy(update={"description": "changed"})
        text = c.model_dump_json()
        (other / f"{name}.json").write_text(text, encoding="utf-8")
    with pytest.raises(TablesError, match="table fr_documents: the contract is not the one"):
        ViewDB.build(world.store.path, m, tables_id, None, contracts_dir=other)


def test_from_rows_builds_a_database_without_an_overlay(world):
    contracts = load_contracts(corpus="gov")
    rows = fr_tables(world.store, None)
    db = ViewDB.from_rows(contracts, {"fr_documents": rows["fr_documents"][:3],
                                      "agencies": []}, "mine")
    assert db.tables_id == "mine"
    assert run_query(db, "fr_documents", {}, "count").count == 3
    assert run_query(db, "fr_documents", {"title__contains": "none"}, "count").count == 0
    assert run_query(db, "fr_agencies", {}, "count").count == 0       # a table with no rows
    assert set(db.contracts) == set(contracts)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        db.conn.execute("DELETE FROM fr_documents")
    with pytest.raises(QueryError, match="unknown table 'nope'"):
        ViewDB.from_rows(contracts, {"nope": []})


def test_from_rows_computes_display_names_from_its_rows(world):
    contracts = load_contracts(corpus="gov")
    m, tables_id = world.manifest["gov"]
    rows = ov.load_rows(world.store.path, m, "agencies")
    db = ViewDB.from_rows(contracts, {"agencies": [r for r in rows if r.row["raw"]
                                                    == "Coast Guard"]})
    assert db.execute("SELECT DISTINCT display_name FROM agencies") == [("Coast Guard",)]


# -- gold queries ----------------------------------------------------------------------------

def test_from_gold_query_maps_v01_queries():
    gq = GoldQuery(store="typed_db", op="lookup", filters={"venue": "arXiv", "_field": "year"})
    assert from_gold_query(gq, "research") == {"table": "papers", "filters": {"venue": "arXiv"},
                                               "op": "lookup", "fields": ["year"]}
    gq = GoldQuery(store="typed_db", op="count", filters={"year__gte": 2020, "type": "Rule"})
    assert from_gold_query(gq, "gov") == {"table": "fr_documents",
                                          "filters": {"year__gte": 2020, "type": "Rule"},
                                          "op": "count"}
    gq = GoldQuery(store="typed_db", op="list", filters={"cfr_parts__contains": "33 CFR 117"})
    assert from_gold_query(gq, "gov")["op"] == "list"


def test_v01_style_count_and_list_queries_run(gov_db, research_db):
    gq = GoldQuery(store="typed_db", op="count",
                   filters={"cfr_parts__contains": "33 CFR 117", "year": 2024})
    assert run_query(gov_db, **from_gold_query(gq, "gov")).count == 3
    gq = GoldQuery(store="typed_db", op="list", filters={"venue": "arXiv"})
    assert run_query(research_db, **from_gold_query(gq, "research")).ids == ["2501.00001"]
