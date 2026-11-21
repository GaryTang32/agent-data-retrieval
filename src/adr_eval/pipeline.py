"""Per-item evaluation pipeline: metered model calls, budget, and one result row per repeat.

Retrieval has already run (in the runner's main thread); each repeat here generates a
query (G2), answers from the retrieved chunks, and scores the answer exactly or with the
judge. Judge validation calls run on repeat 0 only. Replies are parsed with the recovering JSON
parser (the context's Judge should be built with `recover=True`); each row lists the stages
that needed it in "json_recovered".

A typed system (`Context.typed`, Phase 3 `p3-typed`) answers with the generated query
instead: no answer call, no judge, exact scoring only, no retrieval metrics.

Tables mode (`Context.mode == "tables"`, the gov-tables set, Phase 3 spec §10.3, §11): the query
is a `TableQuery` from `generate_table_query` (one prompt and schema text for every system, so a
cached call serves them all), scored against the item's gold query (`Context.table_queries`);
a typed system answers it through `query_table`, a chunk system answers from its chunks as
above. With `judge_enabled=False` (tables mode) no judge, proxy or self-consistency call is
made: every answer is scored exactly. In tables mode only an input rejection stored as a
failure (CachedFailure) or a malformed reply (ModelOutputError) becomes an "error" row; every
other model failure propagates and stops the run (ruling P21).
"""

from __future__ import annotations

import re
import threading
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Literal

from adr_eval.answer.answerer import answer_question
from adr_eval.answer.query_gen import generate_query, generate_table_query
from adr_eval.golden.records import exec_gold_query
from adr_eval.golden.tables import TableQuery, describe_text
from adr_eval.llm import (
    CachedFailure,
    Completion,
    ModelClient,
    ModelError,
    ModelOutputError,
    _CachedClient,
    cost_usd,
    parse_json,
    price_entry,
)
from adr_eval.models import Evidence, GoldenItem, GoldQuery
from adr_eval.retrieval.chunker import Chunk
from adr_eval.retrieval.index import HybridIndex
from adr_eval.scoring import retrieval_metrics as rm
from adr_eval.scoring.exact import exact_outcome, normalize_value
from adr_eval.scoring.judge import Judge, label_to_outcome

K = 10
EXACT_TO_JUDGE = {"correct": "correct", "wrong": "incorrect"}
_PROXY_KINDS = {"number", "set", "id"}


class BudgetExceeded(Exception):  # noqa: N818 - a stop signal, not an error
    pass


# -- cost and budget --------------------------------------------------------------------


def model_id(client: ModelClient) -> str:
    return getattr(client, "model", client.name)


def estimate_tokens(system: str, user: str, max_tokens: int) -> tuple[int, int]:
    """Prompt length / 4 tokens in, `max_tokens` out."""
    return (len(system) + len(user)) // 4, max_tokens


def price_usd(model: str, tokens_in: int, tokens_out: int, prices: dict,
              provider: str = "") -> float:
    """Dollars at the table price; 0.0 for unpriced or subscription-billed models."""
    p = price_entry(model, prices, provider)
    if p is None or "input_per_mtok" not in p:
        return 0.0
    return (tokens_in * p["input_per_mtok"] + tokens_out * p["output_per_mtok"]) / 1_000_000


def completion_cost(c: Completion, prices: dict) -> float:
    """`cost_usd`, except that an unpriced stub completion (a stub model, or any model of the
    cached stub client) costs nothing."""
    if (c.model == "stub" or c.provider == "stub") and c.model not in prices \
            and "stub" not in prices:
        return 0.0
    return cost_usd(c, prices)


class Budget:
    """Thread-safe spend and call tracker; reservations keep concurrent calls under the caps.

    `max_dollars` caps table-priced spend; `max_calls` caps model calls that reach a model
    (cache hits are not calls). `stop_reason` is "budget" or "calls" once stopped.

    `count_attempts=False` (Phase 0) counts one unit per call, whatever its transport retries.
    With `count_attempts=True` (every Phase 3 command that calls a model) a `MeteredClient`
    over a cached client reserves one unit before every transport attempt, retries included
    (`attempt`), so real use never exceeds `max_calls`; a `MeteredClient` refuses (TypeError)
    a client that has no per-attempt hook.
    """

    def __init__(self, max_dollars: float | None, max_calls: int | None = None, *,
                 count_attempts: bool = False):
        self.max_dollars = max_dollars
        self.max_calls = max_calls
        self.count_attempts = count_attempts
        self.spent = 0.0
        self.calls = 0
        self.stopped = False
        self.stop_reason: str | None = None
        self._reserved = 0.0
        self._reserved_calls = 0
        self._lock = threading.Lock()

    def _stop(self, reason: str, message: str) -> None:
        self.stopped, self.stop_reason = True, reason
        raise BudgetExceeded(message)

    def reserve(self, estimate: float, call: bool = True) -> None:
        with self._lock:
            if self.stopped:
                raise BudgetExceeded("budget already exhausted")
            if (self.max_dollars is not None
                    and self.spent + self._reserved + estimate > self.max_dollars):
                self._stop("budget", f"next call (~${estimate:.4f}) would exceed --max-dollars "
                                     f"{self.max_dollars} (spent ${self.spent:.4f})")
            if (call and self.max_calls is not None
                    and self.calls + self._reserved_calls + 1 > self.max_calls):
                self._stop("calls", f"next call would exceed --max-calls {self.max_calls}")
            self._reserved += estimate
            self._reserved_calls += call

    def attempt(self) -> None:
        """Take one unit for a transport attempt about to run; BudgetExceeded when it would
        exceed `max_calls`. The unit is spent whether the attempt succeeds or not."""
        with self._lock:
            if self.stopped:
                raise BudgetExceeded("budget already exhausted")
            if self.max_calls is not None \
                    and self.calls + self._reserved_calls + 1 > self.max_calls:
                self._stop("calls", f"next attempt would exceed --max-calls {self.max_calls}")
            self.calls += 1

    def settle(self, estimate: float, cost: float, call: bool = True,
               made_call: bool = True) -> None:
        with self._lock:
            self._reserved -= estimate
            self._reserved_calls -= call
            self.spent += cost
            self.calls += made_call


def stop_status(budget: Budget | None, error: BaseException | None = None) -> str:
    """The status line of a command that stopped with nothing written, shared by `adr` and
    `adr-eval`: at its cap (`error` None or BudgetExceeded) or on a model failure that is not
    cached (ruling P21), and the budget units `budget` used (`Budget.calls`: with
    `count_attempts` every transport attempt, retries included)."""
    if budget is None:   # a failure that escaped before any budget was attached
        return (f"status: stopped: {' '.join(str(error).split())}; nothing written.")
    if error is None or isinstance(error, BudgetExceeded):
        cap = (f"--max-dollars {budget.max_dollars}" if budget.stop_reason == "budget"
               else f"--max-calls {budget.max_calls}")
        head = f"stopped at {cap}"
    else:
        head = f"stopped: {' '.join(str(error).split())}"
    return (f"status: {head} ({budget.calls} budget unit(s) used); nothing written. "
            f"Completed calls are cached: rerun to continue.")


_ledger = threading.local()


class MeteredClient:
    """Checks the budget before each call and records each completion for the current row.

    `served_models` collects every model the provider reported answering (thread-safe).
    """

    def __init__(self, inner: ModelClient, budget: Budget, prices: dict):
        if budget.count_attempts and not isinstance(inner, _CachedClient):
            raise TypeError(f"count_attempts needs a client with per-attempt hooks (a cached "
                            f"client), not {type(inner).__name__}: its retries would go "
                            f"uncounted")
        self.inner, self.budget, self.prices = inner, budget, prices
        self.name, self.family, self.model = inner.name, inner.family, model_id(inner)
        self.served_models: set[str] = set()
        self._lock = threading.Lock()

    def complete(self, system: str, user: str, *, max_tokens: int, repeat: int = 0,
                 cache_failures: bool = False) -> Completion:
        """`inner.complete` under the budget. `cache_failures` is passed on (a stored failure
        is a cache hit: it reserves nothing). With `budget.count_attempts` each transport
        attempt takes its own unit (`Budget.attempt`)."""
        extra = {"cache_failures": True} if cache_failures else {}
        is_cached = getattr(self.inner, "is_cached", None)
        call = not (is_cached and is_cached(system, user, max_tokens=max_tokens, repeat=repeat,
                                            **extra))
        per_attempt = call and self.budget.count_attempts
        if per_attempt:
            extra["before_attempt"] = self.budget.attempt
        # a cache hit costs nothing, so it reserves nothing: a fully cached rerun never stops
        est = price_usd(self.model, *estimate_tokens(system, user, max_tokens), self.prices,
                        self.name) if call else 0.0
        unit = call and not per_attempt          # per-attempt units are taken as they run
        self.budget.reserve(est, unit)
        cost, made_call = 0.0, unit
        try:
            c = self.inner.complete(system, user, max_tokens=max_tokens, repeat=repeat, **extra)
            cost, made_call = completion_cost(c, self.prices), unit and not c.cached
        finally:
            self.budget.settle(est, cost, unit, made_call)
        if c.served_model is not None:
            with self._lock:
                self.served_models.add(c.served_model)
        entries = getattr(_ledger, "entries", None)
        if entries is not None:
            entries.append((c, cost))
        return c


# -- scoring helpers --------------------------------------------------------------------


def field_hits(gold: GoldQuery, gen: GoldQuery | None) -> dict[str, bool]:
    if gen is None:
        return dict.fromkeys(("store", "op", "filters", "entities", "as_of"), False)
    return {
        "store": gen.store == gold.store,
        "op": gen.op == gold.op,
        "filters": gen.filters == gold.filters,
        "entities": sorted(map(normalize_value, gen.entities))
        == sorted(map(normalize_value, gold.entities)),
        "as_of": gen.as_of == gold.as_of,
    }


def table_field_hits(gold: TableQuery | None, gen: TableQuery | None) -> dict[str, bool]:
    """Per part of a table query (table, op, filters, field): whether the generated one
    equals the gold one; all False without a generated query."""
    parts = ("table", "op", "filters", "field")
    if gen is None or gold is None:
        return dict.fromkeys(parts, False)
    return {p: getattr(gen, p) == getattr(gold, p) for p in parts}


def route(q: GoldQuery) -> str:
    """The retrieval route a query implies (spec §6)."""
    if q.store == "typed_db":
        return "records:" + q.op
    return {"lookup": "prose:fact", "explain": "prose:fact", "procedure": "prose:procedure",
            "abstain": "abstain"}.get(q.op, "prose:" + q.op)


def route_ok(gold: GoldQuery, gen: GoldQuery | None) -> bool | None:
    """None when the gold op is `abstain` (not knowable before retrieval); a missing generated
    query is wrong."""
    if gold.op == "abstain":
        return None
    return gen is not None and route(gen) == route(gold)


def _entity_words(entity: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", entity).lower()))


def _entity_match(a: frozenset[str], b: frozenset[str]) -> bool:
    return bool(a) and bool(b) and (a <= b or b <= a)


def entity_f1(gold: GoldQuery, gen: GoldQuery | None) -> float | None:
    """F1 of entity matches (word-set containment either way); None when the gold query lists
    no entities or its op is `abstain`; 0.0 when nothing is generated or nothing matches."""
    if not gold.entities or gold.op == "abstain":
        return None
    golds = [_entity_words(e) for e in gold.entities]
    gens = [_entity_words(e) for e in gen.entities] if gen is not None else []
    if not gens:
        return 0.0
    p = sum(any(_entity_match(g, x) for x in golds) for g in gens) / len(gens)
    r = sum(any(_entity_match(g, x) for x in gens) for g in golds) / len(golds)
    return 2 * p * r / (p + r) if p + r else 0.0


def exec_match(gold: GoldQuery, gen: GoldQuery | None, records: list[dict]) -> bool | None:
    """None when the gold query is not executable; else whether both results agree."""
    if gold.store != "typed_db":
        return None
    expected = exec_gold_query(gold, records)
    if expected is None:
        return None
    if gen is None:
        return False
    try:
        return exec_gold_query(gen, records) == expected
    except (ValueError, TypeError, KeyError):
        return False


def retrieval_scores(item: GoldenItem, ranked: list[Chunk],
                     groups: list[list[Evidence]]) -> dict | None:
    if item.qtype == "insufficient" or not item.evidence:
        return None
    return {
        "recall@10": rm.recall_at_k(ranked, groups, K),
        "ndcg@10": rm.ndcg_at_k(ranked, groups, K),
        "mrr": rm.mrr(ranked, groups),
        "full_coverage": rm.full_coverage(ranked, groups, K),
        "coverage@10": rm.coverage_at_k(ranked, groups, K),
        "tokens@10": rm.tokens_at_k(ranked, K),
        "n_spans": len(item.evidence),
    }


# -- the pipeline -----------------------------------------------------------------------


@dataclass
class Context:
    index: HybridIndex
    records: list[dict]
    schema: dict[str, str]
    generator: ModelClient
    judge: Judge | None      # None in tables mode (`judge_enabled` False)
    # evidence groups by item id (`scoring.evidence_groups.build_all`); an item missing here
    # is scored with each evidence span as its own group
    groups: dict[str, list[list[Evidence]]] = field(default_factory=dict)
    # a typed system's answer to a generated query: (value, tool error); None for the chunk path
    # (a TableQuery in tables mode)
    typed: Callable[[Any], tuple[Any, str | None]] | None = None
    # "tables": the gov-tables set (table queries); "v0.1": the v0.1 golden sets
    mode: Literal["v0.1", "tables"] = "v0.1"
    # False: no judge, proxy or self-consistency call (every answer scored exactly)
    judge_enabled: bool = True
    # tables mode: each item's gold query by item id
    table_queries: dict[str, TableQuery] = field(default_factory=dict)

    def groups_for(self, item: GoldenItem) -> list[list[Evidence]]:
        return self.groups.get(item.id) or [[e] for e in item.evidence]


def _recovered(c: Completion) -> bool:
    """Whether a reply that was parsed needed `parse_json_recovering`'s fallback, i.e. is
    not one JSON object by itself (the recovering parser tries `parse_json` first)."""
    try:
        parse_json(c.text)
    except ModelOutputError:
        return True
    return False


def _judge_check(item: GoldenItem, candidate: Any, repeat: int, purpose: str,
                 ctx: Context, recovered: set[str]) -> dict:
    try:
        label, reason, comp = ctx.judge.judge(item.question, item.answer, candidate,
                                              repeat=repeat)
    except ModelError as e:
        return {"purpose": purpose, "label": None, "reason": None, "error": str(e)}
    if _recovered(comp):
        recovered.add("judge_check")
    return {"purpose": purpose, "label": label, "reason": reason, "error": None}


def process_repeat(item: GoldenItem, repeat: int, hits: list[tuple[str, float]],
                   ctx: Context) -> dict:
    """One result row. ModelError → outcome "error" (in tables mode only CachedFailure and
    ModelOutputError; any other ModelError propagates); BudgetExceeded propagates.

    With `ctx.typed` the generated query is answered by `ctx.typed` and scored exactly
    (`typed_error` holds the tool's refusal, `metrics` is None)."""
    _ledger.entries = entries = []
    ranked = [ctx.index.chunks[cid] for cid, _ in hits]
    groups = ctx.groups_for(item)
    row: dict[str, Any] = {
        "item_id": item.id, "repeat": repeat, "qtype": item.qtype, "rarity": item.rarity,
        "retrieved": [[cid, score] for cid, score in hits],
        "generated_query": None, "gold_query_field_hits": None, "query_exact": None,
        "query_exec_match": None, "route_ok": None, "entity_f1": None, "answer": None,
        "outcome": "error", "judge_label": None, "judge_reason": None, "judge_check": None,
        "metrics": retrieval_scores(item, ranked, groups), "citation": None,
        "tokens": None, "cost_usd": 0.0, "notional_cost_usd": None, "served_models": [],
        "latency_s": None, "error": None, "json_recovered": [],
    }
    if ctx.typed is not None:
        row.update(metrics=None, typed_error=None)
    recovered: set[str] = set()  # stages whose reply was parsed by the recovering parser
    stage = "query_gen"
    tables = ctx.mode == "tables"
    # tables mode: only a stored input rejection or a malformed reply is an error row (P21)
    row_errors = (CachedFailure, ModelOutputError) if tables else ModelError
    try:
        if tables:
            tq, qc = generate_table_query(item.question, describe_text(), ctx.generator,
                                          repeat, recover=True)
            gq = tq
            if tq is not None and _recovered(qc):
                recovered.add("query")
            hits_ = table_field_hits(ctx.table_queries.get(item.id), tq)
            row.update(generated_query=tq.model_dump(mode="json") if tq else None,
                       gold_query_field_hits=hits_, query_exact=all(hits_.values()))
        else:
            gq, qc = generate_query(item.question, item.as_of, ctx.schema, ctx.generator,
                                    repeat, recover=True)
            if gq is not None and _recovered(qc):
                recovered.add("query")
            hits_ = field_hits(item.gold_query, gq)
            row.update(generated_query=gq.model_dump(mode="json") if gq else None,
                       gold_query_field_hits=hits_, query_exact=all(hits_.values()),
                       query_exec_match=exec_match(item.gold_query, gq, ctx.records),
                       route_ok=route_ok(item.gold_query, gq),
                       entity_f1=entity_f1(item.gold_query, gq))
        if ctx.typed is not None:
            stage = "typed"
            value, row["typed_error"] = ctx.typed(gq)
            row["answer"] = {"value": value, "kind": item.answer.kind, "citations": [],
                             "abstain": False, "confidence": None}
            row["outcome"] = exact_outcome(item.answer,
                                           SimpleNamespace(value=value, abstain=False))
        else:
            stage = "answer"
            sa = answer_question(item.question, item.as_of, ranked, ctx.generator, repeat,
                                 recover=True)
            if _recovered(sa.completion):
                recovered.add("answer")
            row["answer"] = {"value": sa.value, "kind": sa.kind, "citations": sa.citations,
                             "abstain": sa.abstain, "confidence": sa.confidence}
            row["latency_s"] = None if sa.completion.cached else sa.completion.latency_s
            if item.evidence and not sa.abstain:
                cited = [ctx.index.chunks[c] for c in sa.citations]
                row["citation"] = {"precision": rm.citation_precision(cited, groups),
                                   "evidence_cited": rm.evidence_cited(cited, groups)}
            stage = "judge"
            outcome = exact_outcome(item.answer, sa)
            if outcome is None and not ctx.judge_enabled:
                raise ModelOutputError(f"a {item.answer.kind} answer needs the judge, which "
                                       f"this run does not call")
            if outcome is None:
                label, reason, jc = ctx.judge.judge(item.question, item.answer, sa.value)
                if _recovered(jc):
                    recovered.add("judge")
                row.update(judge_label=label, judge_reason=reason)
                outcome = label_to_outcome(label)
                if repeat == 0:
                    row["judge_check"] = _judge_check(item, sa.value, 1, "self_consistency", ctx,
                                                     recovered)
            elif ctx.judge_enabled and repeat == 0 and item.answer.kind in _PROXY_KINDS \
                    and outcome in EXACT_TO_JUDGE:
                row["judge_check"] = _judge_check(item, sa.value, 0, "proxy", ctx, recovered)
            row["outcome"] = outcome
    except row_errors as e:
        row["outcome"], row["error"] = "error", f"{stage}: {e}"
    finally:
        _ledger.entries = None
    row["json_recovered"] = sorted(recovered)
    row["tokens"] = {"in": sum(c.input_tokens for c, _ in entries),
                     "out": sum(c.output_tokens for c, _ in entries)}
    row["cost_usd"] = sum(cost for _, cost in entries)
    row["served_models"] = sorted({c.served_model for c, _ in entries if c.served_model})
    notional = [c for c, _ in entries if c.notional_cost_usd is not None]
    if notional:  # informational (subscription billing); never counted toward --max-dollars
        row["notional_cost_usd"] = sum(0.0 if c.cached else c.notional_cost_usd
                                       for c in notional)
    return row


def process_item(item: GoldenItem, retrieved: list[list[tuple[str, float]]],
                 ctx: Context) -> list[dict]:
    """Rows for every repeat; on a budget stop, the rows completed so far."""
    rows = []
    for repeat, hits in enumerate(retrieved):
        try:
            rows.append(process_repeat(item, repeat, hits, ctx))
        except BudgetExceeded:
            break
    return rows
