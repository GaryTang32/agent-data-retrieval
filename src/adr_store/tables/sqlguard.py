"""Guarded read-only SQL over a caller's view database (Phase 3 spec §8.1, §8.2, rulings
P19, P20).

`run_sql` runs one statement on a `ViewDB` (which holds only the caller's visible rows) under:

- an authorizer that allows `SELECT`, recursive CTEs, calling the functions in `FUNCTIONS`, and
  reading only the view's tables, `json_each` and the statement's own common table expressions,
  all names compared case-folded. SQLite reports a table read as (table, column, `main`), but a
  FROM item whose columns are not used comes as (name as written, `""`, no database), for real
  tables and CTEs alike; such a read is allowed only for a view table, `json_each` or a CTE name
  the statement defines, and a CTE named like a system object (`sqlite_*`, `pragma_*`, a virtual
  table module such as `json_tree`) does not count. Everything else is denied: writes, DDL,
  `ATTACH`, `PRAGMA`, transactions, temporary objects, `sqlite_master`, `load_extension`,
  `random`, the clock;
- deterministic date and time functions: `date`, `datetime`, `strftime` and `julianday` are
  replaced by Python functions that refuse the clock (`'now'`, `'localtime'`, `'utc'`, or no
  time value) and compute every other value with SQLite's own date code on a private
  connection that holds no tables, so the built-in versions are never reached;
- one statement: a `;` after `strip_terminator` is a syntax refusal;
- a budget of virtual-machine steps (no wall clock, so the cut-off is deterministic): recursive
  CTEs and cross joins stop at `SQL_STEP_BUDGET`, which is how "beyond a depth" is enforced;
- bounded work per step (P20): every value, and every row SQLite builds, is at most
  `SQL_MAX_VALUE` bytes (16 KB, the build-time row bound; stored values are at most 8 KB), and
  the functions whose result can be much longer than their inputs
  (`replace`, `printf`/`format`, `substr`/`substring` and the `group_concat` aggregate) are
  Python wrappers that compute with SQLite's own code on the private connection and charge
  `len(result) // SQL_CHARGE_BYTES` extra steps to the budget. A value over the limit, the
  final result or any intermediate one, is refused as `rows` ("result too large");
- at most `SQL_ROW_CAP` rows (one more only sets `truncated`) and `SQL_MAX_BYTES` of canonical
  JSON, counted row by row as the cursor steps, so the refusal comes before the rest is fetched.

Known limit (R1): copying a value already built (a recursive `UNION` that carries one, or
DISTINCT / GROUP BY / an inner ORDER BY without LIMIT over a join with one) calls no function,
so nothing is charged beyond virtual-machine steps, and SQLite's sorter and ephemeral storage
hold up to `rows × SQL_MAX_VALUE`. The step budget bounds the rows: the worst probe measured, a
recursive `UNION` re-copying a 16 KB value, stops at the budget after about 13 s with about
4 GB of temporary files. Running out of temporary storage is refused as `budget`.

Known limit (wide DISTINCT): with `DISTINCT` and its own `ORDER BY`, SQLite's sorter carries
each row twice once the tie-breakers are added, so rows over about 8 KB (one stored row today,
`papers` row 44 at 8.9 KB) are refused as `rows`. `SELECT * FROM (SELECT DISTINCT …) ORDER BY …`
reads them whole.

Order (P19): a statement with its own top-level `ORDER BY` keeps it, with the positional
tie-breakers `, 1, …, n` (every output column) appended before any top-level `LIMIT`; any other is
wrapped as `SELECT * FROM (<statement>) ORDER BY 1, …, n`. Either way the order is total, and a
statement without a `LIMIT` gets `LIMIT SQL_ROW_CAP + 1` so SQLite keeps only the rows it returns.
Cells come back as JSON values: a blob as `"blob:<hex>"`, a non-finite real (SQLite yields
infinity on overflow, as in `9e999`) as null, the way SQLite itself stores NaN.

Every refusal is a `SqlRefused` whose message is one of four fixed texts, never the engine's,
so an error cannot reveal hidden rows or table internals. The authorizer, budget and limit are
installed for the call only. The function overrides cannot be unregistered from a connection,
so they stay registered on the view database once the first call installs them, and dispatch
to the call in progress: they act only inside `run_sql` and raise anywhere else. `query_table`
uses none of them (date, datetime, strftime, julianday, replace, printf, format, substr,
substring, group_concat), so it works on the same database before and after `run_sql`.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Literal

from adr_store.tables.contracts import MAX_ROW_BYTES
from adr_store.tables.engine import ViewDB
from adr_store.tool_records import canonical

SQL_ROW_CAP = 1000
SQL_STEP_BUDGET = 5_000_000
SQL_STEP_EVERY = 1000
SQL_MAX_BYTES = 2_000_000
# SQLite's length limit for the call: the most bytes in one value or in any row SQLite builds
# (a sorter, DISTINCT or ephemeral row). It is the build-time row bound, so every stored row,
# and every stored value, can be read and sorted whole.
SQL_MAX_VALUE = MAX_ROW_BYTES
SQL_CHARGE_BYTES = 64    # an amplifying function's result charges one step per 64 bytes

ERR_SYNTAX = "sql refused (syntax): one SELECT statement over the listed tables"
ERR_DENIED = ("sql refused (denied): only reading the listed tables with whitelisted functions "
              "is allowed")
ERR_BUDGET = "sql refused (budget): the statement ran past its step budget; narrow it"
ERR_ROWS = "sql refused (too many rows): the result is over 2 MB; select fewer rows or columns"

DATE_FUNCTIONS = frozenset({"date", "datetime", "strftime", "julianday"})
AMPLIFYING = frozenset({"replace", "printf", "format", "substr", "substring"})  # + group_concat
FUNCTIONS: frozenset[str] = frozenset("""
    avg count group_concat max min sum total abs coalesce ifnull iif instr length lower ltrim
    nullif printf format replace round rtrim substr substring trim typeof upper like glob
    casefold json_extract json_array_length json_type ceil floor
""".split()) | DATE_FUNCTIONS

Kind = Literal["syntax", "denied", "budget", "rows"]
_MESSAGES: dict[str, str] = {"syntax": ERR_SYNTAX, "denied": ERR_DENIED, "budget": ERR_BUDGET,
                             "rows": ERR_ROWS}
_CLOCK = ("now", "localtime", "utc")   # date arguments that read the clock or the time zone
_SQLITE_NOMEM, _SQLITE_FULL, _SQLITE_TOOBIG = 7, 13, 18
_SPACE = " \t\n\v\f\r"   # SQLite's whitespace; any other character from U+0080 is a word one


def _modules() -> frozenset[str]:
    """Virtual table modules: a CTE with one of these names (or `sqlite_*`, `pragma_*`) is not
    trusted to be the object a no-database read names."""
    known = {"json_each", "json_tree", "jsonb_each", "jsonb_tree", "dbstat", "sqlite_dbpage",
             "sqlite_stmt", "generate_series", "carray", "geopoly", "rtree", "rtree_i32", "fts3",
             "fts4", "fts5", "fts4aux", "fts5vocab", "fts3tokenize", "completion", "zipfile"}
    try:
        with closing(sqlite3.connect(":memory:")) as conn:
            known |= {r[0].casefold() for r in conn.execute("PRAGMA module_list")}
    except sqlite3.Error:
        pass
    return frozenset(known)


_MODULES = _modules()


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


@dataclass(frozen=True)
class _Shape:
    one: bool               # one statement with balanced parentheses
    order_end: int | None   # end of the top-level ORDER BY clause (None: there is none)
    limit: bool             # a top-level LIMIT follows it
    ctes: frozenset[str]    # the CTE names the statement defines, case-folded


def _unquote(text: str) -> str:
    if text[:1] in "'\"`" and len(text) >= 2 and text[-1] == text[0]:
        return text[1:-1].replace(text[0] * 2, text[0])
    if text[:1] == "[" and text.endswith("]"):
        return text[1:-1]
    return text


def _cte_names(statement: str, toks: list[tuple[str, int, int]]) -> frozenset[str]:
    """Names in CTE position: after `WITH`, `RECURSIVE` or `,`, followed by an optional column
    list and `AS [NOT] [MATERIALIZED] (`."""
    words = [statement[s:e].lower() for _, s, e in toks]
    names = set()
    for i in range(1, len(toks)):
        if toks[i][0] not in ("word", "quoted") or words[i - 1] not in ("with", "recursive", ","):
            continue
        j = i + 1
        if j < len(toks) and words[j] == "(":
            depth = 0
            while j < len(toks):
                depth += {"(": 1, ")": -1}.get(words[j], 0)
                j += 1
                if depth == 0:
                    break
        if j < len(toks) and words[j] == "as":
            j += 1
            for optional in ("not", "materialized"):
                if j < len(toks) and words[j] == optional:
                    j += 1
            if j < len(toks) and words[j] == "(":
                names.add(_unquote(statement[toks[i][1]:toks[i][2]]).casefold())
    return frozenset(n for n in names if not n.startswith(("sqlite_", "pragma_"))
                     and n not in _MODULES)


def _shape(statement: str) -> _Shape:
    toks = _significant(statement)
    depth, prev = 0, ""
    order, order_end, limit = False, None, False
    bad = _Shape(False, None, False, frozenset())
    for kind, start, end in toks:
        text = statement[start:end]
        low = text.lower()
        if kind == "punct":
            if text == ";":
                return bad
            depth += {"(": 1, ")": -1}.get(text, 0)
            if depth < 0:
                return bad
        top_word = kind == "word" and depth == 0
        if top_word and low == "limit" and order:
            limit = True
        if top_word and prev == "order" and low == "by" and not limit:
            order = True
        if order and not limit:
            order_end = end
        prev = low if top_word else ""
    if depth != 0:
        return bad
    return _Shape(True, order_end, limit, _cte_names(statement, toks))


def has_top_level_order_by(statement: str) -> bool:
    """Whether the statement has an `ORDER BY` outside parentheses, strings, quoted identifiers
    and comments."""
    return _shape(statement).order_end is not None


# -- the guard -------------------------------------------------------------------------------

class _Guard:
    """The authorizer, step counter and function overrides of one `run_sql` call. It records
    why a statement failed: past the budget, denied (by the authorizer or a date function), or
    a value over `SQL_MAX_VALUE`."""

    def __init__(self, tables: frozenset[str], ctes: frozenset[str]):
        self.tables = frozenset(t.casefold() for t in tables) | {"json_each"}
        self.ctes = ctes
        self.steps = 0
        self.over_budget = False
        self.denied = False
        self.too_big = False
        self._helper: sqlite3.Connection | None = None

    def authorize(self, action: int, arg1: str | None, arg2: str | None, db: str | None,
                  _trigger: str | None) -> int:
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ and arg1 is not None:
            name = arg1.casefold()
            if db == "main" and name in self.tables:
                return sqlite3.SQLITE_OK
            if db is None and arg2 == "" and (name in self.tables or name in self.ctes):
                return sqlite3.SQLITE_OK   # a FROM item whose columns are not used
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

    def charge(self, result: Any) -> None:
        """Charge `len(result) // SQL_CHARGE_BYTES` steps for a text or blob result."""
        if isinstance(result, (str, bytes)):
            self.steps += len(result) // SQL_CHARGE_BYTES
            if self.steps > SQL_STEP_BUDGET:
                self.over_budget = True
                raise ValueError("past the step budget")

    def _private(self) -> sqlite3.Connection:
        if self._helper is None:
            self._helper = sqlite3.connect(":memory:")
            self._helper.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, SQL_MAX_VALUE)
        return self._helper

    def sqlite(self, name: str, args: tuple) -> Any:
        """`name(*args)` computed by SQLite on the private connection (no tables, values
        limited as on the view's)."""
        try:
            return self._private().execute(f"SELECT {name}({', '.join('?' * len(args))})",
                                        args).fetchone()[0]
        except sqlite3.Error as e:
            if getattr(e, "sqlite_errorcode", None) == _SQLITE_TOOBIG:
                self.too_big = True
            raise

    def date(self, name: str, args: tuple) -> Any:
        """`name(*args)`, refusing the clock: any argument naming 'now', 'localtime' or 'utc'
        (in any case and position), or no time value (which means now)."""
        needs = 2 if name == "strftime" else 1
        texts = [a.decode("utf-8", "replace") if isinstance(a, bytes) else a
                 for a in args if isinstance(a, (str, bytes))]
        if len(args) < needs or any(w in t.casefold() for t in texts for w in _CLOCK):
            self.denied = True
            raise ValueError("the clock is not deterministic")
        return self.sqlite(name, args)

    def amplify(self, name: str, args: tuple) -> Any:
        """`name(*args)`, charged by the length of its result."""
        result = self.sqlite(name, args)
        self.charge(result)
        return result

    def text(self, v: Any) -> str:
        """A value as SQLite's text conversion gives it."""
        if isinstance(v, str):
            return v
        if isinstance(v, int):
            return str(v)
        return self._private().execute("SELECT CAST(? AS TEXT)", (v,)).fetchone()[0]

    def group_concat(self) -> Any:
        """A new `group_concat(X[, sep])` accumulator with SQLite's semantics: NULL values
        skipped, `,` by default, a NULL separator adds nothing, NULL when no value; charged by
        the length of its result."""
        guard = self

        class GroupConcat:
            def __init__(self):
                self.parts: list[str] = []
                self.size = 0
                self.any = False

            def _add(self, text: str) -> None:
                self.size += len(text.encode("utf-8"))
                if self.size > SQL_MAX_VALUE:
                    guard.too_big = True
                    raise ValueError("value too long")
                self.parts.append(text)

            def step(self, *args: Any) -> None:
                if len(args) not in (1, 2):
                    raise ValueError("group_concat takes one or two arguments")
                if args[0] is None:
                    return
                if self.any:
                    sep = "," if len(args) == 1 else args[1]
                    if sep is not None:
                        self._add(guard.text(sep))
                self.any = True
                self._add(guard.text(args[0]))

            def finalize(self) -> str | None:
                if not self.any:
                    return None
                result = "".join(self.parts)
                guard.charge(result)
                return result

        return GroupConcat()

    def close(self) -> None:
        if self._helper is not None:
            self._helper.close()
            self._helper = None

    def refusal(self, e: sqlite3.Error) -> SqlRefused:
        if self.over_budget:
            return SqlRefused("budget")
        if self.denied:
            return SqlRefused("denied")
        code = getattr(e, "sqlite_errorcode", None)
        if self.too_big or code == _SQLITE_TOOBIG:
            return SqlRefused("rows")   # the result, or an intermediate value, is too large
        if code in (_SQLITE_NOMEM, _SQLITE_FULL):
            return SqlRefused("budget")   # temporary storage ran out before the step budget
        return SqlRefused("syntax")


class _Slot:
    """The function overrides of one connection, installed once (Python's sqlite3 cannot
    unregister a function: `create_function(name, n, None)` registers a broken one). They
    dispatch to the guard of the `run_sql` call in progress and refuse outside one, so the
    connection never holds a finished call's guard."""

    def __init__(self, conn: sqlite3.Connection):
        self.guard: _Guard | None = None
        for name in sorted(DATE_FUNCTIONS):
            conn.create_function(name, -1, self._call("date", name), deterministic=True)
        for name in sorted(AMPLIFYING):   # not deterministic: evaluated, and charged, per row
            conn.create_function(name, -1, self._call("amplify", name))
        slot = self

        class GroupConcat:
            def __init__(self):
                self.inner = slot._active().group_concat()

            def step(self, *args: Any) -> None:
                self.inner.step(*args)

            def finalize(self) -> str | None:
                return self.inner.finalize()

        conn.create_aggregate("group_concat", -1, GroupConcat)

    def _active(self) -> _Guard:
        if self.guard is None:
            raise ValueError("only guarded sql may call this function")
        return self.guard

    def _call(self, method: str, name: str):
        def fn(*args: Any) -> Any:
            return getattr(self._active(), method)(name, args)
        return fn


def _slot(db: ViewDB, conn: sqlite3.Connection) -> _Slot:
    slot = db.__dict__.get("_sqlguard_slot")
    if slot is None:
        slot = db.__dict__["_sqlguard_slot"] = _Slot(conn)
    return slot


def _cell(v: Any) -> Any:
    if isinstance(v, (bytes, memoryview)):
        return "blob:" + bytes(v).hex()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def _row(r: tuple) -> list:
    return [_cell(v) for v in r]


def _statement(conn: sqlite3.Connection, body: str, shape: _Shape) -> str:
    """The statement that runs: totally ordered, limited to the rows it can return."""
    n = len(conn.execute(f"SELECT * FROM (\n{body}\n) LIMIT 0").description)
    positions = ", ".join(str(i) for i in range(1, n + 1))
    cap = f"LIMIT {SQL_ROW_CAP + 1}"
    if shape.order_end is None:
        return f"SELECT * FROM (\n{body}\n) ORDER BY {positions} {cap}"
    at = shape.order_end
    sql = f"{body[:at]}, {positions}{body[at:]}"
    return sql if shape.limit else f"{sql}\n{cap}"


def _fetch(conn: sqlite3.Connection, body: str, shape: _Shape
           ) -> tuple[list[str], list[list], bool]:
    """Columns, rows and the truncation flag; refuses as soon as the rows pass
    `SQL_MAX_BYTES` of canonical JSON."""
    with closing(conn.execute(_statement(conn, body, shape))) as cur:
        # closed on every path: an unfinished statement would keep the overrides installed
        if cur.description is None:   # not a query (the authorizer stops these first)
            raise sqlite3.ProgrammingError("not a query")
        columns = [d[0] for d in cur.description]
        rows: list[list] = []
        size = 2   # the brackets of the row list
        while (r := cur.fetchone()) is not None:
            if len(rows) == SQL_ROW_CAP:
                return columns, rows, True
            row = _row(r)
            size += len(canonical(row).encode("utf-8")) + (1 if rows else 0)
            if size > SQL_MAX_BYTES:
                raise SqlRefused("rows")
            rows.append(row)
        return columns, rows, False


def run_sql(db: ViewDB, statement: str) -> SqlOutcome:
    """The rows of one read-only statement over the view database, in a total order."""
    if not isinstance(statement, str) or "\x00" in statement:
        raise SqlRefused("syntax")
    try:
        statement.encode("utf-8")
    except UnicodeEncodeError:   # a lone surrogate
        raise SqlRefused("syntax") from None
    body = strip_terminator(statement)
    shape = _shape(body)
    if not shape.one:
        raise SqlRefused("syntax")
    guard = _Guard(frozenset(db.contracts), shape.ctes)
    refusal: SqlRefused | None = None
    with db.exclusive() as conn:
        slot = _slot(db, conn)
        slot.guard = guard
        length = conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, SQL_MAX_VALUE)
        conn.set_authorizer(guard.authorize)
        conn.set_progress_handler(guard.progress, SQL_STEP_EVERY)
        try:
            columns, rows, truncated = _fetch(conn, body, shape)
        except sqlite3.Error as e:
            refusal = guard.refusal(e)
        finally:
            conn.set_progress_handler(None, 0)
            conn.set_authorizer(None)
            conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, length)
            if conn.in_transaction:
                conn.rollback()
            slot.guard = None
            guard.close()
    if refusal is not None:
        raise refusal from None
    return SqlOutcome(columns, rows, truncated)
