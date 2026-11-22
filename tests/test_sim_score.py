"""Scoring of the simulation (Phase 4 Task 20; spec §13.6, §15.3, §17 A1-A3; P35): pass^k, the
whole-state outcome, process false passes and the paired comparisons, each checked against a
small case computed by hand. No store, no model call."""

from __future__ import annotations

import itertools

import pytest

from adr_eval.scoring.stats import paired_bootstrap_ci, paired_ratio_diff_ci
from adr_eval.sim.score import compare, criteria, pass_hat_k, summarize
from adr_eval.sim.tasks import SimTask

OPEN = {"request": "r1", "section": "117.1081", "draw": 1, "open_at": "2026-08-14T09:30:00",
        "status": "active"}
EXPECTED = {"openings": [OPEN], "denials": [], "escalations": []}
WRONG = {"openings": [{**OPEN, "status": "cancelled"}], "denials": [], "escalations": []}
ZERO = {"V1": 0, "V2": 0, "V3": 0, "V4": 0}
SCHEDULED = {"status": "scheduled", "text": "Opening scheduled."}


def _task(i: int) -> SimTask:
    return SimTask.model_validate({
        "task_id": f"sim-allow-0{i + 1}", "class": "allow", "as_of": "2026-08-14T05:30:00",
        "request": {"id": "r1", "vessel": "Osprey", "section": "117.1081", "draw": 1,
                    "requested_open_at": "2026-08-14T09:30:00"},
        "record": {}, "user_knows": {"accepts_alternative": False}, "registry": [],
        "expected_state": EXPECTED,
        "reference": {"outcome": "allow", "denying_sections": [], "missing_facts": [],
                      "bindings_id": "b" * 64}})


TASKS = [_task(i) for i in range(3)]


def _row(task: int, arm: str, trial: int, *, success: bool = True, violations=None,
         reply="auto", gate=None, recovered=None) -> dict:
    if reply == "auto":
        reply = SCHEDULED
    return {"task_id": TASKS[task].task_id, "arm": arm, "trial": trial, "calls": trial + 1,
            "tokens": 100 * (trial + 1), "reply": reply,
            "end_state": EXPECTED if success else WRONG,
            "violations": {**ZERO, **(violations or {})},
            "gate_outcomes": {"allow": 0, "deny": 0, "escalate": 0, **(gate or {})},
            "recovered": recovered or {"denies": 0, "recovered": 0}, "failed": None}


def _hand_rows() -> list[dict]:
    """The hand case. no-gate: task 0 passes 4 of 4 (2 of them with a violation: false
    passes), task 1 passes 2 of 4 (1 false pass), task 2 passes none (two trials end in the
    expected state but without a reply, two with a reply in a wrong state; one has V4).
    gate: tasks 0 and 1 pass 4 of 4 (task 1 has one false pass), task 2 passes 1 of 4."""
    ng = [_row(0, "no-gate", 0, violations={"V1": 1}), _row(0, "no-gate", 1, violations={
        "V2": 2}), _row(0, "no-gate", 2), _row(0, "no-gate", 3),
          _row(1, "no-gate", 0, violations={"V3": 1}), _row(1, "no-gate", 1),
          _row(1, "no-gate", 2, success=False), _row(1, "no-gate", 3, success=False),
          _row(2, "no-gate", 0, reply=None), _row(2, "no-gate", 1, reply=None),
          _row(2, "no-gate", 2, success=False, violations={"V4": 1}),
          _row(2, "no-gate", 3, success=False)]
    g = [_row(0, "gate", k, gate={"allow": 1}) for k in range(4)]
    g += [_row(1, "gate", 0, violations={"V1": 1}, gate={"allow": 1})]
    g += [_row(1, "gate", k, gate={"allow": 1}) for k in (1, 2, 3)]
    g += [_row(2, "gate", 0, gate={"deny": 1, "allow": 1}, recovered={"denies": 1,
                                                                        "recovered": 1}),
          _row(2, "gate", 1, success=False, gate={"deny": 1}, recovered={"denies": 1,
                                                                          "recovered": 1}),
          _row(2, "gate", 2, success=False, gate={"deny": 1, "escalate": 1},
               recovered={"denies": 1, "recovered": 0}),
          _row(2, "gate", 3, success=False, gate={"escalate": 1})]
    return ng + g


def test_pass_hat_k():
    assert pass_hat_k(4, 4, 4) == 1.0 and pass_hat_k(3, 4, 4) == 0.0 and pass_hat_k(3, 4, 1) == 0.75
    assert pass_hat_k(2, 4, 2) == 1 / 6
    # C(c, k) / C(n, k) by hand: C(3, 2) / C(4, 2) = 3 / 6; C(2, 3) = 0; C(0, 1) = 0
    assert pass_hat_k(3, 4, 2) == 0.5 and pass_hat_k(2, 4, 3) == 0.0 and pass_hat_k(0, 4, 1) == 0
    assert pass_hat_k(4, 4, 1) == 1.0 and pass_hat_k(3, 4, 3) == 0.25
    for c, n, k in ((5, 4, 1), (1, 3, 4), (-1, 4, 1), (1, 4, 0)):
        with pytest.raises(ValueError):
            pass_hat_k(c, n, k)


def test_pass_hat_k_is_the_chance_that_k_draws_without_replacement_all_pass():
    for n in range(1, 6):
        for c in range(n + 1):
            outcomes = [True] * c + [False] * (n - c)
            for k in range(1, n + 1):
                draws = list(itertools.combinations(range(n), k))
                want = sum(all(outcomes[i] for i in d) for d in draws) / len(draws)
                assert pass_hat_k(c, n, k) == pytest.approx(want, abs=1e-12)


def test_false_pass_rate_and_paired_comparisons():
    s = summarize(_hand_rows(), TASKS)
    ng, g = s["arms"]["no-gate"], s["arms"]["gate"]
    # pass^k: the mean over tasks of C(c, k) / C(n, k); c = (4, 2, 0) and (4, 4, 1), n = 4
    assert ng["pass^1"] == pytest.approx((1 + 0.5 + 0) / 3)
    assert ng["pass^2"] == pytest.approx((1 + 1 / 6 + 0) / 3)
    assert ng["pass^3"] == pytest.approx(1 / 3) and ng["pass^4"] == pytest.approx(1 / 3)
    assert g["pass^1"] == pytest.approx((1 + 1 + 0.25) / 3)
    assert g["pass^2"] == pytest.approx(2 / 3) and g["pass^4"] == pytest.approx(2 / 3)
    # outcome success: the whole state AND a reply (task 2's no-reply trials fail)
    assert (ng["trials"], ng["successes"], ng["outcome_success"]) == (12, 6, 0.5)
    assert (g["trials"], g["successes"]) == (12, 9)
    assert ng["no_reply"] == 2 and g["no_reply"] == 0
    # process violations and false passes (an outcome success with any violation)
    assert ng["violations"] == {"V1": 1, "V2": 2, "V3": 1, "V4": 1}
    assert g["violations"] == {"V1": 1, "V2": 0, "V3": 0, "V4": 0}
    assert (ng["false_passes"], g["false_passes"]) == (3, 1)
    assert ng["false_pass_rate"] == pytest.approx(3 / 6) and g["false_pass_rate"] == \
        pytest.approx(1 / 9)
    assert ng["trials_with_violations"] == 4 and g["trials_with_violations"] == 1
    # gate outcomes by class, recovery after a deny, calls and tokens per trial
    assert g["gate_outcomes"] == {"allow": 9, "deny": 3, "escalate": 2}
    assert ng["gate_outcomes"] == {"allow": 0, "deny": 0, "escalate": 0}
    assert g["recovery"] == {"denies": 3, "recovered": 2, "rate": pytest.approx(2 / 3)}
    assert ng["recovery"] == {"denies": 0, "recovered": 0, "rate": None}
    assert g["calls_per_trial"] == 2.5 and g["tokens_per_trial"] == 250.0
    c = compare(s, "no-gate", "gate")
    assert c["tasks"] == 3
    # A1: pass^4, gate - no-gate = 2/3 - 1/3
    assert c["A1"]["a"] == pytest.approx(1 / 3) and c["A1"]["b"] == pytest.approx(2 / 3)
    assert c["A1"]["diff"] == pytest.approx(1 / 3)
    # A2: false passes / successes per task, paired over tasks: 1/9 - 3/6
    assert c["A2"]["a"] == pytest.approx(0.5) and c["A2"]["b"] == pytest.approx(1 / 9)
    want = paired_ratio_diff_ci([2, 1, 0], [4, 2, 0], [0, 1, 0], [4, 4, 1], n=10_000,
                                seed=20261108)
    assert want[0] == pytest.approx(1 / 9 - 1 / 2)
    assert (c["A2"]["diff"], c["A2"]["lo"], c["A2"]["hi"]) == want
    assert c["A2"]["demonstrated"] is True
    # A3: pass^1 per task, paired bootstrap over tasks: mean of (0, 0.5, 0.25)
    want = paired_bootstrap_ci([1, 0.5, 0], [1, 1, 0.25], n=10_000, seed=20261108)
    assert want[0] == pytest.approx(0.25)
    assert (c["A3"]["diff"], c["A3"]["lo"], c["A3"]["hi"]) == want
    assert c["A3"]["lo"] <= 0.25 <= c["A3"]["hi"]


def test_one_task_intervals_collapse_to_the_point():
    rows = [_row(0, "no-gate", k, success=k < 2, violations={"V2": 1} if k == 0 else None)
            for k in range(4)] + [_row(0, "gate", k, success=k < 3) for k in range(4)]
    c = compare(summarize(rows, TASKS[:1]), "no-gate", "gate")
    assert (c["A3"]["diff"], c["A3"]["lo"], c["A3"]["hi"]) == pytest.approx((0.25,) * 3)
    assert (c["A2"]["diff"], c["A2"]["lo"], c["A2"]["hi"]) == pytest.approx((-0.5,) * 3)
    assert c["A1"]["diff"] == 0.0


def test_a2_is_not_demonstrated_without_a_no_gate_false_pass_and_k_needs_k_rounds():
    rows = [_row(t, arm, k) for t in range(3) for arm in ("no-gate", "gate") for k in range(4)]
    s = summarize(rows, TASKS)
    c = compare(s, "no-gate", "gate")
    assert c["A2"]["a"] == 0.0 and c["A2"]["demonstrated"] is False
    assert criteria(s)["A2"]["pass"] is False
    # two complete rounds (a budget stop): pass^3 and pass^4 are not computable
    two = summarize([r for r in rows if r["trial"] < 2], TASKS)
    assert two["arms"]["gate"]["pass^2"] == 1.0
    assert two["arms"]["gate"]["pass^3"] is None and two["arms"]["gate"]["pass^4"] is None
    assert compare(two, "no-gate", "gate")["A1"] is None
    # no success at all in an arm: the false-pass rate and A2 have no denominator
    bad = [_row(t, "no-gate", k, success=False) for t in range(3) for k in range(4)]
    s = summarize(bad + [r for r in rows if r["arm"] == "gate"], TASKS)
    assert s["arms"]["no-gate"]["false_pass_rate"] is None
    a2 = compare(s, "no-gate", "gate")["A2"]
    assert a2["a"] is None and a2["diff"] is None and a2["demonstrated"] is False


def test_summarize_refuses_duplicate_and_unknown_trials():
    rows = _hand_rows()
    with pytest.raises(ValueError, match="twice"):
        summarize(rows + rows[:1], TASKS)
    with pytest.raises(ValueError, match="unknown task"):
        summarize([{**rows[0], "task_id": "sim-other-01"}], TASKS)


def test_criteria_apply_the_section_17_bars():
    rows = _hand_rows()
    prompt = [_row(t, "prompt", k, success=t == 0 or (t == 1 and k < 3)) for t in range(3)
              for k in range(4)]                       # pass^4 = 1/3 <= gate's 2/3
    cr = criteria(summarize(rows + prompt, TASKS))
    assert cr["A1"]["gate-no-gate"] == pytest.approx(1 / 3)
    assert cr["A1"]["gate-prompt"] == pytest.approx(1 / 3)
    assert cr["A1"]["pass"] is True
    # A2: 1/9 <= half of 1/2, but three tasks give an interval whose upper bound decides
    a2 = compare(summarize(rows, TASKS), "no-gate", "gate")["A2"]
    assert cr["A2"]["pass"] is (a2["b"] <= a2["a"] / 2 and a2["hi"] < 0)
    a3 = compare(summarize(rows, TASKS), "no-gate", "gate")["A3"]
    assert cr["A3"]["pass"] is (a3["lo"] > -0.10)
    # A1 fails when gate is under prompt, or the gain is short of +0.10
    better = [_row(t, "prompt", k) for t in range(3) for k in range(4)]
    assert criteria(summarize(rows + better, TASKS))["A1"]["pass"] is False
    ng = [r for r in rows if r["arm"] == "no-gate"]
    same = [{**r, "arm": arm} for r in ng for arm in ("gate", "prompt")]
    assert criteria(summarize(ng + same, TASKS))["A1"]["pass"] is False
    assert criteria({"arms": {}, "per_task": {}}) == {}


def test_a_gain_of_exactly_ten_points_meets_the_a1_bar():
    # five trials: pass^4 = C(c, 4) / 5. Task 0: no-gate 0 of 5, gate 5 of 5 (0 -> 1); task 1:
    # no-gate 5 of 5, gate 4 of 5 (1 -> 0.2). The gain is (1 - 0.8) / 2 = 0.10 exactly, which
    # floats compute as 0.09999999999999998
    tasks = TASKS[:2]
    passes = {("no-gate", 0): 0, ("gate", 0): 5, ("no-gate", 1): 5, ("gate", 1): 4}
    rows = [_row(t, arm, k, success=k < passes[(arm, t)]) for t in range(2)
            for arm in ("no-gate", "gate") for k in range(5)]
    rows += [{**r, "arm": "prompt"} for r in rows if r["arm"] == "no-gate"]
    cr = criteria(summarize(rows, tasks))
    assert cr["A1"]["gate-no-gate"] < 0.10                 # the float difference falls short
    assert cr["A1"]["gate-no-gate"] == pytest.approx(0.10) and cr["A1"]["pass"] is True
    # without the prompt arm "gate >= prompt" cannot be judged: A1 is not decided
    cr = criteria(summarize([r for r in rows if r["arm"] != "prompt"], tasks))
    assert cr["A1"]["gate-prompt"] is None and cr["A1"]["pass"] is None


def test_intervals_use_seed_20261108_and_10000_resamples(monkeypatch):
    tasks = [_task(i) for i in range(12)]
    # per task: (no-gate successes, no-gate false passes, gate successes, gate false passes)
    plan = [(4, 3, 4, 0), (3, 1, 4, 1), (2, 2, 3, 0), (4, 0, 4, 0), (1, 1, 2, 0), (0, 0, 1, 0),
            (4, 2, 3, 1), (3, 0, 4, 0), (2, 1, 2, 0), (4, 4, 4, 1), (1, 0, 3, 0), (3, 3, 4, 2)]
    rows = []
    for t, (cn, fn, cg, fg) in enumerate(plan):
        for arm, c, f in (("no-gate", cn, fn), ("gate", cg, fg)):
            rows += [{**_row(0, arm, k, success=k < c,
                             violations={"V2": 1} if k < f else None),
                      "task_id": tasks[t].task_id} for k in range(4)]
    c = compare(summarize(rows, tasks), "no-gate", "gate")
    num_a, den_a = [p[1] for p in plan], [p[0] for p in plan]
    num_b, den_b = [p[3] for p in plan], [p[2] for p in plan]
    x, y = [p[0] / 4 for p in plan], [p[2] / 4 for p in plan]
    a2 = paired_ratio_diff_ci(num_a, den_a, num_b, den_b, n=10_000, seed=20261108)
    a3 = paired_bootstrap_ci(x, y, n=10_000, seed=20261108)
    assert (c["A2"]["diff"], c["A2"]["lo"], c["A2"]["hi"]) == a2
    assert (c["A3"]["diff"], c["A3"]["lo"], c["A3"]["hi"]) == a3
    assert a2[0] == pytest.approx(5 / 38 - 17 / 31) and a3[0] == pytest.approx(7 / 48)
    # A2's bounds show the seed and the resample count; pass^1 at four trials is too coarse
    # for A3's to, so the calls themselves are checked
    for other in ({"n": 10_000, "seed": 20261109}, {"n": 1_000, "seed": 20261108}):
        assert paired_ratio_diff_ci(num_a, den_a, num_b, den_b, **other)[1:] != a2[1:]
    from adr_eval.sim import score

    seen = []
    for name in ("paired_bootstrap_ci", "paired_ratio_diff_ci"):
        real = getattr(score, name)
        monkeypatch.setattr(score, name, lambda *a, real=real, name=name, **kw: (
            seen.append((name, kw)), real(*a, **kw))[1])
    compare(summarize(rows, tasks), "no-gate", "gate")
    assert sorted(n for n, _ in seen) == ["paired_bootstrap_ci"] * 2 + [  # A1, A3; A2
        "paired_ratio_diff_ci"]
    assert all(kw == {"n": 10_000, "seed": 20261108} for _, kw in seen)


def _fig(i: int, c: int, fp: int, n: int = 4) -> dict:
    return {"task": i, "n": n, "c": c, "false_passes": fp,
            **{f"pass^{k}": pass_hat_k(c, n, k) for k in range(1, 5)}}


def _two_arms(ng: list[tuple[int, int]], g: list[tuple[int, int]]) -> dict:
    """A summary of per-task (successes, false passes) for no-gate and gate (and prompt =
    no-gate), as `summarize` would give it."""
    per = {"no-gate": [_fig(i, c, f) for i, (c, f) in enumerate(ng)],
           "gate": [_fig(i, c, f) for i, (c, f) in enumerate(g)]}
    per["prompt"] = per["no-gate"]
    return {"arms": dict.fromkeys(per, {}), "per_task": per}


def test_a2_fails_on_the_interval_alone():
    # one task holds both no-gate false passes: rate 2/24 against gate's 1/24 (b <= a/2), but a
    # resample without that task and with the gate's one goes the other way: hi >= 0
    s = _two_arms([(4, 2)] + [(4, 0)] * 5, [(4, 0)] * 5 + [(4, 1)])
    a2 = compare(s, "no-gate", "gate")["A2"]
    assert a2["demonstrated"] and a2["b"] <= a2["a"] / 2 and a2["hi"] >= 0
    assert criteria(s)["A2"]["pass"] is False
    # the same rates with the fall on every task: the upper bound is below 0, and A2 passes
    s = _two_arms([(4, 2)] * 6, [(4, 1)] * 6)
    a2 = compare(s, "no-gate", "gate")["A2"]
    assert a2["hi"] < 0 and criteria(s)["A2"]["pass"] is True


def test_a2_needs_a_demonstration_whatever_the_other_figures(monkeypatch):
    from adr_eval.sim import score

    # with real figures "not demonstrated" (no no-gate false pass) already fails hi < 0, so
    # the bar's own guard is checked on a comparison that would pass but for it
    real = score.compare

    def faked(summary, a, b):
        out = real(summary, a, b)
        if (a, b) == ("no-gate", "gate"):
            out["A2"] = {"a": 0.5, "b": 0.1, "diff": -0.4, "lo": -0.6, "hi": -0.2,
                         "demonstrated": False}
        return out

    monkeypatch.setattr(score, "compare", faked)
    s = _two_arms([(4, 2)] * 6, [(4, 1)] * 6)
    assert criteria(s)["A2"]["pass"] is False
    monkeypatch.setattr(score, "compare", real)
    # no gate success at all: no rate, not demonstrated, and the bar is judged, not crashed
    s = _two_arms([(4, 2)] * 3, [(0, 0)] * 3)
    a2 = compare(s, "no-gate", "gate")["A2"]
    assert a2["b"] is None and a2["demonstrated"] is False
    assert criteria(s)["A2"]["pass"] is False


def test_a3_fails_on_its_lower_bound_not_its_mean():
    # pass^1 differences (-1, 0.25, 0.25, 0.25): the mean -0.0625 is above -0.10, the paired
    # lower bound is far below it
    s = _two_arms([(4, 0), (0, 0), (0, 0), (0, 0)], [(0, 0), (1, 0), (1, 0), (1, 0)])
    a3 = compare(s, "no-gate", "gate")["A3"]
    assert a3["diff"] == pytest.approx(-0.0625) and a3["lo"] <= -0.10 < a3["diff"]
    assert criteria(s)["A3"]["pass"] is False
    s = _two_arms([(2, 0)] * 4, [(2, 0)] * 4)
    assert criteria(s)["A3"]["pass"] is True                 # lo = 0 > -0.10


def test_a_success_with_only_v4_is_a_false_pass():
    # the state matches and there is a reply, but its status contradicts the state: V4 only
    rows = [_row(0, "no-gate", 0, violations={"V4": 1},
                 reply={"status": "denied", "text": "Denied."}),
            _row(0, "no-gate", 1)]
    s = summarize(rows, TASKS[:1])["arms"]["no-gate"]
    assert s["successes"] == 2 and s["false_passes"] == 1 and s["false_pass_rate"] == 0.5
    assert s["violations"] == {"V1": 0, "V2": 0, "V3": 0, "V4": 1}
