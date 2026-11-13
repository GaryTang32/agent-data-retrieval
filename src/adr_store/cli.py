"""`adr` command line. Task 1 provides `adr ingest <corpus> --store <dir>`.

Ingest reads a pinned corpus through the harness (the manifest is verified, the canonical text
is the harness's), parses and checks every document, and commits one snapshot. Any
conformance violation fails the command with the documents and rules named, and no snapshot
is written. The compile figures of spec §10.3 are printed and written to
`<store>/compile/<snapshot>.json` (no timings in that file, so it is reproducible).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

from adr_eval.corpora.base import ExtractionError
from adr_eval.corpora.registry import NAMES, LocalFilesMissing, check_local_files
from adr_eval.runner import RunError, load_checked_corpus
from adr_store.store import Added, ConformanceError, Store, StoreError, write_atomic

UNKNOWN_LICENSES = frozenset({"", "unknown"})
PROBLEMS_SHOWN = 5


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


def compile_figures(corpus: str, snapshot: str, added: list[Added], checked: int,
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


def _print_figures(f: dict, seconds: float) -> None:
    print(f"{f['corpus']}: snapshot {f['snapshot']}")
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


def _ingest(a: argparse.Namespace) -> int:
    t0 = time.perf_counter()
    check_local_files(a.corpus)
    loaded = load_checked_corpus(a.corpus)
    store = Store.create(a.store)
    added: list[Added] = []
    failures: list[tuple[str, ConformanceError]] = []
    manifest_docs = sorted(loaded.manifest.documents, key=lambda d: d.doc_id)
    for d in manifest_docs:
        raw = (loaded.root / d.path).read_bytes()
        license = None if d.license.strip().lower() in UNKNOWN_LICENSES else d.license
        try:
            added.append(store.add(loaded.docs[d.doc_id], raw, license=license))
        except ConformanceError as e:
            failures.append((d.path, e))
    if failures:
        print(f"error: {len(failures)} of {len(manifest_docs)} documents fail conformance; "
              f"no snapshot written", file=sys.stderr)
        for path, e in failures:
            print(f"  {path} ({e.doc_id[:12]}):", file=sys.stderr)
            for p in e.problems[:PROBLEMS_SHOWN]:
                print(f"    {p}", file=sys.stderr)
        return 1
    snapshot = store.commit()
    figures = compile_figures(a.corpus, snapshot, added, len(manifest_docs), 0)
    payload = json.dumps(figures, indent=2, sort_keys=True) + "\n"
    write_atomic(Path(a.store) / "compile" / f"{snapshot}.json", payload.encode("utf-8"))
    _print_figures(figures, time.perf_counter() - t0)
    return 0


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="adr", description="Evidence store tools.")
    sub = ap.add_subparsers(dest="command", required=True)
    ing = sub.add_parser("ingest", help="read a pinned corpus into a store and commit a "
                                        "snapshot")
    ing.add_argument("corpus", choices=NAMES)
    ing.add_argument("--store", required=True, type=Path, help="store directory")
    ing.set_defaults(fn=_ingest)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = _parser().parse_args(argv)
    try:
        return a.fn(a)
    except (RunError, LocalFilesMissing, ExtractionError, StoreError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
