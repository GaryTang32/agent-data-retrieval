"""The tasks of `sim-drawbridge v0.1` (Phase 4 spec §13.1, §13.4; P16, P31, P33, P35, P37, P49;
preflight C4, C5; Task 19). No model call, no gate.

**Where the draws come from** (`reference_draws`). The bindings manifest (`load_bindings`,
which verifies every hash and sign-off) names the Phase 3 second-pass facts (`facts_id`) and
the agreement pairs `[section, Phase 3 draw, bindings' draw]` (C5): the draws whose bindings are
signed off and decide as the reference evaluator does on the B1 grid. The reference draw of each
pair is `reference.ref_draws` over those facts, keyed by its Phase 3 number; the task's request
targets the bindings' number, which must be one of the manifest's `known_draws` (P49).

**The task screen** (pre-run review I2). An agreement draw is eligible for tasks only when its
governing paragraphs (the section's lines that hold its Phase 3 parameter quotes) name no
phrase of `TASK_SCREEN`: a P47 restricted opening, a vessel-class exception, or a clearance or
height condition, none of which the DSL or the reference evaluator models. Excluded draws stay
in the agreement set for B1; `report` counts them per reason.

**The scenario** (§13.4). Six classes of three, drawn with `random.Random(seed)` (`SEED4`):
classes in `CLASSES` order, each class's draws rotated from a random start over the agreement
draws that can serve it (a draw may serve several classes, and one class several times).
A scenario date is drawn from the days after 2026-06-26 through 2026-12-31 on which the
bindings' 33 CFR 117 version is the one in force (P31; days on which a class cannot be placed
are drawn again). `as_of` is 05:30 on that day. Requested times are on quarter hours from 06:00
to 21:45, placed by class with the reference evaluator's own window rule (`ref_in_window`):

- **allow**: outside every closed window; the record holds the vessel class, and enough
  notice in tasks 2 and 3; in task 1 (on a draw with a threshold when there is one) only the
  user knows the notice.
- **reschedule**: inside a closed window; notice (enough) and vessel class in the record; the
  user accepts another time.
- **deny-closed**: inside a closed window; notice (enough) and vessel class in the record; the
  user accepts no other time.
- **deny-notice**: outside every closed window, on a draw with a threshold; the record holds the
  vessel class (P37); only the user knows the notice, short by at least an hour.
- **escalate**: outside every closed window, on a draw with a threshold; the record holds the
  vessel class (P37); nobody knows the notice.
- **emergency**: inside a closed window; the record holds nothing but the registry, an approved
  local procedure that does not conflict; only the user knows the vessel class,
  `public_safety`.

"Enough" notice is the threshold plus one to twelve hours; notice is always received by `as_of`
(so a deny-notice request is at most `threshold - 1 h` after `as_of`, and a draw with a
threshold under two hours cannot serve that class). Vessel classes of the record are
`commercial` or `recreational`. Every task's user also knows `accepts_alternative`.

**Expected state and `reference`** come only from `reference.ref_decide` and
`reference.ref_next_allowed` (never the gate or the bindings), on the **full record**: the
initial record, the `local_procedure_conflict` fact the environment writes from the registry
(`registry_fact`, P37) and every fact the user knows (`FACT_FIELDS`) with source `user`.
`reference` is the decision on an opening at the requested time; each class needs its outcome
(allow, deny, deny, deny, escalate, allow), else the placement is drawn again. Openings:
allow and emergency at the requested time; reschedule at `ref_next_allowed`. Denials and
escalations: the request id.

**Reschedule tasks and the two `next_allowed` definitions** (the Task 16 caveat). For a draw
whose enrichment basis is `advance_notice`, the gate's basis needs notice while the reference's
on-signal reading does not, so with notice unknown or short the two scans differ. Reschedule
tasks are placed so that they cannot: notice is in the initial record and is enough at the
requested time, so it is enough at every later minute; the vessel class is a non-emergency one.
Then both definitions give the first minute after the request outside every closed window.

**The bindings a task was drawn from** are named in its `reference` (`bindings_id`; the nine
keys of §13.4 stay exact): the environment refuses to run a task on a store whose
`bindings/HEAD` is another set, and the monitor refuses a log of other bindings (fix round 1).

Each line of `tasks.jsonl` is `canonical(task)`: `SimTask.model_dump(by_alias=True)` in
canonical JSON (sorted keys, no padding, UTF-8, one newline).
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from adr_eval.corpora import REPO_ROOT
from adr_store.bindings.dsl import Window
from adr_store.bindings.enrich import section_key
from adr_store.bindings.facts import EMERGENCY_CLASSES
from adr_store.bindings.reference import RefDraw, ref_decide, ref_in_window, ref_next_allowed

__all__ = ["AS_OF_TIME", "CLASSES", "FACT_FIELDS", "FIRST_DATE", "LAST_DATE", "PER_CLASS",
           "REQUEST_ID", "SEED4", "TASKS_DIR", "USER_FIELD_OF", "SimError", "SimTask",
           "canonical",
           "TASK_SCREEN", "draw_screen", "full_record", "generate_tasks", "governing_text",
           "load_tasks", "ref_from_dict", "ref_to_dict", "reference_draws", "registry_fact",
           "screen_reasons", "write_tasks"]

TASKS_DIR = REPO_ROOT / "golden" / "sim-drawbridge" / "v0.1"
CLASSES = ("allow", "reschedule", "deny-closed", "deny-notice", "escalate", "emergency")
PER_CLASS = 3
SEED4 = 20261121
FIRST_DATE = date(2026, 6, 27)          # after 2026-06-26: the newest 117 version (P31)
LAST_DATE = date(2026, 12, 31)
AS_OF_TIME = time(5, 30)
EARLIEST, LATEST, STEP = 6 * 60, 21 * 60 + 45, 15          # requested times, minutes of day
REQUEST_ID = "r1"
FACT_FIELDS = ("notice_received_at", "vessel_class", "accepts_alternative")
# The user's field of each fact the gate and `check_rules` can name missing (P53): the derived
# `notice_minutes` is asked as `notice_received_at`; the registry's fact is the desk's, nobody's
# to tell. One map, imported by the scripted user (`user.answer` takes a name here as an alias
# of its field) and by the procedure runtime (s9 of `desk-request@1` names it, `ASK_MAPS`), so
# the two cannot drift (pre-run review C1).
USER_FIELD_OF: dict[str, str | None] = {"notice_minutes": "notice_received_at",
                                        "vessel_class": "vessel_class",
                                        "local_procedure_conflict": None}
RECORD_CLASSES = ("commercial", "recreational")
EMERGENCY_VESSEL = "public_safety"           # § 117.31(b)(1); one of EMERGENCY_CLASSES
assert EMERGENCY_VESSEL in EMERGENCY_CLASSES
VESSELS = ("Osprey", "Cape Lookout", "Nantucket Belle", "Sea Robin", "Miss Hatteras",
           "Northern Light", "Pamlico Star", "Blue Heron")
# The task screen (pre-run review I2, `whole-branch-review-prerun.md`): a draw whose governing
# paragraphs (the full text of the section's paragraphs, its lines, that hold the draw's
# Phase 3 parameter quotes) name any of these, matched as whole words and case-insensitively,
# is decided by something the DSL and the reference evaluator do not model, so a task on it
# could carry an expected state the regulation contradicts. Such draws stay in the agreement
# set (B1's grid); only task eligibility drops them. "need not open" is not here: it is the
# closed-period phrase the DSL models (`need_not_open`), held by 35 of the 56 simple
# closed-window draws (controller ruling in the pre-run fix round).
TASK_SCREEN: dict[str, tuple[str, ...]] = {
    # the restricted openings of P47 ("the draw need open only on the hour")
    "restricted_opening": ("need open", "need be opened", "need only open",
                           "need only be opened"),
    # exceptions for a vessel class the tasks do not model (§ 117.305(a), § 117.315(a))
    "vessel_class": ("tug", "tugs", "towboat", "public vessel", "vessels of the United States",
                     "commercial vessel", "pleasure craft", "with a tow", "in tow"),
    # conditions on clearance or height (§ 117.949: notice above 50 feet of clearance)
    "clearance": ("vertical clearance", "clearance of", "feet or more", "height"),
}
_SCREEN_RX = {reason: [re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, p.split()))
                                  + r"(?!\w)", re.IGNORECASE) for p in phrases]
              for reason, phrases in TASK_SCREEN.items()}
OUTCOME = {"allow": "allow", "reschedule": "deny", "deny-closed": "deny", "deny-notice": "deny",
           "escalate": "escalate", "emergency": "allow"}
ATTEMPTS = 400


class SimError(ValueError):
    """The tasks cannot be generated (no bindings, no agreement draw, a class no draw serves)."""


class SimTask(BaseModel):
    """One task in the §13.4 format, exactly (`class` is a Python keyword: `class_`)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    task_id: str
    class_: str = Field(alias="class")
    as_of: str
    request: dict
    record: dict
    user_knows: dict
    registry: list[dict]
    expected_state: dict
    reference: dict


def canonical(task: SimTask) -> bytes:
    """The stored line of `task`: canonical JSON of `model_dump(by_alias=True)`."""
    return (json.dumps(task.model_dump(by_alias=True, mode="json"), sort_keys=True,
                       separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def write_tasks(tasks: list[SimTask], path: Path) -> bytes:
    """Write `tasks` to `path` (parents made); the bytes written."""
    data = b"".join(canonical(t) for t in tasks)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def load_tasks(path: Path | None = None) -> list[SimTask]:
    """The tasks of `path` (default `TASKS_DIR / "tasks.jsonl"`, read at call time)."""
    path = Path(path) if path is not None else TASKS_DIR / "tasks.jsonl"
    return [SimTask.model_validate_json(line) for line in path.read_bytes().splitlines()
            if line.strip()]


# -- the reference draws ---------------------------------------------------------------------------

def ref_to_dict(r: RefDraw) -> dict:
    return {"section": r.section, "draw": r.draw, "bridge": r.bridge,
            "opens_on_signal": r.opens_on_signal, "notice_hours": r.notice_hours,
            "closed": [w.model_dump(mode="json") for w in r.closed], "unit": r.unit,
            "section_draws": [list(x) for x in r.section_draws]}


def ref_from_dict(d: dict) -> RefDraw:
    return RefDraw(section=d["section"], draw=d["draw"], bridge=d["bridge"],
                   opens_on_signal=d["opens_on_signal"], notice_hours=d["notice_hours"],
                   closed=tuple(Window.model_validate(w) for w in d["closed"]),
                   unit=d["unit"], section_draws=tuple(tuple(x) for x in d["section_draws"]))


def reference_draws(store_path: Path, bindings_id: str):
    """(the bindings manifest, {(section, bindings' draw): RefDraw} over its agreement pairs,
    the 33 CFR 117 document of those draws). BindingsError for bindings that do not load;
    SimError for a manifest without facts, a pair the facts do not give or a draw outside the
    known draws (P49)."""
    from adr_store.bindings.manifest import load_bindings
    from adr_store.bindings.reference import ref_draws
    from adr_store.store import Store
    from adr_store.tables import extract as ex

    m, bindings = load_bindings(store_path, bindings_id)
    if m.facts_id is None:
        raise SimError(f"bindings {bindings_id[:12]} name no Phase 3 facts (facts_id)")
    keys = {(s, d) for s, _, d in m.agreement_pairs}
    docs = sorted({b.doc_id for b in bindings
                   if (b.target["selector"]["section"], b.target["selector"]["draw"]) in keys})
    if len(docs) > 1:
        raise SimError(f"the agreement draws are bindings of {len(docs)} documents")
    if not docs:
        return m, {}, None
    doc = docs[0]
    refs = ref_draws(ex.load_facts(store_path, m.facts_id), ex.units(Store.open(store_path)),
                     doc_id=doc)
    known = {(d, s, n) for d, s, n in m.known_draws}
    out: dict[tuple[str, int], RefDraw] = {}
    for section, p3, draw in m.agreement_pairs:
        if (section, p3) not in refs:
            raise SimError(f"the facts give no simple reference draw § {section} draw {p3}")
        if (doc, section, draw) not in known:
            raise SimError(f"§ {section} draw {draw} is no known draw (P49)")
        out[(section, draw)] = refs[(section, p3)]
    return m, out, doc


def _scenario_days(store_path: Path, snapshot: str, doc: str) -> list[date]:
    """The days from FIRST_DATE through LAST_DATE on which `doc` is the one 33 CFR 117 version
    in force (P31)."""
    from adr_store.applicability import Filters, admits, load_overlay

    overlay = load_overlay(store_path, snapshot)
    if overlay is None:
        raise SimError(f"no applicability overlay for snapshot {snapshot[:12]}")
    envs = {d: e for d, e in overlay.records.items() if e.chain_id == "ecfr:33:117"}
    out, day = [], FIRST_DATE
    while day <= LAST_DATE:
        f = Filters(as_of=day)
        if [d for d, e in envs.items() if admits(e, f)] == [doc]:
            out.append(day)
        day += timedelta(days=1)
    return out


# -- the task screen (pre-run review I2) -----------------------------------------------------------

def screen_reasons(text: str) -> tuple[str, ...]:
    """The `TASK_SCREEN` reasons whose phrases occur in `text` (whole words, any case), in
    `TASK_SCREEN` order."""
    return tuple(r for r, rxs in _SCREEN_RX.items() if any(rx.search(text) for rx in rxs))


def governing_text(section_text: str, draw: dict) -> str:
    """The full text of the paragraphs (lines) of `section_text` that hold a quote of the
    draw's parameters (`draw`: field -> `tables.extract.Value` with offsets), in order."""
    spans = [(v.start, v.end) for v in draw.values()
             if getattr(v, "start", None) is not None and v.end is not None]
    out, at = [], 0
    for line in section_text.split("\n"):
        end = at + len(line)
        if any(a < end and b > at for a, b in spans):
            out.append(line)
        at = end + 1
    return "\n".join(out)


def draw_screen(facts: list, sections: list, doc_id: str | None) -> dict[tuple[str, int], tuple]:
    """{(section, Phase 3 draw): the `TASK_SCREEN` reasons of its governing paragraphs} for
    every second-pass draw of the sections of `doc_id` (`reference.ref_draws`' numbering)."""
    from adr_store.bindings.reference import _sections

    return {(section, n): screen_reasons(governing_text(u.text, d))
            for section, u, f in _sections(facts, sections, doc_id)
            for n, d in enumerate(f.draws, 1)}


def _screened(store_path: Path, m, doc: str) -> dict[tuple[str, int], tuple]:
    """The screen of the agreement draws, keyed by (section, bindings' draw)."""
    from adr_store.store import Store
    from adr_store.tables import extract as ex

    screen = draw_screen(ex.load_facts(store_path, m.facts_id), ex.units(Store.open(store_path)),
                         doc)
    return {(section, draw): screen.get((section, p3), ())
            for section, p3, draw in m.agreement_pairs}


# -- facts -----------------------------------------------------------------------------------------

def registry_fact(task: SimTask) -> dict:
    """The `local_procedure_conflict` fact the environment writes from the registry (P37):
    True when an approved local procedure of the request's draw conflicts with an opening,
    else False (with no approved procedure nothing can conflict)."""
    req = task.request
    conflict = any(e.get("conflicts_with_opening") is True for e in task.registry
                   if (e.get("section"), e.get("draw")) == (req["section"], req["draw"]))
    return {"value": conflict, "source": "record"}


def full_record(task: SimTask) -> dict:
    """The record once the user has told everything they know: the initial record, the
    registry's fact and each known fact with source `user` (module text)."""
    out = {k: dict(v) for k, v in task.record.items()}
    out["local_procedure_conflict"] = registry_fact(task)
    for name, value in sorted(task.user_knows.items()):
        if name in FACT_FIELDS:
            out[name] = {"value": value, "source": "user"}
    return out


# -- placing a scenario ----------------------------------------------------------------------------

def _closed(r: RefDraw, at: datetime) -> bool:
    return any(ref_in_window(w, at.hour * 60 + at.minute, at.date()) for w in r.closed)


def _times(day: date) -> list[datetime]:
    start = datetime.combine(day, time())
    return [start + timedelta(minutes=m) for m in range(EARLIEST, LATEST + 1, STEP)]


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")


def _fact(value: Any) -> dict:
    return {"value": value, "source": "record"}


def _enough_notice(rng: random.Random, r: RefDraw, at: datetime, as_of: datetime) -> str:
    """A notice time giving the threshold plus one to twelve hours, received by `as_of`."""
    minutes = 60 * (r.notice_hours or 0) + rng.randrange(60, 12 * 60 + 1, STEP)
    return _iso(min(at - timedelta(minutes=minutes), as_of - timedelta(minutes=30)))


def _place(cls: str, i: int, rng: random.Random, r: RefDraw, day: date) -> dict | None:
    """(requested time, record, user_knows, registry) of one scenario on `day`, or None when
    the class cannot be placed on it (module text)."""
    as_of = datetime.combine(day, AS_OF_TIME)
    times = _times(day)
    inside = [t for t in times if _closed(r, t)]
    outside = [t for t in times if not _closed(r, t)]
    vessel = rng.choice(RECORD_CLASSES)
    knows: dict[str, Any] = {"accepts_alternative": cls == "reschedule"}
    registry: list[dict] = []
    if cls in ("reschedule", "deny-closed", "emergency"):
        if not inside:
            return None
        at = rng.choice(inside)
    elif cls == "deny-notice":
        cap = 60 * (r.notice_hours - 1)
        outside = [t for t in outside if t <= as_of + timedelta(minutes=cap)]
        if not outside:
            return None
        at = rng.choice(outside)
    else:
        if not outside:
            return None
        at = rng.choice(outside)
    record: dict[str, dict] = {}
    if cls == "allow":
        notice = _enough_notice(rng, r, at, as_of)
        if i == 0:
            knows["notice_received_at"] = notice
        else:
            record["notice_received_at"] = _fact(notice)
        record["vessel_class"] = _fact(vessel)
    elif cls in ("reschedule", "deny-closed"):
        record["notice_received_at"] = _fact(_enough_notice(rng, r, at, as_of))
        record["vessel_class"] = _fact(vessel)
    elif cls == "deny-notice":
        least = -(-int((at - as_of).total_seconds() // 60) // STEP) * STEP   # received by as_of
        notice = rng.randrange(max(least, STEP), 60 * (r.notice_hours - 1) + 1, STEP)
        knows["notice_received_at"] = _iso(at - timedelta(minutes=notice))
        record["vessel_class"] = _fact(vessel)
    elif cls == "escalate":
        record["vessel_class"] = _fact(vessel)
    else:                                                      # emergency
        knows["vessel_class"] = EMERGENCY_VESSEL
        registry.append({"procedure_id": f"LEP-{r.section}-{rng.randrange(1, 100):02d}",
                         "section": None, "draw": None, "approved": True,
                         "approved_by": "Captain of the Port",
                         "conflicts_with_opening": False})
    return {"at": at, "record": record, "knows": knows, "registry": registry}


def _eligible(cls: str, r: RefDraw) -> bool:
    if cls in ("reschedule", "deny-closed", "emergency"):
        return bool(r.closed)
    if cls == "deny-notice":
        return r.notice_hours is not None and r.notice_hours >= 2
    if cls == "escalate":
        return r.notice_hours is not None
    return True


def _task(cls: str, i: int, key: tuple[str, int], r: RefDraw, placed: dict, day: date,
          rng: random.Random, bindings_id: str) -> SimTask | None:
    section, draw = key
    at = placed["at"]
    registry = [{**e, "section": section, "draw": draw} for e in placed["registry"]]
    request = {"id": REQUEST_ID, "vessel": rng.choice(VESSELS), "section": section,
               "draw": draw, "requested_open_at": _iso(at)}
    draft = SimTask(task_id=f"sim-{cls}-{i + 1:02d}", class_=cls,
                    as_of=_iso(datetime.combine(day, AS_OF_TIME)), request=request,
                    record=placed["record"], user_knows=placed["knows"], registry=registry,
                    expected_state={}, reference={})
    record = full_record(draft)
    ref = ref_decide(r, at, record)
    if ref.outcome != OUTCOME[cls]:
        return None
    openings, denials, escalations = [], [], []
    if cls in ("allow", "emergency"):
        openings.append(at)
    elif cls == "reschedule":
        nxt = ref_next_allowed(r, at, record)
        if nxt is None:
            return None
        openings.append(nxt)
    elif cls == "escalate":
        escalations.append(REQUEST_ID)
    else:
        denials.append(REQUEST_ID)
    expected = {"openings": [{"request": REQUEST_ID, "section": section, "draw": draw,
                              "open_at": _iso(t), "status": "active"} for t in openings],
                "denials": denials, "escalations": escalations}
    reference = {"outcome": ref.outcome, "denying_sections": sorted(ref.denying_sections),
                 "missing_facts": list(ref.missing), "bindings_id": bindings_id}
    return draft.model_copy(update={"expected_state": expected, "reference": reference})


def generate_tasks(store_path: Path, bindings_id: str, seed: int = SEED4, *,
                   report: dict | None = None) -> list[SimTask]:
    """The 18 tasks of `sim-drawbridge v0.1` from the bindings `bindings_id` of the store
    (module text), over the agreement draws the task screen keeps (`TASK_SCREEN`); `report`,
    when given, receives {"agreement_draws", "eligible", "excluded": {reason: draws}} (a draw
    counts under each reason it hits). BindingsError for bindings that do not load; SimError
    when the tasks cannot be made."""
    m, refs, doc = reference_draws(store_path, bindings_id)
    if not refs:
        raise SimError(f"bindings {bindings_id[:12]} have no agreement draw to draw tasks from")
    screen = _screened(store_path, m, doc)
    excluded = Counter(r for k in refs for r in screen.get(k, ()))
    if report is not None:
        report.update({"agreement_draws": len(refs),
                       "eligible": sum(not screen.get(k) for k in refs),
                       "excluded": {r: excluded[r] for r in TASK_SCREEN if excluded[r]}})
    refs = {k: r for k, r in refs.items() if not screen.get(k)}
    if not refs:
        raise SimError(f"the task screen excludes every agreement draw of bindings "
                       f"{bindings_id[:12]} ({dict(excluded)})")
    days = _scenario_days(store_path, m.snapshot, doc)
    if not days:
        raise SimError("the bindings' 33 CFR 117 version is in force on no scenario day after "
                       "2026-06-26")
    rng = random.Random(seed)
    keys = sorted(refs, key=lambda k: (section_key(k[0]), k[1]))
    tasks: list[SimTask] = []
    for cls in CLASSES:
        eligible = [k for k in keys if _eligible(cls, refs[k])]
        if not eligible:
            raise SimError(f"no agreement draw the task screen keeps can serve class {cls}")
        start = rng.randrange(len(eligible))
        picks = [eligible[(start + i) % len(eligible)] for i in range(PER_CLASS)]
        if cls == "allow":       # the task whose notice only the user knows: a threshold draw
            with_notice = [k for k in eligible if refs[k].notice_hours is not None]
            if with_notice and refs[picks[0]].notice_hours is None:
                picks[0] = with_notice[rng.randrange(len(with_notice))]
        for i, key in enumerate(picks):
            for _ in range(ATTEMPTS):
                day = rng.choice(days)
                placed = _place(cls, i, rng, refs[key], day)
                task = placed and _task(cls, i, key, refs[key], placed, day, rng, bindings_id)
                if task is not None:
                    tasks.append(task)
                    break
            else:
                raise SimError(f"class {cls}: § {key[0]} draw {key[1]} could not be placed in "
                               f"{ATTEMPTS} attempts")
    return tasks
