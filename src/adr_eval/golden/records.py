"""Filter grammar over structured records and `gold_query` execution.

Filter keys (all clauses are ANDed; keys starting with "_" are options, not filters):

- `field`: equal to the value.
- `field__in`: one of the listed values.
- `field__gte` / `field__lte`: greater / less than or equal; a missing or incomparable
  value (e.g. None) never matches.
- `field__contains`: case-insensitive substring for string fields; for list fields,
  case-insensitive membership of an element.
"""

from __future__ import annotations

from typing import Any

from adr_eval.models import GoldQuery

_MISSING = object()


def _matches(value: Any, op: str, target: Any) -> bool:
    if value is _MISSING:
        return False
    if op == "":
        return value == target
    if op == "in":
        return isinstance(target, list) and value in target
    if op in ("gte", "lte"):
        if value is None:
            return False
        try:
            return value >= target if op == "gte" else value <= target
        except TypeError:
            return False
    if op == "contains":
        needle = str(target).casefold()
        if isinstance(value, list):
            return any(str(v).casefold() == needle for v in value)
        return isinstance(value, str) and needle in value.casefold()
    raise ValueError(f"unknown filter operator {op!r}")


def _clause(key: str) -> tuple[str, str]:
    field, sep, op = key.rpartition("__")
    if sep and op in ("in", "gte", "lte", "contains"):
        return field, op
    return key, ""


def filter_records(records: list[dict], filters: dict) -> list[dict]:
    clauses = [(*_clause(k), v) for k, v in filters.items() if not k.startswith("_")]
    return [
        r for r in records
        if all(_matches(r.get(field, _MISSING), op, v) for field, op, v in clauses)
    ]


def exec_gold_query(q: GoldQuery, records: list[dict]) -> int | list[str] | str | None:
    """Run a typed-db gold query: count rows, list sorted unique ids, or look up one field.

    `lookup` returns `filters["_field"]` of the single matching record, or None when no
    record or more than one matches. Other ops are not executable and return None.
    """
    if q.op not in ("count", "list", "lookup"):
        return None
    rows = filter_records(records, q.filters)
    if q.op == "count":
        return len(rows)
    if q.op == "list":
        return sorted({str(r["id"]) for r in rows})
    field = q.filters.get("_field")
    if not isinstance(field, str) or len(rows) != 1:
        return None
    return rows[0].get(field)
