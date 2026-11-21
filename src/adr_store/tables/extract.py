"""The 3B extractor: grounded facts from 33 CFR part 117 sections (Phase 3 spec §5.5, §7.1–7.5).

A **unit** is one distinct section text of the `ecfr:33:117` chain with every (version,
section) it occurs in. Each unit is extracted once per column group of `extraction.json`: one
cached call `client.complete(prompt(group), unit.text, max_tokens=MAX_TOKENS, repeat=0,
cache_failures=True)`. The prompt names `PROMPT_VERSION` and the group's spec ids, so the cache
key covers the adapter, model, prompt version, section text and spec versions (§7.1), and
bumping one spec re-extracts only its group (§7.5). The group holding `bridge` defines the
draws; another group's draws are matched to them with `match_draws` (it is asked for each
draw's bridge name and mile for that, under no spec), and its unmatched draws are dropped and
counted.

Checks (§7.2), per value: (1) the reply parses (`parse_json_recovering`), else one retry at
repeat 1, else every model column of the group is null `unparseable` (status `rejected`); (2)
`coerce` to the column type, else null `unparseable`; (3) `find_quote` locates the quote in the
section text, else null `ungrounded`; the stored quote is the located slice; (4) for `NUMERIC`
columns the number (digits or a number word up to one hundred) is in the quote, else status
`auto-accepted` with `checks_failed=("value_in_quote",)`; (5) where a regular expression finds
values in the section, whether the value is among them (`regex_agrees`; recorded, never used to
reject; lenient for sections with several draws, where a value of another draw also agrees).
A call the provider rejected for its input (InputRejected, stored as a failure and raised as
CachedFailure, then and later) makes every model column of its group null `model_error`. Any
other failure (retries exhausted, the usage limit, a configuration error, a malformed
response) and a budget stop (BudgetExceeded) propagate: the run stops, nothing is stored for
that call and a later run retries it (ruling P21).

`drawbridge_rows` writes the rows of every occurrence: the unit's offsets plus the occurrence's
start, so each span slices that version's document text to the quote. `closed_periods` is a
non-null `text[]`: an empty list means absent, with no per-element provenance.

The second pass (§7.2 check 6) asks numbered questions (`second_pass_prompt`, one call per
unit), parses the numbered answers (`parse_numbered`) and applies the same checks; its facts are
written once to `second-pass-<id[:16]>.jsonl` (`write_facts`) and read back by id
(`load_facts`). `agreement` compares the two passes per column.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path
from string import Template
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from adr_eval.golden.verify import find_quote
from adr_eval.llm import CachedFailure, ModelOutputError, parse_json_recovering
from adr_store.records import _HEX64
from adr_store.store import Store
from adr_store.tables.contracts import CONTRACT_DIR, EXTRACTION_CONFIG, Column, Contract
from adr_store.tables.ecfr import SectionUnit, chain_docs, ecfr_sections, heading_waterway_key
from adr_store.tables.entities import normalise_key
from adr_store.tables.overlay import TABLES_DIR, TablesError, _dir, _write_once
from adr_store.tables.parse import base_key
from adr_store.tables.provenance import (
    NullReason,
    RowRecord,
    Status,
    ValueProv,
    null_prov,
    value_prov,
)

PROMPT_VERSION = "drawbridge-extract@2"
SECOND_PASS_VERSION = "drawbridge-questions@2"
MAX_TOKENS = 4000   # up to 10 draws x 5 columns x (value, quote, reason) per section
SECTION_COLUMNS = ("waterway", "seasonal", "owner_or_agency", "vhf_channel")
DRAW_COLUMNS = ("bridge", "mile", "notice_hours", "opens_on_signal", "closed_periods")
MODEL_COLUMNS = SECTION_COLUMNS + DRAW_COLUMNS
NUMERIC = ("vhf_channel", "mile", "notice_hours")
STRUCTURE_COLUMNS = ("section", "version", "heading", "state", "waterway_key")
SECTIONS_TABLE, BRIDGES_TABLE = "drawbridge_sections", "drawbridge_bridges"
REGEXES: dict[str, re.Pattern] = {
    "mile": re.compile(r"\bmile\s+(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)",
                       re.IGNORECASE),
    "notice_hours": re.compile(r"\b(\d+)[\s-]+hours?\s+(?:advance\s+)?notice", re.IGNORECASE),
    "vhf_channel": re.compile(r"\bchannel\s+(\d+)", re.IGNORECASE),
}
_REPLY_KEYS = ("section", "draws")
_MODEL_NULLS = ("absent", "not_applicable")
_IDENTIFY = ("bridge", "mile")    # what a group without `bridge` gives per draw, for matching


class ExtractionConfig(BaseModel):
    """`extraction.json`: the column groups (one cached call per group and unit) and each model
    column's spec version (`bridge.<column>@<n>`), the source of the contracts' spec ids."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    groups: dict[str, list[str]]
    specs: dict[str, str]

    @model_validator(mode="after")
    def _covers_the_model_columns(self) -> ExtractionConfig:
        named = [c for cols in self.groups.values() for c in cols]
        if sorted(named) != sorted(MODEL_COLUMNS):
            raise ValueError(f"the groups must name each model column once: {MODEL_COLUMNS}")
        if any(not re.fullmatch(r"[A-Za-z0-9_]+", g) for g in self.groups):
            raise ValueError("a group name is letters, digits and underscores")
        if set(self.specs) != set(MODEL_COLUMNS):
            raise ValueError(f"specs must name each model column: {MODEL_COLUMNS}")
        for column, spec in self.specs.items():
            if not re.fullmatch(rf"bridge\.{column}@[1-9]\d*", spec):
                raise ValueError(f"{column}: spec {spec!r} is not bridge.{column}@<version>")
        return self


@dataclass(frozen=True)
class Unit:
    text_sha256: str
    text: str
    occurrences: tuple[SectionUnit, ...]   # oldest version first, document order


@dataclass(frozen=True)
class Value:
    value: Any
    quote: str | None              # the located slice of the section text
    start: int | None              # offsets in the section text
    end: int | None
    status: Status | None
    null_reason: NullReason | None
    checks_failed: tuple[str, ...]
    regex_agrees: bool | None


ABSENT = Value(None, None, None, None, None, "absent", (), None)


def _failed(reason: NullReason, *checks: str) -> Value:
    return Value(None, None, None, None, "rejected", reason, checks, None)


@dataclass(frozen=True)
class UnitExtraction:
    unit: str                       # the unit's text_sha256
    section: dict[str, Value]
    draws: list[dict[str, Value]]
    calls: dict[str, str]           # group -> reply | reply_repeat_1 | unparseable | model_error


@dataclass(frozen=True)
class Facts:
    """A unit's facts from the second pass: the same shape as `UnitExtraction`."""

    unit: str
    section: dict[str, Value]
    draws: list[dict[str, Value]]


# -- units, config and prompts -------------------------------------------------------------------

def units(store: Store, chain: str = "ecfr:33:117") -> list[Unit]:
    """One unit per distinct section text of the chain, sorted by its SHA-256."""
    by: dict[str, list[SectionUnit]] = {}
    for doc_id in chain_docs(store, chain):
        for su in ecfr_sections(store, doc_id):
            by.setdefault(hashlib.sha256(su.text.encode("utf-8")).hexdigest(), []).append(su)
    return [Unit(sha, occ[0].text, tuple(occ)) for sha, occ in sorted(by.items())]


def load_config(path: Path = CONTRACT_DIR / EXTRACTION_CONFIG) -> ExtractionConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return ExtractionConfig.model_validate({k: v for k, v in data.items()
                                            if not k.startswith("_")})


@functools.cache
def _template(name: str) -> Template:
    text = resources.files("adr_store.tables").joinpath(f"prompts/{name}.txt").read_text(
        encoding="utf-8")
    return Template(text)


def _column(contracts: dict[str, Contract], name: str) -> Column:
    table = SECTIONS_TABLE if name in SECTION_COLUMNS else BRIDGES_TABLE
    return next(c for c in contracts[table].columns if c.name == name)


def _ctype(contracts: dict[str, Contract], name: str) -> str:
    return _column(contracts, name).type


def _lines(contracts: dict[str, Contract], names: Iterable[str], note: str = "") -> list[str]:
    out = []
    for name in names:
        col = _column(contracts, name)
        out.append(f"- {name} ({col.type}): {col.description}{note}")
    return out


def _identifying(cols: list[str]) -> list[str]:
    """The draw columns a group asks for only to match its draws to the bridge group's."""
    if not any(c in DRAW_COLUMNS for c in cols) or "bridge" in cols:
        return []
    return [c for c in _IDENTIFY if c not in cols]


def prompt(group: str, cfg: ExtractionConfig, contracts: dict[str, Contract]) -> str:
    """The system prompt of one column group: the prompt version, the group's spec ids and
    its columns' descriptions (identification columns carry no spec)."""
    cols = cfg.groups[group]
    section = [c for c in SECTION_COLUMNS if c in cols]
    draw = [c for c in DRAW_COLUMNS if c in cols]
    ident = _identifying(cols)
    draw_lines = _lines(contracts, ident, " Given only to tell the draws apart.") \
        + _lines(contracts, draw)
    return _template("extract").substitute(
        prompt_version=PROMPT_VERSION,
        specs=", ".join(cfg.specs[c] for c in MODEL_COLUMNS if c in cols),
        section_columns="\n".join(_lines(contracts, section)) or "(none: give \"section\": {})",
        draw_columns="\n".join(draw_lines) or "(none: give \"draws\": [])")


def second_pass_prompt(contracts: dict[str, Contract]) -> str:
    """The numbered-question prompt of the second pass, naming its version and the model
    columns' spec ids (from the contracts)."""
    return _template("second_pass").substitute(
        prompt_version=SECOND_PASS_VERSION,
        specs=", ".join(_column(contracts, c).spec_id for c in MODEL_COLUMNS))


# -- checks --------------------------------------------------------------------------------------

def coerce(ctype: str, raw: Any) -> Any:
    """Check 2: `raw` as a value of the column type; ValueError when it is none. Digit strings
    are numbers and yes/no/true/false strings are bools; number words are not numbers."""
    if ctype == "text":
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    elif ctype == "int":
        if isinstance(raw, float) and raw.is_integer():
            raw = int(raw)
        elif isinstance(raw, str) and re.fullmatch(r"\s*[+-]?(\d{1,3}(,\d{3})+|\d+)\s*", raw):
            raw = int(raw.replace(",", ""))
        if isinstance(raw, int) and not isinstance(raw, bool) and -2**63 <= raw < 2**63:
            return raw
    elif ctype == "real":
        if isinstance(raw, str) and re.fullmatch(rf"\s*[+-]?(?:{_NUMBER})\s*", raw):
            raw = float(raw.replace(",", ""))
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            try:
                v = float(raw)
            except OverflowError:
                v = math.inf
            if math.isfinite(v):
                return v
    elif ctype == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.strip().casefold() in ("yes", "true"):
            return True
        if isinstance(raw, str) and raw.strip().casefold() in ("no", "false"):
            return False
    elif ctype == "text[]":
        items = [raw] if isinstance(raw, str) else raw
        if isinstance(items, list) and all(isinstance(x, str) and x.strip() for x in items):
            return [x.strip() for x in items]
    else:
        raise ValueError(f"unknown column type {ctype!r}")
    raise ValueError(f"not a {ctype} value: {raw!r}")


_UNITS = ("one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
          "fifteen sixteen seventeen eighteen nineteen").split()
_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
WORDS: dict[str, int] = {w: i for i, w in enumerate(_UNITS, 1)}
WORDS.update({w: t * 10 for t, w in enumerate(_TENS, 2)})
_NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"     # digits, with thousands commas
_DIGITS = re.compile(_NUMBER)
_WORD = re.compile(r"[a-z]+")
_JOIN = re.compile(r"-|\s+")       # what may stand between the words of one number


def _number(text: str) -> float:
    return float(text.replace(",", ""))


def _numbers(quote: str) -> set[float]:
    """The numbers a quote states: digits ("26.8", "1,088.5") or number words from one to
    ninety-nine, a tens word and a unit word joined by a hyphen or a space ("twenty-four",
    "twenty four") being one number, "hundred" with a unit word before it that many hundreds
    ("two hundred") and alone 100. A word fused to another by a hyphen counts ("two-hour",
    "twenty-four-hour"); a word inside another does not ("fourteen" states no four)."""
    found = {_number(m) for m in _DIGITS.findall(quote)}
    text = quote.casefold()
    words = list(_WORD.finditer(text))
    i = 0
    while i < len(words):
        w = words[i].group()
        nxt = words[i + 1] if i + 1 < len(words) else None
        joined = nxt is not None and _JOIN.fullmatch(text[words[i].end():nxt.start()])
        if joined and w in _TENS and nxt.group() in _UNITS[:9]:
            found.add(float(WORDS[w] + WORDS[nxt.group()]))
            i += 2
        elif joined and w in _UNITS[:9] and nxt.group() == "hundred":
            found.add(float(WORDS[w] * 100))
            i += 2
        else:
            if w in WORDS:
                found.add(float(WORDS[w]))
            elif w == "hundred":
                found.add(100.0)
            i += 1
    return found


def number_in_quote(value: float, quote: str) -> bool:
    """Check 4: the quote states `value`, in digits or in words."""
    return float(value) in _numbers(quote)


def regex_value(column: str, section_text: str) -> tuple | None:
    """Check 5: the distinct values the column's regular expression finds in the section text,
    sorted; None when it has no expression or finds nothing. A value agrees when it is among
    them: lenient for sections with several draws (another draw's value also agrees)."""
    pattern = REGEXES.get(column)
    if pattern is None:
        return None
    cast = float if column == "mile" else int
    found = sorted({cast(m.group(1).replace(",", "")) for m in pattern.finditer(section_text)})
    return tuple(found) or None


def check_value(column: str, ctype: str, raw: dict, section_text: str) -> Value:
    """Checks 2–5 of one cell `{"value", "quote", "null_reason"}` of a reply. A null value keeps
    the model's reason when it is `absent` or `not_applicable` (else `absent`)."""
    if not isinstance(raw, dict):
        return _failed("unparseable", "type")
    value = raw.get("value")
    if value is None or value == []:
        reason = raw.get("null_reason")
        return Value(None, None, None, None, None,
                     reason if reason in _MODEL_NULLS else "absent", (), None)
    try:
        value = coerce(ctype, value)
    except ValueError:
        return _failed("unparseable", "type")
    quote = raw.get("quote")
    span = find_quote(section_text, quote) if isinstance(quote, str) else None
    if span is None:
        return _failed("ungrounded", "span")
    start, end = span
    located = section_text[start:end]
    failed: tuple[str, ...] = ()
    if column in NUMERIC and not number_in_quote(value, located):
        failed = ("value_in_quote",)
    found = regex_value(column, section_text)
    agrees = None if found is None else float(value) in {float(f) for f in found}
    return Value(value, located, start, end, "auto-accepted" if failed else "verified", None,
                 failed, agrees)


# -- calls ---------------------------------------------------------------------------------------

def _call(client, system: str, text: str, parse: Callable[[str], dict], *,
          max_tokens: int = MAX_TOKENS) -> tuple[dict | None, str, Counter]:
    """(parsed reply or None, outcome, call counts) of one unit's call, with one retry at
    repeat 1 for an unparseable reply. A rejected input (CachedFailure, fresh or replayed) is
    the outcome `model_error`; every other failure (retries exhausted, the usage limit, a
    configuration error, a budget stop) propagates and stops the run (ruling P21).
    `max_tokens` (default the extractor's `MAX_TOKENS`, so Phase 3 cache keys are unchanged)
    is in the cache key; the Phase 4 passes give their own (preflight ruling C3)."""
    counts: Counter = Counter()
    for repeat in (0, 1):
        try:
            c = client.complete(system, text, max_tokens=max_tokens, repeat=repeat,
                                cache_failures=True)
        except CachedFailure:
            counts["failed"] += 1
            return None, "model_error", counts
        counts["cached" if c.cached else "made"] += 1
        try:
            return parse(c.text), "reply" if repeat == 0 else "reply_repeat_1", counts
        except ModelOutputError:
            continue
    return None, "unparseable", counts


def _parse_reply(text: str) -> dict:
    reply, _ = parse_json_recovering(text, _REPLY_KEYS)
    if not isinstance(reply["section"], dict) or not isinstance(reply["draws"], list) \
            or not all(isinstance(d, dict) for d in reply["draws"]):
        raise ModelOutputError("expected a section object and a list of draw objects")
    return reply


def _raw_value(cell: Any) -> Any:
    return cell.get("value") if isinstance(cell, dict) else None


def _identity(draws: list[dict]) -> list[dict]:
    return [{c: _raw_value(d.get(c)) for c in _IDENTIFY} for d in draws]


def _extract_unit(unit: Unit, client, cfg: ExtractionConfig, contracts: dict[str, Contract]
                  ) -> tuple[UnitExtraction, Counter]:
    counts: Counter = Counter()
    section: dict[str, Value] = {}
    replies: dict[str, list[dict] | NullReason] = {}   # group -> raw draws, or why none
    calls: dict[str, str] = {}
    for group in sorted(cfg.groups):
        cols = cfg.groups[group]
        reply, outcome, n = _call(client, prompt(group, cfg, contracts), unit.text,
                                  _parse_reply)
        counts += n
        calls[group] = outcome
        if reply is None:
            reason: NullReason = "model_error" if outcome == "model_error" else "unparseable"
            section.update({c: _failed(reason) for c in cols if c in SECTION_COLUMNS})
            replies[group] = reason
            continue
        for c in SECTION_COLUMNS:
            if c in cols:
                cell = reply["section"].get(c)
                section[c] = ABSENT if cell is None else check_value(
                    c, _ctype(contracts, c), cell, unit.text)
        replies[group] = reply["draws"]
    base = next(g for g, cols in cfg.groups.items() if "bridge" in cols)
    base_draws = replies[base]
    draws: list[dict[str, Value]] = []
    if isinstance(base_draws, str):     # no draws: other groups' draws match nothing
        counts["draws_dropped"] += sum(len(got) for g, got in replies.items()
                                       if g != base and not isinstance(got, str)
                                       and any(c in DRAW_COLUMNS for c in cfg.groups[g]))
    else:
        draws = [{} for _ in base_draws]
        for group in sorted(cfg.groups):
            cols = [c for c in DRAW_COLUMNS if c in cfg.groups[group]]
            got = replies[group]
            if not cols:
                continue
            if isinstance(got, str):
                for d in draws:
                    d.update({c: _failed(got) for c in cols})
                continue
            pairs = [(i, i) for i in range(len(got))] if group == base \
                else match_draws(_identity(base_draws), _identity(got))
            for i, j in pairs:
                if i is None:
                    counts["draws_dropped"] += 1
                    continue
                for c in cols:
                    cell = None if j is None else got[j].get(c)
                    draws[i][c] = ABSENT if cell is None else check_value(
                        c, _ctype(contracts, c), cell, unit.text)
        draws = [{c: d[c] for c in DRAW_COLUMNS} for d in draws]
    section = {c: section[c] for c in SECTION_COLUMNS}
    return UnitExtraction(unit.text_sha256, section, draws, calls), counts


def extract_unit(unit: Unit, client, cfg: ExtractionConfig, contracts: dict[str, Contract]
                 ) -> UnitExtraction:
    """The checked values of one unit: one call per column group."""
    return _extract_unit(unit, client, cfg, contracts)[0]


def _map(fn: Callable, items: list, workers: int) -> list:
    """`fn` over `items`, results in item order, on `workers` threads. The first exception to
    happen stops the rest at once: no queued item starts after it (the items in flight end;
    their replies are cached), and it is raised (ruling P21: a failure stops the run)."""
    if workers <= 1:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(fn, x) for x in items]
        try:
            done, pending = wait(futures, return_when=FIRST_EXCEPTION)
            for f in pending:
                f.cancel()
            failed = next((f for f in futures if f in done and f.exception() is not None),
                          None)
            if failed is not None:
                failed.result()                # raises its exception
            return [f.result() for f in futures]
        except BaseException:
            for f in futures:
                f.cancel()
            raise


def _empty_counts() -> dict:
    return {"values": 0, "non_null": 0, "grounded": 0, "ungrounded": 0, "unparseable": 0,
            "model_error": 0, "absent": 0, "not_applicable": 0, "value_in_quote_failed": 0,
            "regex": {"agree": 0, "disagree": 0, "none": 0}}


def _count(counts: dict, v: Value) -> None:
    counts["values"] += 1
    if v.value is not None:
        counts["non_null"] += 1
        counts["grounded"] += 1
        counts["value_in_quote_failed"] += "value_in_quote" in v.checks_failed
        counts["regex"][{True: "agree", False: "disagree", None: "none"}[v.regex_agrees]] += 1
        return
    counts[v.null_reason] += 1
    if v.checks_failed:            # a value the model gave that failed its type or span
        counts["non_null"] += 1


def _report(store: Store, us: list[Unit], results: list, counts: Counter, extra: dict) -> dict:
    """The unhashed extraction report: units and sections, calls, draws and, per model column,
    values by outcome (over units, not occurrences). E1 is grounded / non_null. `regex`
    counts grounded values: agree when the value is among the values the column's expression
    finds anywhere in the section (lenient for sections with several draws), disagree when
    it finds others only, none when it finds nothing."""
    docs = chain_docs(store)
    columns = {c: _empty_counts() for c in MODEL_COLUMNS}
    outcomes: dict[str, Counter] = {}
    for r in results:
        for c, v in r.section.items():
            _count(columns[c], v)
        for d in r.draws:
            for c, v in d.items():
                _count(columns[c], v)
        for group, outcome in getattr(r, "calls", {}).items():
            outcomes.setdefault(group, Counter())[outcome] += 1
    for key, n in counts.items():      # the second pass: one call per unit, no groups
        if key.startswith("outcome:"):
            outcomes.setdefault("second_pass", Counter())[key.split(":", 1)[1]] += n
    return {**extra, "max_tokens": MAX_TOKENS, "units": len(us),
            "sections": sum(len(u.occurrences) for u in us),
            "newest_version_sections": sum(o.doc_id == docs[-1] for u in us
                                           for o in u.occurrences) if docs else 0,
            "calls": {k: counts[k] for k in ("made", "cached", "failed")},
            "outcomes": {g: dict(sorted(c.items())) for g, c in sorted(outcomes.items())},
            "draws": sum(len(r.draws) for r in results),
            "draws_dropped": counts["draws_dropped"], "columns": columns}


def extract_all(store: Store, client, cfg: ExtractionConfig, contracts: dict[str, Contract],
                *, workers: int = 1) -> tuple[list[UnitExtraction], dict]:
    """(the extraction of every unit in unit order, the extraction report)."""
    us = units(store)
    done = _map(lambda u: _extract_unit(u, client, cfg, contracts), us, workers)
    counts = sum((c for _, c in done), Counter())
    results = [r for r, _ in done]
    return results, _report(store, us, results, counts, {
        "pass": "first", "prompt_version": PROMPT_VERSION, "groups": cfg.groups,
        "specs": cfg.specs})


def metered_client(max_calls: int, *, client=None, profile: str | None = None):
    """`client` (default: the client of model `profile`, else the configured generator, with
    the configured reply cache) behind a `MeteredClient` whose budget counts every transport
    attempt against `max_calls` (Phase 3: retries count)."""
    from adr_eval import runner
    from adr_eval.llm import load_prices
    from adr_eval.pipeline import Budget, MeteredClient

    config = runner.load_config()
    if client is None:
        profiles = runner.load_profiles(runner.REPO_ROOT / config.get("models",
                                                                      runner.MODELS_PATH))
        client = runner.make_client(profile or config["generator"], profiles,
                                    runner.llm_cache(config))
    prices = load_prices(runner.REPO_ROOT / config.get("prices", "config/prices.json"))
    return MeteredClient(client, Budget(None, max_calls, count_attempts=True), prices)


# -- rows ----------------------------------------------------------------------------------------

def _structure(occ: SectionUnit) -> dict[str, tuple[Any, ValueProv]]:
    doc = occ.doc_id
    state = (None, null_prov(doc, "structure.state@1", "absent")) if occ.state is None \
        else (occ.state, value_prov(doc, "structure.state@1", occ.state_span))
    return {
        "section": (occ.section, value_prov(doc, "structure.section@1", occ.heading_span)),
        "version": (occ.version, value_prov(doc, "structure.version@1")),
        "heading": (occ.heading, value_prov(doc, "structure.heading@1", occ.heading_span)),
        "state": state,
        "waterway_key": (heading_waterway_key(occ.heading),
                         value_prov(doc, "structure.waterway_key@1", occ.heading_span)),
    }


def _model_cell(occ: SectionUnit, spec: str, v: Value, is_list: bool
                ) -> tuple[Any, ValueProv | list[ValueProv]]:
    if v.value is None:
        if is_list:            # a non-null list column: [] is absent, with no provenance
            return [], []
        return None, ValueProv(doc_id=occ.doc_id, spec_id=spec, status=v.status,
                               null_reason=v.null_reason, checks_failed=list(v.checks_failed))
    p = ValueProv(doc_id=occ.doc_id, start=occ.start + v.start, end=occ.start + v.end,
                  spec_id=spec, status=v.status, quote=v.quote,
                  checks_failed=list(v.checks_failed), regex_agrees=v.regex_agrees)
    if is_list:
        return list(v.value), [p] * len(v.value)
    return v.value, p


def drawbridge_rows(extractions: list[UnitExtraction] | list[Facts], all_units: list[Unit],
                    specs: dict[str, str] | None = None) -> dict[str, list[RowRecord]]:
    """The rows of `drawbridge_sections` and `drawbridge_bridges`: every occurrence (section,
    version) of each extracted unit, its spans shifted by the occurrence's start. Draw rows
    repeat the section's state, waterway and waterway key with their provenance. `specs` are
    the model columns' spec ids (default: `extraction.json`)."""
    specs = load_config().specs if specs is None else specs
    by_sha = {u.text_sha256: u for u in all_units}
    sections: list[RowRecord] = []
    bridges: list[RowRecord] = []
    for ex in extractions:
        for occ in by_sha[ex.unit].occurrences:
            cells = dict(_structure(occ))
            for c in SECTION_COLUMNS:
                cells[c] = _model_cell(occ, specs[c], ex.section.get(c, ABSENT), False)
            sections.append(RowRecord(doc_id=occ.doc_id, row={c: v for c, (v, _) in cells.items()},
                                      prov={c: p for c, (_, p) in cells.items()}))
            for k, draw in enumerate(ex.draws, 1):
                dcells = {c: cells[c] for c in ("section", "version")}
                dcells["draw"] = (k, value_prov(occ.doc_id, "structure.draw@1"))
                dcells.update({c: cells[c] for c in ("state", "waterway", "waterway_key")})
                for c in DRAW_COLUMNS:
                    dcells[c] = _model_cell(occ, specs[c], draw.get(c, ABSENT),
                                            c == "closed_periods")
                bridges.append(RowRecord(doc_id=occ.doc_id,
                                         row={c: v for c, (v, _) in dcells.items()},
                                         prov={c: p for c, (_, p) in dcells.items()}))
    return {SECTIONS_TABLE: sections, BRIDGES_TABLE: bridges}


# -- the second pass -----------------------------------------------------------------------------

_LINE = re.compile(r"^\s*(\d+(?:\.\d+\.[a-e])?)\.?\s+([A-Z][A-Z ]*?)\s*:\s*(.*?)\s*$")
_TOP = (("1", "WATERWAY", "waterway"), ("2", "SEASONAL", "seasonal"),
        ("3", "OWNER", "owner_or_agency"), ("4", "VHF CHANNEL", "vhf_channel"))
_PER_DRAW = (("a", "BRIDGE", "bridge"), ("b", "MILE", "mile"),
             ("c", "NOTICE HOURS", "notice_hours"), ("d", "OPENS ON SIGNAL", "opens_on_signal"),
             ("e", "CLOSED PERIODS", "closed_periods"))
_ANSWER = re.compile(r'^(.*?)\s*\|\s*"(.*)"\s*$')


def _numbered_cell(column: str, rest: str) -> dict:
    m = _ANSWER.match(rest)
    answer, quote = (m.group(1).strip(), m.group(2) or None) if m else (rest.strip(), None)
    if not answer or answer.upper() == "NONE":
        return {"value": None, "quote": None, "null_reason": "absent"}
    value: Any = answer
    if column in ("seasonal", "opens_on_signal") and answer.upper() in ("YES", "NO"):
        value = answer.upper() == "YES"
    elif column == "closed_periods":
        value = [p.strip() for p in answer.split(";") if p.strip()]
    return {"value": value, "quote": quote, "null_reason": None}


def parse_numbered(text: str) -> dict:
    """A second-pass reply as `{"section": {column: cell}, "draws": [{column: cell}]}`, the
    shape `check_value` reads. Lines that do not start with a question number are ignored;
    ModelOutputError when the numbered lines are not exactly 1–5 and, for each of the stated
    number of draws, 5.k.a–e, in order and with their labels."""
    entries = [m.groups() for line in text.splitlines() if (m := _LINE.match(line))]
    top = [(n, label) for n, label, _ in _TOP] + [("5", "DRAWS")]
    if [(n, label) for n, label, _ in entries[:5]] != top:
        raise ModelOutputError("the answers are not numbered 1 to 5 with their labels")
    count = _ANSWER.match(entries[4][2])
    count_text = count.group(1).strip() if count else entries[4][2].strip()
    if not count_text.isdigit():
        raise ModelOutputError("5. DRAWS is not a number")
    n = int(count_text)
    want = [(f"5.{k}.{x}", label) for k in range(1, n + 1) for x, label, _ in _PER_DRAW]
    rest = entries[5:]
    if [(num, label) for num, label, _ in rest] != want:
        raise ModelOutputError(f"the draw answers are not 5.1.a to 5.{n}.e with their labels")
    section = {col: _numbered_cell(col, entries[i][2]) for i, (_, _, col) in enumerate(_TOP)}
    draws = [{col: _numbered_cell(col, rest[k * 5 + i][2])
              for i, (_, _, col) in enumerate(_PER_DRAW)} for k in range(n)]
    return {"section": section, "draws": draws}


def _second_pass_unit(unit: Unit, client, system: str, contracts: dict[str, Contract]
                      ) -> tuple[Facts, Counter]:
    reply, outcome, counts = _call(client, system, unit.text, parse_numbered)
    counts[f"outcome:{outcome}"] += 1
    if reply is None:
        reason: NullReason = "model_error" if outcome == "model_error" else "unparseable"
        return Facts(unit.text_sha256, {c: _failed(reason) for c in SECTION_COLUMNS}, []), counts

    def check(c: str, cell: dict) -> Value:
        return check_value(c, _ctype(contracts, c), cell, unit.text)

    section = {c: check(c, reply["section"][c]) for c in SECTION_COLUMNS}
    draws = [{c: check(c, d[c]) for c in DRAW_COLUMNS} for d in reply["draws"]]
    return Facts(unit.text_sha256, section, draws), counts


def second_pass_all(store: Store, client, contracts: dict[str, Contract], *, workers: int = 1
                    ) -> tuple[list[Facts], dict]:
    """(the second-pass facts of every unit in unit order, its report)."""
    us = units(store)
    system = second_pass_prompt(contracts)
    done = _map(lambda u: _second_pass_unit(u, client, system, contracts), us, workers)
    counts = sum((c for _, c in done), Counter())
    facts = [f for f, _ in done]
    return facts, _report(store, us, facts, counts, {
        "pass": "second", "prompt_version": SECOND_PASS_VERSION})


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8") + b"\n"


def write_facts(store_path: Path, snapshot: str, facts: list[Facts]) -> tuple[str, Path]:
    """Write the facts once as `<store>/tables/<snapshot>/second-pass-<id[:16]>.jsonl` (one
    canonical JSON object per unit, in unit order; id = SHA-256 of the file); (id, path). The
    same bytes again are a no-op, other bytes under the name are refused (TablesError)."""
    data = b"".join(_canonical(asdict(f)) for f in sorted(facts, key=lambda f: f.unit))
    facts_id = hashlib.sha256(data).hexdigest()
    path = _dir(store_path, snapshot) / f"second-pass-{facts_id[:16]}.jsonl"
    _write_once(path, data, "second-pass file")
    return facts_id, path


def _value_of(d: dict) -> Value:
    return Value(d["value"], d["quote"], d["start"], d["end"], d["status"], d["null_reason"],
                 tuple(d["checks_failed"]), d["regex_agrees"])


def load_facts(store_path: Path, facts_id: str) -> list[Facts]:
    """The facts of the second-pass file whose SHA-256 is `facts_id`; TablesError when no such
    file is there (or its bytes have another hash)."""
    if re.fullmatch(_HEX64, facts_id):
        for path in sorted((Path(store_path) / TABLES_DIR).glob(
                f"*/second-pass-{facts_id[:16]}.jsonl")):
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() == facts_id:
                return [Facts(d["unit"], {c: _value_of(v) for c, v in d["section"].items()},
                              [{c: _value_of(v) for c, v in draw.items()} for draw in d["draws"]])
                        for d in map(json.loads, data.splitlines())]
    raise TablesError(f"no second-pass file {facts_id[:12]} under {store_path}/{TABLES_DIR}")


# -- matching and agreement ----------------------------------------------------------------------

def bridge_key(name: str) -> str:
    """The waterways key of a bridge name without a trailing " bridge" or " drawbridge"."""
    key = normalise_key("waterways", name)
    for suffix in (" drawbridge", " bridge"):
        if key.endswith(suffix):
            return key[:-len(suffix)]
    return key


def _key_of(d: dict) -> str | None:
    name = d.get("bridge")
    return bridge_key(name) if isinstance(name, str) and name.strip() else None


def _mile_of(d: dict) -> float | None:
    try:
        return coerce("real", d.get("mile"))
    except ValueError:
        return None


def match_draws(a: list[dict], b: list[dict]) -> list[tuple[int | None, int | None]]:
    """Pair the draws of two lists (`bridge`, `mile` raw values): equal bridge keys first, in
    order, then equal miles among the unmatched. Returns (i, j) for each draw of `a` in order
    (j None when unmatched), then (None, j) for each unmatched draw of `b`."""
    paired: list[int | None] = [None] * len(a)
    used: set[int] = set()
    keys_b = [_key_of(d) for d in b]
    for i, d in enumerate(a):
        key = _key_of(d)
        j = next((j for j, k in enumerate(keys_b) if key is not None and k == key
                  and j not in used), None)
        if j is not None:
            paired[i] = j
            used.add(j)
    miles_b = [_mile_of(d) for d in b]
    for i, d in enumerate(a):
        mile = _mile_of(d)
        if paired[i] is not None or mile is None:
            continue
        j = next((j for j, m in enumerate(miles_b) if m == mile and j not in used), None)
        if j is not None:
            paired[i] = j
            used.add(j)
    return [(i, paired[i]) for i in range(len(a))] + [(None, j) for j in range(len(b))
                                                       if j not in used]


def _same(column: str, a: Any, b: Any) -> bool:
    """Agreement of two values: text by key, numbers and bools exactly, lists as key sets;
    two nulls agree."""
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    if isinstance(a, list) and isinstance(b, list):
        return {base_key(x) for x in a} == {base_key(x) for x in b}
    if isinstance(a, str) and isinstance(b, str):
        key = {"bridge": bridge_key, "waterway": lambda s: normalise_key("waterways", s)}.get(
            column, base_key)
        return key(a) == key(b)
    return False


def _plain(draws: list[dict[str, Value]]) -> list[dict]:
    return [{c: v.value for c, v in d.items()} for d in draws]


def agreement(first: list[UnitExtraction], second: list[Facts]) -> dict:
    """Per model column, how often the passes agree over the units both have: section columns
    per unit, draw columns per matched draw (`match_draws`), and `bridge` as the share of units
    whose sets of draw keys are equal. Shares are None when nothing was compared."""
    by_second = {f.unit: f for f in second}
    tally = {c: [0, 0] for c in MODEL_COLUMNS}          # compared, agree
    draws = Counter()
    seen = set()
    for f in sorted(first, key=lambda f: f.unit):
        s = by_second.get(f.unit)
        if s is None:
            continue
        seen.add(f.unit)
        for c in SECTION_COLUMNS:
            tally[c][0] += 1
            tally[c][1] += _same(c, f.section.get(c, ABSENT).value, s.section.get(c, ABSENT).value)
        a, b = _plain(f.draws), _plain(s.draws)
        for i, j in match_draws(a, b):
            if i is None or j is None:
                draws["first_only" if j is None else "second_only"] += 1
                continue
            draws["matched"] += 1
            for c in DRAW_COLUMNS:
                if c != "bridge":
                    tally[c][0] += 1
                    tally[c][1] += _same(c, a[i].get(c), b[j].get(c))
        keys = [{k for d in x if (k := _key_of(d)) is not None} for x in (a, b)]
        tally["bridge"][0] += 1
        tally["bridge"][1] += keys[0] == keys[1]
    units_first = {f.unit for f in first}
    return {"columns": {c: {"compared": n, "agree": k, "share": k / n if n else None}
                        for c, (n, k) in tally.items()},
            "draws": {k: draws[k] for k in ("matched", "first_only", "second_only")},
            "units": {"compared": len(seen), "first_only": len(units_first - seen),
                      "second_only": len(set(by_second) - units_first)}}
