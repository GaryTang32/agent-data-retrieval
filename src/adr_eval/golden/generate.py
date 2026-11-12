"""Golden-set generators: the LLM proposes, code locates, computes and verifies.

Determinism: every generator samples only through the `random.Random` it is given, from
candidates listed in sorted order (documents by `doc_id`, chunks by offset, record rows by
their canonical JSON, version pairs by URI and version). Model replies are cached by the
client, so a fixed seed regenerates byte-identical items.

Malformed model replies (invalid JSON, missing or ill-typed keys) raise `ModelOutputError`
(Review Focus 2) unless the generator is given an `errors` Counter: then the candidate is
skipped and `errors[qtype]` is incremented (Ruling R6), which `generate_corpus` uses so
one bad cached reply cannot abort a corpus run. Replies that are well formed but unusable
(a quote that is missing, ambiguous, fails the span check or, for overview and procedure,
lies outside its section; an absent term that does occur; equal answers across versions)
skip the candidate.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from functools import cache
from importlib import resources
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ValidationError

from adr_eval.corpora.base import CorpusAdapter, Document, LoadedCorpus
from adr_eval.golden.records import exec_gold_query, filter_records
from adr_eval.golden.verify import (
    assign_rarity,
    assign_split,
    check_spans,
    count_quote,
    dedup,
    find_quote,
    normalize_ws,
)
from adr_eval.golden.verify import exec_matches as _exec_matches
from adr_eval.golden.verify import pair_group as _group
from adr_eval.llm import ModelClient, ModelOutputError, parse_json
from adr_eval.models import (
    Answer,
    Checks,
    Evidence,
    GoldenItem,
    GoldQuery,
    Provenance,
    QType,
)
from adr_eval.retrieval.chunker import Chunk, chunk_document, tokenize

if TYPE_CHECKING:
    from adr_eval.scoring.judge import Judge

PROMPT_NAMES = ("extractive", "count_filter", "policy_asof", "insufficient", "evidence_only")
DEFAULT_SEED = 20261108
MIN_SECTION_TOKENS = 80
MAX_LIST_RESULTS = 25
# Count answers cite every matching record; above this the evidence is too large to cite
# or to re-answer from in the evidence-only check.
MAX_COUNT_MATCHES = 50
ATTEMPTS_PER_ITEM = 3  # model calls allowed per wanted item before reporting a shortfall
FILTER_DRAWS_PER_ITEM = 50  # code-only filter draws per wanted count_filter item
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

ExtractiveQType = Literal["factoid", "id_lookup", "procedure", "overview"]
EXTRACTIVE_OPS = {"factoid": "lookup", "id_lookup": "lookup", "procedure": "procedure",
                  "overview": "explain"}
# Their gold answer spans the generating section, so the section is the evidence (Ruling A).
SECTION_EVIDENCE_QTYPES = ("overview", "procedure")
NATIVE_OPS = {"factoid": "lookup", "overview": "explain", "insufficient": "abstain"}
MAX_TOKENS = {"extractive": 800, "count_filter": 300, "policy_asof": 800, "insufficient": 300,
              "evidence_only": 400}

Compare = Callable[[Answer, str | float | list[str] | None], bool]
log = logging.getLogger(__name__)


# -- prompts and provenance --------------------------------------------------------------


def _prompt_file(name: str):
    if name not in PROMPT_NAMES:
        raise ValueError(f"unknown prompt {name!r}")
    return resources.files("adr_eval.golden").joinpath(f"prompts/{name}.txt")


@cache
def load_prompt(name: str) -> str:
    return _prompt_file(name).read_text(encoding="utf-8")


def prompt_hash(name: str) -> str:
    return hashlib.sha256(_prompt_file(name).read_bytes()).hexdigest()


def _created(corpus: LoadedCorpus) -> datetime:
    """The manifest `version` date at 00:00 UTC; the epoch when the version is not a date."""
    try:
        d = date.fromisoformat(corpus.manifest.version)
    except ValueError:
        return EPOCH
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _provenance(corpus: LoadedCorpus, model: str, prompt: str, seed: int) -> Provenance:
    return Provenance(model=model, prompt_hash=prompt_hash(prompt), seed=seed,
                      created=_created(corpus))


def _item(corpus: LoadedCorpus, snapshot: str, **fields: Any) -> GoldenItem:
    return GoldenItem(
        corpus=corpus.manifest.corpus,
        snapshot=snapshot,
        as_of=fields.pop("as_of", None),
        rarity=None,
        split=None,
        checks=Checks(span_ok=True),
        status="auto_verified",
        **fields,
    )


def _norm(s: str) -> str:
    return normalize_ws(s).casefold()


# -- reply parsing -----------------------------------------------------------------------


def _reply(text: str, keys: tuple[str, ...], strings: tuple[str, ...]) -> dict:
    d = parse_json(text)
    missing = [k for k in keys if k not in d]
    if missing:
        raise ModelOutputError(f"reply is missing keys: {', '.join(missing)}")
    for k in strings:
        if not isinstance(d[k], str) or not d[k].strip():
            raise ModelOutputError(f"reply key {k!r} must be a non-empty string")
    return d


def _answer(kind: Any, value: Any, variants: Any) -> Answer:
    if kind not in ("text", "set", "number", "id"):
        raise ModelOutputError(f"answer_kind {kind!r} is not text, set, number or id")
    if not isinstance(variants, list) or not all(isinstance(v, str) for v in variants):
        raise ModelOutputError("accepted_variants must be a list of strings")
    if kind == "number":
        try:
            if isinstance(value, bool):
                raise TypeError
            value = float(value)
        except (TypeError, ValueError) as e:
            raise ModelOutputError(f"number answer {value!r} is not numeric") from e
    elif kind == "set":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ModelOutputError("set answer must be a list of strings")
    elif not isinstance(value, str) or not value.strip():
        raise ModelOutputError(f"{kind} answer must be a non-empty string")
    return Answer(kind=kind, value=value, accepted_variants=variants)


def _guarded(errors: Counter | None, qtype: str, parse: Callable[..., Any], *args: Any) -> Any:
    """`parse(*args)`, or None after counting a ModelOutputError in `errors[qtype]`.

    Without an `errors` Counter the ModelOutputError propagates."""
    try:
        return parse(*args)
    except ModelOutputError:
        if errors is None:
            raise
        errors[qtype] += 1
        return None


# -- sections and quotes -----------------------------------------------------------------


def _sections(corpus: LoadedCorpus) -> list[Chunk]:
    """Chunks of >= MIN_SECTION_TOKENS tokens from non-empty documents, in sorted order."""
    empty = set(corpus.empty_docs)
    out = []
    for doc_id in sorted(corpus.docs):
        if doc_id in empty:
            continue
        for ch in chunk_document(corpus.docs[doc_id]):
            if len(tokenize(ch.text, drop_stopwords=False)) >= MIN_SECTION_TOKENS:
                out.append(ch)
    return out


def _locate(doc: Document, quote: str) -> Evidence | None:
    """Evidence for a quote that occurs exactly once in `doc`; None if missing or ambiguous."""
    if count_quote(doc.text, quote) != 1:
        return None
    span = find_quote(doc.text, quote)
    if span is None:
        return None
    return Evidence(doc_id=doc.doc_id, char_start=span[0], char_end=span[1], quote=quote)


def _section_evidence(doc: Document, chunk: Chunk, quote_ev: Evidence) -> Evidence | None:
    """Evidence for the whole `chunk`, if the located quote lies within it and passes the
    span re-slice; None otherwise."""
    if not chunk.char_start <= quote_ev.char_start <= quote_ev.char_end <= chunk.char_end:
        return None
    if normalize_ws(doc.text[quote_ev.char_start:quote_ev.char_end]) \
            != normalize_ws(quote_ev.quote):
        return None
    return Evidence(doc_id=chunk.doc_id, char_start=chunk.char_start, char_end=chunk.char_end,
                    quote=doc.text[chunk.char_start:chunk.char_end])


# -- extractive: factoid, id_lookup, procedure, overview ---------------------------------

_EXTRACTIVE_KEYS = ("question", "answer_kind", "answer", "accepted_variants", "quote",
                    "key_entity", "gold_query")


def _numbered(value: Any) -> Any:
    """A list of step strings as numbered lines ("1. first\n2. second"); other values as-is."""
    if not isinstance(value, list):
        return value
    if not all(isinstance(step, str) for step in value):
        raise ModelOutputError("procedure steps must be strings")
    return "\n".join(f"{i}. {step.strip()}" for i, step in enumerate(value, 1))


def _procedure_answer(value: Any, variants: Any) -> Answer:
    """Procedure answers are ordered `text` whatever `answer_kind` says (Ruling B): a list
    of steps, as the answer or as one accepted variant, becomes numbered lines."""
    if isinstance(variants, list):
        variants = [_numbered(v) for v in variants]
    return _answer("text", _numbered(value), variants)


def _parse_extractive(text: str, qtype: str) -> tuple[dict, Answer, GoldQuery]:
    d = _reply(text, _EXTRACTIVE_KEYS, ("question", "quote", "key_entity"))
    if qtype == "procedure":
        answer = _procedure_answer(d["answer"], d["accepted_variants"])
    else:
        answer = _answer(d["answer_kind"], d["answer"], d["accepted_variants"])
    gq = d["gold_query"]
    if not isinstance(gq, dict):
        raise ModelOutputError("gold_query must be an object")
    key = d["key_entity"].strip()
    others = gq.get("entities") or []
    try:
        gold_query = GoldQuery(
            store=gq.get("store", "knowledge"),
            op=EXTRACTIVE_OPS[qtype],
            filters=gq.get("filters") or {},
            entities=[key, *[e for e in others if e != key]],
        )
    except ValidationError as e:
        raise ModelOutputError(f"invalid gold_query: {e}") from e
    return d, answer, gold_query


def gen_extractive(
    qtype: ExtractiveQType,
    corpus: LoadedCorpus,
    client: ModelClient,
    n: int,
    rng: random.Random,
    *,
    seed: int = 0,
    errors: Counter | None = None,
) -> list[GoldenItem]:
    """Up to `n` items, each from a uniformly sampled section.

    A candidate is skipped when its quote is not found in the section's document, occurs
    more than once there (ambiguous span), or its located span fails `check_spans`.
    `factoid` and `id_lookup` items cite the quote. `overview` and `procedure` answers span
    the whole section, so those items cite the whole generating section instead; their
    quote must still pass the checks above and also lie within the section. `procedure`
    answers are `text`, a list of steps becoming numbered lines (see `_procedure_answer`).
    `seed` is recorded in provenance only; sampling uses `rng`.
    """
    if qtype not in EXTRACTIVE_OPS:
        raise ValueError(f"not an extractive qtype: {qtype!r}")
    system = load_prompt("extractive")
    snapshot = corpus.manifest.snapshot()
    sections = _sections(corpus)
    items: list[GoldenItem] = []
    for chunk in rng.sample(sections, len(sections))[: ATTEMPTS_PER_ITEM * n]:
        if len(items) >= n:
            break
        user = f"Question type: {qtype}\n\nSection:\n{chunk.text}"
        c = client.complete(system, user, max_tokens=MAX_TOKENS["extractive"])
        parsed = _guarded(errors, qtype, _parse_extractive, c.text, qtype)
        if parsed is None:
            continue
        d, answer, gold_query = parsed
        doc = corpus.docs[chunk.doc_id]
        ev = _locate(doc, d["quote"])
        if ev is None:
            continue
        if qtype in SECTION_EVIDENCE_QTYPES:
            ev = _section_evidence(doc, chunk, ev)
            if ev is None:
                continue
        item = _item(
            corpus, snapshot,
            id=f"{corpus.manifest.corpus}-{qtype}-{len(items) + 1:03d}",
            qtype=qtype,
            question=d["question"].strip(),
            answer=answer,
            evidence=[ev],
            gold_query=gold_query,
            provenance=_provenance(corpus, c.model, "extractive", seed),
        )
        if check_spans(item, corpus.docs):
            items.append(item)
    return items


# -- count_filter ------------------------------------------------------------------------


def _row_key(row: dict) -> str:
    return json.dumps(row, sort_keys=True, default=str)


def _filter_fields(rows: list[dict]) -> list[tuple[str, str]]:
    """(field, kind) pairs usable in filters: ints, lists of strings, and strings whose
    distinct values are at most half their non-empty values (categorical, not free text or
    ids). Never `id`."""
    names = sorted({k for r in rows for k in r if not k.startswith("_") and k != "id"})
    out = []
    for f in names:
        values = [r.get(f) for r in rows if r.get(f) not in (None, "", [])]
        if not values:
            continue
        if all(isinstance(v, int) and not isinstance(v, bool) for v in values):
            out.append((f, "int"))
        elif all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in values):
            out.append((f, "list"))
        elif all(isinstance(v, str) for v in values) and len(set(values)) <= len(values) / 2:
            out.append((f, "str"))
    return out


def _draw_filter(
    rows: list[dict], fields: list[tuple[str, str]], rng: random.Random
) -> tuple[dict, str] | None:
    """1-2 clauses with values taken from one sampled row, and an op; None if unusable."""
    k = 1 if len(fields) == 1 else rng.choice([1, 2])
    chosen = sorted(rng.sample(fields, k))
    row = rng.choice(rows)
    filters: dict = {}
    for field, kind in chosen:
        v = row.get(field)
        if v in (None, "", []):
            return None
        if kind == "int":
            filters[field + rng.choice(["", "__gte", "__lte"])] = v
        elif kind == "list":
            filters[f"{field}__contains"] = rng.choice(sorted(v))
        else:
            filters[field] = v
    return dict(sorted(filters.items())), rng.choice(["count", "list"])


def _row_evidence(rows: list[dict], corpus: LoadedCorpus) -> list[Evidence] | None:
    """One Evidence per distinct source span: the row's `_span`, else its whole document."""
    spans = set()
    for r in rows:
        doc = corpus.docs.get(r.get("_doc_id"))
        if doc is None:
            return None
        s, e = r.get("_span") or (0, len(doc.text))
        spans.add((doc.doc_id, int(s), int(e)))
    return [Evidence(doc_id=d, char_start=s, char_end=e, quote=corpus.docs[d].text[s:e])
            for d, s, e in sorted(spans)]


def gen_count_filter(
    corpus: LoadedCorpus,
    adapter: CorpusAdapter,
    client: ModelClient,
    n: int,
    rng: random.Random,
    *,
    seed: int = 0,
    errors: Counter | None = None,
) -> list[GoldenItem]:
    """Up to `n` count/list items whose answers are computed by `exec_gold_query`.

    Record ids are not guaranteed unique (bench and research repeat some), so `list`
    answers are the sorted unique ids, and `count` filters are kept only when the matching
    rows have unique ids (a count over repeated ids is ambiguous); other draws are skipped
    and redrawn. `list` is used only for at most MAX_LIST_RESULTS ids and `count` for at
    most MAX_COUNT_MATCHES rows. The model only phrases the question.
    """
    system = load_prompt("count_filter")
    snapshot = corpus.manifest.snapshot()
    rows = sorted(adapter.records(corpus), key=_row_key)
    fields = _filter_fields(rows)
    schema = "\n".join(f"- {k}: {v}" for k, v in adapter.record_schema().items())
    items: list[GoldenItem] = []
    seen: set[str] = set()
    for _ in range(FILTER_DRAWS_PER_ITEM * n if rows and fields else 0):
        if len(items) >= n:
            break
        drawn = _draw_filter(rows, fields, rng)
        if drawn is None:
            continue
        filters, op = drawn
        key = json.dumps([op, filters], sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        matches = filter_records(rows, filters)
        ids = [str(r["id"]) for r in matches]
        if not ids:
            continue
        if op == "list" and len(set(ids)) > MAX_LIST_RESULTS:
            continue
        if op == "count" and (len(set(ids)) != len(ids) or len(ids) > MAX_COUNT_MATCHES):
            continue
        evidence = _row_evidence(matches, corpus)
        if evidence is None:
            continue
        first = filters[min(filters)]
        gold_query = GoldQuery(store="typed_db", op=op, filters=filters, entities=[str(first)])
        value = exec_gold_query(gold_query, rows)
        answer = (Answer(kind="number", value=float(value)) if op == "count"
                  else Answer(kind="set", value=value))
        user = (f"Record schema:\n{schema}\n\nOperation: {op}\n"
                f"Filters: {json.dumps(filters, sort_keys=True, ensure_ascii=False)}")
        c = client.complete(system, user, max_tokens=MAX_TOKENS["count_filter"])
        d = _guarded(errors, "count_filter", _reply, c.text, ("question",), ("question",))
        if d is None:
            continue
        item = _item(
            corpus, snapshot,
            id=f"{corpus.manifest.corpus}-count_filter-{len(items) + 1:03d}",
            qtype="count_filter",
            question=d["question"].strip(),
            answer=answer,
            evidence=evidence,
            gold_query=gold_query,
            provenance=_provenance(corpus, c.model, "count_filter", seed),
        )
        if check_spans(item, corpus.docs):
            items.append(item)
    return items


# -- policy_asof -------------------------------------------------------------------------

_POLICY_KEYS = ("question", "answer_old", "quote_old", "answer_new", "quote_new")


def _locate_in_version(
    corpus: LoadedCorpus, section: Document, other: Document, quote: str
) -> Evidence | None:
    """The quote's span in the full document of `section`, if it occurs exactly once in
    `section` and not at all in `other`. Section texts are substrings of their document."""
    if count_quote(section.text, quote) != 1 or find_quote(other.text, quote) is not None:
        return None
    span = find_quote(section.text, quote)
    full = corpus.docs.get(section.doc_id)
    if span is None or full is None:
        return None
    offset = full.text.find(section.text)
    if offset < 0:
        return None
    return Evidence(doc_id=section.doc_id, char_start=offset + span[0],
                    char_end=offset + span[1], quote=quote)


def _heading(text: str) -> str:
    return next((ln.strip() for ln in text.splitlines() if ln.strip()), "")[:80]


def gen_policy_asof(
    corpus: LoadedCorpus,
    adapter: CorpusAdapter,
    client: ModelClient,
    n: int,
    rng: random.Random,
    *,
    seed: int = 0,
    errors: Counter | None = None,
) -> list[GoldenItem]:
    """Up to `n` items, in pairs: `<stem>-a` (older version) and `<stem>-b` (newer).

    Each pair comes from one `version_pairs` entry; `as_of` is each version's
    `source_version` date. Both quotes must occur once in their own version and not in the
    other, and the two answers must differ after normalization. The key entity (for
    rarity) is the section's first line, since the reply has no key_entity.
    """
    system = load_prompt("policy_asof")
    snapshot = corpus.manifest.snapshot()
    pairs = sorted(adapter.version_pairs(corpus),
                   key=lambda p: (p[0].uri, p[0].source_version, p[1].uri, p[1].source_version))
    items: list[GoldenItem] = []
    for old, new in rng.sample(pairs, len(pairs))[: ATTEMPTS_PER_ITEM * max(1, n // 2)]:
        if len(items) + 2 > n:
            break
        try:
            dates = date.fromisoformat(old.source_version), date.fromisoformat(new.source_version)
        except ValueError:
            continue
        user = (f"Older version ({old.source_version}):\n{old.text}\n\n"
                f"Newer version ({new.source_version}):\n{new.text}")
        c = client.complete(system, user, max_tokens=MAX_TOKENS["policy_asof"])
        d = _guarded(errors, "policy_asof", _reply, c.text, _POLICY_KEYS, _POLICY_KEYS)
        if d is None:
            continue
        if _norm(d["answer_old"]) == _norm(d["answer_new"]):
            continue
        ev_old = _locate_in_version(corpus, old, new, d["quote_old"])
        ev_new = _locate_in_version(corpus, new, old, d["quote_new"])
        if ev_old is None or ev_new is None:
            continue
        stem = f"{corpus.manifest.corpus}-policy_asof-{len(items) // 2 + 1:03d}"
        pair = [
            _item(
                corpus, snapshot,
                id=f"{stem}-{suffix}",
                qtype="policy_asof",
                question=d["question"].strip(),
                as_of=as_of,
                answer=Answer(kind="text", value=d[f"answer_{which}"].strip()),
                evidence=[ev],
                gold_query=GoldQuery(store="knowledge", op="lookup",
                                     entities=[_heading(old.text)], as_of=as_of),
                provenance=_provenance(corpus, c.model, "policy_asof", seed),
            )
            for suffix, which, as_of, ev in (("a", "old", dates[0], ev_old),
                                             ("b", "new", dates[1], ev_new))
        ]
        if all(check_spans(i, corpus.docs) for i in pair):
            items.extend(pair)
    return items


# -- insufficient ------------------------------------------------------------------------


class DocFrequency:
    """`verify.doc_frequency` with every document tokenized once, for repeated lookups."""

    def __init__(self, docs: dict[str, Document]):
        self._toks = [tokenize(d.text, drop_stopwords=False) for d in docs.values()]
        self._sets = [set(t) for t in self._toks]

    def __call__(self, term: str) -> int:
        needle = tokenize(term, drop_stopwords=False)
        if not needle:
            return 0
        n, need = len(needle), set(needle)
        count = 0
        for toks, present in zip(self._toks, self._sets, strict=True):
            if need <= present and any(
                toks[i : i + n] == needle for i in range(len(toks) - n + 1)
            ):
                count += 1
        return count


def gen_insufficient(
    corpus: LoadedCorpus,
    client: ModelClient,
    n: int,
    rng: random.Random,
    *,
    seed: int = 0,
    errors: Counter | None = None,
) -> list[GoldenItem]:
    """Up to `n` abstain items about a term with document frequency 0 in the corpus."""
    system = load_prompt("insufficient")
    snapshot = corpus.manifest.snapshot()
    sections = _sections(corpus)
    df = DocFrequency(corpus.docs)
    items: list[GoldenItem] = []
    for chunk in rng.sample(sections, len(sections))[: ATTEMPTS_PER_ITEM * n]:
        if len(items) >= n:
            break
        c = client.complete(system, f"Section:\n{chunk.text}",
                            max_tokens=MAX_TOKENS["insufficient"])
        d = _guarded(errors, "insufficient", _reply, c.text, ("question", "absent_term"),
                     ("question", "absent_term"))
        if d is None:
            continue
        term = d["absent_term"].strip()
        if not tokenize(term, drop_stopwords=False) or df(term) != 0:
            continue
        items.append(
            _item(
                corpus, snapshot,
                id=f"{corpus.manifest.corpus}-insufficient-{len(items) + 1:03d}",
                qtype="insufficient",
                question=d["question"].strip(),
                answer=Answer(kind="abstain", value=None),
                evidence=[],
                gold_query=GoldQuery(store="raw", op="abstain", entities=[term]),
                provenance=_provenance(corpus, c.model, "insufficient", seed),
            )
        )
    return items


# -- evidence-only check -----------------------------------------------------------------


def _coerce(kind: str, value: Any) -> str | float | list[str] | None:
    if kind == "number" and isinstance(value, str):
        try:
            return float(value.strip().replace(",", ""))
        except ValueError:
            return value
    if kind == "number" and isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if kind == "set":
        return [str(v) for v in value] if isinstance(value, list) else [str(value)]
    if isinstance(value, list):
        return [str(v) for v in value]
    return value if isinstance(value, str | float) else str(value)


def _exact_compare() -> Compare:
    from types import SimpleNamespace

    from adr_eval.scoring.exact import exact_outcome  # Task 10; imported lazily (Ruling R1)

    def compare(gold: Answer, value: str | float | list[str] | None) -> bool:
        pred = SimpleNamespace(value=value, kind=gold.kind, citations=[], abstain=False,
                               confidence=1.0, completion=None)
        return exact_outcome(gold, pred) == "correct"

    return compare


def evidence_only_check(
    item: GoldenItem,
    corpus: LoadedCorpus,
    client: ModelClient,
    compare: Compare | None = None,
    judge: Judge | None = None,
) -> bool:
    """Re-answer the question from the cited evidence text alone and compare.

    `text` answers pass when the gold value or an accepted variant, normalized
    (whitespace, NFKC, case), is contained in the reply; otherwise, if a `judge` is given,
    they pass only when `judge.judge(question, gold, reply)` labels the reply "correct"
    ("partial" and "incorrect" fail; an invalid label raises ModelOutputError). Without a
    judge, containment alone decides. Other kinds use `compare(gold, value)`, by default
    `scoring.exact.exact_outcome(...) == "correct"`, and never call the judge. Items
    without evidence (abstain) cannot be checked and raise ValueError.
    """
    if item.answer.kind == "abstain" or not item.evidence:
        raise ValueError(f"{item.id}: evidence-only check needs an answerable item with evidence")
    passages = "\n\n".join(
        f"[{k}]\n{corpus.docs[ev.doc_id].text[ev.char_start:ev.char_end]}"
        for k, ev in enumerate(item.evidence, 1)
    )
    as_of = f"As of: {item.as_of.isoformat()}\n" if item.as_of else ""
    user = f"Question: {item.question}\n{as_of}\nEvidence:\n{passages}"
    c = client.complete(load_prompt("evidence_only"), user,
                        max_tokens=MAX_TOKENS["evidence_only"])
    d = _reply(c.text, ("answer",), ())
    pred = d["answer"]
    if pred is None:
        return False
    if item.answer.kind == "text":
        got = _norm(" ".join(map(str, pred)) if isinstance(pred, list) else str(pred))
        golds = [str(item.answer.value), *item.answer.accepted_variants]
        if any(_norm(g) and _norm(g) in got for g in golds):
            return True
        if judge is None:
            return False
        label, _, _ = judge.judge(item.question, item.answer, pred)
        return label == "correct"
    return bool((compare or _exact_compare())(item.answer, _coerce(item.answer.kind, pred)))


# -- benchmark-native items --------------------------------------------------------------


def native_to_items(natives: list[dict], corpus: LoadedCorpus, seed: int) -> list[GoldenItem]:
    """Benchmark questions (`bench.native_items()`) as items with `provenance.model="native"`.

    The benchmark gives gold documents, not spans, so evidence is each distinct gold
    document's whole text. Ids are `<corpus>-<qtype>-<question_id>`; `qtype` is the mapping
    from corpora/bench/README.md, already applied by `native_items`.
    """
    snapshot = corpus.manifest.snapshot()
    prov = Provenance(model="native", prompt_hash="native", seed=seed, created=_created(corpus))
    items = []
    for q in natives:
        qtype: QType = q["qtype"]
        if qtype == "insufficient":
            answer, evidence = Answer(kind="abstain", value=None), []
            gold_query = GoldQuery(store="raw", op="abstain")
        else:
            doc_ids = sorted(set(q["manifest_doc_ids"]))
            if not doc_ids or any(d not in corpus.docs for d in doc_ids):
                continue
            answer = Answer(kind="text", value=q["gold_answer"])
            evidence = [Evidence(doc_id=d, char_start=0, char_end=len(corpus.docs[d].text),
                                 quote=corpus.docs[d].text) for d in doc_ids]
            gold_query = GoldQuery(store="knowledge", op=NATIVE_OPS[qtype])
        items.append(_item(
            corpus, snapshot,
            id=f"{corpus.manifest.corpus}-{qtype}-{q['question_id']}",
            qtype=qtype,
            question=q["question"],
            answer=answer,
            evidence=evidence,
            gold_query=gold_query,
            provenance=prov,
        ))
    return items


# -- whole-corpus generation -------------------------------------------------------------


def _load(corpus_name: str) -> tuple[LoadedCorpus, CorpusAdapter]:
    from adr_eval.corpora.base import load_corpus
    from adr_eval.corpora.registry import corpus_root, get_adapter, manifest_path

    return load_corpus(manifest_path(corpus_name), corpus_root(corpus_name)), \
        get_adapter(corpus_name)


def generate_corpus(
    corpus_name: str,
    client: ModelClient,
    per_type: int = 50,
    seed: int = DEFAULT_SEED,
    compare: Compare | None = None,
    judge: Judge | None = None,
    exclusions: Mapping[str, str] | None = None,
) -> tuple[list[GoldenItem], list[GoldenItem]]:
    """Generate, check and split a corpus's golden set; returns (accepted, rejected).

    Generators run in a fixed order on one `random.Random(seed)`. Checks, in order: dedup
    (pair-aware: a policy pair is kept or dropped as one), `gold_query` execution for
    `typed_db` items (also `recompute_ok` for count_filter), and the evidence-only check
    for answerable, generated items (benchmark-native answers are free text written by the
    benchmark and are not re-checked); `judge`, if given, decides `text` answers whose
    re-answer does not contain the gold (see `evidence_only_check`). A malformed
    evidence-only or judge reply rejects the item with reason `evidence_only_output`;
    malformed generator replies skip their candidate and are tallied per qtype. One INFO
    line per qtype is logged to `adr_eval.golden.generate` with requested, accepted,
    rejected and generation_errors counts. If one half of a policy pair is rejected, so is
    the other (`pair_rejected`). Accepted items get `split` from `assign_split` and `rarity`
    from `assign_rarity` over the document frequency of `gold_query.entities[0]`; abstain
    items and items without a key entity keep `rarity = None`. Last, `exclusions` (item id
    -> reason, from review) move those accepted items, with their policy pair partner, to
    rejected (`review_excluded`), leaving every other item unchanged.
    """
    corpus, adapter = _load(corpus_name)
    rng = random.Random(seed)
    errors: Counter = Counter()
    items: list[GoldenItem] = []
    for qtype in ("factoid", "id_lookup", "procedure", "overview"):
        items += gen_extractive(qtype, corpus, client, per_type, rng, seed=seed, errors=errors)
    items += gen_count_filter(corpus, adapter, client, per_type, rng, seed=seed, errors=errors)
    items += gen_policy_asof(corpus, adapter, client, per_type, rng, seed=seed, errors=errors)
    items += gen_insufficient(corpus, client, per_type, rng, seed=seed, errors=errors)
    if corpus_name == "bench":
        from adr_eval.corpora.bench import native_items

        items += native_to_items(native_items(corpus.root), corpus, seed)

    items.sort(key=lambda i: i.id)
    checks = {i.id: i.checks.model_dump() for i in items}
    reasons: dict[str, str] = {}

    groups: dict[str, list[GoldenItem]] = {}
    for i in items:
        groups.setdefault(_group(i), []).append(i)
    _, dropped = dedup([g[0] for g in groups.values()])
    dropped_groups = {_group(i) for i in dropped}
    for i in items:
        checks[i.id]["dedup_ok"] = _group(i) not in dropped_groups
        if not checks[i.id]["dedup_ok"]:
            reasons[i.id] = "dedup"

    records = adapter.records(corpus)
    for i in items:
        if i.id in reasons:
            continue
        if i.gold_query.store == "typed_db":
            ok = _exec_matches(exec_gold_query(i.gold_query, records), i.answer)
            checks[i.id]["gold_query_exec_ok"] = ok
            if i.qtype == "count_filter":
                checks[i.id]["recompute_ok"] = ok
            if not ok:
                reasons[i.id] = "gold_query_exec"
                continue
        if i.answer.kind != "abstain" and i.provenance.model != "native":
            try:
                ok = evidence_only_check(i, corpus, client, compare, judge)
                reason = "evidence_only"
            except ModelOutputError:
                ok, reason = False, "evidence_only_output"
            checks[i.id]["evidence_only_ok"] = ok
            if not ok:
                reasons[i.id] = reason

    for i in items:
        if i.id not in reasons and any(j.id in reasons for j in groups[_group(i)]):
            reasons[i.id] = "pair_rejected"

    accepted, rejected = [], []
    for i in items:
        c = Checks(**checks[i.id])
        if i.id in reasons:
            rejected.append(i.model_copy(update={"checks": c, "status": "rejected",
                                                 "reject_reason": reasons[i.id]}))
        else:
            accepted.append(i.model_copy(update={"checks": c,
                                                 "split": assign_split(i.id, seed)}))

    rated = [i for i in accepted if i.answer.kind != "abstain" and i.gold_query.entities]
    if rated:
        df = DocFrequency(corpus.docs)
        dfs = {i.id: df(i.gold_query.entities[0]) for i in rated}
        by_id = {i.id: i for i in assign_rarity(rated, dfs)}
        accepted = [by_id.get(i.id, i) for i in accepted]
    accepted, rejected = apply_review_exclusions(accepted, rejected, exclusions or {})
    _log_tally(corpus_name, per_type, accepted, rejected, errors)
    return accepted, rejected


def apply_review_exclusions(
    accepted: list[GoldenItem], rejected: list[GoldenItem], exclusions: Mapping[str, str]
) -> tuple[list[GoldenItem], list[GoldenItem]]:
    """Move excluded accepted items (and their policy pair partner) to rejected, as
    `review_excluded` with no split or rarity; other items are untouched. Both lists stay in
    id order."""
    groups = {_group(i) for i in accepted if i.id in exclusions}
    unknown = sorted(set(exclusions) - {i.id for i in accepted})
    if unknown:
        log.warning("review exclusions not among accepted items: %s", ", ".join(unknown))
    if not groups:
        return accepted, rejected
    moved = [i.model_copy(update={"status": "rejected", "reject_reason": "review_excluded",
                                  "split": None, "rarity": None})
             for i in accepted if _group(i) in groups]
    kept = [i for i in accepted if _group(i) not in groups]
    return kept, sorted([*rejected, *moved], key=lambda i: i.id)


GENERATED_QTYPES = ("factoid", "id_lookup", "procedure", "overview", "count_filter",
                    "policy_asof", "insufficient")


def _log_tally(corpus_name: str, per_type: int, accepted: list[GoldenItem],
               rejected: list[GoldenItem], errors: Counter) -> None:
    """One INFO line per generated qtype, so shortfalls and malformed replies are visible.

    Counts cover generated items only (benchmark-native items are not requested)."""
    def count(items: list[GoldenItem], qtype: str) -> int:
        return sum(i.qtype == qtype and i.provenance.model != "native" for i in items)

    for qtype in GENERATED_QTYPES:
        log.info("%s %s: requested=%d accepted=%d rejected=%d generation_errors=%d",
                 corpus_name, qtype, per_type, count(accepted, qtype), count(rejected, qtype),
                 errors[qtype])
