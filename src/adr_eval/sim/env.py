"""The environment of one simulated task (Phase 4 spec §12.6, §13.1-§13.2; P13, P15, P23, P33,
P35, P37, P49; Review Focus 5; Task 19). It runs in its own process (`main`); the in-process
`Env` is for unit tests and for that process.

**Reads** go to the store's `Tools` in-process as `user:auditor` (`rule_lookup`, `define`,
`check_rules`, `procedure_lookup`, `query_table` on the drawbridge tables), with the scenario's
`as_of` as the default filter; `get_request` returns the request, the record (every fact with
its source) and the registry; `ask_user(field)` returns the scripted answer (`user.answer`) and
writes a known fact to the record as `{"value", "source": "user", "seq"}`, `seq` being the
call's number (P33). At start the environment writes `local_procedure_conflict` from the
registry (`tasks.registry_fact`, P37). The agent has no tool that writes a fact.

**Side effects** (`schedule_opening`, `deny_request`, `escalate_request`, `cancel_opening`). In
arms `gate` and `gate-runtime` each call is sent to the gate, which this environment spawns
(`GateProcess`, the key on an inherited pipe, never written anywhere) and asks through one
`GateClient`: the request holds the call's arguments, completed with the target the gate needs
(`deny_request` and `escalate_request` take the request's section, draw and requested time,
`cancel_opening` the opening's section and draw), and the current record as facts. The effect
runs only when the client verifies the allow's single-use token (`check_token`). A gate deny or
escalate changes nothing (P35); an allow whose token does not verify is a fail-closed deny. In
arms `no-gate` and `prompt` side effects run directly.

**The procedure runtime** (`runtime.Runtime` over `desk-request@1`, §9.3; Task 21) runs here,
in the environment, beside the gate and never in the agent loop (N13). Arm `gate-runtime`
forces it on (the measured arm, builder note 19; a test may give its own `runtime`); in the
other arms it is on only when the environment is given a `profile` whose flag in
`runtime_config` (`config/runtime.json`) is enabled (A4), and `adr-eval sim drawbridge` gives
none, so its arms `no-gate`, `prompt` and `gate` are §13.5's arms without it. With a runtime,
every well-formed call is put to `Runtime.allows` (with the record as facts) before anything
else: a refusal executes nothing, never reaches the gate, and is logged with its rule id
`adr.runtime.refused@1`; a side effect it allows then goes to the gate as above, so both must
allow. After a call that succeeded, the runtime advances on its result (for `ask_user`, the
result with `learned`, whether the user knew the answer, and `value`, the field's value in the
record, which the agent never sees). The runtime adds nothing to what the agent sees but a
refusal, so the arms share their calls until it refuses (P50).

**Malformed calls** (Review Focus 5): an unknown tool, arguments that are not an object, a
missing or extra argument, a wrong type (`ARG_SCHEMAS`: exact types, a `draw` is an int and not
a bool, times are `YYYY-MM-DDTHH:MM:SS` with no offset), an unknown request id or opening id, or
a table that is not a drawbridge table: refused before the gate sees it, logged as a deny under
`adr.gate.fail-closed@1`; nothing executes and the trial goes on.

**The log** (`env.jsonl` in `log_dir`, canonical JSON lines): a `start` line (task, arm, initial
record, registry, bindings and units ids, the reference draw the monitor uses, the gate instance
id), one `call` line per call (its number, tool, arguments, `ok`, result or refusal, the record the
call was judged on, the fact an answer wrote, the executed effect, and for a gated arm the gate's
sequence number, instance id, decision and `token_ok`; never the token), and an `end` line with the
end state at `close`. With a runtime the `start` line names it (`{"procedure", "source": "arm" or
"profile", "step"}`) and each call line holds `{"step", "decision": "allow" or "refuse", "after",
"rule_id"?}` (null without one). Logged arguments are bounded: a string over 1,024 characters
(`MAX_LOGGED_CHARS`) keeps its first 256 with `{"truncated": true, "sha256", "length"}`; an executed
deny also logs the sections its full text cites, for the monitor. The task's
`reference["bindings_id"]` must be the store's `bindings/HEAD`, or the environment refuses to start
(the tasks were drawn from other bindings). Two runs of one scripted trace give the same bytes
except the gate instance id (the run directory's timestamp, P38, names the directory and is never
written in it).
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import secrets
import shutil
import sys
from pathlib import Path
from typing import Any

from adr_eval.corpora import REPO_ROOT
from adr_eval.sim import runtime as runtime_mod
from adr_eval.sim import user
from adr_eval.sim.tasks import SimError, SimTask, ref_to_dict, reference_draws, registry_fact
from adr_eval.sim.world import World
from adr_store.bindings.decide import cited_sections

__all__ = ["ARG_SCHEMAS", "ARMS", "CALLER", "DESK_POLICY_PATH", "GATED", "GATED_ARMS", "READS",
           "TOOLS", "Env", "fail_closed_refusal", "load_desk_policy", "main", "malformed_refusal"]

TOOLS = ("get_request", "ask_user", "rule_lookup", "define", "check_rules", "procedure_lookup",
         "query_table", "schedule_opening", "deny_request", "escalate_request", "cancel_opening")
GATED = TOOLS[7:]
READS = TOOLS[:7]
ARMS = ("no-gate", "prompt", "gate", "gate-runtime")
GATED_ARMS = ("gate", "gate-runtime")
CALLER = "user:auditor"
DESK_POLICY_PATH = REPO_ROOT / "config" / "sim" / "desk_policy.txt"   # §13.2, every arm
FAIL_CLOSED = ["adr.gate.fail-closed@1", "1"]
KEY_BYTES = 32
MAX_LOGGED_CHARS = 1024      # a longer logged string keeps KEPT_CHARS, its SHA-256 and length
KEPT_CHARS = 256
# per tool: {"required": {arg: kind}, "optional": {arg: kind}}; kinds are checked exactly
ARG_SCHEMAS: dict[str, dict] = {
    "get_request": {"required": {"id": "str"}, "optional": {}},
    "ask_user": {"required": {"field": "str"}, "optional": {}},
    "rule_lookup": {"required": {}, "optional": {"query": "str", "rule_id": "str", "part": "str",
                                                 "as_of": "str", "closure": "bool",
                                                 "limit": "int"}},
    "define": {"required": {"term": "str"}, "optional": {"context": "str", "as_of": "str"}},
    "check_rules": {"required": {"intent": "object"},
                    "optional": {"facts": "object", "as_of": "str"}},
    "procedure_lookup": {"required": {}, "optional": {"task": "str", "id": "str", "view": "str",
                                                      "as_of": "str", "limit": "int"}},
    "query_table": {"required": {"table": "str"},
                    "optional": {"filters": "object", "op": "str", "fields": "strs",
                                 "order": "strs", "limit": "int"}},
    "schedule_opening": {"required": {"request": "str", "section": "str", "draw": "int",
                                      "open_at": "time"}, "optional": {}},
    "deny_request": {"required": {"request": "str", "rule_id": "str", "reason": "str"},
                     "optional": {}},
    "escalate_request": {"required": {"request": "str", "missing": "strs", "reason": "str"},
                         "optional": {}},
    "cancel_opening": {"required": {"opening_id": "str"}, "optional": {}},
}
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_REFUSAL_KEYS = ("decision", "rule_ids", "deciding_sections", "missing_facts", "next_allowed",
                 "evaluated_outcome")


def load_desk_policy(path: Path = DESK_POLICY_PATH) -> str:
    """The desk policy (§13.2: six instructions, about 200 words, identical in every arm)."""
    return Path(path).read_text(encoding="utf-8")


def _kind_ok(kind: str, v: Any) -> bool:
    from adr_store.bindings.facts import parse_local_datetime

    if kind == "str":
        return isinstance(v, str)
    if kind == "int":
        return type(v) is int and v >= 1
    if kind == "bool":
        return type(v) is bool
    if kind == "object":
        return isinstance(v, dict)
    if kind == "strs":
        return isinstance(v, list) and all(isinstance(x, str) for x in v)
    return isinstance(v, str) and bool(_TIME.fullmatch(v)) and parse_local_datetime(v) is not None


def _schema_problem(tool: object, args: object) -> str | None:
    if not isinstance(tool, str) or tool not in TOOLS:
        return f"unknown tool {str(tool)[:40]!r}"
    if not isinstance(args, dict):
        return f"{tool}: the arguments must be an object"
    schema = ARG_SCHEMAS[tool]
    extra = sorted(str(k) for k in args if k not in schema["required"]
                   and k not in schema["optional"])
    if extra:
        return f"{tool}: unknown argument(s) {', '.join(extra)[:120]}"
    for k, kind in {**schema["required"], **schema["optional"]}.items():
        if k not in args:
            if k in schema["required"]:
                return f"{tool}: missing argument {k}"
        elif not _kind_ok(kind, args[k]):
            want = {"str": "a string", "int": "a positive integer", "bool": "true or false",
                    "object": "an object", "strs": "a list of strings",
                    "time": "a local time YYYY-MM-DDTHH:MM:SS (no offset)"}[kind]
            return f"{tool}: {k} must be {want}"
    return None


def fail_closed_refusal(why: str) -> dict:
    """A refusal under `adr.gate.fail-closed@1` (P15), saying why."""
    return {"decision": "deny", "rule_ids": [list(FAIL_CLOSED)], "deciding_sections": [],
            "missing_facts": [], "next_allowed": None, "evaluated_outcome": None,
            "message": f"deny: fail closed: {why}"}


def malformed_refusal(problem: str) -> dict:
    """The refusal of a malformed call: a deny under `adr.gate.fail-closed@1`."""
    return fail_closed_refusal(f"malformed call: {problem}")


def _json_safe(v: Any) -> Any:
    return json.loads(json.dumps(v, default=lambda o: f"<{type(o).__name__}>"))


def _cut(s: str) -> str | dict:
    if len(s) <= MAX_LOGGED_CHARS:
        return s
    return {"text": s[:KEPT_CHARS], "truncated": True,
            "sha256": hashlib.sha256(s.encode("utf-8", "surrogatepass")).hexdigest(),
            "length": len(s)}


def _long_strings(v: Any) -> set[str]:
    if isinstance(v, str):
        return {v} if len(v) > MAX_LOGGED_CHARS else set()
    if isinstance(v, dict):
        return set().union(*(_long_strings(k) | _long_strings(x) for k, x in v.items()))
    if isinstance(v, list):
        return set().union(*(_long_strings(x) for x in v))
    return set()


def _echoes_bounded(out: dict, args: Any) -> dict:
    """`out` as logged: a result or refusal that echoes a long argument string (a query, a
    term, a field) logs it bounded as the argument is; the store's own text is kept whole."""
    long = _long_strings(_json_safe(args))
    if not long:
        return _json_safe(out)

    def walk(x: Any) -> Any:
        if isinstance(x, str):
            return _cut(x) if x in long else x
        if isinstance(x, list):
            return [walk(y) for y in x]
        if isinstance(x, dict):
            return {k: walk(y) for k, y in x.items()}
        return x
    return walk(_json_safe(out))


def _bounded(v: Any) -> Any:
    """`v` as logged (JSON-safe): every string over `MAX_LOGGED_CHARS` characters, value or key,
    becomes its first `KEPT_CHARS` characters with `truncated`, its SHA-256 and its length (a
    key becomes a string of the same parts)."""
    def walk(x: Any) -> Any:
        if isinstance(x, str):
            return _cut(x)
        if isinstance(x, list):
            return [walk(y) for y in x]
        if isinstance(x, dict):
            out = {}
            for k, y in x.items():
                c = _cut(k)
                key = c if isinstance(c, str) else \
                    f"{c['text']}...[truncated sha256={c['sha256']} length={c['length']}]"
                out[key] = walk(y)
            return out
        return x
    return walk(_json_safe(v))


def _line(entry: dict) -> bytes:
    return (json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            + "\n").encode("utf-8")


class Env:
    """The environment of `task` in `arm` over the store at `store_path`, logging to
    `log_dir/env.jsonl` (a new file; module text). `close` stops its gate."""

    def __init__(self, store_path: Path, task: SimTask, arm: str, log_dir: Path, *,
                 runtime: runtime_mod.Runtime | None = None, profile: str | None = None,
                 runtime_config: Path | None = None):
        from adr_store.bindings.manifest import read_bindings_head
        from adr_store.tools import NO_BINDINGS, Tools

        if arm not in ARMS:
            raise ValueError(f"unknown arm {arm!r}; arms are {', '.join(ARMS)}")
        if runtime is not None and arm != "gate-runtime":
            raise ValueError("a runtime is given only in arm gate-runtime; elsewhere the "
                             "profile's flag in config/runtime.json decides")
        source = None
        if arm == "gate-runtime":            # the measured arm forces it on (builder note 19)
            runtime, source = runtime or runtime_mod.Runtime(
                runtime_mod.load_desk_procedure()), "arm"
        elif profile is not None and runtime_mod.runtime_enabled(profile, runtime_config):
            runtime, source = runtime_mod.Runtime(runtime_mod.load_desk_procedure()), "profile"
        self.store_path = Path(store_path)
        self.task, self.arm, self.runtime = task, arm, runtime
        self.log_dir = Path(log_dir)
        self.log_path = self.log_dir / "env.jsonl"
        if self.log_path.exists():
            raise ValueError(f"{self.log_path} exists: every run logs to a new directory")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.tools = Tools(self.store_path, acl=True, caller=CALLER)
        self.bindings_id = read_bindings_head(self.store_path)
        if self.bindings_id is None:
            raise SimError(NO_BINDINGS.format(self.tools.snapshot[:12]))
        drawn_from = task.reference.get("bindings_id")
        if drawn_from != self.bindings_id:
            raise SimError(f"task {task.task_id} was drawn from bindings "
                           f"{str(drawn_from)[:12]}, but bindings/HEAD is "
                           f"{self.bindings_id[:12]}: regenerate the tasks or restore the head")
        m, refs, _ = reference_draws(self.store_path, self.bindings_id)
        req = task.request
        self.ref = refs.get((req["section"], req["draw"]))
        if self.ref is None:
            raise SimError(f"§ {req['section']} draw {req['draw']} is no agreement draw of "
                           f"bindings {self.bindings_id[:12]}")
        self.units_id = m.units_id
        record = copy.deepcopy(task.record)
        record["local_procedure_conflict"] = registry_fact(task)
        self.world = World(task, record)
        self._n = 0
        self._closed = False
        self._gate = self._client = None
        if arm in GATED_ARMS:
            self._start_gate()
        try:
            self._log({"kind": "start", "task_id": task.task_id, "arm": arm,
                       "as_of": task.as_of, "request": task.request, "record": record,
                       "registry": task.registry, "bindings_id": self.bindings_id,
                       "units_id": self.units_id, "reference": ref_to_dict(self.ref),
                       "gate": None if self._gate is None else
                       {"instance": self._gate.instance},
                       "runtime": None if runtime is None else
                       {"procedure": runtime.name, "source": source, "step": runtime.active}})
        except BaseException:
            self._closed = True
            if self._gate is not None:
                self._gate.stop()
                shutil.rmtree(self._gate.socket_path.parent, ignore_errors=True)
            raise

    # -- the gate --------------------------------------------------------------------------------

    def _start_gate(self) -> None:
        from adr_store.gate.client import GateClient, GateProcess, private_socket

        key = secrets.token_bytes(KEY_BYTES)          # held in memory only (P23)
        proc = GateProcess(self.store_path, self.bindings_id, self.log_dir / "gate",
                           private_socket(), key, units_id=self.units_id)
        if not proc.ok:
            shutil.rmtree(proc.socket_path.parent, ignore_errors=True)
            raise SimError(f"the gate did not start: {proc.error or proc.returncode}")
        self._gate = proc
        self._client = GateClient(proc.socket_path, key)

    def close(self) -> None:
        """Log the end state and stop the gate (idempotent)."""
        if self._closed:
            return
        self._closed = True
        self._log({"kind": "end", "end_state": self.world.end_state()})
        if self._gate is not None:
            self._gate.stop()
            shutil.rmtree(self._gate.socket_path.parent, ignore_errors=True)

    def __enter__(self) -> Env:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _log(self, entry: dict) -> None:
        with open(self.log_path, "ab") as f:
            f.write(_line(entry))

    def log_lines(self) -> list[dict]:
        """The log so far, parsed."""
        return [json.loads(x) for x in self.log_path.read_bytes().splitlines()]

    # -- a call ----------------------------------------------------------------------------------

    def call(self, tool: str, args: dict) -> dict:
        """One tool call: `{"ok": True, "result": ...}` or `{"ok": False, "refusal": ...}`
        (module text). Never raises for what the agent sends."""
        self._n += 1
        entry: dict[str, Any] = {"kind": "call", "n": self._n, "tool": _bounded(tool),
                                 "args": _bounded(args), "record": None, "fact": None,
                                 "effect": None, "gate": None, "runtime": None}
        problem = _schema_problem(tool, args) or self._target_problem(tool, args)
        refusal = None
        if problem:
            out = {"ok": False, "refusal": malformed_refusal(problem)}
        elif self.runtime is not None and (refusal := self._runtime_refusal(tool, args,
                                                                             entry)):
            out = {"ok": False, "refusal": refusal}
        elif tool in READS:
            out = self._read(tool, args, entry)
        else:
            out = self._side_effect(tool, args, entry)
        if entry["runtime"] is not None and refusal is None:
            if out.get("ok") is True:
                self.runtime.advance(tool, self._runtime_result(tool, args, out["result"]),
                                     args)
            entry["runtime"]["after"] = self.runtime.active
        entry.update(_echoes_bounded(out, args))
        self._log(entry)
        return out

    def _runtime_refusal(self, tool: str, args: dict, entry: dict) -> dict | None:
        """The runtime's refusal of the call (None when it allows), noted in `entry`."""
        step = self.runtime.active
        ok, refusal = self.runtime.allows(tool, args, copy.deepcopy(self.world.record))
        entry["runtime"] = {"step": step, "decision": "allow" if ok else "refuse",
                            "after": step}
        if ok:
            return None
        entry["runtime"]["rule_id"] = refusal["rule_ids"][0][0]
        return refusal

    def _runtime_result(self, tool: str, args: dict, result: dict) -> dict:
        """The result the runtime advances on: for `ask_user`, with `learned` and `value`."""
        if tool != "ask_user":
            return result
        learned = result.get("answer") != user.DONT_KNOW
        fact = self.world.record.get(args["field"]) if learned else None
        return {**result, "learned": learned,
                "value": fact.get("value") if isinstance(fact, dict) else None}

    def _target_problem(self, tool: str, args: dict) -> str | None:
        rid = args.get("id") if tool == "get_request" else args.get("request")
        if tool in ("get_request", "schedule_opening", "deny_request", "escalate_request") \
                and rid != self.task.request["id"]:
            return f"{tool}: unknown request id {str(rid)[:40]!r}"
        if tool == "cancel_opening" and self._opening(args["opening_id"]) is None:
            return f"cancel_opening: unknown opening id {args['opening_id'][:40]!r}"
        if tool == "query_table" and not args["table"].startswith("drawbridge_"):
            return f"query_table: {args['table'][:40]!r} is not a drawbridge table"
        return None

    def _opening(self, opening_id: str) -> dict | None:
        return next((o for o in self.world.openings if o["opening_id"] == opening_id), None)

    # -- reads -----------------------------------------------------------------------------------

    def _read(self, tool: str, args: dict, entry: dict) -> dict:
        if tool == "get_request":
            return {"ok": True, "result": {"request": self.task.request,
                                           "record": copy.deepcopy(self.world.record),
                                           "registry": self.task.registry}}
        if tool == "ask_user":
            text, fact = user.answer(self.task, args["field"])
            if fact is not None:
                written = {"value": fact["value"], "source": "user", "seq": self._n}
                self.world.record[fact["name"]] = written
                entry["fact"] = {"name": fact["name"], **written}
            return {"ok": True, "result": {"field": args["field"], "answer": text}}
        day = self.task.as_of[:10]
        kw = dict(args)
        try:
            if tool == "rule_lookup":
                res = self.tools.rule_lookup(kw.pop("query", None), as_of=kw.pop("as_of", day),
                                             **kw)
            elif tool == "define":
                res = self.tools.define(kw.pop("term"), kw.pop("context", None),
                                        as_of=kw.pop("as_of", day))
            elif tool == "check_rules":
                res = self.tools.check_rules(kw["intent"], kw.get("facts"),
                                             as_of=kw.get("as_of", self.task.as_of))
            elif tool == "procedure_lookup":
                res = self.tools.procedure_lookup(kw.pop("task", None),
                                                  as_of=kw.pop("as_of", day), **kw)
            else:
                res = self.tools.query_table(kw.pop("table"), kw.pop("filters", None),
                                             kw.pop("op", "count"), applicability={"as_of": day},
                                             **kw)
        except Exception as e:  # noqa: BLE001 - a refused read is the agent's answer
            return {"ok": False, "refusal": {"code": getattr(e, "code", type(e).__name__),
                                             "message": str(e)}}
        return {"ok": True, "result": _json_safe(res.to_dict())}

    # -- side effects ----------------------------------------------------------------------------

    def _gate_args(self, tool: str, args: dict) -> dict:
        req = self.task.request
        if tool == "schedule_opening":
            return dict(args)
        if tool == "deny_request":
            return {**args, "section": req["section"], "draw": req["draw"],
                    "requested_open_at": req["requested_open_at"]}
        if tool == "escalate_request":
            return {**args, "section": req["section"], "draw": req["draw"]}
        o = self._opening(args["opening_id"])
        return {**args, "section": o["section"], "draw": o["draw"]}

    def _side_effect(self, tool: str, args: dict, entry: dict) -> dict:
        gate_args = self._gate_args(tool, args)
        record = copy.deepcopy(self.world.record)
        entry["record"] = record
        entry["gate_args"] = _bounded(gate_args)
        decided: dict | None = None
        if self._client is not None:
            request = {"session": self.task.task_id, "caller": CALLER, "tool": tool,
                       "args": gate_args, "as_of": self.task.as_of, "facts": record,
                       "units": self.units_id}
            reply = self._client.judge(request)
            token_ok = self._client.check_token(request, reply)
            entry["gate"] = {"seq": reply["seq"], "instance": reply["instance"],
                             "decision": reply["decision"], "token_ok": token_ok}
            decided = {k: reply[k] for k in _REFUSAL_KEYS}
            decided["message"] = reply["explanation"].get("message")
            decided["rule_text"] = reply["explanation"].get("rule_text")
            if not token_ok:
                if reply["decision"] == "allow":
                    decided = fail_closed_refusal("the allow carries no token the environment "
                                                  "accepts")
                return {"ok": False, "refusal": decided}
        effect = self._execute(tool, args)
        entry["effect"] = _bounded(effect)
        result = {"executed": effect}
        if decided is not None:
            result["gate"] = decided
        return {"ok": True, "result": result}

    def _execute(self, tool: str, args: dict) -> dict:
        req, w = self.task.request, self.world
        if tool == "schedule_opening":
            o = {"opening_id": f"o{len(w.openings) + 1}", "request": args["request"],
                 "section": args["section"], "draw": args["draw"], "open_at": args["open_at"],
                 "status": "active"}
            w.openings.append(o)
            return {"opening": dict(o)}
        if tool == "deny_request":
            w.denials.append(req["id"])
            cited = sorted(cited_sections(f"{args['rule_id']} {args['reason']}"))
            return {"denial": req["id"], "rule_id": args["rule_id"], "reason": args["reason"],
                    "cited_sections": cited}
        if tool == "escalate_request":
            w.escalations.append(req["id"])
            return {"escalation": req["id"], "missing": list(args["missing"]),
                    "reason": args["reason"]}
        o = self._opening(args["opening_id"])
        o["status"] = "cancelled"
        return {"cancel": o["opening_id"]}


# -- the process -------------------------------------------------------------------------------

def _write(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    """The environment process: JSON lines on stdin and stdout. The first line is
    `{"task": <a SimTask in the §13.4 format>, "arm": <arm>}`, answered by `{"ready": true,
    "first_message": ...}` (or `{"ready": false, "error": ...}` and exit 2); then each line
    `{"tool", "args"}` is answered by the call's result, until `{"end": true}` or the end of
    input, answered by `{"end_state": ...}`."""
    ap = argparse.ArgumentParser(prog="python -m adr_eval.sim.env")
    ap.add_argument("--store", type=Path, required=True)
    ap.add_argument("--log", type=Path, required=True, help="a new directory for env.jsonl")
    ap.add_argument("--profile", default=None,
                    help="the agent's model profile, whose flag in --runtime-config turns the "
                         "procedure runtime on outside arm gate-runtime (default none)")
    ap.add_argument("--runtime-config", type=Path, default=None,
                    help="the per-profile runtime flags (default config/runtime.json)")
    a = ap.parse_args(argv)
    try:
        first = json.loads(sys.stdin.readline())
        task = SimTask.model_validate(first["task"])
        env = Env(a.store, task, first["arm"], a.log, profile=a.profile,
                  runtime_config=a.runtime_config)
    except Exception as e:  # noqa: BLE001 - any start failure is reported, never hidden
        _write({"ready": False, "error": f"{type(e).__name__}: {e}"})
        return 2
    try:
        _write({"ready": True, "first_message": user.first_message(task)})
        for raw in sys.stdin:
            if not raw.strip():
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                msg = {"tool": None, "args": None}
            if isinstance(msg, dict) and msg.get("end") is True:
                break
            msg = msg if isinstance(msg, dict) else {}
            _write(env.call(msg.get("tool"), msg.get("args")))
        _write({"end_state": env.world.end_state()})
    finally:
        env.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
