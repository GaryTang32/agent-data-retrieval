r"""Table probes (Phase 3 spec §10.4, criteria S1, S2, S3 and the MCP leg of D1) for the three
table tools `describe_tables`, `query_table` and `sql`; deterministic (seed `SEED3`), no model
calls, run through `adr_store.tools.Tools` with the ACL layer, as the Phase 2 probes of
`adr_eval.probes.acl` are.

**Reference stores** (`References`). A view's reference store is the Phase 2 one
(`equivalence.ensure_view_store`: the view's documents alone, re-ingested, its own overlays,
index and ACL sync from the same directory and policy) with its tables built (`build_tables`)
and promoted (`gate(..., [], 0)`), built or reused under a root directory at `<view[:12]>`.
When the store's tables hold the extraction (3B) tables, the reference's do too: built with
`with_extraction=True` from the cached first-pass replies of the generator profile (default: the
configured generator) with `max_calls=0`. The cache key covers adapter, model, prompt, section
text and token cap, not the store, so a reference that holds a subset of the documents hits the
same replies for the sections it has; a reply not cached stops the run (BudgetExceeded, ruling
P21) and extraction tables recorded as coming from anything else than the store's are refused. A
store whose corpus has no tables (bench, the tools store) gets a bare reference: the view's
documents re-ingested and the ACL synced, nothing else (a table tool refuses on both before it
reads anything an index or overlay would give).

**Leak probes** (`leak_probes`, §10.4, S1). Each probe is a (caller, hidden document) pair drawn
by seeded hash, with a hidden row of that document and one of its values. Callers are the
directory users with such a row, so every probe is compared with a reference store;
`user:ghost` (who must be denied F4) only when no directory user has one (research: the
manifest, the only document with rows, is public). For probe `k` of a family: the caller, then
a (table, column) of the family, then a row of a document the caller cannot see whose value in
that column only such documents hold (never a document the caller sees); a (caller, document,
table, column, value) already taken draws again. Values are scalar cells (text, int, date) of
at most 1,000 characters. Every call reads with `include_superseded` (nothing masked by
applicability). Families:

- `by-key`: `query_table(table, {key: v}, "lookup")` on a table's first key column;
- `by-filter`: `query_table(table, {column: v}, "count")`;
- `by-aggregate`: `sql`, in turn `count(*)`, `sum(length(column))` and `group_concat(column)`
  over the rows where the column equals `v`;
- `by-group`: `query_table(table, op="count_by", fields=[column])`;
- `by-error`: three calls that mention `v`: `query_table` with an unknown column named `v`, a
  `sql` statement naming an unknown column `WHERE column = v` (it always fails), and
  `SELECT json_extract('x' || column, '$') … WHERE column = v`, which fails only where a row
  holding `v` is present.

**Leak kinds** (`check_leak`), each True (a leak), False (checked, none) or None (does not apply),
judged against the same calls as the same caller on the caller's reference store:

- `id_outside_view`: a document id the caller cannot see in a result (64 hex characters that
  are a document of the store) or in a refusal (12 or more hex characters beginning one);
- `hidden_value`: the probe's value in a result (the caller's own arguments left out) or a
  refusal where the reference's has none;
- `count_differs`: a count, the number of ids, rows or groups, `truncated` or
  `excluded_by_filter` differ;
- `rows_differ`: the results differ (store-specific fields — snapshot, tables id, applicability
  overlay, handle — left out);
- `error_differs`: one side refused and the other did not, or the refusals differ (snapshot ids
  replaced).

`user:ghost` must be denied F4 on every call with no content; any other denial makes the probe
invalid (reported, not a pass).

**SQL guard** (`sql_guard`, S2): `SQL_GUARD_CASES`, 120 statements in ten categories, `{t}` the
corpus's main table (`fr_documents`, `papers`; both have `id`, `title` and `year`), run as one
caller through one `Tools` instance. A case of a category in `MUST_REFUSE` passes when it is
refused with one of the guard's four fixed messages (or, for the statements in `HARMLESS`, also
when it returns a bounded result); `recursive` and `cross_join` cases pass when refused so or
bounded: at most `SQL_ROW_CAP` rows, at most 2 MB of canonical JSON, every number finite. Every
case must also leave the database intact: the row count of every table, the schema and
`query_only` as before.

**Equivalence** (`equivalence`, S1): for each view, `n_queries` (25) calls as the view's caller
on the store and on its reference store, compared as for the leak kinds: 15 `query_table` calls
drawn by seeded hash from the corpus's v0.1 `count_filter` gold queries (`gate.gold_cases`) and
`count_by` on the categorical columns (`CATEGORICAL`), and the corpus's ten fixed `sql`
statements (`EQUIVALENCE_SQL`); each with the default applicability filters or
`include_superseded`, by seeded hash. A corpus without tables (bench, tools): each table tool
must give the same `NO_TABLES` refusal on the store and on the reference, once per view; those
rows are not counted.

**Fail closed** (`failclosed`, S3): F1–F5 and "no entry" × the three tools × 5 callers = 90,
with the callers, variants and clone machinery of the Phase 2 probes (`acl.failclosed_callers`,
`_F1`, `_cp`; clones removed). The target is a document with rows in the main table, not in a
chain, whose uri begins no other document's, that every one of the five directory callers sees
and finds (by seeded hash order): before any change each of them gets its row from the
`query_table` lookup and the `sql` select. Calls: `describe_tables(main)`, the lookup of the
target's key and `SELECT _doc_id, key … WHERE key = v`. Pass: F1–F5 refuse with that code and
show nothing of the target; "no entry" (an attribute rule mapping the target's uri to `[]`,
which must change that document's access alone) gives the same result as a call naming a key
no row holds, and `describe_tables` names nothing of the target.

**Applicability** (`applicability_probes`): per table (`fr_documents`, and the drawbridge
tables `drawbridge_sections` and `drawbridge_bridges` once they exist), the default filters and
`n` (50) `as_of` dates drawn by seeded hash from the `fr_documents` publication dates (cycled
when there are fewer), as `user:auditor`; for a table with rows of versioned documents (the
drawbridge tables: the eCFR chain) each version's first day in force and the day before it
come first (`applicability_dates`). Every document returned (by the lookup and by
`SELECT _doc_id, count(*) … GROUP BY _doc_id`) must be one the filters admit
(`applicability.admits`) among the caller's view, the counts must equal the rows of the
admitted documents, and at most one version of a chain may be returned (the version in force).

**Log scan** (`scan_table_log`, S3, B5 for tables): every line has `REQUIRED`; every line of a
table tool has the key `tables`; an allowed line has a non-null `RESOLVED` and, for a table tool,
a non-null `tables` unless it was refused before reading any (`NO_TABLES`, a handle refusal); a
`sql` line has `sql_sha256` and args `statement_sha256`, `applicability` (and `handle`) only;
and no line holds the text of a statement given (16 characters or more).

**MCP** (`select_mcp`, `run_mcp`, D1): the `n` (60) leak probes with the lowest SHA-256 of
`"<seed>:<label>/<probe_id>"`, each run through an `adr mcp` server of its caller and judged
as above against the Python API's reference store; every result is replayed with its handle
through the same server (identical, and its handle names the tables).

Run summaries carry counts only; per-item rows go to `results.json` under `runs/`. This module
may import `adr_store` directly (plan, shared rules).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from adr_eval.probes import acl as acl_probes
from adr_eval.probes import equivalence as eq
from adr_eval.probes import mcp as mcp_probes
from adr_eval.probes.acl import (
    _F1,
    AHEAD,
    CONDITIONS,
    F1_VARIANTS,
    F3_VARIANTS,
    F4_CALLERS,
    F5_CALLERS,
    GHOST,
    REQUIRED,
    RESOLVED,
    STALE,
    Probe,
    ProbeResult,
    _cp,
    _no_entry_policy,
    log_path,
    log_size,
)
from adr_store import acl, handles
from adr_store import applicability as ap
from adr_store.applicability import chain_of
from adr_store.store import Store
from adr_store.tables.build import build_tables
from adr_store.tables.contracts import Contract
from adr_store.tables.engine import (
    DEFAULT_TABLE,
    QUERY_LIMIT_MAX,
    contracts_of,
)
from adr_store.tables.gate import gate, gold_cases
from adr_store.tables.overlay import Manifest, load_manifest, load_rows
from adr_store.tables.provenance import RowRecord
from adr_store.tables.sqlguard import (
    ERR_BUDGET,
    ERR_DENIED,
    ERR_ROWS,
    ERR_SYNTAX,
    SQL_MAX_BYTES,
    SQL_ROW_CAP,
)
from adr_store.tools import DEFAULT_EMB_CACHE, NO_HANDLE_TABLES, AccessDenied, ToolError, Tools

SEED3 = 20261120
LEAK_SIZES = {"gov": {"by-key": 100, "by-filter": 80, "by-aggregate": 60, "by-group": 40,
                      "by-error": 20},
              "research": {"by-key": 20, "by-filter": 20, "by-aggregate": 20, "by-group": 20,
                           "by-error": 20}}
LEAK_KINDS = ("id_outside_view", "hidden_value", "count_differs", "rows_differ",
              "error_differs")
TABLE_TOOLS = ("describe_tables", "query_table", "sql")
TABLE_CORPORA = ("gov", "research")   # the corpora with tables; bench and tools have none
WIDE = {"include_superseded": True}
SCALAR = ("text", "int", "date")
MAX_VALUE_CHARS = 1000
STORE_SPECIFIC = ("snapshot", "tables", "applicability", "handle")
ECHO = ("table", "op", "filters", "fields", "order", "limit", "statement_sha256")
FIXED = {ERR_SYNTAX: "syntax", ERR_DENIED: "denied", ERR_BUDGET: "budget", ERR_ROWS: "rows"}
FRESH_MARGIN = timedelta(minutes=15)   # re-sync a store whose ACL is this close to stale
_SNAP = re.compile(r"\b[0-9a-f]{12}…")
_HEX = re.compile(r"[0-9a-f]{12,}")
_DOC = re.compile(r"[0-9a-f]{64}")


def _h(*parts: object) -> int:
    return int(hashlib.sha256(":".join(str(p) for p in parts).encode("utf-8")).hexdigest(), 16)


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sql_literal(v: object) -> str:
    """`v` as an SQL literal: an integer as digits, anything else a quoted string."""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def _json(data: object) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)


# -- the store as the probes see it ------------------------------------------------------------


@dataclass
class TableContext:
    """The store, its ACL snapshot and its current tables (the operator's view, used to build
    probes and judge results; never shown to a caller). `tables_id` is None for a store
    without current tables (bench, the tools store)."""

    store_path: Path
    store: Store
    snap: acl.AclSnapshot
    tables_id: str | None
    manifest: Manifest | None
    contracts: dict[str, Contract]
    rows: dict[str, list[RowRecord]]
    _visible: dict = field(default_factory=dict)
    _holders: dict = field(default_factory=dict)
    _hidden: dict = field(default_factory=dict)
    _docs: dict = field(default_factory=dict)

    @property
    def corpus(self) -> str | None:
        return None if self.manifest is None else self.manifest.corpus

    @property
    def doc_ids(self) -> frozenset[str]:
        return frozenset(self.store.doc_ids())

    def visible(self, caller: str | None) -> frozenset[str]:
        if caller not in self._visible:
            ps = frozenset(self.snap.directory.get(caller, ())) if isinstance(caller, str) \
                else frozenset()
            self._visible[caller] = frozenset(
                d for d, v in self.snap.docs.items() if not ps.isdisjoint(v))
        return self._visible[caller]

    def callers(self) -> list[str]:
        return [*sorted(self.snap.directory), GHOST]

    def scalar_columns(self, table: str) -> list[str]:
        return [c.name for c in self.contracts[table].columns
                if c.computed is None and c.type in SCALAR]

    def docs_of(self, table: str) -> frozenset[str]:
        if table not in self._docs:
            self._docs[table] = frozenset(r.doc_id for r in self.rows[table])
        return self._docs[table]

    def holders(self, table: str, column: str) -> dict:
        """value -> the documents whose rows hold it in that column."""
        key = (table, column)
        if key not in self._holders:
            out: dict = {}
            for r in self.rows[table]:
                v = r.row.get(column)
                if _probe_value(v):
                    out.setdefault(v, set()).add(r.doc_id)
            self._holders[key] = out
        return self._holders[key]

    def hidden_values(self, caller: str | None, table: str, column: str) -> list[tuple]:
        """(row index, value) of the rows of documents `caller` cannot see whose value in the
        column no document the caller sees holds, in row order."""
        key = (caller, table, column)
        if key not in self._hidden:
            seen = self.visible(caller)
            if self.docs_of(table) <= seen:
                self._hidden[key] = []
                return []
            held = self.holders(table, column)
            self._hidden[key] = [(i, r.row[column]) for i, r in enumerate(self.rows[table])
                                 if r.doc_id not in seen and _probe_value(r.row.get(column))
                                 and held[r.row[column]].isdisjoint(seen)]
        return self._hidden[key]


def _probe_value(v: object) -> bool:
    if isinstance(v, bool) or v is None:
        return False
    if isinstance(v, int):
        return True
    return isinstance(v, str) and 0 < len(v) <= MAX_VALUE_CHARS and "\x00" not in v


def table_context(store_path: Path) -> TableContext:
    """The probes' view of the store at `store_path`: its HEAD snapshot, ACL snapshot and the
    tables `tables/HEAD` names for that snapshot (none: no tables)."""
    store = Store.open(store_path)
    snap = acl.read_head(store_path)[1]
    tables_id = handles.tables_head(store_path, store.snapshot_id)
    if tables_id is None:
        return TableContext(Path(store_path), store, snap, None, None, {}, {})
    m = load_manifest(store_path, tables_id)
    contracts = contracts_of(m, tables_id)
    rows = {t: load_rows(store_path, m, t) for t in contracts}
    return TableContext(Path(store_path), store, snap, tables_id, m, contracts, rows)


def keep_fresh(store_path: Path, directory: Path, policy: Path, clock: Callable,
               margin: timedelta = FRESH_MARGIN) -> bool:
    """Re-sync the store's ACL when its snapshot is within `margin` of the freshness limit
    (or past it, or not for HEAD), so a long run is never denied F3 midway. True if synced."""
    store = Store.open(store_path)
    try:
        snap = acl.read_head(store_path)[1]
        age = clock() - snap.synced_at
        fresh = (snap.content_snapshot == store.snapshot_id
                 and age <= timedelta(seconds=snap.max_sync_age_s) - margin
                 and -age <= timedelta(seconds=snap.future_skew_s))
    except acl.AclDenied:
        fresh = False
    if not fresh:
        acl.sync(store_path, directory, policy, clock=clock)
    return not fresh


# -- reference stores --------------------------------------------------------------------------


def bare_reference(src: Store, doc_ids: Iterable[str], dst: Path, *, directory: Path,
                   policy: Path, clock: Callable) -> tuple[Store, str]:
    """(a store of `doc_ids` alone with its ACL synced, "built" | "reused"): the reference of
    a store without tables (no overlay, index or tables)."""
    from adr_eval.corpora.base import Document

    dst = Path(dst)
    docs = sorted(set(doc_ids))
    if (dst / "HEAD").exists():
        store = Store.open(dst)
        if store.doc_ids() != docs:
            raise ValueError(f"{dst}: holds another view than asked; remove it")
        keep_fresh(dst, directory, policy, clock)
        return store, "reused"
    store = Store.create(dst)
    for d in docs:
        source = src.source(d)
        raw = (src.path / "blobs" / d[:2] / d).read_bytes()
        store.add(Document(d, src.text(d), source.format, source.source_version, source.uri),
                  raw, source.license)
    store.commit()
    acl.sync(dst, directory, policy, clock=clock)
    return Store.open(dst), "built"


class References:
    """The reference store of each view of `ctx`'s ACL snapshot, built or reused under `root`
    on first use (module docstring); `path_for(caller)` is the caller's (None outside the
    directory). `info` records what each holds. `generator` names the model profile whose
    cached replies give the extraction tables (None: the configured generator); a store
    without extraction tables resolves none."""

    def __init__(self, ctx: TableContext, root: Path, *, directory: Path = acl.DIRECTORY_PATH,
                 policy: Path = acl.POLICY_PATH, emb_cache: Path = DEFAULT_EMB_CACHE,
                 clock: Callable = acl.utc_now, generator: str | None = None):
        self.ctx, self.root = ctx, Path(root)
        self.directory, self.policy, self.emb_cache, self.clock = \
            directory, policy, emb_cache, clock
        self.generator = generator   # the extraction's model profile (None: the configured)
        self.views = eq.views(ctx.snap)
        self._view_of = {u: v for v in self.views for u in v.users}
        self._paths: dict[str, Path] = {}
        self.offsets: dict[Path, int] = {}
        self.info: list[dict] = []

    def path_for(self, caller: str | None) -> Path | None:
        v = self._view_of.get(caller) if isinstance(caller, str) else None
        return None if v is None else self.path_of(v)

    def path_of(self, v: eq.View) -> Path:
        if v.view in self._paths:   # a long run: keep the reference's ACL fresh too
            keep_fresh(self._paths[v.view], self.directory, self.policy, self.clock)
            return self._paths[v.view]
        path = self.root / v.view[:12]
        if self.ctx.tables_id is None:
            _, how = bare_reference(self.ctx.store, v.docs, path, directory=self.directory,
                                    policy=self.policy, clock=self.clock)
        else:
            store, how = eq.ensure_view_store(self.ctx.store, v.docs, path,
                                              emb_cache=self.emb_cache,
                                              directory=self.directory, policy=self.policy,
                                              clock=self.clock)
            want = self.ctx.manifest.extraction
            head = handles.tables_head(path, store.snapshot_id)
            if head is None or load_manifest(path, head).extraction != want:
                tables_id = self._build_tables(path, want)
                if not gate(path, tables_id, [], 0).promoted:
                    raise ValueError(f"{path}: the reference tables were not promoted")
                how += ", tables built" + ("" if want is None
                                           else " with extraction from the cache")
        self._paths[v.view] = path
        self.offsets[path] = log_size(log_path(path))   # where this run's log lines begin
        self.info.append({**v.summary(), "path": path.name, "how": how,
                          "tables": handles.tables_head(path, Store.open(path).snapshot_id)})
        return path

    def _build_tables(self, path: Path, want: dict | None) -> str:
        """The reference's tables id: the metadata and entity tables, and when the store's
        tables hold extraction tables (`want`: their manifest entry) those too, from the
        cached first-pass replies of `self.generator` with a budget of zero calls (a reply
        not cached stops the run, BudgetExceeded, ruling P21). Extraction tables that would
        come from anything else than the store's (another adapter, model, prompt or specs)
        are refused (ValueError)."""
        if want is None:
            return build_tables(path, self.ctx.corpus).tables_id
        tables_id = build_tables(path, self.ctx.corpus, with_extraction=True,
                                 generator_profile=self.generator, max_calls=0).tables_id
        got = load_manifest(path, tables_id).extraction
        if got != want:
            diff = sorted(k for k in {*want, *got} if want.get(k) != got.get(k))
            raise ValueError(f"{path}: the reference's extraction tables differ from the "
                             f"store's in {', '.join(diff)} (pass the generator profile the "
                             f"store's extraction used)")
        return tables_id

    def log_scans(self, statements: Iterable[str] = ()) -> dict:
        """`scan_table_log` of each reference store's log since it was first used here."""
        return {p.name: scan_table_log(log_path(p), off, statements)
                for p, off in sorted(self.offsets.items())}

    def remove(self) -> list[str]:
        """Remove the reference store of every view under `root`, used in this run or kept
        by an earlier one (and `root`, once empty)."""
        paths = sorted(p for p in {self.root / v.view[:12] for v in self.views} if p.is_dir())
        removed = [str(p) for p in paths]
        for p in paths:
            shutil.rmtree(p, ignore_errors=True)
        if self.root.is_dir() and not any(self.root.iterdir()):
            self.root.rmdir()
        self._paths.clear()
        return removed


# -- calls and outcomes ------------------------------------------------------------------------


def run_table_call(t, call: dict) -> tuple:
    """("ok", result) | ("denied", code, message) | ("refused", message): one table tool call
    `{"tool": …, "args": {…}}` on `t` (a `Tools` or an MCP client of the same shape)."""
    if call["tool"] not in TABLE_TOOLS:
        raise ValueError(f"unknown table tool {call['tool']!r}")
    try:
        res = getattr(t, call["tool"])(**call["args"])
    except AccessDenied as e:
        return ("denied", e.code, str(e))
    except ToolError as e:
        return ("refused", str(e))
    return ("ok", res)


def _stripped(res) -> dict:
    return {k: v for k, v in res.to_dict().items() if k not in STORE_SPECIFIC}


def outcome_key(out: tuple) -> tuple:
    """What two stores' answers are compared by: the result without store-specific fields, or
    the refusal with snapshot ids replaced."""
    if out[0] == "ok":
        return ("ok", _json(_stripped(out[1])))
    if out[0] == "refused":
        return ("refused", _SNAP.sub("<id>…", out[1]))
    return ("denied", out[1], _SNAP.sub("<id>…", out[2]))


def _counts(out: tuple) -> tuple | None:
    if out[0] != "ok":
        return None
    d = out[1].to_dict()
    if "op" in d:   # query_table
        return (d["count"], None if d["ids"] is None else len(d["ids"]),
                None if d["rows"] is None else len(d["rows"]),
                None if d["groups"] is None else len(d["groups"]), d["truncated"],
                d["excluded_by_filter"])
    if "columns" in d:   # sql
        return (len(d["rows"]), d["truncated"], d["excluded_by_filter"])
    return ()


def _payload(out: tuple) -> str:
    """The text a caller learns from an outcome, without the caller's own arguments."""
    if out[0] == "ok":
        return _json({k: v for k, v in _stripped(out[1]).items() if k not in ECHO})
    return out[-1]


def _first_difference(a: tuple, b: tuple) -> str:
    """Where two outcome keys differ, without their contents (no corpus text in summaries)."""
    if a[0] != b[0]:
        return f"{a[0]} vs {b[0]}"
    if a[0] != "ok":
        return "different refusals"
    da, db = json.loads(a[1]), json.loads(b[1])
    return "fields " + ", ".join(sorted(k for k in set(da) | set(db) if da.get(k) != db.get(k)))


# -- leak probes -------------------------------------------------------------------------------


def _family_columns(ctx: TableContext, family: str) -> list[tuple[str, str]]:
    out = []
    for t in sorted(ctx.contracts):
        if family == "by-key":
            key = ctx.contracts[t].key[0]
            if key in ctx.scalar_columns(t):
                out.append((t, key))
        else:
            out += [(t, c) for c in ctx.scalar_columns(t)]
    return out


def _draw(ctx: TableContext, seed: int, family: str, k: int, taken: set, columns: list,
          callers: list) -> tuple:
    for salt in range(10_000):
        caller = callers[_h(seed, family, k, salt, "caller") % len(callers)]
        cols = [(t, col) for t, col in columns if ctx.hidden_values(caller, t, col)]
        t, col = cols[_h(seed, family, k, salt, "column") % len(cols)]
        cands = ctx.hidden_values(caller, t, col)
        i, v = cands[_h(seed, family, k, salt, "row") % len(cands)]
        doc = ctx.rows[t][i].doc_id
        if (caller, doc, t, col, v) in taken:
            continue
        taken.add((caller, doc, t, col, v))
        return caller, t, col, i, v
    raise ValueError(f"{family}: no untaken (caller, document) pair for probe {k}")


def _leak_calls(family: str, k: int, t: str, col: str, v: object) -> list[dict]:
    lit, qt, qc = sql_literal(v), _q(t), _q(col)
    where = f"WHERE {qc} = {lit}"
    if family == "by-key":
        return [{"tool": "query_table", "args": {"table": t, "filters": {col: v},
                                                 "op": "lookup", "applicability": WIDE}}]
    if family == "by-filter":
        return [{"tool": "query_table", "args": {"table": t, "filters": {col: v},
                                                 "op": "count", "applicability": WIDE}}]
    if family == "by-aggregate":
        agg = ("count(*)", f"sum(length({qc}))", f"group_concat({qc})")[k % 3]
        return [{"tool": "sql", "args": {"statement": f"SELECT {agg} FROM {qt} {where}",
                                         "applicability": WIDE}}]
    if family == "by-group":
        return [{"tool": "query_table", "args": {"table": t, "op": "count_by",
                                                 "fields": [col], "applicability": WIDE}}]
    if family == "by-error":
        return [{"tool": "query_table", "args": {"table": t, "filters": {str(v): v},
                                                 "op": "count", "applicability": WIDE}},
                {"tool": "sql", "args": {"statement": f"SELECT no_such_column FROM {qt} {where}",
                                         "applicability": WIDE}},
                {"tool": "sql", "args": {
                    "statement": f"SELECT json_extract('x' || {qc}, '$') FROM {qt} {where}",
                    "applicability": WIDE}}]
    raise ValueError(f"unknown leak family {family!r}")


def leak_probes(store_path: Path, corpus: str, seed: int = SEED3,
                sizes: dict | None = None) -> list[Probe]:
    """The leak probes of the store's current tables (module docstring), in family order."""
    ctx = table_context(store_path)
    if ctx.tables_id is None or ctx.corpus != corpus:
        raise ValueError(f"{store_path}: no current tables of {corpus}")
    sizes = {**LEAK_SIZES[corpus], **(sizes or {})}
    probes = []
    for family in LEAK_SIZES[corpus]:
        taken: set = set()
        columns = _family_columns(ctx, family)
        # directory users with a hidden row, so each probe is compared with a reference store;
        # `user:ghost` (denied F4) only when no user has one (the research manifest is public)
        callers = [c for c in sorted(ctx.snap.directory)
                   if any(ctx.hidden_values(c, t, col) for t, col in columns)]
        if not callers and any(ctx.hidden_values(GHOST, t, col) for t, col in columns):
            callers = [GHOST]
        if not callers and sizes[family]:
            raise ValueError(f"{family}: no caller has a hidden row with a probe value")
        for k in range(sizes[family]):
            caller, t, col, i, v = _draw(ctx, seed, family, k, taken, columns, callers)
            calls = _leak_calls(family, k, t, col, v)
            tools_used = ",".join(dict.fromkeys(c["tool"] for c in calls))
            probes.append(Probe(
                f"{family}:{k:03d}", family, tools_used, caller,
                {"doc_id": ctx.rows[t][i].doc_id, "table": t, "column": col, "row": i,
                 "value": v, "secret": str(v), "in_directory": caller in ctx.snap.directory},
                {"calls": calls}))
    return probes


def _hidden_ids(text: str, ctx: TableContext | None, caller, target: str,
                prefixes: bool) -> set[str]:
    """The documents the caller cannot see that `text` names: by full id (64 hex characters),
    or with `prefixes` (a refusal) also by 12 or more hex characters beginning one; without
    `ctx` only the target is looked for."""
    found = {target} if target in text or (prefixes and target[:12] in text) else set()
    if ctx is None:
        return found
    seen, docs = ctx.visible(caller), ctx.doc_ids
    found |= {d for d in _DOC.findall(text) if d in docs and d not in seen}
    if prefixes:
        found |= {d for tok in _HEX.findall(text) for d in docs
                  if d.startswith(tok[:64]) and d not in seen}
    return found


def check_leak(probe: Probe, tools_for: Callable, reference_for: Callable, *,
               ctx: TableContext | None = None) -> ProbeResult:
    """Run one leak probe as its caller (`tools_for(caller)`) and judge the five kinds (module
    docstring) against the same calls on the caller's reference (`reference_for(caller)`, None
    for a caller outside the directory). With `ctx`, every document id shown is checked
    against the caller's view; without it, the target's."""
    caller, target = probe.caller, probe.target
    calls = probe.call["calls"]
    mine = [run_table_call(tools_for(caller), c) for c in calls]
    kinds: dict = dict.fromkeys(LEAK_KINDS)
    outcome = ",".join(o[0] if o[0] != "denied" else f"denied:{o[1]}" for o in mine)
    secret, doc = target["secret"], target["doc_id"]
    if any(o[0] == "denied" for o in mine):
        given = _json(calls)   # what the caller named itself is no leak
        msgs = [o[-1] for o in mine if o[0] != "ok"]
        kinds["hidden_value"] = any(secret in m and secret not in given for m in msgs)
        kinds["id_outside_view"] = any(
            d not in given for m in msgs for d in _hidden_ids(m, ctx, caller, doc, True))
        valid = not target["in_directory"] and all(o[0] == "denied" and o[1] == "F4"
                                                   for o in mine)
        return ProbeResult(probe.probe_id, probe.family, probe.tool, caller, outcome, kinds,
                           any(bool(v) for v in kinds.values()), valid,
                           None if valid else f"unexpected outcome {outcome}")
    ref = reference_for(caller)
    if not target["in_directory"] or ref is None:
        return ProbeResult(probe.probe_id, probe.family, probe.tool, caller, outcome, kinds,
                           False, False, f"{caller} was not denied" if not
                           target["in_directory"] else "no reference store")
    theirs = [run_table_call(ref, c) for c in calls]
    for k in LEAK_KINDS:
        kinds[k] = False
    for a, b in zip(mine, theirs, strict=True):
        pa, pb = _payload(a), _payload(b)
        kinds["id_outside_view"] |= bool(_hidden_ids(pa, ctx, caller, doc, a[0] != "ok")
                                         - _hidden_ids(pb, ctx, caller, doc, b[0] != "ok"))
        kinds["hidden_value"] |= secret in pa and secret not in pb
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
              emb_cache: Path = DEFAULT_EMB_CACHE, clock: Callable = acl.utc_now,
              refs: References | None = None, generator: str | None = None
              ) -> list[ProbeResult]:
    """Run the leak probes, one caller's `Tools` at a time, against the reference stores
    under `views_root` (built or reused on first use; `refs` to share them), in probe order.
    The store's ACL is re-synced when it nears its freshness limit."""
    ctx = table_context(store_path)
    refs = refs or References(ctx, views_root, directory=directory, policy=policy,
                              emb_cache=emb_cache, clock=clock, generator=generator)
    out: dict[str, ProbeResult] = {}
    for caller in sorted({p.caller for p in probes}, key=str):
        ref_path = refs.path_for(caller)
        keep_fresh(store_path, directory, policy, clock)
        mine = Tools(store_path, emb_cache=emb_cache, acl=True, caller=caller, clock=clock)
        ref = None if ref_path is None else Tools(ref_path, emb_cache=emb_cache, acl=True,
                                                  caller=caller, clock=clock)
        for p in probes:
            if p.caller == caller:
                out[p.probe_id] = check_leak(p, lambda c, m=mine: m, lambda c, r=ref: r,
                                             ctx=ctx)
    return [out[p.probe_id] for p in probes]


def summarize_leaks(results: list[ProbeResult]) -> dict:
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
            b["checked_kinds"][k] += v is not None
            b["leak_kinds"][k] += bool(v)
    families = {name: {"n": b["n"], "leaks": b["leaks"], "invalid": b["invalid"],
                       "outcomes": dict(sorted(b["outcomes"].items())),
                       "callers": len(b["callers"]), "ghost": GHOST in b["callers"],
                       "leak_kinds": {k: b["leak_kinds"][k] for k in LEAK_KINDS},
                       "checked_kinds": {k: b["checked_kinds"][k] for k in LEAK_KINDS}}
                for name, b in fams.items()}
    total = {"n": len(results), "leaks": sum(r.leak for r in results),
             "invalid": sum(not r.valid for r in results),
             "ghost": sum(r.caller == GHOST for r in results),
             "compared": sum(r.kinds["rows_differ"] is not None for r in results),
             "leak_kinds": {k: sum(bool(r.kinds[k]) for r in results) for k in LEAK_KINDS},
             "checked_kinds": {k: sum(r.kinds[k] is not None for r in results)
                               for k in LEAK_KINDS}}
    return {"families": families, "total": total}


# -- the SQL guard (S2) ------------------------------------------------------------------------

_BIG = "replace(printf('%16000d', 1), ' ', 'a')"
_J4 = ", {t} a, {t} b, {t} c, {t} d"
_CASE_D = "CASE WHEN d.id IS NULL THEN '' ELSE {} END"
SQL_GUARD_CASES: tuple[tuple[str, str], ...] = (
    # writes
    ("write", "DELETE FROM {t}"),
    ("write", "DELETE FROM {t} WHERE id = 'x'"),
    ("write", "UPDATE {t} SET title = 'x'"),
    ("write", "UPDATE {t} SET year = year + 1 WHERE 1"),
    ("write", "INSERT INTO {t} (id) VALUES ('x')"),
    ("write", "INSERT INTO {t} SELECT * FROM {t}"),
    ("write", "INSERT OR REPLACE INTO {t} (id) VALUES ('x')"),
    ("write", "REPLACE INTO {t} (id) VALUES ('x')"),
    ("write", "WITH x AS (SELECT 1) DELETE FROM {t}"),
    ("write", "WITH x AS (SELECT 1) UPDATE {t} SET title = NULL"),
    ("write", "INSERT INTO {t} DEFAULT VALUES"),
    ("write", "UPDATE OR IGNORE {t} SET id = 'x'"),
    ("write", "DELETE FROM {t} RETURNING *"),
    ("write", "INSERT INTO {t} (id) VALUES ('x') RETURNING id"),
    ("write", "UPDATE {t} SET title = (SELECT 1) RETURNING title"),
    # DDL, transactions and maintenance
    ("ddl", "DROP TABLE {t}"),
    ("ddl", "DROP TABLE IF EXISTS {t}"),
    ("ddl", "CREATE TABLE x (a)"),
    ("ddl", "CREATE TABLE x AS SELECT * FROM {t}"),
    ("ddl", "CREATE TEMP TABLE x (a)"),
    ("ddl", "CREATE TEMPORARY VIEW v AS SELECT * FROM {t}"),
    ("ddl", "CREATE VIEW v AS SELECT 1"),
    ("ddl", "CREATE INDEX i ON {t} (id)"),
    ("ddl", "CREATE TRIGGER tr AFTER INSERT ON {t} BEGIN SELECT 1; END"),
    ("ddl", "ALTER TABLE {t} ADD COLUMN z"),
    ("ddl", "ALTER TABLE {t} RENAME TO y"),
    ("ddl", "CREATE VIRTUAL TABLE x USING json_each"),
    ("ddl", "BEGIN IMMEDIATE"),
    ("ddl", "SAVEPOINT s"),
    ("ddl", "VACUUM"),
    # ATTACH
    ("attach", "ATTACH DATABASE ':memory:' AS other"),
    ("attach", "ATTACH ':memory:' AS m"),
    ("attach", "ATTACH 'probe-attach.db' AS p"),
    ("attach", "ATTACH 'file:probe?mode=memory&cache=shared' AS p"),
    ("attach", "ATTACH DATABASE '' AS t2"),
    ("attach", "DETACH DATABASE main"),
    # PRAGMA, as statements and as table-valued functions
    ("pragma", "PRAGMA query_only = OFF"),
    ("pragma", "PRAGMA query_only"),
    ("pragma", "PRAGMA table_info({t})"),
    ("pragma", "PRAGMA database_list"),
    ("pragma", "PRAGMA writable_schema = ON"),
    ("pragma", "PRAGMA journal_mode = WAL"),
    ("pragma", "PRAGMA compile_options"),
    ("pragma", "PRAGMA function_list"),
    ("pragma", "SELECT * FROM pragma_table_info('{t}')"),
    ("pragma", "SELECT name FROM pragma_function_list"),
    ("pragma", "SELECT * FROM pragma_database_list"),
    ("pragma", "SELECT count(*) FROM (SELECT 1 AS seq) NATURAL JOIN pragma_database_list"),
    # load_extension
    ("extension", "SELECT load_extension('x')"),
    ("extension", "SELECT load_extension('/usr/lib/sqlite3/pcre.so', 'sqlite3_extension_init')"),
    ("extension", "SELECT load_extension(title) FROM {t}"),
    ("extension", "SELECT id FROM {t} WHERE load_extension('libsqlitefunctions') IS NULL"),
    # more than one statement
    ("multi", "SELECT 1; SELECT 2"),
    ("multi", "SELECT 1; DELETE FROM {t}"),
    ("multi", "SELECT count(*) FROM {t}; DROP TABLE {t}"),
    ("multi", "SELECT 1 ORDER BY 1; DELETE FROM {t}"),
    ("multi", "SELECT 1;;"),
    ("multi", "SELECT 1; ATTACH ':memory:' AS m"),
    ("multi", "SELECT 1; PRAGMA query_only = OFF"),
    ("multi", "SELECT id FROM {t} WHERE id = ''; DROP TABLE {t}; --'"),
    ("multi", "SELECT 1 -- x\n; DROP TABLE {t}"),
    ("multi", "SELECT 1\n;\nSELECT load_extension('x')"),
    ("multi", "BEGIN; DELETE FROM {t}; COMMIT"),
    ("multi", "SELECT 1; /* c */ SELECT 2"),
    # recursive CTE bombs (and one bounded recursion)
    ("recursive", "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) "
                  "SELECT count(*) FROM r"),
    ("recursive", "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) "
                  "SELECT n FROM r"),
    ("recursive", "WITH RECURSIVE r(n, s) AS (SELECT 1, 'x' UNION ALL SELECT n + 1, s || s "
                  "FROM r WHERE n < 40) SELECT max(length(s)) FROM r"),
    ("recursive", "WITH RECURSIVE r(n, s) AS (SELECT 1, replace(printf('%4000d', 1), ' ', "
                  "'x') UNION SELECT n + 1, s FROM r) SELECT count(*) FROM r"),
    ("recursive", "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE "
                  "n < 100000000) SELECT count(*) FROM r WHERE 'x' LIKE 'y'"),
    ("recursive", "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r "
                  "LIMIT 1000000000) SELECT sum(n) FROM r"),
    ("recursive", "WITH RECURSIVE a(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM a WHERE "
                  "n < 100000), b(m) AS (SELECT 1 UNION ALL SELECT m + 1 FROM b WHERE "
                  "m < 100000) SELECT count(*) FROM a, b"),
    ("recursive", "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE "
                  "n < 50) SELECT n FROM r"),
    # huge and large-value cross joins
    ("cross_join", "SELECT count(*) FROM {t} a, {t} b, {t} c, {t} d, {t} e, {t} f"),
    ("cross_join", "SELECT a.id FROM {t} a, {t} b, {t} c, {t} d ORDER BY a.id"),
    ("cross_join", "SELECT a.title || b.title FROM {t} a, {t} b, {t} c"),
    ("cross_join", "SELECT count(*) FROM {t} a CROSS JOIN {t} b CROSS JOIN {t} c "
                   "CROSS JOIN {t} d"),
    ("cross_join", f"SELECT max(length({_BIG} || a.id)) FROM {{t}} a, {{t}} b, {{t}} c, "
                   f"{{t}} d"),
    ("cross_join", "SELECT replace(printf('%3000d', 1), ' ', 'x') || a.id FROM {t} a, {t} b"),
    ("cross_join", "SELECT count(*) FROM {t} a JOIN {t} b ON a.title LIKE '%' || b.title "
                   "|| '%'"),
    ("cross_join", "SELECT a.id, b.id FROM {t} a, {t} b ORDER BY a.id, b.id"),
    # functions outside the whitelist, the clock, and amplification beyond the value bound
    ("function", "SELECT random()"),
    ("function", "SELECT randomblob(16)"),
    ("function", "SELECT zeroblob(1000000000)"),
    ("function", "SELECT sqlite_version()"),
    ("function", "SELECT last_insert_rowid()"),
    ("function", "SELECT hex(title) FROM {t}"),
    ("function", "SELECT json_set('{}', '$.a', 1)"),
    ("function", "SELECT '{}' ->> '$.a'"),
    ("function", "SELECT date('now')"),
    ("function", "SELECT datetime('2024-01-01', 'localtime')"),
    ("function", "SELECT CURRENT_TIMESTAMP"),
    ("function", "SELECT julianday()"),
    ("function", "SELECT unixepoch('2024-01-01')"),
    ("function", "SELECT char(65, 66)"),
    ("function", "SELECT length(replace(replace(printf('%16000d', 1), ' ', 'xx'), 'x', 'yy'))"),
    ("function", f"WITH h AS MATERIALIZED (SELECT {_BIG} AS h), n AS MATERIALIZED (SELECT "
                 f"replace(printf('%7999d', 1), ' ', 'a') || 'b' AS n) SELECT count(*) "
                 f"FROM h, n{_J4} WHERE instr(h, {_CASE_D.format('n')}) > 0"),
    ("function", f"WITH h AS MATERIALIZED (SELECT {_BIG} AS h), p AS MATERIALIZED (SELECT "
                 f"'%' || replace(printf('%7999d', 1), ' ', 'a') || 'b' AS p) SELECT "
                 f"count(*) FROM h, p{_J4} WHERE h LIKE {_CASE_D.format('p')}"),
    ("function", f"WITH h AS MATERIALIZED (SELECT {_BIG} AS h), g AS MATERIALIZED (SELECT "
                 f"'*' || replace(printf('%7999d', 1), ' ', '?') || 'b' AS g) SELECT "
                 f"count(*) FROM h, g{_J4} WHERE h GLOB {_CASE_D.format('g')}"),
    ("function", f"WITH h AS MATERIALIZED (SELECT {_BIG} AS h), y AS MATERIALIZED (SELECT "
                 f"replace(printf('%1360d', 1), ' ', 'b') || 'a' AS y) SELECT count(*) "
                 f"FROM h, y{_J4} WHERE length(ltrim(h, {_CASE_D.format('y')})) = 0"),
    ("function", f"WITH h AS MATERIALIZED (SELECT {_BIG} AS h), n AS MATERIALIZED (SELECT "
                 f"replace(printf('%7999d', 1), ' ', 'a') || 'b' AS n) SELECT count(*) "
                 f"FROM h, n{_J4} WHERE length(replace(h, {_CASE_D.format('n')}, 'x')) > 0"),
    # comment, spelling and encoding tricks; engine errors whose text would leak
    ("trick", "SELECT 1 FROM sqlite/**/_master"),
    ("trick", "SELECT count(*) FROM [sqlite_schema]"),
    ("trick", "SELECT count(*) FROM `sqlite_master`"),
    ("trick", "SELECT count(*) FROM main.sqlite_master"),
    ("trick", "SELECT count(*) FROM sqlite_temp_master"),
    ("trick", "SELECT count(*) FROM {t} NATURAL JOIN sqlite_master"),
    ("trick", "SELECT count(*) FROM {t} a JOIN {t} b USING (id)"),
    ("trick", "SELECT count(*) FROM (SELECT 1 AS key) NATURAL JOIN ('sqlite_master')"),
    ("trick", "SELECT count(*) FROM json_tree('[1,[2,3]]')"),
    ("trick", "SELECT count(*) FROM {t}, 'sqlite_master'"),
    ("trick", "WITH sqlite_master AS (SELECT 1) SELECT count(*) FROM main.sqlite_master"),
    ("trick", "SELECT 1\x00; DROP TABLE {t}"),
    ("trick", "SELECT '\ud800'"),
    ("trick", "ＳＥＬＥＣＴ 1"),
    ("trick", "SELECT json_extract(title, '$') FROM {t} WHERE title IS NOT NULL"),
    ("trick", "SELECT abs(-9223372036854775807 - 1 + 0 * year) FROM {t}"),
    ("trick", "SELECT * FROM no_such_table_named_like_a_hidden_value"),
    ("trick", "SELECT count(*) OVER w FROM {t} WINDOW w AS (), sqlite_master AS ()"),
    ("trick", "SELECT 9e999, -9e999, 9e999 - 9e999"),
    ("trick", "SELECT 1 /* ; DROP TABLE {t} */"),
)
GUARD_CATEGORIES = {"write": 15, "ddl": 15, "attach": 6, "pragma": 12, "extension": 4,
                    "multi": 12, "recursive": 8, "cross_join": 8, "function": 20, "trick": 20}
MUST_REFUSE = frozenset({"write", "ddl", "attach", "pragma", "extension", "multi", "function",
                         "trick"})
# trick statements that are one harmless SELECT: refused, or a bounded result of finite cells
HARMLESS = frozenset({"SELECT 9e999, -9e999, 9e999 - 9e999", "SELECT 1 /* ; DROP TABLE {t} */"})
ATTACH_FILES = ("probe-attach.db",)   # an ATTACH that ran would create it


def _bounded(res) -> bool:
    try:
        size = len(json.dumps(res.rows, allow_nan=False, ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8"))
    except ValueError:   # NaN or infinity
        return False
    finite = all(not (isinstance(c, float) and not math.isfinite(c))
                 for r in res.rows for c in r)
    return len(res.rows) <= SQL_ROW_CAP and size <= SQL_MAX_BYTES and finite


def _state(t: Tools, counts_stmt: str) -> tuple:
    """The database as an operator sees it: every table's row count (through guarded sql),
    the schema and `query_only` of every cached view database."""
    counts = run_table_call(t, {"tool": "sql", "args": {"statement": counts_stmt}})
    dbs = [(db.conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name")
            .fetchall(), db.conn.execute("PRAGMA query_only").fetchall(),
            db.conn.in_transaction) for db in t._table_dbs.values()]
    return outcome_key(counts), dbs


def sql_guard(store_path: Path, caller: str = "user:auditor", *,
              clock: Callable = acl.utc_now) -> list[dict]:
    """Run `SQL_GUARD_CASES` as `caller` through one `Tools` instance; one row per case
    (module docstring): category, statement (with `{t}` replaced), outcome, message (a
    refusal's), rows returned, whether the database is intact afterwards, and pass."""
    ctx = table_context(store_path)
    if ctx.tables_id is None:
        raise ValueError(f"{store_path}: no current tables")
    main = DEFAULT_TABLE[ctx.corpus]
    t = Tools(store_path, acl=True, caller=caller, clock=clock)
    counts_stmt = "SELECT " + ", ".join(f"(SELECT count(*) FROM {_q(n)})"
                                        for n in sorted(ctx.contracts))
    before = _state(t, counts_stmt)
    if before[0][0] != "ok":
        raise ValueError(f"{store_path}: the baseline count was refused ({before[0]})")
    rows = []
    for category, template in SQL_GUARD_CASES:
        stmt = template.replace("{t}", main)
        out = run_table_call(t, {"tool": "sql", "args": {"statement": stmt}})
        intact = _state(t, counts_stmt) == before and not any(
            Path(f).exists() for f in ATTACH_FILES)
        message = out[-1] if out[0] != "ok" else None
        fixed = out[0] == "refused" and message in FIXED
        if out[0] == "ok":
            outcome = "ok"
            ok = (category not in MUST_REFUSE or template in HARMLESS) and _bounded(out[1])
        else:
            outcome = f"refused:{FIXED[message]}" if fixed else \
                f"denied:{out[1]}" if out[0] == "denied" else "refused:other"
            ok = fixed
        rows.append({"case": len(rows), "category": category, "statement": stmt,
                     "harmless": template in HARMLESS, "outcome": outcome, "message": message,
                     "rows": len(out[1].rows) if out[0] == "ok" else None,
                     "intact": intact, "pass": ok and intact})
    return rows


def summarize_guard(rows: list[dict]) -> dict:
    cats: dict[str, dict] = {}
    for r in rows:
        b = cats.setdefault(r["category"], {"n": 0, "passed": 0, "outcomes": Counter()})
        b["n"] += 1
        b["passed"] += r["pass"]
        b["outcomes"][r["outcome"]] += 1
    for b in cats.values():
        b["outcomes"] = dict(sorted(b["outcomes"].items()))
    return {"categories": cats, "total": {
        "n": len(rows), "passed": sum(r["pass"] for r in rows),
        "intact": sum(r["intact"] for r in rows),
        "outcomes": dict(sorted(Counter(r["outcome"] for r in rows).items()))}}


# -- equivalence (S1) --------------------------------------------------------------------------

CATEGORICAL = {
    "gov": [("fr_documents", "type"), ("fr_documents", "status"), ("fr_documents", "year"),
            ("fr_documents", "agency"), ("fr_documents", "title_state"),
            ("fr_agencies", "name"), ("fr_cfr_refs", "cfr_part"), ("fr_dockets", "docket_id"),
            ("agencies", "display_name"), ("cfr_parts", "display_name"),
            ("dockets", "display_name"), ("waterways", "display_name"),
            # the extraction (3B) tables, in the pool only when the store's tables hold them
            ("drawbridge_sections", "state"), ("drawbridge_sections", "seasonal"),
            ("drawbridge_sections", "vhf_channel"), ("drawbridge_bridges", "state"),
            ("drawbridge_bridges", "notice_hours"), ("drawbridge_bridges", "opens_on_signal")],
    "research": [("papers", "topic"), ("papers", "type"), ("papers", "status"),
                 ("papers", "relevance"), ("papers", "research"), ("papers", "year"),
                 ("papers", "venue_id"), ("papers", "license"), ("paper_authors", "et_al"),
                 ("venues", "display_name"), ("licences", "display_name"),
                 ("authors", "display_name")],
}
EQUIVALENCE_SQL = {
    "gov": (
        "SELECT count(*), count(DISTINCT agency), min(publication_date), "
        "max(publication_date) FROM fr_documents",
        "SELECT type, status, count(*) FROM fr_documents GROUP BY type, status",
        "SELECT year, sum(json_array_length(cfr_parts)) FROM fr_documents GROUP BY year",
        "SELECT je.value, count(*) FROM fr_documents, json_each(fr_documents.cfr_parts) AS je "
        "GROUP BY je.value",
        "SELECT id, _prov_title FROM fr_documents WHERE title LIKE '%Drawbridge%' "
        "ORDER BY id DESC LIMIT 20",
        "SELECT a.display_name, count(*) FROM agencies a JOIN fr_agencies f "
        "ON f.agency_id = a.entity_id GROUP BY a.display_name",
        'SELECT key, count(DISTINCT _doc_id), sum("rows") FROM waterways GROUP BY key '
        "ORDER BY 3 DESC, key LIMIT 25",
        "SELECT d.id, count(k.docket) FROM fr_documents d LEFT JOIN fr_dockets k "
        "ON k.id = d.id GROUP BY d.id ORDER BY 2 DESC, d.id LIMIT 30",
        "SELECT group_concat(id, ' ') FROM (SELECT id FROM fr_documents "
        "WHERE status = 'final_rule' ORDER BY id LIMIT 50)",
        "SELECT count(DISTINCT _doc_id), count(*), max(_prov_cfr_part) FROM fr_cfr_refs",
    ),
    "research": (
        "SELECT count(*), count(DISTINCT id), min(year), max(year) FROM papers",
        "SELECT topic, type, count(*) FROM papers GROUP BY topic, type",
        "SELECT je.value, count(*) FROM papers, json_each(papers.also_in_list) AS je "
        "GROUP BY je.value",
        "SELECT id, title, _prov_title FROM papers WHERE year >= 2023 "
        "ORDER BY year DESC, id LIMIT 25",
        "SELECT display_name, count(*) FROM venues GROUP BY display_name "
        "ORDER BY 2 DESC, 1 LIMIT 20",
        "SELECT license, count(*) FROM papers GROUP BY license",
        "SELECT et_al, count(*), max(position) FROM paper_authors GROUP BY et_al",
        'SELECT count(*), count(DISTINCT author_id) FROM paper_authors WHERE "row" IN '
        '(SELECT "row" FROM papers WHERE year >= 2024)',
        "SELECT group_concat(id, ' ') FROM (SELECT id FROM papers WHERE relevance = 'high' "
        "ORDER BY id LIMIT 50)",
        "SELECT status, sum(length(title)), avg(year) FROM papers GROUP BY status",
    ),
}


def equivalence_queries(ctx: TableContext, gold: Path | None) -> tuple[dict, dict]:
    """(query_table pool, sql list) of the store's corpus, each by query id."""
    corpus = ctx.corpus
    pool: dict[str, dict] = {}
    if gold is not None:
        for cid, kwargs, _ in gold_cases(gold, corpus):
            pool[f"gold:{cid}"] = {"tool": "query_table", "args": dict(kwargs)}
    for t, col in CATEGORICAL[corpus]:
        if t in ctx.contracts:
            pool[f"count_by:{t}.{col}"] = {"tool": "query_table", "args": {
                "table": t, "op": "count_by", "fields": [col]}}
    sql = {f"sql:{i}": {"tool": "sql", "args": {"statement": s}}
           for i, s in enumerate(EQUIVALENCE_SQL[corpus])}
    return pool, sql


def equivalence(store_path: Path, corpus: str, views_root: Path, n_queries: int = 25,
                seed: int = SEED3, *, gold: Path | None = None,
                directory: Path = acl.DIRECTORY_PATH, policy: Path = acl.POLICY_PATH,
                emb_cache: Path = DEFAULT_EMB_CACHE, clock: Callable = acl.utc_now,
                refs: References | None = None, generator: str | None = None) -> list[dict]:
    """Table equivalence (module docstring): one row per call per view, in view order, with
    `identical`, the outcome and, when they differ, where (no content)."""
    ctx = table_context(store_path)
    refs = refs or References(ctx, views_root, directory=directory, policy=policy,
                              emb_cache=emb_cache, clock=clock, generator=generator)
    rows: list[dict] = []
    if corpus not in TABLE_CORPORA:
        if ctx.tables_id is not None:
            raise ValueError(f"{store_path}: {corpus} should have no tables, but has some")
        calls = {"empty:describe_tables": {"tool": "describe_tables", "args": {}},
                 "empty:query_table": {"tool": "query_table",
                                       "args": {"table": "fr_documents"}},
                 "empty:sql": {"tool": "sql", "args": {"statement": "SELECT 1"}}}
        for v in refs.views:
            rows += _compare_view(store_path, refs.path_of(v), v, calls, {}, emb_cache, clock,
                                  counted=False)
        return rows
    if ctx.tables_id is None or ctx.corpus != corpus:
        raise ValueError(f"{store_path}: no current tables of {corpus}")
    pool, sql = equivalence_queries(ctx, gold)
    n_sql = min(len(sql), round(n_queries * len(sql) / 25))
    n_qt = n_queries - n_sql
    for v in refs.views:
        picked = sorted(pool, key=lambda q: (_h(seed, "equivalence", v.view, q), q))[:n_qt]
        calls = {q: pool[q] for q in picked} | dict(list(sql.items())[:n_sql])
        app = {q: ({}, WIDE)[_h(seed, "applicability", v.view, q) % 2] for q in calls}
        ref_path = refs.path_of(v)
        keep_fresh(store_path, directory, policy, clock)
        rows += _compare_view(store_path, ref_path, v, calls, app, emb_cache, clock)
    return rows


def _compare_view(store_path: Path, ref_path: Path, v: eq.View, calls: dict, app: dict,
                  emb_cache: Path, clock: Callable, counted: bool = True) -> list[dict]:
    mine = Tools(store_path, emb_cache=emb_cache, acl=True, caller=v.caller, clock=clock)
    ref = Tools(ref_path, emb_cache=emb_cache, acl=True, caller=v.caller, clock=clock)
    rows = []
    for q, call in calls.items():
        if call["tool"] != "describe_tables":
            call = {**call, "args": {**call["args"], "applicability": app.get(q, {})}}
        a, b = run_table_call(mine, call), run_table_call(ref, call)
        ka, kb = outcome_key(a), outcome_key(b)
        same = ka == kb and (counted or (a[0] == "refused"
                                         and a[1].startswith("no tables for snapshot")))
        rows.append({"view": v.view, "caller": v.caller, "query_id": q, "tool": call["tool"],
                     "applicability": app.get(q, {}), "identical": same, "outcome": a[0],
                     "difference": None if ka == kb else _first_difference(ka, kb),
                     "counted": counted})
    return rows


def summarize_equivalence(rows: list[dict]) -> dict:
    counted = [r for r in rows if r["counted"]]
    by: dict[str, dict] = {}
    for r in counted:
        b = by.setdefault(r["tool"], {"n": 0, "identical": 0, "refused": 0})
        b["n"] += 1
        b["identical"] += r["identical"]
        b["refused"] += r["outcome"] != "ok"
    empty = [r for r in rows if not r["counted"]]
    return {"n": len(counted), "identical": sum(r["identical"] for r in counted),
            "differing": sum(not r["identical"] for r in counted),
            "views": len({r["view"] for r in rows}), "by_tool": dict(sorted(by.items())),
            "empty_checks": {"n": len(empty), "identical": sum(r["identical"] for r in empty)},
            "total": {"n": len(counted),
                      "passed": sum(r["identical"] for r in counted)}}


# -- fail closed (S3) --------------------------------------------------------------------------


def failclosed_target(ctx: TableContext, callers: list[str], clock: Callable,
                      seed: int = SEED3) -> dict:
    """The fail-closed target (module docstring): by seeded hash order, the first document
    with rows in the main table, not in a chain, whose uri begins no other document's, that
    every one of `callers` sees and whose row each of them gets from the lookup and the select
    of its key. ValueError when none qualifies."""
    main = DEFAULT_TABLE[ctx.corpus]
    key = ctx.contracts[main].key[0]
    held = ctx.holders(main, key)
    by_doc: dict[str, list[int]] = {}
    for i, r in enumerate(ctx.rows[main]):
        by_doc.setdefault(r.doc_id, []).append(i)
    uris = {d: ctx.store.source(d).uri for d in ctx.store.doc_ids()}
    made = {u: Tools(ctx.store_path, acl=True, caller=u, clock=clock) for u in callers}
    for d in sorted(by_doc, key=lambda d: (_h(seed, "failclosed", d), d)):
        if chain_of(ctx.store.source(d)) is not None or \
                not all(d in ctx.visible(u) for u in callers) or \
                any(o != d and u.startswith(uris[d]) for o, u in uris.items()):
            continue
        rows = [i for i in by_doc[d] if _probe_value(ctx.rows[main][i].row.get(key))
                and held[ctx.rows[main][i].row[key]] == {d}]
        if not rows:
            continue
        v = ctx.rows[main][rows[_h(seed, "failclosed-row", d) % len(rows)]].row[key]
        absent = next(f"{v}~absent{n}" for n in range(1000) if f"{v}~absent{n}" not in held)
        target = {"doc_id": d, "uri": uris[d], "table": main, "key": key, "value": v,
                  "secret": str(v), "absent": absent}
        calls, _ = failclosed_calls(target)
        before = {}
        for u, t in made.items():
            q = run_table_call(t, calls["query_table"])
            s = run_table_call(t, calls["sql"])
            before[u] = {"visible": True,
                         "lookup": q[0] == "ok" and any(r["doc_id"] == d for r in q[1].rows),
                         "select": s[0] == "ok" and any(r[0] == d for r in s[1].rows)}
        if all(b["lookup"] and b["select"] for b in before.values()):
            return {**target, "before": before}
    raise ValueError("no document meets the no-entry precondition (rows in the main table, "
                     "visible to every fail-closed caller, found by its lookup and select)")


def failclosed_identity(target: dict) -> dict:
    """What identifies the fail-closed target in the results: its document id, table and key
    column (not the key's value, which is content)."""
    return {"doc_id": target["doc_id"], "table": target["table"], "key": target["key"]}


def failclosed_calls(target: dict) -> tuple[dict, dict]:
    """(the three calls of the fail-closed probes, the same naming the absent key)."""
    t, key = target["table"], target["key"]

    def of(v):
        return {"describe_tables": {"tool": "describe_tables", "args": {"table": t}},
                "query_table": {"tool": "query_table", "args": {
                    "table": t, "filters": {key: v}, "op": "lookup", "applicability": WIDE}},
                "sql": {"tool": "sql", "args": {
                    "statement": f"SELECT _doc_id, {_q(key)} FROM {_q(t)} WHERE {_q(key)} = "
                                 f"{sql_literal(v)}", "applicability": WIDE}}}
    return of(target["value"]), of(target["absent"])


def _without(res, *keys: str) -> str:
    return _json({k: v for k, v in _stripped(res).items() if k not in keys})


def judge_table_failclosed(cond: str, tool: str, target: dict, out: tuple,
                           control: tuple | None) -> dict:
    """Whether a fail-closed probe returned nothing of the target (module docstring)."""
    secret, doc = target["secret"], target["doc_id"]
    text = _payload(out)
    shown = doc in text or doc[:12] in text or (tool == "describe_tables" and secret in text)
    if cond != "no_entry":
        passed = out[0] == "denied" and out[1] == cond and not shown
        return {"outcome": out[0] if out[0] != "denied" else f"denied:{out[1]}",
                "content": out[0] == "ok", "pass": passed}
    if out[0] != "ok":
        return {"outcome": out[0] if out[0] != "denied" else f"denied:{out[1]}",
                "content": False, "pass": False}
    res = out[1]
    if tool == "describe_tables":
        return {"outcome": "ok", "content": shown, "pass": not shown}
    content = bool(res.rows) or shown
    same = control is not None and control[0] == "ok" and (
        _without(res, "filters", "statement_sha256")
        == _without(control[1], "filters", "statement_sha256"))
    return {"outcome": "ok", "content": content, "not_found_equal": same,
            "pass": not content and same}


def failclosed(store_path: Path, clone_root: Path, corpus: str, seed: int = SEED3, *,
               directory: Path = acl.DIRECTORY_PATH, policy: Path = acl.POLICY_PATH,
               emb_cache: Path = DEFAULT_EMB_CACHE, clock: Callable = acl.utc_now,
               logs: dict | None = None) -> list[dict]:
    """The 90 fail-closed probes (module docstring); one row per probe. F4 and F5 run on the
    store, the others on clones under `clone_root` (removed). `logs`, when given, receives the
    log scan (`scan_table_log`) of each store the calls wrote to."""
    store_path, clone_root = Path(store_path), Path(clone_root)
    ctx = table_context(store_path)
    if ctx.tables_id is None or ctx.corpus != corpus:
        raise ValueError(f"{store_path}: no current tables of {corpus}")
    users = acl_probes.failclosed_callers(ctx, seed)
    target = failclosed_target(ctx, users, clock, seed)
    calls, controls = failclosed_calls(target)
    ident = failclosed_identity(target)
    statements = [c["args"]["statement"] for c in (calls["sql"], controls["sql"])]
    rows: list[dict] = []
    logs = {} if logs is None else logs

    def run(path: Path, cond: str, probes: list[tuple[int, str | None, str | None]]) -> None:
        for i, caller, variant in probes:
            t = Tools(path, emb_cache=emb_cache, acl=True, caller=caller, clock=clock)
            for tool in TABLE_TOOLS:
                out = run_table_call(t, calls[tool])
                ctrl = run_table_call(t, controls[tool]) if cond == "no_entry" else None
                b = target["before"].get(caller)
                rows.append({"probe_id": f"{cond}:{i}:{tool}", "family": cond, "tool": tool,
                             "caller": caller, "variant": variant, "target": ident,
                             "visible_before": None if b is None else b["visible"],
                             **judge_table_failclosed(cond, tool, target, out, ctrl)})

    def scanned(name: str, path: Path, offset: int) -> None:
        logs[name] = merge_table_scans(logs.get(name), scan_table_log(
            log_path(path), offset, statements))

    plain = [(i, u, None) for i, u in enumerate(users)]
    for cond in CONDITIONS:
        if cond in ("F4", "F5"):
            offset = log_size(log_path(store_path))
            run(store_path, cond, [(i, u, None) for i, u in enumerate(
                F4_CALLERS if cond == "F4" else F5_CALLERS)])
            scanned("store", store_path, offset)
            continue
        clone = clone_root / f"tables-failclosed-{cond}"
        _cp(store_path, clone)
        offset = log_size(log_path(clone))
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
                records = {d: r for d, r in s._records.items() if d != target["doc_id"]}
                Store(clone, None, records, s.paths).commit()
                run(clone, cond, plain)
            elif cond == "F3":
                for variant, shift in (("stale", -STALE), ("future", AHEAD)):
                    acl.sync(clone, directory, policy, clock=lambda s=shift: clock() + s)
                    run(clone, cond, [(i, users[i], v) for i, v in enumerate(F3_VARIANTS)
                                      if v == variant])
            else:   # no entry
                pol = _no_entry_policy(policy, target["uri"], clone / "policy-no-entry.json")
                before = acl.read_head(clone)[1].docs
                acl.sync(clone, directory, pol, clock=clock)
                after = acl.read_head(clone)[1].docs
                changed = {d for d in after if after[d] != before.get(d)}
                if after.get(target["doc_id"]) != [] or not changed <= {target["doc_id"]}:
                    raise ValueError(f"the no-entry rule changed {len(changed)} documents' "
                                     f"access, not only the target's")
                run(clone, cond, plain)
            scanned(f"clone-{cond}", clone, offset)
        finally:
            shutil.rmtree(clone, ignore_errors=True)
    if clone_root.is_dir() and not any(clone_root.iterdir()):
        clone_root.rmdir()
    return rows


def summarize_failclosed(rows: list[dict]) -> dict:
    out: dict = {}
    for r in rows:
        b = out.setdefault(r["family"], {"n": 0, "passed": 0, "content": 0,
                                         "outcomes": Counter(), "by_tool": Counter()})
        b["n"] += 1
        b["passed"] += r["pass"]
        b["content"] += r["content"]
        b["outcomes"][r["outcome"]] += 1
        b["by_tool"][r["tool"]] += r["pass"]
    for b in out.values():
        b["outcomes"] = dict(sorted(b["outcomes"].items()))
        b["by_tool"] = dict(sorted(b["by_tool"].items()))
    return {"conditions": out, "total": {"n": len(rows),
                                         "passed": sum(r["pass"] for r in rows),
                                         "content": sum(r["content"] for r in rows)}}


# -- applicability -----------------------------------------------------------------------------


def applicability_statement(table: str) -> str:
    """The per-document row count the applicability probes run through `sql`."""
    return f"SELECT _doc_id, count(*) FROM {_q(table)} GROUP BY _doc_id"


def applicability_dates(ctx: TableContext, overlay, table: str, n: int,
                        seed: int = SEED3) -> list[str]:
    """The `n` `as_of` dates of `table`'s probes: the `fr_documents` publication dates in
    seeded hash order (cycled when there are fewer); for a table with rows of versioned
    documents (a chain: the drawbridge tables) first each version's first day in force and the
    day before it, so `as_of` selects every version and none before the first."""
    dates = sorted({r.row["publication_date"] for r in ctx.rows["fr_documents"]
                    if isinstance(r.row.get("publication_date"), str)})
    if not dates:
        raise ValueError(f"{ctx.store_path}: no Federal Register publication dates")
    order = sorted(dates, key=lambda d: (_h(seed, "as_of", d), d))
    starts = sorted({overlay.records[d].valid_from for d in ctx.docs_of(table)
                     if chain_of(ctx.store.source(d)) is not None
                     and overlay.records[d].valid_from is not None})
    first = sorted({x.isoformat() for s in starts for x in (s - timedelta(days=1), s)})
    rest = [d for d in order if d not in first] or order
    return [*first, *(rest[k % len(rest)] for k in range(max(0, n - len(first))))][:n]


def applicability_probes(store_path: Path, tables: tuple[str, ...] = ("fr_documents",),
                         n: int = 50, seed: int = SEED3, *, caller: str = "user:auditor",
                         clock: Callable = acl.utc_now) -> list[dict]:
    """Per table, the default filters and `n` `as_of` dates (`applicability_dates`, module
    docstring); one row per probe: the rows and documents returned, those expected, the most
    versions of one chain returned (`versions`; at most 1: the version in force only), and
    pass."""
    ctx = table_context(store_path)
    if ctx.tables_id is None or ctx.manifest.applicability is None:
        raise ValueError(f"{store_path}: no current tables with an applicability overlay")
    unknown = [t for t in tables if t not in ctx.contracts]
    if unknown:
        raise ValueError(f"{store_path}: the current tables have no table "
                         f"{', '.join(unknown)} (they have {', '.join(sorted(ctx.contracts))})")
    overlay = ap.load_overlay(store_path, ctx.store.snapshot_id, ctx.manifest.applicability)
    seen = ctx.visible(caller)
    chain = {d: chain_of(ctx.store.source(d)) for d in ctx.doc_ids}
    t = Tools(store_path, acl=True, caller=caller, clock=clock)
    rows = []
    for table in tables:
        key = ctx.contracts[table].key[0]
        dates = applicability_dates(ctx, overlay, table, n, seed)
        for k in range(n + 1):
            as_of = None if k == 0 else dates[k - 1]
            f = ap.Filters() if as_of is None else ap.Filters(as_of=as_of)
            filters = {} if as_of is None else {"as_of": as_of}
            admitted = {d for d in seen if ap.admits(overlay.records[d], f)}
            want = Counter(r.doc_id for r in ctx.rows[table] if r.doc_id in admitted)
            count = run_table_call(t, {"tool": "query_table", "args": {
                "table": table, "op": "count", "applicability": filters}})
            look = run_table_call(t, {"tool": "query_table", "args": {
                "table": table, "op": "lookup", "fields": [key], "limit": QUERY_LIMIT_MAX,
                "applicability": filters}})
            per = run_table_call(t, {"tool": "sql", "args": {
                "statement": applicability_statement(table),
                "applicability": filters}})
            ok = count[0] == look[0] == per[0] == "ok"
            got = Counter({r[0]: r[1] for r in per[1].rows}) if ok else Counter()
            looked = {r["doc_id"] for r in look[1].rows} if ok else set()
            outside = sorted((set(got) | looked) - admitted)
            versions = max(Counter(chain.get(d) for d in set(got) | looked
                                   if chain.get(d) is not None).values(), default=0)
            passed = (ok and not outside and got == want and count[1].count == sum(want.values())
                      and not per[1].truncated and versions <= 1)
            rows.append({"probe_id": f"{table}:{k:03d}", "table": table, "as_of": as_of,
                         "rows": count[1].count if ok else None, "expected": sum(want.values()),
                         "documents": len(got), "outside": len(outside), "versions": versions,
                         "excluded": count[1].excluded_by_filter if ok else None,
                         "pass": passed})
    return rows


def summarize_applicability(rows: list[dict]) -> dict:
    return {"total": {"n": len(rows), "passed": sum(r["pass"] for r in rows),
                      "as_of": sum(r["as_of"] is not None for r in rows),
                      "default": sum(r["as_of"] is None for r in rows),
                      "outside": sum(r["outside"] for r in rows),
                      "dates": len({r["as_of"] for r in rows if r["as_of"]})},
            "tables": sorted({r["table"] for r in rows}),
            "by_table": {t: {"n": sum(r["table"] == t for r in rows),
                             "passed": sum(r["pass"] for r in rows if r["table"] == t),
                             "as_of": sum(r["as_of"] is not None for r in rows
                                          if r["table"] == t),
                             "as_of_with_rows": sum(bool(r["rows"]) for r in rows
                                                    if r["table"] == t and r["as_of"]),
                             "outside": sum(r["outside"] for r in rows if r["table"] == t),
                             "max_versions": max((r["versions"] for r in rows
                                                  if r["table"] == t), default=0)}
                         for t in sorted({r["table"] for r in rows})}}


# -- the log scan (S3) -------------------------------------------------------------------------

SQL_ARGS = frozenset({"statement_sha256", "applicability", "handle"})
MIN_STATEMENT = 16


def _refused_before_tables(error: object) -> bool:
    """A table tool refused before it read any tables (so `tables` is null on its line)."""
    return isinstance(error, str) and (error.startswith("no tables for snapshot")
                                       or error == NO_HANDLE_TABLES
                                       or error.startswith("handle no longer available")
                                       or error.startswith("bad handle"))


def scan_table_log(path: Path, offset: int = 0, statements: Iterable[str] = ()) -> dict:
    """The log lines written after byte `offset` (module docstring): how many, how many lack
    each of `REQUIRED`, table-tool lines without `tables`, allowed lines with a null resolved
    field (or a null `tables` on a table-tool line that read tables), `sql` lines, and lines
    that hold a statement's text (or a `sql` line with other args or no `sql_sha256`)."""
    texts = sorted({x for s in statements if len(s) >= MIN_STATEMENT
                    for x in (s, json.dumps(s, ensure_ascii=False)[1:-1])})
    out = {"lines": 0, "complete_lines": 0, "missing": dict.fromkeys(REQUIRED, 0),
           "table_lines": 0, "tables_missing": 0, "allowed": 0, "allowed_unresolved": 0,
           "sql_lines": 0, "sql_text_lines": 0, "decisions": {}, "tools": {}}
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read()
    except FileNotFoundError:
        return {**out, "complete": True}
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
        table_tool = tool in TABLE_TOOLS
        if table_tool:
            out["table_lines"] += 1
            out["tables_missing"] += "tables" not in rec
        if rec.get("acl_decision") == "allowed":
            out["allowed"] += 1
            need = RESOLVED + (("tables",) if table_tool and not _refused_before_tables(
                rec.get("error")) else ())
            out["allowed_unresolved"] += any(rec.get(k) is None for k in need)
        bad = any(x in line for x in texts)
        if tool == "sql":
            out["sql_lines"] += 1
            args = rec.get("args")
            bad = bad or not isinstance(args, dict) or not set(args) <= SQL_ARGS \
                or "sql_sha256" not in rec
        out["sql_text_lines"] += bad
        decisions[str(rec.get("acl_decision"))] += 1
        tools[str(tool)] += 1
    out["decisions"] = dict(sorted(decisions.items()))
    out["tools"] = dict(sorted(tools.items()))
    out["complete"] = _complete(out)
    return out


def _complete(s: dict) -> bool:
    return (s["lines"] == s["complete_lines"] and s["tables_missing"] == 0
            and s["allowed_unresolved"] == 0 and s["sql_text_lines"] == 0)


def merge_table_scans(a: dict | None, b: dict) -> dict:
    if a is None:
        return b
    out = {k: a[k] + b[k] for k in ("lines", "complete_lines", "table_lines", "tables_missing",
                                    "allowed", "allowed_unresolved", "sql_lines",
                                    "sql_text_lines")}
    out["missing"] = {k: a["missing"][k] + b["missing"][k] for k in REQUIRED}
    out["decisions"] = dict(sorted((Counter(a["decisions"]) + Counter(b["decisions"])).items()))
    out["tools"] = dict(sorted((Counter(a["tools"]) + Counter(b["tools"])).items()))
    out["complete"] = _complete(out)
    return out


def total_table_scan(scans: dict) -> dict:
    """The scans of several logs added up, with `complete`."""
    out = None
    for s in scans.values():
        out = merge_table_scans(out, s)
    return out or scan_table_log(Path("/nonexistent"))


# -- the MCP leg (D1) --------------------------------------------------------------------------

MCP_SUBSET = 60


def select_mcp(universe: list[tuple[str, Probe]], n: int = MCP_SUBSET,
               seed: int = SEED3) -> list[tuple[str, Probe]]:
    """The `n` probes of `universe` ((label, probe) pairs) with the lowest SHA-256 of
    `"<seed>:<label>/<probe_id>"`, in that order."""
    return mcp_probes.select(universe, n, seed)


class _Counting(mcp_probes.CountingTools):
    METHODS = TABLE_TOOLS


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
                results[i] = check_leak(p, lambda c, t=counted: t,
                                        lambda c, lb=label: reference_for(lb, c),
                                        ctx=contexts[label])
                for j, call in enumerate(p.call["calls"]):
                    first = run_table_call(counted, call)
                    if first[0] != "ok":
                        continue
                    handle = first[1].handle
                    again = run_table_call(counted, {**call, "args": {**call["args"],
                                                                      "handle": handle}})
                    replays.append({"store": label, "probe_id": p.probe_id, "call": j,
                                    "tool": call["tool"],
                                    "handle_tables": bool(handle and handle.get("tables")),
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
                      "handle_tables": sum(r["handle_tables"] for r in replays)}
    return out
