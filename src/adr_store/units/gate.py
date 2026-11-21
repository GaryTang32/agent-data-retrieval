"""The units merge gate (Phase 4 spec §6.6, criterion T6): the only code that moves
`<store>/units/HEAD`.

A candidate build and the current build (HEAD) are each asked `hit(store_path, units_id, case)`
on every case of a retrieval gold set (rule ids for gov-rules, procedure ids for the procedure
sets; the hit functions are wired with the gold kinds). A **flip** is a case HEAD hits and the
candidate misses; the candidate becomes HEAD only when it has at most `max_flips` of them.

- **First promotion** (builder note 8): with no HEAD, the comparison is against an empty
  build, which hits nothing, so the case list may be empty and the candidate is promoted with
  0 flips.
- With a HEAD, an empty case list is refused (`UnitsError`, HEAD unchanged): it cannot show
  that the candidate keeps HEAD's hits.
- A HEAD file that names a build that does not load is refused too, rather than read as no
  HEAD; so is a candidate that does not load, and one of another corpus than HEAD's.
- **Promotion pins the unit-index tuning** (spec P42): before HEAD moves, the tuning file's
  entry for the candidate's corpus is pinned for the candidate, with its dense vectors when
  its `w` is below 1 (`tools_units.pin_build`; `emb`, default the tools' embedding cache).
  A tuning that cannot be read or pinned refuses the promotion and HEAD does not move.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from adr_store.units.overlay import (
    UNITS_DIR,
    UnitsError,
    _set_units_head,
    load_units_manifest,
    read_units_head,
)


@dataclass(frozen=True)
class UnitCase:
    case_id: str
    kind: Literal["rule", "procedure"]
    payload: dict


@dataclass(frozen=True)
class UnitsGateResult:
    promoted: bool
    candidate: str
    current: str | None
    flips: list[str]        # hit on HEAD, missed by the candidate (sorted)
    gains: list[str]        # missed on HEAD, hit by the candidate (sorted)
    n: int


def _head_file(store_path: Path) -> str | None:
    try:
        return (Path(store_path) / UNITS_DIR / "HEAD").read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeDecodeError):
        return None


def pin_promoted(store_path: Path, units_id: str, emb=None) -> str:
    """Pin the tuning file's entry in force for build `units_id` (module docstring); its
    `unit_index`. `UnitsError` when the tuning cannot be read or the vectors stored."""
    from adr_store.units import index as units_index
    from adr_store.units.tools_units import pin_build

    corpus = load_units_manifest(store_path, units_id).corpus
    try:
        entry = units_index.load_tuning(corpus)
        if entry["w"] < 1 and emb is None:
            from adr_store.tools import make_embedding_cache  # the tools import this module

            emb = make_embedding_cache()
        return pin_build(store_path, units_id, entry, emb)
    except (OSError, ValueError) as e:
        raise UnitsError(f"cannot pin the unit-index tuning for {units_id[:12]}: {e}; HEAD is "
                         f"unchanged") from e


def units_gate(store_path: Path, candidate: str, cases: list[UnitCase], max_flips: int,
               hit: Callable[[Path, str, UnitCase], bool], *, emb=None) -> UnitsGateResult:
    """Evaluate `candidate` against HEAD on `cases` and move HEAD to it when it has at most
    `max_flips` flips (module docstring)."""
    if max_flips < 0:
        raise ValueError(f"max_flips must not be negative, got {max_flips}")
    ids = [c.case_id for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("gold cases must have distinct ids")
    cand = load_units_manifest(store_path, candidate)   # a candidate that does not load: refused
    current = read_units_head(store_path)
    named = _head_file(store_path)
    if current is None and named is not None:
        raise UnitsError(f"units/HEAD names {named[:12]}, a build that does not load; HEAD is "
                         f"unchanged")
    if current is not None and (corpus := load_units_manifest(store_path, current).corpus) \
            != cand.corpus:
        raise UnitsError(f"units/HEAD is a build of {corpus}, the candidate one of "
                         f"{cand.corpus}; HEAD is unchanged")
    if current is not None and not cases:
        raise UnitsError(f"units/HEAD is {current[:12]}: an empty case list cannot show that "
                         f"the candidate keeps HEAD's hits; give gold cases (HEAD is unchanged)")
    hits_new = {c.case_id for c in cases if hit(store_path, candidate, c)}
    hits_old = {c.case_id for c in cases if hit(store_path, current, c)} \
        if current is not None else set()
    flips = sorted(hits_old - hits_new)
    promoted = len(flips) <= max_flips
    if promoted:
        pin_promoted(store_path, candidate, emb)
        _set_units_head(store_path, candidate)
    return UnitsGateResult(promoted, candidate, current, flips, sorted(hits_new - hits_old),
                           len(cases))
