"""Table contracts and the row validator (Phase 3 spec §5.1).

Each table has a committed contract, `config/tables/<table>.json`: its columns (type,
nullability, description, extraction `spec_id`, allowed values), the `key` that identifies a row,
the `order` that totally orders the stored rows (the key is part of it), the corpus, document
selector and loader that fill it, and which columns link to an entity table. `validate_row`
checks a row and its provenance against the contract; a row that fails is rejected and counted
when the table is built, never stored silently.
"""

from __future__ import annotations

import datetime
import hashlib
import math
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from adr_eval.corpora import REPO_ROOT
from adr_store.records import canonical_json
from adr_store.tables.provenance import SPEC_ID, RowRecord, ValueProv

CONTRACT_DIR = REPO_ROOT / "config" / "tables"
ColumnType = Literal["text", "int", "real", "bool", "date", "text[]", "real[]"]
_INT64 = 2**63
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Column(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, title="Column")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    type: ColumnType
    nullable: bool
    description: str = Field(min_length=1, max_length=120, pattern=r"^[^\r\n]*$")
    spec_id: str = Field(pattern=SPEC_ID)
    allowed: list[str] | None = None
    computed: Literal["display_name"] | None = None  # filled per view (Task 3), not stored

    @model_validator(mode="after")
    def _consistent(self) -> Column:
        if self.allowed is not None:
            if self.type not in ("text", "text[]"):
                raise ValueError(f"{self.name}: allowed values need a text column")
            if not self.allowed or len(set(self.allowed)) != len(self.allowed):
                raise ValueError(f"{self.name}: allowed values must be distinct and not empty")
        return self


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, title="Source")

    corpus: Literal["gov", "research"]
    selector: Literal["fr", "papers_manifest", "ecfr:33:117", "entities"]
    loader: Literal["metadata", "extraction", "entities"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, title="Contract")

    table: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: int = Field(ge=1)
    kind: Literal["data", "entity"]
    description: str = Field(min_length=1, pattern=r"^[^\r\n]*$")
    columns: list[Column] = Field(min_length=1)
    key: list[str] = Field(min_length=1)
    order: list[str] = Field(min_length=1)  # key ⊆ order ⊆ columns
    list_column: str  # what op "list" returns
    source: Source
    entities: dict[str, str] = {}  # column -> entity type

    @model_validator(mode="after")
    def _references_resolve(self) -> Contract:
        by_name = {c.name: c for c in self.columns}
        if len(by_name) != len(self.columns):
            raise ValueError("duplicate column names")
        for what, names in (("key", self.key), ("order", self.order),
                            ("entities", list(self.entities))):
            if len(set(names)) != len(names):
                raise ValueError(f"{what}: repeated column")
            if unknown := [n for n in names if n not in by_name]:
                raise ValueError(f"{what}: no such column {unknown[0]!r}")
        if not set(self.key) <= set(self.order):
            raise ValueError("every key column must be in the order")
        if self.list_column not in by_name:
            raise ValueError(f"list_column: no such column {self.list_column!r}")
        for name in self.order:
            if by_name[name].computed or (name in self.key and by_name[name].nullable):
                raise ValueError(f"{name}: a computed or nullable column cannot identify or "
                                 f"order rows")
        return self

    @property
    def stored_columns(self) -> list[Column]:
        return [c for c in self.columns if c.computed is None]


def contract_sha256(c: Contract) -> str:
    """SHA-256 of the contract's canonical JSON."""
    return hashlib.sha256(canonical_json(c)).hexdigest()


def load_contracts(directory: Path = CONTRACT_DIR, corpus: str | None = None
                   ) -> dict[str, Contract]:
    """The contracts in `directory` (one `<table>.json` each), by table name, in name order;
    only those of `corpus` when given."""
    out: dict[str, Contract] = {}
    for path in sorted(Path(directory).glob("*.json")):
        c = Contract.model_validate_json(path.read_bytes())
        if c.table != path.stem:
            raise ValueError(f"{path}: the contract is for table {c.table!r}")
        if corpus is None or c.source.corpus == corpus:
            out[c.table] = c
    return out


# -- the validator -----------------------------------------------------------------------------

def _kind(v: Any) -> str:
    return type(v).__name__


def _type_problem(typ: str, v: Any) -> str | None:
    """Why `v` (not None) is no value of scalar type `typ`, or None."""
    if typ == "text":
        return None if isinstance(v, str) else f"expected text, got {_kind(v)}"
    if typ == "int":
        if isinstance(v, bool) or not isinstance(v, int):
            return f"expected int, got {_kind(v)}"
        return None if -_INT64 <= v < _INT64 else "int outside 64 bits"
    if typ == "real":
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return f"expected real, got {_kind(v)}"
        return None if math.isfinite(v) else "real is not finite"
    if typ == "bool":
        return None if isinstance(v, bool) else f"expected bool, got {_kind(v)}"
    if typ == "date":
        if not isinstance(v, str):
            return f"expected date, got {_kind(v)}"
        try:
            ok = bool(_ISO_DATE.match(v)) and datetime.date.fromisoformat(v) is not None
        except ValueError:
            ok = False
        return None if ok else "not an ISO date"
    raise AssertionError(typ)


def _value_problems(col: Column, v: Any) -> list[str]:
    """Problems of one non-null value of `col`, each prefixed with the column name."""
    name = col.name
    if col.type.endswith("[]"):
        scalar = col.type[:-2]
        if not isinstance(v, list):
            return [f"{name}: expected {col.type}, got {_kind(v)}"]
        for el in v:
            if el is None or (p := _type_problem(scalar, el)) is not None:
                kinds = "null" if el is None else _kind(el)
                return [f"{name}: expected {col.type}, got a list holding {kinds}"]
            if col.allowed is not None and el not in col.allowed:
                return [f"{name}: {el!r} is not an allowed value"]
        return []
    if (p := _type_problem(col.type, v)) is not None:
        return [f"{name}: {p}"]
    if col.allowed is not None and v not in col.allowed:
        return [f"{name}: {v!r} is not an allowed value"]
    return []


def _prov_problems(col: Column, value: Any, prov: ValueProv | list[ValueProv]) -> list[str]:
    name = col.name
    is_list_value = col.type.endswith("[]") and value is not None
    if is_list_value:
        if not isinstance(prov, list):
            return [f"{name}: a list column needs a list of provenance entries"]
        if not isinstance(value, list) or len(value) != len(prov):
            n = len(value) if isinstance(value, list) else 0
            return [f"{name}: {n} values, {len(prov)} provenance entries"]
        entries = prov
    else:
        if isinstance(prov, list):
            return [f"{name}: a scalar column needs one provenance entry, got a list"]
        entries = [prov]
    problems = []
    for p in entries:
        if p.spec_id != col.spec_id:
            problems.append(f"{name}: provenance spec {p.spec_id}, contract says {col.spec_id}")
        elif value is None and p.null_reason is None:
            problems.append(f"{name}: null without a null reason")
        elif value is not None and p.null_reason is not None:
            problems.append(f"{name}: a value with a null reason")
        elif value is not None and p.status == "rejected":
            problems.append(f"{name}: a stored value with status rejected")
    return problems


def validate_row(c: Contract, rec: RowRecord) -> list[str]:
    """What is wrong with `rec` under contract `c`; [] when it is valid. Checks that the row
    has exactly the stored columns, each value has its column's type (no coercion: a bool is not
    an int, a string is not a number) and allowed values, a null is allowed and has a null
    reason, and every value has provenance of the column's spec (one entry per list element)."""
    problems: list[str] = []
    stored = {col.name: col for col in c.stored_columns}
    for name in sorted(set(rec.row) - set(stored)):
        problems.append(f"{name}: not a column of the contract")
    for name in sorted(set(rec.prov) - set(stored)):
        problems.append(f"{name}: provenance for a column the contract does not store")
    for name, col in stored.items():
        if name not in rec.row:
            problems.append(f"{name}: missing")
            continue
        value = rec.row[name]
        if value is None:
            if not col.nullable:
                problems.append(f"{name}: null in a non-nullable column")
                continue
        elif found := _value_problems(col, value):
            problems.extend(found)
            continue
        if name not in rec.prov:
            problems.append(f"{name}: no provenance")
        else:
            problems.extend(_prov_problems(col, value, rec.prov[name]))
    return problems
