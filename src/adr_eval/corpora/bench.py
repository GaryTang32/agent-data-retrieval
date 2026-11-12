"""Open enterprise benchmark corpus: a seeded subset of EnterpriseRAG-Bench (Onyx).

The pinned source parquet files (documents, questions) are cached under
`<root>/data/bench/_source/`. The subset keeps every row whose benchmark doc_id is a gold
document of a kept native question, then fills up to `max_docs` with a seeded uniform
sample of the other rows. Each selected parquet row is rendered to one markdown file
`data/bench/docs/{row:06d}_{doc_id}.md`; its URI is `<documents url>#row=<n>&doc_id=<id>`,
which `fetcher()` resolves from the cached parquet (row indices are stable for the pinned
file). Benchmark doc_ids are not unique (4 ids repeat), hence rows, not ids, identify
documents. Questions are never part of the manifest, so they cannot be retrieved.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

from adr_eval.corpora import REPO_ROOT
from adr_eval.corpora.base import Document, LoadedCorpus, sha256_bytes
from adr_eval.corpora.http import PoliteFetcher, sha256_file
from adr_eval.models import Manifest, ManifestDoc

DOCS_DIR = "data/bench/docs"
_DOC_FILE = re.compile(r"^(\d{6})_(.+)\.md$")
_URI = re.compile(r"#row=(\d+)&doc_id=(.+)$")


def _row(table, i: int) -> dict:
    # slice() is zero-copy; take() would concatenate >2 GB string columns and overflow.
    return table.slice(i, 1).to_pylist()[0]


def render(row: dict) -> bytes:
    """Deterministic markdown rendering of one benchmark document row."""
    title = " ".join(str(row["title"] or "").split())
    content = str(row["content"] or "").rstrip()
    return f"# {title}\n\nSource: {row['source_type']}\n\n{content}\n".encode()


class BenchAdapter:
    name = "bench"

    def __init__(self, config_path: Path | None = None):
        self.config_path = Path(config_path or REPO_ROOT / "corpora" / "bench" / "config.json")
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))

    # -- sources ----------------------------------------------------------------------

    def _source(self, root: Path, key: str, fetcher: PoliteFetcher | None) -> Path:
        """Path of the pinned source file `key`, downloading it (resumably) if needed."""
        src = self.config[key]
        path = Path(root) / src["path"]
        if path.is_file() and sha256_file(path) == src["sha256"]:
            return path
        (fetcher or PoliteFetcher()).download(src["url"], path, src["sha256"])
        return path

    def _questions(self, root: Path, fetcher: PoliteFetcher | None = None) -> list[dict]:
        import pyarrow.parquet as pq

        rows = pq.read_table(self._source(root, "questions", fetcher)).to_pylist()
        excluded = set(self.config["exclude_question_types"])
        return [q for q in rows if q["question_type"] not in excluded]

    def select_rows(self, root: Path, fetcher: PoliteFetcher | None = None) -> list[int]:
        """Sorted parquet row indices of the seeded subset (gold rows + seeded fill)."""
        import pyarrow.parquet as pq

        gold = {d for q in self._questions(root, fetcher) for d in q["expected_doc_ids"]}
        table = pq.read_table(self._source(root, "documents", fetcher), columns=["doc_id"])
        ids = table.column("doc_id").to_pylist()
        gold_rows = [i for i, d in enumerate(ids) if d in gold]
        missing = gold - {ids[i] for i in gold_rows}
        if missing:
            raise ValueError(f"gold documents missing from the source: {sorted(missing)[:5]}")
        budget = self.config["max_docs"] - len(gold_rows)
        if budget < 0:
            raise ValueError(f"{len(gold_rows)} gold rows exceed max_docs")
        others = [i for i, d in enumerate(ids) if d not in gold]
        fill = random.Random(self.config["seed"]).sample(others, min(budget, len(others)))
        return sorted(gold_rows + fill)

    # -- acquisition --------------------------------------------------------------------

    def download(self, root: Path, fetcher: PoliteFetcher | None = None) -> None:
        """Materialize the subset as markdown files under `root/data/bench/docs`."""
        import pyarrow.parquet as pq

        rows = self.select_rows(root, fetcher)
        table = pq.read_table(self._source(root, "documents", fetcher))
        out = Path(root) / DOCS_DIR
        out.mkdir(parents=True, exist_ok=True)
        for i in rows:
            row = _row(table, i)
            target = out / f"{i:06d}_{row['doc_id']}.md"
            if not target.is_file():
                target.write_bytes(render(row))

    def fetcher(self, root: Path):
        """Fetcher for `fetch_manifest`: resolves `...#row=<n>&doc_id=<id>` from the parquet."""
        cache: dict = {}

        def fetch(uri: str) -> bytes:
            m = _URI.search(uri)
            if m is None or not uri.startswith(self.config["documents"]["url"]):
                raise ValueError(f"not a bench document URI: {uri}")
            if "table" not in cache:
                import pyarrow.parquet as pq

                cache["table"] = pq.read_table(self._source(root, "documents", None))
            row = _row(cache["table"], int(m.group(1)))
            if row["doc_id"] != m.group(2):
                raise ValueError(f"row {m.group(1)} holds {row['doc_id']}, not {m.group(2)}")
            return render(row)

        return fetch

    # -- manifest ---------------------------------------------------------------------

    def build_manifest(self, root: Path) -> Manifest:
        docs = []
        for p in sorted((Path(root) / DOCS_DIR).glob("*.md")):
            m = _DOC_FILE.match(p.name)
            if m is None:
                continue
            data = p.read_bytes()
            row, dsid = int(m.group(1)), m.group(2)
            docs.append(
                ManifestDoc(
                    doc_id=sha256_bytes(data),
                    uri=f"{self.config['documents']['url']}#row={row}&doc_id={dsid}",
                    format="md",
                    source_version=self.config["revision"],
                    bytes=len(data),
                    license=self.config["license"],
                    path=p.relative_to(root).as_posix(),
                )
            )
        return Manifest(
            corpus=self.name,
            version=self.config["version"],
            license_summary=self.config["license_summary"],
            documents=docs,
        )

    # -- structured views and native questions -------------------------------------------

    def records(self, corpus: LoadedCorpus) -> list[dict]:
        rows = []
        for d in corpus.manifest.documents:
            m = _URI.search(d.uri)
            if m is None:
                continue
            lines = corpus.docs[d.doc_id].text.split("\n", 3)
            rows.append({
                "id": m.group(2),
                "source_type": lines[2].removeprefix("Source: "),
                "title": lines[0].removeprefix("# "),
                "_doc_id": d.doc_id,
            })
        return rows

    def record_schema(self) -> dict[str, str]:
        return {
            "id": "str: benchmark document id, e.g. 'dsid_ae06...'",
            "source_type": "str: originating system: slack, gmail, linear, google_drive, "
            "hubspot, fireflies, github, jira or confluence",
            "title": "str: document title",
        }

    def version_pairs(self, corpus: LoadedCorpus) -> list[tuple[Document, Document]]:
        return []

    def native_items(self, root: Path | None = None,
                     manifest: Manifest | None = None) -> list[dict]:
        """The benchmark's own questions answerable on the subset.

        Each is the source question dict plus `qtype` (mapped per corpora/bench/README.md)
        and `manifest_doc_ids` (our doc_ids for its `expected_doc_ids`). `high_level`
        questions are excluded: their answers span the full 500k-document corpus.
        """
        root = Path(root or REPO_ROOT)
        if manifest is None:
            path = REPO_ROOT / "corpora" / "bench" / "manifest.json"
            manifest = Manifest.model_validate_json(path.read_text(encoding="utf-8"))
        by_dsid: dict[str, list[str]] = {}
        for d in manifest.documents:
            if m := _URI.search(d.uri):
                by_dsid.setdefault(m.group(2), []).append(d.doc_id)
        items = []
        for q in self._questions(root):
            ids = [doc_id for dsid in q["expected_doc_ids"] for doc_id in by_dsid.get(dsid, [])]
            if any(dsid not in by_dsid for dsid in q["expected_doc_ids"]):
                continue
            items.append({**q, "qtype": self.config["qtype_map"][q["question_type"]],
                          "manifest_doc_ids": ids})
        return items


def native_items(root: Path | None = None) -> list[dict]:
    """Native EnterpriseRAG-Bench questions for the pinned subset (see BenchAdapter)."""
    return BenchAdapter().native_items(root)
