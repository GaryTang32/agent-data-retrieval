"""ACL directory, policy, sync cycle and snapshot (Phase 2 spec §5.1–§5.3, §5.5, §12
Permissions: schemas; bucket assignment stable and chains share access)."""

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from adr_store import acl, cli, records
from adr_store.acl import AclDenied, Directory, Policy
from adr_store.store import Store, StoreError
from tests.store.test_applicability import (
    FINAL,
    IRM,
    LOOSE,
    V2024,
    V2025,
    V2026,
    doc_id,
)
from tests.store.test_applicability import make_store as make_gov_store

REPO = Path(__file__).parents[2]
T0 = datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)


def fixed(t: datetime = T0):
    return lambda: t


@pytest.fixture
def store(tmp_path) -> Store:
    return make_gov_store(tmp_path / "store")


@pytest.fixture
def config(tmp_path) -> tuple[Path, Path]:
    """Copies of the committed directory and policy, safe to edit."""
    d = tmp_path / "config"
    d.mkdir()
    for name in ("directory.json", "policy.json"):
        (d / name).write_bytes((REPO / "config" / "acl" / name).read_bytes())
    return d / "directory.json", d / "policy.json"


def sync(store, config, **kw):
    return acl.sync(store.path, config[0], config[1], **kw)


def dir_dict() -> dict:
    return json.loads(acl.render_config(acl.default_directory()))


def policy_dict() -> dict:
    return json.loads(acl.render_config(acl.default_policy()))


# -- the directory -------------------------------------------------------------------------

def test_the_synthetic_directory_of_the_spec():
    d = acl.default_directory()
    assert d.tenants == ["acme", "globex", "initech"]
    assert len(d.groups) == 12 and d.groups["group:initech/3"] == "initech"
    assert len(d.users) == 20
    assert d.users["user:acme-0"] == ["group:acme/0"]
    assert d.users["user:globex-3"] == ["group:globex/3"]
    assert d.users["user:acme-4"] == ["group:acme/0", "group:acme/1"]
    assert d.users["user:initech-5"] == ["group:initech/1", "group:initech/2"]
    assert d.users["user:auditor"] == sorted(d.groups)
    assert d.users["user:outsider"] == []
    assert "user:ghost" not in d.users


def test_principals_of_a_user():
    d = acl.default_directory()
    assert acl.principals_of(d, "user:acme-4") == frozenset(
        {"user:acme-4", "group:acme/0", "group:acme/1", "tenant:acme", "public"})
    assert acl.principals_of(d, "user:outsider") == frozenset({"user:outsider", "public"})
    auditor = acl.principals_of(d, "user:auditor")
    assert len(auditor) == 1 + 12 + 3 + 1
    with pytest.raises(KeyError):
        acl.principals_of(d, "user:ghost")


def test_committed_config_equals_the_generated_files():
    assert (REPO / "config/acl/directory.json").read_text(encoding="utf-8") == \
        acl.render_config(acl.default_directory())
    assert (REPO / "config/acl/policy.json").read_text(encoding="utf-8") == \
        acl.render_config(acl.default_policy())


def test_write_config_writes_both_files(tmp_path):
    written = acl.write_config(tmp_path)
    assert sorted(p.name for p in written) == ["directory.json", "policy.json"]
    assert acl.parse_directory((tmp_path / "directory.json").read_bytes()) == \
        acl.default_directory()
    assert acl.parse_policy((tmp_path / "policy.json").read_bytes()) == acl.default_policy()


@pytest.mark.parametrize("edit", [
    lambda d: d["groups"].update({"group:Acme/9": "acme"}),            # bad principal
    lambda d: d["users"].update({"user:Bob": []}),                       # bad principal
    lambda d: d["users"].update({"user:x": ["tenant:acme"]}),            # not a group
    lambda d: d["users"].update({"user:x": ["group:acme/9"]}),           # unknown group
    lambda d: d["users"].update({"user:x": ["group:acme/0", "group:acme/0"]}),
    lambda d: d["groups"].update({"group:umbrella/0": "umbrella"}),      # unknown tenant
    lambda d: d["groups"].update({"group:acme/9": "globex"}),            # wrong tenant
    lambda d: d["tenants"].append("acme"),                               # duplicate tenant
    lambda d: d["tenants"].append("Bad"),
    lambda d: d.update({"extra": 1}),
])
def test_an_invalid_directory_is_refused(edit):
    d = dir_dict()
    edit(d)
    with pytest.raises(ValueError):
        acl.parse_directory(json.dumps(d))


def test_a_duplicate_user_is_refused():
    text = json.dumps(dir_dict())
    dup = text.replace('"user:acme-1":', '"user:acme-0": ["group:acme/1"], "user:acme-1":')
    assert dup != text
    with pytest.raises(ValueError, match="duplicate"):
        acl.parse_directory(dup)


def test_unparsable_config_is_a_value_error():
    with pytest.raises(ValueError):
        acl.parse_directory(b"{not json")
    with pytest.raises(ValueError):
        acl.parse_policy(b"\xff")


# -- the policy ----------------------------------------------------------------------------

def test_the_shipped_policy():
    p = acl.default_policy()
    assert (p.salt, p.max_sync_age_s, p.future_skew_s, p.rules) == ("adr-acl-v1", 3600, 300, [])
    assert [(b.below, b.access) for b in p.buckets] == [
        (20, "public"), (30, "two_tenants"), (75, "tenant"), (100, "group")]


@pytest.mark.parametrize("edit", [
    lambda p: p["buckets"].pop(),                                        # does not reach 100
    lambda p: p["buckets"].insert(1, {"below": 10, "access": "tenant"}),  # not increasing
    lambda p: p["buckets"][0].update({"access": "everyone"}),
    lambda p: p["rules"].append({"match": {}, "access": ["public"]}),     # matches nothing
    lambda p: p["rules"].append({"match": {"format": "docx"}, "access": ["public"]}),
    lambda p: p["rules"].append({"match": {"format": "pdf"}, "access": ["tenant:"]}),
    lambda p: p["rules"].append({"match": {"format": "pdf"}, "access": ["*"]}),
    lambda p: p["rules"].append({"match": {"format": "pdf"},
                                 "access": ["public", "public"]}),
    lambda p: p.update({"max_sync_age_s": 0}),
    lambda p: p.update({"salt": ""}),
])
def test_an_invalid_policy_is_refused(edit):
    p = policy_dict()
    edit(p)
    with pytest.raises(ValueError):
        acl.parse_policy(json.dumps(p))


@pytest.mark.parametrize("principal,ok", [
    ("public", True), ("tenant:acme", True), ("group:acme/0", True), ("user:acme-0", True),
    ("group:globex/a-1", True), ("user:auditor", True),
    ("Public", False), ("tenant:", False), ("group:acme", False), ("user:Ghost", False),
    ("user:1x", False), ("tenant:acme ", False), ("*", False), ("", False),
])
def test_the_principal_grammar(principal, ok):
    assert bool(acl.PRINCIPAL.match(principal)) is ok


# -- assignment ----------------------------------------------------------------------------

@pytest.mark.parametrize("key,b", [
    ("ecfr:33:99", 51), ("irm:5.19.1", 25), ("a" * 64, 75), ("0" * 64, 29), ("doc", 60)])
def test_bucket_is_fixed_by_the_key(key, b):
    assert acl.bucket(key) == b
    expected = int(hashlib.sha256(f"adr-acl-v1\nbucket\n{key}".encode()).hexdigest()[:8], 16)
    assert acl.bucket(key) == expected % 100


def _only(kind: str) -> Policy:
    return acl.default_policy().model_copy(
        update={"buckets": [acl.Bucket(below=100, access=kind)]})


def test_access_lists_of_each_kind_are_consistent():
    d = acl.default_directory()
    for i in range(200):
        key = f"key-{i}"
        assert acl.access_list(key, {}, _only("public"), d) == ["public"]
        [tenant] = acl.access_list(key, {}, _only("tenant"), d)
        shared = acl.access_list(key, {}, _only("two_tenants"), d)
        [group] = acl.access_list(key, {}, _only("group"), d)
        assert tenant in shared and len(set(shared)) == 2 and shared == sorted(shared)
        assert all(p.startswith("tenant:") for p in shared)
        assert group.startswith(f"group:{tenant.removeprefix('tenant:')}/")


def test_tenants_and_groups_are_spread():
    d = acl.default_directory()
    tenants = {acl.access_list(f"k{i}", {}, _only("tenant"), d)[0] for i in range(300)}
    groups = {acl.access_list(f"k{i}", {}, _only("group"), d)[0] for i in range(300)}
    assert tenants == {f"tenant:{t}" for t in d.tenants}
    assert groups == set(d.groups)


def test_the_bucket_table_picks_the_kind():
    d, p = acl.default_directory(), acl.default_policy()
    for i in range(300):
        key = f"k{i}"
        kind, access = acl.assign(key, {}, p, d)
        b = acl.bucket(key)
        assert kind == ("public" if b < 20 else "two_tenants" if b < 30 else
                        "tenant" if b < 75 else "group")
        assert access == acl.access_list(key, {}, p, d)


def test_attribute_rules_come_first_in_order():
    d = acl.default_directory()
    p = acl.parse_policy(json.dumps({**policy_dict(), "rules": [
        {"match": {"uri_prefix": "https://example.org/secret/"}, "access": []},
        {"match": {"format": "pdf", "uri_prefix": "https://example.org/"},
         "access": ["user:auditor", "group:acme/1"]},
        {"match": {"format": "pdf"}, "access": ["public"]},
    ]}))
    assert acl.assign("k", {"format": "pdf", "uri": "https://example.org/secret/x"}, p, d) \
        == ("rule", [])
    assert acl.access_list("k", {"format": "pdf", "uri": "https://example.org/x"}, p, d) == \
        ["group:acme/1", "user:auditor"]
    assert acl.access_list("k", {"format": "pdf", "uri": "file://x"}, p, d) == ["public"]
    assert acl.access_list("k", {"format": "md", "uri": "file://x"}, p, d) == \
        acl.access_list("k", {}, acl.default_policy(), d)


# -- the sync cycle ------------------------------------------------------------------------

def test_sync_writes_the_snapshot_and_moves_head(store, config):
    res = sync(store, config, clock=fixed())
    head = store.path / "acl" / "HEAD"
    assert head.read_text() == res.acl_snapshot + "\n"
    path = store.path / "acl" / "snapshots" / f"{res.acl_snapshot}.json"
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == res.acl_snapshot
    sid, snap = acl.read_head(store.path)
    assert sid == res.acl_snapshot and data == records.canonical_json(snap)
    assert (snap.sequence, res.sequence, res.changed, res.previous) == (1, 1, True, None)
    assert snap.synced_at == T0
    assert snap.content_snapshot == store.snapshot_id
    assert (snap.tool_snapshot, snap.tools) == (None, {})
    assert sorted(snap.docs) == store.doc_ids()
    assert snap.directory_sha256 == hashlib.sha256(config[0].read_bytes()).hexdigest()
    assert snap.policy_sha256 == hashlib.sha256(config[1].read_bytes()).hexdigest()
    assert (snap.max_sync_age_s, snap.future_skew_s) == (3600, 300)
    d = acl.default_directory()
    assert snap.directory == {u: sorted(acl.principals_of(d, u)) for u in d.users}
    entries = json.dumps({"directory": snap.directory, "docs": snap.docs, "tools": snap.tools},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert snap.entries_sha256 == hashlib.sha256(entries.encode()).hexdigest()
    assert res.entries_sha256 == snap.entries_sha256
    assert sum(res.kinds.values()) == len(store.doc_ids())


def test_versions_of_a_chain_share_one_access_list(store, config):
    sync(store, config, clock=fixed())
    _, snap = acl.read_head(store.path)
    d, p = acl.default_directory(), acl.default_policy()
    chain = {tuple(snap.docs[doc_id(v)]) for v in (V2024, V2025, V2026)}
    assert chain == {tuple(acl.access_list("ecfr:33:99", {}, p, d))}
    assert snap.docs[doc_id(IRM)] == acl.access_list("irm:5.19.1", {}, p, d)
    for doc in (FINAL, LOOSE):  # no chain: keyed by doc id
        assert snap.docs[doc_id(doc)] == acl.access_list(doc_id(doc), {}, p, d)


def test_a_chain_without_an_overlay_still_shares_access(tmp_path, config):
    s = make_gov_store(tmp_path / "chain-only", [V2024, V2026])
    assert not (s.path / "applicability").exists()
    acl.sync(s.path, *config, clock=fixed())
    _, snap = acl.read_head(s.path)
    assert snap.docs[doc_id(V2024)] == snap.docs[doc_id(V2026)]


def test_two_syncs_of_the_same_inputs(store, config):
    first = sync(store, config, clock=fixed())
    second = sync(store, config, clock=fixed())
    assert first.entries_sha256 == second.entries_sha256
    assert (first.sequence, second.sequence) == (1, 2)
    assert second.acl_snapshot != first.acl_snapshot
    assert (second.changed, second.previous) == (False, first.acl_snapshot)
    third = sync(store, config, clock=fixed(T0 + timedelta(hours=1)))
    assert third.sequence == 3 and third.entries_sha256 == first.entries_sha256


def test_syncs_of_two_equal_stores_are_byte_identical(tmp_path, config):
    a = make_gov_store(tmp_path / "a")
    b = make_gov_store(tmp_path / "b")
    ra = acl.sync(a.path, *config, clock=fixed())
    rb = acl.sync(b.path, *config, clock=fixed())
    assert ra.acl_snapshot == rb.acl_snapshot


def test_a_directory_change_changes_the_entries(store, config):
    first = sync(store, config, clock=fixed())
    d = json.loads(config[0].read_text())
    d["users"]["user:acme-4"] = ["group:acme/0"]
    config[0].write_text(json.dumps(d))
    second = sync(store, config, clock=fixed())
    assert second.changed and second.entries_sha256 != first.entries_sha256
    _, snap = acl.read_head(store.path)
    assert "group:acme/1" not in snap.directory["user:acme-4"]


def test_sync_follows_the_store_head(store, config, tmp_path):
    sync(store, config, clock=fixed())
    s = Store.open(store.path)
    s._records.pop(doc_id(FINAL))
    new = s.commit()
    sync(store, config, clock=fixed())
    _, snap = acl.read_head(store.path)
    assert snap.content_snapshot == new and doc_id(FINAL) not in snap.docs


def _head(store) -> bytes:
    return (store.path / "acl" / "HEAD").read_bytes()


def _log(store) -> list[dict]:
    lines = (store.path / "acl" / "sync.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def test_an_invalid_policy_leaves_head(store, config):
    sync(store, config, clock=fixed())
    before = _head(store)
    config[1].write_text(json.dumps({**policy_dict(), "max_sync_age_s": -1}))
    with pytest.raises(acl.SyncError, match="policy"):
        sync(store, config, clock=fixed())
    assert _head(store) == before
    last = _log(store)[-1]
    assert last["outcome"] == "error" and "policy" in last["error"]
    assert last["acl_snapshot"] is None


@pytest.mark.parametrize("broken", ["directory", "policy"])
def test_a_missing_config_file_leaves_head(store, config, broken):
    sync(store, config, clock=fixed())
    before = _head(store)
    config[0 if broken == "directory" else 1].unlink()
    with pytest.raises(acl.SyncError, match=broken):
        sync(store, config, clock=fixed())
    assert _head(store) == before


def test_an_unwritable_snapshot_dir_leaves_head(store, config, monkeypatch):
    sync(store, config, clock=fixed())
    before = _head(store)
    real = acl.write_atomic

    def failing(path, data):
        if path.parent.name == "snapshots":
            raise PermissionError(13, "Permission denied", str(path))
        real(path, data)

    monkeypatch.setattr(acl, "write_atomic", failing)
    with pytest.raises(acl.SyncError, match="Permission denied"):
        sync(store, config, clock=fixed(T0 + timedelta(seconds=1)))
    assert _head(store) == before
    assert _log(store)[-1]["outcome"] == "error"
    assert acl.read_head(store.path)[1].sequence == 1


def test_a_failed_head_swap_leaves_head(store, config, monkeypatch):
    sync(store, config, clock=fixed())
    before = _head(store)
    real = acl.write_atomic

    def failing(path, data):
        if path.name == "HEAD":
            raise OSError(28, "No space left on device", str(path))
        real(path, data)

    monkeypatch.setattr(acl, "write_atomic", failing)
    with pytest.raises(acl.SyncError):
        sync(store, config, clock=fixed(T0 + timedelta(seconds=1)))
    assert _head(store) == before


def test_a_store_without_head_cannot_sync(tmp_path, config):
    with pytest.raises(StoreError):
        acl.sync(tmp_path / "nothing", *config)


def test_the_sync_log_line(store, config):
    t_dir, t_pol = T0.timestamp() - 10, T0.timestamp() - 4
    os.utime(config[0], (t_dir, t_dir))
    os.utime(config[1], (t_pol, t_pol))
    res = sync(store, config, clock=fixed())
    [line] = _log(store)
    assert set(line) == {"started", "finished", "duration_s", "lag_s", "sequence",
                         "acl_snapshot", "previous", "content_snapshot", "tool_snapshot",
                         "directory_sha256", "policy_sha256", "entries_sha256", "changed",
                         "outcome", "error"}
    assert line["outcome"] == "ok" and line["error"] is None
    assert line["started"] == line["finished"] == "2026-11-16T12:00:00Z"
    assert line["lag_s"] == res.lag_s == 4.0
    assert line["duration_s"] == res.duration_s >= 0
    assert (line["sequence"], line["acl_snapshot"], line["previous"]) == \
        (1, res.acl_snapshot, None)
    assert line["content_snapshot"] == store.snapshot_id and line["tool_snapshot"] is None
    assert line["entries_sha256"] == res.entries_sha256 and line["changed"] is True
    sync(store, config, clock=fixed())
    assert [x["sequence"] for x in _log(store)] == [1, 2]


def test_sequence_continues_past_a_damaged_head(store, config):
    sync(store, config, clock=fixed())
    sync(store, config, clock=fixed())
    (store.path / "acl" / "HEAD").write_text("garbage\n")
    res = sync(store, config, clock=fixed())
    assert res.sequence == 3 and res.previous is None


# -- reading HEAD: F1 ----------------------------------------------------------------------

def _f1(store, match: str):
    with pytest.raises(AclDenied, match=match) as e:
        acl.read_head(store.path)
    assert e.value.code == "F1"
    assert str(e.value).startswith("access denied (F1): ")


def _put(store, data: bytes) -> None:
    sid = hashlib.sha256(data).hexdigest()
    snaps = store.path / "acl" / "snapshots"
    snaps.mkdir(parents=True, exist_ok=True)
    (snaps / f"{sid}.json").write_bytes(data)
    (store.path / "acl" / "HEAD").write_text(sid + "\n")


def test_read_head_f1_missing(store):
    _f1(store, "no ACL snapshot")


def test_read_head_f1_unreadable(store, config):
    sync(store, config, clock=fixed())
    head = store.path / "acl" / "HEAD"
    head.unlink()
    head.mkdir()
    _f1(store, "unreadable")


def test_read_head_f1_names_a_missing_file(store, config):
    sync(store, config, clock=fixed())
    (store.path / "acl" / "HEAD").write_text("f" * 64 + "\n")
    _f1(store, "unreadable")
    (store.path / "acl" / "HEAD").write_text("not-an-id\n")
    _f1(store, "not an ACL snapshot id")


def test_read_head_f1_unparsable(store):
    _put(store, b"{not json\n")
    _f1(store, "unparsable")


def test_read_head_f1_schema_invalid(store, config):
    res = sync(store, config, clock=fixed())
    body = json.loads((store.path / "acl" / "snapshots" /
                       f"{res.acl_snapshot}.json").read_bytes())
    for bad in ({**body, "sequence": 0}, {**body, "extra": 1}, {**body, "entries_sha256": "0" * 64},
                {**body, "synced_at": "2026-11-16T12:00:00"}, [1, 2]):
        _put(store, json.dumps(bad).encode())
        _f1(store, "schema")


def test_read_head_f1_hash_is_not_the_id(store, config):
    res = sync(store, config, clock=fixed())
    path = store.path / "acl" / "snapshots" / f"{res.acl_snapshot}.json"
    path.write_bytes(path.read_bytes().replace(b'"sequence":1', b'"sequence":2'))
    _f1(store, "hash")


# -- freshness (F3), callers (F4, F5) and snapshot principals (F5) --------------------------

def test_check_fresh(store, config):
    sync(store, config, clock=fixed())
    _, snap = acl.read_head(store.path)
    acl.check_fresh(snap, clock=fixed(T0))
    acl.check_fresh(snap, clock=fixed(T0 + timedelta(seconds=3600)))
    acl.check_fresh(snap, clock=fixed(T0 - timedelta(seconds=300)))
    for t, what in ((T0 + timedelta(seconds=3601), "older"),
                    (T0 - timedelta(seconds=301), "future")):
        with pytest.raises(AclDenied, match=what) as e:
            acl.check_fresh(snap, clock=fixed(t))
        assert e.value.code == "F3"


def test_caller_principals(store, config):
    sync(store, config, clock=fixed())
    _, snap = acl.read_head(store.path)
    assert acl.caller_principals(snap, "user:outsider") == ("public", "user:outsider")
    for caller, code in ((None, "F4"), ("user:ghost", "F4"), ("user:Ghost", "F5"),
                         ("group:acme/0", "F5"), ("public", "F5"), ("user:", "F5"),
                         ("tenant:acme", "F5")):
        with pytest.raises(AclDenied) as e:
            acl.caller_principals(snap, caller)
        assert e.value.code == code


def test_check_principals(store, config):
    sync(store, config, clock=fixed())
    _, snap = acl.read_head(store.path)
    acl.check_principals(snap)
    first = sorted(snap.docs)[0]
    for bad in (snap.model_copy(update={"docs": {**snap.docs, first: ["tenant:Acme"]}}),
                snap.model_copy(update={"directory": {**snap.directory, "user:x": ["*"]}}),
                snap.model_copy(update={"directory": {**snap.directory,
                                                      "group:acme/0": ["public"]}})):
        with pytest.raises(AclDenied) as e:
            acl.check_principals(bad)
        assert e.value.code == "F5"


# -- schemas -------------------------------------------------------------------------------

def test_the_acl_schemas_are_record_schemas():
    s = records.schemas()
    assert s["acl-directory.schema.json"] == Directory.model_json_schema()
    assert s["acl-policy.schema.json"] == Policy.model_json_schema()
    assert s["acl-snapshot.schema.json"] == acl.AclSnapshot.model_json_schema()


# -- the CLI -------------------------------------------------------------------------------

def _cli(capsys, *argv) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_cli_sync_and_show(store, config, capsys):
    flags = ["--store", str(store.path), "--directory", str(config[0]),
             "--policy", str(config[1])]
    code, out, _ = _cli(capsys, "acl", "sync", *flags)
    assert code == 0 and "sequence 1" in out
    sid, snap = acl.read_head(store.path)
    assert sid[:12] in out
    code, out, _ = _cli(capsys, "acl", "sync", *flags, "--json")
    res = json.loads(out)
    assert code == 0 and res["sequence"] == 2 and res["changed"] is False
    assert set(res) >= {"acl_snapshot", "sequence", "entries_sha256", "changed", "duration_s",
                        "lag_s", "kinds", "documents"}

    did = doc_id(V2024)
    code, out, _ = _cli(capsys, "acl", "show", "--store", str(store.path), "--doc", did[:10])
    assert code == 0 and did in out
    for p in snap.docs[did]:
        assert p in out
    code, out, _ = _cli(capsys, "acl", "show", "--store", str(store.path), "--user",
                        "user:acme-4", "--json")
    shown = json.loads(out)
    assert shown["principals"] == snap.directory["user:acme-4"]
    assert shown["visible_documents"] == sum(
        1 for v in snap.docs.values() if set(v) & set(shown["principals"]))


def test_cli_show_chunk(store, config, capsys):
    from adr_store import tools

    sync(store, config, clock=fixed())
    idx = tools.Tools(store.path)
    idx.index("p1-struct", lexical_only=True)
    chunk = next(iter(idx.active_index().chunks.values()))
    _, snap = acl.read_head(store.path)
    code, out, _ = _cli(capsys, "acl", "show", "--store", str(store.path), "--chunk",
                        chunk.chunk_id, "--json")
    shown = json.loads(out)
    assert code == 0 and shown["doc_id"] == chunk.doc_id
    assert shown["principals"] == snap.docs[chunk.doc_id]


def test_cli_show_refusals(store, config, capsys):
    code, _, err = _cli(capsys, "acl", "show", "--store", str(store.path), "--user",
                        "user:acme-0")
    assert code == 2 and "access denied (F1)" in err
    sync(store, config, clock=fixed())
    code, _, err = _cli(capsys, "acl", "show", "--store", str(store.path), "--user",
                        "user:ghost")
    assert code == 2 and "user:ghost" in err
    code, _, err = _cli(capsys, "acl", "show", "--store", str(store.path), "--doc", "ffffffff")
    assert code == 2 and "no document" in err


def test_cli_sync_refusal(store, config, capsys):
    config[1].write_text("{}")
    code, _, err = _cli(capsys, "acl", "sync", "--store", str(store.path), "--directory",
                        str(config[0]), "--policy", str(config[1]))
    assert code == 2 and "policy" in err
    assert not (store.path / "acl" / "HEAD").exists()


def test_cli_help_says_adr_is_not_a_security_boundary(capsys):
    with pytest.raises(SystemExit):
        cli.main(["acl", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "not a security boundary" in out


# -- pinned assignment: the salts and the sorted-tenants rule ---------------------------------

PINNED_ACCESS = {  # default policy and directory; a changed salt or tenant order changes these
    "public": {"key-0": ["public"], "key-6": ["public"]},
    "two_tenants": {"key-27": ["tenant:acme", "tenant:globex"],
                    "key-41": ["tenant:acme", "tenant:initech"],
                    "key-47": ["tenant:acme", "tenant:globex"],
                    "key-54": ["tenant:acme", "tenant:globex"],
                    "key-58": ["tenant:acme", "tenant:initech"],
                    "key-62": ["tenant:globex", "tenant:initech"]},
    "tenant": {"key-2": ["tenant:initech"], "key-4": ["tenant:initech"],
               "key-5": ["tenant:globex"], "key-8": ["tenant:initech"],
               "key-9": ["tenant:acme"], "key-11": ["tenant:globex"]},
    "group": {"key-1": ["group:acme/0"], "key-3": ["group:initech/3"],
              "key-7": ["group:acme/0"], "key-10": ["group:initech/3"],
              "key-13": ["group:acme/1"], "key-14": ["group:acme/0"]},
}


@pytest.mark.parametrize("kind", sorted(PINNED_ACCESS))
def test_access_lists_are_pinned_for_fixed_keys(kind):
    d, p = acl.default_directory(), acl.default_policy()
    for key, want in PINNED_ACCESS[kind].items():
        assert acl.assign(key, {}, p, d) == (kind, want), key


def test_the_tenants_are_taken_in_sorted_order():
    d, p = acl.default_directory(), acl.default_policy()
    reordered = d.model_copy(update={"tenants": list(reversed(d.tenants))})
    for kind in PINNED_ACCESS:
        for key, want in PINNED_ACCESS[kind].items():
            assert acl.assign(key, {}, p, reordered) == (kind, want), key


# -- the sync lock ---------------------------------------------------------------------------

def test_the_sync_cycle_runs_under_the_exclusive_lock(store, config, monkeypatch):
    import fcntl

    real = acl._sync_locked
    held = []

    def probe(store_, adir, *rest):
        with open(adir / "sync.lock", "a") as other:  # another open file description
            try:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                held.append(True)
            else:
                fcntl.flock(other, fcntl.LOCK_UN)
                held.append(False)
        return real(store_, adir, *rest)

    monkeypatch.setattr(acl, "_sync_locked", probe)
    sync(store, config, clock=fixed())
    assert held == [True]


def test_concurrent_syncs_get_gapless_unique_sequences(store, config):
    import threading

    results, errors = [], []

    def work():
        try:
            for _ in range(3):
                results.append(sync(store, config, clock=fixed()).sequence)
        except Exception as e:  # pragma: no cover - reported below
            errors.append(e)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert not errors
    assert sorted(results) == list(range(1, 13))
    assert acl.read_head(store.path)[1].sequence == 12


# -- sync errors say whether HEAD moved; the snapshot file is write-once ----------------------

def test_a_failing_log_after_the_swap_says_head_moved(store, config, monkeypatch):
    def failing(path, line):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(acl, "_append", failing)
    with pytest.raises(acl.SyncError, match="moved") as e:
        sync(store, config, clock=fixed())
    assert e.value.head_moved and "unchanged" not in str(e.value)
    sid, _ = acl.read_head(store.path)
    assert sid[:12] in str(e.value)


def test_a_clock_failing_after_the_swap_says_head_moved(store, config):
    calls = []

    def clock():
        calls.append(1)
        if len(calls) == 3:  # started, synced_at, then the swap time
            raise RuntimeError("clock broke")
        return T0

    with pytest.raises(acl.SyncError, match="moved") as e:
        sync(store, config, clock=clock)
    assert e.value.head_moved and "clock broke" in str(e.value)
    sid, _ = acl.read_head(store.path)
    last = _log(store)[-1]
    assert last["outcome"] == "error" and last["acl_snapshot"] == sid


def test_a_clock_failing_before_the_swap_leaves_head(store, config):
    sync(store, config, clock=fixed())
    before = _head(store)

    def naive():
        return datetime(2026, 11, 16, 12, 0, 0)

    with pytest.raises(acl.SyncError, match="unchanged") as e:
        sync(store, config, clock=naive)
    assert not e.value.head_moved and _head(store) == before
    assert _log(store)[-1]["outcome"] == "error"


def test_an_existing_snapshot_file_with_other_bytes_is_refused(tmp_path, config):
    twin = make_gov_store(tmp_path / "twin")
    sid = acl.sync(twin.path, *config, clock=fixed()).acl_snapshot
    s = make_gov_store(tmp_path / "s")
    path = s.path / "acl" / "snapshots" / f"{sid}.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not the snapshot\n")
    with pytest.raises(acl.SyncError, match="other bytes"):
        acl.sync(s.path, *config, clock=fixed())
    assert not (s.path / "acl" / "HEAD").exists()
    assert path.read_bytes() == b"not the snapshot\n"


# -- resolve: the one entry of a tool call -----------------------------------------------------

def test_resolve_returns_the_callers_access(store, config):
    sync(store, config, clock=fixed())
    sid, snap = acl.read_head(store.path)
    a = acl.resolve(store.path, "user:acme-4", store.snapshot_id, clock=fixed())
    ps = set(acl.principals_of(acl.default_directory(), "user:acme-4"))
    assert (a.acl_snapshot, a.caller, a.principals) == (sid, "user:acme-4", tuple(sorted(ps)))
    assert a.docs == {d for d, v in snap.docs.items() if ps & set(v)}
    assert a.tools == frozenset()
    assert a.view == hashlib.sha256("\n".join(sorted(a.docs)).encode()).hexdigest()


@pytest.mark.parametrize("clock", [
    lambda: datetime(2026, 11, 16, 12, 0, 0),                # naive
    lambda: "2026-11-16T12:00:00Z",                          # not a datetime
    lambda: (_ for _ in ()).throw(RuntimeError("no time")),  # raises
])
def test_a_bad_clock_denies_f3(store, config, clock):
    sync(store, config, clock=fixed())
    with pytest.raises(AclDenied) as e:
        acl.resolve(store.path, "user:acme-0", store.snapshot_id, clock=clock)
    assert e.value.code == "F3" and e.value.acl_snapshot is not None


def test_resolve_runs_every_check(store, config):
    with pytest.raises(AclDenied) as e:
        acl.resolve(store.path, "user:acme-0", store.snapshot_id, clock=fixed())
    assert (e.value.code, e.value.acl_snapshot) == ("F1", None)
    sync(store, config, clock=fixed())
    sid, snap = acl.read_head(store.path)
    cases = [("user:acme-0", "0" * 64, fixed(), "F2"),
             ("user:acme-0", store.snapshot_id, fixed(T0 + timedelta(hours=2)), "F3"),
             ("user:ghost", store.snapshot_id, fixed(), "F4"),
             (None, store.snapshot_id, fixed(), "F4"),
             ("user:Ghost", store.snapshot_id, fixed(), "F5")]
    for caller, content, clock, code in cases:
        with pytest.raises(AclDenied) as e:
            acl.resolve(store.path, caller, content, clock=clock)
        assert (e.value.code, e.value.acl_snapshot) == (code, sid), caller
    bad = snap.model_copy(update={"docs": {**snap.docs, sorted(snap.docs)[0]: ["tenant:Acme"]}})
    bad = bad.model_copy(update={"entries_sha256": acl.entries_sha256(bad.directory, bad.docs,
                                                                      bad.tools)})
    _put(store, records.canonical_json(bad))
    with pytest.raises(AclDenied) as e:
        acl.resolve(store.path, "user:acme-0", store.snapshot_id, clock=fixed())
    assert e.value.code == "F5"


def test_resolve_caches_the_parse_by_id_but_rereads_the_file(store, config, monkeypatch):
    from collections import OrderedDict

    sync(store, config, clock=fixed())
    cache = OrderedDict()
    acl.resolve(store.path, "user:acme-0", store.snapshot_id, clock=fixed(), cache=cache)
    calls = []
    real = acl.AclSnapshot.model_validate_json
    monkeypatch.setattr(acl.AclSnapshot, "model_validate_json",
                        lambda data: calls.append(1) or real(data))
    acl.resolve(store.path, "user:acme-0", store.snapshot_id, clock=fixed(), cache=cache)
    assert calls == []
    sid, _ = acl.read_head(store.path)
    path = store.path / "acl" / "snapshots" / f"{sid}.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(AclDenied) as e:  # the hash is checked on every call
        acl.resolve(store.path, "user:acme-0", store.snapshot_id, clock=fixed(), cache=cache)
    assert e.value.code == "F1"
