"""Snapshot handles (Phase 2 spec §9.2): which versions of the store's parts a tool call ran on,
so a later call can run on exactly the same ones.

    {"snapshot": <content snapshot id>,
     "index": "<index fingerprint>:<system>:<w>" | null,
     "applicability": <applicability overlay id> | null,
     "dedup": <dedup overlay id> | null,
     "tools": <tool snapshot id> | null,
     "tool_index": "<tool index fingerprint>:<w>" | null,
     "tables": <tables id> | null,
     "units": <units id> | null}

Every result of the tool calls (`adr_store.tools`) carries one, and every tool call takes
one (`handle`). A handle names the parts of the store, not the call: the handle of a `read`
can be given to a `search` or a `search_tools`.

Components (planner's calls, Task 12):
- `index` is the active index's fingerprint plus what `index/active.json` adds to it at query
  time: the system name and the fusion weight `w` (JSON: a number, or `null` for a
  lexical-only index). The fingerprint alone does not fix the ranking (`adr index` can make
  the same index active with another weight) nor the result's `system` (a lexical-only
  `p1-struct-bc-rr` index is a lexical-only `p1-struct-bc` one).
- `tool_index` is the active tool index's fingerprint and its fusion weight, for the same
  reason (`w_name` is in the fingerprint), so tool search replays exactly.
- `applicability` and `dedup` are the SHA-256 of the overlay files (their ids), `tools` the
  tool snapshot id, `tables` the tables id (the SHA-256 of a build manifest of the typed
  tables, `adr_store.tables.overlay`; Phase 3 spec §9.3) and `units` the units id (the
  SHA-256 of a knowledge-unit build manifest, `adr_store.units.overlay`; Phase 4 spec §11.3).
  `tables` and `units` are optional (default null), so a handle saved before either existed
  still validates; the other parts are required.
- The ACL snapshot is never part of a handle (ruling R15): every call is judged against the
  current ACL, whatever its handle names (`adr_store.tools`).
- A handle's parameters (the system label and the weights) are what the client asks for, not
  an attestation of what was active: a client may hand back any weight in [0, 1] for a hybrid
  index, and any system label that could have built the index (judged from the index's own
  `meta.json`: breadcrumb prefix, w_bc and reranker). A label the index cannot run (a
  lexical `p1-struct` index called `p1-struct-bc-rr`, say) is a bad handle.
- `current` never raises: a part whose record is damaged (an `active.json` weight outside
  [0, 1] or NaN, a system name of the wrong shape) is null, so a call without a handle behaves
  as it did before handles existed.

`resolve(store_path, None)` is the store as it is now (`current`): HEAD, the active index when
`index/active.json` names a saved index of that snapshot, the overlays of that snapshot (of
that index's chunks for dedup), `tools/HEAD` and the active tool index of that tool snapshot,
`tables/HEAD` when its manifest is of that content snapshot and loads (every table file as
the manifest lists it), and `units/HEAD` likewise (every unit file as its manifest lists it);
a part that is missing or does not belong to the others is null.
`resolve(store_path, handle)` checks that every part the handle names still exists, byte for
byte (a file that no longer hashes to its id, or a deleted index directory, is gone), and
refuses with "handle no longer available: <component>" otherwise; parts that do not belong
together (an index of another snapshot, a dedup overlay without an index, a tool index of
another tool snapshot, a weight that contradicts the index, tables or units of another
content snapshot) are a "bad handle". There is no fallback to HEAD. Resolving writes nothing and
keeps no state: caches here are keyed by file versions (`_stat_key`) or by immutable ids, so
they never change an answer.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from adr_store import applicability as ap
from adr_store import dedup as dedup_mod
from adr_store.retrieval.index import chunk_content_sha256
from adr_store.store import Store, StoreError
from adr_store.tables import overlay as tables_overlay
from adr_store.units import overlay as units_overlay

HEX64 = r"^[0-9a-f]{64}$"
_HEX64 = re.compile(HEX64)
_INDEX = re.compile(r"^([0-9a-f]{64}):([a-z0-9][a-z0-9-]*):(.+)$")
_TOOL_INDEX = re.compile(r"^([0-9a-f]{64}):(.+)$")
UNAVAILABLE = "handle no longer available: {}"
COMPONENTS = ("snapshot", "index", "applicability", "dedup", "tools", "tool_index", "tables",
              "units")
REQUIRED = COMPONENTS[:6]  # the bad-handle message lists these, so its text is unchanged


def _tool_error(message: str) -> Exception:
    from adr_store.tools import ToolError  # the tools import this module

    return ToolError(message)


def unavailable(component: str) -> Exception:
    return _tool_error(UNAVAILABLE.format(component))


def bad(reason: str) -> Exception:
    return _tool_error(f"bad handle: {reason}")


def _weight(text: str) -> float | int | None:
    """The `w` of an encoded index component: JSON `null` or a number in [0, 1]."""
    try:
        w = json.loads(text)
    except (ValueError, RecursionError):
        raise ValueError(f"weight {text!r} is not JSON") from None
    if w is not None and (isinstance(w, bool) or not isinstance(w, int | float)
                          or not 0.0 <= w <= 1.0):
        raise ValueError(f"weight {text!r} is not null or a number from 0 to 1")
    return w


def encode_index(fingerprint: str, system: str, w: float | int | None) -> str:
    return f"{fingerprint}:{system}:{json.dumps(w)}"


def encode_tool_index(fingerprint: str, w: float | int | None) -> str:
    return f"{fingerprint}:{json.dumps(w)}"


def check_index(v: str) -> str:
    """`v` if it is an index component, else ValueError."""
    m = _INDEX.fullmatch(v)
    if m is None:
        raise ValueError("expected '<64 hex characters>:<system>:<weight>'")
    _weight(m.group(3))
    return v


def check_tool_index(v: str) -> str:
    m = _TOOL_INDEX.fullmatch(v)
    if m is None:
        raise ValueError("expected '<64 hex characters>:<weight>'")
    _weight(m.group(2))
    return v


class Handle(BaseModel):
    """A snapshot handle. Every field but `tables` and `units` is required (null: the store
    had no such part); `tables` and `units` default to null, so a handle saved before Phase 3
    or Phase 4 still validates."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="Handle")

    snapshot: str = Field(pattern=HEX64, description="content snapshot id")
    index: str | None = Field(description="'<index fingerprint>:<system>:<w>' (w: a JSON "
                                          "number, or null for a lexical-only index)")
    applicability: str | None = Field(pattern=HEX64, description="applicability overlay id")
    dedup: str | None = Field(pattern=HEX64, description="dedup overlay id")
    tools: str | None = Field(pattern=HEX64, description="tool snapshot id")
    tool_index: str | None = Field(description="'<tool index fingerprint>:<w>'")
    tables: str | None = Field(None, pattern=HEX64, description="tables id (typed tables)")
    units: str | None = Field(None, pattern=HEX64, description="units id (knowledge units)")

    @field_validator("index")
    @classmethod
    def _index(cls, v: str | None) -> str | None:
        return None if v is None else check_index(v)

    @field_validator("tool_index")
    @classmethod
    def _tool_index(cls, v: str | None) -> str | None:
        return None if v is None else check_tool_index(v)

    def index_parts(self) -> tuple[str, str, float | int | None] | None:
        """(fingerprint, system, w) of `index`, or None."""
        if self.index is None:
            return None
        m = _INDEX.fullmatch(self.index)
        return m.group(1), m.group(2), _weight(m.group(3))

    def tool_index_parts(self) -> tuple[str, float | int | None] | None:
        if self.tool_index is None:
            return None
        m = _TOOL_INDEX.fullmatch(self.tool_index)
        return m.group(1), _weight(m.group(2))


def parse(handle: object) -> Handle:
    """A `Handle` from a `Handle` or a dict (as results carry it); "bad handle" otherwise."""
    if isinstance(handle, Handle):
        return handle
    if not isinstance(handle, dict):
        raise bad(f"expected an object with the fields {', '.join(REQUIRED)}, got "
                  f"{type(handle).__name__}")
    try:
        return Handle.model_validate(handle)
    except ValidationError as e:
        errs = "; ".join(f"{'.'.join(map(str, x['loc'])) or 'handle'}: {x['msg']}"
                         for x in e.errors()[:3])
        raise bad(errs) from None


@dataclass(frozen=True)
class Resolved:
    """The parts a handle names, checked: the content snapshot, and the active records the
    tools would read from `index/active.json` and `tools/index/active.json` for them."""

    handle: Handle
    store: Store
    index: dict | None  # system, snapshot, fingerprint, lexical_only, rerank, w
    applicability: str | None
    dedup: str | None
    tools: str | None
    tool_index: dict | None  # tool_snapshot, fingerprint, w_name, lexical_only, w
    tables: str | None = None  # the tables id, its manifest checked
    units: str | None = None  # the units id, its manifest checked


# -- file versions and immutable parts ---------------------------------------------------------

_LOCK = threading.Lock()
_SHA: OrderedDict[tuple, str] = OrderedDict()  # (path, file version) -> SHA-256
_CONTENT: OrderedDict[tuple, tuple[dict, str, str]] = OrderedDict()  # index dir -> parts
CACHE = 64


def _stat_key(path: Path) -> tuple | None:
    try:
        st = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _remember(cache: OrderedDict, key, value):
    with _LOCK:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > CACHE:
            cache.popitem(last=False)
    return value


def file_sha256(path: Path) -> str | None:
    """The SHA-256 of a regular file's bytes, or None when there is none (or it cannot be
    read); reused while the file's version is unchanged."""
    path = Path(path)
    st = _stat_key(path)
    if st is None or not path.is_file():
        return None
    key = (str(path), st)
    with _LOCK:
        if key in _SHA:
            _SHA.move_to_end(key)
            return _SHA[key]
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
    return _remember(_SHA, key, digest)


def _read_meta(path: Path) -> dict | None:
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    return meta if isinstance(meta, dict) else None


def index_meta(store_path: Path, fingerprint: str) -> dict | None:
    """The `meta.json` of a saved index, or None when there is none (or it is damaged)."""
    meta = _read_meta(Path(store_path) / "index" / fingerprint / "meta.json")
    if meta is None or not isinstance(meta.get("snapshot"), str) or \
            not isinstance(meta.get("dense"), bool) or \
            not isinstance(meta.get("settings"), dict) or \
            not isinstance(meta["settings"].get("rerank"), bool) or \
            not isinstance(meta.get("chunker"), dict):
        return None
    return meta


def index_content(store_path: Path, fingerprint: str) -> tuple[dict, str, str] | None:
    """(chunker, chunk_content_sha256, snapshot) of a saved index (what locates its dedup
    overlay), or None when it cannot be read; an index directory is never rewritten, so the
    answer is kept by its path and the version of its files."""
    d = Path(store_path) / "index" / fingerprint
    key = (str(d), _stat_key(d / "meta.json"), _stat_key(d / "chunks.jsonl"))
    if key[1] is None or key[2] is None:
        return None
    with _LOCK:
        if key in _CONTENT:
            _CONTENT.move_to_end(key)
            return _CONTENT[key]
    meta = index_meta(store_path, fingerprint)
    if meta is None:
        return None
    try:
        rows = []
        with open(d / "chunks.jsonl", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    rows.append(SimpleNamespace(chunk_id=r["chunk_id"],
                                                breadcrumb=r["breadcrumb"], text=r["text"]))
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return None
    return _remember(_CONTENT, key, (meta["chunker"], chunk_content_sha256(rows),
                                     meta["snapshot"]))


def dedup_id(store_path: Path, snapshot: str, fingerprint: str) -> str | None:
    """The id of the dedup overlay of an index's chunks (the SHA-256 of its file), or None.
    When the snapshot holds no dedup overlay of the index's chunker at all, that is known
    without reading the index's chunks (`index_content` hashes them once per file version and
    process)."""
    meta = index_meta(store_path, fingerprint)
    if meta is None:
        return None
    prefix = f"{dedup_mod.overlay_key(meta['chunker'], dedup_mod.PARAMS)}-"
    folder = Path(store_path) / dedup_mod.OVERLAY_DIR / snapshot
    try:
        if not any(p.name.startswith(prefix) for p in folder.glob("*.json")):
            return None
    except OSError:
        return None
    parts = index_content(store_path, fingerprint)
    if parts is None:
        return None
    chunker, content, _ = parts
    return file_sha256(dedup_mod.overlay_path(store_path, snapshot, chunker, content))


def tool_index_meta(store_path: Path, fingerprint: str) -> dict | None:
    meta = _read_meta(Path(store_path) / "tools" / "index" / fingerprint / "meta.json")
    if meta is None or not isinstance(meta.get("dense"), bool) or \
            isinstance(meta.get("w_name"), bool) or not isinstance(meta.get("w_name"), int):
        return None
    return meta


def tool_snapshot_ok(store_path: Path, sid: str) -> bool:
    return _HEX64.fullmatch(sid) is not None and file_sha256(
        Path(store_path) / "tools" / "snapshots" / f"{sid}.json") == sid


_TABLES: OrderedDict[str, tuple[tuple, tables_overlay.Manifest]] = OrderedDict()


def tables_manifest(store_path: Path, tables_id: object) -> tables_overlay.Manifest | None:
    """The build manifest whose SHA-256 is `tables_id`, checked as `overlay.load_manifest`
    checks it (every table file there with its hash and row count), or None when it is gone or
    damaged. A check is reused while the manifest file and every table file it lists keep the
    version they had when it was made (`_stat_key`)."""
    if not isinstance(tables_id, str) or _HEX64.fullmatch(tables_id) is None:
        return None
    store_path = Path(store_path)
    path = tables_overlay.manifest_path(store_path, tables_id)
    if path is None:
        return None
    key = str(path)
    with _LOCK:
        hit = _TABLES.get(key)
        if hit is not None:
            _TABLES.move_to_end(key)
    if hit is not None:
        state, m = hit
        if state == _tables_state(path, m):
            return m
    try:
        m = tables_overlay.load_manifest(store_path, tables_id)
    except (tables_overlay.TablesError, OSError):
        return None
    state = _tables_state(path, m)
    return m if None in state else _remember(_TABLES, key, (state, m))[1]


def _tables_state(path: Path, m: tables_overlay.Manifest) -> tuple:
    return (_stat_key(path), *(_stat_key(path.parent / t.file) for t in m.tables))


def tables_head(store_path: Path, snapshot: str) -> str | None:
    """The tables id in `tables/HEAD` when its manifest loads and is of content snapshot
    `snapshot`, else None."""
    try:
        tables_id = (Path(store_path) / tables_overlay.TABLES_DIR / "HEAD").read_text(
            encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    m = tables_manifest(store_path, tables_id)
    return tables_id if m is not None and m.snapshot == snapshot else None


_UNITS: OrderedDict[str, tuple[tuple, units_overlay.UnitsManifest]] = OrderedDict()


def units_manifest(store_path: Path, units_id: object) -> units_overlay.UnitsManifest | None:
    """The units build manifest whose SHA-256 is `units_id`, checked as
    `units.overlay.load_units_manifest` checks it (every unit file there with its hash and unit
    count), or None when it is gone or damaged. A check is reused while the manifest file and
    every unit file it lists keep the version they had when it was made (`_stat_key`)."""
    if not isinstance(units_id, str) or _HEX64.fullmatch(units_id) is None:
        return None
    store_path = Path(store_path)
    try:
        path = units_overlay.units_manifest_path(store_path, units_id)
    except OSError:
        return None
    if path is None:
        return None
    key = str(path)
    with _LOCK:
        hit = _UNITS.get(key)
        if hit is not None:
            _UNITS.move_to_end(key)
    if hit is not None:
        state, m = hit
        if state == _units_state(path, m):
            return m
    try:
        m = units_overlay.load_units_manifest(store_path, units_id)
    except (units_overlay.UnitsError, OSError, ValueError):
        return None
    state = _units_state(path, m)
    return m if None in state else _remember(_UNITS, key, (state, m))[1]


def _units_state(path: Path, m: units_overlay.UnitsManifest) -> tuple:
    return (_stat_key(path), *(_stat_key(path.parent / f.file) for f in m.units))


def units_head(store_path: Path, snapshot: str) -> str | None:
    """The units id in `units/HEAD` when its manifest loads and is of content snapshot
    `snapshot`, else None (units of an older snapshot are never the store's now)."""
    try:
        units_id = (Path(store_path) / units_overlay.UNITS_DIR / "HEAD").read_text(
            encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    m = units_manifest(store_path, units_id)
    return units_id if m is not None and m.snapshot == snapshot else None


# -- the store now ---------------------------------------------------------------------------

_UNSET = object()


def _active_index(store_path: Path, snapshot: str) -> dict | None:
    """`index/active.json` when it is well formed, for `snapshot`, and names a saved index."""
    rec = _read_meta(Path(store_path) / "index" / "active.json")
    if rec is None:
        return None
    try:
        fp, system, w = rec["fingerprint"], rec["system"], rec["w"]
        if rec["snapshot"] != snapshot or not isinstance(fp, str) or \
                _HEX64.fullmatch(fp) is None or not isinstance(system, str) or \
                not isinstance(rec["lexical_only"], bool) or not isinstance(rec["rerank"], bool):
            return None
        _weight(json.dumps(w))
    except (KeyError, ValueError, TypeError):
        return None
    return rec if index_meta(store_path, fp) is not None else None


def _active_tool_index(store_path: Path, tools: str | None) -> dict | None:
    rec = _read_meta(Path(store_path) / "tools" / "index" / "active.json")
    if rec is None or tools is None:
        return None
    try:
        fp, w = rec["fingerprint"], rec["w"]
        if rec["tool_snapshot"] != tools or not isinstance(fp, str) or \
                _HEX64.fullmatch(fp) is None or not isinstance(rec["lexical_only"], bool) or \
                rec["lexical_only"] != (w is None):
            return None
        _weight(json.dumps(w))
    except (KeyError, ValueError, TypeError):
        return None
    meta = tool_index_meta(store_path, fp)
    if meta is None or meta.get("tool_snapshot") != tools:
        return None
    return rec


def tool_head(store_path: Path) -> str | None:
    """`tools/HEAD` when it names a tool snapshot file that hashes to its id, else None."""
    try:
        sid = (Path(store_path) / "tools" / "HEAD").read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    return sid if tool_snapshot_ok(store_path, sid) else None


def current(store_path: Path, snapshot: str, *, index=_UNSET, applicability=_UNSET,
            dedup=_UNSET, tools=_UNSET, tool_index=_UNSET, tables=_UNSET,
            units=_UNSET) -> Handle:
    """The handle of the store as it is now, at content snapshot `snapshot` (HEAD, as the
    caller read it). A component the caller already knows (what its call used: an active
    record, an overlay id, a tool snapshot id) is given and taken as is; the others are
    read (module docstring)."""
    store_path = Path(store_path)
    if index is _UNSET:
        index = _active_index(store_path, snapshot)
    index_s = _valid(check_index, lambda: encode_index(index["fingerprint"],
                                                         index["system"], index["w"]))
    if applicability is _UNSET:
        applicability = file_sha256(ap.overlay_path(store_path, snapshot))
    if index_s is None:  # no index (or a damaged record of it): no dedup overlay of its chunks
        dedup = None
    elif dedup is _UNSET:
        dedup = dedup_id(store_path, snapshot, index["fingerprint"])
    if tools is _UNSET:
        tools = tool_head(store_path)
    if tool_index is _UNSET:
        tool_index = _active_tool_index(store_path, tools)
    ti = None if tools is None else _valid(check_tool_index, lambda: encode_tool_index(
        tool_index["fingerprint"], tool_index["w"]))
    if tables is _UNSET:
        tables = tables_head(store_path, snapshot)
    if units is _UNSET:
        units = units_head(store_path, snapshot)
    parts = {"applicability": applicability, "dedup": dedup, "tools": tools, "tables": tables,
             "units": units}
    parts = {k: v if isinstance(v, str) and _HEX64.fullmatch(v) else None
             for k, v in parts.items()}
    if parts["tools"] is None:
        ti = None
    return Handle(snapshot=snapshot, index=index_s, tool_index=ti, **parts)


def _valid(validator, encode) -> str | None:
    """`encode()` when it gives a component `validator` accepts, else None (a part the store
    has but whose record is damaged is null in a handle, never an error: `current` serves
    every call, and the call itself decides what a damaged record means)."""
    try:
        v = encode()
        validator(v)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return v


# -- resolving a handle ------------------------------------------------------------------------

def _runs(system: str, meta: dict) -> bool:
    """Whether `adr index <system>` can make an index with these settings (`meta.json`): the
    system's breadcrumb prefix and w_bc rule, and its reranker exactly when the index is
    hybrid (a lexical-only index has none, so a lexical-only `p1-struct-bc-rr` index is a
    lexical-only `p1-struct-bc` one, and either label runs it)."""
    from adr_store.tools import SYSTEMS  # the tools import this module

    spec = SYSTEMS.get(system)
    st = meta["settings"]
    return spec is not None and st.get("prefix") == spec.prefix and \
        st.get("rerank") == (spec.rerank and meta["dense"]) and \
        (spec.tune_w_bc or st.get("w_bc") == 0)


def resolve(store_path: Path, handle: Handle | dict | None) -> Resolved:
    """The parts `handle` names, each checked (module docstring); None: the store now."""
    store_path = Path(store_path)
    if handle is None:
        try:
            snapshot = (store_path / "HEAD").read_text(encoding="utf-8").strip()
            store = Store.open(store_path, snapshot)
        except (OSError, StoreError) as e:
            raise _tool_error(f"{store_path}: no store here ({type(e).__name__})") from e
        handle = current(store_path, snapshot)
    else:
        handle = parse(handle)
        try:
            store = Store.open(store_path, handle.snapshot)
        except (OSError, ValueError, KeyError, StoreError):
            raise unavailable("snapshot") from None
    snap = handle.snapshot
    index = None
    if (parts := handle.index_parts()) is not None:
        fp, system, w = parts
        meta = index_meta(store_path, fp)
        if meta is None:
            raise unavailable("index")
        if meta["snapshot"] != snap:
            raise bad(f"index {fp[:12]} is for snapshot {meta['snapshot'][:12]}, not "
                      f"{snap[:12]}")
        if meta["dense"] == (w is None):
            raise bad(f"index {fp[:12]} is {'hybrid' if meta['dense'] else 'lexical-only'} "
                      f"but the handle gives weight {json.dumps(w)}")
        if not _runs(system, meta):
            raise bad(f"index {fp[:12]} cannot be run as {system} (its settings: "
                      f"{json.dumps(meta['settings'], sort_keys=True)}, "
                      f"{'hybrid' if meta['dense'] else 'lexical-only'})")
        index = {"system": system, "snapshot": snap, "fingerprint": fp,
                 "lexical_only": not meta["dense"], "rerank": meta["settings"]["rerank"],
                 "w": w}
    if handle.applicability is not None and \
            file_sha256(ap.overlay_path(store_path, snap)) != handle.applicability:
        raise unavailable("applicability")
    if handle.dedup is not None:
        if index is None:
            raise bad("a dedup overlay without an index")
        if dedup_id(store_path, snap, index["fingerprint"]) != handle.dedup:
            raise unavailable("dedup")
    if handle.tools is not None and not tool_snapshot_ok(store_path, handle.tools):
        raise unavailable("tools")
    tool_index = None
    if (tparts := handle.tool_index_parts()) is not None:
        fp, w = tparts
        if handle.tools is None:
            raise bad("a tool index without a tool snapshot")
        meta = tool_index_meta(store_path, fp)
        if meta is None:
            raise unavailable("tool_index")
        if meta.get("tool_snapshot") != handle.tools:
            raise bad(f"tool index {fp[:12]} is not for tool snapshot {handle.tools[:12]}")
        if meta["dense"] == (w is None):
            raise bad(f"tool index {fp[:12]} is "
                      f"{'hybrid' if meta['dense'] else 'lexical-only'} but the handle gives "
                      f"weight {json.dumps(w)}")
        tool_index = {"tool_snapshot": handle.tools, "fingerprint": fp,
                      "w_name": meta["w_name"], "lexical_only": not meta["dense"], "w": w}
    if handle.tables is not None:
        m = tables_manifest(store_path, handle.tables)
        if m is None:
            raise unavailable("tables")
        if m.snapshot != snap:
            raise bad(f"tables {handle.tables[:12]} is for snapshot {m.snapshot[:12]}")
    if handle.units is not None:
        um = units_manifest(store_path, handle.units)
        if um is None:
            raise unavailable("units")
        if um.snapshot != snap:
            raise bad(f"units {handle.units[:12]} is for snapshot {um.snapshot[:12]}")
    return Resolved(handle, store, index, handle.applicability, handle.dedup, handle.tools,
                    tool_index, handle.tables, handle.units)
