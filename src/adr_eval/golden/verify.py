"""Quote matching, span checks, dedup, splits, rarity and item verification."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import numpy as np

from adr_eval.corpora.base import Document, LoadedCorpus
from adr_eval.golden.records import exec_gold_query
from adr_eval.models import Answer, GoldenItem
from adr_eval.retrieval.chunker import tokenize

# Reviewed items to drop from a corpus's golden set: {item id: one-line reason}, next to
# its items.jsonl. Applied as the last generation step; `verify_items` refuses them.
EXCLUSIONS_FILE = "review_exclusions.json"
DEDUP_THRESHOLD = 0.8

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def _normalize_with_map(s: str) -> tuple[str, list[int]]:
    """Normalize `s`; `idx[k]` is the original offset of normalized char k."""
    out: list[str] = []
    idx: list[int] = []
    pending_space = False
    for i, ch in enumerate(s):
        for c in unicodedata.normalize("NFKC", ch).translate(_QUOTES):
            if c.isspace():
                pending_space = bool(out)
                continue
            if pending_space:
                out.append(" ")
                idx.append(i)
                pending_space = False
            out.append(c)
            idx.append(i)
    return "".join(out), idx


def normalize_ws(s: str) -> str:
    return _normalize_with_map(s)[0]


def find_quote(text: str, quote: str) -> tuple[int, int] | None:
    """First occurrence of `quote` in `text` after normalization, as original offsets."""
    nq = normalize_ws(quote)
    if not nq:
        return None
    nt, idx = _normalize_with_map(text)
    pos = nt.find(nq)
    if pos < 0:
        return None
    start = idx[pos]
    last = idx[pos + len(nq) - 1]
    return start, last + 1


def count_quote(text: str, quote: str) -> int:
    nq = normalize_ws(quote)
    if not nq:
        return 0
    return normalize_ws(text).count(nq)


def check_spans(item: GoldenItem, docs: dict[str, Document]) -> bool:
    for ev in item.evidence:
        doc = docs.get(ev.doc_id)
        if doc is None:
            return False
        if normalize_ws(doc.text[ev.char_start : ev.char_end]) != normalize_ws(ev.quote):
            return False
    return True


def jaccard(a: str, b: str) -> float:
    sa, sb = set(tokenize(a)), set(tokenize(b))
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def dedup(
    items: list[GoldenItem], threshold: float = 0.8
) -> tuple[list[GoldenItem], list[GoldenItem]]:
    """Keep the first of each near-duplicate group, in `id` order."""
    kept: list[GoldenItem] = []
    dropped: list[GoldenItem] = []
    for item in sorted(items, key=lambda i: i.id):
        if any(jaccard(item.question, k.question) >= threshold for k in kept):
            dropped.append(item)
        else:
            kept.append(item)
    return kept, dropped


def assign_split(item_id: str, seed: int = 20261108) -> Literal["dev", "test"]:
    h = int(hashlib.sha256(f"{seed}:{item_id}".encode()).hexdigest(), 16)
    return "dev" if h % 100 < 20 else "test"


def doc_frequency(term: str, docs: dict[str, Document]) -> int:
    needle = tokenize(term, drop_stopwords=False)
    if not needle:
        return 0
    n = len(needle)
    count = 0
    for doc in docs.values():
        toks = tokenize(doc.text, drop_stopwords=False)
        if any(toks[i : i + n] == needle for i in range(len(toks) - n + 1)):
            count += 1
    return count


def assign_rarity(items: list[GoldenItem], dfs: dict[str, int]) -> list[GoldenItem]:
    if len(items) < 3:
        return [i.model_copy(update={"rarity": "torso"}) for i in items]
    lo, hi = np.percentile([dfs[i.id] for i in items], [100 / 3, 200 / 3])
    out = []
    for i in items:
        df = dfs[i.id]
        rarity = "tail" if df <= lo else "head" if df >= hi else "torso"
        out.append(i.model_copy(update={"rarity": rarity}))
    return out


def pair_group(item: GoldenItem) -> str:
    """Policy pairs share a group (their stem); every other item is its own group."""
    if item.qtype == "policy_asof" and item.id[-2:] in ("-a", "-b"):
        return item.id[:-2]
    return item.id


def exec_matches(result: Any, answer: Answer) -> bool:
    """Whether a typed-db query result equals the stored answer."""
    if result is None:
        return False
    if answer.kind == "number":
        return (isinstance(result, int | float) and not isinstance(result, bool)
                and float(result) == answer.value)
    if answer.kind == "set":
        return result == answer.value
    golds = [str(answer.value), *answer.accepted_variants]
    return normalize_ws(str(result)).casefold() in {normalize_ws(g).casefold() for g in golds}


def load_exclusions(path: Path) -> dict[str, str]:
    """The review exclusions file as {item id: reason}; a missing file means none."""
    path = Path(path)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise ValueError(f"{path}: expected a JSON object mapping item id to a reason")
    return data


def _near_duplicates(items: list[GoldenItem], threshold: float) -> dict[str, str]:
    """{group: earlier group's id} for groups whose first question is a near-duplicate of
    an earlier kept group's, in id order (the rule `dedup` applies during generation)."""
    reps: dict[str, GoldenItem] = {}
    for i in sorted(items, key=lambda i: i.id):
        reps.setdefault(pair_group(i), i)
    kept: list[tuple[str, set[str]]] = []
    dup: dict[str, str] = {}
    for group, rep in reps.items():
        toks = set(tokenize(rep.question))
        for kept_id, k in kept:
            union = toks | k
            if (len(toks & k) / len(union) if union else 1.0) >= threshold:
                dup[group] = kept_id
                break
        else:
            kept.append((rep.id, toks))
    return dup


def _broken_pairs(items: list[GoldenItem]) -> set[str]:
    """Policy pair groups that miss a half or whose as_of dates are not ordered a < b."""
    groups: dict[str, dict[str, GoldenItem]] = {}
    for i in items:
        if pair_group(i) != i.id:
            groups.setdefault(pair_group(i), {})[i.id[-1]] = i
    broken = set()
    for g, halves in groups.items():
        a, b = halves.get("a"), halves.get("b")
        if a is None or b is None or not (a.as_of and b.as_of and a.as_of < b.as_of):
            broken.add(g)
    return broken


def verify_items(
    items: list[GoldenItem],
    corpus: LoadedCorpus,
    *,
    records: list[dict] | None = None,
    seed: int | None = None,
    exclusions: Mapping[str, str] | None = None,
) -> tuple[list[GoldenItem], list[GoldenItem]]:
    """Check every item; returns (ok, bad) with each bad item's reasons in `reject_reason`.

    Always: snapshot, evidence documents present, spans re-slice to their quotes, unique
    ids, no near-duplicate questions (Jaccard >= 0.8, pair-aware) and intact policy pairs.
    With `records`: typed_db gold queries re-execute to the stored answer. With `seed`:
    `split == assign_split(id, seed)`. With `exclusions`: no excluded id is present.
    """
    snapshot = corpus.manifest.snapshot()
    id_counts = Counter(i.id for i in items)
    near = _near_duplicates(items, DEDUP_THRESHOLD)
    broken = _broken_pairs(items)
    ok: list[GoldenItem] = []
    bad: list[GoldenItem] = []
    for item in items:
        reasons = []
        if item.snapshot != snapshot:
            reasons.append("snapshot")
        elif any(ev.doc_id not in corpus.docs for ev in item.evidence):
            reasons.append("doc_missing")
        elif not check_spans(item, corpus.docs):
            reasons.append("span")
        span_ok = not reasons
        if id_counts[item.id] > 1:
            reasons.append("duplicate_id")
        if (records is not None and item.gold_query.store == "typed_db"
                and not exec_matches(exec_gold_query(item.gold_query, records), item.answer)):
            reasons.append("gold_query_exec")
        if pair_group(item) in near:
            reasons.append(f"near_duplicate of {near[pair_group(item)]}")
        if seed is not None and item.split != assign_split(item.id, seed):
            reasons.append("split")
        if pair_group(item) in broken:
            reasons.append("pair")
        if exclusions and item.id in exclusions:
            reasons.append("review_excluded")
        checks = item.checks.model_copy(update={"span_ok": span_ok})
        if not reasons:
            ok.append(item.model_copy(update={"checks": checks}))
        else:
            bad.append(item.model_copy(update={
                "status": "rejected", "reject_reason": "; ".join(reasons), "checks": checks}))
    return ok, bad
