"""The gate process (Phase 4 spec §12.6, §15.4; P5, P15, P23, P38; G1-G3; Task 18): each test
spawns `python -m adr_store.gate.server` (the `gate` fixture of `gate_fixtures`) with the key
on an inherited pipe, over a fixture store with promoted bindings; no network, no model
call. Requests are judged under the newest 33 CFR 117 version (Friday 2026-08-14): § 117.821
draw 1 is closed 7-9 a.m. and 4-6 p.m. on weekdays except federal holidays (§ 117.5 at other
times), draw 2 needs four hours notice, § 117.901 draw 1 opens on signal outside its notice
season."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import threading
from pathlib import Path

import pytest

from adr_eval.runner import MODELS_PATH
from adr_store.bindings import decide as dm
from adr_store.bindings.decide import SYSTEM_RULES
from adr_store.bindings.dsl import Binding
from adr_store.bindings.manifest import BINDINGS_DIR, BindingsManifest
from adr_store.gate import log as gate_log
from adr_store.gate import server as gate_server
from adr_store.gate.client import GateClient, GateProcess, private_socket
from adr_store.gate.server import MAX_REQUEST_BYTES
from adr_store.records import canonical_json
from tests.store.gate_fixtures import gate, new_key, start_gate  # noqa: F401
from tests.store.units_fixtures import (  # noqa: F401
    DOC_117_NEW,
    units_built_with_bindings,
)

FC = list(SYSTEM_RULES["fail_closed"])
NOON = "2026-08-14T12:00:00"
CLOSED = "2026-08-14T07:30:00"
COMMERCIAL = {"vessel_class": {"value": "commercial", "source": "record"},
              "local_procedure_conflict": {"value": False, "source": "record"}}


def opening(at: str = NOON, section: str = "117.821", draw: int = 1) -> dict:
    return {"request": "r1", "section": section, "draw": draw, "open_at": at}


def deny_args(rule_id: str = "33 CFR 117.821(a)", reason: str = "closed 7 to 9 a.m.",
              at: str = CLOSED) -> dict:
    return {"request": "r1", "section": "117.821", "draw": 1, "requested_open_at": at,
            "rule_id": rule_id, "reason": reason}


def manifest_of(g) -> Path:
    (p,) = (g.store.path / BINDINGS_DIR).glob(f"*/bindings-{g.bindings_id[:16]}.json")
    return p


def lines(g) -> list[dict]:
    return [json.loads(x) for x in gate_log.read_lines(g.log_path)]


# -- tokens (P23) ----------------------------------------------------------------------------------

def test_allow_token_verifies_once_and_replayed_or_forged_tokens_fail(gate):  # noqa: F811
    req = gate.request("schedule_opening", opening(), COMMERCIAL)
    reply = gate.client.judge(req)
    assert reply["decision"] == "allow" and isinstance(reply["token"], str)
    assert gate.client.check_token(req, reply)              # the one execution
    assert not gate.client.check_token(req, reply)          # replayed: refused
    # forged: one hex digit changed
    other = gate.client.judge(req)
    forged = {**other, "token": other["token"][:-1] + ("0" if other["token"][-1] != "0"
                                                       else "1")}
    assert not gate.client.check_token(req, forged)
    # mismatched: a valid token for another request (another session)
    req2 = {**req, "session": "s2"}
    assert not gate.client.check_token(req2, other)
    assert gate.client.check_token(req, other)              # the genuine one still works once
    # another key cannot verify the gate's tokens
    third = gate.client.judge(req)
    assert not GateClient(gate.process.socket_path, new_key()).check_token(req, third)
    # a deny carries no token and is never executable
    deny = gate.client.judge(gate.request("schedule_opening", opening(CLOSED), COMMERCIAL))
    assert deny["decision"] == "deny" and deny["token"] is None
    assert not gate.client.check_token(req, deny)


def test_a_fake_gate_forging_tokens_is_denied(tmp_path):
    """A process on the socket that answers allow with a token it cannot sign."""
    path = private_socket()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(path))
    srv.listen(1)
    reply = {"seq": 1, "decision": "allow", "rule_ids": [["33 CFR 117.5(p1)", "x"]],
             "deciding_sections": [], "missing_facts": [], "next_allowed": None,
             "explanation": {}, "token": "ab" * 32}

    def answer():
        conn, _ = srv.accept()
        with conn:
            conn.recv(65536)
            conn.sendall(json.dumps(reply).encode() + b"\n")

    t = threading.Thread(target=answer)
    t.start()
    try:
        got = GateClient(path, new_key(), deadline=5).judge({"tool": "schedule_opening"})
    finally:
        t.join()
        srv.close()
        path.unlink()
        path.parent.rmdir()
    assert (got["decision"], got["rule_ids"], got["token"]) == ("deny", [FC], None)
    assert "token" in got["explanation"]["message"]


# -- the log (G1, G3) ------------------------------------------------------------------------------

def _mixed(g) -> list[dict]:
    """A batch over every outcome and fail-closed class; the replies."""
    reqs = [
        g.request("schedule_opening", opening(), COMMERCIAL),                       # allow
        g.request("schedule_opening", opening(CLOSED), COMMERCIAL),                 # deny
        g.request("schedule_opening", opening(CLOSED), {}),                         # escalate
        g.request("schedule_opening", opening(NOON, draw=2), COMMERCIAL),           # escalate
        g.request("schedule_opening", opening(NOON, draw=9), COMMERCIAL),           # no binding
        g.request("schedule_opening", opening(NOON, "117.901"), COMMERCIAL),        # allow
        g.request("deny_request", deny_args(), COMMERCIAL),                         # allow
        g.request("deny_request", deny_args("33 CFR 117.5", "no"), COMMERCIAL),     # deny
        g.request("escalate_request", {"request": "r1", "section": "117.821", "draw": 1,
                                       "missing": ["vessel_class"], "reason": "?"}),
        g.request("cancel_opening", {"opening_id": "o1", "section": "117.821", "draw": 1}),
        g.request("open_bridge", opening()),                                        # FC
        g.request("schedule_opening", opening(section="117.9999")),                 # FC
        g.request("schedule_opening", opening(), units="0" * 64),                   # FC
        g.request("schedule_opening", opening(), {"vessel_class": {"value": "commercial",
                                                                   "source": "agent"}}),
    ]
    out = [g.client.judge(r) for r in reqs]
    raw, _ = g.client.exchange(b"{not json")
    out.append(raw)
    big, _ = g.client.exchange(b"{" + b" " * (MAX_REQUEST_BYTES + 10) + b"}")
    out.append(big)
    return out


def test_log_chain_verifies_and_every_line_has_rule_id_and_version(gate):  # noqa: F811
    replies = _mixed(gate)
    assert [r["decision"] for r in replies[:10]] == [
        "allow", "deny", "escalate", "escalate", "escalate", "allow", "allow", "deny", "allow",
        "allow"]
    assert all(r["decision"] == "deny" and r["rule_ids"] == [FC] for r in replies[10:])
    ok, n, bad = gate_log.verify_chain(gate.log_path)
    assert (ok, n, bad) == (True, len(replies), None)
    logged = lines(gate)
    assert [x["seq"] for x in logged] == list(range(1, n + 1)) == [r["seq"] for r in replies]
    for x in logged:                                                          # G1
        assert x["rule_ids"] and all(r and v for r, v in x["rule_ids"])
        assert all(e["rule_id"] and e["rule_version"] and e["doc_id"] == DOC_117_NEW
                   for e in x["evaluated"])
        assert "token" not in x and "key" not in x
    assert logged[0]["evaluated"] and logged[0]["request"]["facts"] == COMMERCIAL
    assert [x["stage"] for x in logged[-2:]] == ["transport", "transport"]
    # a changed line, a removed line or a token breaks the chain at that line
    raw = gate.log_path.read_bytes().split(b"\n")
    bad_line = json.loads(raw[1])
    bad_line["decision"] = "allow"
    gate.log_path.write_bytes(b"\n".join([raw[0], gate_log.canonical_line(bad_line), *raw[2:]]))
    assert gate_log.verify_chain(gate.log_path)[0] is False
    assert gate_log.verify_chain(gate.log_path)[2].startswith("line 3: prev_sha256")
    gate.log_path.write_bytes(b"\n".join([raw[0], *raw[2:]]))
    assert gate_log.verify_chain(gate.log_path)[2].startswith("line 2: seq")


def test_replay_of_every_line_gives_the_same_decision(gate):  # noqa: F811             # G3
    _mixed(gate)
    assert gate_log.replay(gate.log_path, gate.store.path) == []
    # a line whose logged decision differs from what its request gives is caught
    raw = gate.log_path.read_bytes().split(b"\n")
    line = json.loads(raw[1])
    assert line["decision"] == "deny" and line["next_allowed"] == "2026-08-14T09:00:00"
    line["next_allowed"] = "2026-08-14T09:15:00"
    gate.log_path.write_bytes(b"\n".join([raw[0], gate_log.canonical_line(line), *raw[2:]]))
    mism = gate_log.replay(gate.log_path, gate.store.path)
    assert [(m["seq"], m["fields"]) for m in mism] == [(2, ["next_allowed"])]


def test_an_existing_log_is_continued_and_a_broken_one_stops_the_gate(gate):  # noqa: F811
    req = gate.request("schedule_opening", opening(), COMMERCIAL)
    gate.client.judge(req)
    gate.process.stop()
    again = gate.start()
    assert again.ok, again.error
    assert gate.client.judge(req)["seq"] == 2
    assert gate_log.verify_chain(gate.log_path) == (True, 2, None)
    again.stop()
    with gate.log_path.open("ab") as f:
        f.write(b'{"seq":3}\n')
    broken = gate.start()
    assert not broken.ok and broken.returncode == 2 and "does not verify" in broken.error


# -- fail closed (P15) -----------------------------------------------------------------------------

def test_manifest_altered_under_a_running_gate_denies(gate):  # noqa: F811
    req = gate.request("schedule_opening", opening(), COMMERCIAL)
    assert gate.client.judge(req)["decision"] == "allow"
    path = manifest_of(gate)
    data_path = path.parent / BindingsManifest.model_validate_json(path.read_bytes()).file
    for victim in (path, data_path):
        original = victim.read_bytes()
        victim.write_bytes(original.replace(b"signed_off", b"signed_of_", 1)
                           if victim == data_path else original + b" ")
        try:
            got = gate.client.judge(req)
            assert (got["decision"], got["rule_ids"], got["token"]) == ("deny", [FC], None)
            assert "no longer verifies" in got["explanation"]["message"]
        finally:
            victim.write_bytes(original)
        assert gate.client.judge(req)["decision"] == "allow"      # verifies again
    assert gate_log.verify_chain(gate.log_path)[0]


def test_killed_gate_and_silence_are_deny(gate):  # noqa: F811
    req = gate.request("schedule_opening", opening(), COMMERCIAL)
    # silence: a stopped gate accepts the connection but never answers within the deadline
    os.kill(gate.process.pid, signal.SIGSTOP)
    try:
        quick = GateClient(gate.process.socket_path, gate.key, deadline=0.5)
        got = quick.judge(req)
        assert (got["decision"], got["rule_ids"], got["seq"]) == ("deny", [FC], None)
        assert "deadline" in got["explanation"]["message"]
    finally:
        os.kill(gate.process.pid, signal.SIGCONT)
    # killed: nothing listens
    os.kill(gate.process.pid, signal.SIGKILL)
    gate.process.proc.wait()
    got = gate.client.judge(req)
    assert (got["decision"], got["rule_ids"], got["token"]) == ("deny", [FC], None)
    assert not gate.client.check_token(req, got)


def test_an_oversized_request_is_denied_without_hanging(gate):  # noqa: F811
    req = gate.request("schedule_opening", {**opening(), "request": "x" * MAX_REQUEST_BYTES},
                       COMMERCIAL)
    got = gate.client.judge(req)
    assert (got["decision"], got["rule_ids"]) == ("deny", [FC])
    assert "oversized" in got["explanation"]["message"]
    # a client that keeps sending without a newline and never closes gets its deny as soon as
    # the limit is passed, well before the gate's I/O deadline (3 s here)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(1.5)
        s.connect(str(gate.process.socket_path))
        s.sendall(b"{" + b" " * (MAX_REQUEST_BYTES + 10))
        reply = json.loads(s.makefile("rb").readline())
    finally:
        s.close()
    assert (reply["decision"], reply["rule_ids"], reply["token"]) == ("deny", [FC], None)
    # the gate is still serving
    assert gate.client.judge(gate.request("schedule_opening", opening(), COMMERCIAL)
                             )["decision"] == "allow"


@pytest.mark.parametrize("change,why", [
    ({"tool": "open_bridge"}, "unknown tool"),
    ({"args": opening(section="117.9999")}, "unknown target"),
    ({"units": "f" * 64}, "stale units id"),
    ({"facts": {"vessel_class": "commercial"}}, "malformed"),
    ({"facts": {"vessel_class": {"value": "commercial", "source": "agent"}}}, "malformed"),
    ({"args": {**opening(), "notice_received_at": "2026-08-13T00:00:00"}}, "malformed"),
    ({"extra": 1}, "malformed"),
    ({"as_of": "2020-01-01"}, "no single version"),
])
def test_malformed_unknown_and_stale_requests_are_denied(gate, change, why):  # noqa: F811
    req = {**gate.request("schedule_opening", opening(), COMMERCIAL), **change}
    got = gate.client.judge(req)
    assert (got["decision"], got["rule_ids"], got["token"]) == ("deny", [FC], None)
    assert why in got["explanation"]["message"]


def test_an_unwritable_log_is_a_deny_and_never_an_allow(gate):  # noqa: F811
    req = gate.request("schedule_opening", opening(), COMMERCIAL)
    assert gate.client.judge(req)["seq"] == 1
    saved = gate.log_path.read_bytes()
    gate.log_path.unlink()
    gate.log_path.mkdir()                     # no file can be appended here, even by root
    try:
        got = gate.client.judge(req)
        assert (got["decision"], got["rule_ids"], got["token"], got["seq"]) == (
            "deny", [FC], None, None)
        assert "cannot be written" in got["explanation"]["message"]
    finally:
        gate.log_path.rmdir()
        gate.log_path.write_bytes(saved)
    assert gate.client.judge(req)["seq"] == 2       # the sequence number was not used
    assert gate_log.verify_chain(gate.log_path) == (True, 2, None)


def test_a_set_with_an_unsigned_binding_never_starts(gate, tmp_path):  # noqa: F811
    """A bindings set whose files hash consistently but hold an unsigned binding: the gate
    loads bindings only through `load_bindings`, so it refuses to start and its client meets
    silence (a fail-closed deny)."""
    path = manifest_of(gate)
    m = BindingsManifest.model_validate_json(path.read_bytes())
    rows = [Binding.model_validate_json(x) for x in
            (path.parent / m.file).read_bytes().split(b"\n")[:-1]]
    rows[0] = Binding.model_validate({**rows[0].model_dump(), "status": "analysed"})
    data = b"".join(canonical_json(b) for b in rows)
    sha = hashlib.sha256(data).hexdigest()
    (path.parent / f"bindings-data-{sha[:16]}.jsonl").write_bytes(data)
    mbytes = canonical_json(m.model_copy(update={"sha256": sha,
                                                 "file": f"bindings-data-{sha[:16]}.jsonl"}))
    bad_id = hashlib.sha256(mbytes).hexdigest()
    (path.parent / f"bindings-{bad_id[:16]}.json").write_bytes(mbytes)
    gate.process.stop()
    p = gate.start(bindings_id=bad_id, log_dir=tmp_path / "log2")
    assert not p.ok and p.returncode == 2 and "not signed_off" in p.error
    got = gate.client.judge(gate.request("schedule_opening", opening(), COMMERCIAL))
    assert (got["decision"], got["rule_ids"]) == ("deny", [FC])


def test_a_missing_or_invalid_models_config_stops_the_gate_at_startup(gate, tmp_path):  # noqa: F811
    gate.process.stop()
    bad = tmp_path / "models.json"
    bad.write_text(json.dumps({"profiles": {"claude_code_opus": {"model": "<set later>"}}}))
    for models in (tmp_path / "absent.json", bad):
        p = gate.start(models=models, log_dir=tmp_path / "log-models")
        assert not p.ok and p.returncode == 2 and "models config" in p.error
        assert not gate.process.socket_path.exists()
    # a valid config given at serve time is read instead of the repo's
    good = tmp_path / "good.json"
    good.write_text(MODELS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    p = gate.start(models=good, log_dir=tmp_path / "log-models")
    assert p.ok, p.error
    p.stop()


def test_the_socket_lives_in_a_private_directory(gate, tmp_path):  # noqa: F811
    d = gate.process.socket_path.parent
    assert (d.stat().st_mode & 0o777) == 0o700
    assert (gate.process.socket_path.stat().st_mode & 0o777) == 0o600
    gate.process.stop()
    shared = Path(private_socket()).parent
    os.chmod(shared, 0o755)
    try:
        p = gate.start(socket_path=shared / "gate.sock")
        assert not p.ok and p.returncode == 2 and "mode 0700" in p.error
    finally:
        shared.rmdir()


def test_the_key_is_never_written(gate):  # noqa: F811
    """The key's bytes (and their hex) appear in no log line, no file under the store or the
    log directory, the gate's arguments or environment, or any file it holds open."""
    _mixed(gate)
    pid = gate.process.pid
    needles = (gate.key, gate.key.hex().encode())
    found = []

    def scan(name: str, data: bytes) -> None:
        if any(n in data for n in needles):
            found.append(name)

    scan("log", gate.log_path.read_bytes())
    for root in (gate.store.path, gate.log_dir):
        for p in Path(root).rglob("*"):
            if p.is_file():
                scan(str(p), p.read_bytes())
    scan("cmdline", Path(f"/proc/{pid}/cmdline").read_bytes())
    scan("environ", Path(f"/proc/{pid}/environ").read_bytes())
    fds = list(Path(f"/proc/{pid}/fd").iterdir())
    assert fds
    for fd in fds:
        target = os.readlink(fd)
        if target.startswith("/") and Path(target).is_file():
            scan(target, Path(target).read_bytes())
    assert not found, found
    # the key was really used: an allow's token verifies only under it
    req = gate.request("schedule_opening", opening(), COMMERCIAL)
    assert gate.client.check_token(req, gate.client.judge(req))


# -- visibility (P5) -------------------------------------------------------------------------------

def test_hidden_rule_text_is_withheld(gate):  # noqa: F811
    args = opening(CLOSED)
    seen = gate.client.judge(gate.request("schedule_opening", args, COMMERCIAL,
                                          caller="user:acme-0"))
    hidden = gate.client.judge(gate.request("schedule_opening", args, COMMERCIAL,
                                            caller="user:globex-0"))
    # enforcement ignores visibility: the same decision, rule ids and sections
    for k in ("decision", "rule_ids", "deciding_sections", "next_allowed"):
        assert seen[k] == hidden[k]
    (rule, _), = seen["rule_ids"]
    assert seen["decision"] == "deny" and rule == "33 CFR 117.821(a)"
    assert seen["explanation"]["rule_text"][rule].startswith("(a) The draw of the Main Street")
    assert hidden["explanation"]["rule_text"] == {rule: None}
    # an unknown caller sees no text either; system rules keep their fixed text
    nobody = gate.client.judge(gate.request("schedule_opening", args, COMMERCIAL,
                                            caller="user:nobody"))
    assert nobody["explanation"]["rule_text"] == {rule: None}
    fc = gate.client.judge(gate.request("open_bridge", args, COMMERCIAL, caller="user:globex-0"))
    assert fc["explanation"]["rule_text"] == {FC[0]: dm.SYSTEM_TEXT[FC[0]]}


def test_the_server_module_never_imports_z3():
    import subprocess
    import sys

    out = subprocess.run([sys.executable, "-c", "import adr_store.gate.server, "
                          "adr_store.gate.client, adr_store.gate.log, sys; "
                          "print('z3' in sys.modules)"], capture_output=True, text=True)
    assert out.stdout.strip() == "False"


def test_a_running_gate_sees_requests_one_line_each(gate):  # noqa: F811
    """Protocol: a request without a trailing newline is still one request; bytes after the
    first newline are ignored."""
    req = gate.request("schedule_opening", opening(), COMMERCIAL)
    data = json.dumps(req).encode()
    reply, why = gate.client.exchange(data + b"\n" + data + b"\n")
    assert why is None and reply["decision"] == "allow"
    assert len(lines(gate)) == 1
    assert gate_server.MAX_REQUEST_BYTES == 65_536 and gate_server.IO_DEADLINE_S == 30.0
    assert isinstance(GateProcess, type)


def test_the_cli_serves_verifies_and_replays(gate, tmp_path, capsys):  # noqa: F811
    import subprocess
    import sys

    from adr_store import cli

    gate.client.judge(gate.request("schedule_opening", opening(), COMMERCIAL))
    gate.client.judge(gate.request("schedule_opening", opening(CLOSED), COMMERCIAL))
    assert cli.main(["gate", "verify", "--log", str(gate.log_dir)]) == 0
    assert "2 line(s); the chain verifies" in capsys.readouterr().out
    assert cli.main(["gate", "replay", "--store", str(gate.store.path), "--log",
                     str(gate.log_path)]) == 0
    assert "2 identical, 0 differ" in capsys.readouterr().out
    with gate.log_path.open("ab") as f:
        f.write(b"{}\n")
    assert cli.main(["gate", "verify", "--log", str(gate.log_dir)]) == 1
    # `adr gate serve` reads the key from the descriptor and refuses bindings that do not load
    r, w = os.pipe()
    os.write(w, new_key())
    os.close(w)
    out = subprocess.run([sys.executable, "-m", "adr_store.cli", "gate", "serve", "--store",
                          str(gate.store.path), "--bindings", "0" * 64, "--log",
                          str(tmp_path / "l"), "--socket", str(gate.process.socket_path),
                          "--key-fd", str(r)], pass_fds=(r,), capture_output=True, text=True)
    os.close(r)
    assert out.returncode == 2 and "do not load" in out.stderr
