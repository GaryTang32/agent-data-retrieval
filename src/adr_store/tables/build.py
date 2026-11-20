"""Build the typed tables of one store snapshot (Phase 3 spec §5.2, §5.4).

`build_tables` builds every contract of a corpus whose loader is `metadata` (the 3A loaders of
`loaders.py`, no model call), writes each table file and the build manifest, and returns the
tables id. It never moves `tables/HEAD`: a build is a candidate until the merge gate adopts it.
The applicability overlay it read (gov only) is recorded in the manifest by id.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from adr_store import applicability as ap
from adr_store.store import Store
from adr_store.tables.contracts import CONTRACT_DIR, load_contracts
from adr_store.tables.loaders import fr_tables, papers_tables
from adr_store.tables.overlay import Manifest, TableFile, write_manifest, write_table


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
                 if c.source.loader == "metadata"]
    overlay = ap.load_overlay(store_path, snapshot) if corpus == "gov" else None
    loaded = fr_tables(store, overlay) if corpus == "gov" else papers_tables(store)
    tables: list[TableFile] = []
    reports: dict[str, dict] = {}
    for c in contracts:
        if c.table not in loaded:
            raise ValueError(f"{c.table}: no loader builds this table")
        reports[c.table] = {}
        tables.append(write_table(store_path, snapshot, c, loaded[c.table], reports[c.table]))
    manifest = Manifest(format_version="0.1", snapshot=snapshot, corpus=corpus,
                        applicability=None if overlay is None else overlay.overlay_id,
                        extraction=None, tables=sorted(tables, key=lambda t: t.table))
    tables_id, path = write_manifest(store_path, manifest)
    return BuildResult(tables_id, path, manifest.tables, reports)
