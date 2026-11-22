"""The scripted user (Phase 4 spec §13.2; P16, P33). The first message states the request in a
fixed template filled from the scenario. `answer(task, field)` answers a question from what the
scenario says the user knows:
- a field of `user_knows`: its value, and the fact the environment writes to the record with
  source `user` (every known field, `accepts_alternative` included, is written);
- a fact already in the initial record (the user filed it): its value, and nothing written
  (the record keeps its source `record`);
- anything else: "I don't know", and nothing written, so the fact stays missing."""

from __future__ import annotations

from adr_eval.sim.tasks import SimTask

__all__ = ["DONT_KNOW", "FIRST_MESSAGE", "answer", "first_message"]

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


def answer(task: SimTask, field: str) -> tuple[str, dict | None]:
    """(the user's answer, the fact to write `{"name", "value"}` or None) (module text)."""
    if field in task.user_knows:
        value = task.user_knows[field]
        return _text(field, value), {"name": field, "value": value}
    if field in task.record:
        return _text(field, task.record[field]["value"]), None
    return DONT_KNOW, None
