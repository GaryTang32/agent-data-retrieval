"""Grounding helpers and the model-pass configs of the knowledge units (Phase 4 spec §6.2,
§6.3).

`ground` locates a model's quote in the input text (check 3: Phase 0's whitespace
normalisation, `golden.verify.find_quote`) and gives its offsets in that text; the caller
stores the located slice, so the stored quote always re-slices. `time_in_quote` is check 4 for
clock times: the quote states the minute of the day in a clock form ("7:30 a.m.", "7 a.m.",
"noon", "midnight"); `clock_times` finds the clock times a value states.

`config/units/passes.json` holds one `PassConfig` per model pass ("procedure" now; "rules",
the enrichment pass, is added with it): the prompt version and the field groups, one cached
call per unit and group, with each field's spec version. The prompt of a group names the
prompt version and that group's spec ids, so the cache key covers both, and bumping one spec
recompiles only its group (§6.5, criterion T5).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from adr_eval.golden.verify import find_quote
from adr_store.units.contracts import UNIT_CONTRACT_DIR

PASSES_CONFIG = "passes.json"
_SPEC = re.compile(r"[a-z][a-z_]*\.[a-z][a-z0-9_]*@[1-9]\d*")
_CLOCK = re.compile(r"(?<![\d:])(\d{1,2})(?::([0-5]\d))?\s*([ap])\.?\s?m\b\.?", re.IGNORECASE)
_WORDS = {"noon": (720,), "midnight": (0, 1440)}


def ground(text: str, quote: str) -> tuple[int, int] | None:
    """(start, end) of `quote` in `text`, whitespace normalised as Phase 0 does
    (`find_quote`: the first occurrence); None when it is not there or is no text."""
    if not isinstance(quote, str) or not quote.strip():
        return None
    return find_quote(text, quote)


def clock_times(text: str) -> list[tuple[int, int, frozenset[int]]]:
    """(start, end, the minutes of the day it may mean) of every clock time `text` states, in
    text order: "7:30 a.m.", "7 a.m.", "7:30 PM" (hours 1 to 12; 12 a.m. is 0, 12 p.m. 720),
    "noon" (720) and "midnight" (0, or 1440 at the end of a day)."""
    found = []
    for m in _CLOCK.finditer(text):
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if 1 <= hour <= 12:
            pm = m.group(3).lower() == "p"
            found.append((m.start(), m.end(),
                          frozenset({(hour % 12 + (12 if pm else 0)) * 60 + minute})))
    for word, minutes in _WORDS.items():
        found += [(m.start(), m.end(), frozenset(minutes))
                  for m in re.finditer(rf"\b{word}\b", text, re.IGNORECASE)]
    return sorted(found, key=lambda t: (t[0], t[1]))


def _clock_minutes(quote: str) -> set[int]:
    """Every minute of the day `quote` states as a clock time (`clock_times`)."""
    return {m for _, _, minutes in clock_times(quote) for m in minutes}


def time_in_quote(minutes: int, quote: str) -> bool:
    """Check 4 for a time value: `quote` states the minute of the day `minutes` in a clock
    form (`_clock_minutes`)."""
    return minutes in _clock_minutes(quote)


class PassConfig(BaseModel):
    """One model pass: its prompt version, its field groups (one cached call per unit and
    group; each field in exactly one group) and each field's spec version
    (`<type>.<field>@<n>`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_version: str
    groups: dict[str, list[str]]
    specs: dict[str, str]

    @model_validator(mode="after")
    def _consistent(self) -> PassConfig:
        named = [f for fields in self.groups.values() for f in fields]
        if not named or len(set(named)) != len(named):
            raise ValueError("the groups must name each field once")
        if any(not re.fullmatch(r"[A-Za-z0-9_]+", g) for g in self.groups):
            raise ValueError("a group name is letters, digits and underscores")
        if set(self.specs) != set(named):
            raise ValueError("specs must name exactly the fields of the groups")
        for field, spec in self.specs.items():
            if not _SPEC.fullmatch(spec) or spec.split(".", 1)[1].split("@")[0] != field:
                raise ValueError(f"{field}: spec {spec!r} is not <type>.{field}@<version>")
        return self


def load_pass_config(name: Literal["procedure", "rules"],
                     path: Path = UNIT_CONTRACT_DIR / PASSES_CONFIG) -> PassConfig:
    """The config of model pass `name` in `passes.json` (keys starting "_" are comments);
    ValueError when the file has none for it."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if name not in data or name.startswith("_"):
        raise ValueError(f"{path}: no config for the {name} pass")
    return PassConfig.model_validate(data[name])
