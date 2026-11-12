"""The repository's own research corpus: reports, notes, the papers catalog and a seeded
sample of locally downloaded PDFs. Every path is repo-relative and every URI is
`file://<path>`. PDFs are local only (not in git); rebuild them with
scripts/download_papers.py.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
from pathlib import Path

from adr_eval.corpora import REPO_ROOT
from adr_eval.corpora.base import Document, LoadedCorpus, sha256_bytes
from adr_eval.models import Manifest, ManifestDoc


def _row_id(row: dict) -> str:
    if row.get("arxiv_id"):
        return row["arxiv_id"]
    if row.get("doi"):
        return row["doi"]
    return "url:" + hashlib.sha256(row.get("url", "").encode("utf-8")).hexdigest()[:16]


def _csv_rows_with_spans(text: str) -> list[tuple[dict, tuple[int, int]]]:
    """Parse CSV text into dict rows, each with the [start, end) span of its source lines
    (line terminator excluded)."""
    lines = text.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    consumed = 0

    def feed():
        nonlocal consumed
        for line in lines:
            consumed += 1
            yield line

    reader = csv.reader(feed())
    header = next(reader)
    out = []
    while True:
        first = consumed
        try:
            values = next(reader)
        except StopIteration:
            break
        if not values:
            continue
        end = starts[consumed]
        end -= len(lines[consumed - 1]) - len(lines[consumed - 1].rstrip("\r\n"))
        out.append((dict(zip(header, values, strict=False)), (starts[first], end)))
    return out


LOCAL_LIBRARY_HINT = (
    "The research corpus needs the local PDF library, which is not in git (the PDFs' "
    "licences often forbid redistribution). Download it with `python "
    "scripts/download_papers.py <research_notes folders>`; the script rewrites the tracked "
    "papers/manifest.csv, which is itself a pinned corpus document, so restore it afterwards "
    "with `git checkout papers/manifest.csv`. Downloaded PDFs must match the hashes pinned in "
    "corpora/research/manifest.json."
)


class ResearchAdapter:
    name = "research"
    local_files_hint = LOCAL_LIBRARY_HINT  # its files cannot be fetched, only provided

    def __init__(self, config_path: Path | None = None, sample_size: int | None = None,
                 seed: int | None = None):
        self.config_path = Path(config_path or REPO_ROOT / "corpora" / "research" / "config.json")
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        sample = self.config["pdf_sample"]
        self.sample_size = sample["size"] if sample_size is None else sample_size
        self.seed = sample["seed"] if seed is None else seed
        self.catalog = self.config["catalog"]

    def fetcher(self, root: Path):
        root = Path(root)

        def read(uri: str) -> bytes:
            rel = uri.removeprefix("file://")
            path = root / rel
            if not path.is_file():
                raise FileNotFoundError(f"{rel}: missing locally. {LOCAL_LIBRARY_HINT}")
            return path.read_bytes()

        return read

    def download(self, root: Path, fetcher=None) -> None:
        """Nothing to download: every source is a local repository file."""

    def _catalog(self, root: Path) -> list[dict]:
        with open(root / self.catalog, encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    def sample_pdfs(self, root: Path) -> list[dict]:
        """Seeded sample of catalog rows that are downloaded and present on disk."""
        eligible = {}
        for row in self._catalog(root):
            rel = row.get("local_file") or ""
            status = self.config["pdf_sample"]["status"]
            if row.get("status") == status and rel and (root / rel).is_file():
                eligible.setdefault(rel, row)
        if len(eligible) < self.sample_size:
            raise ValueError(
                f"research sample needs {self.sample_size} downloaded PDFs under papers/, "
                f"found {len(eligible)}; run scripts/download_papers.py"
            )
        rows = [eligible[k] for k in sorted(eligible)]
        picked = random.Random(self.seed).sample(rows, self.sample_size)
        return sorted(picked, key=lambda r: r["local_file"])

    def build_manifest(self, root: Path) -> Manifest:
        root = Path(root)
        entries: list[tuple[str, str, str]] = []  # (path, format, license)
        repo_license = self.config["repo_license"]
        texts = {p for g in self.config["text_globs"] for p in root.glob(g) if p.is_file()}
        for p in sorted(texts):
            entries.append((p.relative_to(root).as_posix(), "md", repo_license))
        entries.append((self.catalog, "csv", repo_license))
        for row in self.sample_pdfs(root):
            entries.append((row["local_file"], "pdf", row.get("license") or "unknown"))
        docs = []
        for rel, fmt, lic in sorted(entries):
            data = (root / rel).read_bytes()
            doc_id = sha256_bytes(data)
            # Content-derived, so the manifest depends on the bytes alone (not on git history,
            # clone depth or uncommitted edits).
            docs.append(ManifestDoc(doc_id=doc_id, uri=f"file://{rel}", format=fmt,
                                    source_version="sha256:" + doc_id[:12], bytes=len(data),
                                    license=lic, path=rel))
        return Manifest(
            corpus=self.name,
            version=self.config["version"],
            license_summary=self.config["license_summary"],
            documents=docs,
        )

    def records(self, corpus: LoadedCorpus) -> list[dict]:
        rows = []
        for d in corpus.manifest.documents:
            if d.path != self.catalog:
                continue
            for row, span in _csv_rows_with_spans(corpus.docs[d.doc_id].text):
                year = row.get("year", "")
                rows.append({
                    **row,
                    "id": _row_id(row),
                    "year": int(year) if year.isdigit() else None,
                    "_doc_id": d.doc_id,
                    "_span": list(span),
                })
        return rows

    def record_schema(self) -> dict[str, str]:
        return {
            "id": "str: arXiv id, else DOI, else 'url:' + hash of the URL",
            "research": "str: research report the source was gathered for",
            "topic": "str: topic folder, e.g. '01_surveys_foundations'",
            "also_in": "str: other topics that cite the source (may be empty)",
            "type": "str: 'paper' or 'web'",
            "title": "str: source title",
            "authors": "str: comma-separated author list",
            "year": "int | None: publication year",
            "venue": "str: venue, e.g. 'arXiv preprint'",
            "url": "str: landing page URL",
            "pdf_url": "str: PDF URL (may be empty)",
            "arxiv_id": "str: arXiv identifier (may be empty)",
            "doi": "str: DOI (may be empty)",
            "license": "str: licence of the source, e.g. 'CC-BY-4.0'",
            "status": "str: download status, e.g. 'downloaded' or 'no_pdf_link'",
            "local_file": "str: repo-relative PDF path when downloaded",
            "relevance": "str: one-sentence note on why the source matters",
        }

    def version_pairs(self, corpus: LoadedCorpus) -> list[tuple[Document, Document]]:
        return []
