"""The environment's client of the gate (Phase 4 spec §12.6, P15, P23, P38): one request per
connection on the gate's Unix socket, under one I/O deadline for the whole exchange (a clock
input that can only deny).

`judge(request)` returns the gate's reply, or a fail-closed deny under
`adr.gate.fail-closed@1` (with `seq` None and no token) when the gate is not running, stays
silent, misses the deadline, or replies with anything malformed: a reply that is not one JSON
object of the protocol's keys and types, an allow whose token does not verify for this request
and sequence number, or a token on anything but an allow.

`check_token(request, reply)` is the environment's mediation: True only for an allow whose
token verifies for exactly this request and sequence number, the first time that sequence
number is presented (single use, P23); the side effect runs only then. Accepted sequence
numbers are kept per gate (socket path and key digest) for the whole process, so every client
of one gate in a process shares them; they are not persisted, so a restarted environment
relies on the gate never reusing a sequence number (it continues its log) under the same key.
The key is held in memory only.

`GateProcess` starts `python -m adr_store.gate.server` with the key on an inherited pipe (never
an argument or an environment variable) and waits for its ready line; `private_socket` makes a
short socket path in a new 0700 directory (Unix socket paths are limited to about 100 bytes).
"""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from adr_store.bindings.decide import SYSTEM_RULES, SYSTEM_TEXT
from adr_store.gate import tokens
from adr_store.gate.server import IO_DEADLINE_S

__all__ = ["REPLY_KEYS", "GateClient", "GateProcess", "fail_closed_reply", "private_socket"]

REPLY_KEYS = tuple(sorted(("seq", "decision", "rule_ids", "deciding_sections", "missing_facts",
                          "next_allowed", "evaluated_outcome", "explanation", "token")))
# sequence numbers already accepted, per gate (socket path, SHA-256 of the key): shared by every
# client of this process, so a second client refuses a token the first accepted
_SEEN: dict[tuple[str, str], set[int]] = {}
_SEEN_LOCK = threading.Lock()
MAX_REPLY_BYTES = 1 << 20


def fail_closed_reply(why: str) -> dict:
    """The deny the environment acts on when the gate gives no usable reply."""
    rule = list(SYSTEM_RULES["fail_closed"])
    return {"seq": None, "decision": "deny", "rule_ids": [rule], "deciding_sections": [],
            "missing_facts": [], "next_allowed": None, "evaluated_outcome": None,
            "explanation": {"message": f"deny: fail closed: {why}",
                            "rule_text": {rule[0]: SYSTEM_TEXT[rule[0]]}},
            "token": None}


def _strs(v: object) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _shape_problem(r: object) -> str | None:
    if not isinstance(r, dict) or sorted(r) != list(REPLY_KEYS):
        return "the reply is not an object of the protocol's keys"
    if r["decision"] not in ("allow", "deny", "escalate"):
        return "the reply's decision is not allow, deny or escalate"
    if not isinstance(r["rule_ids"], list) or not r["rule_ids"] or not all(
            isinstance(x, list) and len(x) == 2 and all(isinstance(y, str) and y for y in x)
            for x in r["rule_ids"]):
        return "the reply carries no [rule_id, rule_version]"
    if not (_strs(r["deciding_sections"]) and _strs(r["missing_facts"])
            and (r["next_allowed"] is None or isinstance(r["next_allowed"], str))
            and r["evaluated_outcome"] in (None, "allow", "deny", "escalate")
            and isinstance(r["explanation"], dict)
            and (r["seq"] is None or type(r["seq"]) is int)):
        return "the reply's fields have the wrong types"
    return None


class GateClient:
    """A client of the gate at `socket_path` holding the shared `key` (module text)."""

    def __init__(self, socket_path: Path, key: bytes, deadline: float = IO_DEADLINE_S):
        if not isinstance(key, bytes) or len(key) < tokens.MIN_KEY_BYTES:
            raise ValueError(f"the key must be at least {tokens.MIN_KEY_BYTES} bytes")
        self.socket_path = Path(socket_path)
        self._key = key
        self.deadline = float(deadline)
        gate = (str(self.socket_path.resolve()), hashlib.sha256(key).hexdigest())
        with _SEEN_LOCK:
            self._seen = _SEEN.setdefault(gate, set())

    def __repr__(self) -> str:
        return f"GateClient({str(self.socket_path)!r}, deadline={self.deadline:g})"

    def exchange(self, data: bytes) -> tuple[dict | None, str | None]:
        """(the reply object, None) for the request bytes `data` (sent as given, newline
        added when missing), or (None, why) on silence, a timeout or bytes that are not
        JSON."""
        end = time.monotonic() + self.deadline
        if not data.endswith(b"\n"):
            data += b"\n"
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.settimeout(self.deadline)
            try:
                s.connect(str(self.socket_path))
            except OSError as e:
                return None, f"the gate is not running ({type(e).__name__})"
            try:
                s.sendall(data)
                s.shutdown(socket.SHUT_WR)
            except OSError:
                pass                     # the gate may have replied and stopped reading
            buf = bytearray()
            while b"\n" not in buf and len(buf) <= MAX_REPLY_BYTES:
                left = end - time.monotonic()
                if left <= 0:
                    return None, "the gate missed the I/O deadline"
                s.settimeout(left)
                try:
                    chunk = s.recv(65536)
                except TimeoutError:
                    return None, "the gate missed the I/O deadline"
                except OSError as e:
                    return None, f"the connection failed ({type(e).__name__})"
                if not chunk:
                    break
                buf += chunk
        finally:
            s.close()
        if b"\n" not in buf:
            return None, "the gate was silent"
        try:
            return json.loads(bytes(buf).split(b"\n", 1)[0]), None
        except ValueError:
            return None, "the reply is not JSON"

    def judge(self, request: dict) -> dict:
        """The gate's reply to `request`, or a fail-closed deny (module text)."""
        try:
            data = json.dumps(request, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError):
            return fail_closed_reply("the request is not JSON")
        reply, why = self.exchange(data)
        if reply is None:
            return fail_closed_reply(why)
        if problem := _shape_problem(reply):
            return fail_closed_reply(problem)
        if reply["decision"] == "allow":
            if not tokens.verify(self._key, reply["token"], request, "allow", reply["seq"]):
                return fail_closed_reply("the allow carries no token that verifies")
        elif reply["token"] is not None:
            return fail_closed_reply("a token on a decision that is not an allow")
        return reply

    def check_token(self, request: dict, reply: dict) -> bool:
        """Whether the side effect of `request` may run on `reply` (module text); a sequence
        number is accepted once."""
        if not isinstance(reply, dict) or reply.get("decision") != "allow":
            return False
        seq = reply.get("seq")
        if type(seq) is not int:
            return False
        if not tokens.verify(self._key, reply.get("token"), request, "allow", seq):
            return False
        with _SEEN_LOCK:
            if seq in self._seen:
                return False
            self._seen.add(seq)
        return True


def private_socket(prefix: str = "adrg-") -> Path:
    """A socket path in a new private (0700) directory under the system temporary directory,
    short enough for AF_UNIX; remove its directory when done."""
    return Path(tempfile.mkdtemp(prefix=prefix, dir="/tmp" if os.path.isdir("/tmp") else None)
                ) / "gate.sock"


class GateProcess:
    """A gate process (`adr_store.gate.server`) on `socket_path`, started with `key` written to
    an inherited pipe; `ok` once it printed its ready line, else `error` holds its stderr and
    `returncode` its exit status. Stop it with `stop` (or use it as a context manager)."""

    def __init__(self, store_path: Path, bindings_id: str, log_dir: Path, socket_path: Path,
                 key: bytes, *, units_id: str | None = None, models: Path | None = None,
                 deadline: float = IO_DEADLINE_S, startup: float = 120.0):
        self.socket_path = Path(socket_path)
        args = [sys.executable, "-m", "adr_store.gate.server", "--store", str(store_path),
                "--bindings", bindings_id, "--log", str(log_dir), "--socket",
                str(socket_path), "--deadline", repr(float(deadline))]
        if units_id is not None:
            args += ["--units", units_id]
        if models is not None:
            args += ["--models", str(models)]
        r, w = os.pipe()
        try:
            self.proc = subprocess.Popen([*args, "--key-fd", str(r)], pass_fds=(r,),
                                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE)
        finally:
            os.close(r)
        try:
            os.write(w, key)
        except OSError:
            pass                                          # the gate already exited
        finally:
            os.close(w)
        self.ready_line = self._ready(startup)
        self.ok = self.ready_line is not None
        self.error: str | None = None
        self.returncode: int | None = None
        if not self.ok:
            self.stop()

    def _ready(self, startup: float) -> str | None:
        with selectors.DefaultSelector() as sel:
            sel.register(self.proc.stdout, selectors.EVENT_READ)
            if not sel.select(timeout=startup):
                return None
        line = self.proc.stdout.readline().decode("utf-8", "replace")
        return line.strip() if line.startswith("gate ready") else None

    @property
    def pid(self) -> int:
        return self.proc.pid

    def stop(self) -> None:
        """Terminate the gate (killed when it does not stop), reap it and close its pipes."""
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.returncode = self.proc.returncode
        if self.proc.stderr is not None and not self.proc.stderr.closed:
            err = self.proc.stderr.read().decode("utf-8", "replace").strip()
            self.error = self.error or err or None
        for f in (self.proc.stdout, self.proc.stderr):
            if f is not None:
                f.close()

    def __enter__(self) -> GateProcess:
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
        if self.socket_path.parent.name.startswith("adrg-"):     # made by `private_socket`
            shutil.rmtree(self.socket_path.parent, ignore_errors=True)
