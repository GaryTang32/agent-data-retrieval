"""The procedure runtime, the desk procedure `desk-request@1` and the per-profile flag (Phase 4
spec §9.3, §13.2, §13.5, §17 A4; P17, P50, P51; builder note 19; preflight N9, N13; Task 21).
No model call, no clock.

**What a `Runtime` enforces.** It holds one procedure IR (`ProcedureBody`, Task 4) and its
active step, the first step at the start. It enforces bodies made of `tool_call`, `condition`
and `end` steps: a body `validate_ir` refuses, a step of another type, a `tool_call` without a
tool or with other than one unguarded successor, a guard or precondition that is no
`adr-dsl@1` expression, or an `args_schema` outside the form below is a ValueError.

- `allows(tool, args, facts)`: a read-only tool (`READ_ONLY`) is always allowed. A
  side-effecting tool is allowed only when the active step is a `tool_call` naming it, the
  step needs no approval (the simulation has no approval channel, so a step that needs one
  refuses), every precondition is True under strong Kleene logic (`dsl.evaluate`: Unknown
  refuses, as False does) and the arguments match the step's `args_schema`. The
  preconditions read `facts` (the request record, bare values or `{"value", ...}` objects)
  over what the runtime learned from the results on its path (`learned`); the record wins a
  name both hold. A refusal is `(False, refusal)`: a deny under `adr.runtime.refused@1`
  (`REFUSED`, distinct from every gate rule id) with the active step, the tools allowed there
  (`allowed_tools`) and the step's text (`step_text`). Nothing executes and nothing advances.
- `advance(tool, result, args)`: called with each executed call's result (a refused call is
  never passed). The call advances only when the active step is a `tool_call` naming its tool
  and its arguments match the step's `args_schema`; any other call (a read off the procedure)
  leaves the step as it is. The runtime goes to the step's successor; at a condition step it
  takes the one edge whose guard is True over **the facts of this last result**
  (`result_facts`), and on through condition steps until a step that is none. When no guard
  is True, or more than one is (an Unknown guard counts as not True), the runtime **stays on
  the tool_call step**: side effects stay refused there and the agent may call the step's tool
  again. So a `check_rules` result whose `outcome` is missing or malformed (absent, null, not a
  string, or none of allow, deny, escalate) fails closed: the runtime stays on s2. Only when
  it moves are the result's facts added to `learned`, replacing the facts the same tool gave
  before (a `check_rules` result replaces `outcome`, `next_allowed` and `missing_facts` as a
  group, so a null `next_allowed` is not taken from an earlier check). A `tool_call` step with
  nothing to ask (`ask_missing`, below, gives no field) is passed as an unknown answer: the
  runtime goes on as if the question had been asked and the user did not know (s9 -> s11).
- `result_facts(tool, result)`: `check_rules` gives `outcome` and `next_allowed` (strings only) and
  `missing_facts` (a list of strings); `ask_user` gives `fact_learned` (the result's `learned`,
  which the environment adds: whether the user knew the answer) and, when it is True, the field's
  value under the field's name (`accepts_alternative`; the result's `value`, which the environment
  adds from the record); every other tool gives none.

**`args_schema`** (free in the IR, §5.3; the runtime reads this form, P53; every path is
dotted into the arguments):
- `{"const": {path: value}}`: the argument must equal the value (s2's `intent.tool` is
  `schedule_opening`, s5's `field` is `accepts_alternative`);
- `{"from_request": {path: request field}}`: the argument must equal that field of the request
  the runtime is bound to (`bind`, which the environment calls with the task's request; an
  unbound runtime refuses). s2's `intent.args.{request,section,draw,open_at}` are the
  request's `id`, `section`, `draw` and `requested_open_at`; so are s4's
  `{request,section,draw,open_at}`; s7's `{request,section,draw}`; s8's and s11's `request`;
- `{"from_result": {path: fact}}`: the argument must equal a string fact the runtime learned
  (s7's `open_at` is the `next_allowed` of the last `check_rules`; refused while none is);
- `{"ask_missing": {path: {missing fact: user field or null}}}`: the argument must be the
  user's field of one of the last `check_rules` result's `missing_facts` (s9: `notice_minutes`
  -> `notice_received_at`, `vessel_class` -> `vessel_class`, `local_procedure_conflict` ->
  none, the environment writes it). Another question stays allowed (a read) but does not
  advance; when no missing fact has a user field, the step is passed as unknown.

**`desk-request@1`** (`config/sim/desk-request.json`, P17: authored as part of the environment,
`source_kind: "authored"`, no spans): s1 `get_request` -> s2 `check_rules` of the requested opening
-> s3 on its outcome: allow -> s4 `schedule_opening` of the requested opening (risk irreversible) ->
s12; deny with a `next_allowed` -> s5 `ask_user` whether another time is acceptable -> s6: accepts
-> s7 `schedule_opening` at `next_allowed` (irreversible) -> s12, declines or does not know -> s8
`deny_request` -> s12; deny with no `next_allowed` -> s8; escalate -> s9 `ask_user` for the user's
field of a missing fact -> s10: learned -> s2 again, unknown -> s11 `escalate_request` -> s12; s12
the reply (`end`). Guards are canonical JSON `adr-dsl@1` expressions over the last result
(`{"eq":["outcome","allow"]}`). Its `tests` are `branch_paths` of its steps. `as_unit` wraps it in a
unit for `render_skill`. The environment serves it through `procedure_lookup` in every arm (P52):
`desk_hit` is its catalog entry (first in every catalog, the store's own entries after it) and
`desk_rendering` its SKILL.md, Mermaid and IR views for the id `DESK_UNIT_ID` or `desk-request@1`.

**Where it runs (§9.3, §12.6; N13).** In the environment process (`env.Env`; the CLI's factory
starts `python -m adr_eval.sim.env` per trial), beside the gate, never in the agent loop. In arm
`gate-runtime` a side effect passes the runtime first and then the gate; both must allow, and a
runtime refusal never reaches the gate. The runtime adds nothing to a result the agent sees,
so the arms still share their calls until the first refusal (P50).

**Enabled per model (§9.3, A4; builder note 19).** `config/runtime.json` maps each profile to
`{"enabled": bool, "check": {...} | null}`; only `adr-eval sim runtime-check` writes it
(`write_runtime_entry`). `runtime_enabled` is True only for an entry whose `enabled` is true (a
missing file or profile is disabled). The measured arm `gate-runtime` forces the runtime on,
because its result sets the flag; outside it the environment reads the flag of the profile it
is given (none: no runtime). `discipline_check` applies §9.3's rule: enabled when pass^1 of
`gate-runtime` is at least pass^1 of `gate` minus `DISCIPLINE_MARGIN`, both rounded to nine
places first, so 0.75 against 0.80 - 0.05 is enabled whatever the float error.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import json
from pathlib import Path
from typing import Any

from adr_eval.corpora import REPO_ROOT
from adr_store.bindings.dsl import Tri, check_expr, evaluate
from adr_store.units.envelope import (
    COMPILER_VERSION,
    Aids,
    Governance,
    Lineage,
    Unit,
    UnitApplicability,
    meta_sha256,
    text_sha12,
    text_sha256,
)
from adr_store.units.procedures import ProcedureBody, Step, validate_ir

__all__ = ["DESK_PROCEDURE", "DESK_PROCEDURE_PATH", "DESK_UNIT_ID", "DISCIPLINE_MARGIN",
           "READ_ONLY", "REFUSED", "RUNTIME_CONFIG", "Runtime", "as_unit", "desk_hit",
           "desk_rendering", "discipline_check", "load_desk_procedure", "load_runtime_config",
           "result_facts", "runtime_enabled", "write_runtime_entry"]

READ_ONLY = ("get_request", "ask_user", "rule_lookup", "define", "check_rules",
             "procedure_lookup", "query_table")
DISCIPLINE_MARGIN = 0.05
DESK_PROCEDURE = "desk-request@1"
DESK_PROCEDURE_PATH = REPO_ROOT / "config" / "sim" / "desk-request.json"
DESK_UNIT_ID = f"procedure/{DESK_PROCEDURE}"   # its stable id in `procedure_lookup` (P52)
RUNTIME_CONFIG = REPO_ROOT / "config" / "runtime.json"   # tests redirect it (N9)
REFUSED = ["adr.runtime.refused@1", "1"]
OUTCOMES = ("allow", "deny", "escalate")
_PLACES = 9                     # the discipline rule is judged on figures rounded here
_ENFORCED = ("tool_call", "condition", "end")
_SCHEMA_KEYS = ("const", "from_request", "from_result", "ask_missing")
# the facts a tool's result gives, replaced as a group when the runtime moves on it
_GROUPS = {"check_rules": ("outcome", "next_allowed", "missing_facts"),
           "ask_user": ("fact_learned",)}


# -- the desk procedure -------------------------------------------------------------------------

def load_desk_procedure(path: Path = DESK_PROCEDURE_PATH) -> ProcedureBody:
    """The body of `desk-request@1` from `path` (`{"id", "title", "body"}`); ValueError when
    the file names another procedure or `validate_ir` refuses the body."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("id") != DESK_PROCEDURE:
        raise ValueError(f"{path}: not {DESK_PROCEDURE}: {str(data.get('id'))[:40]!r}")
    body = ProcedureBody.model_validate(data["body"])
    problems = validate_ir(body)
    if problems:
        raise ValueError(f"{path}: {'; '.join(problems)}")
    return body


def _desk_title(path: Path = DESK_PROCEDURE_PATH) -> str:
    return json.loads(Path(path).read_text(encoding="utf-8"))["title"]


def as_unit(body: ProcedureBody, *, ref: str = DESK_PROCEDURE, title: str | None = None
            ) -> Unit:
    """`body` as a procedure unit for `render_skill`: an authored procedure (P17) has no corpus
    document, so its `doc_id` is the SHA-256 of the body's canonical JSON, its text the steps'
    texts, and it has no source refs."""
    data = body.model_dump(mode="json")
    canon = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    doc_id = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    text = "\n".join(s.text for s in body.steps)
    sha12 = text_sha12(text)
    draft = Unit(
        unit_id=f"procedure/{ref}/{sha12}/{doc_id[:16]}", type="procedure",
        title=title or _desk_title(), heading_path=[ref], canonical_ref=ref, version=sha12,
        doc_id=doc_id, contract="procedure@1", source_refs=[],
        lineage=Lineage(compiler=COMPILER_VERSION, prompt_version=None, served_model=None,
                        cache_key_sha256=None),
        tables_id=None,
        applicability=UnitApplicability(status="validated", effective_from=None,
                                        effective_to=None, supersedes=None, superseded_by=None,
                                        chain=None, jurisdiction=None),
        governance=Governance(owner=None, verifier=None, authority_tier=None), aids=Aids(),
        body=data, hashes={"text": "", "meta": ""})
    return draft.model_copy(update={"hashes": {"text": text_sha256(text),
                                               "meta": meta_sha256(draft)}})


@functools.cache
def _desk_renderings(path: Path) -> tuple[str, str, dict, str, str | None]:
    from adr_store.units.render import render_mermaid, render_skill

    body = load_desk_procedure(path)
    value = body.when_to_use.get("value")
    return (render_skill(as_unit(body, title=_desk_title(path))), render_mermaid(body),
            body.model_dump(mode="json"), _desk_title(path),
            value if isinstance(value, str) else None)


def desk_hit(rank: int = 1, path: Path = DESK_PROCEDURE_PATH) -> dict:
    """The desk procedure as a `procedure_lookup` catalog entry (P52): the keys of the store's
    entries (`rank`, `unit_id` `DESK_UNIT_ID`, `canonical_ref`, `title`, `when_to_use`,
    `doc_id` null: no corpus document, `score` null: not ranked), with `source_kind`
    "authored" and its rendered `skill` (SKILL.md) and `mermaid`."""
    skill, mermaid, _, title, when = _desk_renderings(Path(path))
    return {"rank": rank, "unit_id": DESK_UNIT_ID, "canonical_ref": DESK_PROCEDURE,
            "title": title, "when_to_use": when, "doc_id": None, "score": None,
            "source_kind": "authored", "skill": skill, "mermaid": mermaid}


def desk_rendering(view: str, path: Path = DESK_PROCEDURE_PATH) -> str | dict:
    """The desk procedure's SKILL.md (`skill`), Mermaid (`mermaid`) or IR (`ir`)."""
    skill, mermaid, ir, _, _ = _desk_renderings(Path(path))
    return {"skill": skill, "mermaid": mermaid, "ir": copy.deepcopy(ir)}[view]


# -- the facts of a result ----------------------------------------------------------------------

def result_facts(tool: str, result: Any) -> dict:
    """The facts the guards read from one call's result (module text)."""
    if not isinstance(result, dict):
        return {}
    if tool == "check_rules":
        out = {k: result[k] for k in ("outcome", "next_allowed")
               if isinstance(result.get(k), str)}
        missing = result.get("missing_facts")
        if isinstance(missing, list) and all(isinstance(m, str) for m in missing):
            out["missing_facts"] = list(missing)
        return out
    if tool == "ask_user":
        learned = result.get("learned")
        if type(learned) is not bool:
            return {}
        out: dict[str, Any] = {"fact_learned": learned}
        field = result.get("field")
        if learned and isinstance(field, str) and field and field != "fact_learned":
            out[field] = result.get("value")
        return out
    return {}


def _plain_facts(facts: Any) -> dict:
    """`{name: value}` of a record (`{name: {"value", ...}}`) or of bare values."""
    if not isinstance(facts, dict):
        return {}
    return {k: v.get("value") if isinstance(v, dict) else v for k, v in facts.items()}


def _at(args: Any, path: str) -> tuple[bool, Any]:
    cur = args
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def _same(a: Any, b: Any) -> bool:
    return type(a) is type(b) and a == b


# -- the runtime ---------------------------------------------------------------------------------

class Runtime:
    """The runtime of one procedure for one session (module text)."""

    def __init__(self, body: ProcedureBody, *, name: str = DESK_PROCEDURE,
                 request: dict | None = None):
        problems = validate_ir(body) + self._problems(body)
        if problems:
            raise ValueError(f"the runtime cannot enforce this procedure: {'; '.join(problems)}")
        self.body, self.name = body, name
        self.steps = {s.id: s for s in body.steps}
        self.active: str = body.steps[0].id
        self.learned: dict[str, Any] = {}
        self.request: dict | None = None if request is None else dict(request)
        self._guards = {(s.id, i): json.loads(e.guard) for s in body.steps
                        for i, e in enumerate(s.next) if e.guard is not None}

    @staticmethod
    def _problems(body: ProcedureBody) -> list[str]:
        out = []
        for s in body.steps:
            if s.type not in _ENFORCED:
                out.append(f"{s.id}: a {s.type} step (the runtime enforces "
                           f"{', '.join(_ENFORCED)} steps)")
            if s.type == "tool_call" and (not s.tool or len(s.next) != 1):
                out.append(f"{s.id}: a tool_call needs a tool and one successor")
            for e in s.next:
                if e.guard is None:
                    continue
                try:
                    expr = json.loads(e.guard)
                except ValueError:
                    out.append(f"{s.id}: guard {e.guard[:40]!r} is no adr-dsl@1 expression")
                    continue
                out += [f"{s.id}: guard: {p}" for p in check_expr(expr)]
            if s.type == "condition" and any(e.guard is None for e in s.next):
                out.append(f"{s.id}: a condition edge without a guard")
            for p in s.preconditions:
                out += [f"{s.id}: precondition: {x}" for x in check_expr(p)]
            schema = s.args_schema or {}
            bad = sorted(k for k in schema if k not in _SCHEMA_KEYS)
            named = [schema.get(k, {}) for k in ("from_request", "from_result")]
            asks = schema.get("ask_missing", {})
            if bad or not all(isinstance(schema.get(k, {}), dict) for k in _SCHEMA_KEYS) or \
                    not all(isinstance(v, str) for m in named if isinstance(m, dict)
                            for v in m.values()) or \
                    not all(isinstance(m, dict) and all(v is None or isinstance(v, str)
                                                        for v in m.values())
                            for m in (asks.values() if isinstance(asks, dict) else [None])):
                out.append(f"{s.id}: args_schema takes only {', '.join(_SCHEMA_KEYS)} objects "
                           f"of the forms the module text gives")
        return out

    # -- the active step --------------------------------------------------------------------

    def bind(self, request: dict) -> None:
        """Bind the runtime to the request its `from_request` arguments must match."""
        self.request = dict(request)

    @property
    def step(self) -> Step:
        return self.steps[self.active]

    def allowed_tools(self) -> list[str]:
        """The tools allowed at the active step: the read-only ones, and a side-effecting tool
        the active `tool_call` step names."""
        s = self.step
        extra = [s.tool] if s.type == "tool_call" and s.tool not in READ_ONLY else []
        return [*READ_ONLY, *extra]

    def _refusal(self, reason: str) -> dict:
        s = self.step
        return {"decision": "deny", "rule_ids": [list(REFUSED)], "deciding_sections": [],
                "missing_facts": [], "next_allowed": None, "evaluated_outcome": None,
                "procedure": self.name, "active_step": s.id,
                "allowed_tools": self.allowed_tools(), "step_text": s.text, "reason": reason,
                "message": f"refused by the procedure {self.name} at step {s.id}: {reason}"}

    @staticmethod
    def _askable(mapping: dict, learned: dict) -> list[str]:
        """The user's fields of the missing facts of the last `check_rules` (`ask_missing`)."""
        missing = learned.get("missing_facts")
        missing = missing if isinstance(missing, list) else []
        return sorted({mapping[m] for m in missing if isinstance(mapping.get(m), str)})

    def _args_problem(self, s: Step, args: Any) -> str | None:
        schema = s.args_schema or {}
        for path, want in sorted(schema.get("const", {}).items()):
            found, got = _at(args, path)
            if not found or not _same(got, want):
                return f"{path} must be {json.dumps(want)} at this step"
        for path, field in sorted(schema.get("from_request", {}).items()):
            want = None if self.request is None else self.request.get(field)
            if want is None:
                return f"{path} must be the request's {field}, and no request is bound"
            found, got = _at(args, path)
            if not found or not _same(got, want):
                return f"{path} must be {json.dumps(want)} (the request's {field})"
        for path, fact in sorted(schema.get("from_result", {}).items()):
            want = self.learned.get(fact)
            if not isinstance(want, str):
                return f"{path} must be the {fact} of a result, and none is known"
            found, got = _at(args, path)
            if not found or not _same(got, want):
                return f"{path} must be {want} (the {fact} of the last result)"
        for path, mapping in sorted(schema.get("ask_missing", {}).items()):
            fields = self._askable(mapping, self.learned)
            found, got = _at(args, path)
            if not found or got not in fields:
                return (f"{path} must be one of {json.dumps(fields)}: the user's fields for the "
                        f"missing facts {json.dumps(self.learned.get('missing_facts', []))}")
        return None

    def _nothing_to_ask(self, s: Step, learned: dict) -> bool:
        asks = (s.args_schema or {}).get("ask_missing", {})
        return s.type == "tool_call" and bool(asks) and not any(
            self._askable(m, learned) for m in asks.values())

    # -- the interface ----------------------------------------------------------------------

    def allows(self, tool: str, args: dict, facts: dict) -> tuple[bool, dict | None]:
        """(True, None) or (False, refusal) for a call of `tool` with `args` on the record
        `facts` (module text)."""
        if tool in READ_ONLY:
            return True, None
        s = self.step
        if s.type != "tool_call" or s.tool != tool:
            return False, self._refusal(f"{tool} is not allowed at step {s.id}")
        if s.requires_approval:
            return False, self._refusal(f"step {s.id} needs an approval, and none was given")
        known = {**self.learned, **_plain_facts(facts)}
        for p in s.preconditions:
            v = evaluate(p, known)
            if v is not Tri.T:
                state = "unknown" if v is Tri.U else "false"
                return False, self._refusal(f"precondition {json.dumps(p, sort_keys=True)} is "
                                            f"{state}")
        problem = self._args_problem(s, args)
        if problem:
            return False, self._refusal(problem)
        return True, None

    def advance(self, tool: str, result: dict, args: dict | None = None) -> None:
        """Move on along the matching guard after an executed call (module text)."""
        s = self.step
        if s.type != "tool_call" or s.tool != tool or self._args_problem(s, args):
            return
        facts = result_facts(tool, result)
        nxt = self._follow(s, facts)
        if nxt is None:
            return                                  # fail closed: stay on the tool_call
        learned = {k: v for k, v in self.learned.items() if k not in _GROUPS.get(tool, ())}
        learned.update(copy.deepcopy(facts))
        seen = set()
        while self._nothing_to_ask(nxt, learned) and nxt.id not in seen:
            seen.add(nxt.id)                        # passed as an unknown answer (s9 -> s11)
            unknown = {"fact_learned": False}
            after = self._follow(nxt, unknown)
            if after is None:
                break
            learned.update(unknown)
            nxt = after
        self.learned, self.active = learned, nxt.id

    def _follow(self, s: Step, facts: dict) -> Step | None:
        """The step after tool_call `s` on a result's `facts`: its successor, through condition
        steps by the one True guard; None when a condition has no such guard."""
        nxt, seen = self.steps[s.next[0].to], set()
        while nxt.type == "condition":
            if nxt.id in seen:
                return None
            seen.add(nxt.id)
            true = [e for i, e in enumerate(nxt.next)
                    if evaluate(self._guards[(nxt.id, i)], facts) is Tri.T]
            if len(true) != 1:
                return None
            nxt = self.steps[true[0].to]
        return nxt


# -- the per-profile flag ------------------------------------------------------------------------

def load_runtime_config(path: Path | None = None) -> dict:
    """`config/runtime.json` (or `path`): {profile: {"enabled", "check"}}; {} when the file is
    missing; ValueError when an entry is not of that shape."""
    path = Path(path or RUNTIME_CONFIG)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: not an object of profiles")
    for name, entry in data.items():
        if not (isinstance(entry, dict) and set(entry) == {"enabled", "check"}
                and type(entry["enabled"]) is bool
                and (entry["check"] is None or isinstance(entry["check"], dict))):
            raise ValueError(f"{path}: {name}: not {{\"enabled\": bool, \"check\": object or "
                             f"null}}")
    return data


def runtime_enabled(profile: str, path: Path | None = None) -> bool:
    """Whether `profile` runs with the runtime (module text)."""
    entry = load_runtime_config(path).get(profile)
    return entry is not None and entry["enabled"] is True


def write_runtime_entry(profile: str, entry: dict, path: Path | None = None) -> None:
    """Write `profile`'s `{"enabled", "check"}` into the config at `path`, keeping the other
    profiles (sorted keys, two-space indent)."""
    path = Path(path or RUNTIME_CONFIG)
    data = load_runtime_config(path)
    data[profile] = {"enabled": entry["enabled"], "check": entry["check"]}
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def discipline_check(summary: dict, profile: str) -> dict:
    """{"enabled", "check"} of §9.3's rule on the per-arm totals `summary` (`{"gate":
    {"pass^1", ...}, "gate-runtime": {...}}`, as `score.summarize` gives under "arms");
    ValueError when either arm or its pass^1 is missing."""
    figures = {}
    for arm in ("gate", "gate-runtime"):
        p1 = (summary.get(arm) or {}).get("pass^1")
        if isinstance(p1, bool) or not isinstance(p1, (int, float)):
            raise ValueError(f"the discipline check needs pass^1 of arm {arm}")
        figures[arm] = {"pass^1": p1, **{k: summary[arm][k] for k in ("tasks", "trials")
                                         if k in summary[arm]}}
    floor = round(figures["gate"]["pass^1"] - DISCIPLINE_MARGIN, _PLACES)
    enabled = round(figures["gate-runtime"]["pass^1"], _PLACES) >= floor
    return {"enabled": enabled,
            "check": {"profile": profile, "procedure": DESK_PROCEDURE,
                      "rule": "pass^1(gate-runtime) >= pass^1(gate) - 0.05",
                      "margin": DISCIPLINE_MARGIN, "floor": floor, **figures}}
