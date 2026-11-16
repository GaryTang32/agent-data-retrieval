"""Revocation within one sync cycle (Phase 2 spec §5.5, §12 Revocation, criterion B3) for
`search`, `grep` and `read`, and for `search_tools` and `load_tool`: three change kinds (a
user removed from a group, a document's or tool's rule changed in the policy, a user deleted),
steps 1–5 checked in-process, in a new process and in a `tools_proc` process started before
the change; a new content snapshot (and a new tool snapshot, for the tool tools) denies all
until a sync (F2); a stale snapshot denies all (F3). Subprocesses get explicit `--store` and
`--emb-cache` under `tmp_path`; lexical-only indexes."""

import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from adr_store import acl, tool_catalog, tool_records, tools
from adr_store.store import Store
from tests.store.test_permissions import (
    ACME1,
    NOW,
    PUBLIC,
    RULES,
    T0,
    absent_like,
    did,
    fixed,
    make,
    md,
    write_config,
)

REPO = Path(__file__).parents[2]
TARGET = did(ACME1)
TOKEN = "obsidianite"
CALLER = "user:acme-4"  # groups acme/0 and acme/1: sees the target through acme/1


class Proc:
    """A `tools_proc` process serving one caller's calls."""

    def __init__(self, store, tmp_path, caller=CALLER, clock=NOW):
        self.p = subprocess.Popen(
            [sys.executable, "-m", "tests.store.tools_proc", "--store", str(store.path),
             "--emb-cache", str(tmp_path / "emb"), "--as", caller, "--clock", clock.isoformat()],
            cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        assert json.loads(self.p.stdout.readline()) == {"ready": True}

    def call(self, method, *args, **kwargs) -> dict:
        self.p.stdin.write(json.dumps({"method": method, "args": list(args),
                                       "kwargs": kwargs}) + "\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())

    def close(self):
        self.p.stdin.close()
        assert self.p.wait(30) == 0
        self.p.stdout.close()


@pytest.fixture
def procs():
    made = []

    def start(*a, **kw):
        made.append(Proc(*a, **kw))
        return made[-1]

    yield start
    for p in made:
        if p.p.poll() is None:
            p.close()


def ask(who, method, *a, **kw) -> dict:
    if isinstance(who, Proc):
        return who.call(method, *a, **kw)
    try:
        return {"ok": getattr(who, method)(*a, **kw).to_dict()}
    except tools.ToolError as e:
        return {"error": str(e), "type": type(e).__name__, "code": getattr(e, "code", None)}


def sees(who) -> dict:
    """Whether `who` sees the target through each tool, and the replies."""
    s = ask(who, "search", f"{TOKEN} memo")
    g = ask(who, "grep", TOKEN)
    r = ask(who, "read", TARGET)
    return {"search": TARGET in {h["doc_id"] for h in s.get("ok", {"hits": []})["hits"]},
            "grep": TARGET in {m["doc_id"] for m in g.get("ok", {"matches": []})["matches"]},
            "read": "ok" in r, "replies": (s, g, r)}


def visible_everywhere(*who):
    for w in who:
        got = sees(w)
        assert (got["search"], got["grep"], got["read"]) == (True, True, True), got["replies"]


def invisible_everywhere(store, *who, denied: str | None = None):
    none = absent_like(TARGET, store.doc_ids())
    for w in who:
        got = sees(w)
        assert (got["search"], got["grep"], got["read"]) == (False, False, False)
        s, g, r = got["replies"]
        if denied is None:  # allowed, without the target: read is "not found", byte for byte
            assert "ok" in s and "ok" in g
            assert r["error"] == ask(w, "read", none)["error"]
        else:
            assert all(x.get("code") == denied for x in (s, g, r)), got["replies"]
            assert all("ok" not in x for x in (s, g, r))


def edit_directory(config, fn):
    d = json.loads(config[0].read_text())
    fn(d)
    config[0].write_text(json.dumps(d))


def edit_policy(config, fn):
    p = json.loads(config[1].read_text())
    fn(p)
    config[1].write_text(json.dumps(p))


CHANGES = {
    "user removed from a group": (
        lambda c: edit_directory(c, lambda d: d["users"].update({CALLER: ["group:acme/0"]})),
        None),
    "document rule changed in the policy": (
        lambda c: edit_policy(c, lambda p: p["rules"].insert(0, {
            "match": {"uri_prefix": "file://acl/acme-1/memo.md"},
            "access": ["group:globex/0"]})),
        None),
    "user deleted": (lambda c: edit_directory(c, lambda d: d["users"].pop(CALLER)), "F4"),
}


@pytest.mark.parametrize("change", sorted(CHANGES))
def test_revocation_within_one_sync_cycle(tmp_path, procs, change):
    config = _config(tmp_path)
    store = make(tmp_path / "store", config)
    edit, denied = CHANGES[change]
    # 1. the caller can see the target (in-process, and in a process started now)
    before = procs(store, tmp_path)
    visible_everywhere(tools.Tools(store.path, acl=True, caller=CALLER, clock=fixed()), before)
    # 2. edit the directory or policy copy; 3. before the sync: unchanged
    edit(config)
    visible_everywhere(tools.Tools(store.path, acl=True, caller=CALLER, clock=fixed()), before)
    # 4. one sync
    acl.sync(store.path, *config, clock=fixed(T0))
    # 5. invisible: in-process, in a new process, in the process started before step 2
    after = procs(store, tmp_path)
    invisible_everywhere(store, tools.Tools(store.path, acl=True, caller=CALLER,
                                            clock=fixed()), after, before, denied=denied)
    # the change revoked nothing else: another caller still sees what it saw
    other = tools.Tools(store.path, acl=True, caller="user:acme-0", clock=fixed())
    assert "ok" in ask(other, "read", did(PUBLIC))


def _config(tmp_path):
    return write_config(tmp_path / "config", RULES)


def test_a_new_content_snapshot_denies_all_until_a_sync(tmp_path, procs):
    config = _config(tmp_path)
    store = make(tmp_path / "store", config)
    before = procs(store, tmp_path)
    visible_everywhere(before)
    s = Store.open(store.path)
    s.add(*md("public/later.md", "Later", "A later vessel note."))
    s.commit()
    fresh = tools.Tools(store.path, acl=True, caller=CALLER, clock=fixed())
    for who in (before, fresh, procs(store, tmp_path)):
        for reply in sees(who)["replies"]:
            assert reply["code"] == "F2" and "ok" not in reply
    acl.sync(store.path, *config, clock=fixed(T0))
    for who in (before, fresh):
        assert "ok" in ask(who, "read", TARGET) and "ok" in ask(who, "grep", TOKEN)
        assert "adr index" in ask(who, "search", TOKEN)["error"]  # allowed; the index is old


def test_a_stale_snapshot_denies_all(tmp_path, procs):
    config = _config(tmp_path)
    store = make(tmp_path / "store", config)
    now = [NOW]
    t = tools.Tools(store.path, acl=True, caller=CALLER, clock=lambda: now[0])
    visible_everywhere(t)
    now[0] = T0 + timedelta(seconds=3601)
    stale = procs(store, tmp_path, clock=now[0])
    for who in (t, stale):
        for reply in sees(who)["replies"]:
            assert reply["code"] == "F3" and "ok" not in reply
    acl.sync(store.path, *config, clock=fixed(now[0]))  # a sync makes it fresh again
    visible_everywhere(t)


# -- the tool tools ----------------------------------------------------------------------------

TOOL_URI = "fixture:tools/acme-1/obsidian"
TOOL_RULES = [{"match": {"uri_prefix": TOOL_URI}, "access": ["group:acme/1"]},
              {"match": {"uri_prefix": "fixture:tools/public/"}, "access": ["public"]},
              *RULES]


def _tool(name: str, description: str, uri: str):
    return tool_records.from_mcp({"tools": [{"name": name, "description": description,
                                             "inputSchema": {"type": "object"}}]},
                                 "fixture", uri, "1", "CC0-1.0")[0]


TARGET_TOOL = _tool("obsidian_probe", "Probes the obsidianite memo archive.", TOOL_URI)
OTHER_TOOLS = [_tool("harbour_fees", "Looks up harbour fees for a vessel.",
                     "fixture:tools/public/fees"),
               _tool("vessel_registry", "Finds a vessel in the registry.",
                     "fixture:tools/public/registry")]


def make_with_tools(path, config):
    store = make(path, config)
    tool_catalog.ingest(store.path, [TARGET_TOOL, *OTHER_TOOLS])
    tools.Tools(store.path).tools_index(1, lexical_only=True)
    acl.sync(store.path, *config, clock=fixed(T0))
    return store


def sees_tool(who) -> dict:
    s = ask(who, "search_tools", "obsidianite probe")
    r = ask(who, "load_tool", TARGET_TOOL.tool_id)
    return {"search_tools": TARGET_TOOL.tool_id in {
        h["tool_id"] for h in s.get("ok", {"hits": []})["hits"]},
        "load_tool": "ok" in r, "replies": (s, r)}


def tool_visible_everywhere(*who):
    for w in who:
        got = sees_tool(w)
        assert (got["search_tools"], got["load_tool"]) == (True, True), got["replies"]


def tool_invisible_everywhere(*who, denied: str | None = None):
    none = absent_like(TARGET_TOOL.tool_id, [t.tool_id for t in [TARGET_TOOL, *OTHER_TOOLS]])
    for w in who:
        got = sees_tool(w)
        assert (got["search_tools"], got["load_tool"]) == (False, False)
        s, r = got["replies"]
        if denied is None:  # allowed, without the target: load_tool is "not found", exactly
            assert "ok" in s
            assert r["error"] == ask(w, "load_tool", none)["error"]
        else:
            assert all(x.get("code") == denied and "ok" not in x for x in (s, r)), (s, r)


TOOL_CHANGES = {
    "user removed from a group": CHANGES["user removed from a group"],
    "tool rule changed in the policy": (
        lambda c: edit_policy(c, lambda p: p["rules"].insert(0, {
            "match": {"uri_prefix": TOOL_URI}, "access": ["group:globex/0"]})), None),
    "user deleted": CHANGES["user deleted"],
}


@pytest.mark.parametrize("change", sorted(TOOL_CHANGES))
def test_tool_revocation_within_one_sync_cycle(tmp_path, procs, change):
    config = write_config(tmp_path / "config", TOOL_RULES)
    store = make_with_tools(tmp_path / "store", config)
    edit, denied = TOOL_CHANGES[change]
    # 1. the caller can see the target tool (in-process, and in a process started now)
    before = procs(store, tmp_path)
    tool_visible_everywhere(tools.Tools(store.path, acl=True, caller=CALLER, clock=fixed()),
                            before)
    # 2. edit the directory or policy copy; 3. before the sync: unchanged
    edit(config)
    tool_visible_everywhere(tools.Tools(store.path, acl=True, caller=CALLER, clock=fixed()),
                            before)
    # 4. one sync
    acl.sync(store.path, *config, clock=fixed(T0))
    # 5. invisible: in-process, in a new process, in the process started before step 2
    after = procs(store, tmp_path)
    tool_invisible_everywhere(tools.Tools(store.path, acl=True, caller=CALLER, clock=fixed()),
                              after, before, denied=denied)
    # the change revoked nothing else: another caller still loads a public tool
    other = tools.Tools(store.path, acl=True, caller="user:acme-0", clock=fixed())
    assert "ok" in ask(other, "load_tool", OTHER_TOOLS[0].tool_id)


def test_a_new_tool_snapshot_denies_the_tool_tools_until_a_sync(tmp_path, procs):
    config = write_config(tmp_path / "config", TOOL_RULES)
    store = make_with_tools(tmp_path / "store", config)
    before = procs(store, tmp_path)
    tool_visible_everywhere(before)
    late = _tool("late_tool", "Arrives after the sync.", "fixture:tools/public/late")
    tool_catalog.ingest(store.path, [late])
    fresh = tools.Tools(store.path, acl=True, caller=CALLER, clock=fixed())
    for who in (before, fresh, procs(store, tmp_path)):
        for reply in sees_tool(who)["replies"]:
            assert reply["code"] == "F2" and "ok" not in reply
        assert "ok" in ask(who, "read", TARGET)  # the content tools are not affected
    acl.sync(store.path, *config, clock=fixed(T0))
    for who in (before, fresh):
        assert "ok" in ask(who, "load_tool", late.tool_id)
        assert "adr tools index" in ask(who, "search_tools", "late")["error"]


def test_a_stale_snapshot_denies_the_tool_tools(tmp_path, procs):
    config = write_config(tmp_path / "config", TOOL_RULES)
    store = make_with_tools(tmp_path / "store", config)
    now = T0 + timedelta(seconds=3601)
    for who in (tools.Tools(store.path, acl=True, caller=CALLER, clock=lambda: now),
                procs(store, tmp_path, clock=now)):
        for reply in sees_tool(who)["replies"]:
            assert reply["code"] == "F3" and "ok" not in reply
