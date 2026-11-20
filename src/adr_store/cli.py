"""`adr` command line: `adr ingest <corpus> --store <dir>` and `adr ingest --path <folder>
--store <dir>` (below), and the retrieval tools `adr index`, `adr search`, `adr read` and
`adr grep` (spec §9; the code is in `adr_store.tools`, this module only parses arguments and
prints), `adr applicability derive` (Phase 2 spec §4.2: the applicability overlay of the
store's HEAD snapshot, code in `adr_store.applicability`), `adr dedup build` (Phase 2 spec
§4.5: the dedup overlay of the active index's chunks, code in `adr_store.dedup`), and `adr acl
sync` and `adr acl show` (Phase 2 spec §5.3: one sync cycle of the ACL snapshot from the
directory and policy, and the principals of a chunk, a document or a user; code in
`adr_store.acl`), and `adr tools ingest` (Phase 2 spec §8.1, §8.3: tool records from a
captured MCP `tools/list` result, an OpenAPI 3.x JSON document or the local ToolRet corpus into
a store's tool catalog; code in `adr_store.tool_records` and `adr_store.tool_catalog`), and
`adr mcp --store <dir> --as USER` (Phase 2 spec §9.3: the five tools over MCP on stdio as one
caller; code in `adr_store.mcp_server`, needs the `[mcp]` extra), and the typed tables (Phase 3
spec §5.2, §8): `adr tables build` (build the 3A tables of the store's HEAD snapshot as a
candidate and print its tables id; the corpus is the store's, `--tables-for` when it holds
both; `--generator` and `--max-calls` (default 0) name the model profile and call cap of an
extraction build, and a metadata build calls no model), `adr tables gate` (the merge gate:
evaluate a candidate against `tables/HEAD` on gold sets and promote it when it has at most
`--max-flips` flips; exit 1 when refused), `adr tables show` (a build's manifest and its
semantic layer; never its `.report.json` files), `adr query` and `adr sql` (the `query_table`
and `sql` tools, with the filter flags and `--as USER` of `adr search`). `adr`
is not a security boundary (Phase 2 spec §7.1): whoever can run it
can read the store directory.

The tools take the store as `--store <dir>` or `--corpus <name>` (the store
`.cache/store/<name>`); `adr index` takes a corpus name or a store directory as its argument.
`--json` prints the result as JSON, otherwise a short table; every result names its snapshot.
`adr search`, `adr grep` and `adr read` take the applicability filters (Phase 2 spec §4.4):
`--include-superseded`, `--as-of YYYY-MM-DD`, `--status S` and `--jurisdiction J`
(repeatable) and `--max-tier N`; with none given the call passes no filters (the default:
superseded documents excluded when the store has an applicability overlay). `adr search
--dedup/--no-dedup` turns collapse on or off (default: on when the active index's chunks have
a dedup overlay). `adr search`, `adr read` and `adr grep` take `--as USER`: the call runs as
that caller with the ACL layer (Phase 2 spec §5.4: the caller's view only, F1–F5 deny); for
tests and simulation only, since `adr` is not a security boundary.
A refused call (unknown id, range out of bounds, bad pattern, a pattern that runs past
`adr grep --timeout`, a missing or damaged index) exits 2 with a message on stderr; every tool
call, refused or not, writes one line to the store's retrieval log, and an unexpected error
(exit 3) is logged too.

Ingest reads a pinned corpus through the harness (the manifest is verified, the canonical text
is the harness's), parses and checks every document, and commits one snapshot. Any
conformance violation fails the command with the documents and rules named, and no snapshot
is written. The compile figures of spec §10.3 are printed and written to
`<store>/compile/<snapshot>.json` (no timings in that file, so it is reproducible).

`--path` ingests the loose files of a folder instead (recursive, in relative-path order):
`doc_id` is the SHA-256 of the bytes and the text is the harness's `extract_text`, as for a
corpus. Hidden files and directories (a name that starts with a dot) are not read or counted;
everything else is ingested, counted or reported: files with an unsupported extension (and
anything that is not a regular file) as `unsupported`, symbolic links (to files or
directories, dangling or not; never followed) as `symlinks`, names that are not UTF-8 as
`bad_names` with a warning line each; identical files are ingested once (`duplicates`). A
store directory inside the folder is not read. Every file is read and extracted before the
first write: each file or directory that cannot be read ("cannot read <path>: <reason>") and
each file whose text cannot be extracted is reported on its own line and nothing is written
(exit 3 if any could not be read, else 2). The snapshot records each file's relative path
(`paths`), so re-ingesting a changed folder into the same store gives a new snapshot and an
unchanged one the same; the doc records stay as first written (their uri names the path the
bytes were first ingested under), and bytes stored under another format (a new extension) are
refused. The compile figures do not record the folder, so they do not depend on where it is
or how it is spelled. A missing folder or one without supported files exits 2.

Exit codes: 0 done; 1 a document fails conformance; 2 the corpus cannot be loaded or the
store refuses a write; 3 a document that cannot be read or an unexpected error (a bug),
reported on one line with the document being processed.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import stat
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePath

from adr_eval import runner as eval_runner
from adr_eval.corpora import REPO_ROOT
from adr_eval.corpora.base import Document, ExtractionError, HashMismatch, sha256_bytes
from adr_eval.corpora.extract import extract_text
from adr_eval.corpora.registry import NAMES, LocalFilesMissing, check_local_files
from adr_eval.corpora.toolret import ToolRetMissing
from adr_eval.runner import RunError, load_checked_corpus
from adr_store import acl, applicability, dedup, mcp_server, tool_catalog, tool_records, tools
from adr_store.store import (
    Added,
    ConformanceError,
    Store,
    StoreError,
    stored_source,
    write_atomic,
)
from adr_store.tables import build as tables_build
from adr_store.tables import gate as tables_gate
from adr_store.tables import overlay as tables_overlay
from adr_store.tables.engine import OPS, QUERY_LIMIT, contracts_of
from adr_store.tables.loaders import FR_PREFIX, PAPERS_URI
from adr_store.tables.semantic import describe

UNKNOWN_LICENSES = frozenset({"", "unknown"})
PROBLEMS_SHOWN = 5
EXIT_CONFORMANCE, EXIT_LOAD_OR_STORE, EXIT_UNEXPECTED = 1, 2, 3


class _Unexpected(Exception):
    """An unexpected error while ingesting one document: which document, and the error."""

    def __init__(self, path: str, doc_id: str, error: Exception):
        super().__init__(f"{path} ({doc_id[:12]})")
        self.path, self.doc_id, self.error = path, doc_id, error


def _one_line(e: Exception) -> str:
    return f"{type(e).__name__}: {' '.join(str(e).split())}"


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _format_figures(added: list[Added]) -> dict:
    leaves = [e for a in added for e in a.elements if e.is_leaf]
    found = sum(a.headings_found for a in added)
    aligned = sum(a.headings_aligned for a in added)
    with_sections = sum(1 for a in added if any(e.type == "section" for e in a.elements))
    paged = sum(1 for e in leaves if e.page is not None)
    return {
        "documents": len(added),
        "elements": sum(len(a.elements) for a in added),
        "leaves": len(leaves),
        "sections": sum(1 for a in added for e in a.elements if e.type == "section"),
        "with_sections": with_sections,
        "share_with_sections": _share(with_sections, len(added)),
        "headings_found": found,
        "headings_aligned": aligned,
        "alignment_rate": _share(aligned, found),
        "leaves_with_page": paged,
        "share_leaves_with_page": _share(paged, len(leaves)) if added[0].format == "pdf"
        else None,
    }


def compile_figures(corpus: str | None, snapshot: str, added: list[Added], checked: int,
                    failures: int) -> dict:
    """The compile track of spec §10.3 for one ingest (evidence-in-one-chunk needs chunks
    and comes with the chunker)."""
    by_format: dict[str, list[Added]] = defaultdict(list)
    for a in added:
        by_format[a.format].append(a)
    leaves = [e for a in added for e in a.elements if e.is_leaf]
    spanned = sum(1 for e in leaves if e.char_end > e.char_start)
    return {
        "corpus": corpus,
        "snapshot": snapshot,
        "documents": len(added),
        "elements": sum(len(a.elements) for a in added),
        "leaves": len(leaves),
        "sections": sum(1 for a in added for e in a.elements if e.type == "section"),
        "conformance": {"documents": checked, "failures": failures,
                        "pass_rate": _share(checked - failures, checked)},
        "leaves_with_span": _share(spanned, len(leaves)),
        "by_format": {fmt: _format_figures(group) for fmt, group in sorted(by_format.items())},
    }


def _print_figures(f: dict, label: str, seconds: float) -> None:
    print(f"{label}: snapshot {f['snapshot']}")
    print(f"  documents {f['documents']}, elements {f['elements']}, leaves {f['leaves']}, "
          f"sections {f['sections']}")
    c = f["conformance"]
    print(f"  conformance failures: {c['failures']} of {c['documents']}; "
          f"leaves with a character span: {f['leaves_with_span']:.2%}")
    print("  format  docs  with sections  headings aligned/found  leaves with page")
    for fmt, g in f["by_format"].items():
        share = "-" if g["share_with_sections"] is None else f"{g['share_with_sections']:.1%}"
        rate = "" if g["alignment_rate"] is None else f" ({g['alignment_rate']:.1%})"
        paged = "-" if g["share_leaves_with_page"] is None else \
            f"{g['share_leaves_with_page']:.1%}"
        print(f"  {fmt:<6}  {g['documents']:>4}  {share:>13}  "
              f"{g['headings_aligned']:>8}/{g['headings_found']:<6}{rate:<9}  {paged:>8}")
    print(f"  wall-clock {seconds:.1f}s")


def _report_failures(failures: list[tuple[str, ConformanceError]], checked: int) -> int:
    print(f"error: {len(failures)} of {checked} documents fail conformance; "
          f"no snapshot written", file=sys.stderr)
    for path, e in failures:
        print(f"  {path} ({e.doc_id[:12]}):", file=sys.stderr)
        for p in e.problems[:PROBLEMS_SHOWN]:
            print(f"    {p}", file=sys.stderr)
    return EXIT_CONFORMANCE


def _commit(store: Store, store_dir: Path, label: str, added: list[Added], checked: int,
            t0: float, extra: dict | None = None, *, paths: dict[str, str] | None = None,
            corpus: str | None) -> int:
    """Commit the snapshot (with `paths` for loose files), write and print its compile
    figures (plus `extra` keys); `label` (the corpus, or the folder as given) is printed, not
    written."""
    snapshot = store.commit(paths=paths)
    figures = compile_figures(corpus, snapshot, added, checked, 0)
    figures.update(extra or {})
    payload = json.dumps(figures, indent=2, sort_keys=True) + "\n"
    write_atomic(Path(store_dir) / "compile" / f"{snapshot}.json", payload.encode("utf-8"))
    _print_figures(figures, label, time.perf_counter() - t0)
    return 0


def _ingest(a: argparse.Namespace) -> int:
    if a.path is not None:
        return _ingest_path(a)
    t0 = time.perf_counter()
    check_local_files(a.corpus)
    loaded = load_checked_corpus(a.corpus)
    store = Store.create(a.store)
    added: list[Added] = []
    failures: list[tuple[str, ConformanceError]] = []
    manifest_docs = sorted(loaded.manifest.documents, key=lambda d: d.doc_id)
    for d in manifest_docs:
        license = None if d.license.strip().lower() in UNKNOWN_LICENSES else d.license
        try:
            raw = (loaded.root / d.path).read_bytes()
            added.append(store.add(loaded.docs[d.doc_id], raw, license=license))
        except ConformanceError as e:
            failures.append((d.path, e))
        except StoreError:
            raise
        except Exception as e:  # a bug: name the document, then stop
            raise _Unexpected(d.path, d.doc_id, e) from e
    if failures:
        return _report_failures(failures, len(manifest_docs))
    return _commit(store, a.store, a.corpus, added, len(manifest_docs), t0, corpus=a.corpus)


# -- `adr ingest --path <dir>`: loose files ----------------------------------------------

# file extension (lower case) -> harness format; other files are skipped and counted
PATH_FORMATS = {".md": "md", ".markdown": "md", ".txt": "txt", ".html": "html",
                ".htm": "html", ".pdf": "pdf", ".xml": "xml", ".json": "json", ".csv": "csv"}


class _UsageError(Exception):
    """`adr ingest --path` cannot start (no such folder, nothing to ingest)."""


@dataclass
class Walk:
    """What `loose_files` found under a folder. `files` are the supported regular files as
    (relative POSIX path, path), sorted by relative path; `unsupported` counts the other
    regular files and anything that is neither a file, a directory nor a symlink (a fifo, a
    socket, a device); `symlinks` the symbolic links, to files or directories, dangling or
    not, none of them followed; `bad_names` the escaped relative paths of entries whose name
    is not UTF-8 (a directory counts once, its contents are not listed); `unreadable` the
    (relative path, reason) of directories or entries that could not be listed or examined."""

    files: list[tuple[str, Path]] = field(default_factory=list)
    unsupported: int = 0
    symlinks: int = 0
    bad_names: list[str] = field(default_factory=list)
    unreadable: list[tuple[str, str]] = field(default_factory=list)


def _reason(e: OSError) -> str:
    return e.strerror or _one_line(e)


def _escaped(rel: str) -> str:
    """A relative path that may hold undecodable bytes (surrogate escapes), printable."""
    return os.fsencode(rel).decode("utf-8", "backslashreplace")


def loose_files(folder: Path, exclude: str | None = None) -> Walk:
    """Walk `folder` (top down, symlinks not followed): every entry is ingested, counted or
    reported, none skipped silently except hidden ones (a name that starts with a dot: hidden
    files are not counted and hidden directories are not entered). `exclude` is the relative
    path of a directory left out (the store, when it is inside the folder)."""
    walk = Walk()
    top = os.fspath(folder)

    def rel_of(p: str) -> str:
        return PurePath(os.path.relpath(p, top)).as_posix()

    def failed(e: OSError) -> None:
        walk.unreadable.append((rel_of(e.filename or top), _reason(e)))

    for dirpath, dirnames, filenames in os.walk(top, onerror=failed, followlinks=False):
        keep = []
        for name in sorted(dirnames):
            full = os.path.join(dirpath, name)
            rel = rel_of(full)
            if name.startswith("."):
                continue
            if not _utf8(name):
                walk.bad_names.append(_escaped(rel))
            elif os.path.islink(full):
                walk.symlinks += 1
            elif rel != exclude:
                keep.append(name)
        dirnames[:] = keep  # top down: only these are entered
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = rel_of(full)
            if name.startswith("."):
                continue
            if not _utf8(name):
                walk.bad_names.append(_escaped(rel))
                continue
            try:
                mode = os.lstat(full).st_mode
            except OSError as e:
                walk.unreadable.append((rel, _reason(e)))
                continue
            if stat.S_ISLNK(mode):
                walk.symlinks += 1
            elif stat.S_ISREG(mode) and Path(name).suffix.lower() in PATH_FORMATS:
                walk.files.append((rel, Path(full)))
            else:
                walk.unsupported += 1
    walk.files.sort()
    walk.bad_names.sort()
    walk.unreadable.sort()
    return walk


def _utf8(name: str) -> bool:
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:  # undecodable bytes, kept as surrogate escapes
        return False
    return True


def _store_inside(folder: Path, store: Path) -> str | None:
    """The store's path relative to the folder when it is inside it (whether or not it
    exists yet), else None; both resolved, so the spelling does not matter."""
    rel = os.path.relpath(os.path.realpath(store), os.path.realpath(folder))
    if rel == os.curdir:
        raise _UsageError(f"{store}: the store cannot be the folder itself")
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return None
    return PurePath(rel).as_posix()


def _ingest_path(a: argparse.Namespace) -> int:
    """Ingest the loose files of a folder like a corpus: `doc_id` is the SHA-256 of the bytes,
    the text is the harness's `extract_text`, the uri `file://<relative path>` and the source
    version `sha256:<doc_id[:12]>` (as the research corpus has them), no licence. Identical
    files are ingested once, under the first relative path. Every file is read and its text
    extracted before anything is written; any failure is reported, each on its own line, and
    nothing is written. The snapshot holds every file's relative path (`paths`); a doc record
    already in the store whose uri names an earlier path of the same bytes is kept."""
    t0 = time.perf_counter()
    folder = Path(a.path)
    if not folder.is_dir():
        raise _UsageError(f"{folder}: not a directory")
    store_rel = _store_inside(folder, a.store)
    walk = loose_files(folder, exclude=store_rel)
    for name in walk.bad_names:
        print(f"warning: skipped {name}: the name is not UTF-8", file=sys.stderr)
    if not walk.files and not walk.unreadable:
        raise _UsageError(f"{folder}: no supported files (extensions "
                          f"{', '.join(sorted(PATH_FORMATS))}); {walk.unsupported} "
                          f"unsupported")
    # read and extract everything first
    failed = [(rel, f"cannot read {rel}: {reason}") for rel, reason in walk.unreadable]
    cannot_read = len(failed)
    docs: list[tuple[str, Document, bytes]] = []
    paths: dict[str, str] = {}
    seen: set[str] = set()
    duplicates = 0
    for rel, p in walk.files:
        fmt = PATH_FORMATS[p.suffix.lower()]
        try:
            raw = p.read_bytes()
        except OSError as e:
            failed.append((rel, f"cannot read {rel}: {_reason(e)}"))
            cannot_read += 1
            continue
        doc_id = sha256_bytes(raw)
        paths[rel] = doc_id
        if doc_id in seen:
            duplicates += 1
            continue
        seen.add(doc_id)
        try:
            text = extract_text(raw, fmt)
        except Exception as e:  # as when a corpus is loaded
            failed.append((rel, f"{rel}: could not extract text ({fmt}): {_one_line(e)}"))
            continue
        held = stored_source(a.store, doc_id)
        if held is not None and held.format != fmt:
            failed.append((rel, f"{rel}: the store holds these bytes as {held.format} (from "
                                f"{held.uri}); a store keeps one reading of a file: use a new "
                                f"store or the earlier extension"))
            continue
        docs.append((rel, Document(doc_id, text, fmt, f"sha256:{doc_id[:12]}",
                                   f"file://{rel}"), raw))
    if failed:
        for _, line in sorted(failed):
            print(f"error: {line}", file=sys.stderr)
        n = len(failed)
        print(f"error: {n} {'entry' if n == 1 else 'entries'} could not be read or "
              f"extracted; nothing written", file=sys.stderr)
        return EXIT_UNEXPECTED if cannot_read else EXIT_LOAD_OR_STORE
    store = Store.create(a.store)
    added: list[Added] = []
    failures: list[tuple[str, ConformanceError]] = []
    for rel, doc, raw in docs:
        try:
            added.append(store.add(doc, raw, license=None, keep_uri=True))
        except ConformanceError as e:
            failures.append((rel, e))
        except StoreError:
            raise
        except Exception as e:  # a bug: name the document, then stop
            raise _Unexpected(rel, doc.doc_id, e) from e
    if failures:
        return _report_failures(failures, len(docs))
    counts = {"found": len(walk.files) + walk.unsupported + walk.symlinks
              + len(walk.bad_names),
              "ingested": len(added), "unsupported": walk.unsupported,
              "duplicates": duplicates, "symlinks": walk.symlinks,
              "bad_names": len(walk.bad_names)}
    code = _commit(store, a.store, str(folder), added, len(docs), t0, {"files": counts},
                   paths=paths, corpus=None)
    print(f"  files {counts['found']}: ingested {counts['ingested']}, unsupported "
          f"{counts['unsupported']}, duplicates {duplicates}, symlinks {walk.symlinks}, "
          f"bad names {counts['bad_names']} (hidden files not read, symlinks not followed)")
    if store_rel is not None:
        print(f"  store {store_rel} is inside the folder: not read")
    return code


# -- the retrieval tools -----------------------------------------------------------------

STORE_ROOT = Path(".cache/store")
TABLE_FIELD = 60  # characters of a long field (breadcrumb, context) shown in a table


def _cut(s: str, n: int = TABLE_FIELD) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _store_of(a: argparse.Namespace) -> Path:
    if a.store is not None:
        return a.store
    return STORE_ROOT / a.corpus


def _tools(a: argparse.Namespace) -> tools.Tools:
    """The tools of a search, read or grep: with `--as USER`, as that caller with the ACL
    layer (for tests and simulation, `NOT_A_BOUNDARY`), else without it."""
    caller = getattr(a, "as_user", None)
    if caller is None:
        return tools.Tools(_store_of(a), emb_cache=a.emb_cache)
    return tools.Tools(_store_of(a), emb_cache=a.emb_cache, acl=True, caller=caller)


def _print_json(result) -> None:
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))


def _index(a: argparse.Namespace) -> int:
    if a.target in NAMES:
        store = a.store if a.store is not None else STORE_ROOT / a.target
    elif a.store is not None:
        raise tools.ToolError(f"{a.target!r} is not a corpus name; give a corpus name with "
                              f"--store, or a store directory alone")
    else:
        store = Path(a.target)
    info = tools.Tools(store, emb_cache=a.emb_cache).index(
        a.system, lexical_only=a.lexical_only, w_bc=a.w_bc, weight=a.weight, tuning=a.tuning,
        threads=a.threads)
    if a.json:
        _print_json(info)
        return 0
    mode = "lexical only" if info.lexical_only else f"fusion weight {info.w} ({info.w_from})"
    print(f"{info.system}: index {info.fingerprint[:12]} ({info.source}) for snapshot "
          f"{info.snapshot[:12]}")
    print(f"  chunks {info.n_chunks}; w_bc {info.w_bc} ({info.w_bc_from}); {mode}; "
          f"prefix {info.prefix}; rerank {info.rerank}")
    if info.tuning is not None:
        match = {True: "same fingerprint as the run", False: "fingerprint differs from the run",
                 None: "values overridden"}[info.tuning["fingerprint_match"]]
        print(f"  tuning from {info.tuning['path']} ({match})")
    return 0


def _filters(a: argparse.Namespace) -> dict | None:
    """The filters the flags give, or None when no filter flag is given."""
    f = {}
    if a.include_superseded:
        f["include_superseded"] = True
    for key in ("as_of", "status", "jurisdiction", "max_tier"):
        if getattr(a, key) is not None:
            f[key] = getattr(a, key)
    return f or None


def _print_filters(res, excluded: int | None, filters: dict | None = None) -> None:
    """One line naming the filters of a result (`filters`, else `res.filters`) and what they
    excluded; none without an overlay (the table is then Phase 1's)."""
    if res.applicability is None:
        return
    f = res.filters if filters is None else filters
    parts = [f"as_of {f['as_of']}" if f["as_of"] is not None else
             "include_superseded" if f["include_superseded"] else "default"]
    parts += [f"{k} {','.join(map(str, f[k]))}" for k in ("status", "jurisdiction") if f[k]]
    if f["max_tier"] is not None:
        parts.append(f"max_tier {f['max_tier']}")
    tail = "" if excluded is None else f", {excluded} document(s) excluded"
    print(f"  filters {'; '.join(parts)} (overlay {res.applicability[:12]}){tail}")


def _search(a: argparse.Namespace) -> int:
    res = _tools(a).search(a.query, top=a.top, filters=_filters(a), dedup=a.dedup)
    if a.json:
        _print_json(res)
        return 0
    lex = ", lexical only" if res.lexical_only else ""
    print(f"snapshot {res.snapshot[:12]}  index {res.system} {res.fingerprint[:12]}{lex}  "
          f"{len(res.hits)} hit(s)")
    _print_filters(res, res.excluded_by_filter)
    if res.dedup_note not in (None, dedup.OFF, dedup.NO_OVERLAY):  # an overlay of other chunks
        print(f"  dedup off: {res.dedup_note}")
    if res.dedup is None:  # the Phase 1 table
        print(f"{'rank':>4}  {'score':>10}  {'chunk':<12}  {'doc':<12}  {'range':<15}  "
              f"breadcrumb")
        for h in res.hits:
            print(f"{h.rank:>4}  {h.score:>10.4f}  {h.chunk_id[:12]}  {h.doc_id[:12]}  "
                  f"{f'{h.char_start}-{h.char_end}':<15}  {_cut(h.breadcrumb)}")
        return 0
    print(f"  dedup overlay {res.dedup[:12]}: one hit per cluster, the canonical copy shown; "
          f"alt = other copies")
    print(f"{'rank':>4}  {'score':>10}  {'chunk':<12}  {'doc':<12}  {'range':<15}  {'alt':>3}  "
          f"breadcrumb")
    for h in res.hits:
        print(f"{h.rank:>4}  {h.score:>10.4f}  {h.chunk_id[:12]}  {h.doc_id[:12]}  "
              f"{f'{h.char_start}-{h.char_end}':<15}  {len(h.alternates):>3}  "
              f"{_cut(h.breadcrumb)}")
    if res.short_by:
        print(f"  short by {res.short_by}: the index reranks its top {tools.RERANK_TOP} "
              f"chunks only, which collapse to {len(res.hits)} hit(s); the ranking below them "
              f"has more (ask for --top {len(res.hits)} or fewer, or use --no-dedup)")
    return 0


def _read(a: argparse.Namespace) -> int:
    res = _tools(a).read(a.doc_id, a.start, a.end, element=a.element, chunk=a.chunk,
                         filters=_filters(a))
    if a.json:
        _print_json(res)
        return 0
    what = (f" element {res.element_id[:12]}" if res.element_id else "") + \
        (f" chunk {res.chunk_id[:12]}" if res.chunk_id else "")
    print(f"# doc {res.doc_id[:12]} [{res.char_start}:{res.char_end}]{what} snapshot "
          f"{res.snapshot[:12]} sha256 {res.text_sha256[:12]}")
    print(res.text, end="" if res.text.endswith("\n") else "\n")
    return 0


def _grep(a: argparse.Namespace) -> int:
    res = _tools(a).grep(a.pattern, doc=a.doc, max=a.max, ignore_case=a.ignore_case,
                         timeout=a.timeout, filters=_filters(a))
    if a.json:
        _print_json(res)
        return 0
    more = f" (stopped at --max {res.max})" if res.truncated else ""
    print(f"snapshot {res.snapshot[:12]}  {len(res.matches)} match(es){more}")
    _print_filters(res, res.excluded_by_filter)
    for m in res.matches:
        print(f"{m.doc_id[:12]}  {m.char_start}-{m.char_end}  line {m.line}  "
              f"{_cut(m.context, 2 * TABLE_FIELD)}")
    return 0


GOV_CONFIG = REPO_ROOT / "corpora" / "gov" / "config.json"


def _applicability_derive(a: argparse.Namespace) -> int:
    """Derive the applicability overlay of HEAD, write it once (the same bytes again are a
    no-op, other bytes are refused) with its report beside it, and print the report."""
    store = Store.open(_store_of(a))
    try:
        gov_config = json.loads(Path(a.gov_config).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise _UsageError(f"cannot read the gov config {a.gov_config}: {_one_line(e)}") from e
    try:
        overlay, report = applicability.derive(store, gov_config)
    except ValueError as e:
        raise _UsageError(str(e)) from e
    existed = applicability.overlay_path(store.path, overlay.snapshot).is_file()
    overlay_id, path = applicability.write_overlay(store.path, overlay)
    applicability.write_report(store.path, report)
    if a.json:
        print(json.dumps({"overlay_id": overlay_id, "path": str(path),
                          "snapshot": overlay.snapshot, "report": report}, indent=2,
                         ensure_ascii=False))
        return 0
    print(f"applicability: overlay {overlay_id[:12]} for snapshot {overlay.snapshot[:12]} "
          f"({'unchanged' if existed else 'written'})")
    print(f"  {path}")
    fams = ", ".join(f"{k} {v}" for k, v in report["families"].items())
    print(f"  documents {report['documents']}: {fams}")
    print("  status: " + ", ".join(f"{k} {v}" for k, v in report["status"].items()))
    print("  validity basis: " + ", ".join(f"{k} {v}"
                                           for k, v in report["validity_basis"].items() if v))
    print("  authority tier: " + ", ".join(f"{k} {v}"
                                           for k, v in report["authority_tier"].items()))
    c = report["chains"]
    print(f"  chains {c['count']}, {c['multi_version']} with more than one version "
          f"({c['documents']} documents, {c['links']} supersession links); superseded "
          f"documents {report['superseded_documents']}")
    t = report["temporary_end_dates"]
    print(f"  temporary end dates parsed {t['parsed']} of {t['of']}")
    for f in report["fr_dates_parse_failures"]:
        print(f"    not parsed: {f['document_number']} ({f['doc_id'][:12]}): "
              f"{_cut(f['dates'], 2 * TABLE_FIELD)}")
    for caveat in report["caveats"]:
        print(f"  caveat: {caveat}")
    return 0


# widths fit 5-digit counts and 100.0% shares ("99999 = 100.0% (100.0% of tokens)": 33)
_DEDUP_COLUMNS = [("chunks", 7), ("exact clusters (chunks)", 23), ("redundant (tokens)", 33),
                  ("near pairs (clusters)", 21), ("redundant at {t}", 17)]


def _dedup_header(threshold: float) -> str:
    """The cluster table's header: `view` left-aligned, the other columns right-aligned to
    the widths `_dedup_row` uses."""
    return "  " + f"{'view':<14}" + "".join(
        f"  {label.format(t=f'{threshold:g}'):>{width}}" for label, width in _DEDUP_COLUMNS)


def _dedup_row(label: str, f: dict) -> str:
    def pct(x):
        return "-" if x is None else f"{100 * x:.1f}%" if x == 0 or x >= 0.01 else \
            f"{100 * x:.2f}%"

    cells = [str(f["chunks"]), f"{f['exact_clusters']} ({f['exact_chunks']})",
             f"{f['exact_redundant']} = {pct(f['exact_redundant_share'])} "
             f"({pct(f['exact_redundant_token_share'])} of tokens)",
             f"{f['near_pairs']} ({f['clusters']})", pct(f["redundant_share"])]
    return "  " + f"{label:<14}" + "".join(
        f"  {cell:>{width}}" for cell, (_, width) in zip(cells, _DEDUP_COLUMNS, strict=True))


def _dedup_build(a: argparse.Namespace) -> int:
    """Build the dedup overlay of the active index's chunks, write it once (the same bytes
    again are a no-op, other bytes are refused) and print the cluster table (spec §4.5): all
    chunks, and the default view (superseded documents excluded) when the store has an
    applicability overlay."""
    t = tools.Tools(_store_of(a), emb_cache=a.emb_cache)
    idx = t.active_index()
    t0 = time.perf_counter()
    overlay = dedup.build(list(idx.chunks.values()), idx.snapshot, idx.chunker)
    seconds = time.perf_counter() - t0
    path = dedup.overlay_path(t.store_path, overlay.snapshot, idx.chunker,
                              overlay.chunk_content_sha256)
    existed = path.is_file()
    overlay_id, path = dedup.write_overlay(t.store_path, overlay)
    figures = {"all": dedup.figures(idx.chunks, overlay.clusters), "default": None}
    app = applicability.load_overlay(t.store_path, t.snapshot)
    if app is not None:
        allowed, _ = app.allowed_docs(t.store.doc_ids(), applicability.Filters())
        figures["default"] = dedup.figures(idx.chunks, overlay.clusters,
                                           lambda cid: idx.chunks[cid].doc_id in allowed)
    if a.json:
        print(json.dumps({"overlay_id": overlay_id, "path": str(path), "existed": existed,
                          "snapshot": overlay.snapshot, "index": idx.fingerprint,
                          "params": overlay.params, "stats": overlay.stats,
                          "figures": figures, "seconds": round(seconds, 3)}, indent=2,
                         ensure_ascii=False))
        return 0
    p, st = overlay.params, overlay.stats
    print(f"dedup: overlay {overlay_id[:12]} for snapshot {overlay.snapshot[:12]}, index "
          f"{idx.fingerprint[:12]} ({'unchanged' if existed else 'written'}, built in "
          f"{seconds:.1f} s)")
    print(f"  {path}")
    print(f"  exact {p['exact']}; near: MinHash {p['num_perm']} over word {p['shingle']}-shingles, "
          f"LSH {p['bands']} x {p['rows']}, seed {p['seed']}, threshold {p['threshold']:g} "
          f"(Jaccard, every candidate verified)")
    print(f"  {st['distinct_texts']} distinct texts, {st['candidate_pairs']} candidate pairs, "
          f"{st['verified_candidates']} verified, {st['rejected_candidates']} rejected")
    print(_dedup_header(p["threshold"]))
    print(_dedup_row("all chunks", figures["all"]))
    if figures["default"] is not None:
        print(_dedup_row("default view", figures["default"]))
    return 0


_KIND_LABELS = {"public": "public", "two_tenants": "two tenants", "tenant": "one tenant",
                "group": "one group", "rule": "by attribute rule"}
NOT_A_BOUNDARY = ("`adr` is not a security boundary: whoever can run it can read the store "
                  "directory. The enforcement point is the Tools API, served over MCP "
                  "(Phase 2 spec §7.1).")


def _acl_sync(a: argparse.Namespace) -> int:
    """Run one sync cycle and print what it wrote."""
    res = acl.sync(_store_of(a), a.directory, a.policy)
    if a.json:
        print(json.dumps(res.to_dict(), indent=2, ensure_ascii=False))
        return 0
    print(f"acl: snapshot {res.acl_snapshot[:12]} sequence {res.sequence} for content snapshot "
          f"{res.content_snapshot[:12]} (access {'changed' if res.changed else 'unchanged'}"
          f"{'' if res.previous is None else f' since {res.previous[:12]}'})")
    print(f"  {res.path}")
    print(f"  documents {res.documents}: " + ", ".join(
        f"{_KIND_LABELS[k]} {n}" for k, n in res.kinds.items() if n or k != "rule"))
    if res.tool_snapshot is not None:
        print(f"  tools {res.tools} (tool snapshot {res.tool_snapshot[:12]}): " + ", ".join(
            f"{_KIND_LABELS[k]} {n}" for k, n in res.tool_kinds.items() if n or k != "rule"))
    print(f"  entries {res.entries_sha256[:12]}; sync {res.duration_s:.3f} s; lag "
          f"{res.lag_s:.1f} s since the directory or policy changed")
    return 0


def _acl_show(a: argparse.Namespace) -> int:
    """The principals of a chunk (through the active index), a document, or a user, as the
    current ACL snapshot has them."""
    store_path = _store_of(a)
    sid, snap = acl.read_head(store_path)
    out: dict = {"acl_snapshot": sid, "content_snapshot": snap.content_snapshot}
    head = Store.open(store_path).snapshot_id
    warning = None if head == snap.content_snapshot else (
        f"the ACL snapshot is for content snapshot {snap.content_snapshot[:12]}, the store is "
        f"at {head[:12]}: tools deny every call (F2) until `adr acl sync`")
    out["warning"] = warning
    if a.user is not None:
        principals = acl.caller_principals(snap, a.user)
        visible = sum(1 for v in snap.docs.values() if set(v) & set(principals))
        out.update(user=a.user, principals=list(principals), visible_documents=visible,
                   documents=len(snap.docs))
        lines = [f"{a.user}: {' '.join(principals)}",
                 f"  sees {visible} of {len(snap.docs)} documents"]
    else:
        if a.chunk is not None:
            idx = tools.Tools(store_path, emb_cache=a.emb_cache).active_index()
            cid = tools._resolve(a.chunk, sorted(idx.chunks), "chunk", "the active index")
            doc_id = idx.chunks[cid].doc_id
            out["chunk_id"] = cid
        else:
            doc_id = tools._resolve(a.doc, sorted(snap.docs), "document",
                                    f"ACL snapshot {sid[:12]}")
        principals = snap.docs.get(doc_id)
        out.update(doc_id=doc_id, principals=principals)
        who = "no entry: visible to no one" if not principals else " ".join(principals)
        lines = ([f"chunk {out['chunk_id']}"] if a.chunk is not None else []) + \
            [f"document {doc_id}: {who}"]
    if a.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    print(f"acl snapshot {sid[:12]} (sequence {snap.sequence}, synced "
          f"{snap.synced_at.isoformat().replace('+00:00', 'Z')})")
    for line in lines:
        print(line)
    if warning:
        print(f"warning: {warning}")
    return 0


TOOL_STORE = REPO_ROOT / ".cache" / "store-p2" / "toolret"


def _toolret_records(a: argparse.Namespace) -> tuple[str, list[tool_records.ToolRecord]]:
    from adr_eval.corpora import toolret

    cfg = toolret.load_config(toolret.CONFIG_PATH)
    rows = toolret.tools(a.root if a.root is not None else toolret.DATA_DIR,
                         toolret.CONFIG_PATH)
    recs = []
    for r in rows:
        try:
            doc = json.loads(r["documentation"])
        except ValueError as e:
            raise _UsageError(f"ToolRet tool {r['id']}: documentation is not JSON: "
                              f"{_one_line(e)}") from e
        try:
            recs.append(tool_records.from_toolret(
                doc, tool_records.toolret_uri(r["repo"], r["revision"], r["config"], r["id"]),
                r["revision"], r["license"], toolret_id=r["id"]))
        except tool_records.AdapterError as e:
            raise _UsageError(f"ToolRet tool {r['id']}: {e}") from e
    files = [cfg["files"][k] for k in cfg["tool_files"]]
    return (f"toolret {files[0]['repo']}@{files[0]['revision'][:12]} "
            f"({', '.join(f['config'] for f in files)})", recs)


def _tool_source(a: argparse.Namespace, refs: dict
                 ) -> tuple[str, list[tool_records.ToolRecord]]:
    """(description of the source, its tool records) for `adr tools ingest`; an OpenAPI
    source fills `refs` with its $ref counts."""
    if a.toolret:
        return _toolret_records(a)
    path = a.mcp or a.openapi
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise _UsageError(f"cannot read {path}: {_one_line(e)}") from e
    try:
        if a.mcp:
            for key in ("tools_list", "server"):
                if key not in doc:
                    raise _UsageError(f"{path}: not a captured tools/list file (no {key!r})")
            uri = a.source_uri or doc.get("source_uri")
            lic = a.license or doc.get("license")
            if not uri or not lic:
                raise _UsageError(f"{path}: give --source-uri and --license (the file has "
                                  f"no source_uri or license)")
            recs = tool_records.from_mcp(doc["tools_list"], doc["server"], uri,
                                         a.source_version or str(doc.get("version", "")), lic)
            return f"MCP server {doc['server']} ({path})", recs
        if not a.source_uri or not a.license:
            raise _UsageError("--openapi needs --source-uri and --license (they are part of "
                              "every record, and the source_uri of its tool_id)")
        version = a.source_version or str((doc.get("info") or {}).get("version", ""))
        return f"OpenAPI {path}", tool_records.from_openapi(doc, a.source_uri, version,
                                                            a.license, stats=refs)
    except (ValueError, TypeError, AttributeError) as e:
        raise _UsageError(f"{path}: {_one_line(e)}") from e


def _tools_ingest(a: argparse.Namespace) -> int:
    """Add the tool records of one source to a store's tool catalog and commit a tool
    snapshot; every record is checked first and none is written if one fails."""
    if a.store is None and not a.toolret:
        raise _UsageError("--mcp and --openapi need --store (the default store "
                          f"{TOOL_STORE} is the ToolRet one)")
    store = a.store if a.store is not None else TOOL_STORE
    refs: dict = {}
    source, recs = _tool_source(a, refs)
    failed = [(r, p) for r in recs if (p := tool_records.conformance(r))]
    if failed:
        for r, problems in failed:
            print(f"error: tool {r.name!r} ({r.tool_id[:12]}): {'; '.join(problems)}",
                  file=sys.stderr)
        print(f"error: {len(failed)} of {len(recs)} tools from {source} fail conformance; "
              f"nothing written", file=sys.stderr)
        return EXIT_CONFORMANCE
    sid, before, after = tool_catalog.ingest(store, recs)
    res = {"store": str(store), "source": source, "records": len(recs),
           "added": after - before, "tools": after, "tool_snapshot": sid,
           "content_snapshot": Store.open(store).snapshot_id, "conformance": 1.0,
           "definition_tokens": sum(r.definition_tokens for r in recs),
           "refs": refs or None}
    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    print(f"tools: {len(recs)} tools from {source}: conformance 100%, {res['added']} new; "
          f"catalog {sid[:12]} holds {after} tools")
    print(f"  store {store} (content snapshot {res['content_snapshot'][:12]}); definitions "
          f"{res['definition_tokens']} tokens")
    if refs:
        print(f"  $refs: {refs['missing_refs']} missing $refs and {refs['external_refs']} "
              f"external ones left as {{}}; cut to {{}}: {refs['cycle_cuts']} cycles, "
              f"{refs['depth_cuts']} at depth {tool_records.REF_DEPTH}, "
              f"{refs['budget_cuts']} past the {tool_records.NODE_BUDGET} node budget")
    return 0


def _tools_index(a: argparse.Namespace) -> int:
    """Build or load the tool index of the store's tool catalog and make it active."""
    store = a.store if a.store is not None else TOOL_STORE
    info = tools.Tools(store, emb_cache=a.emb_cache).tools_index(
        a.w_name, weight=a.weight, lexical_only=a.lexical_only, threads=a.threads)
    if a.json:
        _print_json(info)
        return 0
    mode = "lexical only" if info.lexical_only else f"fusion weight {info.w}"
    print(f"tool index {info.fingerprint[:12]} ({info.source}) for tool snapshot "
          f"{info.tool_snapshot[:12]}")
    print(f"  tools {info.n_tools}; w_name {info.w_name}; {mode}")
    return 0


def _search_tools(a: argparse.Namespace) -> int:
    filters = None if not a.source_kind else {"source_kind": a.source_kind}
    res = _tools(a).search_tools(a.query, top=a.top, filters=filters)
    if a.json:
        _print_json(res)
        return 0
    lex = ", lexical only" if res.lexical_only else ""
    kinds = res.filters["source_kind"]
    only = "" if kinds is None else f"; source_kind {','.join(kinds)} ({res.excluded_by_filter}" \
                                    f" excluded)"
    print(f"tool snapshot {res.tools_snapshot[:12]}  tool index {res.fingerprint[:12]}{lex}  "
          f"{len(res.hits)} hit(s){only}")
    print(f"{'rank':>4}  {'score':>10}  {'tool':<12}  {'kind':<8}  {'name':<32}  summary")
    for h in res.hits:
        print(f"{h.rank:>4}  {h.score:>10.4f}  {h.tool_id[:12]}  {h.source_kind:<8}  "
              f"{_cut(h.name, 32):<32}  {_cut(h.summary)}")
    return 0


def _load_tool(a: argparse.Namespace) -> int:
    res = _tools(a).load_tool(a.tool_id)
    if a.json:
        _print_json(res)
        return 0
    print(f"# tool {res.tool_id[:12]} ({res.source_kind}, {res.source_uri}) tool snapshot "
          f"{res.tools_snapshot[:12]}; {res.definition_tokens} tokens")
    print(json.dumps(res.definition, indent=2, ensure_ascii=False))
    return 0


ECFR_PREFIX = "https://www.ecfr.gov/"


def _tables_corpus(a: argparse.Namespace) -> str:
    """The corpus whose tables to build: `--tables-for`, else the one the store's documents
    are of (Federal Register or eCFR documents: gov; the papers manifest: research)."""
    if a.tables_for is not None:
        return a.tables_for
    store = Store.open(a.store)
    found = set()
    for doc_id in store.doc_ids():
        uri = store.source(doc_id).uri
        if uri == PAPERS_URI:
            found.add("research")
        elif uri.startswith((FR_PREFIX, ECFR_PREFIX)):
            found.add("gov")
    if len(found) != 1:
        what = "both gov and research documents" if found else \
            "no Federal Register, eCFR or papers manifest document"
        raise _UsageError(f"{a.store}: the store holds {what}; give --tables-for gov or "
                          f"--tables-for research")
    return found.pop()


def _tables_build(a: argparse.Namespace) -> int:
    corpus = _tables_corpus(a)
    generator = a.generator or eval_runner.load_config()["generator"]
    try:
        res = tables_build.build_tables(a.store, corpus, with_extraction=a.with_extraction,
                                        generator_profile=generator, max_calls=a.max_calls)
    except NotImplementedError as e:
        raise tools.ToolError(str(e)) from e
    m = tables_overlay.load_manifest(a.store, res.tables_id)
    head = tables_overlay.read_head(a.store)
    if a.json:
        print(json.dumps({"tables_id": res.tables_id, "manifest_path": str(res.manifest_path),
                          "head": head, "manifest": m.model_dump(mode="json")}, indent=2,
                         ensure_ascii=False))
        return 0
    print(res.tables_id)
    print(f"candidate tables of {m.corpus} for snapshot {m.snapshot[:12]}: {len(m.tables)} "
          f"table(s), {sum(t.rows for t in m.tables)} row(s), "
          f"{sum(t.rejected for t in m.tables)} rejected; HEAD "
          f"{'is this build' if head == res.tables_id else head[:12] if head else 'none'}")
    _print_tables(m)
    if head != res.tables_id:
        print(f"  not current until promoted: adr tables gate --store {a.store} --candidate "
              f"{res.tables_id} --gold DIR --max-flips N")
    return 0


def _print_tables(m: tables_overlay.Manifest) -> None:
    for t in m.tables:
        print(f"  {t.table:<16} v{t.contract_version}  {t.kind:<10} {t.rows:>7} row(s)  "
              f"{t.rejected:>5} rejected  {t.sha256[:12]}")


def _tables_show(a: argparse.Namespace) -> int:
    head = tables_overlay.read_head(a.store)
    tables_id = a.tables or head
    if tables_id is None:
        raise tools.ToolError(f"{a.store}: no current tables (tables/HEAD); run `adr tables "
                              f"build` and `adr tables gate`, or give --tables ID")
    m = tables_overlay.load_manifest(a.store, tables_id)
    semantic = describe(list(contracts_of(m, tables_id).values()))
    if a.json:
        print(json.dumps({"tables_id": tables_id, "head": head,
                          "manifest": m.model_dump(mode="json"), "semantic": semantic},
                         indent=2, ensure_ascii=False))
        return 0
    state = "HEAD" if tables_id == head else "not HEAD"
    print(f"tables {tables_id[:12]} ({state}) of {m.corpus} for snapshot {m.snapshot[:12]}; "
          f"applicability overlay {m.applicability[:12] if m.applicability else 'none'}")
    _print_tables(m)
    print(json.dumps(semantic, indent=2, ensure_ascii=False))
    return 0


def _gold_path(p: Path) -> Path:
    return p / "items.jsonl" if p.is_dir() else p


def _tables_gate(a: argparse.Namespace) -> int:
    m = tables_overlay.load_manifest(a.store, a.candidate)
    cases = []
    for g in a.gold:
        try:
            cases += tables_gate.gold_cases(_gold_path(g), m.corpus)
        except (OSError, ValueError) as e:
            raise tools.ToolError(f"cannot read the gold set {_gold_path(g)}: "
                                  f"{_one_line(e)}") from e
    try:
        r = tables_gate.gate(a.store, a.candidate, cases, a.max_flips,
                             allow_unreadable_head=a.allow_unreadable_head)
    except ValueError as e:
        raise tools.ToolError(str(e)) from e
    if a.json:
        print(json.dumps(dataclasses.asdict(r), indent=2, ensure_ascii=False))
    else:
        was = r.current[:12] if r.current else "none"
        verdict = (f"promoted: {r.candidate[:12]} is HEAD (was {was})" if r.promoted else
                   f"refused: HEAD stays {was}")
        print(f"{verdict}; candidate right on {r.right_candidate} of {r.n}, HEAD on "
              f"{r.right_current} of {r.n}; {len(r.flips)} flip(s) (at most {a.max_flips}), "
              f"{len(r.gains)} gain(s)")
        if r.flips:
            print(f"  flips: {', '.join(r.flips)}")
        if r.head_unreadable:
            print(f"  HEAD could not be evaluated: {r.head_unreadable}")
    return 0 if r.promoted else EXIT_CONFORMANCE


def _query_filters(a: argparse.Namespace) -> dict | None:
    if a.query_filters is None:
        return None
    try:
        return json.loads(a.query_filters)
    except ValueError as e:
        raise _UsageError(f"--filters is not JSON: {_one_line(e)}") from e


def _query(a: argparse.Namespace) -> int:
    res = _tools(a).query_table(a.table, _query_filters(a), a.op, fields=a.fields,
                                order=a.order, limit=a.limit, applicability=_filters(a))
    if a.json:
        _print_json(res)
        return 0
    more = " (truncated)" if res.truncated else ""
    print(f"snapshot {res.snapshot[:12]}  tables {res.tables[:12]}  {res.op} on "
          f"{res.table}{more}")
    _print_filters(res, res.excluded_by_filter, res.applicability_filters)
    for why in res.never_matches:
        print(f"  never matches: {why}")
    if res.op == "count":
        print(res.count)
    elif res.op == "list":
        for i in res.ids:
            print(i)
    elif res.op == "count_by":
        for g in res.groups:
            print(f"{g['count']:>8}  {json.dumps(g['value'], ensure_ascii=False)}")
    else:
        for r in res.rows:
            print(f"{r['doc_id'][:12]}  {json.dumps(r['row'], ensure_ascii=False)}")
    return 0


def _sql(a: argparse.Namespace) -> int:
    res = _tools(a).sql(a.statement, applicability=_filters(a))
    if a.json:
        _print_json(res)
        return 0
    more = " (truncated)" if res.truncated else ""
    print(f"snapshot {res.snapshot[:12]}  tables {res.tables[:12]}  {len(res.rows)} "
          f"row(s){more}")
    _print_filters(res, res.excluded_by_filter, res.applicability_filters)
    print("\t".join(res.columns))
    for row in res.rows:
        print("\t".join(json.dumps(v, ensure_ascii=False) for v in row))
    return 0


def _mcp(a: argparse.Namespace) -> int:
    """`adr mcp`: the server of `adr_store.mcp_server` (which imports the `mcp` package only
    when it builds the server, so the rest of `adr` runs without the `[mcp]` extra)."""
    return mcp_server.serve(a.store, a.as_user, a.emb_cache)


def _non_negative(s: str) -> int:
    v = int(s)
    if v < 0:
        raise argparse.ArgumentTypeError(f"must be 0 or more, got {v}")
    return v


def _positive(s: str) -> int:
    v = int(s)
    if v < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {v}")
    return v


AS_HELP = ("call as this user principal (e.g. user:acme-0) with the ACL enforced: the "
           "caller's view only, and no access at all if the ACL snapshot is missing, stale, "
           "for another content snapshot or does not know the caller (F1-F5). For tests and "
           "simulation only: ")


def _tool_parser(sub, name: str, help: str, fn) -> argparse.ArgumentParser:
    p = sub.add_parser(name, help=help,
                       description=None if name == "index" else f"{help}. {NOT_A_BOUNDARY}")
    where = p.add_mutually_exclusive_group(required=name != "index")
    where.add_argument("--store", type=Path, default=None, help="store directory")
    if name != "index":
        where.add_argument("--corpus", choices=NAMES,
                           help=f"use the store {STORE_ROOT}/<corpus>")
    p.add_argument("--emb-cache", type=Path, default=tools.DEFAULT_EMB_CACHE,
                   help="embedding cache directory (dense indexes only)")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    if name != "index":
        p.add_argument("--as", dest="as_user", default=None, metavar="USER",
                       help=AS_HELP + NOT_A_BOUNDARY)
    p.set_defaults(fn=fn)
    return p


def _filter_flags(p: argparse.ArgumentParser) -> None:
    f = p.add_argument_group("applicability filters (Phase 2; need an applicability overlay, "
                             "except --include-superseded)")
    f.add_argument("--include-superseded", action="store_true",
                   help="keep superseded documents (the Phase 1 view)")
    f.add_argument("--as-of", default=None, metavar="YYYY-MM-DD",
                   help="only documents in force on this date (replaces the superseded "
                        "default; excludes proposed rules unless --status names them)")
    f.add_argument("--status", action="append", default=None, metavar="S",
                   help="keep this status (repeatable)")
    f.add_argument("--jurisdiction", action="append", default=None, metavar="J",
                   help="keep this jurisdiction (repeatable)")
    f.add_argument("--max-tier", type=int, default=None, metavar="N",
                   help="keep authority tier N or lower (1 to 4)")


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="adr", description="Evidence store tools. " +
                                 NOT_A_BOUNDARY)
    sub = ap.add_subparsers(dest="command", required=True)
    ing = sub.add_parser("ingest", help="read a pinned corpus, or the loose files of a "
                                        "folder, into a store and commit a snapshot")
    what = ing.add_mutually_exclusive_group(required=True)
    what.add_argument("corpus", nargs="?", choices=NAMES, help="a pinned corpus")
    what.add_argument("--path", type=Path, default=None,
                      help="a folder of loose files (recursive; hidden files skipped, "
                           "symlinks not followed; extensions "
                           f"{' '.join(sorted(PATH_FORMATS))})")
    ing.add_argument("--store", required=True, type=Path, help="store directory")
    ing.set_defaults(fn=_ingest)

    idx = _tool_parser(sub, "index", "build or load the index of a system for the store's "
                                     "HEAD snapshot and make it the active index", _index)
    idx.add_argument("target", help=f"a corpus name (store {STORE_ROOT}/<corpus>, or --store) "
                                    f"or a store directory")
    idx.add_argument("--system", required=True, choices=tuple(tools.SYSTEMS))
    idx.add_argument("--lexical-only", action="store_true",
                     help="BM25 channel only: no embedding, fusion or reranker")
    idx.add_argument("--tuning", type=Path, default=None,
                     help="an adr-eval retrieval run (directory or retrieval.json) of this "
                          "system on this store snapshot, for its tuned w_bc and weight")
    idx.add_argument("--w-bc", type=int, default=None, help="breadcrumb weight (overrides "
                                                            "--tuning)")
    idx.add_argument("--weight", type=float, default=None,
                     help="linear fusion weight in [0, 1] (overrides --tuning)")
    idx.add_argument("--threads", type=_non_negative, default=1,
                     help="threads of the embedding model while building (default 1, as the "
                          "baseline; 0 = all cores); the vectors do not depend on it")

    se = _tool_parser(sub, "search", "ranked chunks for a query from the active index",
                      _search)
    se.add_argument("query")
    se.add_argument("--top", type=_positive, default=tools.SEARCH_TOP,
                    help=f"number of chunks (default {tools.SEARCH_TOP})")
    se.add_argument("--dedup", action=argparse.BooleanOptionalAction, default=None,
                    help="collapse copies to one hit per cluster (default: on when the "
                         "active index's chunks have a dedup overlay; `adr dedup build`)")
    _filter_flags(se)

    rd = _tool_parser(sub, "read", "the exact text of a document range", _read)
    rd.add_argument("doc_id", help="document id (or a unique prefix of 8+ characters)")
    rd.add_argument("--start", type=int, default=None)
    rd.add_argument("--end", type=int, default=None)
    rd.add_argument("--element", default=None, help="an element id of the document")
    rd.add_argument("--chunk", default=None, help="a chunk id of the active index")
    _filter_flags(rd)

    gr = _tool_parser(sub, "grep", "regular-expression matches in (doc_id, offset) order",
                      _grep)
    gr.add_argument("pattern", help="a Python regular expression (multi-line mode: ^ and $ "
                                    "match around \\n only)")
    gr.add_argument("--doc", default=None, help="search one document only")
    gr.add_argument("--max", type=_positive, default=tools.GREP_MAX,
                    help=f"at most this many matches (default {tools.GREP_MAX})")
    gr.add_argument("--ignore-case", action="store_true")
    gr.add_argument("--timeout", type=float, default=tools.GREP_TIMEOUT,
                    help=f"seconds the pattern may spend matching (default "
                         f"{tools.GREP_TIMEOUT:g}, at most {tools.GREP_TIMEOUT_MAX:g})")
    _filter_flags(gr)

    st = _tool_parser(sub, "search-tools", "ranked tools of the store's tool catalog for a query "
                                           "(Phase 2)", _search_tools)
    st.add_argument("query")
    st.add_argument("--top", type=_positive, default=tools.SEARCH_TOP,
                    help=f"number of tools (default {tools.SEARCH_TOP})")
    st.add_argument("--source-kind", action="append", default=None, metavar="K",
                    choices=tools.SOURCE_KINDS, help="keep tools of this source kind "
                                                     "(repeatable)")
    lt = _tool_parser(sub, "load-tool", "the MCP Tool definition of one tool (Phase 2)",
                      _load_tool)
    lt.add_argument("tool_id", help="tool id (or a unique prefix of 8+ characters)")

    app = sub.add_parser("applicability", help="the applicability overlay (Phase 2)")
    app_sub = app.add_subparsers(dest="action", required=True)
    der = app_sub.add_parser("derive", help="derive the applicability overlay of the store's "
                                            "HEAD snapshot and write it once")
    where = der.add_mutually_exclusive_group(required=True)
    where.add_argument("--store", type=Path, default=None, help="store directory")
    where.add_argument("--corpus", choices=NAMES, help=f"use the store {STORE_ROOT}/<corpus>")
    der.add_argument("--gov-config", type=Path, default=GOV_CONFIG,
                     help="the gov corpus config, for eCFR issuers (default "
                          "corpora/gov/config.json)")
    der.add_argument("--json", action="store_true", help="print the result as JSON")
    der.set_defaults(fn=_applicability_derive)

    dd = sub.add_parser("dedup", help="the dedup overlay (Phase 2)")
    dd_sub = dd.add_subparsers(dest="action", required=True)
    bld = dd_sub.add_parser("build", help="find exact and near-duplicate chunks of the active "
                                          "index and write the dedup overlay once")
    where = bld.add_mutually_exclusive_group(required=True)
    where.add_argument("--store", type=Path, default=None, help="store directory")
    where.add_argument("--corpus", choices=NAMES, help=f"use the store {STORE_ROOT}/<corpus>")
    bld.add_argument("--emb-cache", type=Path, default=tools.DEFAULT_EMB_CACHE,
                     help="embedding cache directory (to load a dense active index)")
    bld.add_argument("--json", action="store_true", help="print the result as JSON")
    bld.set_defaults(fn=_dedup_build)

    acl_p = sub.add_parser("acl", help="the ACL snapshot (Phase 2): sync and show",
                           description="ACL snapshots: `adr acl sync` runs one sync cycle "
                                       "(read and validate the directory and policy, compute "
                                       "every document's access list, write the snapshot, "
                                       "replace acl/HEAD atomically); `adr acl show` prints "
                                       "principals. " + NOT_A_BOUNDARY)
    acl_sub = acl_p.add_subparsers(dest="action", required=True)
    sy = acl_sub.add_parser("sync", help="one sync cycle: write a new ACL snapshot and move "
                                         "acl/HEAD to it", description=NOT_A_BOUNDARY)
    where = sy.add_mutually_exclusive_group(required=True)
    where.add_argument("--store", type=Path, default=None, help="store directory")
    where.add_argument("--corpus", choices=NAMES, help=f"use the store {STORE_ROOT}/<corpus>")
    sy.add_argument("--directory", type=Path, default=acl.DIRECTORY_PATH,
                    help="the directory (default config/acl/directory.json)")
    sy.add_argument("--policy", type=Path, default=acl.POLICY_PATH,
                    help="the policy (default config/acl/policy.json)")
    sy.add_argument("--json", action="store_true", help="print the result as JSON")
    sy.set_defaults(fn=_acl_sync)
    sh = acl_sub.add_parser("show", help="the principals of a chunk, a document or a user in "
                                         "the current ACL snapshot",
                            description=NOT_A_BOUNDARY)
    where = sh.add_mutually_exclusive_group(required=True)
    where.add_argument("--store", type=Path, default=None, help="store directory")
    where.add_argument("--corpus", choices=NAMES, help=f"use the store {STORE_ROOT}/<corpus>")
    what = sh.add_mutually_exclusive_group(required=True)
    what.add_argument("--chunk", default=None, help="a chunk id of the active index (or a "
                                                   "unique prefix of 8+ characters)")
    what.add_argument("--doc", default=None, help="a document id (or a unique prefix of 8+ "
                                                 "characters)")
    what.add_argument("--user", default=None, help="a user principal, e.g. user:acme-0")
    sh.add_argument("--emb-cache", type=Path, default=tools.DEFAULT_EMB_CACHE,
                    help="embedding cache directory (to load a dense active index)")
    sh.add_argument("--json", action="store_true", help="print the result as JSON")
    sh.set_defaults(fn=_acl_show)

    mc = sub.add_parser("mcp", help="serve the tools over MCP (stdio) as one caller (Phase 2; "
                                     "needs the [mcp] extra)",
                        description="Serve search, read, grep, search_tools and load_tool over "
                                    "MCP on stdio, as one caller with the ACL enforced on every "
                                    "call (code in adr_store.mcp_server). Without a caller "
                                    "(--as or ADR_CALLER) it refuses to start. " +
                                    mcp_server.HELP_HANDLES)
    mcp_server.add_arguments(mc)
    mc.set_defaults(fn=_mcp)

    qt = _tool_parser(sub, "query", "query a typed table: count, list, lookup or count_by "
                                    "(Phase 3; the query_table tool)", _query)
    qt.add_argument("--table", required=True, help="a table (adr tables show lists them)")
    qt.add_argument("--filters", dest="query_filters", default=None, metavar="JSON",
                    help='column filters as a JSON object, e.g. \'{"type": "Rule", '
                         '"year__gte": 2020}\'')
    qt.add_argument("--op", choices=OPS, default="count", help="default count")
    qt.add_argument("--fields", nargs="+", default=None, metavar="F",
                    help="lookup: the columns to show; count_by: the one column to group by")
    qt.add_argument("--order", nargs="+", default=None, metavar="F",
                    help="lookup: sort columns (descending: --order=-F)")
    qt.add_argument("--limit", type=_positive, default=QUERY_LIMIT,
                    help=f"lookup: at most this many rows (default {QUERY_LIMIT})")
    _filter_flags(qt)
    sq = _tool_parser(sub, "sql", "one guarded read-only SELECT over the typed tables (Phase 3; "
                                  "the sql tool)", _sql)
    sq.add_argument("statement", help="one SELECT statement")
    _filter_flags(sq)

    tb = sub.add_parser("tables", help="the typed tables (Phase 3): build, gate and show",
                        description="Typed tables of the store's HEAD snapshot: `build` writes "
                                    "a candidate build, `gate` promotes it to tables/HEAD "
                                    "through the merge gate, `show` prints a build. "
                                    + NOT_A_BOUNDARY)
    tb_sub = tb.add_subparsers(dest="action", required=True)
    tbb = tb_sub.add_parser("build", help="build the tables of the store's HEAD snapshot (a "
                                          "candidate: tables/HEAD does not move)")
    tbb.add_argument("--store", type=Path, required=True, help="store directory")
    tbb.add_argument("--tables-for", choices=("gov", "research"), default=None,
                     help="the corpus whose tables to build (default: the one the store's "
                          "documents are of)")
    tbb.add_argument("--with-extraction", action="store_true",
                     help="also build the extraction (3B) tables")
    tbb.add_argument("--generator", metavar="PROFILE", default=None,
                     help="model profile in config/models.json of an extraction build "
                          "(default: config generator); a metadata build calls no model")
    tbb.add_argument("--max-calls", type=_non_negative, default=0,
                     help="model calls an extraction build may make (default 0: cached "
                          "replies only)")
    tbb.add_argument("--json", action="store_true", help="print the result as JSON")
    tbb.set_defaults(fn=_tables_build)
    tbg = tb_sub.add_parser("gate", help="evaluate a candidate against tables/HEAD on gold sets "
                                         "and promote it when it has at most --max-flips flips")
    tbg.add_argument("--store", type=Path, required=True, help="store directory")
    tbg.add_argument("--candidate", required=True, help="the candidate's tables id")
    tbg.add_argument("--gold", type=Path, action="append", required=True, metavar="DIR",
                     help="a golden set (directory with items.jsonl, or the file); repeatable")
    tbg.add_argument("--max-flips", type=_non_negative, required=True,
                     help="cases HEAD answers right that the candidate may answer wrong")
    tbg.add_argument("--allow-unreadable-head", action="store_true",
                     help="promote even when HEAD cannot be evaluated under the current "
                          "contracts (no comparison)")
    tbg.add_argument("--json", action="store_true", help="print the result as JSON")
    tbg.set_defaults(fn=_tables_gate)
    tbs = tb_sub.add_parser("show", help="a build's manifest and semantic layer (default: "
                                         "tables/HEAD)")
    tbs.add_argument("--store", type=Path, required=True, help="store directory")
    tbs.add_argument("--tables", default=None, metavar="ID", help="a tables id (default HEAD)")
    tbs.add_argument("--json", action="store_true", help="print the result as JSON")
    tbs.set_defaults(fn=_tables_show)
    tl = sub.add_parser("tools", help="the tool catalog (Phase 2): tool records as data")
    tl_sub = tl.add_subparsers(dest="action", required=True)
    ti = tl_sub.add_parser("ingest", help="add the tools of one source to a store's tool "
                                          "catalog and commit a tool snapshot")
    src = ti.add_mutually_exclusive_group(required=True)
    src.add_argument("--mcp", type=Path, default=None, metavar="F",
                     help="a captured tools/list file (server, version, source_uri, license, "
                          "tools_list)")
    src.add_argument("--openapi", type=Path, default=None, metavar="F",
                     help="an OpenAPI 3.x JSON document (needs --source-uri and --license)")
    src.add_argument("--toolret", action="store_true",
                     help="the local ToolRet toolbench tools (`adr-eval tools-fetch` first)")
    ti.add_argument("--store", type=Path, default=None,
                    help=f"store directory (made a tools-only store if new; default "
                         f"{TOOL_STORE} with --toolret)")
    ti.add_argument("--root", type=Path, default=None,
                    help="--toolret: the data directory (default data/tools)")
    ti.add_argument("--source-uri", default=None, help="the records' source_uri")
    ti.add_argument("--source-version", default=None,
                    help="the records' source_version (default: the file's version)")
    ti.add_argument("--license", default=None, help="the records' licence")
    ti.add_argument("--json", action="store_true", help="print the result as JSON")
    ti.set_defaults(fn=_tools_ingest)
    tx = tl_sub.add_parser("index", help="build or load the tool index of the store's tool "
                                         "catalog (tools/HEAD) and make it the active one")
    tx.add_argument("--store", type=Path, default=None,
                    help=f"store directory (default {TOOL_STORE})")
    tx.add_argument("--w-name", type=_non_negative, required=True,
                    help="times the split tool name is repeated in the BM25 text (tuned by "
                         "`adr-eval tools-retrieval`)")
    mode = tx.add_mutually_exclusive_group(required=True)
    mode.add_argument("--weight", type=float, default=None,
                      help="linear fusion weight in [0, 1] on BM25 (tuned)")
    mode.add_argument("--lexical-only", action="store_true",
                      help="BM25 channel only: no embedding, no fusion")
    tx.add_argument("--emb-cache", type=Path, default=tools.DEFAULT_EMB_CACHE,
                    help="embedding cache directory (dense index only)")
    tx.add_argument("--threads", type=_non_negative, default=1,
                    help="threads of the embedding model while building (default 1; 0 = all "
                         "cores); the vectors do not depend on it")
    tx.add_argument("--json", action="store_true", help="print the result as JSON")
    tx.set_defaults(fn=_tools_index)
    return ap


def _silence_stdout() -> None:
    """Point stdout at /dev/null, so the interpreter's flush at exit does not fail again."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
    except (OSError, ValueError):  # no file descriptor (a replaced sys.stdout)
        pass


def main(argv: list[str] | None = None) -> int:
    a = _parser().parse_args(argv)
    code = None
    try:
        code = a.fn(a)
        sys.stdout.flush()  # inside the try: a closed pipe shows here, not at exit
        return code
    except BrokenPipeError:
        # the reader stopped early (`adr ... | head`): every command prints after its work is
        # done, so only output is lost; stop quietly (with the command's own code if it had
        # one), and keep the interpreter's flush at exit from failing too
        _silence_stdout()
        return 0 if code is None else code
    except (RunError, LocalFilesMissing, ExtractionError, StoreError, tools.ToolError,
            acl.AclDenied, _UsageError, ToolRetMissing, HashMismatch) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_LOAD_OR_STORE
    except _Unexpected as e:
        doc = f" ({e.doc_id[:12]})" if e.doc_id else ""
        print(f"error: unexpected {_one_line(e.error)} while processing {e.path}{doc}; "
              f"no snapshot written", file=sys.stderr)
        return EXIT_UNEXPECTED
    except Exception as e:  # a bug outside any one document
        print(f"error: unexpected {_one_line(e)} in adr {a.command}", file=sys.stderr)
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    sys.exit(main())
