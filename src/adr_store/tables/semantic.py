"""The semantic layer `describe_tables` returns (Phase 3 spec §8), generated from the contracts.

For each table: its name, corpus, description, key and `list_column`; its columns as
`name: type[?]` (a `?` marks a nullable column) with their descriptions; the allowed values of a
column when there are at most `ALLOWED_MAX`; entity links (`column -> <entity table>.entity_id`);
and dimensions (categorical columns, meaning ones with allowed values or of type bool, and
entity columns). A column set shared by several tables (every entity table has the same one) is
given once, by the first of them in name order; the others name it in `columns_as`. Metrics are
`count` (a `query_table` op) and `count_distinct` (an `sql` template; `query_table` has no such
op). The compact JSON form is at most `DESCRIBE_MAX_BYTES` over every committed contract.
"""

from __future__ import annotations

import json

from adr_store.tables.contracts import Column, Contract

DESCRIBE_MAX_BYTES = 8192
ALLOWED_MAX = 25
METRICS = [
    {"name": "count", "tool": "query_table",
     "args": {"table": "<table>", "filters": {}, "op": "count"}},
    {"name": "count_distinct", "tool": "sql",
     "sql": "SELECT count(DISTINCT <column>) FROM <table>"},
]
SQL_NOTE = ("One SELECT statement. Every table also has _doc_id (source document) and "
            "_prov_<column> (JSON provenance of the value). type[] columns are JSON arrays: "
            "unnest with json_each, read with json_extract.")


def _type(col: Column) -> str:
    return col.type + ("?" if col.nullable else "")


def _columns(c: Contract) -> dict[str, str]:
    return {f"{col.name}: {_type(col)}": col.description for col in c.columns}


def describe(contracts: list[Contract]) -> dict:
    """The semantic layer of `contracts`, tables in name order."""
    tables = []
    first_with: dict[str, str] = {}   # a column set (as JSON) -> the first table that has it
    for c in sorted(contracts, key=lambda c: c.table):
        entry: dict = {"name": c.table, "corpus": c.source.corpus,
                       "description": c.description, "key": c.key,
                       "list_column": c.list_column}
        columns = _columns(c)
        shape = json.dumps(columns, ensure_ascii=False)
        if shape in first_with:
            entry["columns_as"] = first_with[shape]
        else:
            first_with[shape] = c.table
            entry["columns"] = columns
        allowed = {col.name: col.allowed for col in c.columns
                   if col.allowed is not None and len(col.allowed) <= ALLOWED_MAX}
        if allowed:
            entry["allowed"] = allowed
        if c.entities:
            entry["links"] = {col: f"{table}.entity_id" for col, table in c.entities.items()}
        dimensions = [col.name for col in c.columns
                      if col.allowed is not None or col.type == "bool" or col.name in c.entities]
        if dimensions:
            entry["dimensions"] = dimensions
        tables.append(entry)
    return {"tables": tables, "metrics": METRICS, "sql": SQL_NOTE}
