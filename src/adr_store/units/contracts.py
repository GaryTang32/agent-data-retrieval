"""Unit contracts and the nested unit validator (Phase 4 spec §5.2, §5.3; builder note 1).

Each unit type has a committed contract, `config/units/<type>.json`: the fields of its body,
each with a type, nullability, a one-line description, the extraction `spec_id`
(`<type>.<field>@1`; a nested field carries the spec id of the top-level field it belongs to)
and, for text fields, allowed values. The format is the Phase 3 contract's, extended with
nested fields: `object` (one nested contract) and `object[]` (a list of them), plus `int[]`,
`span` (exactly two ints, `0 <= start <= end`, offsets in the unit's document's canonical
text; every span field has this type) and `json` (any canonical JSON value up to
`MAX_VALUE_BYTES`, whose shape the owning pydantic model checks; preflight ruling C7). The
Phase 3 `Contract` and `Column` models are not touched, because every tables id hashes them;
the scalar checks delegate to the Phase 3 validator (`tables.contracts.type_problem`).

A model-written field (`when_to_use`, a rule card's `subject`, ...) is an `object` holding
`value`, `quotes[]` (`{text, span}`), `status` (Phase 3's `verified` or `auto-accepted`) and
`null_reason` (Phase 3's reasons plus `not_extracted`); a field outside a pass's scope, or
before its pass runs, is `{value: null, quotes: [], status: null, null_reason:
"not_extracted"}` (§5.3, §6.4). A value needs at least one quote and a status and no null
reason; a null value needs a null reason and no status.

`validate_unit` checks a unit's envelope (one document, every source span on it, the contract
named `<type>@<version>`, the id and hashes consistent, no self-reference) and its body
against the contract, reporting problems with dotted and indexed paths
(`body.steps[0].type: missing`); a rule card's closure entries must all name the card's own
document (closure stays in one document, P5 and P31). A unit that fails is rejected and
counted when its file is written, never stored silently.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from adr_eval.corpora import REPO_ROOT
from adr_store.records import canonical_json
from adr_store.tables.contracts import MAX_VALUE_BYTES, ColumnType, type_problem
from adr_store.tables.provenance import SPEC_ID

if TYPE_CHECKING:
    from adr_store.units.envelope import Unit

UNIT_CONTRACT_DIR = REPO_ROOT / "config" / "units"
UnitType = Literal["concept", "rule_card", "procedure", "faq", "table_record"]
UNIT_TYPES: tuple[str, ...] = get_args(UnitType)
FieldType = ColumnType | Literal["int[]", "span", "json", "object", "object[]"]
_NESTED = ("object", "object[]")
MODEL_FIELD_KEYS = frozenset({"value", "quotes", "status", "null_reason"})
_HEX = re.compile(r"^[0-9a-f]+$")


class UnitField(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, title="UnitField")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    type: FieldType
    nullable: bool
    description: str = Field(min_length=1, max_length=120, pattern=r"^[^\r\n]*$")
    spec_id: str = Field(pattern=SPEC_ID)
    allowed: list[str] | None = None
    fields: list[UnitField] | None = None  # exactly when the type is object or object[]

    @model_validator(mode="after")
    def _consistent(self) -> UnitField:
        if self.type in _NESTED and not self.fields:
            raise ValueError(f"{self.name}: an {self.type} field needs its nested fields")
        if self.type not in _NESTED and self.fields is not None:
            raise ValueError(f"{self.name}: only an object field has nested fields")
        if self.fields is not None:
            names = [f.name for f in self.fields]
            if len(set(names)) != len(names):
                raise ValueError(f"{self.name}: duplicate field names")
        if self.allowed is not None:
            if self.type not in ("text", "text[]"):
                raise ValueError(f"{self.name}: allowed values need a text field")
            if not self.allowed or len(set(self.allowed)) != len(self.allowed):
                raise ValueError(f"{self.name}: allowed values must be distinct and not empty")
        return self


class UnitContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, title="UnitContract")

    type: UnitType
    version: int = Field(ge=1)
    description: str = Field(min_length=1, pattern=r"^[^\r\n]*$")
    fields: list[UnitField] = Field(min_length=1)

    @model_validator(mode="after")
    def _distinct(self) -> UnitContract:
        names = [f.name for f in self.fields]
        if len(set(names)) != len(names):
            raise ValueError("duplicate field names")
        return self


def unit_contract_sha256(c: UnitContract) -> str:
    """SHA-256 of the contract's canonical JSON."""
    return hashlib.sha256(canonical_json(c)).hexdigest()


def load_unit_contracts(directory: Path = UNIT_CONTRACT_DIR) -> dict[str, UnitContract]:
    """The unit contracts in `directory` (`<type>.json` for each type of `UNIT_TYPES` that has
    a file; the directory's other configs are not contracts), by type, in type order."""
    out: dict[str, UnitContract] = {}
    for t in sorted(UNIT_TYPES):
        path = Path(directory) / f"{t}.json"
        if not path.is_file():
            continue
        c = UnitContract.model_validate_json(path.read_bytes())
        if c.type != t:
            raise ValueError(f"{path}: the contract is for type {c.type!r}")
        out[t] = c
    return out


# -- the validator -----------------------------------------------------------------------------

def _kind(v: Any) -> str:
    return type(v).__name__


def _json_problem(v: Any) -> str | None:
    """Why `v` is no JSON value (dicts with text keys, lists, text, finite numbers, bools,
    null), or None."""
    if v is None or isinstance(v, (str, bool)):
        return None
    if isinstance(v, int):
        return None
    if isinstance(v, float):
        return None if math.isfinite(v) else "not a JSON value"
    if isinstance(v, list):
        return next((p for p in map(_json_problem, v) if p), None)
    if isinstance(v, dict):
        if not all(isinstance(k, str) for k in v):
            return "not a JSON value"
        return next((p for p in map(_json_problem, v.values()) if p), None)
    return "not a JSON value"


def _span_problem(v: Any) -> str | None:
    """Why `v` is no span (a list of two ints, `0 <= start <= end`), or None."""
    if not isinstance(v, list):
        return f"expected span, got {_kind(v)}"
    if len(v) != 2 or any(isinstance(x, bool) or not isinstance(x, int) for x in v):
        return "a span is [start, end], two ints"
    if v[0] < 0:
        return f"span start {v[0]} is negative"
    if v[0] > v[1]:
        return f"span start {v[0]} is after its end {v[1]}"
    return None


def _model_field_problems(v: dict, path: str) -> list[str]:
    """The invariants of a model-written field (its type checks passed)."""
    if v["value"] is not None:
        return ([f"{path}: a value needs at least one quote"] if not v["quotes"] else []) + \
            ([f"{path}: a value needs a status"] if v["status"] is None else []) + \
            ([f"{path}: a value has no null reason"] if v["null_reason"] is not None else [])
    return ([f"{path}: a null value needs a null reason"] if v["null_reason"] is None else []) \
        + ([f"{path}: a null value has no status"] if v["status"] is not None else [])


def _value_problems(f: UnitField, v: Any, path: str) -> list[str]:
    """Problems of one non-null value of `f` at `path`."""
    if f.type == "span":
        return [] if (p := _span_problem(v)) is None else [f"{path}: {p}"]
    if f.type == "json":
        if _json_problem(v) is not None:
            return [f"{path}: not a JSON value"]
        size = len(json.dumps(v, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False).encode("utf-8"))
        return [f"{path}: value over {MAX_VALUE_BYTES} bytes"] if size > MAX_VALUE_BYTES else []
    if f.type == "object":
        if not isinstance(v, dict):
            return [f"{path}: expected object, got {_kind(v)}"]
        problems = _fields_problems(f.fields, v, path)
        if not problems and {g.name for g in f.fields} == MODEL_FIELD_KEYS:
            problems = _model_field_problems(v, path)
        return problems
    if f.type == "object[]":
        if not isinstance(v, list):
            return [f"{path}: expected object[], got {_kind(v)}"]
        problems = []
        for i, el in enumerate(v):
            if not isinstance(el, dict):
                problems.append(f"{path}[{i}]: expected object, got {_kind(el)}")
            else:
                problems.extend(_fields_problems(f.fields, el, f"{path}[{i}]"))
        return problems
    if f.type.endswith("[]"):
        scalar = f.type[:-2]
        if not isinstance(v, list):
            return [f"{path}: expected {f.type}, got {_kind(v)}"]
        for el in v:
            if el is None or type_problem(scalar, el) is not None:
                kinds = "null" if el is None else _kind(el)
                return [f"{path}: expected {f.type}, got a list holding {kinds}"]
            if f.allowed is not None and el not in f.allowed:
                return [f"{path}: {el!r} is not an allowed value"]
        return []
    if (p := type_problem(f.type, v)) is not None:
        return [f"{path}: {p}"]
    if f.allowed is not None and v not in f.allowed:
        return [f"{path}: {v!r} is not an allowed value"]
    return []


def _fields_problems(fields: list[UnitField], obj: dict, path: str) -> list[str]:
    """Problems of an object holding `fields`: every field present, nothing else, each value
    of its type (nulls only where nullable)."""
    problems = []
    by_name = {f.name: f for f in fields}
    for name in sorted(set(obj) - set(by_name), key=str):
        problems.append(f"{path}.{name}: not a field of the contract")
    for f in fields:
        at = f"{path}.{f.name}"
        if f.name not in obj:
            problems.append(f"{at}: missing")
        elif obj[f.name] is None:
            if not f.nullable:
                problems.append(f"{at}: null in a non-nullable field")
        else:
            problems.extend(_value_problems(f, obj[f.name], at))
    return problems


def _envelope_problems(c: UnitContract, unit: Unit) -> list[str]:
    from adr_store.units.envelope import meta_sha256, unit_id

    problems = []
    if unit.type != c.type:
        problems.append(f"type: {unit.type!r} is not the contract's type {c.type!r}")
    if unit.contract != f"{c.type}@{c.version}":
        problems.append(f"contract: {unit.contract!r} is not '{c.type}@{c.version}'")
    if not unit.source_refs:
        problems.append("source_refs: a unit needs at least one source span")
    for i, r in enumerate(unit.source_refs):
        if r.doc_id != unit.doc_id:
            problems.append(f"source_refs[{i}].doc_id: {r.doc_id[:12]}… is not the unit's "
                            f"document {unit.doc_id[:12]}…")
        if (p := _span_problem([r.start, r.end])) is not None:
            problems.append(f"source_refs[{i}]: {p}")
    if sorted(unit.hashes) != ["meta", "text"]:
        problems.append("hashes: expected exactly the keys meta and text")
    else:
        if unit.version != unit.hashes["text"][:12]:
            problems.append("version: not the first 12 digits of hashes.text")
        if unit.hashes["meta"] != meta_sha256(unit):
            problems.append("hashes.meta: not the SHA-256 of the envelope")
    if len(unit.version) == 12 and _HEX.match(unit.version):
        want = unit_id(unit.type, unit.canonical_ref, unit.version, unit.doc_id)
        if unit.unit_id != want:
            problems.append(f"unit_id: {unit.unit_id!r} is not {want!r}")
    else:
        problems.append(f"version: {unit.version!r} is not 12 hex digits")
    a = unit.applicability
    for name in ("supersedes", "superseded_by"):
        if getattr(a, name) == unit.unit_id:
            problems.append(f"applicability.{name}: a unit never names itself")
    return problems


def validate_unit(c: UnitContract, unit: Unit) -> list[str]:
    """What is wrong with `unit` under contract `c`; [] when it is valid. Checks the envelope
    (see the module docstring) and that the body has exactly the contract's fields, each of
    its type, recursively, with nulls only where allowed and text values among the allowed
    ones."""
    return (_envelope_problems(c, unit) + _fields_problems(c.fields, unit.body, "body")
            + _closure_problems(unit))


def _closure_problems(unit: Unit) -> list[str]:
    """Closure stays in the card's document (P5, P31): every `body.closure` entry names the
    unit's own `doc_id`."""
    entries = unit.body.get("closure") if unit.type == "rule_card" else None
    if not isinstance(entries, list):
        return []
    return [f"body.closure[{i}].doc_id: {e['doc_id'][:12]}… is not the unit's document "
            f"{unit.doc_id[:12]}…"
            for i, e in enumerate(entries)
            if isinstance(e, dict) and isinstance(e.get("doc_id"), str)
            and e["doc_id"] != unit.doc_id]
