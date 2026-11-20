"""Phase 3 harness checks and comparisons (spec §10.2, 3A).

- `cache_inputs_unchanged`: Q1 reuses the baseline's generated queries from the model cache,
  keyed by (adapter, model, query-generation prompt, schema, question); the prompt and the
  record-schema text must be byte-identical to the baseline's (`QUERY_GEN_SHA256`,
  `SCHEMA_SHA256`), or the measurement would ask for new calls.
- `q1_compare`: a `p3-typed` run against a baseline run over the common `count_filter`
  items: accuracy of each, the discordant pairs, the exact McNemar test and every miss with
  its cause. Values are reported as numbers or list lengths, never as lists of ids.
- `also_in_readings`: the research `also_in` wording problem (§4.2): gold compares the
  `;`-joined string exactly, the questions read as membership; both counts per item.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from adr_eval.answer.query_gen import generate_query
from adr_eval.golden.records import exec_gold_query, filter_records
from adr_eval.llm import Completion
from adr_eval.models import GoldenItem
from adr_eval.runner import RunError
from adr_eval.scoring.stats import mcnemar_exact

SCHEMA_SHA256 = {"gov": "1a88b8fce3876640b72c5b752487e0b6682776bb6a4e5e296e5ace2c24cdeef6",
                 "research": "01c9cd8529b8b411be81bc5b516abd82919876ff07c496eb2019aa464f8104ca"}
QUERY_GEN_SHA256 = "249b0449466325d45b4c05813b8fbff7bf108070bb816feaf72cffc88d5997c6"
BASELINE_RUNS = {"gov": "runs/gov-baseline-linear-test-20261113T094503",
                 "research": "runs/research-baseline-linear-test-20261113T094721"}
TYPED_SYSTEM = "p3-typed"
_SCHEMA_HEAD, _QUESTION = "Record schema:\n", "\n\nQuestion: "


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _Capture:
    """A client that records the one prompt it is sent and calls no model."""

    name = family = model = "capture"

    def __init__(self):
        self.system = self.user = ""

    def complete(self, system: str, user: str, *, max_tokens: int, repeat: int = 0):
        self.system, self.user = system, user
        return Completion("{}", 0, 0, self.model, 0.0, False)


def cache_inputs_unchanged(corpus: str) -> list[str]:
    """The ways the query-generation message for `corpus` differs from the baseline's (empty
    when the prompt and the schema text are byte-identical). The message is the one
    `generate_query` builds now, captured without a model."""
    from adr_eval.corpora.registry import get_adapter

    want_schema = SCHEMA_SHA256.get(corpus)
    if want_schema is None:
        return [f"{corpus}: no recorded baseline schema"]
    capture = _Capture()
    generate_query("?", None, get_adapter(corpus).record_schema(), capture)
    problems = []
    got = _sha256(capture.system)
    if got != QUERY_GEN_SHA256:
        problems.append(f"{corpus}: the query-generation prompt has sha256 {got[:12]}, the "
                        f"baseline's {QUERY_GEN_SHA256[:12]}")
    head, sep, _ = capture.user.partition(_QUESTION)
    schema = head.removeprefix(_SCHEMA_HEAD) if sep and head.startswith(_SCHEMA_HEAD) else None
    got = None if schema is None else _sha256(schema)
    if got != want_schema:
        problems.append(f"{corpus}: the record schema text has sha256 "
                        f"{'(not found)' if got is None else got[:12]}, the baseline's "
                        f"{want_schema[:12]}")
    return problems


# -- Q1 ----------------------------------------------------------------------------------------

def _run(run_dir: Path) -> tuple[dict, dict[str, dict]]:
    """(config, repeat-0 count_filter rows by item id) of a run; a run with other repeats is
    refused (Q1 compares one reply per item)."""
    run_dir = Path(run_dir)
    try:
        cfg = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
        lines = (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError as e:
        raise RunError(f"{run_dir}: not a run directory (config.json, results.jsonl)") from e
    rows = [json.loads(x) for x in lines if x.strip()]
    if any(r["repeat"] != 0 for r in rows):
        raise RunError(f"{run_dir}: holds repeats other than repeat 0; Q1 compares repeat 0 "
                       f"of single-repeat runs")
    return cfg, {r["item_id"]: r for r in rows if r["qtype"] == "count_filter"}


def _shown(value: Any) -> Any:
    """A value as committed: a list by its length only (no ids)."""
    return {"n": len(value)} if isinstance(value, list) else value


def _value(row: dict) -> Any:
    return None if row.get("answer") is None else row["answer"].get("value")


def _typed_cause(row: dict) -> str:
    if row.get("error"):
        return f"error: {row['error']}"
    if row.get("generated_query") is None:
        return "no generated query"
    if row.get("typed_error"):
        return f"query refused: {row['typed_error']}"
    if row.get("query_exec_match") is False:
        return ("the generated query's result differs from the gold query's under the "
                "records semantics (the model's reading of the question)")
    return ("the tables differ from the records: the generated query matches the gold "
            "query's result over the records, the typed answer does not")


def _baseline_cause(row: dict) -> str:
    if row["outcome"] == "error":
        return f"error: {row.get('error')}"
    if row["outcome"] == "abstained":
        return "abstained"
    return "the answer from retrieved chunks"


def q1_compare(typed_run: Path, baseline_run: Path) -> dict:
    """Q1 (spec §10.2): a `p3-typed` run against a baseline run over their common
    count_filter items (repeat 0). `b` counts items the typed system gets right and the
    baseline wrong, `c` the reverse; `mcnemar_p` is the exact two-sided test on them. Each
    typed miss carries its generated query and cause, each baseline miss its outcome and
    cause."""
    tcfg, typed = _run(typed_run)
    bcfg, base = _run(baseline_run)
    if tcfg.get("system") != TYPED_SYSTEM:
        raise RunError(f"{typed_run}: not a {TYPED_SYSTEM} run (system "
                       f"{tcfg.get('system')!r})")
    ids = sorted(set(typed) & set(base))
    ok_t = {i: typed[i]["outcome"] == "correct" for i in ids}
    ok_b = {i: base[i]["outcome"] == "correct" for i in ids}
    b = sum(ok_t[i] and not ok_b[i] for i in ids)
    c = sum(ok_b[i] and not ok_t[i] for i in ids)
    n = len(ids)

    def side(ok: dict[str, bool], cfg: dict, rows: dict) -> dict:
        right = sum(ok.values())
        return {"system": cfg.get("system"), "correct": right,
                "accuracy": right / n if n else None, "n_run": len(rows)}

    return {
        "typed_run": Path(typed_run).name, "baseline_run": Path(baseline_run).name,
        "corpus": tcfg.get("corpus"), "split": tcfg.get("split"), "n": n,
        "typed": side(ok_t, tcfg, typed), "baseline": side(ok_b, bcfg, base),
        "b": b, "c": c, "mcnemar_p": mcnemar_exact(b, c),
        "only_typed": sorted(set(typed) - set(base)),
        "only_baseline": sorted(set(base) - set(typed)),
        "misses": [{"item_id": i, "outcome": typed[i]["outcome"],
                    "value": _shown(_value(typed[i])),
                    "generated_query": typed[i].get("generated_query"),
                    "typed_error": typed[i].get("typed_error"),
                    "query_exec_match": typed[i].get("query_exec_match"),
                    "cause": _typed_cause(typed[i])} for i in ids if not ok_t[i]],
        "baseline_misses": [{"item_id": i, "outcome": base[i]["outcome"],
                             "query_exec_match": base[i].get("query_exec_match"),
                             "cause": _baseline_cause(base[i])} for i in ids if not ok_b[i]],
    }


# -- the also_in readings ----------------------------------------------------------------------

def _topics(value: Any) -> list[str]:
    """The topics of an `also_in` string, as the typed `also_in_list` column splits it."""
    return [t.strip() for t in value.split(";") if t.strip()] if isinstance(value, str) else []


def also_in_readings(items: list[GoldenItem], records: list[dict]) -> list[dict]:
    """For each count_filter item whose gold query compares `also_in` exactly (v0.1): the
    count under that string reading (`string`, the frozen gold) and under the membership
    reading the questions use (`membership`: every topic of the value is one of the
    record's topics); a `list` item counts its ids. In item id order."""
    out = []
    for item in sorted(items, key=lambda i: i.id):
        gq = item.gold_query
        value = gq.filters.get("also_in")
        if item.qtype != "count_filter" or gq.store != "typed_db" or not isinstance(value, str):
            continue
        exact = exec_gold_query(gq, records)
        rest = {k: v for k, v in gq.filters.items() if k != "also_in"}
        want = set(_topics(value))
        member = [r for r in filter_records(records, rest) if want <= set(_topics(r.get(
            "also_in")))]
        n_member = len({str(r["id"]) for r in member}) if gq.op == "list" else len(member)
        n_exact = len(exact) if isinstance(exact, list) else exact
        out.append({"item_id": item.id, "split": item.split, "op": gq.op, "also_in": value,
                    "string": n_exact, "membership": n_member, "differs": n_exact != n_member})
    return out
