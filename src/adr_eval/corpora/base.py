"""Manifest fetch/verify, Document loading and the corpus adapter protocol."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from adr_eval.corpora.extract import extract_text
from adr_eval.models import Manifest


class HashMismatch(Exception):  # noqa: N818 - name fixed by the task interface
    def __init__(self, path: str, expected: str, got: str):
        super().__init__(f"{path}: expected sha256 {expected}, got {got}")
        self.path, self.expected, self.got = path, expected, got


class ExtractionError(RuntimeError):
    """Text extraction failed for one corpus file; the message names the file."""


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@dataclass(frozen=True)
class Document:
    doc_id: str
    text: str
    format: str
    source_version: str
    uri: str


@dataclass
class LoadedCorpus:
    manifest: Manifest
    docs: dict[str, Document]
    empty_docs: list[str]
    root: Path | None = None  # where the manifest's `path`s resolve; set by load_corpus


def fetch_manifest(m: Manifest, root: Path, fetcher: Callable[[str], bytes]) -> None:
    """Download missing/corrupt files. `doc_id` is the sha256 of the file bytes.

    Nothing is written when the downloaded bytes do not match the manifest.
    """
    for doc in m.documents:
        target = Path(root) / doc.path
        if target.is_file() and sha256_bytes(target.read_bytes()) == doc.doc_id:
            continue
        data = fetcher(doc.uri)
        got = sha256_bytes(data)
        if got != doc.doc_id:
            raise HashMismatch(doc.path, doc.doc_id, got)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def verify_manifest(m: Manifest, root: Path) -> list[str]:
    problems: list[str] = []
    for doc in m.documents:
        target = Path(root) / doc.path
        if not target.is_file():
            problems.append(f"{doc.path}: missing")
            continue
        data = target.read_bytes()
        if len(data) != doc.bytes:
            problems.append(f"{doc.path}: size {len(data)} != manifest {doc.bytes}")
        got = sha256_bytes(data)
        if got != doc.doc_id:
            problems.append(f"{doc.path}: sha256 {got} != manifest {doc.doc_id}")
    return problems


def load_corpus(manifest_path: Path, root: Path) -> LoadedCorpus:
    manifest = Manifest.model_validate_json(Path(manifest_path).read_text(encoding="utf-8"))
    problems = verify_manifest(manifest, root)
    if problems:
        raise ValueError("manifest verification failed:\n" + "\n".join(problems))
    docs: dict[str, Document] = {}
    empty: list[str] = []
    for d in manifest.documents:
        data = (Path(root) / d.path).read_bytes()
        try:
            text = extract_text(data, d.format)
        except Exception as e:  # name the file whatever the extractor raised
            raise ExtractionError(
                f"{d.path}: could not extract text ({d.format}): {type(e).__name__}: {e}"
            ) from e
        docs[d.doc_id] = Document(d.doc_id, text, d.format, d.source_version, d.uri)
        if not text.strip():
            empty.append(d.doc_id)
    return LoadedCorpus(manifest=manifest, docs=docs, empty_docs=empty, root=Path(root))


class CorpusAdapter(Protocol):
    name: str

    def download(self, root: Path, fetcher: Callable[[str], bytes] | None = None) -> None:
        """Acquire the configured source files under `root` (skip files already present)."""
        ...

    def fetcher(self, root: Path) -> Callable[[str], bytes]:
        """Resolve a manifest URI to its bytes, for `fetch_manifest`."""
        ...

    def build_manifest(self, root: Path) -> Manifest:
        """Describe the corpus files under `root` (hashes, sizes, licences)."""
        ...

    def records(self, corpus: LoadedCorpus) -> list[dict]:
        """Structured rows for count/filter questions.

        Each row has `_doc_id` and an `id` field. A row MAY also carry
        `_span: [char_start, char_end]`, character offsets into the extracted
        text of `_doc_id` (as produced by `extract_text`) locating the record.
        """
        ...

    def record_schema(self) -> dict[str, str]:
        """Field -> type and one-line description, used in G2 prompts."""
        ...

    def version_pairs(self, corpus: LoadedCorpus) -> list[tuple[Document, Document]]:
        """(older, newer) versions of the same section; may be empty."""
        ...
