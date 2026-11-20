"""The query engine over typed tables (Phase 3 spec §5.4, §8).

`ViewDB` is an in-memory SQLite database of the rows a caller's view admits (derived from the
table overlay, never the record). `compile_query` turns a `query_table` call into one
parameterised SQL statement by code, with the operator semantics of `golden/records.py`, not
SQLite's: case-folding through a registered Python function (SQLite's `lower()` is ASCII-only),
no type coercion, comparisons of mixed or null types never match, `__contains` is a case-folded
substring on text and case-folded element equality on lists, and `list` returns sorted unique
ids. The contract's column type decides compatibility at compile time: a clause that can never
match compiles to `0` and is named in `Compiled.never`. Unknown tables, columns, operators and
ops are `QueryError`s naming them.

Tables are created without declared types, so SQLite applies no affinity: a value keeps the
type it was stored with. Bools are stored as 0 or 1, lists and provenance as canonical JSON text.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adr_eval.models import GoldQuery
from adr_store.tables.contracts import (
    CONTRACT_DIR,
    Column,
    Contract,
    contract_sha256,
    load_contracts,
)
from adr_store.tables.entities import display_names
from adr_store.tables.overlay import Manifest, TablesError, load_rows
from adr_store.tables.provenance import RowRecord, sort_key

OPS = ("count", "list", "lookup", "count_by")
OPERATORS = ("", "in", "gte", "lte", "contains", "ne", "isnull", "contains_any")
QUERY_LIMIT, QUERY_LIMIT_MAX = 100, 1000
DEFAULT_TABLE = {"gov": "fr_documents", "research": "papers"}
_INT64 = 2**63


class QueryError(ValueError):
    """A query names an unknown table, column, operator or op, or has a malformed value."""


def _casefold(x: Any) -> str | None:
    return None if x is None else str(x).casefold()


def _contains_casefold(haystack: Any, needle: Any) -> int | None:
    """1 when the case-folded `haystack` contains `needle`, else 0 (the engine's own function:
    guarded SQL overrides `instr`)."""
    if haystack is None or needle is None:
        return None
    return int(str(needle) in str(haystack).casefold())


def _json(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _stored(col: Column, v: Any) -> Any:
    """The SQLite value of a cell."""
    if v is None:
        return None
    if col.type.endswith("[]"):
        return _json(v)
    return int(v) if isinstance(v, bool) else v


def _python(col: Column, v: Any) -> Any:
    """The Python value of a stored cell."""
    if v is None:
        return None
    if col.type == "bool":
        return bool(v)
    if col.type.endswith("[]"):
        return json.loads(v)
    return v


def contracts_of(manifest: Manifest, tables_id: str, contracts_dir: Path = CONTRACT_DIR
                 ) -> dict[str, Contract]:
    """The contract of every table of a build, by table name in the manifest's order;
    TablesError when one is not the contract the build was made under (edited since)."""
    available = load_contracts(contracts_dir, manifest.corpus)
    contracts: dict[str, Contract] = {}
    for t in manifest.tables:
        c = available.get(t.table)
        if c is None or c.version != t.contract_version \
                or contract_sha256(c) != t.contract_sha256:
            raise TablesError(f"table {t.table}: the contract is not the one the build "
                              f"{tables_id[:12]} was made under")
        contracts[t.table] = c
    return contracts


class ViewDB:
    """The in-memory database of one (tables id, caller view, applicability filters)."""

    def __init__(self, conn: sqlite3.Connection, contracts: dict[str, Contract],
                 tables_id: str):
        self.conn = conn
        self.contracts = contracts
        self.tables_id = tables_id
        self._lock = threading.Lock()

    @classmethod
    def build(cls, store_path: Path, manifest: Manifest, tables_id: str,
              admitted: frozenset[str] | None, *, contracts_dir: Path = CONTRACT_DIR
              ) -> ViewDB:
        """The database of the manifest's tables holding the rows of the `admitted` documents
        (None: every row). Each table's contract must be the one the build was made under."""
        contracts = contracts_of(manifest, tables_id, contracts_dir)
        rows = {t: [r for r in load_rows(store_path, manifest, t)
                    if admitted is None or r.doc_id in admitted] for t in contracts}
        return cls._load(contracts, rows, tables_id)

    @classmethod
    def from_rows(cls, contracts: Mapping[str, Contract],
                  rows: Mapping[str, Sequence[RowRecord]], tables_id: str = "") -> ViewDB:
        """A database of in-memory rows (no overlay): a table with no entry in `rows` is
        empty. The rows are taken as given and not validated against the contracts."""
        return cls._load(dict(contracts), {t: list(r) for t, r in rows.items()}, tables_id)

    @classmethod
    def _load(cls, contracts: dict[str, Contract], rows: dict[str, list[RowRecord]],
              tables_id: str) -> ViewDB:
        if unknown := sorted(set(rows) - set(contracts)):
            raise QueryError(f"unknown table {unknown[0]!r}")
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.create_function("casefold", 1, _casefold, deterministic=True)
        conn.create_function("contains_casefold", 2, _contains_casefold, deterministic=True)
        for name, c in contracts.items():
            _create(conn, c, rows.get(name, []))
        conn.commit()
        conn.execute("PRAGMA query_only = ON")
        return cls(conn, contracts, tables_id)

    def close(self) -> None:
        self.conn.close()

    def __del__(self):  # an abandoned database closes its connection without a warning
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001 - during interpreter shutdown anything may be gone
            pass

    def execute(self, sql: str, params: Sequence = ()) -> list[tuple]:
        """All rows of a statement; one statement at a time per database."""
        with self._lock:
            return self.conn.execute(sql, tuple(params)).fetchall()

    @contextmanager
    def exclusive(self) -> Iterator[sqlite3.Connection]:
        """The connection, held by one caller at a time: guarded SQL (`sqlguard.run_sql`)
        installs its authorizer, step budget and limits on it for the length of one call."""
        with self._lock:
            yield self.conn


def _create(conn: sqlite3.Connection, c: Contract, recs: list[RowRecord]) -> None:
    stored = c.stored_columns
    names = ["_doc_id", *(col.name for col in c.columns), *(f"_prov_{col.name}" for col in stored)]
    conn.execute(f"CREATE TABLE {_q(c.table)} ({', '.join(_q(n) for n in names)})")
    display: dict[str, str] = {}
    if any(col.computed == "display_name" for col in c.columns):
        display = display_names(r.row for r in recs)  # the rows of this view only (ruling P17)
    ordered = sorted(recs, key=lambda r: sort_key(c, r.row))
    sql = (f"INSERT INTO {_q(c.table)} VALUES ({', '.join('?' * len(names))})")
    for rec in ordered:
        cells: list[Any] = [rec.doc_id]
        for col in c.columns:
            if col.computed == "display_name":
                cells.append(display.get(rec.row.get("entity_id")))
            else:
                cells.append(_stored(col, rec.row.get(col.name)))
        for col in stored:
            p = rec.prov.get(col.name)
            cells.append(None if p is None else _json(
                [x.model_dump(mode="json") for x in p] if isinstance(p, list)
                else p.model_dump(mode="json")))
        conn.execute(sql, cells)


# -- compiling ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class Compiled:
    sql: str
    params: tuple
    never: tuple[str, ...]   # the clauses that can never match, each named with its reason


def _kind(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "real"
    if isinstance(v, str):
        return "text"
    if isinstance(v, list):
        return "list"
    return "object"


def _a(word: str) -> str:
    return ("an " if word[0] in "aeiou" else "a ") + word


def _compatible(col: Column, v: Any) -> bool:
    if col.type in ("text", "date"):
        return isinstance(v, str)
    if col.type in ("int", "real"):
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if col.type == "bool":
        return isinstance(v, bool)
    return isinstance(v, list)


def _guard(ref: str, col: Column) -> str:
    """Only a cell of the column's storage class: NULL and stray types never match."""
    if col.type in ("int", "real", "bool"):
        return f"typeof({ref}) IN ('integer', 'real')"
    return f"typeof({ref}) = 'text'"


def _param(v: Any) -> Any:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, list):
        return _json(v)
    return v


def _in_range(v: Any) -> bool:
    return not (isinstance(v, int) and not isinstance(v, bool) and not -_INT64 <= v < _INT64)


def _never(key: str, why: str) -> tuple[str, list, str]:
    return "0", [], f"{key}: {why}"


def _mismatch(key: str, col: Column, v: Any) -> tuple[str, list, str]:
    return _never(key, f"{_a(_kind(v))} value never matches {_a(col.type)} column")


def _contains(ref: str, col: Column, v: Any) -> tuple[str, list] | None:
    needle = str(v).casefold()
    if col.type in ("text", "date"):
        return f"({_guard(ref, col)} AND contains_casefold({ref}, ?))", [needle]
    if col.type.endswith("[]"):
        return (f"({_guard(ref, col)} AND EXISTS (SELECT 1 FROM json_each({ref}) AS je "
                f"WHERE casefold(je.value) = ?))"), [needle]
    return None


def _clause(col: Column, ref: str, op: str, v: Any, key: str
            ) -> tuple[str, list, str | None]:
    """(SQL, parameters, why it never matches or None) of one filter clause."""
    g = _guard(ref, col)
    if op == "isnull":
        if not isinstance(v, bool):
            raise QueryError(f"{key}: isnull takes true or false, got {_a(_kind(v))} value")
        return f"{ref} IS {'' if v else 'NOT '}NULL", [], None
    if op == "in":
        if not isinstance(v, list):
            return _never(key, "a non-list value never matches an in clause")
        ok = [x for x in v if _compatible(col, x) and _in_range(x)]
        if not ok:
            return "0", [], (f"{key}: no element can match {_a(col.type)} column" if v else None)
        return f"({g} AND {ref} IN ({', '.join('?' * len(ok))}))", [_param(x) for x in ok], None
    if op == "contains_any":
        if not isinstance(v, list):
            raise QueryError(f"{key}: contains_any takes a list, got {_a(_kind(v))} value")
        if col.type not in ("text", "date") and not col.type.endswith("[]"):
            return _never(key, f"contains never matches {_a(col.type)} column")
        parts = [_contains(ref, col, x) for x in v]
        if not parts:
            return "0", [], None
        return ("(" + " OR ".join(p[0] for p in parts if p) + ")",
                [x for p in parts if p for x in p[1]], None)
    if op == "contains":
        found = _contains(ref, col, v)
        if found is None:
            return _never(key, f"contains never matches {_a(col.type)} column")
        return found[0], found[1], None
    if op in ("gte", "lte"):
        if col.type.endswith("[]"):
            return _never(key, f"a comparison never matches {_a(col.type)} column")
        if not _compatible(col, v):
            return _mismatch(key, col, v)
        sym = ">=" if op == "gte" else "<="
        if not _in_range(v):  # an integer beyond 64 bits sits above or below every cell
            above = v > 0
            return (g, [], None) if above == (op == "lte") else ("0", [], None)
        return f"({g} AND {ref} {sym} ?)", [_param(v)], None
    if not _compatible(col, v):
        return _mismatch(key, col, v)
    if not _in_range(v):
        return (g, [], None) if op == "ne" else ("0", [], None)
    sym = "!=" if op == "ne" else "="
    return f"({g} AND {ref} {sym} ?)", [_param(v)], None


def _unknown_column(table: str, name: str) -> QueryError:
    return QueryError(f"unknown column {name!r} in table {table}")


def _split(c: Contract, key: str) -> tuple[Column, str]:
    by_name = {col.name: col for col in c.columns}
    if key in by_name:
        return by_name[key], ""
    field, sep, op = key.rpartition("__")
    if not sep or field not in by_name:
        if sep and op in OPERATORS and op:
            raise _unknown_column(c.table, field)
        raise _unknown_column(c.table, key)
    if not op or op not in OPERATORS:
        raise QueryError(f"unknown operator {op!r} in {key!r}")
    return by_name[field], op


def _column(c: Contract, name: str) -> Column:
    for col in c.columns:
        if col.name == name:
            return col
    raise _unknown_column(c.table, name)


def _projection(c: Contract, fields: list[str] | None) -> list[Column]:
    return [_column(c, f) for f in fields] if fields else list(c.columns)


def compile_query(c: Contract, filters: dict, op: str, *, fields: list[str] | None = None,
                  order: list[str] | None = None, limit: int = QUERY_LIMIT) -> Compiled:
    """The one SQL statement of a query over table `c`. `lookup` selects at most `limit` + 1
    rows (the extra row tells `run_query` the result is truncated)."""
    if not isinstance(op, str) or op not in OPS:
        raise QueryError(f"unknown op {op!r}; known: {', '.join(OPS)}")
    if not isinstance(filters, dict):
        raise QueryError("filters must be an object")
    if not all(isinstance(k, str) for k in filters):
        raise QueryError("filter names must be strings")
    for what, names in (("fields", fields), ("order", order)):
        if names is not None and not (isinstance(names, list)
                                      and all(isinstance(n, str) for n in names)):
            raise QueryError(f"{what} must be a list of strings")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= QUERY_LIMIT_MAX:
        raise QueryError(f"limit must be an integer from 1 to {QUERY_LIMIT_MAX}, got {limit!r}")
    table = _q(c.table)
    parts: list[str] = []
    params: list[Any] = []
    never: list[str] = []
    for key, value in filters.items():
        col, fop = _split(c, key)
        sql, p, why = _clause(col, f"{table}.{_q(col.name)}", fop, value, key)
        parts.append(sql)
        params += p
        if why:
            never.append(why)
    where = " WHERE " + " AND ".join(parts) if parts else ""
    projection = _projection(c, fields)  # fields are checked for every op
    if op == "count":
        sql = f"SELECT count(*) FROM {table}{where}"
    elif op == "list":
        ref = f"{table}.{_q(c.list_column)}"
        sql = f"SELECT DISTINCT {ref} FROM {table}{where}"
    elif op == "lookup":
        sel = [f"{table}.\"_doc_id\"", *(f"{table}.{_q(col.name)}" for col in projection)]
        sel += [f"{table}.{_q('_prov_' + col.name)}" for col in projection
                if col.computed is None]
        ordering = []
        for item in order or []:
            desc = item.startswith("-")
            col = _column(c, item[1:] if desc else item)
            ordering.append(f"{table}.{_q(col.name)}{' DESC' if desc else ''}")
        ordering += [f"{table}.{_q(name)}" for name in c.order]
        ordering.append(f"{table}.rowid")
        sql = (f"SELECT {', '.join(sel)} FROM {table}{where} ORDER BY {', '.join(ordering)} "
               f"LIMIT {limit + 1}")
    else:
        if not fields or len(fields) != 1:
            raise QueryError("count_by takes exactly one field")
        col = projection[0]
        ref = f"{table}.{_q(col.name)}"
        if col.type.endswith("[]"):
            sql = (f"SELECT je.value, count(DISTINCT {table}.rowid) FROM {table}, "
                   f"json_each({ref}) AS je{where} GROUP BY je.value ORDER BY je.value")
        else:
            sql = f"SELECT {ref}, count(*) FROM {table}{where} GROUP BY {ref} ORDER BY {ref}"
    return Compiled(sql, tuple(params), tuple(never))


# -- running -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class QueryOutcome:
    count: int | None
    ids: list[str] | None
    rows: list[dict] | None
    groups: list[dict] | None
    value: Any
    truncated: bool
    never_matches: list[str]


def run_query(db: ViewDB, table: str, filters: dict | None, op: str, *,
              fields: list[str] | None = None, order: list[str] | None = None,
              limit: int = QUERY_LIMIT) -> QueryOutcome:
    c = db.contracts.get(table) if isinstance(table, str) else None
    if c is None:
        raise QueryError(f"unknown table {table!r}")
    compiled = compile_query(c, {} if filters is None else filters, op, fields=fields,
                             order=order, limit=limit)
    got = db.execute(compiled.sql, compiled.params)
    never = list(compiled.never)
    if op == "count":
        return QueryOutcome(got[0][0], None, None, None, None, False, never)
    if op == "list":
        col = _column(c, c.list_column)
        ids = sorted({str(_python(col, r[0])) for r in got})
        return QueryOutcome(None, ids, None, None, None, False, never)
    if op == "count_by":
        col = _column(c, fields[0])  # type: ignore[index]
        groups = [{"value": bool(v) if col.type == "bool" and v is not None else v,
                   "count": n} for v, n in got]
        return QueryOutcome(None, None, None, groups, None, False, never)
    projection = _projection(c, fields)
    stored = [col for col in projection if col.computed is None]
    out = []
    for r in got[:limit]:
        row = {col.name: _python(col, r[1 + i]) for i, col in enumerate(projection)}
        base = 1 + len(projection)
        prov = {col.name: json.loads(r[base + i]) for i, col in enumerate(stored)
                if r[base + i] is not None}
        out.append({"doc_id": r[0], "row": row, "prov": prov})
    value = out[0]["row"][fields[0]] if fields and len(got) == 1 else None
    return QueryOutcome(None, None, out, None, value, len(got) > limit, never)


# -- gold queries ------------------------------------------------------------------------------

def from_gold_query(gq: GoldQuery, corpus: str) -> dict:
    """The `query_table` keyword arguments of a v0.1 gold query: the corpus's default table,
    the filters without their `_` options, and `_field` as `fields`."""
    out: dict[str, Any] = {
        "table": DEFAULT_TABLE[corpus],
        "filters": {k: v for k, v in gq.filters.items() if not k.startswith("_")},
        "op": gq.op,
    }
    field = gq.filters.get("_field")
    if isinstance(field, str):
        out["fields"] = [field]
    return out
