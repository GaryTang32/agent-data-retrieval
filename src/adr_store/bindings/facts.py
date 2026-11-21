"""The gate's fact module (Phase 4 spec §12.1, builder note 15): federal holidays computed by
rule, and the facts of a request derived from `open_at` and the request record.

- **Holidays (5 U.S.C. 6103(a)):** New Year's Day (1 January), Martin Luther King Jr. Day (third
  Monday of January, from 1986), Washington's Birthday (third Monday of February), Memorial Day
  (last Monday of May), Juneteenth (19 June, from 2021), Independence Day (4 July), Labor Day
  (first Monday of September), Columbus Day (second Monday of October), Veterans Day
  (11 November), Thanksgiving Day (fourth Thursday of November) and Christmas Day (25 December).
  A fixed-date holiday on a Saturday is observed on the Friday before, and on a Sunday on the
  Monday after (6103(b), Executive Order 11582). Both the legal and the observed date count.
  `federal_holidays(year)` holds every such date that falls in `year`, so 2027 holds
  2027-12-31, the observed New Year's Day of 2028. Inauguration Day (6103(c)) is excluded: it
  applies only in the Washington area. Years before the 1971 Monday-holiday rules are refused.
  No calendar file and no rule parameter: the gate and the reference evaluator share this
  module and it keeps the reference independent of the bindings.
- **Facts.** `open_at` (a naive datetime, the simulated local time) gives `open_at` (ISO),
  `minute` (of the day), `weekday`, `month_day` ("MM-DD") and `federal_holiday`. From the record
  (`{fact: {"value", "source", ...}}`; values only are read): `notice_minutes` = `open_at` −
  `notice_received_at` in whole minutes, rounded down (negative when the notice came after the
  requested time), `vessel_class` (one of `VESSEL_CLASSES`) and `local_procedure_conflict`
  (bool). A fact missing from the record, or null, is absent from the facts, so every
  comparison on it is Unknown. A malformed value (wrong type, unknown class, an unparseable or
  zoned time) is a ValueError: the caller fails closed.
"""

from __future__ import annotations

import functools
from datetime import date, datetime, timedelta
from typing import Any

from adr_store.bindings.dsl import DAYS

VESSEL_CLASSES = ("commercial", "recreational", "public_safety", "distress", "rescue_salvage",
                  "severe_weather_shelter")
EMERGENCY_CLASSES = ("public_safety", "distress", "rescue_salvage", "severe_weather_shelter")
FIRST_YEAR = 1971   # the Uniform Monday Holiday Act's rules take effect
OBSERVED = " (observed)"


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The `n`th `weekday` (Monday 0) of the month; `n` = -1 for the last."""
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    last = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _legal(year: int) -> list[tuple[date, str, bool]]:
    """(legal date, name, fixed date?) of each holiday of `year`."""
    out = [(date(year, 1, 1), "New Year's Day", True)]
    if year >= 1986:
        out.append((_nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day", False))
    out += [(_nth_weekday(year, 2, 0, 3), "Washington's Birthday", False),
            (_nth_weekday(year, 5, 0, -1), "Memorial Day", False)]
    if year >= 2021:
        out.append((date(year, 6, 19), "Juneteenth", True))
    out += [(date(year, 7, 4), "Independence Day", True),
            (_nth_weekday(year, 9, 0, 1), "Labor Day", False),
            (_nth_weekday(year, 10, 0, 2), "Columbus Day", False),
            (date(year, 11, 11), "Veterans Day", True),
            (_nth_weekday(year, 11, 3, 4), "Thanksgiving Day", False),
            (date(year, 12, 25), "Christmas Day", True)]
    return out


@functools.lru_cache(maxsize=256)
def _holidays(year: int) -> tuple[tuple[date, str], ...]:
    if year < FIRST_YEAR:
        raise ValueError(f"federal holidays before {FIRST_YEAR} are not modelled")
    found: dict[date, str] = {}
    for y in (year, year + 1):            # 1 January of next year may be observed this year
        for d, name, fixed in _legal(y):
            found.setdefault(d, name)
            if fixed and d.weekday() in (5, 6):
                found.setdefault(d + timedelta(days=-1 if d.weekday() == 5 else 1),
                                 name + OBSERVED)
    return tuple(sorted((d, n) for d, n in found.items() if d.year == year))


def federal_holidays(year: int) -> dict[date, str]:
    """Every legal or observed federal holiday date in `year`, with its name ("… (observed)"
    for an observed date)."""
    return dict(_holidays(year))


def is_federal_holiday(d: date) -> bool:
    return any(h == d for h, _ in _holidays(d.year))


def _value(record: dict[str, dict], fact: str) -> Any:
    """The fact's value in the record, None when missing or null."""
    if fact not in record:
        return None
    entry = record[fact]
    if not isinstance(entry, dict) or "value" not in entry:
        raise ValueError(f"record fact {fact!r} is not an object with a value")
    return entry["value"]


def derive_facts(open_at: datetime, record: dict[str, dict]) -> dict[str, Any]:
    """The facts of an opening at `open_at` under the request `record` (see the module text)."""
    if not isinstance(open_at, datetime) or open_at.tzinfo is not None:
        raise ValueError(f"open_at must be a naive datetime, got {open_at!r}")
    day = open_at.date()
    facts: dict[str, Any] = {
        "open_at": open_at.isoformat(), "minute": open_at.hour * 60 + open_at.minute,
        "weekday": DAYS[open_at.weekday()], "month_day": f"{open_at.month:02d}-{open_at.day:02d}",
        "federal_holiday": is_federal_holiday(day)}
    received = _value(record, "notice_received_at")
    if received is not None:
        try:
            at = datetime.fromisoformat(received) if isinstance(received, str) else None
        except ValueError:
            at = None
        if at is None or at.tzinfo is not None:
            raise ValueError(f"notice_received_at {received!r} is not a naive ISO datetime")
        facts["notice_minutes"] = (open_at - at) // timedelta(minutes=1)
    vessel = _value(record, "vessel_class")
    if vessel is not None:
        if vessel not in VESSEL_CLASSES:
            raise ValueError(f"vessel_class {vessel!r} is not one of {VESSEL_CLASSES}")
        facts["vessel_class"] = vessel
    conflict = _value(record, "local_procedure_conflict")
    if conflict is not None:
        if type(conflict) is not bool:
            raise ValueError(f"local_procedure_conflict {conflict!r} is not a bool")
        facts["local_procedure_conflict"] = conflict
    return facts
