"""Guarded read-only SQL (Phase 3 spec §8.1, §8.2): the authorizer whitelist, one statement,
the deterministic step budget, the row and size caps, fixed error messages, deterministic date
functions and the total order. Fixture stores under `tmp_path`; nothing reads `data/` or
`.cache/`."""

import sqlite3
from pathlib import Path

import pytest

from adr_store.tables import overlay as ov
from adr_store.tables import sqlguard
from adr_store.tables.build import build_tables
from adr_store.tables.contracts import (
    MAX_ROW_BYTES,
    MAX_VALUE_BYTES,
    load_contracts,
    validate_row,
)
from adr_store.tables.engine import ViewDB, run_query
from adr_store.tables.provenance import RowRecord
from adr_store.tables.sqlguard import (
    ERR_BUDGET,
    ERR_DENIED,
    ERR_ROWS,
    ERR_SYNTAX,
    FUNCTIONS,
    SQL_CHARGE_BYTES,
    SQL_MAX_BYTES,
    SQL_MAX_VALUE,
    SQL_ROW_CAP,
    SQL_STEP_BUDGET,
    SQL_STEP_EVERY,
    SqlOutcome,
    SqlRefused,
    has_top_level_order_by,
    run_sql,
    strip_terminator,
)
from tests.store.tables_fixtures import make_tables_store

N = 7   # FR documents in the fixture store
# docs 1, 4, 5 cite 33 CFR 117; doc 2 "117a"; doc 1 also 165; docs 3 and 7 cite 47 CFR 73
EXPECTED_CFR_GROUPS = [["33 CFR 117", 3], ["33 CFR 117a", 1], ["33 CFR 165", 1],
                       ["47 CFR 73", 2]]
FIXED = {ERR_SYNTAX, ERR_DENIED, ERR_BUDGET, ERR_ROWS}
WRITE_DDL_ATTACH_PRAGMA = [
    "DELETE FROM fr_documents",
    "UPDATE fr_documents SET title = 'x'",
    "INSERT INTO fr_documents (id) VALUES ('x')",
    "INSERT INTO fr_documents SELECT * FROM fr_documents ORDER BY 1",
    "REPLACE INTO fr_documents (id) VALUES ('x')",
    "DROP TABLE fr_documents",
    "CREATE TABLE x (a)",
    "CREATE TEMP TABLE x AS SELECT * FROM fr_documents ORDER BY 1",
    "ALTER TABLE fr_documents ADD COLUMN z",
    "CREATE INDEX i ON fr_documents (id)",
    "ATTACH DATABASE ':memory:' AS other",
    "DETACH DATABASE main",
    "PRAGMA query_only = OFF",
    "PRAGMA table_info(fr_documents)",
    "BEGIN; DELETE FROM fr_documents; COMMIT",
]


def _copy_reversed(db: ViewDB) -> ViewDB:
    """The same tables with every table's rows inserted in reverse order."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    for table in db.contracts:
        cur = db.conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid DESC')
        names = [d[0] for d in cur.description]
        conn.execute(f'CREATE TABLE "{table}" ({", ".join(chr(34) + n + chr(34) for n in names)})')
        conn.executemany(f'INSERT INTO "{table}" VALUES ({", ".join("?" * len(names))})', cur)
    conn.commit()
    conn.execute("PRAGMA query_only = ON")
    return ViewDB(conn, db.contracts, db.tables_id)


@pytest.fixture(scope="module")
def gov_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("sql") / "store"
    make_tables_store(path)
    result = build_tables(path, "gov")
    db = ViewDB.build(path, ov.load_manifest(path, result.tables_id), result.tables_id, None)
    yield db
    db.close()   # refusals kept in tracebacks hold the database in cycles: close it here


@pytest.fixture(scope="module")
def gov_db_reversed(gov_db):
    db = _copy_reversed(gov_db)
    yield db
    db.close()


@pytest.fixture(scope="module")
def big_db():
    """1,205 Federal Register rows (more than the row cap), no overlay."""
    c = load_contracts()["fr_documents"]
    rows = [RowRecord(doc_id=f"d{i}", prov={}, row={
        "id": f"2024-{i:05d}", "type": "Rule", "agency": None, "publication_date": "2024-01-01",
        "year": 2024, "title": None, "cfr_parts": [], "action": None, "effective_on": None,
        "status": None, "other_ids": [], "title_state": None, "title_waterway_keys": []})
        for i in range(1205)]
    db = ViewDB.from_rows({"fr_documents": c}, {"fr_documents": rows})
    yield db
    db.close()


def _schema(db):
    return db.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name")


def _refused(db, stmt) -> SqlRefused:
    with pytest.raises(SqlRefused) as e:
        run_sql(db, stmt)
    return e.value


# -- reading --------------------------------------------------------------------------------

def test_json_each_unnests_list_columns(gov_db):
    out = run_sql(gov_db, "SELECT value, count(*) FROM fr_documents, "
                          "json_each(fr_documents.cfr_parts) GROUP BY value")
    assert out.rows == EXPECTED_CFR_GROUPS
    assert out.columns == ["value", "count(*)"] and out.truncated is False


def test_provenance_columns_are_selectable(gov_db):
    out = run_sql(gov_db, "SELECT id, json_extract(_prov_publication_date, '$.start') "
                          "FROM fr_documents")
    assert len(out.rows) == N
    assert all(isinstance(r[1], int) for r in out.rows)
    docs = run_sql(gov_db, "SELECT DISTINCT _doc_id FROM fr_documents").rows
    assert len(docs) == N and all(len(d[0]) == 64 for d in docs)


def test_the_outcome_is_columns_rows_and_a_truncation_flag(gov_db):
    out = run_sql(gov_db, "SELECT id, year FROM fr_documents WHERE id = '2024-00003'")
    assert out == SqlOutcome(columns=["id", "year"], rows=[["2024-00003", 2024]],
                             truncated=False)


def test_whitelisted_functions_and_recursive_ctes_run(gov_db):
    out = run_sql(gov_db, "SELECT upper(type), length(id), coalesce(title, '-') IS NOT NULL, "
                          "json_array_length(cfr_parts), casefold('ÄB') "
                          "FROM fr_documents WHERE id = '2024-00002'")
    assert out.rows == [["PROPOSED RULE", 10, 1, 1, "äb"]]
    assert run_sql(gov_db, "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r "
                           "WHERE n < 5) SELECT n FROM r").rows == [[1], [2], [3], [4], [5]]
    assert run_sql(gov_db, "SELECT count(DISTINCT type) FROM fr_documents").rows == [[2]]


def test_blob_cells_come_back_as_hex(gov_db):
    assert run_sql(gov_db, "SELECT X'00ff'").rows == [["blob:00ff"]]


def test_the_function_whitelist():
    brief = set("avg count group_concat max min sum total abs coalesce ifnull iif instr length "
                "lower ltrim nullif printf format replace round rtrim substr substring trim "
                "typeof upper like glob casefold json_extract json_array_length json_type ceil "
                "floor".split())
    assert FUNCTIONS == frozenset(brief | {"date", "datetime", "strftime", "julianday"})
    assert not {"random", "randomblob", "load_extension", "sqlite_version", "unixepoch",
                "current_timestamp"} & FUNCTIONS


def test_the_limits():
    assert (SQL_ROW_CAP, SQL_STEP_BUDGET, SQL_STEP_EVERY, SQL_MAX_BYTES, SQL_CHARGE_BYTES) == \
        (1000, 5_000_000, 1000, 2_000_000, 64)


# -- date and time functions (deterministic replacements) ----------------------------------

def test_date_functions_on_stored_dates_work(gov_db):
    assert run_sql(gov_db, "SELECT DISTINCT strftime('%Y', publication_date) "
                           "FROM fr_documents").rows == [["2024"]]
    out = run_sql(gov_db, "SELECT date('2024-01-31', '+1 day'), "
                          "datetime('2024-01-01 10:00:00', '+90 minutes'), "
                          "julianday('2024-01-01'), strftime('%m/%d', '2024-03-04')")
    assert out.rows == [["2024-02-01", "2024-01-01 11:30:00", 2460310.5, "03/04"]]


@pytest.mark.parametrize("stmt", [
    "SELECT date('now')", "SELECT strftime('%s','now')",
    "SELECT datetime('2024-01-01','localtime')", "SELECT DATE('NOW')",
    "SELECT julianday(' Now ')", "SELECT datetime('2024-01-01', '+1 day', 'LocalTime')",
    "SELECT datetime('2024-01-01', 'utc')", "SELECT date()", "SELECT strftime('%Y')",
    "SELECT max(date('now')) FROM fr_documents", "SELECT CURRENT_TIMESTAMP",
    "SELECT CURRENT_DATE", "SELECT unixepoch('2024-01-01')",
    "SELECT id FROM fr_documents WHERE publication_date < date('now') ORDER BY id",
])
def test_the_clock_is_denied(gov_db, stmt):
    e = _refused(gov_db, stmt)
    assert e.kind == "denied" and str(e) == ERR_DENIED


# -- refusals -------------------------------------------------------------------------------

@pytest.mark.parametrize("stmt", WRITE_DDL_ATTACH_PRAGMA)
def test_writes_ddl_attach_and_pragma_are_refused_with_fixed_messages(gov_db, stmt):
    before = run_sql(gov_db, "SELECT count(*) FROM fr_documents").rows
    schema = _schema(gov_db)
    e = _refused(gov_db, stmt)
    assert str(e) in {ERR_SYNTAX, ERR_DENIED} and e.kind in {"syntax", "denied"}
    assert run_sql(gov_db, "SELECT count(*) FROM fr_documents").rows == before == [[N]]
    assert _schema(gov_db) == schema
    assert not gov_db.conn.in_transaction


@pytest.mark.parametrize("stmt", [
    "SELECT * FROM sqlite_master", "SELECT name FROM sqlite_schema",
    "SELECT * FROM temp.sqlite_master", "SELECT * FROM pragma_table_info('fr_documents')",
    "SELECT * FROM json_tree('[1]')",
    # a FROM item whose columns are not used is reported with no database (review probes)
    "SELECT count(*) FROM sqlite_master", "SELECT 1 FROM sqlite_schema",
    "SELECT count(*) FROM sqlite_temp_master", "SELECT count(*) FROM json_tree('[1,[2,3]]')",
    "SELECT count(*) FROM fr_documents, sqlite_master", "SELECT count(*) FROM pragma_function_list",
    "SELECT 1 WHERE EXISTS (SELECT 1 FROM sqlite_master)",
    "SELECT (SELECT count(*) FROM sqlite_master WHERE 1)",
    "SELECT count(*) FROM SQLITE_MASTER", "SELECT count(*) FROM main.sqlite_master",
    # a CTE named like a system object does not open the real one
    "SELECT (SELECT count(*) FROM sqlite_master), (WITH sqlite_master AS (SELECT 1) SELECT 1)",
    "SELECT (SELECT count(*) FROM json_tree('[1]')), (WITH json_tree AS (SELECT 1) SELECT 1)",
])
def test_reading_anything_but_the_listed_tables_is_denied(gov_db, stmt):
    e = _refused(gov_db, stmt)
    assert e.kind == "denied" and str(e) == ERR_DENIED


@pytest.mark.parametrize("stmt", [
    "WITH json_tree AS (SELECT 1) SELECT (SELECT count(*) FROM json_tree('[1,2]'))",
    "WITH pragma_table_info AS (SELECT 1) SELECT count(*) FROM pragma_table_info('fr_documents')",
    "WITH sqlite_master AS (SELECT 1) SELECT count(*) FROM main.sqlite_master",
])
def test_system_objects_behind_a_cte_name_are_refused(gov_db, stmt):
    assert str(_refused(gov_db, stmt)) in {ERR_SYNTAX, ERR_DENIED}


def test_two_statements_are_a_syntax_refusal(gov_db):
    for stmt in ("SELECT 1; DELETE FROM papers", "SELECT 1; DELETE FROM fr_documents",
                 "SELECT 1 ORDER BY 1; DELETE FROM fr_documents", "SELECT 1;;",
                 "SELECT 1; SELECT 2"):
        e = _refused(gov_db, stmt)
        assert e.kind == "syntax" and str(e) == ERR_SYNTAX
    assert run_sql(gov_db, "SELECT count(*) FROM fr_documents").rows == [[N]]


def test_trailing_semicolon_and_comments_run(gov_db):
    assert run_sql(gov_db, "SELECT count(*) FROM fr_documents; -- n").rows == [[N]]
    assert run_sql(gov_db, "SELECT count(*) FROM fr_documents -- n").rows == [[N]]
    assert run_sql(gov_db, "SELECT count(*) FROM fr_documents /* n */ ;\n").rows == [[N]]
    assert run_sql(gov_db, "SELECT id FROM fr_documents ORDER BY id DESC; -- n").rows[0] == \
        ["2024-00007"]


def test_recursive_bombs_and_cross_joins_stop_at_the_budget(gov_db, monkeypatch):
    e = _refused(gov_db, "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM r) "
                         "SELECT count(*) FROM r")   # the production budget
    assert e.kind == "budget" and str(e) == ERR_BUDGET
    monkeypatch.setattr(sqlguard, "SQL_STEP_BUDGET", 20_000)
    for stmt in ("WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM r) "
                 "SELECT count(*) FROM r",
                 "SELECT count(*) FROM fr_documents a, fr_documents b, fr_documents c, "
                 "fr_documents d, fr_documents e, fr_documents f",
                 "SELECT a.id FROM fr_documents a, fr_documents b, fr_documents c, "
                 "fr_documents d, fr_documents e ORDER BY a.id"):
        e = _refused(gov_db, stmt)
        assert e.kind == "budget" and str(e) == ERR_BUDGET
    assert run_sql(gov_db, "SELECT count(*) FROM fr_documents").rows == [[N]]


def test_the_budget_is_deterministic(gov_db, monkeypatch):
    """The cut-off counts virtual-machine steps, not time: the same statement under the same
    budget always succeeds or always fails."""
    stmt = ("WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM r WHERE n < 500) "
            "SELECT count(*) FROM r")
    monkeypatch.setattr(sqlguard, "SQL_STEP_BUDGET", 20_000)
    assert all(run_sql(gov_db, stmt).rows == [[500]] for _ in range(5))   # ~8,500 steps
    monkeypatch.setattr(sqlguard, "SQL_STEP_BUDGET", 5_000)
    assert all(_refused(gov_db, stmt).kind == "budget" for _ in range(5))


@pytest.mark.parametrize("fn", ["date('now')", "random()", "load_extension('x')",
                                "sqlite_version()", "randomblob(4)", "abs(random())",
                                "sqlite_source_id()", "changes()", "last_insert_rowid()",
                                "json_set('{}', '$.a', 1)", "'{}' ->> '$.a'", "hex('a')"])
def test_functions_outside_the_whitelist_are_denied(gov_db, fn):
    e = _refused(gov_db, f"SELECT {fn} FROM fr_documents")
    assert e.kind == "denied" and str(e) == ERR_DENIED


def test_results_cap_at_1000_rows_and_flag_truncation(big_db):
    out = run_sql(big_db, "SELECT id FROM fr_documents")
    assert out.truncated is True and len(out.rows) == SQL_ROW_CAP
    assert out.rows == [[f"2024-{i:05d}"] for i in range(1000)]
    exact = run_sql(big_db, "SELECT id FROM fr_documents ORDER BY id LIMIT 1000")
    assert exact.truncated is False and len(exact.rows) == 1000
    assert run_sql(big_db, "SELECT count(*) FROM fr_documents").rows == [[1205]]


def test_a_result_over_2_mb_is_refused(big_db):
    e = _refused(big_db, "SELECT replace(printf('%3000d', 1), ' ', 'x') FROM fr_documents")
    assert e.kind == "rows" and str(e) == ERR_ROWS
    # one value over the limit is refused the same way, and the limit is lifted afterwards
    before = big_db.conn.getlimit(sqlite3.SQLITE_LIMIT_LENGTH)
    e = _refused(big_db, "SELECT group_concat(replace(printf('%3000d', 1), ' ', 'x')) "
                         "FROM fr_documents")
    assert e.kind == "rows" and str(e) == ERR_ROWS
    assert big_db.conn.getlimit(sqlite3.SQLITE_LIMIT_LENGTH) == before
    small = run_sql(big_db, "SELECT replace(printf('%1000d', 1), ' ', 'x') FROM fr_documents")
    assert small.truncated and len(small.rows[0][0]) == 1000


def test_order_is_total_without_an_order_by(gov_db, gov_db_reversed):
    q = "SELECT type, year FROM fr_documents"
    assert gov_db.execute(q) != gov_db_reversed.execute(q)   # unwrapped, storage order shows
    expected = sorted([list(r) for r in gov_db.execute(q)])
    assert run_sql(gov_db, q).rows == run_sql(gov_db_reversed, q).rows == expected
    q2 = "SELECT id, cfr_parts FROM fr_documents"
    assert run_sql(gov_db, q2).rows == run_sql(gov_db_reversed, q2).rows
    assert [r[0] for r in run_sql(gov_db_reversed, q2).rows] == \
        [f"2024-{i:05d}" for i in range(1, 8)]


def test_a_statement_order_by_is_kept(gov_db, gov_db_reversed):
    out = run_sql(gov_db, "SELECT id FROM fr_documents ORDER BY id DESC")
    assert [r[0] for r in out.rows] == [f"2024-{i:05d}" for i in range(7, 0, -1)]
    q = "SELECT type, count(*) AS n FROM fr_documents GROUP BY type ORDER BY n DESC"
    assert run_sql(gov_db, q).rows == [["Rule", 5], ["Proposed Rule", 2]]
    assert run_sql(gov_db, q).columns == ["type", "n"]
    # an ORDER BY inside parentheses is not the statement's: the result is still wrapped
    sub = "SELECT id FROM (SELECT id FROM fr_documents ORDER BY id DESC LIMIT 3)"
    assert run_sql(gov_db, sub).rows == [["2024-00005"], ["2024-00006"], ["2024-00007"]]


def test_errors_never_carry_engine_text(gov_db):
    for stmt in ("SELECT * FROM nosuch", "SELECT nosuchcol FROM fr_documents", "SELEC 1",
                 "SELECT ?", "SELECT 'unterminated", ""):
        e = _refused(gov_db, stmt)
        assert str(e) == ERR_SYNTAX and e.kind == "syntax"
        assert e.args == (ERR_SYNTAX,)
        assert e.__cause__ is None and e.__context__ is None
    for not_text in (None, 7, b"SELECT 1"):
        assert str(_refused(gov_db, not_text)) == ERR_SYNTAX


@pytest.mark.parametrize("stmt", [
    "SELECT/**/1 FROM papers", "SELECT 1 /*; DROP TABLE papers */", "ＳＥＬＥＣＴ 1",
    "SELECT 1\x00; DROP TABLE papers", "SELECT 1 -- x\n; DROP TABLE fr_documents",
    "SELECT '\ud800'", "SELECT 1 /* unterminated", "SELECT 1) , (SELECT 2",
    "SELECT 1) UNION SELECT name FROM (SELECT name FROM sqlite_master",
    "SELECT id FROM fr_documents WHERE id = ''; DROP TABLE fr_documents; --'",
    "SELECT \"ORDER\" FROM (SELECT 1 AS \"ORDER\")", "SELECT 1 ORDER BY 1",
    "SELECT 1 ORDER BY 1) UNION (SELECT 2", "/* x */ PRAGMA query_only = OFF",
])
def test_comment_and_encoding_tricks_are_refused_or_harmless(gov_db, stmt):
    schema = _schema(gov_db)
    try:
        out = run_sql(gov_db, stmt)
    except SqlRefused as e:
        assert str(e) in FIXED
    else:
        assert len(out.rows) <= 1
    assert _schema(gov_db) == schema
    assert run_sql(gov_db, "SELECT count(*) FROM fr_documents").rows == [[N]]
    assert gov_db.execute("PRAGMA query_only") == [(1,)]


def test_the_guard_leaves_the_connection_as_it_found_it(gov_db):
    _refused(gov_db, "SELECT * FROM sqlite_master")
    _refused(gov_db, "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM r) "
                     "SELECT count(*) FROM r")
    # query_table still reads freely (json_each with an alias, casefold) after refusals
    assert run_query(gov_db, "fr_documents", {"cfr_parts__contains": "33 cfr 117"},
                     "count").count == 3
    assert gov_db.execute("SELECT name FROM sqlite_master WHERE name = 'fr_documents'") == \
        [("fr_documents",)]


# -- the statement tokenizer -----------------------------------------------------------------

@pytest.mark.parametrize("stmt, expected", [
    ("SELECT 1;", "SELECT 1"), ("SELECT 1 ; -- c", "SELECT 1"), ("SELECT 1 -- c", "SELECT 1"),
    ("SELECT 1 /* c */  \n", "SELECT 1"), ("SELECT 1;;", "SELECT 1;"),
    ("SELECT ';' ", "SELECT ';'"), ("SELECT '--' -- c", "SELECT '--'"),
    ("SELECT \"a;\" FROM t; /* c", "SELECT \"a;\" FROM t"), ("-- only", ""), ("", ""),
    ("SELECT [x;] FROM t;", "SELECT [x;] FROM t"), ("SELECT `a--` ;", "SELECT `a--`"),
    ("  SELECT 1", "  SELECT 1"),
])
def test_strip_terminator(stmt, expected):
    assert strip_terminator(stmt) == expected


@pytest.mark.parametrize("stmt, expected", [
    ("SELECT a FROM t ORDER BY a", True), ("select a from t order\n by a", True),
    ("SELECT a FROM t ORDER /* c */ BY a", True), ("SELECT a FROM t ORDER -- c\nBY a", True),
    ("SELECT a FROM t", False), ("SELECT a FROM (SELECT a FROM t ORDER BY a)", False),
    ("SELECT group_concat(a ORDER BY a) FROM t", False), ("SELECT 'ORDER BY' FROM t", False),
    ("SELECT \"ORDER BY\" FROM t", False), ("SELECT a FROM t -- ORDER BY a", False),
    ("SELECT a FROM t /* ORDER BY a */", False), ("SELECT a AS [order by] FROM t", False),
    ("SELECT order_by FROM t", False), ("SELECT a FROM t ORDER", False),
    ("WITH x AS (SELECT 1 ORDER BY 1) SELECT * FROM x", False),
    ("SELECT 1 UNION SELECT 2 ORDER BY 1", True), ("SELECT 1 ORDER BY 1", False),
])
def test_has_top_level_order_by(stmt, expected):
    assert has_top_level_order_by(stmt) is expected


# -- fix round 1: case-folded names, CTEs, memory, per-step work, total order -----------------

@pytest.mark.parametrize("stmt, rows", [
    ("SELECT count(*) FROM FR_DOCUMENTS", [[N]]),
    ("SELECT count(*) FROM main.FR_DOCUMENTS", [[N]]),
    ("SELECT count(F.ID) FROM Fr_Documents AS F", [[N]]),
    ("SELECT value FROM JSON_EACH('[1]')", [[1]]),
    ("SELECT count(*) FROM json_each('[1,2]')", [[2]]),
    ("SELECT count(*) FROM (SELECT 1)", [[1]]),
    ("WITH r(n) AS (SELECT 1) SELECT count(*) FROM r", [[1]]),
    ("WITH R(n) AS (SELECT 1) SELECT count(*) FROM r", [[1]]),
    ("WITH \"q r\"(n) AS (SELECT 1) SELECT count(*) FROM \"q r\"", [[1]]),
    ("WITH a AS (SELECT 1), b AS MATERIALIZED (SELECT 2), c AS NOT MATERIALIZED (SELECT 3) "
     "SELECT count(*) FROM a, b, c", [[1]]),
    ("WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 3) "
     "SELECT count(*) FROM r", [[3]]),
    ("SELECT (WITH x AS (SELECT 1) SELECT count(*) FROM x)", [[1]]),
])
def test_tables_ctes_and_json_each_are_read_in_any_case(gov_db, stmt, rows):
    assert run_sql(gov_db, stmt).rows == rows


def test_rows_stream_and_the_size_refusal_comes_before_all_are_fetched(gov_db, monkeypatch):
    seen = []
    real = sqlguard._row
    monkeypatch.setattr(sqlguard, "_row", lambda r: seen.append(r) or real(r))
    monkeypatch.setattr(sqlguard, "SQL_MAX_BYTES", 10_000)
    stmt = ("WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 200) "
            "SELECT n, replace(printf('%1000d', n), ' ', 'x') FROM r")
    e = _refused(gov_db, stmt)
    assert e.kind == "rows" and str(e) == ERR_ROWS
    assert 9 <= len(seen) <= 11   # about 1 KB a row: stopped at the tenth of 200 rows


def test_a_wide_result_is_refused_without_holding_it(gov_db):
    # the review's memory probe, at the value limit: 343 rows of nearly the limit each
    e = _refused(gov_db, f"SELECT replace(printf('%{SQL_MAX_VALUE - 200}d', 1), ' ', 'x') "
                         "|| a.id FROM fr_documents a, fr_documents b, fr_documents c")
    assert e.kind == "rows"


def test_values_are_limited_to_the_shared_bound(gov_db):
    # one bound for reading and building: every stored value and row can be read
    assert SQL_MAX_VALUE == 16_384
    assert SQL_MAX_VALUE >= MAX_ROW_BYTES >= MAX_VALUE_BYTES
    near = SQL_MAX_VALUE - 100
    ok = f"SELECT length(replace(printf('%{near}d', 1), ' ', 'x'))"
    assert run_sql(gov_db, ok).rows == [[near]]
    half = SQL_MAX_VALUE // 2
    for stmt in (f"SELECT length(replace(printf('%{half + 100}d', 1), ' ', 'xx'))",
                 f"SELECT length(group_concat(replace(printf('%{half}d', n), ' ', 'x'))) FROM "
                 "(SELECT 1 AS n UNION ALL SELECT 2 UNION ALL SELECT 3)",
                 "WITH RECURSIVE r(n, s) AS (SELECT 1, 'x' UNION ALL SELECT n + 1, s || s FROM r "
                 "WHERE n < 30) SELECT max(length(s)) FROM r"):
        e = _refused(gov_db, stmt)   # an intermediate value over the limit
        assert e.kind == "rows" and str(e) == ERR_ROWS


def test_amplifying_functions_are_charged_by_result_size(gov_db, monkeypatch):
    # under 1,000 virtual-machine steps, so only the charges can exceed the budget: each
    # 6,400-character result charges 6400 // 64 = 100 steps
    assert SQL_CHARGE_BYTES == 64
    one = "SELECT length(replace(printf('%6400d', 1), ' ', 'x'))"
    # printf 100 + replace 100, and replace's search 6400 * 1 // 4096 = 1
    for stmt, charged in ((one, 201),
                          ("SELECT length(format('%6400d', 1))", 100),
                          ("SELECT length(substr(printf('%6400d', 1), 1))", 200),
                          ("SELECT length(group_concat(x, '')) FROM (SELECT printf('%3200d', 1) "
                           "AS x UNION ALL SELECT printf('%3200d', 2))", 200)):  # 50 + 50 + 100
        monkeypatch.setattr(sqlguard, "SQL_STEP_BUDGET", charged)
        assert run_sql(gov_db, stmt).rows == [[6400]]
        monkeypatch.setattr(sqlguard, "SQL_STEP_BUDGET", charged - 1)
        e = _refused(gov_db, stmt)
        assert e.kind == "budget" and str(e) == ERR_BUDGET


LARGE = SQL_MAX_VALUE - 200
LARGE_VALUE_PROBES = [   # the review's probes, at the largest value the limit allows
    f"SELECT max(length(replace(printf('%{LARGE}d', a.id), ' ', 'x') || b.id)) "
    "FROM fr_documents a, fr_documents b, fr_documents c, fr_documents d, fr_documents e, "
    "fr_documents f",
    f"WITH RECURSIVE r(n, s) AS (SELECT 1, '' UNION SELECT n + 1, replace(printf('%{LARGE}d', "
    "n), ' ', 'x') FROM r) SELECT count(*) FROM r",
]


def test_large_value_joins_and_recursion_stop_at_the_budget(gov_db, monkeypatch):
    big = f"replace(printf('%{LARGE}d', a.id), ' ', 'x')"
    monkeypatch.setattr(sqlguard, "SQL_STEP_BUDGET", 10_000)
    small = ("SELECT max(length(replace(printf('%10d', a.id), ' ', 'x'))) "
             "FROM fr_documents a, fr_documents b, fr_documents c")
    assert run_sql(gov_db, small).rows == [[10]]   # 343 rows: the steps alone are in budget
    e = _refused(gov_db, small.replace("replace(printf('%10d', a.id), ' ', 'x')", big))
    assert e.kind == "budget" and str(e) == ERR_BUDGET
    monkeypatch.setattr(sqlguard, "SQL_STEP_BUDGET", 500_000)
    for stmt in LARGE_VALUE_PROBES:
        e = _refused(gov_db, stmt)
        assert e.kind == "budget" and str(e) == ERR_BUDGET


@pytest.mark.parametrize("stmt", LARGE_VALUE_PROBES)
def test_large_value_probes_stop_quickly_at_the_production_budget(gov_db, stmt):
    """About 1–1.5 s each (measured; see the Task 5 report): the charges, not the steps,
    end them."""
    assert sqlguard.SQL_STEP_BUDGET == 5_000_000
    e = _refused(gov_db, stmt)
    assert e.kind == "budget" and str(e) == ERR_BUDGET


def test_group_concat_keeps_sqlite_semantics(gov_db):
    q = ("SELECT group_concat(x), group_concat(x, ' | '), group_concat(DISTINCT x), "
         "group_concat(x ORDER BY x DESC), group_concat(y), group_concat(x, NULL) FROM "
         "(SELECT 'b' AS x, NULL AS y UNION ALL SELECT NULL, NULL UNION ALL SELECT 'a', NULL "
         "UNION ALL SELECT 'b', NULL)")
    assert run_sql(gov_db, q).rows == [["b,a,b", "b | a | b", "b,a", "b,b,a", None, "bab"]]
    nums = run_sql(gov_db, "SELECT group_concat(v) FROM (SELECT 1 AS v UNION ALL SELECT 2.5 "
                           "UNION ALL SELECT 1e20 UNION ALL SELECT 100.0)").rows
    plain = sqlite3.connect(":memory:")   # SQLite's own group_concat as the oracle
    assert nums == [list(r) for r in plain.execute(
        "SELECT group_concat(v) FROM (SELECT 1 AS v UNION ALL SELECT 2.5 UNION ALL "
        "SELECT 1e20 UNION ALL SELECT 100.0)")]
    plain.close()
    assert nums == [["1,2.5,1.0e+20,100.0"]]
    assert run_sql(gov_db, "SELECT type, group_concat(id, ';') FROM fr_documents "
                           "WHERE type = 'Proposed Rule' GROUP BY type").rows == \
        [["Proposed Rule", "2024-00002;2024-00005"]]


def test_non_finite_numbers_come_back_as_null(gov_db):
    assert run_sql(gov_db, "SELECT 9e999, -9e999, 1.5").rows == [[None, None, 1.5]]


def test_the_overrides_hold_no_finished_call(gov_db):
    import gc
    import warnings
    assert run_sql(gov_db, "SELECT date('2024-01-01'), replace('ab', 'a', 'c')").rows == \
        [["2024-01-01", "cb"]]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        # outside a guarded call the overrides refuse: no finished call's guard, no stray
        # private connection
        for q in ("SELECT date('2024-02-01')", "SELECT replace('ab', 'a', 'c')",
                  "SELECT group_concat(x) FROM (SELECT 'a' AS x)"):
            with pytest.raises(sqlite3.OperationalError):
                gov_db.execute(q)
        gc.collect()
    assert gov_db.execute("SELECT casefold('A'), contains_casefold('AB', 'b')") == [("a", 1)]
    assert run_sql(gov_db, "SELECT date('2024-03-01')").rows == [["2024-03-01"]]


def test_ties_under_a_statement_order_by_come_out_in_a_total_order(gov_db, gov_db_reversed):
    q = "SELECT type, id FROM fr_documents ORDER BY type"
    assert gov_db.execute(q) != gov_db_reversed.execute(q)   # unbroken ties show storage order
    expected = sorted([list(r) for r in gov_db.execute(q)])
    assert run_sql(gov_db, q).rows == run_sql(gov_db_reversed, q).rows == expected
    desc = "SELECT type, id FROM fr_documents ORDER BY type DESC"
    assert [r[1] for r in run_sql(gov_db_reversed, desc).rows] == \
        ["2024-00001", "2024-00003", "2024-00004", "2024-00006", "2024-00007",
         "2024-00002", "2024-00005"]


@pytest.mark.parametrize("q, expected", [
    ("SELECT id FROM fr_documents ORDER BY type LIMIT 3",
     [["2024-00002"], ["2024-00005"], ["2024-00001"]]),
    ("SELECT id FROM fr_documents ORDER BY type LIMIT 2 OFFSET 1",
     [["2024-00005"], ["2024-00001"]]),
    ("SELECT id FROM fr_documents ORDER BY type LIMIT 1, 2", [["2024-00005"], ["2024-00001"]]),
    ("SELECT id, 'ORDER BY x LIMIT 1' FROM fr_documents ORDER BY type /* LIMIT 1 */ LIMIT 2",
     [["2024-00002", "ORDER BY x LIMIT 1"], ["2024-00005", "ORDER BY x LIMIT 1"]]),
    ("SELECT type FROM (SELECT type, id FROM fr_documents ORDER BY id LIMIT 4) ORDER BY type",
     [["Proposed Rule"], ["Rule"], ["Rule"], ["Rule"]]),
    ("SELECT type FROM fr_documents UNION ALL SELECT type FROM fr_documents ORDER BY 1 LIMIT 5",
     [["Proposed Rule"]] * 4 + [["Rule"]]),
    ("SELECT year, id FROM fr_documents WHERE id IN (SELECT id FROM fr_documents ORDER BY id "
     "DESC LIMIT 2) ORDER BY year", [[2024, "2024-00006"], [2024, "2024-00007"]]),
])
def test_a_statement_order_by_keeps_its_limit_and_gets_tie_breakers(gov_db, gov_db_reversed,
                                                                    q, expected):
    assert run_sql(gov_db, q).rows == run_sql(gov_db_reversed, q).rows == expected


@pytest.mark.parametrize("code, kind", [(13, "budget"), (7, "budget"), (18, "rows"),
                                        (1, "syntax")])
def test_error_codes_map_to_fixed_classes(code, kind):
    e = sqlite3.OperationalError("engine text")
    e.sqlite_errorcode = code   # SQLITE_FULL, SQLITE_NOMEM, SQLITE_TOOBIG, SQLITE_ERROR
    refusal = sqlguard._Guard(frozenset(), frozenset()).refusal(e)
    assert refusal.kind == kind and "engine" not in str(refusal)


def test_query_table_works_after_run_sql(gov_db):
    """The overrides stay registered on the view database but act only inside `run_sql`;
    `query_table` uses none of them."""
    run_sql(gov_db, "SELECT date('2024-01-01'), replace(id, '-', ''), group_concat(type), "
                    "printf('%d', year), substr(id, 1, 4) FROM fr_documents")
    assert run_query(gov_db, "fr_documents", {"type": "Rule"}, "count").count == 5
    assert run_query(gov_db, "fr_documents", {"title__contains": "drawbridge"}, "list").ids == \
        ["2024-00001", "2024-00004", "2024-00005"]   # 2024-00002 has no title
    groups = run_query(gov_db, "fr_documents", {}, "count_by", fields=["cfr_parts"]).groups
    assert {"value": "33 CFR 117", "count": 3} in groups
    rows = run_query(gov_db, "fr_documents", {"id": "2024-00003"}, "lookup").rows
    assert rows[0]["row"]["cfr_parts"] == ["47 CFR 73"]


def test_a_stored_row_at_the_row_limit_is_selected_and_sorted_whole():
    from tests.store.test_tables_overlay import CONTRACT, D, fr_row, with_row
    rows = [with_row(fr_row(D, f"2024-0001{i}"), {"title": "t" * 6000, "action": "a" * 6000})
            for i in range(3)]
    assert all(validate_row(CONTRACT, r) == [] for r in rows)   # rows a build would store
    db = ViewDB.from_rows({"fr_documents": CONTRACT}, {"fr_documents": rows})
    try:
        out = run_sql(db, "SELECT * FROM fr_documents")   # sorted on every output column
        assert [r[1] for r in out.rows] == ["2024-00010", "2024-00011", "2024-00012"]
        # DISTINCT with its own ORDER BY carries the row twice in SQLite's sorter once the
        # tie-breakers are added (a known limit); DISTINCT in a subquery reads it whole
        e = _refused(db, "SELECT DISTINCT * FROM fr_documents ORDER BY id DESC")
        assert e.kind == "rows"
        sub = "SELECT * FROM (SELECT DISTINCT * FROM fr_documents) ORDER BY id DESC"
        assert [r[1] for r in run_sql(db, sub).rows] == ["2024-00012", "2024-00011", "2024-00010"]
    finally:
        db.close()


# -- fix round 2: reserved identifiers, search functions, window group_concat -----------------

@pytest.mark.parametrize("stmt", [
    # NATURAL JOIN and JOIN ... USING compare right-hand columns without the authorizer
    "SELECT count(*) FROM (SELECT 'table' AS type) NATURAL JOIN sqlite_master",
    "SELECT count(*) FROM (SELECT 'table' AS type, 'fr_documents' AS name) "
    "NATURAL JOIN sqlite_master",
    "SELECT count(*) FROM (SELECT 'table' AS type) JOIN sqlite_master USING (type)",
    "SELECT count(*) FROM (SELECT 'table' AS type) NATURAL LEFT JOIN sqlite_master",
    "SELECT count(*) FROM sqlite_master NATURAL JOIN (SELECT 'table' AS type)",
    "SELECT count(*) FROM (SELECT 'table' AS type) NATURAL JOIN sqlite_temp_master",
    "SELECT count(*) FROM (SELECT 'table' AS type) NATURAL JOIN temp.sqlite_master",
    "SELECT count(*) FROM (SELECT 0 AS id) NATURAL JOIN json_tree('[1,2,[3]]')",
    "SELECT count(*) FROM (SELECT 'json' AS name) NATURAL JOIN pragma_function_list",
    "SELECT count(*) FROM (SELECT 'id' AS name) NATURAL JOIN pragma_table_info('fr_documents')",
    "SELECT count(*) FROM (SELECT 1 AS value) NATURAL JOIN generate_series(1, 10)",
    "SELECT count(*) FROM (SELECT 'main' AS schema) NATURAL JOIN dbstat",
    "SELECT count(*) FROM (SELECT 1 AS pgno) NATURAL JOIN sqlite_dbpage",
    "SELECT count(*) FROM (SELECT 'fr_documents' AS name) NATURAL JOIN sqlite_stat1",
    # every spelling of a reserved name
    "SELECT count(*) FROM (SELECT 'table' AS type) NATURAL JOIN \"sqlite_master\"",
    "SELECT count(*) FROM (SELECT 'table' AS type) NATURAL JOIN [SQLITE_MASTER]",
    "SELECT count(*) FROM (SELECT 'table' AS type) NATURAL JOIN `Sqlite_Schema`",
    "SELECT count(*) FROM (SELECT 'table' AS type) NATURAL JOIN 'sqlite_master'",
    "SELECT count(*) FROM (SELECT 'table' AS type) NATURAL JOIN main.\"sqlite_master\"",
    "SELECT count(*) FROM (SELECT 0 AS id) NATURAL JOIN \"JSON_TREE\"('[1]')",
    "SELECT count(*) FROM (SELECT 1 AS x) NATURAL JOIN [pragma_database_list]",
    "SELECT count(*) FROM (SELECT 1 AS x) NATURAL JOIN fts5vocab",
    "SELECT count(*) FROM (SELECT 1 AS x) NATURAL JOIN rtree",
    "SELECT count(*) FROM (SELECT 1 AS x) NATURAL JOIN carray",
    "SELECT count(*) FROM (SELECT 1 AS x) NATURAL JOIN sqlite_stmt",
])
def test_reserved_names_are_denied_in_any_spelling(gov_db, stmt):
    e = _refused(gov_db, stmt)
    assert e.kind == "denied" and str(e) == ERR_DENIED
    assert sqlguard._names_reserved(stmt)   # the name check alone catches each spelling too


@pytest.mark.parametrize("stmt, rows", [
    ("SELECT count(*) FROM fr_documents a JOIN fr_documents b ON a.id = b.id", [[N]]),
    ("SELECT count(*) FROM fr_documents, json_each(fr_documents.cfr_parts)", [[7]]),
    ("SELECT 'sqlite_master is a name', 'x pragma_y'", [["sqlite_master is a name",
                                                          "x pragma_y"]]),
    ("SELECT count(*) FROM fr_documents WHERE title LIKE '%sqlite%'", [[0]]),
    ("SELECT \"ſqlite_master\" FROM (SELECT 1 AS \"ſqlite_master\")", [[1]]),  # not ASCII
])
def test_ordinary_names_and_strings_still_run(gov_db, stmt, rows):
    assert run_sql(gov_db, stmt).rows == rows


def _lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, bytes):
        return "X'" + v.hex() + "'"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + v.replace("'", "''") + "'"


def _cases(seed: int, n: int):
    import random
    rng = random.Random(seed)
    alphabet = "aAbB%_*?[]^-\\éÉßẞ!z0 "
    def text():
        return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 8)))
    def value():
        k = rng.random()
        if k < 0.05:
            return None
        if k < 0.10:
            return rng.choice([0, 12, -3, 1.5])
        if k < 0.15:
            return text().encode("utf-8")
        return text()
    return [(value(), value(), rng.choice(["\\", "%", "a", "é", "_"])) for _ in range(n)]


def test_search_overrides_match_sqlite_exactly(gov_db):
    """`instr`, `like` (2 and 3 arguments, so `LIKE`, `NOT LIKE` and `ESCAPE` route to it),
    `glob` and the trim family give SQLite's own answers: an oracle over 400 seeded cases."""
    cases = _cases(20261120, 400)
    values = ", ".join(f"({i}, {_lit(x)}, {_lit(y)}, {_lit(e)})"
                       for i, (x, y, e) in enumerate(cases))
    exprs = ("instr(x, y), x LIKE y, x NOT LIKE y, x LIKE y ESCAPE e, like(y, x), "
             "like(y, x, e), x GLOB y, x NOT GLOB y, glob(y, x), upper(x) LIKE lower(y), "
             "trim(x, y), ltrim(x, y), rtrim(x, y), trim(x), ltrim(x), rtrim(x)")
    q = (f"SELECT i, {exprs} FROM (SELECT column1 AS i, column2 AS x, column3 AS y, "
         f"column4 AS e FROM (VALUES {values})) ORDER BY i")
    plain = sqlite3.connect(":memory:")
    try:
        expected = [list(r) for r in plain.execute(q)]
    finally:
        plain.close()
    assert run_sql(gov_db, q).rows == expected
    assert any(r[2] == 1 for r in expected) and any(r[7] == 1 for r in expected)


def test_a_like_escape_must_be_one_character_as_in_sqlite(gov_db):
    assert _refused(gov_db, "SELECT 'a' LIKE 'a' ESCAPE 'xy'").kind == "syntax"


def test_search_functions_are_charged_by_their_search(gov_db, monkeypatch):
    # printf('%4096d') charges 64 and printf('%1024d') 16. instr searches at 4,096 pairs a step
    # (4096 * 1024 // 4096 = 1024); like, glob and the trim family compare at 128 pairs a step
    # (4096 * 1024 // 128 = 32768); replace also charges its 4,096-character result (64)
    h, n = "printf('%4096d', 1)", "printf('%1024d', 2)"
    for stmt, charged in ((f"SELECT instr({h}, {n})", 1104),
                          (f"SELECT {h} LIKE {n}", 32848),
                          (f"SELECT {h} NOT LIKE {n} ESCAPE '!'", 32848),
                          (f"SELECT {h} GLOB {n}", 32848),
                          (f"SELECT length(trim({h}, {n}))", 32848),
                          (f"SELECT length(ltrim({h}, {n}))", 32848),
                          (f"SELECT length(rtrim({h}, {n}))", 32848),
                          (f"SELECT length(trim({h}))", 64),
                          (f"SELECT length(replace({h}, {n}, 'x'))", 1168)):
        monkeypatch.setattr(sqlguard, "SQL_STEP_BUDGET", charged)
        run_sql(gov_db, stmt)
        monkeypatch.setattr(sqlguard, "SQL_STEP_BUDGET", charged - 1)
        e = _refused(gov_db, stmt)
        assert e.kind == "budget" and str(e) == ERR_BUDGET


_V = ("WITH h AS MATERIALIZED (SELECT replace(printf('%16000d', 1), ' ', 'a') AS h), "
      "n AS MATERIALIZED (SELECT replace(printf('%7999d', 1), ' ', 'a') || 'b' AS n), "
      "p AS MATERIALIZED (SELECT '%' || replace(printf('%7999d', 1), ' ', 'a') || 'b' AS p), "
      "g AS MATERIALIZED (SELECT '*' || replace(printf('%250d', 1), ' ', '[' || "
      "replace(printf('%30d', 1), ' ', 'b') || 'a]') || 'c' AS g), "
      "y AS MATERIALIZED (SELECT replace(printf('%1360d', 1), ' ', 'b') || 'a' AS y) ")
_J = ", fr_documents a, fr_documents b, fr_documents c, fr_documents d"
_X = "CASE WHEN d.id IS NULL THEN '' ELSE {} END"
SEARCH_PROBES = [   # the review's worst cases (none prunable): minutes to the budget before
    _V + "SELECT count(*) FROM h, n" + _J + " WHERE instr(h, " + _X.format("n") + ") > 0",
    _V + "SELECT count(*) FROM h, p" + _J + " WHERE h LIKE " + _X.format("p"),
    _V + "SELECT count(*) FROM h, g" + _J + " WHERE h GLOB " + _X.format("g"),
    _V + "SELECT count(*) FROM h, y" + _J + " WHERE length(ltrim(h, " + _X.format("y")
    + ")) = 0",
    _V + "SELECT count(*) FROM h, y" + _J + " WHERE length(trim(h, " + _X.format("y")
    + ")) = 0",
    _V + "SELECT count(*) FROM h, n" + _J + " WHERE length(replace(h, " + _X.format("n")
    + ", 'x')) > 0",
]


@pytest.mark.parametrize("stmt", SEARCH_PROBES)
def test_search_probes_stop_quickly_at_the_production_budget(gov_db, stmt):
    import time
    assert sqlguard.SQL_STEP_BUDGET == 5_000_000
    start = time.perf_counter()
    e = _refused(gov_db, stmt)
    assert e.kind == "budget" and str(e) == ERR_BUDGET
    assert time.perf_counter() - start < 5   # about 0.2-1 s measured; minutes before


WINDOW_SCRIPT = """
import sys
from adr_store.tables.contracts import load_contracts
from adr_store.tables.engine import ViewDB
from adr_store.tables.provenance import RowRecord
from adr_store.tables.sqlguard import SqlRefused, run_sql
c = load_contracts()["fr_documents"]
rows = [RowRecord(doc_id=f"d{i}", prov={}, row={
    "id": f"2024-0000{i}", "type": "Rule", "agency": None, "publication_date": "2024-01-01",
    "year": 2024, "title": None, "cfr_parts": [], "action": None, "effective_on": None,
    "status": None, "other_ids": [], "title_state": None, "title_waterway_keys": []})
    for i in range(1, 8)]
db = ViewDB.from_rows({"fr_documents": c}, {"fr_documents": rows})
try:
    print("rows", run_sql(db, sys.argv[1]).rows)
except SqlRefused as e:
    print("refused", e.kind)
db.close()
"""


@pytest.mark.parametrize("stmt", [
    "SELECT group_concat(id) OVER (ORDER BY id ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING) "
    "FROM fr_documents",
    "SELECT group_concat(id) FILTER (WHERE id > '2024-00003') OVER (ORDER BY id) "
    "FROM fr_documents",
    "SELECT type, group_concat(id) OVER (PARTITION BY type) FROM fr_documents",
])
def test_group_concat_as_a_window_function_is_refused(stmt):
    """`group_concat` is an aggregate only: CPython's window-function callbacks crash the
    process when SQLite asks for a value before any step, so the window form is refused. Run
    in a subprocess so a regression cannot take the test runner down with it."""
    import subprocess
    import sys
    done = subprocess.run([sys.executable, "-c", WINDOW_SCRIPT, stmt], capture_output=True,
                          text=True, timeout=120, cwd=str(Path(__file__).parents[2]))
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip() == "refused syntax"


def test_group_concat_still_works_as_an_aggregate(gov_db):
    assert run_sql(gov_db, "SELECT type, group_concat(id, ';') FROM fr_documents "
                           "GROUP BY type").rows == [
        ["Proposed Rule", "2024-00002;2024-00005"],
        ["Rule", "2024-00001;2024-00003;2024-00004;2024-00006;2024-00007"]]


def test_on_joins_count_as_sqlite_does(gov_db):
    for q in ("SELECT count(*) FROM fr_documents a JOIN fr_documents b ON a.type = b.type",
              "SELECT count(*) FROM fr_documents a LEFT JOIN fr_documents b "
              "ON a.id = b.id AND a.year > 2030",
              "SELECT count(*) FROM fr_documents d JOIN fr_agencies g ON g.id = d.id"):
        assert run_sql(gov_db, q).rows == [list(r) for r in gov_db.execute(q)]



@pytest.mark.parametrize("stmt", [
    "SELECT count(*) FROM 'sqlite_master'",
    "SELECT count(*) FROM fr_documents, 'sqlite_master'",
    "SELECT count(*) FROM fr_documents JOIN 'sqlite_schema' ON 1",
    "SELECT count(*) FROM fr_documents a JOIN fr_documents b ON a.id = b.id, 'sqlite_master'",
    "SELECT count(*) FROM main.'sqlite_master'",
    "SELECT count(*) FROM 'main'.sqlite_master",
    "SELECT count(*) FROM 'json_tree'('[1]')",
    "SELECT count(*) FROM (SELECT 1 AS x) NATURAL JOIN 'pragma_database_list'",
    "SELECT 1 AS pragma_x", "SELECT 1 AS sqlite_x", "SELECT 1 FROM fr_documents AS sqlite_y",
])
def test_reserved_names_in_name_positions_are_denied(gov_db, stmt):
    e = _refused(gov_db, stmt)
    assert e.kind == "denied" and str(e) == ERR_DENIED


@pytest.mark.parametrize("stmt, rows", [
    ("SELECT 'sqlite_master'", [["sqlite_master"]]),
    ("SELECT 'completion'", [["completion"]]),
    ("SELECT 'zipfile', 'json_tree'", [["zipfile", "json_tree"]]),
    ("SELECT count(*) FROM fr_documents WHERE type = 'rtree'", [[0]]),
    ("SELECT count(*) FROM fr_documents WHERE type IN ('rtree', 'pragma_x', 'Rule')", [[5]]),
    ("SELECT count(*) FROM fr_documents a JOIN fr_documents b ON a.type = 'sqlite_x'", [[0]]),
    ("SELECT count(*) FROM fr_documents WHERE title LIKE 'sqlite_%'", [[0]]),
    ("SELECT coalesce(NULL, 'dbstat'), 'fts5' || 'x'", [["dbstat", "fts5x"]]),
    ("SELECT x FROM (SELECT 'generate_series' AS x)", [["generate_series"]]),
])
def test_reserved_words_as_string_values_run(gov_db, stmt, rows):
    assert run_sql(gov_db, stmt).rows == rows


# -- fix round 6: NATURAL and USING refused, parenthesized FROM items, string aliases ---------

# SQLite never asks the authorizer about the columns NATURAL JOIN and JOIN ... USING compare,
# so both forms are refused outright: these were table-name oracles or ran other modules
NATURAL_AND_USING = [
    "SELECT count(*) FROM (SELECT 'table' AS type, 'fr_documents' AS name) "
    "NATURAL JOIN ('sqlite_master')",
    "SELECT count(*) FROM (SELECT 'table' AS type, 'nosuch' AS name) "
    "NATURAL JOIN ('sqlite_master')",
    "SELECT count(*) FROM (SELECT 'table' AS type) JOIN ('sqlite_master') USING (type)",
    "SELECT count(*) FROM (SELECT 'table' AS type) NATURAL JOIN ('sqlite_schema')",
    "SELECT count(*) FROM (SELECT 'fr_documents' AS name) NATURAL JOIN ( 'sqlite_master' )",
    "SELECT count(*) FROM (SELECT 'fr_documents' AS name) NATURAL JOIN (('sqlite_master'))",
    "SELECT count(*) FROM (SELECT 'fr_documents' AS name) NATURAL JOIN (/**/'sqlite_master')",
    "SELECT count(*) FROM (SELECT 0 AS key) NATURAL JOIN ('json_tree'('[1]'))",
    "SELECT count(*) FROM (SELECT 'fr_documents' AS name) NATURAL JOIN ('dbstat')",
    "SELECT count(*) FROM (SELECT 1 AS x) AS window NATURAL JOIN ('pragma_database_list')",
    # on the listed tables too: the form itself is refused
    "SELECT count(*) FROM fr_documents a NATURAL JOIN fr_documents b",
    "SELECT count(*) FROM fr_documents a JOIN fr_documents b USING (id)",
    "SELECT count(*) FROM fr_documents a natural left outer join fr_documents b",
    "SELECT count(*) FROM fr_documents a LEFT natural JOIN fr_documents b",
    "SELECT count(*) FROM fr_documents a join fr_documents b using(id)",
    "SELECT count(*) FROM fr_documents a/**/NATURAL/**/JOIN fr_documents b",
]


@pytest.mark.parametrize("stmt", NATURAL_AND_USING)
def test_natural_and_using_joins_are_denied(gov_db, stmt):
    e = _refused(gov_db, stmt)
    assert e.kind == "denied" and str(e) == ERR_DENIED


@pytest.mark.parametrize("stmt", [
    "SELECT count(*) FROM ('sqlite_master')",
    "SELECT * FROM ('sqlite_master')",
    "SELECT count(*) FROM ( 'sqlite_master' )",
    "SELECT count(*) FROM (('sqlite_schema'))",
    "SELECT count(*) FROM (/**/'sqlite_master')",
    "SELECT count(*) FROM (fr_documents, 'sqlite_master')",
    "SELECT count(*) FROM fr_documents, ('sqlite_master')",
    "SELECT count(*) FROM fr_documents JOIN ('sqlite_master') ON 1",
    "SELECT count(*) FROM fr_documents a JOIN (fr_documents b, 'sqlite_master') ON 1",
    "SELECT count(*) FROM ('json_tree'('[1]'))",
    "SELECT count(*) FROM fr_documents WHERE id IN (SELECT 1 FROM ('sqlite_master'))",
    "WITH x AS (SELECT 1) SELECT count(*) FROM x, ('sqlite_master')",
    # `window` is not a reserved word: an alias named so keeps the FROM list going
    "SELECT count(*) FROM fr_documents window, 'sqlite_master'",
    "SELECT count(*) FROM fr_documents AS window, 'sqlite_master'",
    # `x IN 'name'` reads a table
    "SELECT 'table' IN 'sqlite_master'",
    "SELECT 'json_each' IN 'pragma_module_list'",
    "SELECT count(*) FROM fr_documents WHERE id NOT IN 'sqlite_master'",
    # string aliases, as bare aliases
    "SELECT 1 AS 'pragma_x'",
    "SELECT 1 'sqlite_x'",
    "SELECT 'a' 'json_tree'",
    "SELECT CASE WHEN 1 THEN 2 END 'pragma_y'",
    "SELECT count(*) FROM fr_documents 'sqlite_master'",
    "SELECT count(*) FROM fr_documents AS 'sqlite_master'",
    "SELECT count(*) FROM (SELECT 1) 'sqlite_x'",
    "SELECT count(*) 'pragma_z' FROM fr_documents",
])
def test_reserved_strings_in_name_positions_are_denied_by_the_name_check(gov_db, stmt):
    assert sqlguard._names_reserved(stmt)
    e = _refused(gov_db, stmt)
    assert e.kind == "denied" and str(e) == ERR_DENIED


@pytest.mark.parametrize("stmt", [
    "SELECT count(*) FROM ('json_tree'('[1]'))",
    "SELECT count(*) FROM fr_documents JOIN ('sqlite_master') ON 1",
    "SELECT count(*) FROM fr_documents d JOIN ('sqlite_master') ON d.type = sqlite_master.type",
    "SELECT count(*) FROM ('sqlite_master')",
    "SELECT count(*) FROM (('sqlite_schema'))",
    "SELECT count(*) FROM fr_documents, ('pragma_function_list')",
    "SELECT count(*) FROM fr_documents WHERE id IN (SELECT 1 FROM ('sqlite_master'))",
    "SELECT 'table' IN 'sqlite_master'",
    "SELECT 'json_each' IN 'pragma_module_list'",
    "SELECT count(*) FROM fr_documents JOIN 'json_tree'('[1]') ON 1",
])
def test_the_authorizer_denies_named_system_objects_without_the_name_check(
        gov_db, monkeypatch, stmt):
    """With NATURAL and USING refused, every read reaches the authorizer: with the name check
    switched off, a parenthesized or string-named system object is still denied."""
    monkeypatch.setattr(sqlguard, "_names_reserved", lambda statement: False)
    e = _refused(gov_db, stmt)
    assert e.kind == "denied" and str(e) == ERR_DENIED


@pytest.mark.parametrize("stmt", NATURAL_AND_USING)
def test_natural_and_using_are_refused_without_the_name_check(gov_db, monkeypatch, stmt):
    monkeypatch.setattr(sqlguard, "_names_reserved", lambda statement: False)
    e = _refused(gov_db, stmt)
    assert e.kind == "denied" and str(e) == ERR_DENIED


@pytest.mark.parametrize("stmt, rows", [
    ("SELECT count(*) FROM fr_documents a JOIN fr_documents b ON a.id = b.id", [[N]]),
    ("SELECT count(*) FROM fr_documents a LEFT JOIN fr_documents b ON a.id = b.id "
     "AND b.type = 'sqlite_x'", [[N]]),
    ("SELECT count(*) FROM fr_documents a JOIN fr_documents b ON a.type IN ('x', 'sqlite_y')",
     [[0]]),
    ("SELECT count(*) FROM fr_documents d JOIN (SELECT id FROM fr_documents) e ON d.id = e.id",
     [[N]]),
    ("SELECT count(*) FROM fr_documents, json_each(fr_documents.cfr_parts)", [[7]]),
    ("SELECT value FROM json_each('[\"sqlite_master\"]')", [["sqlite_master"]]),
    ("WITH x AS (SELECT 'pragma_x' AS v) SELECT v FROM x", [["pragma_x"]]),
    ("SELECT x FROM (SELECT 'dbstat' AS x)", [["dbstat"]]),
    ("SELECT 'sqlite_master' AS x", [["sqlite_master"]]),
    ("SELECT CASE WHEN 1 THEN 'sqlite_x' ELSE 'pragma_y' END", [["sqlite_x"]]),
    ("SELECT count(*) FROM fr_documents WHERE type BETWEEN 'rtree' AND 'zipfile'", [[0]]),
    ("SELECT count(*) FROM fr_documents WHERE type IS NOT 'dbstat'", [[N]]),
    ("SELECT count(*) FROM fr_documents WHERE NOT type = 'fts5'", [[N]]),
    ("SELECT json_extract('{\"a\": \"json_tree\"}', '$.a')", [["json_tree"]]),
    ("SELECT count(*) FROM fr_documents WHERE id = 'x' OR 'sqlite_master' = type", [[0]]),
    ("SELECT natural_x FROM (SELECT 1 AS natural_x)", [[1]]),
    ("SELECT \"natural\", \"using\" FROM (SELECT 1 AS \"natural\", 2 AS \"using\")",
     [[1, 2]]),
])
def test_on_joins_json_each_ctes_and_string_values_still_run(gov_db, stmt, rows):
    assert run_sql(gov_db, stmt).rows == rows
