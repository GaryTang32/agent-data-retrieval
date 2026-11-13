r"""The retrieval tools over one store (spec §9): `index`, `search`, `read`, `grep`, and the
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
ties by chunk id); a reranked index scores its top `RERANK_TOP` (50) fused chunks only, so it
refuses a larger `top`. `search` and `read --chunk` load the active index the same way and
refuse a missing or damaged one (its directory, `active.json` or a field of it of the wrong
type, `chunks.jsonl`, or a fingerprint that does not recompute) with "run `adr index`".
Read returns `store.text(doc_id)[start:end]` (the store checks the text's hash; an element's
or chunk's range is checked against its own hash or text).

Grep runs a Python regular expression over every document of the snapshot in doc-id order,
matches in offset order, at most `max`. A pattern that is empty, or whose shortest match is
empty (`a*`, `^`, `\b`, `x|(?=y)`: the parser's minimum width is 0), is refused before
anything is scanned. Multi-line mode is Python's: `^` matches at the start of the text and
after each `\n`, `$` at the end and before each `\n`, and nothing else is a line break. On a
`\r\n` line, `$` is between the `\r` and the `\n` (`abc$` does not match "abc\r\n", `abc\r$`
does); a `\r` alone, a form feed `\f` (PDF page breaks) and the Unicode line separators are
not line breaks. `line` is 1 plus the number of `\n` before the match. `context` is the
match's `\n`-delimited line, clipped to `CONTEXT_CHARS` on each side, with `\r`, `\f`, tabs and
every other control character (and U+2028, U+2029) shown as a space. The scan runs in a
worker process (`adr_store.grep_worker`) with a deadline (`timeout`, default 10 s, at most
60 s) on the time spent matching; a pattern that runs longer (catastrophic backtracking, as
`(\w+\s?)+X`) is stopped and refused. Results are those of the same scan in process. The
worker limits its own CPU time and dies with its parent (see `adr_store.grep_worker`).
Limits: the pattern is compiled in this process, outside the deadline; the worker is
POSIX-only (it is handed its pipes as file descriptors).

Document, element and chunk ids may be given as a unique prefix of at least 8 characters;
results always carry full ids.

Every call, including a refused or failed one, appends one JSON line to the log (UTC time,
tool, arguments, snapshot id, result ids, and the error for a refused or failed call) with a
single `O_APPEND` write, after the result is computed; the log is never read, so it cannot
change a result. Every result names the snapshot it came from.
"""

from __future__ import annotations

import bisect
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from pathlib import Path
from re import _parser as re_parser

from adr_store import grep_worker
from adr_store.embedding import EmbeddingCache
from adr_store.records import sha256_text
from adr_store.retrieval import Settings, StoreIndex
from adr_store.retrieval.index import CHANNEL_K
from adr_store.retrieval.lexical import check_w_bc
from adr_store.retrieval.rerank import RERANK_TOP, CrossEncoderReranker
from adr_store.store import Store, StoreError, write_atomic

GREP_MAX = 100
GREP_TIMEOUT, GREP_TIMEOUT_MAX = 10.0, 60.0  # seconds a grep pattern may spend matching
GREP_BATCH_CHARS = 4_000_000  # text sent to the grep worker per request
GREP_WORKER = grep_worker.__file__  # the worker's script
WORKER_START = 60.0  # seconds the grep worker may take to start
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


def make_embedding_cache(cache_dir: Path = DEFAULT_EMB_CACHE, *,
                         threads: int = 1) -> EmbeddingCache:
    """The embedding cache of a dense index (tests replace this function); `threads` sets
    how the model runs, not the vectors (`EmbeddingCache`)."""
    return EmbeddingCache(Path(cache_dir), threads=threads)


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


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")


def _context(text: str, start: int, end: int) -> str:
    r"""The `\n`-delimited line around a match, clipped to `CONTEXT_CHARS` on each side, with
    every control character (and U+2028, U+2029) shown as a space."""
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
    return _CONTROL.sub(" ", out)


# the fields of active.json the tools use, with their types
ACTIVE_FIELDS = {"system": str, "snapshot": str, "fingerprint": str, "lexical_only": bool,
                 "rerank": bool, "w": float | int | type(None)}


def _damaged(e: Exception | str) -> ToolError:
    reason = e if isinstance(e, str) else f"{type(e).__name__}: {e}"
    return ToolError(f"active index missing or damaged: {reason}; run `adr index`")


class _GrepWorker:
    """A worker process answering scan requests (`grep_worker.serve`), with a deadline on the
    time spent waiting for its answers; stopped when the `with` block ends."""

    def __init__(self, timeout: float):
        self.timeout, self.left = timeout, timeout
        r_req, w_req = os.pipe()
        r_res, w_res = os.pipe()
        try:
            self.proc = subprocess.Popen(
                [sys.executable, "-I", GREP_WORKER, str(r_req), str(w_res), repr(float(timeout)),
                 str(os.getpid())],
                pass_fds=(r_req, w_res), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        except BaseException:
            for fd in (r_req, w_req, r_res, w_res):
                os.close(fd)
            raise
        os.close(r_req)
        os.close(w_res)
        self.requests = Connection(w_req, readable=False)
        self.responses = Connection(r_res, writable=False)

    def __enter__(self) -> _GrepWorker:
        try:
            ready = self._receive(WORKER_START)
            if ready is None:
                raise RuntimeError(f"the grep worker did not start within {WORKER_START:g} s")
            if ready != "ready":
                raise RuntimeError(f"the grep worker did not start properly ({ready!r})")
        except BaseException:
            self._stop()
            raise
        return self

    def __exit__(self, *exc) -> None:
        try:
            if exc[0] is None:
                self.requests.send(None)
                self.proc.wait(5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            self._stop()

    def _stop(self) -> None:
        """Stop the worker if it still runs, wait for it, close the pipes."""
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait()
        finally:
            self.requests.close()
            self.responses.close()

    def _receive(self, seconds: float):
        if not self.responses.poll(seconds):
            return None
        try:
            return self.responses.recv()
        except EOFError:
            try:
                code = self.proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                code = None
            raise RuntimeError(f"the grep worker stopped (exit code {code})") from None

    def scan(self, pattern: str, flags: int, limit: int, docs: list[tuple[str, str]]):
        """`grep_worker.scan` of `docs` in the worker, within what is left of the deadline."""
        self.requests.send((pattern, flags, limit, docs))
        t0 = time.monotonic()
        answer = self._receive(max(self.left, 0.0))
        self.left -= time.monotonic() - t0
        if answer is None:
            raise ToolError(f"pattern took longer than {self.timeout:g} s; simplify it")
        status, value = answer
        if status != "ok":
            raise RuntimeError(f"grep worker: {value}")
        return value


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
        except BaseException as e:  # refused, unexpected or interrupted: logged, re-raised
            if isinstance(e, (ToolError, StoreError)):
                error = str(e)
            elif isinstance(e, KeyboardInterrupt):
                error = "interrupted"
            else:
                error = f"unexpected {type(e).__name__}: {e}"
            self._append_log({**entry, "results": [], "error": error})
            if isinstance(e, StoreError):
                raise ToolError(str(e)) from e
            raise
        self._append_log({**entry, **extra, "results": ids})
        return result

    # -- index ------------------------------------------------------------------------

    def index(self, system: str, *, lexical_only: bool = False, w_bc: int | None = None,
              weight: float | None = None, tuning: Path | None = None,
              threads: int = 1) -> IndexInfo:
        """Build or load the index of `system` for the HEAD snapshot and make it active.
        `threads` is the embedding model's thread count while building (0: all cores); the
        vectors, and so the index, do not depend on it."""
        args = {"system": system, "lexical_only": lexical_only, "w_bc": w_bc,
                "weight": weight, "tuning": None if tuning is None else str(tuning),
                "threads": threads}

        def run():
            info = self._index_impl(system, lexical_only, w_bc, weight, tuning, threads)
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

    def _index_impl(self, system, lexical_only, w_bc, weight, tuning,
                    threads: int = 1) -> IndexInfo:
        settings, w_bc_from, w, w_from, rec = self._settings(system, lexical_only, w_bc,
                                                             weight, tuning)
        dense = not lexical_only
        cache = make_embedding_cache(self.emb_cache, threads=threads) if dense else None
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
        # queries are embedded single-threaded, as by the baseline: an index built with
        # other threads is reloaded with the default cache on the next search
        self._index = idx if threads == 1 else None
        self._active, self._chunks = info.to_dict(), None
        return info

    # -- the active index -------------------------------------------------------------

    def _active_record(self) -> dict:
        if self._active is not None:
            return self._active
        path = self.index_root / "active.json"
        if not path.is_file():
            raise ToolError(f"{self.store_path}: no index; run `adr index` first")
        try:
            active = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(active, dict):
                raise TypeError(f"not an object: {type(active).__name__}")
            missing = [k for k in ACTIVE_FIELDS if k not in active]
            if missing:
                raise KeyError(", ".join(missing))
            for k, kind in ACTIVE_FIELDS.items():
                v = active[k]
                if not isinstance(v, kind) or (kind is not bool and isinstance(v, bool)) or \
                        (kind is str and not v):
                    raise TypeError(f"{k} {_short(repr(v))}")
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as e:
            raise _damaged(f"{path}: {type(e).__name__}: {e}") from e
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
            try:
                idx = StoreIndex.load(self.index_root / active["fingerprint"], cache=cache,
                                      reranker=reranker)
            except (OSError, ValueError, KeyError, TypeError, RecursionError) as e:
                raise _damaged(e) from e
            if idx.fingerprint != active["fingerprint"]:
                raise _damaged(f"{self.index_root}: loaded index {idx.fingerprint} is not the "
                               f"active one {active['fingerprint']}")
            self._index = idx
        return self._index, active

    def _chunk_rows(self) -> dict[str, dict]:
        """The active index's chunks, from the index as `search` loads it (so its fingerprint
        is checked the same way)."""
        if self._chunks is None:
            idx, _ = self._active_index()
            self._chunks = {cid: asdict(c) for cid, c in idx.chunks.items()}
        return self._chunks

    # -- search -----------------------------------------------------------------------

    def search(self, query: str, top: int = SEARCH_TOP) -> SearchResult:
        """The top chunks of the active index for `query`."""
        def run():
            if isinstance(top, bool) or not isinstance(top, int) or not 1 <= top <= CHANNEL_K:
                raise ToolError(f"top must be between 1 and {CHANNEL_K}, got {top!r}")
            active = self._active_record()
            if active["rerank"] and top > RERANK_TOP:
                raise ToolError(f"the index ({active['system']}) reranks its top {RERANK_TOP} "
                                f"chunks only; ask for --top {RERANK_TOP} or fewer")
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
             ignore_case: bool = False, timeout: float = GREP_TIMEOUT) -> GrepResult:
        """Regular-expression matches in (doc_id, offset) order, at most `max`, within
        `timeout` seconds of matching."""
        args = {"pattern": pattern, "doc": doc, "max": max, "ignore_case": ignore_case,
                "timeout": timeout}

        def run():
            res = self._grep_impl(pattern, doc, max, ignore_case, timeout)
            return res, [[m.doc_id, m.char_start, m.char_end] for m in res.matches], {}

        return self._call("grep", args, run)

    def _grep_impl(self, pattern, doc, max_, ignore_case, timeout) -> GrepResult:
        if isinstance(max_, bool) or not isinstance(max_, int) or max_ < 1:
            raise ToolError(f"max must be a positive integer, got {max_!r}")
        if isinstance(timeout, bool) or not isinstance(timeout, int | float) or \
                not 0 < timeout <= GREP_TIMEOUT_MAX:
            raise ToolError(f"timeout must be more than 0 and at most {GREP_TIMEOUT_MAX:g} "
                            f"seconds, got {timeout!r}")
        if not pattern:
            raise ToolError("empty pattern; give a regular expression that matches some text")
        flags = re.MULTILINE | (re.IGNORECASE if ignore_case else 0)
        try:
            rx = re.compile(pattern, flags)
            min_width = re_parser.parse(pattern, flags).getwidth()[0]
        except re.error as e:
            raise ToolError(f"bad regular expression {pattern!r}: {e}") from e
        empty = (f"pattern {pattern!r} can match the empty string, which would give a match "
                 f"at every position; make it match at least one character")
        if min_width == 0 or rx.search("") is not None:
            raise ToolError(empty)
        doc_ids = self.store.doc_ids()
        if doc is not None:
            doc = _resolve(doc, doc_ids, "document", f"snapshot {_short(self.snapshot)}")
            doc_ids = [doc]
        matches: list[GrepMatch] = []
        status = grep_worker.DONE
        with _GrepWorker(timeout) as worker:
            i = 0
            while i < len(doc_ids) and status == grep_worker.DONE:
                batch, size = [], 0  # documents in order, up to GREP_BATCH_CHARS (at least one)
                while i < len(doc_ids) and (not batch or size < GREP_BATCH_CHARS):
                    text = self.store.text(doc_ids[i])
                    batch.append((doc_ids[i], text))
                    size += len(text)
                    i += 1
                found, status = worker.scan(pattern, flags, max_ - len(matches), batch)
                texts = dict(batch)
                matches += [GrepMatch(d, start, end, line, texts[d][start:end],
                                      _context(texts[d], start, end), self.snapshot)
                            for d, start, end, line in found]
        if status == grep_worker.EMPTY:  # the minimum-width check should have caught it
            raise ToolError(empty)
        return GrepResult(pattern, ignore_case, doc, max_, self.snapshot,
                          status == grep_worker.MORE, matches)
