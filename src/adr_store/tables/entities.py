"""Entity resolution (Phase 3 spec §6): deterministic, no model calls.

Seven entity types, each with a normalisation key (`normalise_key`) and an id that is the
SHA-256 of the key (`entity_id`). Only equal keys merge, so clustering never chains through
fuzzy matches. An optional committed file `config/entities/<type>.json` merges clusters or
splits one by key (`Overrides`); every override is listed in the entity report.

An entity table holds one row per (entity, raw form, source table, source column, document):
the raw forms a document uses for the entity, counted per source rows. A row's access is that
of its document, so a hidden document's spelling never reaches a view. The `display_name` column
is not stored: a view computes it from the rows that view can see (`display_names`, the
byte-smallest raw form), so it never reveals a hidden row's spelling.

Entity rows carry structure provenance without a span: they are computed from the rows of other
tables (and the overrides), not read from one place in a document.
"""

from __future__ import annotations

import hashlib
import random
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from adr_eval.corpora import REPO_ROOT
from adr_store.tables.parse import base_key, waterway_key
from adr_store.tables.provenance import RowRecord, value_prov

ENTITY_TYPES = ("agencies", "cfr_parts", "dockets", "venues", "licences", "waterways", "authors")
ENTITY_DIR = REPO_ROOT / "config" / "entities"
DEFAULT_SEED = 20261120

_TRAILING_YEAR = re.compile(r"\s*\(?(19|20)\d{2}\)?$")
_PREPRINT = re.compile(r"\bpreprint\b")
_CFR_LABEL = re.compile(r"^\s*(\d+)\s*cfr\s+(\S+)\s*$", re.IGNORECASE)


class Overrides(BaseModel):
    """`merge`: groups of keys that become one cluster, the smallest key of the group. `split`:
    a key mapped to groups of raw forms; the raw forms of group i get the key `<key>#<i+1>`,
    those listed in no group keep `<key>`."""

    model_config = ConfigDict(extra="forbid")

    merge: list[list[str]] = []
    split: dict[str, list[list[str]]] = {}


def normalise_key(etype: str, raw: str) -> str:
    """The key of `raw` under the rules of `etype` (§6). Equal keys are one entity."""
    if etype not in ENTITY_TYPES:
        raise ValueError(f"unknown entity type {etype!r}")
    if etype == "venues":
        key = _TRAILING_YEAR.sub("", base_key(raw))
        return base_key(_PREPRINT.sub("", key))
    if etype == "licences":
        return re.sub(r"[\s_-]+", "-", base_key(raw))
    if etype == "cfr_parts":
        m = _CFR_LABEL.match(raw)
        if m and m.group(2).isascii() and m.group(2).isdigit():
            return f"{int(m.group(1))} cfr {int(m.group(2))}"
        return base_key(raw)
    if etype == "waterways":
        return waterway_key(raw)
    return base_key(raw)     # agencies, dockets, authors


def entity_id(key: str) -> str:
    """The canonical id of the entity with this key."""
    return hashlib.sha256(key.encode()).hexdigest()


def load_overrides(etype: str, directory: Path = ENTITY_DIR) -> Overrides:
    """The overrides of `etype` from `<directory>/<etype>.json`; none when there is no file."""
    path = Path(directory) / f"{etype}.json"
    if not path.is_file():
        return Overrides()
    return Overrides.model_validate_json(path.read_bytes())


def overrides_for(etype: str, given: Mapping[str, Overrides] | None) -> Overrides:
    """`given[etype]`, or the committed overrides of `etype` when `given` is None or lacks it."""
    if given is not None and etype in given:
        return given[etype]
    return load_overrides(etype)


def _split(key: str, raw: str, overrides: Overrides) -> str:
    """`key` of the raw form `raw` after the splits of the overrides."""
    for i, group in enumerate(overrides.split.get(key, []), 1):
        if raw in group:
            return f"{key}#{i}"
    return key


def entity_key(etype: str, raw: str, overrides: Overrides) -> str:
    """The cluster key of one raw form: its normalisation key, split and then merged by the
    overrides. Empty when the raw form has no key."""
    key = normalise_key(etype, raw)
    if not key:
        return ""
    key = _split(key, raw, overrides)
    for group in overrides.merge:
        if key in group:
            return min(group)
    return key


def resolve(etype: str, raws: Iterable[str], overrides: Overrides) -> dict[str, str]:
    """raw form -> cluster key, for every raw form given."""
    return {raw: entity_key(etype, raw, overrides) for raw in raws}


# -- entity rows -----------------------------------------------------------------------------

SPEC = {c: f"entity.{c}@1" for c in ("entity_id", "key", "raw", "source_table", "source_column",
                                     "doc_id", "rows")}


def entity_rows(etype: str, sources: list[tuple[str, str, RowRecord]],
                overrides: Overrides | None = None) -> list[RowRecord]:
    """One row per (entity id, raw form, source table, source column, document) over `sources`,
    (source table, column, row): the column's value (or each element of a list) is a raw form;
    `rows` counts the source rows that hold it. A missing value or one with no key makes no
    entity. Rows are sorted by those five columns."""
    ov = load_overrides(etype) if overrides is None else overrides
    counts: dict[tuple[str, str, str, str, str], int] = {}
    keys: dict[str, str] = {}
    for table, column, rec in sources:
        value = rec.row.get(column)
        raws = value if isinstance(value, list) else [value]
        for raw in {r for r in raws if isinstance(r, str)}:
            if raw not in keys:
                keys[raw] = entity_key(etype, raw, ov)
            if keys[raw]:
                k = (entity_id(keys[raw]), raw, table, column, rec.doc_id)
                counts[k] = counts.get(k, 0) + 1
    out = []
    for (eid, raw, table, column, doc_id), n in sorted(counts.items()):
        row = {"entity_id": eid, "key": keys[raw], "raw": raw, "source_table": table,
               "source_column": column, "doc_id": doc_id, "rows": n}
        out.append(RowRecord(doc_id=doc_id, row=row,
                             prov={c: value_prov(doc_id, SPEC[c]) for c in row}))
    return out


def display_names(rows: Iterable[dict]) -> dict[str, str]:
    """entity id -> its display name: the byte-smallest (UTF-8) raw form among the rows given.
    Callers pass the rows of one view only, so a hidden row's spelling is never chosen."""
    best: dict[str, str] = {}
    for r in rows:
        eid, raw = r["entity_id"], r["raw"]
        if eid not in best or raw.encode() < best[eid].encode():
            best[eid] = raw
    return best


def entity_report(etype: str, rows: list[RowRecord], overrides: Overrides,
                  seed: int = DEFAULT_SEED, *, largest: int = 10, sample: int = 50) -> dict:
    """What the resolution of `etype` did: clusters, `singletons` (one raw form) and `merged`
    (two or more), the `largest` clusters (most raw forms, then most rows, then key), a seeded
    `sample` of clusters for inspection, and the overrides with the keys they name that no
    cluster has (`unmatched`)."""
    clusters: dict[str, dict] = {}
    base: set[str] = set()
    after_split: set[str] = set()
    for rec in rows:
        r = rec.row
        c = clusters.setdefault(r["key"], {"key": r["key"], "entity_id": r["entity_id"],
                                           "raws": set(), "rows": 0, "docs": set()})
        c["raws"].add(r["raw"])
        c["rows"] += r["rows"]
        c["docs"].add(r["doc_id"])
        base.add(normalise_key(etype, r["raw"]))
        after_split.add(_split(normalise_key(etype, r["raw"]), r["raw"], overrides))
    listed = [{"key": c["key"], "entity_id": c["entity_id"], "forms": len(c["raws"]),
               "rows": c["rows"], "docs": len(c["docs"]), "raws": sorted(c["raws"], key=_bytes)}
              for _, c in sorted(clusters.items(), key=lambda kv: _bytes(kv[0]))]
    ranked = sorted(listed, key=lambda c: (-c["forms"], -c["rows"], _bytes(c["key"])))
    unmatched = sorted({k for g in overrides.merge for k in g if k not in after_split}
                       | {k for k in overrides.split if k not in base})
    return {
        "etype": etype, "seed": seed, "clusters": len(listed),
        "rows": sum(c["rows"] for c in listed),
        "singletons": sum(1 for c in listed if c["forms"] == 1),
        "merged": sum(1 for c in listed if c["forms"] > 1),
        "largest": ranked[:largest],
        "sample": random.Random(seed).sample(listed, min(sample, len(listed))),
        "overrides": {"merge": overrides.merge, "split": overrides.split,
                      "unmatched": unmatched},
    }


def _bytes(s: str) -> bytes:
    return s.encode()
