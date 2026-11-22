"""The agent loop, the arms and the rounds (Phase 4 Task 20; spec §13.2, §13.3, §13.5, §13.6;
P18, P28, P30, P35, P38; preflight N9, N28, C2, C17). A stub agent only: no model call."""

from __future__ import annotations

import difflib
import json
import re

import pytest

from adr_eval.llm import Completion, InputRejected, RetriesExhausted
from adr_eval.sim import agent
from adr_eval.sim.agent import (
    ARMS,
    MAX_CALLS,
    MAX_TOOL_CALLS,
    PROMPT_SECTIONS,
    local_env_factory,
    run_rounds,
    run_trial,
    system_prompt,
)
from adr_eval.sim.env import TOOLS, load_desk_policy
from adr_eval.sim.score import success
from adr_eval.sim.tasks import SimError
from tests.sim_fixtures import (  # noqa: F401 - fixtures
    oracle_action,
    oracle_reply,
    oracle_script,
    sim_acl,
    sim_store,
    sim_tasks,
    stub_agent,
)


@pytest.fixture(scope="module")
def tasks(sim_store):  # noqa: F811
    return sim_tasks(sim_store)


def _of(tasks, cls: str, i: int = 0):
    return [t for t in tasks if t.class_ == cls][i]


def _rounds(sim_store, tasks, arms, client, out, **kw):  # noqa: F811
    kw.setdefault("env_factory", local_env_factory(sim_store.path, out / "trials"))
    return run_rounds(tasks, arms, client, out, store=sim_store.path, **sim_acl(sim_store),
                      **kw)


def _trial(sim_store, task, arm, client, tmp_path, trial=0):  # noqa: F811
    return run_trial(task, arm, trial, client, local_env_factory(sim_store.path, tmp_path))


def _calls(log: list[dict]) -> list[dict]:
    return [x for x in log if x["kind"] == "call"]


def _open(task, at=None) -> dict:
    r = task.request
    return {"request": r["id"], "section": r["section"], "draw": r["draw"],
            "open_at": at or r["requested_open_at"]}


# -- rounds -----------------------------------------------------------------------------------


def test_a_stub_agent_runs_rounds_by_trial_index(sim_store, tasks, tmp_path):  # noqa: F811
    two = tasks[:2]
    out = _rounds(sim_store, two, ("no-gate", "gate"), stub_agent(tmp_path / "llm",
                                                                   oracle_script, tasks),
                  tmp_path / "run")
    order = out["order"]
    assert [t for _, _, t in order] == [0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3]
    assert order == [(t.task_id, arm, k) for k in range(4) for t in two
                     for arm in ("no-gate", "gate")]
    rows = [json.loads(x) for x in (tmp_path / "run" / "rows.jsonl").read_text().splitlines()]
    assert [(r["task_id"], r["arm"], r["trial"]) for r in rows] == order
    assert out["status"] == "complete" and out["rounds"] == 4
    assert all(success(r, t) for r in rows for t in two if t.task_id == r["task_id"])
    assert all(r["violations"] == {"V1": 0, "V2": 0, "V3": 0, "V4": 0} for r in rows)
    # every trial's logs and transcript are under the run directory (local, P30)
    for r in rows:
        d = tmp_path / "run" / "trials" / r["arm"] / r["task_id"] / f"t{r['trial']}"
        assert (d / "env.jsonl").is_file() and (d / "transcript.json").is_file()
        assert (d / "gate" / "gate.jsonl").is_file() == (r["arm"] == "gate")


def test_trial_index_is_in_the_cache_key_and_replay_is_exact(sim_store, tasks,  # noqa: F811
                                                            tmp_path):
    task = _of(tasks, "allow", 1)          # every fact in the record: one call per trial
    repeats: list[int] = []

    def script(t, turn, repeat, system, user):
        repeats.append(repeat)
        return {"tool_calls": [{"tool": "get_request", "args": {"id": "r1"}},
                               {"tool": "check_rules", "args": {"intent": {
                                   "tool": "schedule_opening", "args": _open(t)}}},
                               oracle_action(t)], "reply": oracle_reply(t)}

    client = stub_agent(tmp_path / "llm", script, tasks)
    first = _rounds(sim_store, [task], ("no-gate",), client, tmp_path / "a")
    assert client.calls == 4 and sorted(repeats) == [0, 1, 2, 3]   # 4 trials = 4 calls
    assert [r["calls"] for r in first["rows"]] == [1, 1, 1, 1]
    again = _rounds(sim_store, [task], ("no-gate",), client, tmp_path / "b")
    assert client.calls == 4 and again["calls"] == {"made": 0, "cached": 4, "input_rejected": 0}
    for k in range(4):
        rel = f"trials/no-gate/{task.task_id}/t{k}"
        for name in ("transcript.json", "env.jsonl"):
            assert (tmp_path / "a" / rel / name).read_bytes() == \
                (tmp_path / "b" / rel / name).read_bytes()
    def same(rows):          # the rows differ only in where the calls were answered from
        return [{k: v for k, v in r.items() if k not in ("made", "cached")} for r in rows]

    assert same(first["rows"]) == same(again["rows"])
    assert [(r["made"], r["cached"]) for r in again["rows"]] == [(0, 1)] * 4
    # the gate arm's logs are identical too, but for the gate's instance id
    g1 = _rounds(sim_store, [task], ("gate",), client, tmp_path / "g1", trials=1)
    g2 = _rounds(sim_store, [task], ("gate",), client, tmp_path / "g2", trials=1)
    logs = []
    for run in ("g1", "g2"):
        raw = (tmp_path / run / f"trials/gate/{task.task_id}/t0/env.jsonl").read_text()
        logs.append(re.sub(r'"instance":"[^"]+"', '"instance":"<i>"', raw))
    assert logs[0] == logs[1] and g1["rows"] == g2["rows"]
    # the gate arm's prompt equals no-gate's (§13.5), so its first call is the same entry
    assert client.calls == 4
    # two calls a trial: the second call's input renders the first turn's results, and a
    # replay renders them byte for byte (else it would miss the cache)
    asks = stub_agent(tmp_path / "llm2", oracle_script, tasks)
    t2 = _of(tasks, "allow", 0)
    _rounds(sim_store, [t2], ("no-gate",), asks, tmp_path / "c")
    assert asks.calls == 8
    replay = _rounds(sim_store, [t2], ("no-gate",), asks, tmp_path / "d")
    assert asks.calls == 8 and replay["calls"]["made"] == 0


def test_the_environment_process_gives_the_in_process_transcript(sim_store, tasks,  # noqa: F811
                                                               tmp_path):
    task = _of(tasks, "emergency")
    client = stub_agent(tmp_path / "llm", oracle_script, tasks)
    local = _rounds(sim_store, [task], ("gate",), client, tmp_path / "local", trials=1)
    proc = run_rounds([task], ("gate",), client, tmp_path / "proc", store=sim_store.path,
                      trials=1, **sim_acl(sim_store))          # the default: one process each
    assert client.calls == 2 and proc["calls"]["made"] == 0
    rel = f"trials/gate/{task.task_id}/t0/transcript.json"
    assert (tmp_path / "local" / rel).read_bytes() == (tmp_path / "proc" / rel).read_bytes()
    drop = ("made", "cached")
    assert [{k: v for k, v in r.items() if k not in drop} for r in local["rows"]] == \
        [{k: v for k, v in r.items() if k not in drop} for r in proc["rows"]]
    assert success(proc["rows"][0], task)
    log = (tmp_path / "proc" / f"trials/gate/{task.task_id}/t0/env.jsonl").read_text()
    assert '"kind":"end"' in log


# -- the loop ---------------------------------------------------------------------------------


def test_at_most_three_calls_and_a_trial_without_reply_fails(sim_store, tasks,  # noqa: F811
                                                            tmp_path):
    task = _of(tasks, "allow", 1)
    looks = stub_agent(tmp_path / "l1", lambda t, turn, r, s, u: {"tool_calls": [
        {"tool": "get_request", "args": {"id": "r1"}}]}, tasks)
    row = _trial(sim_store, task, "no-gate", looks, tmp_path / "t1")
    assert MAX_CALLS == 3 and row["calls"] == 3 and looks.calls == 3
    assert row["reply"] is None and len(row["transcript"]["turns"]) == 3
    # scheduling the expected opening without a reply still fails the trial (§13.3)
    acts = stub_agent(tmp_path / "l2", lambda t, turn, r, s, u: {"tool_calls": [
        oracle_action(t)] if turn == 0 else []}, tasks)
    row = _trial(sim_store, task, "no-gate", acts, tmp_path / "t2")
    assert row["end_state"] == task.expected_state and row["reply"] is None
    assert row["calls"] == 3 and not success(row, task)
    # an unreadable reply is a turn with no action, and it uses one of the three calls
    junk = stub_agent(tmp_path / "l3", lambda t, turn, r, s, u: "I would schedule it.", tasks)
    row = _trial(sim_store, task, "no-gate", junk, tmp_path / "t3")
    assert row["calls"] == 3 and junk.calls == 3 and row["reply"] is None
    assert [t["readable"] for t in row["transcript"]["turns"]] == [False] * 3
    log = json.loads(json.dumps(row["log"]))
    assert [x["kind"] for x in log] == ["start", "end"]
    # a malformed reply object (tool_calls not a list) is unreadable too
    bad = stub_agent(tmp_path / "l4", lambda t, turn, r, s, u: {
        "tool_calls": oracle_action(t), "reply": oracle_reply(t)}, tasks)
    row = _trial(sim_store, task, "no-gate", bad, tmp_path / "t4")
    assert row["reply"] is None and _calls(row["log"]) == []
    # prose around the object is recovered; at most three tool calls of a turn run
    many = stub_agent(tmp_path / "l5", lambda t, turn, r, s, u: "Here: " + json.dumps({
        "tool_calls": [{"tool": "get_request", "args": {"id": "r1"}}] * 4 + [
            oracle_action(t)], "reply": oracle_reply(t)}), tasks)
    row = _trial(sim_store, task, "no-gate", many, tmp_path / "t5")
    assert MAX_TOOL_CALLS == 3 and len(_calls(row["log"])) == 3
    assert row["transcript"]["turns"][0]["json_recovered"] is True
    assert row["transcript"]["turns"][0]["dropped"] == 2
    assert row["reply"] == oracle_reply(task) and row["end_state"]["openings"] == []


def test_execution_stops_at_the_first_refused_tool_call(sim_store, tasks, tmp_path):  # noqa: F811
    task = _of(tasks, "allow", 1)
    malformed = {**_open(task), "draw": str(task.request["draw"])}

    def script(t, turn, repeat, system, user):
        if turn == 0:   # a malformed call refuses: the next call and the reply are not run
            return {"tool_calls": [{"tool": "get_request", "args": {"id": "r1"}},
                                   {"tool": "schedule_opening", "args": malformed},
                                   oracle_action(t)], "reply": oracle_reply(t)}
        assert "refused" in user and "were not acted on" in user
        return {"tool_calls": [oracle_action(t)], "reply": oracle_reply(t)}

    row = _trial(sim_store, task, "no-gate", stub_agent(tmp_path / "l1", script, tasks),
                 tmp_path / "t1")
    calls = _calls(row["log"])
    assert [c["tool"] for c in calls] == ["get_request", "schedule_opening", "schedule_opening"]
    assert [c["ok"] for c in calls] == [True, False, True]
    first = row["transcript"]["turns"][0]
    assert first["refused_at"] == 1 and first["dropped"] == 1 and first["reply"] is None
    assert row["calls"] == 2 and success(row, task)
    # in the gate arm a gate deny refuses: the deny after it in the same turn does not run
    deny = _of(tasks, "deny-closed")
    both = stub_agent(tmp_path / "l2", lambda t, turn, r, s, u: {"tool_calls": [
        {"tool": "schedule_opening", "args": _open(t)}, oracle_action(t)]}, tasks)
    row = _trial(sim_store, deny, "gate", both, tmp_path / "t2")
    assert [c["tool"] for c in _calls(row["log"])] == ["schedule_opening"] * 3
    assert row["end_state"] == {"openings": [], "denials": [], "escalations": []}


def test_stopping_after_a_gate_refusal_fails_the_outcome(sim_store, tasks, tmp_path):  # noqa: F811
    task = _of(tasks, "deny-closed")
    sec = task.request["section"]

    def stops(t, turn, repeat, system, user):
        if turn == 0:
            return {"tool_calls": [{"tool": "schedule_opening", "args": _open(t)}],
                    "reply": {"status": "scheduled", "text": "Scheduled."}}
        return {"tool_calls": [], "reply": {"status": "denied",
                                            "text": f"Denied under 33 CFR {sec}."}}

    row = _trial(sim_store, task, "gate", stub_agent(tmp_path / "l1", stops, tasks),
                 tmp_path / "t1")
    assert row["gate_outcomes"] == {"allow": 0, "deny": 1, "escalate": 0}
    assert row["end_state"] == {"openings": [], "denials": [], "escalations": []}   # P35
    assert row["reply"]["status"] == "denied" and not success(row, task)
    assert row["violations"]["V4"] == 1 and row["recovered"] == {"denies": 1, "recovered": 0}
    # the agent that recovers with an explicit deny passes, and the recovery is counted
    def recovers(t, turn, repeat, system, user):
        if turn == 0:
            return stops(t, turn, repeat, system, user)
        return {"tool_calls": [oracle_action(t)], "reply": oracle_reply(t)}

    row = _trial(sim_store, task, "gate", stub_agent(tmp_path / "l2", recovers, tasks),
                 tmp_path / "t2")
    assert success(row, task) and row["violations"] == {"V1": 0, "V2": 0, "V3": 0, "V4": 0}
    assert row["gate_outcomes"] == {"allow": 1, "deny": 1, "escalate": 0}
    assert row["recovered"] == {"denies": 1, "recovered": 1}
    # a schedule at the deny's next_allowed recovers too; another time does not
    resched = _of(tasks, "reschedule")
    nxt = resched.expected_state["openings"][0]["open_at"]
    for at, ok in ((nxt, 1), (resched.request["requested_open_at"], 0)):
        def again(t, turn, repeat, system, user, at=at):
            return {"tool_calls": [{"tool": "schedule_opening", "args": _open(t)},
                                   ] if turn == 0 else [{"tool": "schedule_opening",
                                                         "args": _open(t, at)}],
                    **({"reply": oracle_reply(t)} if turn else {})}
        row = _trial(sim_store, resched, "gate", stub_agent(tmp_path / f"l-{ok}", again, tasks),
                     tmp_path / f"t-{ok}")
        # the other time is denied again in turns 1 and 2: three denies, none recovered
        assert row["recovered"] == ({"denies": 1, "recovered": 1} if ok else
                                    {"denies": 3, "recovered": 0})
        assert success(row, resched) is bool(ok)


def test_a_cached_input_rejection_fails_the_trial_and_other_failures_stop(
        sim_store, tasks, tmp_path):  # noqa: F811
    two = [_of(tasks, "allow", 1), _of(tasks, "allow", 2)]
    rejected = two[1]

    def script(t, turn, repeat, system, user):
        if t.task_id == rejected.task_id and repeat == 1:
            raise InputRejected("400: prompt is too long")
        return oracle_script(t, turn, repeat, system, user)

    client = stub_agent(tmp_path / "llm", script, tasks)
    out = _rounds(sim_store, two, ("no-gate",), client, tmp_path / "run", trials=2)
    assert out["status"] == "complete" and len(out["rows"]) == 4
    bad = [r for r in out["rows"] if r["failed"]]
    assert [(r["task_id"], r["trial"], r["failed"]) for r in bad] == [
        (rejected.task_id, 1, "input_rejected")]
    assert bad[0]["reply"] is None and not success(bad[0], rejected)
    # 4 calls: 3 made, 1 rejected; per row, made + cached + rejected = calls
    assert out["calls"] == {"made": 3, "cached": 0, "input_rejected": 1}
    assert all(r["made"] + r["cached"] + (r["failed"] is not None) == r["calls"]
               for r in out["rows"])
    # the stored rejection replays without a call (Phase 3 P21)
    n = client.calls
    again = _rounds(sim_store, two, ("no-gate",), client, tmp_path / "run2", trials=2)
    assert client.calls == n
    assert again["calls"] == {"made": 0, "cached": 3, "input_rejected": 1}

    def flaky(t, turn, repeat, system, user):
        if repeat == 1 and t.task_id == two[1].task_id:
            raise RetriesExhausted("giving up after 0 retries: overloaded")
        return oracle_script(t, turn, repeat, system, user)

    out = _rounds(sim_store, two, ("no-gate",), stub_agent(tmp_path / "llm2", flaky, tasks),
                  tmp_path / "run3", trials=3)
    assert out["status"] == "stopped" and out["rounds"] == 1
    assert [(r["task_id"], r["trial"]) for r in out["rows"]] == [(t.task_id, 0) for t in two]
    assert out["stop"]["error"] == "RetriesExhausted"
    # the stop's message stays out of summary.json (it may carry provider text)
    raw = (tmp_path / "run3" / "summary.json").read_text()
    assert "overloaded" not in raw and "giving up" not in raw
    assert json.loads(raw)["stop"] == {"reason": "error", "error": "RetriesExhausted",
                                       "round": 1}


def test_budget_stop_leaves_complete_rounds(sim_store, tasks, tmp_path):  # noqa: F811
    from adr_store.tables.extract import metered_client

    two = [_of(tasks, "allow", 0), _of(tasks, "allow", 1)]   # 2 calls + 1 call per round
    stub = stub_agent(tmp_path / "llm", oracle_script, tasks)
    out = _rounds(sim_store, two, ("no-gate",), metered_client(8, client=stub),
                  tmp_path / "run")
    assert out["status"] == "stopped" and out["stop"]["reason"] == "calls"
    assert out["rounds"] == 2 and stub.calls == 8      # round 2 stopped in its second trial
    rows = [json.loads(x) for x in (tmp_path / "run" / "rows.jsonl").read_text().splitlines()]
    assert sorted((r["task_id"], r["trial"]) for r in rows) == sorted(
        (t.task_id, k) for t in two for k in (0, 1))
    trial_dirs = sorted(p.name for p in (tmp_path / "run" / "trials").glob("*/*/t*"))
    assert trial_dirs == ["t0", "t0", "t1", "t1"]
    summary = json.loads((tmp_path / "run" / "summary.json").read_text())
    assert summary["status"] == "stopped" and summary["rounds_complete"] == 2
    assert summary["summary"]["arms"]["no-gate"]["pass^2"] == 1.0
    assert summary["summary"]["arms"]["no-gate"]["pass^4"] is None
    # only the complete rounds feed the summary
    assert len(out["rows"]) == 4 and summary["summary"]["arms"]["no-gate"]["trials"] == 4
    assert summary["calls"] == {"made": 6, "cached": 0, "input_rejected": 0}
    assert "exceed" not in (tmp_path / "run" / "summary.json").read_text()
    assert summary["stop"] == {"reason": "calls", "error": "BudgetExceeded", "round": 2}
    # a rerun resumes from the cache: the stopped round's first trial is not made again
    out = _rounds(sim_store, two, ("no-gate",), metered_client(4, client=stub),
                  tmp_path / "rerun")
    assert out["status"] == "complete" and out["rounds"] == 4 and stub.calls == 12
    assert out["calls"] == {"made": 4, "cached": 8, "input_rejected": 0}


def test_canary_runs_trial_0_of_the_first_task_in_each_arm(sim_store, tasks,  # noqa: F811
                                                          tmp_path):
    client = stub_agent(tmp_path / "llm", oracle_script, tasks)
    out = _rounds(sim_store, tasks[:3], ("no-gate", "prompt", "gate"), client,
                  tmp_path / "run", canary=True)
    assert out["order"] == [(tasks[0].task_id, arm, 0) for arm in ("no-gate", "prompt", "gate")]
    assert out["status"] == "canary" and len(out["rows"]) == 3
    summary = json.loads((tmp_path / "run" / "summary.json").read_text())
    assert summary["status"] == "canary" and summary["summary"]["arms"]["gate"]["tasks"] == 1


def test_run_rounds_refuses_gate_runtime_until_task_21(sim_store, tasks, tmp_path):  # noqa: F811
    client = stub_agent(tmp_path / "llm", oracle_script, tasks)
    for arms in (("gate-runtime",), ("no-gate", "gate-runtime")):
        with pytest.raises(SimError, match=re.escape("runtime not wired (Task 21)")):
            _rounds(sim_store, tasks[:1], arms, client, tmp_path / "run")
    assert client.calls == 0 and not (tmp_path / "run").exists()
    for make in (local_env_factory, agent.process_env_factory):
        with pytest.raises(SimError, match=re.escape("runtime not wired (Task 21)")):
            make(sim_store.path, tmp_path / "x")(tasks[0], "gate-runtime", 0)
    with pytest.raises(ValueError, match="unknown arm"):
        _rounds(sim_store, tasks[:1], ("gated",), client, tmp_path / "run")
    # the agent loop itself runs the arm, with the gate's prompt (§13.5), once an
    # environment for it is given (Task 21 wires the runtime into the environment)
    seen = []

    def runtime_env(task, arm, trial):
        from adr_eval.sim.agent import LocalEnv

        return LocalEnv(sim_store.path, task, arm, tmp_path / "rt")

    def script(t, turn, repeat, system, user):
        seen.append(system)
        return oracle_script(t, turn, repeat, system, user)

    row = run_trial(tasks[1], "gate-runtime", 0, stub_agent(tmp_path / "l2", script, tasks),
                    runtime_env)
    assert row["arm"] == "gate-runtime" and success(row, tasks[1])
    assert seen[0] == system_prompt("gate", tasks[1], sim_store.path)


def test_the_bindings_guard_refuses_the_whole_run_up_front(sim_store, tasks,  # noqa: F811
                                                         tmp_path, monkeypatch):
    client = stub_agent(tmp_path / "llm", oracle_script, tasks)
    other = tasks[1].model_copy(update={"reference": {**tasks[1].reference,
                                                      "bindings_id": "f" * 64}})
    with pytest.raises(SimError, match="bindings/HEAD"):
        _rounds(sim_store, [tasks[0], other], ("no-gate",), client, tmp_path / "run")
    assert client.calls == 0 and not (tmp_path / "run").exists()
    monkeypatch.setattr("adr_store.bindings.manifest.read_bindings_head", lambda path: None)
    with pytest.raises(SimError, match="NO_BINDINGS"):
        _rounds(sim_store, tasks[:1], ("no-gate",), client, tmp_path / "run")
    assert client.calls == 0 and not (tmp_path / "run").exists()


def test_the_acl_is_kept_fresh_before_every_trial(sim_store, tasks, tmp_path,  # noqa: F811
                                                  monkeypatch):
    from adr_eval.probes import tables as tp

    real, seen = tp.keep_fresh, []

    def spy(store_path, directory, policy, clock, *a, **kw):
        seen.append((store_path, directory, policy))
        return real(store_path, directory, policy, clock, *a, **kw)

    monkeypatch.setattr(tp, "keep_fresh", spy)
    acl = sim_acl(sim_store)
    _rounds(sim_store, tasks[:2], ("no-gate",), stub_agent(tmp_path / "llm", oracle_script,
                                                           tasks), tmp_path / "run", trials=2)
    assert seen == [(sim_store.path, acl["directory"], acl["policy"])] * 4
    assert "keep_fresh" in run_rounds.__doc__ and "every trial" in run_rounds.__doc__


# -- arms and prompts -------------------------------------------------------------------------


def test_prompt_arm_holds_the_section_texts_and_others_do_not(sim_store, tasks):  # noqa: F811
    from adr_eval.sim.tasks import reference_draws
    from adr_store.bindings.decide import cited_sections
    from adr_store.bindings.enrich import section_unit

    task = _of(tasks, "allow", 1)
    prompts = {arm: system_prompt(arm, task, sim_store.path) for arm in ARMS}
    _, _, doc = reference_draws(sim_store.path, task.reference["bindings_id"])
    sections = [s.removeprefix("33 CFR ") for s in PROMPT_SECTIONS] + [task.request["section"]]
    texts = [section_unit(sim_store, doc, s).text for s in sections]
    assert len(texts) == 4 and all(len(t) > 40 for t in texts)
    # no-gate, gate and gate-runtime prompts are one prompt (§13.5)
    assert prompts["no-gate"] == prompts["gate"] == prompts["gate-runtime"]
    for t in texts:
        assert t in prompts["prompt"] and t not in prompts["no-gate"]
    # the prompt arm only adds: by lines, every changed line is an added one
    diff = list(difflib.unified_diff(prompts["no-gate"].splitlines(),
                                     prompts["prompt"].splitlines(), lineterm="", n=0))[2:]
    assert diff and all(x.startswith(("@@", "+")) for x in diff)
    assert sum(x.startswith("@@") for x in diff) == 1                  # one hunk
    # by characters: one inserted block, holding the four texts verbatim, in order
    sm = difflib.SequenceMatcher(None, prompts["no-gate"], prompts["prompt"], autojunk=False)
    ops = [op for op in sm.get_opcodes() if op[0] != "equal"]
    assert [op[0] for op in ops] == ["insert"]
    _, i1, i2, j1, j2 = ops[0]
    block = prompts["prompt"][j1:j2]
    at = [block.index(t) for t in texts]
    assert at == sorted(at)
    rest = block
    for t in texts:
        rest = rest.replace(t, "")
    assert cited_sections(rest) == set() and len(rest) < 300      # framing only, no rule text
    # the desk policy is the same in every arm, verbatim, and names no section
    policy = load_desk_policy()
    assert all(policy.strip() in p for p in prompts.values())
    assert cited_sections(policy) == set() and cited_sections(prompts["no-gate"]) == set()
    # another task's bridge: the prompt arm holds that bridge's section instead
    other = _of(tasks, "allow", 0)
    assert other.request["section"] != task.request["section"]
    po = system_prompt("prompt", other, sim_store.path)
    assert section_unit(sim_store, doc, other.request["section"]).text in po
    assert texts[3] not in po and system_prompt("gate", other, sim_store.path) == \
        prompts["gate"]


def test_every_arm_has_check_rules(sim_store, tasks, tmp_path):  # noqa: F811
    task = _of(tasks, "allow", 1)
    for arm in ARMS:
        p = system_prompt(arm, task, sim_store.path)
        for tool in TOOLS:
            assert f"- {tool}(" in p, (arm, tool)
        assert "- check_rules(intent: object, facts?: object, as_of?: string)" in p
    for arm in ("no-gate", "prompt", "gate"):
        client = stub_agent(tmp_path / f"llm-{arm}", lambda t, turn, r, s, u: {
            "tool_calls": [{"tool": "check_rules", "args": {"intent": {
                "tool": "schedule_opening", "args": _open(t)}, "facts": {}}}],
            "reply": oracle_reply(t)}, tasks)
        row = _trial(sim_store, task, arm, client, tmp_path / arm)
        (call,) = _calls(row["log"])
        assert call["tool"] == "check_rules" and call["ok"], arm
        assert call["result"]["outcome"] in ("allow", "escalate"), arm    # decided, a read
        assert row["end_state"] == {"openings": [], "denials": [], "escalations": []}


def test_summary_holds_no_task_ids_or_text(sim_store, tasks, tmp_path):  # noqa: F811
    three = tasks[:3]
    out = _rounds(sim_store, three, ("no-gate", "gate"), stub_agent(tmp_path / "llm",
                                                                     oracle_script, tasks),
                  tmp_path / "run", trials=1)
    raw = (tmp_path / "run" / "summary.json").read_text(encoding="utf-8")
    summary = json.loads(raw)
    from adr_eval.sim.user import first_message

    for t in tasks:
        for secret in (t.task_id, t.request["vessel"], first_message(t),
                       t.request["requested_open_at"], oracle_reply(t)["text"]):
            assert secret not in raw
    assert "per_task" not in summary["summary"]
    strings: list[str] = []

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            strings.append(x)

    walk(summary)
    allowed = {"no-gate", "gate", "complete", agent.AGENT_PROMPT_VERSION, agent.SUMMARY_FORMAT,
               "stub-agent", tasks[0].reference["bindings_id"]}
    assert set(strings) <= allowed, set(strings) - allowed
    assert summary["served_models"] == [] and summary["tasks"] == 3
    assert summary["summary"]["arms"]["gate"]["outcome_success"] == 1.0
    # the rows and transcripts are local, beside it
    assert out["rows"][0]["task_id"] in (tmp_path / "run" / "rows.jsonl").read_text()


def test_served_models_are_recorded(sim_store, tasks, tmp_path):  # noqa: F811
    from dataclasses import replace

    from adr_eval.llm import CachedStubClient

    class Served(CachedStubClient):
        def _attempt(self, system, user, max_tokens, repeat) -> Completion:
            return replace(super()._attempt(system, user, max_tokens, repeat),
                           served_model="served-x")

    out = _rounds(sim_store, tasks[1:2], ("no-gate",), stub_agent(
        tmp_path / "llm", oracle_script, tasks, cls=Served), tmp_path / "run", trials=1)
    assert out["served_models"] == ["served-x"]
    assert json.loads((tmp_path / "run" / "summary.json").read_text())["served_models"] == \
        ["served-x"]
    # a model served only in a discarded round is recorded too (the meter's served models)
    from adr_store.tables.extract import metered_client

    meter = metered_client(1, client=stub_agent(tmp_path / "llm2", oracle_script, tasks,
                                                cls=Served))
    out = _rounds(sim_store, [_of(tasks, "allow", 0)], ("no-gate",), meter, tmp_path / "run2",
                  trials=1)
    assert out["status"] == "stopped" and out["rows"] == []
    assert out["served_models"] == ["served-x"]


# -- the command line ---------------------------------------------------------------------------


def _cli_args(sim_store, path, arms, *extra):  # noqa: F811
    acl = sim_acl(sim_store)
    return ["sim", "drawbridge", "--store", str(sim_store.path), "--tasks", str(path),
            "--arms", arms, "--max-calls", "10", "--directory", str(acl["directory"]),
            "--policy", str(acl["policy"]), *extra]


def test_cli_drawbridge_writes_its_outputs_and_fails_a_served_model_mismatch(
        sim_store, tasks, tmp_path, monkeypatch, capsys):  # noqa: F811
    import shutil
    from dataclasses import replace

    from adr_eval import cli, runner
    from adr_eval.llm import CachedStubClient
    from adr_eval.sim.tasks import write_tasks

    class Served(CachedStubClient):
        def _attempt(self, system, user, max_tokens, repeat) -> Completion:
            return replace(super()._attempt(system, user, max_tokens, repeat),
                           served_model="served-sonnet")

    from adr_eval.corpora import REPO_ROOT

    assert REPO_ROOT not in agent.OUT_ROOT.resolve().parents        # redirected (N9)
    monkeypatch.setattr(agent, "OUT_ROOT", tmp_path / "runs")
    cls = {"value": Served}
    monkeypatch.setattr(runner, "make_client", lambda name, profiles, cache, max_retries=5:
                        stub_agent(tmp_path / "llm", oracle_script, tasks,
                                   model=f"stub-{name}", cls=cls["value"]))
    path = tmp_path / "tasks.jsonl"
    write_tasks(tasks[1:3], path)
    code = cli.main(_cli_args(sim_store, path, "no-gate,gate", "--trials", "1"))
    out = capsys.readouterr().out
    assert code == 1          # the outputs are written, the run counts as failed
    assert "status: served model mismatch: served-sonnet != stub-claude_code_sonnet; " \
        "complete; 2 budget unit(s) of 10 used" in out
    (run,) = agent.OUT_ROOT.glob("sim-no-gate+gate-*")
    assert re.fullmatch(r"sim-no-gate\+gate-\d{8}T\d{6}", run.name)        # P38
    summary = json.loads((run / "summary.json").read_text())
    assert summary["served_models"] == ["served-sonnet"] and summary["status"] == "complete"
    assert len((run / "rows.jsonl").read_text().splitlines()) == 4
    # a stop in the first round keeps no row, and still reports the served model
    other_path = tmp_path / "ask.jsonl"
    write_tasks([_of(tasks, "allow", 0)], other_path)          # two calls a trial
    args = _cli_args(sim_store, other_path, "no-gate", "--trials", "1")
    args[args.index("--max-calls") + 1] = "1"
    assert cli.main(args) == 1
    out = capsys.readouterr().out
    assert "status: served model mismatch: served-sonnet != stub-claude_code_sonnet; " \
        "stopped at --max-calls 1 in round 0; 0 complete round(s) kept" in out
    # the prompt arm in a second run, with the profile's own model: exit 0
    cls["value"] = CachedStubClient
    assert cli.main(_cli_args(sim_store, path, "prompt", "--trials", "1")) == 0
    assert "status: complete; 2 budget unit(s) of 10 used" in capsys.readouterr().out
    (prompt_run,) = agent.OUT_ROOT.glob("sim-prompt-*")
    # `sim score` merges the runs: three arms, totals only
    assert cli.main(["sim", "score", str(run), str(prompt_run), "--out",
                     str(tmp_path / "score.json")]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == json.loads((tmp_path / "score.json").read_text())
    assert sorted(printed["summary"]["arms"]) == ["gate", "no-gate", "prompt"]
    assert printed["criteria"]["A1"]["pass"] is None             # pass^4 needs four trials
    assert tasks[1].task_id not in (tmp_path / "score.json").read_text()
    # the same trials twice, and runs of other tasks, are refused
    assert cli.main(["sim", "score", str(run), str(run)]) == 2
    assert "twice" in capsys.readouterr().err
    other = tmp_path / "other"
    shutil.copytree(prompt_run, other)
    write_tasks(tasks[3:5], other / "tasks.jsonl")
    assert cli.main(["sim", "score", str(run), str(other)]) == 2
    assert "other tasks" in capsys.readouterr().err
    assert cli.main(["sim", "score", str(tmp_path)]) == 2
    # runs under another model or other bindings do not merge (m6)
    for key, value in (("model", "stub-other"), ("bindings_id", "d" * 64)):
        moved = tmp_path / f"moved-{key}"
        shutil.copytree(prompt_run, moved)
        config = json.loads((moved / "config.json").read_text())
        (moved / "config.json").write_text(json.dumps({**config, key: value}))
        assert cli.main(["sim", "score", str(run), str(moved)]) == 2, key
        assert f"runs merge only under the same {key}" in capsys.readouterr().err


def test_cli_drawbridge_refuses_before_any_call(sim_store, tasks, tmp_path,  # noqa: F811
                                                monkeypatch, capsys):
    from adr_eval import cli, runner
    from adr_eval.sim.tasks import write_tasks

    def no_client(*a, **kw):
        raise AssertionError("no client is made before the run is checked")

    monkeypatch.setattr(runner, "make_client", no_client)
    monkeypatch.setattr(agent, "OUT_ROOT", tmp_path / "runs")
    path = tmp_path / "tasks.jsonl"
    write_tasks(tasks[:2], path)
    cases = [("gate-runtime", path, "runtime not wired (Task 21)"),
             ("no-gate,gate-runtime", path, "runtime not wired (Task 21)"),
             ("no-gate,gated", path, "--arms takes distinct arms"),
             ("no-gate,no-gate", path, "--arms takes distinct arms"),
             ("no-gate", tmp_path / "missing.jsonl", "no tasks file")]
    for arms, p, msg in cases:
        assert cli.main(_cli_args(sim_store, p, arms)) == 2, arms
        assert msg in capsys.readouterr().err, arms
    stale = tmp_path / "stale.jsonl"
    write_tasks([tasks[0].model_copy(update={"reference": {**tasks[0].reference,
                                                           "bindings_id": "e" * 64}})], stale)
    assert cli.main(_cli_args(sim_store, stale, "no-gate")) == 2
    assert "other bindings than bindings/HEAD" in capsys.readouterr().err
    monkeypatch.setattr("adr_store.bindings.manifest.read_bindings_head", lambda path: None)
    assert cli.main(_cli_args(sim_store, tmp_path / "missing.jsonl", "no-gate")) == 2
    err = capsys.readouterr().err
    assert "NO_BINDINGS" in err and "no bindings for snapshot" in err
    assert not (tmp_path / "runs").exists()


def test_null_facts_and_text_are_absent_and_the_turn_still_runs(sim_store, tasks,  # noqa: F811
                                                               tmp_path):
    from adr_eval.sim.agent import parse_turn

    call = {"tool": "get_request", "args": {"id": "r1"}}
    for reply, kept in (({"status": "scheduled", "text": None, "facts": None},
                         {"status": "scheduled"}),
                        ({"status": "denied", "text": 7}, {"status": "denied"}),
                        ({"status": "denied", "text": {"a": 1}, "facts": {"x": 1}},
                         {"status": "denied", "facts": {"x": 1}}),
                        ({"status": "escalated", "text": "t"},
                         {"status": "escalated", "text": "t"})):
        p = parse_turn(json.dumps({"tool_calls": [call], "reply": reply}))
        assert p["readable"] and p["tool_calls"] == [call] and p["reply"] == kept, reply
    for bad in ({"status": None, "text": "t"}, {"text": "t"}, {"status": "denied",
                                                              "facts": ["x"]}, "denied"):
        p = parse_turn(json.dumps({"tool_calls": [call], "reply": bad}))
        assert not p["readable"] and p["tool_calls"] == [] and p["reply"] is None, bad
    # in a trial: the tool call runs and the reply ends it
    task = _of(tasks, "allow", 1)
    client = stub_agent(tmp_path / "llm", lambda t, turn, r, s_, u: {
        "tool_calls": [oracle_action(t)],
        "reply": {"status": "scheduled", "text": None, "facts": None}}, tasks)
    row = _trial(sim_store, task, "no-gate", client, tmp_path / "t")
    assert row["calls"] == 1 and row["reply"] == {"status": "scheduled"}
    assert success(row, task) and row["violations"]["V4"] == 0


def test_the_arms_share_calls_until_the_first_gated_call(sim_store, tasks,  # noqa: F811
                                                         tmp_path):
    task = _of(tasks, "allow", 0)                # the notice is the user's: asked first

    def script(t, turn, repeat, system, user):
        if turn == 0:
            return {"tool_calls": [{"tool": "ask_user", "args": {"field": "notice_received_at"}},
                                   {"tool": "get_request", "args": {"id": "r1"}}]}
        if turn == 1:
            return {"tool_calls": [oracle_action(t)]}
        return {"tool_calls": [], "reply": oracle_reply(t)}

    client = stub_agent(tmp_path / "llm", script, tasks)
    _rounds(sim_store, [task], ("no-gate",), client, tmp_path / "ng", trials=1)
    assert client.calls == 3
    # gate: turns 1 and 2 have the same input (reads only so far); turn 3 renders the gate's
    # decision on the schedule, so it is the first call of its own (P50)
    out = _rounds(sim_store, [task], ("gate",), client, tmp_path / "g", trials=1)
    assert client.calls == 4 and out["rows"][0]["made"] == 1
    assert success(out["rows"][0], task)
    assert "part at the first *gated* call" in agent.__doc__


def test_any_other_failure_keeps_the_complete_rounds_and_is_raised(sim_store, tasks,  # noqa: F811
                                                                  tmp_path):
    two = [_of(tasks, "allow", 1), _of(tasks, "allow", 2)]
    inner = local_env_factory(sim_store.path, tmp_path / "run" / "trials")

    def factory(task, arm, trial):
        if trial == 1 and task.task_id == two[1].task_id:
            raise SimError("the environment did not start: boom")
        return inner(task, arm, trial)

    with pytest.raises(SimError, match="boom"):
        _rounds(sim_store, two, ("no-gate",), stub_agent(tmp_path / "llm", oracle_script,
                                                         tasks), tmp_path / "run",
                env_factory=factory)
    summary = json.loads((tmp_path / "run" / "summary.json").read_text())
    assert summary["status"] == "failed: SimError" and summary["rounds_complete"] == 1
    assert summary["stop"] == {"reason": "failed", "error": "SimError", "round": 1}
    assert summary["summary"]["arms"]["no-gate"]["trials"] == 2
    assert "boom" not in json.dumps(summary)
    assert sorted(p.name for p in (tmp_path / "run" / "trials").glob("*/*/t*")) == ["t0", "t0"]
    assert len((tmp_path / "run" / "rows.jsonl").read_text().splitlines()) == 2


def test_cli_reports_a_failed_run(sim_store, tasks, tmp_path, monkeypatch,  # noqa: F811
                                  capsys):
    from adr_eval import cli, runner
    from adr_eval.sim.tasks import write_tasks

    monkeypatch.setattr(agent, "OUT_ROOT", tmp_path / "runs")
    monkeypatch.setattr(runner, "make_client", lambda name, profiles, cache, max_retries=5:
                        stub_agent(tmp_path / "llm", oracle_script, tasks,
                                   model=f"stub-{name}"))

    def broken(store_path, root):
        def make(task, arm, trial):
            raise SimError("the environment did not start: boom")
        return make

    monkeypatch.setattr(agent, "process_env_factory", broken)
    path = tmp_path / "tasks.jsonl"
    write_tasks(tasks[1:2], path)
    assert cli.main(_cli_args(sim_store, path, "no-gate", "--trials", "1")) == 1
    out = capsys.readouterr().out
    assert "status: failed: SimError: the environment did not start: boom; 0 complete " \
        "round(s) kept" in out
    (run,) = (tmp_path / "runs").glob("sim-no-gate-*")
    assert json.loads((run / "summary.json").read_text())["status"] == "failed: SimError"
