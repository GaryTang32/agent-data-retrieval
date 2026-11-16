"""The applicability overlay: one envelope record per document of a snapshot, derived from the
corpus alone, and the filters that use it (Phase 2 spec §4.2–§4.4).

    <store>/applicability/<snapshot_id>/envelope-1.json          the overlay (canonical JSON)
    <store>/applicability/<snapshot_id>/envelope-1.report.json   the derive report (not hashed)

The overlay id is the SHA-256 of the overlay file. The file is written once: deriving again
writes the same bytes, and a file with other content under the same name is refused.

Families are recognised by URI only (`chain_of`, `family_of`):

- eCFR point-in-time XML (`https://www.ecfr.gov/api/versioner/v1/full/<date>/title-<t>.xml?
  part=<p>`): chain `ecfr:<t>:<p>`; `valid_from` the `source_version` date (basis
  `ecfr_snapshot`), `valid_to` the next version's date; `codified`, tier 1; issuer from the gov
  config's `parts[i].agency`.
- Internal Revenue Manual (`https://www.irs.gov/irm/part<N>/irm_<a>-<b>-<c>r`): chain
  `irm:<a>.<b>.<c>`; `valid_from` the `source_version` (the Manual Transmittal date, basis
  `irm_transmittal`); `guidance`, tier 3; issuer the Internal Revenue Service.
- Federal Register API documents (`https://www.federalregister.gov/api/v1/documents/…`): no
  chain; the fields are read from the document's JSON. Status by the first rule that holds:
  `type` "Proposed Rule" -> `proposed_rule` (tier 4); `action` names a notice or notification
  of enforcement -> `notice` (tier 3); `action` contains "temporary" -> `temporary_rule`
  (tier 2); else `final_rule` (tier 2). `valid_from` is `effective_on`, else
  `publication_date`. A temporary rule whose `dates` text says, in its first sentence,
  "effective … from … through|until … <Month D, YYYY>" (`temporary_end`) is in force through
  that date and ends the day after it (`valid_to` is exclusive); the matched range of the
  canonical text is recorded in the provenance of `valid_to`. End dates have day granularity:
  a time before the date is read past ("through 7 p.m. on D"), and a rule ending 12:01 a.m. on
  D is admitted for all of D. A temporary rule whose end date does not parse, and a
  "Notification of expired temporary rules issued" (status `temporary_rule`, no end date in its
  text), is open-ended (`valid_to` null), so any `as_of` on or after its `valid_from` admits
  it; the derive report lists these.
- Anything else (research, bench, mini, loose files): every field `unknown` or null.

Chains of more than one version are ordered by `valid_from` (ties by doc id); each version's
`valid_to` is the next one's `valid_from` and `supersedes`/`superseded_by` name the neighbours.

Each derived field has one provenance entry naming where it came from: `uri` (the family
rules), `manifest.source_version`, `chain` (neighbours and the next version's date),
`config.parts[i].agency`, `fr.type`, `fr.action`, `fr.effective_on`, `fr.publication_date`,
`fr.agencies[k].name`, `fr.dates` (with the matched character range) or `status` (the tier).

The overlay's `config_sha256` covers only the gov config fields the deriver reads: the
`title`, `part` and `agency` of each `parts` entry, in order (`config_read`). It is null when
the snapshot holds no eCFR document (research, bench), as the config is then not read at all;
other config fields (`version`, `dates`, …) never change an overlay.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from adr_eval.corpora.gov import FR_API, specific_agency
from adr_store.records import SourceRecord, canonical_json
from adr_store.store import Store, StoreError, write_atomic

DERIVER, DERIVER_VERSION = "envelope", 1
DERIVER_NAME = f"{DERIVER}-{DERIVER_VERSION}"
OVERLAY_DIR = "applicability"

Status = Literal["codified", "final_rule", "temporary_rule", "proposed_rule", "notice",
                 "guidance", "unknown"]
Basis = Literal["ecfr_snapshot", "fr_effective_on", "fr_publication_date", "fr_dates_text",
                "irm_transmittal", "unknown"]
STATUSES: tuple[str, ...] = get_args(Status)
BASES: tuple[str, ...] = get_args(Basis)
FAMILIES = ("ecfr", "fr", "irm", "unknown")

_HEX64 = r"^[0-9a-f]{64}$"
_ECFR_URI = re.compile(r"^https://www\.ecfr\.gov/api/versioner/v1/full/(\d{4}-\d{2}-\d{2})/"
                       r"title-(\d+)\.xml\?part=([\w.-]+)$")
_IRM_URI = re.compile(r"^https://www\.irs\.gov/irm/part\d+/irm_(\d+)-(\d+)-(\d+)r$")
_FR_PREFIX = f"{FR_API}/documents/"
_ENFORCEMENT = re.compile(r"(?i)\b(notice|notification) of enforcement\b")
# a sentence end: ". " or a final ".", but not the dots of "a.m."/"p.m.", or ";"
_SENTENCE_END = r"(?:(?<![ap]\.m)(?<!\b[ap])\.(?:\s|$)|;)"
_FIRST_SENTENCE_END = re.compile(_SENTENCE_END, re.IGNORECASE)
# group 2 runs to the sentence end, past any time, to the end date
_END_DATE = re.compile(r"(?is)\beffective\b.*?\bfrom\b(.+?)\b(?:through|until)\b(.+?)"
                       + _SENTENCE_END)
_MONTH_DATE = re.compile(r"\b(January|February|March|April|May|June|July|August|September|"
                         r"October|November|December) (\d{1,2}), (\d{4})\b")

JURISDICTION = "US-federal"
IRM_ISSUER = "Internal Revenue Service"
# gov config agency slug -> issuer name (a fixed table: an unknown slug is refused)
AGENCY_NAMES = {"coast-guard": "Coast Guard",
                "federal-communications-commission": "Federal Communications Commission"}
TIERS = {"codified": 1, "final_rule": 2, "temporary_rule": 2, "notice": 3, "guidance": 3,
         "proposed_rule": 4, "unknown": None}

CAVEATS = (
    "The eCFR interval is the gap between pinned snapshots, not the true amendment interval: a "
    "snapshot is evidence of the text on its own date, and a date between snapshots is served "
    "the latest snapshot on or before it (basis ecfr_snapshot).",
    "The IRM pages are current pages: a date before a chapter's Manual Transmittal finds no "
    "IRM version of it.",
)


# -- records -------------------------------------------------------------------------------

class Provenance(BaseModel):
    """Where one derived field came from; `char_start`/`char_end` is a range of the
    document's canonical text (for `fr.dates`)."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="Provenance")

    field: str
    source: str
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)


class Envelope(BaseModel):
    """The applicability of one document (spec §4.2). `valid_to` is exclusive."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="Envelope")

    doc_id: str = Field(pattern=_HEX64)
    chain_id: str | None
    version_label: str
    supersedes: str | None = Field(pattern=_HEX64)
    superseded_by: str | None = Field(pattern=_HEX64)
    valid_from: date | None
    valid_to: date | None
    validity_basis: Basis
    status: Status
    jurisdiction: str | None
    issuer: str | None
    authority_tier: int | None = Field(ge=1, le=4)
    provenance: list[Provenance]


class ApplicabilityOverlay(BaseModel):
    """The content of `<store>/applicability/<snapshot>/envelope-1.json`: every document of the
    snapshot, by doc id. `config_sha256` is the SHA-256 of the gov config fields the deriver
    read (`config_read`), null when it read none (no eCFR document)."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="ApplicabilityOverlay")

    format_version: Literal["0.1"]
    snapshot: str = Field(pattern=_HEX64)
    deriver: str
    config_sha256: str | None = Field(pattern=_HEX64)
    records: dict[str, Envelope]

    @model_validator(mode="after")
    def _keys_are_doc_ids(self) -> ApplicabilityOverlay:
        for key, envelope in self.records.items():
            if key != envelope.doc_id:
                raise ValueError(f"record {key} holds the envelope of {envelope.doc_id}")
        return self


# -- families --------------------------------------------------------------------------------

def family_of(uri: str) -> str:
    """`ecfr`, `irm`, `fr` or `unknown`, by URI."""
    if _ECFR_URI.match(uri):
        return "ecfr"
    if _IRM_URI.match(uri):
        return "irm"
    if uri.startswith(_FR_PREFIX):
        return "fr"
    return "unknown"


def chain_of(source: SourceRecord) -> str | None:
    """The chain a document belongs to, by its URI alone: `ecfr:<title>:<part>`,
    `irm:<a>.<b>.<c>`, or None (Federal Register documents and everything else)."""
    if m := _ECFR_URI.match(source.uri):
        return f"ecfr:{int(m.group(2))}:{m.group(3)}"
    if m := _IRM_URI.match(source.uri):
        return "irm:" + ".".join(str(int(g)) for g in m.groups())
    return None


def config_read(gov_config: dict) -> dict:
    """The gov config fields the deriver reads (for eCFR issuers): the `title`, `part` and
    `agency` of each `parts` entry, in order."""
    return {"parts": [{k: p.get(k) for k in ("title", "part", "agency")}
                      for p in gov_config.get("parts") or []]}


def config_sha256(gov_config: dict) -> str:
    """The SHA-256 of `config_read(gov_config)` as canonical JSON (sorted keys, compact,
    UTF-8)."""
    payload = json.dumps(config_read(gov_config), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iso(value: str, doc_id: str, what: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{doc_id}: {what} {value!r} is not an ISO date") from e


def _unknown(source: SourceRecord) -> dict:
    return dict(doc_id=source.doc_id, chain_id=None, version_label=source.source_version,
                supersedes=None, superseded_by=None, valid_from=None, valid_to=None,
                validity_basis="unknown", status="unknown", jurisdiction=None, issuer=None,
                authority_tier=None)


def _ecfr_issuer(source: SourceRecord, gov_config: dict) -> tuple[str, str] | None:
    """(issuer, provenance source) from the config part of this eCFR document, if listed."""
    m = _ECFR_URI.match(source.uri)
    title, part = int(m.group(2)), m.group(3)
    for i, p in enumerate(gov_config.get("parts") or []):
        if int(p["title"]) == title and str(p["part"]) == part:
            slug = p["agency"]
            if slug not in AGENCY_NAMES:
                raise ValueError(f"gov config parts[{i}]: agency {slug!r} has no issuer name "
                                 f"(known: {', '.join(sorted(AGENCY_NAMES))})")
            return AGENCY_NAMES[slug], f"config.parts[{i}].agency"
    return None


def _ecfr(source: SourceRecord, gov_config: dict) -> tuple[dict, list[Provenance]]:
    fields = _unknown(source) | dict(
        chain_id=chain_of(source), validity_basis="ecfr_snapshot", status="codified",
        valid_from=_iso(source.source_version, source.doc_id, "source_version"),
        jurisdiction=JURISDICTION, authority_tier=TIERS["codified"])
    prov = [Provenance(field="chain_id", source="uri"),
            Provenance(field="valid_from", source="manifest.source_version"),
            Provenance(field="status", source="uri"),
            Provenance(field="jurisdiction", source="uri"),
            Provenance(field="authority_tier", source="status")]
    if issuer := _ecfr_issuer(source, gov_config):
        fields["issuer"] = issuer[0]
        prov.append(Provenance(field="issuer", source=issuer[1]))
    return fields, prov


def _irm(source: SourceRecord) -> tuple[dict, list[Provenance]]:
    fields = _unknown(source) | dict(
        chain_id=chain_of(source), validity_basis="irm_transmittal", status="guidance",
        valid_from=_iso(source.source_version, source.doc_id, "source_version"),
        jurisdiction=JURISDICTION, issuer=IRM_ISSUER, authority_tier=TIERS["guidance"])
    prov = [Provenance(field="chain_id", source="uri"),
            Provenance(field="valid_from", source="manifest.source_version"),
            Provenance(field="status", source="uri"),
            Provenance(field="jurisdiction", source="uri"),
            Provenance(field="issuer", source="uri"),
            Provenance(field="authority_tier", source="status")]
    return fields, prov


def fr_status(fr: dict) -> tuple[str, str]:
    """(status, the JSON field it was read from) of a Federal Register document."""
    action = fr.get("action") or ""
    if fr.get("type") == "Proposed Rule":
        return "proposed_rule", "fr.type"
    if _ENFORCEMENT.search(action):
        return "notice", "fr.action"
    if "temporary" in action.lower():
        return "temporary_rule", "fr.action"
    return "final_rule", "fr.action"


def _dates_range(text: str, dates: str, start: int, end: int) -> tuple[int, int]:
    """The range of the canonical text (indented JSON) holding `dates[start:end]`: the string
    value is found by its exact encoding, and offsets inside it are counted in escaped
    characters."""
    encoded = json.dumps(dates, ensure_ascii=False)
    at = text.find(f'\n  "dates": {encoded}')
    if at < 0 or text.find(f'\n  "dates": {encoded}', at + 1) >= 0:
        raise ValueError("the dates value is not found once in the canonical text")
    base = at + len('\n  "dates": ') + 1

    def offset(i: int) -> int:
        return base + len(json.dumps(dates[:i], ensure_ascii=False)) - 2

    return offset(start), offset(end)


def temporary_end(dates: str) -> tuple[date, int, int] | None:
    """The last day in force of a temporary rule's `dates` text, with the matched range of
    `dates`: "effective … from … through|until … <Month D, YYYY>" within the first sentence
    (so a later "actual notice … from X until Y" sentence is never read), or None."""
    first = _FIRST_SENTENCE_END.search(dates)
    m = _END_DATE.search(dates, 0, len(dates) if first is None else first.end())
    if m is None:
        return None
    d = _MONTH_DATE.search(m.group(2))
    if d is None:
        return None
    try:
        last = datetime.strptime(f"{d.group(1)} {d.group(2)}, {d.group(3)}", "%B %d, %Y").date()
    except ValueError:
        return None
    return last, m.start(), m.end()


def _fr(source: SourceRecord, text: str) -> tuple[dict, list[Provenance], str | None]:
    """The envelope fields of a Federal Register document, its provenance, and its `dates`
    text when it is a temporary rule whose end date does not parse (else None)."""
    fr = json.loads(text)
    status, status_from = fr_status(fr)
    if fr.get("effective_on"):
        valid_from, basis = _iso(fr["effective_on"], source.doc_id, "effective_on"), \
            "fr_effective_on"
        from_source = "fr.effective_on"
    else:
        valid_from, basis = _iso(fr.get("publication_date"), source.doc_id,
                                 "publication_date"), "fr_publication_date"
        from_source = "fr.publication_date"
    fields = _unknown(source) | dict(
        valid_from=valid_from, validity_basis=basis, status=status, jurisdiction=JURISDICTION,
        authority_tier=TIERS[status])
    prov = [Provenance(field="valid_from", source=from_source),
            Provenance(field="status", source=status_from),
            Provenance(field="jurisdiction", source="uri"),
            Provenance(field="authority_tier", source="status")]
    agencies = fr.get("agencies") or []
    k = specific_agency(agencies)
    if k is not None and agencies[k].get("name"):
        fields["issuer"] = agencies[k]["name"]
        prov.append(Provenance(field="issuer", source=f"fr.agencies[{k}].name"))
    failed = None
    if status == "temporary_rule":
        dates = fr.get("dates") or ""
        found = temporary_end(dates)
        if found is None:
            failed = dates
        else:
            last, start, end = found
            fields["valid_to"] = last + timedelta(days=1)
            cs, ce = _dates_range(text, dates, start, end)
            prov.append(Provenance(field="valid_to", source="fr.dates", char_start=cs,
                                   char_end=ce))
    return fields, prov, failed


def _link_chains(fields: dict[str, dict], prov: dict[str, list[Provenance]]) -> dict:
    """Order each chain's versions by `valid_from` (ties by doc id) and link neighbours;
    returns doc ids by chain, in version order."""
    chains: dict[str, list[str]] = {}
    for doc_id in sorted(fields):
        if (chain := fields[doc_id]["chain_id"]) is not None:
            chains.setdefault(chain, []).append(doc_id)
    for chain in chains:
        versions = sorted(chains[chain], key=lambda d: (fields[d]["valid_from"], d))
        chains[chain] = versions
        for older, newer in zip(versions, versions[1:], strict=False):
            fields[older]["superseded_by"] = newer
            fields[newer]["supersedes"] = older
            fields[older]["valid_to"] = fields[newer]["valid_from"]
            prov[older] += [Provenance(field="superseded_by", source="chain"),
                            Provenance(field="valid_to", source="chain")]
            prov[newer].append(Provenance(field="supersedes", source="chain"))
    return chains


def derive(store: Store, gov_config: dict) -> tuple[ApplicabilityOverlay, dict]:
    """The applicability overlay of the store's snapshot, and the derive report."""
    fields: dict[str, dict] = {}
    prov: dict[str, list[Provenance]] = {}
    families: Counter[str] = Counter({f: 0 for f in FAMILIES})
    failures = []
    for doc_id in store.doc_ids():
        source = store.source(doc_id)
        family = family_of(source.uri)
        families[family] += 1
        if family == "ecfr":
            fields[doc_id], prov[doc_id] = _ecfr(source, gov_config)
        elif family == "irm":
            fields[doc_id], prov[doc_id] = _irm(source)
        elif family == "fr":
            text = store.text(doc_id)
            fields[doc_id], prov[doc_id], failed = _fr(source, text)
            if failed is not None:
                failures.append({"doc_id": doc_id, "document_number": json.loads(text).get(
                    "document_number"), "dates": failed})
        else:
            fields[doc_id], prov[doc_id] = _unknown(source), []
        if family != "unknown":
            prov[doc_id].append(Provenance(field="version_label",
                                           source="manifest.source_version"))
    chains = _link_chains(fields, prov)
    envelopes = {}
    for doc_id in sorted(fields):
        ordered = sorted(prov[doc_id], key=lambda p: (p.field, p.source))
        envelopes[doc_id] = Envelope(**fields[doc_id], provenance=ordered)
    overlay = ApplicabilityOverlay(
        format_version="0.1", snapshot=store.snapshot_id, deriver=DERIVER_NAME,
        config_sha256=config_sha256(gov_config) if families["ecfr"] else None,
        records=envelopes)
    return overlay, _report(overlay, families, chains, failures)


def _report(overlay: ApplicabilityOverlay, families: Counter, chains: dict, failures: list
            ) -> dict:
    envs = list(overlay.records.values())
    tiers = Counter("null" if e.authority_tier is None else str(e.authority_tier) for e in envs)
    temporary = [e for e in envs if e.status == "temporary_rule"]
    return {
        "snapshot": overlay.snapshot,
        "deriver": overlay.deriver,
        "config_sha256": overlay.config_sha256,
        "documents": len(envs),
        "families": dict(sorted(families.items())),
        "status": dict(sorted(Counter(e.status for e in envs).items())),
        "validity_basis": {b: sum(1 for e in envs if e.validity_basis == b) for b in BASES},
        "authority_tier": dict(sorted(tiers.items())),
        "chains": {"count": len(chains),
                   "multi_version": sum(1 for v in chains.values() if len(v) > 1),
                   "documents": sum(len(v) for v in chains.values()),
                   "links": sum(len(v) - 1 for v in chains.values()),
                   "by_chain": {c: len(v) for c, v in sorted(chains.items())}},
        "superseded_documents": sum(1 for e in envs if e.superseded_by is not None),
        "temporary_end_dates": {"parsed": sum(1 for e in temporary if e.valid_to is not None),
                                "of": len(temporary)},
        "fr_dates_parse_failures": sorted(failures, key=lambda f: f["doc_id"]),
        "caveats": list(CAVEATS),
    }


# -- files -----------------------------------------------------------------------------------

def overlay_path(store_path: Path, snapshot: str) -> Path:
    return Path(store_path) / OVERLAY_DIR / snapshot / f"{DERIVER_NAME}.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_overlay(store_path: Path, overlay: ApplicabilityOverlay) -> tuple[str, Path]:
    """Write the overlay once; returns (overlay id, path). The same bytes again are a no-op,
    other bytes under the same name are refused."""
    path = overlay_path(store_path, overlay.snapshot)
    data = canonical_json(overlay)
    if path.exists():
        if path.read_bytes() != data:
            raise StoreError(f"{path} already holds a different overlay for this snapshot "
                             f"(another deriver input or version); it is not replaced")
    else:
        write_atomic(path, data)
    return _sha256(data), path


def write_report(store_path: Path, report: dict) -> Path:
    """Write the derive report beside the overlay (not part of the overlay id)."""
    path = overlay_path(store_path, report["snapshot"]).with_name(
        f"{DERIVER_NAME}.report.json")
    write_atomic(path, (json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
                        + "\n").encode("utf-8"))
    return path


def load_overlay(store_path: Path, snapshot: str, overlay_id: str | None = None
                 ) -> Applicability | None:
    """The overlay of a snapshot, or None if there is none. Refuses (StoreError) a file whose
    hash is not `overlay_id` (when given), that is not a valid canonical overlay, or that
    describes another snapshot or other documents than the snapshot's."""
    path = overlay_path(store_path, snapshot)
    if not path.is_file():
        return None
    data = path.read_bytes()
    oid = _sha256(data)
    if overlay_id is not None and oid != overlay_id:
        raise StoreError(f"{path}: content hash {oid[:12]} is not the overlay id "
                         f"{overlay_id[:12]}")
    try:
        overlay = ApplicabilityOverlay.model_validate_json(data)
    except ValidationError as e:
        raise StoreError(f"{path}: not a valid overlay (schema): "
                         f"{e.errors()[0]['msg']}") from e
    if canonical_json(overlay) != data:
        raise StoreError(f"{path}: not canonical JSON (sorted keys, compact, one newline)")
    if overlay.snapshot != snapshot:
        raise StoreError(f"{path}: describes snapshot {overlay.snapshot[:12]}, not "
                         f"{snapshot[:12]}")
    if overlay.deriver != DERIVER_NAME:
        raise StoreError(f"{path}: deriver {overlay.deriver!r}, expected {DERIVER_NAME!r}")
    if sorted(overlay.records) != Store.open(store_path, snapshot).doc_ids():
        raise StoreError(f"{path}: its records are not the documents of snapshot "
                         f"{snapshot[:12]}")
    return Applicability(oid, overlay.snapshot, dict(overlay.records))


# -- filters ---------------------------------------------------------------------------------

_FILTER_KEYS = ("include_superseded", "as_of", "status", "jurisdiction", "max_tier")
_FILTER_STATUSES = frozenset(STATUSES) - {"unknown"}


def _names(value, what: str, allowed: frozenset[str] | None = None) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError(f"{what} must be a list of strings, got {value!r}")
    if not value:
        raise ValueError(f"{what} must name at least one value")
    for v in value:
        if not isinstance(v, str) or not v:
            raise ValueError(f"{what} values must be non-empty strings, got {v!r}")
        if allowed is not None and v not in allowed:
            raise ValueError(f"{what} {v!r} is not one of {', '.join(sorted(allowed))}")
    return tuple(sorted(set(value)))


@dataclass(frozen=True)
class Filters:
    """The applicability filters of `search`, `grep` and `read` (spec §4.4). Lists are kept
    sorted and without repeats; `parse` takes a dict (strings for dates) as tools receive it."""

    include_superseded: bool = False
    as_of: date | None = None
    status: tuple[str, ...] | None = None
    jurisdiction: tuple[str, ...] | None = None
    max_tier: int | None = None

    def __post_init__(self):
        if not isinstance(self.include_superseded, bool):
            raise ValueError(f"include_superseded must be true or false, got "
                             f"{self.include_superseded!r}")
        as_of = self.as_of
        if isinstance(as_of, str):
            try:
                as_of = date.fromisoformat(as_of)
            except ValueError as e:
                raise ValueError(f"as_of must be an ISO date (YYYY-MM-DD), got {as_of!r}") \
                    from e
        if as_of is not None and (isinstance(as_of, datetime) or not isinstance(as_of, date)):
            raise ValueError(f"as_of must be a date, got {as_of!r}")
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "status", _names(self.status, "status", _FILTER_STATUSES))
        object.__setattr__(self, "jurisdiction", _names(self.jurisdiction, "jurisdiction"))
        t = self.max_tier
        if t is not None and (isinstance(t, bool) or not isinstance(t, int) or not 1 <= t <= 4):
            raise ValueError(f"max_tier must be an integer from 1 to 4, got {t!r}")

    def needs_overlay(self) -> bool:
        """Whether these filters read envelope fields (the default exclusion does too, but
        without an overlay it is the Phase 1 view)."""
        return (self.as_of is not None or self.status is not None
                or self.jurisdiction is not None or self.max_tier is not None)

    def to_dict(self) -> dict:
        return {"include_superseded": self.include_superseded,
                "as_of": None if self.as_of is None else self.as_of.isoformat(),
                "status": None if self.status is None else list(self.status),
                "jurisdiction": None if self.jurisdiction is None else list(self.jurisdiction),
                "max_tier": self.max_tier}

    @classmethod
    def parse(cls, obj: Filters | dict | None) -> Filters:
        if obj is None:
            return cls()
        if isinstance(obj, Filters):
            return obj
        if not isinstance(obj, dict):
            raise ValueError(f"filters must be an object, got {type(obj).__name__}")
        unknown = sorted(set(obj) - set(_FILTER_KEYS))
        if unknown:
            raise ValueError(f"unknown filter(s) {', '.join(map(str, unknown))}; known: "
                             f"{', '.join(_FILTER_KEYS)}")
        if (as_of := obj.get("as_of")) is not None and not isinstance(as_of, (str, date)):
            raise ValueError(f"as_of must be an ISO date (YYYY-MM-DD), got {as_of!r}")
        return cls(**obj)


def admits(env: Envelope, f: Filters) -> bool:
    """Whether the filters let a document through (spec §4.4). Without `as_of`, superseded
    documents are excluded unless `include_superseded`; `as_of=D` replaces that with "in force
    on D" (proposals only when `status` names them). A filter on a field never matches a null
    or `unknown` value."""
    if f.as_of is None:
        if env.superseded_by is not None and not f.include_superseded:
            return False
    else:
        if env.valid_from is None or f.as_of < env.valid_from:
            return False
        if env.valid_to is not None and f.as_of >= env.valid_to:
            return False
        if env.status == "proposed_rule" and (f.status is None
                                              or "proposed_rule" not in f.status):
            return False
    if f.status is not None and (env.status == "unknown" or env.status not in f.status):
        return False
    if f.jurisdiction is not None and (env.jurisdiction is None
                                       or env.jurisdiction not in f.jurisdiction):
        return False
    return not (f.max_tier is not None and (env.authority_tier is None
                                            or env.authority_tier > f.max_tier))


def _listed(values: tuple[str, ...]) -> str:
    return ", ".join(values)


def exclusion_reason(env: Envelope, f: Filters) -> str | None:
    """Why the filters exclude the document (one line, the first rule of `admits` that fails),
    or None when they admit it."""
    if f.as_of is None:
        if env.superseded_by is not None and not f.include_superseded:
            return f"superseded by {env.superseded_by[:12]}…"
    else:
        d = f.as_of.isoformat()
        if env.valid_from is None:
            return f"valid_from unknown, so not in force on {d}"
        span = (f"in force from {env.valid_from.isoformat()}"
                + ("" if env.valid_to is None else f" until {env.valid_to.isoformat()}"))
        if f.as_of < env.valid_from or (env.valid_to is not None and f.as_of >= env.valid_to):
            return f"{span}, not in force on {d}"
        if env.status == "proposed_rule" and (f.status is None
                                              or "proposed_rule" not in f.status):
            return "a proposed rule, excluded under as_of unless status names proposed_rule"
    if f.status is not None and (env.status == "unknown" or env.status not in f.status):
        return f"status {env.status} is not one of {_listed(f.status)}"
    if f.jurisdiction is not None and (env.jurisdiction is None
                                       or env.jurisdiction not in f.jurisdiction):
        return (f"jurisdiction {env.jurisdiction or 'unknown'} is not one of "
                f"{_listed(f.jurisdiction)}")
    if f.max_tier is not None and (env.authority_tier is None
                                   or env.authority_tier > f.max_tier):
        tier = "unknown" if env.authority_tier is None else env.authority_tier
        return f"authority tier {tier} is above {f.max_tier}"
    return None


class Applicability:
    """A loaded overlay: its id, the snapshot it describes and the envelopes by doc id."""

    def __init__(self, overlay_id: str, snapshot: str, records: dict[str, Envelope]):
        self.overlay_id = overlay_id
        self.snapshot = snapshot
        self.records = records

    def allowed_docs(self, doc_ids: Iterable[str], f: Filters) -> tuple[frozenset[str], int]:
        """(the given documents the filters admit, how many of them they exclude). A doc id
        the overlay does not hold is a KeyError."""
        given = set(doc_ids)
        admitted = frozenset(d for d in given if admits(self.records[d], f))
        return admitted, len(given) - len(admitted)
