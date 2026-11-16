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

Applicability filters (Phase 2 spec §4.4, §6.1). `search`, `grep` and `read` take the same
`filters` (`applicability.Filters`, or a dict as `Filters.parse` takes it; None is the
default). The applicability overlay of the store's HEAD snapshot is loaded when present (a
damaged one is refused). The default excludes superseded documents, `include_superseded`
drops that, `as_of`, `status`, `jurisdiction` and `max_tier` as §4.4. Search masks the
excluded documents inside the index before each channel's top-k cut (a filter never starves
the result); when the filters exclude nothing it is the Phase 1 call itself. Grep scans only
the admitted documents. A read, or a doc-scoped grep, of a document the filters exclude is
refused with the reason ("document <id> is excluded by the filters (<reason>); pass
include_superseded or another as_of"): filters are not secret. Without an overlay, filters
that read envelope fields (`Filters.needs_overlay`) are refused ("no applicability overlay;
run `adr applicability derive`") and the default and `include_superseded` exclude nothing
(the Phase 1 behaviour). Results carry `applicability` (the overlay id, or None), `filters`
(the filters applied, as `Filters.to_dict`) and, for search and grep, `excluded_by_filter`
(how many documents of the caller's view the filters excluded; for a doc-scoped grep, of
that one document). Log lines of these tools carry the
caller's `filters` in `args`, and `filters` and `applicability` beside them (null when the call
failed before they were known).

Dedup (Phase 2 spec §4.5). `search(..., dedup=None)` collapses copies when a dedup overlay
exists for the active index's chunks (`adr dedup build`; `dedup.load_overlay`, a damaged one
is refused; an overlay of other chunks, e.g. before a rechunk, is not theirs), `dedup=True`
requires one (refused with `dedup.missing`'s reason, which ends "run `adr dedup build`"), and
`dedup=False` is the uncollapsed ranking (the overlay is not read). Collapse walks the index's
full ranking (`StoreIndex.ranking`: the top 200 fused candidates, then every other candidate,
ranked only if the 200 run out), masked by the filters as above, and gives one hit per
connected component of a cluster's edges among the chunks the filters admit: the component's
canonical chunk with the best-ranked member's score (`scored_by`) and the other admitted
members as `alternates`. So a collapsed result has `top` hits unless fewer components match.
A reranked index collapses its reranked top 50 only; when that gives fewer than `top` hits
while the full ranking has more components, `short_by` says how many (0 otherwise, and
always 0 without a reranker or without collapse). Without collapse `scored_by` is the hit
itself and `alternates` is empty. The result carries `dedup` (the overlay id, or None) and
`dedup_note` (None when collapsed, else why not: `dedup.OFF`, or `dedup.missing`'s reason);
log lines of `search` carry `dedup`.

Per call (Phase 2 spec §5.5, planner's call 12). Every call re-reads HEAD (a new content
snapshot is used from the next call on), `index/active.json` (a new active index is loaded),
and stats the applicability and dedup overlays, reusing a parse while the file is unchanged;
nothing is cached as "absent". So a long-running process sees every change on its next call.

Permissions (Phase 2 spec §5.3–§5.6, §6.2). `Tools(..., acl=True, caller=USER)` resolves the
caller's access on entry to every call (`acl.resolve`: F1–F5, one ACL snapshot for the whole
call, `clock` for F3); a denial is an `AccessDenied` ("access denied (F<n>): <reason>") and
the call returns nothing. An allowed call sees only the caller's view (the documents whose
access list meets the caller's principals; no entry or an empty list: no one):
- search: `StoreIndex.retrieve(..., allowed_docs = view ∩ admitted, lexical = the view's
  BM25)`; the dense channel masks the shared vectors to the same set. The view's BM25 has
  statistics over the view's chunks only (no IDF side channel), from an LRU of `VIEW_CACHE`
  (32) by (index fingerprint, view id); a view of every chunk uses the index's own BM25, so
  a caller who sees everything gets the results of `acl=False`. Dedup components are
  restricted to visible, admitted members: a member outside the view is never shown, listed
  or counted, and never joins two visible ones.
- grep scans the visible, admitted documents only; read and a doc-scoped grep resolve ids
  (and prefixes) among visible ids only, so an invisible document, element or chunk gets
  byte for byte the message of a nonexistent one (an invisible document that the filters
  would exclude is "not found" too: the filter message is for visible documents).
- every count (`excluded_by_filter`, `truncated`, matches, `short_by`) covers the view.
- the dense channel scores each row by `dense.row_scores` (a function of row and query
  alone), a full view included, so scores equal a view-only store's bit for bit; acl=False
  keeps the Phase 1 matrix product (the two may differ in the last float32 bits).
- a view that holds some but not all versions of a chain is denied F1 (all versions of a
  source share access; `adr acl sync` refuses a policy that splits one).
`index`, `active_index` and `active_system` are operator calls, refused with the ACL layer
(`index` after access is resolved: logged `allowed` with the refusal as its error, or
`denied:F<n>`). `acl=False` is the tools without an ACL layer, as in Phase 1.

Every call, including a refused or failed one, appends one JSON line to the log (UTC time,
tool, arguments, snapshot id, result ids, and the error for a refused or failed call) with a
single `O_APPEND` write, after the result is computed; the log is never read, so it cannot
change a result. Every line carries `caller` (as given), `principals`, `acl_snapshot`,
`acl_decision` (`allowed`, `denied:F1`…`denied:F5`, or `off` without the ACL layer), `view`
and `not_visible` (the invisible ids a read or doc-scoped grep named, for audit only; [] when
none), null when not resolved. Every result names the snapshot it came from.

Tools as data (Phase 2 spec §8.2, §5.4). `search_tools(query, top, filters)` ranks the tools of
the store's tool catalog (`<store>/tools`, `adr_store.tool_catalog`) with the active tool index
(`tools_index(w_name, weight=, lexical_only=)` builds or loads a `ToolIndex` for `tools/HEAD`
under `<store>/tools/index/<fingerprint>/` and writes `<store>/tools/index/active.json`; an
operator call, refused with the ACL layer); a hit carries `rank`, `tool_id`, `name`, `summary`
(the first sentence of the description, at most 200 characters), `source_kind`, `source_uri`,
`score` and `tools_snapshot`, never the schema. `filters` is `{"source_kind": [...]}` (mcp,
openapi, toolret): a mask within the caller's tool view, like the applicability filters (it
changes no statistic; `excluded_by_filter` counts the view's tools it excluded).
`load_tool(tool_id)` returns the MCP Tool definition (`tool_records.definition`), the source
fields and `tools_snapshot`; a unique prefix of at least 8 characters resolves among the
caller's visible tools only. With the ACL layer:
- both see only the tools whose access list meets the caller's principals; an invisible tool
  does not exist (byte for byte the message of a nonexistent id; the invisible ids named are
  logged in `not_visible`);
- search scores with BM25 statistics over the caller's tool view (an LRU of `VIEW_CACHE` by
  (tool index fingerprint, tool view id), the tool view id being the SHA-256 of the sorted
  visible tool ids: `Access.view` hashes documents only, so two callers with one document view
  and different tool views never share statistics; a view of every indexed tool uses the
  index's own BM25) and the row-exact dense kernel, so results equal those of a catalog of the
  view's tools only;
- fail closed on the catalog (planner's call: code F2, the rule for content snapshots): the
  ACL snapshot's `tool_snapshot` must be `tools/HEAD` (a catalog changed since the last sync,
  a missing, unreadable or malformed `tools/HEAD` while the ACL names a tool snapshot, or an
  ACL snapshot without a tool snapshot while a catalog exists, all deny), and the tool
  snapshot file must read and hash to its id. With neither a catalog nor a tool snapshot the
  call is refused ("no tool catalog"); nothing is hidden there.
- a tool the ACL lists but the catalog lacks, or whose record does not match its snapshot
  hash, is "not found" with exactly the message of a nonexistent id (the reason is logged in
  `tool_error`, never returned).
Log lines of the tool tools carry `tools_snapshot`, `tool_index`, `tool_view`, `filters` and
`tool_error` beside the fields above.
"""

from __future__ import annotations

import bisect
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from itertools import chain
from multiprocessing.connection import Connection
from pathlib import Path
from re import _parser as re_parser

import numpy as np

from adr_store import acl as acl_mod
from adr_store import dedup as dedup_mod
from adr_store import grep_worker
from adr_store.acl import Access, AclDenied
from adr_store.applicability import (
    Applicability,
    Filters,
    exclusion_reason,
    load_overlay,
    overlay_path,
)
from adr_store.embedding import EmbeddingCache
from adr_store.records import sha256_text
from adr_store.retrieval import Settings, StoreIndex
from adr_store.retrieval.index import CHANNEL_K, chunk_content_sha256
from adr_store.retrieval.lexical import FieldBM25, check_w_bc, doc_mask
from adr_store.retrieval.rerank import RERANK_TOP, CrossEncoderReranker
from adr_store.retrieval.tool_index import ToolIndex, tool_view_id
from adr_store.store import Store, StoreError, write_atomic
from adr_store.tool_catalog import ToolCatalog
from adr_store.tool_records import definition as tool_definition

GREP_MAX = 100
GREP_TIMEOUT, GREP_TIMEOUT_MAX = 10.0, 60.0  # seconds a grep pattern may spend matching
GREP_BATCH_CHARS = 4_000_000  # text sent to the grep worker per request
GREP_WORKER = grep_worker.__file__  # the worker's script
WORKER_START = 60.0  # seconds the grep worker may take to start
SEARCH_TOP = 10
CONTEXT_CHARS = 80  # characters of context on each side of a grep match
MIN_PREFIX = 8
DEFAULT_EMB_CACHE = Path(".cache/emb")
NO_OVERLAY = "no applicability overlay; run `adr applicability derive`"
VIEW_CACHE = 32  # per-view BM25 indexes kept in memory (LRU by index fingerprint and view)
_VIEW_LEXICAL: OrderedDict[tuple[str, str], FieldBM25] = OrderedDict()
_VIEW_LOCK = threading.Lock()
_TOOL_VIEW_LEXICAL: OrderedDict[tuple[str, str], FieldBM25] = OrderedDict()
SOURCE_KINDS = ("mcp", "openapi", "toolret")
CHAIN_CACHE = 8  # chain maps kept in memory, by content snapshot id
_CHAINS: OrderedDict[str, dict[str, tuple[str, ...]]] = OrderedDict()
OPERATOR_UNDER_ACL = ("{} is an operator call (the whole index, unfiltered) and does not run "
                      "with the ACL layer; use Tools(acl=False)")
INDEX_UNDER_ACL = ("index is an operator call and does not run with the ACL layer; use "
                   "Tools(acl=False) (`adr index`)")


class ToolError(Exception):
    """A call the tools refuse, with a message for the caller (exit code 2 on the CLI)."""


class AccessDenied(ToolError):
    """No access for the whole call (fail-closed rule `code`, F1–F5 of §5.4); the message
    is `access denied (F<n>): <reason>`."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


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
    scored_by: str | None = None  # the chunk whose score this is (itself without collapse)
    alternates: list[dedup_mod.Alternate] = field(default_factory=list)


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
    applicability: str | None = None
    filters: dict = field(default_factory=lambda: Filters().to_dict())
    excluded_by_filter: int = 0
    dedup: str | None = None  # the dedup overlay id when collapsed
    dedup_note: str | None = None  # why not collapsed (None when collapsed)
    short_by: int = 0  # slots a reranked collapse is missing although more components match


@dataclass(frozen=True)
class ReadResult(_Result):
    snapshot: str
    doc_id: str
    uri: str
    path: str | None  # loose files: the document's path in the folder now (the snapshot's)
    char_start: int
    char_end: int
    text_sha256: str
    element_id: str | None
    chunk_id: str | None
    text: str
    applicability: str | None = None
    filters: dict = field(default_factory=lambda: Filters().to_dict())


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
    applicability: str | None = None
    filters: dict = field(default_factory=lambda: Filters().to_dict())
    excluded_by_filter: int = 0


@dataclass(frozen=True)
class ToolIndexInfo(_Result):
    tool_snapshot: str
    fingerprint: str
    w_name: int
    w: float | None
    lexical_only: bool
    n_tools: int
    source: str  # "built" or "loaded"
    path: str


@dataclass(frozen=True)
class ToolHit(_Result):
    rank: int
    tool_id: str
    name: str
    summary: str
    source_kind: str
    source_uri: str
    score: float
    tools_snapshot: str


@dataclass(frozen=True)
class SearchToolsResult(_Result):
    query: str
    top: int
    tools_snapshot: str
    fingerprint: str
    lexical_only: bool
    w_name: int
    w: float | None
    hits: list[ToolHit] = field(default_factory=list)
    filters: dict = field(default_factory=lambda: {"source_kind": None})
    excluded_by_filter: int = 0


@dataclass(frozen=True)
class LoadToolResult(_Result):
    tool_id: str
    definition: dict
    source_kind: str
    source_uri: str
    source_version: str
    operation: dict | None
    license: str
    definition_tokens: int
    tools_snapshot: str


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


def _filters_arg(filters: object) -> object:
    """The caller's `filters` as logged: a `Filters` as its dict, anything else as JSON."""
    if isinstance(filters, Filters):
        return filters.to_dict()
    try:
        return json.loads(json.dumps(filters, default=str))
    except (TypeError, ValueError, RecursionError):
        return repr(filters)


@dataclass(frozen=True)
class _Applied:
    """The filters of one call and what they admit: `allowed` None when they exclude
    nothing (the Phase 1 path)."""

    filters: Filters
    overlay: Applicability | None
    allowed: frozenset[str] | None
    excluded: int

    def reason(self, doc_id: str) -> str | None:
        if self.overlay is None:
            return None
        return exclusion_reason(self.overlay.records[doc_id], self.filters)

    def refuse_excluded(self, doc_id: str) -> None:
        reason = self.reason(doc_id)
        if reason is not None:
            raise ToolError(f"document {doc_id} is excluded by the filters ({reason}); pass "
                            f"include_superseded or another as_of")

    def fields(self) -> dict:
        return {"applicability": None if self.overlay is None else self.overlay.overlay_id,
                "filters": self.filters.to_dict()}


_UNLOADED = object()


# the fields of active.json the tools use, with their types
ACTIVE_FIELDS = {"system": str, "snapshot": str, "fingerprint": str, "lexical_only": bool,
                 "rerank": bool, "w": float | int | type(None)}


def _damaged(e: Exception | str) -> ToolError:
    reason = e if isinstance(e, str) else f"{type(e).__name__}: {e}"
    return ToolError(f"active index missing or damaged: {reason}; run `adr index`")


def _stat_key(path: Path) -> tuple | None:
    """What identifies a file's current version for a cache (device, inode, size, mtime and
    ctime in ns), or None when there is no such file."""
    try:
        st = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _hidden_matches(given: object, visible: list[str], everything: list[str]) -> list[str]:
    """The ids of `everything` (sorted) not in `visible` that `given` names: itself, or the
    ids it is a prefix of (at least `MIN_PREFIX` characters), for the audit log only."""
    if not isinstance(given, str) or not given:
        return []
    shown = set(visible)
    i = bisect.bisect_left(everything, given)
    out = []
    while i < len(everything) and everything[i].startswith(given):
        if (everything[i] == given or len(given) >= MIN_PREFIX) and everything[i] not in shown:
            out.append(everything[i])
        i += 1
    return out


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
    """The tools over the store at `store_path`. Every call re-reads HEAD (and so sees a new
    content snapshot), `index/active.json`, the overlays and, with `acl`, `acl/HEAD`.

    `acl=False` is the tools without an ACL layer (Phase 1 behaviour; log `acl_decision`
    "off"). `acl=True` resolves the caller's access on entry to every call (`acl.resolve`,
    one ACL snapshot per call, `clock` for F3) and enforces it; `caller` is a `user:`
    principal. Calls on one instance run one at a time.

    Only the tool methods (`search`, `read`, `grep`, `search_tools`, `load_tool`) serve a
    caller; the MCP layer (Task 12) must call nothing else. `index`, `tools_index`,
    `active_index`, `active_system` and `active_tool_index` are operator calls, refused with
    the ACL layer (`index` and `tools_index` after resolving access, so they are logged with
    the caller's decision)."""

    def __init__(self, store_path: Path, *, emb_cache: Path = DEFAULT_EMB_CACHE,
                 acl: bool = False, caller: str | None = None,
                 clock: Callable[[], datetime] = acl_mod.utc_now):
        if not isinstance(acl, bool):
            raise ToolError(f"acl must be true or false, got {acl!r}")
        self.store_path = Path(store_path)
        try:
            self.store = Store.open(self.store_path)
        except StoreError as e:
            raise ToolError(str(e)) from e
        self.snapshot: str = self.store.snapshot_id
        self.emb_cache = Path(emb_cache)
        self.acl, self.caller, self.clock = acl, caller, clock
        self._lock = threading.RLock()
        self._index: StoreIndex | None = None
        self._memo: dict = {}  # per call: active.json, as read once
        self._chunks: tuple[str, dict[str, dict]] | None = None  # (fingerprint, rows)
        self._content: tuple[str, str] | None = None  # (fingerprint, chunk_content_sha256)
        self._overlay: tuple[tuple, Applicability] | None = None  # (file key, overlay)
        # (key: fingerprint, snapshot, file or directory state), overlay or None, why none
        self._dedup: tuple[tuple, dedup_mod.Dedup | None, str | None] | None = None
        self._acl_cache: OrderedDict = OrderedDict()  # parsed ACL snapshots by id
        self._access_now: Access | None = None  # the access of the call running
        self._not_visible: list[str] | None = None  # requested ids that were invisible
        self._in_call = False
        self._tool_index: ToolIndex | None = None
        self._tool_catalog: tuple[tuple, ToolCatalog] | None = None  # (file key, catalog)
        self._catalog_now: ToolCatalog | None = None  # the checked catalog of the call

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

    def _logged_caller(self) -> str | None:
        c = self.caller
        return c if c is None or isinstance(c, str) else repr(c)

    def _call(self, tool: str, args: dict, fn: Callable[[], tuple[object, list, dict]],
              fields: dict | None = None, *, tool_call: bool = False):
        """Run one tool call and log it; `fn` returns (result, result ids, extra fields).
        `fields` are logged on every line, refused or not: `fn` fills in what it learns.
        On entry the call re-reads HEAD and, with the ACL layer, resolves the caller's access,
        which `fn` sees as `self._access_now` (`tool_call`: and checks the tool catalog
        against it, `_check_tools`)."""
        with self._lock:
            when = datetime.now(UTC).isoformat()
            fields = {} if fields is None else fields
            acl_fields = {"caller": self._logged_caller(), "principals": None,
                          "acl_snapshot": None, "acl_decision": None if self.acl else "off",
                          "view": None, "not_visible": None}
            self._memo, self._access_now, self._not_visible = {}, None, None
            self._catalog_now = None
            self._in_call = True
            try:
                self._refresh()
                if self.acl:
                    self._enter(acl_fields, tool_call)
                result, ids, extra = fn()
            except BaseException as e:  # refused, unexpected or interrupted: logged, re-raised
                if isinstance(e, (ToolError, StoreError)):
                    error = str(e)
                elif isinstance(e, KeyboardInterrupt):
                    error = "interrupted"
                else:
                    error = f"unexpected {type(e).__name__}: {e}"
                acl_fields["not_visible"] = self._not_visible
                self._append_log({"time": when, "tool": tool, "args": args,
                                  "snapshot": self.snapshot, **fields, **acl_fields,
                                  "results": [], "error": error})
                if isinstance(e, StoreError):
                    raise ToolError(str(e)) from e
                raise
            finally:
                self._access_now, self._memo, self._in_call = None, {}, False
                self._catalog_now = None
            acl_fields["not_visible"] = self._not_visible
            self._append_log({"time": when, "tool": tool, "args": args,
                              "snapshot": self.snapshot, **fields, **acl_fields, **extra,
                              "results": ids})
            return result

    # -- the content snapshot and access ------------------------------------------------

    def _refresh(self) -> None:
        """Re-read HEAD: a new content snapshot is used from the next call on (the same
        snapshot keeps the open store)."""
        try:
            head = (self.store_path / "HEAD").read_text(encoding="utf-8").strip()
        except OSError as e:
            raise StoreError(f"{self.store_path}: no store here (HEAD unreadable: "
                             f"{type(e).__name__})") from e
        if head != self.snapshot:
            store = Store.open(self.store_path, head)
            self.store, self.snapshot = store, store.snapshot_id

    def _chains(self) -> dict[str, tuple[str, ...]]:
        """The snapshot's chains of two or more documents (`acl.chains`), cached by content
        snapshot id (a snapshot's documents never change)."""
        with _VIEW_LOCK:
            if self.snapshot in _CHAINS:
                _CHAINS.move_to_end(self.snapshot)
                return _CHAINS[self.snapshot]
        found = acl_mod.chains(self.store)
        with _VIEW_LOCK:
            _CHAINS[self.snapshot] = found
            while len(_CHAINS) > CHAIN_CACHE:
                _CHAINS.popitem(last=False)
        return found

    def _resolve_access(self) -> Access:
        """The caller's access now (AclDenied F1–F5). A snapshot that gives the caller some
        but not all versions of a chain is F1 (all versions of a source share access, §5.2:
        superseded_by and valid_to would show versions the caller cannot see)."""
        access = acl_mod.resolve(self.store_path, self.caller, self.snapshot,
                                 clock=self.clock, cache=self._acl_cache)
        if acl_mod.split_chain(self._chains(), access.docs) is not None:
            raise AclDenied("F1", f"the ACL snapshot {access.acl_snapshot[:12]} splits a chain "
                                  f"across access lists (all versions of a source share "
                                  f"access); fix the policy and run `adr acl sync`",
                            access.acl_snapshot)
        return access

    def _enter(self, acl_fields: dict, tool_call: bool = False) -> None:
        """Resolve the call's access (and for a tool tool, check the catalog against it); a
        denial is an AccessDenied, logged with its code."""
        try:
            access = self._resolve_access()
            if tool_call:
                self._catalog_now = self._check_tools(access)
        except AclDenied as e:
            acl_fields.update(acl_decision=f"denied:{e.code}", acl_snapshot=e.acl_snapshot)
            raise AccessDenied(e.code, str(e)) from e
        acl_fields.update(principals=list(access.principals), acl_snapshot=access.acl_snapshot,
                          acl_decision="allowed", view=access.view)
        self._access_now, self._not_visible = access, []

    def _access(self) -> Access | None:
        """The caller's access to the store as it is now (None without the ACL layer); a
        denial raises AccessDenied (not logged: not a tool call)."""
        with self._lock:
            self._refresh()
            if not self.acl:
                return None
            try:
                return self._resolve_access()
            except AclDenied as e:
                raise AccessDenied(e.code, str(e)) from e

    def _doc_ids(self) -> list[str]:
        """The sorted document ids this call may see: the snapshot's, or with the ACL layer
        those of the caller's view."""
        ids = self.store.doc_ids()
        a = self._access_now
        return ids if a is None else [d for d in ids if d in a.docs]

    def _find(self, given: str, visible: list[str], everything: list[str], what: str,
              where: str) -> str:
        """`_resolve` among the visible ids only; with the ACL layer, the invisible ids the
        request named are noted for the log (never returned)."""
        try:
            return _resolve(given, visible, what, where)
        except ToolError:
            if self._not_visible is not None and len(visible) < len(everything):
                self._not_visible += _hidden_matches(given, visible, everything)
            raise

    def _projection(self) -> np.ndarray:
        """The caller's visibility mask over the active index's chunks (in its chunk order):
        a pure function of (index, ACL snapshot, caller); all true without the ACL layer.
        Private: it carries the index's global chunk count."""
        access = self._access()
        with self._lock:
            idx = self._active_index()[0]
        doc_ids = np.array([c.doc_id for c in idx.chunks.values()], dtype=str)
        if access is None:
            return np.ones(len(doc_ids), dtype=bool)
        return doc_mask(doc_ids, access.docs)

    @staticmethod
    def _view_lexical(idx: StoreIndex, access: Access) -> FieldBM25:
        """BM25 over the chunks of the caller's view (§6.2: statistics per view, so a hidden
        document moves no score), from an LRU of `VIEW_CACHE` by (index fingerprint, view);
        the index's own BM25 when the view holds every chunk."""
        chunks = [c for c in idx.chunks.values() if c.doc_id in access.docs]
        if len(chunks) == len(idx.chunks):
            return idx.lexical
        key = (idx.fingerprint, access.view)
        with _VIEW_LOCK:
            if key in _VIEW_LEXICAL:
                _VIEW_LEXICAL.move_to_end(key)
                return _VIEW_LEXICAL[key]
        lex = FieldBM25(idx.lexical.w_bc, idx.lexical.bm25.k1, idx.lexical.bm25.b)
        lex.build(chunks)
        with _VIEW_LOCK:
            _VIEW_LEXICAL[key] = lex
            _VIEW_LEXICAL.move_to_end(key)
            while len(_VIEW_LEXICAL) > VIEW_CACHE:
                _VIEW_LEXICAL.popitem(last=False)
        return lex

    # -- applicability ------------------------------------------------------------------

    def _applicability(self) -> Applicability | None:
        """The applicability overlay of the snapshot, or None: a stat on every call, the
        parse reused while the file is the same."""
        key = _stat_key(overlay_path(self.store_path, self.snapshot))
        if key is None:
            return None
        key = (self.snapshot, key)
        if self._overlay is not None and self._overlay[0] == key:
            return self._overlay[1]
        overlay = load_overlay(self.store_path, self.snapshot)
        self._overlay = None if overlay is None else (key, overlay)
        return overlay

    def _apply(self, filters: object, fields: dict) -> _Applied:
        """Parse the caller's filters and work out what they admit among the documents the
        call may see (logged in `fields`). `allowed` is None only when nothing is excluded
        by the filters or hidden by the ACL (the Phase 1 path); counts cover the view."""
        try:
            f = Filters.parse(filters)
        except (ValueError, TypeError) as e:
            raise ToolError(f"bad filters: {e}") from e
        fields["filters"] = f.to_dict()
        docs = self._doc_ids()
        hidden = self._access_now is not None and len(docs) < len(self.store.doc_ids())
        overlay = self._applicability()
        if overlay is None:
            if f.needs_overlay():
                raise ToolError(NO_OVERLAY)
            return _Applied(f, None, frozenset(docs) if hidden else None, 0)
        fields["applicability"] = overlay.overlay_id
        admitted, excluded = overlay.allowed_docs(docs, f)
        return _Applied(f, overlay, admitted if excluded or hidden else None, excluded)

    @staticmethod
    def _filter_fields() -> dict:
        return {"filters": None, "applicability": None}

    # -- index ------------------------------------------------------------------------

    def index(self, system: str, *, lexical_only: bool = False, w_bc: int | None = None,
              weight: float | None = None, tuning: Path | None = None,
              threads: int = 1) -> IndexInfo:
        """Build or load the index of `system` for the HEAD snapshot and make it active.
        `threads` is the embedding model's thread count while building (0: all cores); the
        vectors, and so the index, do not depend on it. A lexical-only index ignores it."""
        args = {"system": system, "lexical_only": lexical_only, "w_bc": w_bc,
                "weight": weight, "tuning": None if tuning is None else str(tuning),
                "threads": threads}

        def run():
            if self.acl:
                raise ToolError(INDEX_UNDER_ACL)
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
        # queries are embedded single-threaded, as by the baseline: a dense index built with
        # other threads is reloaded with the default cache on the next search (a lexical
        # index has no embedding model, so `threads` does not apply to it)
        self._index = idx if threads == 1 or lexical_only else None
        self._memo["active"] = info.to_dict()
        return info

    # -- the active index -------------------------------------------------------------

    def _active_record(self) -> dict:
        """`active.json`, read (and checked) once per call; outside a call on every use."""
        if "active" in self._memo:
            return self._memo["active"]
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
        self._memo["active"] = active
        return active

    def _active_index(self) -> tuple[StoreIndex, dict]:
        active = self._active_record()
        if self._index is None or self._index.fingerprint != active["fingerprint"]:
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

    def active_index(self) -> StoreIndex:
        """The active index, loaded and checked as `search` loads it (not logged). An
        operator call: refused with the ACL layer."""
        if self.acl:
            raise ToolError(OPERATOR_UNDER_ACL.format("active_index"))
        with self._lock:
            if not self._in_call:
                self._refresh()
            return self._active_index()[0]

    def active_system(self) -> str:
        """The system name the active index was built as (`active.json`, checked). An
        operator call: refused with the ACL layer."""
        if self.acl:
            raise ToolError(OPERATOR_UNDER_ACL.format("active_system"))
        with self._lock:
            if not self._in_call:
                self._refresh()
            return self._active_record()["system"]

    def _dedup_overlay(self, idx: StoreIndex) -> dedup_mod.Dedup | None:
        """The dedup overlay of the index's chunks, or None."""
        return self._dedup_state(idx)[0]

    def _content_sha256(self, idx: StoreIndex) -> str:
        if self._content is None or self._content[0] != idx.fingerprint:
            self._content = (idx.fingerprint, chunk_content_sha256(idx.chunks.values()))
        return self._content[1]

    def _dedup_state(self, idx: StoreIndex) -> tuple[dedup_mod.Dedup | None, str | None]:
        """(the dedup overlay of the index's chunks or None, why None): a stat on every call
        (of the file, or of its directory when there is none), the parse reused while that
        is unchanged."""
        content = self._content_sha256(idx)
        path = dedup_mod.overlay_path(self.store_path, self.snapshot, idx.chunker, content)
        state = _stat_key(path)
        key = (idx.fingerprint, self.snapshot, state,
               _stat_key(path.parent) if state is None else None)
        if self._dedup is None or self._dedup[0] != key:
            dd = dedup_mod.load_overlay(self.store_path, self.snapshot, idx.chunker, content)
            why = None if dd is not None else dedup_mod.missing(
                self.store_path, self.snapshot, idx.chunker, content)
            self._dedup = (key, dd, why)
        return self._dedup[1], self._dedup[2]

    def _chunk_rows(self) -> dict[str, dict]:
        """The active index's chunks, from the index as `search` loads it (so its fingerprint
        is checked the same way)."""
        idx, _ = self._active_index()
        if self._chunks is None or self._chunks[0] != idx.fingerprint:
            self._chunks = (idx.fingerprint, {cid: asdict(c) for cid, c in idx.chunks.items()})
        return self._chunks[1]

    # -- search -----------------------------------------------------------------------

    def search(self, query: str, top: int = SEARCH_TOP, *,
               filters: Filters | dict | None = None,
               dedup: bool | None = None) -> SearchResult:
        """The top chunks of the active index for `query` among the documents the filters
        admit; with dedup (None: on when a dedup overlay exists for the index's chunks),
        one slot per admitted cluster component, showing its canonical member."""
        fields = {**self._filter_fields(), "dedup": None}

        def run():
            if isinstance(top, bool) or not isinstance(top, int) or not 1 <= top <= CHANNEL_K:
                raise ToolError(f"top must be between 1 and {CHANNEL_K}, got {top!r}")
            if dedup is not None and not isinstance(dedup, bool):
                raise ToolError(f"dedup must be true, false or null, got {dedup!r}")
            applied = self._apply(filters, fields)
            active = self._active_record()
            if active["rerank"] and top > RERANK_TOP:
                raise ToolError(f"the index ({active['system']}) reranks its top {RERANK_TOP} "
                                f"chunks only; ask for --top {RERANK_TOP} or fewer")
            idx, active = self._active_index()
            dd, why = (None, dedup_mod.OFF) if dedup is False else self._dedup_state(idx)
            if dedup is True and dd is None:
                raise ToolError(why)
            # with the ACL layer, dense scores are row-exact (`dense.row_scores`), a full view
            # included, so they equal a view-only store's bit for bit; they may differ from
            # the acl=False scores (the Phase 1 matrix product) in the last float32 bits
            exact = self._access_now is not None
            lexical = None
            if self._access_now is not None:
                lexical = self._view_lexical(idx, self._access_now)
                lexical = None if lexical is idx.lexical else lexical
            if lexical is not None and applied.allowed is None:  # cannot happen: guard
                raise RuntimeError("a per-view BM25 without the view's mask")
            short_by = 0
            if dd is None:
                slots = [dedup_mod.Slot(cid, score, cid, ()) for cid, score in idx.retrieve(
                    query, fusion="linear", w=active["w"], top=top,
                    allowed_docs=applied.allowed, lexical=lexical, exact=exact)]
            else:
                fields["dedup"] = dd.overlay_id
                slots, short_by = self._collapsed(idx, active, query, top, applied, dd,
                                                  lexical, exact)
            hits = []
            for rank, slot in enumerate(slots, start=1):
                c = idx.chunks[slot.chunk_id]
                hits.append(Hit(rank, slot.chunk_id, c.doc_id, c.char_start, c.char_end,
                                c.breadcrumb, slot.score, self.snapshot, slot.scored_by,
                                list(slot.alternates)))
            res = SearchResult(query, top, self.snapshot, active["system"],
                               active["lexical_only"], idx.fingerprint, active["w"], hits,
                               **applied.fields(), excluded_by_filter=applied.excluded,
                               dedup=None if dd is None else dd.overlay_id,
                               dedup_note=why if dd is None else None, short_by=short_by)
            return res, [h.chunk_id for h in hits], {"index": idx.fingerprint}

        return self._call("search", {"query": query, "top": top,
                                     "filters": _filters_arg(filters), "dedup": dedup}, run,
                          fields)

    @staticmethod
    def _collapsed(idx: StoreIndex, active: dict, query: str, top: int, applied: _Applied,
                   dd: dedup_mod.Dedup, lexical: FieldBM25 | None = None,
                   exact: bool = False) -> tuple[list[dedup_mod.Slot], int]:
        """(the collapsed slots, short_by). Without a reranker: the collapse of the index's
        full ranking. A reranked index: the collapse of its reranked top 50, and how many
        more slots the full ranking after those 50 would fill, up to `top`. `applied.allowed`
        is the view's admitted documents (members outside it never join, show or count) and
        `lexical` the view's BM25; `exact` the row-exact dense kernel."""
        allowed = applied.allowed

        def admitted(cid: str) -> bool:
            return allowed is None or idx.chunks[cid].doc_id in allowed

        def collapse(ranked):
            return dedup_mod.collapse(ranked, dd, admitted, idx.chunks, applied.overlay,
                                      applied.filters.as_of, top)

        def full():
            return idx.ranking(query, w=active["w"], allowed_docs=allowed, lexical=lexical,
                               exact=exact)

        if idx.reranker is None:
            return collapse(full()), 0
        # the reranked head and the full ranking from one search of each channel (the
        # query is embedded once)
        head, rest = idx.retrieve_and_ranking(query, w=active["w"], top=RERANK_TOP,
                                              allowed_docs=allowed, lexical=lexical,
                                              exact=exact)
        slots = collapse(head)
        if len(slots) == top:
            return slots, 0
        seen = {cid for cid, _ in head}
        more = collapse(chain(head, ((cid, s) for cid, s in rest if cid not in seen)))
        return slots, len(more) - len(slots)

    # -- read -------------------------------------------------------------------------

    def read(self, doc_id: str, start: int | None = None, end: int | None = None, *,
             element: str | None = None, chunk: str | None = None,
             filters: Filters | dict | None = None) -> ReadResult:
        """The exact text of a range of a document: `start`/`end` (either may be left out),
        an element, a chunk of the active index, or (none given) the whole document. A
        document the filters exclude is refused with the reason."""
        args = {"doc_id": doc_id, "start": start, "end": end, "element": element,
                "chunk": chunk, "filters": _filters_arg(filters)}
        fields = self._filter_fields()

        def run():
            res = self._read_impl(doc_id, start, end, element, chunk, filters, fields)
            return res, [[res.doc_id, res.char_start, res.char_end]], {}

        return self._call("read", args, run, fields)

    def _read_impl(self, doc_id, start, end, element, chunk, filters=None,
                   fields=None) -> ReadResult:
        modes = (start is not None or end is not None, element is not None, chunk is not None)
        if sum(modes) > 1:
            raise ToolError("give one of --start/--end, --element or --chunk")
        applied = self._apply(filters, {} if fields is None else fields)
        where = f"snapshot {_short(self.snapshot)}"
        visible = self._doc_ids()
        doc_id = self._find(doc_id, visible, self.store.doc_ids(), "document", where)
        applied.refuse_excluded(doc_id)  # a visible document only: filters are not secret
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
            every = sorted(rows)
            seen = set(visible)
            shown = every if self._access_now is None else [
                c for c in every if rows[c]["doc_id"] in seen]
            chunk_id = self._find(chunk, shown, every, "chunk", "the active index")
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
        return ReadResult(self.snapshot, doc_id, self.store.source(doc_id).uri,
                          self.store.path_of(doc_id), start, end, sha256_text(part),
                          element_id, chunk_id, part, **applied.fields())

    # -- grep -------------------------------------------------------------------------

    def grep(self, pattern: str, doc: str | None = None, max: int = GREP_MAX,
             ignore_case: bool = False, timeout: float = GREP_TIMEOUT, *,
             filters: Filters | dict | None = None) -> GrepResult:
        """Regular-expression matches in (doc_id, offset) order, at most `max`, within
        `timeout` seconds of matching, in the documents the filters admit."""
        args = {"pattern": pattern, "doc": doc, "max": max, "ignore_case": ignore_case,
                "timeout": timeout, "filters": _filters_arg(filters)}
        fields = self._filter_fields()

        def run():
            res = self._grep_impl(pattern, doc, max, ignore_case, timeout, filters, fields)
            return res, [[m.doc_id, m.char_start, m.char_end] for m in res.matches], {}

        return self._call("grep", args, run, fields)

    def _grep_impl(self, pattern, doc, max_, ignore_case, timeout, filters=None,
                   fields=None) -> GrepResult:
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
        applied = self._apply(filters, {} if fields is None else fields)
        doc_ids = self._doc_ids()
        excluded = applied.excluded
        if doc is not None:
            doc = self._find(doc, doc_ids, self.store.doc_ids(), "document",
                             f"snapshot {_short(self.snapshot)}")
            applied.refuse_excluded(doc)
            doc_ids = [doc]
            excluded = 0  # of this one document, which refuse_excluded let through
        elif applied.allowed is not None:
            doc_ids = [d for d in doc_ids if d in applied.allowed]
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
                          status == grep_worker.MORE, matches, **applied.fields(),
                          excluded_by_filter=excluded)

    # -- tools as data ----------------------------------------------------------------

    @property
    def tool_index_root(self) -> Path:
        return self.store_path / "tools" / "index"

    def _tool_head(self) -> str | None:
        """`tools/HEAD` as written (stripped), None when there is no such file; one that
        cannot be read is a string that names no snapshot."""
        try:
            return (self.store_path / "tools" / "HEAD").read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as e:
            return f"<tools/HEAD unreadable: {type(e).__name__}>"

    def _open_catalog(self, snapshot: str) -> ToolCatalog:
        """The tool catalog at `snapshot` (StoreError when its file is missing or does not
        hash to its id), the parse reused while the snapshot file is unchanged."""
        path = self.store_path / "tools" / "snapshots" / f"{snapshot}.json"
        key = (snapshot, _stat_key(path))
        if self._tool_catalog is not None and self._tool_catalog[0] == key:
            return self._tool_catalog[1]
        try:
            cat = ToolCatalog.open(self.store_path, snapshot)
        except (OSError, ValueError) as e:  # a schema-invalid file (pydantic) or unreadable
            raise StoreError(f"{self.store_path}: tool snapshot {_short(snapshot)} unreadable "
                             f"({type(e).__name__})") from e
        self._tool_catalog = (key, cat)
        return cat

    def _check_tools(self, access: Access) -> ToolCatalog | None:
        """The tool catalog the call may read, checked against the ACL snapshot (AclDenied F2
        otherwise, module docstring); None when there is neither a catalog nor a tool
        snapshot."""
        head, synced = self._tool_head(), access.tool_snapshot
        sid = access.acl_snapshot
        if head is None and synced is None:
            return None
        if synced is None:
            raise AclDenied("F2", f"the ACL snapshot {sid[:12]} covers no tool catalog, the "
                                  f"store has one; run `adr acl sync`", sid)
        if head != synced:
            now = "none" if head is None else _short(head)
            raise AclDenied("F2", f"the ACL snapshot {sid[:12]} is for tool snapshot "
                                  f"{synced[:12]}, the tool catalog is at {now}; run "
                                  f"`adr acl sync`", sid)
        try:
            return self._open_catalog(synced)
        except StoreError as e:
            raise AclDenied("F2", f"tool snapshot {synced[:12]} of the ACL snapshot "
                                  f"{sid[:12]} cannot be read ({type(e).__name__}); fix the "
                                  f"tool catalog and run `adr acl sync`", sid) from e

    def _catalog(self) -> ToolCatalog:
        """The call's tool catalog: the one `_check_tools` checked, or without the ACL layer
        the one at `tools/HEAD`."""
        if self._access_now is not None:
            cat = self._catalog_now
        else:
            head = self._tool_head()
            cat = None if head is None else self._open_catalog(head)
        if cat is None:
            raise ToolError(f"{self.store_path}: no tool catalog here (no tools/HEAD); run "
                            f"`adr tools ingest` first")
        return cat

    def tools_index(self, w_name: int, *, weight: float | None = None,
                    lexical_only: bool = False, threads: int = 1) -> ToolIndexInfo:
        """Build or load the tool index of `tools/HEAD` with name weight `w_name` and fusion
        weight `weight` (none for a lexical-only index) and make it the active tool index.
        An operator call: refused with the ACL layer. `threads` as for `index`."""
        args = {"w_name": w_name, "weight": weight, "lexical_only": lexical_only,
                "threads": threads}

        def run():
            if self.acl:
                raise ToolError(INDEX_UNDER_ACL.replace("index is", "tools_index is")
                                .replace("`adr index`", "`adr tools index`"))
            info = self._tools_index_impl(w_name, weight, lexical_only, threads)
            return info, [info.fingerprint], {}

        return self._call("tools_index", args, run)

    def _tools_index_impl(self, w_name, weight, lexical_only, threads) -> ToolIndexInfo:
        if isinstance(w_name, bool) or not isinstance(w_name, int) or w_name < 0:
            raise ToolError(f"w_name must be an integer >= 0, got {w_name!r}")
        if lexical_only and weight is not None:
            raise ToolError("a lexical-only tool index has no fusion; drop --weight")
        if not lexical_only:
            if weight is None:
                raise ToolError("a hybrid tool index needs a tuned fusion weight: pass "
                                "--weight W (from `adr-eval tools-retrieval`), or use "
                                "--lexical-only")
            if isinstance(weight, bool) or not isinstance(weight, int | float) or \
                    not 0.0 <= float(weight) <= 1.0:
                raise ToolError(f"the fusion weight must be between 0 and 1, got {weight!r}")
        cat = self._catalog()
        dense = not lexical_only
        cache = make_embedding_cache(self.emb_cache, threads=threads) if dense else None
        expected = ToolIndex.expected_fingerprint(cat, w_name, cache, dense=dense)
        final = self.tool_index_root / expected
        if (final / "meta.json").is_file():
            idx, source = ToolIndex.load(final, cache), "loaded"
        else:
            idx, source = ToolIndex.build(cat, w_name, cache, dense=dense), "built"
            if idx.fingerprint != expected:
                raise StoreError(f"built tool index fingerprint {idx.fingerprint} differs "
                                 f"from the expected {expected}")
            idx.save(final)
        info = ToolIndexInfo(tool_snapshot=cat.snapshot_id, fingerprint=idx.fingerprint,
                             w_name=w_name, w=None if lexical_only else float(weight),
                             lexical_only=lexical_only, n_tools=len(idx.rows), source=source,
                             path=str(final))
        write_atomic(self.tool_index_root / "active.json",
                     (json.dumps(info.to_dict(), indent=2, sort_keys=True) + "\n").encode())
        self._tool_index = idx if threads == 1 or lexical_only else None
        return info

    _TOOL_ACTIVE_FIELDS = {"tool_snapshot": str, "fingerprint": str, "w_name": int,
                           "lexical_only": bool, "w": float | int | type(None)}

    def _tool_active(self, catalog: ToolCatalog) -> tuple[ToolIndex, dict]:
        """The active tool index (checked: for the catalog's snapshot, its fingerprint)."""
        path = self.tool_index_root / "active.json"
        if not path.is_file():
            raise ToolError(f"{self.store_path}: no tool index; run `adr tools index` first")
        fix = "run `adr tools index`"
        try:
            active = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(active, dict):
                raise TypeError(f"not an object: {type(active).__name__}")
            for k, kind in self._TOOL_ACTIVE_FIELDS.items():
                v = active[k]
                if not isinstance(v, kind) or (kind is not bool and isinstance(v, bool)):
                    raise TypeError(f"{k} {_short(repr(v))}")
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as e:
            raise ToolError(f"active tool index missing or damaged: {path}: "
                            f"{type(e).__name__}: {e}; {fix}") from e
        if active["tool_snapshot"] != catalog.snapshot_id:
            raise ToolError(f"the tool index is for tool snapshot "
                            f"{_short(active['tool_snapshot'])}, the tool catalog is at "
                            f"{_short(catalog.snapshot_id)}; {fix} again")
        idx = self._tool_index
        if idx is None or idx.fingerprint != active["fingerprint"]:
            cache = None if active["lexical_only"] else make_embedding_cache(self.emb_cache)
            try:
                idx = ToolIndex.load(self.tool_index_root / active["fingerprint"], cache)
            except (OSError, ValueError, KeyError, TypeError, RecursionError) as e:
                raise ToolError(f"active tool index missing or damaged: {type(e).__name__}: "
                                f"{e}; {fix}") from e
            if idx.fingerprint != active["fingerprint"] or \
                    idx.tool_snapshot != catalog.snapshot_id:
                raise ToolError(f"active tool index missing or damaged: the loaded index "
                                f"{_short(idx.fingerprint)} is not the active one; {fix}")
            self._tool_index = idx
        return idx, active

    def active_tool_index(self) -> ToolIndex:
        """The active tool index, loaded and checked as `search_tools` loads it (not
        logged). An operator call: refused with the ACL layer."""
        if self.acl:
            raise ToolError(OPERATOR_UNDER_ACL.format("active_tool_index"))
        with self._lock:
            head = self._tool_head()
            if head is None:
                raise ToolError(f"{self.store_path}: no tool catalog here (no tools/HEAD); "
                                f"run `adr tools ingest` first")
            try:
                cat = self._open_catalog(head)
            except StoreError as e:
                raise ToolError(str(e)) from e
            return self._tool_active(cat)[0]

    @staticmethod
    def _tool_filters(filters: object) -> list[str] | None:
        """The `source_kind` values of `{"source_kind": [...]}` (sorted, distinct), None for
        no filter; ToolError for anything else."""
        if filters is None:
            return None
        if not isinstance(filters, dict) or set(filters) - {"source_kind"}:
            raise ToolError(f"bad filters: expected {{\"source_kind\": [...]}} with kinds "
                            f"{', '.join(SOURCE_KINDS)}, got {_filters_arg(filters)!r}")
        kinds = filters.get("source_kind")
        if kinds is None:
            return None
        if not isinstance(kinds, list) or not kinds or \
                any(k not in SOURCE_KINDS for k in kinds):
            raise ToolError(f"bad filters: source_kind must be a non-empty list of "
                            f"{', '.join(SOURCE_KINDS)}, got {kinds!r}")
        return sorted(set(kinds))

    @staticmethod
    def _tool_view_lexical(idx: ToolIndex, view: frozenset[str], view_id: str) -> FieldBM25:
        """BM25 over the tools of the caller's view (§6.2), from an LRU of `VIEW_CACHE` by
        (tool index fingerprint, tool view id); the index's own when the view holds every
        indexed tool."""
        if len(view) == len(idx.rows):
            return idx.lexical
        key = (idx.fingerprint, view_id)
        with _VIEW_LOCK:
            if key in _TOOL_VIEW_LEXICAL:
                _TOOL_VIEW_LEXICAL.move_to_end(key)
                return _TOOL_VIEW_LEXICAL[key]
        lex = idx.view_lexical(view)
        with _VIEW_LOCK:
            _TOOL_VIEW_LEXICAL[key] = lex
            _TOOL_VIEW_LEXICAL.move_to_end(key)
            while len(_TOOL_VIEW_LEXICAL) > VIEW_CACHE:
                _TOOL_VIEW_LEXICAL.popitem(last=False)
        return lex

    @staticmethod
    def _tool_fields() -> dict:
        return {"filters": None, "tools_snapshot": None, "tool_index": None,
                "tool_view": None, "tool_error": None}

    def search_tools(self, query: str, top: int = SEARCH_TOP, *,
                     filters: dict | None = None) -> SearchToolsResult:
        """The top tools of the active tool index for `query` among the caller's visible
        tools that the filters admit (module docstring)."""
        fields = self._tool_fields()

        def run():
            if isinstance(top, bool) or not isinstance(top, int) or not 1 <= top <= CHANNEL_K:
                raise ToolError(f"top must be between 1 and {CHANNEL_K}, got {top!r}")
            if not isinstance(query, str):
                raise ToolError(f"query must be a string, got {type(query).__name__}")
            kinds = self._tool_filters(filters)
            fields["filters"] = {"source_kind": kinds}
            cat = self._catalog()
            fields["tools_snapshot"] = cat.snapshot_id
            idx, active = self._tool_active(cat)
            fields["tool_index"] = idx.fingerprint
            access = self._access_now
            lexical = view = None
            if access is not None:
                fields["tool_view"] = tool_view_id(access.tools)
                view = frozenset(t for t in access.tools if t in idx.rows)
                lexical = self._tool_view_lexical(idx, view, fields["tool_view"])
                lexical = None if lexical is idx.lexical else lexical
            pool = idx.rows.keys() if view is None else view
            admitted = pool if kinds is None else frozenset(
                t for t in pool if idx.rows[t].source_kind in kinds)
            excluded = len(pool) - len(admitted)
            allowed = None if view is None and kinds is None else frozenset(admitted)
            ranked = idx.retrieve(query, active["w"], top, allowed=allowed, lexical=lexical,
                                  exact=access is not None)
            hits = []
            for rank, (tid, score) in enumerate(ranked, start=1):
                r = idx.rows[tid]
                hits.append(ToolHit(rank, tid, r.name, r.summary, r.source_kind,
                                    r.source_uri, score, cat.snapshot_id))
            res = SearchToolsResult(query, top, cat.snapshot_id, idx.fingerprint,
                                    active["lexical_only"], idx.w_name, active["w"], hits,
                                    {"source_kind": kinds}, excluded)
            return res, [h.tool_id for h in hits], {}

        return self._call("search_tools", {"query": query, "top": top,
                                           "filters": _filters_arg(filters)}, run, fields,
                          tool_call=True)

    def load_tool(self, tool_id: str) -> LoadToolResult:
        """The MCP Tool definition of a visible tool (full id or a unique prefix of at least
        8 characters), its source fields and the tool snapshot (module docstring)."""
        fields = self._tool_fields()

        def run():
            if not isinstance(tool_id, str):
                raise ToolError(f"tool_id must be a string, got {type(tool_id).__name__}")
            cat = self._catalog()
            fields["tools_snapshot"] = cat.snapshot_id
            where = f"tool snapshot {_short(cat.snapshot_id)}"
            everything = cat.ids()
            access = self._access_now
            if access is None:
                visible = everything
            else:
                fields["tool_view"] = tool_view_id(access.tools)
                visible = sorted(access.tools)
                everything = sorted(set(everything) | access.tools)
            tid = self._find(tool_id, visible, everything, "tool", where)
            try:
                rec = cat.get(tid)
            except (KeyError, StoreError, OSError, ValueError) as e:
                # an inconsistent store: exactly what a nonexistent id gets; the reason is
                # for the operator's log only
                fields["tool_error"] = f"{type(e).__name__}: {e}"
                try:
                    _resolve(tool_id, [], "tool", where)
                except ToolError as nf:
                    raise ToolError(str(nf)) from None
                raise AssertionError("unreachable") from None
            res = LoadToolResult(rec.tool_id, tool_definition(rec), rec.source_kind,
                                 rec.source_uri, rec.source_version, rec.operation, rec.license,
                                 rec.definition_tokens, cat.snapshot_id)
            return res, [rec.tool_id], {}

        return self._call("load_tool", {"tool_id": tool_id}, run, fields, tool_call=True)
