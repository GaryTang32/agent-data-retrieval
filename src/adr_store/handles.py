"""Snapshot handles (Phase 2 spec §9.2): which versions of the store's parts a tool call ran on,
so a later call can run on exactly the same ones.

    {"snapshot": <content snapshot id>,
     "index": "<index fingerprint>:<system>:<w>" | null,
     "applicability": <applicability overlay id> | null,
     "dedup": <dedup overlay id> | null,
     "tools": <tool snapshot id> | null,
     "tool_index": "<tool index fingerprint>:<w>" | null}

Every result of the five tool calls (`adr_store.tools`) carries one, and every tool call takes
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
  tool snapshot id.
- The ACL snapshot is never part of a handle (ruling R15): every call is judged against the
  current ACL, whatever its handle names (`adr_store.tools`).

`resolve(store_path, None)` is the store as it is now (`current`): HEAD, the active index when
`index/active.json` names a saved index of that snapshot, the overlays of that snapshot (of
that index's chunks for dedup), `tools/HEAD` and the active tool index of that tool snapshot;
a part that is missing or does not belong to the others is null. `resolve(store_path,
handle)` checks that every part the handle names still exists, byte for byte (a file that no
longer hashes to its id, or a deleted index directory, is gone), and refuses with
"handle no longer available: <component>" otherwise; parts that do not belong together (an
index of another snapshot, a dedup overlay without an index, a tool index of another tool
snapshot, a weight that contradicts the index) are a "bad handle". There is no fallback to
HEAD. Resolving writes nothing and keeps no state: caches here are keyed by file versions
(`_stat_key`) or by immutable ids, so they never change an answer.
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

HEX64 = r"^[0-9a-f]{64}$"
_HEX64 = re.compile(HEX64)
_INDEX = re.compile(r"^([0-9a-f]{64}):([a-z0-9][a-z0-9-]*):(.+)$")
_TOOL_INDEX = re.compile(r"^([0-9a-f]{64}):(.+)$")
UNAVAILABLE = "handle no longer available: {}"
COMPONENTS = ("snapshot", "index", "applicability", "dedup", "tools", "tool_index")


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


class Handle(BaseModel):
    """A snapshot handle. Every field is required (null: the store had no such part)."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="Handle")

    snapshot: str = Field(pattern=HEX64, description="content snapshot id")
    index: str | None = Field(description="'<index fingerprint>:<system>:<w>' (w: a JSON "
                                          "number, or null for a lexical-only index)")
    applicability: str | None = Field(pattern=HEX64, description="applicability overlay id")
    dedup: str | None = Field(pattern=HEX64, description="dedup overlay id")
    tools: str | None = Field(pattern=HEX64, description="tool snapshot id")
    tool_index: str | None = Field(description="'<tool index fingerprint>:<w>'")

    @field_validator("index")
    @classmethod
    def _index(cls, v: str | None) -> str | None:
        if v is not None:
            m = _INDEX.fullmatch(v)
            if m is None:
                raise ValueError("expected '<64 hex characters>:<system>:<weight>'")
            _weight(m.group(3))
        return v

    @field_validator("tool_index")
    @classmethod
    def _tool_index(cls, v: str | None) -> str | None:
        if v is not None:
            m = _TOOL_INDEX.fullmatch(v)
            if m is None:
                raise ValueError("expected '<64 hex characters>:<weight>'")
            _weight(m.group(2))
        return v

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
        raise bad(f"expected an object with the fields {', '.join(COMPONENTS)}, got "
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
    """The id of the dedup overlay of an index's chunks (the SHA-256 of its file), or None."""
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
            dedup=_UNSET, tools=_UNSET, tool_index=_UNSET) -> Handle:
    """The handle of the store as it is now, at content snapshot `snapshot` (HEAD, as the
    caller read it). A component the caller already knows (what its call used: an active
    record, an overlay id, a tool snapshot id) is given and taken as is; the others are
    read (module docstring)."""
    store_path = Path(store_path)
    if index is _UNSET:
        index = _active_index(store_path, snapshot)
    index_s = None if index is None else encode_index(index["fingerprint"], index["system"],
                                                      index["w"])
    if applicability is _UNSET:
        applicability = file_sha256(ap.overlay_path(store_path, snapshot))
    if dedup is _UNSET:
        dedup = None if index is None else dedup_id(store_path, snapshot, index["fingerprint"])
    if tools is _UNSET:
        tools = tool_head(store_path)
    if tool_index is _UNSET:
        tool_index = _active_tool_index(store_path, tools)
    ti = None if tool_index is None else encode_tool_index(tool_index["fingerprint"],
                                                           tool_index["w"])
    return Handle(snapshot=snapshot, index=index_s, applicability=applicability, dedup=dedup,
                  tools=tools, tool_index=ti)


# -- resolving a handle ------------------------------------------------------------------------

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
    return Resolved(handle, store, index, handle.applicability, handle.dedup, handle.tools,
                    tool_index)
