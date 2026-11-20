"""Build the typed tables of one store snapshot (Phase 3 spec §5.2, §5.4, §6).

`build_tables` builds every contract of a corpus whose loader is `metadata` (the 3A loaders of
`loaders.py`, no model call) and every entity table (`entities.py`, built from the loaded rows
and, for waterways, from the eCFR section headings of 33 CFR 117: structure, no model), writes
each table file and the build manifest, and returns the tables id. It never moves
`tables/HEAD`: a build is a candidate until the merge gate adopts it. The applicability
overlay it read (gov only) is recorded in the manifest by id.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from adr_store import applicability as ap
from adr_store.store import Store
from adr_store.tables.contracts import CONTRACT_DIR, load_contracts
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
from adr_store.tables.provenance import RowRecord, value_prov

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
    """One source row per section heading of the 33 CFR 117 chain, its raw form the waterway
    the heading names."""
    out = []
    for doc_id in chain_docs(store):
        for unit in ecfr_sections(store, doc_id):
            text = heading_waterway_text(unit.heading)
            out.append((HEADINGS, "heading", RowRecord(
                doc_id=doc_id, row={"heading": text},
                prov={"heading": value_prov(doc_id, "ecfr.heading@1", unit.heading_span)})))
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
    """Build the metadata tables of `corpus` for the HEAD snapshot of the store.

    `generator_profile` and `max_calls` (default 0) name the model profile and call cap that a
    later extraction build runs under, so zero-call rebuilds find the cached replies under the
    same adapter and model key; `client` is the model client of that build. The metadata
    loaders call no model whatever these are. `with_extraction` (the 3B tables) is not built
    yet."""
    if with_extraction:
        raise NotImplementedError("extraction tables are not built yet (Phase 3 task 9)")
    store = Store.open(store_path)
    snapshot = store.snapshot_id
    contracts = [c for c in load_contracts(contracts_dir, corpus).values()
                 if c.source.loader in ("metadata", "entities")]
    overlay = ap.load_overlay(store_path, snapshot) if corpus == "gov" else None
    loaded = fr_tables(store, overlay) if corpus == "gov" else papers_tables(store)
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
                        extraction=None, tables=sorted(tables, key=lambda t: t.table))
    tables_id, path = write_manifest(store_path, manifest)
    return BuildResult(tables_id, path, manifest.tables, reports)


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
