"""The gate's decision log (Phase 4 spec §12.6; G1, G3): `<log_dir>/gate.jsonl`, written only by
the gate, append-only, one canonical JSON line per decision (sorted keys, no padding, UTF-8).

Each line carries `seq` (1, 2, ...), `prev_sha256` (the SHA-256 of the previous line's bytes
without its newline; `GENESIS` for the first), and the fields of §12.6 that the server writes
(`server.log_line`): session, caller, tool, canonical arguments, facts with their sources, the
units id the request named and the one loaded, the bindings id, every binding evaluated
(`rule_id`, `rule_version`, `doc_id`, `binding_id`, `binding_version`, value T/F/U), the
decision, the deciding rule ids with versions, `deciding_sections`, the missing facts,
`next_allowed`, the fail-closed reason, the SHA-256 of the message, and `stage`: `request` for
a decision on the request's own content, `transport` for a fail-closed deny the gate's state
or the bytes received forced (an oversized or unparseable request, bindings that no longer
verify). A line holds no token and no key (`FORBIDDEN`).

`verify_chain` checks every line: canonical JSON of an object, `seq` consecutive from 1,
`prev_sha256` chaining, no forbidden field, and (G1) at least one `[rule_id, rule_version]`
and, for every evaluated binding, its `rule_id`, `rule_version` and `doc_id`.

`replay` (G3) re-evaluates every `request` line from its logged request and bindings id
against the store (`server.evaluate_request`, the gate's own function) and lists each line
whose decision, rule ids, deciding sections, missing facts, next allowed time, evaluated
bindings or message hash differ; a `transport` line must be a fail-closed deny. A bindings id
that no longer loads makes every one of its lines a mismatch.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

__all__ = ["FORBIDDEN", "GENESIS", "LOG_NAME", "append", "canonical_line", "read_lines",
           "replay", "verify_chain"]

LOG_NAME = "gate.jsonl"
GENESIS = "0" * 64
FORBIDDEN = ("token", "key")
COMPARED = ("decision", "rule_ids", "deciding_sections", "missing_facts", "next_allowed",
            "evaluated", "message_sha256")


def canonical_line(line: dict) -> bytes:
    """`line` as canonical JSON bytes, without a newline."""
    return json.dumps(line, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def append(path: Path, line: dict, prev_sha256: str) -> str:
    """Append `line` with `prev_sha256` to the log at `path` in one write (created 0600) and
    return this line's SHA-256. OSError when it cannot be written whole; ValueError for a line
    carrying a forbidden field or its own `prev_sha256`."""
    bad = [k for k in (*FORBIDDEN, "prev_sha256") if k in line]
    if bad:
        raise ValueError(f"a log line may not carry {', '.join(bad)}")
    data = canonical_line({**line, "prev_sha256": prev_sha256})
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        written = os.write(fd, data + b"\n")
        if written != len(data) + 1:
            raise OSError(f"{path}: short write ({written} of {len(data) + 1} bytes)")
        os.fsync(fd)
    finally:
        os.close(fd)
    return _sha256(data)


def read_lines(path: Path) -> list[bytes]:
    """The log's lines (bytes, no newline); [] for a missing log."""
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        return []
    return raw.split(b"\n")[:-1] if raw.endswith(b"\n") else raw.split(b"\n")


def _g1_problem(line: dict) -> str | None:
    rules = line.get("rule_ids")
    if not isinstance(rules, list) or not rules or not all(
            isinstance(r, list) and len(r) == 2 and all(isinstance(x, str) and x for x in r)
            for r in rules):
        return "no [rule_id, rule_version]"
    for e in line.get("evaluated") or []:
        if not all(isinstance(e.get(k), str) and e.get(k) for k in
                   ("rule_id", "rule_version", "doc_id")):
            return "an evaluated binding without rule_id, rule_version and doc_id"
    return None


def verify_chain(path: Path) -> tuple[bool, int, str | None]:
    """(whether the whole log verifies, the number of lines, the first bad line as
    "line N: why", or None). A missing log is an empty, valid one."""
    lines = read_lines(path)
    prev = GENESIS
    for n, raw in enumerate(lines, 1):
        try:
            line = json.loads(raw)
        except ValueError:
            return False, len(lines), f"line {n}: not JSON"
        if not isinstance(line, dict):
            return False, len(lines), f"line {n}: not an object"
        if canonical_line(line) != raw:
            return False, len(lines), f"line {n}: not canonical JSON"
        if line.get("seq") != n:
            return False, len(lines), f"line {n}: seq {line.get('seq')!r} is not {n}"
        if line.get("prev_sha256") != prev:
            return False, len(lines), f"line {n}: prev_sha256 does not chain"
        if bad := [k for k in FORBIDDEN if k in line]:
            return False, len(lines), f"line {n}: carries {', '.join(bad)}"
        if problem := _g1_problem(line):
            return False, len(lines), f"line {n}: {problem}"
        prev = _sha256(raw)
    return True, len(lines), None


def replay(path: Path, store_path: Path) -> list[dict]:
    """The G3 mismatches of the log at `path` replayed against the store (module text): one
    `{seq, field(s), logged, replayed}` per line that differs."""
    from adr_store.bindings.decide import SYSTEM_RULES
    from adr_store.gate import server

    contexts: dict[tuple[str, str], object] = {}
    out = []
    fail_closed = [list(SYSTEM_RULES["fail_closed"])]
    for raw in read_lines(path):
        line = json.loads(raw)
        if line.get("stage") != "request":
            if line.get("decision") != "deny" or line.get("rule_ids") != fail_closed:
                out.append({"seq": line.get("seq"), "fields": ["decision", "rule_ids"],
                            "logged": [line.get("decision"), line.get("rule_ids")],
                            "replayed": ["deny", fail_closed]})
            continue
        key = (line.get("bindings"), line.get("units_loaded"))
        if key not in contexts:
            try:
                contexts[key] = server.load_enforcement(store_path, key[0], key[1])
            except Exception as e:  # noqa: BLE001 - a set that no longer loads cannot replay
                contexts[key] = e
        enf = contexts[key]
        if isinstance(enf, Exception):
            out.append({"seq": line.get("seq"), "fields": ["bindings"],
                        "logged": key[0], "replayed": f"{type(enf).__name__}: {enf}"})
            continue
        d = server.evaluate_request(enf, line["request"], key[1])
        got = server.decision_fields(d)
        diff = [k for k in COMPARED if line.get(k) != got[k]]
        if diff:
            out.append({"seq": line.get("seq"), "fields": diff,
                        "logged": {k: line.get(k) for k in diff},
                        "replayed": {k: got[k] for k in diff}})
    return out
