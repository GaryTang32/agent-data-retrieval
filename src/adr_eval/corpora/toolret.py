"""The tool corpus: ToolRet's `toolbench` subset, local-only (Phase 2 spec §8.3, ruling R13).

`corpora/tools/config.json` pins two parquet files of the Hugging Face Hub by repository,
revision, path and SHA-256 (the paths at each revision were found once with the Hub tree
API): the tools of `mangopy/ToolRet-Tools` (config `web`) and the queries of
`mangopy/ToolRet-Queries` (config `toolbench`). `fetch` downloads them with `PoliteFetcher`
from `https://huggingface.co/datasets/<repo>/resolve/<revision>/<path>` into `data/tools/`
(git-ignored), verifies each SHA-256, and writes `corpora/tools/manifest.json`: SHA-256 and
size per file plus the corpus counts (`stats`); no timestamps, so a re-fetch writes the same
bytes. Nothing from ToolRet is committed but revisions, hashes and counts.

- `tools(root)`: the ToolRet rows whose id starts with the configured prefix
  (`toolbench_tool_`), as `{"id", "documentation"}` (the raw ToolBench JSON string), sorted by
  id.
- `queries(root)`: `ToolQuery(id, query, gold, split)` sorted by id; `gold` are the ToolRet
  ids of the labels with relevance > 0, in label order without repeats. The query field is
  used; ToolRet's `instruction` is not.
- `split_of(id)`: `dev` when `int(SHA-256(id), 16) % 5 == 0`, else `test` (fixed before any
  tuning).

Reading verifies both files against the config's SHA-256 (`HashMismatch`); a missing file
raises `ToolRetMissing`, which names `adr-eval tools-fetch`.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from adr_eval.corpora import REPO_ROOT
from adr_eval.corpora.base import HashMismatch
from adr_eval.corpora.http import PoliteFetcher, sha256_file

CONFIG_PATH = REPO_ROOT / "corpora" / "tools" / "config.json"
MANIFEST_PATH = REPO_ROOT / "corpora" / "tools" / "manifest.json"
DATA_DIR = REPO_ROOT / "data" / "tools"
HUB = "https://huggingface.co/datasets"
FILE_KEYS = ("tools", "queries")

Split = Literal["dev", "test"]


class ToolRetMissing(Exception):
    """A pinned ToolRet file is not in the data directory."""


class ToolQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    query: str
    gold: tuple[str, ...]
    split: Split


def load_config(path: Path | None = None) -> dict:
    return json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def file_url(entry: dict) -> str:
    """The Hub `resolve` URL of a pinned file entry of the config."""
    return f"{HUB}/{entry['repo']}/resolve/{entry['revision']}/{entry['path']}"


def make_fetcher() -> PoliteFetcher:
    return PoliteFetcher()


def split_of(query_id: str) -> Split:
    """`dev` when the SHA-256 of the id is 0 mod 5, else `test` (spec §8.3)."""
    return "dev" if int(hashlib.sha256(query_id.encode("utf-8")).hexdigest(), 16) % 5 == 0 \
        else "test"


def _file(root: Path | None, config: dict, key: str) -> Path:
    entry = config["files"][key]
    path = Path(root or DATA_DIR) / entry["local"]
    if not path.is_file():
        raise ToolRetMissing(f"{path} is missing; run `adr-eval tools-fetch` (ToolRet is "
                             f"local-only and never committed)")
    got = sha256_file(path)
    if got != entry["sha256"]:
        raise HashMismatch(str(path), entry["sha256"], got)
    return path


def _read(root: Path | None, config: dict, key: str) -> list[dict]:
    import pyarrow.parquet as pq

    return pq.read_table(_file(root, config, key)).to_pylist()


def tools(root: Path | None = None, config_path: Path | None = None) -> list[dict]:
    """The configured ToolRet tools, `{"id", "documentation"}`, sorted by id."""
    config = load_config(config_path)
    prefix = config["tool_prefix"]
    rows = [{"id": r["id"], "documentation": r["documentation"]}
            for r in _read(root, config, "tools") if r["id"].startswith(prefix)]
    return sorted(rows, key=lambda r: r["id"])


def queries(root: Path | None = None, config_path: Path | None = None) -> list[ToolQuery]:
    """The ToolRet queries of the configured subset, sorted by id."""
    config = load_config(config_path)
    out = []
    for r in _read(root, config, "queries"):
        gold: list[str] = []
        for label in json.loads(r["labels"]):
            if label.get("relevance", 1) > 0 and label["id"] not in gold:
                gold.append(label["id"])
        out.append(ToolQuery(id=r["id"], query=r["query"], gold=tuple(gold),
                             split=split_of(r["id"])))
    return sorted(out, key=lambda q: q.id)


def stats(root: Path | None = None, config_path: Path | None = None) -> dict:
    """Corpus counts: tools, queries, gold labels (total, mean per query, distinct, missing
    from the tools), raw documentation tokens (harness tokenizer: total, mean, median), and
    the dev/test split sizes."""
    from adr_eval.retrieval.chunker import _count

    ts = tools(root, config_path)
    qs = queries(root, config_path)
    ids = {t["id"] for t in ts}
    tokens = [_count(t["documentation"]) for t in ts]
    gold = [g for q in qs for g in q.gold]
    return {
        "tools": len(ts),
        "queries": len(qs),
        "gold_total": len(gold),
        "gold_mean": round(len(gold) / len(qs), 4) if qs else 0.0,
        "gold_distinct": len(set(gold)),
        "gold_missing": len(set(gold) - ids),
        "doc_tokens": sum(tokens),
        "doc_tokens_mean": round(sum(tokens) / len(tokens), 4) if tokens else 0.0,
        "doc_tokens_median": statistics.median(tokens) if tokens else 0,
        "dev": sum(q.split == "dev" for q in qs),
        "test": sum(q.split == "test" for q in qs),
    }


def fetch(root: Path | None = None, config_path: Path | None = None,
          manifest_path: Path | None = None, *, fetcher: PoliteFetcher | None = None) -> dict:
    """Download the pinned files (a present file with the pinned hash is not fetched again),
    verify them, and write the manifest; returns it. Nothing is written to the manifest when
    a hash does not match (`HashMismatch`)."""
    config = load_config(config_path)
    root = Path(root or DATA_DIR)
    fetcher = fetcher or make_fetcher()
    files = []
    for key in FILE_KEYS:
        entry = config["files"][key]
        dest = root / entry["local"]
        fetcher.download(file_url(entry), dest, entry["sha256"])
        files.append({"name": key, "repo": entry["repo"], "revision": entry["revision"],
                      "config": entry["config"], "path": entry["path"],
                      "url": file_url(entry), "local": entry["local"],
                      "bytes": dest.stat().st_size, "sha256": sha256_file(dest)})
    manifest = {"corpus": config["corpus"], "license": config["license"],
                "license_summary": config["license_summary"],
                "tool_prefix": config["tool_prefix"], "files": files,
                "counts": stats(root, config_path)}
    path = Path(manifest_path or MANIFEST_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return manifest
