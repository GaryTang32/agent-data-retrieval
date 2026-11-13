"""Exact scorers for non-text answers."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from typing import Any

from adr_eval.models import Answer
from adr_eval.scoring.outcomes import Outcome

_UNITS = {"day", "days", "month", "months", "year", "years", "percent"}
_NUM = re.compile(r"\s*(-?)\s*\$?\s*(-?)(\d[\d,]*\.?\d*|\.\d+)\s*(%|[a-z]+)?\s*", re.IGNORECASE)
_MINUS = str.maketrans({"\u2212": "-", "\u2013": "-", "\u2012": "-"})
_EDGE = re.compile(r"^[\W_]+|[\W_]+$")


def _ws_lower(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", s).lower().split())


def normalize_value(s: str) -> str:
    """NFKC, lowercase, strip punctuation/space at both ends, collapse whitespace."""
    return _EDGE.sub("", _ws_lower(s))


def _boundary(text: str, i: int, step: int) -> bool:
    """Whether text[i] (looking away from a match in direction `step`) ends an identifier:
    out of range, or not a letter/digit and not `.`/`-` followed (in that direction) by one."""
    if not 0 <= i < len(text):
        return True
    c = text[i]
    if c.isalnum():
        return False
    j = i + step
    return not (c in ".-" and 0 <= j < len(text) and text[j].isalnum())


def contains_identifier(pred: str, gold: str) -> bool:
    """Whether `normalize_value(gold)` occurs in `pred` as a whole identifier (spec §5).

    Both sides are NFKC-lowercased with whitespace collapsed. An occurrence qualifies when
    the character before it is not a letter or digit, nor `.`/`-` directly preceded by one,
    and the character after it is not a letter or digit, nor `.`/`-` directly followed by one.
    """
    g = normalize_value(gold)
    if not g:
        return False
    text = _ws_lower(pred)
    i = text.find(g)
    while i != -1:
        if _boundary(text, i - 1, -1) and _boundary(text, i + len(g), 1):
            return True
        i = text.find(g, i + 1)
    return False


def parse_number(s: str | float) -> float | None:
    if isinstance(s, bool):
        return None
    if isinstance(s, int | float):
        return float(s) if math.isfinite(s) else None
    m = _NUM.fullmatch(unicodedata.normalize("NFKC", s).translate(_MINUS))
    if not m or (m.group(4) and m.group(4) != "%" and m.group(4).lower() not in _UNITS):
        return None
    if m.group(1) and m.group(2):
        return None
    try:
        return float((m.group(1) or m.group(2)) + m.group(3).replace(",", ""))
    except ValueError:
        return None


def set_prf(gold: set[str], pred: set[str]) -> tuple[float, float, float]:
    """(precision, recall, F1); both empty is a perfect match."""
    if not gold and not pred:
        return 1.0, 1.0, 1.0
    hit = len(gold & pred)
    p = hit / len(pred) if pred else 0.0
    r = hit / len(gold) if gold else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * (abs(b) if b else 1.0)


def _as_list(v: Any) -> list[str] | None:
    if isinstance(v, list | tuple | set | frozenset) and all(isinstance(x, str) for x in v):
        return list(v)
    return None


def _list_variant(v: str) -> list[str] | None:
    """A variant written as a JSON list of strings, else None."""
    try:
        return _as_list(json.loads(v))
    except ValueError:
        return None


def exact_outcome(gold: Answer, pred: Any) -> Outcome | None:
    """Score `pred` (anything with `.value` and `.abstain`) against `gold` by gold kind.

    Returns None for `text` answers, which need the judge. For `number` and `set`, a
    prediction may also match an accepted variant: parsed as a number (unparseable variants
    are skipped) or, for sets, a variant written as a JSON list; and for either kind, a
    non-list prediction equal to a variant as written (after `normalize_value`). For `id`, a
    non-list prediction is also correct when it contains the gold value (not a variant) as a
    whole identifier (`contains_identifier`).
    """
    if gold.kind == "abstain":
        return "correct" if pred.abstain else "wrong"
    if pred.abstain:
        return "abstained"
    value = pred.value
    if gold.kind == "text":
        return None
    if value is None:
        return "wrong"
    as_written = (not isinstance(value, list)
                  and normalize_value(str(value)) in {normalize_value(v)
                                                      for v in gold.accepted_variants})
    if gold.kind == "number":
        p = None if isinstance(value, list) else parse_number(value)
        golds = [None if isinstance(gold.value, list | None) else parse_number(gold.value),
                 *(parse_number(v) for v in gold.accepted_variants)]
        hit = p is not None and any(g is not None and _close(p, g) for g in golds)
        return "correct" if hit or as_written else "wrong"
    if gold.kind == "set":
        ps = _as_list(value)
        if ps is None:
            return "correct" if as_written else "wrong"
        pred_set = {normalize_value(x) for x in ps}
        golds = [_as_list(gold.value), *(_list_variant(v) for v in gold.accepted_variants)]
        return "correct" if any(g is not None and {normalize_value(x) for x in g} == pred_set
                                for g in golds) else "wrong"
    # id
    if isinstance(value, list):
        return "wrong"
    golds = {normalize_value(str(g))
             for g in [gold.value, *gold.accepted_variants] if g is not None}
    hit = (normalize_value(str(value)) in golds
           or (gold.value is not None and contains_identifier(str(value), str(gold.value))))
    return "correct" if hit else "wrong"
