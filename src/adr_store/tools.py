"""The retrieval tools over one store (spec §9): `index`, `search`, `read`, `grep`, and the
retrieval log. A plain Python API (`Tools`) returning dataclasses, so the command line
(`adr_store.cli`) and a later MCP wrapper call the same code.

    <store>/index/<fingerprint>/      a saved `StoreIndex` (chunks, vectors, meta), never rewritten
    <store>/index/active.json         the index `search` uses: system, settings, weight, snapshot
    <store>/log/retrieval.jsonl       one JSON line per tool call

Index. `Tools.index(system)` builds the `StoreIndex` of a Phase 1 system for the store's HEAD
snapshot (or loads it when an index with the same fingerprint is saved) and makes it the
active index. The systems' settings are those of the harness registry (`adr_eval.systems`;
a test keeps the two tables equal). Tuned values are not tuned here: `w_bc` and the fusion
weight come from the harness run that tuned them (`tuning`: an `adr-eval retrieval` run
directory or its `retrieval.json`, which must be for the same system and the same store
snapshot) or are given (`w_bc`, `weight`), which take precedence. `p1-struct` has `w_bc` 0.
A lexical-only index has the BM25 channel only (no embedding, no fusion, no reranker), as the
harness's `--lexical-only`; with the same snapshot and values its fingerprint is the harness
run's.

Search returns the active index's ranking exactly (`StoreIndex.retrieve`: best score first,
ties by chunk id). Read returns `store.text(doc_id)[start:end]` (the store checks the text's
hash; an element's or chunk's range is checked against its own hash or text). Grep runs a
Python regular expression (multi-line mode, so `^` and `$` match at line ends) over every
document of the snapshot in doc-id order, matches in offset order, at most `max`; a pattern
that is empty or can match the empty string is refused. Document, element and chunk ids may
be given as a unique prefix of at least 8 characters; results always carry full ids.

Every call, including a refused one, appends one JSON line to the log (UTC time, tool,
arguments, snapshot id, result ids, and the error for a refused call) with a single
`O_APPEND` write, after the result is computed; the log is never read, so it cannot change
a result. Every result names the snapshot it came from.
"""

from __future__ import annotations

import bisect
import json
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from adr_store.embedding import EmbeddingCache
from adr_store.records import sha256_text
from adr_store.retrieval import Settings, StoreIndex
from adr_store.retrieval.index import CHANNEL_K
from adr_store.retrieval.lexical import check_w_bc
from adr_store.retrieval.rerank import CrossEncoderReranker
from adr_store.store import Store, StoreError, write_atomic

GREP_MAX = 100
SEARCH_TOP = 10
CONTEXT_CHARS = 80  # characters of context on each side of a grep match
MIN_PREFIX = 8
DEFAULT_EMB_CACHE = Path(".cache/emb")


class ToolError(Exception):
    """A call the tools refuse, with a message for the caller (exit code 2 on the CLI)."""


@dataclass(frozen=True)
class SystemSpec:
    """A Phase 1 system's settings, as `adr_eval.systems.SPECS`."""

    prefix: bool
    tune_w_bc: bool
    rerank: bool


SYSTEMS = {
    "p1-struct": SystemSpec(prefix=False, tune_w_bc=False, rerank=False),
    "p1-struct-bc": SystemSpec(prefix=True, tune_w_bc=True, rerank=False),
    "p1-struct-bc-rr": SystemSpec(prefix=True, tune_w_bc=True, rerank=True),
}


def make_embedding_cache(cache_dir: Path = DEFAULT_EMB_CACHE) -> EmbeddingCache:
    """The embedding cache of a dense index (tests replace this function)."""
    return EmbeddingCache(Path(cache_dir))


def make_reranker() -> CrossEncoderReranker:
    """The cross-encoder of `p1-struct-bc-rr` (tests replace this function)."""
    return CrossEncoderReranker()


# -- results ------------------------------------------------------------------------------


class _Result:
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class IndexInfo(_Result):
    system: str
    snapshot: str
    fingerprint: str
    lexical_only: bool
    prefix: bool
    rerank: bool
    w_bc: int
    w_bc_from: str  # "system", "tuning" or "override"
    w: float | None
    w_from: str | None  # "tuning", "override", or None without fusion
    n_chunks: int
    source: str  # "built" or "loaded"
    path: str
    tuning: dict | None = None


@dataclass(frozen=True)
class Hit(_Result):
    rank: int
    chunk_id: str
    doc_id: str
    char_start: int
    char_end: int
    breadcrumb: str
    score: float
    snapshot: str


@dataclass(frozen=True)
class SearchResult(_Result):
    query: str
    top: int
    snapshot: str
    system: str
    lexical_only: bool
    fingerprint: str
    w: float | None
    hits: list[Hit] = field(default_factory=list)


@dataclass(frozen=True)
class ReadResult(_Result):
    snapshot: str
    doc_id: str
    uri: str
    char_start: int
    char_end: int
    text_sha256: str
    element_id: str | None
    chunk_id: str | None
    text: str


@dataclass(frozen=True)
class GrepMatch(_Result):
    doc_id: str
    char_start: int
    char_end: int
    line: int
    match: str
    context: str
    snapshot: str


@dataclass(frozen=True)
class GrepResult(_Result):
    pattern: str
    ignore_case: bool
    doc: str | None
    max: int
    snapshot: str
    truncated: bool
    matches: list[GrepMatch] = field(default_factory=list)


# -- helpers ------------------------------------------------------------------------------


def _short(s: str) -> str:
    return f"{s[:12]}…" if len(s) > 12 else s


def _resolve(given: str, candidates: list[str], what: str, where: str) -> str:
    """The full id for `given`: itself, or the one sorted candidate it is a prefix of."""
    i = bisect.bisect_left(candidates, given)
    if i < len(candidates) and candidates[i] == given:
        return given
    if len(given) < MIN_PREFIX:
        raise ToolError(f"no {what} {given!r} in {where}; give the full id or at least "
                        f"{MIN_PREFIX} characters of it")
    found = []
    while i < len(candidates) and candidates[i].startswith(given) and len(found) < 2:
        found.append(candidates[i])
        i += 1
    if not found:
        raise ToolError(f"no {what} {_short(given)} in {where}")
    if len(found) > 1:
        raise ToolError(f"{what} prefix {given!r} is ambiguous in {where}; give more of it")
    return found[0]


def _load_tuning(path: Path, system: str, snapshot: str) -> dict:
    """The tuned values of an `adr-eval retrieval` run record, checked against the system
    and the store snapshot."""
    path = Path(path)
    if path.is_dir():
        path = path / "retrieval.json"
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))["config"]
        if cfg["track"] != "retrieval":
            raise KeyError("track")
        rec = {"path": str(path), "run_id": cfg.get("run_id"), "system": cfg["system"],
               "lexical_only": bool(cfg["lexical_only"]), "fingerprint": cfg["fingerprint"],
               "store_snapshot": cfg["settings"]["store_snapshot"],
               "w_bc": cfg["settings"]["w_bc"], "w": cfg["w"]}
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ToolError(f"tuning record {path} is not a readable adr-eval retrieval run of a "
                        f"Phase 1 system ({type(e).__name__}: {e})") from e
    if rec["system"] != system:
        raise ToolError(f"tuning record {path} is for {rec['system']}, not {system}")
    if rec["store_snapshot"] != snapshot:
        values = f"--w-bc {rec['w_bc']}" + ("" if rec["w"] is None else f" --weight {rec['w']}")
        raise ToolError(f"tuning record {path} was made on store snapshot "
                        f"{_short(rec['store_snapshot'])}, this store is at {_short(snapshot)}; "
                        f"rerun the retrieval run on this store, or pass {values} to use its "
                        f"values anyway")
    return rec


def _context(text: str, start: int, end: int) -> str:
    """The line around a match, clipped to `CONTEXT_CHARS` on each side, on one line."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end < 0 else line_end
    left = max(line_start, start - CONTEXT_CHARS)
    right = min(line_end, end + CONTEXT_CHARS)
    match = text[start:end]
    if len(match) > 2 * CONTEXT_CHARS:
        match = f"{match[:CONTEXT_CHARS]}…{match[-CONTEXT_CHARS:]}"
    out = ("…" if left > line_start else "") + text[left:start] + match + text[end:right] + \
        ("…" if right < line_end else "")
    return out.replace("\r", " ").replace("\n", " ")


# -- the tools ------------------------------------------------------------------------------


class Tools:
    """The tools over the store at `store_path`, read at its HEAD snapshot when created."""

    def __init__(self, store_path: Path, *, emb_cache: Path = DEFAULT_EMB_CACHE):
        self.store_path = Path(store_path)
        try:
            self.store = Store.open(self.store_path)
        except StoreError as e:
            raise ToolError(str(e)) from e
        self.snapshot: str = self.store.snapshot_id
        self.emb_cache = Path(emb_cache)
        self._index: StoreIndex | None = None
        self._active: dict | None = None
        self._chunks: dict[str, dict] | None = None

    @property
    def index_root(self) -> Path:
        return self.store_path / "index"

    @property
    def log_path(self) -> Path:
        return self.store_path / "log" / "retrieval.jsonl"

    # -- the log ----------------------------------------------------------------------

    def _append_log(self, entry: dict) -> None:
        line = (json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            written = os.write(fd, line)
            if written != len(line):  # never seen on a local file system; do not leave half
                raise StoreError(f"{self.log_path}: short write ({written} of {len(line)} "
                                 f"bytes)")
        finally:
            os.close(fd)

    def _call(self, tool: str, args: dict, fn: Callable[[], tuple[object, list, dict]]):
        """Run one tool call and log it; `fn` returns (result, result ids, extra fields)."""
        entry = {"time": datetime.now(UTC).isoformat(), "tool": tool, "args": args,
                 "snapshot": self.snapshot}
        try:
            result, ids, extra = fn()
        except (ToolError, StoreError) as e:
            self._append_log({**entry, "results": [], "error": str(e)})
            if isinstance(e, StoreError):
                raise ToolError(str(e)) from e
            raise
        self._append_log({**entry, **extra, "results": ids})
        return result

    # -- index ------------------------------------------------------------------------

    def index(self, system: str, *, lexical_only: bool = False, w_bc: int | None = None,
              weight: float | None = None, tuning: Path | None = None) -> IndexInfo:
        """Build or load the index of `system` for the HEAD snapshot and make it active."""
        args = {"system": system, "lexical_only": lexical_only, "w_bc": w_bc,
                "weight": weight, "tuning": None if tuning is None else str(tuning)}

        def run():
            info = self._index_impl(system, lexical_only, w_bc, weight, tuning)
            return info, [info.fingerprint], {}

        return self._call("index", args, run)

    def _settings(self, system: str, lexical_only: bool, w_bc: int | None,
                  weight: float | None, tuning: Path | None):
        if system not in SYSTEMS:
            raise ToolError(f"unknown system {system!r}; expected one of "
                            f"{', '.join(SYSTEMS)}")
        spec = SYSTEMS[system]
        if w_bc is not None:
            try:
                check_w_bc(w_bc)
            except ValueError as e:
                raise ToolError(str(e)) from e
            if not spec.tune_w_bc and w_bc != 0:
                raise ToolError(f"{system} has w_bc 0 (no breadcrumb field); drop --w-bc")
        if weight is not None:
            if lexical_only:
                raise ToolError("a lexical-only index has no fusion; drop --weight")
            if isinstance(weight, bool) or not 0.0 <= float(weight) <= 1.0:
                raise ToolError(f"the fusion weight must be between 0 and 1, got {weight!r}")
        rec = None if tuning is None else _load_tuning(tuning, system, self.snapshot)
        if w_bc is not None:
            w_bc_value, w_bc_from = w_bc, "override"
        elif not spec.tune_w_bc:
            w_bc_value, w_bc_from = 0, "system"
        elif rec is not None:
            try:
                w_bc_value, w_bc_from = check_w_bc(rec["w_bc"]), "tuning"
            except ValueError as e:
                raise ToolError(f"tuning record {rec['path']}: {e}") from e
        else:
            raise ToolError(f"{system} needs a tuned w_bc: pass --tuning with the adr-eval "
                            f"retrieval run of {system} on this store, or --w-bc N")
        if lexical_only:
            w, w_from = None, None
        elif weight is not None:
            w, w_from = float(weight), "override"
        elif rec is not None and rec["w"] is not None:
            w, w_from = float(rec["w"]), "tuning"
        else:
            raise ToolError(f"{system} needs a tuned fusion weight: pass --tuning with a "
                            f"(not lexical-only) adr-eval retrieval run of {system} on this "
                            f"store, or --weight W, or use --lexical-only")
        settings = Settings(w_bc=w_bc_value, prefix=spec.prefix,
                            rerank=spec.rerank and not lexical_only)
        return settings, w_bc_from, w, w_from, rec

    def _index_impl(self, system, lexical_only, w_bc, weight, tuning) -> IndexInfo:
        settings, w_bc_from, w, w_from, rec = self._settings(system, lexical_only, w_bc,
                                                             weight, tuning)
        dense = not lexical_only
        cache = make_embedding_cache(self.emb_cache) if dense else None
        reranker = make_reranker() if settings.rerank else None
        expected = StoreIndex.expected_fingerprint(self.store, settings, cache, reranker,
                                                   dense=dense)
        final = self.index_root / expected
        if (final / "meta.json").is_file():
            idx, source = StoreIndex.load(final, cache=cache, reranker=reranker), "loaded"
        else:
            idx, source = StoreIndex.build(self.store, settings, cache, reranker,
                                           dense=dense), "built"
            if idx.fingerprint != expected:
                raise StoreError(f"built index fingerprint {idx.fingerprint} differs from the "
                                 f"expected {expected}")
            tmp = self.index_root / f".{expected}.{os.getpid()}.tmp"
            shutil.rmtree(tmp, ignore_errors=True)
            idx.save(tmp)
            try:
                os.rename(tmp, final)
            except OSError:
                if not (final / "meta.json").is_file():
                    raise
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        tuning_info = None
        if rec is not None:
            same = rec["lexical_only"] == lexical_only and settings.w_bc == rec["w_bc"] and \
                (lexical_only or w == rec["w"])
            tuning_info = {**rec, "fingerprint_match":
                           (rec["fingerprint"] == idx.fingerprint) if same else None}
        info = IndexInfo(system=system, snapshot=self.snapshot, fingerprint=idx.fingerprint,
                         lexical_only=lexical_only, prefix=settings.prefix,
                         rerank=settings.rerank, w_bc=settings.w_bc, w_bc_from=w_bc_from, w=w,
                         w_from=w_from, n_chunks=len(idx.chunks), source=source,
                         path=str(final), tuning=tuning_info)
        write_atomic(self.index_root / "active.json",
                     (json.dumps(info.to_dict(), indent=2, sort_keys=True) + "\n").encode())
        self._index, self._active, self._chunks = idx, info.to_dict(), None
        return info

    # -- the active index -------------------------------------------------------------

    def _active_record(self) -> dict:
        if self._active is not None:
            return self._active
        path = self.index_root / "active.json"
        if not path.is_file():
            raise ToolError(f"{self.store_path}: no index; run `adr index` first")
        active = json.loads(path.read_text(encoding="utf-8"))
        if active["snapshot"] != self.snapshot:
            raise ToolError(f"the index ({active['system']}) is for snapshot "
                            f"{_short(active['snapshot'])}, the store is at "
                            f"{_short(self.snapshot)}; run `adr index` again")
        self._active = active
        return active

    def _active_index(self) -> tuple[StoreIndex, dict]:
        active = self._active_record()
        if self._index is None:
            dense = not active["lexical_only"]
            cache = make_embedding_cache(self.emb_cache) if dense else None
            reranker = make_reranker() if active["rerank"] else None
            idx = StoreIndex.load(self.index_root / active["fingerprint"], cache=cache,
                                  reranker=reranker)
            if idx.fingerprint != active["fingerprint"]:
                raise StoreError(f"{self.index_root}: loaded index {idx.fingerprint} is not the "
                                 f"active one {active['fingerprint']}")
            self._index = idx
        return self._index, active

    def _chunk_rows(self) -> dict[str, dict]:
        """The active index's chunks (from its saved file; no BM25 or vectors needed)."""
        if self._chunks is None and self._index is not None:
            self._chunks = {cid: asdict(c) for cid, c in self._index.chunks.items()}
        if self._chunks is None:
            active = self._active_record()
            path = self.index_root / active["fingerprint"] / "chunks.jsonl"
            rows = {}
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        row = json.loads(line)
                        rows[row["chunk_id"]] = row
            self._chunks = rows
        return self._chunks

    # -- search -----------------------------------------------------------------------

    def search(self, query: str, top: int = SEARCH_TOP) -> SearchResult:
        """The top chunks of the active index for `query`."""
        def run():
            if isinstance(top, bool) or not isinstance(top, int) or not 1 <= top <= CHANNEL_K:
                raise ToolError(f"top must be between 1 and {CHANNEL_K}, got {top!r}")
            idx, active = self._active_index()
            hits = []
            for rank, (cid, score) in enumerate(
                    idx.retrieve(query, fusion="linear", w=active["w"], top=top), start=1):
                c = idx.chunks[cid]
                hits.append(Hit(rank, cid, c.doc_id, c.char_start, c.char_end, c.breadcrumb,
                                score, self.snapshot))
            res = SearchResult(query, top, self.snapshot, active["system"],
                               active["lexical_only"], idx.fingerprint, active["w"], hits)
            return res, [h.chunk_id for h in hits], {"index": idx.fingerprint}

        return self._call("search", {"query": query, "top": top}, run)

    # -- read -------------------------------------------------------------------------

    def read(self, doc_id: str, start: int | None = None, end: int | None = None, *,
             element: str | None = None, chunk: str | None = None) -> ReadResult:
        """The exact text of a range of a document: `start`/`end` (either may be left out),
        an element, a chunk of the active index, or (none given) the whole document."""
        args = {"doc_id": doc_id, "start": start, "end": end, "element": element,
                "chunk": chunk}

        def run():
            res = self._read_impl(doc_id, start, end, element, chunk)
            return res, [[res.doc_id, res.char_start, res.char_end]], {}

        return self._call("read", args, run)

    def _read_impl(self, doc_id, start, end, element, chunk) -> ReadResult:
        modes = (start is not None or end is not None, element is not None, chunk is not None)
        if sum(modes) > 1:
            raise ToolError("give one of --start/--end, --element or --chunk")
        where = f"snapshot {_short(self.snapshot)}"
        doc_id = _resolve(doc_id, self.store.doc_ids(), "document", where)
        text = self.store.text(doc_id)
        element_id = chunk_id = None
        if element is not None:
            els = {e.element_id: e for e in self.store.elements(doc_id)}
            element_id = _resolve(element, sorted(els), "element", f"document {_short(doc_id)}")
            el = els[element_id]
            start, end = el.char_start, el.char_end
            if sha256_text(text[start:end]) != el.text_sha256:
                raise StoreError(f"element {element_id} does not re-slice to its text_sha256")
        elif chunk is not None:
            rows = self._chunk_rows()
            chunk_id = _resolve(chunk, sorted(rows), "chunk", "the active index")
            row = rows[chunk_id]
            if row["doc_id"] != doc_id:
                raise ToolError(f"chunk {_short(chunk_id)} belongs to document "
                                f"{_short(row['doc_id'])}, not {_short(doc_id)}")
            start, end = row["char_start"], row["char_end"]
            if text[start:end] != row["text"]:
                raise StoreError(f"chunk {chunk_id} does not re-slice to its text")
        start = 0 if start is None else start
        end = len(text) if end is None else end
        for name, v in (("start", start), ("end", end)):
            if isinstance(v, bool) or not isinstance(v, int):
                raise ToolError(f"{name} must be an integer, got {v!r}")
        if not 0 <= start <= end <= len(text):
            raise ToolError(f"range {start}:{end} is out of range for document "
                            f"{_short(doc_id)} (length {len(text)})")
        part = text[start:end]
        return ReadResult(self.snapshot, doc_id, self.store.source(doc_id).uri, start, end,
                          sha256_text(part), element_id, chunk_id, part)

    # -- grep -------------------------------------------------------------------------

    def grep(self, pattern: str, doc: str | None = None, max: int = GREP_MAX,
             ignore_case: bool = False) -> GrepResult:
        """Regular-expression matches in (doc_id, offset) order, at most `max`."""
        args = {"pattern": pattern, "doc": doc, "max": max, "ignore_case": ignore_case}

        def run():
            res = self._grep_impl(pattern, doc, max, ignore_case)
            return res, [[m.doc_id, m.char_start, m.char_end] for m in res.matches], {}

        return self._call("grep", args, run)

    def _grep_impl(self, pattern, doc, max_, ignore_case) -> GrepResult:
        if isinstance(max_, bool) or not isinstance(max_, int) or max_ < 1:
            raise ToolError(f"max must be a positive integer, got {max_!r}")
        if not pattern:
            raise ToolError("empty pattern; give a regular expression that matches some text")
        flags = re.MULTILINE | (re.IGNORECASE if ignore_case else 0)
        try:
            rx = re.compile(pattern, flags)
        except re.error as e:
            raise ToolError(f"bad regular expression {pattern!r}: {e}") from e
        empty = (f"pattern {pattern!r} can match the empty string, which would give a match "
                 f"at every position; make it match at least one character")
        if rx.search("") is not None:
            raise ToolError(empty)
        doc_ids = self.store.doc_ids()
        if doc is not None:
            doc = _resolve(doc, doc_ids, "document", f"snapshot {_short(self.snapshot)}")
            doc_ids = [doc]
        matches: list[GrepMatch] = []
        truncated = False
        for d in doc_ids:
            text = self.store.text(d)
            line, counted = 1, 0  # line number at offset `counted`
            for m in rx.finditer(text):
                if len(matches) == max_:
                    truncated = True
                    break
                if m.start() == m.end():
                    raise ToolError(empty)
                line += text.count("\n", counted, m.start())
                counted = m.start()
                matches.append(GrepMatch(d, m.start(), m.end(), line, m.group(0),
                                         _context(text, m.start(), m.end()), self.snapshot))
            if truncated:
                break
        return GrepResult(pattern, ignore_case, doc, max_, self.snapshot, truncated, matches)
