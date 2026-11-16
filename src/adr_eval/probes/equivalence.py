"""Equivalence probes (Phase 2 spec §6.2, §10.2, criterion B2) and the reference stores they
and the ACL leak probes compare against.

A **reference store** (`view_store`) holds only one view's documents: each is ingested again
from the source store (its raw blob and its stored text, uri, format, version and licence,
through `Store.add`, which parses it again; every doc record must hash as the source's), the
snapshot is committed, the applicability overlay is derived (the gov config, as the harness
does), the source's active system is indexed with the source's settings (`w_bc`, `w`,
lexical-only), the dedup overlay is built over the view's chunks, and one ACL sync runs from
the same directory and policy, so the view's caller sees the whole reference store. A file
`view.json` written last records what it holds; `ensure_view_store` reuses a store whose
`view.json` matches and syncs it again when its ACL snapshot is stale (F3).

**Views** (`views`): the distinct sets of documents the directory's users see under the
store's ACL snapshot, each with its first user (sorted) as the caller.

**B2** (`run`): for each view, `QUESTIONS` (50) golden questions sampled by seeded hash
(`SEED`) of the item id; for each question `search` and `grep` in two views of the filters,
on the store as the view's caller and on the reference store as the same caller, both with
the ACL layer (so both score dense rows with the row-exact kernel):

- `phase1`: `include_superseded`, dedup off (the Phase 1 view);
- `p2-default`: the default filters, or the item's own `as_of` for a dated `policy_asof`
  item, dedup on.

Grep's pattern is the question's longest word of at least four letters or digits (ties: the
first in sorted order), escaped, case-insensitive. Results must be identical: every hit's
rank, chunk, document, span, breadcrumb, score (full float precision), scoring chunk and
alternates, and `excluded_by_filter`, `short_by` and the dedup state; every grep match's
document, span, line, text and context, `truncated` and `excluded_by_filter`; or the same
refusal (snapshot ids, which differ between the stores, replaced). Store-specific fields (the
snapshot, the index fingerprint, the overlay ids) are not compared.

This module may import `adr_store` directly (plan, shared rules).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from adr_eval.corpora.base import Document
from adr_eval.models import GoldenItem
from adr_eval.probes import SEED
from adr_store import acl, applicability, dedup
from adr_store.store import Store, StoreError
from adr_store.tools import DEFAULT_EMB_CACHE, ToolError, Tools

QUESTIONS = 50
VIEW_FILE = "view.json"
MODES = ("phase1", "p2-default")
_WORD = re.compile(r"[A-Za-z0-9]{4,}")


def canonical(data: dict) -> bytes:
    """Canonical JSON of a plain dict (sorted keys, compact, UTF-8, one trailing newline)."""
    return (json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            + "\n").encode("utf-8")


def gov_config() -> dict:
    """The gov config the deriver reads (the harness's `_ensure_overlays` uses the same)."""
    from adr_store.cli import GOV_CONFIG

    return json.loads(GOV_CONFIG.read_text(encoding="utf-8"))


# -- reference stores -------------------------------------------------------------------------


def _active(store_path: Path) -> dict:
    return json.loads((Path(store_path) / "index" / "active.json").read_text(encoding="utf-8"))


def _view_record(src: Store, docs: list[str], active: dict, directory: Path,
                 policy: Path) -> dict:
    return {"source_snapshot": src.snapshot_id, "view": acl.view_id(docs),
            "documents": len(docs), "system": active["system"],
            "lexical_only": active["lexical_only"], "w_bc": active["w_bc"], "w": active["w"],
            "directory_sha256": hashlib.sha256(Path(directory).read_bytes()).hexdigest(),
            "policy_sha256": hashlib.sha256(Path(policy).read_bytes()).hexdigest()}


def view_store(src: Store, doc_ids: Iterable[str], dst: Path, *,
               emb_cache: Path = DEFAULT_EMB_CACHE, directory: Path = acl.DIRECTORY_PATH,
               policy: Path = acl.POLICY_PATH, clock: Callable = acl.utc_now) -> Store:
    """The reference store of `doc_ids` at `dst` (module docstring): built from nothing
    (`dst` must not hold a store), overlays derived, indexed, synced, `view.json` last."""
    dst = Path(dst)
    if (dst / "HEAD").exists():
        raise StoreError(f"{dst}: already holds a store; remove it or use ensure_view_store")
    docs = sorted(set(doc_ids))
    active = _active(src.path)
    store = Store.create(dst)
    for d in docs:
        source = src.source(d)
        raw = (src.path / "blobs" / d[:2] / d).read_bytes()
        store.add(Document(d, src.text(d), source.format, source.source_version, source.uri),
                  raw, source.license)
        if store._records[d] != src._records[d]:
            raise StoreError(f"{dst}: document {d} re-ingested to another doc record than the "
                             f"source's (another parser or extractor?)")
    store.commit()
    store = Store.open(dst)
    overlay, report = applicability.derive(store, gov_config())
    applicability.write_overlay(dst, overlay)
    applicability.write_report(dst, report)
    t = Tools(dst, emb_cache=emb_cache)
    t.index(active["system"], lexical_only=active["lexical_only"], w_bc=active["w_bc"],
            weight=None if active["lexical_only"] else active["w"])
    idx = t.active_index()
    dedup.write_overlay(dst, dedup.build(list(idx.chunks.values()), idx.snapshot, idx.chunker))
    acl.sync(dst, directory, policy, clock=clock)
    rec = {**_view_record(src, docs, active, directory, policy),
           "snapshot": store.snapshot_id, "index": idx.fingerprint}
    (dst / VIEW_FILE).write_bytes(canonical(rec))
    return store


def ensure_view_store(src: Store, doc_ids: Iterable[str], dst: Path, *,
                      emb_cache: Path = DEFAULT_EMB_CACHE, directory: Path = acl.DIRECTORY_PATH,
                      policy: Path = acl.POLICY_PATH,
                      clock: Callable = acl.utc_now) -> tuple[Store, str]:
    """(the reference store of `doc_ids` at `dst`, "built" | "reused" | "reused, synced"):
    a store whose `view.json` matches is reused (synced again if its ACL snapshot is stale or
    not for its HEAD); anything else at `dst` is refused, nothing is at `dst`: built."""
    dst = Path(dst)
    docs = sorted(set(doc_ids))
    if not dst.exists():
        return view_store(src, docs, dst, emb_cache=emb_cache, directory=directory,
                          policy=policy, clock=clock), "built"
    want = _view_record(src, docs, _active(src.path), directory, policy)
    try:
        rec = json.loads((dst / VIEW_FILE).read_text(encoding="utf-8"))
        store = Store.open(dst)
    except (OSError, ValueError, StoreError) as e:
        raise StoreError(f"{dst}: exists but is not a finished reference store ({e}); remove "
                         f"it") from e
    have = {k: rec.get(k) for k in want}
    if have != want or store.doc_ids() != docs or rec.get("snapshot") != store.snapshot_id:
        raise StoreError(f"{dst}: holds another view or settings than asked; remove it")
    try:
        sid, snap = acl.read_head(dst)
        if snap.content_snapshot != store.snapshot_id:
            raise acl.AclDenied("F2", "not for HEAD")
        acl.check_fresh(snap, clock=clock)
        return store, "reused"
    except acl.AclDenied:
        acl.sync(dst, directory, policy, clock=clock)
        return store, "reused, synced"


def describe(path: Path) -> dict:
    """What a reference store holds, for the run record: content snapshot, index, overlays,
    ACL snapshot and sequence, and the document count."""
    path = Path(path)
    store = Store.open(path)
    rec = json.loads((path / VIEW_FILE).read_text(encoding="utf-8"))
    sid, snap = acl.read_head(path)
    app = applicability.load_overlay(path, store.snapshot_id)
    return {"path": path.name, "view": rec["view"], "documents": rec["documents"],
            "snapshot": store.snapshot_id, "index": rec["index"],
            "applicability": None if app is None else app.overlay_id,
            "acl_snapshot": sid, "acl_sequence": snap.sequence}


# -- views and questions ----------------------------------------------------------------------


@dataclass(frozen=True)
class View:
    view: str  # acl.view_id of the documents
    caller: str  # the first user (sorted) who sees exactly these documents
    users: tuple[str, ...]
    docs: frozenset[str]

    def summary(self) -> dict:
        return {"view": self.view, "caller": self.caller, "users": list(self.users),
                "documents": len(self.docs)}


def views(snap: acl.AclSnapshot) -> list[View]:
    """The distinct views of the snapshot's users, in order of their first user."""
    by: dict[frozenset[str], list[str]] = {}
    for user in sorted(snap.directory):
        ps = frozenset(snap.directory[user])
        docs = frozenset(d for d, v in snap.docs.items() if not ps.isdisjoint(v))
        by.setdefault(docs, []).append(user)
    out = [View(acl.view_id(docs), users[0], tuple(users), docs) for docs, users in by.items()]
    return sorted(out, key=lambda v: v.caller)


def _h(*parts: object) -> int:
    return int(hashlib.sha256(":".join(str(p) for p in parts).encode("utf-8")).hexdigest(), 16)


def questions(items: list[GoldenItem], n: int = QUESTIONS, seed: int = SEED
              ) -> list[GoldenItem]:
    """`n` items by seeded hash of their id (all of them when there are fewer)."""
    return sorted(items, key=lambda i: (_h(seed, "b2", i.id), i.id))[:n]


def grep_pattern(question: str) -> str:
    """The question's longest word of at least 4 letters or digits (ties: first in sorted
    order), escaped; the whole question escaped when it has none."""
    words = sorted(set(_WORD.findall(question)), key=lambda w: (-len(w), w))
    return re.escape(words[0] if words else question.strip() or question)


def filters_for(item: GoldenItem, mode: str) -> tuple[dict, bool | None]:
    """(filters, dedup) of one mode for one item."""
    if mode == "phase1":
        return {"include_superseded": True}, False
    if item.qtype == "policy_asof" and item.as_of is not None:
        return {"as_of": item.as_of.isoformat()}, True
    return {}, True


# -- comparing results ------------------------------------------------------------------------


_SNAP = re.compile(r"\b[0-9a-f]{12}…")


def _error(e: Exception) -> tuple:
    return ("error", type(e).__name__, getattr(e, "code", None), _SNAP.sub("<id>…", str(e)))


def search_key(res) -> tuple:
    """What B2 compares of a search result (module docstring)."""
    return ("ok", [(h.rank, h.chunk_id, h.doc_id, h.char_start, h.char_end, h.breadcrumb,
                    h.score, h.scored_by,
                    [(a.chunk_id, a.doc_id, a.kind, a.jaccard) for a in h.alternates])
                   for h in res.hits],
            res.excluded_by_filter, res.short_by, res.dedup is None, res.dedup_note,
            res.filters, res.top, res.query)


def grep_key(res) -> tuple:
    return ("ok", [(m.doc_id, m.char_start, m.char_end, m.line, m.match, m.context)
                   for m in res.matches],
            res.truncated, res.excluded_by_filter, res.filters, res.pattern, res.max,
            res.ignore_case, res.doc)


def outcome(fn: Callable, key: Callable) -> tuple:
    """`key(fn())`, or the refusal as `_error` (a ToolError only; anything else raises)."""
    try:
        return key(fn())
    except ToolError as e:
        return _error(e)


def first_difference(a: tuple, b: tuple) -> str:
    """Where two keys first differ, without their contents (no corpus text in summaries)."""
    if a[0] != b[0]:
        return f"{a[0]} vs {b[0]}"
    if a[0] == "error":
        return "different refusals"
    if a[1] != b[1]:
        la, lb = a[1], b[1]
        for k, (x, y) in enumerate(zip(la, lb, strict=False)):
            if x != y:
                fields = [i for i, (p, q) in enumerate(zip(x, y, strict=False)) if p != q]
                return f"item {k + 1} differs in fields {fields}"
        return f"{len(la)} vs {len(lb)} items"
    rest = [i for i, (p, q) in enumerate(zip(a[2:], b[2:], strict=False), start=2) if p != q]
    return f"fields {rest}"


@dataclass(frozen=True)
class Check:
    view: str
    caller: str
    item_id: str
    tool: str
    mode: str
    identical: bool
    outcome: str  # "ok" or "error"
    hits: int
    difference: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def compare_view(t: Tools, ref: Tools, view: View, items: list[GoldenItem]) -> list[Check]:
    """B2 for one view: every item, both tools, both modes, on `t` (the store, as the view's
    caller) and `ref` (its reference store, as the same caller)."""
    out = []
    for item in items:
        pattern = grep_pattern(item.question)
        for mode in MODES:
            filters, dd = filters_for(item, mode)
            calls = {
                "search": (lambda tt, q=item.question, f=filters, d=dd: tt.search(
                    q, filters=f, dedup=d), search_key),
                "grep": (lambda tt, p=pattern, f=filters: tt.grep(p, ignore_case=True,
                                                                  filters=f), grep_key)}
            for tool, (call, key) in calls.items():
                a = outcome(lambda c=call: c(t), key)
                b = outcome(lambda c=call: c(ref), key)
                same = a == b
                out.append(Check(view.view, view.caller, item.id, tool, mode, same, a[0],
                                 len(a[1]) if a[0] == "ok" else 0,
                                 None if same else first_difference(a, b)))
    return out


def summarize(checks: list[Check]) -> dict:
    by: dict[str, dict] = {}
    for c in checks:
        b = by.setdefault(f"{c.tool}/{c.mode}", {"n": 0, "identical": 0, "refused": 0,
                                                  "empty": 0, "hits": 0})
        b["n"] += 1
        b["identical"] += c.identical
        b["refused"] += c.outcome == "error"
        b["empty"] += c.outcome == "ok" and c.hits == 0
        b["hits"] += c.hits
    return {"n": len(checks), "identical": sum(c.identical for c in checks),
            "differing": sum(not c.identical for c in checks),
            "views": len({c.view for c in checks}),
            "items": len({c.item_id for c in checks}), "by_tool_mode": dict(sorted(by.items()))}
