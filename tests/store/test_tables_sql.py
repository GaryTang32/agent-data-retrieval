"""Guarded read-only SQL (Phase 3 spec §8.1, §8.2): the authorizer whitelist, one statement,
the deterministic step budget, the row and size caps, fixed error messages, deterministic date
functions and the total order. Fixture stores under `tmp_path`; nothing reads `data/` or
`.cache/`."""

import sqlite3

import pytest

from adr_store.tables import overlay as ov
from adr_store.tables import sqlguard
from adr_store.tables.build import build_tables
from adr_store.tables.contracts import load_contracts
from adr_store.tables.engine import ViewDB, run_query
from adr_store.tables.provenance import RowRecord
from adr_store.tables.sqlguard import (
    ERR_BUDGET,
    ERR_DENIED,
    ERR_ROWS,
    ERR_SYNTAX,
    FUNCTIONS,
    SQL_MAX_BYTES,
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
    return ViewDB.build(path, ov.load_manifest(path, result.tables_id), result.tables_id, None)


@pytest.fixture(scope="module")
def gov_db_reversed(gov_db):
    return _copy_reversed(gov_db)


@pytest.fixture(scope="module")
def big_db():
    """1,205 Federal Register rows (more than the row cap), no overlay."""
    c = load_contracts()["fr_documents"]
    rows = [RowRecord(doc_id=f"d{i}", prov={}, row={
        "id": f"2024-{i:05d}", "type": "Rule", "agency": None, "publication_date": "2024-01-01",
        "year": 2024, "title": None, "cfr_parts": [], "action": None, "effective_on": None,
        "status": None, "other_ids": [], "title_state": None, "title_waterway_keys": []})
        for i in range(1205)]
    return ViewDB.from_rows({"fr_documents": c}, {"fr_documents": rows})


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
    assert (SQL_ROW_CAP, SQL_STEP_BUDGET, SQL_STEP_EVERY, SQL_MAX_BYTES) == \
        (1000, 5_000_000, 1000, 2_000_000)


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
    "INSERT INTO fr_documents SELECT * FROM fr_documents ORDER BY 1",
    "CREATE TEMP TABLE x AS SELECT * FROM fr_documents ORDER BY 1",
])
def test_reading_anything_but_the_listed_tables_is_denied(gov_db, stmt):
    e = _refused(gov_db, stmt)
    assert e.kind == "denied" and str(e) == ERR_DENIED


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
