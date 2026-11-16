r"""ACL probes (Phase 2 spec §5.4, §10.2, criteria B1, B4, B5) for the content tools `search`,
`grep` and `read`; deterministic (seed `SEED`), no model calls, run through
`adr_store.tools.Tools` with the ACL layer.

**Leak probes** (`leak_probes`). Each probe is a (caller, target) pair: the target is a
document or chunk the caller cannot see. Callers are the directory's users and `user:ghost`
(not in the directory); for probe `k` of a family a seeded hash picks the caller among those
with at least one hidden target (the auditor sees everything and has none), then the target
among the caller's hidden ones; a pair already taken draws again. Per store:

- `search-rare` (100): `search` of the 10 rarest tokens (highest IDF over all the index's
  chunks; ties by token) of a hidden chunk;
- `search-title` (50): `search` of a hidden document's title (its first non-blank line, even
  `k`) or breadcrumb (its first chunk's, odd `k`);
- `grep-literal` (50): `grep` of a 30-character substring found in that hidden document
  only (escaped);
- `grep-doc` (20): `grep(doc=...)` of a hidden document, by full id (even `k`) or
  8-character prefix (odd `k`);
- `read` (60): `read` of a hidden document by full id, by 8-character prefix, of a hidden
  chunk (of a visible document), of a hidden document's element (15 each);
- `alternate-cross-view` (as many as exist): for each dedup cluster whose members' documents
  have different access lists, each directory user who sees some members and not others
  searches the 10 rarest tokens of a visible member (`cross_view_probes`); the visible
  member's rank is reported.

Search, grep and read run with `include_superseded` (nothing masked by applicability) and
search with dedup on when the store has an overlay (so alternates are exercised).

**Leak kinds** (`check`, spec §10.2), each True (a leak), False (checked, none) or None (does
not apply to this outcome):

- `id_outside_view`: a returned document or chunk id (hit, scoring chunk, match, read) whose
  document the caller cannot see;
- `alternate_outside_view`: an alternate whose document the caller cannot see;
- `hidden_text`: text not attributable to a visible document (a breadcrumb, match, context or
  read text that is not the visible document's own), the probe's secret (the `grep-literal`
  substring) anywhere in the result or refusal, or a hidden id (8+ hex characters that begin
  a hidden document or chunk id and were not given by the caller) in a refusal;
- `not_found_differs`: a refusal for a hidden id that differs from the refusal for an id
  that names nothing (the same store and caller; a full id: one with the same first 12
  characters, so byte for byte; a prefix: an 8-character prefix of no id, compared with each
  given string replaced by `<given>`). A prefix that resolves to a visible document is no
  leak (prefixes resolve among visible ids);
- `count_includes_hidden`: `excluded_by_filter`, `short_by`, `truncated` or the number of
  hits or matches differ from the same call on the caller's reference store;
- `score_differs`: hits (ids, scores at full precision, scoring chunks, alternates) or
  matches differ from the reference store's (B2).

`user:ghost` must be denied (F4) with no content; any other denial or an unexpected error
makes the probe invalid (reported, not a pass).

**Fail closed** (`failclosed_probes`, `run_failclosed`): F1–F5 and "no entry" × `search`,
`grep`, `read` × 5 callers = 90 per store. One target document (seeded, not in a chain, whose
uri begins no other document's) that must pass a precondition, so that "no entry" can fail:
every one of the five directory callers sees it before the rule, finds it in the top 10 of the
search query (its title, else the 10 rarest tokens of its first chunk), matches it with the
grep pattern and reads it (`failclosed_target`, `tools_precheck`); the next seeded candidate is
tried otherwise, and none qualifying is an error. The result rows record `visible_before`,
`top10_before` and `rank_before` per probe. Callers (planner's call): F1–F3 and "no entry" use
five directory users (`user:auditor`, `user:outsider` and three by seeded hash); F4 uses
`None`, `user:ghost`, `user:nobody`, `user:acme-6`, `user:auditor2`; F5 `group:acme/0`,
`public`, `user:`, `user:Ghost`, `tenant:acme`. F1 (a variant per caller: HEAD missing, HEAD
unreadable, an unparsable snapshot, a schema-invalid one, a file whose hash is not its id), F2
(a new content snapshot without the target), F3 (synced with a clock 2 h behind for three
callers, 1 h ahead for two) and "no entry" (re-synced from the policy plus an attribute rule
mapping the target's uri to `[]`) run on `cp -a` clones of the store, removed afterwards; F4
and F5 on the store itself. Pass: F1–F5 refuse with that code and return nothing; "no entry"
returns nothing of the target (no hit, alternate, scoring chunk or match of it, its secret
nowhere, and `read` refused exactly as an id that names nothing).

**Log fields** (`log_size`, `scan_log`, B5): every line written has `caller`, `principals`,
`acl_snapshot` and `acl_decision`, and every `allowed` line has a non-null `caller`,
`principals`, `acl_snapshot` and `view` (a denied line may hold nulls where access was not
resolved; an `off` line has no ACL layer).

**The tool tools** (`search_tools`, `load_tool`): 200 leak probes, 80 fail-closed probes and
their judges, in the last section of this module (`adr-eval tools-probes`).

This module may import `adr_store` directly (plan, shared rules).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from pathlib import Path

from adr_eval.probes import SEED
from adr_eval.probes.equivalence import canonical, grep_key, search_key
from adr_eval.probes.temporal import first_line
from adr_eval.retrieval.chunker import tokenize
from adr_store import acl
from adr_store.applicability import chain_of
from adr_store.store import Store
from adr_store.tools import AccessDenied, ToolError

FAMILY_SIZES = {"search-rare": 100, "search-title": 50, "grep-literal": 50, "grep-doc": 20,
                "read": 60}
FAMILY_TOOL = {"search-rare": "search", "search-title": "search", "grep-literal": "grep",
               "grep-doc": "grep", "read": "read", "alternate-cross-view": "search"}
READ_KINDS = ("doc", "prefix", "chunk", "element")
KINDS = ("id_outside_view", "alternate_outside_view", "hidden_text", "not_found_differs",
         "count_includes_hidden", "score_differs")
GHOST = "user:ghost"
RARE_TOKENS = 10
SUBSTRING = 30
PREFIX = 8
WIDE = {"include_superseded": True}

CONDITIONS = ("F1", "F2", "F3", "F4", "F5", "no_entry")
TOOLS = ("search", "grep", "read")
F1_VARIANTS = ("missing", "unreadable", "unparsable", "schema-invalid", "hash-not-id")
F3_VARIANTS = ("stale", "stale", "stale", "future", "future")
F4_CALLERS = (None, "user:ghost", "user:nobody", "user:acme-6", "user:auditor2")
F5_CALLERS = ("group:acme/0", "public", "user:", "user:Ghost", "tenant:acme")
FIXED_USERS = ("user:auditor", "user:outsider")
STALE = timedelta(hours=2)
AHEAD = timedelta(hours=1)
REQUIRED = ("caller", "principals", "acl_snapshot", "acl_decision")
RESOLVED = ("caller", "principals", "acl_snapshot", "view")  # non-null on an allowed line
_HEX = re.compile(r"[0-9a-f]{8,}")


def _h(*parts: object) -> int:
    return int(hashlib.sha256(":".join(str(p) for p in parts).encode("utf-8")).hexdigest(), 16)


# -- the store as the probes see it -----------------------------------------------------------


@dataclass
class Context:
    """The store, its ACL snapshot and its active index's chunks (the operator's view, used
    to build probes and judge results; never shown to a caller)."""

    store: Store
    snap: acl.AclSnapshot
    chunks: dict  # chunk id -> StoreChunk, in index order
    clusters: list = field(default_factory=list)  # dedup clusters: sorted member chunk ids
    _texts: dict = field(default_factory=dict)
    _visible: dict = field(default_factory=dict)
    _doc_chunks: dict | None = None

    def text(self, doc_id: str) -> str:
        if doc_id not in self._texts:
            self._texts[doc_id] = self.store.text(doc_id)
        return self._texts[doc_id]

    def visible(self, caller: str | None) -> frozenset[str]:
        """The documents `caller` sees under the snapshot (none for one not in it)."""
        if caller not in self._visible:
            ps = frozenset(self.snap.directory.get(caller, ())) if isinstance(caller, str) \
                else frozenset()
            self._visible[caller] = frozenset(
                d for d, v in self.snap.docs.items() if not ps.isdisjoint(v))
        return self._visible[caller]

    def hidden(self, caller: str | None) -> list[str]:
        seen = self.visible(caller)
        return [d for d in self.store.doc_ids() if d not in seen]

    def doc_chunks(self) -> dict[str, list[str]]:
        if self._doc_chunks is None:
            out: dict[str, list] = {}
            for c in self.chunks.values():
                out.setdefault(c.doc_id, []).append(c)
            self._doc_chunks = {d: [c.chunk_id for c in sorted(cs, key=lambda c: (
                c.char_start, c.chunk_id))] for d, cs in out.items()}
        return self._doc_chunks

    def callers(self) -> list[str]:
        return [*sorted(self.snap.directory), GHOST]


def context(store_path: Path, idx) -> Context:
    """The probes' view of the store at `store_path` with its active index `idx` (a
    `StoreIndex`): its chunks and its dedup overlay's clusters (none without an overlay)."""
    from adr_store import dedup
    from adr_store.retrieval.index import chunk_content_sha256

    store = Store.open(store_path)
    dd = dedup.load_overlay(store_path, store.snapshot_id, idx.chunker,
                            chunk_content_sha256(idx.chunks.values()))
    clusters = [] if dd is None else [sorted(c.members) for _, c in sorted(dd.clusters.items())]
    return Context(store, acl.read_head(store_path)[1], idx.chunks, clusters)


# -- probes ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Probe:
    probe_id: str
    family: str
    tool: str
    caller: str | None
    target: dict
    call: dict
    control: dict | None = None  # the call's arguments replaced to name nothing

    def to_dict(self) -> dict:
        return asdict(self)


def absent_like(x: str, taken) -> str:
    """An id with the same first 12 characters (so the same short form) that names nothing."""
    for c in "0123456789abcdef":
        y = x[:12] + c + x[13:]
        if y != x and y not in taken:
            return y
    raise ValueError(f"no absent id like {x[:12]}")


def absent_prefix(seed: object, taken: list[str], n: int = PREFIX) -> str:
    """A seeded `n`-hex-character prefix that begins no id of `taken` (sorted)."""
    for k in range(10_000):
        p = f"{_h(seed, 'absent', k):064x}"[:n]
        if not any(t.startswith(p) for t in taken):
            return p
    raise ValueError("no absent prefix")


def idf_order(chunks) -> dict[str, int]:
    """Document frequency of every token over the chunks' texts."""
    df: Counter[str] = Counter()
    for c in chunks:
        df.update(set(tokenize(c.text)))
    return df


def rare_tokens(text: str, df: dict[str, int], n: int = RARE_TOKENS) -> list[str]:
    """The `n` distinct tokens of `text` with the highest IDF (lowest document frequency;
    ties by token)."""
    return sorted(set(tokenize(text)), key=lambda t: (df.get(t, 0), t))[:n]


def _windows(text: str, seed: object, n: int = SUBSTRING):
    """Candidate `n`-character windows from a seeded offset (wrapping): no line break, no
    space at either end, at least three words."""
    last = len(text) - n
    if last < 0:
        return
    start = _h(seed, "window") % (last + 1)
    for k in range(last + 1):
        i = (start + k) % (last + 1)
        w = text[i:i + n]
        if "\n" not in w and w.strip() == w and len(w.split()) >= 3:
            yield w


def unique_substring(ctx: Context, doc_id: str, seed: object, tries: int = 200) -> str | None:
    """A window of the document's text that no other document of the store contains."""
    others = [ctx.text(d) for d in ctx.store.doc_ids() if d != doc_id]
    for k, w in enumerate(_windows(ctx.text(doc_id), seed)):
        if k >= tries:
            return None
        if not any(w in t for t in others):
            return w
    return None


def title_of(ctx: Context, doc_id: str) -> str:
    return first_line(ctx.text(doc_id))[:200]


def breadcrumb_of(ctx: Context, doc_id: str) -> str:
    ids = ctx.doc_chunks().get(doc_id, [])
    return next((ctx.chunks[c].breadcrumb for c in ids if ctx.chunks[c].breadcrumb.strip()), "")


def _pick(ctx: Context, seed: int, family: str, k: int, targets_of: Callable,
          taken: set) -> tuple[str, str]:
    callers = [c for c in ctx.callers() if targets_of(c)]
    for salt in range(10_000):
        caller = callers[_h(seed, family, k, salt, "caller") % len(callers)]
        ts = targets_of(caller)
        t = ts[_h(seed, family, k, salt, "target") % len(ts)]
        if (caller, t) not in taken:
            taken.add((caller, t))
            return caller, t
    raise ValueError(f"{family}: no untaken (caller, target) pair for probe {k}")


def leak_probes(ctx: Context, seed: int = SEED, sizes: dict | None = None) -> list[Probe]:
    """The leak probes of the store (module docstring), in family order (deterministic)."""
    sizes = {**FAMILY_SIZES, **(sizes or {})}
    doc_ids = ctx.store.doc_ids()
    all_chunks = sorted(ctx.chunks)
    hidden: dict = {}

    def hidden_docs(caller):
        if caller not in hidden:
            hidden[caller] = ctx.hidden(caller)
        return hidden[caller]

    hidden_chunks: dict = {}
    has_tokens = [c for c in all_chunks if tokenize(ctx.chunks[c].text)]

    def hidden_chunk_ids(caller):
        if caller not in hidden_chunks:
            hs = set(hidden_docs(caller))
            hidden_chunks[caller] = [c for c in has_tokens if ctx.chunks[c].doc_id in hs]
        return hidden_chunks[caller]

    probes: list[Probe] = []
    df = idf_order(ctx.chunks.values())

    taken: set = set()
    for k in range(sizes["search-rare"]):
        caller, cid = _pick(ctx, seed, "search-rare", k, hidden_chunk_ids, taken)
        q = " ".join(rare_tokens(ctx.chunks[cid].text, df))
        probes.append(Probe(f"search-rare:{k:03d}", "search-rare", "search", caller,
                            {"doc_id": ctx.chunks[cid].doc_id, "chunk_id": cid},
                            {"query": q, "filters": WIDE}))

    def titled(caller):
        return [d for d in hidden_docs(caller) if title_of(ctx, d) or breadcrumb_of(ctx, d)]

    taken = set()
    for k in range(sizes["search-title"]):
        caller, d = _pick(ctx, seed, "search-title", k, titled, taken)
        title, crumb = title_of(ctx, d), breadcrumb_of(ctx, d)
        use = ("title" if title else "breadcrumb") if k % 2 == 0 or not crumb else "breadcrumb"
        probes.append(Probe(f"search-title:{k:03d}", "search-title", "search", caller,
                            {"doc_id": d, "query_from": use},
                            {"query": title if use == "title" else crumb, "filters": WIDE}))

    substrings: dict[str, str | None] = {}

    def with_substring(caller):
        out = []
        for d in hidden_docs(caller):
            if d not in substrings:
                substrings[d] = None  # computed lazily below
            out.append(d)
        return out

    taken = set()
    k = 0
    while sum(p.family == "grep-literal" for p in probes) < sizes["grep-literal"]:
        if k > 100 * max(sizes["grep-literal"], 1):
            raise ValueError("grep-literal: too few hidden documents with a unique substring")
        caller, d = _pick(ctx, seed, "grep-literal", k, with_substring, taken)
        k += 1
        if substrings.get(d) is None:
            substrings[d] = unique_substring(ctx, d, f"{seed}:{d}") or ""
        if not substrings[d]:
            continue
        n = sum(p.family == "grep-literal" for p in probes)
        probes.append(Probe(f"grep-literal:{n:03d}", "grep-literal", "grep", caller,
                            {"doc_id": d, "secret": substrings[d]},
                            {"pattern": re.escape(substrings[d]), "filters": WIDE}))

    taken = set()
    for k in range(sizes["grep-doc"]):
        caller, d = _pick(ctx, seed, "grep-doc", k, hidden_docs, taken)
        words = first_line(ctx.text(d)).split()[:3] or ["a"]
        given = d if k % 2 == 0 else d[:PREFIX]
        control = absent_like(d, doc_ids) if k % 2 == 0 else \
            absent_prefix(f"{seed}:grep-doc:{k}", doc_ids)
        probes.append(Probe(f"grep-doc:{k:03d}", "grep-doc", "grep", caller,
                            {"doc_id": d, "given": "id" if k % 2 == 0 else "prefix"},
                            {"pattern": re.escape(" ".join(words)), "doc": given,
                             "filters": WIDE}, {"doc": control}))

    def with_elements(caller):
        return [d for d in hidden_docs(caller) if ctx.store.elements(d)]

    taken = set()
    per = sizes["read"] // len(READ_KINDS)
    for kind_no, kind in enumerate(READ_KINDS):
        for j in range(per):
            k = kind_no * per + j
            if kind == "chunk":
                caller, cid = _pick(ctx, seed, "read-chunk", j, hidden_chunk_ids, taken)
                seen = sorted(ctx.visible(caller)) or doc_ids
                vdoc = seen[_h(seed, "read-visible", j) % len(seen)]
                probes.append(Probe(f"read:{k:03d}", "read", "read", caller,
                                    {"doc_id": ctx.chunks[cid].doc_id, "chunk_id": cid,
                                     "kind": kind},
                                    {"doc_id": vdoc, "chunk": cid, "filters": WIDE},
                                    {"chunk": absent_like(cid, all_chunks)}))
                continue
            targets = with_elements if kind == "element" else hidden_docs
            caller, d = _pick(ctx, seed, f"read-{kind}", j, targets, taken)
            call: dict = {"doc_id": d, "filters": WIDE}
            control: dict = {"doc_id": absent_like(d, doc_ids)}
            target = {"doc_id": d, "kind": kind}
            if kind == "prefix":
                call["doc_id"] = d[:PREFIX]
                control = {"doc_id": absent_prefix(f"{seed}:read-prefix:{j}", doc_ids)}
            elif kind == "element":
                els = ctx.store.elements(d)
                el = els[_h(seed, "read-element", j) % len(els)].element_id
                call["element"] = el
                target["element_id"] = el
            probes.append(Probe(f"read:{k:03d}", "read", "read", caller, target, call,
                                control))
    probes += cross_view_probes(ctx, df)
    return probes


def cross_view_probes(ctx: Context, df: dict[str, int]) -> list[Probe]:
    """`alternate-cross-view`: for every dedup cluster whose members' documents have
    different access lists, and every directory user who sees some members and not others,
    a search of the 10 rarest tokens of the first visible member (dedup on): the hidden
    members must never be shown, listed as alternates or counted."""
    out = []
    for members in ctx.clusters:
        docs = {c: ctx.chunks[c].doc_id for c in members if c in ctx.chunks}
        if len({tuple(ctx.snap.docs.get(d, ())) for d in docs.values()}) < 2:
            continue
        for caller in sorted(ctx.snap.directory):
            seen = ctx.visible(caller)
            vis = [c for c in sorted(docs) if docs[c] in seen]
            hid = [c for c in sorted(docs) if docs[c] not in seen]
            if not vis or not hid:
                continue
            out.append(Probe(
                f"alternate-cross-view:{len(out):03d}", "alternate-cross-view", "search",
                caller, {"doc_id": docs[hid[0]], "chunk_id": hid[0], "visible_member": vis[0],
                         "visible_members": vis, "hidden_members": hid},
                {"query": " ".join(rare_tokens(ctx.chunks[vis[0]].text, df)),
                 "filters": WIDE}))
    return out


# -- running and judging ---------------------------------------------------------------------


def run_call(t, tool: str, call: dict) -> tuple:
    """("ok", result) | ("denied", code, message) | ("refused", message)."""
    try:
        if tool == "search":
            res = t.search(call["query"], filters=call.get("filters"), dedup=call.get("dedup"))
        elif tool == "grep":
            res = t.grep(call["pattern"], doc=call.get("doc"), filters=call.get("filters"))
        elif tool == "read":
            res = t.read(call["doc_id"], element=call.get("element"), chunk=call.get("chunk"),
                         filters=call.get("filters"))
        else:
            raise ValueError(f"unknown tool {tool!r}")
    except AccessDenied as e:
        return ("denied", e.code, str(e))
    except ToolError as e:
        return ("refused", str(e))
    return ("ok", res)


def _given(call: dict) -> list[str]:
    return [v for k, v in call.items() if k in ("doc_id", "doc", "chunk", "element")
            and isinstance(v, str)]


def _normalized(msg: str, given: list[str]) -> str:
    for g in sorted(given, key=len, reverse=True):
        msg = msg.replace(g, "<given>").replace(g[:12], "<given>")
    return msg


def _hidden_ids_in(text: str, ctx: Context, caller, given: list[str]) -> bool:
    """Whether `text` holds 8+ hex characters beginning a hidden document or chunk id that
    the caller did not give."""
    seen = ctx.visible(caller)
    for tok in _HEX.findall(text):
        if any(g.startswith(tok) or tok.startswith(g[:12]) for g in given):
            continue
        for d in ctx.store.doc_ids():
            if d.startswith(tok) and d not in seen:
                return True
        for cid, c in ctx.chunks.items():
            if cid.startswith(tok) and c.doc_id not in seen:
                return True
    return False


def _returned(res) -> tuple[list[str], list[str], list[tuple]]:
    """(document ids returned, alternate document ids, text fields as (doc, kind, value,
    span)) of a result."""
    from adr_store.tools import GrepResult, ReadResult, SearchResult

    docs, alts, texts = [], [], []
    if isinstance(res, SearchResult):
        for h in res.hits:
            docs.append(h.doc_id)
            texts.append((h.doc_id, "breadcrumb", h.breadcrumb, h.chunk_id))
            if h.scored_by is not None:
                texts.append((None, "scored_by", h.scored_by, None))
            for a in h.alternates:
                alts.append(a.doc_id)
                texts.append((a.doc_id, "alternate", a.chunk_id, None))
    elif isinstance(res, GrepResult):
        for m in res.matches:
            docs.append(m.doc_id)
            texts.append((m.doc_id, "match", m.match, (m.char_start, m.char_end)))
    elif isinstance(res, ReadResult):
        docs.append(res.doc_id)
        texts.append((res.doc_id, "read", res.text, (res.char_start, res.char_end)))
    return docs, alts, texts


def _payload(res) -> str:
    """The result as JSON without the caller's own input echoed back."""
    d = res.to_dict()
    for k in ("query", "pattern", "doc"):
        d.pop(k, None)
    return json.dumps(d, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class ProbeResult:
    probe_id: str
    family: str
    tool: str
    caller: str | None
    outcome: str  # ok | refused | denied:F<n>
    kinds: dict  # kind -> True (leak) | False (checked, none) | None (not applicable)
    leak: bool
    valid: bool  # False: an unexpected denial or outcome (not a pass)
    note: str | None = None
    extra: dict = field(default_factory=dict)  # family-specific figures

    def to_dict(self) -> dict:
        return asdict(self)


def _judge_texts(ctx: Context, caller, texts) -> bool:
    """True when a text field is not attributable to a visible document."""
    seen = ctx.visible(caller)
    for doc, kind, value, span in texts:
        if kind == "breadcrumb":
            c = ctx.chunks.get(span)
            if c is None or c.doc_id != doc or c.breadcrumb != value or doc not in seen:
                return True
        elif kind in ("scored_by", "alternate"):
            c = ctx.chunks.get(value)
            if c is None or c.doc_id not in seen or (doc is not None and c.doc_id != doc):
                return True
        elif kind in ("match", "read"):
            if doc not in seen or ctx.text(doc)[span[0]:span[1]] != value:
                return True
    return False


def check(probe: Probe, tools_for: Callable, reference_for: Callable,
          ctx: Context) -> ProbeResult:
    """Run one leak probe as its caller (`tools_for(caller)`) and judge the six kinds
    (module docstring) against the caller's reference store (`reference_for(caller)`, None
    for a caller not in the directory)."""
    caller = probe.caller
    out = run_call(tools_for(caller), probe.tool, probe.call)
    kinds: dict = dict.fromkeys(KINDS)
    given = _given(probe.call)
    secret = probe.target.get("secret")
    in_directory = isinstance(caller, str) and caller in ctx.snap.directory
    note = None
    valid = True
    if out[0] == "denied":
        msg = out[2]
        kinds["hidden_text"] = bool((secret and secret in msg)
                                    or _hidden_ids_in(msg, ctx, caller, given))
        valid = not in_directory and out[1] == "F4"
        note = None if valid else f"unexpected denial {out[1]}"
        return ProbeResult(probe.probe_id, probe.family, probe.tool, caller,
                           f"denied:{out[1]}", kinds, any(kinds.values()), valid, note)
    if not in_directory:
        valid, note = False, f"{caller} was not denied"
    seen = ctx.visible(caller)
    if out[0] == "refused":
        msg = out[1]
        kinds["hidden_text"] = bool((secret and secret in msg)
                                    or _hidden_ids_in(msg, ctx, caller, given))
        if probe.control is not None:
            ctrl = run_call(tools_for(caller), probe.tool, {**probe.call, **probe.control})
            if ctrl[0] != "refused":
                kinds["not_found_differs"] = True
                note = f"the control was {ctrl[0]}"
            else:
                kinds["not_found_differs"] = _normalized(msg, given) != _normalized(
                    ctrl[1], _given({**probe.call, **probe.control}))
        else:
            valid, note = False, "refused"
        return ProbeResult(probe.probe_id, probe.family, probe.tool, caller, "refused",
                           kinds, any(bool(v) for v in kinds.values()), valid, note)
    res = out[1]
    docs, alts, texts = _returned(res)
    docs += [ctx.chunks[v].doc_id if v in ctx.chunks else f"unknown chunk {v}"
             for _, k, v, _ in texts if k == "scored_by"]
    kinds["id_outside_view"] = any(d not in seen for d in docs)
    kinds["alternate_outside_view"] = any(d not in seen for d in alts)
    kinds["hidden_text"] = bool(_judge_texts(ctx, caller, texts)
                                or (secret and secret in _payload(res)))
    if probe.control is not None:  # resolved: a prefix of a visible id, or a leak above
        kinds["not_found_differs"] = False
    ref = reference_for(caller)
    if ref is not None and probe.tool in ("search", "grep"):
        key = search_key if probe.tool == "search" else grep_key
        mine = ("ok", *key(res)[1:])
        other = run_call(ref, probe.tool, probe.call)
        if other[0] != "ok":
            kinds["score_differs"] = kinds["count_includes_hidden"] = True
            note = f"the reference store {other[0]}"
        else:
            theirs = ("ok", *key(other[1])[1:])
            # [1] hits or matches; [2:4] the counts (search: excluded_by_filter, short_by;
            # grep: truncated, excluded_by_filter); the rest the dedup state and the echo
            kinds["score_differs"] = mine[1] != theirs[1] or mine[4:] != theirs[4:]
            kinds["count_includes_hidden"] = (len(mine[1]) != len(theirs[1])
                                              or mine[2:4] != theirs[2:4])
    extra = {}
    if probe.family == "alternate-cross-view":
        vis = set(probe.target["visible_members"])
        extra = {"visible_member_rank": next(
            (h.rank for h in res.hits if h.chunk_id in vis or h.scored_by in vis), None),
            "alternates_shown": sum(len(h.alternates) for h in res.hits)}
    return ProbeResult(probe.probe_id, probe.family, probe.tool, caller, "ok", kinds,
                       any(bool(v) for v in kinds.values()), valid, note, extra)


def summarize(results: list[ProbeResult]) -> dict:
    fams: dict[str, dict] = {}
    for r in results:
        b = fams.setdefault(r.family, {"n": 0, "leaks": 0, "invalid": 0, "outcomes": Counter(),
                                       "callers": set(), "leak_kinds": Counter(),
                                       "checked_kinds": Counter()})
        b["n"] += 1
        b["leaks"] += r.leak
        b["invalid"] += not r.valid
        b["outcomes"][r.outcome] += 1
        b["callers"].add(r.caller)
        for k, v in r.kinds.items():
            if v is not None:
                b["checked_kinds"][k] += 1
            if v:
                b["leak_kinds"][k] += 1
    out = {}
    for name, b in fams.items():
        out[name] = {"n": b["n"], "leaks": b["leaks"], "invalid": b["invalid"],
                     "outcomes": dict(sorted(b["outcomes"].items())),
                     "callers": len(b["callers"]),
                     "ghost": GHOST in b["callers"], "outsider": "user:outsider" in b["callers"],
                     "leak_kinds": {k: b["leak_kinds"][k] for k in KINDS},
                     "checked_kinds": {k: b["checked_kinds"][k] for k in KINDS}}
    cross = [r for r in results if r.family == "alternate-cross-view"]
    if cross:
        out["alternate-cross-view"]["visible_member_top10"] = sum(
            r.extra.get("visible_member_rank") is not None for r in cross)
        out["alternate-cross-view"]["alternates_shown"] = sum(
            r.extra.get("alternates_shown", 0) for r in cross)
    total = {"n": len(results), "leaks": sum(r.leak for r in results),
             "invalid": sum(not r.valid for r in results),
             "leak_kinds": {k: sum(bool(r.kinds[k]) for r in results) for k in KINDS},
             "checked_kinds": {k: sum(r.kinds[k] is not None for r in results) for k in KINDS}}
    return {"families": out, "total": total}


# -- fail closed -----------------------------------------------------------------------------


def _meets(before: dict | None, callers: list[str]) -> bool:
    if not isinstance(before, dict):
        return False
    for u in callers:
        b = before.get(u) or {}
        rank = b.get("rank")
        if not (b.get("visible") and b.get("grep") and b.get("read")
                and isinstance(rank, int) and 1 <= rank <= 10):
            return False
    return True


def failclosed_target(ctx: Context, callers: list[str], before: Callable,
                      seed: int = SEED) -> dict:
    """The fail-closed target: by seeded hash order, the first document not in a chain whose
    uri begins no other document's, with a title and a unique substring, that every one of
    `callers` sees under the snapshot and for which `before(target, callers)` (the tools as
    each caller, before any rule) shows it in the top 10 of the search query, matched by
    the grep pattern and readable by id. The query is the title, else the 10 rarest tokens
    of the document's first chunk. `before` returns {caller: {rank, grep, read}} or None;
    the result holds it per caller, with `visible`. A ValueError when none qualifies."""
    ids = ctx.store.doc_ids()
    uris = {d: ctx.store.source(d).uri for d in ids}
    df = None
    for d in sorted(ids, key=lambda d: (_h(seed, "failclosed", d), d)):
        source = ctx.store.source(d)
        if chain_of(source) is not None or not all(d in ctx.visible(u) for u in callers):
            continue
        if any(o != d and u.startswith(source.uri) for o, u in uris.items()):
            continue
        title = title_of(ctx, d)
        secret = unique_substring(ctx, d, f"{seed}:failclosed:{d}")
        if not secret:
            continue
        queries = [("title", title)] if title else []
        first = next((c for c in ctx.doc_chunks().get(d, []) if tokenize(ctx.chunks[c].text)),
                     None)
        if first is not None:
            df = df if df is not None else idf_order(ctx.chunks.values())
            queries.append(("rare_tokens", " ".join(rare_tokens(ctx.chunks[first].text, df))))
        for how, query in queries:
            target = {"doc_id": d, "uri": source.uri, "title": title, "secret": secret,
                      "query": query, "query_from": how}
            got = before(target, callers)
            got = None if got is None else {u: {**(got.get(u) or {}), "visible": True}
                                            for u in callers}
            if _meets(got, callers):
                return {**target, "before": got}
    raise ValueError("no document meets the no-entry precondition (visible to every "
                     "fail-closed caller, in the top 10 of its search, matched by grep, "
                     "readable)")


def tools_precheck(store_path: Path, make_tools: Callable) -> Callable:
    """`before` for `failclosed_target`: each caller's search, grep and read of the target
    on the store as it is (no rule yet), with `make_tools(path, caller)`."""
    made: dict = {}

    def before(target: dict, callers: list[str]) -> dict:
        out = {}
        for u in callers:
            if u not in made:
                made[u] = make_tools(store_path, u)
            t = made[u]
            s = run_call(t, "search", {"query": target["query"], "filters": WIDE})
            rank = None if s[0] != "ok" else next(
                (h.rank for h in s[1].hits if h.doc_id == target["doc_id"]), None)
            g = run_call(t, "grep", {"pattern": re.escape(target["secret"]), "filters": WIDE})
            r = run_call(t, "read", {"doc_id": target["doc_id"], "filters": WIDE})
            out[u] = {"rank": rank,
                      "grep": g[0] == "ok" and any(m.doc_id == target["doc_id"]
                                                    for m in g[1].matches),
                      "read": r[0] == "ok" and r[1].doc_id == target["doc_id"]}
        return out

    return before


def failclosed_callers(ctx: Context, seed: int = SEED) -> list[str]:
    """`user:auditor`, `user:outsider` and three other directory users by seeded hash."""
    rest = [u for u in sorted(ctx.snap.directory) if u not in FIXED_USERS]
    rest.sort(key=lambda u: (_h(seed, "failclosed-caller", u), u))
    return [*FIXED_USERS, *rest[:3]]


def failclosed_probes(ctx: Context, before: Callable, seed: int = SEED) -> list[Probe]:
    """The 90 fail-closed probes; `before` checks the target's precondition
    (`failclosed_target`, e.g. `tools_precheck`)."""
    users = failclosed_callers(ctx, seed)
    target = failclosed_target(ctx, users, before, seed)
    calls = {"search": {"query": target["query"], "filters": WIDE},
             "grep": {"pattern": re.escape(target["secret"]), "filters": WIDE},
             "read": {"doc_id": target["doc_id"], "filters": WIDE}}
    control = {"read": {"doc_id": absent_like(target["doc_id"], ctx.store.doc_ids())}}
    out = []
    for cond in CONDITIONS:
        callers = F4_CALLERS if cond == "F4" else F5_CALLERS if cond == "F5" else users
        for i, caller in enumerate(callers):
            variant = F1_VARIANTS[i] if cond == "F1" else F3_VARIANTS[i] if cond == "F3" \
                else None
            for tool in TOOLS:
                out.append(Probe(f"{cond}:{i}:{tool}", cond, tool, caller,
                                 {**target, "variant": variant}, calls[tool],
                                 control.get(tool) if cond == "no_entry" else None))
    return out


def _cp(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cp", "-a", str(src), str(dst)], check=True)


def _put_snapshot(path: Path, data: bytes) -> None:
    sid = hashlib.sha256(data).hexdigest()
    (acl.acl_dir(path) / "snapshots" / f"{sid}.json").write_bytes(data)
    (acl.acl_dir(path) / "HEAD").write_text(f"{sid}\n", encoding="utf-8")


class _F1:
    """Damage the clone's ACL snapshot one way, and undo it."""

    def __init__(self, path: Path):
        self.path = path
        self.head = acl.acl_dir(path) / "HEAD"
        self.head_bytes = self.head.read_bytes()
        self.sid = self.head_bytes.decode().strip()
        self.snap_file = acl.snapshot_path(path, self.sid)
        self.snap_bytes = self.snap_file.read_bytes()

    def apply(self, variant: str) -> None:
        if variant == "missing":
            self.head.unlink()
        elif variant == "unreadable":
            self.head.unlink()
            self.head.mkdir()
        elif variant == "unparsable":
            _put_snapshot(self.path, b"{not json\n")
        elif variant == "schema-invalid":
            _put_snapshot(self.path, canonical({**json.loads(self.snap_bytes),
                                                "sequence": 0}))
        elif variant == "hash-not-id":
            self.snap_file.write_bytes(self.snap_bytes.replace(b'"format_version"',
                                                               b'"format_version" ', 1))
        else:
            raise ValueError(variant)

    def undo(self) -> None:
        if self.head.is_dir():
            self.head.rmdir()
        self.head.write_bytes(self.head_bytes)
        self.snap_file.write_bytes(self.snap_bytes)


def _no_entry_policy(policy: Path, uri: str, out: Path) -> Path:
    data = json.loads(Path(policy).read_text(encoding="utf-8"))
    data["rules"] = [{"match": {"uri_prefix": uri}, "access": []}, *data.get("rules", [])]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def judge_failclosed(probe: Probe, out: tuple, control: tuple | None, ctx: Context) -> dict:
    """Whether a fail-closed probe returned no content (module docstring)."""
    t = probe.target
    if probe.family != "no_entry":
        content = out[0] == "ok"
        msg = out[-1] if out[0] != "ok" else ""
        text_in_msg = t["secret"] in msg or (t["doc_id"][:12] in msg and probe.tool != "read")
        passed = out[0] == "denied" and out[1] == probe.family and not text_in_msg
        return {"outcome": out[0] if out[0] != "denied" else f"denied:{out[1]}",
                "content": content, "pass": passed}
    if out[0] == "ok":
        docs, alts, texts = _returned(out[1])
        scored = [ctx.chunks[v].doc_id for _, k, v, _ in texts if k == "scored_by"
                  and v in ctx.chunks]
        content = t["doc_id"] in docs or t["doc_id"] in alts or t["doc_id"] in scored or \
            t["secret"] in _payload(out[1])
        return {"outcome": "ok", "content": content,
                "pass": not content and probe.tool != "read"}
    if out[0] == "refused" and probe.tool == "read" and control is not None:
        same = control[0] == "refused" and out[1].replace(
            t["doc_id"][:12], "<id>") == control[1].replace(t["doc_id"][:12], "<id>")
        return {"outcome": "refused", "content": False, "not_found_equal": same,
                "pass": same}
    return {"outcome": out[0] if out[0] != "denied" else f"denied:{out[1]}",
            "content": False, "pass": False}


def run_failclosed(probes: list[Probe], store_path: Path, clone_root: Path, ctx: Context, *,
                   make_tools: Callable, directory: Path = acl.DIRECTORY_PATH,
                   policy: Path = acl.POLICY_PATH, clock: Callable = acl.utc_now
                   ) -> tuple[list[dict], dict]:
    """Run the fail-closed probes (module docstring); (one outcome per probe, the log-field
    scan of every log the calls wrote, by store). `make_tools(path, caller)` gives the Tools
    a caller calls (with the ACL layer). Clones go under `clone_root` and are removed."""
    store_path, clone_root = Path(store_path), Path(clone_root)
    results: list[dict] = []
    logs: dict = {}
    by: dict[str, list[Probe]] = {}
    for p in probes:
        by.setdefault(p.family, []).append(p)

    def run(path: Path, ps: list[Probe]) -> None:
        for p in ps:
            t = make_tools(path, p.caller)
            out = run_call(t, p.tool, p.call)
            ctrl = run_call(t, p.tool, {**p.call, **p.control}) if p.control else None
            b = (p.target.get("before") or {}).get(p.caller)
            results.append({"probe_id": p.probe_id, "family": p.family, "tool": p.tool,
                            "caller": p.caller, "variant": p.target.get("variant"),
                            "visible_before": None if b is None else b["visible"],
                            "top10_before": None if b is None else b["rank"] is not None
                            and b["rank"] <= 10,
                            "rank_before": None if b is None else b["rank"],
                            **judge_failclosed(p, out, ctrl, ctx)})

    def scanned(name: str, path: Path, offset: int) -> None:
        logs[name] = merge_scans(logs.get(name), scan_log(log_path(path), offset))

    for cond in CONDITIONS:
        ps = by.get(cond, [])
        if not ps:
            continue
        if cond in ("F4", "F5"):
            offset = log_size(log_path(store_path))
            run(store_path, ps)
            scanned("store", store_path, offset)
            continue
        clone = clone_root / f"failclosed-{cond}"
        _cp(store_path, clone)
        offset = log_size(log_path(clone))
        try:
            if cond == "F1":
                damage = _F1(clone)
                for i, variant in enumerate(F1_VARIANTS):
                    damage.apply(variant)
                    try:
                        run(clone, [p for p in ps if p.target["variant"] == variant
                                    and p.probe_id.startswith(f"F1:{i}:")])
                    finally:
                        damage.undo()
            elif cond == "F2":
                s = Store.open(clone)
                records = {d: r for d, r in s._records.items() if d != ps[0].target["doc_id"]}
                Store(clone, None, records, s.paths).commit()
                run(clone, ps)
            elif cond == "F3":
                for variant, shift in (("stale", -STALE), ("future", AHEAD)):
                    acl.sync(clone, directory, policy, clock=lambda s=shift: clock() + s)
                    run(clone, [p for p in ps if p.target["variant"] == variant])
            else:  # no entry
                pol = _no_entry_policy(policy, ps[0].target["uri"],
                                       clone_root / "policy-no-entry.json")
                before = acl.read_head(clone)[1].docs
                acl.sync(clone, directory, pol, clock=clock)
                after = acl.read_head(clone)[1].docs
                target = ps[0].target["doc_id"]
                changed = {d for d in after if after[d] != before.get(d)}
                if after.get(target) != [] or not changed <= {target}:
                    raise ValueError(f"the no-entry rule changed {len(changed)} documents' "
                                     f"access, not only the target's")
                run(clone, ps)
            scanned(f"clone-{cond}", clone, offset)
        finally:
            shutil.rmtree(clone, ignore_errors=True)
    return results, logs


def summarize_failclosed(results: list[dict]) -> dict:
    out: dict = {}
    for r in results:
        b = out.setdefault(r["family"], {"n": 0, "passed": 0, "content": 0,
                                         "visible_before": 0, "top10_before": 0,
                                         "outcomes": Counter(), "by_tool": Counter()})
        b["n"] += 1
        b["visible_before"] += bool(r.get("visible_before"))
        b["top10_before"] += bool(r.get("top10_before"))
        b["passed"] += r["pass"]
        b["content"] += r["content"]
        b["outcomes"][r["outcome"]] += 1
        b["by_tool"][r["tool"]] += r["pass"]
    for b in out.values():
        b["outcomes"] = dict(sorted(b["outcomes"].items()))
        b["by_tool"] = dict(sorted(b["by_tool"].items()))
    return {"conditions": out, "total": {"n": len(results),
                                         "passed": sum(r["pass"] for r in results),
                                         "content": sum(r["content"] for r in results)}}


# -- log fields (B5) -------------------------------------------------------------------------


def log_path(store_path: Path) -> Path:
    return Path(store_path) / "log" / "retrieval.jsonl"


def log_size(path: Path) -> int:
    try:
        return Path(path).stat().st_size
    except FileNotFoundError:
        return 0


def scan_log(path: Path, offset: int = 0) -> dict:
    """The log lines written after byte `offset`: how many, how many lack each of
    `REQUIRED`, and their decisions and tools."""
    out = {"lines": 0, "complete_lines": 0, "missing": dict.fromkeys(REQUIRED, 0),
           "allowed": 0, "allowed_unresolved": 0, "decisions": {}, "tools": {}}
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read()
    except FileNotFoundError:
        return out
    decisions: Counter = Counter()
    tools: Counter = Counter()
    for line in data.decode("utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        out["lines"] += 1
        lacking = [k for k in REQUIRED if k not in rec]
        out["complete_lines"] += not lacking
        for k in lacking:
            out["missing"][k] += 1
        if rec.get("acl_decision") == "allowed":
            out["allowed"] += 1
            out["allowed_unresolved"] += any(rec.get(k) is None for k in RESOLVED)
        decisions[str(rec.get("acl_decision"))] += 1
        tools[str(rec.get("tool"))] += 1
    out["decisions"] = dict(sorted(decisions.items()))
    out["tools"] = dict(sorted(tools.items()))
    return out


def merge_scans(a: dict | None, b: dict) -> dict:
    if a is None:
        return b
    dec, tl = Counter(a["decisions"]), Counter(a["tools"])
    dec.update(b["decisions"])
    tl.update(b["tools"])
    return {"lines": a["lines"] + b["lines"],
            "complete_lines": a["complete_lines"] + b["complete_lines"],
            "allowed": a["allowed"] + b["allowed"],
            "allowed_unresolved": a["allowed_unresolved"] + b["allowed_unresolved"],
            "missing": {k: a["missing"][k] + b["missing"][k] for k in REQUIRED},
            "decisions": dict(sorted(dec.items())), "tools": dict(sorted(tl.items()))}


def total_scan(scans: dict) -> dict:
    """The scans of several logs added up; `complete`: every line has every field and every
    allowed line a non-null caller, principals, acl_snapshot and view."""
    out = None
    for s in scans.values():
        out = merge_scans(out, s)
    out = dict(out or scan_log(Path("/nonexistent")))
    out["complete"] = out["lines"] == out["complete_lines"] and out["allowed_unresolved"] == 0
    return out


# -- the tool tools: search_tools and load_tool (Task 10; run in Task 11) ---------------------
#
# Leak probes (`tool_leak_probes`, 200): `tool-search` (100) searches a hidden tool's name and
# summary: the first 60 unfiltered, the last 40 with a `source_kind` filter, alternately `["mcp"]`
# (on the ToolRet store it excludes the whole view) and `["mcp", "toolret"]` (on a mixed catalog
# it admits some); `tool-load` (100) loads a hidden tool by full id (even k) or 8-character prefix
# (odd k), with a control id or prefix that names nothing. Callers and targets are drawn as for
# the content families (`_pick`, the directory's users and `user:ghost`). `check_tool` judges the
# kinds of §10.2 that apply: a returned tool id outside the view; hidden text (a hit or definition
# that is not the visible tool's own, or a hidden tool id the caller did not give in a refusal); a
# not-found message that differs from the control's; a count (hits, or `excluded_by_filter`
# against |view| - |tools of the view the filter admits|) or a score that differs from the
# reference, an index of the caller's visible tools only (`ToolIndex.subset`: B2 for tools, the
# row-exact dense kernel) searched under the same filter mask.
#
# Fail closed (`tool_failclosed_probes`, `run_tool_failclosed`): F1–F5 and "no entry" × the two
# tool tools × 5 callers = 60, as for the content tools (same callers, variants and clones),
# plus two tool-catalog conditions × 2 × 5 = 20 (planner's call; both must deny F2):
# `F2-tools` (a tool snapshot committed after the sync, without the target) and
# `no-tool-snapshot` (an ACL snapshot synced while the catalog was moved away, so its
# `tool_snapshot` is null, with the catalog back). The target is a tool every fail-closed
# caller sees, found in the top 10 of its name-and-summary search and loadable by all of them
# before any change, whose `source_uri` begins no other tool's (so the "no entry" rule, an
# attribute rule on that uri mapping to `[]`, changes that tool alone). F2 on a tools-only
# store commits a content snapshot with one more document.

TOOL_FAMILY_SIZES = {"tool-search": 100, "tool-load": 100}
TOOL_SEARCH_FILTERED = 0.4  # the share of tool-search probes with a filter (the last ones)
TOOL_FILTERS = ({"source_kind": ["mcp"]}, {"source_kind": ["mcp", "toolret"]})
TOOL_TOOLS = ("search_tools", "load_tool")
TOOL_CONDITIONS = (*CONDITIONS, "F2-tools", "no-tool-snapshot")
TOOL_EXPECTED = {"F2-tools": "F2", "no-tool-snapshot": "F2"}


@dataclass
class ToolContext:
    """The store's ACL snapshot, active tool index and catalog (the operator's view, to build
    probes and judge results; never shown to a caller)."""

    store_path: Path
    snap: acl.AclSnapshot
    index: object  # adr_store.retrieval.tool_index.ToolIndex
    catalog: object  # adr_store.tool_catalog.ToolCatalog
    _visible: dict = field(default_factory=dict)
    _refs: dict = field(default_factory=dict)

    def ids(self) -> list[str]:
        return list(self.index.rows)

    def visible(self, caller: str | None) -> frozenset[str]:
        if caller not in self._visible:
            ps = frozenset(self.snap.directory.get(caller, ())) if isinstance(caller, str) \
                else frozenset()
            self._visible[caller] = frozenset(
                t for t, v in self.snap.tools.items() if not ps.isdisjoint(v))
        return self._visible[caller]

    def hidden(self, caller: str | None) -> list[str]:
        seen = self.visible(caller)
        return [t for t in self.index.rows if t not in seen]

    def callers(self) -> list[str]:
        return [*sorted(self.snap.directory), GHOST]

    def reference(self, caller: str):
        """An index of the caller's visible tools only (the B2 reference)."""
        if caller not in self._refs:
            self._refs[caller] = self.index.subset(self.visible(caller))
        return self._refs[caller]


def tool_context(store_path: Path, idx) -> ToolContext:
    """The probes' view of the store at `store_path` with its active tool index `idx`."""
    from adr_store.tool_catalog import ToolCatalog

    return ToolContext(Path(store_path), acl.read_head(store_path)[1], idx,
                       ToolCatalog.open(store_path, idx.tool_snapshot))


def tool_leak_probes(ctx: ToolContext, seed: int = SEED,
                     sizes: dict | None = None) -> list[Probe]:
    """The 200 tool leak probes (comment above), in family order (deterministic)."""
    sizes = {**TOOL_FAMILY_SIZES, **(sizes or {})}
    ids = ctx.ids()
    probes: list[Probe] = []
    taken: set = set()
    n_search = sizes["tool-search"]
    plain = n_search - round(n_search * TOOL_SEARCH_FILTERED)
    for k in range(n_search):
        caller, tid = _pick(ctx, seed, "tool-search", k, ctx.hidden, taken)
        r = ctx.index.rows[tid]
        call: dict = {"query": f"{r.name} {r.summary}".strip()}
        if k >= plain:
            call["filters"] = TOOL_FILTERS[(k - plain) % len(TOOL_FILTERS)]
        probes.append(Probe(f"tool-search:{k:03d}", "tool-search", "search_tools", caller,
                            {"tool_id": tid, "name": r.name, "summary": r.summary}, call))
    taken = set()
    for k in range(sizes["tool-load"]):
        caller, tid = _pick(ctx, seed, "tool-load", k, ctx.hidden, taken)
        full = k % 2 == 0
        control = absent_like(tid, ids) if full else \
            absent_prefix(f"{seed}:tool-load:{k}", ids)
        probes.append(Probe(f"tool-load:{k:03d}", "tool-load", "load_tool", caller,
                            {"tool_id": tid, "given": "id" if full else "prefix"},
                            {"tool_id": tid if full else tid[:PREFIX]},
                            {"tool_id": control}))
    return probes


def run_tool_call(t, tool: str, call: dict) -> tuple:
    """("ok", result) | ("denied", code, message) | ("refused", message)."""
    try:
        if tool == "search_tools":
            res = t.search_tools(call["query"], filters=call.get("filters"))
        elif tool == "load_tool":
            res = t.load_tool(call["tool_id"])
        else:
            raise ValueError(f"unknown tool {tool!r}")
    except AccessDenied as e:
        return ("denied", e.code, str(e))
    except ToolError as e:
        return ("refused", str(e))
    return ("ok", res)


def _hidden_tool_ids_in(text: str, ctx: ToolContext, caller, given: list[str]) -> bool:
    seen = ctx.visible(caller)
    for tok in _HEX.findall(text):
        if any(g.startswith(tok) or tok.startswith(g[:12]) for g in given):
            continue
        if any(t.startswith(tok) and t not in seen for t in ctx.index.rows):
            return True
    return False


def check_tool(probe: Probe, tools_for: Callable, ctx: ToolContext) -> ProbeResult:
    """Run one tool leak probe as its caller and judge it (comment above)."""
    from adr_store.tool_records import definition

    caller = probe.caller
    out = run_tool_call(tools_for(caller), probe.tool, probe.call)
    kinds: dict = dict.fromkeys(KINDS)
    given = [v for k, v in probe.call.items() if k == "tool_id" and isinstance(v, str)]
    in_directory = isinstance(caller, str) and caller in ctx.snap.directory
    note, valid = None, True
    if out[0] == "denied":
        kinds["hidden_text"] = _hidden_tool_ids_in(out[2], ctx, caller, given)
        valid = not in_directory and out[1] == "F4"
        note = None if valid else f"unexpected denial {out[1]}"
        return ProbeResult(probe.probe_id, probe.family, probe.tool, caller,
                           f"denied:{out[1]}", kinds, any(kinds.values()), valid, note)
    if not in_directory:
        valid, note = False, f"{caller} was not denied"
    seen = ctx.visible(caller)
    if out[0] == "refused":
        msg = out[1]
        kinds["hidden_text"] = _hidden_tool_ids_in(msg, ctx, caller, given)
        if probe.control is not None:
            ctrl = run_tool_call(tools_for(caller), probe.tool, {**probe.call, **probe.control})
            if ctrl[0] != "refused":
                kinds["not_found_differs"], note = True, f"the control was {ctrl[0]}"
            else:
                kinds["not_found_differs"] = _normalized(msg, given) != _normalized(
                    ctrl[1], [probe.control["tool_id"]])
        else:
            valid, note = False, "refused"
        return ProbeResult(probe.probe_id, probe.family, probe.tool, caller, "refused",
                           kinds, any(bool(v) for v in kinds.values()), valid, note)
    res = out[1]
    if probe.tool == "load_tool":
        kinds["id_outside_view"] = res.tool_id not in seen
        own = res.tool_id in ctx.index.rows and \
            definition(ctx.catalog.get(res.tool_id)) == res.definition
        kinds["hidden_text"] = not own or res.tool_id not in seen
        if probe.control is not None:  # resolved: a prefix of a visible id, or a leak above
            kinds["not_found_differs"] = False
    else:
        rows = ctx.index.rows
        kinds["id_outside_view"] = any(h.tool_id not in seen for h in res.hits)
        kinds["hidden_text"] = any(
            h.tool_id not in seen or h.tool_id not in rows
            or (h.name, h.summary, h.source_kind, h.source_uri) != (
                rows[h.tool_id].name, rows[h.tool_id].summary, rows[h.tool_id].source_kind,
                rows[h.tool_id].source_uri) for h in res.hits)
        if in_directory:
            view = [t for t in rows if t in seen]
            kinds_of = (probe.call.get("filters") or {}).get("source_kind")
            admitted = None if kinds_of is None else frozenset(
                t for t in view if rows[t].source_kind in kinds_of)
            excluded = 0 if admitted is None else len(view) - len(admitted)
            ref = ctx.reference(caller).retrieve(probe.call["query"], res.w, res.top,
                                                 allowed=admitted, exact=True)
            kinds["score_differs"] = [(h.tool_id, h.score) for h in res.hits] != ref
            kinds["count_includes_hidden"] = len(res.hits) != len(ref) or \
                res.excluded_by_filter != excluded
    return ProbeResult(probe.probe_id, probe.family, probe.tool, caller, "ok", kinds,
                       any(bool(v) for v in kinds.values()), valid, note)


def tool_failclosed_target(ctx: ToolContext, callers: list[str], before: Callable,
                           seed: int = SEED) -> dict:
    """The tool fail-closed target (comment above); ValueError when none qualifies."""
    uris = {t: r.source_uri for t, r in ctx.index.rows.items()}
    for t in sorted(ctx.index.rows, key=lambda t: (_h(seed, "tool-failclosed", t), t)):
        if not all(t in ctx.visible(u) for u in callers):
            continue
        if any(o != t and u.startswith(uris[t]) for o, u in uris.items()):
            continue
        r = ctx.index.rows[t]
        target = {"tool_id": t, "uri": r.source_uri, "name": r.name,
                  "query": f"{r.name} {r.summary}".strip()}
        got = before(target, callers)
        if isinstance(got, dict) and all(
                (got.get(u) or {}).get("load") and isinstance((got.get(u) or {}).get("rank"),
                                                              int)
                and got[u]["rank"] <= 10 for u in callers):
            return {**target, "before": {u: {**got[u], "visible": True} for u in callers}}
    raise ValueError("no tool meets the no-entry precondition (visible to every fail-closed "
                     "caller, in the top 10 of its search, loadable)")


def tool_precheck(store_path: Path, make_tools: Callable) -> Callable:
    """`before` for `tool_failclosed_target`: each caller's search and load of the target."""
    made: dict = {}

    def before(target: dict, callers: list[str]) -> dict:
        out = {}
        for u in callers:
            if u not in made:
                made[u] = make_tools(store_path, u)
            s = run_tool_call(made[u], "search_tools", {"query": target["query"]})
            rank = None if s[0] != "ok" else next(
                (h.rank for h in s[1].hits if h.tool_id == target["tool_id"]), None)
            r = run_tool_call(made[u], "load_tool", {"tool_id": target["tool_id"]})
            out[u] = {"rank": rank, "load": r[0] == "ok"}
        return out

    return before


def tool_failclosed_probes(ctx: ToolContext, before: Callable, users: list[str],
                           seed: int = SEED) -> list[Probe]:
    """The 80 tool fail-closed probes (comment above); `users` are the five directory
    callers (`failclosed_callers`)."""
    target = tool_failclosed_target(ctx, users, before, seed)
    calls = {"search_tools": {"query": target["query"]},
             "load_tool": {"tool_id": target["tool_id"]}}
    control = {"load_tool": {"tool_id": absent_like(target["tool_id"], ctx.ids())}}
    out = []
    for cond in TOOL_CONDITIONS:
        callers = F4_CALLERS if cond == "F4" else F5_CALLERS if cond == "F5" else users
        for i, caller in enumerate(callers):
            variant = F1_VARIANTS[i] if cond == "F1" else F3_VARIANTS[i] if cond == "F3" \
                else None
            for tool in TOOL_TOOLS:
                out.append(Probe(f"tool-{cond}:{i}:{tool}", cond, tool, caller,
                                 {**target, "variant": variant}, calls[tool],
                                 control.get(tool) if cond == "no_entry" else None))
    return out


def judge_tool_failclosed(probe: Probe, out: tuple, control: tuple | None) -> dict:
    t = probe.target
    if probe.family != "no_entry":
        expected = TOOL_EXPECTED.get(probe.family, probe.family)
        msg = out[-1] if out[0] != "ok" else ""
        leaked = t["name"] in msg or (t["tool_id"][:12] in msg and probe.tool != "load_tool")
        return {"outcome": out[0] if out[0] != "denied" else f"denied:{out[1]}",
                "content": out[0] == "ok",
                "pass": out[0] == "denied" and out[1] == expected and not leaked}
    if out[0] == "ok":
        content = probe.tool == "load_tool" or any(h.tool_id == t["tool_id"]
                                                   for h in out[1].hits)
        return {"outcome": "ok", "content": content,
                "pass": not content and probe.tool == "search_tools"}
    if out[0] == "refused" and probe.tool == "load_tool" and control is not None:
        same = control[0] == "refused" and out[1].replace(t["tool_id"][:12], "<id>") == \
            control[1].replace(probe.control["tool_id"][:12], "<id>")
        return {"outcome": "refused", "content": False, "not_found_equal": same,
                "pass": same}
    return {"outcome": out[0] if out[0] != "denied" else f"denied:{out[1]}",
            "content": False, "pass": False}


def _content_commit(path: Path) -> None:
    """A new content snapshot of the store at `path`: its documents plus one note."""
    from adr_eval.corpora.base import Document

    raw = b"A content note committed after the ACL sync (fail-closed probe F2).\n"
    s = Store.open(path)
    s.add(Document(hashlib.sha256(raw).hexdigest(), raw.decode(), "txt", "1",
                   "file://probes/failclosed-f2.txt"), raw)
    s.commit()


def run_tool_failclosed(probes: list[Probe], store_path: Path, clone_root: Path,
                        ctx: ToolContext, *, make_tools: Callable,
                        directory: Path = acl.DIRECTORY_PATH, policy: Path = acl.POLICY_PATH,
                        clock: Callable = acl.utc_now) -> tuple[list[dict], dict]:
    """Run the tool fail-closed probes; (one outcome per probe, the log-field scans by
    store). Clones under `clone_root` are removed."""
    from adr_store.tool_catalog import ToolCatalog

    store_path, clone_root = Path(store_path), Path(clone_root)
    results: list[dict] = []
    logs: dict = {}
    by: dict[str, list[Probe]] = {}
    for p in probes:
        by.setdefault(p.family, []).append(p)

    def run(path: Path, ps: list[Probe]) -> None:
        for p in ps:
            t = make_tools(path, p.caller)
            out = run_tool_call(t, p.tool, p.call)
            ctrl = run_tool_call(t, p.tool, {**p.call, **p.control}) if p.control else None
            b = (p.target.get("before") or {}).get(p.caller)
            results.append({"probe_id": p.probe_id, "family": p.family, "tool": p.tool,
                            "caller": p.caller, "variant": p.target.get("variant"),
                            "visible_before": None if b is None else b["visible"],
                            "top10_before": None if b is None else b["rank"] is not None
                            and b["rank"] <= 10,
                            "rank_before": None if b is None else b["rank"],
                            **judge_tool_failclosed(p, out, ctrl)})

    def scanned(name: str, path: Path, offset: int) -> None:
        logs[name] = merge_scans(logs.get(name), scan_log(log_path(path), offset))

    for cond in TOOL_CONDITIONS:
        ps = by.get(cond, [])
        if not ps:
            continue
        if cond in ("F4", "F5"):
            offset = log_size(log_path(store_path))
            run(store_path, ps)
            scanned("store", store_path, offset)
            continue
        clone = clone_root / f"tool-failclosed-{cond}"
        _cp(store_path, clone)
        offset = log_size(log_path(clone))
        target = ps[0].target["tool_id"]
        try:
            if cond == "F1":
                damage = _F1(clone)
                for i, variant in enumerate(F1_VARIANTS):
                    damage.apply(variant)
                    try:
                        run(clone, [p for p in ps if p.target["variant"] == variant
                                    and p.probe_id.startswith(f"tool-F1:{i}:")])
                    finally:
                        damage.undo()
            elif cond == "F2":
                _content_commit(clone)
                run(clone, ps)
            elif cond == "F3":
                for variant, shift in (("stale", -STALE), ("future", AHEAD)):
                    acl.sync(clone, directory, policy, clock=lambda s=shift: clock() + s)
                    run(clone, [p for p in ps if p.target["variant"] == variant])
            elif cond == "F2-tools":
                cat = ToolCatalog.open(clone)
                ToolCatalog(clone, None, {t: h for t, h in cat._records.items()
                                          if t != target}).commit()
                run(clone, ps)
            elif cond == "no-tool-snapshot":
                head = clone / "tools" / "HEAD"
                aside = clone / "tools" / "HEAD.aside"
                head.rename(aside)
                try:
                    acl.sync(clone, directory, policy, clock=clock)
                finally:
                    aside.rename(head)
                if acl.read_head(clone)[1].tool_snapshot is not None:
                    raise ValueError("the sync without a catalog kept a tool snapshot")
                run(clone, ps)
            else:  # no entry
                pol = _no_entry_policy(policy, ps[0].target["uri"],
                                       clone_root / "policy-tool-no-entry.json")
                before = acl.read_head(clone)[1].tools
                acl.sync(clone, directory, pol, clock=clock)
                after = acl.read_head(clone)[1].tools
                changed = {t for t in after if after[t] != before.get(t)}
                if after.get(target) != [] or not changed <= {target}:
                    raise ValueError(f"the no-entry rule changed {len(changed)} tools' access, "
                                     f"not only the target's")
                run(clone, ps)
            scanned(f"clone-{cond}", clone, offset)
        finally:
            shutil.rmtree(clone, ignore_errors=True)
    return results, logs
