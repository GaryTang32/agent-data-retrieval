"""The knowledge units as the tools serve them (Phase 4 spec §7, §8.3, §9.2, §11; Task 8): the
units of one build with their unit index, cached per process, and the pure helpers the four unit
tools of `adr_store.tools.Tools` use (`define`, `rule_lookup`, `procedure_lookup`,
`unit_search`). Access, applicability, handles, logging and every refusal stay in
`adr_store.tools`; nothing here reads the ACL or raises a `ToolError`.

- `UnitSet.of(store_path, units_id, manifest, tuning, emb)` loads a build's units and its unit
  index with `tuning` (the pinned entry the call runs on, spec P42). At `w = 1.0` the index is
  lexical-only and built in memory (preflight C8: `emb=None`); below 1 it is fused with the
  dense vectors `pin_build` stored under `<store>/units-index/<units id>/dense-*` (only read
  here: `UnitVectorsMissing` without them). A read writes nothing. Kept in a process LRU of
  `UNIT_CACHE` builds by (store, units id, tuning, embedding model). A build is immutable
  (its id is the SHA-256 of a manifest naming every file by its hash), so the cache never
  changes an answer.
- `pin_build(store_path, units_id, entry, emb)` is the one writer: it pins a tuning entry for
  a build (no file for the corpus's default entry) and, below `w = 1`, stores its dense
  vectors. `adr-eval p4-tune`, units promotion and `adr units pin` call it.
- `part_prefix`, `under`, `section_of`, `subpart`, `context_ref`, `span`, `model_value`, `labels`,
  `edit_distance`, `reader_text`, `catalog_entry`, `hit` and `card_order`: what their
  docstrings say.
"""

from __future__ import annotations

import json
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from adr_store.units import index as units_index
from adr_store.units.ecfr import _TITLE_OF_PART, normalise_rule_id
from adr_store.units.envelope import Unit
from adr_store.units.overlay import UnitsManifest, load_units, load_units_manifest

UNIT_CACHE = 4  # unit builds (units, index) kept in memory, by store, units id and tuning
UNIT_SETS: OrderedDict[tuple[str, str, str, str | None], UnitSet] = OrderedDict()
_LOCK = threading.Lock()


@dataclass(frozen=True)
class UnitSet:
    """The units of one build and their lexical unit index (module docstring)."""

    units_id: str
    corpus: str
    types: tuple[str, ...]
    units: dict[str, Unit]
    by_type: dict[str, list[Unit]]  # each sorted by unit id
    index: units_index.UnitIndex

    @classmethod
    def of(cls, store_path: Path, units_id: str, manifest: UnitsManifest, tuning: dict,
           emb=None) -> UnitSet:
        """The units of build `units_id` with their index under `tuning`; `emb` (an
        `EmbeddingCache`) is used only when `tuning["w"]` is below 1."""
        emb = emb if tuning["w"] < 1 else None
        key = (str(Path(store_path).resolve()), units_id, json.dumps(tuning, sort_keys=True),
               None if emb is None else emb.model_hash)
        with _LOCK:
            if key in UNIT_SETS:
                UNIT_SETS.move_to_end(key)
                return UNIT_SETS[key]
        units = sorted(load_units(store_path, manifest), key=lambda u: u.unit_id)
        by_type: dict[str, list[Unit]] = {}
        for u in units:
            by_type.setdefault(u.type, []).append(u)
        docs = units_index.unit_docs(units, by_type.get("concept", []))
        index = units_index.UnitIndex.build(store_path, units_id, docs, emb, tuning,
                                            install=False, stored_only=True) \
            if emb is not None else units_index.UnitIndex.build(
                store_path, units_id, docs, None, tuning, install=False)
        found = cls(units_id, manifest.corpus, tuple(f.type for f in manifest.units),
                    {u.unit_id: u for u in units}, by_type, index)
        with _LOCK:
            UNIT_SETS[key] = found
            UNIT_SETS.move_to_end(key)
            while len(UNIT_SETS) > UNIT_CACHE:
                UNIT_SETS.popitem(last=False)
        return found


def pin_build(store_path: Path, units_id: str, entry: dict | None = None, emb=None) -> str:
    """Pin `entry` (default: the tuning file's entry for the build's corpus) for build
    `units_id` and, when its `w` is below 1, store the build's dense vectors from `emb` (an
    `EmbeddingCache`, required then); idempotent. The corpus's default entry needs no file.
    Returns the entry's `unit_index`."""
    m = load_units_manifest(store_path, units_id)
    corpus_types = units_index.CORPUS_TYPES[m.corpus]
    entry = units_index.check_tuning(units_index.load_tuning(m.corpus) if entry is None
                                     else entry, corpus_types)
    tid = units_index.tuning_id(entry)
    if tid != units_index.tuning_id(units_index.default_tuning(m.corpus)):
        units_index.pin_tuning(store_path, units_id, entry)
    if entry["w"] < 1:
        if emb is None:
            raise ValueError(f"w {entry['w']} needs the embedding cache to store the dense "
                             f"vectors")
        units = sorted(load_units(store_path, m), key=lambda u: u.unit_id)
        docs = units_index.unit_docs(units, [u for u in units if u.type == "concept"])
        units_index.UnitIndex.build(store_path, units_id, docs, emb, entry)
    return tid


_PART = re.compile(r"^(?:(\d+)\s*C\.?\s?F\.?\s?R\.?\s*)?(?:part\s+)?(\d+)$", re.IGNORECASE)


def part_prefix(part: str) -> str | None:
    """"<title> CFR <part>" for a part written as "33 CFR 117", "33 CFR part 117", "part 117"
    or "117" (a bare number takes its title as `normalise_rule_id` does); None otherwise."""
    m = _PART.match(part.strip())
    title = None if m is None else (m.group(1) or _TITLE_OF_PART.get(m.group(2)))
    return None if title is None else f"{int(title)} CFR {m.group(2)}"


def under(ref: str, target: str) -> bool:
    """Whether provision `ref` is `target` or lies under it ("33 CFR 117.5(p1)" is under
    "33 CFR 117.5"; "33 CFR 117.50" is not)."""
    return ref == target or ref.startswith(target + "(")


def section_of(ref: str) -> str:
    return re.sub(r"\s*\(.*$", "", ref)


def subpart(unit: Unit) -> str | None:
    return next((h.removeprefix("Subpart ") for h in unit.heading_path
                 if h.startswith("Subpart ")), None)


_TABLE_SUFFIX = re.compile(r" table \d+$")
_SECTION_FILTER = re.compile(r'^tables:drawbridge_\w+:\{"section":"([^"]+)"')


def context_ref(unit: Unit, corpus: str) -> str | None:
    """Where `unit` sits, as a ref a concept scope can hold (§7, a unit id as `define`'s
    context): a rule card's provision; a concept's scope; an eCFR or IRM table's section
    ("33 CFR 117.313 table 1" sits in "33 CFR 117.313"); a Phase 3 drawbridge record's
    section; an IRM procedure's own number; else the unit's document scope
    "<corpus>:<doc_id>" (bench and research units, Federal Register records, IRM
    exhibits). A document scope also holds every unit of its document (`Tools.define`)."""
    if unit.type == "rule_card":
        return unit.canonical_ref
    if unit.type == "concept":
        return unit.body["scope"]["ref"]
    ref = _TABLE_SUFFIX.sub("", unit.canonical_ref)
    if m := _SECTION_FILTER.match(ref):
        return normalise_rule_id(m.group(1))
    if normalise_rule_id(ref) is not None or re.match(r"^IRM \d+(\.\d+)*$", ref):
        return normalise_rule_id(ref) or ref
    return f"{corpus}:{unit.doc_id}"


def span(unit: Unit) -> tuple[int, int]:
    """The unit's first source span: a card's paragraph, a concept's first definition."""
    return unit.source_refs[0].start, unit.source_refs[0].end


def model_value(field: object):
    """The value of a model-written body field when it was extracted, else None."""
    return field.get("value") if isinstance(field, dict) and field.get("status") else None


def labels(concept: Unit) -> list[str]:
    return [concept.body["pref_label"], *concept.body["alt_labels"]]


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance (insert, delete, substitute; each 1)."""
    if len(a) < len(b):
        a, b = b, a
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def reader_text(unit: Unit) -> str:
    """The reader text of a unit for a search hit (§11.1: body fields, never its aids)."""
    b = unit.body
    if unit.type == "concept":
        return b["definition"]["text"]
    if unit.type == "rule_card":
        return b["text"]
    if unit.type == "procedure":
        value = model_value(b.get("when_to_use"))
        if isinstance(value, str):
            return value
        return "\n".join(s["text"] for s in b["steps"] if s["text"])
    if unit.type == "faq":
        if b.get("question") is not None:
            return f"Q: {b['question']['text']}\nA: {b['answer']['text']}"
        return "\n".join(f"{f.capitalize()}: {b[f]['text']}"
                         for f in ("issue", "environment", "cause", "resolution")
                         if b.get(f) is not None)
    if unit.type == "table_record":
        return b["description"]
    return unit.title


def catalog_entry(unit: Unit, rank: int, score: float | None) -> dict:
    value = model_value(unit.body.get("when_to_use"))
    return {"rank": rank, "unit_id": unit.unit_id, "canonical_ref": unit.canonical_ref,
            "title": unit.title, "when_to_use": value if isinstance(value, str) else None,
            "doc_id": unit.doc_id, "score": score}


def hit(unit: Unit, rank: int, score: float, text_max: int) -> dict:
    """A `unit_search` hit: the envelope, the first span, the reader text cut at `text_max`
    characters (`truncated` beyond) and a table record's pointer."""
    text = reader_text(unit)
    start, end = span(unit)
    return {"rank": rank, "unit_id": unit.unit_id, "type": unit.type, "title": unit.title,
            "canonical_ref": unit.canonical_ref, "doc_id": unit.doc_id, "start": start,
            "end": end, "status": unit.applicability.status, "score": score,
            "text": text[:text_max], "truncated": len(text) > text_max,
            "pointer": unit.body.get("pointer") if unit.type == "table_record" else None}


def card_order(unit: Unit) -> tuple:
    """Cards of one rule id: the newest version first, then document order."""
    when = unit.applicability.effective_from
    return (when is None, -(when.toordinal() if when else 0), unit.doc_id, span(unit)[0],
            unit.unit_id)
