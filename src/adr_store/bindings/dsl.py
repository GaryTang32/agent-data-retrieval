"""The binding language `adr-dsl@1` (Phase 4 spec §12.1): a binding is canonical JSON whose
`when` is an expression over typed facts, evaluated with strong Kleene logic.

- **Constructs** (and nothing else; `check_expr` refuses the rest, recursively, naming the path
  of each problem):
  `{"and": [e, ...]}`, `{"or": [e, ...]}` (non-empty lists), `{"not": e}`,
  `{"cmp": [fact, op, int]}` (op one of `<`, `<=`, `>`, `>=`, `==`, `!=`; the comparand an int,
  never a bool), `{"eq": [fact, str | bool]}` (an enum, or a bool fact as a two-valued enum,
  e.g. `local_procedure_conflict`), `{"in": [fact, [str, ...]]}`,
  `{"in_window": {"fact": "open_at"}, "window": Window}`, `{"known": fact}`,
  `{"const": bool}`.
- **Three values.** A fact that is missing, null or not of the construct's type (a str where
  `cmp` needs an int, a bool where `eq` names a str) is no value, and the leaf reading it is
  Unknown. `known` is never Unknown: it is T for a present value some construct can read (an
  int, a str or a bool) and F otherwise, so it is F exactly where every leaf on the fact is U.
  `and`, `or` and `not` follow the strong Kleene tables: `and` is F if any operand is F, else U
  if any is U, else T; `or` is the dual; `not U` is U.
- **Windows** are half-open minute ranges `[start, end)` of a day (0–1440; `start > end`
  crosses midnight; 0–1440 is the whole day), a set of weekdays, an optional exception for
  federal holidays and an optional inclusive month-day range that may wrap the year end. A
  window that crosses midnight belongs to the night that starts on a listed day (P44): minutes
  in `[start, 1440)` are judged on their own calendar day, minutes in `[0, end)` on the day
  before, for the weekdays, the holiday exception and the date range alike. `in_window` on the
  fact `open_at` (a naive ISO datetime with a time, as `derive_facts` writes it) computes the
  minute, the day and the day before from it, holidays by `facts.is_federal_holiday`; a
  missing or malformed `open_at` is Unknown.
- **Ids.** `binding_ids` hashes the canonical JSON (sorted keys, no padding, UTF-8) of the
  identity fields (`rule_id`, `rule_version`, `doc_id`, `target`, `effect`) into the
  `binding_id`, and of the logic (the language, `when`, and `overrides` as a sorted set) into
  the `binding_version`. `Binding` checks that its ids and `required_facts` are those of its
  own content. A changed condition is a new version of the same binding; a changed
  rule, document version, target or effect is a different binding. The identity holds no
  ordinal, so a compiler emits at most one binding per identity (two windows of one rule
  paragraph and effect are one `or`).
"""

from __future__ import annotations

import hashlib
import json
import operator
import re
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from adr_store.bindings.facts import DAYS, is_federal_holiday, parse_local_datetime

LANGUAGE = "adr-dsl@1"
# the same literal as `adr_store.units.envelope.BindingStatus` (a test pins it); declared here
# so the gate's evaluator imports nothing beyond the standard library and pydantic
BindingStatus = Literal["proposed", "tested", "analysed", "signed_off", "rejected"]
Expr = dict
CONSTRUCTS = ("and", "or", "not", "cmp", "eq", "in", "in_window", "known", "const")
OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge,
       "==": operator.eq, "!=": operator.ne}
TIME_FACT = "open_at"
IDENTITY_FIELDS = ("rule_id", "rule_version", "doc_id", "target", "effect")
LOGIC_FIELDS = ("when", "overrides")
_MONTH_DAYS = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_MD = re.compile(r"(\d{2})-(\d{2})")


class Tri(Enum):
    T = "T"
    F = "F"
    U = "U"


def is_month_day(s: object) -> bool:
    """`s` is "MM-DD" naming a calendar day (29 February included)."""
    m = _MD.fullmatch(s) if isinstance(s, str) else None
    return bool(m) and 1 <= int(m[1]) <= 12 and 1 <= int(m[2]) <= _MONTH_DAYS[int(m[1]) - 1]


class Window(BaseModel):
    """A half-open window of minutes `[start, end)`, on some weekdays, optionally not on federal
    holidays, optionally within an inclusive month-day range (which may wrap the year end)."""

    model_config = ConfigDict(frozen=True, extra="forbid", title="Window")

    start: StrictInt = Field(ge=0, le=1439)
    end: StrictInt = Field(ge=1, le=1440)
    days: tuple[StrictStr, ...]
    except_federal_holidays: StrictBool
    date_from: StrictStr | None
    date_to: StrictStr | None

    @field_validator("days")
    @classmethod
    def _days(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v or any(d not in DAYS for d in v) or \
                [DAYS.index(d) for d in v] != sorted({DAYS.index(d) for d in v}):
            raise ValueError(f"days must be distinct names from {DAYS}, in that order")
        return v

    @field_validator("date_from", "date_to")
    @classmethod
    def _month_day(cls, v: str | None) -> str | None:
        if v is not None and not is_month_day(v):
            raise ValueError(f"{v!r} is not a calendar day written MM-DD")
        return v

    @model_validator(mode="after")
    def _shape(self) -> Window:
        if self.start == self.end:
            raise ValueError(f"start {self.start} equals end {self.end}: an empty window")
        if (self.date_from is None) != (self.date_to is None):
            raise ValueError("date_from and date_to are both set or both null")
        return self


def _admits(w: Window, day: date) -> bool:
    """Whether `w`'s weekdays, holiday exception and date range admit the calendar day `day`."""
    if DAYS[day.weekday()] not in w.days or (w.except_federal_holidays
                                             and is_federal_holiday(day)):
        return False
    if w.date_from is not None and w.date_to is not None:
        md = f"{day.month:02d}-{day.day:02d}"
        if w.date_from <= w.date_to:
            return w.date_from <= md <= w.date_to
        return not w.date_to < md < w.date_from
    return True


def in_window(w: Window, minute: int, day: date) -> bool:
    """Whether minute `minute` of the calendar day `day` lies in `w`. The minutes after midnight
    of a window that crosses midnight are judged on the day before (P44). ValueError for inputs
    outside their domain (a datetime is not a day)."""
    if type(minute) is not int or not 0 <= minute < 1440:
        raise ValueError(f"minute {minute!r} is not in 0..1439")
    if not isinstance(day, date) or isinstance(day, datetime):
        raise ValueError(f"day {day!r} is not a date")
    if w.start < w.end:
        return w.start <= minute < w.end and _admits(w, day)
    if minute >= w.start:
        return _admits(w, day)
    return minute < w.end and _admits(w, day - timedelta(days=1))


# -- checking --------------------------------------------------------------------------------

def _is_fact(f: object) -> bool:
    return isinstance(f, str) and bool(f)


def _validation_text(err: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" if e["loc"] else e["msg"]
                     for e in err.errors())


def check_expr(e: Expr) -> list[str]:
    """The problems of `e` as an `adr-dsl@1` expression, [] when it is one: only the constructs
    above, each with its arity and types, recursively. A nested problem names its path
    ("and[1].or[0]: cmp: unknown operator '=>'")."""
    return _check(e, "")


def _check(e: Any, path: str) -> list[str]:
    out: list[str] = []

    def problem(msg: str) -> None:
        out.append(f"{path}: {msg}" if path else msg)

    if not isinstance(e, dict):
        problem(f"expression must be an object, got {type(e).__name__}")
        return out
    if not e:
        problem("empty expression")
        return out
    unknown = sorted((k for k in e if k not in CONSTRUCTS and k != "window"), key=str)
    for k in unknown:
        problem(f"unknown construct {k!r}")
    if unknown:
        return out
    names = sorted(k for k in e if k in CONSTRUCTS)
    if len(names) > 1:
        problem(f"more than one construct: {', '.join(names)}")
        return out
    if not names or ("window" in e and names != ["in_window"]):
        problem("'window' outside in_window")
        return out
    (op,) = names
    arg = e[op]
    child = f"{path}.{op}" if path else op
    if op in ("and", "or"):
        if not isinstance(arg, list) or not arg:
            problem(f"{op}: expects a non-empty list of expressions")
        else:
            for i, x in enumerate(arg):
                out += _check(x, f"{child}[{i}]")
    elif op == "not":
        if isinstance(arg, dict):
            out += _check(arg, child)
        else:
            problem("not: expects one expression")
    elif op == "cmp":
        if not (isinstance(arg, list) and len(arg) == 3):
            problem("cmp: expects [fact, op, int]")
        else:
            fact, o, v = arg
            if not _is_fact(fact):
                problem("cmp: fact must be a non-empty string")
            if not isinstance(o, str) or o not in OPS:
                problem(f"cmp: unknown operator {o!r}")
            if type(v) is not int:
                problem(f"cmp: comparand must be an int, got {type(v).__name__}")
    elif op == "eq":
        if not (isinstance(arg, list) and len(arg) == 2):
            problem("eq: expects [fact, str or bool]")
        else:
            if not _is_fact(arg[0]):
                problem("eq: fact must be a non-empty string")
            if type(arg[1]) not in (str, bool):
                problem(f"eq: comparand must be a str or a bool, got {type(arg[1]).__name__}")
    elif op == "in":
        if not (isinstance(arg, list) and len(arg) == 2 and isinstance(arg[1], list) and arg[1]
                and all(type(x) is str for x in arg[1])):
            problem("in: expects [fact, [str, ...]]")
        elif not _is_fact(arg[0]):
            problem("in: fact must be a non-empty string")
    elif op == "known":
        if not _is_fact(arg):
            problem("known: fact must be a non-empty string")
    elif op == "const":
        if type(arg) is not bool:
            problem("const: expects a bool")
    else:  # in_window
        if arg != {"fact": TIME_FACT}:
            problem(f'in_window: expects {{"fact": "{TIME_FACT}"}}')
        if "window" not in e:
            problem("in_window: needs a window")
        elif not isinstance(e["window"], Window):
            try:
                Window.model_validate(e["window"])
            except ValidationError as err:
                problem(f"in_window.window: {_validation_text(err)}")
    return out


# -- evaluation ------------------------------------------------------------------------------

def evaluate(e: Expr, facts: dict[str, Any]) -> Tri:
    """The strong Kleene value of `e` over `facts`. ValueError when `e` is not an `adr-dsl@1`
    expression (`check_expr`)."""
    problems = check_expr(e)
    if problems:
        raise ValueError("; ".join(problems))
    return _eval(e, facts)


def _tri(b: bool) -> Tri:
    return Tri.T if b else Tri.F


def _eval(e: Expr, facts: dict[str, Any]) -> Tri:
    op = next(k for k in e if k != "window")
    arg = e[op]
    if op == "and":
        vals = [_eval(x, facts) for x in arg]
        return Tri.F if Tri.F in vals else Tri.U if Tri.U in vals else Tri.T
    if op == "or":
        vals = [_eval(x, facts) for x in arg]
        return Tri.T if Tri.T in vals else Tri.U if Tri.U in vals else Tri.F
    if op == "not":
        v = _eval(arg, facts)
        return Tri.U if v is Tri.U else _tri(v is Tri.F)
    if op == "cmp":
        fact, o, c = arg
        v = facts.get(fact)
        return Tri.U if type(v) is not int else _tri(OPS[o](v, c))
    if op == "eq":
        v = facts.get(arg[0])
        return Tri.U if type(v) is not type(arg[1]) else _tri(v == arg[1])
    if op == "in":
        v = facts.get(arg[0])
        return Tri.U if type(v) is not str else _tri(v in arg[1])
    if op == "known":
        return _tri(type(facts.get(arg)) in (int, str, bool))
    if op == "const":
        return _tri(arg)
    w = e["window"] if isinstance(e["window"], Window) else Window.model_validate(e["window"])
    at = parse_local_datetime(facts.get(arg["fact"]))
    if at is None:
        return Tri.U
    return _tri(in_window(w, at.hour * 60 + at.minute, at.date()))


def required_facts(e: Expr) -> list[str]:
    """The facts `e` reads, sorted and distinct (`open_at` for a window). ValueError when `e`
    is not an `adr-dsl@1` expression."""
    problems = check_expr(e)
    if problems:
        raise ValueError("; ".join(problems))
    found: set[str] = set()

    def walk(x: Expr) -> None:
        op = next(k for k in x if k != "window")
        arg = x[op]
        if op in ("and", "or"):
            for y in arg:
                walk(y)
        elif op == "not":
            walk(arg)
        elif op in ("cmp", "eq", "in"):
            found.add(arg[0])
        elif op == "known":
            found.add(arg)
        elif op == "in_window":
            found.add(arg["fact"])

    walk(e)
    return sorted(found)


# -- ids -------------------------------------------------------------------------------------

def _json_default(o: Any) -> Any:
    if isinstance(o, BaseModel):
        return o.model_dump(mode="json")
    raise TypeError(f"{type(o).__name__} is not JSON")


def _sha256_canonical(obj: Any) -> str:
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      default=_json_default)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def binding_ids(core: dict) -> tuple[str, str]:
    """(binding_id, binding_version): the SHA-256 of the canonical JSON of the identity fields,
    and of the logic (language, `when`, `overrides` sorted and distinct). Other keys of `core`
    are ignored; `overrides` defaults to none. ValueError when an identity field or `when` is
    missing."""
    missing = [k for k in (*IDENTITY_FIELDS, "when") if k not in core]
    if missing:
        raise ValueError(f"binding core lacks {', '.join(missing)}")
    identity = {k: core[k] for k in IDENTITY_FIELDS}
    logic = {"language": LANGUAGE, "when": core["when"],
             "overrides": sorted(set(core.get("overrides") or []))}
    return _sha256_canonical(identity), _sha256_canonical(logic)


# -- the binding -----------------------------------------------------------------------------

class Binding(BaseModel):
    """One binding (§12.1). `when` must be an `adr-dsl@1` expression; `binding_id`,
    `binding_version` and `required_facts` must be those of the binding's own content
    (`binding_ids`, `required_facts(when)`); only a `basis` may carry `overrides` (the `forbid`s
    it sets aside when True, P32)."""

    model_config = ConfigDict(extra="forbid", title="Binding")

    binding_id: str
    binding_version: str
    rule_id: str
    rule_version: str
    doc_id: str
    target: dict
    effect: Literal["forbid", "basis"]
    when: Expr
    overrides: list[str] = Field(default_factory=list)
    required_facts: list[str]
    derivation: str
    params_prov: dict
    tests: list[dict] = Field(default_factory=list)
    analysis: dict = Field(default_factory=dict)
    review: dict = Field(default_factory=dict)
    status: BindingStatus
    verifier: str | None = None

    @model_validator(mode="after")
    def _valid(self) -> Binding:
        problems = check_expr(self.when)
        if problems:
            raise ValueError(f"when: {'; '.join(problems)}")
        if self.effect == "forbid" and self.overrides:
            raise ValueError("overrides: only a basis overrides forbids")
        bid, version = binding_ids(self.model_dump())
        if self.binding_id != bid:
            raise ValueError(f"binding_id {self.binding_id!r} is not {bid} (from the identity)")
        if self.binding_version != version:
            raise ValueError(f"binding_version {self.binding_version!r} is not {version} "
                             "(from the logic)")
        wanted = required_facts(self.when)
        if self.required_facts != wanted:
            raise ValueError(f"required_facts {self.required_facts} is not {wanted}")
        return self
