"""The gov-rules, gov-procedures and bench-procedures v0.1 golden generators (Phase 4 spec §14,
rulings P22, P30, P36): items drawn by code over the source structure, phrased by a model.

Gold comes from the source structure, never from the system under test (P22): provisions
(`units.ecfr.provisions`, `cross_refs`), IRM sections (`units.procedures.irm_sections`,
`is_procedure_like`) and bench procedure documents (`units.procedures.bench_candidates`). No
unit is built, indexed or looked up here, and no item holds a unit id.

- **The rule universe** (`rule_universe`): per eCFR part, in every stored version, the modal
  provisions (the rule-card lexicon, §8.1) of at least `MIN_CHARS` characters (whitespace
  collapsed) whose span re-slices, less boilerplate: a provision whose normalised text (leading
  markers off, whitespace collapsed, case-folded) is the normalised text of a provision of
  another section of the same version. (This normalisation reproduces the survey's counts of
  §4.1: 1,136, 823 and 1,239 modal paragraphs of the newest versions occur in one section.)
- **The draw** (`draw_rules`). Per part of `RULE_COUNTS`, `OLDER_SHARE` of the count (rounded
  half up) comes from the older versions and the rest from the newest. The older pool holds the
  eligible provisions of an older version whose provision id the newest version holds with
  another normalised text (a provision the newest version no longer has is not drawn: its text
  cannot "differ from the newest"); a (provision id, text) found in two older versions is kept
  once, from the later of them. An older-version draw has `as_of` = that version's `valid_from`
  (the Phase 2 applicability overlay), a newest-version draw `as_of` None. Each pool is ranked by
  the SHA-256 of "<seed>:<doc id>:<start>:<end>"; the draw is the head of each pool, and a
  provision whose phrasing fails is replaced by the next one of its pool. A pool shorter than
  its share is drawn whole and the shortfall reported, not padded.
- **Closure** (N23): `closure_rules` are the in-part `cites` targets of the drawn provision, in
  text order, once each: its resolved cross-references in its own part, whole-part references
  aside, and a target reaching only the drawn provision itself aside. `closure_evidence[k]` is
  the span of `closure_rules[k]` in the drawn version: from the first provision at or under the
  target to the end of the last one, re-sliced.
- **Procedures** (`generate_procedures`): gov, the procedure-like located sections of the IRM
  documents of a store (gold "IRM <number>", evidence the section's located span); bench, the
  drawn bench candidates (gold the document id, evidence the whole document). `N_PROCEDURES`
  per set, ranked as above by "<seed>:<doc id>:<start>:<end>".
- **Phrasing**: one cached call per draw (`client.complete(prompt, message, max_tokens=MAX_TOKENS,
  repeat=r, cache_failures=True)`) with the source text, never a unit. `leak_reason` rejects a
  question holding the section or IRM number, a 3-gram of the heading's words after stop words,
  or a 6-gram of the source; a rejected or malformed phrasing is redrawn once at repeat 1, then
  the draw is replaced. A call the provider rejected for its input (stored, ruling P21) replaces
  the draw at once (the same input would be rejected again). Any other model failure and a
  budget stop propagate: nothing is returned and the completed calls stay cached.
- **Items**: ids `gov-rules-001`..., `gov-procedures-001`..., `bench-procedures-001`... in draw
  order (rules: part by part in `RULE_COUNTS` order, newest draws before older ones), splits by
  `assign_split(id)`, `created` the newest ISO date among the source versions of the documents
  drawn from (the Unix epoch when none is a date, as for bench). With `limit`, generation stops
  after that many items per set, so a limited run gives the first items of the full one.

gov items are written under `golden/gov-rules/v0.1/` and `golden/gov-procedures/v0.1/` (US
government works, committed); bench items under `golden/bench-procedures/v0.1/` stay local
(`.gitignore`, P30).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from importlib import resources
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from adr_eval.corpora import REPO_ROOT
from adr_eval.golden.generate import _reply
from adr_eval.golden.verify import assign_split
from adr_eval.llm import CachedFailure, ModelOutputError
from adr_eval.models import Evidence, Provenance, jsonl_lines
from adr_store import applicability as ap
from adr_store.store import Store
from adr_store.tables.ecfr import chain_docs
from adr_store.units.ecfr import PARTS, Provision, cross_refs, provisions
from adr_store.units.procedures import bench_candidates, irm_sections, is_procedure_like

__all__ = ["BENCH_PROCEDURES_DIR", "GOV_PROCEDURES_DIR", "MAX_TOKENS", "MIN_CHARS",
           "N_PROCEDURES", "OLDER_SHARE", "PROCEDURE_CORPORA", "PROCEDURE_PROMPT_VERSION",
           "RULES_DIR", "RULE_COUNTS", "RULE_PROMPT_VERSION", "SEED4", "STOP_WORDS",
           "GoldenError", "ProcedureItem", "RuleItem", "draw_rules", "generate_procedures",
           "generate_rules", "leak_reason", "load_procedure_items", "load_rule_items",
           "normalised", "older_count", "procedure_message", "procedures_dir", "rule_message",
           "rule_universe", "write_items"]

RULE_PROMPT_VERSION = "rule_question@1"
PROCEDURE_PROMPT_VERSION = "procedure_question@1"
MAX_TOKENS = 400
RULES_DIR = REPO_ROOT / "golden" / "gov-rules" / "v0.1"
GOV_PROCEDURES_DIR = REPO_ROOT / "golden" / "gov-procedures" / "v0.1"
BENCH_PROCEDURES_DIR = REPO_ROOT / "golden" / "bench-procedures" / "v0.1"
RULE_COUNTS = {"33 CFR 117": 40, "33 CFR 165": 30, "47 CFR 73": 30}
OLDER_SHARE = 0.20
N_PROCEDURES = 50
MIN_CHARS = 60
SEED4 = 20261121
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
STOP_WORDS = frozenset((
    "a", "an", "and", "any", "are", "as", "at", "be", "been", "but", "by", "can", "do", "does",
    "for", "from", "has", "have", "how", "i", "if", "in", "into", "is", "it", "its", "may",
    "my", "no", "not", "of", "on", "or", "our", "s", "should", "so", "than", "that", "the",
    "their", "then", "there", "these", "this", "those", "to", "under", "upon", "was", "we",
    "were", "what", "when", "where", "which", "who", "whom", "why", "will", "with", "would",
    "you", "your"))
_PROMPTS = {"rules": "prompts/rule_question.txt", "procedures": "prompts/procedure_question.txt"}
ProcedureCorpus = Literal["gov-procedures", "bench-procedures"]
PROCEDURE_CORPORA: tuple[ProcedureCorpus, ...] = ("gov-procedures", "bench-procedures")


class GoldenError(Exception):
    """A store the generators cannot draw from (no applicability overlay, a set found in two
    stores or in none)."""


class RuleItem(BaseModel):
    id: str
    corpus: Literal["gov-rules"]
    snapshot: str
    part: str                       # "33 CFR 117"
    question: str
    as_of: date | None              # the older version's valid_from; None for the newest
    gold_rules: list[str]           # the drawn provision's id (its canonical ref)
    closure_rules: list[str]        # its in-part `cites` targets
    closure_evidence: list[Evidence]  # one span per closure rule, in the drawn version (N23)
    evidence: list[Evidence]        # the drawn provision's span
    split: Literal["dev", "test"]
    provenance: Provenance
    status: Literal["auto_verified"]


class ProcedureItem(BaseModel):
    id: str
    corpus: ProcedureCorpus
    snapshot: str
    question: str
    gold: str                       # IRM canonical_ref, or the bench doc id
    evidence: list[Evidence]
    split: Literal["dev", "test"]
    provenance: Provenance
    status: Literal["auto_verified"]


# -- prompts -------------------------------------------------------------------------------------


def load_prompt(kind: Literal["rules", "procedures"]) -> str:
    return resources.files("adr_eval.golden").joinpath(_PROMPTS[kind]).read_text(
        encoding="utf-8")


def prompt_hash(kind: Literal["rules", "procedures"]) -> str:
    return hashlib.sha256(
        resources.files("adr_eval.golden").joinpath(_PROMPTS[kind]).read_bytes()).hexdigest()


_SECTION_SIGN = re.compile(r"^\s*§+\s*\S+\s*")


def section_title(heading: str) -> str:
    """A section heading without its "§ N" ("§ 117.821 Smith River." -> "Smith River.")."""
    return _SECTION_SIGN.sub("", heading).strip()


def rule_message(p: Provision) -> str:
    """The rule phrasing call's user message: the part, the section's title and the source
    text (the provision's paragraph). No number and no unit."""
    return f"Part: {p.part}\nSection heading: {section_title(p.heading)}\n\nSource text:\n{p.text}"


def procedure_message(corpus: ProcedureCorpus, title: str, text: str) -> str:
    """The procedure phrasing call's user message: where the text comes from, its title and
    the source text (the IRM section's own text or the bench document). No number."""
    where = ("a section of the Internal Revenue Manual" if corpus == "gov-procedures"
             else "an internal company document")
    return f"Source: {where}\nTitle: {title}\n\nSource text:\n{text}"


# -- leaks ---------------------------------------------------------------------------------------

_WORD = re.compile(r"[^\W_]+")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


def _grams(tokens: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def leak_reason(question: str, source: str, heading: str, numbers: list[str]) -> str | None:
    """Why `question` leaks its source, or None: "number" when it holds one of `numbers` (the
    section or IRM number, not inside a longer number), "heading 3-gram" when it holds three
    consecutive words of `heading` (both with `STOP_WORDS` left out), "source 6-gram" when it
    holds six consecutive words of `source`. Words are case-folded runs of letters and
    digits."""
    folded = question.casefold()
    for n in numbers:
        if n and re.search(rf"(?<![\w.]){re.escape(n.casefold())}(?!\w|\.\w)", folded):
            return "number"
    words = _tokens(question)

    def content(tokens: list[str]) -> list[str]:
        return [t for t in tokens if t not in STOP_WORDS]

    if _grams(content(words), 3) & _grams(content(_tokens(heading)), 3):
        return "heading 3-gram"
    if _grams(words, 6) & _grams(_tokens(source), 6):
        return "source 6-gram"
    return None


# -- the rule universe and the draw --------------------------------------------------------------

_LEADING_MARKERS = re.compile(r"^\s*(?:\(\w{1,5}\)\s*)+")


def normalised(text: str) -> str:
    """The boilerplate key of a provision's text: leading markers off, whitespace collapsed,
    case-folded."""
    return " ".join(_LEADING_MARKERS.sub("", text).split()).casefold()


def _part_name(chain: str) -> str:
    _, title, part = chain.split(":")
    return f"{title} CFR {part}"


def _eligible(full: str, provs: list[Provision]) -> list[Provision]:
    sections: dict[str, set[str]] = {}
    for p in provs:
        sections.setdefault(normalised(p.text), set()).add(p.section)
    return [p for p in provs if p.modality is not None
            and len(" ".join(p.text.split())) >= MIN_CHARS
            and len(sections[normalised(p.text)]) == 1 and full[p.start:p.end] == p.text]


def _versions(store: Store) -> dict[str, list[tuple[str, list[Provision], list[Provision]]]]:
    """{part: [(doc id, its provisions, its eligible provisions)] oldest version first}."""
    out = {}
    for chain in PARTS:
        rows = []
        for d in chain_docs(store, chain):
            provs = provisions(store, d)
            rows.append((d, provs, _eligible(store.text(d), provs)))
        out[_part_name(chain)] = rows
    return out


def rule_universe(store: Store) -> dict[str, list[Provision]]:
    """{part: its eligible provisions (modal, at least `MIN_CHARS` characters, not
    boilerplate), every version, oldest version first, each in document order}."""
    return {part: [p for _, _, elig in rows for p in elig]
            for part, rows in _versions(store).items()}


def _overlay(store: Store) -> ap.Applicability:
    overlay = ap.load_overlay(store.path, store.snapshot_id)
    if overlay is None:
        raise GoldenError(f"{store.path}: no applicability overlay for snapshot "
                          f"{store.snapshot_id[:12]}: an older version's valid_from is unknown"
                          f"\nfix: derive it (`adr applicability derive --store {store.path}`)")
    return overlay


def _valid_from(overlay: ap.Applicability, doc_id: str) -> date:
    env = overlay.records.get(doc_id)
    if env is None or env.valid_from is None:
        raise GoldenError(f"{doc_id[:12]}: the applicability overlay gives no valid_from")
    return env.valid_from


def _rank(seed: int, doc_id: str, start: int, end: int) -> str:
    return hashlib.sha256(f"{seed}:{doc_id}:{start}:{end}".encode()).hexdigest()


def _rule_pools(store: Store, seed: int = SEED4) -> dict[str, dict]:
    """{part: {"versions": [(doc id, version label, eligible count)], "newest": [(provision,
    None)], "older": [(provision, as_of)]}}, each pool ranked by seed."""
    overlay = _overlay(store)
    out = {}
    for part, rows in _versions(store).items():
        if not rows:
            out[part] = {"versions": [], "newest": [], "older": []}
            continue
        newest_doc, newest_provs, newest_elig = rows[-1]
        newest_texts: dict[str, set[str]] = {}
        for p in newest_provs:
            newest_texts.setdefault(p.provision_id, set()).add(normalised(p.text))
        older, seen = [], set()
        for d, _, elig in reversed(rows[:-1]):          # the later older version first
            for p in elig:
                key = (p.provision_id, normalised(p.text))
                texts = newest_texts.get(p.provision_id)
                if texts is None or key[1] in texts or key in seen:
                    continue
                seen.add(key)
                older.append((p, _valid_from(overlay, d)))

        def ranked(pool: list) -> list:
            return sorted(pool, key=lambda x: _rank(seed, x[0].doc_id, x[0].start, x[0].end))

        out[part] = {
            "versions": [(d, store.source(d).source_version, len(elig)) for d, _, elig in rows],
            "newest": ranked([(p, None) for p in newest_elig]), "older": ranked(older)}
    return out


def older_count(n: int) -> int:
    """How many of a part's `n` draws come from older versions (`OLDER_SHARE`, half up)."""
    return math.floor(n * OLDER_SHARE + 0.5)


def _wants(n: int) -> tuple[tuple[str, int], tuple[str, int]]:
    k = older_count(n)
    return ("newest", n - k), ("older", k)


def draw_rules(store: Store, seed: int = SEED4) -> list[tuple[Provision, date | None]]:
    """The head of each pool, part by part in `RULE_COUNTS` order, newest before older: the
    provisions phrased first (a failed phrasing takes the next of its pool, `generate_rules`)."""
    pools = _rule_pools(store, seed)
    out = []
    for part, n in RULE_COUNTS.items():
        pool = pools.get(part, {"newest": [], "older": []})
        for stratum, want in _wants(n):
            out += pool[stratum][:want]
    return out


# -- closure (N23) -------------------------------------------------------------------------------


def _under(provision_id: str, target: str) -> bool:
    return provision_id == target or provision_id.startswith(target + "(")


def _closure(p: Provision, provs: list[Provision], full: str
             ) -> tuple[list[str], list[Evidence]]:
    """(the in-part cites targets of `p`, their spans in its document), as the module says."""
    sections = {q.section for q in provs}
    ids = {q.provision_id for q in provs}
    rules: list[str] = []
    evidence: list[Evidence] = []
    for x in cross_refs(p, sections, ids):
        target = x.target_ref
        if x.resolution != "resolved" or " CFR part " in target or target in rules:
            continue
        under = [q for q in provs if _under(q.provision_id, target)]
        if not under or all((q.start, q.end) == (p.start, p.end) for q in under):
            continue
        start, end = min(q.start for q in under), max(q.end for q in under)
        rules.append(target)
        evidence.append(Evidence(doc_id=p.doc_id, char_start=start, char_end=end,
                                 quote=full[start:end]))
    return rules, evidence


# -- phrasing ------------------------------------------------------------------------------------


def _phrase(client, system: str, user: str, leak: tuple[str, str, list[str]], row: dict,
            rejected: list[dict], calls: Counter) -> tuple[str, str] | None:
    """(question, model) of the first clean phrasing at repeat 0 or 1, else None; every failed
    try is appended to `rejected` as `row` with its repeat, reason and question."""
    for repeat in (0, 1):
        try:
            c = client.complete(system, user, max_tokens=MAX_TOKENS, repeat=repeat,
                                cache_failures=True)
        except CachedFailure:
            calls["failed"] += 1
            rejected.append({**row, "repeat": repeat, "reason": "input rejected",
                             "question": None})
            return None
        calls["cached" if c.cached else "made"] += 1
        try:
            question = _reply(c.text, ("question",), ("question",))["question"].strip()
        except ModelOutputError:
            question, reason = None, "malformed phrasing"
        else:
            reason = leak_reason(question, *leak)
        if reason is None:
            return question, c.model
        rejected.append({**row, "repeat": repeat, "reason": reason, "question": question})
    return None


def _created(store: Store, doc_ids) -> datetime:
    """The newest ISO date among the source versions of `doc_ids`, at 00:00 UTC (the epoch
    when none is a date)."""
    dates = []
    for d in doc_ids:
        try:
            dates.append(date.fromisoformat(store.source(d).source_version))
        except ValueError:
            continue
    if not dates:
        return EPOCH
    d = max(dates)
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _full(items: list, limit: int | None) -> bool:
    return limit is not None and len(items) >= limit


# -- rules ---------------------------------------------------------------------------------------


def generate_rules(store_path: Path, client, seed: int = SEED4, limit: int | None = None, *,
                   report: dict | None = None) -> tuple[list[RuleItem], list[dict]]:
    """(the gov-rules items of the store, the failed phrasings). `client` is a cached client (or
    a `MeteredClient` over one). `report`, when given, receives the universe and the draw
    before the first call (`universe`: per part, the eligible provisions per version and the
    older pool; `draw`: per part, newest and older) and, on return, `calls` (made, cached,
    failed) and `short` (per part and stratum, the draws the pools could not fill)."""
    store = Store.open(store_path)
    pools = _rule_pools(store, seed)
    plan = {part: {"versions": [(label, n) for _, label, n in pools[part]["versions"]],
                   "older": len(pools[part]["older"])} for part in pools}
    draw = {part: dict(_wants(n)) for part, n in RULE_COUNTS.items()}
    if report is not None:
        report.update(universe=plan, draw=draw)
    system, phash = load_prompt("rules"), prompt_hash("rules")
    created = _created(store, [rows["versions"][-1][0] for rows in pools.values()
                               if rows["versions"]])
    items: list[RuleItem] = []
    rejected: list[dict] = []
    short: dict[str, dict[str, int]] = {}
    calls = Counter(made=0, cached=0, failed=0)
    provs_of: dict[str, list[Provision]] = {}
    for part, n in RULE_COUNTS.items():
        pool = pools.get(part, {"newest": [], "older": []})
        for stratum, want in _wants(n):
            got = 0
            for p, as_of in pool[stratum]:
                if got >= want or _full(items, limit):
                    break
                row = {"corpus": "gov-rules", "source": p.provision_id, "doc_id": p.doc_id,
                       "as_of": None if as_of is None else as_of.isoformat()}
                phrased = _phrase(client, system, rule_message(p),
                                  (p.text, section_title(p.heading), [p.section]),
                                  row, rejected, calls)
                if phrased is None:
                    continue
                question, model = phrased
                full = store.text(p.doc_id)
                if p.doc_id not in provs_of:
                    provs_of[p.doc_id] = provisions(store, p.doc_id)
                closure_rules, closure_evidence = _closure(p, provs_of[p.doc_id], full)
                item_id = f"gov-rules-{len(items) + 1:03d}"
                items.append(RuleItem(
                    id=item_id, corpus="gov-rules", snapshot=store.snapshot_id, part=part,
                    question=question, as_of=as_of, gold_rules=[p.provision_id],
                    closure_rules=closure_rules, closure_evidence=closure_evidence,
                    evidence=[Evidence(doc_id=p.doc_id, char_start=p.start, char_end=p.end,
                                       quote=full[p.start:p.end])],
                    split=assign_split(item_id),
                    provenance=Provenance(model=model, prompt_hash=phash, seed=seed,
                                          created=created),
                    status="auto_verified"))
                got += 1
            if got < want and not _full(items, limit):
                short.setdefault(part, {})[stratum] = want - got
    if report is not None:
        report.update(calls=dict(calls), short=short)
    return items, rejected


# -- procedures ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Candidate:
    store: Store
    gold: str              # "IRM 21.4.1.3.1", or the bench doc id
    doc_id: str
    start: int
    end: int
    title: str
    numbers: tuple[str, ...]


def _doc_title(text: str) -> str:
    first = next((line for line in text.split("\n") if line.strip()), "")
    return first.strip().lstrip("#").strip()


def _candidates(store: Store) -> dict[str, list[_Candidate]]:
    """{set: the candidates of `store`}: the procedure-like located IRM sections and the drawn
    bench procedure documents."""
    gov = []
    for d in sorted(store.doc_ids()):
        if ap.family_of(store.source(d).uri) != "irm":
            continue
        secs, _ = irm_sections(store, d)
        gov += [_Candidate(store, f"IRM {s.number}", d, s.start, s.end, s.title, (s.number,))
                for s in secs if is_procedure_like(s)]
    bench = []
    for d in bench_candidates(store):
        text = store.text(d)
        bench.append(_Candidate(store, d, d, 0, len(text), _doc_title(text), ()))
    return {"gov-procedures": gov, "bench-procedures": bench}


def generate_procedures(store_paths: list[Path], client, seed: int = SEED4,
                        limit: int | None = None, *, report: dict | None = None
                        ) -> dict[str, tuple[list[ProcedureItem], list[dict]]]:
    """{set: (its items, its failed phrasings)} for gov-procedures (from the store holding IRM
    documents) and bench-procedures (from the store holding bench procedure documents);
    GoldenError when a set is found in no store or in more than one. `report`, when given,
    receives `universe` and `draw` (per set) before the first call and `calls` and `short`
    (per set) on return. `limit` caps each set."""
    found: dict[str, tuple[Path, list[_Candidate]]] = {}
    for path in store_paths:
        for corpus, cands in _candidates(Store.open(path)).items():
            if not cands:
                continue
            if corpus in found:
                raise GoldenError(f"{corpus}: candidates in more than one store ("
                                  f"{found[corpus][0]}, {path}); give one store per set")
            found[corpus] = (Path(path), cands)
    missing = [c for c in PROCEDURE_CORPORA if c not in found]
    if missing:
        raise GoldenError(f"no store holds candidates of {', '.join(missing)}: give the gov "
                          f"store (IRM sections) and the bench store (procedure documents)")
    pools = {c: sorted(found[c][1], key=lambda x: _rank(seed, x.doc_id, x.start, x.end))
             for c in PROCEDURE_CORPORA}
    if report is not None:
        report.update(universe={c: len(pools[c]) for c in PROCEDURE_CORPORA},
                      draw={c: min(N_PROCEDURES, len(pools[c])) for c in PROCEDURE_CORPORA},
                      stores={c: str(found[c][0]) for c in PROCEDURE_CORPORA})
    system, phash = load_prompt("procedures"), prompt_hash("procedures")
    calls = Counter(made=0, cached=0, failed=0)
    out: dict[str, tuple[list[ProcedureItem], list[dict]]] = {}
    short: dict[str, int] = {}
    for corpus in PROCEDURE_CORPORA:
        pool = pools[corpus]
        store = pool[0].store
        created = _created(store, sorted({x.doc_id for x in pool}))
        items: list[ProcedureItem] = []
        rejected: list[dict] = []
        for x in pool:
            if len(items) >= N_PROCEDURES or _full(items, limit):
                break
            text = store.text(x.doc_id)[x.start:x.end]
            row = {"corpus": corpus, "source": x.gold, "doc_id": x.doc_id}
            phrased = _phrase(client, system, procedure_message(corpus, x.title, text),
                              (text, x.title, list(x.numbers)), row, rejected, calls)
            if phrased is None:
                continue
            question, model = phrased
            item_id = f"{corpus}-{len(items) + 1:03d}"
            items.append(ProcedureItem(
                id=item_id, corpus=corpus, snapshot=store.snapshot_id, question=question,
                gold=x.gold, evidence=[Evidence(doc_id=x.doc_id, char_start=x.start,
                                                char_end=x.end, quote=text)],
                split=assign_split(item_id),
                provenance=Provenance(model=model, prompt_hash=phash, seed=seed,
                                      created=created),
                status="auto_verified"))
        if len(items) < N_PROCEDURES and not _full(items, limit):
            short[corpus] = N_PROCEDURES - len(items)
        out[corpus] = (items, rejected)
    if report is not None:
        report.update(calls=dict(calls), short=short)
    return out


# -- files ---------------------------------------------------------------------------------------


def _line(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False) + "\n"


def write_items(directory: Path, items: list[RuleItem] | list[ProcedureItem],
                rejected: list[dict]) -> None:
    """`items.jsonl` (sorted by id) and `rejected.jsonl` (in draw order) under `directory`."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "items.jsonl").write_text(
        "".join(_line(i.model_dump(mode="json")) for i in sorted(items, key=lambda i: i.id)),
        encoding="utf-8")
    (directory / "rejected.jsonl").write_text("".join(_line(r) for r in rejected),
                                              encoding="utf-8")


def load_rule_items(path: Path | None = None) -> list[RuleItem]:
    """The items of `path` (default `RULES_DIR / "items.jsonl"`, read when called)."""
    path = RULES_DIR / "items.jsonl" if path is None else Path(path)
    return [RuleItem.model_validate_json(line)
            for line in jsonl_lines(path.read_text(encoding="utf-8"))]


def procedures_dir(corpus: str) -> Path:
    """Where the items of a procedure set live (read when called)."""
    if corpus not in PROCEDURE_CORPORA:
        raise ValueError(f"{corpus!r} is not one of {', '.join(PROCEDURE_CORPORA)}")
    return GOV_PROCEDURES_DIR if corpus == "gov-procedures" else BENCH_PROCEDURES_DIR


def load_procedure_items(corpus: str) -> list[ProcedureItem]:
    """The items of `corpus` ("gov-procedures" or "bench-procedures")."""
    path = procedures_dir(corpus) / "items.jsonl"
    return [ProcedureItem.model_validate_json(line)
            for line in jsonl_lines(path.read_text(encoding="utf-8"))]
