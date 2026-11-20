"""The merge gate (Phase 3 spec §5.2, §8, criterion T6): the only code that moves
`<store>/tables/HEAD`.

A candidate build and the current build (HEAD) are evaluated on a gold set through the query
engine, on a database of every row under the default applicability filters (the Phase 2 view of
documents in force). A **flip** is a case HEAD answers right and the candidate answers wrong; the
candidate becomes HEAD only when it has at most `max_flips` of them. With no HEAD, or a HEAD the
current contracts can no longer read, every case counts as wrong on HEAD, so a first build
promotes with no flips.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adr_eval.models import load_items
from adr_store import applicability as ap
from adr_store.tables.engine import QueryError, ViewDB, from_gold_query, run_query
from adr_store.tables.overlay import (
    TablesError,
    _set_head,
    load_manifest,
    load_rows,
    read_head,
)

GoldCase = tuple[str, dict, Any]   # (item id, query_table kwargs, expected answer)


def gold_cases(path: Path, corpus: str) -> list[GoldCase]:
    """The v0.1 `count_filter` items of the golden set at `path` that the typed database
    answers, as (id, `query_table` kwargs, expected answer), in file order. Rejected items are
    left out. (The gov-tables set is added with the 3B tables.)"""
    return [(item.id, from_gold_query(item.gold_query, corpus), item.answer.value)
            for item in load_items(path)
            if item.qtype == "count_filter" and item.gold_query.store == "typed_db"
            and item.corpus == corpus and item.status != "rejected"]


def _right(db: ViewDB, kwargs: dict, expected: Any) -> bool:
    try:
        out = run_query(db, **kwargs)
    except QueryError:
        return False
    op = kwargs["op"]
    if op == "count":
        return out.count == int(expected)
    if op == "list":
        return set(out.ids or []) == set(expected or [])
    return out.value == expected


def _default_view(store_path: Path, tables_id: str) -> ViewDB:
    """Every row of the build whose document the default applicability filters admit."""
    m = load_manifest(store_path, tables_id)
    admitted = None
    if m.applicability is not None:
        overlay = ap.load_overlay(store_path, m.snapshot, m.applicability)
        docs = {r.doc_id for t in m.tables for r in load_rows(store_path, m, t.table)}
        admitted, _ = overlay.allowed_docs(docs, ap.Filters())
    return ViewDB.build(store_path, m, tables_id, admitted)


def _right_cases(store_path: Path, tables_id: str, cases: list[GoldCase]) -> set[str]:
    db = _default_view(store_path, tables_id)
    return {cid for cid, kwargs, expected in cases if _right(db, kwargs, expected)}


@dataclass(frozen=True)
class GateResult:
    promoted: bool
    candidate: str
    current: str | None
    flips: list[str]        # right on HEAD, wrong on the candidate (sorted)
    gains: list[str]        # wrong on HEAD, right on the candidate (sorted)
    right_current: int
    right_candidate: int
    n: int


def gate(store_path: Path, candidate: str, cases: list[GoldCase], max_flips: int) -> GateResult:
    """Evaluate `candidate` against HEAD on `cases` and move HEAD to it when it has at most
    `max_flips` flips. A candidate that does not load is a `TablesError`; nothing moves."""
    if max_flips < 0:
        raise ValueError(f"max_flips must not be negative, got {max_flips}")
    ids = [cid for cid, _, _ in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("gold cases must have distinct ids")
    current = read_head(store_path)
    right_new = _right_cases(store_path, candidate, cases)
    right_old: set[str] = set()
    if current is not None:
        try:
            right_old = _right_cases(store_path, current, cases)
        except TablesError:   # a HEAD the current contracts cannot read answers nothing
            right_old = set()
    flips = sorted(right_old - right_new)
    promoted = len(flips) <= max_flips
    if promoted:
        _set_head(store_path, candidate)
    return GateResult(promoted, candidate, current, flips, sorted(right_new - right_old),
                      len(right_old), len(right_new), len(cases))
