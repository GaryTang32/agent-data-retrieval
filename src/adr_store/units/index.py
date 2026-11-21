"""The unit index: BM25F and dense retrieval over the knowledge units of one build, per caller
view (Phase 4 spec §11.1, P25; preflight rulings C8, C13, N24).

It is separate from the Phase 1 chunk index, which it never reads or writes: Phase 2 `search`
is unchanged.

**Documents.** `unit_docs` makes one `UnitDoc` per unit, sorted by unit id, with five fields
(`FIELDS`):
- `title`: the unit's title, then its heading path (deduplicated, in order);
- `ref`: the canonical ref, then the provision id of a rule card or the Phase 3 table of a
  table record;
- `labels`: one label per line. A concept holds its preferred label, then its alternate
  labels. A rule card holds the labels of the concepts it defines (`defined_terms`, which
  Task 3 linked by scope and mention). A procedure holds the labels of the concepts of its own
  document whose scope contains it and whose hidden label it mentions (§7 "Concepts in
  retrieval"). Each holds its envelope `aids.labels` too.
- `body`, which differs by type:
  - concept: the definition and scope note;
  - rule card: the rule text, then its closure headings. A heading is the deepest heading of a
    closure target other than its own title, or the entry's ref for a non-modal provision.
    `defines` targets are left out, because their labels are in `labels`.
  - procedure: `when_to_use`, inputs, preconditions, the step texts, escalation and success
    criteria. `not_for` is left out, so a query about what a procedure is not for does not
    find it.
  - FAQ: the question and answer, or the KCS fields;
  - table record: the caption, headers and description.
- `aids`: one aid per line, index only (§5.1, §11.1). These are the envelope's keywords,
  problem abstractions and trigger examples, then a procedure's model-written problem
  abstractions and trigger examples. `UnitDoc.aids` holds the same texts. No other field and
  no dense text contains them, and a search returns unit ids only.

`dense_text` is the heading path joined by " > ", a newline, and the body field.

**Lexical (BM25F as field repetition, builder note 10).** A unit's indexed text is each field
repeated by its type's weight from the tuning (`indexed_text`). It is indexed by the
baseline's `BM25Index` (the same tokenizer, `k1` and `b` as `FieldBM25`, which does the same
for the Phase 1 breadcrumb). Statistics come from the units of the view alone. There is one
index per (index fingerprint, view id) in an LRU of `VIEW_CACHE`, as `Tools._view_lexical`
keeps them, so a hidden unit moves no score.

**View and filters (Phase 2 §6.1, §6.2).** `search(query, *, types, view, admitted=None, k)`
takes two document sets:
- `view` is the caller's ACL-visible documents. It alone chooses the BM25 statistics, the LRU
  key and the label map. The key uses the documents of `view` that hold units of the index;
  the full index serves `view=None` and any view that holds every document.
- `admitted` is what the applicability filters admit, and None means the whole view. With
  `types`, it masks both channels to `view ∩ admitted` before any cut, as
  `StoreIndex.retrieve(allowed_docs=…)` does with Phase 2's per-view BM25. A filter therefore
  changes no statistic and never starves the result, and two filters in one view share one
  BM25 index.

**Concept expansion (BM25 only).** The lexical query gains, after the caller's words, the
other labels of every view concept label it contains as whole words (`expand_query`). A label
matches under its own key or the key of any of its hidden labels (`concepts.hidden_labels`),
so "RNAs" expands as "RNA" does. The label map is built from the view's concepts only, so a
hidden concept expands nothing.

**Dense.** Each unit's `dense_text` gets one vector, and each aid gets one vector more. These
come from the `EmbeddingCache` once, over every unit, and are stored under
`<store>/units-index/<units id>/dense-<model hash[:16]>/`:
- `index.json`: format, units id, `lexical_only`, embedding, counts and SHA-256 of the docs
  and of the vectors;
- `rows.jsonl`: one row per vector, giving its unit id and aid index;
- `vectors.npy`.

A unit's dense score is its best cosine over its own row and its aid rows (`row_scores`, a
function of the row and the query alone). Scoring masks the rows to `view ∩ admitted` and
`types`. A
later build with the same docs and model reuses the stored vectors and computes no
embedding.

**Lexical-only (C8).** `emb=None` builds no vector and embeds no query, so it never loads the
embedding model. It records `lexical_only` in `<store>/units-index/<units id>/lexical/
index.json`, and `search` is BM25's ranking: every unit with a positive score. The MCP and
environment subprocesses, fixture stores and tests use it.

**Fusion and order (spec P41).** With vectors, `fuse` scores every unit the masks keep as
`w * l + (1 - w) * d`.
- `l` is the BM25 score divided by the best BM25 score of the masked pool. A unit with no BM25
  score gets 0, so the lowest or only lexical hit stays above every non-match.
- `d` is the dense score min-max scaled over the whole masked pool.

The scaling covers the complete pools, so there is no separate head and tail: a deeper cut
never reorders the top. At `w = 1.0` the order is the lexical-only order, followed by the
non-matching units at 0. Phase 1's `fusion.linear` and `retrieval.index._full_ranking`, which
scale min-max over each channel's top `CHANNEL_K` and so give the lowest BM25 hit 0, are left
untouched (constraint 2).

Every ranking is sorted by (score descending, unit id). `search(k=…)` cuts it at `k`. A caller
that fills a token budget (P20, builder note 11) can ask for as many hits as it needs. The
index returns ids and scores, never text.

**Tuning (C13).** `config/units/tuning.json` is keyed by corpus:
`{corpus: {"weights": {type: {field: weight}}, "w": float}}`. Weights come from `WEIGHT_GRID`
and `w` from `W_GRID`. The defaults set every weight to 1 and `w` to 1.0, and Task 13 tunes
them on dev (`adr_eval.phase4.tune`, written by `write_tuning`).

**Pinned tuning (P42).** A handle names the tuning entry it ran on by its SHA-256 (handle part
`unit_index`, `tuning_id`); the entry is pinned, write-once, at
`<store>/units-index/<units id>/tuning-<unit_index>.json` (`pin_tuning`, `pinned_tuning`).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import threading
import unicodedata
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from adr_eval.retrieval.chunker import Chunk
from adr_eval.retrieval.dense import _unit
from adr_eval.retrieval.lexical import BM25Index
from adr_store import acl
from adr_store.chunking import BREADCRUMB_SEP
from adr_store.embedding import EmbeddingCache
from adr_store.retrieval.dense import row_scores
from adr_store.retrieval.lexical import masked_hits
from adr_store.units.build import CORPUS_TYPES
from adr_store.units.concepts import _Labels, _subpart_of, hidden_labels, scope_contains
from adr_store.units.contracts import UNIT_CONTRACT_DIR, UNIT_TYPES
from adr_store.units.envelope import Unit

FIELDS = ("title", "ref", "labels", "body", "aids")
WEIGHT_GRID = (1, 2, 3)
W_GRID = tuple(round(0.50 + 0.05 * i, 2) for i in range(11))
INDEX_DIR = "units-index"
VIEW_CACHE = 16
FORMAT_VERSION = "0.1"
TUNING_PATH = UNIT_CONTRACT_DIR / "tuning.json"
TUNING_ENV = "ADR_UNITS_TUNING"  # overrides TUNING_PATH (tests; `adr mcp` inherits it)

Hits = list[tuple[str, float]]

_VIEW_LOCK = threading.Lock()
_VIEW_LEXICAL: OrderedDict[tuple[str, str], _ViewLexical] = OrderedDict()


@dataclass(frozen=True)
class UnitDoc:
    """What the index holds of one unit (module docstring)."""

    unit_id: str
    type: str
    doc_id: str
    fields: dict[str, str]
    dense_text: str
    aids: tuple[str, ...]


# -- documents ---------------------------------------------------------------------------------

def _dedup(texts) -> list[str]:
    """The non-empty texts, first occurrence kept."""
    out: list[str] = []
    for t in texts:
        if t and t not in out:
            out.append(t)
    return out


def _model_values(field) -> list[str]:
    """The value of a model-written field (`{value, quotes, status, null_reason}`) as a list
    of texts: none when null, one for a string, all of a list."""
    value = field.get("value") if isinstance(field, dict) else None
    if value is None:
        return []
    return [value] if isinstance(value, str) else [v for v in value if isinstance(v, str)]


def _concept_labels(concept: Unit) -> list[str]:
    return _dedup([concept.body["pref_label"], *concept.body["alt_labels"]])


def _closure_headings(card: Unit, units: dict[str, Unit]) -> list[str]:
    out = []
    for e in card.body.get("closure", []):
        if e["relation"] == "defines":
            continue
        target = units.get(e["unit_id"]) if e["unit_id"] else None
        if target is None:
            out.append(e["ref"])
            continue
        heads = [h for h in target.heading_path if h != target.title]
        out.append(heads[-1] if heads else target.title)
    return _dedup(out)


def _body(u: Unit, units: dict[str, Unit]) -> str:
    b = u.body
    if u.type == "concept":
        parts = [b["definition"]["text"], b.get("scope_note")]
    elif u.type == "rule_card":
        parts = [b["text"], *_closure_headings(u, units)]
    elif u.type == "procedure":
        parts = [*_model_values(b.get("when_to_use")), *b.get("inputs", []),
                 *b.get("preconditions", []), *(s["text"] for s in b["steps"]),
                 b.get("escalation"), b.get("success_criteria")]
    elif u.type == "faq":
        parts = [(b.get(k) or {}).get("text") for k in
                 ("question", "answer", "issue", "environment", "cause", "resolution")]
    else:  # table_record
        parts = [b.get("caption"), " ".join(b.get("headers", [])), b["description"]]
    return "\n".join(p for p in parts if p)


def _ref(u: Unit) -> str:
    extra = []
    if u.type == "rule_card":
        extra = [u.body["provision_id"]]
    elif u.type == "table_record":
        extra = [(u.body.get("pointer") or {}).get("table")]
    return "\n".join(_dedup([u.canonical_ref, *extra]))


def _aids(u: Unit) -> tuple[str, ...]:
    texts = [*u.aids.keywords, *u.aids.problem_abstractions, *u.aids.trigger_examples]
    if u.type == "procedure":
        texts += [*_model_values(u.body.get("problem_abstractions")),
                  *_model_values(u.body.get("trigger_examples"))]
    return tuple(_dedup(texts))


def unit_docs(units: list[Unit], concept_units: list[Unit]) -> list[UnitDoc]:
    """One `UnitDoc` per unit of `units`, sorted by unit id; `labels` come from the concepts
    in scope (`concept_units`, module docstring)."""
    by_id = {u.unit_id: u for u in units}
    concepts = {c.unit_id: c for c in concept_units}
    index = _Labels(concept_units)
    docs = []
    for u in sorted(units, key=lambda u: u.unit_id):
        body = _body(u, by_id)
        if u.type == "concept":
            labels = _concept_labels(u)
        elif u.type == "rule_card":
            labels = [lab for cid in u.body.get("defined_terms", []) if cid in concepts
                      for lab in _concept_labels(concepts[cid])]
        elif u.type == "procedure":
            text = "\n".join([u.title, body])
            sub = _subpart_of(u)
            found = index.mentions(u.doc_id, text)
            hits = sorted(cid for cid in found if scope_contains(
                concepts[cid].body["scope"]["ref"], u.canonical_ref, subpart=sub))
            labels = [lab for cid in hits for lab in _concept_labels(concepts[cid])]
        else:
            labels = []
        aids = _aids(u)
        fields = {"title": "\n".join(_dedup([u.title, *u.heading_path])), "ref": _ref(u),
                  "labels": "\n".join(_dedup([*labels, *u.aids.labels])), "body": body,
                  "aids": "\n".join(aids)}
        docs.append(UnitDoc(u.unit_id, u.type, u.doc_id, fields,
                            BREADCRUMB_SEP.join(u.heading_path) + "\n" + body, aids))
    return docs


def indexed_text(doc: UnitDoc, weights: dict[str, int]) -> str:
    """The text BM25 indexes for `doc`: each field repeated by its weight, in `FIELDS` order."""
    return " ".join(doc.fields[f] for f in FIELDS for _ in range(weights[f]))


# -- concept expansion -------------------------------------------------------------------------

_WORD = re.compile(r"\w+")


def _words(text: str) -> list[str]:
    return _WORD.findall(unicodedata.normalize("NFKC", text).casefold())


def label_key(label: str) -> str:
    """The matching key of a label or query phrase: NFKC, case-folded words joined by spaces."""
    return " ".join(_words(label))


def label_variants(label: str) -> frozenset[str]:
    """The keys a label matches under: its own key and the keys of its hidden labels
    (`concepts.hidden_labels`: case-folded, hyphen and space variants, joined, plural "s")."""
    return frozenset({label_key(label)} | {label_key(h) for h in hidden_labels(label)}) - {""}


def expand_query(query: str, label_map: dict[str, tuple[str, ...]]) -> str:
    """`query` followed by the alternate labels (`label_map[key]`) of every label key it holds
    as whole words, in the order the keys start in the query (longer first at one start),
    leaving out a label when the query or an earlier addition already holds one of its
    variants (`label_variants`). BM25 only."""
    words = _words(query)
    if not words or not label_map:
        return query
    longest = max(len(k.split()) for k in label_map)
    grams = [[" ".join(words[i:i + n]) for n in range(min(longest, len(words) - i), 0, -1)]
             for i in range(len(words))]                 # per start, longest first
    seen = {g for at in grams for g in at}              # what the query already says
    added: list[str] = []
    for key in (g for at in grams for g in at):
        for alt in label_map.get(key, ()):
            variants = label_variants(alt)
            if not variants & seen:
                seen |= variants
                added.append(alt)
    return query if not added else query + " " + " ".join(added)


def _label_map(docs: list[UnitDoc]) -> dict[str, tuple[str, ...]]:
    """{label variant key: the other labels of every concept that has a label with that
    variant}, from the concept docs given (the labels field, one label per line; the
    variants are each label's key and its hidden labels' keys, M3)."""
    out: dict[str, list[str]] = {}
    for d in docs:
        if d.type != "concept":
            continue
        labels = [lab for lab in d.fields["labels"].split("\n") if label_key(lab)]
        variants = {lab: label_variants(lab) for lab in labels}
        for lab in labels:
            for key in sorted(variants[lab]):
                alts = out.setdefault(key, [])
                for other in labels:
                    if key not in variants[other] and other not in alts:
                        alts.append(other)
    return {k: tuple(v) for k, v in sorted(out.items()) if v}


# -- tuning ------------------------------------------------------------------------------------

def check_tuning(tuning: object, types: tuple[str, ...] | None = None) -> dict:
    """`tuning` (`{"weights": {type: {field: weight}}, "w": float}`) checked: every weight in
    `WEIGHT_GRID`, exactly the `FIELDS` per type, `w` in `W_GRID`, and (given `types`) exactly
    those types."""
    if not isinstance(tuning, dict) or set(tuning) != {"weights", "w"}:
        raise ValueError(f"tuning must be {{'weights': ..., 'w': ...}}, got {tuning!r}")
    w = tuning["w"]
    if isinstance(w, bool) or not isinstance(w, (int, float)) or float(w) not in W_GRID:
        raise ValueError(f"w must be one of {W_GRID}, got {w!r}")
    weights = tuning["weights"]
    if not isinstance(weights, dict):
        raise ValueError(f"tuning weights must be {{type: {{field: weight}}}}, got {weights!r}")
    if types is not None and set(weights) != set(types):
        raise ValueError(f"tuning types {sorted(weights)} are not the corpus types "
                         f"{sorted(types)}")
    for t, fw in weights.items():
        if t not in UNIT_TYPES:
            raise ValueError(f"unknown unit type {t!r} in tuning")
        if not isinstance(fw, dict) or set(fw) != set(FIELDS):
            raise ValueError(f"tuning weights of {t!r} must name exactly the fields {FIELDS}")
        for f, v in fw.items():
            if isinstance(v, bool) or v not in WEIGHT_GRID:
                raise ValueError(f"weight of {t}.{f} must be one of {WEIGHT_GRID}, got {v!r}")
    return {"weights": {t: {f: int(weights[t][f]) for f in FIELDS} for t in sorted(weights)},
            "w": float(w)}


def tuning_path() -> Path:
    """The tuning file in force: `$ADR_UNITS_TUNING` when set, else `TUNING_PATH` (read when
    called)."""
    env = os.environ.get(TUNING_ENV)
    return Path(env) if env else TUNING_PATH


def load_tuning(corpus: str, path: Path | None = None) -> dict:
    """The tuning of `corpus` from the tuning file (C13; `path`, default `tuning_path()`):
    `{"weights": {type: {field: weight}}, "w": float}` for exactly the corpus's unit types."""
    if corpus not in CORPUS_TYPES:
        raise ValueError(f"no tuning for corpus {corpus!r}; one of {', '.join(CORPUS_TYPES)}")
    path = tuning_path() if path is None else Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if corpus not in data:
        raise ValueError(f"{path}: no tuning for corpus {corpus!r}")
    return check_tuning(data[corpus], CORPUS_TYPES[corpus])


def write_tuning(corpus: str, entry: dict, path: Path | None = None) -> Path:
    """Set the tuning of `corpus` in the tuning file (`path`, default `tuning_path()`) to
    `entry` (checked), keeping the other corpora's entries and their order; the file is
    written whole (indent 2, newline-terminated). Returns the path."""
    if corpus not in CORPUS_TYPES:
        raise ValueError(f"no tuning for corpus {corpus!r}; one of {', '.join(CORPUS_TYPES)}")
    entry = check_tuning(entry, CORPUS_TYPES[corpus])
    path = tuning_path() if path is None else Path(path)
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data[corpus] = entry
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def default_tuning(corpus: str) -> dict:
    """Every field weight 1 for every unit type of `corpus`, and `w = 1.0` (lexical-only): the
    entry that resolves without a pin file, and what a handle saved before Task 12 (null
    `unit_index`) stands for (the index Task 8 served)."""
    if corpus not in CORPUS_TYPES:
        raise ValueError(f"no tuning for corpus {corpus!r}; one of {', '.join(CORPUS_TYPES)}")
    return check_tuning({"weights": {t: dict.fromkeys(FIELDS, 1) for t in CORPUS_TYPES[corpus]},
                         "w": 1.0}, CORPUS_TYPES[corpus])


# -- the pinned tuning (spec P42) --------------------------------------------------------------
# A handle's `unit_index` is the SHA-256 of a corpus's canonical tuning entry (`tuning_bytes`:
# sorted keys, no spaces, no trailing newline). The entry is pinned, content-addressed and
# write-once, at `<store>/units-index/<units id>/tuning-<id>.json`, so a handle replays with
# the weights it names whatever the tuning file says later. Pins are written only where a
# tuning is written or adopted (`adr-eval p4-tune`, units promotion, `adr units pin`), never
# by a read; the corpus's default entry resolves without a file.

def tuning_bytes(entry: dict) -> bytes:
    """The canonical bytes of a tuning entry (checked): its SHA-256 is its `unit_index`."""
    return json.dumps(check_tuning(entry), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def tuning_id(entry: dict) -> str:
    """The `unit_index` of a tuning entry: the SHA-256 of `tuning_bytes(entry)`."""
    return hashlib.sha256(tuning_bytes(entry)).hexdigest()


def pin_path(store_path: Path, units_id: str, tid: str) -> Path:
    return Path(store_path) / INDEX_DIR / units_id / f"tuning-{tid}.json"


def pinned_tuning(store_path: Path, units_id: str, tid: str,
                  types: tuple[str, ...] | None = None, corpus: str | None = None
                  ) -> dict | None:
    """The tuning entry pinned as `tid` for build `units_id` (checked, and of exactly `types`
    when given), or None when it is missing, does not hash to `tid` or does not check. With
    `corpus`, its default entry (`default_tuning`) resolves without a file."""
    if corpus is not None and corpus in CORPUS_TYPES and \
            tid == tuning_id(default_tuning(corpus)):
        return default_tuning(corpus)
    try:
        data = pin_path(store_path, units_id, tid).read_bytes()
    except OSError:
        return None
    if hashlib.sha256(data).hexdigest() != tid:
        return None
    try:
        return check_tuning(json.loads(data.decode("utf-8")), types)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None


def pin_tuning(store_path: Path, units_id: str, entry: dict) -> str:
    """Pin `entry` for build `units_id` (write-once: an existing pin with the right bytes is
    kept, a damaged one replaced through a fresh file and a rename); its `unit_index`. Never
    writes an index directory."""
    data = tuning_bytes(entry)
    tid = hashlib.sha256(data).hexdigest()
    path = pin_path(store_path, units_id, tid)
    try:
        if path.read_bytes() == data:
            return tid
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return tid


# -- the per-view lexical index ----------------------------------------------------------------

class _ViewLexical:
    """BM25 over the indexed texts of one view's units, with their types, doc ids and the
    view's label map."""

    def __init__(self, docs: list[UnitDoc], weights: dict[str, dict[str, int]]):
        self.ids = [d.unit_id for d in docs]
        self.types = np.array([d.type for d in docs], dtype=str)
        self.doc_ids = np.array([d.doc_id for d in docs], dtype=str)
        self.bm25 = BM25Index()
        self.bm25.build([Chunk(d.unit_id, d.doc_id, 0, 1, indexed_text(d, weights[d.type]))
                         for d in docs])
        self.label_map = _label_map(docs)

    def hits(self, query: str, types: tuple[str, ...] | None,
             allowed: frozenset[str] | None) -> Hits:
        """Every unit of the view with a positive BM25 score for `query` (the expanded
        query), masked to `types` and to the documents `allowed` (None: all), sorted by
        (-score, unit id). The mask changes no statistic."""
        scores = self.bm25.scores(query)
        mask = np.ones(len(self.ids), dtype=bool)
        if types is not None:
            mask &= np.isin(self.types, np.array(types, dtype=str))
        if allowed is not None:
            mask &= np.isin(self.doc_ids, np.array(sorted(allowed), dtype=str))
        return masked_hits(self.ids, scores, mask, len(self.ids), positive=True)


def _check_types(types) -> tuple[str, ...] | None:
    if types is None:
        return None
    if not isinstance(types, tuple) or not types:
        raise ValueError(f"types must be None or a non-empty tuple of unit types, got "
                         f"{types!r}")
    for t in types:
        if t not in UNIT_TYPES:
            raise ValueError(f"unknown unit type {t!r}; one of {', '.join(UNIT_TYPES)}")
    return tuple(sorted(set(types)))


def _check_docs(name: str, docs) -> frozenset[str] | None:
    if docs is None:
        return None
    if not isinstance(docs, (frozenset, set)):
        raise ValueError(f"{name} must be None or a set of document ids, got "
                         f"{type(docs).__name__}")
    return frozenset(docs)


def _sha256_json(value) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _json_bytes(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            + "\n").encode("utf-8")


# -- the stored dense vectors ------------------------------------------------------------------

def _rows(docs: list[UnitDoc]) -> list[tuple[str, int | None, str]]:
    """(unit id, aid index or None, embedded text) of every vector: each unit's `dense_text`
    in unit-id order, then each unit's aids."""
    return ([(d.unit_id, None, d.dense_text) for d in docs]
            + [(d.unit_id, i, a) for d in docs for i, a in enumerate(d.aids)])


def _read_stored(dir: Path, meta: dict) -> np.ndarray | None:
    """The stored vectors of `dir` when its index.json equals `meta` (vectors hash aside)
    and the vectors file has the recorded hash, else None."""
    try:
        stored = json.loads((dir / "index.json").read_text(encoding="utf-8"))
        data = (dir / "vectors.npy").read_bytes()
    except (OSError, ValueError):
        return None
    if {k: v for k, v in stored.items() if k != "vectors_sha256"} != meta or \
            stored.get("vectors_sha256") != hashlib.sha256(data).hexdigest():
        return None
    return np.load(dir / "vectors.npy", allow_pickle=False)


def _install(dir: Path, files: dict[str, bytes]) -> None:
    """Write `files` into `dir` as one directory, through a fresh sibling and a rename; an
    existing `dir` with exactly these files is kept, any other is replaced."""
    def same() -> bool:
        try:
            return (sorted(p.name for p in dir.iterdir()) == sorted(files)
                    and all((dir / n).read_bytes() == b for n, b in files.items()))
        except OSError:
            return False

    if dir.is_dir() and same():
        return
    dir.parent.mkdir(parents=True, exist_ok=True)
    tmp = dir.parent / f".{dir.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    tmp.mkdir()
    try:
        for name, data in files.items():
            (tmp / name).write_bytes(data)
        try:
            os.rename(tmp, dir)
            return
        except OSError:
            if same():                  # another process installed the same index
                return
        old = dir.parent / f".{dir.name}.{os.getpid()}.{uuid.uuid4().hex}.old"
        os.rename(dir, old)
        os.rename(tmp, dir)
        shutil.rmtree(old, ignore_errors=True)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def _npy_bytes(vectors: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, np.ascontiguousarray(vectors, dtype=np.float32), allow_pickle=False)
    return buf.getvalue()


# -- fusion (P41) ------------------------------------------------------------------------------

def fuse(lex: Hits, dense: Hits, w: float) -> Hits:
    """The unit index's linear fusion (spec P41): every candidate unit (`dense` holds every
    unit the masks keep, `lex` those with a positive BM25 score) scored
    `w * l + (1 - w) * d`, where `l` is its BM25 score divided by the pool's best (0 without
    a BM25 score, so the lowest or only hit stays above every non-match) and `d` its dense
    score min-max scaled over the whole masked pool (0 when the pool's range is 0). Rounded to
    6 decimals and sorted by (-score, unit id). The scaling is over the complete pools, so
    the ranking has no separate head and tail: a deeper cut never reorders the top."""
    best = max((s for _, s in lex), default=0.0)
    bm25 = dict(lex)
    lo = min((s for _, s in dense), default=0.0)
    span = max((s for _, s in dense), default=0.0) - lo
    dn = {u: (s - lo) / span if span > 0 else 0.0 for u, s in dense}
    scores = {u: w * (bm25.get(u, 0.0) / best if best > 0 else 0.0)
              + (1.0 - w) * dn.get(u, 0.0) for u in bm25.keys() | dn.keys()}
    hits = [(u, round(float(s), 6)) for u, s in scores.items()]
    hits.sort(key=lambda h: (-h[1], h[0]))
    return hits


# -- the index ---------------------------------------------------------------------------------

class UnitVectorsMissing(ValueError):
    """A read needs the stored dense vectors of a build and they are not there."""


class UnitIndex:
    """Build with `UnitIndex.build(store_path, units_id, docs, emb, tuning)`."""

    def __init__(self, units_id: str, docs: list[UnitDoc], tuning: dict, directory: Path,
                 emb: EmbeddingCache | None, vectors: np.ndarray | None,
                 rows: list[tuple[str, int | None, str]] | None):
        self.units_id = units_id
        self.docs = docs
        self.tuning = tuning
        self.directory = directory
        self.emb = emb
        self.lexical_only = emb is None
        self.doc_ids = frozenset(d.doc_id for d in docs)
        self.docs_sha256 = _sha256_json([[d.unit_id, d.type, d.doc_id, d.fields,
                                          d.dense_text, list(d.aids)] for d in docs])
        self.fingerprint = _sha256_json({
            "format": FORMAT_VERSION, "units_id": units_id, "docs": self.docs_sha256,
            "weights": tuning["weights"], "bm25": BM25Index().config()})
        self._ids = [d.unit_id for d in docs]
        self._doc_of = np.array([d.doc_id for d in docs], dtype=str)
        self._type_of = np.array([d.type for d in docs], dtype=str)
        self._vectors = vectors
        if rows is not None:
            pos = {u: i for i, u in enumerate(self._ids)}
            self._aid_parent = np.array([pos[u] for u, aid, _ in rows if aid is not None],
                                        dtype=np.int64)
        self._full: _ViewLexical | None = None
        self._full_lock = threading.Lock()

    @classmethod
    def build(cls, store_path: Path, units_id: str, docs: list[UnitDoc],
              emb: EmbeddingCache | None, tuning: dict, *, install: bool = True,
              stored_only: bool = False) -> UnitIndex:
        """The index of `docs` (`unit_docs` of build `units_id`), with dense vectors from
        `emb` stored under `<store_path>/units-index/<units id>/`; `emb=None` builds a
        lexical-only index (C8). `tuning` is a corpus's entry of the tuning file.
        `install=False` (lexical-only only) builds it in memory and writes nothing.
        `stored_only=True` (dense) reads the stored vectors and never embeds a document or
        writes: `UnitVectorsMissing` when they are not there. Both are the tools' path,
        where a read call never writes into the store."""
        if not install and emb is not None and not stored_only:
            raise ValueError("a dense unit index stores its vectors: install=False needs "
                             "emb=None")
        docs = sorted(docs, key=lambda d: d.unit_id)
        if len({d.unit_id for d in docs}) != len(docs):
            raise ValueError("unit docs repeat a unit id")
        tuning = check_tuning(tuning)
        missing = sorted({d.type for d in docs} - set(tuning["weights"]))
        if missing:
            raise ValueError(f"the tuning has no field weights for unit types "
                             f"{', '.join(missing)}")
        root = Path(store_path) / INDEX_DIR / units_id
        index = cls(units_id, docs, tuning, root / "lexical", emb, None, None)
        meta = {"format": FORMAT_VERSION, "units_id": units_id, "units": len(docs),
                "docs_sha256": index.docs_sha256}
        if emb is None:
            if install:
                _install(index.directory, {"index.json": _json_bytes(
                    {**meta, "lexical_only": True, "embedding": None})})
            return index
        rows = _rows(docs)
        directory = root / f"dense-{emb.model_hash[:16]}"
        meta = {**meta, "lexical_only": False, "rows": len(rows),
                "embedding": {"model": emb.model_name, "model_hash": emb.model_hash}}
        vectors = _read_stored(directory, meta)
        if vectors is None and stored_only:
            raise UnitVectorsMissing(f"no stored dense vectors of units {units_id[:12]} for "
                                     f"{emb.model_name}")
        if vectors is None:
            vectors, _ = emb.embed_texts([t for _, _, t in rows])
            data = _npy_bytes(vectors)
            _install(directory, {
                "index.json": _json_bytes({**meta,
                                           "vectors_sha256": hashlib.sha256(data).hexdigest()}),
                "rows.jsonl": b"".join(_json_bytes({"unit_id": u, "aid": a})
                                       for u, a, _ in rows),
                "vectors.npy": data})
        return cls(units_id, docs, tuning, directory, emb, vectors, rows)

    # -- views -----------------------------------------------------------------------------

    def _view(self, view: frozenset[str] | None) -> _ViewLexical | None:
        """The lexical index of the caller's view (module docstring); None for a view with no
        unit. Only `view` chooses it: filters never do (Phase 2 §6.2)."""
        docs = self.doc_ids if view is None else view & self.doc_ids
        if not docs:
            return None
        if docs == self.doc_ids:
            with self._full_lock:
                if self._full is None:
                    self._full = _ViewLexical(self.docs, self.tuning["weights"])
            return self._full
        key = (self.fingerprint, acl.view_id(docs))
        with _VIEW_LOCK:
            if key in _VIEW_LEXICAL:
                _VIEW_LEXICAL.move_to_end(key)
                return _VIEW_LEXICAL[key]
        lex = _ViewLexical([d for d in self.docs if d.doc_id in docs], self.tuning["weights"])
        with _VIEW_LOCK:
            _VIEW_LEXICAL[key] = lex
            _VIEW_LEXICAL.move_to_end(key)
            while len(_VIEW_LEXICAL) > VIEW_CACHE:
                _VIEW_LEXICAL.popitem(last=False)
        return lex

    def label_map(self, view: frozenset[str] | None) -> dict[str, tuple[str, ...]]:
        """The label map of the view's concepts (what `expand_query` reads)."""
        lex = self._view(_check_docs("view", view))
        return {} if lex is None else lex.label_map

    def lexical_query(self, query: str, view: frozenset[str] | None) -> str:
        """`query` expanded by the view's concept labels: what BM25 searches."""
        return expand_query(query, self.label_map(view))

    @staticmethod
    def _allowed(view: frozenset[str] | None, admitted: frozenset[str] | None
                 ) -> frozenset[str] | None:
        """The documents both channels keep: `view ∩ admitted` (None: no restriction)."""
        if view is None:
            return admitted
        return view if admitted is None else view & admitted

    # -- channels --------------------------------------------------------------------------

    def _dense(self, query: str, allowed: frozenset[str] | None,
               types: tuple[str, ...] | None) -> Hits:
        mask = np.ones(len(self._ids), dtype=bool)
        if allowed is not None:
            mask &= np.isin(self._doc_of, np.array(sorted(allowed), dtype=str))
        if types is not None:
            mask &= np.isin(self._type_of, np.array(types, dtype=str))
        if not mask.any():
            return []
        q = _unit(next(iter(self.emb.model().query_embed([query]))))
        scores = row_scores(self._vectors, q)
        best = scores[:len(self._ids)].copy()
        np.maximum.at(best, self._aid_parent, scores[len(self._ids):])
        return masked_hits(self._ids, best, mask, len(self._ids), positive=False)

    def dense_scores(self, query: str, *, types: tuple[str, ...] | None,
                     view: frozenset[str] | None, admitted: frozenset[str] | None = None
                     ) -> Hits:
        """Every unit of `types` in `view ∩ admitted` with its dense score (best cosine of its
        own row and its aid rows), sorted by (-score, unit id)."""
        if self.lexical_only:
            raise ValueError("this unit index is lexical-only (built with emb=None)")
        view, admitted = _check_docs("view", view), _check_docs("admitted", admitted)
        return self._dense(query, self._allowed(view, admitted), _check_types(types))

    def search(self, query: str, *, types: tuple[str, ...] | None,
               view: frozenset[str] | None, admitted: frozenset[str] | None = None,
               k: int = 10) -> Hits:
        """The top `k` units for `query` as (unit id, score), sorted by (-score, unit id).

        `view` (the caller's ACL-visible documents; None: every document) sets the BM25
        statistics, the cache key and the label map. `admitted` (the documents the filters
        admit; None: the whole view) and `types` (None: every type) mask both channels to
        `view ∩ admitted` before any cut, as `StoreIndex.retrieve(allowed_docs=...)` does."""
        if isinstance(k, bool) or not isinstance(k, int) or k < 0:
            raise ValueError(f"k must be an integer >= 0, got {k!r}")
        view, admitted = _check_docs("view", view), _check_docs("admitted", admitted)
        types = _check_types(types)
        lexv = self._view(view)
        if lexv is None or k == 0:
            return []
        allowed = self._allowed(view, admitted)
        lex = lexv.hits(expand_query(query, lexv.label_map), types, allowed)
        if self.lexical_only:
            return lex[:k]
        return fuse(lex, self._dense(query, allowed, types), self.tuning["w"])[:k]
