"""`adr` command line: `adr ingest <corpus> --store <dir>` and `adr ingest --path <folder>
--store <dir>` (below), and the retrieval tools `adr index`, `adr search`, `adr read` and
`adr grep` (spec §9; the code is in `adr_store.tools`, this module only parses arguments and
prints).

The tools take the store as `--store <dir>` or `--corpus <name>` (the store
`.cache/store/<name>`); `adr index` takes a corpus name or a store directory as its argument.
`--json` prints the result as JSON, otherwise a short table; every result names its snapshot.
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
import json
import os
import stat
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePath

from adr_eval.corpora.base import Document, ExtractionError, sha256_bytes
from adr_eval.corpora.extract import extract_text
from adr_eval.corpora.registry import NAMES, LocalFilesMissing, check_local_files
from adr_eval.runner import RunError, load_checked_corpus
from adr_store import tools
from adr_store.store import (
    Added,
    ConformanceError,
    Store,
    StoreError,
    stored_source,
    write_atomic,
)

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
    return tools.Tools(_store_of(a), emb_cache=a.emb_cache)


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


def _search(a: argparse.Namespace) -> int:
    res = _tools(a).search(a.query, top=a.top)
    if a.json:
        _print_json(res)
        return 0
    lex = ", lexical only" if res.lexical_only else ""
    print(f"snapshot {res.snapshot[:12]}  index {res.system} {res.fingerprint[:12]}{lex}  "
          f"{len(res.hits)} hit(s)")
    print(f"{'rank':>4}  {'score':>10}  {'chunk':<12}  {'doc':<12}  {'range':<15}  breadcrumb")
    for h in res.hits:
        print(f"{h.rank:>4}  {h.score:>10.4f}  {h.chunk_id[:12]}  {h.doc_id[:12]}  "
              f"{f'{h.char_start}-{h.char_end}':<15}  {_cut(h.breadcrumb)}")
    return 0


def _read(a: argparse.Namespace) -> int:
    res = _tools(a).read(a.doc_id, a.start, a.end, element=a.element, chunk=a.chunk)
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
                         timeout=a.timeout)
    if a.json:
        _print_json(res)
        return 0
    more = f" (stopped at --max {res.max})" if res.truncated else ""
    print(f"snapshot {res.snapshot[:12]}  {len(res.matches)} match(es){more}")
    for m in res.matches:
        print(f"{m.doc_id[:12]}  {m.char_start}-{m.char_end}  line {m.line}  "
              f"{_cut(m.context, 2 * TABLE_FIELD)}")
    return 0


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


def _tool_parser(sub, name: str, help: str, fn) -> argparse.ArgumentParser:
    p = sub.add_parser(name, help=help)
    where = p.add_mutually_exclusive_group(required=name != "index")
    where.add_argument("--store", type=Path, default=None, help="store directory")
    if name != "index":
        where.add_argument("--corpus", choices=NAMES,
                           help=f"use the store {STORE_ROOT}/<corpus>")
    p.add_argument("--emb-cache", type=Path, default=tools.DEFAULT_EMB_CACHE,
                   help="embedding cache directory (dense indexes only)")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p.set_defaults(fn=fn)
    return p


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="adr", description="Evidence store tools.")
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

    rd = _tool_parser(sub, "read", "the exact text of a document range", _read)
    rd.add_argument("doc_id", help="document id (or a unique prefix of 8+ characters)")
    rd.add_argument("--start", type=int, default=None)
    rd.add_argument("--end", type=int, default=None)
    rd.add_argument("--element", default=None, help="an element id of the document")
    rd.add_argument("--chunk", default=None, help="a chunk id of the active index")

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
    return ap


def main(argv: list[str] | None = None) -> int:
    a = _parser().parse_args(argv)
    try:
        return a.fn(a)
    except (RunError, LocalFilesMissing, ExtractionError, StoreError, tools.ToolError,
            _UsageError) as e:
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
