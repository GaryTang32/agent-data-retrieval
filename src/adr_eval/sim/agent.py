"""The desk agent, its arms and the rounds of trials (Phase 4 spec §13.2, §13.3, §13.5; P18,
P28, P30, P35, P38; preflight N1, N9, N28, C17; builder note 18; Task 20).

**The system prompt** (`system_prompt`, template `prompts/agent.txt`, `AGENT_PROMPT_VERSION`)
is the desk policy (`config/sim/desk_policy.txt`: §13.2's six instructions, naming no
section), the tool list (all 11 tools in every arm, `check_rules` included: P18) and the reply
format. The arms differ only where §13.5 says: arm `prompt` adds, between the tool list and the
reply format, the verbatim text of §§ 117.5, 117.31 and 117.40 (`PROMPT_SECTIONS`) and of the
request's bridge section, read from the store in the 33 CFR 117 version the task's bindings
were built from (the version in force on every scenario date, P31). Arms `no-gate`, `gate` and
`gate-runtime` get the same prompt, so a trial's first call is one cache entry for the three
(identical input; the arms part once a gate refusal changes the transcript).

**One trial** (`run_trial`): up to `MAX_CALLS` agent calls, each
`client.complete(system, <rendered transcript>, max_tokens=MAX_TOKENS, repeat=trial,
cache_failures=True)`; the trial index is in the cache key, so k trials are k calls and a
replay is exact. A reply is one JSON object `{"tool_calls": [{"tool", "args"}], "reply":
{"status", "text", "facts"?}}` (prose around it is recovered with `parse_json_recovering`).
Up to `MAX_TOOL_CALLS` tool calls run in order; the first refused call ends the turn, and the
calls after it **and that turn's reply** are not acted on (the agent sees the refusal in the
next turn). A reply that is no such object is a turn with no action that still uses its call
(builder note 18). A reply ends the trial; a trial that ends without one fails. A
`CachedFailure` (an input rejection, stored: Phase 3 P21) ends the trial as failed; every
other model failure, and a budget stop, propagates.

**Rounds** (`run_rounds`, P28): every task in every arm at trial 0, then trial 1, and so on;
a round's rows are written only when the round is complete, so a budget stop or a model
failure leaves complete rounds for every arm (the stopped round's trial directories are
removed; a rerun replays the cached calls). `canary` runs trial 0 of the first task in each
arm and stops. The run refuses up front, before any call or file: an unknown arm, the
`gate-runtime` arm until Task 21 wires the procedure runtime (`RUNTIME_NOT_WIRED`; it is never
run as `gate`), a store with no bindings (`NO_BINDINGS`) and tasks drawn from other bindings
than `bindings/HEAD`. **The ACL is kept fresh** with `probes.tables.keep_fresh` before every
trial (so at least every round, N28): it re-syncs the store's ACL only when it is within 15
minutes of the freshness limit, so a long run is never denied F3 midway. That check, and the
timestamp in the run directory's name (`adr-eval sim drawbridge`, P38), are the run's only
clock inputs; nothing in the run directory depends on the clock.

**Outputs** (local, under the run directory `runs/sim-<arms>-<ts>/`, P30): `config.json`,
`tasks.jsonl` (a copy, for `adr-eval sim score`), `rows.jsonl` (one row per trial: the
trial without its transcript and log), and `trials/<arm>/<task>/t<k>/` (`env.jsonl`, the
gate's log, `transcript.json`). `summary.json` holds totals only (`score.public`): no task id,
transcript or text.

**The environment** of a trial is its own process by default (`ProcessEnv`: `python -m
adr_eval.sim.env`, JSON lines); `LocalEnv` runs the same `Env` in-process (tests).
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from string import Template
from typing import Any

from adr_eval.llm import CachedFailure, ModelError, ModelOutputError, parse_json_recovering
from adr_eval.pipeline import BudgetExceeded
from adr_eval.sim import env as env_mod
from adr_eval.sim import monitor, score, user
from adr_eval.sim.tasks import SimError, SimTask, canonical, reference_draws
from adr_store import acl

__all__ = ["AGENT_PROMPT_VERSION", "ARMS", "K", "MAX_CALLS", "MAX_TOKENS", "MAX_TOOL_CALLS",
           "OUT_ROOT", "PROMPT_SECTIONS", "RUNTIME_NOT_WIRED", "SUMMARY_FORMAT", "LocalEnv",
           "ProcessEnv", "check_bindings", "local_env_factory", "parse_turn",
           "process_env_factory", "render_transcript", "run_rounds", "run_trial",
           "system_prompt", "tool_list"]

AGENT_PROMPT_VERSION = "desk-agent@1"
MAX_TOKENS = 1500
MAX_CALLS = 3
MAX_TOOL_CALLS = 3
K = 4
ARMS = env_mod.ARMS
PROMPT_SECTIONS = ("33 CFR 117.5", "33 CFR 117.31", "33 CFR 117.40")
SUMMARY_FORMAT = "sim-summary@1"
OUT_ROOT = Path("runs")      # where `adr-eval sim drawbridge` writes by default (tests redirect)
RUNTIME_WIRED = False        # Task 21 wires the procedure runtime into the environment
RUNTIME_NOT_WIRED = ("the gate-runtime arm needs the procedure runtime in the environment: "
                     "runtime not wired (Task 21)")
STATUSES = monitor.STATUSES
TURN = "== Turn {n}: your reply =="
DONE = "== Turn {n}: what happened =="
REQUEST = "== The request =="
TOOL_HELP = {
    "get_request": "the request record: the request, every fact known so far with its source, "
                   "and the registry of approved local emergency procedures",
    "ask_user": "ask the user for one fact (for example when notice was given, the vessel "
                "class, or whether another time is acceptable); the desk writes the answer to "
                "the request record",
    "rule_lookup": "search the regulations, or fetch a rule by its id",
    "define": "the definition of a term in the regulations",
    "check_rules": "the rules' decision on an intended call, intent = {\"tool\": ..., \"args\": "
                   "{...}}, on the facts you give; it executes nothing",
    "procedure_lookup": "search the procedures, or fetch one by its id",
    "query_table": "query a drawbridge table",
    "schedule_opening": "schedule an opening of a bridge's draw at a time",
    "deny_request": "deny the request, citing the rule that decides it",
    "escalate_request": "escalate the request, naming the facts that are missing",
    "cancel_opening": "cancel a scheduled opening",
}
_KINDS = {"str": "string", "int": "integer", "bool": "boolean", "object": "object",
          "strs": "string[]", "time": "YYYY-MM-DDTHH:MM:SS"}


# -- the prompt -------------------------------------------------------------------------------

@functools.cache
def _template() -> Template:
    return Template(resources.files("adr_eval.sim").joinpath("prompts/agent.txt").read_text(
        encoding="utf-8"))


def tool_list() -> str:
    """The tools of every arm (`env.TOOLS`, arguments from `env.ARG_SCHEMAS`), one per line."""
    lines = []
    for tool in env_mod.TOOLS:
        schema = env_mod.ARG_SCHEMAS[tool]
        args = [f"{k}: {_KINDS[v]}" for k, v in schema["required"].items()] + \
            [f"{k}?: {_KINDS[v]}" for k, v in schema["optional"].items()]
        kind = "read" if tool in env_mod.READS else "changes the desk's records"
        lines.append(f"- {tool}({', '.join(args)}): {TOOL_HELP[tool]} ({kind})")
    return "\n".join(lines)


@functools.lru_cache(maxsize=16)
def _section_texts(store_path: str, bindings_id: str, sections: tuple[str, ...]
                   ) -> tuple[str, ...]:
    from adr_store.bindings.enrich import section_unit
    from adr_store.store import Store

    doc = reference_draws(Path(store_path), bindings_id)[2]
    if doc is None:
        raise SimError(f"bindings {bindings_id[:12]} have no agreement draw: no 33 CFR 117 "
                       f"version to quote")
    store = Store.open(Path(store_path))
    return tuple(section_unit(store, doc, s).text for s in sections)


def _store_path(store) -> Path:
    return Path(getattr(store, "path", store))


def rule_text(task: SimTask, store) -> str:
    """The block arm `prompt` adds: the verbatim text of `PROMPT_SECTIONS` and of the request's
    section, in that order, from the 33 CFR 117 version of the task's bindings."""
    sections = tuple(dict.fromkeys([s.removeprefix("33 CFR ") for s in PROMPT_SECTIONS]
                                   + [task.request["section"]]))
    texts = _section_texts(str(_store_path(store)), task.reference["bindings_id"], sections)
    return ("RULE TEXT\n\nThe text of the regulations that decide this request, quoted "
            "verbatim:\n\n" + "\n\n".join(t.strip("\n") for t in texts) + "\n\n")


def system_prompt(arm: str, task: SimTask, store) -> str:
    """The system prompt of `arm` for `task` (module text); `store` is a `Store` or its path."""
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}; arms are {', '.join(ARMS)}")
    return _template().substitute(
        desk_policy=env_mod.load_desk_policy().strip("\n"), tools=tool_list(),
        rule_text=rule_text(task, store) if arm == "prompt" else "")


# -- one turn ---------------------------------------------------------------------------------

def _readable_reply(reply: Any) -> bool:
    return (isinstance(reply, dict) and isinstance(reply.get("status"), str)
            and isinstance(reply.get("text", ""), str)
            and isinstance(reply.get("facts", {}), dict))


def parse_turn(text: str) -> dict:
    """{"readable", "json_recovered", "tool_calls", "reply"} of one agent reply: an object with
    an optional `tool_calls` list and an optional `reply` {status, text, facts?}; anything else
    is unreadable (no tool call, no reply)."""
    none = {"readable": False, "json_recovered": False, "tool_calls": [], "reply": None}
    obj = None
    for required in (("tool_calls",), ("reply",)):
        try:
            obj, recovered = parse_json_recovering(text, required)
            break
        except ModelOutputError:
            continue
    if obj is None:
        return none
    calls, reply = obj.get("tool_calls", []), obj.get("reply")
    if calls is None:
        calls = []
    if not isinstance(calls, list) or (reply is not None and not _readable_reply(reply)):
        return none
    if reply is not None:
        reply = {"status": reply["status"], "text": reply.get("text", ""),
                 **({"facts": reply["facts"]} if "facts" in reply else {})}
    return {"readable": True, "json_recovered": recovered, "tool_calls": calls, "reply": reply}


def _dumps(v: Any) -> str:
    return json.dumps(v, sort_keys=True, ensure_ascii=False, default=str)


def render_transcript(first_message: str, turns: list[dict]) -> str:
    """The user message of the next agent call: the request, then each turn's reply and what
    came of it, then the header of the turn to answer."""
    parts = [REQUEST, first_message]
    for n, t in enumerate(turns, 1):
        parts += [TURN.format(n=n), t["text"], DONE.format(n=n)]
        if t.get("failed"):
            parts.append(f"The call failed: {t['failed']}.")
            continue
        if not t["readable"]:
            parts.append("Your reply is not the JSON object the format asks for: nothing was "
                         "done.")
            continue
        for i, c in enumerate(t["calls"], 1):
            ok = c["out"].get("ok") is True
            body = c["out"].get("result") if ok else c["out"].get("refusal")
            parts.append(f"Tool call {i}: {_dumps(c['tool'])} {_dumps(c['args'])}\n"
                         f"{'Result' if ok else 'Refused'}: {_dumps(body)}")
        if t["refused_at"] is not None:
            parts.append(f"Tool call {t['refused_at'] + 1} was refused: the "
                         f"{t['dropped']} call(s) after it"
                         + (" and the reply" if t["reply_dropped"] else "")
                         + " were not acted on.")
        elif t["dropped"]:
            parts.append(f"Only three tool calls of a turn run: {t['dropped']} more were not "
                         f"acted on.")
        if not t["calls"] and t["reply"] is None and not t["reply_dropped"]:
            parts.append("No tool call and no reply: nothing was done.")
    parts.append(TURN.format(n=len(turns) + 1))
    return "\n\n".join(parts)


# -- the environment of a trial ------------------------------------------------------------

def _plain(v: Any) -> Any:
    return json.loads(json.dumps(v, default=str))


def _refuse_unwired(arm: str) -> None:
    if arm == "gate-runtime" and not RUNTIME_WIRED:
        raise SimError(RUNTIME_NOT_WIRED)


class LocalEnv:
    """`env.Env` in this process, with the process's interface (results as plain JSON)."""

    def __init__(self, store_path: Path, task: SimTask, arm: str, log_dir: Path):
        self.store_path = Path(store_path)
        self._env = env_mod.Env(self.store_path, task, arm, log_dir)
        self.first_message = user.first_message(task)
        self._end: dict | None = None
        self._closed = False

    def call(self, tool: Any, args: Any) -> dict:
        return _plain(self._env.call(tool, args))

    def close(self) -> dict:
        if not self._closed:
            self._closed = True
            self._end = _plain(self._env.world.end_state())
            self._env.close()
        return self._end

    def log_lines(self) -> list[dict]:
        return self._env.log_lines()


class ProcessEnv:
    """The environment process of one trial (`python -m adr_eval.sim.env`, JSON lines)."""

    def __init__(self, store_path: Path, task: SimTask, arm: str, log_dir: Path):
        self.store_path = Path(store_path)
        self.log_path = Path(log_dir) / "env.jsonl"
        self._end: dict | None = None
        self._closed = False
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "adr_eval.sim.env", "--store", str(self.store_path),
             "--log", str(log_dir)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, encoding="utf-8",
            env={**os.environ, "HF_HUB_OFFLINE": "1", "PYTHONIOENCODING": "utf-8"})
        try:
            first = self._ask({"task": task.model_dump(by_alias=True, mode="json"),
                               "arm": arm})
        except BaseException:
            self._kill()
            raise
        if not first.get("ready"):
            self._kill()
            raise SimError(f"the environment did not start: {first.get('error')}")
        self.first_message = first["first_message"]

    def _ask(self, msg: dict) -> dict:
        self._proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            raise SimError(f"the environment process ended (exit {self._proc.poll()})")
        return json.loads(line)

    def _kill(self) -> None:
        if self._proc.poll() is None:
            self._proc.kill()
        self._proc.wait()
        for f in (self._proc.stdin, self._proc.stdout):
            f.close()

    def call(self, tool: Any, args: Any) -> dict:
        return self._ask({"tool": tool, "args": args})

    def close(self) -> dict:
        if not self._closed:
            self._closed = True
            try:
                self._end = self._ask({"end": True})["end_state"]
                self._proc.stdin.close()
                self._proc.wait(timeout=120)
            finally:
                self._kill()
        return self._end

    def log_lines(self) -> list[dict]:
        return [json.loads(x) for x in self.log_path.read_bytes().splitlines()]


def _trial_dir(root: Path, task_id: str, arm: str, trial: int) -> Path:
    return Path(root) / arm / task_id / f"t{trial}"


def local_env_factory(store_path: Path, root: Path) -> Callable:
    """`(task, arm, trial) -> LocalEnv` logging to `root/<arm>/<task>/t<trial>`."""
    def make(task: SimTask, arm: str, trial: int) -> LocalEnv:
        _refuse_unwired(arm)
        return LocalEnv(store_path, task, arm, _trial_dir(root, task.task_id, arm, trial))
    return make


def process_env_factory(store_path: Path, root: Path) -> Callable:
    """`(task, arm, trial) -> ProcessEnv` logging to `root/<arm>/<task>/t<trial>`."""
    def make(task: SimTask, arm: str, trial: int) -> ProcessEnv:
        _refuse_unwired(arm)
        return ProcessEnv(store_path, task, arm, _trial_dir(root, task.task_id, arm, trial))
    return make


# -- one trial ------------------------------------------------------------------------------

def _gate_stats(log: list[dict]) -> tuple[dict, dict]:
    """(gate decisions by class, {"denies", "recovered"}): after a gate deny, the agent
    recovered when its next attempted side effect is a deny, an escalation, or a schedule at
    the deny's `next_allowed`."""
    outcomes = dict.fromkeys(score.GATE_CLASSES, 0)
    calls = [x for x in log if x.get("kind") == "call"]
    denies = recovered = 0
    for i, x in enumerate(calls):
        g = x.get("gate")
        if not g or g.get("decision") not in outcomes:
            continue
        outcomes[g["decision"]] += 1
        if g["decision"] != "deny":
            continue
        denies += 1
        nxt = next((y for y in calls[i + 1:] if y.get("tool") in env_mod.GATED), None)
        if nxt is None:
            continue
        at = (x.get("refusal") or {}).get("next_allowed")
        if nxt["tool"] in ("deny_request", "escalate_request") or (
                nxt["tool"] == "schedule_opening" and isinstance(nxt.get("args"), dict)
                and at is not None and nxt["args"].get("open_at") == at):
            recovered += 1
    return outcomes, {"denies": denies, "recovered": recovered}


def run_trial(task: SimTask, arm: str, trial: int, client, env_factory: Callable) -> dict:
    """One trial of `task` in `arm` (module text): {task_id, arm, trial, calls, tokens,
    transcript, reply, end_state, gate_outcomes, recovered} with `violations` (the trace
    monitor's V1-V4), `failed` ("input_rejected" or None), `made` and `cached` (calls that
    reached the model and cache hits), `served_models` and `log` (the environment's log)."""
    env = env_factory(task, arm, trial)
    turns: list[dict] = []
    reply = None
    calls = tokens = made = 0
    failed = None
    served: set[str] = set()
    try:
        system = system_prompt(arm, task, env.store_path)
        for _ in range(MAX_CALLS):
            text = render_transcript(env.first_message, turns)
            calls += 1
            try:
                c = client.complete(system, text, max_tokens=MAX_TOKENS, repeat=trial,
                                    cache_failures=True)
            except CachedFailure as e:          # an input rejection, stored (Phase 3 P21)
                failed = "input_rejected"
                turns.append({"text": "", "readable": False, "failed": str(e)})
                break
            tokens += c.input_tokens + c.output_tokens
            made += not c.cached
            if c.served_model is not None:
                served.add(c.served_model)
            p = parse_turn(c.text)
            turn = {"text": c.text, "readable": p["readable"],
                    "json_recovered": p["json_recovered"], "calls": [], "refused_at": None,
                    "dropped": 0, "reply": None, "reply_dropped": False}
            for i, call in enumerate(p["tool_calls"][:MAX_TOOL_CALLS]):
                tool, args = (call.get("tool"), call.get("args")) if isinstance(call, dict) \
                    else (None, None)
                out = env.call(tool, args)
                turn["calls"].append({"tool": tool, "args": args, "out": out})
                if out.get("ok") is not True:
                    turn["refused_at"] = i
                    break
            turn["dropped"] = len(p["tool_calls"]) - len(turn["calls"])
            if p["reply"] is not None:
                if turn["refused_at"] is None:
                    turn["reply"] = reply = p["reply"]
                else:
                    turn["reply_dropped"] = True
            turns.append(turn)
            if reply is not None:
                break
        end_state = env.close()
        log = env.log_lines()
    finally:
        env.close()
    gate_outcomes, recovered = _gate_stats(log)
    return {"task_id": task.task_id, "arm": arm, "trial": trial, "calls": calls,
            "tokens": tokens, "made": made, "cached": calls - made - (failed is not None),
            "transcript": {"agent_prompt": AGENT_PROMPT_VERSION,
                           "system_sha256": hashlib.sha256(system.encode()).hexdigest(),
                           "first_message": env.first_message, "turns": turns},
            "reply": reply, "end_state": end_state, "gate_outcomes": gate_outcomes,
            "recovered": recovered, "violations": monitor.violations(task, log, reply),
            "failed": failed, "served_models": sorted(served), "log": log}


# -- rounds ---------------------------------------------------------------------------------

def check_bindings(tasks: list[SimTask], store_path: Path) -> str:
    """`bindings/HEAD` of the store, which every task must have been drawn from; SimError
    (`NO_BINDINGS`, or the tasks of other bindings) otherwise."""
    from adr_store.bindings import manifest
    from adr_store.store import Store
    from adr_store.tools import NO_BINDINGS

    head = manifest.read_bindings_head(store_path)
    if head is None:
        snapshot = Store.open(store_path).snapshot_id
        raise SimError(f"NO_BINDINGS: {NO_BINDINGS.format(snapshot[:12])}")
    other = sorted(t.task_id for t in tasks if t.reference.get("bindings_id") != head)
    if other:
        raise SimError(f"{len(other)} task(s) ({', '.join(other[:3])}"
                       f"{', ...' if len(other) > 3 else ''}) were drawn from other bindings "
                       f"than bindings/HEAD {head[:12]}: regenerate the tasks or restore the "
                       f"head; nothing was run")
    return head


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _row(trial: dict) -> dict:
    return {k: v for k, v in trial.items() if k not in ("transcript", "log")}


def run_rounds(tasks: list[SimTask], arms: tuple[str, ...], client, out_dir: Path, *, store,
               trials: int = K, canary: bool = False, env_factory: Callable | None = None,
               directory: Path = acl.DIRECTORY_PATH, policy: Path = acl.POLICY_PATH,
               clock: Callable = acl.utc_now) -> dict:
    """Run `tasks` in `arms` in rounds by trial index into the run directory `out_dir`
    (module text); `store` is the store (or its path) the tasks were drawn from. The store's
    ACL is kept fresh before every trial, so at least every round (`probes.tables.keep_fresh`
    with `directory`, `policy` and `clock`; N28). Returns {"order", "rows", "rounds",
    "status" ("complete", "canary" or "stopped"), "stop", "calls", "served_models",
    "summary"}; the env factory defaults to one environment process per trial."""
    from adr_eval.probes import tables as tp

    arms = tuple(arms)
    unknown = [a for a in arms if a not in ARMS]
    if unknown or not arms or len(set(arms)) != len(arms):
        raise ValueError(f"unknown arm(s) {', '.join(unknown) or '(none or repeated)'}; arms "
                         f"are {', '.join(ARMS)}")
    for arm in arms:
        _refuse_unwired(arm)
    if trials < 1 or not tasks:
        raise ValueError("a run needs at least one task and one trial")
    store_path = _store_path(store)
    bindings_id = check_bindings(tasks, store_path)
    if canary:
        tasks, trials = tasks[:1], 1
    out_dir = Path(out_dir)
    if (out_dir / "rows.jsonl").exists():
        raise ValueError(f"{out_dir} holds a run: every run writes a new directory")
    out_dir.mkdir(parents=True, exist_ok=True)
    root = out_dir / "trials"
    make_env = env_factory or process_env_factory(store_path, root)
    model = getattr(client, "model", None)
    _write_json(out_dir / "config.json", {
        "arms": list(arms), "trials": trials, "canary": canary, "store": str(store_path),
        "bindings_id": bindings_id, "agent_prompt": AGENT_PROMPT_VERSION, "model": model,
        "max_tokens": MAX_TOKENS, "max_calls_per_trial": MAX_CALLS,
        "max_tool_calls_per_turn": MAX_TOOL_CALLS,
        "tasks_sha256": hashlib.sha256(b"".join(canonical(t) for t in tasks)).hexdigest()})
    (out_dir / "tasks.jsonl").write_bytes(b"".join(canonical(t) for t in tasks))
    (out_dir / "rows.jsonl").write_bytes(b"")
    order: list[tuple[str, str, int]] = []
    rows: list[dict] = []
    stop: dict | None = None
    complete = 0
    for k in range(trials):
        done: list[dict] = []
        try:
            for task in tasks:
                for arm in arms:
                    tp.keep_fresh(store_path, directory, policy, clock)
                    order.append((task.task_id, arm, k))
                    done.append(run_trial(task, arm, k, client, make_env))
        except (BudgetExceeded, ModelError) as e:     # CachedFailure never reaches here
            budget = getattr(client, "budget", None)
            stop = {"reason": (budget.stop_reason if isinstance(e, BudgetExceeded) and budget
                               else "error"), "error": type(e).__name__, "message": str(e),
                    "round": k}
            for d in root.glob(f"*/*/t{k}"):
                shutil.rmtree(d, ignore_errors=True)
            break
        for t in done:
            d = _trial_dir(root, t["task_id"], t["arm"], k)
            d.mkdir(parents=True, exist_ok=True)
            _write_json(d / "transcript.json", t["transcript"])
        with open(out_dir / "rows.jsonl", "a", encoding="utf-8") as f:
            for t in done:
                f.write(json.dumps(_row(t), sort_keys=True, ensure_ascii=False) + "\n")
        rows += [_row(t) for t in done]
        complete = k + 1
    status = "stopped" if stop else "canary" if canary else "complete"
    calls = {"made": sum(r["made"] for r in rows), "cached": sum(r["cached"] for r in rows),
             "input_rejected": sum(r["failed"] is not None for r in rows)}
    served = sorted({m for r in rows for m in r["served_models"]})
    summary = score.summarize(rows, tasks)
    _write_json(out_dir / "summary.json", {
        "format": SUMMARY_FORMAT, "status": status,
        "stop": None if stop is None else {k: v for k, v in stop.items() if k != "message"},
        "arms": list(arms), "trials": trials, "rounds_complete": complete, "tasks": len(tasks),
        "bindings_id": bindings_id, "agent_prompt": AGENT_PROMPT_VERSION, "model": model,
        "served_models": served, "calls": calls, "summary": score.public(summary),
        "criteria": score.criteria(summary)})
    return {"order": order, "rows": rows, "rounds": complete, "status": status, "stop": stop,
            "calls": calls, "served_models": served, "summary": summary, "out_dir": out_dir}
