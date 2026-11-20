"""The merge gate (Phase 3 spec §5.2, criterion T6): only the gate moves `tables/HEAD`, and it
refuses a candidate that turns too many right answers wrong. Fixture stores under `tmp_path`."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

import adr_store
from adr_eval.models import (
    Answer,
    Checks,
    GoldenItem,
    GoldQuery,
    Provenance,
    write_items,
)
from adr_store.tables import overlay as ov
from adr_store.tables.build import build_tables
from adr_store.tables.contracts import load_contracts
from adr_store.tables.gate import GateResult, gate, gold_cases
from adr_store.tables.overlay import Manifest, TablesError, read_head
from tests.store.tables_fixtures import make_tables_store

FR = "fr_documents"
CASES = [
    ("a", {"table": FR, "filters": {"type": "Rule"}, "op": "count"}, 5),
    ("b", {"table": FR, "filters": {"agency": "Coast Guard"}, "op": "count"}, 3),
    ("c", {"table": FR, "filters": {"year": 2024}, "op": "list"},
     ["2024-00001", "2024-00002", "2024-00003", "2024-00004", "2024-00005", "2024-00006",
      "2024-00007"]),
    ("d", {"table": FR, "filters": {"id": "2024-00004"}, "op": "lookup", "fields": ["year"]},
     2024),
]


@pytest.fixture
def built(tmp_path):
    store = make_tables_store(tmp_path / "s")
    return store.path, build_tables(store.path, "gov").tables_id


def derived(path, tables_id, change) -> str:
    """A second build of the store's fr_documents table: `change(rows)` edits its rows."""
    m = ov.load_manifest(path, tables_id)
    c = load_contracts(corpus="gov")[FR]
    rows = ov.load_rows(path, m, FR)
    change(rows)
    tf = ov.write_table(path, m.snapshot, c, rows, {})
    tables = [tf if t.table == FR else t for t in m.tables]
    new = Manifest(format_version=m.format_version, snapshot=m.snapshot, corpus=m.corpus,
                   applicability=m.applicability, extraction=m.extraction, tables=tables)
    return ov.write_manifest(path, new)[0]


def retype(n):
    """Edit that makes the first `n` Rule rows Proposed Rules (breaks case "a"; "c" is
    unchanged)."""
    def change(rows):
        left = n
        for r in rows:
            if left and r.row["type"] == "Rule":
                r.row["type"] = "Proposed Rule"
                left -= 1
    return change


def drop_coast_guard(rows):
    rows[:] = [r for r in rows if r.row["agency"] != "Coast Guard"]


def test_gate_promotes_a_first_build(built):
    path, cand = built
    assert read_head(path) is None
    r = gate(path, cand, CASES, max_flips=0)
    assert r == GateResult(True, cand, None, [], ["a", "b", "c", "d"], 0, 4, 4)
    assert read_head(path) == cand


def test_gate_refuses_too_many_flips_and_keeps_head(built):   # T6
    path, head = built
    gate(path, head, CASES, max_flips=0)

    def worse(rows):
        retype(1)(rows)
        drop_coast_guard(rows)
    bad = derived(path, head, worse)
    r = gate(path, bad, CASES, max_flips=1)
    assert not r.promoted and read_head(path) == head
    assert r.flips == ["a", "b", "c", "d"] and r.gains == []
    assert (r.current, r.candidate) == (head, bad)
    assert (r.right_current, r.right_candidate, r.n) == (4, 0, 4)


def test_gate_promotes_when_the_flips_are_within_the_limit(built):
    path, head = built
    gate(path, head, CASES, max_flips=0)
    one = derived(path, head, retype(1))
    refused = gate(path, one, CASES, max_flips=0)
    assert not refused.promoted and refused.flips == ["a"] and read_head(path) == head
    r = gate(path, one, CASES, max_flips=1)
    assert r.promoted and r.flips == ["a"] and read_head(path) == one
    assert (r.right_current, r.right_candidate) == (4, 3)


def test_gate_counts_gains_and_wrong_to_wrong_is_no_flip(built):
    path, head = built
    broken = derived(path, head, retype(1))
    gate(path, broken, CASES, max_flips=0)               # HEAD answers "a" wrong
    r = gate(path, head, CASES, max_flips=0)
    assert r.promoted and r.flips == [] and r.gains == ["a"] and read_head(path) == head
    still = gate(path, derived(path, head, retype(2)), CASES, max_flips=0)
    assert still.flips == ["a"] and not still.promoted    # "a" is right on HEAD now


def test_gate_regards_a_query_error_as_wrong(built):
    path, head = built
    cases = [*CASES, ("e", {"table": FR, "filters": {"nope": 1}, "op": "count"}, 0)]
    r = gate(path, head, cases, max_flips=0)
    assert r.promoted and r.gains == ["a", "b", "c", "d"] and r.n == 5


def test_gate_leaves_head_alone_for_a_candidate_that_does_not_load(built):
    path, head = built
    gate(path, head, CASES, max_flips=0)
    with pytest.raises(TablesError, match="no tables manifest"):
        gate(path, "0" * 64, CASES, max_flips=10)
    assert read_head(path) == head


def test_gate_checks_its_arguments(built):
    path, head = built
    with pytest.raises(ValueError, match="max_flips"):
        gate(path, head, CASES, max_flips=-1)
    with pytest.raises(ValueError, match="distinct ids"):
        gate(path, head, [CASES[0], CASES[0]], max_flips=0)
    assert read_head(path) is None


def test_gate_with_the_same_candidate_as_head_has_no_flips(built):
    path, head = built
    gate(path, head, CASES, max_flips=0)
    r = gate(path, head, CASES, max_flips=0)
    assert r.promoted and r.flips == [] and r.gains == [] and r.right_current == 4


def test_head_moves_only_through_the_gate():
    src = Path(adr_store.__file__).parent
    users = {p.relative_to(src).as_posix() for p in src.rglob("*.py")
             if "_set_head" in p.read_text(encoding="utf-8")}
    assert users == {"tables/overlay.py", "tables/gate.py"}


def test_a_head_the_current_contracts_cannot_read_answers_nothing(built, monkeypatch):
    path, head = built
    gate(path, head, CASES, max_flips=0)
    cand = derived(path, head, retype(1))
    import adr_store.tables.gate as g
    real = g._default_view

    def view(store_path, tables_id):
        if tables_id == head:
            raise TablesError("contract drift")
        return real(store_path, tables_id)
    monkeypatch.setattr(g, "_default_view", view)
    r = gate(path, cand, CASES, max_flips=0)
    assert r.promoted and r.right_current == 0 and r.flips == []


# -- gold cases -------------------------------------------------------------------------------

def item(id_, corpus="gov", qtype="count_filter", op="count", store="typed_db",
         status="auto_verified", value=3.0, kind="number", filters=None):
    return GoldenItem(
        id=id_, corpus=corpus, snapshot="0" * 64, qtype=qtype, question="q", as_of=None,
        answer=Answer(kind=kind, value=value), evidence=[],
        gold_query=GoldQuery(store=store, op=op, filters=filters or {"type": "Rule"}),
        rarity=None, split=None,
        provenance=Provenance(model="m", prompt_hash="h", seed=1,
                              created=datetime(2026, 1, 1, tzinfo=UTC)),
        checks=Checks(), status=status)


def test_gold_cases_are_the_typed_count_filter_items_of_the_corpus(tmp_path):
    path = tmp_path / "items.jsonl"
    write_items(path, [
        item("g1"),
        item("g2", op="list", kind="set", value=["x", "y"], filters={"year__gte": 2020}),
        item("g3", qtype="factoid", op="lookup", store="knowledge"),
        item("g4", status="rejected"),
        item("g5", corpus="research", filters={"venue": "arXiv"}),
        item("g6", op="lookup", filters={"id": "z", "_field": "year"}, value=2024.0),
    ])
    assert gold_cases(path, "gov") == [
        ("g1", {"table": FR, "filters": {"type": "Rule"}, "op": "count"}, 3.0),
        ("g2", {"table": FR, "filters": {"year__gte": 2020}, "op": "list"}, ["x", "y"]),
        ("g6", {"table": FR, "filters": {"id": "z"}, "op": "lookup", "fields": ["year"]},
         2024.0),
    ]
    assert [c[0] for c in gold_cases(path, "research")] == ["g5"]


def test_a_float_count_answer_is_compared_as_an_integer(built):
    path, head = built
    cases = [("n", {"table": FR, "filters": {"type": "Rule"}, "op": "count"}, 5.0)]
    assert gate(path, head, cases, max_flips=0).right_candidate == 1
