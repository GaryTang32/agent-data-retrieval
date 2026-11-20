"""The table overlay: typed tables of one store snapshot, write-once, and the build manifest
that names a build (Phase 3 spec §5.2).

    <store>/tables/<snapshot>/<table>-v<version>-<id[:16]>.jsonl          one table (rows sorted
                                                                          by the contract's order)
    <store>/tables/<snapshot>/<table>-v<version>-<id[:16]>.report.json    counts, rejections with
                                                                          reasons, null reasons
    <store>/tables/<snapshot>/tables-<id[:16]>.json                       the build manifest
    <store>/tables/HEAD                                                   the current tables id

A table file holds one canonical JSON `RowRecord` per line; its id is the SHA-256 of the file,
and the id is in the name, so a candidate build, the current build and a re-extraction after a
spec change coexist; an existing file with other bytes is refused, never replaced. The `.report`
file is not hashed. The manifest lists every table file of a build (entity tables included);
its SHA-256 is the **tables id** handles carry. `HEAD` names the current manifest and moves only
through the merge gate (`gate.py` calls `_set_head`). `read_head` returns the tables id only
when that manifest loads, every table file included, as the manifest says.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from adr_store.records import _HEX64, canonical_json
from adr_store.store import StoreError, write_atomic
from adr_store.tables.contracts import Contract, contract_sha256, validate_row
from adr_store.tables.provenance import RowRecord, sort_key

TABLES_DIR = "tables"
FORMAT_VERSION = "0.1"
_NAME = re.compile(r"^([a-z][a-z0-9_]*)-v(\d+)-([0-9a-f]{16})\.jsonl$")


class TablesError(StoreError):
    """A table file or manifest is missing, altered or would have to be overwritten."""


class TableFile(BaseModel):
    """One table of a build: which contract it was made under and its file."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="TableFile")

    table: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    kind: str
    contract_version: int = Field(ge=1)
    contract_sha256: str = Field(pattern=_HEX64)
    file: str
    sha256: str = Field(pattern=_HEX64)
    rows: int = Field(ge=0)
    rejected: int = Field(ge=0)

    @model_validator(mode="after")
    def _named_by_its_id(self) -> TableFile:
        want = f"{self.table}-v{self.contract_version}-{self.sha256[:16]}.jsonl"
        if self.file != want:
            raise ValueError(f"file {self.file!r} is not {want!r}")
        return self


class Manifest(BaseModel):
    """The content of `tables-<id[:16]>.json`: every table file of one build."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="TablesManifest")

    format_version: Literal["0.1"]
    snapshot: str = Field(min_length=1)
    corpus: str
    applicability: str | None  # the applicability overlay id the build used
    extraction: dict | None  # what the extraction tables came from (3B)
    tables: list[TableFile]  # sorted by table

    @model_validator(mode="after")
    def _sorted(self) -> Manifest:
        names = [t.table for t in self.tables]
        if names != sorted(set(names)):
            raise ValueError("tables must be sorted by table name and distinct")
        return self


def _dir(store_path: Path, snapshot: str) -> Path:
    if not snapshot or Path(snapshot).name != snapshot or snapshot in (".", ".."):
        raise TablesError(f"not a snapshot name: {snapshot!r}")
    return Path(store_path) / TABLES_DIR / snapshot


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_once(path: Path, data: bytes, what: str) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise TablesError(f"{path} already holds a different {what} under the same name; "
                              f"it is not replaced")
    else:
        write_atomic(path, data)


# -- tables ------------------------------------------------------------------------------------

def _null_reasons(rows: list[RowRecord]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for rec in rows:
        for column, prov in sorted(rec.prov.items()):
            for p in prov if isinstance(prov, list) else [prov]:
                if p.null_reason is not None:
                    by = out.setdefault(column, {})
                    by[p.null_reason] = by.get(p.null_reason, 0) + 1
    return {c: dict(sorted(by.items())) for c, by in sorted(out.items())}


def write_table(store_path: Path, snapshot: str, c: Contract, rows: list[RowRecord],
                report: dict) -> TableFile:
    """Validate `rows` against `c`, write the valid ones once (sorted by `c.order`, ties by
    their stored line) and a `.report.json` beside them. A row that fails validation, or
    repeats the key of an earlier one, is rejected and counted, not stored. `report` is filled
    in place (and written): `table`, `contract_version`, `contract_sha256`, `sha256`, `rows`,
    `rejected` (one entry per rejected row: `doc_id`, `key`, `problems`) and `null_reasons`
    (column -> reason -> count, over the stored rows). An existing table file of this id is
    left as it is when its bytes are the same and refused (TablesError) when they are not."""
    directory = _dir(store_path, snapshot)
    rejected: list[dict] = []
    valid: list[tuple[tuple, bytes, RowRecord]] = []
    for rec in rows:
        if problems := validate_row(c, rec):
            rejected.append({"doc_id": rec.doc_id, "key": {k: rec.row.get(k) for k in c.key},
                             "problems": problems})
        else:
            valid.append((sort_key(c, rec.row), canonical_json(rec), rec))
    valid.sort(key=lambda t: (t[0], t[1]))
    stored: list[tuple[bytes, RowRecord]] = []
    seen: set[tuple] = set()
    for _, line, rec in valid:
        key = tuple(json.dumps(rec.row[k], sort_keys=True) for k in c.key)
        if key in seen:
            rejected.append({"doc_id": rec.doc_id, "key": {k: rec.row[k] for k in c.key},
                             "problems": ["duplicate key"]})
            continue
        seen.add(key)
        stored.append((line, rec))
    rejected.sort(key=lambda r: (json.dumps(r["key"], sort_keys=True), r["doc_id"],
                                 r["problems"]))
    data = b"".join(line for line, _ in stored)
    table_id = _sha256(data)
    tf = TableFile(table=c.table, kind=c.kind, contract_version=c.version,
                   contract_sha256=contract_sha256(c),
                   file=f"{c.table}-v{c.version}-{table_id[:16]}.jsonl", sha256=table_id,
                   rows=len(stored), rejected=len(rejected))
    path = directory / tf.file
    _write_once(path, data, "table")
    report.update({"table": c.table, "contract_version": c.version,
                   "contract_sha256": tf.contract_sha256, "sha256": table_id,
                   "rows": len(stored), "rejected": rejected,
                   "null_reasons": _null_reasons([rec for _, rec in stored])})
    write_atomic(path.with_suffix(".report.json"),
                 (json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
                  + "\n").encode("utf-8"))
    return tf


# -- manifests ---------------------------------------------------------------------------------

def write_manifest(store_path: Path, m: Manifest) -> tuple[str, Path]:
    """Write the manifest once; returns (tables id, path). The same bytes again are a no-op,
    other bytes under the same name are refused."""
    data = canonical_json(m)
    tables_id = _sha256(data)
    path = _dir(store_path, m.snapshot) / f"tables-{tables_id[:16]}.json"
    _write_once(path, data, "manifest")
    return tables_id, path


def _manifest_files(store_path: Path, tables_id: str) -> list[Path]:
    if not re.fullmatch(_HEX64, tables_id):
        return []
    return sorted((Path(store_path) / TABLES_DIR).glob(f"*/tables-{tables_id[:16]}.json"))


def manifest_path(store_path: Path, tables_id: str) -> Path | None:
    """The manifest file whose SHA-256 is `tables_id`, or None (no such file, or a file of that
    name whose hash is another)."""
    for path in _manifest_files(store_path, tables_id):
        if path.is_file() and _sha256(path.read_bytes()) == tables_id:
            return path
    return None


def _read_table(store_path: Path, snapshot: str, t: TableFile) -> bytes:
    path = _dir(store_path, snapshot) / t.file
    try:
        data = path.read_bytes()
    except OSError as e:
        raise TablesError(f"table {t.table}: {path} is missing or unreadable") from e
    if _sha256(data) != t.sha256:
        raise TablesError(f"table {t.table}: {path} has hash {_sha256(data)[:12]}, the "
                          f"manifest says {t.sha256[:12]}")
    if data.count(b"\n") != t.rows or (data and not data.endswith(b"\n")):
        raise TablesError(f"table {t.table}: {path} does not hold {t.rows} rows")
    return data


def load_manifest(store_path: Path, tables_id: str) -> Manifest:
    """The manifest `tables_id`, checked: its hash is the id, it is canonical and sits under
    its snapshot, and every table file it lists is there with its hash and row count. Refuses
    (TablesError) otherwise, naming the table that fails."""
    path = manifest_path(store_path, tables_id)
    if path is None:
        found = _manifest_files(store_path, tables_id)
        if found:
            raise TablesError(f"{found[0]}: content hash is not the tables id "
                              f"{tables_id[:12]}")
        raise TablesError(f"no tables manifest {tables_id[:12]} under {store_path}/"
                          f"{TABLES_DIR}")
    data = path.read_bytes()
    try:
        m = Manifest.model_validate_json(data)
    except ValidationError as e:
        raise TablesError(f"{path}: not a valid tables manifest: {e.errors()[0]['msg']}") from e
    if canonical_json(m) != data:
        raise TablesError(f"{path}: not canonical JSON")
    if path.parent.name != m.snapshot:
        raise TablesError(f"{path}: describes snapshot {m.snapshot[:12]}, not "
                          f"{path.parent.name[:12]}")
    for t in m.tables:
        _read_table(store_path, m.snapshot, t)
    return m


def load_rows(store_path: Path, m: Manifest, table: str) -> list[RowRecord]:
    """The rows of `table` in a manifest, in stored order; the file is checked against the
    manifest's hash first."""
    t = next((t for t in m.tables if t.table == table), None)
    if t is None:
        raise TablesError(f"the build has no table {table!r}")
    data = _read_table(store_path, m.snapshot, t)
    return [RowRecord.model_validate_json(line) for line in data.splitlines()]


# -- HEAD --------------------------------------------------------------------------------------

def read_head(store_path: Path) -> str | None:
    """The tables id in `<store>/tables/HEAD` when it names a manifest that loads (every table
    file as listed), else None."""
    try:
        tables_id = (Path(store_path) / TABLES_DIR / "HEAD").read_text(
            encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    try:
        load_manifest(store_path, tables_id)
    except (TablesError, OSError):
        return None
    return tables_id


def _set_head(store_path: Path, tables_id: str) -> None:
    """Move HEAD to a manifest that loads. Only the merge gate (`gate.py`) calls this."""
    load_manifest(store_path, tables_id)
    write_atomic(Path(store_path) / TABLES_DIR / "HEAD", f"{tables_id}\n".encode())
