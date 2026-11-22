"""Shared fixtures of the simulation tests (Phase 4 Task 19; preflight C2, C8): `sim_store`,
`env` and `env_gate`.

**The simulation store** (`make_sim_store`) is the units fixture with its Phase 3 tables
(`make_units_store_with_tables`), carried through the whole 4B path with stub replies and no
model call:
1. the rule enrichment of every pool section (`sim_enrich_reply`: the Task 15 replies, plus a
   draw for § 117.1081, the Coast Channel Bridge, which "shall open as required by §§ 117.5 and
   117.31" and "need not open from 6:30 a.m. to 8:30 a.m. Monday through Friday");
2. the gov units built with the rules pass and promoted (first promotion, no cases);
3. the Phase 3 second pass (`sim_ecfr_facts`: the Task 6 facts, with § 117.1081's draw opening
   on signal, so that the reference evaluator reads it as the simple shape);
4. the candidate bindings of `bindings.build.build_candidates` (enrichment read again from the
   cache, compiled, tested with the real tests, the B1 grid on the agreement set) with the Z3
   analysis replaced by `stamp_analysed` (**`StampedAnalysis`**, the documented helper: CI has
   no z3, and `analysis.py` is never imported);
5. the review by a stub (`review_reply`, every binding approved), the signed-off set written
   with its agreement pairs and known draws, and promoted to `bindings/HEAD`;
6. the store's ACL synced again at the real clock (`fresh_acl`), since the environment's read
   tools and the gate check freshness against it.

Its agreement set holds two draws: § 117.821 draw 2 (the railroad bridge, on signal with four
hours notice; Phase 3 draw 2) and § 117.1081 draw 1 (on signal, closed 6:30-8:30 a.m. Monday
through Friday; Phase 3 draw 1). Its unit index is the corpus default (lexical only, C8), so the
environment process never loads an embedding model.

**`env`** is a factory: `env(cls, index=0, arm="no-gate")` builds an `Env` over the task of
class `cls` (the `index`-th of that class) generated from the store; every environment is
closed (its gate stopped) at teardown. **`env_gate`** is one `Env` in arm `gate` over the first
allow task.
"""

from __future__ import annotations

import functools
import json
import types
from pathlib import Path
from unittest import mock

import pytest

from tests.store.gate_fixtures import fresh_acl
from tests.store.units_fixtures import (
    UNITS_ECFR_FACTS,
    enrich_cell,
    enrich_closed_period,
    make_units_store_with_tables,
    review_reply,
    units_ecfr_facts,
    units_enrich_reply,
    units_fixture_numbered,
    units_fixture_reply,
)

__all__ = ["SIM_1081_DRAW", "StampedAnalysis", "env", "env_gate", "make_sim_store",
           "sim_ecfr_facts", "sim_enrich_reply", "sim_store", "sim_tasks"]

# § 117.1081's draw as the enrichment pass would give it (on signal, one closed window)
SIM_1081_DRAW = {
    "bridge": enrich_cell("Coast Channel Bridge", "Coast Channel Bridge"),
    "mile": enrich_cell(2.2, "mile 2.2"),
    "opening_basis": enrich_cell("on_signal", "shall open as required by"),
    "notice_hours": enrich_cell(None),
    "periods": [enrich_closed_period(
        "6:30 a.m.", "8:30 a.m.", "from 6:30 a.m. to 8:30 a.m.",
        except_federal_holidays=enrich_cell(None))]}


def sim_enrich_reply(system: str, user: str, repeat: int) -> str:
    """`units_enrich_reply`, with § 117.1081's draw (`SIM_1081_DRAW`)."""
    reply = json.loads(units_enrich_reply(system, user, repeat))
    if user.split(" ", 2)[1] == "117.1081":
        reply["draws"] = [SIM_1081_DRAW]
    return json.dumps(reply)


def sim_ecfr_facts(section_text: str) -> dict:
    """`units_ecfr_facts`, with § 117.1081's draw opening on signal."""
    facts = units_ecfr_facts(section_text)
    if facts is UNITS_ECFR_FACTS["117.1081"]:
        (d,) = facts["draws"]
        facts = {**facts, "draws": [{**d, "opens_on_signal": (True, "shall open as required by")}]}
    return facts


class StampedAnalysis(types.SimpleNamespace):
    """Stands in for `adr_store.bindings.analysis` in `build_candidates` (CI has no z3): every
    draw is stamped `analysed` by `bindings_fixtures.stamp_analysed` with an empty analysis
    record (no conflict, nothing vacuous) that says it was stamped by the tests."""

    @staticmethod
    def analyse_draw(bindings):
        return None

    @staticmethod
    def mark_analysed(bindings, analysis):
        from tests.store.bindings_fixtures import stamp_analysed

        return stamp_analysed(bindings)


def make_sim_store(path: Path):
    """The simulation store under `path` (module text); returns the `Store`."""
    from adr_eval.cache import Cache
    from adr_eval.llm import CachedStubClient
    from adr_store.bindings import build as bb
    from adr_store.bindings import enrich
    from adr_store.bindings.manifest import draw_sizes, promote_bindings, write_bindings
    from adr_store.bindings.review import review_all
    from adr_store.tables import extract as ex
    from adr_store.tables.contracts import load_contracts
    from adr_store.units import overlay as units_overlay
    from adr_store.units.build import build_units
    from adr_store.units.gate import units_gate

    store = make_units_store_with_tables(
        path, functools.partial(units_fixture_reply, facts_of=sim_ecfr_facts))
    llm = Path(path).parent / f"{Path(path).name}-sim-llm"
    client = CachedStubClient("stub-claude_code_sonnet", Cache(llm / "enrich"), sim_enrich_reply)
    enrich.enrich_all(store, client)
    units_id = build_units(store.path, "gov", passes=("rules",),
                           client=ex.metered_client(0, client=client)).units_id

    def no_case(store_path, units_id, case):    # a first promotion has no cases to hit
        raise AssertionError("no case is evaluated in a first promotion")

    assert units_gate(store.path, units_id, [], 0, hit=no_case).promoted
    numbered = CachedStubClient("stub-numbered", Cache(llm / "numbered"),
                                functools.partial(units_fixture_numbered,
                                                  facts_of=sim_ecfr_facts))
    facts, _ = ex.second_pass_all(store, numbered, load_contracts())
    facts_id, _ = ex.write_facts(store.path, store.snapshot_id, facts)
    with mock.patch.object(bb, "analysis_module", lambda: StampedAnalysis):
        cands = bb.build_candidates(store, ex.metered_client(0, client=client),
                                    units_id=units_id, facts_id=facts_id)
    cards = units_overlay.load_units(store.path, units_overlay.load_units_manifest(
        store.path, units_id), "rule_card")
    review = CachedStubClient("stub-opus", Cache(llm / "review"), review_reply())
    reviewed, _ = review_all(store, cands.bindings, review, cards=cards)
    bindings_id, _ = write_bindings(store.path, store.snapshot_id, units_id, cands.tables_id,
                                    reviewed, facts_id=facts_id,
                                    enrichment_id=cands.enrichment_id,
                                    agreement_pairs=cands.agreement_pairs,
                                    candidate_draws=draw_sizes(cands.bindings),
                                    known_draws=cands.known_draws)
    promote_bindings(store.path, bindings_id)
    fresh_acl(store.path)
    return store


@pytest.fixture(scope="session")
def sim_store(tmp_path_factory):
    """`make_sim_store` once per session (tests only read it; the read tools append to its
    retrieval log)."""
    return make_sim_store(tmp_path_factory.mktemp("sim") / "store")


def sim_tasks(store) -> list:
    """The tasks generated from `store`'s promoted bindings with `SEED4`."""
    from adr_eval.sim.tasks import generate_tasks
    from adr_store.bindings.manifest import read_bindings_head

    return generate_tasks(store.path, read_bindings_head(store.path))


@pytest.fixture
def env(sim_store, tmp_path):
    """A factory of environments (module text)."""
    from adr_eval.sim.env import Env

    made = []
    tasks = sim_tasks(sim_store)

    def make(cls: str, index: int = 0, arm: str = "no-gate", log: str | None = None):
        task = [t for t in tasks if t.class_ == cls][index]
        e = Env(sim_store.path, task, arm, tmp_path / (log or f"env-{len(made)}"))
        made.append(e)
        return e

    try:
        yield make
    finally:
        for e in made:
            e.close()


@pytest.fixture
def env_gate(env):
    """An environment in arm `gate` over the first allow task."""
    return env("allow", 0, "gate")

