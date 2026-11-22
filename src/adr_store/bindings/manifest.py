"""Candidate bindings, the bindings manifest and `bindings/HEAD` (Phase 4 spec §5.2, §12.2–§12.5,
P32, P46, P48; builder note 17; preflight C5, C6, N16; Task 17), on the overlay pattern:

    <store>/bindings/<snapshot>/bindings-candidates-data-<sha[:16]>.jsonl   the build's bindings
    <store>/bindings/<snapshot>/bindings-candidates-<id[:16]>.json          its manifest: the
                                                                            candidates id
    <store>/bindings/<snapshot>/bindings-candidates-<id[:16]>.report.json   B1, B2 (unhashed)
    <store>/bindings/<snapshot>/bindings-data-<sha[:16]>.jsonl              the signed-off set
    <store>/bindings/<snapshot>/bindings-<id[:16]>.json                     its manifest: the
                                                                            bindings id
    <store>/bindings/<snapshot>/review-<id[:16]>.report.json                the review (unhashed)
    <store>/bindings/HEAD                                                   the current bindings

A data file holds one canonical JSON `Binding` per line, sorted by binding id, and is named by
its own SHA-256; its manifest names it with that hash, and the SHA-256 of the manifest is the
id (N16: data and manifest have their own stems and hashes). Every file is written once: the
same bytes again are a no-op, other bytes under the name are refused.

**The build** (`build_candidates`, `adr bindings build`): the enrichment is read again from the
model cache (`--max-calls 0`) and written (write-once, so its id is the file the units pass
read); the compiler (§12.2) runs on it with the rule cards of the units build named by
`units_id` (C6); every binding is tested (§12.3, `checks.mark_tested`); every draw whose
bindings all passed is analysed with Z3 (§12.4, `analysis`, the `[analysis]` extra; imported
here only, at build time); the agreement set (C5) is computed with `reference.agreement_set`
over the reference draws of the Phase 3 second-pass facts `facts_id` (draws paired by bridge
key, then mile), less the draws whose parameters are period-specific or flagged (a period-less
notice or basis whose sentence states times, days, holidays or dates, P46, or a period with
sentence qualifiers or conditions), and each agreement draw is compared with the reference on
the B1 grid; a draw with a mismatch is rejected whole (P48). The candidates manifest records
the units, tables, facts and enrichment ids and the agreement pairs
`[section, Phase 3 draw, bindings' draw]` of the draws still `analysed`.

**The bindings manifest** (`write_bindings`) holds the signed-off set only (§12.5, B3): the
same ids, plus `agreement_set` (Phase 3 `[section, draw]` keys) and `agreement_pairs`, kept
only for draws whose bindings are in the set. `load_bindings` re-validates every binding
(`Binding.model_validate`: ids, version and required facts are those of its content) and
verifies every hash, the order, canonical bytes, and that each binding is `signed_off` with
its tests, its analysis and an approving `model-review` record, that every override names a
forbid of the set, and that each agreement draw is in the set. `promote_bindings` moves
`bindings/HEAD` only to a set that loads and is not empty (builder note 17: no flip gate);
`read_bindings_head` returns the id only when it still loads.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from adr_store.bindings import checks
from adr_store.bindings.dsl import LANGUAGE, Binding
from adr_store.bindings.enrich import section_key
from adr_store.bindings.review import VERIFIER
from adr_store.records import _HEX64, canonical_json
from adr_store.store import StoreError, write_atomic
from adr_store.tables.overlay import TablesError, _write_once

__all__ = ["BINDINGS_DIR", "INSTALL_ANALYSIS", "BindingsError", "BindingsManifest",
           "Candidates", "CandidatesManifest", "build_candidates", "load_bindings",
           "load_candidates", "promote_bindings", "read_bindings_head", "write_bindings",
           "write_candidates"]

BINDINGS_DIR = "bindings"
FORMAT_VERSION = "0.1"
INSTALL_ANALYSIS = "install the analysis extra: pip install -e '.[analysis]'"
_HEX16 = r"[0-9a-f]{16}"


class BindingsError(StoreError):
    """A bindings file or manifest is missing, altered, unsigned or would be overwritten."""


def _pair_list(v: list) -> list:
    return sorted(v, key=lambda p: (section_key(p[0]), *p[1:]))


class _Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal["0.1"]
    snapshot: str = Field(min_length=1)
    units_id: str = Field(pattern=_HEX64)
    tables_id: str = Field(pattern=_HEX64)
    facts_id: str | None = Field(pattern=_HEX64)        # the Phase 3 second-pass facts (C5)
    enrichment_id: str | None = Field(pattern=_HEX64)   # the enrichment compiled (C5)
    agreement_pairs: list[tuple[str, int, int]]          # [section, Phase 3 draw, bindings' draw]
    file: str
    sha256: str = Field(pattern=_HEX64)
    bindings: int = Field(ge=0)
    language: Literal["adr-dsl@1"]

    @model_validator(mode="after")
    def _checked(self):
        if list(self.agreement_pairs) != _pair_list(list(set(self.agreement_pairs))):
            raise ValueError("agreement_pairs must be sorted and distinct")
        return self


class CandidatesManifest(_Manifest):
    """The content of `bindings-candidates-<id[:16]>.json`: one bindings build, every status."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="CandidatesManifest")

    @model_validator(mode="after")
    def _named_by_its_hash(self) -> CandidatesManifest:
        if self.file != f"bindings-candidates-data-{self.sha256[:16]}.jsonl":
            raise ValueError(f"file {self.file!r} is not named by its hash")
        return self


class BindingsManifest(_Manifest):
    """The content of `bindings-<id[:16]>.json` (§5.2): the signed-off bindings; its SHA-256 is
    the bindings id. `agreement_set` holds the Phase 3 (section, draw) keys of the agreement
    draws (C5), `agreement_pairs` the same with the bindings' draw number."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="BindingsManifest")

    agreement_set: list[tuple[str, int]]

    @model_validator(mode="after")
    def _named_and_agreeing(self) -> BindingsManifest:
        if self.file != f"bindings-data-{self.sha256[:16]}.jsonl":
            raise ValueError(f"file {self.file!r} is not named by its hash")
        if list(self.agreement_set) != [(s, p) for s, p, _ in self.agreement_pairs]:
            raise ValueError("agreement_set must be the Phase 3 keys of agreement_pairs")
        return self


# -- files ---------------------------------------------------------------------------------------

def _dir(store_path: Path, snapshot: str) -> Path:
    if not snapshot or Path(snapshot).name != snapshot or snapshot in (".", ".."):
        raise BindingsError(f"not a snapshot name: {snapshot!r}")
    return Path(store_path) / BINDINGS_DIR / snapshot


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _once(path: Path, data: bytes, what: str) -> None:
    try:
        _write_once(path, data, what)
    except TablesError as e:
        raise BindingsError(str(e)) from e


def _data(bindings: list[Binding]) -> bytes:
    ordered = sorted(bindings, key=lambda b: b.binding_id)
    ids = [b.binding_id for b in ordered]
    if len(set(ids)) != len(ids):
        raise BindingsError("two bindings have one binding id")
    return b"".join(canonical_json(Binding.model_validate(b.model_dump())) for b in ordered)


def _find(store_path: Path, prefix: str, the_id: str, what: str) -> Path:
    if re.fullmatch(_HEX64, the_id or ""):
        found = sorted((Path(store_path) / BINDINGS_DIR).glob(f"*/{prefix}-{the_id[:16]}.json"))
        for path in found:
            if path.is_file() and _sha256(path.read_bytes()) == the_id:
                return path
        if found:
            raise BindingsError(f"{found[0]}: content hash is not the {what} id {the_id[:12]}")
    raise BindingsError(f"no {what} manifest {str(the_id)[:12]} under "
                        f"{store_path}/{BINDINGS_DIR}")


def _read(store_path: Path, path: Path, cls, what: str):
    data = path.read_bytes()
    try:
        m = cls.model_validate_json(data)
    except ValidationError as e:
        raise BindingsError(f"{path}: not a valid {what} manifest: {e.errors()[0]['msg']}") from e
    if canonical_json(m) != data:
        raise BindingsError(f"{path}: not canonical JSON")
    if path.parent.name != m.snapshot:
        raise BindingsError(f"{path}: describes snapshot {m.snapshot[:12]}, not "
                            f"{path.parent.name[:12]}")
    dpath = path.parent / m.file
    try:
        raw = dpath.read_bytes()
    except OSError as e:
        raise BindingsError(f"{what}: {dpath} is missing or unreadable") from e
    if _sha256(raw) != m.sha256:
        raise BindingsError(f"{what}: {dpath} has hash {_sha256(raw)[:12]}, the manifest says "
                            f"{m.sha256[:12]}")
    if raw.count(b"\n") != m.bindings or (raw and not raw.endswith(b"\n")):
        raise BindingsError(f"{what}: {dpath} does not hold {m.bindings} bindings")
    out = []
    for n, line in enumerate(raw.splitlines(), 1):
        try:
            b = Binding.model_validate_json(line)
        except ValidationError as e:
            raise BindingsError(f"{what}: binding {n} of {dpath.name} does not validate: "
                                f"{e.errors()[0]['msg']}") from e
        if canonical_json(b) != line + b"\n":
            raise BindingsError(f"{what}: binding {n} of {dpath.name} is not canonical JSON")
        out.append(b)
    ids = [b.binding_id for b in out]
    if ids != sorted(set(ids)):
        raise BindingsError(f"{what}: {dpath.name} is not sorted by distinct binding id")
    return m, out


def _draw(b: Binding) -> tuple[str, int]:
    sel = b.target.get("selector", {})
    return sel.get("section"), sel.get("draw")


# -- candidates ----------------------------------------------------------------------------------

def write_candidates(store_path: Path, snapshot: str, units_id: str, tables_id: str,
                     bindings: list[Binding], *, facts_id: str | None,
                     enrichment_id: str | None, agreement_pairs, report: dict
                     ) -> tuple[str, Path]:
    """Write a build's bindings (every status) once, their manifest and `report` (unhashed);
    (candidates id, manifest path)."""
    data = _data(bindings)
    sha = _sha256(data)
    m = CandidatesManifest(format_version=FORMAT_VERSION, snapshot=snapshot, units_id=units_id,
                           tables_id=tables_id, facts_id=facts_id, enrichment_id=enrichment_id,
                           agreement_pairs=_pair_list([tuple(p) for p in agreement_pairs]),
                           file=f"bindings-candidates-data-{sha[:16]}.jsonl", sha256=sha,
                           bindings=len(bindings), language=LANGUAGE)
    d = _dir(store_path, snapshot)
    _once(d / m.file, data, "candidates file")
    mbytes = canonical_json(m)
    cid = _sha256(mbytes)
    path = d / f"bindings-candidates-{cid[:16]}.json"
    _once(path, mbytes, "candidates manifest")
    write_atomic(path.with_suffix(".report.json"), (json.dumps(
        {**report, "candidates_id": cid}, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n").encode("utf-8"))
    return cid, path


def load_candidates(store_path: Path, candidates_id: str
                    ) -> tuple[CandidatesManifest, list[Binding]]:
    """The candidates `candidates_id`, every hash verified and every binding re-validated."""
    path = _find(store_path, "bindings-candidates", candidates_id, "candidates")
    return _read(store_path, path, CandidatesManifest, "candidates")


# -- the bindings manifest -------------------------------------------------------------------------

def _signed_problems(b: Binding) -> list[str]:
    """Why `b` cannot be loaded by the gate (B3), or []."""
    out = []
    if b.status != "signed_off":
        out.append(f"is {b.status}, not signed_off")
    if b.verifier != VERIFIER:
        out.append(f"has verifier {b.verifier!r}, not a {VERIFIER} model-review record")
    elif b.review.get("verdict") != "approve":
        out.append(f"has no approving review (verdict {b.review.get('verdict')!r})")
    if not b.tests or any(t.get("failures") or t.get("mismatches") for t in b.tests):
        out.append("has no passing tests")
    if not b.analysis or b.analysis.get("conflicts") or b.analysis.get("vacuous"):
        out.append("has no clean analysis")
    return out


def _set_problems(bindings: list[Binding], pairs) -> list[str]:
    forbids = {b.binding_id: _draw(b) for b in bindings if b.effect == "forbid"}
    out = []
    for b in bindings:
        for x in b.overrides:
            if forbids.get(x) != _draw(b):
                out.append(f"binding {b.binding_id[:12]} overrides {x[:12]}, which is no "
                           f"forbid of its draw in the set")
    present = {_draw(b) for b in bindings}
    for s, p, d in pairs:
        if (s, d) not in present:
            out.append(f"agreement draw § {s} draw {d} (Phase 3 draw {p}) has no binding in "
                       f"the set")
    for i, what in ((1, "Phase 3 draw"), (2, "bindings' draw")):
        keys = [(p[0], p[i]) for p in pairs]
        if len(set(keys)) != len(keys):
            out.append(f"agreement pairs name one {what} twice")
    return out


def write_bindings(store_path: Path, snapshot: str, units_id: str, tables_id: str,
                   bindings: list[Binding], *, facts_id: str | None = None,
                   enrichment_id: str | None = None, agreement_pairs=()) -> tuple[str, Path]:
    """Write the signed-off bindings of `bindings` (the others are left out) once, with their
    manifest; (bindings id, manifest path). `agreement_pairs` ([section, Phase 3 draw,
    bindings' draw]) are kept for the draws whose bindings are in the set. Refuses
    (BindingsError) a set an override or an agreement pair cannot be read in."""
    kept = [b for b in bindings if b.status == "signed_off"]
    for b in kept:
        if problems := _signed_problems(b):
            raise BindingsError(f"binding {b.binding_id[:12]} {'; '.join(problems)}")
    present = {_draw(b) for b in kept}
    pairs = _pair_list(list({tuple(p) for p in agreement_pairs if (p[0], p[2]) in present}))
    if problems := _set_problems(kept, pairs):
        raise BindingsError("; ".join(problems))
    data = _data(kept)
    sha = _sha256(data)
    m = BindingsManifest(format_version=FORMAT_VERSION, snapshot=snapshot, units_id=units_id,
                         tables_id=tables_id, facts_id=facts_id, enrichment_id=enrichment_id,
                         agreement_set=[(s, p) for s, p, _ in pairs], agreement_pairs=pairs,
                         file=f"bindings-data-{sha[:16]}.jsonl", sha256=sha,
                         bindings=len(kept), language=LANGUAGE)
    d = _dir(store_path, snapshot)
    _once(d / m.file, data, "bindings file")
    mbytes = canonical_json(m)
    bindings_id = _sha256(mbytes)
    path = d / f"bindings-{bindings_id[:16]}.json"
    _once(path, mbytes, "bindings manifest")
    return bindings_id, path


def load_bindings(store_path: Path, bindings_id: str) -> tuple[BindingsManifest, list[Binding]]:
    """The bindings `bindings_id` (module text): every hash verified, every binding
    re-validated and signed off with an approving model-review record; BindingsError
    otherwise."""
    path = _find(store_path, "bindings", bindings_id, "bindings")
    m, out = _read(store_path, path, BindingsManifest, "bindings")
    for b in out:
        if problems := _signed_problems(b):
            raise BindingsError(f"bindings {bindings_id[:12]}: binding {b.binding_id[:12]} "
                                f"{'; '.join(problems)}")
    if problems := _set_problems(out, m.agreement_pairs):
        raise BindingsError(f"bindings {bindings_id[:12]}: {'; '.join(problems)}")
    return m, out


def read_bindings_head(store_path: Path) -> str | None:
    """The bindings id in `<store>/bindings/HEAD` when it names a set that loads, else None."""
    try:
        bindings_id = (Path(store_path) / BINDINGS_DIR / "HEAD").read_text(
            encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    try:
        load_bindings(store_path, bindings_id)
    except (BindingsError, OSError):
        return None
    return bindings_id


def promote_bindings(store_path: Path, bindings_id: str) -> None:
    """Move `bindings/HEAD` to `bindings_id`: only a set that loads (every binding signed off
    with an approving model-review record, B3) and holds at least one binding."""
    m, _ = load_bindings(store_path, bindings_id)
    if m.bindings == 0:
        raise BindingsError(f"bindings {bindings_id[:12]} hold no binding; nothing to enforce")
    write_atomic(Path(store_path) / BINDINGS_DIR / "HEAD", f"{bindings_id}\n".encode())


# -- the build -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Candidates:
    bindings: list[Binding]
    tables_id: str
    enrichment_id: str
    agreement_pairs: list[tuple[str, int, int]]
    served_models: list[str]
    report: dict


def analysis_module():
    """The Z3 analysis (`adr_store.bindings.analysis`); BindingsError naming the `[analysis]`
    extra when z3 is not installed."""
    try:
        return importlib.import_module("adr_store.bindings.analysis")
    except ImportError as e:
        raise BindingsError(INSTALL_ANALYSIS) from e


def _by_draw(bindings: list[Binding]) -> dict[tuple[str, int], list[Binding]]:
    out: dict[tuple[str, int], list[Binding]] = {}
    for b in bindings:
        out.setdefault(_draw(b), []).append(b)
    return out


def _with(b: Binding, **update) -> Binding:
    return Binding.model_validate({**b.model_dump(), **update})


def _period_specific(d) -> bool:
    """A draw whose parameters a sentence limits beyond what they state (P46, Task 15 flags)."""
    return bool(d.sentence_qualifiers) or any(p.sentence_qualifiers or p.sentence_conditions
                                              for p in d.periods)


def _b2(bindings: list[Binding]) -> dict:
    draws = [bs for bs in _by_draw(bindings).values() if all(b.analysis for b in bs)]
    return {"draws_analysed": len(draws),
            "conflicts": sum(len(bs[0].analysis.get("conflicts", [])) for bs in draws),
            "vacuous": sum(bool(b.analysis.get("vacuous")) for bs in draws for b in bs),
            "redundant": sum(bool(b.analysis.get("redundant")) for bs in draws for b in bs),
            "draws_with_gaps": sum(bool(bs[0].analysis.get("gaps")) for bs in draws)}


def build_candidates(store, client, *, units_id: str, facts_id: str) -> Candidates:
    """The candidate bindings of `store` (module text): compiled from the enrichment `client`
    reads (from the cache under `--max-calls 0`), against the rule cards of `units_id`, tested,
    analysed and compared with the reference evaluator over `facts_id`. Raises BindingsError
    without z3 (before any work), and what the enrichment raises at the cap."""
    from adr_store.bindings import enrich, reference
    from adr_store.bindings.compile import compile_bindings
    from adr_store.tables import extract as ex
    from adr_store.units import overlay as units_overlay

    analysis = analysis_module()
    units = units_overlay.load_units_manifest(store.path, units_id)
    cards = units_overlay.load_units(store.path, units, "rule_card")
    facts = ex.load_facts(store.path, facts_id)
    items, enrich_report = enrich.enrich_all(store, client)
    enrichment_id, _ = enrich.write_enrichment(store.path, store.snapshot_id, items)
    compiled, compile_report = compile_bindings(items, cards)
    tested = checks.mark_tested(compiled)
    passed = sum(not t["failures"] for b in tested for t in b.tests)
    out: list[Binding] = []
    for bs in _by_draw(tested).values():
        if all(b.status == "tested" for b in bs):
            out += analysis.mark_analysed(bs, analysis.analyse_draw(bs))
        else:
            out += bs
    # B1: the agreement set (C5) and the grid on each of its draws
    docs = sorted({i.doc_id for i in items})
    refs = {}
    for doc in docs:
        refs.update(reference.ref_draws(facts, ex.units(store), doc_id=doc))
    by_draw = {k: [b for b in bs if b.status == "analysed"] for k, bs in _by_draw(out).items()}
    agree = reference.agreement_set(by_draw, items, refs)
    params = {(i.section, d.draw): d for i in items for d in i.draws}
    agree = [k for k in agree if not _period_specific(params[k])]
    pairs = reference.paired_refs(items, refs)
    grid_ok, grid_bad = [], []
    stamped: dict[str, Binding] = {}
    for key in agree:
        ref = refs[pairs[key]]
        mismatches = checks.grid_equivalence(by_draw[key], ref)
        summary = {"kind": "grid", "phase3_draw": pairs[key][1],
                   "points": checks.grid_size(ref), "mismatches": len(mismatches),
                   "first": mismatches[:3]}
        (grid_bad if mismatches else grid_ok).append(key)
        for b in by_draw[key]:
            update = {"tests": [*b.tests, summary]}
            if mismatches:
                update["status"] = "rejected"
            stamped[b.binding_id] = _with(b, **update)
    out = [stamped.get(b.binding_id, b) for b in out]
    agreement_pairs = [(s, pairs[(s, d)][1], d) for s, d in grid_ok]
    statuses = {k: sum(b.status == k for b in out) for k in ("analysed", "rejected")}
    report = {
        "units_id": units_id, "facts_id": facts_id, "enrichment_id": enrichment_id,
        "tables_id": enrich_report["tables_id"], "calls": enrich_report["calls"],
        "served_models": enrich_report["served_models"], "compile": compile_report,
        "statuses": statuses,
        "b1": {"bindings": len(tested), "tests_passed": passed,
               "tests_failed": len(tested) - passed,
               "draws": len(_by_draw(tested)),
               "draws_rejected_by_tests": sum(any(b.status == "rejected" for b in bs)
                                              for bs in _by_draw(tested).values()),
               "agreement_draws": len(agree), "grid_equal": len(grid_ok),
               "grid_mismatch": [list(k) for k in grid_bad]},
        "b2": _b2(out)}
    return Candidates(out, enrich_report["tables_id"], enrichment_id, agreement_pairs,
                      enrich_report["served_models"], report)
