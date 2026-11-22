"""Rule enrichment for the binding sections (Phase 4 spec §6.2–§6.4, §4.5; Task 15).

**The pool** (`pools`, `binding_sections`). The newest 33 CFR 117 version's subpart A sections
(23 in the real store), in document order, then two seeded draws of subpart B sections whose
draws are all crisp in the Phase 3 first-pass table (`drawbridge_bridges` of the given tables
id, rows of the newest document): a draw is crisp when its `opens_on_signal` is known and each
of its `closed_periods` strings is read by the window grammar (`parse_windows`). `POOL
["closed_window"]` sections are drawn from those with at least one closed window, then
`POOL["notice"]` from the rest of those with a stated `notice_hours`, without overlap. A draw
takes the sections with the lowest SHA-256 of `"<seed>:<section>"`; each group is listed in
document order; a short pool gives what it has.

**The call** (one per section, `tables.extract._call`, so Phase 3 P21 holds: an unparseable
reply is retried once at repeat 1; an input rejection is stored and makes every value null
`model_error`; any other failure and a budget stop propagate uncached). The system prompt
(`prompts/rule_enrich.txt`) names `PROMPT_VERSION` and the rule-card spec ids of
`passes.json` (group `rules`), so the cache key covers both; `max_tokens` is `MAX_TOKENS`
(preflight C3). The user message is the section text (as `tables.ecfr.ecfr_sections` cuts it
from the newest document) and `"\\n\\nRULE CARDS:\\n"` with the provision ids of the section's
rule cards in that document, one per line.

**The checks (§6.3), per value** `{value, quote, null_reason}`: (1) the reply parses, holds
`cards` (an object) and `draws` (a list of objects whose `periods`, when given, is a list of
objects), else the retry, else every value is null `unparseable`; (2) the value is coerced to
its type (times to minutes of the day with `parse_time`, an end at midnight to 1440 and an end
written "H:59" through that minute, P45; dates to "MM-DD"; weekdays to `DAYS`; effects and
opening bases to their allowed values; numbers; card fields to strings or lists of strings),
else null `unparseable`; a null value keeps the model's reason when it is `absent` or
`not_applicable`, else `absent`; (3) a negative (no holiday exception, 0 notice hours,
`closed_to_navigation`) without a quote is null `absent` (Phase 3 P22); any other value whose
quote is not located in the section text (Phase 0 whitespace) is null `ungrounded`; the stored
quote is the located slice at document offsets; (4) numbers must be in their quote
(`number_in_quote`), times (`time_in_quote`, the minute as written) and dates too, and the
clock times and numbers of a card field; a miss keeps the value as `auto-accepted`, else it
is `verified`.

**The window grammar on the whole sentence** (check 5, recorded, never used to reject; the
Task 14 rulings). A period's window quote is the source text spanning its start and end
quotes (else its date quotes, else its effect quote); `window_readable` records whether the
grammar reads it (for `need_not_open` only; the compiler gives a draw with an unreadable one no
bindings). `read_sentence` then reads the sentence of the source text that holds the clock
times of that quote: the widest span around them that the grammar reads (`widest_reading`),
and what the grammar's phrases state in the quote's clause (the sentence cut at ";" and at
", except that"): times, days, the holiday exception, dates, and the words "only", "unless"
and "notice". `window_grammar_agrees` (closures only) is whether the period's window is one of
the windows read, and None when nothing reads or when the clause has one of those words (not a
plain closure). `sentence_qualifiers` lists the days, holiday exception or dates the clause
states that the period lacks (`missing_qualifiers`); for a draw's period-less notice or
on-signal basis, the times, days, holidays or dates its quote's clause states.

`write_enrichment` writes the items once as `<store>/units/<snapshot>/enrichment-<id[:16]>.jsonl`
(canonical JSON per section in document order; the id is the file's SHA-256);
`load_enrichment` reads them back by id. `apply` fills the build's in-scope rule cards (the
newest version's cards of the pool sections) from the cached replies. `e2_agreement` compares
the parameters with both Phase 3 passes (§6.3 check 5, criterion E2).
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from string import Template
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from adr_eval.cache import Cache
from adr_eval.llm import Completion, ModelOutputError, parse_json_recovering
from adr_store import applicability as ap
from adr_store.bindings.dsl import DAYS, Window, is_month_day
from adr_store.bindings.windows import (
    parse_time,
    parse_windows,
    stated_qualifiers,
    widest_reading,
)
from adr_store.store import Store
from adr_store.tables import extract as ex
from adr_store.tables.ecfr import SectionUnit, chain_docs, ecfr_sections
from adr_store.tables.overlay import _write_once, load_manifest, load_rows, read_head
from adr_store.tables.provenance import RowRecord
from adr_store.units.ecfr import provisions, rule_cards
from adr_store.units.envelope import COMPILER_VERSION, Lineage, Unit, UnitNullReason, meta_sha256
from adr_store.units.grounding import (
    PassConfig,
    clock_times,
    ground,
    load_pass_config,
    time_in_quote,
)
from adr_store.units.overlay import UNITS_DIR, UnitsError
from adr_store.units.procedure_pass import value_in_quotes
from adr_store.units.procedures import SEED4

__all__ = ["BASES", "EFFECTS", "MAX_TOKENS", "POOL", "PROMPT_VERSION", "SEED4", "DrawParams",
           "Grounded", "Period", "SectionEnrichment", "SentenceReading", "apply",
           "binding_sections", "e2_agreement", "enrich_all", "enrich_section",
           "grammar_agrees", "load_enrichment", "missing_qualifiers", "period_window", "pools",
           "read_sentence", "write_enrichment"]

PROMPT_VERSION = "rule-enrich@1"
MAX_TOKENS = 4000   # cards and draws of one section, each value with its quote
POOL = {"closed_window": 15, "notice": 15}
EFFECTS = ("need_not_open", "on_signal", "notice_required")
BASES = ("on_signal", "advance_notice", "closed_to_navigation")
CHAIN = "ecfr:33:117"
CARD_FIELDS = ("subject", "conditions", "thresholds", "exceptions")
DRAW_FIELDS = ("bridge", "mile", "opening_basis", "notice_hours")
PERIOD_FIELDS = ("effect", "start", "end", "days", "except_federal_holidays", "date_from",
                 "date_to")
FAILED = ("unparseable", "ungrounded", "model_error")    # checks 1-3 (§12.2)
CONDITION_WORDS = ("only", "unless", "notice")
ENRICHMENT_PREFIX = "enrichment"
_MODEL_NULLS = ("absent", "not_applicable")
_REPLY_KEYS = ("cards", "draws")
_KINDS = {"subject": "text", "conditions": "strings", "thresholds": "strings",
          "exceptions": "strings", "bridge": "text", "mile": "real", "opening_basis": "basis",
          "notice_hours": "hours", "effect": "effect", "start": "start", "end": "end",
          "days": "days", "except_federal_holidays": "bool", "date_from": "date",
          "date_to": "date"}


# -- the models ----------------------------------------------------------------------------------

class Grounded(BaseModel):
    """One checked value: its quote (the located slice) at document offsets, its status when
    kept (`verified`, `auto-accepted`) and its null reason when not."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: Any
    quote: str | None
    start: int | None
    end: int | None
    status: str | None
    null_reason: UnitNullReason | None


class Period(BaseModel):
    """One window of a draw with its own rule, and the window grammar's reading of it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    effect: Grounded
    start: Grounded
    end: Grounded
    days: Grounded
    except_federal_holidays: Grounded
    date_from: Grounded
    date_to: Grounded
    window_grammar_agrees: bool | None
    window_readable: bool | None = None        # need_not_open only: the grammar reads it
    window_quote: str | None = None            # the source text the readability check read
    sentence_qualifiers: list[str] = Field(default_factory=list)
    sentence_conditions: list[str] = Field(default_factory=list)


class DrawParams(BaseModel):
    """The binding parameters of one draw (in the order the reply names the draws, from 1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    draw: int
    bridge: Grounded
    mile: Grounded
    opening_basis: Grounded
    notice_hours: Grounded
    periods: list[Period]
    sentence_qualifiers: list[str] = Field(default_factory=list)   # period-less parameters


class SectionEnrichment(BaseModel):
    """The checked reply for one section: per rule card (provision id) its four fields, per
    draw its parameters; `outcome` is the call's (reply, reply_repeat_1, unparseable,
    model_error). `section_sha256` is the SHA-256 of the section text, the Phase 3 unit key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    section: str
    doc_id: str
    section_sha256: str
    cards: dict[str, dict[str, Grounded]]
    draws: list[DrawParams]
    outcome: str


# -- the pool ------------------------------------------------------------------------------------

def _section_key(section: str) -> tuple:
    head, _, rest = section.partition(".")
    return (int(head) if head.isdigit() else 0, int(rest) if rest.isdigit() else 10**9, rest)


def newest_doc(store: Store) -> str:
    docs = chain_docs(store, CHAIN)
    if not docs:
        raise UnitsError(f"{store.path}: no {CHAIN} document")
    return docs[-1]


def _ranked(sections: list[str], seed: int) -> list[str]:
    return sorted(sections, key=lambda s: hashlib.sha256(f"{seed}:{s}".encode()).hexdigest())


def _crisp(row: dict) -> bool:
    return row.get("opens_on_signal") is not None and all(
        parse_windows(q) is not None for q in row.get("closed_periods") or [])


def pools(store: Store, tables_id: str, seed: int = SEED4) -> dict[str, list[str]]:
    """The pool of the binding sections (module text): `subpart_a`, the candidates
    `closed_window_candidates` and `notice_candidates` (document order) and the drawn
    `closed_window` and `notice` sections. TablesError for an unknown tables id."""
    doc = newest_doc(store)
    subparts: dict[str, str | None] = {}
    for p in provisions(store, doc):
        subparts.setdefault(p.section, p.subpart)
    rows = [r.row for r in load_rows(store.path, load_manifest(store.path, tables_id),
                                     "drawbridge_bridges") if r.doc_id == doc]
    by: dict[str, list[dict]] = {}
    for row in rows:
        by.setdefault(row["section"], []).append(row)
    crisp = sorted((s for s, rs in by.items() if subparts.get(s) == "B"
                    and all(_crisp(r) for r in rs)), key=_section_key)
    closed = [s for s in crisp if any(r.get("closed_periods") for r in by[s])]
    notice = [s for s in crisp if any(r.get("notice_hours") is not None for r in by[s])]
    drawn_closed = _ranked(closed, seed)[:POOL["closed_window"]]
    drawn_notice = _ranked([s for s in notice if s not in drawn_closed], seed)[:POOL["notice"]]
    return {"subpart_a": [s for s, sp in subparts.items() if sp == "A"],
            "closed_window_candidates": closed, "notice_candidates": notice,
            "closed_window": sorted(drawn_closed, key=_section_key),
            "notice": sorted(drawn_notice, key=_section_key)}


def binding_sections(store: Store, tables_id: str, seed: int = SEED4) -> list[str]:
    """The sections the enrichment covers: subpart A, then the closed-window draw, then the
    notice draw (`pools`)."""
    p = pools(store, tables_id, seed)
    return p["subpart_a"] + p["closed_window"] + p["notice"]


# -- the config and the prompt -------------------------------------------------------------------

def check_config(cfg: PassConfig) -> None:
    """ValueError unless `cfg` is the rules pass config: this module's prompt version and one
    group naming exactly `CARD_FIELDS` (one call per section)."""
    if cfg.prompt_version != PROMPT_VERSION:
        raise ValueError(f"prompt version {cfg.prompt_version!r} is not {PROMPT_VERSION!r}")
    if len(cfg.groups) != 1 or sorted(*cfg.groups.values()) != sorted(CARD_FIELDS):
        raise ValueError(f"the rules pass has one group naming each field of {CARD_FIELDS}")


@functools.cache
def _template() -> Template:
    return Template(resources.files("adr_store.units").joinpath(
        "prompts/rule_enrich.txt").read_text(encoding="utf-8"))


def pass_prompt(cfg: PassConfig) -> str:
    """The system prompt: the prompt version and the rule-card spec ids, then the rules."""
    check_config(cfg)
    return _template().substitute(prompt_version=cfg.prompt_version,
                                  specs=", ".join(cfg.specs[f] for f in CARD_FIELDS))


# -- coercion and checks -------------------------------------------------------------------------

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")
_MONTH_RX = r"(january|february|march|april|may|june|july|august|september|october|november|" \
    r"december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)\.?"
_DATE_MD = re.compile(rf"{_MONTH_RX}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", re.IGNORECASE)
_DATE_DM = re.compile(rf"\b(\d{{1,2}})\s+{_MONTH_RX}", re.IGNORECASE)
_DAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DAY_SHORT = {"tues": 1, "thur": 3, "thurs": 3, "weds": 2}
_EVERY_DAY = ("daily", "every day", "each day", "all days", "seven days a week")


def _month(word: str) -> int:
    w = word.lower().rstrip(".")
    return next(i for i, m in enumerate(_MONTHS, 1) if m == w or m[:3] == w[:3])


def _md(month: int, day: int) -> str | None:
    md = f"{month:02d}-{day:02d}"
    return md if is_month_day(md) else None


def _dates_in(text: str) -> set[str]:
    found = {_md(_month(m[1]), int(m[2])) for m in _DATE_MD.finditer(text)}
    found |= {_md(_month(m[2]), int(m[1])) for m in _DATE_DM.finditer(text)}
    return found - {None}


def _coerce_date(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"not a date: {raw!r}")
    s = raw.strip()
    if is_month_day(s):
        return s
    for rx, mi, di in ((_DATE_MD, 1, 2), (_DATE_DM, 2, 1)):
        m = rx.fullmatch(s)
        if m:
            md = _md(_month(m[mi]), int(m[di]))
            if md is not None:
                return md
    raise ValueError(f"not a calendar day: {raw!r}")


def _day(word: str) -> int:
    w = word.strip().lower().rstrip(".")
    if w.endswith("s") and w[:-1] in _DAY_NAMES:
        w = w[:-1]
    if w in _DAY_NAMES:
        return _DAY_NAMES.index(w)
    if w in _DAY_SHORT:
        return _DAY_SHORT[w]
    if len(w) == 3 and any(n.startswith(w) for n in _DAY_NAMES):
        return next(i for i, n in enumerate(_DAY_NAMES) if n.startswith(w))
    raise ValueError(f"not a weekday: {word!r}")


def _coerce_days(raw: Any) -> list[str]:
    if isinstance(raw, list):
        if not all(isinstance(x, str) for x in raw):
            raise ValueError(f"not weekdays: {raw!r}")
        found = {_day(x) for x in raw}
    elif isinstance(raw, str):
        s = " ".join(raw.lower().split())
        if s in _EVERY_DAY:
            found = set(range(7))
        elif s == "weekdays":
            found = set(range(5))
        elif s == "weekends":
            found = {5, 6}
        elif m := re.fullmatch(r"(\w+)\s*(?:through|to|-|–)\s*(\w+)", s):
            i, j = _day(m[1]), _day(m[2])
            found = {(i + k) % 7 for k in range((j - i) % 7 + 1)}
        else:
            found = {_day(w) for w in re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+", s) if w}
    else:
        raise ValueError(f"not weekdays: {raw!r}")
    if not found:
        raise ValueError("no weekday")
    return [DAYS[i] for i in sorted(found)]


def _coerce_time(raw: Any) -> int:
    t = parse_time(raw) if isinstance(raw, str) else None
    if t is None:
        raise ValueError(f"not a clock time: {raw!r}")
    return t


def _coerce(kind: str, raw: Any) -> Any:
    """Check 2: `raw` as a value of `kind`; ValueError when it is not one."""
    if kind == "text":
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("not a text")
        return raw.strip()
    if kind == "strings":
        items = [raw] if isinstance(raw, str) else raw
        if not isinstance(items, list) or not items or not all(
                isinstance(x, str) and x.strip() for x in items):
            raise ValueError("not a list of texts")
        return [x.strip() for x in items]
    if kind == "real":
        return ex.coerce("real", raw)
    if kind == "hours":
        if isinstance(raw, bool):
            raise ValueError("not a number of hours")
        if isinstance(raw, str) and raw.strip().isdigit():
            raw = int(raw.strip())
        if isinstance(raw, float) and raw.is_integer():
            raw = int(raw)
        if not isinstance(raw, int) or raw < 0:
            raise ValueError(f"not a number of hours: {raw!r}")
        return raw
    if kind in ("basis", "effect"):
        allowed = BASES if kind == "basis" else EFFECTS
        if raw not in allowed:
            raise ValueError(f"{raw!r} is not one of {allowed}")
        return raw
    if kind == "bool":
        if type(raw) is not bool:
            raise ValueError(f"not a bool: {raw!r}")
        return raw
    if kind == "start":
        return _coerce_time(raw)
    if kind == "end":
        t = _coerce_time(raw)
        if t == 0:
            return 1440                         # a window ending at midnight ends the day
        if re.search(r":59\s*[ap]\.?m", raw, re.IGNORECASE):
            return t + 1                        # P45: "to 5:59 p.m." includes 17:59
        return t
    if kind == "days":
        return _coerce_days(raw)
    if kind == "date":
        return _coerce_date(raw)
    raise ValueError(f"unknown kind {kind!r}")


def _negative(kind: str, value: Any) -> bool:
    """A value that states a negative (Phase 3 P22): it needs a quote of its own."""
    return (kind == "bool" and value is False) or (kind == "hours" and value == 0) or (
        kind == "basis" and value == "closed_to_navigation")


def _in_quote(kind: str, raw: Any, value: Any, quote: str) -> bool:
    """Check 4: the value is stated in its quote (numbers, times as written, dates, the clock
    times and numbers of a text)."""
    if kind in ("real", "hours"):
        return ex.number_in_quote(value, quote)
    if kind in ("start", "end"):
        return time_in_quote(parse_time(raw), quote)
    if kind == "date":
        return value in _dates_in(quote)
    if kind in ("text", "strings"):
        return value_in_quotes(value if kind == "text" else tuple(value), [quote])
    return True


def _null(reason: UnitNullReason) -> Grounded:
    return Grounded(value=None, quote=None, start=None, end=None, status=None,
                    null_reason=reason)


def check_cell(kind: str, cell: Any, section_text: str, offset: int) -> tuple[Grounded, bool]:
    """Checks 2-4 of one cell (module text); (the value, whether a quote was given for a
    typed value). Offsets are the section's plus `offset` (its start in the document)."""
    if cell is None:
        return _null("absent"), False
    if not isinstance(cell, dict):
        return _null("unparseable"), False
    raw = cell.get("value")
    if raw is None or raw == [] or (isinstance(raw, str) and not raw.strip()):
        reason = cell.get("null_reason")
        return _null(reason if reason in _MODEL_NULLS else "absent"), False
    try:
        value = _coerce(kind, raw)
    except (ValueError, TypeError):
        return _null("unparseable"), False
    quote = cell.get("quote")
    given = isinstance(quote, str) and bool(quote.strip())
    if not given and _negative(kind, value):
        return _null("absent"), False                   # Phase 3 P22: silence is absent
    span = ground(section_text, quote) if given else None
    if span is None:
        return _null("ungrounded"), given
    s, e = span
    located = section_text[s:e]
    status = "verified" if _in_quote(kind, raw, value, located) else "auto-accepted"
    return Grounded(value=value, quote=located, start=s + offset, end=e + offset,
                    status=status, null_reason=None), True


# -- the window grammar on the whole sentence ------------------------------------------------------

_CLOCK_WORD = re.compile(r"[ap]\.m\.\W*$", re.IGNORECASE)
_NOT_A_START = re.compile(r"(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)days?\b|" + "|".join(
    m.title() for m in _MONTHS) + r"|Federal\b|Eastern\b|Central\b|Pacific\b|Mountain\b|"
    r"Atlantic\b|E\.?[SD]\.?T\b|Standard\b|Daylight\b|Local\b")
_ABBREVIATION = re.compile(
    r"(?:^|[\s(])(?:(?:[A-Za-z]\.){1,4}|St|Ste|Mt|Ft|Pt|Ave|Blvd|Rd|Hwy|Pkwy|Rte|No|Nos|Jr|Sr|Dr|"
    r"Co|Corp|Inc|Bros|Sq|Ln|Twp|Is|Br|Cr)\.$")
_SENTENCE_END = re.compile(r"\.(?=\s+[A-Z(\[§“\"])")
_MARKERS = re.compile(r"(?:\(\w{1,5}\)\s*)+")
_CLAUSE_CUT = re.compile(r";|,(?=\s+except\s+that\b)", re.IGNORECASE)


@dataclass(frozen=True)
class SentenceReading:
    """The window grammar's reading of the sentence around a quote (module text)."""

    sentence: str                     # paragraph markers dropped
    readable: bool                    # the grammar reads the whole sentence
    windows: list[Window] | None      # the widest reading around the quote
    span: tuple[int, int] | None      # where that reading stands in `sentence`
    clause: str                       # the quote's clause
    stated: dict                      # what the clause and the reading state
    conditions: tuple[str, ...]       # "only", "unless", "notice" in the clause


def _sentence_ends(line: str) -> list[int]:
    """Offsets in `line` just after each "." that ends a sentence."""
    out = []
    for m in _SENTENCE_END.finditer(line):
        before = line[:m.start() + 1]
        if _CLOCK_WORD.search(before):
            if _NOT_A_START.match(line[m.end():].lstrip()):
                continue
        elif _ABBREVIATION.search(before):
            continue
        out.append(m.start() + 1)
    return out


def read_sentence(text: str, start: int, end: int) -> SentenceReading:
    """The sentence of `text` holding `[start, end)` (a paragraph is a line; a sentence ends
    at "." before a capital, not after an abbreviation or after "a.m."/"p.m." when a weekday,
    month or "Federal" follows), with leading paragraph markers dropped, and the grammar's
    reading of it (module text)."""
    ls = text.rfind("\n", 0, start) + 1
    le = text.find("\n", end)
    le = len(text) if le < 0 else le
    line = text[ls:le]
    ends = _sentence_ends(line)
    a, b = start - ls, end - ls
    s0 = max([0] + [e for e in ends if e <= a])
    s1 = min([e for e in ends if e >= b] + [len(line)])
    raw = line[s0:s1]
    lead = len(raw) - len(raw.lstrip())
    m = _MARKERS.match(raw, lead)
    lead = m.end() if m else lead
    sentence = raw[lead:].rstrip()
    a = max(0, min(a - s0 - lead, len(sentence)))
    b = max(a, min(b - s0 - lead, len(sentence)))
    windows, span = widest_reading(sentence, a, b)
    cuts = [m.end() if m.group() == ";" else m.start() + 1
            for m in _CLAUSE_CUT.finditer(sentence)]
    c0 = max([0] + [c for c in cuts if c <= a])
    c1 = min([c for c in cuts if c >= b] + [len(sentence)])
    clause = sentence[c0:c1]
    stated = stated_qualifiers(clause)
    for w in windows or []:
        stated["times"].append((w.start, w.end))
        if w.days != DAYS:
            stated["days"].append(w.days)
        stated["holidays"] = stated["holidays"] or w.except_federal_holidays
        if w.date_from is not None:
            stated["dates"].append((w.date_from, w.date_to))
    for k in ("times", "days", "dates"):
        stated[k] = list(dict.fromkeys(tuple(x) for x in stated[k]))
    conditions = tuple(w for w in CONDITION_WORDS
                       if re.search(rf"\b{w}\b", clause, re.IGNORECASE))
    return SentenceReading(sentence, parse_windows(sentence) is not None, windows, span,
                           clause, stated, conditions)


def missing_qualifiers(window: Window, reading: SentenceReading) -> list[str]:
    """The qualifiers (`days`, `holidays`, `dates`, sorted) that the reading states and the
    window lacks: a day set other than every day that the window's is not, a holiday exception
    the window does not make, a date range that the window's is not."""
    stated = reading.stated
    out = []
    days = [tuple(d) for d in stated["days"] if tuple(d) != DAYS]
    if days and tuple(window.days) not in days:
        out.append("days")
    if stated["holidays"] and not window.except_federal_holidays:
        out.append("holidays")
    if stated["dates"] and (window.date_from, window.date_to) not in stated["dates"]:
        out.append("dates")
    return sorted(out)


def stated_kinds(reading: SentenceReading) -> list[str]:
    """What a clause states that a period-less rule would leave out (sorted): `times` (a
    time range short of the whole day), `days` (other than every day), `holidays`, `dates`."""
    s = reading.stated
    out = []
    if any(t != (0, 1440) for t in s["times"]):
        out.append("times")
    if any(tuple(d) != DAYS for d in s["days"]):
        out.append("days")
    if s["holidays"]:
        out.append("holidays")
    if s["dates"]:
        out.append("dates")
    return sorted(out)


def grammar_agrees(window: Window, reading: SentenceReading) -> bool | None:
    """Whether the window is one the sentence's reading holds; None when nothing reads or the
    clause is no plain closure ("only", "unless", "notice")."""
    if reading.conditions or reading.windows is None:
        return None
    return window in reading.windows


def period_window(p: Period) -> tuple[Window | None, str | None]:
    """(the window of period `p`, None) or (None, the problem): no times is the whole day, no
    days every day, no holiday exception none, no dates all year."""
    s, e = p.start.value, p.end.value
    if s is None and e is None:
        s, e = 0, 1440
    elif e is None:
        return None, "a start with no end"
    elif s is None:
        return None, "an end with no start"
    df, dt = p.date_from.value, p.date_to.value
    if (df is None) != (dt is None):
        return None, "a date range with one end"
    if s == e:
        return None, f"start {s} equals end {e}"
    try:
        return Window(start=s, end=e, days=tuple(p.days.value or DAYS),
                      except_federal_holidays=p.except_federal_holidays.value is True,
                      date_from=df, date_to=dt), None
    except ValidationError as err:
        return None, "; ".join(x["msg"] for x in err.errors())


def _span_of(gs: list[Grounded]) -> tuple[int, int] | None:
    found = [g for g in gs if g.start is not None]
    return (min(g.start for g in found), max(g.end for g in found)) if found else None


def _read_period(p: Period, text: str, offset: int) -> Period:
    """`p` with its window quote, readability, agreement, sentence qualifiers and conditions
    (module text)."""
    closure = p.effect.value == "need_not_open"
    span = (_span_of([p.start, p.end]) or _span_of([p.date_from, p.date_to])
            or _span_of([p.effect]))
    if span is None:
        return p.model_copy(update={"window_readable": False if closure else None})
    a, b = span[0] - offset, span[1] - offset
    quote = text[a:b]
    times = clock_times(quote)
    anchor = (a + times[0][0], a + times[-1][1]) if times else (a, b)
    reading = read_sentence(text, *anchor)
    window, _ = period_window(p)
    return p.model_copy(update={
        "window_quote": quote,
        "window_readable": (parse_windows(quote) is not None) if closure else None,
        "window_grammar_agrees": grammar_agrees(window, reading)
        if closure and window is not None else None,
        "sentence_qualifiers": missing_qualifiers(window, reading)
        if window is not None else [],
        "sentence_conditions": list(reading.conditions) if closure else []})


def _draw_qualifiers(d: DrawParams, text: str, offset: int) -> list[str]:
    """What the clauses of a draw's period-less notice or on-signal basis state (module text):
    a notice with no `notice_required` period, an `on_signal` basis with no `on_signal`
    period (the compiler gives both the all-times window)."""
    effects = {p.effect.value for p in d.periods}
    period_less = []
    if d.notice_hours.value is not None and "notice_required" not in effects:
        period_less.append(d.notice_hours)
    if d.opening_basis.value == "on_signal" and "on_signal" not in effects:
        period_less.append(d.opening_basis)
    found: set[str] = set()
    for g in period_less:
        found.update(stated_kinds(read_sentence(text, g.start - offset, g.end - offset)))
    return sorted(found)


# -- one section ---------------------------------------------------------------------------------

def _parse(text: str) -> dict:
    reply, _ = parse_json_recovering(text, _REPLY_KEYS)
    missing = [k for k in _REPLY_KEYS if k not in reply]
    if missing:
        raise ModelOutputError(f"the reply has no {', '.join(missing)}")
    draws = reply["draws"]
    if not isinstance(reply["cards"], dict) or not isinstance(draws, list) or not all(
            isinstance(d, dict) for d in draws):
        raise ModelOutputError("expected a cards object and a list of draw objects")
    for d in draws:
        periods = d.get("periods")
        if periods is not None and (not isinstance(periods, list) or not all(
                isinstance(p, dict) for p in periods)):
            raise ModelOutputError("a draw's periods must be a list of objects")
    return reply


class _Recorder:
    """`client` that remembers the repeat index of its last call and its completions."""

    def __init__(self, client):
        self.client, self.repeat, self.completions = client, 0, []

    def complete(self, system: str, user: str, *, max_tokens: int, repeat: int = 0,
                 cache_failures: bool = False) -> Completion:
        self.repeat = repeat
        c = self.client.complete(system, user, max_tokens=max_tokens, repeat=repeat,
                                 cache_failures=cache_failures)
        self.completions.append(c)
        return c


@dataclass(frozen=True)
class _Run:
    item: SectionEnrichment
    counts: Counter                  # made, cached, failed
    served: tuple[str, ...]
    key: str                         # the cache key of the call (or of its stored failure)
    tally: dict                      # field -> Counter


def _in_section(ref: str, section: str) -> bool:
    head = f"33 CFR {section}"
    return ref == head or ref.startswith(head + "(")


def _card_ids(cards: list[Unit], doc: str, section: str) -> list[str]:
    own = sorted((c for c in cards if c.doc_id == doc and _in_section(c.canonical_ref, section)),
                 key=lambda c: c.source_refs[0].start)
    return list(dict.fromkeys(c.canonical_ref for c in own))


def _all(reason: UnitNullReason, ids: list[str]) -> dict[str, dict[str, Grounded]]:
    return {i: dict.fromkeys(CARD_FIELDS, _null(reason)) for i in ids}


def _enrich(su: SectionUnit, doc: str, cards: list[Unit], client, cfg: PassConfig) -> _Run:
    ids = _card_ids(cards, doc, su.section)
    user = su.text + "\n\nRULE CARDS:\n" + "\n".join(ids)
    system = pass_prompt(cfg)
    rec = _Recorder(client)
    reply, outcome, counts = ex._call(rec, system, user, _parse, max_tokens=MAX_TOKENS)
    key = Cache.key(client.name, getattr(client, "model", client.name), system, user,
                    MAX_TOKENS, rec.repeat)
    if outcome == "model_error":     # stored under its failure key (`_failure_key`)
        key = Cache.key("failure", key)
    served = tuple(sorted({c.served_model for c in rec.completions if c.served_model}))
    sha = hashlib.sha256(su.text.encode("utf-8")).hexdigest()
    tally: dict[str, Counter] = {}
    if reply is None:
        reason = "model_error" if outcome == "model_error" else "unparseable"
        item = SectionEnrichment(section=su.section, doc_id=doc, section_sha256=sha,
                                 cards=_all(reason, ids), draws=[], outcome=outcome)
        for f in CARD_FIELDS:
            tally.setdefault(f, Counter())[f"null:{reason}"] += len(ids)
        return _Run(item, counts, served, key, tally)

    def check(field: str, cell: Any) -> Grounded:
        g, given = check_cell(_KINDS[field], cell, su.text, su.start)
        t = tally.setdefault(field, Counter())
        t["quotes_given"] += given
        t["quotes_grounded"] += g.quote is not None
        t[g.status if g.value is not None else f"null:{g.null_reason}"] += 1
        return g

    out_cards: dict[str, dict[str, Grounded]] = {}
    for i in ids:
        got = reply["cards"].get(i)
        if got is not None and not isinstance(got, dict):
            got = dict.fromkeys(CARD_FIELDS, "not a cell")
        out_cards[i] = {f: check(f, (got or {}).get(f)) for f in CARD_FIELDS}
    draws = []
    for n, d in enumerate(reply["draws"], 1):
        periods = []
        for p in d.get("periods") or []:
            draft = Period(**{f: check(f, p.get(f)) for f in PERIOD_FIELDS},
                           window_grammar_agrees=None)
            periods.append(_read_period(draft, su.text, su.start))
        dp = DrawParams(draw=n, **{f: check(f, d.get(f)) for f in DRAW_FIELDS}, periods=periods)
        draws.append(dp.model_copy(update={
            "sentence_qualifiers": _draw_qualifiers(dp, su.text, su.start)}))
    item = SectionEnrichment(section=su.section, doc_id=doc, section_sha256=sha,
                             cards=out_cards, draws=draws, outcome=outcome)
    return _Run(item, counts, served, key, tally)


def section_unit(store: Store, doc: str, section: str) -> SectionUnit:
    for su in ecfr_sections(store, doc):
        if su.section == section:
            return su
    raise UnitsError(f"{doc[:12]}: no section {section}")


def enrich_section(section: str, store: Store, cards: list[Unit], client) -> SectionEnrichment:
    """The checked enrichment of `section` of the newest 33 CFR 117 version (one cached call;
    `cards` are rule cards, of which the section's cards in that version are sent)."""
    doc = newest_doc(store)
    return _enrich(section_unit(store, doc, section), doc, cards, client,
                   load_pass_config("rules")).item


def section_cards(store: Store) -> tuple[str, list[Unit]]:
    """(the newest 33 CFR 117 document, its rule cards built by code)."""
    doc = newest_doc(store)
    return doc, rule_cards(store, doc, ap.load_overlay(store.path, store.snapshot_id))[0]


# -- the whole pass ------------------------------------------------------------------------------

def _needs_tables(store: Store) -> str:
    tables_id = read_head(store.path)
    if tables_id is None:
        raise UnitsError(f"{store.path}: the rules pass needs tables/HEAD (the Phase 3 "
                         f"first-pass table draws its pool); build and promote the tables")
    return tables_id


def _runs(store: Store, sections: list[str], doc: str, cards: list[Unit], client,
          cfg: PassConfig, workers: int = 1) -> list[_Run]:
    by = {su.section: su for su in ecfr_sections(store, doc)}
    missing = [s for s in sections if s not in by]
    if missing:
        raise UnitsError(f"{doc[:12]}: no section {', '.join(missing)}")
    return ex._map(lambda s: _enrich(by[s], doc, cards, client, cfg), sections, workers)


def _summary(runs: list[_Run]) -> dict:
    fields: dict[str, dict] = {}
    for f in (*CARD_FIELDS, *DRAW_FIELDS, *PERIOD_FIELDS):
        t = sum((r.tally.get(f, Counter()) for r in runs), Counter())
        fields[f] = {"quotes_given": t["quotes_given"], "quotes_grounded": t["quotes_grounded"],
                     "values": t["verified"] + t["auto-accepted"], "verified": t["verified"],
                     "auto-accepted": t["auto-accepted"],
                     "nulls": {k.split(":", 1)[1]: v for k, v in sorted(t.items())
                               if k.startswith("null:")}}
    draws = [d for r in runs for d in r.item.draws]
    closures = [p for d in draws for p in d.periods if p.effect.value == "need_not_open"]
    flagged = [d for d in draws if d.sentence_qualifiers
               or any(p.sentence_qualifiers for p in d.periods)]
    return {"fields": fields,
            "outcomes": dict(sorted(Counter(r.item.outcome for r in runs).items())),
            "draws": {"draws": len(draws), "periods": sum(len(d.periods) for d in draws)},
            "window_grammar": {
                "windows": len(closures),
                "readable": sum(p.window_readable is True for p in closures),
                "agree": sum(p.window_grammar_agrees is True for p in closures),
                "disagree": sum(p.window_grammar_agrees is False for p in closures),
                "not_compared": sum(p.window_grammar_agrees is None for p in closures),
                "conditioned": sum(bool(p.sentence_conditions) for p in closures),
                "sentence_qualifiers": len(flagged)}}


def _calls(runs: list[_Run]) -> dict:
    counts = sum((r.counts for r in runs), Counter())
    return {k: counts[k] for k in ("made", "cached", "failed")}


def enrich_all(store: Store, client, *, limit: int | None = None, workers: int = 1
               ) -> tuple[list[SectionEnrichment], dict]:
    """(the enrichment of the binding sections in pool order, the report); with `limit` only
    the first sections (the canary). The report (unhashed): prompt version, max tokens, groups
    and specs, seed, tables id, the pool sizes, the calls and served models of the run, and
    per field the quotes given and grounded (E1), values and nulls, the call outcomes and the
    window grammar's counts."""
    cfg = load_pass_config("rules")
    check_config(cfg)
    tables_id = _needs_tables(store)
    p = pools(store, tables_id)
    sections = p["subpart_a"] + p["closed_window"] + p["notice"]
    chosen = sections if limit is None else sections[:limit]
    doc, cards = section_cards(store)
    runs = _runs(store, chosen, doc, cards, client, cfg, workers)
    report = {"pass": "rules", "prompt_version": cfg.prompt_version, "max_tokens": MAX_TOKENS,
              "groups": cfg.groups, "specs": cfg.specs, "seed": SEED4, "tables_id": tables_id,
              "limit": limit, "doc_id": doc,
              "sections": {"subpart_a": len(p["subpart_a"]),
                           "closed_window": len(p["closed_window"]),
                           "notice": len(p["notice"]), "run": len(chosen)},
              "calls": _calls(runs),
              "served_models": sorted({m for r in runs for m in r.served}), **_summary(runs)}
    return [r.item for r in runs], report


# -- the enrichment file -------------------------------------------------------------------------

def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8") + b"\n"


def write_enrichment(store_path: Path, snapshot: str, items: list[SectionEnrichment]
                     ) -> tuple[str, Path]:
    """Write the items once (module text); (enrichment id, path). The same bytes again are a
    no-op; other bytes under the name are refused."""
    ordered = sorted(items, key=lambda i: _section_key(i.section))
    data = b"".join(_canonical(i.model_dump(mode="json")) for i in ordered)
    eid = hashlib.sha256(data).hexdigest()
    path = Path(store_path) / UNITS_DIR / snapshot / f"{ENRICHMENT_PREFIX}-{eid[:16]}.jsonl"
    _write_once(path, data, "enrichment file")
    return eid, path


def load_enrichment(store_path: Path, enrichment_id: str) -> list[SectionEnrichment]:
    """The items of the enrichment file whose SHA-256 is `enrichment_id`; UnitsError when no
    such file is there (or its bytes have another hash)."""
    if re.fullmatch(r"[0-9a-f]{64}", enrichment_id or ""):
        for path in sorted((Path(store_path) / UNITS_DIR).glob(
                f"*/{ENRICHMENT_PREFIX}-{enrichment_id[:16]}.jsonl")):
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() == enrichment_id:
                return [SectionEnrichment.model_validate_json(x) for x in data.splitlines()]
    raise UnitsError(f"no enrichment file {enrichment_id[:12]} under {store_path}/{UNITS_DIR}")


# -- the build -----------------------------------------------------------------------------------

def _body_field(g: Grounded) -> dict:
    return {"value": g.value,
            "quotes": [] if g.quote is None else [{"text": g.quote, "span": [g.start, g.end]}],
            "status": g.status if g.value is not None else None,
            "null_reason": None if g.value is not None else g.null_reason}


def apply(store: Store, cards: list[Unit], client, cfg: PassConfig) -> tuple[list[Unit], dict]:
    """(`cards` with the four fields and the lineage of each in-scope card filled from the
    pass, the manifest's record of the pass). In scope: the newest 33 CFR 117 version's cards
    of the binding sections; every other card is returned as it is (null `not_extracted`)."""
    check_config(cfg)
    tables_id = _needs_tables(store)
    sections = binding_sections(store, tables_id)
    doc = newest_doc(store)
    runs = {r.item.section: r for r in _runs(store, sections, doc, cards, client, cfg)}
    out = []
    for c in cards:
        r = next((runs[s] for s in runs if c.doc_id == doc and _in_section(c.canonical_ref, s)),
                 None)
        fields = r.item.cards.get(c.canonical_ref) if r is not None else None
        if fields is None:
            out.append(c)
            continue
        body = {**c.body, **{f: _body_field(fields[f]) for f in CARD_FIELDS}}
        lineage = Lineage(compiler=COMPILER_VERSION, prompt_version=cfg.prompt_version,
                          served_model=",".join(r.served) or None, cache_key_sha256=r.key)
        u = c.model_copy(update={"body": body, "lineage": lineage})
        out.append(u.model_copy(update={"hashes": {**u.hashes, "meta": meta_sha256(u)}}))
    info = {"prompt_version": cfg.prompt_version, "adapter": client.name,
            "model": getattr(client, "model", client.name), "max_tokens": MAX_TOKENS,
            "groups": cfg.groups, "specs": cfg.specs, "tables_id": tables_id,
            "sections": len(sections)}
    return out, info


# -- E2 (§6.3 check 5) ---------------------------------------------------------------------------

def _signal(d: DrawParams) -> bool | None:
    """Whether the draw opens on signal in at least one period (the Phase 3 question)."""
    if any(p.effect.value in ("on_signal", "notice_required") for p in d.periods) or \
            d.opening_basis.value in ("on_signal", "advance_notice"):
        return True
    return False if d.opening_basis.value == "closed_to_navigation" else None


def _windows(quotes: list[str | None]) -> set[Window] | None:
    """The windows the grammar reads in `quotes`; None when one is missing or unread."""
    out: set[Window] = set()
    for q in dict.fromkeys(quotes):
        ws = parse_windows(q) if isinstance(q, str) else None
        if ws is None:
            return None
        out.update(ws)
    return out


def _same(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return float(a) == float(b)


def _share(n: int, k: int) -> dict:
    return {"compared": n, "agree": k, "share": k / n if n else None}


def e2_agreement(items: list[SectionEnrichment], first_pass: list[RowRecord],
                 facts: list[ex.Facts]) -> dict:
    """Agreement of the enrichment's draw parameters with each Phase 3 pass: `notice_hours`,
    `opens_on_signal` (`_signal`) and the closed windows (the window grammar on the
    enrichment's window quotes and on the pass's closed-period quotes, compared as sets; a
    draw with an unread quote on either side is counted `unread`), over draws matched by
    bridge-name key then mile (`match_draws`, as Phase 3 E2). First-pass rows are those of the
    item's document and section; second-pass facts are found by the section text's SHA-256."""
    rows: dict[tuple[str, str], list[RowRecord]] = {}
    for r in first_pass:
        rows.setdefault((r.doc_id, r.row.get("section")), []).append(r)
    by_unit = {f.unit: f for f in facts}
    passes = ("first", "second")
    tally = {p: {"notice_hours": [0, 0], "opens_on_signal": [0, 0], "closed": [0, 0, 0],
                 "draws": Counter()} for p in passes}
    sections = Counter()
    for item in sorted(items, key=lambda i: _section_key(i.section)):
        if not item.draws:
            continue
        sections["compared"] += 1
        mine = [{"bridge": d.bridge.value, "mile": d.mile.value, "notice_hours":
                 d.notice_hours.value, "opens_on_signal": _signal(d),
                 "closed": [p.window_quote for p in d.periods
                            if p.effect.value == "need_not_open"]} for d in item.draws]
        first = sorted(rows.get((item.doc_id, item.section), []), key=lambda r: r.row["draw"])
        fact = by_unit.get(item.section_sha256)
        sections["no_first_pass"] += not first
        sections["no_second_pass"] += fact is None
        theirs = {
            "first": [{"bridge": r.row.get("bridge"), "mile": r.row.get("mile"),
                       "notice_hours": r.row.get("notice_hours"),
                       "opens_on_signal": r.row.get("opens_on_signal"),
                       "closed": [p.quote for p in r.prov.get("closed_periods") or []]
                       if r.row.get("closed_periods") else []} for r in first],
            "second": [{"bridge": d["bridge"].value if "bridge" in d else None,
                        "mile": d["mile"].value if "mile" in d else None,
                        "notice_hours": d["notice_hours"].value if "notice_hours" in d
                        else None,
                        "opens_on_signal": d["opens_on_signal"].value
                        if "opens_on_signal" in d else None,
                        "closed": [d["closed_periods"].quote]
                        if "closed_periods" in d and d["closed_periods"].value else []}
                       for d in (fact.draws if fact is not None else [])]}
        for p in passes:
            t = tally[p]
            for i, j in ex.match_draws(mine, theirs[p]):
                if i is None or j is None:
                    t["draws"]["pass_only" if i is None else "enrichment_only"] += 1
                    continue
                t["draws"]["matched"] += 1
                a, b = mine[i], theirs[p][j]
                for c in ("notice_hours", "opens_on_signal"):
                    t[c][0] += 1
                    t[c][1] += _same(a[c], b[c])
                wa = _windows(a["closed"]) if a["closed"] else set()
                wb = _windows(b["closed"]) if b["closed"] else set()
                if wa is None or wb is None:
                    t["closed"][2] += 1
                else:
                    t["closed"][0] += 1
                    t["closed"][1] += wa == wb
    out: dict = {}
    for p in passes:
        t = tally[p]
        out[p] = {"notice_hours": _share(*t["notice_hours"]),
                  "opens_on_signal": _share(*t["opens_on_signal"]),
                  "closed_windows": {**_share(*t["closed"][:2]), "unread": t["closed"][2]},
                  "draws": {k: t["draws"][k] for k in ("matched", "enrichment_only",
                                                       "pass_only")}}
    out["sections"] = {k: sections[k] for k in ("compared", "no_first_pass", "no_second_pass")}
    return out
