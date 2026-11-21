"""Phase 3 harness checks and comparisons (spec §10.2, 3A).

- `cache_inputs_unchanged`: Q1 reuses the baseline's generated queries from the model cache,
  keyed by (adapter, model, query-generation prompt, schema, question); the prompt and the
  record-schema text must be byte-identical to the baseline's (`QUERY_GEN_SHA256`,
  `SCHEMA_SHA256`), or the measurement would ask for new calls.
- `q1_compare`: a `p3-typed` run against a baseline run over the common `count_filter`
  items: accuracy of each, the discordant pairs, the exact McNemar test and every miss with
  its cause and generated query. It names items, so it stays in `runs/` (gitignored).
- `q1_summary`: the committed form of `q1_compare`: no item id and no filter value (no
  per-item rows are committed, spec §1); typed misses by cause and query shape, baseline
  misses and the `also_in` readings as counts.
- `also_in_readings`: the research `also_in` wording problem (§4.2): gold compares the
  `;`-joined string exactly, the questions read as membership; both counts per item.
- `q2_compare` / `q2_summary` (spec §12 Q2, 3B): a `p3-typed` run against a `baseline-linear`
  run over the test items of gov-tables v0.1: accuracies, the paired bootstrap interval of the
  accuracy difference (typed minus baseline), the pass flags, McNemar, and every miss with a
  gov-tables cause; the summary names no item, filter value or answer. Q1 (`q1_compare`)
  refuses gov-tables runs: its causes and the `also_in` readings are v0.1's.
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
from adr_eval.scoring.stats import mcnemar_exact, paired_bootstrap_ci

SCHEMA_SHA256 = {"gov": "1a88b8fce3876640b72c5b752487e0b6682776bb6a4e5e296e5ace2c24cdeef6",
                 "research": "01c9cd8529b8b411be81bc5b516abd82919876ff07c496eb2019aa464f8104ca"}
QUERY_GEN_SHA256 = "249b0449466325d45b4c05813b8fbff7bf108070bb816feaf72cffc88d5997c6"
BASELINE_RUNS = {"gov": "runs/gov-baseline-linear-test-20261113T094503",
                 "research": "runs/research-baseline-linear-test-20261113T094721"}
TYPED_SYSTEM = "p3-typed"
BASELINE_SYSTEM = "baseline-linear"
GOV_TABLES = "gov-tables"
Q2_MIN_ACCURACY = 0.80     # spec §12 Q2: p3-typed accuracy at least this
Q2_MARGIN = 0.02           # and the interval's lower bound above this
Q2_SEED, Q2_RESAMPLES = 20261108, 10_000
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

def _run(run_dir: Path, comparison: str) -> tuple[dict, dict[str, dict]]:
    """(config, repeat-0 count_filter rows by item id) of a run; a run that did not complete,
    or has other repeats, is refused (`comparison`, "Q1" or "Q2", compares one reply per item
    of a whole run, and its refusals say so)."""
    run_dir = Path(run_dir)
    try:
        cfg = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
        lines = (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError as e:
        raise RunError(f"{run_dir}: not a run directory (config.json, results.jsonl)") from e
    if cfg.get("status") != "complete":
        raise RunError(f"{run_dir}: status {cfg.get('status')!r}; {comparison} compares "
                       f"complete runs")
    rows = [json.loads(x) for x in lines if x.strip()]
    if any(r["repeat"] != 0 for r in rows):
        raise RunError(f"{run_dir}: holds repeats other than repeat 0; {comparison} compares "
                       f"repeat 0 of single-repeat runs")
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
    tcfg, typed = _run(typed_run, "Q1")
    bcfg, base = _run(baseline_run, "Q1")
    for path, cfg in ((typed_run, tcfg), (baseline_run, bcfg)):
        if cfg.get("golden_set", "v0.1") != "v0.1":
            raise RunError(f"{path}: a {cfg['golden_set']} run; Q1 compares v0.1 count_filter "
                           f"runs (its causes and also_in readings are v0.1's): use `adr-eval "
                           f"p3-q2` for gov-tables")
    if tcfg.get("system") != TYPED_SYSTEM:
        raise RunError(f"{typed_run}: not a {TYPED_SYSTEM} run (system "
                       f"{tcfg.get('system')!r})")
    for key in ("corpus", "split"):
        if tcfg.get(key) != bcfg.get(key):
            raise RunError(f"the runs are not comparable: {key} {tcfg.get(key)!r} "
                           f"({Path(typed_run).name}) against {bcfg.get(key)!r} "
                           f"({Path(baseline_run).name})")
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


def _query_shape(gq: dict | None) -> dict | None:
    """A generated query without its values: store, op and the sorted filter keys."""
    if gq is None:
        return None
    return {"store": gq.get("store"), "op": gq.get("op"),
            "filter_keys": sorted(gq.get("filters") or {})}


def _count_rows(rows: list[dict], keys: tuple[str, ...]) -> list[dict]:
    """`rows` counted by the values of `keys`, sorted by them."""
    counts: dict[str, dict] = {}
    for r in rows:
        group = {k: r[k] for k in keys}
        counts.setdefault(json.dumps(group, sort_keys=True), {**group, "n": 0})["n"] += 1
    return [counts[k] for k in sorted(counts)]


def q1_summary(c: dict) -> dict:
    """The committed form of a `q1_compare` result (with or without its `also_in`): the same
    counts, accuracies and McNemar test; each typed miss by outcome, cause, record match, tool
    error, value (a list by its length) and query shape; baseline misses and the items found
    in one run only as counts; the `also_in` readings by split, op and wording. No item id,
    filter value or entity."""
    misses = [{"outcome": m["outcome"], "cause": m["cause"],
               "query_exec_match": m["query_exec_match"], "typed_error": m["typed_error"],
               "value": _shown(m["value"]), "query": _query_shape(m["generated_query"])}
              for m in c["misses"]]
    out = {k: c[k] for k in ("typed_run", "baseline_run", "corpus", "split", "n", "typed",
                             "baseline", "b", "c", "mcnemar_p")}
    out.update(
        only_typed=len(c["only_typed"]), only_baseline=len(c["only_baseline"]),
        misses=sorted(misses, key=lambda m: json.dumps(m, sort_keys=True)),
        baseline_misses=_count_rows(c["baseline_misses"],
                                    ("outcome", "cause", "query_exec_match")))
    if "also_in" in c:
        out["also_in"] = [{k: a[k] for k in ("split", "op", "wording", "string", "membership",
                                             "differs")} for a in c["also_in"]]
    return out


# -- the also_in readings ----------------------------------------------------------------------

def _topics(value: Any) -> list[str]:
    """The topics of an `also_in` string, as the typed `also_in_list` column splits it."""
    return [t.strip() for t in value.split(";") if t.strip()] if isinstance(value, str) else []


def also_in_readings(items: list[GoldenItem], records: list[dict]) -> list[dict]:
    """For each count_filter item whose gold query compares `also_in` exactly (v0.1): the
    count under that string reading (`string`, the frozen gold) and under the membership
    reading (`membership`: every topic of the value is one of the record's topics); a
    `list` item counts its ids. `wording` is "value" for a question that asks for an
    "also_in value" (the string reading is its own), else "membership" ("also cited by").
    In item id order."""
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
        wording = "value" if "also_in value" in item.question.casefold() else "membership"
        out.append({"item_id": item.id, "split": item.split, "op": gq.op, "also_in": value,
                    "wording": wording, "string": n_exact, "membership": n_member,
                    "differs": n_exact != n_member})
    return out



# -- Q2: gov-tables v0.1 (3B) ---------------------------------------------------------------------

_QUERY_PARTS = ("table", "op", "filters", "field")


def _typed_tables_cause(row: dict) -> str:
    """Why a p3-typed gov-tables row is not correct: an error, an unparseable query, a refused
    query (an unknown column named apart), a query that differs from the gold one, or a query
    equal to the gold one whose answer differs (the tables differ from the second-pass facts)."""
    if row["outcome"] == "error":
        return "error"
    if row.get("generated_query") is None:
        return "unparseable query"
    if row.get("typed_error") and row["typed_error"] != "truncated":
        return ("unknown column" if row["typed_error"].startswith("unknown column")
                else "query refused")
    if not row.get("query_exact"):
        return "query differs from gold"
    return "query equals gold, wrong value"


def _baseline_tables_cause(row: dict) -> str:
    if row["outcome"] in ("error", "abstained"):
        return row["outcome"]
    if row.get("generated_query") is None:
        return "wrong value (unparseable query)"
    return "wrong value"


def _differs(row: dict) -> list[str]:
    """The parts of the generated table query that differ from the gold one."""
    hits = row.get("gold_query_field_hits") or {}
    return [p for p in _QUERY_PARTS if hits.get(p) is False]


def _tables_shape(q: dict | None) -> dict | None:
    """A generated table query without its values: table, op, sorted filter keys, field."""
    if q is None:
        return None
    return {"table": q.get("table"), "op": q.get("op"),
            "filter_keys": sorted(q.get("filters") or {}), "field": q.get("field")}


def q2_compare(typed_run: Path, baseline_run: Path) -> dict:
    """Q2 (spec §12): a `p3-typed` run against a `baseline-linear` run, both complete
    single-repeat test-split runs of the same gov-tables v0.1 file (`golden_sha256`) over the
    same items. Each item scores 1 when correct, else 0 (an error is 0). `ci` is
    `paired_bootstrap_ci(baseline, typed)` (mean of typed minus baseline, 95%, seed 20261108,
    10,000 resamples); Q2 passes when the typed accuracy is at least 0.80 and the lower bound is
    above +0.02. `b` counts items only the typed system gets right, `c` the reverse, and
    `mcnemar_p` is the exact test on them. Each miss carries its cause."""
    tcfg, typed = _run(typed_run, "Q2")
    bcfg, base = _run(baseline_run, "Q2")
    for path, cfg, system in ((typed_run, tcfg, TYPED_SYSTEM),
                              (baseline_run, bcfg, BASELINE_SYSTEM)):
        if cfg.get("golden_set") != GOV_TABLES:
            raise RunError(f"{path}: not a {GOV_TABLES} run (golden set "
                           f"{cfg.get('golden_set', 'v0.1')!r}); Q2 compares gov-tables runs")
        if cfg.get("system") != system:
            raise RunError(f"{path}: not a {system} run (system {cfg.get('system')!r})")
        if cfg.get("split") != "test":
            raise RunError(f"{path}: split {cfg.get('split')!r}; Q2 is measured on the test "
                           f"split")
    if tcfg.get("golden_sha256") != bcfg.get("golden_sha256"):
        raise RunError(f"the runs are not comparable: golden set "
                       f"{str(tcfg.get('golden_sha256'))[:12]} ({Path(typed_run).name}) against "
                       f"{str(bcfg.get('golden_sha256'))[:12]} ({Path(baseline_run).name})")
    if set(typed) != set(base) or not typed:
        raise RunError(f"the runs cover different items: {len(set(typed) - set(base))} only in "
                       f"{Path(typed_run).name}, {len(set(base) - set(typed))} only in "
                       f"{Path(baseline_run).name}" if typed else
                       f"{typed_run}: no items to compare")
    ids = sorted(typed)
    t = [1.0 if typed[i]["outcome"] == "correct" else 0.0 for i in ids]
    x = [1.0 if base[i]["outcome"] == "correct" else 0.0 for i in ids]
    diff, lo, hi = paired_bootstrap_ci(x, t, n=Q2_RESAMPLES, seed=Q2_SEED)
    b = sum(ti == 1.0 and xi == 0.0 for ti, xi in zip(t, x, strict=True))
    c = sum(xi == 1.0 and ti == 0.0 for ti, xi in zip(t, x, strict=True))
    n = len(ids)
    acc_t, acc_b = sum(t) / n, sum(x) / n
    return {
        "typed_run": Path(typed_run).name, "baseline_run": Path(baseline_run).name,
        "golden_sha256": tcfg.get("golden_sha256"), "facts": tcfg.get("facts"), "n": n,
        "typed": {"system": TYPED_SYSTEM, "correct": int(sum(t)), "accuracy": acc_t},
        "baseline": {"system": BASELINE_SYSTEM, "correct": int(sum(x)), "accuracy": acc_b},
        "difference": {"mean": diff, "ci95": [lo, hi], "seed": Q2_SEED,
                       "resamples": Q2_RESAMPLES},
        "thresholds": {"min_accuracy": Q2_MIN_ACCURACY, "margin": Q2_MARGIN},
        "accuracy_ok": acc_t >= Q2_MIN_ACCURACY, "margin_ok": lo > Q2_MARGIN,
        "passed": acc_t >= Q2_MIN_ACCURACY and lo > Q2_MARGIN,
        "b": b, "c": c, "mcnemar_p": mcnemar_exact(b, c),
        "misses": [{"item_id": i, "outcome": typed[i]["outcome"],
                    "cause": _typed_tables_cause(typed[i]), "differs": _differs(typed[i]),
                    "typed_error": typed[i].get("typed_error"), "error": typed[i].get("error"),
                    "value": _value(typed[i]), "generated_query": typed[i].get("generated_query")}
                   for i in ids if typed[i]["outcome"] != "correct"],
        "baseline_misses": [{"item_id": i, "outcome": base[i]["outcome"],
                             "cause": _baseline_tables_cause(base[i]),
                             "error": base[i].get("error"), "value": _value(base[i])}
                            for i in ids if base[i]["outcome"] != "correct"],
    }


def q2_summary(c: dict) -> dict:
    """The committed form of a `q2_compare` result: the counts, accuracies, interval, pass
    flags and McNemar test; typed misses counted by outcome, cause, differing query parts and
    the generated query's shape (table, op, filter keys, field); baseline misses counted by
    outcome and cause. No item id, filter value, answer or error text."""
    misses = [{"outcome": m["outcome"], "cause": m["cause"], "differs": m["differs"],
               "query": _tables_shape(m["generated_query"])} for m in c["misses"]]
    counted: dict[str, dict] = {}
    for m in misses:
        counted.setdefault(json.dumps(m, sort_keys=True), {**m, "n": 0})["n"] += 1
    out = {k: c[k] for k in ("typed_run", "baseline_run", "golden_sha256", "facts", "n",
                             "typed", "baseline", "difference", "thresholds", "accuracy_ok",
                             "margin_ok", "passed", "b", "c", "mcnemar_p")}
    out.update(misses=[counted[k] for k in sorted(counted)],
               baseline_misses=_count_rows(c["baseline_misses"], ("outcome", "cause")))
    return out
