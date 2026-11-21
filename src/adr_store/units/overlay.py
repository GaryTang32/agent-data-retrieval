"""The unit overlay: knowledge units of one store snapshot, write-once, and the build manifest
that names a build (Phase 4 spec §5.2), on the pattern of the Phase 3 table overlay.

    <store>/units/<snapshot>/<type>-v<version>-<id[:16]>.jsonl          one unit type (units
                                                                        sorted by unit id)
    <store>/units/<snapshot>/<type>-v<version>-<id[:16]>.report.json    counts, rejections with
                                                                        problems, null reasons,
                                                                        grounding
    <store>/units/<snapshot>/units-<id[:16]>.json                       the build manifest
    <store>/units/HEAD                                                  the current units id

A unit file holds one canonical JSON `Unit` per line; its id is the SHA-256 of the file and is
in the name, so builds coexist; an existing file with other bytes is refused, never replaced.
The `.report.json` is not hashed, but it is written once too: writing the same unit file again
with a different report is refused. The manifest lists every unit file of a build and the tables
id and applicability overlay id it read; its SHA-256 is the **units id**. `HEAD` names the
current manifest and moves only through the units merge gate (`units/gate.py` calls
`_set_units_head`). `read_units_head` returns the units id only when that manifest loads,
every unit file included.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from adr_store.records import _HEX64, canonical_json
from adr_store.store import StoreError, write_atomic
from adr_store.tables.overlay import TablesError, _write_once
from adr_store.units.contracts import (
    MODEL_FIELD_KEYS,
    UnitContract,
    unit_contract_sha256,
    validate_unit,
)
from adr_store.units.envelope import Unit

UNITS_DIR = "units"
FORMAT_VERSION = "0.1"


class UnitsError(StoreError):
    """A unit file or manifest is missing, altered or would have to be overwritten."""


class UnitFile(BaseModel):
    """One unit type of a build: the contract it was checked against and its file."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="UnitFile")

    type: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    contract_version: int = Field(ge=1)
    contract_sha256: str = Field(pattern=_HEX64)
    file: str
    sha256: str = Field(pattern=_HEX64)
    units: int = Field(ge=0)
    rejected: int = Field(ge=0)

    @model_validator(mode="after")
    def _named_by_its_id(self) -> UnitFile:
        want = f"{self.type}-v{self.contract_version}-{self.sha256[:16]}.jsonl"
        if self.file != want:
            raise ValueError(f"file {self.file!r} is not {want!r}")
        return self


class UnitsManifest(BaseModel):
    """The content of `units-<id[:16]>.json`: every unit file of one build."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="UnitsManifest")

    format_version: Literal["0.1"]
    snapshot: str = Field(min_length=1)
    corpus: str
    tables_id: str | None = Field(pattern=_HEX64)  # the tables build read (table records)
    applicability: str | None = Field(pattern=_HEX64)  # the applicability overlay id
    passes: dict[str, dict]  # model pass -> what filled its fields (prompt, cache, counts)
    units: list[UnitFile]  # sorted by type

    @model_validator(mode="after")
    def _sorted(self) -> UnitsManifest:
        types = [f.type for f in self.units]
        if types != sorted(set(types)):
            raise ValueError("unit files must be sorted by type and distinct")
        return self


def _dir(store_path: Path, snapshot: str) -> Path:
    if not snapshot or Path(snapshot).name != snapshot or snapshot in (".", ".."):
        raise UnitsError(f"not a snapshot name: {snapshot!r}")
    return Path(store_path) / UNITS_DIR / snapshot


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_unit_file(path: Path, data: bytes, what: str) -> None:
    try:
        _write_once(path, data, what)
    except TablesError as e:
        raise UnitsError(str(e)) from e


# -- unit files ----------------------------------------------------------------------------------

def _model_fields(unit: Unit) -> dict[str, dict]:
    """The body's model-written fields (objects holding value, quotes, status and
    null_reason)."""
    return {k: v for k, v in unit.body.items()
            if isinstance(v, dict) and set(v) == MODEL_FIELD_KEYS}


def _summaries(units: list[Unit]) -> tuple[dict, dict]:
    """(null reasons: field -> reason -> count; grounding: field -> value status -> count)
    over the stored units' model-written fields."""
    nulls: dict[str, dict[str, int]] = {}
    grounding: dict[str, dict[str, int]] = {}
    for u in units:
        for name, f in sorted(_model_fields(u).items()):
            if f["value"] is None:
                by = nulls.setdefault(name, {})
                by[f["null_reason"]] = by.get(f["null_reason"], 0) + 1
            else:
                g = grounding.setdefault(name, {"auto-accepted": 0, "verified": 0})
                g[f["status"]] += 1
    return ({k: dict(sorted(v.items())) for k, v in sorted(nulls.items())},
            dict(sorted(grounding.items())))


def write_units(store_path: Path, snapshot: str, c: UnitContract, units: list[Unit],
                report: dict) -> UnitFile:
    """Validate `units` against `c` and write the valid ones once, sorted by unit id, with a
    `.report.json` beside them. A unit that fails validation is rejected and counted, not
    stored. Two units with the same id are a compiler error and refused (UnitsError) before
    anything is written, so the file never depends on input order. `report` is filled in place
    (and written): `type`, `contract_version`, `contract_sha256`, `sha256`, `units`,
    `rejected` (one entry per rejected unit: `unit_id`, `doc_id`, `problems`), `null_reasons`
    and `grounding` (over the stored units' model-written fields). An existing unit file of
    this id is left as it is when its bytes are the same and refused (UnitsError) when they
    are not; so is its report."""
    directory = _dir(store_path, snapshot)
    seen: set[str] = set()
    for u in units:
        if u.unit_id in seen:
            raise UnitsError(f"two {c.type} units have the id {u.unit_id!r}; unit ids must be "
                             f"unique (one unit per document and source element)")
        seen.add(u.unit_id)
    rejected: list[dict] = []
    stored: list[tuple[bytes, Unit]] = []
    for u in units:
        if problems := validate_unit(c, u):
            rejected.append({"unit_id": u.unit_id, "doc_id": u.doc_id, "problems": problems})
        else:
            stored.append((canonical_json(u), u))
    stored.sort(key=lambda t: t[1].unit_id)
    rejected.sort(key=lambda r: (r["unit_id"], r["doc_id"], r["problems"]))
    data = b"".join(line for line, _ in stored)
    file_id = _sha256(data)
    uf = UnitFile(type=c.type, contract_version=c.version,
                  contract_sha256=unit_contract_sha256(c),
                  file=f"{c.type}-v{c.version}-{file_id[:16]}.jsonl", sha256=file_id,
                  units=len(stored), rejected=len(rejected))
    path = directory / uf.file
    nulls, grounding = _summaries([u for _, u in stored])
    report.update({"type": c.type, "contract_version": c.version,
                   "contract_sha256": uf.contract_sha256, "sha256": file_id,
                   "units": len(stored), "rejected": rejected, "null_reasons": nulls,
                   "grounding": grounding})
    report_bytes = (json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
                    + "\n").encode("utf-8")
    report_path = path.with_suffix(".report.json")
    if path.exists() and report_path.exists() and report_path.read_bytes() != report_bytes:
        raise UnitsError(f"{report_path} already reports another build of {uf.file} (other "
                         f"rejections or pass details); it is not replaced")
    _write_unit_file(path, data, "unit file")
    _write_unit_file(report_path, report_bytes, "unit report")
    return uf


# -- manifests ---------------------------------------------------------------------------------

def write_units_manifest(store_path: Path, m: UnitsManifest) -> tuple[str, Path]:
    """Write the manifest once; returns (units id, path). The same bytes again are a no-op,
    other bytes under the same name are refused."""
    data = canonical_json(m)
    units_id = _sha256(data)
    path = _dir(store_path, m.snapshot) / f"units-{units_id[:16]}.json"
    _write_unit_file(path, data, "units manifest")
    return units_id, path


def _manifest_files(store_path: Path, units_id: str) -> list[Path]:
    if not re.fullmatch(_HEX64, units_id):
        return []
    return sorted((Path(store_path) / UNITS_DIR).glob(f"*/units-{units_id[:16]}.json"))


def units_manifest_path(store_path: Path, units_id: str) -> Path | None:
    """The manifest file whose SHA-256 is `units_id`, or None."""
    for path in _manifest_files(store_path, units_id):
        if path.is_file() and _sha256(path.read_bytes()) == units_id:
            return path
    return None


def _read_unit_file(store_path: Path, snapshot: str, f: UnitFile) -> bytes:
    path = _dir(store_path, snapshot) / f.file
    try:
        data = path.read_bytes()
    except OSError as e:
        raise UnitsError(f"units {f.type}: {path} is missing or unreadable") from e
    if _sha256(data) != f.sha256:
        raise UnitsError(f"units {f.type}: {path} has hash {_sha256(data)[:12]}, the manifest "
                         f"says {f.sha256[:12]}")
    if data.count(b"\n") != f.units or (data and not data.endswith(b"\n")):
        raise UnitsError(f"units {f.type}: {path} does not hold {f.units} units")
    return data


def load_units_manifest(store_path: Path, units_id: str) -> UnitsManifest:
    """The manifest `units_id`, checked: its hash is the id, it is canonical and sits under its
    snapshot, and every unit file it lists is there with its hash and unit count. Refuses
    (UnitsError) otherwise, naming the type that fails."""
    path = units_manifest_path(store_path, units_id)
    if path is None:
        found = _manifest_files(store_path, units_id)
        if found:
            raise UnitsError(f"{found[0]}: content hash is not the units id {units_id[:12]}")
        raise UnitsError(f"no units manifest {units_id[:12]} under {store_path}/{UNITS_DIR}")
    data = path.read_bytes()
    try:
        m = UnitsManifest.model_validate_json(data)
    except ValidationError as e:
        raise UnitsError(f"{path}: not a valid units manifest: {e.errors()[0]['msg']}") from e
    if canonical_json(m) != data:
        raise UnitsError(f"{path}: not canonical JSON")
    if path.parent.name != m.snapshot:
        raise UnitsError(f"{path}: describes snapshot {m.snapshot[:12]}, not "
                         f"{path.parent.name[:12]}")
    for f in m.units:
        _read_unit_file(store_path, m.snapshot, f)
    return m


def load_units(store_path: Path, m: UnitsManifest, type_: str | None = None) -> list[Unit]:
    """The units of one type of a manifest (every type, in manifest order, when `type_` is
    None), in stored order; each file is checked against the manifest's hash first."""
    files = m.units if type_ is None else [f for f in m.units if f.type == type_]
    if type_ is not None and not files:
        raise UnitsError(f"the build has no unit file of type {type_!r}")
    return [Unit.model_validate_json(line) for f in files
            for line in _read_unit_file(store_path, m.snapshot, f).splitlines()]


# -- HEAD --------------------------------------------------------------------------------------

def read_units_head(store_path: Path) -> str | None:
    """The units id in `<store>/units/HEAD` when it names a manifest that loads (every unit
    file as listed), else None."""
    try:
        units_id = (Path(store_path) / UNITS_DIR / "HEAD").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    try:
        load_units_manifest(store_path, units_id)
    except (UnitsError, OSError):
        return None
    return units_id


def _set_units_head(store_path: Path, units_id: str) -> None:
    """Move HEAD to a manifest that loads. Only the units merge gate (`units/gate.py`) calls
    this."""
    load_units_manifest(store_path, units_id)
    write_atomic(Path(store_path) / UNITS_DIR / "HEAD", f"{units_id}\n".encode())
