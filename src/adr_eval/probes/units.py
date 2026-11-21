r"""Unit probes (Phase 4 spec §15.4; criteria S1, S2, U1, U2, U3, the applicability probes and
the MCP leg of D1) for the unit tools of `adr_store.tools.Tools` (`define`, `rule_lookup`,
`procedure_lookup`, `unit_search`; `check_rules` joins in Task 18); deterministic (seed `SEED4`),
no model calls, run through `Tools` with the ACL layer, as the Phase 3 table probes of
`adr_eval.probes.tables` are. The tools probed are those of `UNIT_TOOLS` that `Tools` has
(`present_tools`): the four read tools until Task 18 (preflight ruling C10).

**Reference stores** (`UnitReferences`, `unit_reference`). A view's reference store holds the
view's documents alone (`tables.bare_reference`: re-ingested from the store's blobs and texts,
the ACL synced from the same directory and policy), its applicability overlay derived under the
gov config (each document's envelope must equal the store's), its Phase 3 tables when the
store's units read some (built and promoted; the extraction tables from the cached first-pass
replies of the generator profile with a budget of zero calls, so a reply not cached stops the
build, BudgetExceeded, and extraction tables recorded as coming from anything else than the
store's are refused), and its units built by code (`build_units`, no model pass, so no client
and no call) and promoted as its first `units/HEAD`. The units build config of the reference
(format, corpus, model passes, unit contracts, whether tables and an applicability overlay were
read, the tables' extraction) must equal the store's, or the reference is refused
(ValueError): a store whose units were filled by a model pass cannot be reproduced from code.
`units-view.json`, written last, records what the reference holds; a reference whose record
matches is reused (its ACL kept fresh), anything else at its path is refused. References live
under a root at `<view[:12]>`; `info` records each one's units id and how many of its units
equal the store's units of the view's documents (`units_equal` of `units_of_view`), apart from
the Phase 3 tables id a table record names (`comparable`): it is the id of each store's own
tables build, as the snapshot id is of its own documents.

**Leak probes** (`leak_probes`, §15.4, S1). Each probe is a (caller, hidden unit) pair drawn by
seeded hash: for probe `k` of a family, a directory user with a hidden unit the family can
target, then a unit type of the family (cycled with `k`), then a unit of that type of a
document the caller cannot see; a (caller, unit) already taken draws again. Every call reads as
widely as the tool allows (`include_superseded` on `define` and `rule_lookup`). Families:

- `by-id`: a hidden rule card by its provision and by its section (`rule_lookup(rule_id=…)`),
  or a hidden procedure by unit id (each view in turn) and by canonical ref;
- `by-term`: `define` of a label, alternate label or hidden label of a hidden concept that no
  concept the caller sees holds, without and with the concept's scope as context;
- `by-query`: `unit_search` (all types and the unit's type) of the hidden unit's words, and
  `rule_lookup(query)`, `procedure_lookup(task)` or `define` for its type;
- `by-closure`: the units a closure or a context resolution would reach: on a corpus with rule
  cards, even `k` a hidden card's closure target by its ref and the card's words, both with
  closure expansion; otherwise (and odd `k`) `define` of a term the caller sees with the
  hidden unit as context, by unit id and by canonical ref;
- `by-error`: three refusals that name the hidden unit: its ref with an absent paragraph,
  `procedure_lookup` of its unit id (or one character more for a procedure), and a task
  together with its id.

**Leak kinds** (`check_leak`), each True (a leak), False (checked, none) or None (does not
apply), judged against the same calls as the same caller on the caller's reference store:
`id_outside_view` (a document id, or 12 or more hex characters beginning one, of a document the
caller cannot see, the caller's own arguments left out; unit ids carry 16), `hidden_value` (the
probe's secret, the hidden unit's reader text, where the reference shows none), `count_differs`
(senses, nearest labels, cards, closure entries, catalog entries, hits, `excluded_by_filter`,
`truncated`), `rows_differ` (the results without store-specific fields: snapshot, units id,
handle, and the tables id of a `unit_search` hit's table-record pointer) and
`error_differs`. A directory user denied any call makes the probe invalid.

**Equivalence** (`equivalence`, S1): for each view, `n_calls` (25) calls as the view's caller on
the store and on its reference store; call `i` uses the tool of slot `i` (the four in turn,
then a last `unit_search`: 6 `define`, 6 `rule_lookup`, 6 `procedure_lookup`, 7 `unit_search`
in 25) on a unit drawn by seeded hash from the
view's units (two calls in three) or from all units (the third), with its arguments (term,
context, rule id, section, query, part, view, types) and applicability (default,
`include_superseded`, an `as_of` date of a version boundary) by seeded hash. Results must be
identical, or the same refusal.

**Fail closed** (`failclosed`, S2): F1–F5 and "no entry" × the tools × 5 callers (120 with the
four read tools, 150 once `check_rules` exists), with the callers, variants and clone machinery
of the Phase 2 probes (`acl.failclosed_callers`, `_F1`, `_cp`; clones removed). Each tool has a
target unit, by seeded hash among the units the most fail-closed callers see: a concept whose
label only its document (chain) holds (`define`), a rule card whose provision only its chain
holds (`rule_lookup` by id), a procedure (`procedure_lookup` by unit id), a unit its own words
find (`unit_search`); before any change each caller that sees the target gets it, and no other
does. The target documents are the targets' documents with every version of their chains.
Pass: F1–F5 refuse with that code and show nothing of the targets; "no entry" (an attribute
rule mapping each target document's uri to `[]`, which must change those documents' access
alone) shows nothing of the targets and, for a lookup by id, gives the same refusal as an id
that names nothing.

**Applicability** (`applicability_probes`): as `user:auditor`, the default filters and `n` (50)
`as_of` dates (each eCFR version's first day in force and the day before it, then dates drawn
by seeded hash around them); per date each read tool: `rule_lookup` by a provision that
several versions hold (`id`) and by its words (`query`), `define` of a term several versions
define, `unit_search` of rule cards and concepts and `procedure_lookup` of a task. Every unit
returned (closure entries included) must be of a document the filters admit, at most one
version of a chain may be returned (the version in force), and the lookups by id and term must
return exactly the units the filters admit.

**`define`** (`define_probes`, U1): every distinct label, alternate label and hidden label of
every concept, each as a caller drawn by seeded hash (the auditor included) with the default
filters or `include_superseded`; `n_absent` (50) terms no concept holds; every term defined in
more than one scope, with each of its scopes as context and once without, each as a caller
who sees a sense of that scope (drawn by seeded hash); and for each such scope, a unit id as
context (`unit_context`): the sense's own concept and another unit of its document (a rule
card, procedure, FAQ or table record, by seeded hash), as a caller who sees that unit. A
unit-id context is judged by an independent reading of §7 (`place_of`, `holds`, `BREADTH`):
where the unit sits is read from its own fields (a concept's scope, a card's provision, a
table's section, its subpart, its document) and containment from the sense's scope kind and
ref, sharing no code with the tool's context resolution or ranking. The expected senses
are worked out from the units and the ACL snapshot (labels first, hidden labels only when no
label matches; ranked by scope holding the context, then narrowest scope, then unit id; the
nearest labels by edit distance when none): `correct` when the senses (and nearest labels) are
exactly those; `hidden_senses` counts senses of documents the caller cannot see (must be 0).

**Censuses**: `closure_census` (U2) recomputes `units.closure.closure_census` over the stored
rule cards and the re-read provisions of every eCFR version, and over the newest versions
alone, with every unresolved in-part reference listed with its reason; `procedure_census` (U3)
checks every procedure: a valid IR, Mermaid re-parsed to the IR's graph, SKILL.md re-parsed to
its front matter and step count, a description of at most 1,024 characters, a body under 500
lines, labels of at most 80 characters, byte-stable renderings and unique names.

**Log scan** (`scan_unit_log`, S2): every line has `REQUIRED`; every unit-tool line has the key
`units`; an allowed line has a non-null `RESOLVED` and, for a unit tool that answered (or
refused an id after reading the units), a non-null `units`; a `sql` line logs only the
statement's hash and no line holds the text of a statement given (16 characters or more), as
Phase 3's scan. Given the unit tool calls made through `run_unit_call` on a store since the
offset (`unit_calls`), the scan also requires one unit-tool line per call; a log that does not
exist is not complete.

**MCP** (`select_mcp`, `run_mcp`, D1): the `n` (60) leak probes with the lowest SHA-256 of
`"<seed>:<label>/<probe_id>"`, each run through an `adr mcp` server of its caller and judged
as above against the Python API's reference store; every result is replayed with its handle
through the same server (identical, and its handle names the units).

Run summaries carry counts only; per-item rows go to `results.json` under `runs/`. This module
may import `adr_store` directly (plan, shared rules).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from adr_eval.probes import acl as acl_probes
from adr_eval.probes import equivalence as eq
from adr_eval.probes import mcp as mcp_probes
from adr_eval.probes import tables as tp
from adr_eval.probes.acl import (
    _F1,
    AHEAD,
    CONDITIONS,
    F1_VARIANTS,
    F3_VARIANTS,
    F4_CALLERS,
    F5_CALLERS,
    REQUIRED,
    RESOLVED,
    STALE,
    Probe,
    ProbeResult,
    _cp,
    log_path,
    log_size,
)
from adr_store import acl, handles
from adr_store import applicability as ap
from adr_store.store import Store
from adr_store.tables.build import build_tables
from adr_store.tables.gate import gate as tables_gate
from adr_store.tables.overlay import load_manifest as load_tables_manifest
from adr_store.tables.parse import base_key
from adr_store.tools import (
    UNKNOWN_PROCEDURE,
    UNKNOWN_RULE,
    AccessDenied,
    ToolError,
    Tools,
)
from adr_store.units import closure as closure_mod
from adr_store.units import tools_units as tu
from adr_store.units.build import build_units, unit_reports
from adr_store.units.concepts import _KIND_RANK, scope_contains
from adr_store.units.ecfr import ecfr_docs, normalise_rule_id, rule_cards
from adr_store.units.envelope import Unit
from adr_store.units.gate import units_gate
from adr_store.units.overlay import UnitsManifest, load_units, load_units_manifest
from adr_store.units.procedures import WHEN_TO_USE_MAX, ProcedureBody, validate_ir
from adr_store.units.render import (
    LABEL_MAX,
    NAME_MAX,
    SKILL_BODY_MAX_LINES,
    ir_graph,
    parse_mermaid,
    parse_skill,
    render_mermaid,
    render_skill,
)

SEED4 = 20261121
UNIT_TOOLS = ("define", "rule_lookup", "procedure_lookup", "unit_search", "check_rules")
READ_TOOLS = UNIT_TOOLS[:4]
LEAK_SIZES = {"gov": {"by-id": 100, "by-term": 60, "by-query": 60, "by-closure": 40,
                      "by-error": 40},
              "bench": {"by-id": 20, "by-term": 20, "by-query": 20, "by-closure": 20,
                        "by-error": 20}}
LEAK_KINDS = tp.LEAK_KINDS
FAMILY_TYPES = {"by-id": ("rule_card", "procedure"), "by-term": ("concept",),
                "by-query": ("rule_card", "procedure", "concept", "faq", "table_record"),
                "by-closure": ("rule_card", "procedure", "concept", "faq", "table_record"),
                "by-error": ("rule_card", "procedure", "concept")}
VIEWS = ("catalog", "skill", "mermaid", "ir")
WIDE = {"include_superseded": True}
STORE_SPECIFIC = ("snapshot", "units", "handle")
ECHO = ("term", "context", "query", "rule_id", "task", "id", "view", "types")
UNITS_VIEW_FILE = "units-view.json"
SECRET_CHARS = 200
QUERY_WORDS = 8
FRESH_EVERY = 200        # calls between ACL freshness checks in the long probe sets
U2_THRESHOLD = 0.99
_HEX = re.compile(r"[0-9a-f]{12,}")
_WORD = re.compile(r"[A-Za-z0-9]{3,}")
_NODE_LABEL = re.compile(r'^\s+s\d+(?:\["([^"]*)"\]|\{"([^"]*)"\})')


def _h(*parts: object) -> int:
    return int(hashlib.sha256(":".join(str(p) for p in parts).encode("utf-8")).hexdigest(), 16)


def _json(data: object) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)


def present_tools() -> tuple[str, ...]:
    """The names of `UNIT_TOOLS` that `Tools` has (C10: four until Task 18 adds
    `check_rules`)."""
    return tuple(t for t in UNIT_TOOLS if callable(getattr(Tools, t, None)))


# -- the store as the probes see it ------------------------------------------------------------


@dataclass
class UnitContext:
    """The store, its ACL snapshot, its current units and its applicability overlay (the
    operator's view, used to build probes and judge results; never shown to a caller)."""

    store_path: Path
    store: Store
    snap: acl.AclSnapshot
    units_id: str
    manifest: UnitsManifest
    units: dict[str, Unit]              # by unit id
    by_type: dict[str, list[Unit]]      # each sorted by unit id
    overlay: ap.Applicability | None
    _visible: dict = field(default_factory=dict)
    _hidden: dict = field(default_factory=dict)
    _keys: dict = field(default_factory=dict)
    _chains: dict = field(default_factory=dict)

    @property
    def corpus(self) -> str:
        return self.manifest.corpus

    def visible(self, caller: str | None) -> frozenset[str]:
        if caller not in self._visible:
            ps = frozenset(self.snap.directory.get(caller, ())) if isinstance(caller, str) \
                else frozenset()
            self._visible[caller] = frozenset(
                d for d, v in self.snap.docs.items() if not ps.isdisjoint(v))
        return self._visible[caller]

    def callers(self) -> list[str]:
        return sorted(self.snap.directory)

    def hidden(self, caller: str, type_: str) -> list[Unit]:
        """The units of `type_` of documents `caller` cannot see, by unit id."""
        key = (caller, type_)
        if key not in self._hidden:
            seen = self.visible(caller)
            self._hidden[key] = [u for u in self.by_type.get(type_, ()) if u.doc_id not in seen]
        return self._hidden[key]

    def label_keys(self, caller: str) -> frozenset[str]:
        """The base keys of every label and hidden label of the concepts `caller` sees."""
        if caller not in self._keys:
            seen = self.visible(caller)
            self._keys[caller] = frozenset(k for u in self.by_type.get("concept", ())
                                           if u.doc_id in seen for k in _term_keys(u))
        return self._keys[caller]

    def chain(self, doc_id: str) -> str | None:
        if not self._chains:
            for d in self.store.doc_ids():
                rec = None if self.overlay is None else self.overlay.records.get(d)
                self._chains[d] = rec.chain_id if rec is not None and rec.chain_id else \
                    ap.chain_of(self.store.source(d))
        return self._chains[doc_id]

    def chain_docs(self, doc_id: str) -> frozenset[str]:
        """The document's chain: every document of its chain id (itself when it has none)."""
        c = self.chain(doc_id)
        if c is None:
            return frozenset({doc_id})
        return frozenset(d for d, x in self._chains.items() if x == c)

    def admitted(self, docs: Iterable[str], filters: dict) -> frozenset[str]:
        """The documents of `docs` that the applicability filters admit (all of them without
        an overlay and filters that need none)."""
        f = ap.Filters.parse(filters)
        if self.overlay is None:
            return frozenset(docs)
        return self.overlay.allowed_docs(docs, f)[0]


def _labels(u: Unit) -> list[str]:
    return [u.body["pref_label"], *u.body["alt_labels"]]


def _term_keys(u: Unit) -> set[str]:
    return {base_key(x) for x in _labels(u)} | set(u.body["hidden_labels"])


def unit_context(store_path: Path) -> UnitContext:
    """The probes' view of the store at `store_path`: its HEAD snapshot, ACL snapshot, the
    units `units/HEAD` names for that snapshot (ValueError without) and its overlay."""
    store = Store.open(store_path)
    snap = acl.read_head(store_path)[1]
    units_id = handles.units_head(store_path, store.snapshot_id)
    if units_id is None:
        raise ValueError(f"{store_path}: no units/HEAD for snapshot {store.snapshot_id[:12]}; "
                         f"run `adr units build` and `adr units gate`")
    m = load_units_manifest(store_path, units_id)
    units = sorted(load_units(store_path, m), key=lambda u: u.unit_id)
    by_type: dict[str, list[Unit]] = {}
    for u in units:
        by_type.setdefault(u.type, []).append(u)
    overlay = ap.load_overlay(store_path, store.snapshot_id, m.applicability) \
        if m.applicability is not None else None
    return UnitContext(Path(store_path), store, snap, units_id, m, {u.unit_id: u for u in units},
                       by_type, overlay)


def query_of(u: Unit) -> str:
    """The words a probe searches a unit by: the first `QUERY_WORDS` distinct words of three
    or more letters or digits of its title and reader text."""
    seen: dict[str, str] = {}
    for w in _WORD.findall(f"{u.title} {tu.reader_text(u)}"):
        seen.setdefault(w.lower(), w)
        if len(seen) == QUERY_WORDS:
            break
    return " ".join(seen.values()) or u.title


def secret_of(u: Unit) -> str:
    """What only the hidden unit's document holds: its reader text (cut), or its unit id."""
    text = " ".join(tu.reader_text(u).split())[:SECRET_CHARS]
    return text if len(text) >= 16 else u.unit_id


# -- reference stores --------------------------------------------------------------------------


def units_config(store_path: Path, m: UnitsManifest) -> dict:
    """What a units build was built with, apart from its inputs' ids: format, corpus, model
    passes, unit contracts, whether it read tables (and their extraction) and an overlay."""
    tables = None
    if m.tables_id is not None:
        tables = {"extraction": load_tables_manifest(store_path, m.tables_id).extraction}
    return {"format_version": m.format_version, "corpus": m.corpus, "passes": m.passes,
            "contracts": {f.type: [f.contract_version, f.contract_sha256] for f in m.units},
            "tables": tables, "applicability": m.applicability is not None}


def _view_record(ctx: UnitContext, docs: list[str], directory: Path, policy: Path) -> dict:
    return {"source_snapshot": ctx.store.snapshot_id, "view": acl.view_id(docs),
            "documents": len(docs), "units_config": units_config(ctx.store_path, ctx.manifest),
            "directory_sha256": hashlib.sha256(Path(directory).read_bytes()).hexdigest(),
            "policy_sha256": hashlib.sha256(Path(policy).read_bytes()).hexdigest()}


def _no_case(store_path, units_id, case):   # a first promotion evaluates no case
    raise AssertionError("no case is evaluated in a first promotion")


def unit_reference(ctx: UnitContext, doc_ids: Iterable[str], dst: Path, *, directory: Path,
                   policy: Path, clock: Callable, generator: str | None = None,
                   gov_config: dict | None = None) -> str:
    """Build or reuse the reference store of `doc_ids` at `dst` (module docstring): "built" or
    "reused". The overlay derives under `gov_config` (default: the repository's gov config,
    which the stores were derived with). Refuses (ValueError) anything else at `dst`, an
    envelope that derives otherwise than the store's, and a units build config that differs
    from the store's; a reply missing from the cache stops the tables build (BudgetExceeded)
    before any call."""
    dst = Path(dst)
    docs = sorted(set(doc_ids))
    want = _view_record(ctx, docs, directory, policy)
    if dst.exists():
        try:
            rec = json.loads((dst / UNITS_VIEW_FILE).read_text(encoding="utf-8"))
            store = Store.open(dst)
        except (OSError, ValueError) as e:
            raise ValueError(f"{dst}: exists but is not a finished unit reference store ({e}); "
                             f"remove it") from e
        if rec != want or store.doc_ids() != docs:
            raise ValueError(f"{dst}: holds another view or units build than asked; remove it")
        tp.keep_fresh(dst, directory, policy, clock)
        return "reused"
    tp.bare_reference(ctx.store, docs, dst, directory=directory, policy=policy, clock=clock)
    store = Store.open(dst)
    corpus = ctx.corpus
    if ctx.manifest.applicability is not None:
        overlay, _ = ap.derive(store, eq.gov_config() if gov_config is None else gov_config)
        ap.write_overlay(dst, overlay)
        differ = [d for d in docs if overlay.records[d] != ctx.overlay.records[d]]
        if differ:
            raise ValueError(f"{dst}: the applicability of {len(differ)} documents derives "
                             f"otherwise than in the store")
    if ctx.manifest.tables_id is not None:
        extraction = load_tables_manifest(ctx.store_path, ctx.manifest.tables_id).extraction
        if extraction is None:
            tables_id = build_tables(dst, corpus).tables_id
        else:   # the cached first-pass replies, zero calls (a miss stops: BudgetExceeded)
            tables_id = build_tables(dst, corpus, with_extraction=True,
                                     generator_profile=generator, max_calls=0).tables_id
        if not tables_gate(dst, tables_id, [], 0).promoted:
            raise ValueError(f"{dst}: the reference tables were not promoted")
    units_id = build_units(dst, corpus).units_id   # code only: no model pass, no client
    if not units_gate(dst, units_id, [], 0, hit=_no_case).promoted:
        raise ValueError(f"{dst}: the reference units were not promoted")
    got = units_config(dst, load_units_manifest(dst, units_id))
    if got != want["units_config"]:
        diff = sorted(k for k in got if got[k] != want["units_config"].get(k))
        raise ValueError(f"{dst}: the reference's units build differs from the store's in "
                         f"{', '.join(diff)} (a store whose units were filled by a model pass "
                         f"cannot be rebuilt by code)")
    (dst / UNITS_VIEW_FILE).write_bytes(eq.canonical(want))
    return "built"


class UnitReferences:
    """The unit reference store of each view of `ctx`'s ACL snapshot, built or reused under
    `root` on first use (module docstring); `path_for(caller)` is the caller's (None outside
    the directory). `info` records what each holds (deterministic), `how` whether it was built
    or reused (provenance only)."""

    def __init__(self, ctx: UnitContext, root: Path, *, directory: Path = acl.DIRECTORY_PATH,
                 policy: Path = acl.POLICY_PATH, clock: Callable = acl.utc_now,
                 generator: str | None = None, gov_config: dict | None = None):
        self.ctx, self.root = ctx, Path(root)
        self.directory, self.policy, self.clock = directory, policy, clock
        self.generator, self.gov_config = generator, gov_config
        self.views = eq.views(ctx.snap)
        self._view_of = {u: v for v in self.views for u in v.users}
        self._paths: dict[str, Path] = {}
        self.offsets: dict[Path, int] = {}
        self.calls0: dict[Path, int] = {}
        self.info: list[dict] = []
        self.how: dict[str, str] = {}

    def path_for(self, caller: str | None) -> Path | None:
        v = self._view_of.get(caller) if isinstance(caller, str) else None
        return None if v is None else self.path_of(v)

    def path_of(self, v: eq.View) -> Path:
        if v.view in self._paths:   # a long run: keep the reference's ACL fresh too
            tp.keep_fresh(self._paths[v.view], self.directory, self.policy, self.clock)
            return self._paths[v.view]
        path = self.root / v.view[:12]
        how = unit_reference(self.ctx, v.docs, path, directory=self.directory,
                             policy=self.policy, clock=self.clock, generator=self.generator,
                             gov_config=self.gov_config)
        ref = unit_context(path)
        mine = {i: u for i, u in self.ctx.units.items() if u.doc_id in v.docs}
        self._paths[v.view] = path
        self.offsets[path] = log_size(log_path(path))
        self.calls0[path] = unit_calls(log_path(path))
        self.how[path.name] = how
        self.info.append({**v.summary(), "path": path.name, "units": ref.units_id,
                          "units_of_view": len(mine),
                          "units_equal": sum(i in ref.units and comparable(ref.units[i])
                                             == comparable(u) for i, u in mine.items())})
        return path

    def log_scans(self) -> dict:
        """`scan_unit_log` of each reference store's log since it was first used here, with
        the unit calls made on it since then."""
        return {p.name: scan_unit_log(log_path(p), off,
                                      calls=unit_calls(log_path(p)) - self.calls0[p])
                for p, off in sorted(self.offsets.items())}

    def provenance(self) -> dict:
        """What differs between runs: how each reference came about and its ACL snapshot."""
        out = {}
        for name in sorted(self.how):
            sid, snap = acl.read_head(self.root / name)
            out[name] = {"how": self.how[name], "acl_snapshot": sid,
                         "acl_sequence": snap.sequence}
        return out

    def remove(self) -> list[str]:
        """Remove the reference store of every view under `root`, used in this run or kept
        by an earlier one (and `root`, once empty)."""
        paths = sorted(p for p in {self.root / v.view[:12] for v in self.views} if p.is_dir())
        for p in paths:
            shutil.rmtree(p, ignore_errors=True)
        if self.root.is_dir() and not any(self.root.iterdir()):
            self.root.rmdir()
        self._paths.clear()
        return [str(p) for p in paths]


# -- calls and outcomes ------------------------------------------------------------------------


_calls: Counter = Counter()      # unit tool calls made through `run_unit_call`, by log file
_calls_lock = threading.Lock()


def unit_calls(log: Path) -> int:
    """How many unit tool calls `run_unit_call` has made on a `Tools` whose log is `log` (in
    this process); the S2 scans compare the difference over a run with the log lines."""
    with _calls_lock:
        return _calls[str(Path(log).resolve())]


def run_unit_call(t, call: dict) -> tuple:
    """("ok", result) | ("denied", code, message) | ("refused", message): one unit tool call
    `{"tool": …, "args": {…}}` on `t` (a `Tools` or an MCP client of the same shape). A call on
    a `Tools` is counted against its log file (`unit_calls`)."""
    if call["tool"] not in UNIT_TOOLS:
        raise ValueError(f"unknown unit tool {call['tool']!r}")
    if isinstance(t, Tools):
        with _calls_lock:
            _calls[str(Path(t.log_path).resolve())] += 1
    try:
        res = getattr(t, call["tool"])(**call["args"])
    except AccessDenied as e:
        return ("denied", e.code, str(e))
    except ToolError as e:
        return ("refused", str(e))
    return ("ok", res)


def _stripped(res) -> dict:
    return {k: v for k, v in res.to_dict().items() if k not in STORE_SPECIFIC}


def _canonical(data: dict) -> str:
    """`data` as canonical JSON with the tables id of each hit's table-record pointer (that
    path only) replaced: it names the store's Phase 3 tables build (a hash over every row, as
    the snapshot id is over every document), which differs between a store and its reference
    like the snapshot."""
    hits = data.get("hits")
    if isinstance(hits, list):
        data = {**data, "hits": [
            {**h, "pointer": {**h["pointer"], "tables_id": "<tables id>"}}
            if isinstance(h, dict) and isinstance(h.get("pointer"), dict)
            and "tables_id" in h["pointer"] else h for h in hits]}
    return _json(data)


def comparable(u: Unit) -> dict:
    """A unit without what names its store's builds: the tables id (envelope and pointer)
    and the metadata hash that covers it."""
    d = u.model_dump(mode="json")
    d.pop("tables_id", None)
    d["hashes"] = {k: v for k, v in d.get("hashes", {}).items() if k != "meta"}
    if isinstance(d["body"].get("pointer"), dict):
        d["body"]["pointer"] = {k: v for k, v in d["body"]["pointer"].items()
                                if k != "tables_id"}
    return d


def outcome_key(out: tuple) -> tuple:
    """What two stores' answers are compared by: the result without store-specific fields, or
    the refusal with snapshot ids replaced."""
    if out[0] == "ok":
        return ("ok", _canonical(_stripped(out[1])))
    if out[0] == "refused":
        return ("refused", tp._SNAP.sub("<id>…", out[1]))
    return ("denied", out[1], tp._SNAP.sub("<id>…", out[2]))


def _counts(out: tuple) -> tuple | None:
    if out[0] != "ok":
        return None
    d = out[1].to_dict()
    if "senses" in d:
        return (len(d["senses"]), len(d["nearest"]))
    if "cards" in d:
        return (len(d["cards"]), sum(len(c["closure"]) for c in d["cards"]),
                d["excluded_by_filter"], d["truncated"])
    if "catalog" in d:
        return (None if d["catalog"] is None else len(d["catalog"]), d["rendering"] is None)
    if "hits" in d:
        return (len(d["hits"]), sum(bool(h["truncated"]) for h in d["hits"]))
    return ()


def _payload(out: tuple) -> str:
    """The text a caller learns from an outcome, without the caller's own arguments."""
    if out[0] == "ok":
        return _canonical({k: v for k, v in _stripped(out[1]).items() if k not in ECHO})
    return out[-1]


def _first_difference(a: tuple, b: tuple) -> str:
    """Where two outcome keys differ, without their contents."""
    if a[0] != b[0]:
        return f"{a[0]} vs {b[0]}"
    if a[0] != "ok":
        return "different refusals"
    da, db = json.loads(a[1]), json.loads(b[1])
    return "fields " + ", ".join(sorted(k for k in set(da) | set(db) if da.get(k) != db.get(k)))


def _units_in(out: tuple) -> list[tuple[str, str]]:
    """(unit id, document id) of every unit an answer returns (closure entries included)."""
    if out[0] != "ok":
        return []
    d = out[1].to_dict()
    found = []
    for s in d.get("senses") or ():
        found.append((s["unit_id"], s["doc_id"]))
    for c in d.get("cards") or ():
        found.append((c["unit_id"], c["doc_id"]))
        found += [(e["unit_id"], e["doc_id"]) for e in c["closure"]]
    for e in d.get("catalog") or ():
        found.append((e["unit_id"], e["doc_id"]))
    for h in d.get("hits") or ():
        found.append((h["unit_id"], h["doc_id"]))
    return found


# -- leak probes -------------------------------------------------------------------------------


class _Pick:
    """Seeded choices for one probe (`k` of `family`, salt `salt`)."""

    def __init__(self, seed: int, family: str, k: int, salt: int):
        self.parts = (seed, family, k, salt)

    def of(self, items: list, what: str):
        return items[_h(*self.parts, what) % len(items)]


def _new_terms(ctx: UnitContext, caller: str, u: Unit) -> list[str]:
    """The labels, alternate labels and hidden labels of concept `u` whose base key no concept
    the caller sees holds."""
    held = ctx.label_keys(caller)
    return [t for t in dict.fromkeys([*_labels(u), *u.body["hidden_labels"]])
            if base_key(t) and base_key(t) not in held]


def _candidates(ctx: UnitContext, caller: str, family: str, type_: str, variant: str) -> list:
    units = ctx.hidden(caller, type_)
    if family == "by-term":
        return [u for u in units if _new_terms(ctx, caller, u)]
    if family == "by-closure" and variant == "closure":
        return [u for u in units if u.body.get("closure")]
    return units


def _variant(ctx: UnitContext, family: str, k: int) -> str:
    if family != "by-closure":
        return "plain"
    has = any(u.body.get("closure") for u in ctx.by_type.get("rule_card", ()))
    return "closure" if has and k % 2 == 0 else "context"


def _shared_term(ctx: UnitContext, caller: str, pick: _Pick, fallback: str) -> str:
    """A preferred label held by two or more concepts the caller sees (so ranking by context
    matters), else `fallback`."""
    seen = ctx.visible(caller)
    keys = Counter(base_key(u.body["pref_label"]) for u in ctx.by_type.get("concept", ())
                   if u.doc_id in seen)
    shared = sorted({u.body["pref_label"] for u in ctx.by_type.get("concept", ())
                     if u.doc_id in seen and keys[base_key(u.body["pref_label"])] > 1})
    return pick.of(shared, "term") if shared else fallback


def _leak_calls(ctx: UnitContext, family: str, variant: str, k: int, caller: str, u: Unit,
                pick: _Pick) -> list[dict]:
    q = query_of(u)
    if family == "by-id":
        if u.type == "rule_card":
            return [{"tool": "rule_lookup", "args": {"rule_id": u.canonical_ref, "limit": 100,
                                                     **WIDE}},
                    {"tool": "rule_lookup", "args": {"rule_id": tu.section_of(u.canonical_ref),
                                                     "limit": 100, "closure": k % 2 == 0,
                                                     **WIDE}}]
        return [{"tool": "procedure_lookup", "args": {"id": u.unit_id, "view": VIEWS[k % 4]}},
                {"tool": "procedure_lookup", "args": {"id": u.canonical_ref}}]
    if family == "by-term":
        term = pick.of(_new_terms(ctx, caller, u), "term")
        return [{"tool": "define", "args": {"term": term, **WIDE}},
                {"tool": "define", "args": {"term": term, "context": u.body["scope"]["ref"],
                                            **WIDE}}]
    if family == "by-query":
        calls = [{"tool": "unit_search", "args": {"query": q, "limit": 20}},
                 {"tool": "unit_search", "args": {"query": q, "types": [u.type], "limit": 20}}]
        if u.type == "rule_card":
            calls.append({"tool": "rule_lookup", "args": {"query": q, "limit": 20, **WIDE}})
        elif u.type == "procedure":
            calls.append({"tool": "procedure_lookup", "args": {"task": q, "limit": 20}})
        elif u.type == "concept":
            calls.append({"tool": "define", "args": {"term": u.body["pref_label"], **WIDE}})
        return calls
    if family == "by-closure":
        if variant == "closure":
            e = pick.of(u.body["closure"], "entry")
            rid = e["ref"] if normalise_rule_id(e["ref"]) else tu.section_of(u.canonical_ref)
            return [{"tool": "rule_lookup", "args": {"rule_id": rid, "limit": 100, **WIDE}},
                    {"tool": "rule_lookup", "args": {"query": q, "limit": 20, **WIDE}}]
        term = _shared_term(ctx, caller, pick,
                            u.body["pref_label"] if u.type == "concept" else u.title)
        return [{"tool": "define", "args": {"term": term, "context": u.unit_id, **WIDE}},
                {"tool": "define", "args": {"term": term, "context": u.canonical_ref, **WIDE}}]
    if family == "by-error":
        pid = u.unit_id + "~" if u.type == "procedure" else u.unit_id
        return [{"tool": "rule_lookup", "args": {"rule_id": f"{u.canonical_ref}(zz9)", **WIDE}},
                {"tool": "procedure_lookup", "args": {"id": pid, "view": "skill"}},
                {"tool": "procedure_lookup", "args": {"task": u.title, "id": u.unit_id}}]
    raise ValueError(f"unknown leak family {family!r}")


def _draw(ctx: UnitContext, seed: int, family: str, k: int, taken: set, callers: list[str]
          ) -> tuple[str, Unit, str, _Pick]:
    variant = _variant(ctx, family, k)
    for salt in range(10_000):
        pick = _Pick(seed, family, k, salt)
        caller = pick.of(callers, "caller")
        types = [t for t in FAMILY_TYPES[family]
                 if _candidates(ctx, caller, family, t, variant)]
        if variant == "closure":
            types = [t for t in types if t == "rule_card"]
        if not types:
            continue
        type_ = types[(k + salt) % len(types)]
        u = pick.of(_candidates(ctx, caller, family, type_, variant), "unit")
        if (caller, u.unit_id) in taken:
            continue
        taken.add((caller, u.unit_id))
        return caller, u, variant, pick
    raise ValueError(f"{family}: no untaken (caller, hidden unit) pair for probe {k}")


def leak_probes(store_path: Path, corpus: str, seed: int = SEED4,
                sizes: dict | None = None) -> list[Probe]:
    """The leak probes of the store's current units (module docstring), in family order."""
    ctx = unit_context(store_path)
    if ctx.corpus != corpus:
        raise ValueError(f"{store_path}: its units are of {ctx.corpus}, not {corpus}")
    if corpus not in LEAK_SIZES:
        raise ValueError(f"no leak probe sizes for {corpus} (only {', '.join(LEAK_SIZES)})")
    sizes = {**LEAK_SIZES[corpus], **(sizes or {})}
    probes = []
    for family in LEAK_SIZES[corpus]:
        taken: set = set()
        callers = [c for c in ctx.callers()
                   if any(_candidates(ctx, c, family, t, v) for t in FAMILY_TYPES[family]
                          for v in {_variant(ctx, family, 0), _variant(ctx, family, 1)})]
        if not callers and sizes[family]:
            raise ValueError(f"{family}: no directory user has a hidden unit to probe")
        for k in range(sizes[family]):
            caller, u, variant, pick = _draw(ctx, seed, family, k, taken, callers)
            calls = _leak_calls(ctx, family, variant, k, caller, u, pick)
            probes.append(Probe(
                f"{family}:{k:03d}", family, ",".join(dict.fromkeys(c["tool"] for c in calls)),
                caller, {"unit_id": u.unit_id, "doc_id": u.doc_id, "type": u.type,
                         "variant": variant, "secret": secret_of(u),
                         "in_directory": caller in ctx.snap.directory},
                {"calls": calls}))
    return probes


class _HiddenIds:
    """Finds ids of documents a caller cannot see in a text: full document ids, or 12 or more
    hex characters beginning one (unit ids carry 16)."""

    def __init__(self, ctx: UnitContext, caller):
        seen = ctx.visible(caller)
        self.by12: dict[str, list[str]] = {}
        for d in ctx.store.doc_ids():
            if d not in seen:
                self.by12.setdefault(d[:12], []).append(d)

    def __call__(self, text: str) -> set[str]:
        return {d for tok in _HEX.findall(text) for d in self.by12.get(tok[:12], ())
                if d.startswith(tok[:64])}


def check_leak(probe: Probe, mine, ref, ctx: UnitContext,
               hidden_ids: _HiddenIds | None = None) -> ProbeResult:
    """Run one leak probe as its caller (`mine`, a `Tools` or MCP client) and judge the five
    kinds (module docstring) against the same calls on the caller's reference (`ref`, a
    `Tools`; None when the caller has none)."""
    caller, target = probe.caller, probe.target
    calls = probe.call["calls"]
    outs = [run_unit_call(mine, c) for c in calls]
    kinds: dict = dict.fromkeys(LEAK_KINDS)
    outcome = ",".join(o[0] if o[0] != "denied" else f"denied:{o[1]}" for o in outs)
    if any(o[0] == "denied" for o in outs) or ref is None:
        return ProbeResult(probe.probe_id, probe.family, probe.tool, caller, outcome, kinds,
                           False, False, "no reference store" if ref is None
                           else f"unexpected outcome {outcome}")
    hidden_ids = hidden_ids or _HiddenIds(ctx, caller)
    given = _json(calls)
    theirs = [run_unit_call(ref, c) for c in calls]
    for k in LEAK_KINDS:
        kinds[k] = False
    secret = target["secret"]
    for a, b in zip(outs, theirs, strict=True):
        pa, pb = _payload(a), _payload(b)
        kinds["id_outside_view"] |= bool({d for d in hidden_ids(pa) - hidden_ids(pb)
                                          if d[:12] not in given})
        kinds["hidden_value"] |= secret in pa and secret not in pb and secret not in given
        ka, kb = outcome_key(a), outcome_key(b)
        if a[0] == "ok" and b[0] == "ok":
            kinds["count_differs"] |= _counts(a) != _counts(b)
            kinds["rows_differ"] |= ka != kb
        else:
            kinds["error_differs"] |= ka != kb
    return ProbeResult(probe.probe_id, probe.family, probe.tool, caller, outcome, kinds,
                       any(kinds.values()), True)


def run_leaks(probes: list[Probe], store_path: Path, views_root: Path, *,
              directory: Path = acl.DIRECTORY_PATH, policy: Path = acl.POLICY_PATH,
              clock: Callable = acl.utc_now, refs: UnitReferences | None = None,
              generator: str | None = None, gov_config: dict | None = None
              ) -> list[ProbeResult]:
    """Run the leak probes, one caller's `Tools` at a time, against the reference stores under
    `views_root` (built or reused on first use; `refs` to share them), in probe order. The
    store's ACL is re-synced when it nears its freshness limit."""
    ctx = unit_context(store_path)
    refs = refs or UnitReferences(ctx, views_root, directory=directory, policy=policy,
                                  clock=clock, generator=generator, gov_config=gov_config)
    out: dict[str, ProbeResult] = {}
    for caller in sorted({p.caller for p in probes}, key=str):
        ref_path = refs.path_for(caller)
        tp.keep_fresh(store_path, directory, policy, clock)
        mine = Tools(store_path, acl=True, caller=caller, clock=clock)
        ref = None if ref_path is None else Tools(ref_path, acl=True, caller=caller,
                                                  clock=clock)
        hidden_ids = _HiddenIds(ctx, caller)
        for p in probes:
            if p.caller == caller:
                out[p.probe_id] = check_leak(p, mine, ref, ctx, hidden_ids)
    return [out[p.probe_id] for p in probes]


def summarize_leaks(results: list[ProbeResult]) -> dict:
    """Counts per family and in total (no ids)."""
    out = tp.summarize_leaks(results)
    for b in out["families"].values():
        b.pop("ghost", None)
    out["total"].pop("ghost", None)
    return out


# -- equivalence (S1) --------------------------------------------------------------------------

SLOTS = ("define", "rule_lookup", "procedure_lookup", "unit_search") * 6 + ("unit_search",)
TOOL_TYPES = {"define": ("concept",), "rule_lookup": ("rule_card",),
              "procedure_lookup": ("procedure",), "unit_search": None}


def boundary_dates(ctx: UnitContext) -> list[str]:
    """Each chain version's first day in force and the day before it (ISO dates), sorted;
    one fixed date when no document has one."""
    starts = sorted({r.valid_from for d, r in (ctx.overlay.records.items() if ctx.overlay
                                               else ()) if r.chain_id and r.valid_from})
    found = sorted({x.isoformat() for s in starts for x in (s - timedelta(days=1), s)})
    return found or ["2026-06-30"]


def _filters_variant(h: int, dates: list[str], wide: bool) -> dict:
    v = h % 3
    if v == 1 and wide:
        return dict(WIDE)
    if v == 2:
        return {"as_of": dates[(h // 3) % len(dates)]}
    return {}


def _equivalence_call(ctx: UnitContext, tool: str, pool: list[Unit], h: int,
                      dates: list[str]) -> dict:
    types = TOOL_TYPES[tool]
    units = [u for u in pool if types is None or u.type in types] or \
        [u for u in ctx.units.values() if types is None or u.type in types] or \
        list(ctx.units.values())
    u = units[h % len(units)]
    h2 = h // max(1, len(units))
    if tool == "define":
        terms = [*_labels(u), *u.body.get("hidden_labels", [])] if u.type == "concept" \
            else [u.title]
        term = terms[h2 % len(terms)]
        cards = ctx.by_type.get("rule_card", [])
        contexts = [None, u.body["scope"]["ref"] if u.type == "concept" else None,
                    cards[h2 % len(cards)].canonical_ref if cards else None]
        args = {"term": term, **_filters_variant(h2 // 7, dates, True)}
        if (c := contexts[(h2 // 5) % 3]) is not None:
            args["context"] = c
        return {"tool": tool, "args": args}
    if tool == "rule_lookup":
        v = h2 % 4
        f = _filters_variant(h2 // 4, dates, True)
        if u.type != "rule_card" or v == 2:
            return {"tool": tool, "args": {"query": query_of(u), **f}}
        if v == 0:
            return {"tool": tool, "args": {"rule_id": u.canonical_ref, **f}}
        if v == 1:
            return {"tool": tool, "args": {"rule_id": tu.section_of(u.canonical_ref), **f}}
        part = u.canonical_ref.split(".", 1)[0]
        return {"tool": tool, "args": {"query": query_of(u), "part": part, **f}}
    if tool == "procedure_lookup":
        v = h2 % 6
        f = _filters_variant(h2 // 6, dates, False)
        if u.type != "procedure" or v == 0:
            return {"tool": tool, "args": {"task": query_of(u), **f}}
        if v == 5:
            return {"tool": tool, "args": {"id": u.canonical_ref, **f}}
        return {"tool": tool, "args": {"id": u.unit_id, "view": VIEWS[v - 1], **f}}
    args = {"query": query_of(u), **_filters_variant(h2 // 2, dates, False)}
    if h2 % 2:
        args["types"] = [u.type]
    return {"tool": "unit_search", "args": args}


def equivalence_calls(ctx: UnitContext, v: eq.View, n_calls: int = 25,
                      seed: int = SEED4) -> dict[str, dict]:
    """The `n_calls` calls of view `v` (module docstring), by call id."""
    mine = [u for u in ctx.units.values() if u.doc_id in v.docs]
    every = list(ctx.units.values())
    dates = boundary_dates(ctx)
    tools = [t for t in SLOTS if t in present_tools()]
    out = {}
    for i in range(n_calls):
        tool = tools[i % len(tools)]
        pool = mine if i % 3 != 2 and mine else every
        out[f"{i:03d}"] = _equivalence_call(ctx, tool, pool, _h(seed, "equivalence", v.view, i),
                                            dates)
    return out


def equivalence(store_path: Path, corpus: str, views_root: Path, n_calls: int = 25,
                seed: int = SEED4, *, directory: Path = acl.DIRECTORY_PATH,
                policy: Path = acl.POLICY_PATH, clock: Callable = acl.utc_now,
                refs: UnitReferences | None = None, generator: str | None = None,
                gov_config: dict | None = None) -> list[dict]:
    """Unit equivalence (module docstring): one row per call per view, in view order, with
    `identical`, the outcome and, when they differ, where (no content)."""
    ctx = unit_context(store_path)
    if ctx.corpus != corpus:
        raise ValueError(f"{store_path}: its units are of {ctx.corpus}, not {corpus}")
    refs = refs or UnitReferences(ctx, views_root, directory=directory, policy=policy,
                                  clock=clock, generator=generator, gov_config=gov_config)
    rows: list[dict] = []
    for v in refs.views:
        calls = equivalence_calls(ctx, v, n_calls, seed)
        ref_path = refs.path_of(v)
        tp.keep_fresh(store_path, directory, policy, clock)
        mine = Tools(store_path, acl=True, caller=v.caller, clock=clock)
        ref = Tools(ref_path, acl=True, caller=v.caller, clock=clock)
        for q, call in calls.items():
            a, b = run_unit_call(mine, call), run_unit_call(ref, call)
            ka, kb = outcome_key(a), outcome_key(b)
            rows.append({"view": v.view, "caller": v.caller, "call_id": q, "tool": call["tool"],
                         "identical": ka == kb, "outcome": a[0],
                         "difference": None if ka == kb else _first_difference(ka, kb)})
    return rows


def summarize_equivalence(rows: list[dict]) -> dict:
    by: dict[str, dict] = {}
    for r in rows:
        b = by.setdefault(r["tool"], {"n": 0, "identical": 0, "refused": 0})
        b["n"] += 1
        b["identical"] += r["identical"]
        b["refused"] += r["outcome"] != "ok"
    return {"n": len(rows), "identical": sum(r["identical"] for r in rows),
            "differing": sum(not r["identical"] for r in rows),
            "views": len({r["view"] for r in rows}), "by_tool": dict(sorted(by.items())),
            "total": {"n": len(rows), "passed": sum(r["identical"] for r in rows)}}


# -- fail closed (S2) --------------------------------------------------------------------------

FAILCLOSED_TYPES = {"define": ("concept",), "rule_lookup": ("rule_card",),
                    "procedure_lookup": ("procedure",),
                    "unit_search": ("procedure", "rule_card", "concept", "faq", "table_record")}
FAILCLOSED_TRIES = 40


def _absent_ref(ctx: UnitContext, ref: str) -> str:
    section = tu.section_of(ref)
    refs = {u.canonical_ref for u in ctx.by_type.get("rule_card", ())}
    out = section + "9"
    while any(tu.under(r, out) for r in refs):
        out += "9"
    return out


def _failclosed_calls(ctx: UnitContext, tool: str, u: Unit) -> tuple[dict, dict | None]:
    """(the call naming target `u` with `tool`, the same call naming nothing, or None)."""
    if tool == "define":
        return {"tool": tool, "args": {"term": u.body["pref_label"], **WIDE}}, None
    if tool == "rule_lookup":
        return ({"tool": tool, "args": {"rule_id": u.canonical_ref, **WIDE}},
                {"tool": tool, "args": {"rule_id": _absent_ref(ctx, u.canonical_ref), **WIDE}})
    if tool == "procedure_lookup":
        absent = next(f"{u.unit_id[:-1]}{c}" for c in "0123456789abcdef"
                      if f"{u.unit_id[:-1]}{c}" not in ctx.units)
        return ({"tool": tool, "args": {"id": u.unit_id}},
                {"tool": tool, "args": {"id": absent}})
    if tool == "unit_search":
        return {"tool": tool, "args": {"query": query_of(u), "limit": 10}}, None
    raise ValueError(f"no fail-closed calls for tool {tool!r}")


def _unique_to(ctx: UnitContext, tool: str, u: Unit, docs: frozenset[str]) -> bool:
    """Whether the call naming `u` can only find units of `docs` (its chain)."""
    if tool == "define":
        key = base_key(u.body["pref_label"])
        return bool(key) and all(c.doc_id in docs for c in ctx.by_type.get("concept", ())
                                 if key in _term_keys(c))
    if tool == "rule_lookup":
        return all(c.doc_id in docs for c in ctx.by_type.get("rule_card", ())
                   if tu.under(c.canonical_ref, u.canonical_ref))
    return True


def _found(tool: str, out: tuple, u: Unit, docs: frozenset[str]) -> bool:
    """Whether an answer returns target `u` (or, for `define`, a sense of its documents)."""
    got = _units_in(out)
    if tool == "define":
        return any(d in docs for _, d in got)
    return any(i == u.unit_id for i, _ in got)


def failclosed_targets(ctx: UnitContext, users: list[str], tools: tuple[str, ...],
                       clock: Callable, seed: int = SEED4) -> dict[str, dict]:
    """The fail-closed target of each tool (module docstring): tool -> {unit_id, doc_id, type,
    docs (the target documents), secret, call, control, before (caller -> visible, found)}.
    ValueError when a tool has none."""
    made = {u: Tools(ctx.store_path, acl=True, caller=u, clock=clock) for u in users}
    uris = {d: ctx.store.source(d).uri for d in ctx.store.doc_ids()}
    out = {}
    for tool in tools:
        cands = [u for t in FAILCLOSED_TYPES.get(tool, ()) for u in ctx.by_type.get(t, ())]
        if tool not in FAILCLOSED_TYPES:
            raise ValueError(f"no fail-closed calls for tool {tool!r}")
        cands.sort(key=lambda u: (-sum(u.doc_id in ctx.visible(x) for x in users),
                                  _h(seed, "failclosed", tool, u.unit_id), u.unit_id))
        tried = 0
        for u in cands:
            docs = ctx.chain_docs(u.doc_id)
            if any(o not in docs and uri.startswith(uris[d]) for d in docs
                   for o, uri in uris.items()) or not _unique_to(ctx, tool, u, docs):
                continue
            tried += 1
            if tried > FAILCLOSED_TRIES:
                break
            call, control = _failclosed_calls(ctx, tool, u)
            before = {}
            for x, t in made.items():
                sees = u.doc_id in ctx.visible(x)
                before[x] = {"visible": sees, "found": _found(tool, run_unit_call(t, call), u,
                                                              docs)}
            if all(b["found"] == b["visible"] for b in before.values()) and \
                    any(b["visible"] for b in before.values()):
                out[tool] = {"unit_id": u.unit_id, "doc_id": u.doc_id, "type": u.type,
                             "docs": sorted(docs), "secret": secret_of(u), "call": call,
                             "control": control, "before": before}
                break
        if tool not in out:
            raise ValueError(f"{tool}: no unit meets the fail-closed precondition (seen by a "
                             f"fail-closed caller, found by its call exactly by those who see "
                             f"it)")
    return out


def _shows(text: str, target: dict) -> bool:
    return any(d in text or d[:12] in text for d in target["docs"]) or \
        target["secret"] in text


def judge_unit_failclosed(cond: str, tool: str, target: dict, out: tuple,
                          control: tuple | None) -> dict:
    """Whether a fail-closed probe returned nothing of the target (module docstring)."""
    shown = _shows(_payload(out), target) or any(d in target["docs"] for _, d in _units_in(out))
    label = out[0] if out[0] != "denied" else f"denied:{out[1]}"
    if cond != "no_entry":
        return {"outcome": label, "content": out[0] == "ok",
                "pass": out[0] == "denied" and out[1] == cond and not shown}
    if out[0] == "denied":
        return {"outcome": label, "content": False, "pass": False}
    if control is None:
        return {"outcome": label, "content": shown, "pass": out[0] == "ok" and not shown}
    same = out[0] == control[0] == "refused" and out[1] == control[1] and \
        out[1] in (UNKNOWN_RULE, UNKNOWN_PROCEDURE)
    return {"outcome": label, "content": shown, "not_found_equal": same,
            "pass": same and not shown}


def _no_entry_policy(policy: Path, uris: list[str], out: Path) -> Path:
    data = json.loads(Path(policy).read_text(encoding="utf-8"))
    data["rules"] = [*({"match": {"uri_prefix": u}, "access": []} for u in uris),
                     *data.get("rules", [])]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def failclosed(store_path: Path, clone_root: Path, corpus: str, seed: int = SEED4,
               tools: tuple[str, ...] | None = None, *, directory: Path = acl.DIRECTORY_PATH,
               policy: Path = acl.POLICY_PATH, clock: Callable = acl.utc_now,
               logs: dict | None = None) -> list[dict]:
    """The fail-closed probes (module docstring): 6 conditions × `tools` (None: every unit
    tool `Tools` has) × 5 callers, one row each. F4 and F5 run on the store, the others on
    clones under `clone_root` (removed). `logs`, when given, receives the log scan of each
    store the calls wrote to."""
    store_path, clone_root = Path(store_path), Path(clone_root)
    present = present_tools()
    tools = present if tools is None else tuple(tools)
    unknown = [t for t in tools if t not in present]
    if unknown:
        raise ValueError(f"unknown or absent unit tool(s) {', '.join(unknown)}; the tools are "
                         f"{', '.join(present)}")
    ctx = unit_context(store_path)
    if ctx.corpus != corpus:
        raise ValueError(f"{store_path}: its units are of {ctx.corpus}, not {corpus}")
    users = acl_probes.failclosed_callers(ctx, seed)
    targets = failclosed_targets(ctx, users, tools, clock, seed)
    target_docs = sorted({d for t in targets.values() for d in t["docs"]})
    rows: list[dict] = []
    logs = {} if logs is None else logs

    def run(path: Path, cond: str, probes: list[tuple[int, str | None, str | None]]) -> None:
        for i, caller, variant in probes:
            t = Tools(path, acl=True, caller=caller, clock=clock)
            for tool in tools:
                tg = targets[tool]
                out = run_unit_call(t, tg["call"])
                ctrl = run_unit_call(t, tg["control"]) \
                    if cond == "no_entry" and tg["control"] is not None else None
                b = tg["before"].get(caller)
                rows.append({"probe_id": f"{cond}:{i}:{tool}", "family": cond, "tool": tool,
                             "caller": caller, "variant": variant, "target_type": tg["type"],
                             "visible_before": None if b is None else b["visible"],
                             **judge_unit_failclosed(cond, tool, tg, out, ctrl)})

    def mark(path: Path) -> tuple[int, int]:
        return log_size(log_path(path)), unit_calls(log_path(path))

    def scanned(name: str, path: Path, since: tuple[int, int]) -> None:
        offset, calls = since
        logs[name] = merge_unit_scans(logs.get(name), scan_unit_log(
            log_path(path), offset, calls=unit_calls(log_path(path)) - calls))

    plain = [(i, u, None) for i, u in enumerate(users)]
    for cond in CONDITIONS:
        if cond in ("F4", "F5"):
            since = mark(store_path)
            run(store_path, cond, [(i, u, None) for i, u in enumerate(
                F4_CALLERS if cond == "F4" else F5_CALLERS)])
            scanned("store", store_path, since)
            continue
        clone = clone_root / f"units-failclosed-{cond}"
        _cp(store_path, clone)
        since = mark(clone)
        try:
            if cond == "F1":
                damage = _F1(clone)
                for i, variant in enumerate(F1_VARIANTS):
                    damage.apply(variant)
                    try:
                        run(clone, cond, [(i, users[i], variant)])
                    finally:
                        damage.undo()
            elif cond == "F2":
                s = Store.open(clone)
                records = {d: r for d, r in s._records.items() if d != target_docs[0]}
                Store(clone, None, records, s.paths).commit()
                run(clone, cond, plain)
            elif cond == "F3":
                for variant, shift in (("stale", -STALE), ("future", AHEAD)):
                    acl.sync(clone, directory, policy, clock=lambda s=shift: clock() + s)
                    run(clone, cond, [(i, users[i], v) for i, v in enumerate(F3_VARIANTS)
                                      if v == variant])
            else:   # no entry
                uris = [ctx.store.source(d).uri for d in target_docs]
                pol = _no_entry_policy(policy, uris, clone / "policy-no-entry.json")
                before = acl.read_head(clone)[1].docs
                acl.sync(clone, directory, pol, clock=clock)
                after = acl.read_head(clone)[1].docs
                changed = {d for d in after if after[d] != before.get(d)}
                if any(after.get(d) != [] for d in target_docs) or \
                        not changed <= set(target_docs):
                    raise ValueError(f"the no-entry rules changed {len(changed)} documents' "
                                     f"access, not only the {len(target_docs)} targets'")
                run(clone, cond, plain)
            scanned(f"clone-{cond}", clone, since)
        finally:
            shutil.rmtree(clone, ignore_errors=True)
    if clone_root.is_dir() and not any(clone_root.iterdir()):
        clone_root.rmdir()
    return rows


def failclosed_identity(rows: list[dict]) -> dict:
    """What the probe set targeted, without ids: each tool's target unit type."""
    return dict(sorted({r["tool"]: r["target_type"] for r in rows}.items()))


def summarize_failclosed(rows: list[dict]) -> dict:
    """Counts per condition and per tool; per tool, how many "no entry" callers saw its
    target before the change (`visible_before`; the rest prove only that nothing appears)."""
    entry = [r for r in rows if r["family"] == "no_entry"]
    return tp.summarize_failclosed(rows) | {
        "by_tool": {t: {"n": sum(r["tool"] == t for r in rows),
                        "passed": sum(r["pass"] for r in rows if r["tool"] == t),
                        "no_entry": sum(r["tool"] == t for r in entry),
                        "no_entry_visible_before": sum(bool(r["visible_before"])
                                                       for r in entry if r["tool"] == t)}
                    for t in sorted({r["tool"] for r in rows})}}


# -- applicability -----------------------------------------------------------------------------


def applicability_dates(ctx: UnitContext, n: int, seed: int = SEED4) -> list[str]:
    """The `n` `as_of` dates: the version boundaries first (`boundary_dates`), then dates
    drawn by seeded hash from a year before the first to a year after the last."""
    first = boundary_dates(ctx)
    lo = date.fromisoformat(first[0]) - timedelta(days=365)
    span = (date.fromisoformat(first[-1]) + timedelta(days=365) - lo).days
    rest, k = [], 0
    while len(first) + len(rest) < n:
        d = (lo + timedelta(days=_h(seed, "as_of", k) % (span + 1))).isoformat()
        if d not in first and d not in rest:
            rest.append(d)
        k += 1
    return [*first, *rest][:n]


def _multi_version(units: list[Unit], ctx: UnitContext, key: Callable) -> list[str]:
    """The keys held by units of two or more documents of one chain, sorted."""
    docs: dict[str, set] = {}
    for u in units:
        if ctx.chain(u.doc_id):
            docs.setdefault(key(u), set()).add(u.doc_id)
    return sorted(k for k, d in docs.items() if len(d) > 1)


def applicability_probes(store_path: Path, n: int = 50, seed: int = SEED4, *,
                         caller: str = "user:auditor", clock: Callable = acl.utc_now
                         ) -> list[dict]:
    """The applicability probes (module docstring): per date (the default, then `n` as_of
    dates) one row per read tool: the units returned, the documents outside the filters, the
    most versions of one chain, the expected count for the lookups by id and term, and
    pass."""
    ctx = unit_context(store_path)
    seen = ctx.visible(caller)
    cards = ctx.by_type.get("rule_card", [])
    concepts = ctx.by_type.get("concept", [])
    refs = _multi_version(cards, ctx, lambda u: u.canonical_ref) or \
        sorted({u.canonical_ref for u in cards})
    terms = _multi_version(concepts, ctx, lambda u: u.body["pref_label"]) or \
        sorted({u.body["pref_label"] for u in concepts})
    queries = [query_of(u) for u in cards if u.canonical_ref in set(refs)] or \
        [query_of(u) for u in ctx.units.values()]
    tasks = sorted({query_of(u) for u in ctx.by_type.get("procedure", ())}) or queries
    order = lambda xs, what: sorted(xs, key=lambda x: (_h(seed, what, x), x))   # noqa: E731
    refs, terms, queries, tasks = (order(refs, "ref"), order(terms, "term"),
                                   order(sorted(set(queries)), "query"), order(tasks, "task"))
    dates = applicability_dates(ctx, n, seed)
    t = Tools(store_path, acl=True, caller=caller, clock=clock)
    tools = [x for x in READ_TOOLS if x in present_tools()]
    rows = []
    for k in range(n + 1):
        as_of = None if k == 0 else dates[k - 1]
        filters = {} if as_of is None else {"as_of": as_of}
        admitted = ctx.admitted(seen, filters)
        calls: dict[str, tuple[str, dict, list | None]] = {}
        if refs:
            rid = refs[k % len(refs)]
            want = sorted(u.unit_id for u in cards
                          if tu.under(u.canonical_ref, rid) and u.doc_id in admitted)
            calls["id"] = ("rule_lookup", {"rule_id": rid, "limit": 100, **filters}, want)
        if queries:
            calls["query"] = ("rule_lookup", {"query": queries[k % len(queries)], "limit": 20,
                                              **filters}, None)
        if terms:
            term = terms[k % len(terms)]
            calls["term"] = ("define", {"term": term, **filters},
                             _expected_ids(ctx, term, None, admitted))
        if queries:
            calls["search"] = ("unit_search", {"query": queries[k % len(queries)],
                                               "types": ["concept", "rule_card"], "limit": 20,
                                               **filters}, None)
        if tasks:
            calls["task"] = ("procedure_lookup", {"task": tasks[k % len(tasks)], "limit": 10,
                                                  **filters}, None)
        for name, (tool, args, want) in calls.items():
            if tool not in tools:
                continue
            out = run_unit_call(t, {"tool": tool, "args": args})
            got = _units_in(out)
            docs = {d for _, d in got}
            chains = Counter(ctx.chain(d) for d in docs if ctx.chain(d) is not None)
            ids: list[str] = []
            if out[0] == "ok" and name == "id":
                ids = sorted(c.unit_id for c in out[1].cards)
            elif out[0] == "ok" and name == "term":
                ids = [s.unit_id for s in out[1].senses]
            answered = out[0] == "ok" or (out == ("refused", UNKNOWN_RULE) and want == [])
            first = out[1].cards[0].doc_id[:12] if name == "id" and out[0] == "ok" and \
                out[1].cards else None
            rows.append({"probe_id": f"{name}:{k:03d}", "tool": tool, "as_of": as_of,
                         "returned": len(got), "documents": len(docs),
                         "outside": len(docs - admitted), "versions": max(chains.values(),
                                                                          default=0),
                         "expected": None if want is None else len(want), "doc": first,
                         "pass": answered and not docs - admitted
                         and max(chains.values(), default=0) <= 1
                         and (want is None or ids == want)})
    return rows


def summarize_applicability(rows: list[dict]) -> dict:
    by = {t: {"n": sum(r["tool"] == t for r in rows),
              "passed": sum(r["pass"] for r in rows if r["tool"] == t),
              "with_units": sum(bool(r["returned"]) for r in rows if r["tool"] == t),
              "outside": sum(r["outside"] for r in rows if r["tool"] == t),
              "max_versions": max((r["versions"] for r in rows if r["tool"] == t), default=0)}
          for t in sorted({r["tool"] for r in rows})}
    return {"total": {"n": len(rows), "passed": sum(r["pass"] for r in rows),
                      "as_of": sum(r["as_of"] is not None for r in rows),
                      "default": sum(r["as_of"] is None for r in rows),
                      "outside": sum(r["outside"] for r in rows),
                      "dates": len({r["as_of"] for r in rows if r["as_of"]})},
            "by_tool": by}


# -- define (U1) -------------------------------------------------------------------------------


def _oracle_context(ctx: UnitContext, context: str | None, allowed: frozenset[str]
                    ) -> tuple[str | None, str | None]:
    """(the canonical ref of a ref `context`, the subpart holding it): the subpart of a
    visible card in force of its section. Unit-id contexts are judged by `place_of` and
    `holds` instead."""
    if context is None:
        return None, None
    ref = normalise_rule_id(context.strip()) or context.strip()
    section = tu.section_of(ref)
    unit = next((u for u in ctx.by_type.get("rule_card", ())
                 if u.doc_id in allowed and tu.section_of(u.canonical_ref) == section), None)
    return ref, None if unit is None else tu.subpart(unit)


# An independent reading of §7 for unit-id contexts: where a unit sits is read from its own
# fields, and whether a sense's scope holds it from the sense's scope kind and ref. It shares
# no code with the tool's context resolution or ranking (`_sense_context`, `context_ref`,
# `scope_contains`, `_KIND_RANK`).
BREADTH = ("paragraph", "section", "subpart", "part", "document")   # §7: narrowest first
_O_PART = re.compile(r"^(\d+) CFR part (\w+)(?:, subpart (\w+))?$")
_O_PROV = re.compile(r"^(\d+) CFR (\w+)\.([\w-]+)((?:\([^()]*\))*)")
_O_DRAW = re.compile(r'^tables:drawbridge_\w+:\{"section":"(\w+)\.([\w-]+)"')
_O_MARK = re.compile(r"\(([^()]*)\)")
_O_TITLE = {"117": "33", "165": "33", "73": "47"}   # the eCFR parts of the gov corpus


@dataclass(frozen=True)
class Place:
    """Where a unit sits: its document and, where it has one, its eCFR title, part, section
    ("117.313"), paragraph marks and subpart."""

    doc: str
    title: str | None = None
    part: str | None = None
    section: str | None = None
    marks: tuple[str, ...] = ()
    subpart: str | None = None


def place_of(u: Unit) -> Place:
    """A unit's place from its own fields: a concept's scope, a rule card's provision, a
    table's section ("33 CFR 117.313 table 1"), a drawbridge record's section filter; the
    subpart from its heading path; for everything else its document alone."""
    sub = next((h[len("Subpart "):] for h in u.heading_path if h.startswith("Subpart ")), None)
    ref = u.body["scope"]["ref"] if u.type == "concept" else u.canonical_ref
    if m := _O_PART.match(ref):
        return Place(u.doc_id, m.group(1), m.group(2), subpart=m.group(3))
    ref = re.sub(r" table \d+$", "", ref)
    if m := _O_DRAW.match(ref):
        return Place(u.doc_id, _O_TITLE.get(m.group(1)), m.group(1),
                     f"{m.group(1)}.{m.group(2)}", subpart=sub)
    if m := _O_PROV.match(ref):
        return Place(u.doc_id, m.group(1), m.group(2), f"{m.group(2)}.{m.group(3)}",
                     tuple(_O_MARK.findall(m.group(4))), sub)
    return Place(u.doc_id)


def holds(sense: Unit, place: Place) -> bool:
    """Whether concept `sense`'s scope holds `place`: a document scope every unit of its
    document; a part every place in that part; a subpart the places in it; a section its
    paragraphs; a paragraph those under it."""
    kind, ref = sense.body["scope"]["kind"], sense.body["scope"]["ref"]
    if kind == "document":
        return place.doc == sense.doc_id
    if m := _O_PART.match(ref):
        same = (place.title, place.part) == (m.group(1), m.group(2))
        return same and (kind == "part" or place.subpart == m.group(3))
    if m := _O_PROV.match(ref):
        marks = tuple(_O_MARK.findall(m.group(4)))
        return ((place.title, place.part, place.section)
                == (m.group(1), m.group(2), f"{m.group(2)}.{m.group(3)}")
                and place.marks[:len(marks)] == marks)
    return False


def _expected_senses(ctx: UnitContext, term: str, context: str | None,
                     allowed: frozenset[str]) -> list[Unit]:
    concepts = [u for u in ctx.by_type.get("concept", ()) if u.doc_id in allowed]
    key = base_key(term)
    found = [u for u in concepts if key and key in {base_key(x) for x in _labels(u)}]
    if not found:
        found = [u for u in concepts if key and key in u.body["hidden_labels"]]
    unit = ctx.units.get(context.strip()) if context is not None else None
    if unit is not None and unit.doc_id in allowed:   # a unit-id context (independent oracle)
        place = place_of(unit)
        return sorted(found, key=lambda u: (not holds(u, place),
                                            BREADTH.index(u.body["scope"]["kind"]), u.unit_id))
    ref, sub = _oracle_context(ctx, context, allowed)

    def rank(u: Unit) -> tuple:
        inside = ref is not None and scope_contains(u.body["scope"]["ref"], ref, subpart=sub)
        return (not inside, _KIND_RANK.get(u.body["scope"]["kind"], len(_KIND_RANK)),
                u.unit_id)

    return sorted(found, key=rank)


def _expected_ids(ctx: UnitContext, term: str, context: str | None,
                  allowed: frozenset[str]) -> list[str]:
    return [u.unit_id for u in _expected_senses(ctx, term, context, allowed)]


def _expected_nearest(ctx: UnitContext, term: str, allowed: frozenset[str]) -> list[str]:
    key = base_key(term)
    labels = sorted({x for u in ctx.by_type.get("concept", ()) if u.doc_id in allowed
                     for x in _labels(u)})
    return sorted(labels, key=lambda x: (tu.edit_distance(key, base_key(x)), x))[:5]


def define_terms(ctx: UnitContext, n_absent: int = 50, seed: int = SEED4) -> list[dict]:
    """The `define` probes (module docstring), in order: every distinct label, alternate label
    and hidden label (its first concept by unit id), the absent terms, the scoped terms with
    each scope as context and without."""
    callers = ctx.callers()
    probes: list[dict] = []
    seen_terms: set[str] = set()
    concepts = ctx.by_type.get("concept", [])
    for c in concepts:
        for kind, terms in (("label", [c.body["pref_label"]]), ("alt", c.body["alt_labels"]),
                            ("hidden", c.body["hidden_labels"])):
            for term in terms:
                if term in seen_terms:
                    continue
                seen_terms.add(term)
                h = _h(seed, "define", term)
                probes.append({"kind": kind, "term": term, "of": c.unit_id,
                               "caller": callers[h % len(callers)], "context": None,
                               "filters": dict(WIDE) if (h // len(callers)) % 2 else {}})
    keys = {k for c in concepts for k in _term_keys(c)}
    pool = sorted({c.body["pref_label"] for c in concepts}) or ["term"]
    k = 0
    while sum(p["kind"] == "absent" for p in probes) < n_absent:
        h = _h(seed, "absent", k)
        term = f"{pool[h % len(pool)]} zq{k}"
        k += 1
        if base_key(term) in keys:
            continue
        probes.append({"kind": "absent", "term": term, "of": None,
                       "caller": callers[(h // len(pool)) % len(callers)], "context": None,
                       "filters": {}})
    scopes: dict[str, dict[str, set]] = {}
    first: dict[str, str] = {}
    for c in concepts:
        key = base_key(c.body["pref_label"])
        scopes.setdefault(key, {}).setdefault(c.body["scope"]["ref"], set()).add(c.doc_id)
        first.setdefault(key, c.body["pref_label"])
    for key in sorted(k for k, s in scopes.items() if len(s) > 1):
        term = first[key]
        for ref in [*sorted(scopes[key]), None]:
            docs = scopes[key][ref] if ref else set().union(*scopes[key].values())
            eligible = [u for u in callers if docs & ctx.visible(u)] or callers
            h = _h(seed, "scoped", key, ref)
            probes.append({"kind": "context" if ref else "no_context", "term": term, "of": None,
                           "caller": eligible[h % len(eligible)], "context": ref,
                           "filters": dict(WIDE)})
    by_doc: dict[str, list[Unit]] = {}
    for u in ctx.units.values():
        by_doc.setdefault(u.doc_id, []).append(u)
    for key in sorted(k for k, s in scopes.items() if len(s) > 1):
        term = first[key]
        for ref in sorted(scopes[key]):
            sense = next(c for c in concepts if base_key(c.body["pref_label"]) == key
                         and c.body["scope"]["ref"] == ref)
            others = [u for u in by_doc[sense.doc_id] if u.type != "concept"]
            contexts = [sense]
            if others:
                contexts.append(others[_h(seed, "unit-context", key, ref) % len(others)])
            for unit in contexts:
                eligible = [u for u in callers if unit.doc_id in ctx.visible(u)] or callers
                h = _h(seed, "unit-context", key, ref, unit.unit_id)
                probes.append({"kind": "unit_context", "term": term, "of": None,
                               "caller": eligible[h % len(eligible)], "context": unit.unit_id,
                               "filters": dict(WIDE), "context_type": unit.type})
    return probes


def define_probes(store_path: Path, n_absent: int = 50, seed: int = SEED4, *,
                  directory: Path = acl.DIRECTORY_PATH, policy: Path = acl.POLICY_PATH,
                  clock: Callable = acl.utc_now) -> list[dict]:
    """Run the `define` probes (module docstring); one row per probe: the senses returned, the
    expected count, senses of documents the caller cannot see, and `correct`."""
    ctx = unit_context(store_path)
    probes = define_terms(ctx, n_absent, seed)
    made: dict[str, Tools] = {}
    rows = []
    for i, p in enumerate(probes):
        if i % FRESH_EVERY == 0:
            tp.keep_fresh(store_path, directory, policy, clock)
        t = made.setdefault(p["caller"], Tools(store_path, acl=True, caller=p["caller"],
                                               clock=clock))
        args = {"term": p["term"], **p["filters"]}
        if p["context"] is not None:
            args["context"] = p["context"]
        out = run_unit_call(t, {"tool": "define", "args": args})
        seen = ctx.visible(p["caller"])
        allowed = ctx.admitted(seen, p["filters"])
        want = _expected_ids(ctx, p["term"], p["context"], allowed)
        senses = out[1].senses if out[0] == "ok" else []
        got = [s.unit_id for s in senses]
        ctx_unit = ctx.units[p["context"]] if p.get("context_type") else None
        correct = out[0] == "ok" and got == want and (ctx_unit is None
                                                      or ctx_unit.doc_id in allowed)
        if correct and not want:
            correct = out[1].nearest == _expected_nearest(ctx, p["term"], allowed)
        own = p["of"]
        rows.append({"probe_id": f"{p['kind']}:{i:05d}", "kind": p["kind"], "term": p["term"],
                     "caller": p["caller"], "context": p["context"] is not None,
                     "include_superseded": bool(p["filters"]),
                     "own_visible": None if own is None else ctx.units[own].doc_id in allowed,
                     "context_type": p.get("context_type"),
                     "context_visible": None if ctx_unit is None
                     else ctx_unit.doc_id in allowed,
                     "senses": len(got), "expected": len(want), "outcome": out[0],
                     "hidden_senses": sum(s.doc_id not in seen for s in senses),
                     "correct": correct})
    return rows


def summarize_define(rows: list[dict]) -> dict:
    kinds = sorted({r["kind"] for r in rows})
    return {"total": {"n": len(rows), "correct": sum(r["correct"] for r in rows),
                      "hidden_senses": sum(r["hidden_senses"] for r in rows),
                      "owner_hidden": sum(r["own_visible"] is False for r in rows),
                      "callers": len({r["caller"] for r in rows})},
            "by_kind": {k: {"n": sum(r["kind"] == k for r in rows),
                            "correct": sum(r["correct"] for r in rows if r["kind"] == k),
                            "with_senses": sum(bool(r["senses"]) for r in rows
                                               if r["kind"] == k),
                            "hidden_senses": sum(r["hidden_senses"] for r in rows
                                                 if r["kind"] == k)} for k in kinds},
            "unit_context_types": dict(sorted(Counter(
                r["context_type"] for r in rows if r["kind"] == "unit_context").items()))}


# -- censuses (U2, U3) -------------------------------------------------------------------------


def closure_census(store_path: Path) -> dict:
    """U2 (module docstring): the census of `units.closure.closure_census` over the stored
    rule cards with the re-read provisions of every eCFR version (`all`) and of the newest
    versions alone (`newest`, with its document count), whether `all` equals the build's
    report, and pass (both at least `U2_THRESHOLD`; every unresolved one listed)."""
    ctx = unit_context(store_path)
    cards = ctx.by_type.get("rule_card", [])
    provs = []
    for d in ecfr_docs(ctx.store):
        provs += rule_cards(ctx.store, d, ctx.overlay, ctx.corpus)[1]
    every = closure_mod.closure_census(cards, provs)
    newest_docs = {u.doc_id for u in cards if ctx.overlay is None
                   or ctx.overlay.records[u.doc_id].superseded_by is None}
    newest = closure_mod.closure_census([u for u in cards if u.doc_id in newest_docs],
                                        [p for p in provs if p.doc_id in newest_docs])
    newest["documents"] = len(newest_docs)
    report = unit_reports(store_path, ctx.units_id).get("rule_card", {})
    keys = ("cards", "in_part", "in_part_resolved", "resolution", "reasons", "unresolved")
    rates = [c["resolved_rate"] for c in (every, newest) if c["resolved_rate"] is not None]
    return {"all": every, "newest": newest, "threshold": U2_THRESHOLD,
            "matches_build_report": all(report.get(k) == every[k] for k in keys),
            "pass": bool(rates) and min(rates) >= U2_THRESHOLD}


def census_counts(c: dict) -> dict:
    """A closure census without its lists (counts only, for the committed summary)."""
    return {k: (len(v) if isinstance(v, list) else v) for k, v in c.items()}


def _skill_body_lines(text: str) -> int:
    lines = text.split("\n")
    end = lines.index("---", 1) if "---" in lines[1:] else 0
    return len(lines[end + 1:]) - (1 if text.endswith("\n") else 0)


def procedure_census(store_path: Path) -> dict:
    """U3 (module docstring): one row per procedure and the counts."""
    ctx = unit_context(store_path)
    rows, names = [], []
    for u in ctx.by_type.get("procedure", []):
        row = {"unit_id": u.unit_id, "valid_ir": False, "mermaid_round_trip": False,
               "skill_round_trip": False, "description_chars": None, "body_lines": None,
               "labels_ok": False, "stable": False, "name_chars": None}
        try:
            body = ProcedureBody.model_validate(u.body)
            row["valid_ir"] = validate_ir(body) == []
            mermaid = render_mermaid(body)
            row["mermaid_round_trip"] = parse_mermaid(mermaid) == ir_graph(body)
            labels = [m.group(1) if m.group(1) is not None else m.group(2)
                      for line in mermaid.split("\n") if (m := _NODE_LABEL.match(line))]
            row["labels_ok"] = len(labels) == len(body.steps) and all(
                len(x) <= LABEL_MAX for x in labels)
            skill = render_skill(u)
            meta, steps = parse_skill(skill)
            names.append(meta["name"])
            row["name_chars"] = len(meta["name"])
            row["description_chars"] = len(meta["description"])
            row["body_lines"] = _skill_body_lines(skill)
            row["skill_round_trip"] = steps == len(body.steps)
            row["stable"] = render_mermaid(body) == mermaid and render_skill(u) == skill
        except (ValueError, KeyError, TypeError):
            pass
        row["pass"] = (row["valid_ir"] and row["mermaid_round_trip"] and row["skill_round_trip"]
                       and row["labels_ok"] and row["stable"]
                       and row["description_chars"] is not None
                       and row["description_chars"] <= WHEN_TO_USE_MAX
                       and row["body_lines"] < SKILL_BODY_MAX_LINES
                       and row["name_chars"] <= NAME_MAX)
        rows.append(row)
    checks = ("valid_ir", "mermaid_round_trip", "skill_round_trip", "labels_ok", "stable")
    return {"n": len(rows), "passed": sum(r["pass"] for r in rows),
            "names_unique": len(set(names)) == len(names),
            "checks": {c: sum(bool(r[c]) for r in rows) for c in checks},
            "max_description_chars": max((r["description_chars"] or 0 for r in rows), default=0),
            "max_body_lines": max((r["body_lines"] or 0 for r in rows), default=0),
            "max_name_chars": max((r["name_chars"] or 0 for r in rows), default=0),
            "procedures": rows}


# -- the log scan (S2) -------------------------------------------------------------------------

SQL_ARGS = tp.SQL_ARGS
MIN_STATEMENT = tp.MIN_STATEMENT
AFTER_UNITS = (UNKNOWN_RULE, UNKNOWN_PROCEDURE)   # refusals made after the units were read


def _empty_scan(calls: int | None = None) -> dict:
    return {"lines": 0, "complete_lines": 0, "missing": dict.fromkeys(REQUIRED, 0),
            "unit_lines": 0, "units_missing": 0, "allowed": 0, "allowed_unresolved": 0,
            "text_lines": 0, "unit_calls": calls, "calls_mismatch": 0, "logs_missing": 0,
            "decisions": {}, "tools": {}}


def _complete(s: dict) -> bool:
    return (s["lines"] == s["complete_lines"] and s["units_missing"] == 0
            and s["allowed_unresolved"] == 0 and s["text_lines"] == 0
            and s["calls_mismatch"] == 0 and s["logs_missing"] == 0)


def scan_unit_log(path: Path, offset: int = 0, *, calls: int | None = None,
                  statements: Iterable[str] = ()) -> dict:
    """The log lines written after byte `offset` (module docstring): how many, how many lack
    each of `REQUIRED`, unit-tool lines without `units`, allowed lines with a null resolved
    field (or a null `units` on a unit-tool line that read units), and lines with a
    statement's text (or a `sql` line with other args or no `sql_sha256`). `calls`, when
    given, is the number of unit tool calls made on the store since `offset`
    (`unit_calls`): `calls_mismatch` is 1 when the unit-tool lines are not that many. A log
    that does not exist counts in `logs_missing` and is not complete."""
    texts = sorted({x for s in statements if len(s) >= MIN_STATEMENT
                    for x in (s, json.dumps(s, ensure_ascii=False)[1:-1])})
    out = _empty_scan(calls)
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read()
    except FileNotFoundError:
        out.update(logs_missing=1, calls_mismatch=int(bool(calls)))
        out["complete"] = _complete(out)
        return out
    decisions: Counter = Counter()
    tools: Counter = Counter()
    for line in data.decode("utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        tool = rec.get("tool")
        out["lines"] += 1
        lacking = [k for k in REQUIRED if k not in rec]
        out["complete_lines"] += not lacking
        for k in lacking:
            out["missing"][k] += 1
        unit_tool = tool in UNIT_TOOLS
        if unit_tool:
            out["unit_lines"] += 1
            out["units_missing"] += "units" not in rec
        if rec.get("acl_decision") == "allowed":
            out["allowed"] += 1
            error = rec.get("error")
            read = unit_tool and (error is None or error in AFTER_UNITS)
            need = RESOLVED + (("units",) if read else ())
            out["allowed_unresolved"] += any(rec.get(k) is None for k in need)
        bad = any(x in line for x in texts)
        if tool == "sql":
            args = rec.get("args")
            bad = bad or not isinstance(args, dict) or not set(args) <= SQL_ARGS \
                or "sql_sha256" not in rec
        out["text_lines"] += bad
        decisions[str(rec.get("acl_decision"))] += 1
        tools[str(tool)] += 1
    out["decisions"] = dict(sorted(decisions.items()))
    out["tools"] = dict(sorted(tools.items()))
    out["calls_mismatch"] = int(calls is not None and out["unit_lines"] != calls)
    out["complete"] = _complete(out)
    return out


def merge_unit_scans(a: dict | None, b: dict) -> dict:
    """Two scans added up; `unit_calls` is None unless both counted their calls."""
    if a is None:
        return b
    out = {k: a[k] + b[k] for k in ("lines", "complete_lines", "unit_lines", "units_missing",
                                    "allowed", "allowed_unresolved", "text_lines",
                                    "calls_mismatch", "logs_missing")}
    out["unit_calls"] = None if a["unit_calls"] is None or b["unit_calls"] is None \
        else a["unit_calls"] + b["unit_calls"]
    out["missing"] = {k: a["missing"][k] + b["missing"][k] for k in REQUIRED}
    out["decisions"] = dict(sorted((Counter(a["decisions"]) + Counter(b["decisions"])).items()))
    out["tools"] = dict(sorted((Counter(a["tools"]) + Counter(b["tools"])).items()))
    out["complete"] = _complete(out)
    return out


def total_unit_scan(scans: dict) -> dict:
    """The scans of several logs added up, with `complete`."""
    out = None
    for s in scans.values():
        out = merge_unit_scans(out, s)
    if out is None:                    # nothing scanned: nothing missing
        out = _empty_scan()
        out["complete"] = _complete(out)
    return out


# -- the MCP leg (D1) --------------------------------------------------------------------------

MCP_SUBSET = 60


def select_mcp(universe: list[tuple[str, Probe]], n: int = MCP_SUBSET,
               seed: int = SEED4) -> list[tuple[str, Probe]]:
    """The `n` probes of `universe` ((label, probe) pairs) with the lowest SHA-256 of
    `"<seed>:<label>/<probe_id>"`, in that order."""
    return mcp_probes.select(universe, n, seed)


class _Counting(mcp_probes.CountingTools):
    METHODS = UNIT_TOOLS


def run_mcp(selected: list[tuple[str, Probe]], *, contexts: dict,
            reference_for: Callable[[str, str], object],
            make_server: Callable[[str, str | None], object]
            ) -> tuple[list[tuple[str, ProbeResult]], list[dict], dict]:
    """Run the selected leak probes through MCP (module docstring): (one (label, result) per
    probe in `selected` order, one replay row per call that returned a result, the calls made
    through MCP per label and tool). One server per (label, caller), closed after its
    probes."""
    groups: dict[tuple[str, str | None], list[int]] = {}
    for i, (label, p) in enumerate(selected):
        groups.setdefault((label, p.caller), []).append(i)
    results: dict[int, ProbeResult] = {}
    replays: list[dict] = []
    calls: dict[str, Counter] = {}
    for (label, caller), idxs in sorted(groups.items(), key=lambda kv: (kv[0][0],
                                                                        str(kv[0][1]))):
        server = make_server(label, caller)
        counted = _Counting(server)
        try:
            for i in idxs:
                p = selected[i][1]
                results[i] = check_leak(p, counted, reference_for(label, caller),
                                        contexts[label])
                for j, call in enumerate(p.call["calls"]):
                    first = run_unit_call(counted, call)
                    if first[0] != "ok":
                        continue
                    handle = first[1].handle
                    again = run_unit_call(counted, {**call, "args": {**call["args"],
                                                                     "handle": handle}})
                    replays.append({"store": label, "probe_id": p.probe_id, "call": j,
                                    "tool": call["tool"],
                                    "handle_units": bool(handle and handle.get("units")),
                                    "identical": again[0] == "ok" and again[1] == first[1]})
        finally:
            close = getattr(server, "close", None)
            if close is not None:
                close()
        calls.setdefault(label, Counter()).update(counted.calls)
    return ([(selected[i][0], results[i]) for i in range(len(selected))], replays,
            {k: dict(sorted(v.items())) for k, v in sorted(calls.items())})


def summarize_mcp(results: list[tuple[str, ProbeResult]], replays: list[dict]) -> dict:
    out = summarize_leaks([r for _, r in results])
    out["stores"] = {label: {"n": sum(lb == label for lb, _ in results),
                             "leaks": sum(r.leak for lb, r in results if lb == label),
                             "invalid": sum(not r.valid for lb, r in results if lb == label)}
                     for label in sorted({lb for lb, _ in results})}
    out["replays"] = {"n": len(replays), "identical": sum(r["identical"] for r in replays),
                      "handle_units": sum(r["handle_units"] for r in replays)}
    return out
