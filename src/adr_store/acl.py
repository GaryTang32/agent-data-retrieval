"""Permissions as data: the synthetic directory, the policy, the sync cycle and the ACL
snapshot (Phase 2 spec §5.1–§5.3, §5.5).

    config/acl/directory.json                  tenants, groups, users and memberships
    config/acl/policy.json                     salt, sync limits, attribute rules, bucket table
    <store>/acl/snapshots/<acl_snapshot>.json  one ACL snapshot (canonical JSON)
    <store>/acl/HEAD                           the current ACL snapshot id
    <store>/acl/sync.jsonl                     one line per sync cycle, ok or failed

Regenerate the committed directory and policy with `python -m adr_store.acl`.

A principal is `public`, `tenant:<t>`, `group:<t>/<g>` or `user:<id>` (`PRINCIPAL`). A user
resolves to itself, its groups, their tenants and `public` (`principals_of`). There is no
wildcard: the all-access caller `user:auditor` is a member of every group.

Assignment (`assign`). The key of a document is its chain (`applicability.chain_of`, by URI
alone, so every version of a source shares access whether or not an applicability overlay
was written), else its doc id. The policy's attribute rules (match by `format` and/or
`uri_prefix`; the first rule that matches wins; an empty list is "no entry") come first. Else
`bucket(key) = int(SHA-256(salt + "\\nbucket\\n" + key)[:8], 16) mod 100` picks a row of the
bucket table: `public`; `two_tenants`; `tenant`; `group`. The tenant is
`H("tenant") mod n` over the sorted tenants, the second tenant of a shared list
`H("tenant2") mod (n - 1)` over the other tenants (sorted), the group `H("group") mod m` over
the tenant's sorted groups, where `H(x) = int(SHA-256(salt + "\\n" + x + "\\n" + key)[:8], 16)`
(planner's call: the spec fixes only the bucket hash).

A sync cycle (`sync`) reads and validates the directory and the policy, computes the access
list of every document of the store's HEAD content snapshot (refusing a policy whose
attribute rules give the versions of one chain different lists: all versions of a source
share access, `split_chain`; the tools deny F1 to a view that splits a chain; tool records
arrive with the tool catalog in Task 9: until then `tool_snapshot` is null and `tools`
empty), writes the snapshot and atomically replaces `acl/HEAD`. Every failure is logged
and raised as `SyncError`; one before the swap leaves the old HEAD, and the error says
whether HEAD moved (after the swap only reading the clock or appending the sync log can
fail). The snapshot file is written once: an existing file under its id with other bytes is
refused.
The snapshot id is the SHA-256 of its file; it includes `synced_at`, so every sync is a new
version, and `entries_sha256` (directory, docs and tools) is equal for equal inputs. Besides
the fields of §5.3 the snapshot carries the policy's `max_sync_age_s` and `future_skew_s`, so
the freshness check (F3) needs the snapshot alone (planner's call).

Reading (`read_head`) refuses with `AclDenied("F1", ...)` a missing, unreadable, unparsable
or schema-invalid snapshot, or one whose file does not hash to its id. `check_fresh` (F3, the
only clock-dependent decision; the clock is injectable, and a clock that fails or gives a
naive time denies), `caller_principals` (F4, F5) and `check_principals` (F5) are the other
checks. `resolve` is the one entry a tool call makes: it runs every check in that order
(F1, F5 of the snapshot, F2, F3, then F4/F5 of the caller) and returns the caller's `Access`
(the visible documents and tools, and the view id); the tools (`adr_store.tools`) enforce it.
The snapshot file is read and hashed on every call, its parse is cached by id (`cache`).
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import re
import sys
import time
from collections import Counter, OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from adr_eval.corpora import REPO_ROOT
from adr_store.applicability import chain_of
from adr_store.records import Format, canonical_json
from adr_store.store import Store, StoreError, write_atomic

FORMAT_VERSION = "0.1"
SALT = "adr-acl-v1"
MAX_SYNC_AGE_S = 3600
FUTURE_SKEW_S = 300
CONFIG_DIR = REPO_ROOT / "config" / "acl"
DIRECTORY_PATH = CONFIG_DIR / "directory.json"
POLICY_PATH = CONFIG_DIR / "policy.json"
ACL_DIR = "acl"

TENANTS = ("acme", "globex", "initech")
GROUPS_PER_TENANT = 4
USERS_PER_TENANT = 6

_NAME = r"[a-z][a-z0-9-]*"
TENANT_NAME_PATTERN = rf"^{_NAME}$"
GROUP_PATTERN = rf"^group:{_NAME}/[0-9a-z-]+$"
USER_PATTERN = rf"^user:{_NAME}$"
PRINCIPAL_PATTERN = rf"^(public|tenant:{_NAME}|group:{_NAME}/[0-9a-z-]+|user:{_NAME})$"
PRINCIPAL = re.compile(PRINCIPAL_PATTERN)
USER = re.compile(USER_PATTERN)
_HEX64 = r"^[0-9a-f]{64}$"
_ID = re.compile(r"[0-9a-f]{64}")

TenantName = Annotated[str, Field(pattern=TENANT_NAME_PATTERN)]
GroupPrincipal = Annotated[str, Field(pattern=GROUP_PATTERN)]
UserPrincipal = Annotated[str, Field(pattern=USER_PATTERN)]
Principal = Annotated[str, Field(pattern=PRINCIPAL_PATTERN)]
Kind = Literal["public", "two_tenants", "tenant", "group"]


def utc_now() -> datetime:
    return datetime.now(UTC)


def is_principal(s: object) -> bool:
    """Whether `s` is a principal string of the grammar of §5.1 (the whole string)."""
    return isinstance(s, str) and PRINCIPAL.fullmatch(s) is not None


def _dupes(values: list[str]) -> list[str]:
    return sorted(v for v, n in Counter(values).items() if n > 1)


# -- the directory and the policy ------------------------------------------------------------

class Directory(BaseModel):
    """The synthetic directory (§5.2): tenants, groups (group principal -> its tenant) and
    users (user principal -> its groups)."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="AclDirectory")

    format_version: Literal["0.1"]
    tenants: list[TenantName]
    groups: dict[GroupPrincipal, TenantName]
    users: dict[UserPrincipal, list[GroupPrincipal]]

    @model_validator(mode="after")
    def _consistent(self) -> Directory:
        if dupes := _dupes(self.tenants):
            raise ValueError(f"duplicate tenant(s): {', '.join(dupes)}")
        for group, tenant in self.groups.items():
            if tenant not in self.tenants:
                raise ValueError(f"{group}: unknown tenant {tenant!r}")
            if group.removeprefix("group:").split("/")[0] != tenant:
                raise ValueError(f"{group}: is not a group of its tenant {tenant!r}")
        for user, groups in self.users.items():
            if unknown := sorted(set(groups) - set(self.groups)):
                raise ValueError(f"{user}: unknown group(s) {', '.join(unknown)}")
            if dupes := _dupes(groups):
                raise ValueError(f"{user}: group(s) listed twice: {', '.join(dupes)}")
        return self


class RuleMatch(BaseModel):
    """What an attribute rule matches: every condition given must hold."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="RuleMatch")

    format: Format | None = None
    uri_prefix: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _something(self) -> RuleMatch:
        if self.format is None and self.uri_prefix is None:
            raise ValueError("a rule must match on format, uri_prefix or both")
        return self


class AttributeRule(BaseModel):
    """An ordered attribute rule: documents it matches get exactly `access` (`[]`: no one)."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="AttributeRule")

    match: RuleMatch
    access: list[Principal]

    @model_validator(mode="after")
    def _unique(self) -> AttributeRule:
        if dupes := _dupes(self.access):
            raise ValueError(f"principal(s) listed twice: {', '.join(dupes)}")
        return self


class Bucket(BaseModel):
    """A row of the bucket table: buckets below `below` (and at or above the previous row's)
    get an access list of this kind."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="Bucket")

    below: int = Field(ge=1, le=100)
    access: Kind


class Policy(BaseModel):
    """The assignment policy (§5.2): the salt of every hash, the sync limits (F3), the
    attribute rules (applied first, in order) and the bucket table."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="AclPolicy")

    format_version: Literal["0.1"]
    salt: str = Field(min_length=1)
    max_sync_age_s: int = Field(gt=0)
    future_skew_s: int = Field(ge=0)
    rules: list[AttributeRule]
    buckets: list[Bucket] = Field(min_length=1)

    @model_validator(mode="after")
    def _table(self) -> Policy:
        bounds = [b.below for b in self.buckets]
        if any(a >= b for a, b in zip(bounds, bounds[1:], strict=False)):
            raise ValueError(f"bucket bounds must increase: {bounds}")
        if bounds[-1] != 100:
            raise ValueError(f"the last bucket bound must be 100, got {bounds[-1]}")
        return self


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    keys = [k for k, _ in pairs]
    if dupes := _dupes(keys):
        raise ValueError(f"duplicate key(s): {', '.join(dupes)}")
    return dict(pairs)


def _parse(data: bytes | str, model: type[BaseModel]):
    """`model` from JSON text; any problem (not JSON, a duplicate key, the schema) is a
    ValueError."""
    if isinstance(data, bytes):
        data = data.decode("utf-8")  # UnicodeDecodeError is a ValueError
    obj = json.loads(data, object_pairs_hook=_no_duplicate_keys)
    return model.model_validate(obj)


def parse_directory(data: bytes | str) -> Directory:
    return _parse(data, Directory)


def parse_policy(data: bytes | str) -> Policy:
    return _parse(data, Policy)


def default_directory() -> Directory:
    """The synthetic directory of §5.2: user k of a tenant is in group k mod 4, users 4 and 5
    also in group (k + 1) mod 4; `user:auditor` in every group; `user:outsider` in none."""
    groups = {f"group:{t}/{g}": t for t in TENANTS for g in range(GROUPS_PER_TENANT)}
    users: dict[str, list[str]] = {}
    for t in TENANTS:
        for k in range(USERS_PER_TENANT):
            gs = {k % GROUPS_PER_TENANT}
            if k >= GROUPS_PER_TENANT:
                gs.add((k + 1) % GROUPS_PER_TENANT)
            users[f"user:{t}-{k}"] = sorted(f"group:{t}/{g}" for g in gs)
    users["user:auditor"] = sorted(groups)
    users["user:outsider"] = []
    return Directory(format_version=FORMAT_VERSION, tenants=list(TENANTS), groups=groups,
                     users=dict(sorted(users.items())))


def default_policy() -> Policy:
    """The shipped policy: no attribute rules, the bucket table of §5.2."""
    return Policy(format_version=FORMAT_VERSION, salt=SALT, max_sync_age_s=MAX_SYNC_AGE_S,
                  future_skew_s=FUTURE_SKEW_S, rules=[],
                  buckets=[Bucket(below=20, access="public"),
                           Bucket(below=30, access="two_tenants"),
                           Bucket(below=75, access="tenant"),
                           Bucket(below=100, access="group")])


def render_config(model: BaseModel) -> str:
    """The exact text of a committed config file (indented, sorted keys, one newline)."""
    return json.dumps(model.model_dump(mode="json"), indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"


def write_config(out_dir: Path = CONFIG_DIR) -> list[Path]:
    """Write the generated directory and policy into `out_dir`; returns the paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in (("directory.json", default_directory()),
                        ("policy.json", default_policy())):
        path = out_dir / name
        path.write_text(render_config(model), encoding="utf-8")
        written.append(path)
    return written


# -- principals and assignment ---------------------------------------------------------------

def principals_of(directory: Directory, user: str) -> frozenset[str]:
    """A user's principal set: itself, its groups, their tenants and `public` (KeyError for a
    user not in the directory)."""
    groups = directory.users[user]
    tenants = {f"tenant:{directory.groups[g]}" for g in groups}
    return frozenset({user, "public", *groups, *tenants})


def _h(salt: str, what: str, key: str) -> int:
    return int(hashlib.sha256(f"{salt}\n{what}\n{key}".encode()).hexdigest()[:8], 16)


def bucket(key: str, salt: str = SALT) -> int:
    """The bucket of a key: `int(SHA-256(salt + "\\nbucket\\n" + key)[:8], 16) mod 100`."""
    return _h(salt, "bucket", key) % 100


def assign(key: str, attrs: dict, policy: Policy, directory: Directory
           ) -> tuple[str, list[str]]:
    """(kind, sorted access list) of a key: `rule` when an attribute rule matched `attrs`
    (`format`, `uri`), else the bucket table's kind. ValueError when the directory lacks what
    the kind needs (a tenant, a second tenant, a group of the tenant)."""
    for rule in policy.rules:
        m = rule.match
        if m.format is not None and attrs.get("format") != m.format:
            continue
        if m.uri_prefix is not None and not str(attrs.get("uri", "")).startswith(m.uri_prefix):
            continue
        return "rule", sorted(rule.access)
    b = bucket(key, policy.salt)
    kind = next(row.access for row in policy.buckets if b < row.below)
    if kind == "public":
        return kind, ["public"]
    tenants = sorted(directory.tenants)
    if not tenants:
        raise ValueError(f"{key}: bucket {b} ({kind}) needs a tenant; the directory has none")
    t1 = tenants[_h(policy.salt, "tenant", key) % len(tenants)]
    if kind == "tenant":
        return kind, [f"tenant:{t1}"]
    if kind == "two_tenants":
        others = [t for t in tenants if t != t1]
        if not others:
            raise ValueError(f"{key}: bucket {b} (two_tenants) needs two tenants")
        t2 = others[_h(policy.salt, "tenant2", key) % len(others)]
        return kind, sorted([f"tenant:{t1}", f"tenant:{t2}"])
    groups = sorted(g for g, t in directory.groups.items() if t == t1)
    if not groups:
        raise ValueError(f"{key}: bucket {b} (group) needs a group of tenant {t1}")
    return kind, [groups[_h(policy.salt, "group", key) % len(groups)]]


def access_list(key: str, attrs: dict, policy: Policy, directory: Directory) -> list[str]:
    """The sorted access list of a key (`assign` without the kind)."""
    return assign(key, attrs, policy, directory)[1]


# -- the snapshot ----------------------------------------------------------------------------

def entries_sha256(directory: dict, docs: dict, tools: dict) -> str:
    """SHA-256 of the canonical JSON (sorted keys, compact, UTF-8) of the access entries."""
    payload = json.dumps({"directory": directory, "docs": docs, "tools": tools},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AclSnapshot(BaseModel):
    """The content of `<store>/acl/snapshots/<id>.json` (§5.3). Principal strings are not
    checked here: an off-grammar one is F5 (`check_principals`), not a schema error."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="AclSnapshot")

    format_version: Literal["0.1"]
    sequence: int = Field(ge=1)
    synced_at: datetime
    content_snapshot: str = Field(pattern=_HEX64)
    tool_snapshot: str | None = Field(pattern=_HEX64)
    directory_sha256: str = Field(pattern=_HEX64)
    policy_sha256: str = Field(pattern=_HEX64)
    max_sync_age_s: int = Field(gt=0)
    future_skew_s: int = Field(ge=0)
    directory: dict[str, list[str]]
    docs: dict[str, list[str]]
    tools: dict[str, list[str]]
    entries_sha256: str = Field(pattern=_HEX64)

    @model_validator(mode="after")
    def _checks(self) -> AclSnapshot:
        offset = self.synced_at.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError(f"synced_at {self.synced_at.isoformat()} is not UTC")
        if entries_sha256(self.directory, self.docs, self.tools) != self.entries_sha256:
            raise ValueError("entries_sha256 is not the hash of directory, docs and tools")
        return self


class AclDenied(Exception):
    """No access for the whole call, for one of the fail-closed reasons F1–F5 of §5.4.
    `acl_snapshot` is the snapshot that was read (None for F1)."""

    def __init__(self, code: Literal["F1", "F2", "F3", "F4", "F5"], reason: str,
                 acl_snapshot: str | None = None):
        super().__init__(f"access denied ({code}): {reason}")
        self.code, self.reason, self.acl_snapshot = code, reason, acl_snapshot


class SyncError(StoreError):
    """A sync cycle failed. `head_moved` says whether `acl/HEAD` was replaced before the
    failure (only a failure after the swap: reading the clock, or appending the sync log);
    otherwise `acl/HEAD` is unchanged. The message says which."""

    def __init__(self, message: str, head_moved: bool = False):
        super().__init__(message)
        self.head_moved = head_moved


def acl_dir(store_path: Path) -> Path:
    return Path(store_path) / ACL_DIR


def snapshot_path(store_path: Path, acl_snapshot: str) -> Path:
    return acl_dir(store_path) / "snapshots" / f"{acl_snapshot}.json"


def read_head(store_path: Path, cache: dict | None = None) -> tuple[str, AclSnapshot]:
    """(id, snapshot) of `acl/HEAD`; AclDenied F1 if it is missing, unreadable, unparsable,
    schema-invalid, or its file does not hash to its id. The file is read and hashed every
    time; with `cache` (id -> snapshot) a snapshot already parsed under that id is reused."""
    head = acl_dir(store_path) / "HEAD"
    try:
        text = head.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise AclDenied("F1", "no ACL snapshot (acl/HEAD missing); run `adr acl sync`") from None
    except (OSError, ValueError) as e:
        raise AclDenied("F1", f"acl/HEAD unreadable ({type(e).__name__})") from e
    sid = text.strip()
    if not _ID.fullmatch(sid):
        raise AclDenied("F1", f"acl/HEAD holds {sid[:20]!r}, not an ACL snapshot id")
    try:
        data = snapshot_path(store_path, sid).read_bytes()
    except OSError as e:
        raise AclDenied("F1", f"ACL snapshot {sid[:12]} unreadable ({type(e).__name__})") from e
    if hashlib.sha256(data).hexdigest() != sid:
        raise AclDenied("F1", f"ACL snapshot {sid[:12]}: the file's hash is not its id")
    if cache is not None and sid in cache:
        return sid, cache[sid]
    try:
        json.loads(data)
    except (ValueError, RecursionError) as e:
        raise AclDenied("F1", f"ACL snapshot {sid[:12]} unparsable ({type(e).__name__})") from e
    try:
        snap = AclSnapshot.model_validate_json(data)
    except ValidationError as e:
        err = e.errors()[0]
        where = ".".join(str(x) for x in err["loc"]) or "(root)"
        raise AclDenied("F1", f"ACL snapshot {sid[:12]} schema-invalid: {where}: "
                              f"{err['msg']}") from e
    if cache is not None:
        cache[sid] = snap
    return sid, snap


def check_fresh(snapshot: AclSnapshot, *, clock: Callable[[], datetime] = utc_now) -> None:
    """AclDenied F3 when `now - synced_at` exceeds `max_sync_age_s` or `synced_at` is more
    than `future_skew_s` in the future; also F3 when the clock fails or gives anything but a
    timezone-aware datetime (no time, no freshness)."""
    try:
        now = clock()
    except Exception as e:  # any failure of the clock denies
        raise AclDenied("F3", f"the clock failed ({type(e).__name__}); freshness unknown") from e
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise AclDenied("F3", f"the clock gave {type(now).__name__} {str(now)[:40]!r}, not a "
                              f"timezone-aware datetime; freshness unknown")
    age = (now - snapshot.synced_at).total_seconds()
    if age > snapshot.max_sync_age_s:
        raise AclDenied("F3", f"the ACL snapshot is {age:.0f} s old, older than "
                              f"max_sync_age_s {snapshot.max_sync_age_s}; run `adr acl sync`")
    if -age > snapshot.future_skew_s:
        raise AclDenied("F3", f"the ACL snapshot's synced_at is {-age:.0f} s in the future "
                              f"(more than future_skew_s {snapshot.future_skew_s})")


def caller_principals(snapshot: AclSnapshot, caller: str | None) -> tuple[str, ...]:
    """The caller's resolved principal set (sorted); AclDenied F4 for no caller or one not
    in the snapshot's directory, F5 for a caller that is not a `user:` principal."""
    if caller is None:
        raise AclDenied("F4", "no caller given")
    if not isinstance(caller, str) or USER.fullmatch(caller) is None:
        raise AclDenied("F5", f"caller {str(caller)[:40]!r} is not a user principal")
    if caller not in snapshot.directory:
        raise AclDenied("F4", f"caller {caller} is not in the ACL snapshot's directory")
    return tuple(sorted(snapshot.directory[caller]))


def check_principals(snapshot: AclSnapshot) -> None:
    """AclDenied F5 when a directory key is not a `user:` principal or any principal string
    of the snapshot is off the grammar of §5.1."""
    for user, principals in snapshot.directory.items():
        if USER.fullmatch(user) is None:
            raise AclDenied("F5", f"directory entry {user[:40]!r} is not a user principal")
        for p in principals:
            if not is_principal(p):
                raise AclDenied("F5", f"off-grammar principal {p[:40]!r} in the directory")
    for what, entries in (("docs", snapshot.docs), ("tools", snapshot.tools)):
        for principals in entries.values():
            for p in principals:
                if not is_principal(p):
                    raise AclDenied("F5", f"off-grammar principal {p[:40]!r} in {what}")


# -- a tool call's access ---------------------------------------------------------------------

def view_id(docs) -> str:
    """The id of a view: SHA-256 of the sorted visible doc ids joined by newlines."""
    return hashlib.sha256("\n".join(sorted(docs)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Access:
    """What one call may see: the caller's resolved principals under one ACL snapshot, the
    documents and tools whose access list meets them (no entry or an empty list: no one),
    and the view id (`view_id` of `docs`)."""

    acl_snapshot: str
    caller: str
    principals: tuple[str, ...]
    docs: frozenset[str]
    tools: frozenset[str]
    view: str


def _visible(entries: dict[str, list[str]], principals: frozenset[str]) -> frozenset[str]:
    return frozenset(k for k, ps in entries.items() if not principals.isdisjoint(ps))


def chains(store: Store) -> dict[str, tuple[str, ...]]:
    """The chains of the store's snapshot that hold two or more documents: the assignment
    key (`applicability.chain_of`) -> its sorted doc ids."""
    members: dict[str, list[str]] = {}
    for doc_id in store.doc_ids():
        key = chain_of(store.source(doc_id))
        if key is not None:
            members.setdefault(key, []).append(doc_id)
    return {k: tuple(sorted(v)) for k, v in sorted(members.items()) if len(v) > 1}


def split_chain(chain_map: dict[str, tuple[str, ...]], docs: frozenset[str]) -> str | None:
    """The first chain of which `docs` holds some but not all documents, or None. All
    versions of a source share access (§5.2): a view that splits a chain would see chain
    fields (superseded_by, valid_to) computed from versions it cannot see."""
    for key, members in chain_map.items():
        n = sum(d in docs for d in members)
        if 0 < n < len(members):
            return key
    return None


def _check_chains(members: dict[str, list[str]], docs: dict[str, list[str]]) -> None:
    """SyncError when the versions of one chain got different access lists."""
    for key, ids in sorted(members.items()):
        lists = {d: docs[d] for d in sorted(ids)}
        if len({tuple(v) for v in lists.values()}) > 1:
            shown = "; ".join(f"{d}: {v}" for d, v in lists.items())
            raise SyncError(f"the policy gives the versions of chain {key} different access "
                            f"lists ({shown}); all versions of a source share access (spec "
                            f"§5.2): make the rule cover the whole chain")


SNAPSHOT_CACHE = 4  # parsed snapshots `resolve` keeps per cache


def resolve(store_path: Path, caller: str | None, content_snapshot: str, *,
            clock: Callable[[], datetime] = utc_now, cache: OrderedDict | None = None
            ) -> Access:
    """The access of one call by `caller` to the store at `store_path` whose HEAD content
    snapshot is `content_snapshot`, or AclDenied: F1 (`read_head`), F5 (`check_principals`),
    F2 (the snapshot is for another content snapshot), F3 (`check_fresh`), F4/F5
    (`caller_principals`), in that order. `cache` (an OrderedDict kept by the caller) holds
    the last `SNAPSHOT_CACHE` parsed snapshots and their F5 verdict, by id."""
    parsed: dict = {} if cache is None else {k: v[0] for k, v in cache.items()}
    sid, snap = read_head(store_path, parsed)
    if cache is not None and sid in cache:
        cache.move_to_end(sid)
        f5 = cache[sid][1]
    else:
        try:
            check_principals(snap)
            f5 = None
        except AclDenied as e:
            f5 = e
        if cache is not None:
            cache[sid] = (snap, f5)
            while len(cache) > SNAPSHOT_CACHE:
                cache.popitem(last=False)
    try:
        if f5 is not None:
            raise AclDenied(f5.code, f5.reason)
        if snap.content_snapshot != content_snapshot:
            raise AclDenied("F2", f"the ACL snapshot {sid[:12]} is for content snapshot "
                                  f"{snap.content_snapshot[:12]}, the store is at "
                                  f"{str(content_snapshot)[:12]}; run `adr acl sync`")
        check_fresh(snap, clock=clock)
        principals = caller_principals(snap, caller)
    except AclDenied as e:
        e.acl_snapshot = sid
        raise
    ps = frozenset(principals)
    docs = _visible(snap.docs, ps)
    return Access(acl_snapshot=sid, caller=caller, principals=principals, docs=docs,
                  tools=_visible(snap.tools, ps), view=view_id(docs))


# -- the sync cycle --------------------------------------------------------------------------

@dataclass(frozen=True)
class SyncResult:
    acl_snapshot: str
    sequence: int
    entries_sha256: str
    changed: bool
    duration_s: float
    lag_s: float
    previous: str | None
    content_snapshot: str
    tool_snapshot: str | None
    path: str
    documents: int
    kinds: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _aware(t: datetime) -> datetime:
    if t.utcoffset() is None:
        raise ValueError(f"the clock gave a naive datetime {t.isoformat()}")
    return t.astimezone(UTC)


def _read_config(path: Path, parse, what: str):
    """(model, SHA-256 of the file, mtime) of a config file; SyncError names the file."""
    path = Path(path)
    try:
        mtime = path.stat().st_mtime
        data = path.read_bytes()
    except OSError as e:
        raise SyncError(f"cannot read the {what} {path}: {type(e).__name__}: "
                        f"{e.strerror or e}") from e
    try:
        model = parse(data)
    except ValidationError as e:
        err = e.errors()[0]
        where = ".".join(str(x) for x in err["loc"]) or "(root)"
        raise SyncError(f"invalid {what} {path}: {where}: {err['msg']}") from e
    except ValueError as e:
        raise SyncError(f"invalid {what} {path}: {' '.join(str(e).split())}") from e
    return model, hashlib.sha256(data).hexdigest(), mtime


def _previous(store_path: Path) -> tuple[str | None, str | None, int]:
    """(id, entries_sha256, sequence) of the current HEAD; when HEAD cannot be read, no id
    and the highest sequence among the snapshot files, so sequences keep increasing."""
    try:
        sid, snap = read_head(store_path)
        return sid, snap.entries_sha256, snap.sequence
    except AclDenied:
        pass
    best = 0
    for p in sorted((acl_dir(store_path) / "snapshots").glob("*.json")):
        try:
            seq = json.loads(p.read_bytes()).get("sequence")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(seq, int) and not isinstance(seq, bool):
            best = max(best, seq)
    return None, None, best


def _append(path: Path, line: dict) -> None:
    with open(path, "ab") as f:
        f.write((json.dumps(line, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))


def write_once(path: Path, data: bytes) -> None:
    """Write `data` to `path` unless the file exists; an existing file with other bytes is
    refused (StoreError), the same bytes are a no-op (the shared write-once rule)."""
    path = Path(path)
    if path.exists():
        if path.read_bytes() != data:
            raise StoreError(f"{path} already holds other bytes under this snapshot id; it is "
                             f"not replaced")
        return
    write_atomic(path, data)


def sync(store_path: Path, directory_path: Path = DIRECTORY_PATH,
         policy_path: Path = POLICY_PATH, *, clock: Callable[[], datetime] = utc_now
         ) -> SyncResult:
    """One sync cycle over the store's HEAD content snapshot (module docstring), serialized
    by an exclusive `flock` on `acl/sync.lock`. Raises SyncError (the failure logged; HEAD
    unchanged unless `head_moved`) or StoreError (no store)."""
    store_path = Path(store_path)
    store = Store.open(store_path)
    adir = acl_dir(store_path)
    adir.mkdir(parents=True, exist_ok=True)
    with open(adir / "sync.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _sync_locked(store, adir, Path(directory_path), Path(policy_path), clock)


def _sync_locked(store: Store, adir: Path, directory_path: Path, policy_path: Path,
                 clock: Callable[[], datetime]) -> SyncResult:
    t0 = time.perf_counter()
    line: dict = {"started": None, "finished": None, "duration_s": None,
                  "lag_s": None, "sequence": None, "acl_snapshot": None, "previous": None,
                  "content_snapshot": store.snapshot_id, "tool_snapshot": None,
                  "directory_sha256": None, "policy_sha256": None, "entries_sha256": None,
                  "changed": None, "outcome": "error", "error": None}
    sid = None  # set once acl/HEAD names the new snapshot
    try:
        line["started"] = _iso(_aware(clock()))
        directory, dir_sha, dir_mtime = _read_config(directory_path, parse_directory,
                                                     "directory")
        line["directory_sha256"] = dir_sha
        policy, pol_sha, pol_mtime = _read_config(policy_path, parse_policy, "policy")
        line["policy_sha256"] = pol_sha
        previous, prev_entries, prev_seq = _previous(store.path)
        line["previous"] = previous
        docs: dict[str, list[str]] = {}
        kinds: Counter[str] = Counter()
        members: dict[str, list[str]] = {}
        for doc_id in store.doc_ids():
            source = store.source(doc_id)
            key = chain_of(source)
            if key is not None:
                members.setdefault(key, []).append(doc_id)
            kind, docs[doc_id] = assign(key or doc_id,
                                        {"format": source.format, "uri": source.uri},
                                        policy, directory)
            kinds[kind] += 1
        _check_chains(members, docs)
        users = {u: sorted(principals_of(directory, u)) for u in sorted(directory.users)}
        tools: dict[str, list[str]] = {}
        entries = entries_sha256(users, docs, tools)
        snap = AclSnapshot(
            format_version=FORMAT_VERSION, sequence=prev_seq + 1, synced_at=_aware(clock()),
            content_snapshot=store.snapshot_id, tool_snapshot=None, directory_sha256=dir_sha,
            policy_sha256=pol_sha, max_sync_age_s=policy.max_sync_age_s,
            future_skew_s=policy.future_skew_s, directory=users, docs=docs, tools=tools,
            entries_sha256=entries)
        line.update(sequence=snap.sequence, entries_sha256=entries,
                    changed=entries != prev_entries)
        data = canonical_json(snap)
        new_sid = hashlib.sha256(data).hexdigest()
        path = snapshot_path(store.path, new_sid)
        write_once(path, data)
        write_atomic(adir / "HEAD", f"{new_sid}\n".encode())
        sid = new_sid
        swapped = _aware(clock())
    except Exception as e:  # every failure is logged and named; HEAD moved only if sid is set
        msg = str(e) if isinstance(e, SyncError) else f"{type(e).__name__}: {e}"
        try:
            finished = _iso(_aware(clock()))
        except Exception:  # the clock itself may be what failed
            finished = None
        line.update(finished=finished, duration_s=round(time.perf_counter() - t0, 6),
                    error=msg, acl_snapshot=sid)
        try:
            _append(adir / "sync.jsonl", line)
        except OSError:
            pass
        if sid is None:
            raise SyncError(f"ACL sync failed, acl/HEAD unchanged: {msg}") from e
        raise SyncError(f"ACL sync failed after acl/HEAD moved to {sid[:12]} (the new snapshot "
                        f"is in force): {msg}", head_moved=True) from e
    duration = round(time.perf_counter() - t0, 6)
    lag = round(swapped.timestamp() - max(dir_mtime, pol_mtime), 6)
    line.update(finished=_iso(swapped), duration_s=duration, lag_s=lag, acl_snapshot=sid,
                outcome="ok")
    try:
        _append(adir / "sync.jsonl", line)
    except OSError as e:
        raise SyncError(f"acl/HEAD moved to {sid[:12]} (the new snapshot is in force), but the "
                        f"sync log could not be written: {type(e).__name__}: {e}",
                        head_moved=True) from e
    return SyncResult(acl_snapshot=sid, sequence=snap.sequence, entries_sha256=entries,
                      changed=line["changed"], duration_s=duration, lag_s=lag,
                      previous=previous, content_snapshot=store.snapshot_id,
                      tool_snapshot=None, path=str(path), documents=len(docs),
                      kinds={k: kinds[k] for k in ("public", "two_tenants", "tenant", "group",
                                                   "rule")})


if __name__ == "__main__":
    for p in write_config(Path(sys.argv[1]) if len(sys.argv) > 1 else CONFIG_DIR):
        print(p)
