"""The candidate bindings build, `adr bindings build` (Phase 4 spec §12.2–§12.4, P46, P48;
preflight C5, C6; Task 17).

`build_candidates(store, client, *, units_id, facts_id)`:
1. z3 is checked first (`analysis_module`: the `[analysis]` extra, or BindingsError naming it).
2. The rule cards are those of the units build `units_id` (C6); the facts `facts_id` are the
   Phase 3 second pass the reference evaluator reads (C5).
3. The enrichment is read again from the model cache through `client` (`--max-calls 0`) and
   written (write-once, so its id is the file the units pass read).
4. The compiler (§12.2) runs on it; every binding is tested (§12.3, `checks.mark_tested`);
   every draw whose bindings all passed is analysed with Z3 (§12.4).
5. **B1:** the agreement set is `reference.agreement_set` over the reference draws of the facts
   (draws paired by bridge key, then mile), less the draws whose parameters are period-specific
   or flagged (a period-less notice or basis whose sentence states times, days, holidays or
   dates, P46, or a period with sentence qualifiers or conditions); each agreement draw is
   compared with the reference on the B1 grid, and a draw with a mismatch is rejected whole
   (P48). The grid summary is appended to each of its bindings' `tests`.
6. **B2:** totals of the analysis records (conflicts, vacuous, redundant, draws with gaps).
7. **Known draws (P49):** every enriched draw in the bindings' numbering, failed ones included;
   a pool section whose reply produced no draw gets its Phase 3 table count (`known_draws`).

Draws are keyed by document and target (`checks._draw_key`). The agreement pairs are
`(section, Phase 3 draw, bindings' draw)` of the draws still `analysed`.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass

from adr_store.bindings import checks
from adr_store.bindings.dsl import Binding
from adr_store.bindings.enrich import section_key
from adr_store.bindings.manifest import INSTALL_ANALYSIS, BindingsError, by_draw

__all__ = ["Candidates", "analysis_module", "build_candidates"]


@dataclass(frozen=True)
class Candidates:
    bindings: list[Binding]
    tables_id: str
    enrichment_id: str
    agreement_pairs: list[tuple[str, int, int]]
    served_models: list[str]
    report: dict
    known_draws: list[tuple[str, str, int]] = ()


def known_draws(items, fallback: dict[str, int], doc_id: str | None
                ) -> list[tuple[str, str, int]]:
    """The known-draws census (P49): `[doc_id, section, draw]` of every enriched draw in the
    bindings' own numbering (`DrawParams.draw`, failed draws included), and for each section
    of `fallback` with no enriched draw, draws 1..n of its count in `doc_id`."""
    out = {(i.doc_id, i.section, d.draw) for i in items for d in i.draws}
    with_draws = {i.section for i in items if i.draws}
    if doc_id is not None:
        out |= {(doc_id, s, n) for s, count in fallback.items() if s not in with_draws
                for n in range(1, count + 1)}
    return sorted(out, key=lambda k: (k[0], section_key(k[1]), k[2]))


def pool_draw_counts(store, tables_id: str) -> dict[str, int]:
    """The Phase 3 `drawbridge_bridges` row count of each pool section (`enrich.pools`) in
    the newest 33 CFR 117 version: the fallback of `known_draws`."""
    from adr_store.bindings import enrich
    from adr_store.tables.overlay import load_manifest, load_rows

    doc = enrich.newest_doc(store)
    p = enrich.pools(store, tables_id)
    pool = set(p["closed_window"]) | set(p["notice"])
    counts: dict[str, int] = {}
    for r in load_rows(store.path, load_manifest(store.path, tables_id), "drawbridge_bridges"):
        if r.doc_id == doc and r.row["section"] in pool:
            counts[r.row["section"]] = counts.get(r.row["section"], 0) + 1
    return counts


def analysis_module():
    """The Z3 analysis (`adr_store.bindings.analysis`); BindingsError naming the `[analysis]`
    extra when z3 is not installed."""
    try:
        return importlib.import_module("adr_store.bindings.analysis")
    except ImportError as e:
        raise BindingsError(INSTALL_ANALYSIS) from e


def _period_specific(d) -> bool:
    """A draw whose parameters a sentence limits beyond what they state (P46, Task 15 flags)."""
    return bool(d.sentence_qualifiers) or any(p.sentence_qualifiers or p.sentence_conditions
                                              for p in d.periods)


def _b2(bindings: list[Binding]) -> dict:
    draws = [bs for bs in by_draw(bindings).values() if all(b.analysis for b in bs)]
    return {"draws_analysed": len(draws),
            "conflicts": sum(len(bs[0].analysis.get("conflicts", [])) for bs in draws),
            "vacuous": sum(bool(b.analysis.get("vacuous")) for bs in draws for b in bs),
            "redundant": sum(bool(b.analysis.get("redundant")) for bs in draws for b in bs),
            "draws_with_gaps": sum(bool(bs[0].analysis.get("gaps")) for bs in draws)}


def _selector(bs: list[Binding]) -> tuple[str, int]:
    sel = bs[0].target.get("selector", {})
    return sel.get("section"), sel.get("draw")


def build_candidates(store, client, *, units_id: str, facts_id: str) -> Candidates:
    """The candidate bindings of `store` (module text). Raises BindingsError without z3
    (before any work), and what the enrichment raises at the cap."""
    from adr_store.bindings import enrich, reference
    from adr_store.bindings.compile import compile_bindings
    from adr_store.tables import extract as ex
    from adr_store.units import overlay as units_overlay

    analysis = analysis_module()
    units = units_overlay.load_units_manifest(store.path, units_id)
    cards = units_overlay.load_units(store.path, units, "rule_card")
    facts = ex.load_facts(store.path, facts_id)
    items, enrich_report = enrich.enrich_all(store, client)
    enrichment_id, _ = enrich.write_enrichment(store.path, store.snapshot_id, items)
    compiled, compile_report = compile_bindings(items, cards)
    tested = checks.mark_tested(compiled)
    tested_draws = by_draw(tested)
    out: list[Binding] = []
    for bs in tested_draws.values():
        if all(b.status == "tested" for b in bs):
            out += analysis.mark_analysed(bs, analysis.analyse_draw(bs))
        else:
            out += bs
    # B1: the agreement set (C5) and the grid on each of its draws. The reference functions
    # key draws by (section, draw); every enrichment item is of one document (the newest).
    refs = {}
    for doc in sorted({i.doc_id for i in items}):
        refs.update(reference.ref_draws(facts, ex.units(store), doc_id=doc))
    analysed: dict[tuple[str, int], list[Binding]] = {}
    for bs in by_draw(out).values():
        key = _selector(bs)
        if key in analysed:
            raise ValueError(f"§ {key[0]} draw {key[1]} has bindings of two documents")
        analysed[key] = [b for b in bs if b.status == "analysed"]
    agree = reference.agreement_set(analysed, items, refs)
    params = {(i.section, d.draw): d for i in items for d in i.draws}
    agree = [k for k in agree if not _period_specific(params[k])]
    pairs = reference.paired_refs(items, refs)
    grid_ok, grid_bad = [], []
    stamped: dict[str, Binding] = {}
    for key in agree:
        ref = refs[pairs[key]]
        mismatches = checks.grid_equivalence(analysed[key], ref)
        summary = {"kind": "grid", "phase3_draw": pairs[key][1],
                   "points": checks.grid_size(ref), "mismatches": len(mismatches),
                   "first": mismatches[:3]}
        (grid_bad if mismatches else grid_ok).append(key)
        for b in analysed[key]:
            update = {"tests": [*b.tests, summary]}
            if mismatches:
                update["status"] = "rejected"
            stamped[b.binding_id] = checks._with(b, **update)
    out = [stamped.get(b.binding_id, b) for b in out]
    agreement_pairs = [(s, pairs[(s, d)][1], d) for s, d in grid_ok]
    passed = sum(b.status == "tested" for b in tested)
    report = {
        "units_id": units_id, "facts_id": facts_id, "enrichment_id": enrichment_id,
        "tables_id": enrich_report["tables_id"], "calls": enrich_report["calls"],
        "served_models": enrich_report["served_models"], "compile": compile_report,
        "statuses": {k: sum(b.status == k for b in out) for k in ("analysed", "rejected")},
        "b1": {"bindings": len(tested), "bindings_passed": passed,
               "bindings_rejected": len(tested) - passed, "draws": len(tested_draws),
               "draws_rejected_by_tests": sum(any(b.status == "rejected" for b in bs)
                                              for bs in tested_draws.values()),
               "agreement_draws": len(agree), "grid_equal": len(grid_ok),
               "grid_mismatch": [list(k) for k in grid_bad]},
        "b2": _b2(out)}
    known = known_draws(items, pool_draw_counts(store, enrich_report["tables_id"]),
                        enrich.newest_doc(store))
    report["known_draws"] = len(known)
    return Candidates(out, enrich_report["tables_id"], enrichment_id, agreement_pairs,
                      enrich_report["served_models"], report, known)
