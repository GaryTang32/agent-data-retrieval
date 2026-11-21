"""Phase 4 retrieval harness (spec §14, §15.1, §15.2, rulings P19, P20, P21, P36, P42; preflight
C12, C13, N4, N9, N23, N25): rule-ID recall (R1), procedure top-5 (R2), the unit-index tuning,
and the hit functions of the units merge gate's gold sets. No model is called here.

**Golden sets** (`GOLDENS`, `load_items`), each read as `P4Item`s:
- `gov-rules` (rule items): gold provisions = the item's `evidence` (one span per `gold_rules`
  id); closure provisions = its `closure_evidence` (the located spans of `closure_rules`, N23).
- `gov-procedures`, `bench-procedures` (procedure items): gold = the item's `gold` (an IRM
  canonical ref, "IRM 21.4.1.3.1", or a bench document id).
- `gov-v0.1-ecfr` (rule items; the secondary R1 of §15.2): the gov v0.1 items with evidence in
  an eCFR document; gold provisions = the provisions (`units.ecfr.provisions`, every paragraph)
  whose spans overlap the item's eCFR evidence spans. Items with eCFR evidence but no
  overlapped provision (evidence in a section heading, a table row or a list outside every
  paragraph) have no gold provision: they are counted per split (`secondary.no_provision`,
  beside `secondary.ecfr_evidence`) and left out.

**Systems** (`SYSTEMS`, `build_system`). Every system runs each item with the item's `as_of`
(P36): the harness passes it itself, so `runner._takes_as_of` is unchanged and Phase 2 runs
stay identical. All search the p2 store of the corpus (`systems.p2_store_dir`) as
`config["p2_caller"]` (`user:auditor`; none: without the ACL layer).
- `p2-default`: `systems.build("p2-default", …)` over the corpus's v0.1 items (N25), searched
  directly at depth `DEPTH` = `CHANNEL_K` (C12): `searcher.search(q, top=DEPTH,
  filters=filters_for(as_of), dedup=spec.dedup)`.
- `p2-default-scoped`: `p2-default`'s ranking at depth `DEPTH`, restricted to chunks of eCFR
  documents (rule sets) or to chunks starting inside a procedure-candidate IRM section or a
  bench candidate document (procedure sets), order kept (builder note 12 as revised by C12).
- `p1-struct-bc`: the Phase 1 system at depth `DEPTH`, which takes no `as_of`: reported beside,
  flagged `as_of_applied: false`.
- `p4-units`: routed by golden set (oracle routing, P21): rule items `rule_lookup(question,
  as_of, closure=True, limit=UNIT_DEPTH)`, procedure items `procedure_lookup(question, as_of,
  limit=UNIT_DEPTH)`; `UNIT_DEPTH` (the tools' cap, 100) hits reach the budget.
- `p4-unit-search`: `unit_search(question, as_of, limit=UNIT_DEPTH)` over every type.

**Pieces** (`Piece`, N4: `char_start`/`char_end`, as `retrieval_metrics.overlap` reads). A
system returns ranked items, each a list of pieces: a chunk is one piece; a `p4-units` rule hit
is the card's span followed by its closure entries' spans in closure order; a procedure or
unit-search hit is the unit's first span. A piece's text is the verbatim slice of its span.
`budget_cut` keeps pieces in order while the harness token count (`n_tokens`:
`tokenize(text, drop_stopwords=False)`, as `tokens_at_k`) stays within `TOKEN_BUDGET`; the
piece that crosses it is cut to the longest prefix that fits, its span shrunk to that prefix,
and nothing after it is kept (builder note 11).

**R1 metrics** (rule items; `score_rule`): `recall` = the share of gold provisions a piece of
the budget-cut list touches (span overlap, the Phase 0 `touches` rule, `rule_recall`);
`closure_recall` likewise over the closure provisions (None without closure rules);
`recall@10` and `tokens@10` over the pieces of the first `RECALL_K` items, uncut; `mrr` = 1 /
rank of the first item touching a gold provision; `tokens` = tokens in the cut.
**R2 metrics** (procedure items; `score_procedure`): each item's first piece is mapped to a
section key (`section_key`: the located IRM section holding its start, by
`units.procedures.irm_sections`, else its document id), the keys deduped in rank order
(`procedure_ranks`): `hit@1`, `hit@5` (`HIT_K`) and `rr`.

**Runs** (`run_p4`) write `<out_root>/<golden>-<system>-<split>-p4-<started>/p4.json` (config,
summary, rows) under `runs/` (local, gitignored; `OUT_ROOT`, which the tests redirect).
`p4_compare` pairs rows by item id and reports means, the paired difference (run_b − run_a)
with `paired_bootstrap_ci` (seed 20261108, 10,000 resamples) for each pair of runs and for all
pairs pooled; it names no item.

**Tuning** (`tune`, C13): per unit type with dev items (gov-rules → `rule_card`, the procedure
sets → `procedure`), field weights from `WEIGHT_GRID` on that type's dev nDCG@10 over gold
keys (lexical, `w = 1`); then `w` from `W_GRID` on the pooled dev nDCG@10 of every set given,
ties to the larger `w`. Types without dev items keep weight 1. The result is one corpus entry
of the tuning file (`units.index.write_tuning`).

**Gate gold** (`gold_cases`, `rule_hit`, `procedure_hit`): `adr units gate --gold DIR` reads
gov-rules items as `UnitCase(kind="rule")`, hit when every gold provision is within the budget
of `p4-units` on that build, and procedure items as `UnitCase(kind="procedure")`, hit when the
gold section is among the first `HIT_K`; both as `user:auditor` on dev and test items, through
a handle naming the build and the pinned tuning in force.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from adr_eval import runner
from adr_eval.models import Evidence, GoldenItem
from adr_eval.retrieval.chunker import tokenize
from adr_eval.runner import RunError
from adr_eval.scoring.retrieval_metrics import overlap
from adr_eval.scoring.stats import paired_bootstrap_ci
from adr_store import acl
from adr_store.retrieval.index import CHANNEL_K

TOKEN_BUDGET = 2000
DEPTH = CHANNEL_K       # chunk systems' ranking depth (C12): Tools.search's cap
UNIT_DEPTH = 100        # hits asked of the unit tools (tools.UNIT_LIMIT_MAX)
HIT_K = 5
RECALL_K = 10
SYSTEMS = ("p2-default", "p1-struct-bc", "p2-default-scoped", "p4-units", "p4-unit-search")
GOLDENS = ("gov-rules", "gov-procedures", "bench-procedures", "gov-v0.1-ecfr")
CORPUS = {"gov-rules": "gov", "gov-procedures": "gov", "bench-procedures": "bench",
          "gov-v0.1-ecfr": "gov"}
KIND = {"gov-rules": "rule", "gov-procedures": "procedure", "bench-procedures": "procedure",
        "gov-v0.1-ecfr": "rule"}
TUNE_GOLDENS = ("gov-rules", "gov-procedures", "bench-procedures")
TUNE_TYPE = {"rule": "rule_card", "procedure": "procedure"}
RULE_METRICS = ("recall", "closure_recall", "recall@10", "mrr", "tokens@10", "tokens")
PROCEDURE_METRICS = ("hit@1", "hit@5", "rr")
AUDITOR = "user:auditor"
MARGIN = 0.02
N_RESAMPLES = 10_000
SEED = 20261108
FORMAT = "p4-retrieval@1"
OUT_ROOT = Path("runs")   # where `adr-eval p4-retrieval` writes by default (tests redirect it)
CLOCK: Callable[[], datetime] = acl.utc_now   # the ACL freshness clock (tests set it)


# -- pieces, the budget, recall ----------------------------------------------------------------

@dataclass(frozen=True)
class Piece:
    doc_id: str
    char_start: int
    char_end: int
    text: str
    source: str      # chunk id, unit id or closure ref


def n_tokens(text: str) -> int:
    """The harness token count (`tokenize`, stop words kept), as `tokens_at_k` counts."""
    return len(tokenize(text, drop_stopwords=False))


def _longest_prefix(text: str, budget: int) -> int:
    """The length of the longest prefix of `text` with at most `budget` tokens (the count is
    monotone in the prefix length)."""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if n_tokens(text[:mid]) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return lo


def budget_cut(pieces: list[Piece], budget: int = TOKEN_BUDGET) -> list[Piece]:
    """The pieces in order while their tokens stay within `budget`; the piece that crosses it
    cut to the longest prefix that fits (its span shrunk to that prefix, dropped when the
    prefix holds no token), and nothing after it."""
    out: list[Piece] = []
    left = budget
    for p in pieces:
        n = n_tokens(p.text)
        if n <= left:
            out.append(p)
            left -= n
            continue
        cut = _longest_prefix(p.text, left)
        if left > 0 and n_tokens(p.text[:cut]) > 0:
            out.append(replace(p, char_end=p.char_start + cut, text=p.text[:cut]))
        break
    return out


def _touches(piece: Piece, ev: Evidence) -> bool:
    return overlap(piece, ev) > 0     # `overlap` reads doc_id, char_start and char_end


def rule_recall(pieces: list[Piece], gold: list[Evidence]) -> float:
    """The share of gold provisions that a piece touches (any span overlap on the same
    document)."""
    if not gold:
        raise ValueError("rule_recall needs at least one gold provision")
    return sum(any(_touches(p, e) for p in pieces) for e in gold) / len(gold)


# -- sections and procedure ranks --------------------------------------------------------------

def section_key(doc_id: str, start: int, sections: dict[str, list]) -> str:
    """The source section a span starting at `start` belongs to: "IRM <number>" of the located
    IRM section of `doc_id` holding `start` (`sections[doc_id]`, `IrmSection`s), else the
    document id (a bench document, or text outside every located section)."""
    for s in sections.get(doc_id, ()):
        if s.start <= start < s.end:
            return f"IRM {s.number}"
    return doc_id


def procedure_ranks(keys: list[str], gold: str) -> dict:
    """hit@1, hit@5 and the reciprocal rank of `gold` among `keys` deduped in rank order."""
    seen: list[str] = []
    for k in keys:
        if k not in seen:
            seen.append(k)
    rank = seen.index(gold) + 1 if gold in seen else None
    return {"hit@1": int(rank == 1), f"hit@{HIT_K}": int(rank is not None and rank <= HIT_K),
            "rr": 0.0 if rank is None else 1.0 / rank}


def irm_section_map(store) -> dict[str, list]:
    """{IRM document id: its located sections} of `store`."""
    from adr_store import applicability as ap
    from adr_store.units.procedures import irm_sections

    return {d: irm_sections(store, d)[0] for d in sorted(store.doc_ids())
            if ap.family_of(store.source(d).uri) == "irm"}


# -- items -------------------------------------------------------------------------------------

@dataclass(frozen=True)
class P4Item:
    id: str
    question: str
    as_of: date | None
    split: str
    kind: Literal["rule", "procedure"]
    gold: tuple[Evidence, ...] = ()       # rule items: the gold provisions
    closure: tuple[Evidence, ...] = ()    # rule items: the closure provisions (N23)
    gold_rules: tuple[str, ...] = ()      # rule items: their ids (tuning, the gate)
    gold_key: str | None = None           # procedure items: the gold section key
    part: str | None = None


def p4_item(item) -> P4Item:
    """A `RuleItem` or `ProcedureItem` as the harness reads it."""
    from adr_eval.golden.units import RuleItem

    if isinstance(item, RuleItem):
        return P4Item(item.id, item.question, item.as_of, item.split, "rule",
                      tuple(item.evidence), tuple(item.closure_evidence),
                      tuple(item.gold_rules), None, item.part)
    return P4Item(item.id, item.question, None, item.split, "procedure", tuple(item.evidence),
                  (), (), item.gold, None)


def _part_of(chain: str) -> str:
    _, title, part = chain.split(":")
    return f"{title} CFR {part}"


def secondary_gold(store, item: GoldenItem, cache: dict | None = None) -> tuple[list[Evidence],
                                                                               str | None]:
    """(the gold provisions of a gov v0.1 item: the provisions overlapping its eCFR evidence
    spans, in document order and once each; the eCFR part of its evidence, or None without
    eCFR evidence)."""
    from adr_store import applicability as ap
    from adr_store.units.ecfr import provisions

    cache = {} if cache is None else cache
    gold: dict[tuple, Evidence] = {}
    parts = []
    for e in item.evidence:
        chain = ap.chain_of(store.source(e.doc_id)) if e.doc_id in store.doc_ids() else None
        if not (chain or "").startswith("ecfr:"):
            continue
        parts.append(_part_of(chain))
        if e.doc_id not in cache:
            cache[e.doc_id] = provisions(store, e.doc_id)
        for p in cache[e.doc_id]:
            if p.start < e.char_end and e.char_start < p.end:
                gold[(p.doc_id, p.start, p.end)] = Evidence(doc_id=p.doc_id, char_start=p.start,
                                                            char_end=p.end, quote=p.text)
    return [gold[k] for k in sorted(gold)], (sorted(set(parts))[0] if parts else None)


def load_items(golden: str, store_path: Path | None = None, report: dict | None = None
               ) -> list[P4Item]:
    """The items of `golden` (`GOLDENS`), sorted by id; `gov-v0.1-ecfr` reads the provisions of
    the store at `store_path` (module docstring) and counts in `report` the items it leaves
    out."""
    from adr_eval.golden.units import load_procedure_items, load_rule_items

    if golden not in GOLDENS:
        raise RunError(f"unknown golden set {golden!r}; one of {', '.join(GOLDENS)}")
    try:
        if golden == "gov-rules":
            return sorted((p4_item(i) for i in load_rule_items()), key=lambda i: i.id)
        if golden in ("gov-procedures", "bench-procedures"):
            return sorted((p4_item(i) for i in load_procedure_items(golden)),
                          key=lambda i: i.id)
    except FileNotFoundError as e:
        raise RunError(f"{e.filename}: golden set not found; run `adr-eval golden "
                       f"{golden.split('-')[1]} --gen`") from e
    from adr_store.store import Store

    _, items, _ = _v01("gov")
    store = Store.open(store_path)
    out, cache = [], {}
    counts = {"ecfr_evidence": {}, "no_provision": {}}
    for i in sorted(items, key=lambda i: i.id):
        gold, part = secondary_gold(store, i, cache)
        if part is None:
            continue
        split = i.split or "none"
        counts["ecfr_evidence"][split] = counts["ecfr_evidence"].get(split, 0) + 1
        if not gold:
            counts["no_provision"][split] = counts["no_provision"].get(split, 0) + 1
            continue
        out.append(P4Item(i.id, i.question, i.as_of, i.split, "rule", tuple(gold), (), (),
                          None, part))
    if report is not None:
        report["secondary"] = counts
    return out


# -- systems -----------------------------------------------------------------------------------

def _v01(corpus: str) -> tuple:
    """(the loaded corpus, its v0.1 golden items, their evidence groups): what
    `systems.build` tunes the Phase 1 reference on (N25)."""
    from adr_eval.scoring import evidence_groups

    loaded = runner.load_checked_corpus(corpus)
    items = runner.load_golden(corpus, loaded)
    return loaded, items, evidence_groups.build_all(items, loaded.docs)


@dataclass
class ChunkSystem:
    """`p2-default`, `p2-default-scoped` or `p1-struct-bc` over the chunks of a store."""

    name: str
    base: object            # systems.P2System or systems.StoreSystem
    store: object           # adr_store.store.Store the chunks are sliced from
    as_of_applied: bool
    scope: Callable[[Piece], bool] | None = None
    _text: dict = field(default_factory=dict)

    def text(self, doc_id: str, start: int, end: int) -> str:
        if doc_id not in self._text:
            self._text[doc_id] = self.store.text(doc_id)
        return self._text[doc_id][start:end]

    def ranked(self, item: P4Item) -> list[list[Piece]]:
        if self.as_of_applied:
            b = self.base
            res = b.searcher.search(item.question, top=DEPTH, filters=b.filters_for(item.as_of),
                                    dedup=b.spec.dedup)
            ids = [h.chunk_id for h in res.hits]
        else:
            ids = [c for c, _ in self.base.index.retrieve(item.question, fusion="linear",
                                                          w=self.base.w, top=DEPTH)]
        chunks = self.base.chunks
        out = []
        for c in ids:
            ch = chunks[c]
            p = Piece(ch.doc_id, ch.char_start, ch.char_end,
                      self.text(ch.doc_id, ch.char_start, ch.char_end), c)
            if self.scope is None or self.scope(p):
                out.append([p])
        return out

    def config(self) -> dict:
        return {"fingerprint": self.base.fingerprint, "w": self.base.w,
                "as_of_applied": self.as_of_applied, "scoped": self.scope is not None,
                "settings": self.base.run_config()}


@dataclass
class UnitSystem:
    """`p4-units` or `p4-unit-search` through the unit tools of the p2 store."""

    name: str
    tools: object           # adr_store.tools.Tools of the p2 store
    store: object
    as_of_applied: bool = True
    seen: dict = field(default_factory=dict)       # units id and unit_index of the results
    _spans: dict = field(default_factory=dict)     # units id -> {procedure unit id: span}
    _text: dict = field(default_factory=dict)

    def text(self, doc_id: str, start: int, end: int) -> str:
        if doc_id not in self._text:
            self._text[doc_id] = self.store.text(doc_id)
        return self._text[doc_id][start:end]

    def _note(self, res) -> None:
        self.seen.setdefault("units", res.units)
        self.seen.setdefault("unit_index", (res.handle or {}).get("unit_index"))
        if self.seen["units"] != res.units:
            raise RunError(f"the units changed during the run ({self.seen['units'][:12]} to "
                           f"{res.units[:12]})")

    def _procedure_spans(self, units_id: str) -> dict:
        if units_id not in self._spans:
            from adr_store.units.overlay import load_units, load_units_manifest

            m = load_units_manifest(self.tools.store_path, units_id)
            self._spans[units_id] = {u.unit_id: (u.doc_id, u.source_refs[0].start,
                                                 u.source_refs[0].end)
                                     for u in load_units(self.tools.store_path, m)
                                     if u.type == "procedure"}
        return self._spans[units_id]

    def ranked(self, item: P4Item) -> list[list[Piece]]:
        if self.name == "p4-unit-search":
            res = self.tools.unit_search(item.question, as_of=item.as_of, limit=UNIT_DEPTH)
            self._note(res)
            return [[Piece(h["doc_id"], h["start"], h["end"],
                           self.text(h["doc_id"], h["start"], h["end"]), h["unit_id"])]
                    for h in res.hits]
        if item.kind == "rule":
            res = self.tools.rule_lookup(item.question, as_of=item.as_of, closure=True,
                                         limit=UNIT_DEPTH)
            self._note(res)
            return [[Piece(c.doc_id, c.start, c.end, self.text(c.doc_id, c.start, c.end),
                           c.unit_id),
                     *(Piece(e["doc_id"], e["start"], e["end"], e["text"], e["ref"])
                       for e in c.closure)] for c in res.cards]
        res = self.tools.procedure_lookup(item.question, as_of=item.as_of, limit=UNIT_DEPTH)
        self._note(res)
        spans = self._procedure_spans(res.units)
        out = []
        for e in res.catalog:
            doc, start, end = spans[e["unit_id"]]
            out.append([Piece(doc, start, end, self.text(doc, start, end), e["unit_id"])])
        return out

    def config(self) -> dict:
        return {"as_of_applied": True, "caller": self.tools.caller, **self.seen}


def _unit_tools(path: Path, caller: str | None):
    from adr_store.tools import Tools

    if caller is None:
        return Tools(path)
    return Tools(path, acl=True, caller=caller, clock=CLOCK)


def _scope(kind: str, store) -> Callable[[Piece], bool]:
    """In scope for `p2-default-scoped`: a chunk of an eCFR document (rule sets), or one starting
    inside a procedure-candidate IRM section or a bench candidate document (procedure sets)."""
    from adr_store import applicability as ap
    from adr_store.units.procedures import bench_candidates, is_procedure_like

    if kind == "rule":
        ecfr = frozenset(d for d in store.doc_ids()
                         if (ap.chain_of(store.source(d)) or "").startswith("ecfr:"))
        return lambda p: p.doc_id in ecfr
    spans = {d: [(s.start, s.end) for s in secs if is_procedure_like(s)]
             for d, secs in irm_section_map(store).items()}
    bench = frozenset(bench_candidates(store))
    return lambda p: p.doc_id in bench or any(a <= p.char_start < b
                                              for a, b in spans.get(p.doc_id, ()))


def build_system(name: str, corpus: str, config: dict, kind: Literal["rule", "procedure"]):
    """The system `name` of `SYSTEMS` for `corpus` and items of `kind` (module docstring)."""
    from adr_eval import systems
    from adr_store.store import Store

    if name not in SYSTEMS:
        raise RunError(f"unknown system {name!r}; one of {', '.join(SYSTEMS)}")
    path = systems.p2_store_dir(config, corpus)
    if name in ("p4-units", "p4-unit-search"):
        if not (path / "HEAD").is_file():
            raise RunError(f"{path}: no store\nfix: run a Phase 2 configuration of {corpus} "
                           f"(it copies the Phase 1 store), then build and promote its units")
        return UnitSystem(name, _unit_tools(path, config.get("p2_caller")), Store.open(path))
    loaded, items, groups = _v01(corpus)
    base_name = "p1-struct-bc" if name == "p1-struct-bc" else "p2-default"
    base = systems.build(base_name, corpus, loaded, items, groups, config)
    if name == "p1-struct-bc":
        return ChunkSystem(name, base, Store.open(base.store_path), as_of_applied=False)
    store = base.tools.store
    scope = _scope(kind, store) if name == "p2-default-scoped" else None
    return ChunkSystem(name, base, store, as_of_applied=True, scope=scope)


def ranked_items(system, item: P4Item) -> list[list[Piece]]:
    """The system's ranked items for `item`, each a list of pieces (module docstring)."""
    return system.ranked(item)


def pieces_for(system, item: P4Item) -> list[Piece]:
    """Every piece the system returns for `item`, in rank order (before the budget)."""
    return [p for it in ranked_items(system, item) for p in it]


# -- scoring -----------------------------------------------------------------------------------

def score_rule(item: P4Item, ranked: list[list[Piece]], budget: int = TOKEN_BUDGET) -> dict:
    pieces = [p for it in ranked for p in it]
    cut = budget_cut(pieces, budget)
    top = [p for it in ranked[:RECALL_K] for p in it]
    first = next((r for r, it in enumerate(ranked, 1)
                  if any(_touches(p, e) for p in it for e in item.gold)), None)
    return {"recall": rule_recall(cut, list(item.gold)),
            "closure_recall": rule_recall(cut, list(item.closure)) if item.closure else None,
            "recall@10": rule_recall(top, list(item.gold)),
            "mrr": 0.0 if first is None else 1.0 / first,
            "tokens@10": sum(n_tokens(p.text) for p in top),
            "tokens": sum(n_tokens(p.text) for p in cut)}


def item_keys(ranked: list[list[Piece]], sections: dict) -> list[str]:
    """The section key of each ranked item (its first piece), in rank order."""
    return [section_key(it[0].doc_id, it[0].char_start, sections) for it in ranked if it]


def score_procedure(item: P4Item, ranked: list[list[Piece]], sections: dict) -> dict:
    return procedure_ranks(item_keys(ranked, sections), item.gold_key)


def _mean(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def summarize(rows: list[dict], kind: str) -> dict:
    """Means of every metric (a metric's mean over the items where it is defined, with its
    count), pooled and by part (rule items)."""
    keys = RULE_METRICS if kind == "rule" else PROCEDURE_METRICS

    def block(rs: list[dict]) -> dict:
        return {"n": len(rs),
                **{k: _mean([r["metrics"][k] for r in rs]) for k in keys},
                "n_defined": {k: sum(r["metrics"][k] is not None for r in rs) for k in keys}}

    out = {"pooled": block(rows)}
    if kind == "rule":
        parts = sorted({r["part"] for r in rows if r.get("part")})
        out["by_part"] = {p: block([r for r in rows if r.get("part") == p]) for p in parts}
    return out


# -- runs --------------------------------------------------------------------------------------

def _golden_file(golden: str) -> Path:
    from adr_eval.golden import units as gu

    if golden == "gov-rules":
        return gu.RULES_DIR / "items.jsonl"
    if golden == "gov-v0.1-ecfr":
        return runner.golden_items_path("gov")
    return gu.procedures_dir(golden) / "items.jsonl"


def run_p4(golden: str, system: str, split: Literal["dev", "test"], config: dict,
           out_root: Path | None = None) -> str:
    """Run `system` over the `split` items of `golden` (module docstring); writes
    `<out_root>/<run id>/p4.json` (`out_root` default `OUT_ROOT`) and returns the run id. No
    model is called."""
    from adr_eval import systems

    t0 = time.perf_counter()
    started = datetime.now(UTC)
    if golden not in GOLDENS:
        raise RunError(f"unknown golden set {golden!r}; one of {', '.join(GOLDENS)}")
    if system not in SYSTEMS:
        raise RunError(f"unknown system {system!r}; one of {', '.join(SYSTEMS)}")
    corpus, kind = CORPUS[golden], KIND[golden]
    store_path = systems.p2_store_dir(config, corpus)
    report: dict = {}
    every = load_items(golden, store_path, report)
    items = [i for i in every if i.split == split]
    if not items:
        raise RunError(f"{golden}: no items in split {split!r}")
    built = build_system(system, corpus, config, kind)
    sections = irm_section_map(built.store) if kind == "procedure" else {}
    rows = []
    for item in items:
        ranked = ranked_items(built, item)
        metrics = (score_rule(item, ranked) if kind == "rule"
                   else score_procedure(item, ranked, sections))
        row = {"item_id": item.id, "kind": kind, "part": item.part,
               "as_of": (item.as_of.isoformat() if item.as_of and built.as_of_applied
                         else None),
               "ranked": [it[0].source for it in ranked if it][:RECALL_K * 2],
               "metrics": metrics}
        if kind == "procedure":
            row["keys"] = item_keys(ranked, sections)[:RECALL_K * 2]
        rows.append(row)
    out_root = OUT_ROOT if out_root is None else Path(out_root)
    run_dir = runner._new_run_dir(out_root, f"{golden}-{system}-{split}-p4-{started:%Y%m%dT%H%M%S}")
    gfile = _golden_file(golden)
    cfg = {"run_id": run_dir.name, "format": FORMAT, "golden": golden, "corpus": corpus,
           "kind": kind, "system": system, "split": split, "n_items": len(items),
           "budget": TOKEN_BUDGET, "depth": DEPTH, "unit_depth": UNIT_DEPTH, "hit_k": HIT_K,
           "store": runner._display_path(store_path), "store_snapshot": built.store.snapshot_id,
           "caller": config.get("p2_caller"), "system_config": built.config(),
           "golden_file": runner._display_path(gfile),
           "golden_sha256": hashlib.sha256(gfile.read_bytes()).hexdigest()
           if gfile.is_file() else None, **report,
           "started": started.isoformat(), "finished": datetime.now(UTC).isoformat(),
           "wall_clock_s": round(time.perf_counter() - t0, 1)}
    data = {"config": cfg, "summary": summarize(rows, kind), "rows": rows}
    (run_dir / "p4.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                                     encoding="utf-8")
    return run_dir.name


def load_run(run: Path) -> dict:
    run = Path(run)
    path = run / "p4.json" if run.is_dir() else run
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RunError(f"{run}: not a p4-retrieval run (p4.json)") from e
    if data.get("config", {}).get("format") != FORMAT:
        raise RunError(f"{run}: not a p4-retrieval run of format {FORMAT}")
    return data


def _ci(x: list[float], y: list[float]) -> dict:
    diff, lo, hi = paired_bootstrap_ci(x, y, n=N_RESAMPLES, seed=SEED)
    return {"n": len(x), "mean_a": sum(x) / len(x), "mean_b": sum(y) / len(y), "diff": diff,
            "ci": [lo, hi]}


def p4_compare(run_a: Path, run_b: Path, metric: str, *,
               pooled: Sequence[tuple[Path, Path]] = ()) -> dict:
    """`run_b − run_a` on `metric` over the items both runs score it on, for the pair given
    and each pair in `pooled` (other corpora's runs of the same two systems), and over all
    pairs pooled (items of the first pair, then of each pooled pair, by id within each).
    Refuses runs of different golden sets or splits within a pair, or of other systems than
    the first pair's. No item id is written."""
    pairs = [(Path(run_a), Path(run_b)), *((Path(a), Path(b)) for a, b in pooled)]
    each, xs, ys = [], [], []
    systems_ab = None
    for pa, pb in pairs:
        a, b = load_run(pa), load_run(pb)
        ca, cb = a["config"], b["config"]
        for key in ("golden", "split", "budget"):
            if ca.get(key) != cb.get(key):
                raise RunError(f"cannot compare runs of different {key}: {ca.get(key)} "
                               f"({pa.name}) and {cb.get(key)} ({pb.name})")
        if systems_ab is None:
            systems_ab = (ca["system"], cb["system"])
        elif (ca["system"], cb["system"]) != systems_ab:
            raise RunError(f"pooled runs must compare {systems_ab[1]} with {systems_ab[0]}, "
                           f"not {cb['system']} with {ca['system']}")
        ra = {r["item_id"]: r["metrics"] for r in a["rows"]}
        rb = {r["item_id"]: r["metrics"] for r in b["rows"]}
        if set(ra) != set(rb):
            raise RunError(f"{pa.name} and {pb.name} score different items")
        if any(metric not in m for m in (*ra.values(), *rb.values())):
            raise RunError(f"{metric!r} is not a metric of {pa.name} and {pb.name}")
        ids = sorted(i for i in ra if ra[i][metric] is not None and rb[i][metric] is not None)
        if not ids:
            raise RunError(f"{pa.name} and {pb.name}: no item scores {metric!r} in both")
        x, y = [float(ra[i][metric]) for i in ids], [float(rb[i][metric]) for i in ids]
        each.append({"golden": ca["golden"], "split": ca["split"], **_ci(x, y)})
        xs += x
        ys += y
    pooled_block = _ci(xs, ys)
    pooled_block["lower_above_margin"] = pooled_block["ci"][0] > MARGIN
    return {"metric": metric, "difference": "run_b - run_a", "system_a": systems_ab[0],
            "system_b": systems_ab[1], "margin": MARGIN, "seed": SEED,
            "resamples": N_RESAMPLES, "each": each, "pooled": pooled_block,
            "each_point_non_negative": all(e["diff"] >= 0 for e in each)}


# -- tuning (C13) ------------------------------------------------------------------------------

def ndcg_keys(keys: list[str], gold: set[str], k: int = 10) -> float:
    """Binary nDCG@k of ranked keys against gold keys: a key's first occurrence in `gold`
    gains 1 / log2(rank + 1); ideal = min(k, |gold|) gains."""
    if not gold:
        return 0.0
    dcg, seen = 0.0, set()
    for r, key in enumerate(keys[:k], 1):
        if key in gold and key not in seen:
            seen.add(key)
            dcg += 1.0 / math.log2(r + 1)
    return dcg / sum(1.0 / math.log2(r + 1) for r in range(1, min(k, len(gold)) + 1))


@dataclass
class _TuneSet:
    store_path: Path
    units_id: str
    docs: list
    keys: dict          # unit id -> its gold key (a card's canonical ref, a procedure's section)
    view: frozenset | None
    admitted: dict      # item id -> the documents the filters admit for it


def _tune_set(store_path: Path, corpus: str, items: list[P4Item]) -> _TuneSet:
    from adr_store import handles
    from adr_store.applicability import Filters, load_overlay
    from adr_store.store import Store
    from adr_store.units import index as ui
    from adr_store.units.overlay import load_units, load_units_manifest

    store = Store.open(store_path)
    units_id = handles.units_head(store_path, store.snapshot_id)
    if units_id is None:
        raise RunError(f"{store_path}: no promoted units for snapshot {store.snapshot_id[:12]}")
    m = load_units_manifest(store_path, units_id)
    if m.corpus != corpus:
        raise RunError(f"{store_path}: its units are of {m.corpus}, not {corpus}")
    units = load_units(store_path, m)
    sections = irm_section_map(store)
    keys = {u.unit_id: (u.canonical_ref if u.type == "rule_card" else
                        section_key(u.doc_id, u.source_refs[0].start, sections))
            for u in units if u.type in ("rule_card", "procedure")}
    view = None
    if (Path(store_path) / "acl").is_dir():
        access = _unit_tools(Path(store_path), AUDITOR)._access()
        view = frozenset(access.docs) if access is not None else None
    overlay = load_overlay(store_path, store.snapshot_id)
    docs_in_view = sorted(view) if view is not None else store.doc_ids()
    admitted = {}
    for i in items:
        f = Filters(as_of=i.as_of) if i.as_of else Filters()
        admitted[i.id] = (None if overlay is None
                          else overlay.allowed_docs(docs_in_view, f)[0])
    return _TuneSet(Path(store_path), units_id,
                    ui.unit_docs(units, [u for u in units if u.type == "concept"]), keys, view,
                    admitted)


def _gold_of(item: P4Item) -> set[str]:
    return set(item.gold_rules) if item.kind == "rule" else {item.gold_key}


def _score(index, ts: _TuneSet, items: list[P4Item]) -> float:
    """Mean nDCG@10 of `index` over `items` (each searched for its type, its filters)."""
    vals = []
    for i in items:
        hits = index.search(i.question, types=(TUNE_TYPE[i.kind],), view=ts.view,
                            admitted=ts.admitted[i.id], k=10)
        vals.append(ndcg_keys([ts.keys[u] for u, _ in hits], _gold_of(i)))
    return sum(vals) / len(vals)


def tune(goldens: Sequence[str], store_path: Path, *, emb=None,
         report: dict | None = None) -> dict:
    """The tuned corpus entry `{"weights", "w"}` (module docstring) from the dev items of
    `goldens` (gov-rules and/or gov-procedures for gov; bench-procedures for bench) over the
    promoted units of the store at `store_path`; `emb` (an `EmbeddingCache`) builds the dense
    vectors `w` is tuned with (required). `report`, when given, receives the dev counts and
    the best scores."""
    from adr_store.units import index as ui
    from adr_store.units.build import CORPUS_TYPES

    goldens = list(dict.fromkeys(goldens))
    bad = [g for g in goldens if g not in TUNE_GOLDENS]
    if not goldens or bad:
        raise RunError(f"tune takes golden sets of {', '.join(TUNE_GOLDENS)}, got "
                       f"{', '.join(goldens) or 'none'}")
    corpora = {CORPUS[g] for g in goldens}
    if len(corpora) != 1:
        raise RunError(f"tune one corpus at a time: {', '.join(goldens)} are of "
                       f"{', '.join(sorted(corpora))}")
    corpus = corpora.pop()
    if emb is None:
        raise RunError("tuning w needs the embedding cache (the dense channel)")
    dev = {g: [i for i in load_items(g) if i.split == "dev"] for g in goldens}
    if not any(dev.values()):
        raise RunError(f"no dev items in {', '.join(goldens)}")
    every = [i for g in goldens for i in dev[g]]
    ts = _tune_set(store_path, corpus, every)
    base = ui.default_tuning(corpus)
    by_type: dict[str, list[P4Item]] = {}
    for i in every:
        by_type.setdefault(TUNE_TYPE[i.kind], []).append(i)
    best_scores = {}
    for t in sorted(by_type):
        best, best_score = None, -1.0
        for combo in itertools.product(ui.WEIGHT_GRID, repeat=len(ui.FIELDS)):
            entry = {**base, "weights": {**base["weights"], t: dict(zip(ui.FIELDS, combo,
                                                                        strict=True))}}
            idx = ui.UnitIndex.build(store_path, ts.units_id, ts.docs, None, entry,
                                     install=False)
            s = _score(idx, ts, by_type[t])
            if s > best_score:
                best, best_score = combo, s
        base = {**base, "weights": {**base["weights"], t: dict(zip(ui.FIELDS, best,
                                                                   strict=True))}}
        best_scores[t] = best_score
    w_best, w_score = None, -1.0
    for w in sorted(ui.W_GRID, reverse=True):          # ties keep the larger w
        idx = ui.UnitIndex.build(store_path, ts.units_id, ts.docs, emb, {**base, "w": w})
        s = _score(idx, ts, every)
        if s > w_score:
            w_best, w_score = w, s
    entry = ui.check_tuning({**base, "w": w_best}, CORPUS_TYPES[corpus])
    if report is not None:
        report.update(corpus=corpus, units=ts.units_id,
                      dev={g: len(dev[g]) for g in goldens},
                      weights_ndcg10=best_scores, w_ndcg10=w_score)
    return entry


# -- the units merge gate's gold (adr units gate --gold) ---------------------------------------

def gold_cases(directory: Path) -> list:
    """The `UnitCase`s of a unit golden set directory (its items.jsonl): gov-rules items as
    `kind="rule"`, procedure items as `kind="procedure"`, the item as payload; dev and test."""
    from adr_eval.golden.units import ProcedureItem, RuleItem
    from adr_eval.models import jsonl_lines
    from adr_store.units.gate import UnitCase

    path = Path(directory) / "items.jsonl"
    try:
        lines = jsonl_lines(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise RunError(f"{path}: not a unit golden set (items.jsonl)") from e
    cases = []
    for line in lines:
        obj = json.loads(line)
        if obj.get("corpus") == "gov-rules":
            item = RuleItem.model_validate(obj)
            cases.append(UnitCase(item.id, "rule", item.model_dump(mode="json")))
        elif obj.get("corpus") in ("gov-procedures", "bench-procedures"):
            item = ProcedureItem.model_validate(obj)
            cases.append(UnitCase(item.id, "procedure", item.model_dump(mode="json")))
        else:
            raise RunError(f"{path}: an item of {obj.get('corpus')!r} is not a unit gold case")
    return cases


def _build_tools(store_path: Path, units_id: str):
    """(the auditor's tools, a handle naming build `units_id` and the pinned tuning in force
    for its corpus)."""
    from adr_store import handles
    from adr_store.store import Store
    from adr_store.units import index as ui

    m = handles.units_manifest(store_path, units_id)
    if m is None:
        raise RunError(f"{store_path}: units {units_id[:12]} do not load")
    snapshot = Store.open(store_path).snapshot_id
    tid = ui.pin_tuning(store_path, units_id, ui.load_tuning(m.corpus))
    handle = handles.current(store_path, snapshot, units=units_id, unit_index=tid)
    return _unit_tools(Path(store_path), AUDITOR), handle.model_dump()


def rule_hit(store_path: Path, units_id: str, case) -> bool:
    """Whether every gold provision of rule case `case` is within the budget of `p4-units` on
    build `units_id`, as `user:auditor`."""
    from adr_eval.golden.units import RuleItem

    item = p4_item(RuleItem.model_validate(case.payload))
    tools, handle = _build_tools(store_path, units_id)
    res = tools.rule_lookup(item.question, as_of=item.as_of, closure=True, limit=UNIT_DEPTH,
                            handle=handle)
    text: dict[str, str] = {}

    def sl(doc, a, b):
        if doc not in text:
            text[doc] = tools.store.text(doc)
        return text[doc][a:b]

    pieces = [p for c in res.cards for p in
              (Piece(c.doc_id, c.start, c.end, sl(c.doc_id, c.start, c.end), c.unit_id),
               *(Piece(e["doc_id"], e["start"], e["end"], e["text"], e["ref"])
                 for e in c.closure))]
    return rule_recall(budget_cut(pieces), list(item.gold)) == 1.0


def procedure_hit(store_path: Path, units_id: str, case) -> bool:
    """Whether the gold section of procedure case `case` is among the first `HIT_K` sections
    of `procedure_lookup` on build `units_id`, as `user:auditor`."""
    from adr_eval.golden.units import ProcedureItem
    from adr_store.store import Store
    from adr_store.units.overlay import load_units, load_units_manifest

    item = p4_item(ProcedureItem.model_validate(case.payload))
    tools, handle = _build_tools(store_path, units_id)
    res = tools.procedure_lookup(item.question, limit=UNIT_DEPTH, handle=handle)
    units = {u.unit_id: u for u in load_units(store_path, load_units_manifest(
        store_path, units_id)) if u.type == "procedure"}
    sections = irm_section_map(Store.open(store_path))
    keys = [section_key(units[e["unit_id"]].doc_id, units[e["unit_id"]].source_refs[0].start,
                        sections) for e in res.catalog]
    return procedure_ranks(keys, item.gold_key)[f"hit@{HIT_K}"] == 1


def gate_hit(store_path: Path, units_id: str, case) -> bool:
    """`rule_hit` or `procedure_hit` by the case's kind."""
    return (rule_hit if case.kind == "rule" else procedure_hit)(store_path, units_id, case)
