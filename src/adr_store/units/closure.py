"""Citation closure of rule cards (Phase 4 spec §8.3 as amended after the Task 2 review, P5,
P8, P31; criterion U2).

A card's closure lists, with a relation, the provisions an agent needs to apply it, in the
order of `RELATIONS`, computed by code from explicit text plus the one structural rule
(`config/units/closure.json`). Every entry lies in the card's own document (version): closure
never crosses documents, so a unit reaches nothing its caller could not see (P5, P31).

- `cites`: per resolved in-part section or paragraph reference of the card (in text order),
  the provisions at or under the target (`33 CFR 117.31` reaches `33 CFR 117.31(b)(1)`), in
  document order, at most `CITES_PER_REF`. A reference to a whole part, an external or a
  dangling one reaches nothing.
- `defines`: the concepts of the card's document whose labels occur in the card and whose
  scope contains it (`units.concepts.defines_entries`, rules there), each pointing at its
  definition span; written when `concepts` are given, as `units.concepts.link_concepts`
  writes them into an existing closure.
- `exception_of`: for a card in a rule's part and subpart, the provisions at or under each
  target, as for `cites` (§ 117.5 is reached as its card `33 CFR 117.5(p1)`, § 117.31(b)
  with its vessel list (b)(1)-(4)).
- `context`: the card's non-modal ancestor paragraphs (the "(c) The draw of the X bridge,
  mile 5.8:" above a modal "(c)(1)"), always; then in 33 CFR 117 the same section's
  non-modal provisions that share a `draw_keys` key ("mile 3.4") with the card, whose keys
  are its own or else those of its nearest ancestor that has any; in other parts, the
  section's `CONTEXT_MAX` non-modal provisions nearest the card (by paragraph distance, the
  earlier first at equal distance). Context is listed in document order.

A card target gives its `unit_id`; a non-modal provision gives `unit_id` null and keeps its
ref and span. The card never reaches itself. Within a relation an entry is kept once (the
first); the same provision reached under two relations is kept under both, since the relation
says how it applies (a subpart B card citing § 117.5 is still an exception of it).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from adr_store.records import _HEX64
from adr_store.units.contracts import UNIT_CONTRACT_DIR
from adr_store.units.ecfr import _UNMARKED, Provision, normalise_rule_id
from adr_store.units.envelope import Unit

__all__ = ["CITES_PER_REF", "CLOSURE_PATH", "CONTEXT_MAX", "DRAW_KEY_PARTS", "RELATIONS",
           "ClosureEntry", "closure", "closure_census", "draw_keys", "duplicate_provision_ids",
           "load_structural_rules"]

CLOSURE_PATH = UNIT_CONTRACT_DIR / "closure.json"
Relation = Literal["cites", "defines", "exception_of", "context"]
RELATIONS: tuple[str, ...] = get_args(Relation)
CITES_PER_REF = 5
CONTEXT_MAX = 3
DRAW_KEY_PARTS = ("33 CFR 117",)  # parts whose context is by draw key
_MILE = re.compile(r"\bmiles?\s+(\d+(?:\.\d+)?)", re.IGNORECASE)


class ClosureEntry(BaseModel):
    """One closure target: `{relation, ref, unit_id, doc_id, span}` (the `rule_card.closure`
    contract); `unit_id` is None for a non-modal provision."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="ClosureEntry")

    relation: Relation
    ref: str = Field(min_length=1)
    unit_id: str | None
    doc_id: str = Field(pattern=_HEX64)
    span: tuple[int, int]


def load_structural_rules(path: Path = CLOSURE_PATH) -> list[dict]:
    """The structural rules of `closure.json`: `{part, subpart, targets}` each, targets in
    normalised rule-id form."""
    rules = json.loads(Path(path).read_text(encoding="utf-8"))["rules"]
    for r in rules:
        if sorted(r) != ["part", "subpart", "targets"]:
            raise ValueError(f"{path}: a rule holds exactly part, subpart and targets: {r}")
        for t in r["targets"]:
            if normalise_rule_id(t) != t:
                raise ValueError(f"{path}: target {t!r} is not a normalised rule id")
    return rules


def draw_keys(text: str) -> frozenset[str]:
    """The "mile <n>" mentions of `text`, lower-cased: the draw keys of 33 CFR 117."""
    return frozenset(f"mile {m.group(1)}" for m in _MILE.finditer(text))


def _under(provision_id: str, target: str) -> bool:
    return provision_id == target or provision_id.startswith(target + "(")


def _entry(relation: str, p: Provision, card_of: dict) -> ClosureEntry:
    card = card_of.get((p.doc_id, p.start, p.end))
    return ClosureEntry(relation=relation, ref=p.provision_id,
                        unit_id=None if card is None else card.unit_id, doc_id=p.doc_id,
                        span=(p.start, p.end))


def _ancestors(here: Provision, section: list[Provision]) -> list[Provision]:
    """The provisions of the section whose marked path is a proper prefix of `here`'s
    (`(c)` for `(c)(1)` and for `(c)(p1)`), nearest last."""
    mine = here.path
    out = [p for p in section if p is not here and not any(_UNMARKED.match(m) for m in p.path)
           and len(p.path) < len(mine) and mine[:len(p.path)] == p.path]
    return sorted(out, key=lambda p: len(p.path))


def closure(cards: list[Unit], provs: list[Provision], concepts: list[Unit] = ()
            ) -> dict[str, list[ClosureEntry]]:
    """{card unit id: its closure entries} for every card of `cards`; `provs` are the
    provisions of the cards' documents (from `ecfr.rule_cards`); `concepts` are the concept
    units the `defines` entries come from (none: no `defines`)."""
    # imported here: units.concepts builds on ClosureEntry and RELATIONS of this module
    from adr_store.units.concepts import _Labels, defines_entries

    labels = _Labels(list(concepts))
    rules = load_structural_rules()
    by_doc: dict[str, list[Provision]] = {}
    for p in provs:
        by_doc.setdefault(p.doc_id, []).append(p)
    for ps in by_doc.values():
        ps.sort(key=lambda p: p.start)
    at = {(p.doc_id, p.start, p.end): p for p in provs}
    card_of = {(c.doc_id, c.source_refs[0].start, c.source_refs[0].end): c for c in cards}
    out: dict[str, list[ClosureEntry]] = {}
    for c in cards:
        here = at.get((c.doc_id, c.source_refs[0].start, c.source_refs[0].end))
        if here is None:
            raise ValueError(f"{c.unit_id}: no provision at the card's span")
        others = [p for p in by_doc[c.doc_id] if p is not here]
        entries: list[ClosureEntry] = []
        for x in c.body.get("cross_refs", []):
            if x["resolution"] != "resolved" or " CFR part " in x["target_ref"]:
                continue
            hits = [p for p in others if _under(p.provision_id, x["target_ref"])]
            entries += [_entry("cites", p, card_of) for p in hits[:CITES_PER_REF]]
        entries += defines_entries(c, labels)
        for r in rules:
            if (here.part, here.subpart) != (r["part"], r["subpart"]):
                continue
            for t in r["targets"]:
                entries += [_entry("exception_of", p, card_of) for p in others
                            if _under(p.provision_id, t)]
        section = [p for p in by_doc[c.doc_id] if p.section == here.section]
        ancestors = _ancestors(here, section)
        plain = [p for p in section if p.modality is None]
        if here.part in DRAW_KEY_PARTS:
            keys = draw_keys(here.text) or next(
                (k for a in reversed(ancestors) if (k := draw_keys(a.text))), frozenset())
            near = [p for p in plain if keys & draw_keys(p.text)]
        else:
            idx = {id(p): i for i, p in enumerate(section)}
            me = idx[id(here)]
            near = sorted(plain, key=lambda p: (abs(idx[id(p)] - me), idx[id(p)]))[:CONTEXT_MAX]
        context = {id(p): p for p in [*(a for a in ancestors if a.modality is None), *near]}
        entries += [_entry("context", p, card_of)
                    for p in sorted(context.values(), key=lambda p: p.start)]
        seen: set[tuple] = set()
        kept = []
        for e in entries:
            key = (e.relation, e.doc_id, e.span)
            if key not in seen:
                seen.add(key)
                kept.append(e)
        out[c.unit_id] = kept
    return out


def duplicate_provision_ids(provs: list[Provision]) -> list[dict]:
    """Provision ids held by more than one provision of one document (repeated markers in
    the source), sorted by (document, id): `{doc_id, provision_id, count, modal}`."""
    groups: dict[tuple[str, str], list[Provision]] = {}
    for p in provs:
        groups.setdefault((p.doc_id, p.provision_id), []).append(p)
    return [{"doc_id": d, "provision_id": pid, "count": len(ps),
             "modal": sum(p.modality is not None for p in ps)}
            for (d, pid), ps in sorted(groups.items()) if len(ps) > 1]


def closure_census(cards: list[Unit], provs: list[Provision]) -> dict:
    """Criterion U2 over the cards' cross-references (`provs`: the provisions of the cards'
    documents). Counts per resolution; the in-part provision references (resolved and
    dangling; whole-part references are counted apart, `part_references`) and the share
    resolved; every unresolved in-part reference and, apart, every part reference with its
    reason (`section_missing`: the version holds no provision of that section, absent or
    reserved;
    `paragraph_missing`: the section is there but no provision at or under the target;
    `part_reference`), sorted by (unit id, span); and the duplicate provision ids."""
    sections = {(p.doc_id, p.section) for p in provs}
    counts = {"resolved": 0, "dangling": 0, "external": 0}
    parts = 0
    listed = []
    for c in cards:
        for x in c.body.get("cross_refs", []):
            counts[x["resolution"]] += 1
            reason = None
            if " CFR part " in x["target_ref"]:
                if x["resolution"] == "external":
                    continue
                parts += 1
                reason = "part_reference"
            elif x["resolution"] == "dangling":
                section = x["target_ref"].split(" CFR ", 1)[1].split("(", 1)[0]
                reason = ("paragraph_missing" if (c.doc_id, section) in sections
                          else "section_missing")
            if reason is not None:
                listed.append({
                    "unit_id": c.unit_id, "canonical_ref": c.canonical_ref,
                    "doc_id": c.doc_id, "raw": x["raw"], "target_ref": x["target_ref"],
                    "span": x["span"], "reason": reason})
    resolved = counts["resolved"] - parts
    in_part = resolved + counts["dangling"]
    reasons: dict[str, int] = {}
    for u in listed:
        reasons[u["reason"]] = reasons.get(u["reason"], 0) + 1
    listed.sort(key=lambda u: (u["unit_id"], u["span"]))
    return {"cards": len(cards), "in_part": in_part, "in_part_resolved": resolved,
            "resolved_rate": resolved / in_part if in_part else None, "resolution": counts,
            "reasons": dict(sorted(reasons.items())),
            "unresolved": [u for u in listed if u["reason"] != "part_reference"],
            "part_references": [u for u in listed if u["reason"] == "part_reference"],
            "duplicate_provision_ids": duplicate_provision_ids(provs)}
