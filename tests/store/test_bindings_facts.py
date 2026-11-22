"""The gate's fact module: federal holidays by the rules of 5 U.S.C. 6103 (legal and observed
dates, no calendar file, Inauguration Day excluded) and the facts derived from `open_at` and the
request record (Phase 4 spec §12.1; plan Task 14, Review Focus 3, builder note 15). Every
expected date below was read off a calendar, not computed by the code under test."""

from datetime import UTC, date, datetime, timedelta

import pytest

from adr_store.bindings.dsl import Tri, evaluate
from adr_store.bindings.facts import (
    EMERGENCY_CLASSES,
    VESSEL_CLASSES,
    derive_facts,
    federal_holidays,
    is_federal_holiday,
)


@pytest.mark.parametrize("d", ["2027-12-31", "2026-07-03", "2027-12-24", "2027-06-18",
                               "2026-11-26", "2026-05-25", "2026-07-04"])
def test_observed_and_legal_federal_holidays(d):                    # Review Focus 3
    assert is_federal_holiday(date.fromisoformat(d))


def test_ordinary_days_are_not_holidays():
    assert not is_federal_holiday(date(2026, 7, 2)) and not is_federal_holiday(date(2027, 12, 30))


def test_the_2026_calendar_exactly():
    assert federal_holidays(2026) == {
        date(2026, 1, 1): "New Year's Day",
        date(2026, 1, 19): "Martin Luther King Jr. Day",          # third Monday of January
        date(2026, 2, 16): "Washington's Birthday",               # third Monday of February
        date(2026, 5, 25): "Memorial Day",                        # last Monday of May
        date(2026, 6, 19): "Juneteenth",                          # a Friday: no other date
        date(2026, 7, 3): "Independence Day (observed)",          # 4 July is a Saturday
        date(2026, 7, 4): "Independence Day",
        date(2026, 9, 7): "Labor Day",                            # first Monday of September
        date(2026, 10, 12): "Columbus Day",                       # second Monday of October
        date(2026, 11, 11): "Veterans Day",
        date(2026, 11, 26): "Thanksgiving Day",                   # fourth Thursday of November
        date(2026, 12, 25): "Christmas Day",
    }


def test_new_year_on_a_saturday_is_observed_the_previous_december():
    # 2028-01-01 is a Saturday: observed Friday 2027-12-31, which belongs to the 2027 calendar
    assert federal_holidays(2027)[date(2027, 12, 31)] == "New Year's Day (observed)"
    assert federal_holidays(2028)[date(2028, 1, 1)] == "New Year's Day"
    assert date(2027, 12, 31) not in federal_holidays(2028)
    assert is_federal_holiday(date(2027, 12, 31)) and is_federal_holiday(date(2028, 1, 1))
    assert not is_federal_holiday(date(2028, 1, 3))           # no Monday as well
    # the same in 2033 (2033-01-01 is a Saturday)
    assert is_federal_holiday(date(2032, 12, 31)) and is_federal_holiday(date(2033, 1, 1))


def test_saturday_holidays_move_to_the_friday_before():
    # Christmas 2027 and Veterans Day 2028 fall on Saturdays
    assert is_federal_holiday(date(2027, 12, 25)) and is_federal_holiday(date(2027, 12, 24))
    assert not is_federal_holiday(date(2027, 12, 27))
    assert is_federal_holiday(date(2028, 11, 11)) and is_federal_holiday(date(2028, 11, 10))
    assert not is_federal_holiday(date(2028, 11, 13))


def test_sunday_holidays_move_to_the_monday_after():
    # Christmas 2022 and New Year's Day 2023 fall on Sundays
    assert is_federal_holiday(date(2022, 12, 25)) and is_federal_holiday(date(2022, 12, 26))
    assert not is_federal_holiday(date(2022, 12, 23))
    assert federal_holidays(2023)[date(2023, 1, 2)] == "New Year's Day (observed)"
    assert is_federal_holiday(date(2023, 1, 1)) and not is_federal_holiday(date(2022, 12, 30))


def test_juneteenth_on_a_weekend():
    # 2027-06-19 is a Saturday (observed Friday the 18th), 2022-06-19 a Sunday (Monday the 20th)
    assert federal_holidays(2027)[date(2027, 6, 18)] == "Juneteenth (observed)"
    assert is_federal_holiday(date(2027, 6, 19)) and not is_federal_holiday(date(2027, 6, 21))
    assert federal_holidays(2022)[date(2022, 6, 20)] == "Juneteenth (observed)"
    assert is_federal_holiday(date(2022, 6, 19)) and not is_federal_holiday(date(2022, 6, 17))
    # a holiday only from 2021 (first observed Friday 2021-06-18)
    assert is_federal_holiday(date(2021, 6, 18)) and is_federal_holiday(date(2021, 6, 19))
    assert not is_federal_holiday(date(2020, 6, 19))


def test_inauguration_day_is_not_a_holiday():                        # builder note 15
    # 20 January after a presidential election: a Friday (2017), a Wednesday (2021) and a
    # Saturday (2029, so neither it nor the Friday before is a holiday)
    for d in (date(2017, 1, 20), date(2021, 1, 20), date(2029, 1, 20), date(2029, 1, 19)):
        assert not is_federal_holiday(d), d
    assert all("Inauguration" not in name for y in (2021, 2025, 2029)
               for name in federal_holidays(y).values())


def test_nth_weekday_rules_in_other_years():
    assert federal_holidays(2027)[date(2027, 5, 31)] == "Memorial Day"   # May has 5 Mondays
    assert federal_holidays(2029)[date(2029, 11, 22)] == "Thanksgiving Day"
    assert not is_federal_holiday(date(2027, 5, 24))
    assert not is_federal_holiday(date(2029, 11, 29))


def test_every_year_has_eleven_holidays_and_dates_stay_in_the_year():
    for y in range(2021, 2041):
        hs = federal_holidays(y)
        assert all(d.year == y for d in hs)
        assert sum(1 for n in hs.values() if not n.endswith("(observed)")) == 11
        assert all(d.weekday() < 5 for d, n in hs.items() if n.endswith("(observed)"))
        assert is_federal_holiday(date(y, 12, 25))


def test_years_before_1978_are_refused():
    # 1971-1977 kept Veterans Day on the fourth Monday of October: out of scope
    for y in (1970, 1975, 1977):
        with pytest.raises(ValueError):
            federal_holidays(y)
        with pytest.raises(ValueError):
            is_federal_holiday(date(y, 11, 11))
    assert federal_holidays(1978)[date(1978, 11, 10)] == "Veterans Day (observed)"  # a Saturday
    assert date(1978, 1, 16) not in federal_holidays(1978)       # no MLK Day before 1986


def test_federal_holidays_returns_a_fresh_dict():
    federal_holidays(2026).clear()
    assert len(federal_holidays(2026)) == 12


# -- derive_facts ----------------------------------------------------------------------------

def test_derive_facts_from_the_record():
    f = derive_facts(datetime(2026, 8, 14, 9, 30),
                     {"notice_received_at": {"value": "2026-08-13T18:00:00", "source": "record"}})
    assert (f["minute"], f["weekday"], f["month_day"], f["notice_minutes"]) == (570, "Fri",
                                                                                 "08-14", 930)
    assert "vessel_class" not in f


def test_derive_facts_every_key():
    rec = {"notice_received_at": {"value": "2026-07-01T06:15:30", "source": "user", "seq": 2},
           "vessel_class": {"value": "distress", "source": "user", "seq": 3},
           "local_procedure_conflict": {"value": False, "source": "record"},
           "accepts_alternative": {"value": True, "source": "user"}}
    f = derive_facts(datetime(2026, 7, 3, 7, 0, 59), rec)
    assert f == {"open_at": "2026-07-03T07:00:59", "minute": 420, "weekday": "Fri",
                 "month_day": "07-03", "federal_holiday": True,
                 "notice_minutes": (2 * 24 * 60) + 45, "vessel_class": "distress",
                 "local_procedure_conflict": False}


def test_absent_and_null_record_facts_stay_absent():
    f = derive_facts(datetime(2026, 8, 10, 0, 0), {"vessel_class": {"value": None,
                                                                    "source": "record"}})
    assert f == {"open_at": "2026-08-10T00:00:00", "minute": 0, "weekday": "Mon",
                 "month_day": "08-10", "federal_holiday": False}
    assert evaluate({"cmp": ["notice_minutes", ">=", 240]}, f) is Tri.U
    assert evaluate({"in": ["vessel_class", list(EMERGENCY_CLASSES)]}, f) is Tri.U


def test_notice_minutes_floors_and_can_be_negative():
    at = datetime(2026, 8, 14, 9, 30)
    rec = {"notice_received_at": {"value": "2026-08-14T05:30:01", "source": "record"}}
    assert derive_facts(at, rec)["notice_minutes"] == 239            # 3 h 59 min 59 s
    rec = {"notice_received_at": {"value": "2026-08-14T09:31:00", "source": "record"}}
    assert derive_facts(at, rec)["notice_minutes"] == -1             # given after the time


@pytest.mark.parametrize("record", [
    {"notice_received_at": {"value": "yesterday", "source": "record"}},
    {"notice_received_at": {"value": "2026-08-13T18:00:00+00:00", "source": "record"}},
    {"notice_received_at": {"value": 1755100000, "source": "record"}},
    {"notice_received_at": {"value": "2026-08-13", "source": "record"}},          # no time
    {"notice_received_at": {"value": "20260813T180000", "source": "record"}},
    {"vessel_class": {"value": "battleship", "source": "user"}},
    {"vessel_class": {"value": ["distress"], "source": "user"}},
    {"local_procedure_conflict": {"value": "no", "source": "record"}},
    {"vessel_class": "distress"},
    {"vessel_class": {"source": "user"}},
])
def test_malformed_record_values_are_refused(record):
    with pytest.raises(ValueError):
        derive_facts(datetime(2026, 8, 14, 9, 30), record)


def test_open_at_must_be_a_naive_datetime():
    with pytest.raises(ValueError):
        derive_facts(datetime(2026, 8, 14, 9, 30, tzinfo=UTC), {})
    with pytest.raises(ValueError):
        derive_facts(date(2026, 8, 14), {})


def test_holiday_fact_on_observed_new_year():
    f = derive_facts(datetime(2027, 12, 31, 8, 0), {})
    assert (f["weekday"], f["month_day"], f["federal_holiday"]) == ("Fri", "12-31", True)
    assert derive_facts(datetime(2027, 12, 30, 8, 0), {})["federal_holiday"] is False


def test_vessel_classes():
    assert set(EMERGENCY_CLASSES) < set(VESSEL_CLASSES)
    assert set(VESSEL_CLASSES) - set(EMERGENCY_CLASSES) == {"commercial", "recreational"}
    for c in VESSEL_CLASSES:
        rec = {"vessel_class": {"value": c, "source": "user"}}
        assert derive_facts(datetime(2026, 8, 14) + timedelta(hours=1), rec)["vessel_class"] == c
