"""The procedure pass (Phase 4 spec §6.2–6.5, §9; ruling P1): the four descriptive fields of a
procedure unit, `when_to_use`, `not_for`, `trigger_examples` and `problem_abstractions`, from
one cached model call per procedure and field group of `passes.json` (the committed config has
one group, preflight N7).

**The call.** `client.complete(pass_prompt(group), <section text> + "\\n\\nSKELETON:\\n" +
<numbered step texts>, max_tokens=MAX_TOKENS, cache_failures=True)` through
`tables.extract._call`, so the Phase 3 outcomes hold: an unparseable reply is retried once at
repeat 1; an input rejection (stored, raised as CachedFailure then and later) makes the group's
fields null `model_error`; every other failure (retries exhausted, the usage limit, a
configuration error) and a budget stop propagate uncached, and a rerun resumes from the cache
(Phase 3 P21). The section text is the slice of the document's canonical text under the unit's
first source span (an IRM section, a whole bench document); the skeleton lists the steps that
have text, numbered, whitespace collapsed. The prompt names `PROMPT_VERSION` and the group's
spec ids, so the cache key covers both and a spec bump recompiles only its group (§6.5, T5).

**The checks (§6.3), per field.** (1) The reply parses (`parse_json_recovering`) and holds
every field of the group, else the retry, else every field of the group is null `unparseable`.
(2) Type and limits: `when_to_use` and `not_for` are non-empty strings, `when_to_use` at most
`LIMITS["when_to_use"]` characters; `trigger_examples` and `problem_abstractions` are lists of
non-empty strings, at most `LIMITS[field]` of them; `quotes` is a list of strings (a missing or
null list is no quote, a single string one). A value that fails is null `unparseable`. A
null value (or an empty one) keeps the model's reason when it is `absent` or
`not_applicable`, else `absent`. (3) `not_for` without a quote is null `absent`
(Phase 3 P22: a negative needs a quote that states it). (4) Grounding: each quote is located in
the section text (`grounding.ground`); the field is kept when at least one quote is found, with
every found quote (distinct spans, in the order given) stored as the located slice and its
offsets in the document's canonical text (the section's start added), so each re-slices from
the document; else the field is null `ungrounded`. Descriptive fields state no numbers or
times, so there is no value-in-quote check and a kept value is `verified`.

`quotes_given` and `quotes_grounded` count the quotes of every value that passed the type
check, before ungrounded values are dropped (criterion E1).

`compile_procedures` runs the pass over the procedure units of one or more stores
(`store_procedures`: the IRM procedures of a gov store, the drawn procedures of a bench store,
both built by code exactly as the units build does, so the build sends the same inputs and
reads the same cache entries); `--limit` takes the first procedures over the stores in order
(the canary). `apply` fills a build's procedure units from the cache: the four body fields in
the contract shape `{value, quotes[{text, span}], status, null_reason}` and the lineage
(prompt version, the served model when the provider reports it, the cache key of the call).
"""

from __future__ import annotations

import functools
import hashlib
from collections import Counter
from dataclasses import dataclass
from importlib import resources
from string import Template
from typing import Any

from adr_eval.cache import Cache
from adr_eval.llm import Completion, ModelOutputError, parse_json_recovering
from adr_store import applicability as ap
from adr_store.store import Store
from adr_store.tables import extract as ex
from adr_store.units.envelope import COMPILER_VERSION, Lineage, Unit, UnitNullReason, meta_sha256
from adr_store.units.grounding import PassConfig, ground
from adr_store.units.procedures import WHEN_TO_USE_MAX, procedure_units

PROMPT_VERSION = "procedure-compile@1"
MAX_TOKENS = 1500   # four fields, each a short value and a few quotes
FIELDS = ("when_to_use", "not_for", "trigger_examples", "problem_abstractions")
LIMITS = {"when_to_use": WHEN_TO_USE_MAX, "trigger_examples": 3, "problem_abstractions": 5}
_LISTS = ("trigger_examples", "problem_abstractions")
_MODEL_NULLS = ("absent", "not_applicable")
_FIELD_LINES = {
    "when_to_use": "- when_to_use (a string of at most 1,024 characters): the situation in which "
                   "someone should follow this procedure, in one or two sentences.",
    "not_for": "- not_for (a string): what the text states the procedure is not for.",
    "trigger_examples": "- trigger_examples (a list of two or three strings): requests or "
                        "questions, in a user's own words, that this procedure answers.",
    "problem_abstractions": "- problem_abstractions (a list of at most five strings): short, "
                            "general statements of the problems this procedure solves.",
}


@dataclass(frozen=True)
class FieldValue:
    value: Any                                    # str, a tuple of str, or None
    quotes: tuple[tuple[str, int, int], ...]      # (located quote, start, end) in the document
    null_reason: UnitNullReason | None
    quotes_given: int
    quotes_grounded: int


@dataclass(frozen=True)
class _Compiled:
    unit_id: str
    fields: dict[str, FieldValue]
    outcomes: dict[str, str]        # group -> reply | reply_repeat_1 | unparseable | model_error
    counts: Counter                 # made, cached, failed
    served: tuple[str, ...]         # models the provider reported answering
    keys: dict[str, str]            # group -> cache key of its last call


# -- config and prompt ---------------------------------------------------------------------------

def check_config(cfg: PassConfig) -> None:
    """ValueError unless `cfg` is a procedure pass config: this module's prompt version and
    groups naming exactly `FIELDS`."""
    if cfg.prompt_version != PROMPT_VERSION:
        raise ValueError(f"prompt version {cfg.prompt_version!r} is not {PROMPT_VERSION!r}")
    named = sorted(f for fields in cfg.groups.values() for f in fields)
    if named != sorted(FIELDS):
        raise ValueError(f"the procedure pass groups must name each field of {FIELDS} once")


@functools.cache
def _template() -> Template:
    return Template(resources.files("adr_store.units").joinpath(
        "prompts/procedure_compile.txt").read_text(encoding="utf-8"))


def pass_prompt(group: str, cfg: PassConfig) -> str:
    """The system prompt of one field group: the prompt version, the group's spec ids, the
    reply shape and the group's fields."""
    fields = [f for f in FIELDS if f in cfg.groups[group]]
    return _template().substitute(
        prompt_version=cfg.prompt_version,
        specs=", ".join(cfg.specs[f] for f in fields),
        shape=", ".join(f'"{f}": <field>' for f in fields),
        fields="\n".join(_FIELD_LINES[f] for f in fields))


def _skeleton(unit: Unit) -> str:
    steps = [s["text"] for s in unit.body["steps"] if s["text"].strip()]
    return "\n".join(f"{i}. {' '.join(t.split())}" for i, t in enumerate(steps, 1))


# -- checks --------------------------------------------------------------------------------------

def _null(reason: UnitNullReason, given: int = 0) -> FieldValue:
    return FieldValue(None, (), reason, given, 0)


def _coerce(field: str, raw: Any) -> Any:
    """Check 2: the value of `field` (a stripped string, or a tuple of them), or None when
    it has the wrong type or is over its limit."""
    if field in _LISTS:
        items = [raw] if isinstance(raw, str) else raw
        if not isinstance(items, list) or not all(isinstance(x, str) and x.strip()
                                                  for x in items):
            return None
        return tuple(x.strip() for x in items) if len(items) <= LIMITS[field] else None
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip()
    return value if len(value) <= LIMITS.get(field, len(value)) else None


def check_field(field: str, cell: Any, section: str, offset: int) -> FieldValue:
    """Checks 2–4 of one field of a reply (module docstring); quote offsets are in `section`
    plus `offset` (the section's start in its document)."""
    if not isinstance(cell, dict):
        return _null("unparseable")
    raw = cell.get("value")
    if raw is None or raw == [] or (isinstance(raw, str) and not raw.strip()):
        reason = cell.get("null_reason")
        return _null(reason if reason in _MODEL_NULLS else "absent")
    value = _coerce(field, raw)
    quotes = cell.get("quotes")
    quotes = [] if quotes is None else [quotes] if isinstance(quotes, str) else quotes
    if value is None or not isinstance(quotes, list) \
            or not all(isinstance(q, str) for q in quotes):
        return _null("unparseable")
    if field == "not_for" and not any(q.strip() for q in quotes):
        return _null("absent", len(quotes))           # Phase 3 P22: a negative needs a quote
    found = [span for q in quotes if (span := ground(section, q)) is not None]
    if not found:
        return _null("ungrounded", len(quotes))
    stored = tuple((section[s:e], s + offset, e + offset) for s, e in dict.fromkeys(found))
    return FieldValue(value, stored, None, len(quotes), len(found))


def _parser(fields: list[str]):
    def parse(text: str) -> dict:
        reply, _ = parse_json_recovering(text, fields)
        missing = [f for f in fields if f not in reply]
        if missing:
            raise ModelOutputError(f"the reply has no {', '.join(missing)}")
        return reply
    return parse


# -- calls ---------------------------------------------------------------------------------------

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


def _compile(unit: Unit, text: str, client, cfg: PassConfig) -> _Compiled:
    ref = unit.source_refs[0]
    section = text[ref.start:ref.end]
    user = section + "\n\nSKELETON:\n" + _skeleton(unit)
    fields: dict[str, FieldValue] = {}
    outcomes, keys, counts, served = {}, {}, Counter(), set()
    for group in sorted(cfg.groups):
        names = [f for f in FIELDS if f in cfg.groups[group]]
        system = pass_prompt(group, cfg)
        rec = _Recorder(client)
        reply, outcome, c = ex._call(rec, system, user, _parser(names), max_tokens=MAX_TOKENS)
        counts += c
        outcomes[group] = outcome
        keys[group] = Cache.key(client.name, getattr(client, "model", client.name), system,
                                user, MAX_TOKENS, rec.repeat)
        served.update(x.served_model for x in rec.completions if x.served_model)
        for f in names:
            if reply is None:
                fields[f] = _null("model_error" if outcome == "model_error" else "unparseable")
            else:
                fields[f] = check_field(f, reply[f], section, ref.start)
    return _Compiled(unit.unit_id, {f: fields[f] for f in FIELDS}, outcomes, counts,
                     tuple(sorted(served)), keys)


def compile_procedure(unit: Unit, text: str, client, cfg: PassConfig) -> dict[str, FieldValue]:
    """The checked fields of procedure `unit` (field -> value, in `FIELDS` order); `text` is
    its document's canonical text."""
    check_config(cfg)
    return _compile(unit, text, client, cfg).fields


def compile_units(store: Store, units: list[Unit], client, cfg: PassConfig, *,
                  workers: int = 1) -> list[_Compiled]:
    """The pass over `units` of `store`, in their order, on `workers` threads (the first
    failure stops the rest; replies already made are cached)."""
    check_config(cfg)
    texts = {d: store.text(d) for d in sorted({u.doc_id for u in units})}
    return ex._map(lambda u: _compile(u, texts[u.doc_id], client, cfg), units, workers)


def store_procedures(store: Store) -> list[Unit]:
    """The procedure units of `store` built by code, sorted by unit id: its procedure-like IRM
    sections and its drawn bench documents (a store of one corpus has only that corpus's)."""
    overlay = ap.load_overlay(store.path, store.snapshot_id)
    units = [u for corpus in ("gov", "bench") for u in procedure_units(store, corpus, overlay)[0]]
    return sorted(units, key=lambda u: u.unit_id)


# -- reports -------------------------------------------------------------------------------------

def _summary(done: list[_Compiled]) -> dict:
    """What is the same on every rebuild from the same cache: per field the quotes given and
    grounded (E1), values kept and nulls by reason; per group the call outcomes."""
    fields = {f: {"quotes_given": 0, "quotes_grounded": 0, "values": 0, "nulls": Counter()}
              for f in FIELDS}
    outcomes: dict[str, Counter] = {}
    for r in done:
        for f, v in r.fields.items():
            fields[f]["quotes_given"] += v.quotes_given
            fields[f]["quotes_grounded"] += v.quotes_grounded
            if v.value is None:
                fields[f]["nulls"][v.null_reason] += 1
            else:
                fields[f]["values"] += 1
        for g, o in r.outcomes.items():
            outcomes.setdefault(g, Counter())[o] += 1
    for v in fields.values():
        v["nulls"] = dict(sorted(v["nulls"].items()))
    return {"fields": fields,
            "outcomes": {g: dict(sorted(c.items())) for g, c in sorted(outcomes.items())}}


def _calls(done: list[_Compiled]) -> dict:
    counts = sum((r.counts for r in done), Counter())
    return {k: counts[k] for k in ("made", "cached", "failed")}


def compile_procedures(stores: list[Store], client, cfg: PassConfig, *, limit: int | None = None,
                       workers: int = 1, units: list[list[Unit]] | None = None
                       ) -> tuple[dict[str, dict[str, FieldValue]], dict]:
    """(unit id -> checked fields, the report) of the pass over the procedures of `stores`
    (`units`, one list per store, when the caller built them already, else
    `store_procedures`); with `limit` only the first procedures over the stores in order.
    The report (unhashed): prompt version, max tokens, groups and specs, the calls and served
    models of the run, and per store (by path) the procedures available and compiled, the
    calls, served models and `_summary`."""
    check_config(cfg)
    per_store = units if units is not None else [store_procedures(s) for s in stores]
    left = limit
    results: dict[str, dict[str, FieldValue]] = {}
    everything: list[_Compiled] = []
    report: dict = {"pass": "procedure", "prompt_version": cfg.prompt_version,
                    "max_tokens": MAX_TOKENS, "groups": cfg.groups, "specs": cfg.specs,
                    "limit": limit, "stores": {}}
    for store, available in zip(stores, per_store, strict=True):
        chosen = available if left is None else available[:left]
        if left is not None:
            left -= len(chosen)
        done = compile_units(store, chosen, client, cfg, workers=workers)
        results.update((r.unit_id, r.fields) for r in done)
        everything += done
        report["stores"][str(store.path)] = {
            "snapshot": store.snapshot_id, "available": len(available),
            "procedures": len(done), "calls": _calls(done),
            "served_models": sorted({m for r in done for m in r.served}), **_summary(done)}
    report["calls"] = _calls(everything)
    report["served_models"] = sorted({m for r in everything for m in r.served})
    return results, report


# -- the build -----------------------------------------------------------------------------------

def _body_field(v: FieldValue) -> dict:
    return {"value": list(v.value) if isinstance(v.value, tuple) else v.value,
            "quotes": [{"text": t, "span": [s, e]} for t, s, e in v.quotes],
            "status": None if v.value is None else "verified", "null_reason": v.null_reason}


def _cache_key(keys: dict[str, str]) -> str:
    """The cache key of the unit's call; with several groups the SHA-256 of their keys."""
    if len(keys) == 1:
        return next(iter(keys.values()))
    lines = "".join(f"{g} {k}\n" for g, k in sorted(keys.items()))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def fill(unit: Unit, r: _Compiled, cfg: PassConfig) -> Unit:
    """`unit` with its four model fields from `r` and its lineage (prompt version, served
    model when reported, cache key); the meta hash recomputed."""
    body = {**unit.body, **{f: _body_field(v) for f, v in r.fields.items()}}
    lineage = Lineage(compiler=COMPILER_VERSION, prompt_version=cfg.prompt_version,
                      served_model=",".join(r.served) or None,
                      cache_key_sha256=_cache_key(r.keys))
    u = unit.model_copy(update={"body": body, "lineage": lineage})
    return u.model_copy(update={"hashes": {**u.hashes, "meta": meta_sha256(u)}})


def apply(store: Store, units: list[Unit], report: dict, client, cfg: PassConfig
          ) -> tuple[list[Unit], dict, dict]:
    """(the procedure `units` filled by the pass, `report` with the pass's `_summary` under
    `procedure_pass`, the manifest's record of the pass: prompt version, adapter, model, max
    tokens, groups and specs, nothing that differs between rebuilds)."""
    done = compile_units(store, units, client, cfg)
    filled = [fill(u, r, cfg) for u, r in zip(units, done, strict=True)]
    info = {"prompt_version": cfg.prompt_version, "adapter": client.name,
            "model": getattr(client, "model", client.name), "max_tokens": MAX_TOKENS,
            "groups": cfg.groups, "specs": cfg.specs}
    return filled, {**report, "procedure_pass": _summary(done)}, info
