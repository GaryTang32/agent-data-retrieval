"""The window grammar (Phase 4 spec §4.5, §12.2): clock words to minutes, and the closed-period
quotes of 33 CFR 117 to `Window`s.

A quote is read only if every word of it belongs to the grammar; anything else makes it None
(unreadable), because a wrong window is worse than a null, and a draw whose window the grammar
cannot read gets no bindings (the gate escalates). The grammar, case-insensitively:

- **Times:** `7 a.m.`, `7:30 p.m.`, `noon`, `12 noon`, `midnight`, `12 midnight` (`parse_time`).
  `12 p.m.` is noon and `12:01 a.m.` is minute 1; `12 a.m.` is refused (midnight is written
  "12 midnight"). A window ending at midnight ends at 1440.
- **Time ranges** (half-open): `[from] T to|until T` and `between [the hours of] T and T`.
  "T through T" is refused (whether the last minute is in is unsure).
- **Days:** `[from|on|every] Monday through Friday` (cyclic ranges, plurals), `on Saturdays and
  Sundays` and other lists, `on Sunday`, `[on] weekdays`, `[on] weekends`, `daily`,
  `seven days a week`, `every day`. Default: every day.
- **Holidays:** `except [for] Federal holidays`, `excluding Federal holidays`, in parentheses or
  not, and `including Federal holidays`. A bare "holidays" is refused: 33 CFR 117 also writes
  "Federal and State holidays" and "holidays observed in the locality", so it is not known to
  mean federal ones.
- **Dates:** `[from] April 16th through|to November 1st`, `15 May through 31 October` (inclusive;
  may wrap the year end), and one day, `on July 4`. A date range with no time range is the
  whole day, as is `at all times`.
- **The closure itself and fillers:** `[the|these|all] [draw(s)|drawspan(s)|bridge(s)] need not
  open|be opened|be open` or `shall remain closed`, optionally `for [the] passage of vessels|
  vessel traffic`, `for vessels`, `to vessels`, `to navigation`; `year-round`, `throughout the
  year`, `each year`, `of every year`, `annually`, `however`, `and`, commas, semicolons, a
  leading `except [that]` (only with the closure in the quote: otherwise what is excepted may be
  the opening hours) and a final period.

One quote holds at most one day, holiday, date and closure phrase, and they hold for every time
range in it; the time ranges must stand together (a qualifier between two of them makes the
quote None, since which ranges it covers is unsure). A range that crosses midnight is read only
when it holds every day with no holiday or date limit (which night is meant is otherwise
unsure). A final colon (the rule continues in the next paragraphs), a second sentence, a lone
time, a condition ("unless", "if", "when", "only"), a vessel class, a named bridge, a paragraph
reference, a special day ("the fourth Sunday in March") or an impossible date all make it None.
"""

from __future__ import annotations

import re

from adr_store.bindings.dsl import DAYS, Window, is_month_day

_CLOCK = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.m\.")
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")

_TIME = (r"(?:\d{1,2}(?::\d{2})?\s*[ap]\.m\.|(?:12\s+)?noon(?!\w)|(?:12\s+)?midnight(?!\w))")
_DAY = r"(?:mon|tues|wednes|thurs|fri|satur|sun)days?"
_MONTH = "(?:" + "|".join(_MONTHS) + ")"
_DATE = rf"(?:{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?(?!\w)|\d{{1,2}}\s+{_MONTH}(?!\w))"

_TOKENS = [(kind, re.compile(pattern, re.IGNORECASE)) for kind, pattern in [
    ("range", rf"(?:from\s+)?(?P<a>{_TIME})\s+(?:to|until)\s+(?P<b>{_TIME})"),
    ("range", rf"between\s+(?:the\s+hours\s+of\s+)?(?P<a>{_TIME})\s+and\s+(?P<b>{_TIME})"),
    ("dates", rf"(?:from\s+)?(?P<da>{_DATE})\s+(?:through|to)\s+(?P<db>{_DATE})"),
    ("dates", rf"on\s+(?P<da>{_DATE})"),
    ("days", rf"(?:(?:from|on|every)\s+)?(?P<d1>{_DAY})\s+through\s+(?P<d2>{_DAY})(?!\w)"),
    ("days", rf"(?:on\s+)?(?P<list>{_DAY}(?:\s*,\s*{_DAY})*\s*,?\s+and\s+{_DAY})(?!\w)"),
    ("days", rf"on\s+(?P<one>{_DAY})(?!\w)"),
    ("days", r"(?:on\s+)?(?P<weekdays>weekdays)(?!\w)"),
    ("days", r"(?:on\s+)?(?P<weekends>weekends)(?!\w)"),
    ("days", r"(?P<every>daily|seven\s+days\s+a\s+week|every\s+day)(?!\w)"),
    ("holidays", r"\(\s*(?:except|excluding)\s+(?:for\s+)?federal\s+holidays\s*\)"),
    ("holidays", r"(?:except|excluding)\s+(?:for\s+)?federal\s+holidays(?!\w)"),
    ("holidays", r"(?P<incl>including)\s+federal\s+holidays(?!\w)"),
    ("all_times", r"at\s+all\s+times(?!\w)"),
    ("closure", r"(?:(?:(?:the|these|all)\s+)?(?:draws?|drawspans?|bridges?)\s+)?"
                r"(?:need\s+not\s+(?:be\s+)?open(?:ed)?|shall\s+remain\s+closed)"
                r"(?:\s+(?:for\s+(?:the\s+)?passage\s+of\s+(?:vessels|vessel\s+traffic)"
                r"|for\s+vessels|for\s+vessel\s+traffic|to\s+vessels|to\s+vessel\s+traffic"
                r"|to\s+navigation))?(?!\w)"),
    ("except", r"except(?:\s+that)?(?!\w)"),
    ("filler", r"(?:year[-\s]round|throughout\s+the\s+year|(?:of\s+)?(?:each|every)\s+year"
               r"|annually|however|and)(?!\w)|[,;]"),
    ("end", r"\.$"),
]]
_ONCE = ("days", "holidays", "dates", "all_times", "closure")


def parse_time(s: str) -> int | None:
    """Minutes after midnight of a clock word ("7 a.m.", "7:30 a.m.", "noon", "12 noon",
    "midnight", "12 midnight" = 0); None when it is not one."""
    if not isinstance(s, str):
        return None
    t = " ".join(s.split()).lower()
    if t in ("noon", "12 noon"):
        return 720
    if t in ("midnight", "12 midnight"):
        return 0
    m = _CLOCK.fullmatch(t)
    if not m:
        return None
    hour, minute = int(m[1]), int(m[2] or 0)
    if not 1 <= hour <= 12 or minute > 59:
        return None
    if m[3] == "a":
        if hour == 12:
            return minute or None        # "12 a.m." is ambiguous; "12:01 a.m." is minute 1
        return hour * 60 + minute
    return (hour % 12 + 12) * 60 + minute


def _tokens(text: str) -> tuple[list[tuple[str, re.Match]], int | None]:
    """The tokens of `text`, and the offset where no token matches (None when all do)."""
    out: list[tuple[str, re.Match]] = []
    pos = 0
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos == len(text):
            return out, None
        for kind, rx in _TOKENS:
            m = rx.match(text, pos)
            if m and m.end() > pos and (kind != "except" or pos == 0):
                out.append((kind, m))
                pos = m.end()
                break
        else:
            return out, pos


def _day(word: str) -> str:
    return word[:3].title()


def _days(m: re.Match) -> tuple[str, ...]:
    g = m.groupdict()
    if g.get("d1"):
        i, j = DAYS.index(_day(g["d1"])), DAYS.index(_day(g["d2"]))
        return tuple(sorted({DAYS[(i + k) % 7] for k in range((j - i) % 7 + 1)}, key=DAYS.index))
    if g.get("list"):
        named = {_day(w) for w in re.findall(_DAY, g["list"], re.IGNORECASE)}
        return tuple(d for d in DAYS if d in named)
    if g.get("one"):
        return (_day(g["one"]),)
    if g.get("weekdays"):
        return DAYS[:5]
    if g.get("weekends"):
        return DAYS[5:]
    return DAYS


def _month_day(text: str) -> str | None:
    words = re.findall(r"[a-z]+|\d+", text.lower())
    month = next(w for w in words if w in _MONTHS)
    day = next(w for w in words if w.isdigit())
    md = f"{_MONTHS.index(month) + 1:02d}-{int(day):02d}"
    return md if is_month_day(md) else None


def parse_windows(quote: str) -> list[Window] | None:
    """The windows a closed-period quote states, in order; None when the grammar cannot read it
    (see the module text)."""
    return read_windows(quote)[0]


def read_windows(quote: str) -> tuple[list[Window] | None, str]:
    """`parse_windows` with the reason a quote is unreadable ("" when it is read): one of
    "empty", "words outside the grammar: <rest>", "a qualifier stated twice", "except with no
    closure", "a qualifier between time ranges", "an unreadable time", "all times and a time
    range", "no time or date range", "an impossible date", "an empty window", "crossing midnight
    with a day, holiday or date limit"."""
    text = " ".join(quote.split()) if isinstance(quote, str) else ""
    if not text:
        return None, "empty"
    toks, stuck = _tokens(text)
    if stuck is not None:
        return None, f"words outside the grammar: {text[stuck:]}"
    kinds = [k for k, _ in toks]
    if any(kinds.count(k) > 1 for k in _ONCE):
        return None, "a qualifier stated twice"
    if "except" in kinds and "closure" not in kinds:
        return None, "except with no closure"
    at = [i for i, k in enumerate(kinds) if k == "range"]
    if at and any(kinds[i] != "filler" for i in range(at[0], at[-1] + 1) if i not in at):
        return None, "a qualifier between time ranges"
    by = {k: m for k, m in toks if k in _ONCE}
    ranges: list[tuple[int, int]] = []
    for kind, m in toks:
        if kind == "range":
            a, b = parse_time(m["a"]), parse_time(m["b"])
            if a is None or b is None:
                return None, "an unreadable time"
            ranges.append((a, b or 1440))
    if ranges and "all_times" in by:
        return None, "all times and a time range"
    if not ranges:
        if "all_times" not in by and "dates" not in by:
            return None, "no time or date range"
        ranges = [(0, 1440)]
    days = _days(by["days"]) if "days" in by else DAYS
    holidays = "holidays" in by and not by["holidays"].groupdict().get("incl")
    date_from = date_to = None
    if "dates" in by:
        date_from = _month_day(by["dates"]["da"])
        date_to = (_month_day(by["dates"]["db"]) if by["dates"].groupdict().get("db")
                   else date_from)
        if date_from is None or date_to is None:
            return None, "an impossible date"
    windows = []
    for start, end in ranges:
        if start == end:
            return None, "an empty window"
        if start > end and (days != DAYS or holidays or date_from is not None):
            return None, "crossing midnight with a day, holiday or date limit"
        windows.append(Window(start=start, end=end, days=days, except_federal_holidays=holidays,
                              date_from=date_from, date_to=date_to))
    return windows, ""
