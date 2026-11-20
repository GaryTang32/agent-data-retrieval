"""Build the typed tables of one store snapshot (Phase 3 spec §5.2, §5.4, §6).

`build_tables` builds every contract of a corpus whose loader is `metadata` (the 3A loaders of
`loaders.py`, no model call) and every entity table (`entities.py`, built from the loaded rows
and, for waterways, from the eCFR section headings of 33 CFR 117: structure, no model), and with
`with_extraction` the extraction (3B) tables of `extract.py` (33 CFR 117 drawbridges, through
the reply cache under a per-attempt call cap, default 0: a zero-call rebuild); it writes each
table file and the build manifest, and returns the tables id. It never moves
`tables/HEAD`: a build is a candidate until the merge gate adopts it. The applicability
overlay it read (gov only) is recorded in the manifest by id.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from adr_store import applicability as ap
from adr_store.store import Store
from adr_store.tables import extract as ex
from adr_store.tables.contracts import CONTRACT_DIR, EXTRACTION_CONFIG, load_contracts
from adr_store.tables.ecfr import chain_docs, ecfr_sections, heading_waterway_text
from adr_store.tables.entities import entity_report, entity_rows, overrides_for
from adr_store.tables.loaders import fr_tables, papers_tables
from adr_store.tables.overlay import (
    FORMAT_VERSION,
    Manifest,
    TableFile,
    write_manifest,
    write_table,
)
from adr_store.tables.provenance import RowRecord

# entity type -> the (source table, column) pairs its raw forms are read from
ENTITY_SOURCES: dict[str, list[tuple[str, str]]] = {
    "agencies": [("fr_agencies", "name")],
    "cfr_parts": [("fr_cfr_refs", "cfr_part")],
    "dockets": [("fr_dockets", "docket")],
    "waterways": [("fr_documents", "title_waterway_keys")],
    "venues": [("papers", "venue")],
    "licences": [("papers", "license")],
    "authors": [("paper_authors", "raw")],
}
HEADINGS = "ecfr_headings"     # the waterway entity source that is no table: 33 CFR 117 headings


def _heading_sources(store: Store) -> list[tuple[str, str, RowRecord]]:
    """One source row per section heading of the 33 CFR 117 chain that sits in a state group,
    its raw form the waterway the heading names. General sections (no state: "Purpose.") and
    reserved or empty headings name no waterway and give no row (the link index skips the same
    sections). The rows carry no provenance: entity rows are computed, without spans."""
    out = []
    for doc_id in chain_docs(store):
        for unit in ecfr_sections(store, doc_id):
            text = heading_waterway_text(unit.heading)
            if unit.state is None or not text or text.strip("[]. ").casefold() == "reserved":
                continue
            out.append((HEADINGS, "heading", RowRecord(doc_id=doc_id, row={"heading": text},
                                                       prov={})))
    return out


@dataclass(frozen=True)
class BuildResult:
    tables_id: str
    manifest_path: Path
    tables: list[TableFile]
    reports: dict[str, dict]     # table -> its report (counts, rejected rows, null reasons)


def build_tables(store_path: Path, corpus: Literal["gov", "research"], *,
                 contracts_dir: Path = CONTRACT_DIR, with_extraction: bool = False,
                 client=None, generator_profile: str | None = None, max_calls: int = 0
                 ) -> BuildResult:
    """Build the tables of `corpus` for the HEAD snapshot of the store: the metadata and entity
    tables, and with `with_extraction` the extraction tables too.

    The extraction reads its replies through `client` (default: the model client of
    `generator_profile`, else the configured generator) metered by `ex.metered_client` with a
    budget of `max_calls` (default 0), every transport attempt counted, so a rebuild finds the
    cached replies under the same adapter and model key and calls nothing; a reply that is not
    cached stops the build (BudgetExceeded) when the cap is reached. The metadata loaders call
    no model whatever these are."""
    store = Store.open(store_path)
    snapshot = store.snapshot_id
    available = load_contracts(contracts_dir, corpus)
    loaders = ("metadata", "entities", "extraction") if with_extraction \
        else ("metadata", "entities")
    contracts = [c for c in available.values() if c.source.loader in loaders]
    overlay = ap.load_overlay(store_path, snapshot) if corpus == "gov" else None
    loaded = fr_tables(store, overlay) if corpus == "gov" else papers_tables(store)
    extraction = None
    if any(c.source.loader == "extraction" for c in contracts):
        rows, extraction = _extraction(store, available, contracts_dir, client,
                                       generator_profile, max_calls)
        loaded = {**loaded, **rows}
    tables: list[TableFile] = []
    reports: dict[str, dict] = {}
    for c in contracts:
        reports[c.table] = {}
        if c.source.loader == "entities":
            rows = _entity_table(store, c.table, loaded, corpus, reports[c.table])
        elif c.table in loaded:
            rows = loaded[c.table]
        else:
            raise ValueError(f"{c.table}: no loader builds this table")
        tables.append(write_table(store_path, snapshot, c, rows, reports[c.table]))
    manifest = Manifest(format_version=FORMAT_VERSION, snapshot=snapshot, corpus=corpus,
                        applicability=None if overlay is None else overlay.overlay_id,
                        extraction=extraction, tables=sorted(tables, key=lambda t: t.table))
    tables_id, path = write_manifest(store_path, manifest)
    return BuildResult(tables_id, path, manifest.tables, reports)


def _extraction(store: Store, contracts: dict, contracts_dir: Path, client,
                generator_profile: str | None, max_calls: int) -> tuple[dict, dict]:
    """(the extraction tables' rows, what they came from for the manifest: prompt version,
    adapter, model, max tokens, groups and specs, nothing that differs between rebuilds)."""
    cfg = ex.load_config(Path(contracts_dir) / EXTRACTION_CONFIG)
    meter = ex.metered_client(max_calls, client=client, profile=generator_profile)
    results, _ = ex.extract_all(store, meter, cfg, contracts)
    rows = ex.drawbridge_rows(results, ex.units(store), cfg.specs)
    return rows, {"prompt_version": ex.PROMPT_VERSION, "adapter": meter.name,
                  "model": meter.model, "max_tokens": ex.MAX_TOKENS, "groups": cfg.groups,
                  "specs": cfg.specs}


def _entity_table(store: Store, etype: str, loaded: dict[str, list[RowRecord]], corpus: str,
                  report: dict) -> list[RowRecord]:
    """The rows of the entity table `etype`; `report["entities"]` gets its resolution report."""
    if etype not in ENTITY_SOURCES:
        raise ValueError(f"{etype}: no entity sources are defined for this table")
    sources = [(table, column, rec) for table, column in ENTITY_SOURCES[etype]
               for rec in loaded.get(table, [])]
    if etype == "waterways" and corpus == "gov":
        sources += _heading_sources(store)
    overrides = overrides_for(etype, None)
    rows = entity_rows(etype, sources, overrides)
    report["entities"] = entity_report(etype, rows, overrides)
    return rows
