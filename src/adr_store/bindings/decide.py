"""The gate's decision (Phase 4 spec §12.6 steps 1-6, §12.7, §13.6; P5, P13, P15, P31-P35, P37,
P44; Task 18). One implementation, used by the gate process (`adr_store.gate.server`), by
`check_rules` (`adr_store.tools`) and by the binding tests (`checks.decide_bindings` and the B1
grid adapt `decide_values`). No z3, no store access, no clock.

**One draw** (`decide_values`, `decide_draw`; §12.6 for `schedule_opening`):
1. every selected binding is evaluated (strong Kleene, `dsl.evaluate`);
2. each forbid listed in the `overrides` of a True overriding basis is discarded;
3. a remaining True forbid that no Unknown overriding basis lists -> **deny**, naming the
   section-level refs of those forbids (`section_of`, "117.821", P34);
4. else a remaining Unknown forbid, or a True one an Unknown overriding basis lists ->
   **escalate**;
5. else a True basis (an overriding basis included, P32) -> **allow**;
6. else an Unknown basis -> **escalate**; no basis at all -> **escalate** ("no rule binding
   covers this call", P15).

**Missing facts** (the facts whose value would change the outcome): at step 4 the absent
required facts of the Unknown forbids among the unsure ones and of the Unknown overriding
bases that list an unsure forbid; a True forbid's absent facts count only when its value is
U, i.e. never (a True forbid stays True whatever its absent facts: Task 16's rule). At step 6
the absent required facts of the Unknown bases. Sorted and distinct.

**`next_allowed`** (`next_allowed`, the definition `reference.ref_next_allowed` shares): the
first minute after the requested one (seconds dropped), scanned minute by minute over seven
days, at which, after step 2, no forbid is True and a basis is True; an Unknown counts as
not True. It is not "the first minute the decision is allow": with notice unknown an
on-signal draw is next allowed at the end of its closed window. None when no such minute.

**A call** (`decide`): `args` define only the action judged; facts come only from `record`
(`{name: {"value", "source", ...}}`, read by `facts.derive_facts`; P13, P33).
- `schedule_opening(section, draw, open_at)`: the draw's bindings (`select`: target tool
  `schedule_opening`, selector `{section, draw}` with draws 1-based, `doc_id` the version of
  33 CFR 117 in force, P31) decided as above; a deny carries `next_allowed`.
- `deny_request(section, draw, requested_open_at, rule_id, reason)`: an opening of that draw
  at `requested_open_at` is decided as above. The deny is allowed only if that evaluation is a
  deny **and** `cited_sections(rule_id + " " + reason)` meets its deciding sections (P34);
  otherwise it is denied, with the evaluation's rule ids and deciding sections (denying an
  opening the rules allow is denied under the rules that allow it, § 117.5 among them).
- `escalate_request` and `cancel_opening`: allowed under the desk-policy system rules
  `adr.desk.escalate@1` and `adr.desk.cancel@1`.
Every decision carries at least one (rule id, version) (G1): the deciding bindings', or a
system rule's (`SYSTEM_RULES`; `no_binding` for a draw with no binding at all).

**Arguments** (`check_args`, N12): every gated call names its target `section` (a string) and
`draw` (a positive int, not a bool); `schedule_opening` adds `open_at`, `deny_request`
`requested_open_at`, `rule_id` and `reason`, `escalate_request` `missing` (strings) and
`reason`, `cancel_opening` `opening_id`; `request` (an id string) is optional on the first
three; times are naive ISO datetimes with a time. Any other key, a missing one or a wrong type
is a ValueError.

**Judging under an enforcement context** (`judge`, what the gate and `check_rules` call): the
loaded bindings, the 33 CFR 117 versions with their envelopes, and the sections that hold a
rule card in each version. Fail closed (P15) under `adr.gate.fail-closed@1`: an unknown tool,
malformed arguments or facts, no version in force on `as_of`, an unknown target (a section
with no rule card in the version in force), a selected binding that is not signed off, or any
exception while selecting or evaluating.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

from adr_store.bindings.dsl import Binding, Tri, Window, evaluate
from adr_store.bindings.facts import derive_facts, parse_local_datetime

__all__ = ["CITATION", "GATED", "SCAN_DAYS", "SYSTEM_RULES", "SYSTEM_TEXT", "Decision",
           "DrawDecision", "Enforcement", "Evaluated", "check_args", "cited_sections",
           "decide", "decide_draw", "decide_values", "fail_closed", "judge", "next_allowed",
           "parse_as_of", "prepared", "section_of", "select"]

SYSTEM_RULES = {"fail_closed": ("adr.gate.fail-closed@1", "1"),
                "escalate": ("adr.desk.escalate@1", "1"),
                "cancel": ("adr.desk.cancel@1", "1"),
                "no_binding": ("adr.gate.no-binding@1", "1")}
SYSTEM_TEXT = {
    "adr.gate.fail-closed@1": "The gate denies any call it cannot judge: a malformed request, "
                              "an unknown tool or target, bindings that do not verify, a stale "
                              "units id, or a failure on the enforcement path (P15).",
    "adr.desk.escalate@1": "Desk policy: an escalation is always allowed and logged.",
    "adr.desk.cancel@1": "Desk policy: cancelling an opening is always allowed and logged.",
    "adr.gate.no-binding@1": "No rule binding covers this call: no basis is not permission, so "
                             "the call is escalated (P15).",
}
CITATION = re.compile(r"(?<!mile )(?<![\w.])(?:33\s*c\.?\s*f\.?\s*r\.?\s*(?:§+\s*)?|§+\s*)?"
                      r"117\.(\d{1,4})(?:\([a-z0-9]{1,4}\))*(?!\.?\d)", re.IGNORECASE)
GATED = ("schedule_opening", "deny_request", "escalate_request", "cancel_opening")
OPENING_TOOL = "schedule_opening"
SCAN_DAYS = 7
CHAIN = "ecfr:33:117"
_SECTION = re.compile(r"CFR\s+(\d+\.\d+)")
_WS = re.compile(r"\s+")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# per tool: (required keys and their kinds, optional keys and their kinds)
_ARGS = {
    "schedule_opening": ({"section": "section", "draw": "draw", "open_at": "time"},
                         {"request": "str"}),
    "deny_request": ({"section": "section", "draw": "draw", "requested_open_at": "time",
                      "rule_id": "str", "reason": "str"}, {"request": "str"}),
    "escalate_request": ({"section": "section", "draw": "draw", "missing": "strs",
                          "reason": "str"}, {"request": "str"}),
    "cancel_opening": ({"section": "section", "draw": "draw", "opening_id": "str"}, {}),
}


@dataclass(frozen=True)
class Evaluated:
    binding_id: str
    binding_version: str
    rule_id: str
    rule_version: str
    doc_id: str
    value: str                      # "T", "F" or "U"


@dataclass(frozen=True)
class Decision:
    outcome: Literal["allow", "deny", "escalate"]
    rule_ids: list[tuple[str, str]]          # (rule_id, rule_version), sorted, distinct, >= 1
    deciding_sections: list[str]
    missing_facts: list[str]
    next_allowed: str | None
    evaluated: list[Evaluated]
    message: str
    fail_closed: str | None = None           # why the call failed closed, when it did
    sources: dict[str, str] = field(default_factory=dict)   # rule_id -> doc_id of its binding

    @property
    def message_sha256(self) -> str:
        return hashlib.sha256(self.message.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DrawDecision:
    """The decision over one draw's bindings: the outcome, the deciding sections (deny), the
    missing facts (escalate) and the bindings that decided (deny: the True forbids; escalate:
    the unsure forbids and the Unknown overriding bases listing them, or the Unknown bases;
    allow: the True bases)."""

    outcome: Literal["allow", "deny", "escalate"]
    sections: frozenset[str]
    missing: tuple[str, ...]
    deciding: tuple[Binding, ...] = ()


# -- citations and sections ------------------------------------------------------------------------

def section_of(rule_id: str) -> str:
    """The section-level ref of a rule id ("33 CFR 117.821(a)" -> "117.821", P34)."""
    m = _SECTION.search(rule_id)
    return m[1] if m else rule_id


def cited_sections(text: str) -> set[str]:
    """The section keys "117.<n>" that `text` cites by the citation rule of §13.6 (P34): the
    text NFKC-normalised with whitespace collapsed, every match of `CITATION`."""
    norm = _WS.sub(" ", unicodedata.normalize("NFKC", text))
    return {f"117.{m[1]}" for m in CITATION.finditer(norm)}


# -- one draw (§12.6 steps 1-6) --------------------------------------------------------------------

def prepared(e: Any) -> Any:
    """`e` with its windows as `Window` objects (validated once, not at every evaluation)."""
    if isinstance(e, list):
        return [prepared(x) for x in e]
    if not isinstance(e, dict):
        return e
    return {k: (Window.model_validate(v) if k == "window" and isinstance(v, dict) else
                prepared(v)) for k, v in e.items()}


def _absent(b: Binding, facts: dict) -> set[str]:
    return {f for f in b.required_facts if facts.get(f) is None}


def decide_values(bindings: list[Binding], values: dict[str, Tri], facts: dict
                  ) -> DrawDecision:
    """Steps 2-6 of §12.6 over one draw's bindings and their values (module text)."""
    forbids = [b for b in bindings if b.effect == "forbid"]
    bases = [b for b in bindings if b.effect == "basis"]
    overriding = [b for b in bases if b.overrides]
    discarded = {f for o in overriding if values[o.binding_id] is Tri.T for f in o.overrides}
    remaining = [f for f in forbids if f.binding_id not in discarded]
    unknown_over = [o for o in overriding if values[o.binding_id] is Tri.U]
    listed = {f for o in unknown_over for f in o.overrides}
    deny = [f for f in remaining if values[f.binding_id] is Tri.T and f.binding_id not in listed]
    if deny:
        return DrawDecision("deny", frozenset(section_of(f.rule_id) for f in deny), (),
                            tuple(deny))
    unsure = [f for f in remaining if values[f.binding_id] is Tri.U
              or (values[f.binding_id] is Tri.T and f.binding_id in listed)]
    if unsure:
        ids = {f.binding_id for f in unsure}
        over = [o for o in unknown_over if ids & set(o.overrides)]
        # a True forbid stays True whatever its absent facts: only an Unknown one's count
        missing = set().union(*(_absent(f, facts) for f in unsure
                                if values[f.binding_id] is Tri.U),
                              *(_absent(o, facts) for o in over))
        return DrawDecision("escalate", frozenset(), tuple(sorted(missing)),
                            tuple(unsure + over))
    true_bases = [b for b in bases if values[b.binding_id] is Tri.T]
    if true_bases:
        return DrawDecision("allow", frozenset(), (), tuple(true_bases))
    unknown = [b for b in bases if values[b.binding_id] is Tri.U]
    return DrawDecision("escalate", frozenset(),
                        tuple(sorted(set().union(*(_absent(b, facts) for b in unknown)))),
                        tuple(unknown))


def _values(bindings: list[Binding], facts: dict, whens: dict | None = None) -> dict[str, Tri]:
    whens = whens or {}
    return {b.binding_id: evaluate(whens.get(b.binding_id, b.when), facts) for b in bindings}


def decide_draw(bindings: list[Binding], facts: dict) -> DrawDecision:
    """§12.6 steps 1-6 over one draw's bindings on derived `facts`. Exceptions propagate (the
    caller fails closed)."""
    return decide_values(bindings, _values(bindings, facts), facts)


def _next_ok(bindings: list[Binding], values: dict[str, Tri]) -> bool:
    discarded = {f for b in bindings if b.effect == "basis" and b.overrides
                 and values[b.binding_id] is Tri.T for f in b.overrides}
    if any(b.effect == "forbid" and b.binding_id not in discarded
           and values[b.binding_id] is Tri.T for b in bindings):
        return False
    return any(b.effect == "basis" and values[b.binding_id] is Tri.T for b in bindings)


def next_allowed(selected: list[Binding], open_at: datetime, record: dict) -> datetime | None:
    """The first minute after `open_at` within seven days at which no forbid is True and a
    basis is True (module text); None when there is none. ValueError for a malformed
    record."""
    whens = {b.binding_id: prepared(b.when) for b in selected}
    start = open_at.replace(second=0, microsecond=0)
    for k in range(1, SCAN_DAYS * 1440 + 1):
        at = start + timedelta(minutes=k)
        if _next_ok(selected, _values(selected, derive_facts(at, record), whens)):
            return at
    return None


# -- a call ----------------------------------------------------------------------------------------

def _kind_problem(kind: str, v: Any) -> str | None:
    if kind == "str":
        return None if isinstance(v, str) else "a string"
    if kind == "section":
        return None if isinstance(v, str) and v.strip() else "a non-empty string"
    if kind == "draw":
        return None if type(v) is int and v >= 1 else "a positive int (draws are 1-based)"
    if kind == "strs":
        return None if isinstance(v, list) and all(isinstance(x, str) for x in v) else \
            "a list of strings"
    return None if parse_local_datetime(v) is not None else \
        "a naive ISO datetime with a time"


def check_args(tool: str, args: object) -> None:
    """ValueError naming the first problem of `args` for `tool` (module text)."""
    if tool not in _ARGS:
        raise ValueError(f"unknown tool {tool!r}")
    if not isinstance(args, dict):
        raise ValueError("args must be an object")
    required, optional = _ARGS[tool]
    extra = sorted(str(k) for k in args if k not in required and k not in optional)
    if extra:
        raise ValueError(f"{tool}: unknown argument(s) {', '.join(extra)}")
    for k, kind in {**required, **optional}.items():
        if k not in args:
            if k in required:
                raise ValueError(f"{tool}: missing argument {k}")
            continue
        problem = _kind_problem(kind, args[k])
        if problem:
            raise ValueError(f"{tool}: {k} must be {problem}")


def select(bindings: list[Binding], tool: str, args: dict, doc_in_force: str) -> list[Binding]:
    """The bindings judging the opening `tool` acts on: target tool `schedule_opening` with
    selector `{section, draw}` of `args`, of the document version `doc_in_force` (P31);
    bindings of other versions are never selected."""
    if tool not in GATED:
        raise ValueError(f"unknown tool {tool!r}")
    want = {"tool": OPENING_TOOL, "selector": {"section": args["section"],
                                               "draw": args["draw"]}}
    return [b for b in bindings if b.doc_id == doc_in_force and b.target == want]


def _rule_ids(bs) -> list[tuple[str, str]]:
    return sorted({(b.rule_id, b.rule_version) for b in bs})


def _evaluated(selected: list[Binding], values: dict[str, Tri]) -> list[Evaluated]:
    return [Evaluated(b.binding_id, b.binding_version, b.rule_id, b.rule_version, b.doc_id,
                      values[b.binding_id].value)
            for b in sorted(selected, key=lambda b: b.binding_id)]


def _message(outcome: str, rule_ids, sections, missing, nxt: str | None, why: str) -> str:
    parts = [f"{outcome}: {why}", "rules " + ", ".join(f"{r}@{v}" for r, v in rule_ids)]
    if sections:
        parts.append("deciding sections " + ", ".join(f"§ {s}" for s in sections))
    if missing:
        parts.append("missing facts " + ", ".join(missing))
    if nxt is not None:
        parts.append(f"next allowed {nxt}")
    return "; ".join(parts)


def _system(outcome: str, key: str, why: str, evaluated=(), *, failed: str | None = None
            ) -> Decision:
    rule = SYSTEM_RULES[key]
    return Decision(outcome, [rule], [], [], None, list(evaluated),
                    _message(outcome, [rule], [], [], None, why), failed)


def fail_closed(why: str) -> Decision:
    """A deny under `adr.gate.fail-closed@1` (P15), saying why."""
    return _system("deny", "fail_closed", f"fail closed: {why}", failed=why)


def _opening(selected: list[Binding], open_at: datetime, record: dict
             ) -> tuple[DrawDecision, dict[str, Tri], str | None]:
    facts = derive_facts(open_at, record)
    whens = {b.binding_id: prepared(b.when) for b in selected}
    values = _values(selected, facts, whens)
    d = decide_values(selected, values, facts)
    nxt = None
    if d.outcome == "deny":
        found = next_allowed(selected, open_at, record)
        nxt = None if found is None else found.isoformat()
    return d, values, nxt


def _of_draw(d: DrawDecision, selected, values, nxt, outcome=None, why=None) -> Decision:
    if not selected:
        rules = [SYSTEM_RULES["no_binding"]]
    else:
        rules = _rule_ids(d.deciding) or _rule_ids(selected)
    outcome = outcome or d.outcome
    sections = sorted(d.sections)
    missing = list(d.missing)
    why = why or {"deny": "a forbid holds", "allow": "a basis holds",
                  "escalate": "a needed fact is missing" if d.deciding else
                  "no rule binding covers this call"}[d.outcome]
    return Decision(outcome, rules, sections, missing, nxt, _evaluated(selected, values),
                    _message(outcome, rules, sections, missing, nxt, why),
                    sources={b.rule_id: b.doc_id for b in selected})


def decide(tool: str, args: dict, record: dict, bindings: list[Binding], doc_in_force: str
           ) -> Decision:
    """The decision on one gated call (module text). `args` are checked (`check_args`);
    ValueError for malformed arguments or record, and whatever evaluation raises (the caller
    fails closed)."""
    check_args(tool, args)
    if tool == "escalate_request":
        return _system("allow", "escalate", "escalations are always allowed and logged")
    if tool == "cancel_opening":
        return _system("allow", "cancel", "cancellations are always allowed and logged")
    selected = select(bindings, tool, args, doc_in_force)
    if tool == OPENING_TOOL:
        d, values, nxt = _opening(selected, parse_local_datetime(args["open_at"]), record)
        return _of_draw(d, selected, values, nxt)
    d, values, nxt = _opening(selected, parse_local_datetime(args["requested_open_at"]),
                              record)
    cited = cited_sections(f"{args['rule_id']} {args['reason']}")
    if d.outcome == "deny" and cited & d.sections:
        return _of_draw(d, selected, values, nxt, "allow",
                        "the opening is denied and the call cites a deciding section")
    why = ("the call cites no deciding section" if d.outcome == "deny" else
           f"an opening at the requested time is not denied ({d.outcome})")
    return _of_draw(d, selected, values, nxt, "deny", why)


# -- judging under an enforcement context ----------------------------------------------------------

@dataclass(frozen=True)
class Enforcement:
    """What a call is judged against: the loaded bindings (id, units id, snapshot), the
    envelopes of the 33 CFR 117 versions (`applicability.Envelope`), the sections holding a
    rule card in each version, and each card's text by (rule id, doc id)."""

    bindings_id: str
    units_id: str
    snapshot: str
    bindings: tuple[Binding, ...]
    envelopes: dict
    sections: dict[str, frozenset[str]]
    texts: dict[tuple[str, str], str]

    def doc_in_force(self, as_of: date | None) -> str | None:
        """The one 33 CFR 117 version in force on `as_of` (None: the one not superseded), or
        None when there is not exactly one."""
        from adr_store.applicability import Filters, admits

        f = Filters(as_of=as_of)
        found = sorted(d for d, env in self.envelopes.items() if admits(env, f))
        return found[0] if len(found) == 1 else None


def parse_as_of(value: object) -> date | None:
    """`as_of` (an ISO date, or a naive ISO datetime: its date) as a date; None for None.
    ValueError otherwise."""
    if value is None:
        return None
    if isinstance(value, str):
        at = parse_local_datetime(value)
        if at is not None:
            return at.date()
        if _DATE.fullmatch(value):
            try:
                return date.fromisoformat(value)
            except ValueError:
                pass
    raise ValueError(f"as_of {str(value)[:40]!r} is not an ISO date or naive datetime")


def _check_record(record: object) -> None:
    if not isinstance(record, dict):
        raise ValueError("facts must be an object")
    for name, entry in record.items():
        if not isinstance(name, str) or not isinstance(entry, dict) or "value" not in entry:
            raise ValueError(f"fact {str(name)[:40]!r} is not an object with a value")


def judge(enf: Enforcement, tool: object, args: object, record: object, as_of: object
          ) -> Decision:
    """The decision on a call under `enf` (module text): `decide`, or a fail-closed deny. Never
    raises."""
    try:
        if tool not in GATED:
            return fail_closed(f"unknown tool {str(tool)[:40]!r}")
        try:
            check_args(tool, args)
            _check_record(record)
            day = parse_as_of(as_of)
        except ValueError as e:
            return fail_closed(f"malformed request: {e}")
        doc = enf.doc_in_force(day)
        if doc is None:
            return fail_closed("no single version of 33 CFR 117 is in force on "
                               f"{day.isoformat() if day else 'today'}")
        if args["section"] not in enf.sections.get(doc, frozenset()):
            return fail_closed(f"unknown target: § {args['section'][:20]} has no rule card in "
                               f"the version in force")
        selected = select(list(enf.bindings), tool, args, doc)
        unsigned = [b.binding_id[:12] for b in selected if b.status != "signed_off"]
        if unsigned:
            return fail_closed(f"binding(s) without sign-off: {', '.join(unsigned)}")
        try:
            return decide(tool, args, record, list(enf.bindings), doc)
        except ValueError as e:
            return fail_closed(f"malformed request: {e}")
    except Exception as e:  # noqa: BLE001 - any failure on the enforcement path denies (P15)
        return fail_closed(f"error: {type(e).__name__}: {str(e)[:120]}")

