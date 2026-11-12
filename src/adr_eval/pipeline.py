"""Per-item evaluation pipeline: metered model calls, budget, and one result row per repeat.

Retrieval has already run (in the runner's main thread); each repeat here generates a
query (G2), answers from the retrieved chunks, and scores the answer exactly or with the
judge. Judge validation calls run on repeat 0 only. Replies are parsed with the recovering JSON
parser (the context's Judge should be built with `recover=True`); each row lists the stages
that needed it in "json_recovered".
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from adr_eval.answer.answerer import answer_question
from adr_eval.answer.query_gen import generate_query
from adr_eval.golden.records import exec_gold_query
from adr_eval.llm import (
    Completion,
    ModelClient,
    ModelError,
    ModelOutputError,
    cost_usd,
    parse_json,
    price_entry,
)
from adr_eval.models import GoldenItem, GoldQuery
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
    """`cost_usd`, except that an unpriced stub completion costs nothing."""
    if c.model == "stub" and "stub" not in prices:
        return 0.0
    return cost_usd(c, prices)


class Budget:
    """Thread-safe spend and call tracker; reservations keep concurrent calls under the caps.

    `max_dollars` caps table-priced spend; `max_calls` caps model calls that reach a model
    (cache hits are not calls). `stop_reason` is "budget" or "calls" once stopped.
    """

    def __init__(self, max_dollars: float | None, max_calls: int | None = None):
        self.max_dollars = max_dollars
        self.max_calls = max_calls
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

    def settle(self, estimate: float, cost: float, call: bool = True,
               made_call: bool = True) -> None:
        with self._lock:
            self._reserved -= estimate
            self._reserved_calls -= call
            self.spent += cost
            self.calls += made_call


_ledger = threading.local()


class MeteredClient:
    """Checks the budget before each call and records each completion for the current row.

    `served_models` collects every model the provider reported answering (thread-safe).
    """

    def __init__(self, inner: ModelClient, budget: Budget, prices: dict):
        self.inner, self.budget, self.prices = inner, budget, prices
        self.name, self.family, self.model = inner.name, inner.family, model_id(inner)
        self.served_models: set[str] = set()
        self._lock = threading.Lock()

    def complete(self, system: str, user: str, *, max_tokens: int, repeat: int = 0) -> Completion:
        is_cached = getattr(self.inner, "is_cached", None)
        call = not (is_cached and is_cached(system, user, max_tokens=max_tokens, repeat=repeat))
        # a cache hit costs nothing, so it reserves nothing: a fully cached rerun never stops
        est = price_usd(self.model, *estimate_tokens(system, user, max_tokens), self.prices,
                        self.name) if call else 0.0
        self.budget.reserve(est, call)
        cost, made_call = 0.0, call
        try:
            c = self.inner.complete(system, user, max_tokens=max_tokens, repeat=repeat)
            cost, made_call = completion_cost(c, self.prices), not c.cached
        finally:
            self.budget.settle(est, cost, call, made_call)
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


def retrieval_scores(item: GoldenItem, ranked: list[Chunk]) -> dict | None:
    if item.qtype == "insufficient" or not item.evidence:
        return None
    return {
        "recall@10": rm.recall_at_k(ranked, item.evidence, K),
        "ndcg@10": rm.ndcg_at_k(ranked, item.evidence, K),
        "mrr": rm.mrr(ranked, item.evidence),
        "full_coverage": rm.full_coverage(ranked, item.evidence, K),
        "n_spans": len(item.evidence),
    }


# -- the pipeline -----------------------------------------------------------------------


@dataclass
class Context:
    index: HybridIndex
    records: list[dict]
    schema: dict[str, str]
    generator: ModelClient
    judge: Judge


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
    """One result row. ModelError → outcome "error"; BudgetExceeded propagates."""
    _ledger.entries = entries = []
    ranked = [ctx.index.chunks[cid] for cid, _ in hits]
    row: dict[str, Any] = {
        "item_id": item.id, "repeat": repeat, "qtype": item.qtype, "rarity": item.rarity,
        "retrieved": [[cid, score] for cid, score in hits],
        "generated_query": None, "gold_query_field_hits": None, "query_exact": None,
        "query_exec_match": None, "answer": None, "outcome": "error",
        "judge_label": None, "judge_reason": None, "judge_check": None,
        "metrics": retrieval_scores(item, ranked), "citation": None,
        "tokens": None, "cost_usd": 0.0, "notional_cost_usd": None, "served_models": [],
        "latency_s": None, "error": None, "json_recovered": [],
    }
    recovered: set[str] = set()  # stages whose reply was parsed by the recovering parser
    stage = "query_gen"
    try:
        gq, qc = generate_query(item.question, item.as_of, ctx.schema, ctx.generator, repeat,
                                recover=True)
        if gq is not None and _recovered(qc):
            recovered.add("query")
        hits_ = field_hits(item.gold_query, gq)
        row.update(generated_query=gq.model_dump(mode="json") if gq else None,
                   gold_query_field_hits=hits_, query_exact=all(hits_.values()),
                   query_exec_match=exec_match(item.gold_query, gq, ctx.records))
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
            row["citation"] = {"precision": rm.citation_precision(cited, item.evidence),
                               "evidence_cited": rm.evidence_cited(cited, item.evidence)}
        stage = "judge"
        outcome = exact_outcome(item.answer, sa)
        if outcome is None:
            label, reason, jc = ctx.judge.judge(item.question, item.answer, sa.value)
            if _recovered(jc):
                recovered.add("judge")
            row.update(judge_label=label, judge_reason=reason)
            outcome = label_to_outcome(label)
            if repeat == 0:
                row["judge_check"] = _judge_check(item, sa.value, 1, "self_consistency", ctx,
                                                 recovered)
        elif repeat == 0 and item.answer.kind in _PROXY_KINDS and outcome in EXACT_TO_JUDGE:
            row["judge_check"] = _judge_check(item, sa.value, 0, "proxy", ctx, recovered)
        row["outcome"] = outcome
    except ModelError as e:
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
