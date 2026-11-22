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

**Known draws (P49).** Both manifests record `known_draws`, `[doc_id, section, draw]` of every
draw the enrichment knows in the bindings' own numbering, failed draws included (with the
Phase 3 table's draw count for a pool section whose reply produced no draw;
`build.known_draws`), sorted; every draw holding bindings must be among them. The gate denies a
target outside them for the version in force (an unknown target) and escalates a known draw
with no binding (P15).

**The candidates** (`write_candidates`, from `bindings.build.build_candidates`) record the
units, tables, facts and enrichment ids, the agreement pairs `[section, Phase 3 draw, bindings'
draw]` of the draws still `analysed`, and every draw with its number of bindings (`draws`:
`[doc_id, section, draw, bindings]`). `load_candidates` refuses a draw that mixes statuses
(P48: a draw's bindings are analysed, or rejected, together).

**The bindings manifest** (`write_bindings`) holds the signed-off set only (§12.5, B3): the
same ids, plus `agreement_set` (Phase 3 `[section, draw]` keys) and `agreement_pairs`, kept
only for draws whose bindings are in the set, and `draws`, each draw of the set with its
number of bindings. Only **complete** draws are written (P48, defence in depth): a draw with
a binding of the input that is not signed off is refused, and with the candidates' `draws`
given each written draw must hold every binding the candidates list for it; every draw holds
its § 117.31(b) emergency basis. `load_bindings` re-validates every binding
(`Binding.model_validate`: ids, version and required facts are those of its content) and
verifies every hash, the order, canonical bytes, and that each binding is `signed_off` with
its tests, its analysis and an approving `model-review:claude_code_opus` record whose served
model, when the provider reported one, is the review profile's; that every override names a
forbid of its draw in the set; that each draw holds its emergency basis and as many bindings
as `draws` records; and that each agreement draw is in the set. Draws are keyed by document
and target (`checks._draw_key`). `promote_bindings` moves
`bindings/HEAD` only to a set that loads and is not empty (builder note 17: no flip gate);
`read_bindings_head` returns the id only when it still loads.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from adr_store.bindings.checks import _draw_key, _under
from adr_store.bindings.compile import EMERGENCY
from adr_store.bindings.dsl import LANGUAGE, Binding
from adr_store.bindings.enrich import section_key
from adr_store.bindings.review import VERIFIER, served_problem
from adr_store.records import _HEX64, canonical_json
from adr_store.store import StoreError, write_atomic
from adr_store.tables.overlay import TablesError, _write_once

__all__ = ["BINDINGS_DIR", "INSTALL_ANALYSIS", "BindingsError", "BindingsManifest",
           "CandidatesManifest", "by_draw", "draw_keys", "draw_sizes", "load_bindings",
           "load_candidates", "promote_bindings", "read_bindings_head", "write_bindings",
           "write_candidates"]

BINDINGS_DIR = "bindings"
FORMAT_VERSION = "0.1"
INSTALL_ANALYSIS = "install the analysis extra: pip install -e '.[analysis]'"


class BindingsError(StoreError):
    """A bindings file or manifest is missing, altered, unsigned or would be overwritten."""


def _pair_list(v: list) -> list:
    return sorted(v, key=lambda p: (section_key(p[0]), *p[1:]))


def _draw_order(d) -> tuple:
    return (d[0], section_key(d[1]), d[2])


def by_draw(bindings: list[Binding]) -> dict[str, list[Binding]]:
    """The bindings grouped by draw (`checks._draw_key`: document and target), in order."""
    out: dict[str, list[Binding]] = {}
    for b in bindings:
        out.setdefault(_draw_key(b), []).append(b)
    return out


def draw_keys(bindings: list[Binding]) -> list[tuple[str, str, int]]:
    """(doc_id, section, draw) of every draw of `bindings`, sorted (a known-draws census of
    the draws that hold bindings, for callers that know of no other draw)."""
    return [d[:3] for d in draw_sizes(bindings)]


def _known(known_draws) -> list[tuple[str, str, int]]:
    return sorted({(d, s, n) for d, s, n in known_draws}, key=_draw_order)


def _check_known(bindings: list[Binding], known_draws) -> None:
    missing = set(draw_keys(bindings)) - set(_known(known_draws))
    if missing:
        d = sorted(missing, key=_draw_order)[0]
        raise BindingsError(f"§ {d[1]} draw {d[2]} holds bindings but is no known draw (P49)")


def draw_sizes(bindings: list[Binding]) -> list[tuple[str, str, int, int]]:
    """(doc_id, section, draw, number of bindings) of every draw of `bindings`, sorted."""
    out = []
    for bs in by_draw(bindings).values():
        sel = bs[0].target.get("selector", {})
        out.append((bs[0].doc_id, sel.get("section"), sel.get("draw"), len(bs)))
    return sorted(out, key=_draw_order)


class _Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal["0.1"]
    snapshot: str = Field(min_length=1)
    units_id: str = Field(pattern=_HEX64)
    tables_id: str = Field(pattern=_HEX64)
    facts_id: str | None = Field(pattern=_HEX64)        # the Phase 3 second-pass facts (C5)
    enrichment_id: str | None = Field(pattern=_HEX64)   # the enrichment compiled (C5)
    agreement_pairs: list[tuple[str, int, int]]          # [section, Phase 3 draw, bindings' draw]
    draws: list[tuple[str, str, int, int]]               # [doc_id, section, draw, bindings]
    known_draws: list[tuple[str, str, int]]              # [doc_id, section, draw] (P49)
    file: str
    sha256: str = Field(pattern=_HEX64)
    bindings: int = Field(ge=0)
    language: Literal["adr-dsl@1"]

    @model_validator(mode="after")
    def _checked(self):
        if list(self.agreement_pairs) != _pair_list(list(set(self.agreement_pairs))):
            raise ValueError("agreement_pairs must be sorted and distinct")
        keys = [d[:3] for d in self.draws]
        if list(self.draws) != sorted(self.draws, key=_draw_order) or len(set(keys)) != len(keys):
            raise ValueError("draws must be sorted and distinct")
        if sum(d[3] for d in self.draws) != self.bindings:
            raise ValueError("draws must count every binding")
        if any(d[3] < 1 for d in self.draws):   # a recorded draw holds at least its emergency basis
            raise ValueError("every recorded draw holds at least one binding")
        known = [tuple(k) for k in self.known_draws]
        if known != sorted(set(known), key=_draw_order):
            raise ValueError("known_draws must be sorted and distinct")
        if not {tuple(k) for k in keys} <= set(known):
            raise ValueError("every draw holding bindings must be a known draw (P49)")
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


def _selector(b: Binding) -> tuple[str, int]:
    sel = b.target.get("selector", {})
    return sel.get("section"), sel.get("draw")


# -- candidates ----------------------------------------------------------------------------------

def write_candidates(store_path: Path, snapshot: str, units_id: str, tables_id: str,
                     bindings: list[Binding], *, facts_id: str | None,
                     enrichment_id: str | None, agreement_pairs, report: dict,
                     known_draws) -> tuple[str, Path]:
    """Write a build's bindings (every status) once, their manifest and `report` (unhashed);
    (candidates id, manifest path). Refuses a draw that mixes statuses (P48)."""
    if problems := _uniform_problems(bindings):
        raise BindingsError("; ".join(problems))
    _check_known(bindings, known_draws)
    data = _data(bindings)
    sha = _sha256(data)
    m = CandidatesManifest(format_version=FORMAT_VERSION, snapshot=snapshot, units_id=units_id,
                           tables_id=tables_id, facts_id=facts_id, enrichment_id=enrichment_id,
                           agreement_pairs=_pair_list([tuple(p) for p in agreement_pairs]),
                           draws=draw_sizes(bindings), known_draws=_known(known_draws),
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


def _uniform_problems(bindings: list[Binding]) -> list[str]:
    """The draws whose bindings do not share one status (P48 forbids it)."""
    out = []
    for bs in by_draw(bindings).values():
        statuses = sorted({b.status for b in bs})
        if len(statuses) > 1:
            sel = _selector(bs[0])
            out.append(f"§ {sel[0]} draw {sel[1]} mixes statuses {', '.join(statuses)} (P48: "
                       f"a draw passes or fails as a whole)")
    return out


def load_candidates(store_path: Path, candidates_id: str
                    ) -> tuple[CandidatesManifest, list[Binding]]:
    """The candidates `candidates_id`, every hash verified, every binding re-validated, every
    draw counted as the manifest records it and of one status (P48)."""
    path = _find(store_path, "bindings-candidates", candidates_id, "candidates")
    m, out = _read(store_path, path, CandidatesManifest, "candidates")
    problems = _uniform_problems(out)
    if [tuple(d) for d in m.draws] != draw_sizes(out):
        problems.append("the draws do not hold the bindings the manifest counts")
    if problems:
        raise BindingsError(f"candidates {candidates_id[:12]}: {'; '.join(problems)}")
    return m, out


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
    elif problem := served_problem(b.review.get("served_model")):
        out.append(f"was reviewed by another model ({problem})")
    if not b.tests or any(t.get("failures") or t.get("mismatches") for t in b.tests):
        out.append("has no passing tests")
    if not b.analysis or b.analysis.get("conflicts") or b.analysis.get("vacuous"):
        out.append("has no clean analysis")
    return out


def _set_problems(bindings: list[Binding], pairs, sizes) -> list[str]:
    """Problems of a signed-off set: overrides that name no forbid of their draw, draws
    without their emergency basis or with other than `sizes` bindings (P48), agreement pairs
    that name no draw of the set or a draw twice."""
    forbids = {b.binding_id: _draw_key(b) for b in bindings if b.effect == "forbid"}
    out = []
    for b in bindings:
        for x in b.overrides:
            if forbids.get(x) != _draw_key(b):
                out.append(f"binding {b.binding_id[:12]} overrides {x[:12]}, which is no "
                           f"forbid of its draw in the set")
    counts = {d[:3]: d[3] for d in sizes}
    for bs in by_draw(bindings).values():
        sel = _selector(bs[0])
        key = (bs[0].doc_id, *sel)
        if not any(b.effect == "basis" and _under(b.rule_id, EMERGENCY) for b in bs):
            out.append(f"§ {sel[0]} draw {sel[1]} has no § 117.31(b) emergency basis (an "
                       f"incomplete draw, P48)")
        if counts.get(key) != len(bs):
            out.append(f"§ {sel[0]} draw {sel[1]} holds {len(bs)} binding(s), not the "
                       f"{counts.get(key, 0)} its record lists (an incomplete draw, P48)")
    present = {_selector(b) for b in bindings}
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
                   enrichment_id: str | None = None, agreement_pairs=(),
                   candidate_draws=None, known_draws) -> tuple[str, Path]:
    """Write the signed-off bindings of `bindings` (the others are left out) once, with their
    manifest; (bindings id, manifest path). Only whole draws are written: a draw with any
    binding of `bindings` not signed off is refused, and with `candidate_draws` (the
    candidates' `draws`) each draw must hold every binding they list for it.
    `agreement_pairs` ([section, Phase 3 draw, bindings' draw]) are kept for the draws whose
    bindings are in the set. Refuses (BindingsError) a set an override, a draw or an agreement
    pair cannot be read in. `known_draws` ([doc_id, section, draw]) is the census of every draw
    the enrichment knows (P49); each written draw must be in it."""
    kept = [b for b in bindings if b.status == "signed_off"]
    for b in kept:
        if problems := _signed_problems(b):
            raise BindingsError(f"binding {b.binding_id[:12]} {'; '.join(problems)}")
    partial = [bs for bs in by_draw(bindings).values()
               if any(b.status == "signed_off" for b in bs)
               and not all(b.status == "signed_off" for b in bs)]
    if partial:
        raise BindingsError("; ".join(
            f"§ {_selector(bs[0])[0]} draw {_selector(bs[0])[1]} is signed off in part (an "
            f"incomplete draw, P48)" for bs in partial))
    sizes = draw_sizes(kept)
    _check_known(kept, known_draws)
    if candidate_draws is not None:
        listed = {tuple(d[:3]): d[3] for d in candidate_draws}
        sizes = [(*d[:3], listed.get(d[:3], 0)) for d in sizes]
    present = {_selector(b) for b in kept}
    pairs = _pair_list(list({tuple(p) for p in agreement_pairs if (p[0], p[2]) in present}))
    if problems := _set_problems(kept, pairs, sizes):
        raise BindingsError("; ".join(problems))
    data = _data(kept)
    sha = _sha256(data)
    m = BindingsManifest(format_version=FORMAT_VERSION, snapshot=snapshot, units_id=units_id,
                         tables_id=tables_id, facts_id=facts_id, enrichment_id=enrichment_id,
                         agreement_set=[(s, p) for s, p, _ in pairs], agreement_pairs=pairs,
                         draws=sizes, known_draws=_known(known_draws),
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
    re-validated and signed off with an approving model-review record, every draw complete;
    BindingsError otherwise."""
    path = _find(store_path, "bindings", bindings_id, "bindings")
    m, out = _read(store_path, path, BindingsManifest, "bindings")
    for b in out:
        if problems := _signed_problems(b):
            raise BindingsError(f"bindings {bindings_id[:12]}: binding {b.binding_id[:12]} "
                                f"{'; '.join(problems)}")
    problems = _set_problems(out, m.agreement_pairs, [tuple(d) for d in m.draws])
    if {tuple(d[:3]) for d in m.draws} != {d[:3] for d in draw_sizes(out)}:
        problems.append("the draws recorded are not the draws of the set")
    if problems:
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
