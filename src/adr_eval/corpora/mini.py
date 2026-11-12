"""Fixture corpus over tests/fixtures/mini: tiny hand-written files for offline tests.

Dated XML files (`<stem>_YYYY-MM-DD.xml`) are versions of one regulation section; their
date is the source_version. `records.json` holds the structured rows.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from adr_eval.corpora.base import Document, LoadedCorpus, sha256_bytes
from adr_eval.models import Manifest, ManifestDoc

FORMATS = {".xml", ".json", ".pdf", ".html", ".md", ".csv", ".txt"}
LICENSE = "fixture-original"
_DATED = re.compile(r"^(.+)_(\d{4}-\d{2}-\d{2})\.xml$")


class MiniAdapter:
    name = "mini"

    def fetcher(self, root: Path):
        root = Path(root)
        return lambda uri: (root / uri.removeprefix("file://")).read_bytes()

    def download(self, root: Path, fetcher=None) -> None:
        """Nothing to download: the fixture files are committed."""

    def build_manifest(self, root: Path) -> Manifest:
        root = Path(root)
        docs = []
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.suffix not in FORMATS or p.name == "manifest.json":
                continue
            data = p.read_bytes()
            rel = p.relative_to(root).as_posix()
            dated = _DATED.match(p.name)
            docs.append(
                ManifestDoc(
                    doc_id=sha256_bytes(data),
                    uri=f"file://{rel}",
                    format=p.suffix[1:],
                    source_version=dated.group(2) if dated else "1",
                    bytes=len(data),
                    license=LICENSE,
                    path=rel,
                )
            )
        return Manifest(corpus=self.name, version="1", license_summary=LICENSE, documents=docs)

    def records(self, corpus: LoadedCorpus) -> list[dict]:
        rows = []
        for d in corpus.manifest.documents:
            if Path(d.path).name == "records.json":
                for r in json.loads(corpus.docs[d.doc_id].text):
                    rows.append({**r, "_doc_id": d.doc_id})
        return rows

    def record_schema(self) -> dict[str, str]:
        return {
            "id": "str: record id, e.g. 'REC-001'",
            "type": "str: record type: 'grant', 'contract' or 'audit'",
            "year": "int: year of the record",
            "title": "str: record title",
        }

    def version_pairs(self, corpus: LoadedCorpus) -> list[tuple[Document, Document]]:
        groups: dict[str, list[Document]] = {}
        for d in corpus.manifest.documents:
            if m := _DATED.match(Path(d.path).name):
                groups.setdefault(m.group(1), []).append(corpus.docs[d.doc_id])
        pairs = []
        for stem in sorted(groups):
            versions = sorted(groups[stem], key=lambda doc: doc.source_version)
            pairs += [(a, b) for a, b in zip(versions, versions[1:], strict=False)
                      if a.text != b.text]
        return pairs
