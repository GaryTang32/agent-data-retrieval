"""The scripted user (Phase 4 spec §13.2; P16, P33). The first message states the request in a
fixed template filled from the scenario. `answer(task, field)` answers a question from what the
scenario says the user knows:
- a field of `user_knows`: its value, and the fact the environment writes to the record with
  source `user` (every known field, `accepts_alternative` included, is written);
- a fact already in the initial record (the user filed it): its value, and nothing written
  (the record keeps its source `record`);
- anything else: "I don't know", and nothing written, so the fact stays missing.

A name the gate and `check_rules` report missing is asked as the user's field it maps to
(`tasks.USER_FIELD_OF`, the map the procedure runtime reads too, P53): `notice_minutes` is
answered as `notice_received_at`, and the fact is written under the record's name (pre-run
review C1)."""

from __future__ import annotations

from adr_eval.sim.tasks import USER_FIELD_OF, SimTask

__all__ = ["DONT_KNOW", "FIRST_MESSAGE", "USER_FIELD_OF", "answer", "first_message",
           "record_field"]

FIRST_MESSAGE = ("Request {id}: vessel {vessel} asks for an opening of {section} draw {draw} at "
                 "{requested_open_at}.")
DONT_KNOW = "I don't know"


def first_message(task: SimTask) -> str:
    return FIRST_MESSAGE.format(**task.request)


def _text(field: str, value) -> str:
    if field == "notice_received_at":
        return f"I gave notice at {value}."
    if field == "vessel_class":
        return f"The vessel class is {value}."
    if field == "accepts_alternative":
        return ("Yes, another time is acceptable." if value is True else
                "No, the opening has to be at the requested time.")
    return f"{field}: {value}."


def record_field(field: str) -> str:
    """The record's name of an asked `field`: a name of `USER_FIELD_OF` with a user field is
    that field (an alias); any other name is itself."""
    alias = USER_FIELD_OF.get(field)
    return alias if isinstance(alias, str) else field


def answer(task: SimTask, field: str) -> tuple[str, dict | None]:
    """(the user's answer, the fact to write `{"name", "value"}` or None) (module text)."""
    name = record_field(field)
    if name in task.user_knows:
        value = task.user_knows[name]
        return _text(name, value), {"name": name, "value": value}
    if name in task.record:
        return _text(name, task.record[name]["value"]), None
    return DONT_KNOW, None
