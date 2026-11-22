"""The procedure runtime, `desk-request@1` and the per-profile flag (Phase 4 Task 21; spec §5.3,
§9.3, §13.2-§13.5, §17 A4; P17, P35, P50, P51; builder note 19; preflight N9, N13, C2). A stub
agent only: no model call. Every test that writes `config/runtime.json` writes a temporary copy
(N9); the conftest points the default there as well."""

from __future__ import annotations

import hashlib
import json

import pytest

from adr_eval.corpora import REPO_ROOT
from adr_eval.sim import agent
from adr_eval.sim import runtime as rt_mod
from adr_eval.sim.agent import local_env_factory, run_rounds, run_trial
from adr_eval.sim.env import Env
from adr_eval.sim.runtime import (
    DISCIPLINE_MARGIN,
    READ_ONLY,
    REFUSED,
    Runtime,
    as_unit,
    discipline_check,
    load_desk_procedure,
    result_facts,
    runtime_enabled,
    write_runtime_entry,
)
from adr_eval.sim.score import success
from adr_eval.sim.tasks import registry_fact
from adr_store.bindings.dsl import check_expr
from adr_store.units.procedures import Edge, ProcedureBody, Step, branch_paths, validate_ir
from adr_store.units.render import (
    ir_graph,
    parse_mermaid,
    parse_skill,
    render_mermaid,
    render_skill,
)
from tests.sim_fixtures import (  # noqa: F401 - fixtures
    env,
    oracle_script,
    sim_acl,
    sim_store,
    sim_tasks,
    stub_agent,
)

ARGS = {"request": "r1", "section": "117.1081", "draw": 1, "open_at": "2026-08-14T09:30:00"}
SIDE_EFFECTS = ("schedule_opening", "deny_request", "escalate_request", "cancel_opening")
REAL_CONFIG = REPO_ROOT / "config" / "runtime.json"
SONNET = "claude_code_sonnet"
TABLE = [  # Task 21's table: (id, type, tool, [(to, guard)])
    ("s1", "tool_call", "get_request", [("s2", None)]),
    ("s2", "tool_call", "check_rules", [("s3", None)]),
    ("s3", "condition", None, [("s4", {"eq": ["outcome", "allow"]}),
                               ("s5", {"eq": ["outcome", "deny"]}),
                               ("s9", {"eq": ["outcome", "escalate"]})]),
    ("s4", "tool_call", "schedule_opening", [("s12", None)]),
    ("s5", "tool_call", "ask_user", [("s6", None)]),
    ("s6", "condition", None, [("s7", {"eq": ["accepts_alternative", True]}),
                               ("s8", {"eq": ["accepts_alternative", False]})]),
    ("s7", "tool_call", "schedule_opening", [("s12", None)]),
    ("s8", "tool_call", "deny_request", [("s12", None)]),
    ("s9", "tool_call", "ask_user", [("s10", None)]),
    ("s10", "condition", None, [("s2", {"eq": ["fact_learned", True]}),
                                ("s11", {"eq": ["fact_learned", False]})]),
    ("s11", "tool_call", "escalate_request", [("s12", None)]),
    ("s12", "end", None, []),
]


@pytest.fixture(scope="module")
def tasks(sim_store):  # noqa: F811
    return sim_tasks(sim_store)


def _of(tasks, cls: str, i: int = 0):
    return [t for t in tasks if t.class_ == cls][i]


def _config(tmp_path, enabled: bool, name: str = "runtime.json"):
    path = tmp_path / name
    path.write_text(json.dumps({SONNET: {"enabled": enabled, "check": None}}))
    return path


# -- results as the environment hands them to `advance` -----------------------------------------

REQUEST = {"request": {"id": "r1"}, "record": {}, "registry": []}
INTENT = {"intent": {"tool": "schedule_opening", "args": ARGS}}


def rules(outcome, next_allowed=None) -> dict:
    return {"outcome": outcome, "rule_ids": [], "deciding_sections": [], "missing_facts": [],
            "next_allowed": next_allowed, "evaluated_outcome": None}


def answer(field, value=None, learned=True) -> dict:
    return {"field": field, "answer": "I don't know" if not learned else str(value),
            "learned": learned, "value": value if learned else None}


def walk(r: Runtime, *calls) -> list[str]:
    """Advance `r` over (tool, result, args) calls; the active step after each."""
    seen = []
    for tool, result, args in calls:
        assert r.allows(tool, args, {})[0], (tool, r.active)
        r.advance(tool, result, args)
        seen.append(r.active)
    return seen


def to_s2() -> Runtime:
    r = Runtime(load_desk_procedure())
    walk(r, ("get_request", REQUEST, {"id": "r1"}))
    assert r.active == "s2"
    return r


# -- desk-request@1 -----------------------------------------------------------------------------

def test_desk_procedure_is_valid_and_renders():
    body = load_desk_procedure()
    assert validate_ir(body) == [] and parse_skill(render_skill(as_unit(body)))[1] == 12
    assert body.source_kind == "authored" and all(s.span is None for s in body.steps)
    assert [(s.id, s.type, s.tool, [(e.to, None if e.guard is None else json.loads(e.guard))
                                    for e in s.next]) for s in body.steps] == TABLE
    # guards are adr-dsl@1 expressions, never empty, on condition steps only
    for s in body.steps:
        for e in s.next:
            assert (e.guard is not None) == (s.type == "condition")
            if e.guard is not None:
                assert e.guard.strip() and check_expr(json.loads(e.guard)) == []
        assert all(check_expr(p) == [] for p in s.preconditions)
    # every side effect is a tool_call; a schedule is irreversible, nothing else is
    for s in body.steps:
        if s.tool in SIDE_EFFECTS:
            assert s.type == "tool_call"
        assert (s.risk == "irreversible") == (s.tool == "schedule_opening"), s.id
    assert not any(s.requires_approval for s in body.steps)
    # tests: object[] of {condition, edge, steps}, one per condition outcome (Task 6 ruling)
    data = json.loads(rt_mod.DESK_PROCEDURE_PATH.read_text())["body"]
    assert body.tests == branch_paths(body) and len(body.tests) == 7
    assert all(set(t) == {"condition", "edge", "steps"} for t in data["tests"])
    # the Mermaid round trip, guards quoted (P40)
    text = render_mermaid(body)
    assert parse_mermaid(text) == ir_graph(body)
    guarded = [x for x in text.splitlines() if "-->|" in x]
    assert len(guarded) == 7 and all('-->|"' in x and '"|' in x for x in guarded)
    skill = render_skill(as_unit(body))
    assert "Tool: schedule_opening" in skill and 'description: "Use for every request' in skill
    assert render_skill(as_unit(load_desk_procedure())) == skill            # byte-stable


def test_load_desk_procedure_refuses_another_file(tmp_path):
    data = json.loads(rt_mod.DESK_PROCEDURE_PATH.read_text())
    (tmp_path / "other.json").write_text(json.dumps({**data, "id": "desk-request@2"}))
    with pytest.raises(ValueError, match="not desk-request@1"):
        load_desk_procedure(tmp_path / "other.json")
    data["body"]["steps"][1]["next"] = [{"to": "s99", "guard": None}]
    (tmp_path / "bad.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="s2: next s99 does not exist"):
        load_desk_procedure(tmp_path / "bad.json")


# -- the runtime ---------------------------------------------------------------------------------

def test_side_effect_refused_off_its_step_with_active_step_and_tools():
    rt = Runtime(load_desk_procedure())
    ok, refusal = rt.allows("schedule_opening", ARGS, {})
    assert not ok and refusal["active_step"] == "s1" and "get_request" in refusal["allowed_tools"]
    assert refusal["allowed_tools"] == list(READ_ONLY)
    assert refusal["step_text"] == rt.step.text and refusal["step_text"].startswith("Read the")
    assert refusal["rule_ids"] == [REFUSED] and refusal["decision"] == "deny"
    assert REFUSED[0] == "adr.runtime.refused@1"
    assert "schedule_opening is not allowed at step s1" in refusal["message"]
    for tool in SIDE_EFFECTS:
        assert not rt.allows(tool, {}, {})[0]
    assert rt.active == "s1" and rt.learned == {}               # a refusal moves nothing
    # at its own step the side effect is allowed, and the tools there name it
    r = to_s2()
    walk(r, ("check_rules", rules("allow"), INTENT))
    assert r.active == "s4" and r.allowed_tools() == [*READ_ONLY, "schedule_opening"]
    assert r.allows("schedule_opening", ARGS, {}) == (True, None)
    assert not r.allows("deny_request", {}, {})[0] and not r.allows("cancel_opening", {}, {})[0]


def test_reads_always_allowed_and_advance_follows_guards():
    body = load_desk_procedure()
    for s in body.steps:                                    # at every step, every read
        r = Runtime(body)
        r.active = s.id
        assert all(r.allows(tool, {}, {}) == (True, None) for tool in READ_ONLY), s.id
    r = Runtime(body)
    # a read that is not the active step's call leaves the step where it is
    for tool, result in (("check_rules", rules("allow")), ("rule_lookup", {"hits": []}),
                         ("ask_user", answer("vessel_class", "commercial"))):
        r.advance(tool, result, INTENT if tool == "check_rules" else {})
        assert r.active == "s1"
    assert walk(r, ("get_request", REQUEST, {"id": "r1"})) == ["s2"]
    # s2 advances only on a check of the requested opening (args_schema)
    r.advance("check_rules", rules("allow"), {"intent": {"tool": "deny_request", "args": {}}})
    assert r.active == "s2"
    for outcome, step in (("allow", "s4"), ("deny", "s5"), ("escalate", "s9")):
        r2 = to_s2()
        assert walk(r2, ("check_rules", rules(outcome), INTENT)) == [step]
        assert r2.learned["outcome"] == outcome
    # the guards read the last result only: an earlier outcome does not satisfy s6
    r3 = to_s2()
    walk(r3, ("check_rules", rules("deny", "2026-08-14T08:30:00"), INTENT))
    r3.advance("ask_user", answer("accepts_alternative", True), {"field": "vessel_class"})
    assert r3.active == "s5"                                 # not the step's question


@pytest.mark.parametrize("result", [
    {k: v for k, v in rules("allow").items() if k != "outcome"},   # missing
    rules(None), rules("maybe"), rules("ALLOW"), {**rules("allow"), "outcome": 5},
    {**rules("allow"), "outcome": True}, {**rules("allow"), "outcome": ["allow"]},
    "allow", None])
def test_a_missing_or_malformed_outcome_fails_closed_on_s2(result):
    r = to_s2()
    r.advance("check_rules", result, INTENT)
    assert r.active == "s2" and "outcome" not in r.learned
    for tool in SIDE_EFFECTS:
        ok, refusal = r.allows(tool, ARGS, {})
        assert not ok and refusal["active_step"] == "s2"
    # a well-formed result on the same step still moves it
    assert walk(r, ("check_rules", rules("allow"), INTENT)) == ["s4"]


def test_reschedule_path_reaches_s7_and_escalate_loop_returns_to_s2():
    at = "2026-08-14T08:30:00"
    # deny -> s5 -> accepts -> s7: a schedule only at next_allowed
    r = to_s2()
    assert walk(r, ("check_rules", rules("deny", at), INTENT),
                ("ask_user", answer("accepts_alternative", True),
                 {"field": "accepts_alternative"})) == ["s5", "s7"]
    ok, refusal = r.allows("schedule_opening", ARGS, {})
    assert not ok and "open_at must be 2026-08-14T08:30:00" in refusal["reason"]
    assert r.allows("schedule_opening", {**ARGS, "open_at": at}, {}) == (True, None)
    assert not r.allows("deny_request", {}, {})[0]
    r.advance("schedule_opening", {"executed": {}}, {**ARGS, "open_at": at})
    assert r.active == "s12"
    for tool in SIDE_EFFECTS:                       # the end step: nothing more, no cancel
        assert not r.allows(tool, {**ARGS, "open_at": at}, {})[0]
    # declines -> s8 deny
    r = to_s2()
    walk(r, ("check_rules", rules("deny", at), INTENT),
         ("ask_user", answer("accepts_alternative", False), {"field": "accepts_alternative"}))
    assert r.active == "s8" and r.allows("deny_request", {}, {}) == (True, None)
    assert not r.allows("schedule_opening", {**ARGS, "open_at": at}, {})[0]
    # an unknown acceptance stays on s5 (no guard holds) and refuses the side effects
    r = to_s2()
    walk(r, ("check_rules", rules("deny", at), INTENT),
         ("ask_user", answer("accepts_alternative", learned=False),
          {"field": "accepts_alternative"}))
    assert r.active == "s5" and not r.allows("deny_request", {}, {})[0]
    # escalate -> s9 -> the fact learned -> s2 again -> deny -> s5
    r = to_s2()
    assert walk(r, ("check_rules", rules("escalate"), INTENT),
                ("ask_user", answer("notice_received_at", "2026-08-13T18:00:00"),
                 {"field": "notice_received_at"}),
                ("check_rules", rules("deny", at), INTENT)) == ["s9", "s2", "s5"]
    assert r.learned["notice_received_at"] == "2026-08-13T18:00:00"
    # escalate -> s9 -> unknown -> s11, where only the escalation is allowed
    r = to_s2()
    assert walk(r, ("check_rules", rules("escalate"), INTENT),
                ("ask_user", answer("notice_received_at", learned=False),
                 {"field": "notice_received_at"})) == ["s9", "s11"]
    assert r.allows("escalate_request", {}, {}) == (True, None)
    assert not r.allows("schedule_opening", ARGS, {})[0]
    r.advance("escalate_request", {"executed": {}}, {})
    assert r.active == "s12"
    # the s10 guard reads the last result only, never an earlier one: a fact learned on the
    # first pass does not carry a malformed second answer (no `learned`) back to s2
    r = to_s2()
    walk(r, ("check_rules", rules("escalate"), INTENT),
         ("ask_user", answer("vessel_class", "commercial"), {"field": "vessel_class"}),
         ("check_rules", rules("escalate"), INTENT))
    assert r.active == "s9" and r.learned["fact_learned"] is True
    r.advance("ask_user", {"field": "notice_received_at", "answer": "?"},
              {"field": "notice_received_at"})
    assert r.active == "s9"


def test_a_condition_with_two_true_guards_stays_put():
    body = ProcedureBody(steps=[
        Step(id="s1", type="tool_call", text="Check.", span=None, tool="check_rules",
             next=[Edge(to="s2")]),
        Step(id="s2", type="condition", text="If.", span=None, next=[
            Edge(to="s3", guard='{"eq":["outcome","allow"]}'),
            Edge(to="s4", guard='{"known":"outcome"}')]),
        Step(id="s3", type="tool_call", text="Schedule.", span=None, tool="schedule_opening",
             next=[Edge(to="s5")]),
        Step(id="s4", type="tool_call", text="Deny.", span=None, tool="deny_request",
             next=[Edge(to="s5")]),
        Step(id="s5", type="end", text="", span=None)], source_kind="authored")
    r = Runtime(body)
    r.advance("check_rules", rules("allow"), {})          # both guards hold: ambiguous
    assert r.active == "s1" and not r.allows("schedule_opening", ARGS, {})[0]
    r.advance("check_rules", rules("deny"), {})           # only the second holds
    assert r.active == "s4"


def _one_step_body(**step) -> ProcedureBody:
    return ProcedureBody(steps=[
        Step(id="s1", type="tool_call", text="Schedule.", span=None, tool="schedule_opening",
             next=[Edge(to="s2")], **step),
        Step(id="s2", type="end", text="Reply.", span=None)], source_kind="authored")


def test_preconditions_are_kleene_and_unknown_refuses():
    r = Runtime(_one_step_body(preconditions=[{"cmp": ["notice_hours", ">=", 2]}]))
    ok, refusal = r.allows("schedule_opening", ARGS, {})                     # missing: U
    assert not ok and "is unknown" in refusal["reason"] and refusal["active_step"] == "s1"
    ok, refusal = r.allows("schedule_opening", ARGS, {"notice_hours": "four"})   # wrong type
    assert not ok and "is unknown" in refusal["reason"]
    ok, refusal = r.allows("schedule_opening", ARGS, {"notice_hours": {"value": 1}})
    assert not ok and "is false" in refusal["reason"]
    assert r.allows("schedule_opening", ARGS, {"notice_hours": {"value": 4,
                                                                "source": "record"}})[0]
    assert r.allows("schedule_opening", ARGS, {"notice_hours": 2})[0]
    # the record wins a name the runtime learned too; the desk's s8 reads both
    r = to_s2()
    walk(r, ("check_rules", rules("deny"), INTENT),
         ("ask_user", answer("accepts_alternative", False), {"field": "accepts_alternative"}))
    assert not r.allows("deny_request", {}, {"accepts_alternative": {"value": True}})[0]
    assert not r.allows("deny_request", {}, {"accepts_alternative": {"value": "no"}})[0]
    # a step that needs an approval refuses: the simulation has no approval channel
    ok, refusal = Runtime(_one_step_body(requires_approval=True)).allows(
        "schedule_opening", ARGS, {})
    assert not ok and "needs an approval" in refusal["reason"]


def test_the_runtime_refuses_procedures_it_cannot_enforce():
    bad = [_one_step_body(preconditions=[{"eq": ["x"]}]),
           _one_step_body(args_schema={"pattern": {"open_at": ".*"}}),
           ProcedureBody(steps=[Step(id="s1", type="instruction", text="Do.", span=None,
                                     next=[Edge(to="s2")]),
                                Step(id="s2", type="end", text="", span=None)],
                         source_kind="authored"),
           ProcedureBody(steps=[Step(id="s1", type="condition", text="If.", span=None,
                                     next=[Edge(to="s2", guard="If the bank rejected it"),
                                           Edge(to="s2", guard="otherwise")]),
                                Step(id="s2", type="end", text="", span=None)],
                         source_kind="authored"),
           ProcedureBody(steps=[Step(id="s1", type="tool_call", text="x", span=None,
                                     tool="get_request", next=[Edge(to="s9")]),
                                Step(id="s2", type="end", text="", span=None)],
                         source_kind="authored")]
    for body in bad:
        with pytest.raises(ValueError, match="cannot enforce"):
            Runtime(body)


def test_result_facts_read_only_the_named_fields():
    assert result_facts("check_rules", rules("deny", "2026-08-14T08:30:00")) == {
        "outcome": "deny", "next_allowed": "2026-08-14T08:30:00"}
    assert result_facts("check_rules", rules("allow")) == {"outcome": "allow"}
    assert result_facts("ask_user", answer("accepts_alternative", True)) == {
        "fact_learned": True, "accepts_alternative": True}
    assert result_facts("ask_user", answer("notice_received_at", learned=False)) == {
        "fact_learned": False}
    assert result_facts("ask_user", {"field": "x", "answer": "y"}) == {}   # no `learned`
    assert result_facts("get_request", REQUEST) == {} and result_facts("check_rules", 1) == {}


# -- the flag and the discipline check ----------------------------------------------------------

def test_discipline_check_rule():
    assert discipline_check({"gate": {"pass^1": 0.80}, "gate-runtime": {"pass^1": 0.75}},
                            "claude_code_sonnet")["enabled"]
    assert not discipline_check({"gate": {"pass^1": 0.80}, "gate-runtime": {"pass^1": 0.74}},
                                "claude_code_sonnet")["enabled"]
    assert DISCIPLINE_MARGIN == 0.05
    # pairs exactly 0.05 apart whose float difference is not: the naive comparison would
    # refuse them, the rule (rounded to nine places) enables them
    for g, gr in ((0.20, 0.15), (0.34, 0.29), (0.46, 0.41)):
        assert not gr >= g - 0.05
        assert discipline_check({"gate": {"pass^1": g}, "gate-runtime": {"pass^1": gr}},
                                SONNET)["enabled"], (g, gr)
    assert not discipline_check({"gate": {"pass^1": 0.20},
                                 "gate-runtime": {"pass^1": 0.1499999}}, SONNET)["enabled"]
    out = discipline_check({"gate": {"pass^1": 0.8, "tasks": 18, "trials": 72},
                            "gate-runtime": {"pass^1": 0.9, "tasks": 18, "trials": 72},
                            "no-gate": {"pass^1": 0.2}}, SONNET)
    assert out["enabled"] and out["check"]["profile"] == SONNET
    assert out["check"]["gate"] == {"pass^1": 0.8, "tasks": 18, "trials": 72}
    assert out["check"]["floor"] == 0.75 and out["check"]["margin"] == 0.05
    for summary in ({"gate": {"pass^1": 0.8}}, {"gate": {"pass^1": 0.8},
                                                "gate-runtime": {"pass^1": None}}):
        with pytest.raises(ValueError, match="needs pass\\^1"):
            discipline_check(summary, SONNET)


def test_runtime_enabled_reads_the_profile_flag(tmp_path):
    assert json.loads(REAL_CONFIG.read_text()) == {SONNET: {"enabled": False, "check": None}}
    assert rt_mod.RUNTIME_CONFIG != REAL_CONFIG                   # the conftest's copy (N9)
    assert rt_mod.RUNTIME_CONFIG.read_bytes() == REAL_CONFIG.read_bytes()
    assert not runtime_enabled(SONNET)
    assert not runtime_enabled(SONNET, _config(tmp_path, False))
    assert runtime_enabled(SONNET, _config(tmp_path, True))
    assert not runtime_enabled("claude_code_opus", _config(tmp_path, True))  # no entry
    assert not runtime_enabled(SONNET, tmp_path / "missing.json")
    (tmp_path / "bad.json").write_text(json.dumps({SONNET: {"enabled": "yes", "check": None}}))
    with pytest.raises(ValueError, match="not {\"enabled\": bool"):
        runtime_enabled(SONNET, tmp_path / "bad.json")
    path = _config(tmp_path, False)
    write_runtime_entry("claude_code_opus", {"enabled": True, "check": {"x": 1}}, path)
    assert runtime_enabled("claude_code_opus", path) and not runtime_enabled(SONNET, path)
    assert path.read_text().endswith("}\n")


# -- the environment ----------------------------------------------------------------------------

def _calls(log: list[dict]) -> list[dict]:
    return [x for x in log if x["kind"] == "call"]


def _schedule(task, at=None) -> dict:
    r = task.request
    return {"request": r["id"], "section": r["section"], "draw": r["draw"],
            "open_at": at or r["requested_open_at"]}


def test_a_disabled_profile_runs_without_the_runtime(sim_store, tmp_path, tasks):  # noqa: F811
    task = _of(tasks, "allow", 1)                     # the gate allows the requested time
    off, on = _config(tmp_path, False, "off.json"), _config(tmp_path, True, "on.json")
    # disabled: no runtime, and an off-procedure side effect goes straight to the gate
    with Env(sim_store.path, task, "gate", tmp_path / "a", profile=SONNET,
             runtime_config=off) as e:
        assert e.runtime is None
        out = e.call("schedule_opening", _schedule(task))
        assert out["ok"] and out["result"]["gate"]["decision"] == "allow"
        assert e.log_lines()[0]["runtime"] is None and _calls(e.log_lines())[0]["runtime"] is None
    # enabled: the same call is refused by the runtime and never reaches the gate
    with Env(sim_store.path, task, "gate", tmp_path / "b", profile=SONNET,
             runtime_config=on) as e:
        assert e.runtime is not None
        out = e.call("schedule_opening", _schedule(task))
        assert not out["ok"] and out["refusal"]["rule_ids"] == [REFUSED]
        assert e.world.end_state()["openings"] == []
        assert e.log_lines()[0]["runtime"] == {"procedure": "desk-request@1",
                                               "source": "profile", "step": "s1"}
    # no profile: no runtime, whatever the flag
    with Env(sim_store.path, task, "no-gate", tmp_path / "c", runtime_config=on) as e:
        assert e.runtime is None and e.call("schedule_opening", _schedule(task))["ok"]
    # the measured arm forces the runtime on, even for a disabled profile (builder note 19)
    with Env(sim_store.path, task, "gate-runtime", tmp_path / "d", profile=SONNET,
             runtime_config=off) as e:
        assert e.runtime is not None
        assert e.log_lines()[0]["runtime"]["source"] == "arm"
        assert not e.call("schedule_opening", _schedule(task))["ok"]
    # a runtime is given only in that arm; elsewhere the profile's flag decides
    with pytest.raises(ValueError, match="only in arm gate-runtime"):
        Env(sim_store.path, task, "gate", tmp_path / "e",
            runtime=Runtime(load_desk_procedure()))
    # the same through the environment process the CLI's factory starts
    for config, refused in ((off, False), (on, True)):
        make = agent.process_env_factory(sim_store.path, tmp_path / f"p-{refused}",
                                         profile=SONNET, runtime_config=config)
        pe = make(task, "gate", 0)
        try:
            out = pe.call("schedule_opening", _schedule(task))
        finally:
            pe.close()
        assert out["ok"] is not refused
        assert (pe.log_lines()[0]["runtime"] is None) is not refused


def test_gate_runtime_passes_the_runtime_then_the_gate(sim_store, tasks, tmp_path):  # noqa: F811
    allow, closed = _of(tasks, "allow", 1), _of(tasks, "deny-closed", 0)
    # the gate alone allows this schedule ...
    with Env(sim_store.path, allow, "gate", tmp_path / "g") as e:
        assert e.call("schedule_opening", _schedule(allow))["result"]["gate"]["decision"] \
            == "allow"
    # ... the runtime refuses it off its step, so the gate is never asked
    with Env(sim_store.path, allow, "gate-runtime", tmp_path / "gr") as e:
        out = e.call("schedule_opening", _schedule(allow))
        assert not out["ok"] and out["refusal"]["rule_ids"] == [REFUSED]
        assert out["refusal"]["active_step"] == "s1"
        (call,) = _calls(e.log_lines())
        assert call["gate"] is None and call["effect"] is None
        assert call["runtime"] == {"step": "s1", "decision": "refuse", "after": "s1",
                                   "rule_id": REFUSED[0]}
        assert e.world.end_state() == {"openings": [], "denials": [], "escalations": []}
        assert not (tmp_path / "gr" / "gate" / "gate.jsonl").exists()   # the gate judged none
    assert len((tmp_path / "g" / "gate" / "gate.jsonl").read_text().splitlines()) == 1
    # the runtime allows and the gate denies: a runtime whose first step is the schedule
    body = _one_step_body()
    with Env(sim_store.path, closed, "gate-runtime", tmp_path / "rg",
             runtime=Runtime(body)) as e:
        out = e.call("schedule_opening", _schedule(closed))
        assert not out["ok"] and out["refusal"]["decision"] == "deny"
        assert out["refusal"]["rule_ids"] != [REFUSED]
        (call,) = _calls(e.log_lines())
        assert call["gate"]["decision"] == "deny" and call["effect"] is None
        assert call["runtime"]["decision"] == "allow" and call["runtime"]["after"] == "s1"
        assert e.runtime.active == "s1"             # a gate refusal does not advance
    # both allow: executed, and the runtime moves on
    with Env(sim_store.path, allow, "gate-runtime", tmp_path / "both",
             runtime=Runtime(_one_step_body())) as e:
        out = e.call("schedule_opening", _schedule(allow))
        assert out["ok"] and out["result"]["gate"]["decision"] == "allow"
        assert e.runtime.active == "s2" and _calls(e.log_lines())[0]["runtime"]["after"] == "s2"


def test_the_environment_advances_on_its_own_results(sim_store, tasks, tmp_path):  # noqa: F811
    task = _of(tasks, "escalate", 0)
    with Env(sim_store.path, task, "gate-runtime", tmp_path / "e") as e:
        assert e.call("get_request", {"id": "r1"})["ok"] and e.runtime.active == "s2"
        facts = {k: v["value"] for k, v in task.record.items()}
        out = e.call("check_rules", {"intent": {"tool": "schedule_opening",
                                                "args": _schedule(task)}, "facts": facts})
        assert out["ok"] and out["result"]["outcome"] == "escalate"
        assert e.runtime.active == "s9"
        # the read results carry nothing of the runtime (P50: the arms share their calls)
        assert "runtime" not in json.dumps(out["result"])
        assert e.call("ask_user", {"field": "notice_received_at"})["result"]["answer"] \
            == "I don't know"
        assert e.runtime.active == "s11"
        out = e.call("escalate_request", {"request": "r1", "missing": ["notice_received_at"],
                                          "reason": "nobody knows when notice was given"})
        assert out["ok"] and e.runtime.active == "s12"
        steps = [(c["tool"], c["runtime"]["step"], c["runtime"]["after"])
                 for c in _calls(e.log_lines())]
        assert steps[:4] == [("get_request", "s1", "s2"), ("check_rules", "s2", "s9"),
                             ("ask_user", "s9", "s11"), ("escalate_request", "s11", "s12")]


# -- procedure_lookup serves the desk procedure (P52) -------------------------------------------

LOOKUP = {"task": "open a drawbridge for a vessel"}


STORE_HITS = [  # the sim store holds no procedure units: two store entries stand in for them
    {"rank": 1, "unit_id": "procedure/IRM 21.4.1.3/aaaaaaaaaaaa/" + "1" * 16,
     "canonical_ref": "IRM 21.4.1.3", "title": "Refund trace", "when_to_use": None,
     "doc_id": "1" * 64, "score": 2.5},
    {"rank": 2, "unit_id": "procedure/IRM 5.19.1/bbbbbbbbbbbb/" + "2" * 16,
     "canonical_ref": "IRM 5.19.1", "title": "Balance due", "when_to_use": "When owed.",
     "doc_id": "2" * 64, "score": 1.0}]


def test_procedure_lookup_serves_the_desk_procedure_first_in_every_arm(sim_store, tasks,  # noqa: F811
                                                                      tmp_path, monkeypatch):
    import dataclasses

    from adr_store.tools import Tools

    real = Tools.procedure_lookup

    def with_hits(self, task=None, **kw):
        res = real(self, task, **kw)
        return dataclasses.replace(res, catalog=[dict(h) for h in STORE_HITS]) \
            if task is not None else res

    monkeypatch.setattr(Tools, "procedure_lookup", with_hits)
    task = _of(tasks, "allow", 1)
    store = Tools(sim_store.path, acl=True, caller="user:auditor").procedure_lookup(
        LOOKUP["task"], as_of=task.as_of[:10]).to_dict()
    results = {}
    for arm in ("no-gate", "prompt", "gate", "gate-runtime"):
        with Env(sim_store.path, task, arm, tmp_path / arm) as e:
            out = e.call("procedure_lookup", LOOKUP)
            assert out["ok"], arm
            results[arm] = out["result"]
            if e.runtime is not None:
                assert e.runtime.active == "s1"            # a read: the runtime stays put
    first = results["no-gate"]
    assert all(r == first for r in results.values())          # identical in all four arms
    desk, *rest = first["catalog"]
    assert desk == rt_mod.desk_hit() and desk["rank"] == 1
    assert desk["unit_id"] == "procedure/desk-request@1" and desk["source_kind"] == "authored"
    assert desk["canonical_ref"] == "desk-request@1" and desk["doc_id"] is None
    assert set(store["catalog"][0]) < set(desk)                # the store entries' keys, and more
    assert desk["skill"] == render_skill(as_unit(load_desk_procedure()))
    assert 'If outcome == "allow" then step 4' in desk["skill"]
    assert desk["mermaid"] == render_mermaid(load_desk_procedure())
    # the store's own hits follow, in their order, ranks moved down by one
    assert store["catalog"] and rest == [{**h, "rank": h["rank"] + 1} for h in store["catalog"]]
    assert {k: v for k, v in first.items() if k != "catalog"} == \
        {k: v for k, v in json.loads(json.dumps(store)).items() if k != "catalog"}
    # the desk procedure by its id, in each view, exempt from the store's view and filters
    with Env(sim_store.path, task, "gate", tmp_path / "views") as e:
        body = load_desk_procedure()
        for ident in ("procedure/desk-request@1", "desk-request@1"):
            out = e.call("procedure_lookup", {"id": ident, "view": "catalog"})["result"]
            assert out["catalog"] == [rt_mod.desk_hit()] and out["rendering"] is None
            assert out["applicability_filters"] == {} and out["handle"] is None
            assert out["units"] == e.units_id and out["snapshot"] == e.tools.snapshot
            for view, want in (("skill", desk["skill"]), ("mermaid", desk["mermaid"]),
                               ("ir", body.model_dump(mode="json"))):
                out = e.call("procedure_lookup", {"id": ident, "view": view})["result"]
                assert out["rendering"] == want and out["catalog"] is None, (ident, view)
        # a task and the id together, or an unknown view, are the store's refusals still
        out = e.call("procedure_lookup", {"id": "desk-request@1", "task": "x"})
        assert not out["ok"] and "not both" in out["refusal"]["message"]
        out = e.call("procedure_lookup", {"id": "desk-request@1", "view": "pdf"})
        assert not out["ok"] and "view must be one of" in out["refusal"]["message"]


def test_the_stores_own_procedure_lookup_is_unchanged(sim_store, tasks,  # noqa: F811
                                                    tmp_path):
    from adr_store.tools import UNKNOWN_PROCEDURE, ToolError, Tools

    tools = Tools(sim_store.path, acl=True, caller="user:auditor")
    res = tools.procedure_lookup(LOOKUP["task"]).to_dict()
    assert res["catalog"] == []          # the sim store holds no procedure; no desk entry
    # the environment's catalog of the same store: the desk entry alone
    with Env(sim_store.path, _of(tasks, "allow", 1), "no-gate", tmp_path / "e") as e:
        assert e.call("procedure_lookup", LOOKUP)["result"]["catalog"] == [rt_mod.desk_hit()]
    for ident in ("procedure/desk-request@1", "desk-request@1"):
        with pytest.raises(ToolError, match=UNKNOWN_PROCEDURE):
            tools.procedure_lookup(id=ident, view="skill")


def test_env_log_with_the_desk_procedure_is_identical_twice(sim_store, tasks,  # noqa: F811
                                                            tmp_path):
    task = _of(tasks, "allow", 1)
    runs = []
    for k in range(2):
        with Env(sim_store.path, task, "gate-runtime", tmp_path / f"run-{k}") as e:
            e.call("get_request", {"id": "r1"})
            e.call("procedure_lookup", LOOKUP)
            e.call("procedure_lookup", {"id": "procedure/desk-request@1", "view": "skill"})
            e.call("check_rules", {"intent": {"tool": "schedule_opening",
                                              "args": _schedule(task)},
                                   "facts": _facts(task, False)})
            e.call("deny_request", {"request": "r1", "rule_id": "33 CFR 117.1081",
                                    "reason": "x"})                       # refused off s4
            e.call("schedule_opening", _schedule(task))
            instance = e._gate.instance
        runs.append(e.log_path.read_bytes().replace(instance.encode(), b"<instance>"))
    assert runs[0] == runs[1]
    lines = [json.loads(x) for x in runs[0].splitlines()]
    assert lines[2]["result"]["catalog"][0]["unit_id"] == "procedure/desk-request@1"
    assert [c["runtime"]["decision"] for c in lines[1:-1]] == ["allow"] * 4 + ["refuse", "allow"]


# -- trials in the gate-runtime arm -------------------------------------------------------------

def _facts(task, asked: bool) -> dict:
    facts = {k: v["value"] for k, v in task.record.items()}
    facts["local_procedure_conflict"] = registry_fact(task)
    if asked:
        facts.update({k: v for k, v in task.user_knows.items() if k != "accepts_alternative"})
    return facts


def procedure_script(task, turn: int, repeat: int, system: str, user: str) -> dict:
    """An agent that follows desk-request@1: read, ask what only the user knows, check the
    rules; then the terminal action of the expected state, and the reply."""
    req, cls = task.request, task.class_
    if turn == 0:
        asks = [{"tool": "ask_user", "args": {"field": f}} for f in sorted(task.user_knows)
                if f != "accepts_alternative"]
        check = {"tool": "check_rules", "args": {
            "intent": {"tool": "schedule_opening", "args": _schedule(task)},
            "facts": _facts(task, True)}}
        return {"tool_calls": [{"tool": "get_request", "args": {"id": req["id"]}}, *asks,
                               check]}
    if cls in ("allow", "emergency"):
        calls, status = [{"tool": "schedule_opening", "args": _schedule(task)}], "scheduled"
    elif cls == "reschedule":
        (o,) = task.expected_state["openings"]
        calls = [{"tool": "ask_user", "args": {"field": "accepts_alternative"}},
                 {"tool": "schedule_opening", "args": _schedule(task, o["open_at"])}]
        status = "scheduled"
    elif cls in ("deny-closed", "deny-notice"):
        calls = [{"tool": "ask_user", "args": {"field": "accepts_alternative"}},
                 {"tool": "deny_request", "args": {
                     "request": req["id"], "rule_id": f"33 CFR {req['section']}",
                     "reason": "the rules do not allow an opening at the requested time"}}]
        status = "denied"
    else:
        calls = [{"tool": "ask_user", "args": {"field": "notice_received_at"}},
                 {"tool": "escalate_request", "args": {
                     "request": req["id"], "missing": ["notice_received_at"],
                     "reason": "nobody knows when notice was given"}}]
        status = "escalated"
    return {"tool_calls": calls, "reply": {
        "status": status, "text": f"Request {status} under 33 CFR {req['section']}."}}


def _rounds(sim_store, tasks, arms, client, out, **kw):  # noqa: F811
    kw.setdefault("env_factory", local_env_factory(sim_store.path, out / "trials"))
    return run_rounds(tasks, arms, client, out, store=sim_store.path, **sim_acl(sim_store),
                      **kw)


def test_gate_runtime_runs_end_to_end_in_rounds(sim_store, tasks, tmp_path):  # noqa: F811
    one_each = [_of(tasks, c) for c in ("allow", "reschedule", "deny-closed", "deny-notice",
                                        "escalate", "emergency")]
    client = stub_agent(tmp_path / "llm", procedure_script, tasks)
    gate = _rounds(sim_store, one_each, ("gate",), client, tmp_path / "g", trials=1)
    made = client.calls
    out = _rounds(sim_store, one_each, ("gate-runtime",), client, tmp_path / "gr", trials=1)
    assert out["status"] == "complete" and len(out["rows"]) == 6
    for row, task in zip(out["rows"], one_each, strict=True):
        assert row["arm"] == "gate-runtime" and success(row, task), task.class_
        assert not any(row["violations"].values()), task.class_
        assert [c["runtime"]["after"] for c in _calls(row_log(tmp_path / "gr", row))][-1] \
            == "s12"
    assert out["summary"]["arms"]["gate-runtime"]["pass^1"] == 1.0
    assert gate["summary"]["arms"]["gate"]["pass^1"] == 1.0
    # nothing refused, so every gate-runtime call was one of the gate arm's (P50)
    assert client.calls == made and out["calls"]["made"] == 0
    summary = json.loads((tmp_path / "gr" / "summary.json").read_text())
    assert summary["arms"] == ["gate-runtime"]


def row_log(out_dir, row) -> list[dict]:
    path = out_dir / "trials" / row["arm"] / row["task_id"] / f"t{row['trial']}" / "env.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()]


def test_a_runtime_refusal_drops_the_turn_and_the_agent_sees_it(sim_store, tasks,  # noqa: F811
                                                                tmp_path):
    task = _of(tasks, "allow", 1)
    seen = []

    def script(t, turn, repeat, system, user):
        seen.append(user)
        if turn == 0:             # straight to the side effect, with a reply (P51)
            return {"tool_calls": [{"tool": "schedule_opening", "args": _schedule(t)},
                                   {"tool": "get_request", "args": {"id": "r1"}}],
                    "reply": {"status": "scheduled", "text": "Scheduled."}}
        return procedure_script(t, turn - 1, repeat, system, user)

    row = run_trial(task, "gate-runtime", 0, stub_agent(tmp_path / "llm", script, tasks),
                    local_env_factory(sim_store.path, tmp_path / "t"))
    first = row["transcript"]["turns"][0]
    assert first["refused_at"] == 0 and first["dropped"] == 1 and first["reply_dropped"]
    assert first["calls"][0]["out"]["refusal"]["rule_ids"] == [REFUSED]
    assert "adr.runtime.refused@1" in seen[1] and '"active_step": "s1"' in seen[1]
    assert "Read the request record with get_request" in seen[1]
    log = _calls(row["log"])
    assert log[0]["runtime"]["decision"] == "refuse" and log[0]["gate"] is None
    assert row["gate_outcomes"] == {"allow": 1, "deny": 0, "escalate": 0}
    assert success(row, task) and row["calls"] == 3


# -- where the runtime runs (N13) ---------------------------------------------------------------

def test_runtime_runs_in_the_environment_process_not_the_agent_loop(sim_store, tasks,  # noqa: F811
                                                                    tmp_path, monkeypatch,
                                                                    capsys):
    from adr_eval import cli, runner
    from adr_eval.sim.tasks import write_tasks

    def not_here(*a, **kw):
        raise AssertionError("the runtime ran in the agent's process")

    # in this (the agent loop's) process the runtime cannot run at all
    monkeypatch.setattr(Runtime, "allows", not_here)
    monkeypatch.setattr(Runtime, "advance", not_here)
    monkeypatch.setattr(Runtime, "__init__", not_here)
    made = []
    real = agent.process_env_factory

    def spy(store_path, root, **kw):
        made.append(kw)
        return real(store_path, root, **kw)

    monkeypatch.setattr(agent, "process_env_factory", spy)
    monkeypatch.setattr(runner, "make_client", lambda name, profiles, cache, max_retries=5:
                        stub_agent(tmp_path / "llm", oracle_script, tasks,
                                   model=f"stub-{name}"))
    path = tmp_path / "tasks.jsonl"
    task = _of(tasks, "allow", 1)
    write_tasks([task], path)
    acl = sim_acl(sim_store)
    code = cli.main(["sim", "drawbridge", "--store", str(sim_store.path), "--tasks", str(path),
                     "--arms", "gate-runtime", "--max-calls", "10", "--trials", "1",
                     "--directory", str(acl["directory"]), "--policy", str(acl["policy"])])
    out = capsys.readouterr().out
    assert code == 0, out
    assert made == [{}]                       # the CLI's factory: one process per trial
    (run,) = agent.OUT_ROOT.glob("sim-gate-runtime-*")
    log = row_log(run, {"arm": "gate-runtime", "task_id": task.task_id, "trial": 0})
    assert log[0]["runtime"]["source"] == "arm"
    refused = [c for c in _calls(log) if c["runtime"]["decision"] == "refuse"]
    # the oracle goes straight to the side effect: the runtime refused it in the env process
    assert refused and all(c["refusal"]["rule_ids"] == [REFUSED] and c["gate"] is None
                           for c in refused)


# -- `adr-eval sim runtime-check` ---------------------------------------------------------------

def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cli_runtime_check_writes_the_profiles_entry(sim_store, tasks, tmp_path,  # noqa: F811
                                                     monkeypatch, capsys):
    from adr_eval import cli
    from adr_eval.runner import REPO_ROOT as root
    from adr_eval.runner import load_profiles

    real_before = _sha(REAL_CONFIG)
    model = load_profiles(root / "config" / "models.json")[SONNET]["model"]
    two = [_of(tasks, "allow", 1), _of(tasks, "deny-closed", 0)]

    def run(arms, script, out):
        client = stub_agent(tmp_path / f"llm-{out}", script, tasks, model=model)
        _rounds(sim_store, two, arms, client, tmp_path / out, trials=1)
        return tmp_path / out

    good = run(("gate",), procedure_script, "gate")
    disciplined = run(("gate-runtime",), procedure_script, "gr")
    undisciplined = run(("gate-runtime",), oracle_script, "gr-oracle")
    config = _config(tmp_path, False)
    # pass^1 1.0 against 1.0: enabled
    assert cli.main(["sim", "runtime-check", str(good), str(disciplined), "--profile", SONNET,
                     "--config", str(config)]) == 0
    entry = json.loads(config.read_text())[SONNET]
    assert entry["enabled"] is True and entry["check"]["gate"]["pass^1"] == 1.0
    assert entry["check"]["gate-runtime"]["pass^1"] == 1.0 and entry["check"]["model"] == model
    assert "enabled" in capsys.readouterr().out
    # the oracle ignores the procedure: pass^1 0 against 1.0, so disabled
    assert cli.main(["sim", "runtime-check", str(good), str(undisciplined), "--profile",
                     SONNET, "--config", str(config)]) == 0
    entry = json.loads(config.read_text())[SONNET]
    assert entry["enabled"] is False and entry["check"]["gate-runtime"]["pass^1"] == 0.0
    assert not any(t.task_id in config.read_text() for t in two)   # totals only (P30)
    # refusals: a canary run, an arm missing, another profile's model, an unknown profile
    canary = tmp_path / "canary"
    _rounds(sim_store, two, ("gate", "gate-runtime"),
            stub_agent(tmp_path / "llm-canary", procedure_script, tasks, model=model), canary,
            canary=True)
    assert cli.main(["sim", "runtime-check", str(canary), "--profile", SONNET, "--config",
                     str(config)]) == 2
    assert "is a canary run" in capsys.readouterr().err
    for argv, msg in (([str(good)], "needs pass^1 of arm gate-runtime"),
                      ([str(good), str(disciplined), "--profile", "claude_code_opus"],
                       "ran under model"),
                      ([str(good), str(disciplined), "--profile", "nobody"],
                       "unknown profile")):
        if "--profile" not in argv:
            argv = [*argv, "--profile", SONNET]
        assert cli.main(["sim", "runtime-check", *argv, "--config", str(config)]) == 2, msg
        assert msg in capsys.readouterr().err, msg
    # the default path is the conftest's copy, never the committed file (N9)
    assert cli.main(["sim", "runtime-check", str(good), str(disciplined), "--profile",
                     SONNET]) == 0
    assert runtime_enabled(SONNET) and _sha(REAL_CONFIG) == real_before
