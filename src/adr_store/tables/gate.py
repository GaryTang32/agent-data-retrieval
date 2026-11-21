"""The merge gate (Phase 3 spec §5.2, §8, criterion T6): the only code that moves
`<store>/tables/HEAD`.

A candidate build and the current build (HEAD) are evaluated on a gold set through the query
engine, on a database of every row under the default applicability filters (the Phase 2 view of
documents in force). A **flip** is a case HEAD answers right and the candidate answers wrong; the
candidate becomes HEAD only when it has at most `max_flips` of them. With no HEAD every case
counts as wrong on HEAD, so a first build promotes with no flips; a HEAD the current contracts
can no longer read blocks the gate unless the caller overrides it.

Gold sets are v0.1 `count_filter` items and gov-tables v0.1 items (`golden.tables`, the 3B
drawbridge questions), each case a `query_table` call and its expected answer (`gold_cases`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adr_eval.models import GoldenItem, jsonl_lines
from adr_store import applicability as ap
from adr_store.tables.contracts import CONTRACT_DIR
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
    """The cases of the golden set at `path` that the typed database answers, as (id,
    `query_table` kwargs, expected answer), in file order: its v0.1 `count_filter` items of
    `corpus` (rejected items left out), and its gov-tables v0.1 items when `corpus` is gov
    (their query's kwargs; a yes / no lookup expects true / false). A line is a gov-tables item
    when its `corpus` is "gov-tables"."""
    from adr_eval.golden.tables import TablesItem, expected_value

    cases: list[GoldCase] = []
    for line in jsonl_lines(Path(path).read_text(encoding="utf-8")):
        if json.loads(line).get("corpus") == "gov-tables":
            t = TablesItem.model_validate_json(line)
            if corpus == "gov":
                cases.append((t.id, t.query.to_kwargs(), expected_value(t)))
            continue
        item = GoldenItem.model_validate_json(line)
        if item.qtype == "count_filter" and item.gold_query.store == "typed_db" \
                and item.corpus == corpus and item.status != "rejected":
            cases.append((item.id, from_gold_query(item.gold_query, corpus), item.answer.value))
    return cases


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


def _default_view(store_path: Path, tables_id: str, contracts_dir: Path = CONTRACT_DIR
                  ) -> ViewDB:
    """Every row of the build whose document the default applicability filters admit."""
    m = load_manifest(store_path, tables_id)
    admitted = None
    if m.applicability is not None:
        overlay = ap.load_overlay(store_path, m.snapshot, m.applicability)
        docs = {r.doc_id for t in m.tables for r in load_rows(store_path, m, t.table)}
        admitted, _ = overlay.allowed_docs(docs, ap.Filters())
    return ViewDB.build(store_path, m, tables_id, admitted, contracts_dir=contracts_dir)


def _right_cases(store_path: Path, tables_id: str, cases: list[GoldCase],
                 contracts_dir: Path = CONTRACT_DIR) -> set[str]:
    db = _default_view(store_path, tables_id, contracts_dir)
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
    head_unreadable: str | None = None   # why HEAD could not be evaluated (override used)


def gate(store_path: Path, candidate: str, cases: list[GoldCase], max_flips: int, *,
         contracts_dir: Path = CONTRACT_DIR, allow_unreadable_head: bool = False
         ) -> GateResult:
    """Evaluate `candidate` against HEAD on `cases` and move HEAD to it when it has at most
    `max_flips` flips. A candidate that does not load is a `TablesError`; nothing moves.

    A HEAD that exists but cannot be evaluated under the current contracts (a contract edited
    since it was built) leaves the gate with nothing to compare against: it refuses
    (`TablesError`, HEAD unchanged) unless `allow_unreadable_head`, in which case HEAD answers
    no case and `GateResult.head_unreadable` gives the reason."""
    if max_flips < 0:
        raise ValueError(f"max_flips must not be negative, got {max_flips}")
    ids = [cid for cid, _, _ in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("gold cases must have distinct ids")
    current = read_head(store_path)
    right_new = _right_cases(store_path, candidate, cases, contracts_dir)
    right_old: set[str] = set()
    unreadable = None
    if current is not None:
        try:
            right_old = _right_cases(store_path, current, cases, contracts_dir)
        except TablesError as e:
            if not allow_unreadable_head:
                raise TablesError(
                    f"HEAD {current[:12]} cannot be evaluated under the current contracts "
                    f"({e}); HEAD is unchanged. Pass allow_unreadable_head=True to promote "
                    f"the candidate without a comparison") from e
            unreadable = str(e)
    flips = sorted(right_old - right_new)
    promoted = len(flips) <= max_flips
    if promoted:
        _set_head(store_path, candidate)
    return GateResult(promoted, candidate, current, flips, sorted(right_new - right_old),
                      len(right_old), len(right_new), len(cases), unreadable)
