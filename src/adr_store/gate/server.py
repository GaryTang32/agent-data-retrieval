"""The gate process (Phase 4 spec §12.6, P5, P13, P15, P23, P31, P38; Task 18):

    adr gate serve --store S --bindings ID --log DIR --socket PATH --key-fd N
                   [--units ID] [--models PATH] [--deadline SECONDS]
    python -m adr_store.gate.server (the same arguments)

**Startup.** The HMAC key is read whole from the inherited file descriptor `--key-fd` (a pipe
the parent writes and closes) and then lives only in memory: it is never written to the log,
a file, an argument, an environment variable or a message. The review model is read once from
`--models` (default the repo's `config/models.json`) because loading bindings checks each
review's served model; a missing or invalid file stops the gate here. The bindings are loaded
only through `manifest.load_bindings` (every hash, sign-off and draw verified); the units id
must be the one the bindings were built against (default: that one); the 33 CFR 117 versions
come from the snapshot's applicability overlay and the sections of each from the rule cards of
the units build. An existing log must verify end to end (`log.verify_chain`) and is
continued. The socket's directory must be private (mode 0700; it is created so when absent)
and the socket is made 0600. Any startup failure prints one line on stderr and exits 2, with
no socket: a client then meets silence, which it treats as a fail-closed deny.

**Protocol.** One connection per request: one JSON object on one line, at most
`MAX_REQUEST_BYTES` bytes, `{session, caller, tool, args, as_of, facts, units}` with `facts`
`{name: {value, source ("record" or "user"), seq?}}` (P13, P33: facts only from the
environment's record; `args` define only the action). The reply is one line, `{seq,
decision, rule_ids, deciding_sections, missing_facts, next_allowed, explanation: {message,
rule_text}, token}`, with a token (`tokens.sign`) on allows only. Connections are served one at
a time, each under the I/O deadline (`IO_DEADLINE_S`, P38: a clock input that can only deny).

**Every request** is first checked against the gate's state: the bindings manifest and data
file are stat-ed and, when either changed, the set is loaded again; a set that no longer loads
(an altered manifest, an unsigned binding) denies every request until it loads again. Then
`evaluate_request`: a malformed request (not an object, other keys, wrong types, a fact
without a value or with another source), a units id other than the loaded one, or anything
`decide.judge` fails closed on (an unknown tool or target, malformed arguments or facts, an
evaluation error) is a deny under `adr.gate.fail-closed@1`; otherwise the decision of §12.6.
An oversized or unparseable request is a `transport` deny (`log` module text). The log line is
written before the reply; when it cannot be written the reply is a fail-closed deny without a
token (and the sequence number is not used).

**Visibility (P5).** Enforcement ignores what the caller may read. The explanation's
`rule_text` gives each deciding rule's card text when the caller can see its document under
the current ACL (`acl.resolve` per request, against the store's HEAD), else None; system rules
give their fixed text. An ACL that cannot be resolved (stale: the ACL freshness check, the
other clock input that can only deny) withholds every rule text.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import socket
import stat
import sys
from pathlib import Path

from adr_store import acl as acl_mod
from adr_store.bindings import decide as dm
from adr_store.bindings.decide import Decision, Enforcement, fail_closed
from adr_store.gate import log as gate_log
from adr_store.gate import tokens

__all__ = ["FACT_SOURCES", "IO_DEADLINE_S", "MAX_REQUEST_BYTES", "REQUEST_KEYS", "Gate",
           "decision_fields", "evaluate_request", "load_enforcement", "main", "serve"]

MAX_REQUEST_BYTES = 65_536
IO_DEADLINE_S = 30.0
REQUEST_KEYS = ("args", "as_of", "caller", "facts", "session", "tool", "units")
FACT_SOURCES = ("record", "user")
FACT_KEYS = ("seq", "source", "value")
DRAIN_BYTES = 4 * MAX_REQUEST_BYTES
DRAIN_S = 1.0


class GateStartError(Exception):
    """The gate cannot start (module text); the message never holds the key."""


# -- the enforcement context -----------------------------------------------------------------------

def load_enforcement(store_path: Path, bindings_id: str, units_id: str | None = None
                     ) -> Enforcement:
    """The bindings `bindings_id` (loaded through `load_bindings`, which verifies them), the
    33 CFR 117 versions of their snapshot and the rule cards of the units build (`units_id`,
    default the bindings'). Raises when any of them does not load or the ids disagree."""
    from adr_store.applicability import load_overlay
    from adr_store.bindings.manifest import BindingsError, load_bindings
    from adr_store.units import overlay as units_overlay

    m, bindings = load_bindings(store_path, bindings_id)
    units_id = units_id or m.units_id
    if units_id != m.units_id:
        raise BindingsError(f"bindings {bindings_id[:12]} were built against units "
                            f"{m.units_id[:12]}, not {units_id[:12]}")
    overlay = load_overlay(store_path, m.snapshot)
    if overlay is None:
        raise BindingsError(f"no applicability overlay for snapshot {m.snapshot[:12]}")
    envelopes = {d: env for d, env in overlay.records.items() if env.chain_id == dm.CHAIN}
    um = units_overlay.load_units_manifest(store_path, units_id)
    if um.snapshot != m.snapshot:
        raise BindingsError(f"units {units_id[:12]} are of snapshot {um.snapshot[:12]}, the "
                            f"bindings of {m.snapshot[:12]}")
    sections: dict[str, set[str]] = {}
    texts: dict[tuple[str, str], str] = {}
    for u in units_overlay.load_units(store_path, um, "rule_card"):
        if u.doc_id in envelopes:
            sections.setdefault(u.doc_id, set()).add(dm.section_of(u.canonical_ref))
            texts[(u.canonical_ref, u.doc_id)] = u.body["text"]
    return Enforcement(bindings_id, units_id, m.snapshot, tuple(bindings), envelopes,
                       {d: frozenset(s) for d, s in sections.items()}, texts)


def _request_problem(req: object, units_loaded: str) -> str | None:
    if not isinstance(req, dict):
        return "malformed request: not a JSON object"
    keys = sorted(map(str, req))
    if keys != list(REQUEST_KEYS):
        return f"malformed request: keys {', '.join(keys)[:200]} are not {', '.join(REQUEST_KEYS)}"
    for k in ("session", "caller", "tool", "as_of", "units"):
        if not isinstance(req[k], str):
            return f"malformed request: {k} must be a string"
    if not isinstance(req["args"], dict) or not isinstance(req["facts"], dict):
        return "malformed request: args and facts must be objects"
    for name, entry in req["facts"].items():
        if not isinstance(entry, dict) or "value" not in entry or "source" not in entry or \
                any(k not in FACT_KEYS for k in entry):
            return f"malformed request: fact {name[:40]!r} is not {{value, source, seq?}}"
        if entry["source"] not in FACT_SOURCES:
            return f"malformed request: fact {name[:40]!r} has source other than record or user"
        if "seq" in entry and (type(entry["seq"]) is not int or entry["seq"] < 0):
            return f"malformed request: fact {name[:40]!r} has a bad seq"
    if req["units"] != units_loaded:
        return f"stale units id: {req['units'][:12]} is not the loaded {units_loaded[:12]}"
    return None


def evaluate_request(enf: Enforcement, req: object, units_loaded: str) -> Decision:
    """The gate's decision on a parsed request (module text): fail closed on a malformed request
    or another units id, else `decide.judge`. Never raises."""
    problem = _request_problem(req, units_loaded)
    if problem is not None:
        return fail_closed(problem)
    return dm.judge(enf, req["tool"], req["args"], req["facts"], req["as_of"])


def decision_fields(d: Decision) -> dict:
    """The logged fields of a decision (compared by `log.replay`)."""
    return {"decision": d.outcome, "rule_ids": [list(r) for r in d.rule_ids],
            "deciding_sections": list(d.deciding_sections),
            "missing_facts": list(d.missing_facts), "next_allowed": d.next_allowed,
            "evaluated": [dict(e.__dict__) for e in d.evaluated],
            "fail_closed": d.fail_closed, "message_sha256": d.message_sha256}


# -- the gate --------------------------------------------------------------------------------------

def _stat_key(path: Path) -> tuple | None:
    try:
        s = path.stat()
    except OSError:
        return None
    return (s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


class Gate:
    """One gate's state: the key, the loaded bindings, the log position. `handle` turns the
    bytes of one request into the reply (module text)."""

    def __init__(self, store_path: Path, bindings_id: str, units_id: str | None, log_dir: Path,
                 key: bytes):
        from adr_store.bindings.manifest import _find

        if not isinstance(key, bytes) or len(key) < tokens.MIN_KEY_BYTES:
            raise GateStartError(f"the key must be at least {tokens.MIN_KEY_BYTES} bytes")
        self._key = key
        self.store_path = Path(store_path)
        self.bindings_id = bindings_id
        try:
            self.enf = load_enforcement(self.store_path, bindings_id, units_id)
            self.manifest = _find(self.store_path, "bindings", bindings_id, "bindings")
        except Exception as e:  # noqa: BLE001 - the gate does not start on bindings it cannot load
            raise GateStartError(f"bindings {bindings_id[:12]} do not load: {e}") from e
        from adr_store.bindings.manifest import BindingsManifest

        data = BindingsManifest.model_validate_json(self.manifest.read_bytes()).file
        self.files = (self.manifest, self.manifest.parent / data)
        self.state = tuple(_stat_key(p) for p in self.files)
        self.units_id = self.enf.units_id
        self.broken: str | None = None
        self.log_path = Path(log_dir) / gate_log.LOG_NAME
        ok, n, bad = gate_log.verify_chain(self.log_path)
        if not ok:
            raise GateStartError(f"{self.log_path} does not verify: {bad}")
        lines = gate_log.read_lines(self.log_path)
        self.seq = n
        self.prev = gate_log.GENESIS if not lines else gate_log._sha256(lines[-1])
        self._acl_cache: dict = {}

    # -- state ----------------------------------------------------------------------------------

    def _check_state(self) -> str | None:
        """Why the loaded bindings cannot be trusted now, or None (re-loaded when a file
        changed)."""
        now = tuple(_stat_key(p) for p in self.files)
        if now != self.state:
            try:
                self.enf = load_enforcement(self.store_path, self.bindings_id, self.units_id)
                self.broken = None
            except Exception as e:  # noqa: BLE001 - bindings that do not load deny everything
                self.broken = f"the bindings manifest no longer verifies: {e}"[:300]
            self.state = now
        return self.broken

    def _rule_text(self, caller: object, d: Decision) -> dict[str, str | None]:
        visible: frozenset[str] = frozenset()
        try:
            head = (self.store_path / "HEAD").read_text(encoding="utf-8").strip()
            visible = frozenset(acl_mod.resolve(self.store_path, caller, head,
                                                cache=self._acl_cache).docs)
        except Exception:  # noqa: BLE001 - no resolvable access: every rule text withheld
            pass
        out: dict[str, str | None] = {}
        for rule_id, _ in d.rule_ids:
            if rule_id in dm.SYSTEM_TEXT:
                out[rule_id] = dm.SYSTEM_TEXT[rule_id]
                continue
            doc = d.sources.get(rule_id)
            out[rule_id] = self.enf.texts.get((rule_id, doc)) if doc in visible else None
        return out

    # -- one request ----------------------------------------------------------------------------

    def handle(self, raw: bytes, *, oversized: bool = False) -> dict:
        """The reply to the request bytes `raw` (one line, newline excluded), the log line
        written first (module text)."""
        req: object = None
        stage = "transport"
        if oversized:
            d = fail_closed(f"oversized request (more than {MAX_REQUEST_BYTES} bytes)")
        elif (broken := self._check_state()) is not None:
            d = fail_closed(broken)
        else:
            try:
                req = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                d = fail_closed("malformed request: not JSON")
            else:
                stage = "request"
                d = evaluate_request(self.enf, req, self.units_id)
        caller = req.get("caller") if isinstance(req, dict) else None
        seq = self.seq + 1
        line = {"seq": seq, "stage": stage, "request": req if stage == "request" else None,
                "request_sha256": gate_log._sha256(raw), "request_bytes": len(raw),
                "bindings": self.bindings_id, "units_loaded": self.units_id,
                **decision_fields(d), "token_issued": d.outcome == "allow"}
        try:
            sha = gate_log.append(self.log_path, line, self.prev)
        except (OSError, ValueError, TypeError):
            d = fail_closed("the decision log cannot be written")
            return self._reply(None, d, caller, None)
        self.seq, self.prev = seq, sha
        return self._reply(seq, d, caller, req)

    def _reply(self, seq, d: Decision, caller, signed_req) -> dict:
        token = None
        if d.outcome == "allow" and isinstance(signed_req, dict) and seq is not None:
            token = tokens.sign(self._key, signed_req, "allow", seq)
        return {"seq": seq, "decision": d.outcome, "rule_ids": [list(r) for r in d.rule_ids],
                "deciding_sections": list(d.deciding_sections),
                "missing_facts": list(d.missing_facts), "next_allowed": d.next_allowed,
                "explanation": {"message": d.message, "rule_text": self._rule_text(caller, d)},
                "token": token}


# -- the socket ------------------------------------------------------------------------------------

def _read_key(fd: int) -> bytes:
    chunks = []
    try:
        while True:
            b = os.read(fd, 4096)
            if not b:
                break
            chunks.append(b)
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)
    return b"".join(chunks)


def _private_dir(path: Path) -> None:
    if not path.exists():
        path.mkdir(mode=0o700, parents=True)
    s = path.stat()
    if not stat.S_ISDIR(s.st_mode) or s.st_mode & 0o077 or s.st_uid != os.getuid():
        raise GateStartError(f"{path}: the socket directory must be ours with mode 0700")


def _receive(conn: socket.socket) -> tuple[bytes | None, bool]:
    """(the request line without its newline, oversized?); None on silence or EOF without a
    newline."""
    buf = bytearray()
    while True:
        try:
            chunk = conn.recv(65536)
        except OSError:
            return None, False
        if not chunk:
            return (bytes(buf) if buf else None), False
        nl = chunk.find(b"\n")
        if nl >= 0:
            buf += chunk[:nl]
            return (bytes(buf), False) if len(buf) <= MAX_REQUEST_BYTES else (None, True)
        buf += chunk
        if len(buf) > MAX_REQUEST_BYTES:
            return None, True


def _drain(conn: socket.socket) -> None:
    """Read and drop what the client still sends (bounded), so closing does not reset the
    connection before it reads the reply."""
    conn.settimeout(DRAIN_S)
    left = DRAIN_BYTES
    with contextlib.suppress(OSError):
        while left > 0:
            chunk = conn.recv(min(65536, left))
            if not chunk:
                break
            left -= len(chunk)


def _serve_one(gate: Gate, conn: socket.socket, deadline: float) -> None:
    conn.settimeout(deadline)
    raw, oversized = _receive(conn)
    if raw is None and not oversized:
        return                                       # silence: no request, no decision
    reply = gate.handle(raw or b"", oversized=oversized)
    with contextlib.suppress(OSError):
        conn.sendall(json.dumps(reply, sort_keys=True, ensure_ascii=False).encode("utf-8")
                     + b"\n")
        conn.shutdown(socket.SHUT_WR)
    _drain(conn)


def serve(store_path: Path, bindings_id: str, units_id: str | None, log_dir: Path,
          socket_path: Path, key_fd: int, *, models: Path | None = None,
          deadline: float = IO_DEADLINE_S) -> int:
    """Run the gate until terminated (module text); 2 when it cannot start."""
    from adr_store.bindings import review

    key = _read_key(key_fd)
    socket_path, log_dir = Path(socket_path), Path(log_dir)
    try:
        if models is None:
            from adr_eval import runner

            models = runner.MODELS_PATH
        try:
            review.use_models_file(models)
        except ValueError as e:
            raise GateStartError(f"the models config cannot be read: {e}") from e
        log_dir.mkdir(parents=True, exist_ok=True)
        gate = Gate(store_path, bindings_id, units_id, log_dir, key)
        _private_dir(socket_path.parent)
        if socket_path.exists() or socket_path.is_symlink():
            socket_path.unlink()
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    except (GateStartError, OSError) as e:
        print(f"error: gate: {e}", file=sys.stderr)
        return 2
    del key
    try:
        srv.bind(str(socket_path))
        os.chmod(socket_path, 0o600)
        srv.listen(16)
    except OSError as e:
        srv.close()
        print(f"error: gate: cannot listen on {socket_path}: {e}", file=sys.stderr)
        return 2

    def stop(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    print(f"gate ready on {socket_path} (bindings {bindings_id[:12]}, units "
          f"{gate.units_id[:12]}, log {gate.log_path}, {gate.seq} line(s) before)", flush=True)
    try:
        while True:
            conn, _ = srv.accept()
            with conn:
                _serve_one(gate, conn, deadline)
    except (SystemExit, KeyboardInterrupt):
        return 0
    finally:
        srv.close()
        with contextlib.suppress(OSError):
            socket_path.unlink()


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--store", type=Path, required=True, help="store directory")
    p.add_argument("--bindings", required=True, metavar="ID", help="the bindings id to enforce")
    p.add_argument("--units", default=None, metavar="ID",
                   help="the units id requests must name (default: the bindings')")
    p.add_argument("--log", type=Path, required=True, metavar="DIR",
                   help="the decision log directory (gate.jsonl; continued when present)")
    p.add_argument("--socket", type=Path, required=True, metavar="PATH",
                   help="the Unix socket (its directory must be private, mode 0700)")
    p.add_argument("--key-fd", type=int, required=True, metavar="N",
                   help="an inherited file descriptor holding the HMAC key (read to EOF)")
    p.add_argument("--models", type=Path, default=None, metavar="PATH",
                   help="the models config (default config/models.json)")
    p.add_argument("--deadline", type=float, default=IO_DEADLINE_S, metavar="SECONDS",
                   help=f"the I/O deadline per connection (default {IO_DEADLINE_S:g})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="adr gate serve",
                                 description="Run the out-of-process gate (Phase 4 §12.6).")
    add_arguments(ap)
    a = ap.parse_args(argv)
    return serve(a.store, a.bindings, a.units, a.log, a.socket, a.key_fd, models=a.models,
                 deadline=a.deadline)


if __name__ == "__main__":
    sys.exit(main())
