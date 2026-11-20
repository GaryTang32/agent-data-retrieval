"""The semantic layer `describe_tables` returns (Phase 3 spec §8, ruling P18), generated from
the contracts. Each response is at most `DESCRIBE_MAX_BYTES` of compact JSON.

- `describe(contracts)`: the index of every table, in name order. For each table its name,
  corpus, description, key and `list_column`; its columns as `name: type` (a `?` after the type
  marks a nullable column); entity links (`column -> <entity table>.entity_id`); and dimensions
  (categorical columns, meaning ones with allowed values or of type bool, and entity columns).
  Then the metrics, `count` (a `query_table` op) and `count_distinct` (an `sql` template;
  `query_table` has no such op), and a note on what `sql` sees.
- `describe(contracts, table=...)`: that table's entry with every column's description, its
  allowed values when a column has at most `ALLOWED_MAX`, the metrics and the `sql` note.

An unknown table is an `UnknownTable` with a fixed message.
"""

from __future__ import annotations

from adr_store.tables.contracts import Column, Contract

DESCRIBE_MAX_BYTES = 8192
ALLOWED_MAX = 25
ERR_UNKNOWN_TABLE = "describe_tables refused: unknown table; describe_tables() lists the tables"
METRICS = [
    {"name": "count", "tool": "query_table",
     "args": {"table": "<table>", "filters": {}, "op": "count"}},
    {"name": "count_distinct", "tool": "sql",
     "sql": "SELECT count(DISTINCT <column>) FROM <table>"},
]
SQL_NOTE = ("One SELECT statement. Every table also has _doc_id (source document) and "
            "_prov_<column> (JSON provenance of the value). type[] columns are JSON arrays: "
            "unnest with json_each, read with json_extract. DISTINCT with its own ORDER BY "
            "refuses rows over about 8 KB; put the DISTINCT in a subquery. group_concat is not a "
            "window function. joins use ON (NATURAL and USING are refused).")
DETAIL_NOTE = 'describe_tables(table="<name>") gives column descriptions and allowed values.'


class UnknownTable(ValueError):
    """`describe_tables` was asked for a table no contract defines."""

    def __init__(self):
        super().__init__(ERR_UNKNOWN_TABLE)


def _column(col: Column) -> str:
    return f"{col.name}: {col.type}{'?' if col.nullable else ''}"


def _summary(c: Contract) -> dict:
    out: dict = {"name": c.table, "corpus": c.source.corpus, "description": c.description,
                 "key": c.key, "list_column": c.list_column}
    if c.entities:
        out["links"] = {col: f"{table}.entity_id" for col, table in c.entities.items()}
    dimensions = [col.name for col in c.columns
                  if col.allowed is not None or col.type == "bool" or col.name in c.entities]
    if dimensions:
        out["dimensions"] = dimensions
    return out


def _detail(c: Contract) -> dict:
    out = {**_summary(c), "columns": {_column(col): col.description for col in c.columns}}
    allowed = {col.name: col.allowed for col in c.columns
               if col.allowed is not None and len(col.allowed) <= ALLOWED_MAX}
    if allowed:
        out["allowed"] = allowed
    return {**out, "metrics": METRICS, "sql": SQL_NOTE}


def describe(contracts: list[Contract], table: str | None = None) -> dict:
    """The index of `contracts`, or with `table` that table's detail."""
    if table is not None:
        for c in contracts:
            if isinstance(table, str) and c.table == table:
                return _detail(c)
        raise UnknownTable()
    tables = [{**_summary(c), "columns": [_column(col) for col in c.columns]}
              for c in sorted(contracts, key=lambda c: c.table)]
    return {"tables": tables, "metrics": METRICS, "sql": SQL_NOTE, "detail": DETAIL_NOTE}
