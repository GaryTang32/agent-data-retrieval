"""The window grammar: clock words to minutes, and closed-period quotes to `Window`s (Phase 4
spec §4.5, §12.2; plan Task 14, Review Focus 2 and 3). The grammar reads a quote only when every
word of it is accounted for; anything it is unsure of is None (unreadable), because a wrong
window is worse than a null."""

from datetime import datetime

import pytest

from adr_store.bindings.dsl import DAYS, Window, in_window
from adr_store.bindings.facts import derive_facts
from adr_store.bindings.windows import parse_time, parse_windows, read_windows

WEEKDAYS = DAYS[:5]


def W(start, end, days=DAYS, hol=False, date_from=None, date_to=None) -> Window:
    return Window(start=start, end=end, days=days, except_federal_holidays=hol,
                  date_from=date_from, date_to=date_to)


# -- parse_time ------------------------------------------------------------------------------

@pytest.mark.parametrize("s,m", [("7 a.m.", 420), ("7:30 a.m.", 450), ("noon", 720),
                                 ("12 noon", 720), ("12:01 a.m.", 1), ("5 p.m.", 1020)])
def test_parse_time(s, m):
    assert parse_time(s) == m


@pytest.mark.parametrize("s,m", [                                 # Review Focus 2
    ("midnight", 0), ("12 midnight", 0), ("12 p.m.", 720), ("12:15 p.m.", 735),
    ("11:59 p.m.", 1439), ("1 a.m.", 60), ("9:00 a.m.", 540), ("  6:45 P.M. ", 1125),
    ("12:59 a.m.", 59),
])
def test_parse_time_more_forms(s, m):
    assert parse_time(s) == m


@pytest.mark.parametrize("s", ["7.pm.", "7 pm", "7:30 p.m", "13 p.m.", "0 a.m.", "7:60 a.m.",
                               "7:5 a.m.", "12 a.m.", "12:00 a.m.", "seven a.m.", "", "noonish",
                               "7 a.m. to 9 a.m.", "19:00"])
def test_parse_time_refuses_what_it_cannot_read(s):
    assert parse_time(s) is None


# -- parse_windows: the plan's cases ---------------------------------------------------------

def test_parse_windows_two_windows_weekdays_holidays():
    assert parse_windows("6 a.m. to 9 a.m. and 5 p.m. to 7 p.m., Monday through Friday, "
                         "except federal holidays") == [
        Window(start=360, end=540, days=WEEKDAYS, except_federal_holidays=True, date_from=None,
               date_to=None),
        Window(start=1020, end=1140, days=WEEKDAYS, except_federal_holidays=True, date_from=None,
               date_to=None)]


def test_midnight_as_start_and_end():
    assert [(w.start, w.end) for w in parse_windows("midnight to 6 a.m.")] == [(0, 360)]
    assert [(w.start, w.end) for w in parse_windows("10 p.m. to midnight")] == [(1320, 1440)]


def test_date_ranges_and_unreadable_quotes():
    assert parse_windows("from April 1 through October 31")[0].date_from == "04-01"
    assert parse_windows("from April 1 through October 31") == [W(0, 1440, date_from="04-01",
                                                                  date_to="10-31")]
    assert parse_windows("shall open on signal if at least two hours notice is given") is None


def test_crossing_midnight():                                       # Review Focus 2
    assert parse_windows("11 p.m. to 6 a.m.") == [W(1380, 360)]
    assert parse_windows("from 10 p.m. to 6 a.m., daily, the draw need not open for the "
                         "passage of vessels") == [W(1320, 360)]
    assert parse_windows("12 midnight to 12 noon") == [W(0, 720)]


# -- parse_windows: readable shapes from 33 CFR 117 ------------------------------------------

@pytest.mark.parametrize("quote,want", [
    ("The draw need not be opened from 6:30 a.m. to 9:30 a.m. and 4 p.m. to 6 p.m.",
     [W(390, 570), W(960, 1080)]),
    ("from 7:30 a.m. to 9 a.m. and 4:30 p.m. to 6 p.m., Monday through Friday, except Federal "
     "holidays, the draw need not open",
     [W(450, 540, WEEKDAYS, True), W(990, 1080, WEEKDAYS, True)]),
    ("the draw need not open for the passage of vessels Monday through Friday except Federal "
     "holidays from 6:30 a.m. to 8:30 a.m., from 11:45 a.m. to 12:15 p.m., from 12:45 p.m. to "
     "1:15 p.m. and from 4:30 p.m. to 6 p.m.",
     [W(390, 510, WEEKDAYS, True), W(705, 735, WEEKDAYS, True), W(765, 795, WEEKDAYS, True),
      W(990, 1080, WEEKDAYS, True)]),
    ("From Monday through Friday, except Federal holidays, the draw need not open between 7:30 "
     "a.m. and 8:30 a.m., between 12 p.m. and 1 p.m., and between 4:30 p.m. and 5:30 p.m.",
     [W(450, 510, WEEKDAYS, True), W(720, 780, WEEKDAYS, True), W(990, 1050, WEEKDAYS, True)]),
    ("from April 16th through November 1st, from 7:30 a.m. to 8:30 a.m. and from 4 p.m. to "
     "5:30 p.m. Monday through Friday, except Federal holidays, the draws need not be opened",
     [W(450, 510, WEEKDAYS, True, "04-16", "11-01"),
      W(960, 1050, WEEKDAYS, True, "04-16", "11-01")]),
    ("From December 16 through March 31, the draw need not open for the passage of vessel "
     "traffic.", [W(0, 1440, date_from="12-16", date_to="03-31")]),
    ("from 15 August to 5 June, the draw need not be opened from 7 a.m. to 8 a.m., Monday "
     "through Friday except Federal holidays",
     [W(420, 480, WEEKDAYS, True, "08-15", "06-05")]),
    ("From 6:30 a.m. to 8:30 a.m. and from 3:30 p.m. to 5:30 p.m., Monday through Friday, except "
     "Federal holidays", [W(390, 510, WEEKDAYS, True), W(930, 1050, WEEKDAYS, True)]),
    ("Monday through Friday (except Federal holidays), 5 a.m. to 12 midnight;",
     [W(300, 1440, WEEKDAYS, True)]),
    ("4:15 p.m. to 5:15 p.m. Monday through Saturday", [W(975, 1035, DAYS[:6])]),
    ("However, the draw need not open from 7 a.m. to 8:30 a.m., and from 4:30 p.m. to 6 p.m., "
     "Monday through Saturday.", [W(420, 510, DAYS[:6]), W(990, 1080, DAYS[:6])]),
    ("Year-round, need not open weekdays, except Federal holidays, from 7 a.m. to 8:30 a.m. and "
     "5:30 p.m. to 7:30 p.m.", [W(420, 510, WEEKDAYS, True), W(1050, 1170, WEEKDAYS, True)]),
    ("On Monday through Friday, except Federal holidays, throughout the year, the draw need not "
     "open for the passage of vessels from 7 a.m. to 8 a.m. and from 1:45 p.m. to 2:45 p.m.",
     [W(420, 480, WEEKDAYS, True), W(825, 885, WEEKDAYS, True)]),
    ("except that from 7 a.m. to 9 a.m. and from 4 p.m. to 6 p.m., Monday through Friday, except "
     "Federal holidays, the bridge need not open",
     [W(420, 540, WEEKDAYS, True), W(960, 1080, WEEKDAYS, True)]),
    ("the draw need not open for the passage of vessel traffic from 7:45 a.m. to 9 a.m., 9:10 a.m. "
     "to 10 a.m., and 5 p.m. to 6 p.m., daily", [W(465, 540), W(550, 600), W(1020, 1080)]),
    ("From 10 p.m. to midnight on July 3 each year the draw need not open for the passage of "
     "vessel traffic.", [W(1320, 1440, date_from="07-03", date_to="07-03")]),
    ("except that from 9 p.m. until 11 p.m. on July 4, each year, the draw need not open for the "
     "passage of vessels", [W(1260, 1380, date_from="07-04", date_to="07-04")]),
    ("from 7 a.m. to 8:30 a.m.; from 2 p.m. to 4 p.m. and from 4:30 p.m. to 5:30 p.m.",
     [W(420, 510), W(840, 960), W(990, 1050)]),
    ("the draw shall remain closed from 6 p.m. to 6 a.m., year-round", [W(1080, 360)]),
    ("the draw need not be opened on Saturdays and Sundays from 11 a.m. to 2 p.m.",
     [W(660, 840, ("Sat", "Sun"))]),
    ("From December 1 through April 30, at all times.",
     [W(0, 1440, date_from="12-01", date_to="04-30")]),
    # the review's surviving mutants: an inclusion is not an exception, midnight to midnight is
    # the whole day, and a day range may wrap the week
    ("from 7 a.m. to 7 p.m. daily, including Federal holidays", [W(420, 1140)]),
    ("from 7 a.m. to 9 a.m., Monday through Friday, including Federal holidays",
     [W(420, 540, WEEKDAYS)]),
    ("midnight to midnight", [W(0, 1440)]),
    ("from 7 a.m. to 9 a.m., Friday through Monday", [W(420, 540, ("Mon", "Fri", "Sat", "Sun"))]),
    ("from 7 a.m. to 9 a.m., Saturday through Sunday", [W(420, 540, ("Sat", "Sun"))]),
    ("from 7 a.m. to 9 a.m., Sunday through Tuesday", [W(420, 540, ("Mon", "Tue", "Sun"))]),
])
def test_readable_quotes(quote, want):
    assert parse_windows(quote) == want


# -- P45: an end written H:59 runs through that minute --------------------------------------

@pytest.mark.parametrize("quote,want", [
    ("4:35 p.m. to 5:59 p.m.", [W(995, 1080)]),
    ("from 7:35 a.m. to 8:59 a.m., 12:05 p.m. to 12:59 p.m. and 4:35 p.m. to 5:59 p.m., Monday "
     "through Friday, except Federal holidays",
     [W(455, 540, WEEKDAYS, True), W(725, 780, WEEKDAYS, True), W(995, 1080, WEEKDAYS, True)]),
    ("from 12 p.m. to 11:59 p.m.", [W(720, 1440)]),
    ("from 6 a.m. to 7:59 a.m. the draw need not open", [W(360, 480)]),
    ("10 p.m. to 5:59 a.m.", [W(1320, 360)]),
    # a start at :59 and other ends stay as written, half-open
    ("5:59 p.m. to 7 p.m.", [W(1079, 1140)]),
    ("4:05 p.m. to 6:58 p.m.", [W(965, 1138)]),
    ("between 4:35 p.m. and 5:59 p.m.", [W(995, 1080)]),
])
def test_an_end_at_59_includes_its_minute(quote, want):
    assert parse_windows(quote) == want


def test_59_end_is_closed_at_that_minute_and_open_after():
    (w,) = parse_windows("4:45 p.m. to 5:59 p.m., Monday through Friday")
    friday = datetime(2026, 8, 14).date()
    assert in_window(w, 17 * 60 + 59, friday) and not in_window(w, 18 * 60, friday)


# -- parse_windows: near misses are None, never a guess ---------------------------------------

@pytest.mark.parametrize("quote", [
    # "through" between two times leaves the last minute unsure
    "from 5:45 a.m. through 9:45 a.m., Monday through Friday",
    # bare "holidays": 33 CFR 117 also says "Federal and State holidays" and "holidays observed
    # in the locality", so an unqualified holiday is not known to be a federal one
    "6 a.m. to 9 a.m., Monday through Friday, except holidays",
    "From 6:30 a.m. to 9 a.m., Monday through Friday, except holidays observed in the locality",
    "from 7 a.m. to 9 a.m., Monday through Friday, except Federal and State holidays",
    "excluding all federal holidays except for Martin Luther King Day, 6 a.m. to 7:45 a.m.",
    # holidays as days the window covers, which a Window cannot hold
    "Saturdays, Sundays, and Federal holidays, 2 p.m. to 7 p.m.",
    # a qualifier between two windows: which windows it covers is unsure
    "from 7 a.m. to 9 a.m., Monday through Friday, and 4 p.m. to 5:45 p.m. daily",
    # a clock word the grammar cannot read
    "5:30 p.m. to 7:30 p.m on weekdays",
    "between 9 a.m. and 7.pm.",
    # crossing midnight with a day, holiday or date limit: which night is meant is unsure
    "11 p.m. to 6 a.m., Monday through Friday",
    "From May 1 through November 30, from 11 p.m. to 7 a.m.",
    # the window is outside the quote, or the quote is about something else
    "need not be opened for the passage of vessels",
    "At all other times the draw need not open for the passage of vessels.",
    "The draw need not open for the passage of vessels except at these hours:",
    "From 6:30 a.m. to 8:30 a.m., Monday through Friday, except Federal holidays:",
    "Monday through Friday, except Federal holidays",
    # restricted openings, conditions and exceptions are not closed windows
    "from 6 a.m. to 7 p.m., the draw need be opened only on the hour and half hour",
    "the draw need not open for the passage of pleasure craft from 7 a.m. to 9:30 a.m.",
    "from 5:45 a.m. to 9:45 a.m., the draw need not open unless an emergency exists",
    "Year round from 11 p.m. to 7 a.m. need not open for the passage of vessels, except as "
    "provided in paragraph (a)(1) of this section.",
    "except between 4:35 p.m. and 5:35 p.m. when the draw need not open",
    "except 6:30 a.m. to 7:30 a.m. and 5:30 p.m. to 6:30 p.m. daily",
    "The draw shall open on signal; except that, from 10 p.m. to 6 a.m. the draw need not be "
    "opened for the passage of vessels.",
    "The draw of the Broadway Bridge need not open from 7 a.m. to 10 a.m.",
    "between 7 a.m. and 9 a.m., and 4 p.m. and 6 p.m., Monday through Friday",
    "Mondays through Fridays the draw need not open at 12 noon and 1 p.m.",
    # two sentences, two date ranges, special days and impossible dates
    "from 12 noon to 1 p.m. Monday through Friday, the draw need not be opened. The draw need "
    "not be opened from 8 p.m. to 6 a.m.",
    "from 7 a.m. to 9 a.m. from April 30 to September 1 and from 7 a.m. to 10 a.m. from "
    "September 1 to April 30",
    "From 9:15 a.m. to 2:30 p.m. on the fourth Sunday in March of every year",
    "first weekend in May, 4 p.m. to 6 p.m. on Saturday and Sunday",
    "From December 1 through April 31, the bridge need not open",
    "On July 4, the draw need not open from 10 p.m. until 11 p.m. to accommodate the annual "
    "July 4th fireworks show.",
    # degenerate: an empty window, or nothing at all
    "7 a.m. to 7 a.m.",
    "",
])
def test_near_misses_are_unreadable(quote):
    assert parse_windows(quote) is None


# -- Review Focus 3, end to end --------------------------------------------------------------

@pytest.mark.parametrize("when,closed", [
    (datetime(2027, 12, 31, 7, 0), False),   # observed New Year's Day (2028-01-01 a Saturday)
    (datetime(2026, 7, 3, 7, 0), False),     # observed Independence Day
    (datetime(2027, 12, 30, 7, 0), True),    # an ordinary Thursday
    (datetime(2026, 7, 2, 8, 59), True),
    (datetime(2026, 7, 2, 9, 0), False),     # half-open: 9:00 is outside "7 a.m. to 9 a.m."
])
def test_weekday_window_does_not_close_on_an_observed_holiday(when, closed):
    (w,) = parse_windows("7 a.m. to 9 a.m., Monday through Friday, except federal holidays")
    f = derive_facts(when, {})
    assert in_window(w, f["minute"], when.date()) is closed


@pytest.mark.parametrize("quote,reason", [
    ("", "empty"),
    ("6 a.m. to 9 a.m., except holidays", "words outside the grammar: except holidays"),
    ("6 a.m. to 9 a.m. daily, 7 a.m. to 8 a.m. daily", "a qualifier stated twice"),
    ("except 6 a.m. to 9 a.m.", "except with no closure"),
    ("6 a.m. to 9 a.m., daily, and 5 p.m. to 7 p.m.", "a qualifier between time ranges"),
    ("13 p.m. to 9 p.m.", "an unreadable time"),
    ("at all times from 6 a.m. to 9 a.m.", "all times and a time range"),
    ("need not be opened for the passage of vessels", "no time or date range"),
    ("from February 30 through March 31", "an impossible date"),
    ("noon to 12 p.m.", "an empty window"),
    ("11 p.m. to 6 a.m. on weekdays", "crossing midnight with a day, holiday or date limit"),
    ("6 a.m. to 9 a.m.", ""),
])
def test_read_windows_names_why_a_quote_is_unreadable(quote, reason):
    windows, why = read_windows(quote)
    assert why == reason and (windows is None) == bool(reason)
    assert parse_windows(quote) == windows
