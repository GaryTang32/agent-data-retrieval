"""Guarded read-only SQL over a caller's view database (Phase 3 spec §8.1, §8.2).

`run_sql` runs one statement on a `ViewDB` (which holds only the caller's visible rows) under:

- an authorizer that allows `SELECT`, reading the view's tables, `json_each` and common table
  expressions, recursive CTEs, and calling the functions in `FUNCTIONS`, and denies everything
  else (writes, DDL, `ATTACH`, `PRAGMA`, transactions, temporary objects, `sqlite_master`,
  `load_extension`, `random`, the clock);
- deterministic date and time functions: `date`, `datetime`, `strftime` and `julianday` are
  replaced by Python functions that refuse the clock (`'now'`, `'localtime'`, `'utc'`, or no
  time value) and compute every other value with SQLite's own date code on a private
  connection that holds no tables, so the built-in versions are never reached;
- one statement: a `;` after `strip_terminator` is a syntax refusal;
- a budget of virtual-machine steps (no wall clock, so the cut-off is deterministic): recursive
  CTEs and cross joins stop at `SQL_STEP_BUDGET`, which is how "beyond a depth" is enforced;
- at most `SQL_ROW_CAP` rows (one more only sets `truncated`) and `SQL_MAX_BYTES` of canonical
  JSON; SQLite's value-length limit is lowered to the same bound for the call, so one value
  over it is refused the same way.

A statement with its own top-level `ORDER BY` keeps it; any other is wrapped as
`SELECT * FROM (<statement>) ORDER BY 1, …, n` over every output column, so the order is total.
Every refusal is a `SqlRefused` whose message is one of four fixed texts, never the engine's,
so an error cannot reveal hidden rows or table internals.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

from adr_store.tables.engine import ViewDB

SQL_ROW_CAP = 1000
SQL_STEP_BUDGET = 5_000_000
SQL_STEP_EVERY = 1000
SQL_MAX_BYTES = 2_000_000

ERR_SYNTAX = "sql refused (syntax): one SELECT statement over the listed tables"
ERR_DENIED = ("sql refused (denied): only reading the listed tables with whitelisted functions "
              "is allowed")
ERR_BUDGET = "sql refused (budget): the statement ran past its step budget; narrow it"
ERR_ROWS = "sql refused (too many rows): the result is over 2 MB; select fewer rows or columns"

DATE_FUNCTIONS = frozenset({"date", "datetime", "strftime", "julianday"})
FUNCTIONS: frozenset[str] = frozenset("""
    avg count group_concat max min sum total abs coalesce ifnull iif instr length lower ltrim
    nullif printf format replace round rtrim substr substring trim typeof upper like glob
    casefold json_extract json_array_length json_type ceil floor
""".split()) | DATE_FUNCTIONS

Kind = Literal["syntax", "denied", "budget", "rows"]
_MESSAGES: dict[str, str] = {"syntax": ERR_SYNTAX, "denied": ERR_DENIED, "budget": ERR_BUDGET,
                             "rows": ERR_ROWS}
_CLOCK = ("now", "localtime", "utc")   # date arguments that read the clock or the time zone
_SQLITE_TOOBIG = 18
_SPACE = " \t\n\v\f\r"   # SQLite's whitespace; any other character from U+0080 is a word one


class SqlRefused(ValueError):
    """A refused statement; `str(e)` is the fixed message of its `kind`."""

    def __init__(self, kind: Kind):
        self.kind: Kind = kind
        super().__init__(_MESSAGES[kind])


@dataclass(frozen=True)
class SqlOutcome:
    columns: list[str]
    rows: list[list]
    truncated: bool


# -- the statement tokenizer -----------------------------------------------------------------

def _tokens(sql: str) -> Iterator[tuple[str, int, int]]:
    """(kind, start, end) of each token: `space`, `comment`, `quoted` (a string or quoted
    identifier), `word` or `punct` (one character). Unterminated comments and quotes run to the
    end of the text."""
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in _SPACE:
            kind, j = "space", i + 1
            while j < n and sql[j] in _SPACE:
                j += 1
        elif sql.startswith("--", i):
            kind, j = "comment", sql.find("\n", i)
            j = n if j < 0 else j + 1
        elif sql.startswith("/*", i):
            kind, j = "comment", sql.find("*/", i + 2)
            j = n if j < 0 else j + 2
        elif ch in "'\"`[":
            close = "]" if ch == "[" else ch
            kind, j = "quoted", i + 1
            while j < n:
                if sql[j] == close:
                    if close != "]" and sql.startswith(close, j + 1):   # a doubled quote
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
        elif not _is_word_char(ch):
            kind, j = "punct", i + 1
        else:
            kind, j = "word", i + 1
            while j < n and _is_word_char(sql[j]):
                j += 1
        yield kind, i, j
        i = j


def _is_word_char(ch: str) -> bool:
    """A character of an SQLite identifier or keyword: ASCII letters, digits, `_` and `$`, and
    every character from U+0080."""
    return not ch.isascii() or ch.isalnum() or ch in "_$"


def _significant(sql: str) -> list[tuple[str, int, int]]:
    return [t for t in _tokens(sql) if t[0] not in ("space", "comment")]


def strip_terminator(statement: str) -> str:
    """The statement without trailing whitespace and comments and one trailing `;`."""
    toks = _significant(statement)
    if toks and toks[-1][0] == "punct" and statement[toks[-1][1]] == ";":
        toks = toks[:-1]
    return statement[:toks[-1][2]] if toks else ""


def _shape(statement: str) -> tuple[bool, bool]:
    """(whether it is one statement with balanced parentheses, whether it has a top-level
    `ORDER BY`)."""
    depth, order_by, prev = 0, False, ""
    for kind, start, end in _significant(statement):
        text = statement[start:end]
        if kind == "punct":
            if text == ";":
                return False, order_by
            depth += {"(": 1, ")": -1}.get(text, 0)
            if depth < 0:
                return False, order_by
        elif kind == "word" and depth == 0 and prev == "order" and text.lower() == "by":
            order_by = True
        prev = text.lower() if kind == "word" and depth == 0 else ""
    return depth == 0, order_by


def has_top_level_order_by(statement: str) -> bool:
    """Whether the statement has an `ORDER BY` outside parentheses, strings, quoted identifiers
    and comments."""
    return _shape(statement)[1]


# -- the guard -------------------------------------------------------------------------------

class _Guard:
    """The authorizer, step counter and date functions of one `run_sql` call. It records why a
    statement failed: past the budget, or denied (by the authorizer or a date function)."""

    def __init__(self, tables: frozenset[str]):
        self.tables = tables
        self.steps = 0
        self.over_budget = False
        self.denied = False
        self._dates: sqlite3.Connection | None = None

    def authorize(self, action: int, arg1: str | None, arg2: str | None, db: str | None,
                  _trigger: str | None) -> int:
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            # a common table expression is read with no database; a table of the view or
            # json_each in "main"
            if db is None or (db == "main" and (arg1 in self.tables or arg1 == "json_each")):
                return sqlite3.SQLITE_OK
        elif action == sqlite3.SQLITE_FUNCTION and arg2 is not None \
                and arg2.lower() in FUNCTIONS:
            return sqlite3.SQLITE_OK
        self.denied = True
        return sqlite3.SQLITE_DENY

    def progress(self) -> int:
        self.steps += SQL_STEP_EVERY
        if self.steps > SQL_STEP_BUDGET:
            self.over_budget = True
            return 1
        return 0

    def date_function(self, name: str, needs: int):
        """`name` computed by SQLite's date code, refusing the clock: any argument naming
        'now', 'localtime' or 'utc' (in any case and position), or fewer than `needs`
        arguments (no time value means now)."""
        def fn(*args: Any) -> Any:
            texts = [a.decode("utf-8", "replace") if isinstance(a, bytes) else a
                     for a in args if isinstance(a, (str, bytes))]
            if len(args) < needs or any(w in t.casefold() for t in texts for w in _CLOCK):
                self.denied = True
                raise ValueError("the clock is not deterministic")
            if self._dates is None:
                self._dates = sqlite3.connect(":memory:")
            sql = f"SELECT {name}({', '.join('?' * len(args))})"
            return self._dates.execute(sql, args).fetchone()[0]
        return fn

    def close(self) -> None:
        if self._dates is not None:
            self._dates.close()
            self._dates = None

    def refusal(self, e: sqlite3.Error) -> SqlRefused:
        if self.over_budget:
            return SqlRefused("budget")
        if self.denied:
            return SqlRefused("denied")
        if getattr(e, "sqlite_errorcode", None) == _SQLITE_TOOBIG:
            return SqlRefused("rows")
        return SqlRefused("syntax")


def _cell(v: Any) -> Any:
    return "blob:" + bytes(v).hex() if isinstance(v, (bytes, memoryview)) else v


def _execute(conn: sqlite3.Connection, body: str, ordered: bool
             ) -> tuple[list[str], list[tuple]]:
    if ordered:
        sql = body
    else:
        probe = conn.execute(f"SELECT * FROM (\n{body}\n) LIMIT 0")
        n = len(probe.description)
        sql = (f"SELECT * FROM (\n{body}\n) ORDER BY "
               f"{', '.join(str(i) for i in range(1, n + 1))}")
    cur = conn.execute(sql)
    if cur.description is None:   # not a query (the authorizer stops these first)
        raise sqlite3.ProgrammingError("not a query")
    return [d[0] for d in cur.description], cur.fetchmany(SQL_ROW_CAP + 1)


def run_sql(db: ViewDB, statement: str) -> SqlOutcome:
    """The rows of one read-only statement over the view database, in a total order."""
    if not isinstance(statement, str) or "\x00" in statement:
        raise SqlRefused("syntax")
    try:
        statement.encode("utf-8")
    except UnicodeEncodeError:   # a lone surrogate
        raise SqlRefused("syntax") from None
    body = strip_terminator(statement)
    one, ordered = _shape(body)
    if not one:
        raise SqlRefused("syntax")
    guard = _Guard(frozenset(db.contracts))
    refusal: SqlRefused | None = None
    with db.exclusive() as conn:
        for name in sorted(DATE_FUNCTIONS):
            conn.create_function(name, -1, guard.date_function(name, 2 if name == "strftime"
                                                                 else 1), deterministic=True)
        length = conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, SQL_MAX_BYTES)
        conn.set_authorizer(guard.authorize)
        conn.set_progress_handler(guard.progress, SQL_STEP_EVERY)
        try:
            columns, got = _execute(conn, body, ordered)
        except sqlite3.Error as e:
            refusal = guard.refusal(e)
        finally:
            conn.set_progress_handler(None, 0)
            conn.set_authorizer(None)
            conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, length)
            if conn.in_transaction:
                conn.rollback()
            guard.close()
    if refusal is not None:
        raise refusal from None
    rows = [[_cell(v) for v in r] for r in got[:SQL_ROW_CAP]]
    size = len(json.dumps(rows, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False).encode("utf-8"))
    if size > SQL_MAX_BYTES:
        raise SqlRefused("rows")
    return SqlOutcome(columns, rows, len(got) > SQL_ROW_CAP)
