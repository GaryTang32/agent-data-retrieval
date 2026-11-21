"""The gov-tables v0.1 golden generator (Phase 3 spec §10.3, ruling P9): questions over the
drawbridge facts of 33 CFR part 117, drawn and answered by code, phrased by a model.

- **Facts:** the independent second extraction (`adr tables extract --second-pass`), read back by
  its id (`load_facts`), never the table under test. `facts_db` holds its rows of the
  `drawbridge_sections` and `drawbridge_bridges` contracts (`drawbridge_rows`), kept to the
  documents the default applicability filters admit: the version in force.
- **Draws:** v0.1's count_filter drawer (`_filter_fields`, `_draw_filter`) over the fact rows of one
  table, extended to a bool equality, a numeric range (`__gte` and `__lte` together) and
  `__isnull` true or false: one or two clauses whose values come from one sampled row. The op is
  `count`, `list` or `lookup` (a numeric or bool field the clauses do not name); a lookup is kept
  only when exactly one row matches. Structure columns other than `state` (section, version,
  heading, draw, waterway key) are not drawn: they identify rows or repeat the version in force.
- **Answers:** `answer_of`, by code over `facts_db`: a count is a `number`, a list the sorted
  unique section numbers (`set`), a numeric lookup a `number`, a bool lookup the `id` "yes" or
  "no" with the variant "true" or "false". Draws with no match, lists over `MAX_LIST`, counts over
  `MAX_COUNT`, lookups matching more than one row and repeats of an earlier draw are rejected
  (code only, no call).
- **Phrasing:** one cached call per item (`client.complete(prompt, phrasing_message(query),
  max_tokens=300, cache_failures=True)`), no evidence check. A malformed reply, or a call the
  provider rejected for its input (stored as a failure, ruling P21), redraws; any other model
  failure and a budget stop propagate (nothing is returned, the completed calls stay cached).
- **Items:** ids `gov-tables-001`..., evidence the matched rows' quotes of the drawn columns (a
  row with none gives its section heading), each re-sliced from the document text; split
  `assign_split(id)`. `TablesItem.as_golden()` is the harness's view (qtype `count_filter`).

Sampling goes only through `random.Random(seed)`, over rows in contract order and fields in
sorted order, so a fixed seed and the reply cache regenerate byte-identical items.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from adr_eval.corpora import REPO_ROOT
from adr_eval.golden.generate import _filter_fields, _reply
from adr_eval.golden.verify import assign_split
from adr_eval.llm import CachedFailure, ModelOutputError
from adr_eval.models import (
    Answer,
    Checks,
    Evidence,
    GoldenItem,
    GoldQuery,
    Provenance,
    jsonl_lines,
)
from adr_store import applicability as ap
from adr_store.store import Store
from adr_store.tables.contracts import Contract, load_contracts
from adr_store.tables.engine import QUERY_LIMIT_MAX, ViewDB, run_query
from adr_store.tables.extract import (
    BRIDGES_TABLE,
    SECTIONS_TABLE,
    Facts,
    Unit,
    drawbridge_rows,
    load_facts,
    units,
)
from adr_store.tables.overlay import TablesError
from adr_store.tables.provenance import RowRecord, sort_key
from adr_store.tables.semantic import describe

PROMPT_VERSION = "tables_question@1"
N_ITEMS = 120
SEED = 20261120
MAX_LIST = 25
MAX_COUNT = 50
MAX_TOKENS = 300
DRAWS_PER_ITEM = 50          # code-only draws per wanted item before reporting a shortfall
GOLDEN_DIR = REPO_ROOT / "golden" / "gov-tables" / "v0.1"
TABLES = (SECTIONS_TABLE, BRIDGES_TABLE)
NOT_DRAWN = ("section", "version", "heading", "draw", "waterway_key")
LOOKUP_KINDS = ("int", "real", "bool")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_PROMPT = "prompts/tables_question.txt"


class TableQuery(BaseModel):
    """A gov-tables gold query: `query_table` arguments over a drawbridge table."""

    table: Literal["drawbridge_sections", "drawbridge_bridges"]
    op: Literal["count", "list", "lookup"]
    filters: dict[str, str | int | float | bool | list[str]] = {}
    field: str | None = None

    def to_kwargs(self) -> dict:
        """The `query_table` keyword arguments: `field` becomes `fields=[field]`."""
        out: dict[str, Any] = {"table": self.table, "filters": dict(self.filters), "op": self.op}
        if self.field is not None:
            out["fields"] = [self.field]
        return out


class TablesItem(BaseModel):
    id: str
    corpus: Literal["gov-tables"]
    snapshot: str                    # the store's content snapshot
    facts: str                       # the second-pass facts id
    qtype: Literal["count", "list", "lookup"]
    question: str
    answer: Answer
    query: TableQuery
    evidence: list[Evidence]
    split: Literal["dev", "test"]
    provenance: Provenance
    status: Literal["auto_verified"]

    def as_golden(self) -> GoldenItem:
        """The harness's view: a `count_filter` item whose gold query names the op (v0.1's
        `GoldQuery` has no table, bool filter or field: the query is `self.query`)."""
        return GoldenItem(
            id=self.id, corpus=self.corpus, snapshot=self.snapshot, qtype="count_filter",
            question=self.question, as_of=None, answer=self.answer, evidence=self.evidence,
            gold_query=GoldQuery(store="typed_db", op=self.query.op), rarity=None,
            split=self.split, provenance=self.provenance, checks=Checks(span_ok=True),
            status=self.status)


# -- prompts and the schema text ---------------------------------------------------------------


def load_prompt() -> str:
    return resources.files("adr_eval.golden").joinpath(_PROMPT).read_text(encoding="utf-8")


def prompt_hash() -> str:
    return hashlib.sha256(
        resources.files("adr_eval.golden").joinpath(_PROMPT).read_bytes()).hexdigest()


@cache
def contracts() -> dict[str, Contract]:
    """The drawbridge contracts (the repository's, as the extraction builds use)."""
    available = load_contracts(corpus="gov")
    return {t: available[t] for t in TABLES}


@cache
def describe_text() -> str:
    """The schema text of table-query generation: the semantic layer's detail of the two
    drawbridge tables (`semantic.describe`, without its notes on the `sql` tool), rendered
    once, so every system sends the same bytes."""
    cs = list(contracts().values())
    details = [{k: v for k, v in describe(cs, t).items() if k not in ("metrics", "sql")}
               for t in TABLES]
    return json.dumps(details, ensure_ascii=False)


def phrasing_message(q: TableQuery, cs: dict[str, Contract] | None = None) -> str:
    """The phrasing call's user message: the table, the columns the query uses (name, type,
    description), the op, the filters and, for a lookup, the field."""
    c = (cs or contracts())[q.table]
    by_name = {col.name: col for col in c.columns}
    names = [k.split("__", 1)[0] for k in q.filters] + ([q.field] if q.field else [])
    lines = [f"Table: {q.table} ({c.description})", "Columns:"]
    for name in dict.fromkeys(names):
        col = by_name.get(name)
        if col is not None:
            lines.append(f"- {name} ({col.type}): {col.description}")
    lines += [f"Operation: {q.op}",
              f"Filters: {json.dumps(q.filters, sort_keys=True, ensure_ascii=False)}"]
    if q.field is not None:
        lines.append(f"Field: {q.field}")
    return "\n".join(lines)


# -- the facts -----------------------------------------------------------------------------------


def fact_rows(store_path: Path, facts: list[Facts], all_units: list[Unit]
              ) -> dict[str, list[RowRecord]]:
    """The drawbridge rows of the facts whose documents the default applicability filters
    admit (the version in force); TablesError when the store has no applicability overlay
    (without it every version would count)."""
    rows = drawbridge_rows(facts, all_units)
    store = Store.open(store_path)
    overlay = ap.load_overlay(store_path, store.snapshot_id)
    if overlay is None:
        raise TablesError(f"{store_path}: no applicability overlay for snapshot "
                          f"{store.snapshot_id[:12]}: the version in force is unknown\nfix: "
                          f"derive it (`adr applicability derive --store {store_path}`)")
    docs = {r.doc_id for recs in rows.values() for r in recs}
    admitted, _ = overlay.allowed_docs(docs, ap.Filters())
    return {t: [r for r in recs if r.doc_id in admitted] for t, recs in rows.items()}


def facts_db(store_path: Path, facts: list[Facts], all_units: list[Unit]) -> ViewDB:
    """The drawbridge tables built from the facts, version in force (`fact_rows`)."""
    return ViewDB.from_rows(contracts(), fact_rows(store_path, facts, all_units))


# -- the drawer ----------------------------------------------------------------------------------


def _number(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def fact_fields(rows: list[dict]) -> list[tuple[str, str]]:
    """(field, kind) pairs usable in filters, sorted: v0.1's (`_filter_fields`: "int", "list",
    categorical "str") plus "bool" (every value true or false), "real" (numbers, not all
    integers) and "nullable" (null in some rows, not in all). Never a `NOT_DRAWN` column."""
    kept = [{k: v for k, v in r.items() if k not in NOT_DRAWN} for r in rows]
    out = list(_filter_fields(kept))
    for f in sorted({k for r in kept for k in r}):
        values = [r.get(f) for r in kept if r.get(f) not in (None, "", [])]
        if not values:
            continue
        if all(isinstance(v, bool) for v in values):
            out.append((f, "bool"))
        elif all(_number(v) for v in values) and not all(isinstance(v, int) for v in values):
            out.append((f, "real"))
        if any(r.get(f) is None for r in kept):
            out.append((f, "nullable"))
    return sorted(out)


def draw_table_filter(rows: list[dict], fields: list[tuple[str, str]], rng: random.Random
                      ) -> tuple[dict, str, str | None] | None:
    """(filters, op, lookup field) of one or two clauses with values from one sampled row, or
    None when the draw is unusable (a clause on a null value, two clauses on one column, a
    lookup with no field left). Numbers take equality, `__gte`, `__lte` or a range to another
    row's value; bools equality; lists `__contains` one element; "nullable" `__isnull` as the
    row has it; categorical strings equality. The field of a lookup is a numeric or bool column
    the clauses do not name, set in the sampled row."""
    k = 1 if len(fields) == 1 else rng.choice([1, 2])
    chosen = sorted(rng.sample(fields, k))
    if len({f for f, _ in chosen}) < k:
        return None
    row = rng.choice(rows)
    filters: dict = {}
    for name, kind in chosen:
        v = row.get(name)
        if kind == "nullable":
            filters[f"{name}__isnull"] = v is None
            continue
        if v in (None, "", []):
            return None
        if kind in ("int", "real"):
            how = rng.choice(["", "__gte", "__lte", "range"])
            if how == "range":
                others = sorted({r[name] for r in rows if _number(r.get(name))} - {v})
                w = rng.choice(others) if others else v
                filters[f"{name}__gte"], filters[f"{name}__lte"] = min(v, w), max(v, w)
            else:
                filters[name + how] = v
        elif kind == "list":
            filters[f"{name}__contains"] = rng.choice(sorted(v))
        else:   # "bool" and "str": equality
            filters[name] = v
    op = rng.choice(["count", "list", "lookup"])
    lookup = None
    if op == "lookup":
        named = {f for f, _ in chosen}
        candidates = sorted({f for f, kind in fields if kind in LOOKUP_KINDS
                             and f not in named and row.get(f) is not None})
        if not candidates:
            return None
        lookup = rng.choice(candidates)
    return dict(sorted(filters.items())), op, lookup


# -- answers -------------------------------------------------------------------------------------


def answer_of(q: TableQuery, db: ViewDB) -> Answer:
    """The answer to `q` over `db` by code; ValueError for a lookup that does not match exactly
    one row or whose value is no number or bool."""
    if q.op == "count":
        return Answer(kind="number", value=float(run_query(db, q.table, q.filters, "count").count))
    if q.op == "list":
        return Answer(kind="set", value=run_query(db, q.table, q.filters, "list").ids)
    if q.field is None:
        raise ValueError("a lookup names a field")
    out = run_query(db, q.table, q.filters, "lookup", fields=[q.field], limit=QUERY_LIMIT_MAX)
    if len(out.rows) != 1:
        raise ValueError(f"lookup matches {len(out.rows)} rows, not one")
    v = out.rows[0]["row"][q.field]
    if isinstance(v, bool):
        return Answer(kind="id", value="yes" if v else "no",
                      accepted_variants=["true" if v else "false"])
    if _number(v):
        return Answer(kind="number", value=float(v))
    raise ValueError(f"lookup of {q.field} gives {v!r}, not a number or a bool")


def expected_value(item: TablesItem) -> Any:
    """What `query_table` returns when it answers `item` right: the count, the ids, the number,
    or true / false for a yes / no lookup."""
    if item.answer.kind == "id":
        return item.answer.value == "yes"
    return item.answer.value


def _rejection(q: TableQuery, db: ViewDB) -> tuple[str | None, list[dict]]:
    """(why the draw is rejected or None, the matched rows with provenance)."""
    n = run_query(db, q.table, q.filters, "count").count
    if n == 0:
        return "zero matches", []
    if q.op == "list" and len(run_query(db, q.table, q.filters, "list").ids) > MAX_LIST:
        return f"list over {MAX_LIST}", []
    if q.op == "count" and n > MAX_COUNT:
        return f"count over {MAX_COUNT}", []
    if q.op == "lookup" and n != 1:
        return "lookup matches more than one row", []
    out = run_query(db, q.table, q.filters, "lookup", limit=QUERY_LIMIT_MAX)
    if out.truncated:
        return "too many rows to cite", []
    return None, out.rows


def _spans(prov: Any) -> list[dict]:
    return [p for p in (prov if isinstance(prov, list) else [prov])
            if isinstance(p, dict) and p.get("start") is not None and p.get("end") is not None]


def _evidence(store: Store, q: TableQuery, matched: list[dict]) -> list[Evidence] | None:
    """One Evidence per distinct span of the matched rows' drawn columns (a row with none
    gives its section heading), sliced from the document text; None when a stored quote does
    not re-slice."""
    columns = [k.split("__", 1)[0] for k in q.filters] + ([q.field] if q.field else [])
    spans: dict[tuple[str, int, int], str | None] = {}
    for r in matched:
        found = [p for c in columns for p in _spans(r["prov"].get(c))] \
            or _spans(r["prov"].get("section"))
        for p in found:
            spans[(r["doc_id"], p["start"], p["end"])] = p.get("quote")
    out = []
    for (doc, start, end), quote in sorted(spans.items()):
        text = store.text(doc)[start:end]
        if quote is not None and text != quote:
            return None
        out.append(Evidence(doc_id=doc, char_start=start, char_end=end, quote=text))
    return out


def _created(rows: dict[str, list[RowRecord]]) -> datetime:
    """The newest eCFR version date among the rows (the version in force), at 00:00 UTC."""
    versions = sorted({r.row.get("version") for recs in rows.values() for r in recs
                       if isinstance(r.row.get("version"), str)})
    try:
        d = date.fromisoformat(versions[-1])
    except (IndexError, ValueError):
        return EPOCH
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


# -- generation ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Generation:
    items: list[TablesItem]
    rejected: list[dict]           # each distinct draw not kept: its query and the reason
    counts: dict = field(default_factory=dict)   # draws, duplicates, calls made/cached/failed


def generate_all(store_path: Path, facts_id: str, client, n: int = N_ITEMS, seed: int = SEED
                 ) -> Generation:
    """Up to `n` items from the second-pass facts `facts_id` of the store, with the draws that
    were rejected. `client` is a cached client (or a `MeteredClient` over one): the phrasing
    call stores an input rejection as a failure (`cache_failures=True`)."""
    store_path = Path(store_path)
    store = Store.open(store_path)
    rows = fact_rows(store_path, load_facts(store_path, facts_id), units(store))
    cs = contracts()
    db = ViewDB.from_rows(cs, rows)
    plain = {t: [r.row for r in sorted(rows.get(t, []), key=lambda r: sort_key(cs[t], r.row))]
             for t in TABLES}
    fields = {t: fact_fields(plain[t]) for t in TABLES}
    drawable = [t for t in TABLES if plain[t] and fields[t]]
    system = load_prompt()
    created = _created(rows)
    rng = random.Random(seed)
    items: list[TablesItem] = []
    rejected: list[dict] = []
    seen: set[str] = set()
    counts = Counter(dict.fromkeys(("draws", "unusable", "duplicates"), 0))
    calls = {"made": 0, "cached": 0, "failed": 0}
    for _ in range(DRAWS_PER_ITEM * n if drawable else 0):
        if len(items) >= n:
            break
        table = rng.choice(drawable)
        drawn = draw_table_filter(plain[table], fields[table], rng)
        counts["draws"] += 1
        if drawn is None:
            counts["unusable"] += 1
            continue
        filters, op, lookup = drawn
        q = TableQuery(table=table, op=op, filters=filters, field=lookup)
        key = json.dumps([table, op, filters, lookup], sort_keys=True)
        if key in seen:
            counts["duplicates"] += 1
            continue
        seen.add(key)
        reason, matched = _rejection(q, db)
        evidence = None if reason else _evidence(store, q, matched)
        if reason is None and evidence is None:
            reason = "evidence does not re-slice"
        if reason is None:
            try:
                c = client.complete(system, phrasing_message(q, cs), max_tokens=MAX_TOKENS,
                                    cache_failures=True)
            except CachedFailure:
                calls["failed"] += 1
                reason = "input rejected"
            else:
                calls["cached" if c.cached else "made"] += 1
                try:
                    question = _reply(c.text, ("question",), ("question",))["question"].strip()
                except ModelOutputError:
                    reason = "malformed phrasing"
        if reason is not None:
            rejected.append({"table": table, "op": op, "filters": filters, "field": lookup,
                             "reason": reason})
            continue
        item_id = f"gov-tables-{len(items) + 1:03d}"
        items.append(TablesItem(
            id=item_id, corpus="gov-tables", snapshot=store.snapshot_id, facts=facts_id,
            qtype=op, question=question, answer=answer_of(q, db), query=q, evidence=evidence,
            split=assign_split(item_id),
            provenance=Provenance(model=c.model, prompt_hash=prompt_hash(), seed=seed,
                                  created=created),
            status="auto_verified"))
    counts.update(items=len(items), rejected=len(rejected))
    return Generation(items, rejected, {**dict(sorted(counts.items())), "calls": calls})


def generate(store_path: Path, facts_id: str, client, n: int = N_ITEMS, seed: int = SEED
             ) -> list[TablesItem]:
    """Up to `n` items (`generate_all` without the rejected draws)."""
    return generate_all(store_path, facts_id, client, n, seed).items


# -- files ---------------------------------------------------------------------------------------


def _line(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False) + "\n"


def write_items(directory: Path, items: list[TablesItem], rejected: list[dict]) -> None:
    """`items.jsonl` (sorted by id) and `rejected.jsonl` (in draw order) under `directory`."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "items.jsonl").write_text(
        "".join(_line(i.model_dump(mode="json")) for i in sorted(items, key=lambda i: i.id)),
        encoding="utf-8")
    (directory / "rejected.jsonl").write_text("".join(_line(r) for r in rejected),
                                              encoding="utf-8")


def load_items(path: Path | None = None) -> list[TablesItem]:
    """The items of `path` (default: `GOLDEN_DIR / "items.jsonl"`, read when called)."""
    path = GOLDEN_DIR / "items.jsonl" if path is None else Path(path)
    return [TablesItem.model_validate_json(line)
            for line in jsonl_lines(path.read_text(encoding="utf-8"))]
