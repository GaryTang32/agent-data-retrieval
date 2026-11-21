"""The Phase 4 retrieval harness (spec §14, §15, R1, R2, P20, P21, P36, P42; Task 12): pieces and
the token budget, rule-ID recall with closure, procedure ranks, every system given the item's
`as_of`, the scoped reference, `p4-compare`, the unit-index tuning, the units gate's gold, and
`paired_ratio_diff_ci`.

The store is `units_fixtures.make_units_built` placed where the harness finds a p2 store
(`<p2_store_dir>/gov`), with a lexical `p1-struct` chunk index. `p2-default` is a
`systems.P2System` over that store (the real `systems.build` needs the gov corpus and v0.1
items, N25, so it is monkeypatched). Gold items are written into the redirected golden
directories. Nothing calls a model or reads `.cache/`."""

from __future__ import annotations

import itertools
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from adr_eval import phase4, runner, systems
from adr_eval.cli import main as eval_main
from adr_eval.golden import units as gu
from adr_eval.golden.units import ProcedureItem, RuleItem, write_items
from adr_eval.models import Evidence, Provenance
from adr_eval.phase4 import (
    P4Item,
    Piece,
    budget_cut,
    n_tokens,
    p4_compare,
    procedure_ranks,
    rule_recall,
    run_p4,
    section_key,
)
from adr_eval.runner import _takes_as_of
from adr_eval.scoring.stats import (
    cluster_bootstrap_ratio_ci,
    paired_bootstrap_ci,
    paired_ratio_diff_ci,
)
from adr_store import applicability as ap
from adr_store import tools
from adr_store.applicability import Filters
from adr_store.units import index as ui
from adr_store.units.ecfr import provisions
from adr_store.units.overlay import read_units_head
from adr_store.units.procedures import bench_candidates, irm_sections, is_procedure_like
from tests.store.tables_fixtures import T0
from tests.store.units_fixtures import (
    DOC_117_NEW,
    DOC_117_OLD,
    DOC_165,
    DOC_IRM,
    make_units_built,
)

NOW = T0 + timedelta(minutes=1)
PROV = Provenance(model="stub", prompt_hash="0" * 64, seed=20261121,
                  created=datetime(2026, 6, 26, tzinfo=UTC))
OLD_AS_OF = date(2025, 7, 1)          # in force: the older 33 CFR 117 version (2025-06-27 on)


# -- fixtures and helpers ----------------------------------------------------------------------

def prov(store, doc, pid):
    return next(p for p in provisions(store, doc) if p.provision_id == pid)


def ev(p) -> Evidence:
    return Evidence(doc_id=p.doc_id, char_start=p.start, char_end=p.end, quote=p.text)


def rule_item(store, n, pid, question, split="test", doc=DOC_117_NEW, as_of=None,
              closure=()) -> RuleItem:
    p = prov(store, doc, pid)
    cl = [prov(store, doc, c) for c in closure]
    return RuleItem(id=f"gov-rules-{n:03d}", corpus="gov-rules", snapshot=store.snapshot_id,
                    part=p.part, question=question, as_of=as_of, gold_rules=[pid],
                    closure_rules=list(closure), closure_evidence=[ev(c) for c in cl],
                    evidence=[ev(p)], split=split, provenance=PROV, status="auto_verified")


def procedure_item(store, n, number, question, split="test") -> ProcedureItem:
    s = next(x for x in irm_sections(store, DOC_IRM)[0] if x.number == number)
    text = store.text(DOC_IRM)[s.start:s.end]
    return ProcedureItem(id=f"gov-procedures-{n:03d}", corpus="gov-procedures",
                         snapshot=store.snapshot_id, question=question, gold=f"IRM {number}",
                         evidence=[Evidence(doc_id=DOC_IRM, char_start=s.start,
                                            char_end=s.end, quote=text)],
                         split=split, provenance=PROV, status="auto_verified")


def rule_items(store) -> list[RuleItem]:
    return [
        rule_item(store, 1, "33 CFR 117.901(c)", "Where must the owner of the Harbor Avenue "
                  "Bridge post the notice requirement?", closure=["33 CFR 117.901(b)"]),
        rule_item(store, 2, "33 CFR 117.821(b)", "How much notice does the Smith River "
                  "Railroad Bridge need before it opens on signal?", doc=DOC_117_OLD,
                  as_of=OLD_AS_OF),
        rule_item(store, 3, "33 CFR 165.13(b)", "May a vessel anchor in a regulated "
                  "navigation area without permission?", doc=DOC_165),
        rule_item(store, 4, "33 CFR 117.1081(a)(2)", "When need the Coast Channel Bridge not "
                  "open on weekday mornings?", split="dev"),
        rule_item(store, 5, "33 CFR 117.31(a)", "What must a drawtender do for an emergency "
                  "vehicle responding to an emergency?", split="dev"),
    ]


def procedure_items(store) -> list[ProcedureItem]:
    return [procedure_item(store, 1, "21.4.1.3.1", "A taxpayer says the refund never arrived; "
                           "what research should be done?"),
            procedure_item(store, 2, "21.4.1.3.2", "A direct deposit was rejected by the bank; "
                           "what should be done?"),
            procedure_item(store, 3, "21.4.1.3.2", "The bank returned a direct deposit refund; "
                           "what should be done?", split="dev")]


@pytest.fixture
def p4(tmp_path, monkeypatch):
    """(store, config): the units store as the gov p2 store, a lexical chunk index, gold items
    of gov-rules and gov-procedures written, the harness's clock one minute after the ACL
    sync, and `systems.build` giving a `P2System` over the store."""
    root = tmp_path / "p2"
    store = make_units_built(root / "gov")
    tools.Tools(store.path).index("p1-struct", lexical_only=True)
    write_items(gu.RULES_DIR, rule_items(store), [])
    write_items(gu.GOV_PROCEDURES_DIR, procedure_items(store), [])
    monkeypatch.setattr(phase4, "CLOCK", lambda: NOW)
    monkeypatch.setattr(phase4, "_v01", lambda corpus: (None, [], {}))
    monkeypatch.setattr(systems, "build", fake_build(store.path))
    return store, {"p2_store_dir": str(root), "p2_caller": "user:auditor"}


def fake_build(path: Path):
    def build(name, corpus, loaded, items, groups, config, **kw):
        t = tools.Tools(path)
        if name == "p1-struct-bc":
            idx = t.active_index()
            return SimpleNamespace(name=name, index=idx, w=None, chunks=idx.chunks,
                                   fingerprint=idx.fingerprint, store_path=path,
                                   run_config=lambda: {"system": name})
        assert name == "p2-default"
        searcher = tools.Tools(path, acl=True, caller="user:auditor", clock=lambda: NOW)
        phase1 = SimpleNamespace(w=None, store_path=path,
                                 run_config=lambda: {"system": "p1-struct-bc"})
        return systems.P2System(name, systems.P2Spec(Filters(), as_of=True, dedup=False), t,
                                phase1, "built", None, None, [], caller="user:auditor",
                                searcher=searcher)

    return build


def run_data(out: Path, run_id: str) -> dict:
    return json.loads((out / run_id / "p4.json").read_text(encoding="utf-8"))


def piece(tokens: int, doc: str = "d", start: int = 0) -> Piece:
    text = " ".join(f"w{i}" for i in range(tokens))
    return Piece(doc, start, start + len(text), text, f"s{tokens}")


# -- the budget ----------------------------------------------------------------------------------

def test_budget_cut_shortens_the_crossing_piece():
    pieces = [piece(1500), piece(800, start=10_000), piece(10, start=20_000)]
    ps = budget_cut(pieces, 2000)
    assert len(ps) == 2 and n_tokens(ps[1].text) == 500
    assert ps[1].char_end - ps[1].char_start == len(ps[1].text)
    assert ps[0] == pieces[0]                                   # kept whole
    assert pieces[1].text.startswith(ps[1].text) and ps[1].char_start == 10_000
    # the longest prefix: one more character starts the 501st token
    assert n_tokens(pieces[1].text[:len(ps[1].text) + 1]) == 501
    assert sum(n_tokens(p.text) for p in ps) == 2000


def test_budget_cut_edges():
    pieces = [piece(1200), piece(800, start=5000), piece(3, start=9000)]
    assert budget_cut(pieces[:2], 2000) == pieces[:2]           # an exact fit is kept whole
    assert budget_cut(pieces, 2000) == pieces[:2]               # nothing after a full budget
    assert budget_cut(pieces, 0) == []
    assert budget_cut([], 2000) == []
    assert phase4.TOKEN_BUDGET == 2000 and budget_cut([piece(2001)]) == [
        replace(piece(2001), char_end=len(piece(2000).text) + 1,
                text=piece(2001).text[:len(piece(2000).text) + 1])]


# -- rule-ID recall (R1) -------------------------------------------------------------------------

def test_rule_recall_is_span_based_and_counts_closure(p4):
    store, cfg = p4
    item = phase4.p4_item(rule_items(store)[0])          # 117.901(c), closure 117.901(b)
    system = phase4.build_system("p4-units", "gov", cfg, "rule")
    ranked = phase4.ranked_items(system, item)
    card, closure_b = ranked[0][0], ranked[0][1]
    c, b = item.gold[0], item.closure[0]
    assert (card.doc_id, card.char_start, card.char_end) == (c.doc_id, c.char_start, c.char_end)
    assert (closure_b.char_start, closure_b.char_end) == (b.char_start, b.char_end)
    assert closure_b.source == "33 CFR 117.901(b)" and closure_b.text == b.quote
    gold = [*item.gold, *item.closure]
    pieces = phase4.pieces_for(system, item)
    two = n_tokens(card.text) + n_tokens(closure_b.text)
    # the closure piece covers the second gold provision within the budget
    assert rule_recall(budget_cut(pieces, two), gold) == 1.0
    assert rule_recall(budget_cut(pieces, n_tokens(card.text)), gold) == 0.5
    # span based: the same text in the superseded version's document is not the gold span
    assert rule_recall([replace(p, doc_id=DOC_117_OLD) for p in (card, closure_b)], gold) == 0
    # any overlap touches; an adjacent span does not
    assert rule_recall([Piece(b.doc_id, b.char_end - 1, b.char_end, "x", "s")], [b]) == 1.0
    assert rule_recall([Piece(b.doc_id, b.char_end, b.char_end + 9, "x", "s")], [b]) == 0.0
    with pytest.raises(ValueError):
        rule_recall(pieces, [])
    # the row: recall on gold_rules, closure recall on closure_rules (reported apart)
    m = phase4.score_rule(item, ranked)
    assert m["recall"] == 1.0 and m["closure_recall"] == 1.0 and m["mrr"] == 1.0
    m = phase4.score_rule(item, ranked, budget=n_tokens(card.text))
    assert m["recall"] == 1.0 and m["closure_recall"] == 0.0
    assert m["tokens"] == n_tokens(card.text)


def test_older_items_pass_as_of_to_every_system(p4, monkeypatch):                       # P36
    store, cfg = p4
    items = rule_items(store)
    by_question = {i.question: i.id for i in items}
    seen: dict[str, dict] = {"p2-default": {}, "p4-units": {}}
    real_search, real_lookup = tools.Tools.search, tools.Tools.rule_lookup

    def search(self, query, *a, filters=None, **kw):
        seen["p2-default"][by_question[query]] = getattr(filters, "as_of", None)
        return real_search(self, query, *a, filters=filters, **kw)

    def rule_lookup(self, query=None, **kw):
        seen["p4-units"][by_question[query]] = kw.get("as_of")
        return real_lookup(self, query, **kw)

    monkeypatch.setattr(tools.Tools, "search", search)
    monkeypatch.setattr(tools.Tools, "rule_lookup", rule_lookup)
    out = Path(cfg["p2_store_dir"]).parent / "runs"
    a = run_data(out, run_p4("gov-rules", "p2-default", "test", cfg, out))
    b = run_data(out, run_p4("gov-rules", "p4-units", "test", cfg, out))
    want = {i.id: i.as_of for i in items if i.split == "test"}
    assert OLD_AS_OF in want.values()
    assert seen["p2-default"] == seen["p4-units"] == want
    for data in (a, b):
        rows = {r["item_id"]: r for r in data["rows"]}
        assert {k: r["as_of"] for k, r in rows.items()} == {
            k: v and v.isoformat() for k, v in want.items()}
        # the older item's gold is the superseded version's span, found with its as_of
        assert rows["gov-rules-002"]["metrics"]["recall"] == 1.0
    # without its as_of the newest version's paragraph is found, not the gold one
    older = phase4.p4_item(items[1])
    sys_units = phase4.build_system("p4-units", "gov", cfg, "rule")
    assert phase4.score_rule(replace(older, as_of=None),
                             phase4.ranked_items(sys_units, replace(older, as_of=None))
                             )["recall"] == 0.0
    # p1-struct-bc takes no as_of: reported beside, flagged
    c = run_data(out, run_p4("gov-rules", "p1-struct-bc", "test", cfg, out))
    assert c["config"]["system_config"]["as_of_applied"] is False
    assert all(r["as_of"] is None for r in c["rows"])


def test_runner_takes_as_of_is_unchanged(make_item):
    p2_like = SimpleNamespace(accepts_as_of=True)
    assert _takes_as_of(p2_like, make_item(qtype="factoid", as_of=date(2025, 7, 1))) is False
    assert _takes_as_of(p2_like, make_item(qtype="policy_asof", as_of=date(2025, 7, 1)))
    assert _takes_as_of(SimpleNamespace(), make_item(qtype="policy_asof",
                                                     as_of=date(2025, 7, 1))) is False


# -- procedure top-5 (R2) ------------------------------------------------------------------------

def test_procedure_ranks_dedup_sections_in_rank_order():
    assert procedure_ranks(["IRM 1", "IRM 1", "IRM 2", "IRM 3"], "IRM 3") == {
        "hit@1": 0, "hit@5": 1, "rr": 1 / 3}
    assert procedure_ranks(["IRM 3", "IRM 1"], "IRM 3") == {"hit@1": 1, "hit@5": 1, "rr": 1.0}
    six = ["a", "a", "b", "c", "d", "e", "e", "g"]                 # deduped: g is 6th
    assert procedure_ranks(six, "g") == {"hit@1": 0, "hit@5": 0, "rr": 1 / 6}
    assert procedure_ranks(six, "e") == {"hit@1": 0, "hit@5": 1, "rr": 1 / 5}
    assert procedure_ranks([], "x") == {"hit@1": 0, "hit@5": 0, "rr": 0.0}


def test_section_key_maps_irm_sections_and_documents(p4):
    store, _ = p4
    sections = phase4.irm_section_map(store)
    assert list(sections) == [DOC_IRM]
    s1, s2 = (x for x in sections[DOC_IRM] if x.number in ("21.4.1.3.1", "21.4.1.3.2"))
    assert section_key(DOC_IRM, s1.start, sections) == "IRM 21.4.1.3.1"
    assert section_key(DOC_IRM, s1.end - 1, sections) == "IRM 21.4.1.3.1"
    assert section_key(DOC_IRM, s2.start, sections) == "IRM 21.4.1.3.2"
    assert section_key(DOC_IRM, 0, sections) == DOC_IRM                 # before any section
    assert section_key(DOC_117_NEW, 10, sections) == DOC_117_NEW        # not an IRM document


def test_p4_units_routes_procedures_and_scores_r2(p4):
    store, cfg = p4
    out = Path(cfg["p2_store_dir"]).parent / "runs"
    data = run_data(out, run_p4("gov-procedures", "p4-units", "test", cfg, out))
    rows = {r["item_id"]: r for r in data["rows"]}
    assert set(rows) == {"gov-procedures-001", "gov-procedures-002"}
    for item in procedure_items(store)[:2]:
        r = rows[item.id]
        assert r["metrics"] == procedure_ranks(r["keys"], item.gold)
        assert r["keys"][0] == item.gold and r["metrics"]["hit@1"] == 1
    assert data["summary"]["pooled"]["hit@5"] == 1.0


def test_scoped_system_keeps_only_in_scope_chunks_in_order(p4):
    store, cfg = p4
    chunks = tools.Tools(store.path).active_index().chunks
    ecfr = {d for d in store.doc_ids()
            if (ap.chain_of(store.source(d)) or "").startswith("ecfr:")}
    proc_spans = [(s.start, s.end) for s in irm_sections(store, DOC_IRM)[0]
                  if is_procedure_like(s)]
    bench = set(bench_candidates(store))

    def in_procedure_scope(c):
        return c.doc_id in bench or (c.doc_id == DOC_IRM and any(
            a <= c.char_start < b for a, b in proc_spans))

    question = ("refund research direct deposit drawbridge notice vessel gateway failover "
                "region rotate key what should be done")
    for kind, keep in (("rule", lambda c: c.doc_id in ecfr), ("procedure", in_procedure_scope)):
        item = P4Item("x", question, None, "test", kind)
        full = [it[0].source for it in phase4.ranked_items(
            phase4.build_system("p2-default", "gov", cfg, kind), item)]
        got = [it[0].source for it in phase4.ranked_items(
            phase4.build_system("p2-default-scoped", "gov", cfg, kind), item)]
        assert got == [c for c in full if keep(chunks[c])], kind
        assert got and len(got) < len(full), kind                # some kept, some dropped
        assert len(full) <= phase4.DEPTH == 100
        if kind == "procedure":   # the fixture's IRM text is one chunk, starting before 3.1
            irm = [c for c in full if chunks[c].doc_id == DOC_IRM]
            assert irm and not set(irm) & set(got)
            assert {chunks[c].doc_id for c in got} == bench


def test_secondary_gold_is_the_provisions_the_evidence_overlaps(p4, make_item):
    store, _ = p4
    a, b = prov(store, DOC_117_NEW, "33 CFR 117.31(a)"), prov(store, DOC_117_NEW,
                                                              "33 CFR 117.31(b)")
    span = Evidence(doc_id=DOC_117_NEW, char_start=a.end - 5, char_end=b.start + 5, quote="x")
    gold, part = phase4.secondary_gold(store, make_item(evidence=[span]))
    assert [(g.char_start, g.char_end) for g in gold] == [(a.start, a.end), (b.start, b.end)]
    assert part == "33 CFR 117" and gold[0].quote == a.text
    irm = Evidence(doc_id=DOC_IRM, char_start=0, char_end=50, quote="x")
    assert phase4.secondary_gold(store, make_item(evidence=[irm])) == ([], None)
    inside = Evidence(doc_id=DOC_165, char_start=prov(store, DOC_165, "33 CFR 165.13(b)").start,
                      char_end=prov(store, DOC_165, "33 CFR 165.13(b)").start + 3, quote="x")
    gold, part = phase4.secondary_gold(store, make_item(evidence=[irm, inside]))
    assert [g.char_start for g in gold] == [inside.char_start] and part == "33 CFR 165"


# -- runs, the CLI and no model calls -------------------------------------------------------------

def _forbid_model_clients(monkeypatch):
    import adr_eval.llm as llm

    def boom(*a, **kw):
        raise AssertionError("a model client was created")

    for name in ("AnthropicClient", "ClaudeCodeClient", "OpenAICompatibleClient",
                 "StubClient", "CachedStubClient"):
        monkeypatch.setattr(getattr(llm, name), "__init__", boom)
    for name in ("make_client", "_role_clients", "stub_clients"):
        monkeypatch.setattr(runner, name, boom)


def test_retrieval_runs_make_no_model_call(p4, monkeypatch, capsys):
    store, cfg = p4
    _forbid_model_clients(monkeypatch)
    monkeypatch.setattr(runner, "load_config", lambda *a, **kw: cfg)
    out = Path(cfg["p2_store_dir"]).parent / "runs"
    for golden in ("gov-rules", "gov-procedures"):
        for system in phase4.SYSTEMS:
            assert eval_main(["p4-retrieval", "--golden", golden, "--system", system,
                              "--split", "test", "--out", str(out)]) == 0, (golden, system)
    printed = capsys.readouterr().out
    assert printed.count("p4-retrieval") >= 10 and "recall" in printed and "hit@5" in printed
    runs = sorted(p.name for p in out.iterdir())
    assert len(runs) == 10
    data = run_data(out, next(r for r in runs if r.startswith("gov-rules-p4-units-")))
    cfg_run = data["config"]
    assert cfg_run["n_items"] == 3 and cfg_run["budget"] == 2000 and cfg_run["depth"] == 100
    assert cfg_run["system_config"]["units"] == read_units_head(store.path)
    assert cfg_run["system_config"]["unit_index"] == ui.tuning_id(ui.load_tuning("gov"))
    assert set(data["summary"]["pooled"]) >= set(phase4.RULE_METRICS)
    assert set(data["summary"]["by_part"]) == {"33 CFR 117", "33 CFR 165"}


def test_run_p4_rows_score_every_item(p4):
    store, cfg = p4
    out = Path(cfg["p2_store_dir"]).parent / "runs"
    data = run_data(out, run_p4("gov-rules", "p4-units", "test", cfg, out))
    system = phase4.build_system("p4-units", "gov", cfg, "rule")
    for item in rule_items(store):
        if item.split != "test":
            continue
        row = next(r for r in data["rows"] if r["item_id"] == item.id)
        want = phase4.score_rule(phase4.p4_item(item),
                                 phase4.ranked_items(system, phase4.p4_item(item)))
        assert row["metrics"] == want
        assert row["metrics"]["tokens"] <= 2000
    pooled = data["summary"]["pooled"]
    assert pooled["n"] == 3 and pooled["n_defined"]["closure_recall"] == 1
    assert pooled["recall"] == pytest.approx(np.mean([r["metrics"]["recall"]
                                                      for r in data["rows"]]))
    assert data["config"]["golden_sha256"] and data["config"]["caller"] == "user:auditor"
    # the same run again gives the same rows (no clock in a row)
    again = run_data(out, run_p4("gov-rules", "p4-units", "test", cfg, out))
    assert again["rows"] == data["rows"] and again["summary"] == data["summary"]
    with pytest.raises(runner.RunError, match="unknown system"):
        run_p4("gov-rules", "p9", "test", cfg, out)
    with pytest.raises(runner.RunError, match="unknown golden set"):
        run_p4("gov-x", "p4-units", "test", cfg, out)


# -- p4-compare ----------------------------------------------------------------------------------

def fake_run(path: Path, golden: str, system: str, values: dict, metric: str = "hit@5",
             split: str = "test") -> Path:
    path.mkdir(parents=True)
    rows = [{"item_id": k, "metrics": {metric: v, "rr": 0.0}} for k, v in values.items()]
    data = {"config": {"format": phase4.FORMAT, "golden": golden, "system": system,
                       "split": split, "budget": 2000}, "summary": {}, "rows": rows}
    (path / "p4.json").write_text(json.dumps(data), encoding="utf-8")
    return path


def test_p4_compare_pools_corpora_and_reports_each(tmp_path, capsys):
    ga = fake_run(tmp_path / "ga", "gov-procedures", "p2-default",
                  {"gov-procedures-003": 0, "gov-procedures-001": 0, "gov-procedures-002": 1})
    gb = fake_run(tmp_path / "gb", "gov-procedures", "p4-units",
                  {"gov-procedures-001": 1, "gov-procedures-002": 1, "gov-procedures-003": 1})
    ba = fake_run(tmp_path / "ba", "bench-procedures", "p2-default",
                  {"bench-procedures-001": 1, "bench-procedures-002": 0})
    bb = fake_run(tmp_path / "bb", "bench-procedures", "p4-units",
                  {"bench-procedures-001": 0, "bench-procedures-002": 1})
    c = p4_compare(ga, gb, "hit@5", pooled=[(ba, bb)])
    gov, bench = c["each"]
    assert (gov["golden"], gov["n"], gov["mean_a"], gov["mean_b"]) == (
        "gov-procedures", 3, pytest.approx(1 / 3), 1.0)
    assert gov["diff"] == pytest.approx(2 / 3)
    assert (bench["n"], bench["mean_a"], bench["mean_b"], bench["diff"]) == (2, 0.5, 0.5, 0.0)
    # pooled: gov items by id, then bench items by id
    x, y = [0, 1, 0, 1, 0], [1, 1, 1, 0, 1]
    diff, lo, hi = paired_bootstrap_ci(x, y, n=10_000, seed=20261108)
    assert c["pooled"]["n"] == 5 and c["pooled"]["diff"] == pytest.approx(0.4) == diff
    assert c["pooled"]["ci"] == [lo, hi]
    assert c["pooled"]["lower_above_margin"] is (lo > 0.02)
    assert c["each_point_non_negative"] is True
    assert (c["system_a"], c["system_b"], c["seed"], c["resamples"]) == (
        "p2-default", "p4-units", 20261108, 10_000)
    assert "procedures-00" not in json.dumps(c)                         # no item id
    worse = fake_run(tmp_path / "bw", "bench-procedures", "p4-units",
                     {"bench-procedures-001": 0, "bench-procedures-002": 0})
    assert p4_compare(ga, gb, "hit@5", pooled=[(ba, worse)])["each_point_non_negative"] is False
    # refusals
    other = fake_run(tmp_path / "o", "gov-procedures", "p4-units", {"gov-procedures-001": 1})
    with pytest.raises(runner.RunError, match="different items"):
        p4_compare(ga, other, "hit@5")
    dev = fake_run(tmp_path / "d", "gov-procedures", "p4-units", {"gov-procedures-001": 1},
                   split="dev")
    with pytest.raises(runner.RunError, match="different split"):
        p4_compare(ga, dev, "hit@5")
    with pytest.raises(runner.RunError, match="not a metric"):
        p4_compare(ga, gb, "recall")
    with pytest.raises(runner.RunError, match="pooled runs must compare"):
        p4_compare(ga, gb, "hit@5", pooled=[(bb, ba)])
    # the CLI writes the comparison beside run_a and a committed form without ids
    summary = tmp_path / "summary.json"
    assert eval_main(["p4-compare", str(ga), str(gb), "--metric", "hit@5", "--pool", str(ba),
                      str(bb), "--summary", str(summary)]) == 0
    assert "pooled" in capsys.readouterr().out
    assert json.loads(summary.read_text()) == c
    assert json.loads((ga / f"p4-compare-{gb.name}-hit@5.json").read_text()) == c


# -- the units gate's gold -----------------------------------------------------------------------

def test_gate_with_rule_gold_refuses_a_regression(p4, tmp_path, monkeypatch, capsys):
    from adr_store import cli as adr_cli
    from tests.store.test_units_build import derived

    store, _ = p4
    head = read_units_head(store.path)
    gold = tmp_path / "gold" / "gov-rules"
    write_items(gold, rule_items(store), [])
    worse = derived(store.path, head, "33 CFR 117.901(c)")
    args = ["units", "gate", "--store", str(store.path), "--candidate", worse, "--gold",
            str(gold), "--max-flips", "0", "--json"]
    assert adr_cli.main(args) == adr_cli.EXIT_CONFORMANCE
    r = json.loads(capsys.readouterr().out)
    assert (r["promoted"], r["flips"], r["gains"], r["n"]) == (False, ["gov-rules-001"], [], 5)
    assert read_units_head(store.path) == head                         # HEAD unchanged
    # every rule case HEAD hits, dev items included; the candidate misses only the dropped one
    cases = phase4.gold_cases(gold)
    assert [c.kind for c in cases] == ["rule"] * 5
    assert [phase4.rule_hit(store.path, head, c) for c in cases] == [True] * 5
    assert [phase4.rule_hit(store.path, worse, c) for c in cases] == [False] + [True] * 4
    # procedure gold: a candidate without the procedure units misses them
    pgold = tmp_path / "gold" / "gov-procedures"
    write_items(pgold, procedure_items(store), [])
    pcases = phase4.gold_cases(pgold)
    assert [phase4.procedure_hit(store.path, head, c) for c in pcases] == [True] * 3
    no_procs = _without_procedures(store.path, head)
    assert [phase4.procedure_hit(store.path, no_procs, c) for c in pcases] == [False] * 3
    args = ["units", "gate", "--store", str(store.path), "--candidate", no_procs, "--gold",
            str(gold), "--gold", str(pgold), "--max-flips", "2", "--json"]
    assert adr_cli.main(args) == adr_cli.EXIT_CONFORMANCE
    r = json.loads(capsys.readouterr().out)
    assert r["flips"] == ["gov-procedures-001", "gov-procedures-002", "gov-procedures-003"]
    assert read_units_head(store.path) == head
    # HEAD against itself: no flip, promoted (HEAD stays where it is)
    args = ["units", "gate", "--store", str(store.path), "--candidate", head, "--gold",
            str(gold), "--max-flips", "0"]
    assert adr_cli.main(args) == 0 and read_units_head(store.path) == head
    assert "0 flip(s) of 5 case(s)" in capsys.readouterr().out
    # a directory of other items is refused
    bad = tmp_path / "gold" / "bad"
    bad.mkdir()
    (bad / "items.jsonl").write_text(json.dumps({"corpus": "gov", "id": "x"}) + "\n")
    args[args.index(str(gold))] = str(bad)
    assert adr_cli.main(args) == 2
    assert "not a unit gold case" in capsys.readouterr().err


def _without_procedures(store_path: Path, units_id: str) -> str:
    from adr_store.units.overlay import load_units_manifest, write_units_manifest

    m = load_units_manifest(store_path, units_id)
    return write_units_manifest(store_path, m.model_copy(
        update={"units": [f for f in m.units if f.type != "procedure"]}))[0]


# -- tuning --------------------------------------------------------------------------------------

def _ndcg(keys, gold, k=10):
    """An independent binary nDCG@k over keys (the first occurrence of a gold key gains)."""
    gains = []
    credited = set()
    for key in keys[:k]:
        gains.append(1.0 if key in gold and key not in credited else 0.0)
        credited |= {key} & gold
    dcg = sum(g / np.log2(r + 2) for r, g in enumerate(gains))
    return dcg / sum(1 / np.log2(r + 2) for r in range(min(k, len(gold))))


def test_tune_picks_weights_then_w_on_dev(p4, tmp_path, monkeypatch, capsys):
    from adr_store.units.build import CORPUS_TYPES
    from adr_store.units.overlay import load_units, load_units_manifest
    from tests.store.test_retrieval import fake_cache

    store, _ = p4
    report: dict = {}
    entry = phase4.tune(["gov-rules", "gov-procedures"], store.path,
                        emb=fake_cache(tmp_path / "emb"), report=report)
    assert ui.check_tuning(entry, CORPUS_TYPES["gov"]) == entry
    for t in ("concept", "table_record"):                    # no dev items: weights stay 1
        assert set(entry["weights"][t].values()) == {1}
    assert report["dev"] == {"gov-rules": 2, "gov-procedures": 1}
    # the oracle: every grid point scored on its type's dev items through the unit index
    head = read_units_head(store.path)
    units = load_units(store.path, load_units_manifest(store.path, head))
    docs = ui.unit_docs(units, [u for u in units if u.type == "concept"])
    by_id = {u.unit_id: u for u in units}
    sections = phase4.irm_section_map(store)

    def key(uid):
        u = by_id[uid]
        return u.canonical_ref if u.type == "rule_card" else section_key(
            u.doc_id, u.source_refs[0].start, sections)

    dev_rules = [phase4.p4_item(i) for i in rule_items(store) if i.split == "dev"]
    dev_procs = [phase4.p4_item(i) for i in procedure_items(store) if i.split == "dev"]
    old = {u.doc_id for u in units if u.applicability.status == "superseded"}
    admitted = frozenset(store.doc_ids()) - old

    def score(tuning, items, emb=None):
        idx = ui.UnitIndex.build(store.path, head, docs, emb, tuning, install=emb is not None)
        vals = []
        for i in items:
            t = "rule_card" if i.kind == "rule" else "procedure"
            gold = set(i.gold_rules) if i.kind == "rule" else {i.gold_key}
            hits = idx.search(i.question, types=(t,), view=None, admitted=admitted, k=10)
            vals.append(_ndcg([key(u) for u, _ in hits], gold))
        return float(np.mean(vals))

    base = ui.default_tuning("gov")
    for t, items in (("procedure", dev_procs), ("rule_card", dev_rules)):
        grid = [dict(zip(ui.FIELDS, c, strict=True))
                for c in itertools.product(ui.WEIGHT_GRID, repeat=5)]
        scores = [score({**base, "weights": {**base["weights"], t: g}}, items) for g in grid]
        first_best = grid[int(np.argmax(scores))]              # ties: first in grid order
        assert entry["weights"][t] == first_best, t
        assert report["weights_ndcg10"][t] == pytest.approx(max(scores))
        base = {**base, "weights": {**base["weights"], t: first_best}}
    w_scores = {w: score({**base, "w": w}, [*dev_rules, *dev_procs],
                         fake_cache(tmp_path / "emb-oracle")) for w in ui.W_GRID}
    best = max(w_scores.values())
    assert entry["w"] == max(w for w, s in w_scores.items() if s == pytest.approx(best))
    # deterministic, and written into the gov entry of a tuning file by p4-tune
    assert phase4.tune(["gov-rules", "gov-procedures"], store.path,
                       emb=fake_cache(tmp_path / "emb3")) == entry
    out = tmp_path / "tuning.json"
    out.write_text(ui.TUNING_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(tools, "make_embedding_cache",
                        lambda *a, **kw: fake_cache(tmp_path / "emb4"))
    assert eval_main(["p4-tune", "--golden", "gov-rules", "--golden", "gov-procedures",
                      "--store", str(store.path), "--out", str(out)]) == 0
    assert "gov" in capsys.readouterr().out
    written = json.loads(out.read_text())
    committed = json.loads(ui.TUNING_PATH.read_text(encoding="utf-8"))
    assert written["gov"] == entry and list(written) == list(committed)
    assert {k: v for k, v in written.items() if k != "gov"} == {
        k: v for k, v in committed.items() if k != "gov"}
    head = read_units_head(store.path)
    assert ui.pinned_tuning(store.path, head, ui.tuning_id(entry), corpus="gov") == entry
    # refusals: two corpora at once, the secondary set
    with pytest.raises(runner.RunError, match="one corpus"):
        phase4.tune(["gov-rules", "bench-procedures"], store.path, emb=object())
    with pytest.raises(runner.RunError, match="tune takes"):
        phase4.tune(["gov-v0.1-ecfr"], store.path, emb=object())


def test_p4_tune_pins_its_entry_and_dense_vectors(p4, tmp_path, monkeypatch, capsys):
    """I1: `adr-eval p4-tune` pins the entry it writes under the tuned store's units, with the
    dense vectors below w = 1, so the unit tools serve it once it is the tuning in force."""
    from tests.store.test_retrieval import fake_cache

    store, cfg = p4
    head = read_units_head(store.path)
    tuned = ui.default_tuning("gov")
    tuned["weights"]["rule_card"].update(body=3, title=2)
    tuned = {**tuned, "w": 0.6}
    emb = fake_cache(tmp_path / "emb")

    def fake_tune(goldens, store_path, *, emb=None, report=None):
        report.update(corpus="gov", units=head, dev={"gov-rules": 2}, weights_ndcg10={},
                      w_ndcg10=0.0)
        return tuned

    monkeypatch.setattr(phase4, "tune", fake_tune)
    monkeypatch.setattr(tools, "make_embedding_cache", lambda *a, **kw: emb)
    out = tmp_path / "tuning.json"
    out.write_bytes(ui.tuning_path().read_bytes())
    t = tools.Tools(store.path, acl=True, caller="user:auditor", clock=lambda: NOW)
    monkeypatch.setenv(ui.TUNING_ENV, str(out))
    assert eval_main(["p4-tune", "--golden", "gov-rules", "--store", str(store.path),
                      "--out", str(out)]) == 0
    assert f"pinned as unit_index {ui.tuning_id(tuned)[:12]}" in capsys.readouterr().out
    assert json.loads(ui.pin_path(store.path, head, ui.tuning_id(tuned)).read_bytes()) == tuned
    assert list((store.path / "units-index" / head).glob("dense-*/vectors.npy"))
    res = t.rule_lookup("drawbridge notice")                   # served, embedding no document
    assert res.handle["unit_index"] == ui.tuning_id(tuned) and res.cards
    # `adr units pin` is idempotent over it
    from adr_store import cli as adr_cli

    assert adr_cli.main(["units", "pin", "--store", str(store.path)]) == 0
    assert ui.tuning_id(tuned)[:12] in capsys.readouterr().out


def test_rule_hit_respects_the_budget(p4, monkeypatch):
    """M1: the gate's rule hit cuts at the budget: with no budget left nothing is hit."""
    store, _ = p4
    head = read_units_head(store.path)
    case = phase4.gold_cases(gu.RULES_DIR)[0]
    assert phase4.rule_hit(store.path, head, case)
    monkeypatch.setattr(phase4, "TOKEN_BUDGET", 0)
    assert not phase4.rule_hit(store.path, head, case)


def test_recall_at_10_counts_closure_pieces():
    """M1 (ruling 6): a card and its closure are one item: a gold provision covered only by
    the closure piece of the first item counts for Recall@10; the eleventh item does not."""
    gold = Evidence(doc_id="d", char_start=100, char_end=120, quote="x" * 20)
    card = Piece("d", 0, 10, "card text", "u1")
    closure = Piece("d", 105, 115, "closure text", "33 CFR 1.1(a)")
    filler = [[Piece("e", i * 10, i * 10 + 5, f"w{i}", f"f{i}")] for i in range(10)]
    item = P4Item("x", "q", None, "test", "rule", (gold,))
    assert phase4.score_rule(item, [[card, closure], *filler[:9]])["recall@10"] == 1.0
    assert phase4.score_rule(item, [*filler, [card, closure]])["recall@10"] == 0.0
    assert phase4.score_rule(item, [[card], *filler[:9]])["recall@10"] == 0.0


def test_tune_never_reads_test_items(p4, tmp_path, monkeypatch):
    """M1 (C13): tuning searches the dev questions only; poisoned test items are never
    searched; a set without dev items is refused."""
    from tests.store.test_retrieval import fake_cache

    store, _ = p4
    poisoned = [rule_item(store, 9, "33 CFR 117.40(a)", "POISON drawbridge owner request"),
                *rule_items(store)]
    write_items(gu.RULES_DIR, poisoned, [])
    asked: list[str] = []
    real = ui.UnitIndex.search

    def search(self, query, **kw):
        asked.append(query)
        return real(self, query, **kw)

    monkeypatch.setattr(ui.UnitIndex, "search", search)
    phase4.tune(["gov-rules", "gov-procedures"], store.path, emb=fake_cache(tmp_path / "e"))
    dev = {i.question for i in [*poisoned, *procedure_items(store)] if i.split == "dev"}
    assert asked and set(asked) == dev
    write_items(gu.GOV_PROCEDURES_DIR, [i for i in procedure_items(store) if i.split == "test"],
                [])
    with pytest.raises(runner.RunError, match="no dev items"):
        phase4.tune(["gov-procedures"], store.path, emb=object())


def test_write_tuning_keeps_the_file_and_other_corpora(tmp_path):
    path = tmp_path / "t.json"
    path.write_bytes(ui.TUNING_PATH.read_bytes())
    ui.write_tuning("gov", ui.load_tuning("gov"), path)
    assert path.read_bytes() == ui.TUNING_PATH.read_bytes()      # an unchanged entry: same bytes
    entry = {**ui.default_tuning("bench"), "w": 0.75}
    ui.write_tuning("bench", entry, path)
    assert ui.load_tuning("bench", path) == entry and ui.load_tuning("gov", path) == \
        ui.load_tuning("gov")
    with pytest.raises(ValueError):
        ui.write_tuning("bench", {**entry, "w": 0.72}, path)      # not on the grid


# -- paired_ratio_diff_ci ------------------------------------------------------------------------

def test_paired_ratio_diff_ci():
    # by hand: two clusters, a = 1/2 overall, b = 1; the paired resamples are (0,0): b-a = 0,
    # (1,1): 1, and (0,1)/(1,0): 0.5, so with 10,000 draws the 2.5% and 97.5% points are 0, 1
    point, lo, hi = paired_ratio_diff_ci([1, 0], [1, 1], [1, 1], [1, 1], n=10_000,
                                         seed=20261108)
    assert (point, lo, hi) == (0.5, 0.0, 1.0)
    # unequal denominators: the point is the difference of the pooled ratios, not of means
    point, lo, hi = paired_ratio_diff_ci([1, 2], [2, 2], [2, 2], [2, 4])
    assert point == pytest.approx(4 / 6 - 3 / 4) and lo <= point <= hi
    # side a all zero: exactly the cluster bootstrap of side b (same draws)
    assert paired_ratio_diff_ci([0, 0, 0], [1, 2, 1], [1, 2, 0], [2, 2, 1], n=2000, seed=7) \
        == cluster_bootstrap_ratio_ci([1, 2, 0], [2, 2, 1], n=2000, seed=7)
    # pairing: identical sides differ by 0 in every resample
    assert paired_ratio_diff_ci([1, 3, 0], [2, 4, 1], [1, 3, 0], [2, 4, 1]) == (0.0, 0.0, 0.0)
    # a resample with no denominator on one side is left out, the rest still give an interval
    point, lo, hi = paired_ratio_diff_ci([1, 0], [1, 0], [1, 1], [1, 1], n=1000, seed=3)
    assert point == 0.0 and np.isfinite([lo, hi]).all()
    with pytest.raises(ValueError):
        paired_ratio_diff_ci([1], [1], [1, 2], [1, 1])
    with pytest.raises(ValueError):
        paired_ratio_diff_ci([0, 0], [0, 0], [1, 1], [1, 1])
