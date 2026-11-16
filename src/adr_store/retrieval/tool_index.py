"""`ToolIndex`: hybrid retrieval over the tool records of one tool snapshot (Phase 2 spec §8.2).

It mirrors `StoreIndex` (build, expected fingerprint, save, load, retrieve with a mask) with a
tool in place of a chunk:

- **BM25** over a fielded text: the tool's name split on case and underscores
  (`split_name`), repeated `w_name` times; the description; each top-level parameter of the
  input schema, its name split the same way (planner's call: a camelCase parameter name is
  otherwise one token) followed by its description. It is `FieldBM25` with the description and
  parameters as the body and the split name as the field repeated `w_name` times (`w_name` 0:
  the name is not indexed), so tokenizer, library, `k1`, `b`, rounding and ties are the
  baseline's. BM25 is a bag of words: the order of the parts does not matter.
- **Dense** over "name: description. Parameters: p1 (desc), p2, …" (`dense_text`; the
  period is not doubled after a description that ends a sentence, a parameter without a
  description has no parentheses, no parameters: "name: description"), with the Phase 1
  embedding model through the `EmbeddingCache`.
- **Fusion:** the baseline's min-max linear fusion of each channel's top `CHANNEL_K` (100) with
  the weight `w` (`w` on BM25); a lexical-only index (`dense=False`) ranks by BM25 alone (its
  top `max(CHANNEL_K, top)`). `w` is not part of the index; `w_name` is.

`retrieve(query, w, top, allowed=, lexical=, exact=)` keeps only the tools in `allowed`
(masked in each channel before its cut, so a mask never starves the result); `lexical` is a
BM25 index over a subset of the tools (`view_lexical`: per-view statistics, §6.2) used in place
of the index's own, and needs `allowed`; `exact` scores the dense channel with
`dense.row_scores`, a function of (row, query) alone, so a view's scores equal those of an index
of the view's tools only bit for bit (`subset`). The ACL layer always passes `exact=True`.

Each tool's row also carries what a search hit shows without reading the record: its name, a
one-line `summary` (the first sentence of the description, whitespace collapsed, at most 200
characters: a longer one is cut to 199 and "…"), `source_kind` and `source_uri`.

The fingerprint covers the tool snapshot id, `TOOL_INDEX_VERSION`, `w_name`, the tokenizer and
BM25 configuration, the embedding model (name and hash; None for a lexical-only index), the
channel depth, the sorted tool ids and a SHA-256 of every row's content. `save(dir)` writes
`tools.jsonl` (one row per tool, sorted by id), `dense.npy` and `meta.json` as
`StoreIndex.save` does (a temporary directory renamed into place, under `flock`); `load(dir)`
rebuilds BM25 from the rows and refuses a fingerprint that does not recompute.

    <store>/tools/index/<fingerprint>/    a saved ToolIndex (never rewritten)
    <store>/tools/index/active.json       the tool index `search_tools` uses (adr_store.tools)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from adr_eval.models import jsonl_lines
from adr_eval.retrieval.chunker import TOKENIZER_CONFIG
from adr_eval.retrieval.fusion import linear
from adr_store.embedding import EmbeddingCache
from adr_store.retrieval.dense import CachedDense
from adr_store.retrieval.index import CHANNEL_K, Hits, _fresh_dir, _locked, _siblings
from adr_store.retrieval.lexical import FieldBM25, check_w_bc, doc_mask
from adr_store.tool_records import ToolRecord

TOOL_INDEX_VERSION = "1"
SUMMARY_CHARS = 200
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_SENTENCE = re.compile(r"[.!?](?=\s|$)")


def split_name(name: str) -> str:
    """A tool or parameter name split on underscores and case changes, words joined by one
    space ("getCurrentTime" -> "get Current Time", "HTTPServer" -> "HTTP Server")."""
    words = []
    for part in name.split("_"):
        words += _CAMEL.sub(" ", part).split()
    return " ".join(words)


def summary(description: str) -> str:
    """The first sentence of a description (whitespace collapsed), at most `SUMMARY_CHARS`
    characters (a longer one is cut and ends with "…")."""
    text = " ".join(description.split())
    m = _SENTENCE.search(text)
    first = text if m is None else text[:m.end()]
    return first if len(first) <= SUMMARY_CHARS else first[:SUMMARY_CHARS - 1] + "…"


def _params(rec: ToolRecord) -> list[tuple[str, str]]:
    """(name, description) of each top-level input parameter, in schema order."""
    props = rec.input_schema.get("properties") or {}
    out = []
    for name, schema in props.items():
        desc = schema.get("description") if isinstance(schema, dict) else None
        out.append((name, " ".join(desc.split()) if isinstance(desc, str) else ""))
    return out


def bm25_texts(rec: ToolRecord) -> tuple[str, str]:
    """(the split name, the body: description then each parameter's split name and
    description) of a tool's BM25 text; the name is repeated `w_name` times after the body."""
    parts = [rec.description] if rec.description.strip() else []
    for name, desc in _params(rec):
        parts.append(f"{split_name(name)} {desc}".strip())
    return split_name(rec.name), " ".join(p for p in parts if p)


def dense_text(rec: ToolRecord) -> str:
    """"name: description. Parameters: p1 (desc), p2, …" (module docstring)."""
    desc = " ".join(rec.description.split())
    text = f"{rec.name}: {desc}".rstrip()
    params = _params(rec)
    if params:
        if desc and not desc.endswith((".", "!", "?")):
            text += "."
        text += " Parameters: " + ", ".join(f"{n} ({d})" if d else n for n, d in params)
    return text


def tool_view_id(tool_ids: Iterable[str]) -> str:
    """The id of a tool view: SHA-256 of the sorted visible tool ids joined by newlines (as
    `acl.view_id` for documents)."""
    return hashlib.sha256("\n".join(sorted(tool_ids)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ToolRow:
    """One tool as the index holds it. `chunk_id`, `doc_id`, `text` and `breadcrumb` are what
    `FieldBM25` reads (the tool id; the body; the split name)."""

    tool_id: str
    name: str
    summary: str
    source_kind: str
    source_uri: str
    name_text: str
    body_text: str
    dense_text: str

    @property
    def chunk_id(self) -> str:
        return self.tool_id

    @property
    def doc_id(self) -> str:
        return self.tool_id

    @property
    def char_start(self) -> int:
        return 0

    @property
    def char_end(self) -> int:
        return 0

    @property
    def text(self) -> str:
        return self.body_text

    @property
    def breadcrumb(self) -> str:
        return self.name_text


def row_of(rec: ToolRecord) -> ToolRow:
    name_text, body = bm25_texts(rec)
    return ToolRow(rec.tool_id, rec.name, summary(rec.description), rec.source_kind,
                   rec.source_uri, name_text, body, dense_text(rec))


def rows_sha256(rows: Iterable[ToolRow]) -> str:
    h = hashlib.sha256()
    for r in sorted(rows, key=lambda r: r.tool_id):
        h.update(json.dumps(asdict(r), sort_keys=True, ensure_ascii=False,
                            separators=(",", ":")).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def fingerprint(tool_snapshot: str | None, w_name: int, lexical: FieldBM25,
                embedding: tuple[str, str] | None, rows: list[ToolRow]) -> str:
    payload = {
        "kind": "tool-index",
        "version": TOOL_INDEX_VERSION,
        "tool_snapshot": tool_snapshot,
        "w_name": w_name,
        "tokenizer": TOKENIZER_CONFIG,
        "bm25": lexical.bm25.config(),
        "embedding": None if embedding is None else {"model": embedding[0],
                                                     "model_hash": embedding[1]},
        "channel_k": CHANNEL_K,
        "tool_ids": sorted(r.tool_id for r in rows),
        "rows_sha256": rows_sha256(rows),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _default_cache() -> EmbeddingCache:
    return EmbeddingCache(Path(".cache/emb"))


class ToolIndex:
    """Build with `ToolIndex.build(catalog, w_name, cache)`."""

    def __init__(self, tool_snapshot: str | None, rows: list[ToolRow], w_name: int,
                 lexical: FieldBM25, dense: CachedDense | None,
                 embedding: tuple[str, str] | None):
        check_w_bc(w_name)
        if lexical.w_bc != w_name:
            raise ValueError(f"lexical w_bc {lexical.w_bc} differs from w_name {w_name}")
        self.tool_snapshot = tool_snapshot
        self.rows: dict[str, ToolRow] = {r.tool_id: r for r in
                                         sorted(rows, key=lambda r: r.tool_id)}
        self.w_name = w_name
        self.lexical = lexical
        self.dense = dense
        self.embedding = embedding
        self.fingerprint = fingerprint(tool_snapshot, w_name, lexical, embedding,
                                       list(self.rows.values()))
        self._dense_ids = None if dense is None else np.array(dense.chunk_ids, dtype=str)

    # -- building --------------------------------------------------------------------

    @staticmethod
    def _rows(catalog) -> list[ToolRow]:
        return [row_of(catalog.get(t)) for t in catalog.ids()]

    @staticmethod
    def _embedding(cache: EmbeddingCache | None, dense: bool):
        cache = cache if cache is not None or not dense else _default_cache()
        return cache, ((cache.model_name, cache.model_hash) if dense else None)

    @classmethod
    def from_rows(cls, tool_snapshot: str | None, rows: list[ToolRow], w_name: int,
                  cache: EmbeddingCache | None, *, dense: bool = True) -> ToolIndex:
        """An index of `rows`: BM25 built, vectors from the cache (embedding what it lacks)."""
        check_w_bc(w_name)
        cache, embedding = cls._embedding(cache, dense)
        rows = sorted(rows, key=lambda r: r.tool_id)
        lexical = FieldBM25(w_name)
        lexical.build(rows)
        dense_index = None
        if dense:
            dense_index = CachedDense(cache)
            dense_index.build_texts([r.tool_id for r in rows], [r.dense_text for r in rows])
        return cls(tool_snapshot, rows, w_name, lexical, dense_index, embedding)

    @classmethod
    def build(cls, catalog, w_name: int, cache: EmbeddingCache | None, *,
              dense: bool = True) -> ToolIndex:
        """The index of every tool of `catalog` (a `ToolCatalog`)."""
        check_w_bc(w_name)
        return cls.from_rows(catalog.snapshot_id, cls._rows(catalog), w_name, cache,
                             dense=dense)

    @classmethod
    def expected_fingerprint(cls, catalog, w_name: int, cache: EmbeddingCache | None, *,
                             dense: bool = True) -> str:
        """The fingerprint `build` would give, without building BM25 or embedding."""
        check_w_bc(w_name)
        _, embedding = cls._embedding(cache, dense)
        return fingerprint(catalog.snapshot_id, w_name, FieldBM25(w_name), embedding,
                           cls._rows(catalog))

    def with_w_name(self, w_name: int) -> ToolIndex:
        """The same rows and vectors with another name weight."""
        lexical = FieldBM25(w_name, self.lexical.bm25.k1, self.lexical.bm25.b)
        lexical.build(list(self.rows.values()))
        return ToolIndex(self.tool_snapshot, list(self.rows.values()), w_name, lexical,
                         self.dense, self.embedding)

    def view_lexical(self, tool_ids: Iterable[str]) -> FieldBM25:
        """BM25 over the rows of `tool_ids` only (statistics of those tools alone), with this
        index's `w_name`, `k1` and `b`."""
        keep = set(tool_ids)
        lex = FieldBM25(self.w_name, self.lexical.bm25.k1, self.lexical.bm25.b)
        lex.build([r for t, r in self.rows.items() if t in keep])
        return lex

    def subset(self, tool_ids: Iterable[str]) -> ToolIndex:
        """An index of the rows of `tool_ids` only, with their vectors (what a catalog of
        those tools alone would index): the reference of per-view equivalence."""
        keep = set(tool_ids)
        rows = [r for t, r in self.rows.items() if t in keep]
        dense = None
        if self.dense is not None:
            pos = {t: i for i, t in enumerate(self.dense.chunk_ids)}
            dense = CachedDense(self.dense.cache)
            ids = [r.tool_id for r in rows]
            dense.set_vectors(ids, self.dense.vectors[[pos[t] for t in ids]] if ids
                              else np.zeros((0, 0), dtype=np.float32))
        return ToolIndex(self.tool_snapshot, rows, self.w_name, self.view_lexical(keep), dense,
                         self.embedding)

    def lexical_text(self, tool_id: str) -> str:
        """The text BM25 indexes for a tool: its body, then its split name `w_name` times."""
        r = self.rows[tool_id]
        return r.body_text + (" " + r.name_text) * self.w_name

    # -- searching -------------------------------------------------------------------

    def retrieve(self, query: str, w: float | None, top: int = 10, *,
                 allowed: frozenset[str] | None = None, lexical: FieldBM25 | None = None,
                 exact: bool = False) -> Hits:
        """The top tools for `query` (module docstring)."""
        if allowed is None and lexical is not None:
            raise ValueError("a per-view lexical index needs the view's allowed tool ids too")
        if allowed is not None and not isinstance(allowed, (frozenset, set)):
            raise ValueError(f"allowed must be a set of tool ids, got {type(allowed).__name__}")
        if self.dense is not None and w is None:
            raise ValueError("linear fusion needs a tuned weight w")
        bm25 = self.lexical if lexical is None else lexical
        if lexical is not None and (lexical.w_bc, lexical.bm25.k1, lexical.bm25.b) != (
                self.w_name, self.lexical.bm25.k1, self.lexical.bm25.b):
            raise ValueError("the lexical index does not match this index (w_name, k1, b)")

        def lex(k: int) -> Hits:
            return bm25.search(query, k=k, mask=None if allowed is None else
                               bm25.mask(allowed))

        if self.dense is None:
            return lex(max(CHANNEL_K, top))[:top]
        mask = None if allowed is None else doc_mask(self._dense_ids, allowed)
        dense = self.dense.search(query, k=CHANNEL_K, mask=mask, exact=exact)
        return linear(lex(CHANNEL_K), dense, w, top=top)

    def channels(self, query: str, *, exact: bool = False) -> tuple[Hits, Hits | None]:
        """Each channel's top `CHANNEL_K` for `query` over every tool (for tuning `w`: fusing
        them with `linear(lex, dense, w, top)` is `retrieve(query, w, top, exact=exact)`)."""
        lex = self.lexical.search(query, k=CHANNEL_K)
        if self.dense is None:
            return lex, None
        return lex, self.dense.search(query, k=CHANNEL_K, exact=exact)

    # -- persistence -----------------------------------------------------------------

    def save(self, dir: Path) -> None:
        """Write the index to `dir` as `StoreIndex.save` does (a temporary directory beside
        it renamed into place, under an exclusive `flock`)."""
        started = time.time()
        dir = Path(dir)
        dir.parent.mkdir(parents=True, exist_ok=True)
        with _locked(dir, exclusive=True):
            for stale in _siblings(dir, started):
                shutil.rmtree(stale, ignore_errors=True)
            tmp = _fresh_dir(dir, "tmp")
            old = dir.parent / f".{dir.name}.{os.getpid()}.{uuid.uuid4().hex}.old"
            try:
                self._write(tmp)
                if dir.exists():
                    os.replace(dir, old)
                os.replace(tmp, dir)
            finally:
                if not dir.exists() and old.exists():
                    os.replace(old, dir)
                if dir.exists() and old.exists():
                    shutil.rmtree(old, ignore_errors=True)
                if tmp.exists():
                    shutil.rmtree(tmp, ignore_errors=True)

    def _write(self, dir: Path) -> None:
        with open(dir / "tools.jsonl", "w", encoding="utf-8") as f:
            for r in self.rows.values():
                f.write(json.dumps(asdict(r), ensure_ascii=False, sort_keys=True) + "\n")
        if self.dense is not None:
            np.save(dir / "dense.npy", self.dense.vectors)
        meta = {"fingerprint": self.fingerprint, "tool_snapshot": self.tool_snapshot,
                "w_name": self.w_name, "dense": self.dense is not None,
                "version": TOOL_INDEX_VERSION,
                "bm25": {"k1": self.lexical.bm25.k1, "b": self.lexical.bm25.b}}
        (dir / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n",
                                       encoding="utf-8")

    @classmethod
    def load(cls, dir: Path, cache: EmbeddingCache | None = None) -> ToolIndex:
        """Read a saved index (BM25 rebuilt from the rows, vectors read back); a fingerprint
        that does not recompute is refused (ValueError)."""
        dir = Path(dir)
        with _locked(dir, exclusive=False):
            meta = json.loads((dir / "meta.json").read_text(encoding="utf-8"))
            text = (dir / "tools.jsonl").read_text(encoding="utf-8")
            vectors = np.load(dir / "dense.npy") if meta["dense"] else None
        rows = [ToolRow(**json.loads(line)) for line in jsonl_lines(text)]
        cache, embedding = cls._embedding(cache, meta["dense"])
        lexical = FieldBM25(meta["w_name"], **meta["bm25"])
        lexical.build(rows)
        dense = None
        if vectors is not None:
            if vectors.ndim != 2 or vectors.shape[0] != len(rows):
                raise ValueError(f"{dir}: dense.npy does not hold one vector per tool; "
                                 f"rebuild the tool index")
            dense = CachedDense(cache)
            dense.set_vectors([r.tool_id for r in rows], vectors)
        idx = cls(meta["tool_snapshot"], rows, meta["w_name"], lexical, dense, embedding)
        if idx.fingerprint != meta["fingerprint"]:
            raise ValueError(f"{dir}: fingerprint mismatch: stored {meta['fingerprint']}, "
                             f"recomputed {idx.fingerprint}")
        return idx
