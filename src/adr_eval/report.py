"""Reports over a run directory (JSON and markdown) and paired comparisons of two runs; the
same for retrieval-track runs (`retrieval.json`)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import numpy as np

from adr_eval.models import jsonl_lines
from adr_eval.pipeline import EXACT_TO_JUDGE
from adr_eval.runner import RunError
from adr_eval.scoring.determinism import answer_agreement, pass_hat_k, retrieval_identity_rate
from adr_eval.scoring.outcomes import penalised_score
from adr_eval.scoring.stats import (
    bootstrap_mean_ci,
    cluster_bootstrap_ratio_ci,
    cohen_kappa,
    holm,
    mcnemar_exact,
    paired_bootstrap_ci,
)

DEFAULT_SEED = 20261108
COMPARE_T = 0.75
PROXY_NOTE = "proxy, not human κ: judge vs the exact scorer on number/set/id items"
G2_FIELDS = ("store", "op", "filters", "entities", "as_of")
G3_KEYS = ("recall@10", "ndcg@10", "mrr", "coverage@10")
RECOVERY_STAGES = ("query", "answer", "judge", "judge_check")


def load_rows(run_dir: Path) -> list[dict]:
    path = Path(run_dir) / "results.jsonl"
    return [json.loads(line) for line in jsonl_lines(path.read_text(encoding="utf-8"))]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _mean(xs) -> float | None:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def _group(rows: list[dict], key: Callable[[dict], str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(key(r), []).append(r)
    return dict(sorted(out.items()))


def _rarity(r: dict) -> str:
    return r["rarity"] or "none"


def _rarity_qtype(r: dict) -> str:
    return f"{_rarity(r)}/{r['qtype']}"


def _ci(values: list[float]) -> dict | None:
    """95% percentile-bootstrap CI of the mean over items; None when n < 2."""
    if len(values) < 2:
        return None
    mean, lo, hi = bootstrap_mean_ci(values)
    return {"mean": mean, "ci95": [lo, hi], "n": len(values)}


# -- tracks -----------------------------------------------------------------------------


def _g2(rows: list[dict]) -> dict:
    scored = [r for r in rows if r["gold_query_field_hits"] is not None]
    executable = [r["query_exec_match"] for r in scored if r["query_exec_match"] is not None]
    # rows recorded before metrics version 2 lack route_ok and entity_f1
    routed = [r["route_ok"] for r in scored if r.get("route_ok") is not None]
    entities = [r["entity_f1"] for r in scored if r.get("entity_f1") is not None]
    return {
        "n": len(scored),
        "route_accuracy": _mean(routed), "route_n": len(routed),
        "entity_f1": _mean(entities), "entity_n": len(entities),
        "per_field": {f: _mean(r["gold_query_field_hits"][f] for r in scored) for f in G2_FIELDS},
        "exact": _mean(r["query_exact"] for r in scored),
        "exec_match": _mean(executable), "exec_n": len(executable),
    }


def _metric(rows: list[dict], key: str) -> list[float]:
    """`key` from each row's metrics; rows recorded before the metric existed are skipped."""
    return [r["metrics"][key] for r in rows if r["metrics"].get(key) is not None]


def _g3_block(rows: list[dict]) -> dict:
    multi = [r["metrics"]["full_coverage"] for r in rows if r["metrics"]["n_spans"] > 1]
    return {"n": len(rows),
            **{k: _mean(_metric(rows, k)) for k in G3_KEYS},
            "tokens@10": _mean(_metric(rows, "tokens@10")),
            "full_coverage": _mean(multi), "n_multi_span": len(multi),
            "ci": {k: _ci(_metric(rows, k)) for k in G3_KEYS}}


def _g3(rows: list[dict]) -> dict:
    """Over repeat 0 (retrieval is deterministic); `insufficient` items carry no metrics."""
    r0 = [r for r in rows if r["repeat"] == 0 and r["metrics"] is not None]
    return {
        "pooled": _g3_block(r0),
        "by_rarity": {k: _g3_block(v) for k, v in _group(r0, _rarity).items()},
        "by_qtype": {k: _g3_block(v) for k, v in _group(r0, lambda r: r["qtype"]).items()},
        "by_rarity_qtype": {k: _g3_block(v) for k, v in
                            _group(r0, _rarity_qtype).items()},
    }


def _answer_text(answer: dict) -> str:
    if answer["abstain"]:
        return "<abstain>"
    v = answer["value"]
    return json.dumps(sorted(v), ensure_ascii=False) if isinstance(v, list) else str(v)


def _determinism(rows: list[dict], k: int) -> dict:
    by_item = _group(rows, lambda r: r["item_id"])
    ranked = {i: [[c for c, _ in r["retrieved"]] for r in rs] for i, rs in by_item.items()}
    answers = {i: [_answer_text(r["answer"]) for r in rs if r["answer"]]
               for i, rs in by_item.items()}
    outcomes = {i: [r["outcome"] for r in rs] for i, rs in by_item.items()}
    # with one repeat there is nothing to compare: identity and agreement are not measured
    return {
        "retrieval_identity_rate": retrieval_identity_rate(ranked) if rows and k >= 2 else None,
        "answer_agreement": answer_agreement(answers),
        "pass^k": pass_hat_k(outcomes) if rows else None, "k": k,
    }


def _cluster_ci(clusters: list[tuple[float, int]]) -> dict | None:
    """95% CI of sum(num)/sum(den) by a cluster bootstrap over items; items with den 0 are
    dropped first, and the CI is None when fewer than 2 items contribute."""
    clusters = [(num, den) for num, den in clusters if den > 0]
    if len(clusters) < 2:
        return None
    mean, lo, hi = cluster_bootstrap_ratio_ci([c[0] for c in clusters], [c[1] for c in clusters])
    return {"mean": mean, "ci95": [lo, hi], "n": len(clusters)}


def _rates(rows: list[dict], t_values: list[float]) -> dict:
    n = len(rows)
    count = {o: sum(r["outcome"] == o for r in rows)
             for o in ("correct", "partial", "wrong", "abstained", "error")}
    outcomes = [r["outcome"] for r in rows]
    # CIs resample items (all their repeats together) for the same row-level ratio shown
    items = [[r["outcome"] for r in rs] for rs in _group(rows, lambda r: r["item_id"]).values()]
    return {
        "n": n, "counts": count,
        "accuracy": count["correct"] / n if n else None,
        "error_rate": count["error"] / n if n else None,
        "abstention_rate": count["abstained"] / n if n else None,
        "partial_rate": count["partial"] / n if n else None,
        # None where no row is scorable (empty, or every row an error)
        "penalised": {str(t): penalised_score(outcomes, t) if n > count["error"] else None
                      for t in t_values},
        "ci": {
            "accuracy": _cluster_ci([(float(os_.count("correct")), len(os_)) for os_ in items]),
            "penalised": {str(t): _cluster_ci(
                [(sum(penalised_score([o], t) for o in os_ if o != "error"),
                  sum(o != "error" for o in os_)) for os_ in items]) for t in t_values},
        },
    }


def _end_to_end(rows: list[dict], t_values: list[float], spent_usd: float | None) -> dict:
    cited = [r["citation"] for r in rows if r["citation"] is not None]
    latencies = [r["latency_s"] for r in rows if r["latency_s"] is not None]
    p50, p95 = (np.percentile(latencies, [50, 95]).tolist() if latencies else (None, None))
    return {
        **_rates(rows, t_values),
        "error_count": sum(r["outcome"] == "error" for r in rows),
        # rows from runs before the field existed count as not recovered
        "json_recovered_rows": sum(bool(r.get("json_recovered")) for r in rows),
        "json_recovered_by_stage": {s: sum(s in (r.get("json_recovered") or []) for r in rows)
                                    for s in RECOVERY_STAGES},
        "citation_precision": _mean(c["precision"] for c in cited if c["precision"] is not None),
        "evidence_cited_rate": _mean(c["evidence_cited"] for c in cited),
        "tokens": {"in": sum(r["tokens"]["in"] for r in rows),
                   "out": sum(r["tokens"]["out"] for r in rows)},
        "cost_usd": sum(r["cost_usd"] for r in rows),  # rows written
        "spent_usd": spent_usd,  # authoritative: every call, incl. a row dropped at a budget stop
        "latency_p50_s": p50, "latency_p95_s": p95, "latency_n": len(latencies),
        "by_qtype": {k: _rates(v, t_values) for k, v in _group(rows, lambda r: r["qtype"]).items()},
        "by_rarity": {k: _rates(v, t_values) for k, v in _group(rows, _rarity).items()},
        "by_rarity_qtype": {k: _rates(v, t_values)
                            for k, v in _group(rows, _rarity_qtype).items()},
    }


def _binary_kappa(a: list[str], b: list[str]) -> float | None:
    """Cohen's κ; None when undefined (no rows, or both raters give one same label)."""
    if not a or len(set(a) | set(b)) < 2:
        return None
    return cohen_kappa(a, b)


def _judge(rows: list[dict], cfg: dict) -> dict:
    checks = [r for r in rows if r.get("judge_check")]
    proxy = [r for r in checks if r["judge_check"]["purpose"] == "proxy"
             and r["judge_check"]["label"] is not None and r["outcome"] in EXACT_TO_JUDGE]
    selfc = [r for r in checks if r["judge_check"]["purpose"] == "self_consistency"
             and r["judge_check"]["label"] is not None and r["judge_label"] is not None]
    exact = [EXACT_TO_JUDGE[r["outcome"]] for r in proxy]
    judged = [r["judge_check"]["label"] for r in proxy]
    kappa = cohen_kappa(exact, judged) if proxy else None
    binary = ["incorrect" if label == "partial" else label for label in judged]
    return {
        "model": cfg.get("judge", {}).get("model"),
        "proxy_kappa": kappa, "proxy_kappa_n": len(proxy), "proxy_kappa_note": PROXY_NOTE,
        "proxy_agreement": _mean(x == y for x, y in zip(exact, binary, strict=True)),
        "proxy_kappa_binary": _binary_kappa(exact, binary),
        "self_consistency": _mean(r["judge_check"]["label"] == r["judge_label"] for r in selfc),
        "self_consistency_n": len(selfc),
        "check_errors": sum(r["judge_check"]["error"] is not None for r in checks),
        "human_kappa": None,
        "same_family_judge": bool(cfg.get("same_family_judge")),
    }


def metrics_version(run_dir: Path) -> int:
    """The metrics version a run was recorded under; 1 when config.json has no such field."""
    return _read_json(Path(run_dir) / "config.json").get("metrics_version", 1)


def build_report(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    cfg = _read_json(run_dir / "config.json")
    rows = load_rows(run_dir)
    t_values = cfg.get("t_values", [0.5, 0.75, 0.9])
    det = _determinism(rows, cfg.get("repeats", 0))
    violation = det["retrieval_identity_rate"] is not None and det["retrieval_identity_rate"] < 1.0
    rep = {
        **{k: cfg.get(k) for k in ("run_id", "corpus", "system", "split", "repeats", "status",
                                   "stub", "w", "snapshot", "n_items")},
        "generator_model": cfg.get("generator", {}).get("model"),
        "metrics_version": cfg.get("metrics_version", 1),
        "n_rows": len(rows),
        "g1": _read_json(run_dir / "compile.json"),
        "g2": _g2(rows), "g3": _g3(rows),
        "determinism": det, "determinism_violation": violation,
        "end_to_end": _end_to_end(rows, t_values, cfg.get("spent_usd")),
        "judge": _judge(rows, cfg),
    }
    warnings = []
    if violation:
        warnings.append(f"determinism check failed: retrieval identity rate "
                        f"{det['retrieval_identity_rate']:.3f} < 1.0 (expected 1.0; this is a bug)")
    if rep["judge"]["same_family_judge"]:
        warnings.append("judge and generator share a model family")
    if cfg.get("status") == "stopped_budget":
        warnings.append("run stopped at the --max-dollars budget; rows are incomplete")
    if cfg.get("served_model_mismatch"):
        served = {r: (cfg.get(r) or {}).get("served_models") for r in ("generator", "judge")}
        warnings.append(f"served model differs from the profile's model ID: "
                        f"generator {cfg['generator'].get('model')} served {served['generator']},"
                        f" judge {cfg['judge'].get('model')} served {served['judge']}")
    if cfg.get("status") == "stopped_calls":
        warnings.append("run stopped at the --max-calls limit; rows are incomplete")
    if cfg.get("stub"):
        warnings.append("stub model run (tests and demos): numbers do not measure a model")
    if rep["end_to_end"]["error_count"]:
        warnings.append(f"{rep['end_to_end']['error_count']} row(s) ended in a model error")
    rep["warnings"] = warnings
    return rep


def write_report(run_dir: Path) -> dict:
    rep = build_report(run_dir)
    (Path(run_dir) / "report.json").write_text(
        json.dumps(rep, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    (Path(run_dir) / "report.md").write_text(render_markdown(rep), encoding="utf-8")
    return rep


# -- markdown ---------------------------------------------------------------------------


def _fmt(x) -> str:
    if x is None:
        return "–"
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, float):
        return f"{x:.3f}"
    return str(x)


def _with_ci(value, ci: dict | None) -> str:
    if ci is None:
        return _fmt(value)
    return f"{_fmt(value)} [{ci['ci95'][0]:.3f}, {ci['ci95'][1]:.3f}]"


def _penalised_cells(block: dict) -> list[str]:
    return [_with_ci(v, block["ci"]["penalised"][t]) for t, v in block["penalised"].items()]


def _table(header: list[str], rows: list[list]) -> list[str]:
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header),
            *("| " + " | ".join(_fmt(c) for c in row) + " |" for row in rows), ""]


def render_markdown(report: dict) -> str:
    r, e2e, g1, g2, g3, det, j = (report, report["end_to_end"], report["g1"], report["g2"],
                                  report["g3"], report["determinism"], report["judge"])
    ts = list(e2e["penalised"])
    out = [f"# Report: {r['run_id']}", "",
           f"Corpus `{r['corpus']}`, system `{r['system']}`, split `{r['split']}`, "
           f"{r['repeats']} repeats, {r['n_rows']} rows, status `{r['status']}`. "
           f"Generator `{r['generator_model']}`, judge `{j['model']}`"
           + (f", linear w = {r['w']}" if r.get("w") is not None else "")
           + f". Metrics version {r.get('metrics_version', 1)}.", ""]
    for w in r["warnings"]:
        out += [f"> **Warning:** {w}", ""]
    out += ["Values in brackets are 95% CIs (percentile bootstrap, 10,000 resamples). "
            "End to end: cluster bootstrap over items of the statistic shown, using every "
            "repeat (items are resampled with all their rows); none where fewer than 2 items "
            "contribute. G3 retrieval: bootstrap of the mean over items at repeat 0 (retrieval "
            "is deterministic); none where n < 2.", ""]
    out += ["## End to end", ""]
    out += _table(["n", "accuracy", "error", "abstained", "partial",
                   *[f"penalised t={t}" for t in ts]],
                  [[e2e["n"], _with_ci(e2e["accuracy"], e2e["ci"]["accuracy"]),
                    e2e["error_rate"], e2e["abstention_rate"], e2e["partial_rate"],
                    *_penalised_cells(e2e)]])
    out += _table(["stratum", "n", "accuracy", *[f"penalised t={t}" for t in ts]],
                  [[k, v["n"], _with_ci(v["accuracy"], v["ci"]["accuracy"]),
                    *_penalised_cells(v)]
                   for k, v in [*((f"qtype {k}", v) for k, v in e2e["by_qtype"].items()),
                                *((f"rarity {k}", v) for k, v in e2e["by_rarity"].items()),
                                *e2e["by_rarity_qtype"].items()]])
    spent = e2e.get("spent_usd")
    out += [f"Citation precision {_fmt(e2e['citation_precision'])}, evidence cited "
            f"{_fmt(e2e['evidence_cited_rate'])}. Tokens {e2e['tokens']['in']} in / "
            f"{e2e['tokens']['out']} out. Spent "
            + (f"${spent:.4f}" if spent is not None else "unknown")
            + f" in total (authoritative: every call, including any row dropped at a budget "
            f"stop); rows written sum to ${e2e['cost_usd']:.4f}. Latency p50 "
            f"{_fmt(e2e['latency_p50_s'])} s, p95 {_fmt(e2e['latency_p95_s'])} s "
            f"(uncached calls: {e2e['latency_n']}). Errors: {e2e['error_count']}.", ""]
    if e2e.get("json_recovered_rows"):
        stages = ", ".join(f"{k} {v}" for k, v in e2e["json_recovered_by_stage"].items() if v)
        out += [f"JSON recovered (a reply held several objects or prose; the last object "
                f"with the required keys was used) in {e2e['json_recovered_rows']} row(s): "
                f"{stages}.", ""]
    out += ["## G3 retrieval (excluding `insufficient`)", ""]
    out += _table(["stratum", "n", "Recall@10", "nDCG@10", "MRR", "coverage@10", "tokens@10",
                   "full coverage"],
                  [[k, v["n"], *(_with_ci(v.get(m), v["ci"].get(m)) for m in G3_KEYS),
                    v.get("tokens@10"), v["full_coverage"]]
                   for k, v in [("pooled", g3["pooled"]),
                                *((f"rarity {k}", v) for k, v in g3["by_rarity"].items()),
                                *((f"qtype {k}", v) for k, v in g3["by_qtype"].items()),
                                *g3["by_rarity_qtype"].items()]])
    if det["k"] < 2:
        det_line = (f"Retrieval identity: not measured ({det['k']} repeat); answer agreement: "
                    f"not measured; pass^{det['k']} {_fmt(det['pass^k'])}.")
    else:
        det_line = (f"Retrieval identity rate {_fmt(det['retrieval_identity_rate'])}; answer "
                    f"agreement {_fmt(det['answer_agreement'])}; pass^{det['k']} "
                    f"{_fmt(det['pass^k'])}.")
    out += ["## Determinism", "", det_line, ""]
    out += ["## G2 query understanding", "",
            "Route accuracy over rows whose gold op is not `abstain`; record match over rows "
            "whose gold query can be executed on the records; entity F1 over rows whose gold "
            "query lists entities. Per-field hits are kept in report.json as diagnostics.", ""]
    out += _table(["route accuracy", "n", "record match", "n", "entity F1", "n"],
                  [[g2["route_accuracy"], g2["route_n"], g2["exec_match"], g2["exec_n"],
                    g2["entity_f1"], g2["entity_n"]]])
    tf = g1.get("text_fidelity") or {}
    out += ["## G1 compile", "",
            f"Span containment {_fmt(g1.get('span_containment'))}; text fidelity "
            f"{_fmt(tf.get('share'))}; empty documents {len(g1.get('empty_docs', []))}; "
            f"index fingerprint `{g1.get('fingerprint')}`.", ""]
    out += ["## Judge", "",
            f"Proxy κ {_fmt(j['proxy_kappa'])} "
            f"(n = {j['proxy_kappa_n']}; {j['proxy_kappa_note']}); raw agreement "
            f"{_fmt(j.get('proxy_agreement'))}, binary κ {_fmt(j.get('proxy_kappa_binary'))} "
            f"(judge \"partial\" counted as incorrect; n = {j['proxy_kappa_n']}). "
            f"Self-consistency {_fmt(j['self_consistency'])} (n = {j['self_consistency_n']}). "
            f"Human κ: not yet measured.", ""]
    return "\n".join(out)


# -- comparisons ------------------------------------------------------------------------


def _bootstrap_p(x: list[float], y: list[float], n: int, seed: int) -> float:
    """Two-sided percentile-bootstrap p for mean(y - x) = 0, same resamples as the CI."""
    d = np.asarray(y, dtype=float) - np.asarray(x, dtype=float)
    idx = np.random.default_rng(seed).integers(0, len(d), size=(n, len(d)))
    means = d[idx].mean(axis=1)
    return float(min(1.0, 2 * min((means <= 0).mean(), (means >= 0).mean())))


def _first_repeat(run_dir: Path) -> dict[str, dict]:
    return {r["item_id"]: r for r in load_rows(run_dir) if r["repeat"] == 0}


def compare(run_a: Path, run_b: Path, n_resamples: int = 10_000) -> dict:
    """Paired over shared (item_id, repeat 0); differences are run_b - run_a.

    Refuses (RunError) runs recorded under different metrics versions."""
    va, vb = metrics_version(run_a), metrics_version(run_b)
    if va != vb:
        raise RunError(f"cannot compare runs with different metrics versions: "
                       f"{Path(run_a).name} is metrics version {va}, "
                       f"{Path(run_b).name} is metrics version {vb}")
    seed = _read_json(Path(run_a) / "config.json").get("seed") or DEFAULT_SEED
    a, b = _first_repeat(run_a), _first_repeat(run_b)
    shared = sorted(a.keys() & b.keys())
    getters: dict[str, Callable[[dict], float | None]] = {
        f"penalised@{COMPARE_T}": lambda r: None if r["outcome"] == "error"
        else penalised_score([r["outcome"]], COMPARE_T),
        "ndcg@10": lambda r: r["metrics"]["ndcg@10"] if r["metrics"] else None,
        "recall@10": lambda r: r["metrics"]["recall@10"] if r["metrics"] else None,
        "coverage@10": lambda r: r["metrics"].get("coverage@10") if r["metrics"] else None,
    }
    metrics: dict[str, dict] = {}
    for name, get in getters.items():
        pairs = [(get(a[i]), get(b[i])) for i in shared]
        pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
        if not pairs:
            metrics[name] = {"n": 0, "mean_diff": None, "ci95": None, "p": None}
            continue
        x, y = [p[0] for p in pairs], [p[1] for p in pairs]
        mean, lo, hi = paired_bootstrap_ci(x, y, n=n_resamples, seed=seed)
        metrics[name] = {"n": len(pairs), "mean_diff": mean, "ci95": [lo, hi],
                         "p": _bootstrap_p(x, y, n_resamples, seed)}
    only_a = sum(a[i]["outcome"] == "correct" and b[i]["outcome"] != "correct" for i in shared)
    only_b = sum(a[i]["outcome"] != "correct" and b[i]["outcome"] == "correct" for i in shared)
    mc = {"n": len(shared), "only_a_correct": only_a, "only_b_correct": only_b,
          "p": mcnemar_exact(only_a, only_b)}
    pvals = {k: m["p"] for k, m in metrics.items() if m["p"] is not None}
    adjusted = holm({**pvals, "mcnemar": mc["p"]})
    for k, m in metrics.items():
        m["p_holm"] = adjusted.get(k)
    mc["p_holm"] = adjusted["mcnemar"]
    return {"run_a": Path(run_a).name, "run_b": Path(run_b).name, "n_pairs": len(shared),
            "n_resamples": n_resamples,
            "difference": "run_b - run_a", "metrics": metrics, "mcnemar": mc}


def _p_cell(p: float | None, bound: float | None) -> str | float | None:
    """A bootstrap p of 0 only says p is below the resolution: print "< bound"."""
    if p == 0 and bound is not None:
        return f"< {bound:.4f}"
    return p


def render_compare_markdown(c: dict) -> str:
    n = c.get("n_resamples")
    bound = 2 / n if n else None  # the smallest nonzero two-sided bootstrap p
    tests = 1 + sum(m["p"] is not None for m in c["metrics"].values())  # Holm's largest factor
    out = [f"# Comparison: {c['run_b']} minus {c['run_a']}", "",
           f"Paired over {c['n_pairs']} shared items (repeat 0); paired bootstrap 95% CIs; "
           f"Holm-adjusted p across the metrics below.", ""]
    out += _table(["metric", "n", "mean diff", "95% CI", "p", "p (Holm)"],
                  [[k, m["n"], m["mean_diff"],
                    f"[{m['ci95'][0]:.3f}, {m['ci95'][1]:.3f}]" if m["ci95"] else None,
                    _p_cell(m["p"], bound), _p_cell(m["p_holm"], bound and bound * tests)]
                   for k, m in c["metrics"].items()])
    mc = c["mcnemar"]
    out += [f"McNemar exact on correct vs not: only A correct {mc['only_a_correct']}, only B "
            f"correct {mc['only_b_correct']}, p = {mc['p']:.4f} (Holm {mc['p_holm']:.4f}).", ""]
    return "\n".join(out)


# -- the retrieval track ----------------------------------------------------------------


def retrieval_summary(rows: list[dict]) -> dict:
    """G3 figures of a retrieval-track run: pooled and per rarity / qtype, with 95% CIs
    (items without metrics, i.e. `insufficient`, are left out)."""
    return _g3([{**r, "repeat": 0} for r in rows])


def load_retrieval(run_dir: Path) -> dict:
    path = Path(run_dir) / "retrieval.json"
    if not path.is_file():
        raise RunError(f"{run_dir}: no retrieval.json; pass a retrieval run id or directory")
    return json.loads(path.read_text(encoding="utf-8"))


def render_retrieval_markdown(data: dict) -> str:
    cfg, g3 = data["config"], data["summary"]
    s = cfg["settings"]
    knobs = ", ".join(f"{k} {s[k]}" for k in ("fusion", "linear_w", "w_bc", "prefix", "rerank")
                      if k in s)
    out = [f"# Retrieval: {cfg['run_id']}", "",
           f"Corpus `{cfg['corpus']}`, system `{cfg['system']}`"
           + (" (lexical channel only)" if cfg.get("lexical_only") else "")
           + f", split `{cfg['split']}`, {cfg['n_items']} items. Settings: {knobs}. "
           f"Index fingerprint `{cfg['fingerprint']}`. Metrics version "
           f"{cfg['metrics_version']}. No model calls. Wall-clock {cfg['wall_clock_s']} s.", "",
           "Values in brackets are 95% CIs (percentile bootstrap of the mean over items, "
           "10,000 resamples); none where n < 2. `insufficient` items carry no metrics.", ""]
    out += _table(["stratum", "n", "Recall@10", "nDCG@10", "MRR", "coverage@10", "tokens@10",
                   "full coverage"],
                  [[k, v["n"], *(_with_ci(v.get(m), v["ci"].get(m)) for m in G3_KEYS),
                    v.get("tokens@10"), v["full_coverage"]]
                   for k, v in [("pooled", g3["pooled"]),
                                *((f"rarity {k}", v) for k, v in g3["by_rarity"].items()),
                                *((f"qtype {k}", v) for k, v in g3["by_qtype"].items())]])
    comp = cfg.get("compile") or {}
    out += [f"Chunks {comp.get('n_chunks')}; span containment "
            f"{_fmt(comp.get('span_containment'))}.", ""]
    return "\n".join(out)


def compare_retrieval(run_a: Path, run_b: Path, n_resamples: int = 10_000) -> dict:
    """Paired differences (run_b - run_a) of the retrieval metrics over shared items, with
    paired bootstrap CIs and Holm-adjusted p across the four metrics. Refuses runs of other
    metrics versions, corpora or splits."""
    a, b = load_retrieval(run_a), load_retrieval(run_b)
    ca, cb = a["config"], b["config"]
    if ca["metrics_version"] != cb["metrics_version"]:
        raise RunError(f"cannot compare runs with different metrics versions: "
                       f"{Path(run_a).name} is metrics version {ca['metrics_version']}, "
                       f"{Path(run_b).name} is metrics version {cb['metrics_version']}")
    for key in ("corpus", "split"):
        if ca[key] != cb[key]:
            raise RunError(f"cannot compare runs of different {key}s: {ca[key]} and {cb[key]}")
    seed = ca.get("seed") or DEFAULT_SEED
    ra = {r["item_id"]: r for r in a["rows"] if r["metrics"] is not None}
    rb = {r["item_id"]: r for r in b["rows"] if r["metrics"] is not None}
    shared = sorted(ra.keys() & rb.keys())
    if not shared:
        raise RunError(f"{Path(run_a).name} and {Path(run_b).name} share no scored items")
    metrics: dict[str, dict] = {}
    for k in G3_KEYS:
        x = [ra[i]["metrics"][k] for i in shared]
        y = [rb[i]["metrics"][k] for i in shared]
        mean, lo, hi = paired_bootstrap_ci(x, y, n=n_resamples, seed=seed)
        metrics[k] = {"n": len(shared), "a": _mean(x), "b": _mean(y), "mean_diff": mean,
                      "ci95": [lo, hi], "p": _bootstrap_p(x, y, n_resamples, seed)}
    adjusted = holm({k: m["p"] for k, m in metrics.items()})
    for k, m in metrics.items():
        m["p_holm"] = adjusted[k]
    return {"run_a": Path(run_a).name, "run_b": Path(run_b).name,
            "system_a": ca["system"], "system_b": cb["system"], "corpus": ca["corpus"],
            "split": ca["split"], "metrics_version": ca["metrics_version"],
            "n_pairs": len(shared), "n_resamples": n_resamples, "difference": "run_b - run_a",
            "metrics": metrics}


def render_retrieval_compare_markdown(c: dict) -> str:
    bound = 2 / c["n_resamples"]
    out = [f"# Retrieval comparison: {c['run_b']} minus {c['run_a']}", "",
           f"`{c['system_b']}` minus `{c['system_a']}` on `{c['corpus']}` / `{c['split']}`, "
           f"paired over {c['n_pairs']} shared items; paired bootstrap 95% CIs; Holm-adjusted "
           f"p across the four metrics. Metrics version {c['metrics_version']}.", ""]
    out += _table(["metric", "n", "A", "B", "mean diff", "95% CI", "p", "p (Holm)"],
                  [[k, m["n"], m["a"], m["b"], m["mean_diff"],
                    f"[{m['ci95'][0]:.3f}, {m['ci95'][1]:.3f}]", _p_cell(m["p"], bound),
                    _p_cell(m["p_holm"], bound * len(c["metrics"]))]
                   for k, m in c["metrics"].items()])
    return "\n".join(out)
