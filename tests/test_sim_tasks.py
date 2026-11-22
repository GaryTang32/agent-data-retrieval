"""The tasks of `sim-drawbridge v0.1` (Phase 4 Task 19; spec §13.4, P16, P31, P33, P35, P37,
P49; preflight C4, C5): six classes of three in the §13.4 format, placed by class on the
fixture's agreement draws, with expected states and `reference` from the reference evaluator
only, and `adr-eval sim tasks --gen`. No model call; no gate."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta

import pytest

from adr_eval import cli
from adr_eval.sim import tasks as st
from adr_eval.sim.tasks import (
    CLASSES,
    SEED4,
    SimError,
    SimTask,
    canonical,
    full_record,
    generate_tasks,
    load_tasks,
    reference_draws,
)
from adr_eval.sim.user import DONT_KNOW, answer
from adr_store.bindings import decide
from adr_store.bindings.manifest import load_bindings, read_bindings_head
from adr_store.bindings.reference import ref_decide, ref_in_window, ref_next_allowed
from tests.sim_fixtures import sim_store  # noqa: F401 - the fixture
from tests.store.units_fixtures import make_units_store

SPEC_KEYS = {"task_id", "class", "as_of", "request", "record", "user_knows", "registry",
             "expected_state", "reference"}


def _bindings(store) -> str:
    return read_bindings_head(store.path)


def _inside(ref, at: datetime) -> bool:
    return any(ref_in_window(w, at.hour * 60 + at.minute, at.date()) for w in ref.closed)


def _requested(t: SimTask) -> datetime:
    return datetime.fromisoformat(t.request["requested_open_at"])


def test_tasks_are_six_classes_of_three_in_the_spec_format(sim_store):  # noqa: F811
    ts = generate_tasks(sim_store.path, _bindings(sim_store), SEED4)
    assert Counter(t.class_ for t in ts) == {c: 3 for c in CLASSES}
    assert [t.task_id for t in ts] == [f"sim-{c}-{i:02d}" for c in CLASSES for i in (1, 2, 3)]
    for t in ts:
        line = json.loads(canonical(t))
        assert set(line) == SPEC_KEYS and line["class"] == t.class_
        assert set(line["request"]) == {"id", "vessel", "section", "draw", "requested_open_at"}
        assert set(line["expected_state"]) == {"openings", "denials", "escalations"}
        assert set(line["reference"]) == {"outcome", "denying_sections", "missing_facts"}
        for o in line["expected_state"]["openings"]:
            assert set(o) == {"request", "section", "draw", "open_at", "status"}
        for fact in line["record"].values():
            assert fact["source"] == "record" and set(fact) == {"value", "source"}
        # canonical JSON: sorted keys, no padding, one newline, and it loads back the same
        raw = canonical(t)
        assert raw.endswith(b"\n") and raw.count(b"\n") == 1 and b": " not in raw
        assert SimTask.model_validate_json(raw) == t


def test_expected_states_come_from_the_reference_evaluator(sim_store, monkeypatch):  # noqa: F811
    from adr_store.bindings import checks
    from adr_store.gate import client, server

    before = b"".join(canonical(t) for t in generate_tasks(sim_store.path, _bindings(sim_store)))

    def boom(*a, **k):
        raise AssertionError("the gate or the bindings' decision was consulted")

    # the gate process, its client and every decision over bindings raise: still generated
    for owner, name in ((client.GateClient, "__init__"), (client.GateClient, "judge"),
                        (client.GateProcess, "__init__"), (server, "load_enforcement"),
                        (decide, "decide"), (decide, "judge"), (decide, "decide_draw"),
                        (decide, "decide_values"), (decide, "next_allowed"),
                        (checks, "decide_bindings")):
        monkeypatch.setattr(owner, name, boom)
    after = b"".join(canonical(t) for t in generate_tasks(sim_store.path, _bindings(sim_store)))
    assert after == before
    # and they follow the reference evaluator: a shifted ref_next_allowed moves every
    # reschedule opening by that minute, an evaluator that allows everything leaves no
    # deny or escalate class to place
    monkeypatch.setattr(st, "ref_next_allowed",
                        lambda r, at, rec: ref_next_allowed(r, at, rec) + timedelta(minutes=1))
    shifted = generate_tasks(sim_store.path, _bindings(sim_store))
    old = {t.task_id: t for t in load_from(before)}
    for t in shifted:
        if t.class_ == "reschedule":
            (o,), (p,) = t.expected_state["openings"], old[t.task_id].expected_state["openings"]
            assert datetime.fromisoformat(o["open_at"]) == \
                datetime.fromisoformat(p["open_at"]) + timedelta(minutes=1)
    monkeypatch.setattr(st, "ref_decide", lambda r, at, rec: ref_decide(r, at, {
        **rec, "vessel_class": {"value": "public_safety", "source": "user"}}))
    with pytest.raises(SimError, match="could not be placed"):
        generate_tasks(sim_store.path, _bindings(sim_store))


def load_from(data: bytes) -> list[SimTask]:
    return [SimTask.model_validate_json(x) for x in data.splitlines()]


def test_expected_states_and_references_hold_under_the_reference_evaluator(sim_store):  # noqa: F811
    _, refs, _ = reference_draws(sim_store.path, _bindings(sim_store))
    for t in generate_tasks(sim_store.path, _bindings(sim_store)):
        ref = refs[(t.request["section"], t.request["draw"])]
        rec, at = full_record(t), _requested(t)
        d = ref_decide(ref, at, rec)
        assert t.reference == {"outcome": d.outcome, "denying_sections": sorted(
            d.denying_sections), "missing_facts": list(d.missing)}
        want = {"allow": "allow", "reschedule": "deny", "deny-closed": "deny",
                "deny-notice": "deny", "escalate": "escalate", "emergency": "allow"}
        assert d.outcome == want[t.class_]
        slot = {"request": "r1", "section": t.request["section"], "draw": t.request["draw"],
                "status": "active"}
        if t.class_ in ("allow", "emergency"):
            opens = [{**slot, "open_at": t.request["requested_open_at"]}]
        elif t.class_ == "reschedule":
            opens = [{**slot, "open_at": ref_next_allowed(ref, at, rec).isoformat()}]
        else:
            opens = []
        assert t.expected_state == {
            "openings": opens, "denials": ["r1"] if t.class_.startswith("deny") else [],
            "escalations": ["r1"] if t.class_ == "escalate" else []}
        if t.class_ in ("deny-closed", "deny-notice", "reschedule"):
            assert t.reference["denying_sections"] == [t.request["section"]]


def test_escalate_tasks_hide_notice_from_record_and_user(sim_store):  # noqa: F811
    ts = [t for t in generate_tasks(sim_store.path, _bindings(sim_store))
          if t.class_ == "escalate"]
    _, refs, _ = reference_draws(sim_store.path, _bindings(sim_store))
    assert len(ts) == 3
    for t in ts:
        assert "notice_received_at" not in t.record and "notice_received_at" not in t.user_knows
        assert answer(t, "notice_received_at") == (DONT_KNOW, None)
        assert refs[(t.request["section"], t.request["draw"])].notice_hours is not None
        assert t.record["vessel_class"]["value"] in ("commercial", "recreational")   # P37
        assert t.reference == {"outcome": "escalate", "denying_sections": [],
                               "missing_facts": ["notice_minutes"]}
        assert t.expected_state == {"openings": [], "denials": [], "escalations": ["r1"]}
        assert not _inside(refs[(t.request["section"], t.request["draw"])], _requested(t))


def test_requested_times_are_placed_by_class(sim_store):  # noqa: F811
    _, refs, _ = reference_draws(sim_store.path, _bindings(sim_store))
    ts = generate_tasks(sim_store.path, _bindings(sim_store))
    user_notice = []
    for t in ts:
        ref = refs[(t.request["section"], t.request["draw"])]
        at, as_of = _requested(t), datetime.fromisoformat(t.as_of)
        assert as_of.date() > datetime(2026, 6, 26).date()                       # P31
        assert as_of.date() == at.date() and as_of.time().isoformat() == "05:30:00"
        assert at > as_of and at.minute % 15 == 0
        assert _inside(ref, at) == (t.class_ in ("reschedule", "deny-closed", "emergency"))
        notice = t.record.get("notice_received_at", {}).get("value") or \
            t.user_knows.get("notice_received_at")
        if notice is not None:
            got = datetime.fromisoformat(notice)
            assert got <= as_of                                  # received by the scenario
            minutes = (at - got) / timedelta(minutes=1)
            if t.class_ == "deny-notice":                        # short by at least an hour
                assert minutes <= 60 * ref.notice_hours - 60
            else:
                assert minutes >= 60 * (ref.notice_hours or 0) + 60
        if t.class_ in ("allow", "reschedule", "deny-closed", "deny-notice", "escalate"):
            assert t.record["vessel_class"]["value"] in ("commercial", "recreational")  # P37
        assert t.user_knows["accepts_alternative"] is (t.class_ == "reschedule")
        if t.class_ == "deny-notice":
            assert set(t.record) == {"vessel_class"} and "notice_received_at" in t.user_knows
        if t.class_ in ("reschedule", "deny-closed"):
            assert set(t.record) == {"notice_received_at", "vessel_class"}
        if t.class_ == "emergency":
            assert t.record == {} and t.user_knows["vessel_class"] == "public_safety"
            assert t.registry == [{"procedure_id": t.registry[0]["procedure_id"],
                                   "section": t.request["section"], "draw": t.request["draw"],
                                   "approved": True, "approved_by": "Captain of the Port",
                                   "conflicts_with_opening": False}]
            assert full_record(t)["local_procedure_conflict"] == {"value": False,
                                                                  "source": "record"}
        else:
            assert t.registry == []
        if t.class_ == "allow" and "notice_received_at" in t.user_knows:
            user_notice.append(t)
    # notice only the user knows in exactly one allow task, on a draw with a threshold
    assert [t.task_id for t in user_notice] == ["sim-allow-01"]
    assert refs[(user_notice[0].request["section"],
                 user_notice[0].request["draw"])].notice_hours is not None
    allow = [t for t in ts if t.class_ == "allow"]
    assert sum("notice_received_at" in t.record for t in allow) == 2


def test_reschedule_time_is_the_same_under_both_next_allowed_definitions(sim_store):  # noqa: F811
    # the gate's definition (decide.next_allowed over the signed-off bindings) and the
    # reference's agree on every reschedule task: notice is known and enough (Task 16 caveat)
    m, bindings = load_bindings(sim_store.path, _bindings(sim_store))
    for t in generate_tasks(sim_store.path, _bindings(sim_store)):
        if t.class_ != "reschedule":
            continue
        args = {"section": t.request["section"], "draw": t.request["draw"]}
        doc = bindings[0].doc_id
        sel = decide.select(bindings, "schedule_opening", args, doc)
        assert sel
        gate_next = decide.next_allowed(sel, _requested(t), full_record(t))
        assert gate_next.isoformat() == t.expected_state["openings"][0]["open_at"]


def test_requests_target_the_bindings_draw_numbers_of_known_draws(sim_store, monkeypatch):  # noqa: F811
    m, bindings = load_bindings(sim_store.path, _bindings(sim_store))
    pairs = {(s, d) for s, _, d in m.agreement_pairs}
    known = {(s, d) for _, s, d in m.known_draws}
    for t in generate_tasks(sim_store.path, _bindings(sim_store)):
        key = (t.request["section"], t.request["draw"])
        assert key in pairs and key in known                                  # C5, P49
    # the bindings' number targets the request; the Phase 3 number picks the reference draw
    from adr_store.bindings import manifest

    def renumbered(path, bid):
        m0, bs = load_bindings(path, bid)
        bs = [b.model_copy(update={"target": {"tool": "schedule_opening", "selector": {
            "section": "117.821", "draw": 7}}}) if b.target["selector"] == {
            "section": "117.821", "draw": 2} else b for b in bs]
        doc = bs[0].doc_id
        return m0.model_copy(update={
            "agreement_pairs": [("117.821", 2, 7)],
            "known_draws": sorted({*m0.known_draws, (doc, "117.821", 7)})}), bs

    monkeypatch.setattr(manifest, "load_bindings", renumbered)
    _, refs, _ = reference_draws(sim_store.path, _bindings(sim_store))
    assert list(refs) == [("117.821", 7)] and refs[("117.821", 7)].draw == 2
    assert refs[("117.821", 7)].notice_hours == 4

    def unknown(path, bid):
        m0, bs = renumbered(path, bid)
        return m0.model_copy(update={"known_draws": [k for k in m0.known_draws
                                                     if k[1:] != ("117.821", 7)]}), bs

    monkeypatch.setattr(manifest, "load_bindings", unknown)
    with pytest.raises(SimError, match="no known draw"):
        reference_draws(sim_store.path, _bindings(sim_store))


def test_scenario_days_are_those_the_bindings_version_is_in_force(sim_store):  # noqa: F811
    from datetime import date

    from tests.store.units_fixtures import DOC_117_NEW, DOC_117_OLD

    days = st._scenario_days(sim_store.path, sim_store.snapshot_id, DOC_117_NEW)
    assert days[0] == date(2026, 6, 27) and days[-1] == date(2026, 12, 31)
    assert len(days) == (date(2026, 12, 31) - date(2026, 6, 27)).days + 1
    # the older version (superseded on 2026-06-26) is in force on none of them (P31)
    assert st._scenario_days(sim_store.path, sim_store.snapshot_id, DOC_117_OLD) == []


def test_generation_is_deterministic_and_seeded(sim_store):  # noqa: F811
    one = b"".join(canonical(t) for t in generate_tasks(sim_store.path, _bindings(sim_store)))
    two = b"".join(canonical(t) for t in generate_tasks(sim_store.path, _bindings(sim_store)))
    other = b"".join(canonical(t) for t in generate_tasks(sim_store.path, _bindings(sim_store),
                                                          seed=SEED4 + 1))
    assert one == two and one != other


def test_sim_tasks_cli_writes_the_tasks_and_refuses_without_bindings(sim_store, tmp_path,  # noqa: F811
                                                                     capsys):
    assert cli.main(["sim", "tasks", "--gen", "--store", str(sim_store.path)]) == 0
    out = capsys.readouterr().out
    assert "18 task(s)" in out and "allow 3" in out
    path = st.TASKS_DIR / "tasks.jsonl"
    want = generate_tasks(sim_store.path, _bindings(sim_store))
    assert load_tasks() == want == load_tasks(path)
    assert path.read_bytes() == b"".join(canonical(t) for t in want)
    assert cli.main(["sim", "tasks", "--gen", "--store", str(sim_store.path)]) == 0  # same
    path.write_bytes(path.read_bytes()[:-1] + b" \n")
    assert cli.main(["sim", "tasks", "--gen", "--store", str(sim_store.path)]) == 2
    assert "holds other tasks" in capsys.readouterr().err
    assert cli.main(["sim", "tasks", "--gen", "--store", str(sim_store.path),
                     "--overwrite"]) == 0
    assert load_tasks() == want
    other = tmp_path / "elsewhere" / "t.jsonl"
    assert cli.main(["sim", "tasks", "--gen", "--store", str(sim_store.path), "--out",
                     str(other), "--bindings", _bindings(sim_store)]) == 0
    assert load_tasks(other) == want
    # a store without bindings: NO_BINDINGS, nothing written
    bare = make_units_store(tmp_path / "bare")
    capsys.readouterr()
    assert cli.main(["sim", "tasks", "--gen", "--store", str(bare.path), "--out",
                     str(tmp_path / "none.jsonl")]) == 2
    err = capsys.readouterr().err
    assert "NO_BINDINGS" in err and "no bindings for snapshot" in err
    assert not (tmp_path / "none.jsonl").exists()
    assert cli.main(["sim", "tasks", "--store", str(sim_store.path)]) == 2      # no --gen
    assert cli.main(["sim", "tasks", "--gen", "--store", str(tmp_path / "nowhere")]) == 2
    assert cli.main(["sim", "tasks", "--gen", "--store", str(sim_store.path), "--bindings",
                     "f" * 64]) == 2
