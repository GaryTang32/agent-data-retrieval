"""The content-addressed evidence store on disk, with immutable snapshots (spec §5).

    <store>/blobs/<doc_id[:2]>/<doc_id>            raw bytes, never rewritten
    <store>/text/<doc_id[:2]>/<doc_id>.txt         canonical text (UTF-8)
    <store>/docs/<doc_id[:2]>/<doc_id>.json        source record + element records
    <store>/snapshots/<snapshot_id>.json           sorted doc_ids with record hashes, versions
    <store>/HEAD                                   the current snapshot id

A snapshot file holds its canonical JSON, so its id is the SHA-256 of the file. Every file is
written once, atomically (temporary file, then rename); a file that already exists under the
same id is left untouched, and one with different content is refused rather than replaced.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from adr_eval.corpora.base import Document
from adr_eval.corpora.extract import EXTRACTOR_VERSION
from adr_store import conformance
from adr_store.records import (
    FORMAT_VERSION,
    DocRecord,
    Element,
    SourceRecord,
    canonical_json,
    sha256_text,
)
from adr_store.structure import PARSER, parse_document

EXTRACTOR = f"adr_eval.extract/{EXTRACTOR_VERSION}"
_RECORD_CACHE = 64  # parsed doc records kept in memory per open store


class StoreError(Exception):
    """The store on disk is missing, inconsistent, or would have to be overwritten."""


class ConformanceError(StoreError):
    """A document's records break the conformance rules; nothing of it was written."""

    def __init__(self, doc_id: str, problems: list[str]):
        super().__init__(f"{doc_id}: {len(problems)} conformance problem(s): {problems[0]}")
        self.doc_id, self.problems = doc_id, problems


@dataclass(frozen=True)
class Added:
    """What `Store.add` stored for one document, with the parser's heading counts."""

    doc_id: str
    format: str
    elements: list[Element]
    headings_found: int
    headings_aligned: int


def source_record(document: Document, raw: bytes, license: str | None) -> SourceRecord:
    """The source record of spec §4.1 for a document and its raw bytes."""
    return SourceRecord(
        doc_id=document.doc_id, uri=document.uri, format=document.format,
        source_version=document.source_version, byte_length=len(raw),
        text_sha256=sha256_text(document.text), text_length=len(document.text),
        extractor=EXTRACTOR, parser=PARSER, license=license)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _write_once(path: Path, data: bytes) -> None:
    """Write `data` unless the file exists; refuse if it exists with other content."""
    if path.exists():
        if path.read_bytes() != data:
            raise StoreError(f"{path} already holds a different file under the same id (another "
                             f"parser or extractor version, or the same bytes with another uri, "
                             f"version or licence); use a new store")
        return
    write_atomic(path, data)


class Store:
    """One snapshot of a store: read its documents, add more, commit a new snapshot.

    `Store.create(path)` starts an empty snapshot (creating the directory if needed);
    `Store.open(path, snapshot=None)` reads HEAD or the named snapshot. `add` writes a
    document's files at once; `commit` writes the snapshot of everything added or opened
    and moves HEAD to it.
    """

    def __init__(self, path: Path, snapshot_id: str | None, records: dict[str, str]):
        self.path = Path(path)
        self.snapshot_id = snapshot_id
        self._records = dict(records)  # doc_id -> SHA-256 of its doc record file
        self._cache: OrderedDict[str, DocRecord] = OrderedDict()

    @classmethod
    def create(cls, path: Path) -> Store:
        path = Path(path)
        for sub in ("blobs", "text", "docs", "snapshots"):
            (path / sub).mkdir(parents=True, exist_ok=True)
        return cls(path, None, {})

    @classmethod
    def open(cls, path: Path, snapshot: str | None = None) -> Store:
        path = Path(path)
        head = path / "HEAD"
        if snapshot is None:
            if not head.is_file():
                raise StoreError(f"{path}: no store here (no HEAD); run `adr ingest` first")
            snapshot = head.read_text(encoding="utf-8").strip()
        snap_path = path / "snapshots" / f"{snapshot}.json"
        if not snap_path.is_file():
            raise StoreError(f"{path}: snapshot {snapshot} not found")
        data = snap_path.read_bytes()
        if _sha256(data) != snapshot:
            raise StoreError(f"{snap_path}: content does not hash to its snapshot id")
        body = json.loads(data)
        records = {d["doc_id"]: d["record_sha256"] for d in body["documents"]}
        return cls(path, snapshot, records)

    def _paths(self, doc_id: str) -> tuple[Path, Path, Path]:
        d = doc_id[:2]
        return (self.path / "blobs" / d / doc_id, self.path / "text" / d / f"{doc_id}.txt",
                self.path / "docs" / d / f"{doc_id}.json")

    def add(self, document: Document, raw: bytes, license: str | None = None) -> Added:
        """Parse, check and store one document; it joins the next snapshot."""
        if _sha256(raw) != document.doc_id:
            raise ValueError(f"{document.uri}: raw bytes do not hash to doc_id {document.doc_id}"
                             f" (doc_id must be their SHA-256)")
        parsed = parse_document(document.format, raw, document.text, document.doc_id)
        source = source_record(document, raw, license)
        problems = conformance.check(source, parsed.elements, document.text, raw)
        if problems:
            raise ConformanceError(document.doc_id, problems)
        record = canonical_json(DocRecord(source=source, elements=parsed.elements))
        blob_path, text_path, doc_path = self._paths(document.doc_id)
        _write_once(blob_path, raw)
        _write_once(text_path, document.text.encode("utf-8"))
        _write_once(doc_path, record)
        self._records[document.doc_id] = _sha256(record)
        return Added(document.doc_id, document.format, parsed.elements,
                     parsed.headings_found, parsed.headings_aligned)

    def commit(self) -> str:
        """Write the snapshot of the current documents, move HEAD to it, return its id."""
        body = {
            "format_version": FORMAT_VERSION,
            "extractor": EXTRACTOR,
            "parser": PARSER,
            "documents": [{"doc_id": d, "record_sha256": self._records[d]}
                          for d in sorted(self._records)],
        }
        data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        snapshot_id = _sha256(data)
        _write_once(self.path / "snapshots" / f"{snapshot_id}.json", data)
        write_atomic(self.path / "HEAD", f"{snapshot_id}\n".encode())
        self.snapshot_id = snapshot_id
        return snapshot_id

    def doc_ids(self) -> list[str]:
        return sorted(self._records)

    def _record(self, doc_id: str) -> DocRecord:
        if doc_id not in self._records:
            raise KeyError(f"{doc_id} is not in snapshot {self.snapshot_id}")
        if doc_id in self._cache:
            self._cache.move_to_end(doc_id)
            return self._cache[doc_id]
        path = self._paths(doc_id)[2]
        data = path.read_bytes()
        if _sha256(data) != self._records[doc_id]:
            raise StoreError(f"{path}: doc record does not match the snapshot's record hash")
        record = DocRecord.model_validate_json(data)
        self._cache[doc_id] = record
        if len(self._cache) > _RECORD_CACHE:
            self._cache.popitem(last=False)
        return record

    def source(self, doc_id: str) -> SourceRecord:
        return self._record(doc_id).source

    def elements(self, doc_id: str) -> list[Element]:
        return list(self._record(doc_id).elements)

    def text(self, doc_id: str) -> str:
        """The canonical text, byte for byte as ingested (no newline translation)."""
        source = self.source(doc_id)
        path = self._paths(doc_id)[1]
        text = path.read_bytes().decode("utf-8")
        if sha256_text(text) != source.text_sha256:
            raise StoreError(f"{path}: text does not match the source record's text_sha256")
        return text
