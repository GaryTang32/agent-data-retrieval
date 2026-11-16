"""`adr-eval` command line: fetch, tools-fetch, golden, index, run, retrieval,
retrieval-compare, retrieval-identical, p2-compare, probes (temporal, acl, equivalence),
report, doctor."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from adr_eval import runner, systems
from adr_eval.cache import Cache
from adr_eval.corpora.base import ExtractionError, HashMismatch
from adr_eval.corpora.registry import (
    NAMES,
    LocalFilesMissing,
    check_local_files,
    fetch_corpus,
    get_adapter,
)
from adr_eval.corpora.toolret import ToolRetMissing
from adr_eval.models import GoldenItem, jsonl_lines, write_items
from adr_eval.report import (
    compare,
    compare_retrieval,
    load_retrieval,
    render_compare_markdown,
    render_markdown,
    render_retrieval_compare_markdown,
    write_report,
)


def _fetch(a: argparse.Namespace) -> int:
    fetch_corpus(a.corpus)
    print(f"{a.corpus}: all manifest files present and verified")
    return 0


def _tools_fetch(a: argparse.Namespace) -> int:
    """Download the pinned ToolRet files into data/tools and write corpora/tools/manifest.json
    (Phase 2 spec §8.3; local-only, like bench)."""
    from adr_eval.corpora import toolret

    root = a.root if a.root is not None else toolret.DATA_DIR
    m = toolret.fetch(root, toolret.CONFIG_PATH, toolret.MANIFEST_PATH)
    c = m["counts"]
    for f in m["files"]:
        print(f"{f['name']}: {f['repo']}@{f['revision'][:12]} {f['path']} ({f['bytes']} bytes, "
              f"sha256 {f['sha256'][:12]})")
    pool = " + ".join(f"{t['prefix']}* ({t['config']})" for t in m["tool_selection"])
    print(f"tools: {c['tools']} tools ({pool}), {c['queries']} queries, mean "
          f"{c['gold_mean']:.2f} gold tools ({c['gold_distinct']} distinct, "
          f"{c['gold_missing']} missing from the tools), {c['doc_tokens']} documentation "
          f"tokens (mean {c['doc_tokens_mean']:.1f}, median {c['doc_tokens_median']:g}), "
          f"dev {c['dev']} / test {c['test']}")
    print(f"  manifest {toolret.MANIFEST_PATH}")
    return 0


LOCAL_ONLY_GOLDEN = ("bench", "research")  # item files hold verbatim source text; not in git


def _exclusions(corpus: str) -> dict[str, str]:
    from adr_eval.golden.verify import EXCLUSIONS_FILE, load_exclusions

    return load_exclusions(runner.golden_dir(corpus) / EXCLUSIONS_FILE)


def _golden_gen(a: argparse.Namespace) -> int:
    items = runner.golden_dir(a.corpus) / "items.jsonl"
    if items.exists() and not a.overwrite:  # checked before any client is made or call sent
        print(f"error: {items} exists and is frozen (golden sets are data, not regenerated "
              f"when scoring rules change; a regenerated set is a new version); pass "
              f"--overwrite to replace it", file=sys.stderr)
        return 2
    handler = logging.StreamHandler(sys.stderr)  # the per-qtype tally lines
    handler.setFormatter(logging.Formatter("%(message)s"))
    log = logging.getLogger("adr_eval.golden.generate")
    old_level = log.level
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        return _golden_gen_logged(a)
    finally:
        log.removeHandler(handler)
        log.setLevel(old_level)


def _golden_gen_logged(a: argparse.Namespace) -> int:
    from adr_eval.golden.generate import generate_corpus
    from adr_eval.llm import load_prices
    from adr_eval.pipeline import Budget, BudgetExceeded, MeteredClient
    from adr_eval.scoring.judge import Judge

    config = runner.load_config()
    profiles = runner.load_profiles(runner.REPO_ROOT / config.get("models", runner.MODELS_PATH))
    cache = runner.llm_cache(config)
    judge_name = a.judge or config["judge"]
    client = runner.make_client(a.generator or config["generator"], profiles, cache)
    judge_client = runner.make_client(judge_name, profiles, cache)
    budget = Budget(None, a.max_calls)
    if a.max_calls is not None:  # one cap for the generator and the judge together
        prices = load_prices(runner.REPO_ROOT / config.get("prices", "config/prices.json"))
        client = MeteredClient(client, budget, prices)
        judge_client = MeteredClient(judge_client, budget, prices)
    try:
        accepted, rejected = generate_corpus(a.corpus, client, seed=config["seed"],
                                             judge=Judge(judge_client),
                                             exclusions=_exclusions(a.corpus))
    except BudgetExceeded:
        print(f"error: stopped at --max-calls {a.max_calls} ({budget.calls} model calls made); "
              f"nothing written. Completed calls are cached: rerun to continue.",
              file=sys.stderr)
        return 3
    d = runner.golden_dir(a.corpus)
    d.mkdir(parents=True, exist_ok=True)
    write_items(d / "items.jsonl", accepted)
    write_items(d / "rejected.jsonl", rejected)
    per_type = Counter(i.qtype for i in accepted)
    rated = [i for i in accepted if i.rarity is not None]
    tail = sum(i.rarity == "tail" for i in rated) / len(rated) if rated else 0.0
    print(f"{d}: {len(accepted)} accepted, {len(rejected)} rejected (judge {judge_name}); "
          f"per type {dict(sorted(per_type.items()))}; tail share {tail:.2f}"
          + (" (below the 30% target; reported, not padded)" if rated and tail < 0.3 else ""))
    return 0


def _golden_verify(a: argparse.Namespace) -> int:
    from adr_eval.golden.verify import verify_items

    path = runner.golden_items_path(a.corpus)
    if not path.is_file():
        local = (f"the {a.corpus} golden set is local only (not in git); "
                 if a.corpus in LOCAL_ONLY_GOLDEN else "")
        raise runner.RunError(
            f"{path}: not found; {local}regenerate it with `adr-eval golden {a.corpus} --gen "
            f"--max-calls N` (see golden/{a.corpus}/v0.1/README.md for the pinned counts)")
    items, failures = [], []
    for n, line in enumerate(jsonl_lines(path.read_text(encoding="utf-8")), 1):
        try:
            items.append(GoldenItem.model_validate_json(line))
        except ValidationError as e:
            try:
                item_id = json.loads(line).get("id", f"line {n}")
            except ValueError:
                item_id = f"line {n}"
            failures.append((item_id, f"schema: {e.errors()[0]['msg']}"))
    loaded = runner.load_checked_corpus(a.corpus)
    ok, bad = verify_items(items, loaded, records=get_adapter(a.corpus).records(loaded),
                           seed=runner.load_config()["seed"],
                           exclusions=_exclusions(a.corpus))
    failures += [(i.id, i.reject_reason) for i in bad]
    for item_id, reason in failures:
        print(f"{path}: {item_id}: {reason}", file=sys.stderr)
    print(f"{path}: {len(ok)} ok, {len(failures)} failed")
    return 1 if failures else 0


def _index(a: argparse.Namespace) -> int:
    config = runner.load_config()
    loaded = runner.load_checked_corpus(a.corpus)
    idx, source = runner.ensure_index(a.corpus, loaded, config, rebuild=a.rebuild)
    print(f"{a.corpus}: index {source} at {runner.index_dir(config, a.corpus)}; "
          f"{len(idx.chunks)} chunks; {len(loaded.empty_docs)} empty docs; "
          f"fingerprint {idx.fingerprint}")
    return 0


def _run(a: argparse.Namespace) -> int:
    config = runner.load_config()
    if a.stub:
        config["stub"] = True
    for role in ("generator", "judge"):
        if getattr(a, role):
            config[role] = getattr(a, role)
    repeats = a.repeats if a.repeats is not None else config["repeats"]
    run_id = runner.run(a.corpus, a.system, a.split, repeats, config, out_root=a.out,
                        max_dollars=a.max_dollars, dry_run=a.dry_run, rebuild=a.rebuild,
                        max_calls=a.max_calls)
    if a.dry_run:
        return 0
    run_dir = a.out / run_id
    rep = write_report(run_dir)
    e2e = rep["end_to_end"]
    print(f"{run_dir}: status {rep['status']}; {rep['n_rows']} rows; accuracy "
          f"{e2e['accuracy']}; errors {e2e['error_count']}; ${e2e['cost_usd']:.4f}")
    for w in rep["warnings"]:
        print(f"warning: {w}")
    return 4 if rep["determinism_violation"] else 0


def _retrieval(a: argparse.Namespace) -> int:
    t0 = time.perf_counter()
    run_id = runner.run_retrieval(a.corpus, a.system, a.split, runner.load_config(),
                                  out_root=a.out, rebuild=a.rebuild,
                                  lexical_only=a.lexical_only)
    data = load_retrieval(a.out / run_id)
    p = data["summary"]["pooled"]
    print(f"{a.out / run_id}: {p['n']} scored items; Recall@10 {p['recall@10']:.3f}, "
          f"nDCG@10 {p['ndcg@10']:.3f}, MRR {p['mrr']:.3f}, coverage@10 "
          f"{p['coverage@10']:.3f}; wall-clock {time.perf_counter() - t0:.1f} s")
    return 0


def _retrieval_dir(name: str, out: Path) -> Path:
    d = Path(name) if Path(name).is_dir() else out / name
    if not (d / "retrieval.json").is_file():
        raise runner.RunError(f"{d}: no retrieval.json; pass a retrieval run id under {out} "
                              f"or a run dir")
    return d


def _retrieval_compare(a: argparse.Namespace) -> int:
    run_a, run_b = _retrieval_dir(a.run_a, a.out), _retrieval_dir(a.run_b, a.out)
    c = compare_retrieval(run_a, run_b, allow_mixed=a.allow_mixed)
    (run_a / f"compare-{run_b.name}.json").write_text(
        json.dumps(c, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md = render_retrieval_compare_markdown(c)
    (run_a / f"compare-{run_b.name}.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


def _retrieval_identical(a: argparse.Namespace) -> int:
    from adr_eval import phase2

    run_a, run_b = _retrieval_dir(a.run_a, a.out), _retrieval_dir(a.run_b, a.out)
    r = phase2.identical(load_retrieval(run_a), load_retrieval(run_b))
    if r["identical"]:
        print(f"identical: {r['n_shared']} items, ranked chunk ids and scores equal "
              f"({run_a.name}, {run_b.name})")
        return 0
    print(f"not identical: {r['n_differing']} of {r['n_shared']} shared items differ; "
          f"{len(r['only_a'])} only in {run_a.name}, {len(r['only_b'])} only in {run_b.name}")
    for d in r["differences"][:a.show]:
        print(f"  {d['item_id']}: rank {d['rank']}: {d['a']} vs {d['b']} "
              f"({d['len_a']} vs {d['len_b']} hits)")
    for side, ids in (("A", r["only_a"]), ("B", r["only_b"])):
        if ids:
            print(f"  only in {side}: {', '.join(ids[:a.show])}")
    return 1


def _p2_compare(a: argparse.Namespace) -> int:
    from adr_eval import phase2

    out = phase2.OUT_ROOT if a.out is None else a.out
    run_a, run_b = _retrieval_dir(a.run_a, out), _retrieval_dir(a.run_b, out)
    c = phase2.compare(run_a, run_b, a.store, margin=a.margin)
    d = phase2.write_compare(c, out)
    print((d / "compare.md").read_text(encoding="utf-8"))
    print(f"written: {d / 'compare.json'}")
    return 0


def _probes(a: argparse.Namespace) -> int:
    if a.kind == "temporal":
        if a.corpus != "gov":
            raise runner.RunError(f"the temporal probes are for gov, not {a.corpus}")
        return _probes_temporal(a)
    return _probes_acl(a) if a.kind == "acl" else _probes_equivalence(a)


def _probes_temporal(a: argparse.Namespace) -> int:
    """`adr-eval probes temporal gov`: build T1-T5, run them through the tools of `--store`,
    write `<out>/probes-temporal-gov-<ts>/probes.{json,md}` (no wall-clock in the files)."""
    from datetime import UTC, datetime

    from adr_eval import probes
    from adr_eval.probes import temporal
    from adr_store.applicability import load_overlay
    from adr_store.tools import ToolError, Tools

    t0 = time.perf_counter()
    started = datetime.now(UTC)
    config = runner.load_config()
    loaded = runner.load_checked_corpus(a.corpus)
    items = runner.load_golden(a.corpus, loaded)
    try:
        tools = Tools(a.store, emb_cache=runner.REPO_ROOT / config.get(
            "embedding_cache_dir", ".cache/emb"))
        idx = tools.active_index()
    except ToolError as e:
        raise runner.RunError(f"{a.store}: {e}") from e
    if tools.store.doc_ids() != sorted(d.doc_id for d in loaded.manifest.documents):
        raise runner.RunError(f"{a.store}: the store does not hold the {a.corpus} corpus's "
                              f"documents")
    system = tools.active_system()
    recorded = systems.phase1_fingerprints(a.corpus)
    phase1 = system == systems.P2_REFERENCE and idx.fingerprint in recorded
    if not phase1 and not a.allow_other_index:
        raise runner.RunError(
            f"{a.store}: the active index is {system} {idx.fingerprint[:12]}, not "
            f"{systems.P2_REFERENCE} with the fingerprint of a committed Phase 1 run of "
            f"{a.corpus} ({', '.join(f[:12] for f in sorted(recorded)) or 'none committed'})"
            f"\nfix: activate it (`adr index {systems.P2_REFERENCE} --store {a.store}` with "
            f"the recorded weights; an `adr-eval retrieval` run of a p2 system does so) or "
            f"pass --allow-other-index to probe this index (recorded in the output)")
    overlay = load_overlay(tools.store_path, tools.snapshot)
    if overlay is None:
        raise runner.RunError(f"{a.store}: no applicability overlay; run `adr applicability "
                              f"derive --store {a.store}`")
    built = temporal.build(loaded, items, overlay)
    try:
        result = temporal.run(built, tools, caller=a.as_user, dedup=a.dedup)
    except (ValueError, ToolError) as e:
        raise runner.RunError(str(e)) from e
    sizes = dict(Counter(p.set for p in built if p.mode == "as_of" or p.set == "T4"))
    golden = runner.golden_items_path(a.corpus)
    data = {"config": {"corpus": a.corpus, "kind": "temporal",
                       "store": runner._display_path(tools.store_path),
                       "snapshot": tools.snapshot, "index": idx.fingerprint,
                       "index_system": system, "index_phase1": phase1,
                       "allow_other_index": a.allow_other_index,
                       "applicability": result["applicability"], "dedup": result["dedup"],
                       "caller": a.as_user, "seed": probes.SEED, "sizes": sizes,
                       "spec_sizes": temporal.SPEC_SIZES,
                       "golden_sha256": hashlib.sha256(golden.read_bytes()).hexdigest()
                       if golden.is_file() else None},
            "summary": result["summary"], "probes": result["probes"]}
    out = probes.OUT_ROOT if a.out is None else a.out
    d = runner._new_run_dir(Path(out), f"probes-temporal-{a.corpus}-{started:%Y%m%dT%H%M%S}")
    (d / "probes.json").write_text(json.dumps(data, indent=2, sort_keys=True,
                                              ensure_ascii=False) + "\n", encoding="utf-8")
    md = temporal.render_markdown(data)
    (d / "probes.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"{d}: {len(built)} probes; wall-clock {time.perf_counter() - t0:.1f} s")
    return 0


def _probe_store(a: argparse.Namespace, emb: Path):
    """(operator Tools of `--store`, its active index, system, whether it is the recorded
    Phase 1 index) for the ACL and equivalence probes; the index must be the Phase 1 one
    unless --allow-other-index, and the auditor's access must resolve (a fresh ACL snapshot
    for the store's HEAD) before anything is built."""
    from adr_store.tools import ToolError, Tools

    try:
        tools = Tools(a.store, emb_cache=emb)
        idx = tools.active_index()
        system = tools.active_system()
    except ToolError as e:
        raise runner.RunError(f"{a.store}: {e}") from e
    phase1 = system == systems.P2_REFERENCE and idx.fingerprint in \
        systems.phase1_fingerprints(a.corpus)
    if not phase1 and not a.allow_other_index:
        raise runner.RunError(
            f"{a.store}: the active index is {system} {idx.fingerprint[:12]}, not "
            f"{systems.P2_REFERENCE} with the fingerprint of a committed Phase 1 run of "
            f"{a.corpus}; pass --allow-other-index to probe this index")
    try:
        Tools(a.store, emb_cache=emb, acl=True, caller="user:auditor")._access()
    except ToolError as e:
        raise runner.RunError(f"{a.store}: {e}\nfix: run `adr acl sync --store {a.store}`") \
            from e
    return tools, idx, system, phase1


def _views_root(a: argparse.Namespace, config: dict) -> Path:
    if a.views is not None:
        return Path(a.views)
    return runner.REPO_ROOT / config.get("p2_store_dir", ".cache/store-p2") / "views" / \
        a.corpus


def _reference_stores(a, store, views, emb: Path, root: Path) -> tuple[dict, list[dict]]:
    """(caller -> reference store path for every user of every view, their descriptions):
    each view's store at `<root>/<view[:12]>`, built or reused (`ensure_view_store`)."""
    from adr_eval.probes import equivalence

    paths, info = {}, []
    for v in views:
        path = root / v.view[:12]
        _, how = equivalence.ensure_view_store(store, v.docs, path, emb_cache=emb,
                                               directory=a.directory, policy=a.policy)
        for u in v.users:
            paths[u] = path
        info.append({**v.summary(), **equivalence.describe(path), "how": how})
        print(f"  reference store {path.name}: {len(v.docs)} documents, {how}",
              file=sys.stderr)
    return paths, info


def _remove_views(a: argparse.Namespace, paths: dict, root: Path) -> list[str]:
    import shutil

    if a.keep_views:
        return []
    removed = sorted({str(runner._display_path(p)) for p in paths.values()})
    for p in sorted(set(paths.values())):
        shutil.rmtree(p)
    if root.is_dir() and not any(root.iterdir()):
        root.rmdir()
    return removed


def _store_config(a, tools, idx, system, phase1) -> dict:
    from adr_store import acl as acl_mod

    sid, snap = acl_mod.read_head(tools.store_path)
    return {"corpus": a.corpus, "store": runner._display_path(tools.store_path),
            "snapshot": tools.snapshot, "index": idx.fingerprint, "index_system": system,
            "index_phase1": phase1, "allow_other_index": a.allow_other_index,
            "acl_snapshot": sid, "acl_sequence": snap.sequence,
            "acl_entries_sha256": snap.entries_sha256,
            "directory_sha256": snap.directory_sha256, "policy_sha256": snap.policy_sha256}


def _write_probe_run(a, kind: str, started, files: dict, md: str) -> Path:
    from adr_eval import probes

    out = probes.OUT_ROOT if a.out is None else a.out
    d = runner._new_run_dir(Path(out), f"probes-{kind}-{a.corpus}-{started:%Y%m%dT%H%M%S}")
    for name, data in files.items():
        (d / name).write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
                              + "\n", encoding="utf-8")
    (d / "summary.md").write_text(md, encoding="utf-8")
    return d


def _probes_equivalence(a: argparse.Namespace) -> int:
    """`adr-eval probes equivalence <corpus>` (B2): every view of the store's ACL snapshot
    against its reference store (built under --views, kept with --keep-views)."""
    from datetime import UTC, datetime

    from adr_eval import probes
    from adr_eval.probes import acl as acl_probes
    from adr_eval.probes import equivalence
    from adr_store.tools import Tools

    t0 = time.perf_counter()
    started = datetime.now(UTC)
    config = runner.load_config()
    emb = runner.REPO_ROOT / config.get("embedding_cache_dir", ".cache/emb")
    tools, idx, system, phase1 = _probe_store(a, emb)
    cfg = _store_config(a, tools, idx, system, phase1)
    golden = runner.golden_items_path(a.corpus)
    items = [GoldenItem.model_validate_json(x) for x in
             jsonl_lines(golden.read_text(encoding="utf-8"))]
    qs = equivalence.questions(items, a.questions)
    from adr_store import acl as acl_mod

    snap = acl_mod.read_head(tools.store_path)[1]
    vs = equivalence.views(snap)
    root = _views_root(a, config)
    refs, info = _reference_stores(a, tools.store, vs, emb, root)
    offsets = {"store": acl_probes.log_size(acl_probes.log_path(tools.store_path)),
               **{p.name: acl_probes.log_size(acl_probes.log_path(p))
                  for p in set(refs.values())}}
    checks = []
    for v in vs:
        t = Tools(tools.store_path, emb_cache=emb, acl=True, caller=v.caller)
        ref = Tools(refs[v.caller], emb_cache=emb, acl=True, caller=v.caller)
        checks += equivalence.compare_view(t, ref, v, qs)
        print(f"  view {v.view[:12]} ({v.caller}): "
              f"{sum(c.identical for c in checks if c.view == v.view)} of "
              f"{sum(c.view == v.view for c in checks)} identical", file=sys.stderr)
    scans = {"store": acl_probes.scan_log(acl_probes.log_path(tools.store_path),
                                          offsets["store"]),
             **{p.name: acl_probes.scan_log(acl_probes.log_path(p), offsets[p.name])
                for p in set(refs.values())}}
    logs = {"total": acl_probes.total_scan(scans), "by_store": scans}
    summary = equivalence.summarize(checks)
    removed = _remove_views(a, refs, root)
    config_out = {**cfg, "kind": "equivalence", "seed": probes.SEED,
                  "questions": len(qs), "golden_sha256": hashlib.sha256(
                      golden.read_bytes()).hexdigest(),
                  "views": info, "views_removed": removed}
    probe_set = {"seed": probes.SEED, "questions": [
        {"item_id": i.id, "question": i.question, "qtype": i.qtype,
         "as_of": None if i.as_of is None else i.as_of.isoformat(),
         "grep": equivalence.grep_pattern(i.question)} for i in qs],
        "views": [v.summary() for v in vs], "modes": list(equivalence.MODES)}
    md = (f"# Equivalence probes (B2): {a.corpus}\n\nStore `{cfg['store']}` (snapshot "
          f"`{cfg['snapshot'][:12]}`, ACL snapshot `{cfg['acl_snapshot'][:12]}` sequence "
          f"{cfg['acl_sequence']}), index `{cfg['index'][:12]}`. {len(vs)} views x "
          f"{len(qs)} questions x search and grep x {len(equivalence.MODES)} modes. Seed "
          f"{probes.SEED}. No model calls.\n\n| tool/mode | checks | identical | refused | "
          f"empty |\n|---|---|---|---|---|\n" + "".join(
              f"| {k} | {b['n']} | {b['identical']} | {b['refused']} | {b['empty']} |\n"
              for k, b in summary["by_tool_mode"].items())
          + f"\nIdentical: {summary['identical']} of {summary['n']}. Log lines: "
            f"{logs['total']['lines']}, all with caller, principals, acl_snapshot and "
            f"acl_decision: {logs['total']['complete']}.\n")
    d = _write_probe_run(a, "equivalence", started,
                         {"probes.json": probe_set,
                          "results.json": {"checks": [c.to_dict() for c in checks]},
                          "summary.json": {"config": config_out, "summary": summary,
                                           "logs": logs}}, md)
    print(md)
    print(f"{d}: {summary['n']} checks; wall-clock {time.perf_counter() - t0:.1f} s")
    return 0 if summary["differing"] == 0 else 1


def _probes_acl(a: argparse.Namespace) -> int:
    """`adr-eval probes acl <corpus>` (B1, B4, B5 for the content tools): the leak probes
    against the reference stores (built or reused under --views) and the fail-closed probes
    (clones under --clones, removed)."""
    from datetime import UTC, datetime

    from adr_eval import probes
    from adr_eval.probes import acl as acl_probes
    from adr_eval.probes import equivalence
    from adr_store.tools import Tools

    t0 = time.perf_counter()
    started = datetime.now(UTC)
    config = runner.load_config()
    emb = runner.REPO_ROOT / config.get("embedding_cache_dir", ".cache/emb")
    tools, idx, system, phase1 = _probe_store(a, emb)
    cfg = _store_config(a, tools, idx, system, phase1)
    ctx = acl_probes.context(tools.store_path, idx)
    vs = equivalence.views(ctx.snap)
    root = _views_root(a, config)
    refs, info = _reference_stores(a, tools.store, vs, emb, root)
    store_log = acl_probes.log_path(tools.store_path)
    offsets = {"store": acl_probes.log_size(store_log),
               **{p.name: acl_probes.log_size(acl_probes.log_path(p))
                  for p in set(refs.values())}}
    sizes = None if a.per_family is None else dict.fromkeys(acl_probes.FAMILY_SIZES,
                                                            a.per_family)
    leak = acl_probes.leak_probes(ctx, sizes=sizes)
    def make_tools(path, caller):
        return Tools(path, emb_cache=emb, acl=True, caller=caller)

    fc = acl_probes.failclosed_probes(ctx, before=acl_probes.tools_precheck(
        tools.store_path, make_tools))
    results: dict[str, object] = {}
    for caller in sorted({p.caller for p in leak}, key=str):  # one caller's Tools at a time
        mine = Tools(tools.store_path, emb_cache=emb, acl=True, caller=caller)
        ref = None if caller not in refs else Tools(refs[caller], emb_cache=emb, acl=True,
                                                    caller=caller)
        for p in leak:
            if p.caller == caller:
                results[p.probe_id] = acl_probes.check(p, lambda c, m=mine: m,
                                                       lambda c, r=ref: r, ctx)
    leak_results = [results[p.probe_id] for p in leak]
    clones = Path(a.clones) if a.clones is not None else \
        runner.REPO_ROOT / config.get("p2_store_dir", ".cache/store-p2") / "clones" / a.corpus
    fc_results, fc_logs = acl_probes.run_failclosed(
        fc, tools.store_path, clones, ctx, directory=a.directory, policy=a.policy,
        make_tools=make_tools)
    if clones.is_dir() and not any(p for p in clones.iterdir() if p.is_dir()):
        import shutil

        shutil.rmtree(clones)
    scans = {"store": acl_probes.scan_log(store_log, offsets["store"]),
             **{p.name: acl_probes.scan_log(acl_probes.log_path(p), offsets[p.name])
                for p in set(refs.values())},
             **{k: v for k, v in fc_logs.items() if k != "store"}}
    logs = {"total": acl_probes.total_scan(scans), "by_store": scans}
    leak_summary = acl_probes.summarize(leak_results)
    fc_summary = acl_probes.summarize_failclosed(fc_results)
    removed = _remove_views(a, refs, root)
    config_out = {**cfg, "kind": "acl", "seed": probes.SEED,
                  "sizes": sizes or acl_probes.FAMILY_SIZES,
                  "views": info, "views_removed": removed,
                  "failclosed_callers": acl_probes.failclosed_callers(ctx)}
    md_rows = "".join(
        f"| {name} | {b['n']} | {b['leaks']} | {b['invalid']} | {b['callers']} | "
        f"{', '.join(f'{k} {v}' for k, v in b['checked_kinds'].items())} |\n"
        for name, b in leak_summary["families"].items())
    fc_rows = "".join(f"| {name} | {b['n']} | {b['passed']} | {b['content']} | "
                      f"{b['visible_before']} | {b['top10_before']} | "
                      f"{', '.join(f'{k} {v}' for k, v in b['outcomes'].items())} |\n"
                      for name, b in fc_summary["conditions"].items())
    md = (f"# ACL probes: {a.corpus}\n\nStore `{cfg['store']}` (snapshot "
          f"`{cfg['snapshot'][:12]}`, ACL snapshot `{cfg['acl_snapshot'][:12]}` sequence "
          f"{cfg['acl_sequence']}), index `{cfg['index'][:12]}`, {len(vs)} reference stores. "
          f"Seed {probes.SEED}. No model calls.\n\n## Leak probes\n\n| family | probes | "
          f"leaks | invalid | callers | kinds checked |\n|---|---|---|---|---|---|\n"
          + md_rows + f"\nTotal: {leak_summary['total']['n']} probes, "
          f"{leak_summary['total']['leaks']} leaks, {leak_summary['total']['invalid']} "
          f"invalid.\n\n## Fail closed\n\n| condition | probes | passed | with content | "
          f"visible before | top 10 before | outcomes |\n|---|---|---|---|---|---|---|\n"
          + fc_rows
          + f"\nTotal: {fc_summary['total']['n']} probes, {fc_summary['total']['passed']} "
            f"passed, {fc_summary['total']['content']} with content.\n\n## Log fields\n\n"
            f"{logs['total']['lines']} log lines, {logs['total']['complete_lines']} with "
            f"caller, principals, acl_snapshot and acl_decision; {logs['total']['allowed']} "
            f"allowed, {logs['total']['allowed_unresolved']} of them with a null caller, "
            f"principals, acl_snapshot or view.\n")
    probe_set = {"seed": probes.SEED, "leak": [p.to_dict() for p in leak],
                 "failclosed": [p.to_dict() for p in fc]}
    d = _write_probe_run(a, "acl", started,
                         {"probes.json": probe_set,
                          "results.json": {"leak": [r.to_dict() for r in leak_results],
                                           "failclosed": fc_results},
                          "summary.json": {"config": config_out, "leak": leak_summary,
                                           "failclosed": fc_summary, "logs": logs}}, md)
    print(md)
    print(f"{d}: {len(leak)} leak and {len(fc)} fail-closed probes; wall-clock "
          f"{time.perf_counter() - t0:.1f} s")
    ok = (leak_summary["total"]["leaks"] == 0 and leak_summary["total"]["invalid"] == 0
          and fc_summary["total"]["passed"] == fc_summary["total"]["n"]
          and logs["total"]["complete"])
    return 0 if ok else 1


def _run_dir(name: str, out: Path) -> Path:
    d = Path(name) if Path(name).is_dir() else out / name
    if not (d / "results.jsonl").is_file():
        raise runner.RunError(f"{d}: no results.jsonl; pass a run id under {out} or a run dir")
    return d


def _report(a: argparse.Namespace) -> int:
    run_dir = _run_dir(a.run_id, a.out)
    rep = write_report(run_dir)
    print(render_markdown(rep))
    if a.compare:
        other = _run_dir(a.compare, a.out)
        c = compare(run_dir, other)
        (run_dir / f"compare-{other.name}.json").write_text(
            json.dumps(c, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        md = render_compare_markdown(c)
        (run_dir / f"compare-{other.name}.md").write_text(md, encoding="utf-8")
        print(md)
    return 4 if rep["determinism_violation"] else 0  # the warning is in the markdown above


def _doctor(a: argparse.Namespace) -> int:
    """One line per profile: ok, why it is unconfigured, or (--live) a 1-token call's result."""
    config = runner.load_config()
    profiles = runner.load_profiles(runner.REPO_ROOT / config.get("models", runner.MODELS_PATH))
    unknown = sorted(set(a.profiles) - set(profiles))
    if unknown:
        raise runner.RunError(f"{runner.MODELS_PATH}: unknown profile(s) {', '.join(unknown)}")
    failed = False
    with tempfile.TemporaryDirectory() as tmp:  # a live check must reach the model
        for name in sorted(a.profiles or profiles):
            status = runner.profile_status(profiles[name]) or "ok"
            if status == "ok" and a.live:
                try:
                    client = runner.make_client(name, profiles, Cache(Path(tmp)), max_retries=0)
                    client.complete("Reply with the word OK.", "ping", max_tokens=1)
                except Exception as e:  # report any failure, per profile
                    status, failed = f"error: {e}", True
            print(f"{name}: {status}")
    return 1 if failed else 0


def _profile_args(p: argparse.ArgumentParser, judge: bool) -> None:
    p.add_argument("--generator", metavar="PROFILE", default=None,
                   help="model profile in config/models.json (default: config generator)")
    if judge:
        p.add_argument("--judge", metavar="PROFILE", default=None,
                       help="model profile in config/models.json (default: config judge)")
    p.add_argument("--max-calls", type=int, default=None, metavar="N",
                   help="stop before the model call that would exceed N (cache hits are free)")


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="adr-eval", description="Phase 0 evaluation harness")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("fetch", help="download and verify the corpus files in the manifest")
    p.add_argument("corpus", choices=NAMES)
    p.set_defaults(fn=_fetch)

    p = sub.add_parser("tools-fetch", help="download and verify the pinned ToolRet files "
                                           "(local-only) and write corpora/tools/manifest.json")
    p.add_argument("--root", type=Path, default=None,
                   help="data directory (default data/tools)")
    p.set_defaults(fn=_tools_fetch)

    p = sub.add_parser("golden", help="generate or verify the golden set")
    p.add_argument("corpus", choices=NAMES)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--gen", action="store_const", const=_golden_gen, dest="fn")
    mode.add_argument("--verify", action="store_const", const=_golden_verify, dest="fn")
    p.add_argument("--overwrite", action="store_true",
                   help="with --gen: replace an existing (frozen) items.jsonl")
    _profile_args(p, judge=True)

    p = sub.add_parser("index", help="build (or check) the saved hybrid index")
    p.add_argument("corpus", choices=NAMES)
    p.add_argument("--rebuild", action="store_true", help="replace a saved index")
    p.set_defaults(fn=_index)

    p = sub.add_parser("run", help="run a registered system over a split")
    p.add_argument("corpus", choices=NAMES)
    p.add_argument("--system", required=True, choices=systems.ALL_NAMES)
    p.add_argument("--repeats", type=int, default=None, help="default: config repeats")
    p.add_argument("--split", choices=("dev", "test"), default="test")
    p.add_argument("--max-dollars", type=float, default=None)
    p.add_argument("--dry-run", action="store_true", help="estimate calls and cost only")
    p.add_argument("--rebuild", action="store_true",
                   help="rebuild a stale saved index (a p2 system: the Phase 1 p1-struct-bc "
                        "index it reuses)")
    p.add_argument("--out", type=Path, default=Path("runs"), help="run output root")
    p.add_argument("--stub", action="store_true",
                   help="deterministic stub generator and judge (tests and demos)")
    _profile_args(p, judge=True)
    p.set_defaults(fn=_run)

    p = sub.add_parser("retrieval", help="retrieval track only (no model calls): "
                                         "retrieval.json/retrieval.md for a system")
    p.add_argument("corpus", choices=NAMES)
    p.add_argument("--system", required=True, choices=systems.ALL_NAMES)
    p.add_argument("--split", choices=("dev", "test"), default="test")
    p.add_argument("--rebuild", action="store_true",
                   help="rebuild a stale saved index (a p2 system: the Phase 1 p1-struct-bc "
                        "index it reuses)")
    p.add_argument("--lexical-only", action="store_true",
                   help="the system's BM25 channel alone (no embedding; a diagnostic)")
    p.add_argument("--out", type=Path, default=Path("runs"), help="run output root")
    p.set_defaults(fn=_retrieval)

    p = sub.add_parser("retrieval-compare",
                       help="paired comparison of two retrieval runs (run_b minus run_a)")
    p.add_argument("run_a")
    p.add_argument("run_b")
    p.add_argument("--allow-mixed", action="store_true",
                   help="compare a lexical-only run with a full run (marked in the output)")
    p.add_argument("--out", type=Path, default=Path("runs"), help="run output root")
    p.set_defaults(fn=_retrieval_compare)

    p = sub.add_parser("retrieval-identical",
                       help="exit 0 when two retrieval runs give the same items, ranked ids "
                            "and exact scores, else 1 with the first differences")
    p.add_argument("run_a")
    p.add_argument("run_b")
    p.add_argument("--show", type=int, default=5, metavar="N",
                   help="differences to print (default 5)")
    p.add_argument("--out", type=Path, default=Path("runs"), help="run output root")
    p.set_defaults(fn=_retrieval_identical)

    p = sub.add_parser("p2-compare",
                       help="Phase 2 comparison of two retrieval runs (run_b minus run_a): "
                            "slot counts, item subsets and non-inferiority (A3, A4)")
    p.add_argument("run_a")
    p.add_argument("run_b")
    p.add_argument("--store", type=Path, required=True,
                   help="the store whose HEAD the runs searched (chunks and overlays)")
    p.add_argument("--margin", type=float, default=0.02,
                   help="non-inferiority margin (default 0.02, fixed in the spec)")
    p.add_argument("--out", type=Path, default=None,
                   help="run output root (default runs); writes p2-compare-<a>--<b>/")
    p.set_defaults(fn=_p2_compare)

    p = sub.add_parser("probes", help="Phase 2 probe sets (no model calls): temporal (gov), "
                                      "acl (leak and fail-closed), equivalence (B2)")
    p.add_argument("kind", choices=("temporal", "acl", "equivalence"))
    p.add_argument("corpus", choices=NAMES)
    p.add_argument("--store", type=Path, required=True,
                   help="the store to probe (its active index and overlays)")
    p.add_argument("--views", type=Path, default=None, metavar="DIR",
                   help="acl, equivalence: where the reference stores are built or reused "
                        "(default <p2_store_dir>/views/<corpus>)")
    p.add_argument("--keep-views", action="store_true",
                   help="acl, equivalence: keep the reference stores (default: removed)")
    p.add_argument("--clones", type=Path, default=None, metavar="DIR",
                   help="acl: where the fail-closed clones go (default "
                        "<p2_store_dir>/clones/<corpus>; removed)")
    acl_config = runner.REPO_ROOT / "config" / "acl"
    p.add_argument("--directory", type=Path, default=acl_config / "directory.json",
                   help="acl, equivalence: the directory the reference stores and clones sync "
                        "from (default config/acl/directory.json)")
    p.add_argument("--policy", type=Path, default=acl_config / "policy.json",
                   help="acl, equivalence: the policy (default config/acl/policy.json)")
    p.add_argument("--questions", type=int, default=50, metavar="N",
                   help="equivalence: golden questions per view (default 50)")
    p.add_argument("--per-family", type=int, default=None, metavar="N",
                   help="acl: N leak probes per family instead of the spec's counts (a quick "
                        "check; recorded in the output)")
    p.add_argument("--as", dest="as_user", default=None, metavar="USER",
                   help="search as this caller (needs the ACL layer of Phase 2B)")
    p.add_argument("--dedup", action=argparse.BooleanOptionalAction, default=True,
                   help="collapse copies in search (default on)")
    p.add_argument("--allow-other-index", action="store_true",
                   help="probe an active index that is not p1-struct-bc with a recorded "
                        "Phase 1 fingerprint (recorded in the output)")
    p.add_argument("--out", type=Path, default=None,
                   help="output root (default runs); writes probes-<kind>-<corpus>-<ts>/")
    p.set_defaults(fn=_probes)

    p = sub.add_parser("report", help="write report.json/report.md for a run")
    p.add_argument("run_id")
    p.add_argument("--compare", metavar="RUN_ID", default=None)
    p.add_argument("--out", type=Path, default=Path("runs"), help="run output root")
    p.set_defaults(fn=_report)

    p = sub.add_parser("doctor", help="check each model profile in config/models.json")
    p.add_argument("--live", action="store_true", help="make a 1-token call per ready profile")
    p.add_argument("profiles", nargs="*", metavar="PROFILE", help="check only these profiles")
    p.set_defaults(fn=_doctor)
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = _parser()
    a = ap.parse_args(argv)
    if a.command == "golden" and a.fn is _golden_verify:
        given = [f for f, v in (("--generator", a.generator), ("--judge", a.judge),
                                ("--max-calls", a.max_calls),
                                ("--overwrite", a.overwrite or None)) if v is not None]
        if given:
            ap.error(f"golden --verify makes no model calls; remove {', '.join(given)} "
                     f"(used only with --gen)")
    try:
        if getattr(a, "corpus", None):
            check_local_files(a.corpus)
        return a.fn(a)
    except (runner.RunError, HashMismatch, LocalFilesMissing, ExtractionError,
            ToolRetMissing) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
