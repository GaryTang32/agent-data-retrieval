"""Build the knowledge units of one store snapshot (Phase 4 spec §5.2, §6.1; preflight ruling
C9).

`build_units` builds every unit type of a corpus (`CORPUS_TYPES`), even a type with no unit,
by code from source structure, with no model call:
- gov: concepts (eCFR definitions, IRM acronyms), rule cards of the three eCFR parts in every
  version with their citation closure and their `defines` entries and `defined_terms` from the
  concepts (`closure.closure`, `concepts.link_concepts`), IRM procedure skeletons, and table
  records (the Federal Register and drawbridge tables of `tables/HEAD`, the eCFR and IRM
  in-document tables);
- research: concepts (long forms) and table records (the manifest tables of `tables/HEAD`,
  the markdown tables);
- bench: concepts, procedure skeletons, FAQ pairs and KCS articles, and the markdown tables.

Every type's units are version-linked (`envelope.link_versions`), every stored span is checked
to re-slice (a unit whose span does not is rejected and reported, §6.1), and each type is
written once (`overlay.write_units`) with a per-file report of deterministic values only (no
call counts, no times: the report is write-once). The build manifest records the tables id
and the applicability overlay id read; its SHA-256 is the units id. A build never moves
`units/HEAD`: it is a candidate until the units merge gate (`units/gate.py`) adopts it.

`passes` names the model passes whose replies fill model-written fields ("procedure",
"rules"). A model client is made only when a pass is asked for (`client`, default
`tables.extract.metered_client(0)`: cached replies only), so a metadata build never resolves
a model profile (preflight ruling C9). The procedure pass (`procedure_pass.apply`, its config
`passes.json` in `contracts_dir`) fills the four descriptive fields of every procedure unit
and its lineage before anything is written, so a budget stop or a model failure leaves no
file; the manifest records the pass (prompt version, adapter, model, max tokens, groups,
specs). The rules pass (`bindings.enrich.apply`, Task 15) fills `subject`, `conditions`,
`thresholds` and `exceptions` and the lineage of the newest 33 CFR 117 version's cards of the
binding sections (the pool drawn from `tables/HEAD`, which it needs), one cached call per
section, the same way; every other card keeps them null `not_extracted`. Its manifest record
adds the tables id and the number of sections.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from adr_store import applicability as ap
from adr_store.applicability import Applicability
from adr_store.bindings import enrich
from adr_store.store import Store
from adr_store.tables import extract as ex
from adr_store.units import procedure_pass
from adr_store.units.closure import closure, closure_census
from adr_store.units.concepts import concepts, link_concepts
from adr_store.units.contracts import UNIT_CONTRACT_DIR, load_unit_contracts
from adr_store.units.ecfr import ecfr_docs, rule_cards
from adr_store.units.envelope import Unit, link_versions
from adr_store.units.faq import KCS_FIELDS, faq_units, kcs_units
from adr_store.units.grounding import PASSES_CONFIG, load_pass_config
from adr_store.units.overlay import (
    FORMAT_VERSION,
    UNITS_DIR,
    UnitFile,
    UnitsManifest,
    load_units_manifest,
    write_units,
    write_units_manifest,
)
from adr_store.units.procedures import procedure_units
from adr_store.units.table_records import document_tables, phase3_records

CORPUS_TYPES: dict[str, tuple[str, ...]] = {
    "gov": ("concept", "procedure", "rule_card", "table_record"),
    "research": ("concept", "table_record"),
    "bench": ("concept", "faq", "procedure", "table_record"),
}
PASSES = ("procedure", "rules")     # the procedure pass (§6.2) and the rule enrichment


@dataclass(frozen=True)
class UnitsBuild:
    units_id: str
    manifest_path: Path
    files: list[UnitFile]
    reports: dict[str, dict]     # unit type -> its report (as written beside its file)


def _walk(value, path: str = ""):
    if isinstance(value, dict):
        yield path, value
        for k, v in value.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk(v, f"{path}[{i}]")


def span_problems(unit: Unit, text: str) -> list[str]:
    """Where a span stored in `unit` does not re-slice from its document's canonical text
    `text` (§6.1, criterion T3): every source ref inside the text; every body object with a
    `span` and a `text` (or a cross-reference `raw`) equal to that slice of the text; a span
    pointer inside the text; a rule card's verbatim text equal to its source span."""
    problems = []
    for r in unit.source_refs:
        if not 0 <= r.start <= r.end <= len(text):
            problems.append(f"source_refs: ({r.start}, {r.end}) is outside the document")
    if unit.type == "rule_card" and unit.source_refs:
        r = unit.source_refs[0]
        if text[r.start:r.end] != unit.body.get("text"):
            problems.append("body.text: span does not re-slice")
    for where, d in _walk(unit.body):
        span = d.get("span")
        if isinstance(span, list) and len(span) == 2 and all(isinstance(x, int) for x in span):
            said = d.get("text") if isinstance(d.get("text"), str) else d.get("raw")
            if not 0 <= span[0] <= span[1] <= len(text) or (
                    isinstance(said, str) and text[span[0]:span[1]] != said):
                problems.append(f"body{where}: span does not re-slice")
    p = unit.body.get("pointer")
    if isinstance(p, dict) and p.get("kind") == "span" and not (
            p.get("doc_id") == unit.doc_id
            and 0 <= (p.get("start") or 0) <= (p.get("end") or -1) <= len(text)):
        problems.append("body.pointer: span is outside the document")
    return problems


def _span_check(store: Store):
    texts: dict[str, str] = {}

    def check(unit: Unit) -> list[str]:
        if unit.doc_id not in texts:
            texts.clear()            # units arrive grouped by document: keep one text
            texts[unit.doc_id] = store.text(unit.doc_id)
        return span_problems(unit, texts[unit.doc_id])

    return check


def _concepts(store: Store, corpus: str, overlay: Applicability | None
              ) -> tuple[list[Unit], dict]:
    misses: list[dict] = []
    units = concepts(store, corpus, overlay, misses)
    misses.sort(key=lambda m: (m["doc_id"], m["where"], m["reason"], m["detail"]))
    return units, {"missed": misses,
                   "reasons": dict(sorted(Counter(m["reason"] for m in misses).items()))}


def _rule_cards(store: Store, overlay: Applicability | None, concept_units: list[Unit]
                ) -> tuple[list[Unit], dict]:
    cards, provs = [], []
    for d in ecfr_docs(store):
        c, p = rule_cards(store, d, overlay)
        cards += c
        provs += p
    closures = closure(cards, provs)
    cards, closures = link_concepts(cards, concept_units, closures)
    cards = [c.model_copy(update={"body": {**c.body, "closure": [
        e.model_dump(mode="json") for e in closures[c.unit_id]]}}) for c in cards]
    return cards, closure_census(cards, provs)


def _faq(store: Store, overlay: Applicability | None, corpus: str) -> tuple[list[Unit], dict]:
    pairs = faq_units(store, overlay, corpus)
    articles = kcs_units(store, overlay, corpus)
    return pairs + articles, {
        "faq_pairs": len(pairs), "faq_documents": len({u.doc_id for u in pairs}),
        "kcs_articles": len(articles),
        "kcs_absent": {f: sum(u.body[f] is None for u in articles) for f in KCS_FIELDS}}


def _table_records(store: Store, overlay: Applicability | None, corpus: str
                   ) -> tuple[list[Unit], dict]:
    report: dict = {}
    units = phase3_records(store.path, store, overlay, corpus, report=report)
    units += document_tables(store, overlay, corpus, report=report)
    return units, report


def build_units(store_path: Path, corpus: Literal["gov", "research", "bench"], *,
                contracts_dir: Path = UNIT_CONTRACT_DIR, passes: tuple[str, ...] = (),
                client=None) -> UnitsBuild:
    """Build every unit type of `corpus` for the HEAD snapshot of the store, write the unit
    files and the build manifest, and return the units id (module docstring)."""
    if corpus not in CORPUS_TYPES:
        raise ValueError(f"no units are built for corpus {corpus!r}; one of "
                         f"{', '.join(CORPUS_TYPES)}")
    for name in passes:
        if name not in PASSES:
            raise ValueError(f"unknown model pass {name!r}; one of {', '.join(PASSES)}")
    if "procedure" in passes and "procedure" not in CORPUS_TYPES[corpus]:
        raise ValueError(f"the procedure pass fills procedure units; corpus {corpus!r} has "
                         f"none")
    if "rules" in passes and "rule_card" not in CORPUS_TYPES[corpus]:
        raise ValueError(f"the rules pass fills rule cards; corpus {corpus!r} has none")
    if passes and client is None:   # made only now: a metadata build resolves no model profile
        client = ex.metered_client(0)
    store = Store.open(store_path)
    snapshot = store.snapshot_id
    overlay = ap.load_overlay(store_path, snapshot)
    contracts = load_unit_contracts(contracts_dir)
    types = CORPUS_TYPES[corpus]
    built: dict[str, tuple[list[Unit], dict]] = {"concept": _concepts(store, corpus, overlay)}
    pass_info: dict[str, dict] = {}
    if "rule_card" in types:
        cards, report = _rule_cards(store, overlay, built["concept"][0])
        if "rules" in passes:
            cfg = load_pass_config("rules", Path(contracts_dir) / PASSES_CONFIG)
            cards, pass_info["rules"] = enrich.apply(store, cards, client, cfg)
        built["rule_card"] = (cards, report)
    if "procedure" in types:
        units, report = procedure_units(store, corpus, overlay)
        if "procedure" in passes:
            cfg = load_pass_config("procedure", Path(contracts_dir) / PASSES_CONFIG)
            units, report, pass_info["procedure"] = procedure_pass.apply(
                store, units, report, client, cfg)
        built["procedure"] = (units, report)
    if "faq" in types:
        built["faq"] = _faq(store, overlay, corpus)
    built["table_record"] = _table_records(store, overlay, corpus)
    check = _span_check(store)
    files: list[UnitFile] = []
    reports: dict[str, dict] = {}
    for t in types:
        units, report = built[t]
        units = sorted(link_versions(units, overlay), key=lambda u: (u.doc_id, u.unit_id))
        files.append(write_units(store_path, snapshot, contracts[t], units, report, check))
        reports[t] = report
    manifest = UnitsManifest(
        format_version=FORMAT_VERSION, snapshot=snapshot, corpus=corpus,
        tables_id=built["table_record"][1].get("tables_id"),
        applicability=None if overlay is None else overlay.overlay_id, passes=pass_info,
        units=sorted(files, key=lambda f: f.type))
    units_id, path = write_units_manifest(store_path, manifest)
    return UnitsBuild(units_id, path, manifest.units, reports)


def unit_reports(store_path: Path, units_id: str) -> dict[str, dict]:
    """The per-file report of every unit type of the build `units_id` (type -> report)."""
    m = load_units_manifest(store_path, units_id)
    directory = Path(store_path) / UNITS_DIR / m.snapshot
    return {f.type: json.loads((directory / f.file).with_suffix(".report.json").read_text(
        encoding="utf-8")) for f in m.units}
