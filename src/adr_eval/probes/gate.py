"""Gate fail-closed probes (Phase 4 spec §12.6, §15.4; criteria G1, G2, G3; Task 18): no model
calls, deterministic (seed `SEED4`).

`gate_failclosed(store_path, work_dir)` runs a real gate process (`client.GateProcess`, the key
on an inherited pipe) over a **shadow** of the store under `work_dir`: the store's top-level
entries linked, its `bindings/` directory copied, so every fault is planted in the shadow and
the store is never written (a real store under `.cache/store-p2` stays as it was). It needs
`bindings/HEAD` (ValueError without: on every real store before Task 22 there is none).

**Seeded requests** (`seeded_requests`): per gated tool, three requests the gate **allows**
under normal conditions, drawn by `random.Random(SEED4)` from candidates over the draws of the
version in force: `schedule_opening` at the half hours of the week after that version's first
day with a commercial vessel, no conflicting procedure and two days' notice; `deny_request` of
an opening the gate denies, citing a deciding rule; `escalate_request` and `cancel_opening` of
a draw. Every seeded request is judged first (`baseline`): each must be an allow whose token
the environment accepts once, so each probe shows a fault turning an allow into a deny.

**Conditions** (12, crossed with the 4 tools and 3 seeded requests: 144 probes), each probe a
row `{probe_id, condition, tool, seed, outcome, gate_decision, executed, rule_ids, reason}`:
`killed` (SIGKILL; nothing listens), `timeout` (SIGSTOP; a client with a 0.3 s deadline),
`malformed` (a key dropped, a fact smuggled into the arguments, bytes that are not JSON),
`oversized` (a string argument padded past `MAX_REQUEST_BYTES`), `unknown_tool`,
`unknown_target` (a section with no rule card in the version in force), `manifest_altered` (a
byte appended to the manifest, a byte changed in the data file, the manifest truncated, each
under the running gate and restored after), `unsigned_binding` (a gate started on a set whose
files hash consistently but hold a binding that is not signed off: it refuses to start, so its
socket is silent), `stale_units` (zeros, the units id with its last digit changed, the
bindings id), `forged_token` (the genuine allow's token with a digit changed, signed with
another key, or empty), `replayed_token` (the genuine allow accepted once, then presented
again), `mismatched_token` (a genuine allow presented with another request: another session,
other arguments, another caller). `unwritable_log` (the log replaced by a directory) is a
13th condition counted separately (`separate`). `outcome` is what the environment does: allow
only when the reply is an allow and `GateClient.check_token` accepts it (`executed`); a probe
passes when it is not executed.

`log_checks` gives G1 (`log.verify_chain`) and G3 (`log.replay`) over the probe gate's log.
"""

from __future__ import annotations

import contextlib
import json
import os
import random
import shutil
import signal
from datetime import datetime, timedelta
from pathlib import Path

from adr_store.bindings import decide as dm
from adr_store.bindings.dsl import Binding
from adr_store.bindings.manifest import BINDINGS_DIR, BindingsManifest, read_bindings_head
from adr_store.gate import log as gate_log
from adr_store.gate import tokens
from adr_store.gate.client import GateClient, GateProcess, private_socket
from adr_store.gate.server import MAX_REQUEST_BYTES, load_enforcement
from adr_store.records import canonical_json

__all__ = ["CONDITIONS", "SEED4", "SEPARATE", "TOOLS", "gate_failclosed", "log_checks",
           "seeded_requests", "summarize"]

SEED4 = 20261121
TOOLS = dm.GATED
CONDITIONS = ("killed", "timeout", "malformed", "oversized", "unknown_tool", "unknown_target",
              "manifest_altered", "unsigned_binding", "stale_units", "forged_token",
              "replayed_token", "mismatched_token")
SEPARATE = ("unwritable_log",)
SEEDS = 3
DEADLINE = 10.0
TIMEOUT_DEADLINE = 0.3
CALLER = "user:auditor"
FACTS_OK = {"vessel_class": {"value": "commercial", "source": "record"},
            "local_procedure_conflict": {"value": False, "source": "record"}}


# -- the shadow store and the seeded requests ------------------------------------------------------

def _shadow(store_path: Path, dest: Path) -> Path:
    """`dest` holding links to the store's top-level entries and a copy of `bindings/`."""
    store_path = Path(store_path).resolve()
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for p in sorted(store_path.iterdir()):
        if p.name in (BINDINGS_DIR, "log"):
            continue
        (dest / p.name).symlink_to(p)
    shutil.copytree(store_path / BINDINGS_DIR, dest / BINDINGS_DIR, symlinks=False)
    return dest


def _request(tool: str, args: dict, facts: dict, as_of: str, units: str, k: int) -> dict:
    return {"session": f"probe-{tool}-{k}", "caller": CALLER, "tool": tool, "args": args,
            "as_of": as_of, "facts": facts, "units": units}


def _notice(at: datetime) -> dict:
    return {**FACTS_OK, "notice_received_at": {"value": (at - timedelta(days=2)).isoformat(),
                                               "source": "record"}}


def seeded_requests(store_path: Path, bindings_id: str, seed: int = SEED4
                    ) -> dict[str, list[dict]]:
    """Per gated tool, `SEEDS` requests the gate allows (module text). ValueError when a tool
    has fewer candidates."""
    enf = load_enforcement(store_path, bindings_id)
    doc = enf.doc_in_force(None)
    if doc is None:
        raise ValueError("no single 33 CFR 117 version in force")
    first = enf.envelopes[doc].valid_from + timedelta(days=7)
    draws = sorted({(b.target["selector"]["section"], b.target["selector"]["draw"])
                    for b in enf.bindings if b.doc_id == doc},
                   key=lambda k: (dm.section_of(k[0]), k[1]))
    rng = random.Random(seed)
    as_of = f"{first.isoformat()}T05:00:00"
    out: dict[str, list[dict]] = {}
    allow, deny = [], []
    for section, draw in draws:
        for m in range(0, 7 * 1440, 30):
            at = datetime.combine(first, datetime.min.time()) + timedelta(minutes=m)
            args = {"request": "r", "section": section, "draw": draw,
                    "open_at": at.isoformat()}
            facts = _notice(at)
            d = dm.judge(enf, "schedule_opening", args, facts, as_of)
            if d.outcome == "allow":
                allow.append((args, facts))
            elif d.outcome == "deny" and d.deciding_sections:
                rule = d.rule_ids[0][0]
                dargs = {"request": "r", "section": section, "draw": draw,
                         "requested_open_at": at.isoformat(), "rule_id": rule,
                         "reason": f"the opening is closed under {rule}"}
                if dm.judge(enf, "deny_request", dargs, facts, as_of).outcome == "allow":
                    deny.append((dargs, facts))
    pools = {"schedule_opening": allow, "deny_request": deny,
             "escalate_request": [({"request": "r", "section": s, "draw": n,
                                    "missing": ["notice_received_at"], "reason": "unknown"},
                                   {}) for s, n in draws],
             "cancel_opening": [({"opening_id": f"o-{s}-{n}", "section": s, "draw": n}, {})
                                for s, n in draws]}
    for tool in TOOLS:
        pool = pools[tool]
        if not pool:
            raise ValueError(f"{tool}: no request the gate allows")
        picked = rng.sample(pool, SEEDS) if len(pool) >= SEEDS else \
            [pool[i % len(pool)] for i in range(SEEDS)]
        out[tool] = [_request(tool, a, f, as_of, enf.units_id, k)
                     for k, (a, f) in enumerate(picked)]
    return out


# -- planting and judging --------------------------------------------------------------------------

def _row(cond: str, tool: str, k: int, reply: dict | None, executed: bool, *,
         gate_decision: str | None = None, reason: str | None = None) -> dict:
    decision = None if reply is None else reply.get("decision")
    gate_decision = gate_decision or decision
    outcome = "allow" if executed else (decision if decision not in (None, "allow") else "deny")
    return {"probe_id": f"{cond}:{tool}:{k}", "condition": cond, "tool": tool, "seed": k,
            "outcome": outcome, "gate_decision": gate_decision, "executed": executed,
            "rule_ids": None if reply is None else reply.get("rule_ids"),
            "reason": reason if reason is not None else (reply or {}).get(
                "explanation", {}).get("message"),
            "separate": cond in SEPARATE}


def _act(client: GateClient, req: dict) -> tuple[dict, bool]:
    reply = client.judge(req)
    return reply, reply["decision"] == "allow" and client.check_token(req, reply)


def _absent_section(enf, doc: str, base: str) -> str:
    out = base
    while out in enf.sections.get(doc, frozenset()):
        out += "9"
    return out


def _with_args(req: dict, **update) -> dict:
    return {**req, "args": {**req["args"], **update}}


def _malformed(req: dict, k: int) -> bytes:
    if k == 0:
        return json.dumps({x: v for x, v in req.items() if x != "facts"}).encode()
    if k == 1:
        return json.dumps(_with_args(req, notice_received_at="2026-01-01T00:00:00")).encode()
    return json.dumps(req).encode()[:-7]


def _oversized(req: dict) -> dict:
    key = "opening_id" if req["tool"] == "cancel_opening" else "request"
    return _with_args(req, **{key: "x" * (MAX_REQUEST_BYTES + 1)})


def _unknown_tool(req: dict, k: int) -> dict:
    return {**req, "tool": (f"{req['tool']}_v2", req["tool"].upper(), f" {req['tool']}")[k]}


def _alter(files: tuple[Path, Path], k: int) -> bytes:
    manifest, data = files
    victim = data if k == 1 else manifest
    original = victim.read_bytes()
    if k == 0:
        victim.write_bytes(original + b" ")
    elif k == 1:
        i = original.index(b"signed_off")
        victim.write_bytes(original[:i] + b"S" + original[i + 1:])
    else:
        victim.write_bytes(original[: len(original) // 2])
    return original


def _unsigned_set(shadow: Path, bindings_id: str) -> str:
    """A set beside `bindings_id` in the shadow whose first binding is `analysed` (files
    named by their hashes, so only the sign-off check can refuse it); its id."""
    (path,) = (shadow / BINDINGS_DIR).glob(f"*/bindings-{bindings_id[:16]}.json")
    m = BindingsManifest.model_validate_json(path.read_bytes())
    rows = [Binding.model_validate_json(x)
            for x in (path.parent / m.file).read_bytes().split(b"\n")[:-1]]
    rows[0] = Binding.model_validate({**rows[0].model_dump(), "status": "analysed"})
    data = b"".join(canonical_json(b) for b in rows)
    sha = gate_log._sha256(data)
    name = f"bindings-data-{sha[:16]}.jsonl"
    (path.parent / name).write_bytes(data)
    mbytes = canonical_json(m.model_copy(update={"sha256": sha, "file": name}))
    bad = gate_log._sha256(mbytes)
    (path.parent / f"bindings-{bad[:16]}.json").write_bytes(mbytes)
    return bad


def _token_probes(cond: str, client: GateClient, req: dict, other: dict, k: int
                  ) -> tuple[dict, bool]:
    """A genuine allow of `req` tampered with by `cond` and presented to the environment."""
    reply = client.judge(req)
    if reply["decision"] != "allow":
        return reply, False
    if cond == "forged_token":
        token = reply["token"]
        forged = (token[:-1] + ("0" if token[-1] != "0" else "1"),
                  tokens.sign(os.urandom(32), req, "allow", reply["seq"]), "")[k]
        return reply, client.check_token(req, {**reply, "token": forged})
    if cond == "replayed_token":
        if not client.check_token(req, reply):           # the one genuine execution
            return reply, False
        return reply, client.check_token(req, reply)
    changed = ({**req, "session": req["session"] + "-other"}, other,
               {**req, "caller": "user:outsider"})[k]
    return reply, client.check_token(changed, reply)


def gate_failclosed(store_path: Path, work_dir: Path, *, bindings_id: str | None = None,
                    seed: int = SEED4, deadline: float = DEADLINE,
                    logs: dict | None = None) -> list[dict]:
    """The gate fail-closed probes (module text): 144 rows of the 12 conditions, then 12 of the
    separate `unwritable_log`; `logs`, when given, receives the baseline rows and the probe
    gate's log path."""
    store_path, work_dir = Path(store_path), Path(work_dir)
    bindings_id = bindings_id or read_bindings_head(store_path)
    if bindings_id is None:
        raise ValueError(f"{store_path}: no bindings/HEAD to enforce; the gate probes need "
                         f"promoted bindings (`adr units review`, `adr bindings promote`)")
    shadow = _shadow(store_path, work_dir / "shadow")
    reqs = seeded_requests(shadow, bindings_id, seed)
    enf = load_enforcement(shadow, bindings_id)
    doc = enf.doc_in_force(None)
    (manifest,) = (shadow / BINDINGS_DIR).glob(f"*/bindings-{bindings_id[:16]}.json")
    data = manifest.parent / BindingsManifest.model_validate_json(manifest.read_bytes()).file
    key = os.urandom(32)
    log_dir = work_dir / "gate-log"
    sock = private_socket()
    rows: list[dict] = []
    logs = {} if logs is None else logs
    cases = [(tool, k, req) for tool in TOOLS for k, req in enumerate(reqs[tool])]
    proc = GateProcess(shadow, bindings_id, log_dir, sock, key, deadline=deadline)
    try:
        if not proc.ok:
            raise ValueError(f"the gate did not start: {proc.error}")
        client = GateClient(sock, key, deadline=deadline)
        baseline = []
        for tool, k, req in cases:
            reply, executed = _act(client, req)
            baseline.append(_row("baseline", tool, k, reply, executed))
            if not executed:
                raise ValueError(f"seeded {tool} request {k} is not allowed: "
                                 f"{reply['explanation']['message']}")
        logs["baseline"] = baseline
        for tool, k, req in cases:
            rows.append(_row("malformed", tool, k, *_raw(client, _malformed(req, k))))
        for tool, k, req in cases:
            rows.append(_row("oversized", tool, k, *_act(client, _oversized(req))))
        for tool, k, req in cases:
            rows.append(_row("unknown_tool", tool, k, *_act(client, _unknown_tool(req, k))))
        for tool, k, req in cases:
            base = ("117.9999", "118.1", "117.0")[k]
            target = _with_args(req, section=_absent_section(enf, doc, base))
            rows.append(_row("unknown_target", tool, k, *_act(client, target)))
        for tool, k, req in cases:
            stale = ("0" * 64, req["units"][:-1] + ("0" if req["units"][-1] != "0" else "1"),
                     bindings_id)[k]
            rows.append(_row("stale_units", tool, k, *_act(client, {**req, "units": stale})))
        for cond in ("forged_token", "replayed_token", "mismatched_token"):
            for i, (tool, k, req) in enumerate(cases):
                other = cases[(i + 1) % len(cases)][2]
                reply, executed = _token_probes(cond, client, req, other, k)
                rows.append(_row(cond, tool, k, reply, executed,
                                 reason=f"the environment refused the {cond.split('_')[0]} "
                                        f"token" if not executed else None))
        for tool, k, req in cases:
            original = _alter((manifest, data), k)
            victim = data if k == 1 else manifest
            try:
                rows.append(_row("manifest_altered", tool, k, *_act(client, req)))
            finally:
                victim.write_bytes(original)
        separate = []
        for tool, k, req in cases:
            path = log_dir / gate_log.LOG_NAME
            saved = path.read_bytes()
            path.unlink()
            path.mkdir()
            try:
                separate.append(_row("unwritable_log", tool, k, *_act(client, req)))
            finally:
                path.rmdir()
                path.write_bytes(saved)
        quick = GateClient(sock, key, deadline=TIMEOUT_DEADLINE)
        os.kill(proc.pid, signal.SIGSTOP)
        try:
            for tool, k, req in cases:
                rows.append(_row("timeout", tool, k, *_act(quick, req)))
        finally:
            os.kill(proc.pid, signal.SIGCONT)
        # the gate now serves the connections the stopped process queued (their clients gone);
        # a last request waits behind them, so the log is complete before the gate is killed
        client.judge(cases[0][2])
        bad_id = _unsigned_set(shadow, bindings_id)
        bad_sock = private_socket()
        with GateProcess(shadow, bad_id, work_dir / "gate-log-unsigned", bad_sock, key,
                         deadline=deadline) as bad:
            if bad.ok or "not signed_off" not in (bad.error or ""):
                raise ValueError(f"the gate on an unsigned set did not refuse it: {bad.error}")
            why = f"the gate refused to start on it (exit {bad.returncode})"
            bad_client = GateClient(bad_sock, key, deadline=deadline)
            for tool, k, req in cases:
                reply, executed = _act(bad_client, req)
                rows.append(_row("unsigned_binding", tool, k, reply, executed,
                                 reason=f"{reply['explanation']['message']}; {why}"))
        proc.proc.send_signal(signal.SIGKILL)
        proc.proc.wait()
        for tool, k, req in cases:
            rows.append(_row("killed", tool, k, *_act(client, req)))
    finally:
        proc.stop()
        with contextlib.suppress(OSError):
            shutil.rmtree(sock.parent)
    logs["log"] = log_dir / gate_log.LOG_NAME
    order = {c: i for i, c in enumerate(CONDITIONS)}
    rows.sort(key=lambda r: (order[r["condition"]], TOOLS.index(r["tool"]), r["seed"]))
    return rows + separate


def _raw(client: GateClient, data: bytes) -> tuple[dict, bool]:
    reply, why = client.exchange(data)
    if reply is None:
        from adr_store.gate.client import fail_closed_reply

        reply = fail_closed_reply(why)
    return reply, False


def log_checks(log_path: Path, store_path: Path) -> dict:
    """G1 (the chain and a rule id and version on every line) and G3 (every line replays to
    the same decision) over a probe gate's log, run against `store_path` (the shadow)."""
    ok, n, bad = gate_log.verify_chain(log_path)
    mism = gate_log.replay(log_path, store_path)
    return {"g1": {"lines": n, "chain_ok": ok, "first_bad": bad},
            "g3": {"lines": n, "identical": n - len(mism), "differ": len(mism)}}


def summarize(rows: list[dict]) -> dict:
    """Counts per condition: probes, allows, executions; the 144 and the separate 12."""
    def block(rs: list[dict]) -> dict:
        return {"n": len(rs), "allowed": sum(r["outcome"] == "allow" for r in rs),
                "executed": sum(r["executed"] for r in rs),
                "passed": sum(not r["executed"] and r["outcome"] != "allow" for r in rs)}

    main = [r for r in rows if not r["separate"]]
    sep = [r for r in rows if r["separate"]]
    conds = {c: block([r for r in rows if r["condition"] == c]) for c in (*CONDITIONS,
                                                                           *SEPARATE)}
    return {"total": block(main), "separate": block(sep), "conditions": conds,
            "tools": {t: block([r for r in main if r["tool"] == t]) for t in TOOLS}}
