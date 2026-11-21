"""The `Unit` model: the envelope every knowledge unit carries, its ids and versions, and the
envelope fields derived from the source document's Phase 2 record (Phase 4 spec §5.1, §5.4,
P31).

- **One unit per (document, source element).** A unit is built from exactly one document and
  takes that document's applicability: `status` is `superseded` when the document's Phase 2
  envelope has `superseded_by`, else `validated`; `effective_from`/`effective_to` are its
  `valid_from`/`valid_to`; `chain` is its `chain_id`.
- **Ids.** `version` is `text_sha12`, the first 12 hex digits of the SHA-256 of the unit's
  whitespace-normalised source text; `unit_id = <type>/<canonical_ref>/<text_sha12>/<doc_id16>`.
  The same text in two versions of a document gives two units.
- **Governance** (`config/units/governance.json`, per corpus): `jurisdiction` is the Phase 2
  value ("US-federal") for gov and the configured company for bench; `owner` is the Phase 2
  issuer (gov) or the source system named on line 3 of a bench document; `authority_tier`
  comes from the configured table (eCFR and IRM 1; bench Confluence and Drive 2, chat, mail
  and tickets 4; research markdown 3, PDFs 4), else from the Phase 2 tier through the
  configured mapping onto the unit scale (Federal Register rules 1, notices 2, proposed
  rules 4). `verifier` is set only
  on bindings; `review_due` and `last_verified_at` are always null.
- **Hashes.** `hashes.text` is the SHA-256 of the normalised text; `hashes.meta` is the
  SHA-256 of the canonical JSON of every envelope field (all but `body` and `hashes`).
- **Versions.** `link_versions` sets `superseded_by` on a unit of a superseded document to the
  unit with the same type and `canonical_ref` in the successor document, and `supersedes` on
  that one (a ref repeated within a document is paired by occurrence, in document order); a
  unit never names itself.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
import threading
from collections import OrderedDict
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from adr_eval.golden.verify import normalize_ws
from adr_store import applicability as ap
from adr_store.applicability import Applicability
from adr_store.records import _HEX64
from adr_store.store import Store
from adr_store.tables.provenance import SPEC_ID, NullReason
from adr_store.units.contracts import UNIT_CONTRACT_DIR, UnitType

COMPILER_VERSION = "units@1"
GOVERNANCE_PATH = UNIT_CONTRACT_DIR / "governance.json"
UnitStatus = Literal["validated", "superseded", "retired"]
BindingStatus = Literal["proposed", "tested", "analysed", "signed_off", "rejected"]
UnitNullReason = NullReason | Literal["not_extracted"]
_SHA12 = re.compile(r"^[0-9a-f]{12}$")
_DOC_ID = re.compile(_HEX64)


# -- the model -------------------------------------------------------------------------------

class SourceRef(BaseModel):
    """A character span of the unit's document's canonical text, and the spec that read it."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="SourceRef")

    doc_id: str = Field(pattern=_HEX64)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    spec_id: str = Field(pattern=SPEC_ID)

    @model_validator(mode="after")
    def _ordered(self) -> SourceRef:
        if self.end < self.start:
            raise ValueError(f"end {self.end} < start {self.start}")
        return self


class Lineage(BaseModel):
    """How the unit was made: the compiler, and for model-written fields the prompt version,
    the served model and the cache key (all null for code-built units)."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="Lineage")

    compiler: str
    prompt_version: str | None
    served_model: str | None
    cache_key_sha256: str | None = Field(pattern=_HEX64)


class UnitApplicability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, title="UnitApplicability")

    status: UnitStatus
    effective_from: date | None
    effective_to: date | None  # exclusive, as the Phase 2 envelope's valid_to
    supersedes: str | None
    superseded_by: str | None
    chain: str | None
    jurisdiction: str | None
    audience: None = None


class Governance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, title="Governance")

    owner: str | None
    verifier: str | None
    authority_tier: int | None = Field(ge=1, le=4)
    review_due: None = None
    last_verified_at: None = None


class Aids(BaseModel):
    """Retrieval aids: indexed, never returned in reader text (§11.1)."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="Aids")

    labels: list[str] = []
    keywords: list[str] = []
    problem_abstractions: list[str] = []
    trigger_examples: list[str] = []


class Unit(BaseModel):
    """One knowledge unit: the envelope (§5.1) and a body that its type's contract types."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="Unit")

    unit_id: str = Field(min_length=1)
    type: UnitType
    title: str
    heading_path: list[str]
    canonical_ref: str = Field(min_length=1)
    version: str
    doc_id: str = Field(pattern=_HEX64)
    contract: str  # "<type>@<contract version>"
    source_refs: list[SourceRef]
    lineage: Lineage
    tables_id: str | None = Field(pattern=_HEX64)
    applicability: UnitApplicability
    governance: Governance
    hashes: dict[str, str]  # {"text", "meta"}
    aids: Aids
    body: dict[str, Any]


# -- ids and hashes --------------------------------------------------------------------------

def text_sha256(text: str) -> str:
    """SHA-256 of the whitespace-normalised text (Phase 0's `normalize_ws`)."""
    return hashlib.sha256(normalize_ws(text).encode("utf-8")).hexdigest()


def text_sha12(text: str) -> str:
    """The unit version: the first 12 hex digits of `text_sha256(text)`."""
    return text_sha256(text)[:12]


def unit_id(type_: str, canonical_ref: str, sha12: str, doc_id: str) -> str:
    """`<type>/<canonical_ref>/<text_sha12>/<doc_id16>` (P31)."""
    if not _SHA12.match(sha12):
        raise ValueError(f"not a text_sha12 (12 hex digits): {sha12!r}")
    if not _DOC_ID.match(doc_id):
        raise ValueError(f"not a document id (64 hex digits): {doc_id!r}")
    return f"{type_}/{canonical_ref}/{sha12}/{doc_id[:16]}"


def meta_sha256(unit: Unit) -> str:
    """SHA-256 of the canonical JSON of the unit's envelope: every field but `body` and
    `hashes`."""
    envelope = unit.model_dump(mode="json", exclude={"body", "hashes"})
    payload = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8") + b"\n").hexdigest()


def _rehashed(unit: Unit) -> Unit:
    return unit.model_copy(update={"hashes": {**unit.hashes, "meta": meta_sha256(unit)}})


# -- governance ------------------------------------------------------------------------------

class CorpusGovernance(BaseModel):
    """How one corpus fills the governance fields. `jurisdiction` null takes the Phase 2
    value; `owner` names where the owner comes from; `authority_tier` maps the `tier_by` key
    of a document (its URI family, bench source system or format) to a tier of the unit scale
    (§5.1). A document whose key is not listed takes `phase2_tier[<its Phase 2 tier>]`: the
    Phase 2 scale (codified 1, final and temporary rules 2, notices and guidance 3, proposed
    rules 4) is another scale, so it is mapped, never copied; no entry gives no tier."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    jurisdiction: str | None
    owner: Literal["issuer", "source_system"] | None
    tier_by: Literal["family", "source_system", "format"]
    authority_tier: dict[str, int]
    phase2_tier: dict[Literal["1", "2", "3", "4"], int]


class GovernanceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)
    description: str
    corpora: dict[str, CorpusGovernance]


@functools.lru_cache(maxsize=4)
def governance_config(path: Path = GOVERNANCE_PATH) -> GovernanceConfig:
    return GovernanceConfig.model_validate_json(Path(path).read_bytes())


_DOC_FACTS: OrderedDict[tuple[str, str | None, str], tuple[int, str | None]] = OrderedDict()
_DOC_FACTS_LOCK = threading.Lock()


def _doc_facts(store: Store, doc_id: str) -> tuple[int, str | None]:
    """(length of the canonical text, the bench source system on line 3 or None). Cached by
    store path, snapshot and doc id: a snapshot's documents never change."""
    key = (str(store.path), store.snapshot_id, doc_id)
    with _DOC_FACTS_LOCK:
        if key in _DOC_FACTS:
            _DOC_FACTS.move_to_end(key)
            return _DOC_FACTS[key]
    text = store.text(doc_id)  # outside the lock: reading is slow, and the value is the same
    lines = text.split("\n", 3)
    system = (lines[2].removeprefix("Source: ").strip() or None
              if len(lines) > 2 and lines[2].startswith("Source: ") else None)
    facts = (len(text), system)
    with _DOC_FACTS_LOCK:
        _DOC_FACTS[key] = facts
        if len(_DOC_FACTS) > 64:
            _DOC_FACTS.popitem(last=False)
    return facts


def doc_envelope(store: Store, overlay: Applicability | None, doc_id: str, corpus: str
                 ) -> tuple[UnitApplicability, Governance]:
    """The applicability and governance of every unit of `doc_id` (§5.1): from the document's
    Phase 2 envelope (none when `overlay` is None or lacks the document) and the corpus's
    governance config."""
    env = overlay.records.get(doc_id) if overlay is not None else None
    cfg = governance_config().corpora.get(corpus)
    source = store.source(doc_id)
    system = _doc_facts(store, doc_id)[1] if cfg is not None and "source_system" in (
        cfg.owner, cfg.tier_by) else None
    jurisdiction = env.jurisdiction if env is not None else None
    owner = tier = None
    if cfg is not None:
        if cfg.jurisdiction is not None:
            jurisdiction = cfg.jurisdiction
        owner = (env.issuer if env is not None else None) if cfg.owner == "issuer" else (
            system if cfg.owner == "source_system" else None)
        key = {"family": ap.family_of(source.uri), "source_system": system,
               "format": source.format}[cfg.tier_by]
        if key is not None and key in cfg.authority_tier:
            tier = cfg.authority_tier[key]
        elif env is not None and env.authority_tier is not None:
            tier = cfg.phase2_tier.get(str(env.authority_tier))
    applicability = UnitApplicability(
        status="superseded" if env is not None and env.superseded_by else "validated",
        effective_from=env.valid_from if env is not None else None,
        effective_to=env.valid_to if env is not None else None,
        supersedes=None, superseded_by=None,
        chain=env.chain_id if env is not None else None, jurisdiction=jurisdiction)
    return applicability, Governance(owner=owner, verifier=None, authority_tier=tier)


# -- versions --------------------------------------------------------------------------------

def _doc_order(u: Unit) -> tuple:
    """Where a unit stands in its document: its first source span, then its unit id."""
    first = min(((r.start, r.end) for r in u.source_refs), default=(0, 0))
    return (*first, u.unit_id)


def link_versions(units: list[Unit], overlay: Applicability | None) -> list[Unit]:
    """`units` in the same order, each unit of a superseded document pointing at the unit of
    the same type and `canonical_ref` in its successor document (`superseded_by`) and that
    unit pointing back (`supersedes`). A `canonical_ref` held by several units of one
    document (a marker repeated in the source) is paired by occurrence: the k-th such unit in
    document order (by first source span) with the k-th in the successor; one with no k-th
    counterpart links nothing. Meta hashes are recomputed; without an overlay nothing
    changes."""
    if overlay is None:
        return list(units)
    by_key: dict[tuple[str, str, str], list[Unit]] = {}
    for u in units:
        by_key.setdefault((u.type, u.canonical_ref, u.doc_id), []).append(u)
    for group in by_key.values():
        group.sort(key=_doc_order)
    successor: dict[str, str] = {}
    for u in units:
        env = overlay.records.get(u.doc_id)
        if env is None or env.superseded_by is None:
            continue
        k = next(i for i, x in enumerate(by_key[(u.type, u.canonical_ref, u.doc_id)])
                 if x.unit_id == u.unit_id)
        found = by_key.get((u.type, u.canonical_ref, env.superseded_by), [])
        if k < len(found) and found[k].unit_id != u.unit_id:
            successor[u.unit_id] = found[k].unit_id
    predecessor: dict[str, str] = {}
    for old, new in sorted(successor.items()):
        predecessor.setdefault(new, old)
    out = []
    for u in units:
        update = {}
        if u.unit_id in successor:
            update["superseded_by"] = successor[u.unit_id]
        if u.unit_id in predecessor:
            update["supersedes"] = predecessor[u.unit_id]
        if update:
            u = _rehashed(u.model_copy(update={
                "applicability": u.applicability.model_copy(update=update)}))
        out.append(u)
    return out


# -- building ----------------------------------------------------------------------------------

def make_unit(*, type_: str, title: str, heading_path: list[str], canonical_ref: str,
              text: str, doc_id: str, spans: Iterable[tuple[int, int, str]], body: dict,
              store: Store, overlay: Applicability | None, corpus: str,
              aids: Aids | None = None, lineage: Lineage | None = None,
              tables_id: str | None = None, contract_version: int = 1) -> Unit:
    """A unit of `doc_id` with its envelope filled: ids and hashes from `text` (the unit's
    source text), source refs from `spans` (`(start, end, spec_id)` in the document's
    canonical text; ValueError when one is outside it), applicability and governance from
    `doc_envelope`. Versions are linked afterwards by `link_versions`; the body is checked
    when the unit is written (`overlay.write_units`)."""
    length = _doc_facts(store, doc_id)[0]
    refs = []
    for start, end, spec_id in spans:
        if not 0 <= start <= end <= length:
            raise ValueError(f"{doc_id[:12]}: span ({start}, {end}) is outside the document "
                             f"(0, {length})")
        refs.append(SourceRef(doc_id=doc_id, start=start, end=end, spec_id=spec_id))
    applicability, governance = doc_envelope(store, overlay, doc_id, corpus)
    full = text_sha256(text)
    unit = Unit(
        unit_id=unit_id(type_, canonical_ref, full[:12], doc_id), type=type_, title=title,
        heading_path=list(heading_path), canonical_ref=canonical_ref, version=full[:12],
        doc_id=doc_id, contract=f"{type_}@{contract_version}", source_refs=refs,
        lineage=lineage or Lineage(compiler=COMPILER_VERSION, prompt_version=None,
                                   served_model=None, cache_key_sha256=None),
        tables_id=tables_id, applicability=applicability, governance=governance,
        hashes={"text": full, "meta": ""}, aids=aids or Aids(), body=body)
    return _rehashed(unit)
