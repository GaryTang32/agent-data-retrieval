"""The tool catalog: tool records in a store, with their own snapshots (Phase 2 spec §8.1).

    <store>/tools/records/<tool_id[:2]>/<tool_id>.json   canonical JSON of a ToolRecord
    <store>/tools/snapshots/<tool_snapshot_id>.json      sorted tool ids with record hashes
    <store>/tools/HEAD                                   the current tool snapshot id

The catalog is versioned apart from the content snapshot, so tools can change without a new
content snapshot. A snapshot file is the canonical JSON of a `ToolSnapshot` (sorted keys,
compact, UTF-8, one trailing newline) and its id is the SHA-256 of the file, so the same set
of records gives the same id whatever the order they were added in. Every file is written
once (temporary file, then rename); an existing file under the same name with other bytes is
refused (`StoreError`). `add` refuses a record that fails `tool_records.conformance`
(`ToolConformanceError`) before writing anything.

`ingest` adds records and commits under an exclusive `flock` on `tools/ingest.lock` (as
`acl.sync` serializes on `acl/sync.lock`), from reading `tools/HEAD` to moving it, so two
concurrent ingests cannot drop each other's tools.

A tools-only store (`ensure_store`) is a store whose content snapshot is empty
(`Store.create(path).commit()`), so the ACL layer (`acl.sync`, F2) works on it unchanged.
"""

from __future__ import annotations

import fcntl
import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from adr_store.records import canonical_json
from adr_store.store import Store, StoreError, write_atomic
from adr_store.tool_records import ToolRecord, conformance

FORMAT_VERSION = "0.1"
_HEX64 = r"^[0-9a-f]{64}$"


class ToolEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, title="ToolEntry")

    tool_id: str = Field(pattern=_HEX64)
    record_sha256: str = Field(pattern=_HEX64)


class ToolSnapshot(BaseModel):
    """The content of `<store>/tools/snapshots/<id>.json`: tool ids in sorted order."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="ToolSnapshot")

    format_version: Literal["0.1"] = FORMAT_VERSION
    tools: list[ToolEntry]


class ToolConformanceError(StoreError):
    """A tool record breaks the structural conformance rules; nothing of it was written."""

    def __init__(self, rec: ToolRecord, problems: list[str]):
        super().__init__(f"tool {rec.name!r} ({rec.tool_id[:12]}) from {rec.source_uri}: "
                         f"{'; '.join(problems)}")
        self.record, self.problems = rec, problems


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_once(path: Path, data: bytes, what: str) -> None:
    """Write `data` unless the file exists; refuse if it exists with other bytes."""
    if path.exists():
        if path.read_bytes() != data:
            raise StoreError(f"{path} already holds a different {what} under the same id; "
                             f"it is not replaced")
        return
    write_atomic(path, data)


def tools_dir(store_path: Path) -> Path:
    return Path(store_path) / "tools"


def has_catalog(store_path: Path) -> bool:
    return (tools_dir(store_path) / "HEAD").is_file()


def ensure_store(store_path: Path) -> Path:
    """The store at `store_path`, made a tools-only store (an empty content snapshot) when it
    has no HEAD yet; an existing store is left as it is."""
    store_path = Path(store_path)
    if not (store_path / "HEAD").is_file():
        Store.create(store_path).commit()
    return store_path


class ToolCatalog:
    """One tool snapshot of a store: read its records, add more, commit a new snapshot."""

    def __init__(self, store_path: Path, snapshot_id: str | None, records: dict[str, str]):
        self.store_path = Path(store_path)
        self.snapshot_id = snapshot_id
        self._records = dict(records)  # tool_id -> SHA-256 of its record file

    @classmethod
    def create(cls, store_path: Path) -> ToolCatalog:
        """An empty catalog (nothing written until `add` or `commit`)."""
        return cls(store_path, None, {})

    @classmethod
    def open(cls, store_path: Path, snapshot: str | None = None) -> ToolCatalog:
        """The catalog at `tools/HEAD`, or the named tool snapshot (StoreError if there is
        none, or its file does not hash to its id)."""
        tdir = tools_dir(store_path)
        if snapshot is None:
            head = tdir / "HEAD"
            if not head.is_file():
                raise StoreError(f"{store_path}: no tool catalog here (no tools/HEAD); run "
                                 f"`adr tools ingest` first")
            snapshot = head.read_text(encoding="utf-8").strip()
        path = tdir / "snapshots" / f"{snapshot}.json"
        if not path.is_file():
            raise StoreError(f"{store_path}: tool snapshot {snapshot} not found")
        data = path.read_bytes()
        if _sha256(data) != snapshot:
            raise StoreError(f"{path}: content does not hash to its tool snapshot id")
        body = ToolSnapshot.model_validate_json(data)
        return cls(store_path, snapshot, {e.tool_id: e.record_sha256 for e in body.tools})

    def _path(self, tool_id: str) -> Path:
        return tools_dir(self.store_path) / "records" / tool_id[:2] / f"{tool_id}.json"

    def add(self, rec: ToolRecord) -> None:
        """Check and write one record; it joins the next snapshot."""
        problems = conformance(rec)
        if problems:
            raise ToolConformanceError(rec, problems)
        data = canonical_json(rec)
        _write_once(self._path(rec.tool_id), data, f"tool record for {rec.tool_id}")
        self._records[rec.tool_id] = _sha256(data)

    def snapshot_bytes(self) -> bytes:
        return canonical_json(ToolSnapshot(tools=[
            ToolEntry(tool_id=t, record_sha256=self._records[t]) for t in sorted(self._records)]))

    def commit(self) -> str:
        """Write the snapshot of the current records, move tools/HEAD to it, return its id."""
        data = self.snapshot_bytes()
        sid = _sha256(data)
        tdir = tools_dir(self.store_path)
        _write_once(tdir / "snapshots" / f"{sid}.json", data, f"tool snapshot {sid}")
        write_atomic(tdir / "HEAD", f"{sid}\n".encode())
        self.snapshot_id = sid
        return sid

    def ids(self) -> list[str]:
        return sorted(self._records)

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, tool_id: str) -> bool:
        return tool_id in self._records

    def get(self, tool_id: str) -> ToolRecord:
        """The record of a tool id (KeyError if not in this snapshot; StoreError if its file
        does not match the snapshot's record hash)."""
        if tool_id not in self._records:
            raise KeyError(f"{tool_id} is not in tool snapshot {self.snapshot_id}")
        path = self._path(tool_id)
        data = path.read_bytes()
        if _sha256(data) != self._records[tool_id]:
            raise StoreError(f"{path}: tool record does not match the snapshot's record hash")
        return ToolRecord.model_validate_json(data)


@contextmanager
def lock(store_path: Path) -> Iterator[None]:
    """An exclusive `flock` on `<store>/tools/ingest.lock` for the block."""
    tdir = tools_dir(store_path)
    tdir.mkdir(parents=True, exist_ok=True)
    with open(tdir / "ingest.lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def ingest(store_path: Path, records: list[ToolRecord]) -> tuple[str, int, int]:
    """Add `records` to the store's catalog (made a tools-only store if new) and commit, under
    the catalog lock; returns (tool snapshot id, tools before, tools after)."""
    ensure_store(store_path)
    with lock(store_path):
        cat = ToolCatalog.open(store_path) if has_catalog(store_path) \
            else ToolCatalog.create(store_path)
        before = len(cat)
        for rec in records:
            cat.add(rec)
        return cat.commit(), before, len(cat)
