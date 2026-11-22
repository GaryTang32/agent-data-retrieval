"""Unit probes (Phase 4 spec §15.4; criteria S1, S2, U1, U2, U3, the applicability probes and
the MCP leg of D1): leak probes of the unit tools against reference stores of each view, unit
equivalence, the fail-closed probes, applicability, `define`, the closure and procedure
censuses and the log scan, on the promoted gov units of `units_fixtures.make_units_built`
(two versions of a 33 CFR 117 excerpt, a 33 CFR 165 excerpt, an IRM chapter; per-document
access: acme-0 sees 117, 165 and bench; acme-1 117 and bench; globex-0 the IRM only; the
outsider nothing; the auditor everything). Nothing reads `data/` or `.cache/`; every unit index
is lexical-only (C8)."""

from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pytest

from adr_eval.cli import main
from adr_eval.probes import units as pu
from adr_eval.probes.acl import CONDITIONS
from adr_store import acl, tools
from adr_store.tools import AccessDenied
from adr_store.units import overlay as units_overlay
from tests.store import units_fixtures as uf
from tests.store.tables_fixtures import T0
from tests.store.units_fixtures import (
    DOC_117_NEW,
    DOC_117_OLD,
    DOC_165,
    DOC_FAQ,
    DOC_IRM,
    DOC_KCS,
    DOC_RUNBOOK,
    make_units_built,
)

REPO = Path(__file__).parents[1]
NOW = T0 + timedelta(minutes=1)
SMALL = dict.fromkeys(pu.LEAK_SIZES["gov"], 3)
units_built = uf.units_built


def config_of(store) -> tuple[Path, Path]:
    d = store.path.parent / f"{store.path.name}-acl"
    return d / "directory.json", d / "policy.json"


def kw(store, clock=lambda: NOW) -> dict:
    directory, policy = config_of(store)
    return {"directory": directory, "policy": policy, "clock": clock}


def rkw(store, clock=lambda: NOW) -> dict:
    """`kw` and the fixture's gov config, which the reference stores derive under."""
    return {**kw(store, clock), "gov_config": uf.UNITS_GOV_CONFIG}


def seen_by(store, caller) -> set[str]:
    snap = acl.read_head(store.path)[1]
    ps = set(snap.directory.get(caller, ()))
    return {d for d, v in snap.docs.items() if ps & set(v)}


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    """One promoted gov units store for the read-only tests of this module."""
    return make_units_built(tmp_path_factory.mktemp("units-probes") / "store")


@pytest.fixture(scope="module")
def refs_root(tmp_path_factory):
    """Reference stores shared by the read-only tests (built once, reused)."""
    return tmp_path_factory.mktemp("units-views") / "views"


# -- the tools probed --------------------------------------------------------------------------


def test_the_probed_tools_are_the_unit_tools_present():
    """C10: `check_rules` joins in Task 18; until then the four read tools are probed."""
    assert pu.UNIT_TOOLS == ("define", "rule_lookup", "procedure_lookup", "unit_search",
                             "check_rules")
    present = pu.present_tools()
    assert set(present) <= set(pu.UNIT_TOOLS)
    assert {"define", "rule_lookup", "procedure_lookup", "unit_search"} <= set(present)
    assert present == tuple(t for t in pu.UNIT_TOOLS if callable(getattr(tools.Tools, t, None)))


# -- leak probes (S1) --------------------------------------------------------------------------


def test_leak_probes_cover_every_family_and_find_no_leak(store, refs_root):
    probes = pu.leak_probes(store.path, "gov", sizes=SMALL)
    assert {p.family for p in probes} == set(pu.LEAK_SIZES["gov"])
    assert Counter(p.family for p in probes) == Counter(SMALL)
    assert probes == pu.leak_probes(store.path, "gov", sizes=SMALL)   # deterministic
    ctx = pu.unit_context(store.path)
    for p in probes:   # every probe targets a unit of a document its caller cannot see
        assert p.target["doc_id"] not in seen_by(store, p.caller)
        assert ctx.units[p.target["unit_id"]].doc_id == p.target["doc_id"]
        assert p.caller in acl.read_head(store.path)[1].directory
        assert set(c["tool"] for c in p.call["calls"]) <= set(pu.present_tools())
    results = pu.run_leaks(probes, store.path, refs_root, **rkw(store))
    assert len(results) == len(probes)
    assert all(r.valid for r in results), [r.note for r in results if not r.valid]
    assert all(not any(r.kinds.values()) for r in results)
    checked = {k for r in results for k, v in r.kinds.items() if v is not None}
    assert checked == set(pu.LEAK_KINDS)
    summary = pu.summarize_leaks(results)
    assert summary["total"]["n"] == 15 and summary["total"]["leaks"] == 0
    assert summary["total"]["compared"] == 15
    # the probes reach every read tool and more than one caller (check_rules discloses a
    # blocking rule's id by design, P5, so it is not a leak probe; its hidden text is checked
    # by the fail-closed probes and the gate's visibility tests)
    assert {c["tool"] for p in probes for c in p.call["calls"]} == set(pu.READ_TOOLS)
    assert len({p.caller for p in probes}) > 1


def test_leak_families_name_the_hidden_unit(store):
    probes = pu.leak_probes(store.path, "gov", sizes=SMALL)
    ctx = pu.unit_context(store.path)
    for p in probes:
        u = ctx.units[p.target["unit_id"]]
        given = json.dumps(p.call["calls"], ensure_ascii=False)
        if p.family == "by-id":
            assert u.type in ("rule_card", "procedure")
            assert u.canonical_ref in given or u.unit_id in given
        elif p.family == "by-term":
            assert u.type == "concept"
            assert all(c["tool"] == "define" for c in p.call["calls"])
        elif p.family == "by-error":
            assert len(p.call["calls"]) == 3
        elif p.family == "by-closure":
            calls = p.call["calls"]
            if p.target["variant"] == "closure":   # the closure target's ref, then the words
                assert u.type == "rule_card" and u.body["closure"]
                rids = {e["ref"] for e in u.body["closure"]} | {
                    u.canonical_ref.split("(")[0]}
                assert [c["tool"] for c in calls] == ["rule_lookup", "rule_lookup"]
                assert calls[0]["args"]["rule_id"] in rids
                assert calls[1]["args"]["query"] == pu.query_of(u)
            else:                                    # the hidden unit as define's context
                assert [c["tool"] for c in calls] == ["define", "define"]
                assert [c["args"]["context"] for c in calls] == [u.unit_id, u.canonical_ref]


def test_a_planted_leak_is_caught(store, refs_root, monkeypatch):
    """The unit tools admitting every document before the ACL (a planted leak) are caught."""
    probes = pu.leak_probes(store.path, "gov", sizes=SMALL)

    def leaky_scope(self, filters, fields):
        applied = self._apply(filters, fields)
        return applied, None, None, frozenset(self.store.doc_ids())

    monkeypatch.setattr(tools.Tools, "_unit_scope", leaky_scope)
    results = pu.run_leaks(probes, store.path, refs_root, **rkw(store))
    found = Counter(k for r in results for k, v in r.kinds.items() if v)
    assert found["id_outside_view"] and found["rows_differ"]
    assert any(r.leak for r in results if r.family == "by-term")
    assert any(r.leak for r in results if r.family == "by-id")
    assert pu.summarize_leaks(results)["total"]["leaks"] > 0


def test_bench_leak_probes(tmp_path):
    bench = make_units_built(tmp_path / "bench", corpus="bench")
    sizes = dict.fromkeys(pu.LEAK_SIZES["bench"], 2)
    probes = pu.leak_probes(bench.path, "bench", sizes=sizes)
    assert Counter(p.family for p in probes) == Counter(sizes)
    results = pu.run_leaks(probes, bench.path, tmp_path / "views", **rkw(bench))
    assert all(r.valid and not r.leak for r in results), [r for r in results if r.leak]


# -- reference stores ----------------------------------------------------------------------------


def test_reference_stores_hold_one_view_and_are_reused(store, refs_root):
    ctx = pu.unit_context(store.path)
    refs = pu.UnitReferences(ctx, refs_root, **rkw(store))
    path = refs.path_for("user:acme-1")
    ref = pu.unit_context(path)
    assert set(ref.store.doc_ids()) == seen_by(store, "user:acme-1") == {
        DOC_117_OLD, DOC_117_NEW, DOC_RUNBOOK, DOC_FAQ, DOC_KCS}
    # the reference's units of the view equal the store's
    mine = {u.unit_id: u for u in ctx.units.values() if u.doc_id in seen_by(store, "user:acme-1")}
    assert {i: u for i, u in ref.units.items()} == mine
    info = next(i for i in refs.info if i["caller"] == "user:acme-1")
    assert info["units_equal"] == info["units_of_view"] == len(mine)
    again = pu.UnitReferences(ctx, refs_root, **rkw(store))
    assert again.path_for("user:acme-1") == path
    assert again.how[path.name] == "reused"
    assert refs.path_for("user:no-such-user") is None


def test_a_reference_of_another_units_build_config_is_refused(tmp_path):
    """The store's units were built with a model pass the reference cannot reproduce from
    code: the reference is refused, not compared."""
    s = make_units_built(tmp_path / "s")
    head = units_overlay.read_units_head(s.path)
    m = units_overlay.load_units_manifest(s.path, head)
    passed = m.model_copy(update={"passes": {"procedure": {"prompt": "x"}}})
    units_id, _ = units_overlay.write_units_manifest(s.path, passed)
    units_overlay._set_units_head(s.path, units_id)
    refs = pu.UnitReferences(pu.unit_context(s.path), tmp_path / "views", **rkw(s))
    with pytest.raises(ValueError, match="passes"):
        refs.path_for("user:acme-1")


def test_reference_tables_come_from_the_cache_with_zero_calls(tmp_path, monkeypatch):
    """A store whose units hold Phase 3 table records: the reference builds its tables, the
    33 CFR 117 extraction included, from the cached replies with a budget of zero calls; an
    empty cache stops the build (no call is made)."""
    from adr_eval import runner
    from adr_eval.cache import Cache
    from adr_eval.llm import CachedStubClient
    from adr_eval.pipeline import BudgetExceeded

    s = uf.make_units_store_with_tables(tmp_path / "t")
    uf.promote_units(s.path)
    calls: list[str] = []

    def no_call(system, user, repeat):
        calls.append(user)
        raise AssertionError("a reference build made a model call")

    cache = {"dir": tmp_path / "t-llm"}

    def make_client(name, profiles, c, max_retries=5):
        return CachedStubClient("stub-sonnet", Cache(cache["dir"]), no_call)

    monkeypatch.setattr(runner, "make_client", make_client)
    ctx = pu.unit_context(s.path)
    assert ctx.manifest.tables_id is not None
    refs = pu.UnitReferences(ctx, tmp_path / "views", generator="gen", **rkw(s))
    path = refs.path_for("user:acme-1")
    assert not calls
    ref = pu.unit_context(path)
    assert ref.manifest.tables_id is not None
    assert {u.unit_id for u in ref.units.values()} == {
        u.unit_id for u in ctx.units.values()}   # acme sees every document of this store
    # a view without one Federal Register document: its reference's tables build (and so the
    # tables id its table records name) differs from the store's, and nothing else does
    from tests.store.test_tables_tools import fr

    directory, policy = config_of(s)
    rules = [fr(1, ["group:acme/0"]), *uf.UNITS_RULES]
    data = json.loads(policy.read_text(encoding="utf-8"))
    policy.write_text(json.dumps({**data, "rules": rules}), encoding="utf-8")
    acl.sync(s.path, directory, policy, clock=lambda: T0)
    ctx = pu.unit_context(s.path)
    refs3 = pu.UnitReferences(ctx, tmp_path / "views3", generator="gen", **rkw(s))
    sub = pu.unit_context(refs3.path_for("user:acme-1"))
    assert sub.manifest.tables_id != ctx.manifest.tables_id and not calls
    info = next(i for i in refs3.info if i["caller"] == "user:acme-1")
    assert 0 < info["units_equal"] == info["units_of_view"] < len(ctx.units)
    assert any(u.type == "table_record" and u != ctx.units[u.unit_id]
               for u in sub.units.values())
    probes = [p for p in pu.leak_probes(s.path, "gov", sizes=SMALL) if p.caller == "user:acme-1"]
    calls_ = [{"tool": "unit_search", "args": {"query": "Federal Register", "limit": 50}}]
    mine = tools.Tools(s.path, acl=True, caller="user:acme-1", clock=lambda: NOW)
    ref = tools.Tools(refs3.path_for("user:acme-1"), acl=True, caller="user:acme-1",
                      clock=lambda: NOW)
    a, b = (pu.run_unit_call(t, calls_[0]) for t in (mine, ref))
    assert any(h["pointer"] for h in a[1].hits)        # table records, naming each tables id
    assert pu.outcome_key(a) == pu.outcome_key(b)
    assert all(r.valid and not r.leak for r in pu.run_leaks(probes, s.path, None, refs=refs3))
    cache["dir"] = tmp_path / "empty-llm"
    refs2 = pu.UnitReferences(ctx, tmp_path / "views2", generator="gen", **rkw(s))
    with pytest.raises(BudgetExceeded):
        refs2.path_for("user:acme-1")
    assert not calls


# -- equivalence (S1) ----------------------------------------------------------------------------


def test_equivalence_on_fixture_views(store, refs_root):
    rows = pu.equivalence(store.path, "gov", refs_root, n_calls=12, **rkw(store))
    views = pu.UnitReferences(pu.unit_context(store.path), refs_root, **rkw(store)).views
    assert len({r["view"] for r in rows}) == len(views) >= 4
    assert len(rows) == 12 * len(views)
    assert all(r["identical"] for r in rows), [r for r in rows if not r["identical"]]
    assert {r["tool"] for r in rows} == set(pu.present_tools()) - {"check_rules"}
    assert any(r["outcome"] == "ok" for r in rows) and any(r["outcome"] != "ok" for r in rows)
    summary = pu.summarize_equivalence(rows)
    assert summary["n"] == summary["identical"] == len(rows) and summary["differing"] == 0
    assert rows == pu.equivalence(store.path, "gov", refs_root, n_calls=12, **rkw(store))


def test_equivalence_detects_a_view_that_counts_hidden_units(store, refs_root, monkeypatch):
    def leaky_scope(self, filters, fields):
        applied = self._apply(filters, fields)
        return applied, None, None, frozenset(self.store.doc_ids())

    monkeypatch.setattr(tools.Tools, "_unit_scope", leaky_scope)
    rows = pu.equivalence(store.path, "gov", refs_root, n_calls=12, **rkw(store))
    assert any(not r["identical"] for r in rows)
    assert all(r["identical"] for r in rows if r["caller"] == "user:auditor")


# -- fail closed (S2) ----------------------------------------------------------------------------


def test_failclosed_six_conditions_by_tools_by_five_callers(store, tmp_path):
    present = pu.present_tools()
    logs: dict = {}
    rows = pu.failclosed(store.path, tmp_path / "c", "gov", logs=logs, **kw(store))
    assert len(rows) == 6 * len(present) * 5 == 150    # C10: 6 × 5 tools × 5 callers
    assert all(r["pass"] for r in rows), [r for r in rows if not r["pass"]]
    assert Counter(r["family"] for r in rows) == dict.fromkeys(CONDITIONS, len(present) * 5)
    assert Counter(r["tool"] for r in rows) == dict.fromkeys(present, 30)
    assert not any(r["content"] for r in rows)
    entry = [r for r in rows if r["family"] == "no_entry"]
    assert any(r["visible_before"] for r in entry)   # the targets were visible before
    assert all(r["outcome"] in ("ok", "refused") for r in entry)
    assert all(r["not_found_equal"] for r in entry if r["tool"] in ("rule_lookup",
                                                                    "procedure_lookup"))
    assert not any((tmp_path / "c").glob("*/HEAD"))   # clones removed
    by_tool = pu.summarize_failclosed(rows)["by_tool"]
    assert all(b["no_entry"] == 5 for b in by_tool.values())
    assert {t: b["no_entry_visible_before"] for t, b in by_tool.items()} == {
        t: sum(bool(r["visible_before"]) for r in entry if r["tool"] == t) for t in present}
    total = pu.total_unit_scan(logs)
    assert total["complete"] and total["lines"] >= len(rows)
    assert rows == pu.failclosed(store.path, tmp_path / "c", "gov", **kw(store))


def test_failclosed_tools_can_be_named(store, tmp_path):
    rows = pu.failclosed(store.path, tmp_path / "c", "gov", tools=("define",), **kw(store))
    assert len(rows) == 6 * 5 and {r["tool"] for r in rows} == {"define"}
    with pytest.raises(ValueError, match="no_such_tool"):
        pu.failclosed(store.path, tmp_path / "c", "gov", tools=("no_such_tool",), **kw(store))


def test_a_unit_tool_that_fails_open_is_caught(store, tmp_path, monkeypatch):
    real = tools.Tools.define

    def define(self, *a, **k):   # answers as an unrestricted caller when access is denied
        try:
            return real(self, *a, **k)
        except AccessDenied:
            return real(tools.Tools(self.store_path), *a, **k)

    monkeypatch.setattr(tools.Tools, "define", define)
    rows = pu.failclosed(store.path, tmp_path / "c", "gov", **kw(store))
    bad = [r for r in rows if not r["pass"]]
    assert bad and {r["tool"] for r in bad} == {"define"}
    assert any(r["content"] for r in bad if r["family"] == "F4")


def test_failclosed_check_rules_target_with_bindings(tmp_path, monkeypatch):
    """With promoted bindings the check_rules target is a card whose text decides a call:
    those who see its document get it before the change, and no fail-closed probe shows it."""
    s = uf.make_units_built_with_bindings(tmp_path / "b")
    rows = pu.failclosed(s.path, tmp_path / "c", "gov", tools=("check_rules",), **kw(s))
    assert len(rows) == 6 * 5 and all(r["pass"] for r in rows), [r for r in rows
                                                                 if not r["pass"]]
    entry = [r for r in rows if r["family"] == "no_entry"]
    assert any(r["visible_before"] for r in entry) and all(r["outcome"] == "ok" for r in entry)
    assert not any(r["content"] for r in rows)
    # a check_rules that answers as an unrestricted caller when access is denied is caught
    real = tools.Tools.check_rules

    def leaky(self, *a, **k):
        try:
            return real(self, *a, **k)
        except AccessDenied:
            return real(tools.Tools(self.store_path), *a, **k)

    monkeypatch.setattr(tools.Tools, "check_rules", leaky)
    bad = [r for r in pu.failclosed(s.path, tmp_path / "c", "gov", tools=("check_rules",),
                                    **kw(s)) if not r["pass"]]
    assert bad and any(r["content"] for r in bad)


# -- applicability -----------------------------------------------------------------------------


def test_applicability_probes_pass(store):
    rows = pu.applicability_probes(store.path, n=8, **{"clock": lambda: NOW})
    read = [t for t in pu.present_tools() if t != "check_rules"]
    assert len(rows) == 9 * 5   # per date: rule_lookup by id and by query, and the other three
    assert {r["tool"] for r in rows} == set(read)
    assert all(r["pass"] for r in rows), [r for r in rows if not r["pass"]]
    assert all(r["versions"] <= 1 and r["outside"] == 0 for r in rows)
    by_id = [r for r in rows if r["tool"] == "rule_lookup" and r["probe_id"].startswith("id")]
    # the default and the dates of the newest version return it; the older dates the old one
    assert {r["doc"] for r in by_id if r["as_of"] is None} == {DOC_117_NEW[:12]}
    assert {DOC_117_OLD[:12], DOC_117_NEW[:12]} <= {r["doc"] for r in by_id}
    summary = pu.summarize_applicability(rows)
    assert summary["total"]["passed"] == summary["total"]["n"] == len(rows)


def test_applicability_probes_catch_a_superseded_version(store, monkeypatch):
    real = tools.Tools._unit_scope

    def wide(self, filters, fields):   # ignores as_of and the default exclusion
        return real(self, {"include_superseded": True}, fields)

    monkeypatch.setattr(tools.Tools, "_unit_scope", wide)
    rows = pu.applicability_probes(store.path, n=8, clock=lambda: NOW)
    assert any(r["versions"] > 1 or r["outside"] for r in rows)
    assert not all(r["pass"] for r in rows)


# -- define (U1) -------------------------------------------------------------------------------


def test_define_probes_cover_labels_hidden_labels_absent_and_context(store):
    rows = pu.define_probes(store.path, n_absent=10, clock=lambda: NOW)
    kinds = Counter(r["kind"] for r in rows)
    assert {"label", "hidden", "absent", "context", "no_context", "unit_context"} <= set(kinds)
    unit_rows = [r for r in rows if r["kind"] == "unit_context"]
    assert {r["context_type"] for r in unit_rows} >= {"concept", "rule_card"}
    assert all(r["context_visible"] and r["senses"] for r in unit_rows)
    assert kinds["absent"] == 10
    ctx = pu.unit_context(store.path)
    terms = {t for c in ctx.by_type["concept"]
             for t in [c.body["pref_label"], *c.body["alt_labels"], *c.body["hidden_labels"]]}
    assert {r["term"] for r in rows if r["kind"] in ("label", "alt", "hidden")} == terms
    assert all(r["correct"] for r in rows), [r for r in rows if not r["correct"]]
    assert sum(r["hidden_senses"] for r in rows) == 0
    assert any(not r["own_visible"] for r in rows if r["kind"] == "label")   # hidden owners
    assert any(r["senses"] for r in rows if r["kind"] == "context")
    summary = pu.summarize_define(rows)
    assert summary["total"]["correct"] == summary["total"]["n"] == len(rows)
    assert summary["total"]["hidden_senses"] == 0
    assert rows == pu.define_probes(store.path, n_absent=10, clock=lambda: NOW)


def test_the_unit_context_oracle_reads_section_7_on_its_own(store):
    """`place_of` and `holds`: the part-165 sense holds its own unit and every 165 card; the
    § 165.T01 sense holds its own unit and the cards under it only; the IRM chapter sense
    holds every unit of its document."""
    ctx = pu.unit_context(store.path)
    by_ref = {u.body["scope"]["ref"]: u for u in ctx.by_type["concept"]
              if u.body["pref_label"].lower() == "designated representative"}
    part, section = by_ref["33 CFR part 165"], by_ref["33 CFR 165.T01"]
    assert pu.holds(part, pu.place_of(part)) and not pu.holds(section, pu.place_of(part))
    assert pu.holds(section, pu.place_of(section)) and pu.holds(part, pu.place_of(section))
    cards = [u for u in ctx.by_type["rule_card"] if u.doc_id == DOC_165]
    assert cards and all(pu.holds(part, pu.place_of(c)) for c in cards)
    assert {pu.holds(section, pu.place_of(c)) for c in cards} == {True, False}
    assert all(pu.holds(section, pu.place_of(c)) == c.canonical_ref.startswith(
        "33 CFR 165.T01(") for c in cards)
    irm = next(u for u in ctx.by_type["concept"] if u.doc_id == DOC_IRM)
    assert all(pu.holds(irm, pu.place_of(u)) for u in ctx.units.values()
               if u.doc_id == DOC_IRM)
    assert not any(pu.holds(irm, pu.place_of(u)) for u in cards)
    # the drawbridge 117 senses (part scope) do not hold a 165 place
    drawbridge = next(u for u in ctx.by_type["concept"] if u.body["pref_label"] == "Drawbridge")
    assert not pu.holds(drawbridge, pu.place_of(section))


def test_the_u1_oracle_reads_ref_contexts_on_its_own(store, monkeypatch):
    """Task 12 carry C: a ref-string context is judged by the oracle's own `place_of_ref` and
    `holds_ref` (no `scope_contains`, `_KIND_RANK` or `tools_units` helper), and a hidden
    unit-id context by the ref inside the id, as the tool reads it."""
    from adr_store.units import concepts

    ctx = pu.unit_context(store.path)
    by_ref = {u.body["scope"]["ref"]: u for u in ctx.by_type["concept"]
              if u.body["pref_label"].lower() == "designated representative"}
    part, section = by_ref["33 CFR part 165"], by_ref["33 CFR 165.T01"]
    every = frozenset(ctx.units[u].doc_id for u in ctx.units)
    for ref, holds_part, holds_section in (("33 CFR part 165", True, False),
                                           ("33 CFR 165.T01", True, True),
                                           ("33 CFR 165.T01(b)", True, True),
                                           ("33 CFR 165.13(b)", True, False),
                                           ("33 CFR part 117", False, False),
                                           ("IRM 21.4.1.3", False, False)):
        place = pu.place_of_ref(ctx, ref, every)
        assert pu.holds_ref(part, ref, place) is holds_part, ref
        assert pu.holds_ref(section, ref, place) is holds_section, ref
    irm = next(u for u in ctx.by_type["concept"] if u.doc_id == DOC_IRM)
    chapter = irm.body["scope"]["ref"]
    assert pu.holds_ref(irm, chapter, pu.place_of_ref(ctx, chapter, every))
    deeper = chapter + ".9"
    assert pu.holds_ref(irm, deeper, pu.place_of_ref(ctx, deeper, every))
    assert not pu.holds_ref(irm, chapter + "9", pu.place_of_ref(ctx, chapter + "9", every))
    # the subpart of a section ref comes from a visible card of that section
    sub_place = pu.place_of_ref(ctx, "33 CFR 117.821", every)
    assert sub_place.subpart == "B" and sub_place.section == "117.821"
    assert pu.place_of_ref(ctx, "33 CFR 117.821", frozenset()).subpart is None
    # the ref inside a unit id, read without the tool's pattern
    card = next(u for u in ctx.by_type["rule_card"] if u.doc_id == DOC_165)
    assert pu.ref_of_unit_id(card.unit_id) == card.canonical_ref
    assert pu.ref_of_unit_id("33 CFR 165.13") is None
    assert pu.ref_of_unit_id(f"rule_card/{card.canonical_ref}/xyz/{DOC_165[:16]}") is None
    # a hidden unit-id context ranks as its ref does, not as the whole id string
    term = "designated representative"
    hidden_ctx = f"rule_card/33 CFR 165.T01(c)/{'0' * 12}/{'f' * 16}"       # absent unit
    assert pu._expected_ids(ctx, term, hidden_ctx, every) == \
        pu._expected_ids(ctx, term, "33 CFR 165.T01(c)", every)
    assert pu._expected_ids(ctx, term, hidden_ctx, every)[0] == section.unit_id
    # independence: the oracle never calls the tool's helpers
    def boom(*a, **kw):
        raise AssertionError("the U1 oracle used a tool helper")

    for target, name in ((pu, "scope_contains"), (concepts, "scope_contains"),
                         (pu.tu, "section_of"), (pu.tu, "subpart"), (pu.tu, "context_ref")):
        if hasattr(target, name):
            monkeypatch.setattr(target, name, boom)
    for context in ("33 CFR part 165", "33 CFR 165.T01(b)", "33 CFR 117.821", chapter,
                    hidden_ctx, None):
        pu._expected_ids(ctx, term, context, every)


def test_the_u1_oracle_normalises_ref_contexts_on_its_own(store):
    """Fix round M2: a rule id written another way ("§ 117.821", "117.821(b)", "33 C.F.R.
    117.821 (b)") is read as its canonical ref by the oracle's own normaliser, as the tool
    reads it, so oracle and tool agree."""
    ctx = pu.unit_context(store.path)
    assert pu.oracle_rule_id("§ 117.821") == "33 CFR 117.821"
    assert pu.oracle_rule_id("117.821(b)") == "33 CFR 117.821(b)"
    assert pu.oracle_rule_id("33 C.F.R. § 117.821 (b)") == "33 CFR 117.821(b)"
    assert pu.oracle_rule_id("47 CFR 73.3526(e)(2)") == "47 CFR 73.3526(e)(2)"
    assert pu.oracle_rule_id("§§ 165.T01") == "33 CFR 165.T01"
    for other in ("IRM 21.4.1.3", "33 CFR part 165", "999.1", "drawbridge"):
        assert pu.oracle_rule_id(other) is None
    every = frozenset(u.doc_id for u in ctx.units.values())
    t = tools.Tools(store.path, acl=True, caller="user:auditor", clock=lambda: NOW)
    term = "designated representative"
    for written, canonical in (("§ 165.T01(c)", "33 CFR 165.T01(c)"),
                               ("165.T01", "33 CFR 165.T01"),
                               ("33 C.F.R. 165.13 (b)", "33 CFR 165.13(b)")):
        want = pu._expected_ids(ctx, term, canonical, every)
        assert pu._expected_ids(ctx, term, written, every) == want
        got = [x.unit_id for x in t.define(term, context=written,
                                            include_superseded=True).senses]
        assert got == want, written


def test_equivalence_contexts_include_visible_unit_ids(store):
    """Task 12 carry C (ii): `define` calls of the equivalence set take a visible unit id as
    context too."""
    import adr_eval.probes.equivalence as eq

    ctx = pu.unit_context(store.path)
    seen = frozenset(ctx.visible("user:acme-1"))
    view = eq.View("v", "user:acme-1", ("user:acme-1",), seen)
    calls = pu.equivalence_calls(ctx, view, n_calls=300)
    contexts = [c["args"].get("context") for c in calls.values() if c["tool"] == "define"]
    unit_ids = [c for c in contexts if c in ctx.units]
    assert unit_ids and all(ctx.units[c].doc_id in seen for c in unit_ids)
    assert any(c is None for c in contexts) and any(c and c not in ctx.units for c in contexts)


def test_define_probes_catch_a_unit_context_read_as_its_ref(store, monkeypatch):
    """The Task 8 reading before fix round 1 (a unit id stands for its canonical ref only) is
    caught by the unit-id context probes."""
    from adr_store.units.concepts import _UNIT_ID

    real = tools.Tools._sense_context

    def as_ref(self, context, us, allowed):
        if context is not None and (m := _UNIT_ID.match(context.strip())):
            return real(self, m.group(1), us, allowed)
        return real(self, context, us, allowed)

    monkeypatch.setattr(tools.Tools, "_sense_context", as_ref)
    rows = pu.define_probes(store.path, n_absent=5, clock=lambda: NOW)
    bad = [r for r in rows if not r["correct"]]
    assert bad and {r["kind"] for r in bad} == {"unit_context"}


def test_define_probes_catch_a_hidden_sense(store, monkeypatch):
    def leaky_scope(self, filters, fields):
        applied = self._apply(filters, fields)
        return applied, None, None, frozenset(self.store.doc_ids())

    monkeypatch.setattr(tools.Tools, "_unit_scope", leaky_scope)
    rows = pu.define_probes(store.path, n_absent=5, clock=lambda: NOW)
    assert sum(r["hidden_senses"] for r in rows) > 0
    assert not all(r["correct"] for r in rows)


# -- censuses (U2, U3) ---------------------------------------------------------------------------


def test_closure_and_procedure_census(store):
    from adr_store.units.build import unit_reports

    c = pu.closure_census(store.path)
    report = unit_reports(store.path, units_overlay.read_units_head(store.path))["rule_card"]
    assert c["all"]["in_part"] == report["in_part"]
    assert c["all"]["in_part_resolved"] == report["in_part_resolved"]
    assert c["matches_build_report"] is True
    assert c["all"]["reasons"] == report["reasons"]
    # every unresolved reference is listed with its reason; the absent § 117.999 is one
    assert len(c["all"]["unresolved"]) == c["all"]["in_part"] - c["all"]["in_part_resolved"]
    assert any(u["reason"] == "section_missing" and "117.999" in u["target_ref"]
               for u in c["all"]["unresolved"])
    assert all(u["reason"] for u in c["all"]["unresolved"])
    newest = c["newest"]
    assert newest["cards"] < c["all"]["cards"] and newest["documents"] == 2   # 117 new, 165
    assert c["threshold"] == 0.99 and c["pass"] == (
        min(c["all"]["resolved_rate"], newest["resolved_rate"]) >= 0.99)
    p = pu.procedure_census(store.path)
    assert p["n"] == 2 and p["passed"] == 2 and p["names_unique"]
    assert all(r["pass"] and r["valid_ir"] and r["mermaid_round_trip"]
               and r["skill_round_trip"] for r in p["procedures"])
    assert all(r["description_chars"] <= 1024 and r["body_lines"] < 500 for r in p["procedures"])


def test_procedure_census_catches_a_broken_renderer(store, monkeypatch):
    from adr_eval.probes import units as mod

    monkeypatch.setattr(mod, "render_mermaid", lambda body: "flowchart TD\n")
    p = pu.procedure_census(store.path)
    assert p["passed"] == 0 and not any(r["mermaid_round_trip"] for r in p["procedures"])


# -- the log scan (S2) ---------------------------------------------------------------------------


def _line(**k) -> str:
    base = {"caller": "user:a", "principals": ["public"], "acl_snapshot": "s",
            "acl_decision": "allowed", "view": "v", "tool": "define", "args": {},
            "units": "u" * 64, "error": None}
    return json.dumps({**base, **k}) + "\n"


def test_scan_unit_log_requires_units_on_allowed_lines(tmp_path):
    log = tmp_path / "retrieval.jsonl"
    log.write_text(_line() + _line(tool="search", units=None)
                   + _line(acl_decision="denied:F4", principals=None, view=None, units=None)
                   + _line(units=None, error="give a query or a rule_id, not both")
                   + _line(tool="rule_lookup", error=tools.UNKNOWN_RULE), encoding="utf-8")
    s = pu.scan_unit_log(log)
    assert s["lines"] == 5 and s["unit_lines"] == 4 and s["complete"]
    assert s["units_missing"] == 0 and s["allowed_unresolved"] == 0
    # an allowed unit-tool line that answered without naming its units is incomplete
    with log.open("a", encoding="utf-8") as f:
        f.write(_line(tool="unit_search", units=None))
    assert not pu.scan_unit_log(log)["complete"]
    assert pu.scan_unit_log(log)["allowed_unresolved"] == 1
    # so is a unit-tool line without the key, one without the Phase 2 fields, a refusal after
    # the units were read with no units id, and an allowed line with no principals
    for bad in ({"units": None, "error": tools.UNKNOWN_PROCEDURE, "tool": "procedure_lookup"},
                {"principals": None}):
        log.write_text(_line(**bad), encoding="utf-8")
        assert not pu.scan_unit_log(log)["complete"], bad
    rec = json.loads(_line())
    del rec["units"]
    log.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    assert pu.scan_unit_log(log)["units_missing"] == 1
    rec = json.loads(_line())
    del rec["acl_snapshot"]
    log.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    assert pu.scan_unit_log(log)["missing"]["acl_snapshot"] == 1
    # an offset skips earlier lines; the call count must match the unit-tool lines
    log.write_text(_line() + _line(), encoding="utf-8")
    first = len(_line().encode())
    assert pu.scan_unit_log(log, first)["lines"] == 1
    assert pu.scan_unit_log(log, calls=2)["complete"]
    assert not pu.scan_unit_log(log, calls=3)["complete"]
    assert not pu.scan_unit_log(tmp_path / "missing.jsonl", calls=1)["complete"]


def test_only_the_pointer_tables_id_is_set_aside():
    """M1: the comparison excuses the tables id of a hit's table-record pointer, nothing
    else named `tables_id`."""
    a = {"hits": [{"pointer": {"table": "t", "tables_id": "a" * 64}}], "tables_id": "a" * 64}
    b = {"hits": [{"pointer": {"table": "t", "tables_id": "b" * 64}}], "tables_id": "a" * 64}
    assert pu._canonical(a) == pu._canonical(b)
    assert pu._canonical({**a, "tables_id": "c" * 64}) != pu._canonical(a)
    c = {"hits": [{"pointer": {"table": "u", "tables_id": "b" * 64}}], "tables_id": "a" * 64}
    assert pu._canonical(c) != pu._canonical(a)   # the rest of the pointer is compared
    d = {"cards": [{"tables_id": "a" * 64}]}
    assert pu._canonical(d) != pu._canonical({"cards": [{"tables_id": "b" * 64}]})


def test_the_log_scan_finds_statement_text(tmp_path):
    """No SQL text in any log line (B5-style, as Phase 3): a `sql` line logs only the
    statement's hash, and no line holds a statement given."""
    log = tmp_path / "retrieval.jsonl"
    stmt = "SELECT count(*) FROM fr_documents WHERE id = 'x'"
    log.write_text(_line(tool="sql", units=None, args={"statement_sha256": "h"},
                         sql_sha256="h"), encoding="utf-8")
    assert pu.scan_unit_log(log, statements=[stmt])["complete"]
    log.write_text(_line(tool="sql", units=None, args={"statement": stmt}), encoding="utf-8")
    s = pu.scan_unit_log(log, statements=[stmt])
    assert s["text_lines"] == 1 and not s["complete"]


def test_unit_calls_are_counted_per_log(store):
    t = tools.Tools(store.path, acl=True, caller="user:auditor", clock=lambda: NOW)
    before = pu.unit_calls(t.log_path)
    out = pu.run_unit_call(t, {"tool": "define", "args": {"term": "Drawtender"}})
    assert out[0] == "ok" and pu.unit_calls(t.log_path) == before + 1
    out = pu.run_unit_call(t, {"tool": "rule_lookup", "args": {"rule_id": "33 CFR 117.9999"}})
    assert out == ("refused", tools.UNKNOWN_RULE)
    with pytest.raises(ValueError):
        pu.run_unit_call(t, {"tool": "search", "args": {"query": "x"}})


# -- the MCP leg (D1) ----------------------------------------------------------------------------


def test_the_mcp_leg_finds_no_leak_and_replays_handles(tmp_path):
    pytest.importorskip("mcp")
    from adr_store.mcp_client import McpTools

    s = make_units_built(tmp_path / "s")
    directory, policy = config_of(s)
    acl.sync(s.path, directory, policy)   # the real clock: the servers read it
    probes = pu.leak_probes(s.path, "gov", sizes=dict.fromkeys(pu.LEAK_SIZES["gov"], 2))
    selected = pu.select_mcp([("gov", p) for p in probes], 4)
    assert len(selected) == 4 and selected == pu.select_mcp([("gov", p) for p in probes], 4)
    refs = pu.UnitReferences(pu.unit_context(s.path), tmp_path / "views",
                             directory=directory, policy=policy,
                             gov_config=uf.UNITS_GOV_CONFIG)

    def reference_for(label, caller):
        path = refs.path_for(caller)
        return None if path is None else tools.Tools(path, acl=True, caller=caller)

    def make_server(label, caller):
        return McpTools(s.path, caller, cwd=REPO, env={"HF_HUB_OFFLINE": "1"},
                        emb_cache=tmp_path / "emb")

    results, replays, calls = pu.run_mcp(selected, contexts={"gov": pu.unit_context(s.path)},
                                         reference_for=reference_for, make_server=make_server)
    assert len(results) == 4 and all(r.valid and not r.leak for _, r in results)
    assert replays and all(r["identical"] and r["handle_units"] for r in replays)
    assert sum(calls["gov"].values()) >= 4
    summary = pu.summarize_mcp(results, replays)
    assert summary["total"]["leaks"] == 0 and summary["replays"]["n"] == len(replays)


# -- the command line ----------------------------------------------------------------------------


def _summaries(out: Path, kind: str, corpus: str = "gov") -> list[Path]:
    return sorted(out.glob(f"probes-units-{kind}-{corpus}-*"))


def test_the_cli_runs_the_unit_probe_kinds(tmp_path, capsys):
    s = make_units_built(tmp_path / "s")
    directory, policy = config_of(s)
    acl.sync(s.path, directory, policy)   # the real clock: the CLI's tools read it
    out = tmp_path / "runs"
    gov_config = tmp_path / "gov-config.json"
    gov_config.write_text(json.dumps(uf.UNITS_GOV_CONFIG), encoding="utf-8")
    common = ["--store", str(s.path), "--directory", str(directory), "--policy",
              str(policy), "--views", str(tmp_path / "views"), "--out", str(out),
              "--gov-config", str(gov_config)]
    n_tools = len(pu.present_tools())
    runs = {"leak": (["--per-family", "2", "--keep-views"], 10),
            "equivalence": (["--queries", "6", "--keep-views"], None),
            "failclosed": (["--clones", str(tmp_path / "clones")], 6 * n_tools * 5),
            "applicability": (["--n", "4"], None),
            "define": (["--absent", "5"], None),
            "closure": ([], None),
            "procedures": ([], None)}
    for kind, (extra, total) in runs.items():
        codes = [main(["probes", f"units-{kind}", "gov", *common, *extra])
                 for _ in range(2)]   # twice: the per-item files are identical
        a, b = _summaries(out, kind)
        passed = json.loads((a / "summary.json").read_text())["summary"].get("pass", True)
        assert codes == [0 if passed else 1] * 2, kind   # U2 decides the closure census
        for name in ("probes.json", "results.json", "summary.json", "summary.md"):
            assert (a / name).read_bytes() == (b / name).read_bytes(), (kind, name)
        summary = json.loads((a / "summary.json").read_text())
        assert summary["logs"]["total"]["complete"], kind
        if total is not None:
            assert summary["summary"]["total"]["n"] == total, kind
        assert (a / "provenance.json").exists()
        text = (a / "summary.json").read_text() + (a / "summary.md").read_text()
        for d in (DOC_117_NEW, DOC_117_OLD, DOC_165, DOC_IRM):   # no ids in the summaries
            assert d[:12] not in text, kind
    capsys.readouterr()
    (a, _) = _summaries(out, "closure")
    c = json.loads((a / "summary.json").read_text())["summary"]
    assert isinstance(c["all"]["unresolved"], int)   # counted; the list is in results.json
    assert main(["probes", "units-leak", "research", *common]) == 2   # no leak sizes
    assert (tmp_path / "views").exists()   # kept
    assert main(["probes", "units-equivalence", "gov", *common, "--queries", "3"]) == 0
    assert not (tmp_path / "views").exists()   # removed without --keep-views


class _StubMcp:
    """An `adr mcp` client stand-in: the unit tools of the caller in this process."""

    closed = 0

    def __init__(self, store, caller, **kw):
        self.t = tools.Tools(store, acl=True, caller=caller)

    def __getattr__(self, name):
        return getattr(self.t, name)

    def close(self):
        _StubMcp.closed += 1


def test_the_cli_runs_units_mcp_with_also(tmp_path, capsys, monkeypatch):
    """M4: `units-mcp` with a second store (`--also`): every selected probe runs through a
    server of its caller (stubbed here), the log lines equal the calls, the replays name the
    units, and the summaries are byte-identical twice; `--also` is checked; M6: a reference
    whose units differ from the store's fails the run."""
    from adr_store import mcp_client

    monkeypatch.setattr(mcp_client, "McpTools", _StubMcp)
    gov = make_units_built(tmp_path / "gov")
    bench = make_units_built(tmp_path / "bench", corpus="bench")
    for st in (gov, bench):
        acl.sync(st.path, *config_of(st))   # the real clock: the CLI's tools read it
    directory, policy = config_of(gov)
    gov_config = tmp_path / "gov-config.json"
    gov_config.write_text(json.dumps(uf.UNITS_GOV_CONFIG), encoding="utf-8")
    out = tmp_path / "runs"
    common = ["probes", "units-mcp", "gov", "--store", str(gov.path), "--also",
              f"bench={bench.path}", "--directory", str(directory), "--policy", str(policy),
              "--views", str(tmp_path / "views" / "units-gov"), "--out", str(out),
              "--gov-config", str(gov_config), "--n", "8", "--per-family", "2"]
    assert main(common) == 0 and main(common) == 0
    a, b = _summaries(out, "mcp")
    for name in ("probes.json", "results.json", "summary.json", "summary.md"):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
    summary = json.loads((a / "summary.json").read_text())
    assert summary["summary"]["total"]["n"] == 8 and summary["summary"]["total"]["leaks"] == 0
    assert set(summary["summary"]["stores"]) == {"gov", "bench"}
    rp = summary["summary"]["replays"]
    assert rp["n"] and rp["identical"] == rp["handle_units"] == rp["n"]
    assert summary["logs"]["total"]["complete"]
    assert summary["logs"]["mcp"]["total"]["unit_lines"] == sum(
        sum(c.values()) for c in summary["logs"]["mcp"]["calls"].values())
    assert _StubMcp.closed > 0
    assert not (tmp_path / "views").exists() or not any((tmp_path / "views").iterdir())
    assert main([*common[:5], "--also", "research=x", *common[7:]]) == 2
    capsys.readouterr()
    # M6: a reference whose units would not equal the store's fails the run
    monkeypatch.setattr(pu, "comparable", lambda u: {"x": id(u)})
    assert main(common) == 1
