"""`adr-eval` command line: fetch, tools-fetch, golden, index, run, retrieval,
retrieval-compare, retrieval-identical, p2-compare, p3-q1, p3-q2, probes (temporal, acl,
equivalence; the table probes tables-leak, tables-sql, tables-equivalence, tables-failclosed,
tables-applicability, tables-mcp), tools-retrieval, tools-probes, mcp-probes, report, doctor."""

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
from typing import get_args

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
from adr_eval.models import GoldenItem, QType, jsonl_lines, write_items
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


def _tools_probes(a: argparse.Namespace) -> int:
    """`adr-eval tools-probes --store S` (B1, B4, B5 for `search_tools` and `load_tool`): the
    200 tool leak probes against per-caller reference indexes and the 80 tool fail-closed
    probes (clones under --clones, removed); writes <out>/probes-tools-<time>/."""
    import shutil
    from datetime import UTC, datetime

    from adr_eval import probes
    from adr_eval.probes import acl as acl_probes
    from adr_store import tools as store_tools

    t0 = time.perf_counter()
    started = datetime.now(UTC)
    emb = a.emb_cache if a.emb_cache is not None else store_tools.DEFAULT_EMB_CACHE
    if len(a.index) < store_tools.MIN_PREFIX:
        raise runner.RunError(f"--index needs at least {store_tools.MIN_PREFIX} characters of "
                              f"the tool index fingerprint, got {a.index!r}")
    try:
        idx = store_tools.Tools(a.store, emb_cache=emb).active_tool_index()
    except store_tools.ToolError as e:
        raise runner.RunError(str(e)) from e
    if not idx.fingerprint.startswith(a.index):
        raise runner.RunError(f"{a.store}: the active tool index is {idx.fingerprint[:12]}, not "
                              f"{a.index}; run `adr tools index` with the chosen system's "
                              f"values first (the probes run against the active index)")
    ctx = acl_probes.tool_context(a.store, idx)

    def make_tools(path, caller):
        return store_tools.Tools(path, emb_cache=emb, acl=True, caller=caller)

    sizes = None if a.per_family is None else dict.fromkeys(acl_probes.TOOL_FAMILY_SIZES,
                                                            a.per_family)
    leak = acl_probes.tool_leak_probes(ctx, sizes=sizes)
    users = acl_probes.failclosed_callers(ctx)
    fc = acl_probes.tool_failclosed_probes(ctx, acl_probes.tool_precheck(a.store, make_tools),
                                           users)
    store_log = acl_probes.log_path(a.store)
    offset = acl_probes.log_size(store_log)
    made: dict = {}

    def tools_for(caller):
        if caller not in made:
            made[caller] = make_tools(a.store, caller)
        return made[caller]

    leak_results = [acl_probes.check_tool(p, tools_for, ctx) for p in leak]
    config = runner.load_config()
    clones = Path(a.clones) if a.clones is not None else \
        runner.REPO_ROOT / config.get("p2_store_dir", ".cache/store-p2") / "clones" / "tools"
    fc_results, fc_logs = acl_probes.run_tool_failclosed(
        fc, a.store, clones, ctx, make_tools=make_tools, directory=a.directory,
        policy=a.policy)
    if clones.is_dir() and not any(clones.iterdir()):
        shutil.rmtree(clones)
    scans = {"store": acl_probes.scan_log(store_log, offset),
             **{k: v for k, v in fc_logs.items() if k != "store"}}
    logs = {"total": acl_probes.total_scan(scans), "by_store": scans}
    leak_summary = acl_probes.summarize(leak_results)
    fc_summary = acl_probes.summarize_failclosed(fc_results)
    sid, snap = acl_probes.acl.read_head(a.store)
    cfg = {"kind": "tools", "store": str(a.store), "tools_snapshot": idx.tool_snapshot,
           "tool_index": idx.fingerprint, "acl_snapshot": sid, "acl_sequence": snap.sequence,
           "seed": probes.SEED, "sizes": sizes or acl_probes.TOOL_FAMILY_SIZES,
           "failclosed_callers": users, "failclosed_target": fc[0].target["tool_id"]}
    rows = "".join(f"| {name} | {b['n']} | {b['leaks']} | {b['invalid']} | {b['callers']} | "
                   f"{', '.join(f'{k} {v}' for k, v in b['checked_kinds'].items())} |\n"
                   for name, b in leak_summary["families"].items())
    fc_rows = "".join(f"| {name} | {b['n']} | {b['passed']} | {b['content']} | "
                      f"{', '.join(f'{k} {v}' for k, v in b['outcomes'].items())} |\n"
                      for name, b in fc_summary["conditions"].items())
    md = (f"# ACL probes: tools\n\nStore `{cfg['store']}` (tool snapshot "
          f"`{cfg['tools_snapshot'][:12]}`, ACL snapshot `{sid[:12]}` sequence {snap.sequence}),"
          f" tool index `{idx.fingerprint[:12]}`. Seed {probes.SEED}. No model calls.\n\n"
          f"## Leak probes\n\n| family | probes | leaks | invalid | callers | kinds checked |\n"
          f"|---|---|---|---|---|---|\n" + rows +
          f"\nTotal: {leak_summary['total']['n']} probes, {leak_summary['total']['leaks']} "
          f"leaks, {leak_summary['total']['invalid']} invalid.\n\n## Fail closed\n\n"
          f"| condition | probes | passed | with content | outcomes |\n|---|---|---|---|---|\n"
          + fc_rows + f"\nTotal: {fc_summary['total']['n']} probes, "
          f"{fc_summary['total']['passed']} passed, {fc_summary['total']['content']} with "
          f"content.\n\n## Log fields\n\n{logs['total']['lines']} log lines, "
          f"{logs['total']['complete_lines']} with caller, principals, acl_snapshot and "
          f"acl_decision; {logs['total']['allowed']} allowed, "
          f"{logs['total']['allowed_unresolved']} of them unresolved.\n")
    d = Path(a.out or probes.OUT_ROOT) / f"probes-tools-{started:%Y%m%dT%H%M%S}"
    d.mkdir(parents=True, exist_ok=False)
    files = {"probes.json": {"seed": probes.SEED, "leak": [p.to_dict() for p in leak],
                             "failclosed": [p.to_dict() for p in fc]},
             "results.json": {"leak": [r.to_dict() for r in leak_results],
                              "failclosed": fc_results},
             "summary.json": {"config": cfg, "leak": leak_summary, "failclosed": fc_summary,
                              "logs": logs}}
    for name, data in files.items():
        (d / name).write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False,
                                         default=str) + "\n", encoding="utf-8")
    (d / "probes.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"{d}: {len(leak)} tool leak and {len(fc)} tool fail-closed probes; wall-clock "
          f"{time.perf_counter() - t0:.1f} s")
    ok = (leak_summary["total"]["leaks"] == 0 and leak_summary["total"]["invalid"] == 0
          and fc_summary["total"]["passed"] == fc_summary["total"]["n"]
          and logs["total"]["complete"])
    return 0 if ok else 1


MCP_STORES = ("gov", "research", "bench", "tools")


def _mcp_stores(a: argparse.Namespace, p2: Path) -> dict[str, Path]:
    """label -> store path for `mcp-probes`: the corpora's p2 copies and the ToolRet store,
    unless given as LABEL=PATH (labels: the corpora and `tools`)."""
    if not a.store:
        return {c: p2 / ("toolret" if c == "tools" else c) for c in MCP_STORES}
    out = {}
    for spec in a.store:
        label, sep, path = spec.partition("=")
        if not sep or label not in (*NAMES, "tools"):
            raise runner.RunError(f"--store takes LABEL=PATH with LABEL one of "
                                  f"{', '.join((*NAMES, 'tools'))}, got {spec!r}")
        out[label] = Path(path)
    return out


def _mcp_probes(a: argparse.Namespace) -> int:
    """`adr-eval mcp-probes` (B1 through MCP, B5 of its calls): the seeded subset of the leak
    probes of every store (`adr_eval.probes.mcp`), each run through an `adr mcp` server of its
    caller and judged as the API probes are; writes <out>/probes-mcp-<time>/."""
    from datetime import UTC, datetime

    from adr_eval import probes
    from adr_eval.probes import acl as acl_probes
    from adr_eval.probes import equivalence
    from adr_eval.probes import mcp as mcp_probes
    from adr_store import acl as acl_mod
    from adr_store import tools as store_tools
    from adr_store.mcp_client import McpTools

    t0 = time.perf_counter()
    started = datetime.now(UTC)
    config = runner.load_config()
    emb = a.emb_cache if a.emb_cache is not None else \
        runner.REPO_ROOT / config.get("embedding_cache_dir", ".cache/emb")
    p2 = runner.REPO_ROOT / config.get("p2_store_dir", ".cache/store-p2")
    stores = _mcp_stores(a, p2)
    contexts: dict = {}
    universe: list = []
    cfg_stores: dict = {}
    ops: dict = {}
    nss: dict = {}
    for label, path in stores.items():
        if label == "tools":
            if a.tool_index is None or len(a.tool_index) < store_tools.MIN_PREFIX:
                raise runner.RunError(f"--tool-index needs at least {store_tools.MIN_PREFIX} "
                                      f"characters of the tool index fingerprint")
            try:
                idx = store_tools.Tools(path, emb_cache=emb).active_tool_index()
                store_tools.Tools(path, emb_cache=emb, acl=True,
                                  caller="user:auditor").search_tools("probe", top=1)
            except store_tools.ToolError as e:
                raise runner.RunError(f"{path}: {e}\nfix: run `adr acl sync --store {path}`") \
                    from e
            if not idx.fingerprint.startswith(a.tool_index):
                raise runner.RunError(f"{path}: the active tool index is "
                                      f"{idx.fingerprint[:12]}, not {a.tool_index}")
            ctx = acl_probes.tool_context(path, idx)
            ps = acl_probes.tool_leak_probes(ctx, sizes=None if a.per_family is None else
                                             dict.fromkeys(acl_probes.TOOL_FAMILY_SIZES,
                                                           a.per_family))
            sid, snap = acl_mod.read_head(path)
            cfg_stores[label] = {"store": runner._display_path(Path(path)),
                                 "tools_snapshot": idx.tool_snapshot,
                                 "tool_index": idx.fingerprint, "acl_snapshot": sid,
                                 "acl_sequence": snap.sequence,
                                 "acl_entries_sha256": snap.entries_sha256}
        else:
            ns = argparse.Namespace(store=path, corpus=label, directory=a.directory,
                                    policy=a.policy, allow_other_index=a.allow_other_index,
                                    keep_views=a.keep_views, views=None)
            tools, idx, system, phase1 = _probe_store(ns, emb)
            cfg_stores[label] = _store_config(ns, tools, idx, system, phase1)
            ctx = acl_probes.context(tools.store_path, idx)
            ps = acl_probes.leak_probes(ctx, sizes=None if a.per_family is None else
                                        dict.fromkeys(acl_probes.FAMILY_SIZES, a.per_family))
            ops[label], nss[label] = tools, ns
        contexts[label] = ctx
        universe += [(label, p) for p in ps]
        print(f"  {label}: {len(ps)} leak probes", file=sys.stderr)
    selected = mcp_probes.select(universe, a.n)
    counts = {"universe": mcp_probes.family_counts(universe),
              "selected": mcp_probes.family_counts(selected)}
    short = mcp_probes.short_families(counts["selected"])
    refs: dict = {}
    roots: dict = {}
    infos: dict = {}
    for label, tools in ops.items():
        roots[label] = (Path(a.views) if a.views is not None else p2 / "views") / label
        refs[label], infos[label] = _reference_stores(
            nss[label], tools.store, equivalence.views(contexts[label].snap), emb,
            roots[label])
    logs_of = {}  # one scan per log file (two labels may name one store)
    for label, path in stores.items():
        logs_of.setdefault(acl_probes.log_path(path).resolve(), label)
    offsets = {label: acl_probes.log_size(log) for log, label in logs_of.items()}
    ref_offsets = {(label, p.name): acl_probes.log_size(acl_probes.log_path(p))
                   for label, r in refs.items() for p in set(r.values())}
    ref_tools: dict = {}

    def reference_for(label, caller):
        if caller not in refs.get(label, {}):
            return None
        if (label, caller) not in ref_tools:
            ref_tools[(label, caller)] = store_tools.Tools(refs[label][caller], emb_cache=emb,
                                                           acl=True, caller=caller)
        return ref_tools[(label, caller)]

    env = {"HF_HUB_OFFLINE": "1"}

    def make_server(label, caller):
        return McpTools(stores[label], caller, emb_cache=emb, env=env, cwd=runner.REPO_ROOT,
                        timeout=a.timeout)

    results, calls = mcp_probes.run_subset(selected, contexts=contexts,
                                           reference_for=reference_for,
                                           make_server=make_server)
    mcp_scans = {label: acl_probes.scan_log(log, offsets[label])
                 for log, label in logs_of.items()}
    ref_scans = {f"{label}/{name}": acl_probes.scan_log(
        acl_probes.log_path(root / name), off)
        for (label, name), off in ref_offsets.items() for root in [roots[label]]}
    n_calls = sum(sum(v.values()) for v in calls.values())
    logs = {"mcp": {"total": acl_probes.total_scan(mcp_scans), "by_store": mcp_scans,
                    "calls": calls, "calls_total": n_calls},
            "reference": {"total": acl_probes.total_scan(ref_scans) if ref_scans else None,
                          "by_store": ref_scans}}
    removed = {label: _remove_views(nss[label], refs[label], roots[label]) for label in refs}
    summary = mcp_probes.summarize(results)
    cfg = {"kind": "mcp", "seed": probes.SEED, "n": a.n, "stores": cfg_stores,
           "per_family": a.per_family,
           "universe": len(universe), "counts": counts, "short_families": short,
           "min_per_family": mcp_probes.MIN_PER_FAMILY, "server_env": env,
           "views": infos, "views_removed": removed}
    rows = "".join(f"| {name} | {counts['universe']['families'].get(name, 0)} | {b['n']} | "
                   f"{b['leaks']} | {b['invalid']} | {b['callers']} | "
                   f"{', '.join(f'{k} {v}' for k, v in b['outcomes'].items())} |\n"
                   for name, b in summary["families"].items())
    spec_rows = "".join(f"| {f} | {counts['universe']['spec_families'][f]} | {b['n']} | "
                        f"{b['leaks']} | {b['invalid']} |\n"
                        for f, b in summary["spec_families"].items())
    mt = logs["mcp"]["total"]
    md = (f"# ACL probes through MCP (B1 subset)\n\nThe {a.n} of {len(universe)} leak probes "
          f"with the lowest SHA-256 of `<seed>:<store>/<probe id>` (seed {probes.SEED}), each "
          f"through an `adr mcp` server of its caller. No model calls.\n\n| family | universe | "
          f"probes | leaks | invalid | callers | outcomes |\n|---|---|---|---|---|---|---|\n"
          + rows + "\n| spec family | universe | probes | leaks | invalid |\n"
          "|---|---|---|---|---|\n" + spec_rows
          + f"\nTotal: {summary['total']['n']} probes, {summary['total']['leaks']} leaks, "
            f"{summary['total']['invalid']} invalid. Spec families under "
            f"{mcp_probes.MIN_PER_FAMILY}: {short or 'none'}.\n\n## Log fields (MCP calls)\n\n"
            f"{n_calls} calls through MCP; {mt['lines']} log lines in the probed stores, "
            f"{mt['complete_lines']} with caller, principals, acl_snapshot and acl_decision; "
            f"{mt['allowed']} allowed, {mt['allowed_unresolved']} of them unresolved.\n")
    d = runner._new_run_dir(Path(a.out or probes.OUT_ROOT),
                            f"probes-mcp-{started:%Y%m%dT%H%M%S}")
    files = {"probes.json": {"seed": probes.SEED, "n": a.n, "selected": [
                 {"store": label, "key": mcp_probes.sample_key(label, p.probe_id),
                  **p.to_dict()} for label, p in selected]},
             "results.json": {"results": [{"store": label, **r.to_dict()}
                                          for label, r in results]},
             "summary.json": {"config": cfg, "summary": summary, "logs": logs}}
    for name, data in files.items():
        (d / name).write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False,
                                         default=str) + "\n", encoding="utf-8")
    (d / "summary.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"{d}: {len(selected)} probes through MCP; wall-clock {time.perf_counter() - t0:.1f} s")
    ok = (summary["total"]["leaks"] == 0 and summary["total"]["invalid"] == 0
          and mt["complete"] and mt["lines"] == n_calls)
    return 0 if ok else 1


def _tools_retrieval(a: argparse.Namespace) -> int:
    """`adr-eval tools-retrieval` (Phase 2 spec §8.4): one tool system over one ToolRet split;
    writes <out>/tools-<system>-<split>-<time>/tools.{json,md}."""
    from adr_eval import tools_eval

    d = tools_eval.run(a.system, a.split, a.store, root=a.root, lexical_only=a.lexical_only,
                       out=a.out, emb_cache=a.emb_cache, threads=a.threads, sync=a.sync)
    rec = json.loads((d / "tools.json").read_text(encoding="utf-8"))
    print((d / "tools.md").read_text(encoding="utf-8"), end="")
    print(f"{d}: {rec['summary']['n']} queries")
    return 0


LOCAL_ONLY_GOLDEN = ("bench", "research")  # item files hold verbatim source text; not in git


def _exclusions(corpus: str) -> dict[str, str]:
    from adr_eval.golden.verify import EXCLUSIONS_FILE, load_exclusions

    return load_exclusions(runner.golden_dir(corpus) / EXCLUSIONS_FILE)


def _golden_gen(a: argparse.Namespace) -> int:
    if a.corpus == TABLES_GOLDEN:
        return _golden_tables_gen(a)
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


TABLES_GOLDEN = "tables"   # `adr-eval golden tables`: the gov-tables v0.1 set (Phase 3 §10.3)


def _stopped(max_calls: int, units: int) -> str:
    """The status line of a command stopped by its call cap (as `adr tables extract`)."""
    return (f"status: stopped at --max-calls {max_calls} ({units} budget unit(s) used); "
            f"nothing written. Completed calls are cached: rerun to continue.")


def _failed(error: Exception, units: int) -> str:
    """The status line of a command stopped by a model failure that is not cached (retries
    exhausted, the usage limit, a configuration error; ruling P21)."""
    text = " ".join(str(error).split())
    return (f"status: stopped: {text} ({units} budget unit(s) used); nothing written. "
            f"Completed calls are cached: rerun to continue.")


def _golden_tables_gen(a: argparse.Namespace) -> int:
    """`adr-eval golden tables --gen --store S --facts ID --generator P --max-calls N`: the
    gov-tables v0.1 items from the second-pass facts `ID` of store `S`, phrased by profile `P`
    under `N` budget units (every transport attempt counts). A stop at the cap or on a model
    failure that is no input rejection exits 1 and writes nothing; a rerun reads the completed
    calls from the cache."""
    from adr_eval.golden import tables
    from adr_eval.llm import ModelError
    from adr_eval.pipeline import BudgetExceeded
    from adr_store.tables.extract import metered_client
    from adr_store.tables.overlay import TablesError

    out = tables.GOLDEN_DIR
    if (out / "items.jsonl").exists() and not a.overwrite:  # before any client or call
        print(f"error: {out / 'items.jsonl'} exists and is frozen (a regenerated set is a new "
              f"version); pass --overwrite to replace it", file=sys.stderr)
        return 2
    try:
        meter = metered_client(a.max_calls, profile=a.generator)
    except runner.ProfileError as e:
        raise runner.RunError(str(e)) from e
    try:
        res = tables.generate_all(a.store, a.facts, meter, n=tables.N_ITEMS)
    except TablesError as e:
        raise runner.RunError(str(e)) from e
    except BudgetExceeded:
        print(_stopped(a.max_calls, meter.budget.calls))
        return 1
    except ModelError as e:            # a stored input rejection never reaches here
        print(_failed(e, meter.budget.calls))
        return 1
    tables.write_items(out, res.items, res.rejected)
    dev = sum(i.split == "dev" for i in res.items)
    ops = Counter(i.qtype for i in res.items)
    c, calls = res.counts, res.counts["calls"]
    reasons = Counter(r["reason"] for r in res.rejected)
    print(f"{out}: {len(res.items)} items ({dev} dev, {len(res.items) - dev} test); per op "
          f"{dict(sorted(ops.items()))}; facts {a.facts[:12]}")
    print(f"  {c['draws']} draws: {c['duplicates']} repeats, {c['unusable']} unusable, "
          f"{len(res.rejected)} rejected {dict(sorted(reasons.items()))}")
    print(f"status: complete; {calls['made']} model call(s) made, {calls['cached']} cached, "
          f"{calls['failed']} failed; {meter.budget.calls} budget unit(s) of {a.max_calls} "
          f"used; served {', '.join(sorted(meter.served_models)) or 'none reported'}")
    if len(res.items) < tables.N_ITEMS:
        print(f"  short of {tables.N_ITEMS} items: the draws ran out (reported, not padded)")
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
    """`adr-eval run`. With `--golden gov-tables` (tables mode, Phase 3 §10.3, §11) the default
    is one repeat (the budget is one query and, for a chunk system, one answer call per item),
    and a stop at the call cap or on a model failure that is no input rejection exits 1 with
    nothing written."""
    from adr_eval.llm import ModelError
    from adr_eval.pipeline import BudgetExceeded

    config = runner.load_config()
    if a.stub:
        config["stub"] = True
    for role in ("generator", "judge"):
        if getattr(a, role):
            config[role] = getattr(a, role)
    tables = a.golden == runner.GOV_TABLES
    if tables and a.judge:
        raise runner.RunError("a gov-tables run makes no judge call; remove --judge")
    if tables and a.max_calls is None and not (a.stub or a.dry_run):
        raise runner.RunError("a gov-tables run needs --max-calls (its share of the approved "
                              "budget; every transport attempt counts)")
    repeats = a.repeats if a.repeats is not None else (1 if tables else config["repeats"])
    try:
        run_id = runner.run(a.corpus, a.system, a.split, repeats, config, out_root=a.out,
                            max_dollars=a.max_dollars, dry_run=a.dry_run, rebuild=a.rebuild,
                            max_calls=a.max_calls,
                            qtypes=None if a.qtype is None else tuple(a.qtype),
                            golden=a.golden)
    except BudgetExceeded as e:        # tables mode only: v0.1 runs stop per item
        print(f"status: {e}")
        return 1
    except ModelError as e:            # tables mode only; a stored input rejection is a row
        print(f"status: stopped: {' '.join(str(e).split())}; nothing written. Completed "
              f"calls are cached: rerun to continue.")
        return 1
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


def _p3_q1(a: argparse.Namespace) -> int:
    """`adr-eval p3-q1 TYPED_RUN BASELINE_RUN`: Q1 (`phase3.q1_compare`) with the `also_in`
    readings of the corpus's golden items; printed and written to
    `<typed run>/q1-<baseline run>.json` (it names items: keep it in runs/). With
    `--summary OUT` the committed form (`phase3.q1_summary`, no item id or filter value) is
    written to OUT too."""
    from adr_eval import phase3

    typed, base = Path(a.typed_run), Path(a.baseline_run)
    c = phase3.q1_compare(typed, base)
    loaded = runner.load_checked_corpus(c["corpus"])
    c["also_in"] = phase3.also_in_readings(runner.load_golden(c["corpus"], loaded),
                                           get_adapter(c["corpus"]).records(loaded))
    text = json.dumps(c, indent=2, sort_keys=True) + "\n"
    (typed / f"q1-{base.name}.json").write_text(text, encoding="utf-8")
    if a.summary is not None:
        a.summary.parent.mkdir(parents=True, exist_ok=True)
        a.summary.write_text(json.dumps(phase3.q1_summary(c), indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
    print(text, end="")
    return 0


def _p3_q2(a: argparse.Namespace) -> int:
    """`adr-eval p3-q2 TYPED_RUN BASELINE_RUN`: Q2 (`phase3.q2_compare`, spec §12), printed and
    written to `<typed run>/q2-<baseline run>.json` (it names items: keep it in runs/); with
    `--summary OUT` the committed form (`phase3.q2_summary`) is written to OUT too."""
    from adr_eval import phase3

    typed, base = Path(a.typed_run), Path(a.baseline_run)
    c = phase3.q2_compare(typed, base)
    text = json.dumps(c, indent=2, sort_keys=True) + "\n"
    (typed / f"q2-{base.name}.json").write_text(text, encoding="utf-8")
    if a.summary is not None:
        a.summary.parent.mkdir(parents=True, exist_ok=True)
        a.summary.write_text(json.dumps(phase3.q2_summary(c), indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
    d = c["difference"]
    print(text, end="")
    print(f"Q2 {'pass' if c['passed'] else 'fail'}: p3-typed {c['typed']['accuracy']:.3f} "
          f"(>= {phase3.Q2_MIN_ACCURACY}: {c['accuracy_ok']}), baseline-linear "
          f"{c['baseline']['accuracy']:.3f}; difference {d['mean']:+.3f} [{d['ci95'][0]:+.3f}, "
          f"{d['ci95'][1]:+.3f}] (lower bound > +{phase3.Q2_MARGIN}: {c['margin_ok']}); "
          f"McNemar b={c['b']} c={c['c']} p={c['mcnemar_p']:.4g}; n={c['n']}")
    return 0


def _probes(a: argparse.Namespace) -> int:
    if a.kind.startswith("tables-"):
        return _probes_tables(a)
    if a.corpus == "tools":
        raise runner.RunError(f"the {a.kind} probes take a content corpus, not tools")
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
    for name, data in files.items():   # a lone surrogate (a probe statement) as its \u escape
        (d / name).write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
                              + "\n", encoding="utf-8", errors="backslashreplace")
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


TABLE_KINDS = ("tables-leak", "tables-sql", "tables-equivalence", "tables-failclosed",
               "tables-applicability", "tables-mcp")


def _tables_config(a: argparse.Namespace, path: Path, label: str) -> dict:
    """What a table probe run read of one store: snapshot, tables id, ACL snapshot."""
    from adr_store import acl as acl_mod
    from adr_store import handles
    from adr_store.store import Store

    store = Store.open(path)
    sid, snap = acl_mod.read_head(path)
    return {"corpus": label, "store": runner._display_path(Path(path)),
            "snapshot": store.snapshot_id,
            "tables": handles.tables_head(path, store.snapshot_id), "acl_snapshot": sid,
            "acl_sequence": snap.sequence, "acl_entries_sha256": snap.entries_sha256,
            "directory_sha256": snap.directory_sha256, "policy_sha256": snap.policy_sha256}


def _tables_fresh(path: Path) -> None:
    """Refuse a store whose ACL does not resolve for the auditor now (stale, not for HEAD)."""
    from adr_store.tools import AccessDenied, Tools

    try:
        Tools(path, acl=True, caller="user:auditor")._access()
    except AccessDenied as e:
        raise runner.RunError(f"{path}: {e}\nfix: run `adr acl sync --store {path}`") from e


def _probes_tables(a: argparse.Namespace) -> int:
    """`adr-eval probes tables-<kind> <corpus> --store S` (Phase 3 spec §10.4; S1, S2, S3 and
    the MCP leg of D1): the table probes of `adr_eval.probes.tables`, through `Tools` with the
    ACL layer (tables-mcp: through `adr mcp` servers), against reference stores of each view
    built or reused under --views (removed unless --keep-views). Writes
    <out>/probes-<kind>-<corpus>-<time>/: probes.json, results.json (per-item rows),
    summary.json and summary.md (counts only)."""
    from datetime import UTC, datetime

    from adr_eval.probes import tables as tp

    if a.corpus not in tp.TABLE_CORPORA and a.kind != "tables-equivalence":
        raise runner.RunError(f"{a.kind} needs a store with tables (gov or research), not "
                              f"{a.corpus}; bench and tools are checked empty by "
                              f"tables-equivalence")
    t0 = time.perf_counter()
    started = datetime.now(UTC)
    config = runner.load_config()
    emb = runner.REPO_ROOT / config.get("embedding_cache_dir", ".cache/emb")
    p2 = runner.REPO_ROOT / config.get("p2_store_dir", ".cache/store-p2")
    _tables_fresh(a.store)
    kw = {"directory": a.directory, "policy": a.policy, "emb_cache": emb}
    root = Path(a.views) if a.views is not None else p2 / "views-tables" / a.corpus
    ctx = tp.table_context(a.store)
    refs = tp.References(ctx, root, **kw)
    cfg = {**_tables_config(a, a.store, a.corpus), "kind": a.kind, "seed": tp.SEED3}
    store_log = tp.log_path(a.store)
    offset = tp.log_size(store_log)
    statements: list[str] = []
    extra_logs: dict = {}
    probe_set: dict = {"seed": tp.SEED3}
    if a.kind == "tables-leak":
        sizes = None if a.per_family is None else dict.fromkeys(tp.LEAK_SIZES[a.corpus],
                                                                a.per_family)
        probes = tp.leak_probes(a.store, a.corpus, sizes=sizes)
        results = tp.run_leaks(probes, a.store, root, refs=refs, **kw)
        statements = [c["args"]["statement"] for p in probes for c in p.call["calls"]
                      if c["tool"] == "sql"]
        summary = tp.summarize_leaks(results)
        cfg["sizes"] = sizes or tp.LEAK_SIZES[a.corpus]
        probe_set["leak"] = [p.to_dict() for p in probes]
        rows = [r.to_dict() for r in results]
        ok = summary["total"]["leaks"] == 0 and summary["total"]["invalid"] == 0
        head = f"{summary['total']['n']} leak probes, {summary['total']['leaks']} leaks, " \
               f"{summary['total']['invalid']} invalid; {summary['total']['compared']} " \
               f"compared with a reference store, {summary['total']['ghost']} as user:ghost " \
               f"(denied F4: no directory user has a hidden row)"
        table = ("| family | probes | leaks | invalid | callers | outcomes |\n"
                 "|---|---|---|---|---|---|\n" + "".join(
                     f"| {n} | {b['n']} | {b['leaks']} | {b['invalid']} | {b['callers']} | "
                     f"{', '.join(f'{k} {v}' for k, v in b['outcomes'].items())} |\n"
                     for n, b in summary["families"].items()))
    elif a.kind == "tables-sql":
        rows = tp.sql_guard(a.store, a.as_user or "user:auditor")
        statements = [r["statement"] for r in rows]
        summary = tp.summarize_guard(rows)
        cfg["caller"] = a.as_user or "user:auditor"
        probe_set["cases"] = [{"category": c, "statement": s} for c, s in tp.SQL_GUARD_CASES]
        ok = summary["total"]["passed"] == summary["total"]["n"]
        head = f"{summary['total']['n']} statements, {summary['total']['passed']} refused " \
               f"with a fixed message or bounded, {summary['total']['intact']} with the " \
               f"database intact afterwards"
        table = ("| category | cases | passed | outcomes |\n|---|---|---|---|\n" + "".join(
            f"| {n} | {b['n']} | {b['passed']} | "
            f"{', '.join(f'{k} {v}' for k, v in b['outcomes'].items())} |\n"
            for n, b in summary["categories"].items()))
    elif a.kind == "tables-equivalence":
        gold = None
        if a.corpus in tp.TABLE_CORPORA:
            gold = Path(a.gold) if a.gold is not None else runner.golden_dir(a.corpus)
            gold = gold / "items.jsonl" if gold.is_dir() else gold
            cfg["gold_sha256"] = hashlib.sha256(gold.read_bytes()).hexdigest()
        rows = tp.equivalence(a.store, a.corpus, root, a.queries, gold=gold, refs=refs, **kw)
        statements = list(tp.EQUIVALENCE_SQL.get(a.corpus, ()))
        summary = tp.summarize_equivalence(rows)
        cfg["queries"] = a.queries
        if a.corpus in tp.TABLE_CORPORA:
            pool, sql = tp.equivalence_queries(ctx, gold)
            probe_set["query_table"] = pool
            probe_set["sql"] = sql
        ok = summary["differing"] == 0 and \
            summary["empty_checks"]["identical"] == summary["empty_checks"]["n"]
        head = (f"{summary['identical']} of {summary['n']} identical over "
                f"{summary['views']} views" if summary["n"] else
                f"no tables: {summary['empty_checks']['identical']} of "
                f"{summary['empty_checks']['n']} table tool calls refused alike on the store "
                f"and the reference ({summary['views']} views; not counted)")
        table = ("| tool | calls | identical | refused |\n|---|---|---|---|\n" + "".join(
            f"| {n} | {b['n']} | {b['identical']} | {b['refused']} |\n"
            for n, b in summary["by_tool"].items()))
    elif a.kind == "tables-failclosed":
        clones = Path(a.clones) if a.clones is not None else p2 / "clones" / a.corpus
        rows = tp.failclosed(a.store, clones, a.corpus, logs=extra_logs, **kw)
        extra_logs.pop("store", None)   # the store's log is scanned below
        probe_set["target"] = rows[0]["target"]
        summary = tp.summarize_failclosed(rows)
        cfg["failclosed_callers"] = sorted({r["caller"] for r in rows
                                            if r["family"] == "no_entry"})
        ok = summary["total"]["passed"] == summary["total"]["n"]
        head = f"{summary['total']['n']} probes, {summary['total']['passed']} passed, " \
               f"{summary['total']['content']} with content; target document " \
               f"`{rows[0]['target']['doc_id'][:12]}` ({rows[0]['target']['table']})"
        table = ("| condition | probes | passed | with content | outcomes |\n"
                 "|---|---|---|---|---|\n" + "".join(
                     f"| {n} | {b['n']} | {b['passed']} | {b['content']} | "
                     f"{', '.join(f'{k} {v}' for k, v in b['outcomes'].items())} |\n"
                     for n, b in summary["conditions"].items()))
    elif a.kind == "tables-applicability":
        rows = tp.applicability_probes(a.store, n=a.n or 50)
        statements = [tp.applicability_statement(t) for t in sorted({r["table"] for r in rows})]
        summary = tp.summarize_applicability(rows)
        ok = summary["total"]["passed"] == summary["total"]["n"]
        head = (f"{summary['total']['n']} probes on {', '.join(summary['tables'])} "
                f"({summary['total']['default']} default, {summary['total']['as_of']} as_of "
                f"over {summary['total']['dates']} dates), {summary['total']['passed']} passed, "
                f"{summary['total']['outside']} rows of documents not in force")
        table = ""
    else:   # tables-mcp
        return _probes_tables_mcp(a, tp, ctx, refs, root, kw, started, t0, emb)
    scans = {"store": tp.scan_table_log(store_log, offset, statements),
             **{f"reference/{k}": v for k, v in refs.log_scans(statements).items()},
             **extra_logs}
    logs = {"total": tp.total_table_scan(scans), "by_store": scans,
            "statements_checked": len({x for x in statements
                                       if len(x) >= tp.MIN_STATEMENT})}
    ok = ok and logs["total"]["complete"]
    if a.kind in ("tables-leak", "tables-equivalence"):   # the kinds that use them
        cfg["views"] = refs.info
        cfg["views_removed"] = [] if a.keep_views else [
            runner._display_path(Path(p)) for p in refs.remove()]
    lt = logs["total"]
    md = (f"# Table probes: {a.kind[len('tables-'):]} ({a.corpus})\n\nStore `{cfg['store']}` "
          f"(snapshot `{cfg['snapshot'][:12]}`, tables "
          f"`{(cfg['tables'] or 'none')[:12]}`, ACL snapshot `{cfg['acl_snapshot'][:12]}` "
          f"sequence {cfg['acl_sequence']}). Seed {tp.SEED3}. No model calls.\n\n{head}.\n\n"
          + table + f"\n## Log fields\n\n{lt['lines']} log lines ({lt['table_lines']} of the "
          f"table tools), {lt['complete_lines']} with caller, principals, acl_snapshot and "
          f"acl_decision; {lt['tables_missing']} without `tables`; {lt['allowed']} allowed, "
          f"{lt['allowed_unresolved']} of them with a null resolved field or tables id; "
          f"{lt['sql_text_lines']} with statement text. Complete: {lt['complete']}.\n")
    d = _write_probe_run(a, a.kind, started,
                         {"probes.json": probe_set, "results.json": {"results": rows},
                          "summary.json": {"config": cfg, "summary": summary, "logs": logs}},
                         md)
    print(md)
    print(f"{d}: {a.kind}; wall-clock {time.perf_counter() - t0:.1f} s")
    return 0 if ok else 1


def _probes_tables_mcp(a, tp, ctx, refs, root, kw, started, t0, emb) -> int:
    """`adr-eval probes tables-mcp <corpus> --store S [--also LABEL=PATH]`: the seeded --n (60)
    of the leak probes of the stores, each through an `adr mcp` server of its caller, judged
    against the Python API's reference stores, every result replayed with its handle."""
    from adr_store import tools as store_tools
    from adr_store.mcp_client import McpTools

    stores = {a.corpus: Path(a.store)}
    for spec in a.also or []:
        label, sep, path = spec.partition("=")
        if not sep or label not in tp.TABLE_CORPORA or label in stores:
            raise runner.RunError(f"--also takes CORPUS=PATH with another corpus of "
                                  f"{', '.join(tp.TABLE_CORPORA)}, got {spec!r}")
        _tables_fresh(Path(path))
        stores[label] = Path(path)
    contexts = {a.corpus: ctx}
    references = {a.corpus: refs}
    universe = []
    cfg_stores = {}
    for label, path in stores.items():
        if label not in contexts:
            contexts[label] = tp.table_context(path)
            references[label] = tp.References(contexts[label], root.parent / label, **kw)
        cfg_stores[label] = _tables_config(a, path, label)
        universe += [(label, p) for p in tp.leak_probes(path, label)]
    selected = tp.select_mcp(universe, a.n or tp.MCP_SUBSET)
    logs_of = {label: tp.log_path(path) for label, path in stores.items()}
    offsets = {label: tp.log_size(log) for label, log in logs_of.items()}
    made: dict = {}

    def reference_for(label, caller):
        path = references[label].path_for(caller)
        if path is None:
            return None
        if (label, caller) not in made:
            made[(label, caller)] = store_tools.Tools(path, emb_cache=emb, acl=True,
                                                      caller=caller)
        return made[(label, caller)]

    def make_server(label, caller):
        tp.keep_fresh(stores[label], a.directory, a.policy, tp.acl.utc_now)
        return McpTools(stores[label], caller, emb_cache=emb, env={"HF_HUB_OFFLINE": "1"},
                        cwd=runner.REPO_ROOT, timeout=a.timeout)

    results, replays, calls = tp.run_mcp(selected, contexts=contexts,
                                         reference_for=reference_for, make_server=make_server)
    statements = [c["args"]["statement"] for _, p in selected for c in p.call["calls"]
                  if c["tool"] == "sql"]
    mcp_scans = {label: tp.scan_table_log(log, offsets[label], statements)
                 for label, log in logs_of.items()}
    ref_scans = {f"{label}/{k}": v for label, r in references.items()
                 for k, v in r.log_scans(statements).items()}
    n_calls = {label: sum(c.values()) for label, c in calls.items()}
    logs = {"mcp": {"total": tp.total_table_scan(mcp_scans), "by_store": mcp_scans,
                    "calls": calls},
            "reference": {"total": tp.total_table_scan(ref_scans), "by_store": ref_scans},
            "total": tp.total_table_scan({**mcp_scans, **ref_scans})}
    summary = tp.summarize_mcp(results, replays)
    removed = [] if a.keep_views else [runner._display_path(Path(p))
                                       for r in references.values() for p in r.remove()]
    cfg = {"kind": a.kind, "seed": tp.SEED3, "n": a.n or tp.MCP_SUBSET,
           "universe": len(universe), "stores": cfg_stores,
           "selected": dict(sorted(Counter(f"{lb}/{p.family}" for lb, p in selected).items())),
           "server_env": {"HF_HUB_OFFLINE": "1"},
           "views": {label: r.info for label, r in references.items()},
           "views_removed": removed}
    calls_match = all(mcp_scans[label]["lines"] == n_calls.get(label, 0) for label in stores)
    t = summary["total"]
    rp = summary["replays"]
    ok = (t["leaks"] == 0 and t["invalid"] == 0 and rp["identical"] == rp["n"]
          and rp["handle_tables"] == rp["n"] and logs["total"]["complete"] and calls_match)
    md = (f"# Table probes through MCP (D1)\n\nThe {cfg['n']} of {len(universe)} table leak "
          f"probes with the lowest SHA-256 of `<seed>:<store>/<probe id>` (seed {tp.SEED3}), "
          f"each through an `adr mcp` server of its caller. No model calls.\n\n"
          f"{t['n']} probes, {t['leaks']} leaks, {t['invalid']} invalid ({t['ghost']} as "
          f"user:ghost, denied F4). Handle replays: {rp['identical']} of {rp['n']} identical, "
          f"{rp['handle_tables']} handles naming the tables.\n\n| store | probes | leaks | "
          f"invalid |\n|---|---|---|---|\n" + "".join(
              f"| {lb} | {b['n']} | {b['leaks']} | {b['invalid']} |\n"
              for lb, b in summary["stores"].items())
          + f"\n## Log fields\n\n{sum(n_calls.values())} calls through MCP; "
            f"{logs['mcp']['total']['lines']} log lines in the probed stores (equal per store: "
            f"{calls_match}). Complete (MCP and reference logs): {logs['total']['complete']}.\n")
    d = _write_probe_run(a, a.kind, started, {
        "probes.json": {"seed": tp.SEED3, "selected": [
            {"store": lb, **p.to_dict()} for lb, p in selected]},
        "results.json": {"results": [{"store": lb, **r.to_dict()} for lb, r in results],
                         "replays": replays},
        "summary.json": {"config": cfg, "summary": summary, "logs": logs}}, md)
    print(md)
    print(f"{d}: {len(selected)} probes through MCP; wall-clock "
          f"{time.perf_counter() - t0:.1f} s")
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

    p = sub.add_parser("golden", help="generate or verify the golden set; `golden tables --gen` "
                                      "generates gov-tables v0.1 (3B drawbridge questions)")
    p.add_argument("corpus", choices=(*NAMES, TABLES_GOLDEN),
                   help=f"a corpus, or {TABLES_GOLDEN!r} for gov-tables v0.1 (--gen only, with "
                        f"--store, --facts, --generator and --max-calls)")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--gen", action="store_const", const=_golden_gen, dest="fn")
    mode.add_argument("--verify", action="store_const", const=_golden_verify, dest="fn")
    p.add_argument("--overwrite", action="store_true",
                   help="with --gen: replace an existing (frozen) items.jsonl")
    p.add_argument("--store", type=Path, default=None,
                   help="golden tables: the store holding the second-pass facts")
    p.add_argument("--facts", default=None, metavar="ID",
                   help="golden tables: the second-pass facts id (`adr tables extract "
                        "--second-pass` prints it)")
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
    p.add_argument("--qtype", action="append", default=None, choices=get_args(QType),
                   help="run only the items of this question type (repeatable); p3-typed "
                        "needs --qtype count_filter")
    p.add_argument("--golden", choices=runner.GOLDEN_SETS, default="v0.1",
                   help="golden set: the corpus's v0.1 set, or gov-tables (corpus gov; no "
                        "judge; default one repeat; every transport attempt counts against "
                        "--max-calls; a stop writes nothing)")
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

    p = sub.add_parser("p3-q2",
                       help="Phase 3 Q2: a p3-typed gov-tables test run against a "
                            "baseline-linear one (accuracies, paired bootstrap interval, pass "
                            "flags, McNemar, misses); writes <typed run>/q2-<baseline run>.json")
    p.add_argument("typed_run", help="the p3-typed gov-tables run directory")
    p.add_argument("baseline_run", help="the baseline-linear gov-tables run directory")
    p.add_argument("--summary", type=Path, default=None, metavar="OUT",
                   help="also write the committed form (no item id, filter value or answer) "
                        "to OUT")
    p.set_defaults(fn=_p3_q2)

    p = sub.add_parser("p3-q1",
                       help="Phase 3 Q1: a p3-typed run against a baseline run on their "
                            "common count_filter items (accuracy, McNemar, misses, also_in "
                            "readings); writes <typed run>/q1-<baseline run>.json")
    p.add_argument("typed_run", help="the p3-typed run directory")
    p.add_argument("baseline_run", help="the baseline run directory")
    p.add_argument("--summary", type=Path, default=None, metavar="OUT",
                   help="also write the committed form (no item id or filter value) to OUT")
    p.set_defaults(fn=_p3_q1)

    p = sub.add_parser("probes", help="probe sets (no model calls): Phase 2 temporal (gov), "
                                      "acl (leak and fail-closed), equivalence (B2); Phase 3 "
                                      "tables-leak, tables-sql, tables-equivalence, "
                                      "tables-failclosed, tables-applicability, tables-mcp")
    p.add_argument("kind", choices=("temporal", "acl", "equivalence", *TABLE_KINDS))
    p.add_argument("corpus", choices=(*NAMES, "tools"),
                   help="the store's corpus (tools: the tool store, tables-equivalence only)")
    p.add_argument("--store", type=Path, required=True,
                   help="the store to probe (its active index and overlays)")
    p.add_argument("--views", type=Path, default=None, metavar="DIR",
                   help="acl, equivalence, tables-leak, tables-equivalence, tables-mcp: where "
                        "the reference stores are built or reused (default "
                        "<p2_store_dir>/views/<corpus>; tables-*: views-tables/<corpus>)")
    p.add_argument("--keep-views", action="store_true",
                   help="acl, equivalence, tables-leak, tables-equivalence, tables-mcp: keep "
                        "the reference stores (default: removed)")
    p.add_argument("--clones", type=Path, default=None, metavar="DIR",
                   help="acl, tables-failclosed: where the fail-closed clones go (default "
                        "<p2_store_dir>/clones/<corpus>; removed)")
    acl_config = runner.REPO_ROOT / "config" / "acl"
    p.add_argument("--directory", type=Path, default=acl_config / "directory.json",
                   help="acl, equivalence and the tables-* kinds: the directory the reference "
                        "stores and clones sync from (default config/acl/directory.json)")
    p.add_argument("--policy", type=Path, default=acl_config / "policy.json",
                   help="acl, equivalence and the tables-* kinds: the policy (default "
                        "config/acl/policy.json)")
    p.add_argument("--questions", type=int, default=50, metavar="N",
                   help="equivalence: golden questions per view (default 50)")
    p.add_argument("--per-family", type=int, default=None, metavar="N",
                   help="acl, tables-leak: N leak probes per family instead of the spec's "
                        "counts (a quick check; recorded in the output)")
    p.add_argument("--as", dest="as_user", default=None, metavar="USER",
                   help="search as this caller (needs the ACL layer of Phase 2B)")
    p.add_argument("--dedup", action=argparse.BooleanOptionalAction, default=True,
                   help="collapse copies in search (default on)")
    p.add_argument("--allow-other-index", action="store_true",
                   help="probe an active index that is not p1-struct-bc with a recorded "
                        "Phase 1 fingerprint (recorded in the output)")
    p.add_argument("--queries", type=int, default=25, metavar="N",
                   help="tables-equivalence: calls per view (default 25: 15 query_table, "
                        "10 sql)")
    p.add_argument("--gold", type=Path, default=None, metavar="PATH",
                   help="tables-equivalence: the golden set whose count_filter gold queries "
                        "are drawn (default golden/<corpus>/v0.1)")
    p.add_argument("--n", type=int, default=None, metavar="N",
                   help="tables-applicability: as_of dates (default 50); tables-mcp: probes "
                        "through MCP (default 60)")
    p.add_argument("--also", action="append", default=None, metavar="CORPUS=PATH",
                   help="tables-mcp: another store whose leak probes join the universe")
    p.add_argument("--timeout", type=float, default=300.0,
                   help="tables-mcp: seconds to wait for a server's reply")
    p.add_argument("--out", type=Path, default=None,
                   help="output root (default runs); writes probes-<kind>-<corpus>-<ts>/")
    p.set_defaults(fn=_probes)

    p = sub.add_parser("tools-retrieval",
                       help="tool retrieval on ToolRet (no model calls): tools.json/tools.md for "
                            "a tool system (Phase 2)")
    p.add_argument("--system", required=True,
                   choices=("tools-bm25-raw", "tools-bm25f", "tools-hybrid"))
    p.add_argument("--split", choices=("dev", "test"), required=True)
    p.add_argument("--store", type=Path, default=None,
                   help="the tools-only store (tools-bm25f, tools-hybrid; e.g. "
                        ".cache/store-p2/toolret); its active tool index is replaced by the "
                        "tuned one")
    p.add_argument("--root", type=Path, default=None,
                   help="the ToolRet data directory (default data/tools)")
    p.add_argument("--lexical-only", action="store_true",
                   help="tools-hybrid: the BM25 channel alone (no embedding)")
    p.add_argument("--emb-cache", type=Path, default=None,
                   help="embedding cache directory (dense index only)")
    p.add_argument("--threads", type=int, default=1,
                   help="threads of the embedding model while building (vectors unchanged)")
    p.add_argument("--sync", action="store_true",
                   help="run one ACL sync cycle (committed directory and policy) first")
    p.add_argument("--out", type=Path, default=None,
                   help="output root (default runs); writes tools-<system>-<split>-<time>/")
    p.set_defaults(fn=_tools_retrieval)

    p = sub.add_parser("tools-probes",
                       help="ACL probes of search_tools and load_tool (no model calls): 200 "
                            "leak and 80 fail-closed probes (Phase 2)")
    p.add_argument("--store", type=Path, required=True,
                   help="the store to probe (its tool catalog, active tool index and ACL)")
    p.add_argument("--clones", type=Path, default=None, metavar="DIR",
                   help="where the fail-closed clones go (default <p2_store_dir>/clones/tools; "
                        "removed)")
    tools_acl = runner.REPO_ROOT / "config" / "acl"
    p.add_argument("--directory", type=Path, default=tools_acl / "directory.json",
                   help="the directory the clones sync from (default config/acl/directory.json)")
    p.add_argument("--policy", type=Path, default=tools_acl / "policy.json",
                   help="the policy (default config/acl/policy.json)")
    p.add_argument("--index", required=True, metavar="FP",
                   help="the fingerprint (or a prefix of 8+ characters) of the tool index to "
                        "probe; refused unless it is the store's active tool index")
    p.add_argument("--per-family", type=int, default=None, metavar="N",
                   help="N leak probes per family instead of 100 (a quick check; recorded)")
    p.add_argument("--emb-cache", type=Path, default=None,
                   help="embedding cache directory (a dense tool index)")
    p.add_argument("--out", type=Path, default=None,
                   help="output root (default runs); writes probes-tools-<time>/")
    p.set_defaults(fn=_tools_probes)

    p = sub.add_parser("mcp-probes",
                       help="B1 through MCP (no model calls): the seeded 300 of the leak probes "
                            "of every store, each through an `adr mcp` server of its caller "
                            "(Phase 2)")
    p.add_argument("--store", action="append", default=None, metavar="LABEL=PATH",
                   help="a store to sample from (labels: the corpora and tools; default the "
                        "p2 copies of gov, research and bench and the ToolRet store)")
    p.add_argument("--tool-index", default=None, metavar="FP",
                   help="the fingerprint (or a prefix of 8+ characters) of the tools store's "
                        "active tool index; refused unless it is that")
    p.add_argument("--n", type=int, default=300, help="probes to select (default 300)")
    p.add_argument("--per-family", type=int, default=None, metavar="N",
                   help="N leak probes per family in the universe instead of the spec's (a "
                        "quick check; recorded)")
    p.add_argument("--views", type=Path, default=None, metavar="DIR",
                   help="root of the reference stores, one folder per corpus (default "
                        "<p2_store_dir>/views; built or reused, removed unless --keep-views)")
    p.add_argument("--keep-views", action="store_true", help="keep the reference stores")
    p.add_argument("--directory", type=Path, default=acl_config / "directory.json",
                   help="the directory reference stores sync from")
    p.add_argument("--policy", type=Path, default=acl_config / "policy.json",
                   help="the policy reference stores sync from")
    p.add_argument("--allow-other-index", action="store_true",
                   help="probe a content store whose active index is not the Phase 1 one")
    p.add_argument("--timeout", type=float, default=300.0,
                   help="seconds an MCP call may take (the first call loads the index)")
    p.add_argument("--emb-cache", type=Path, default=None, help="embedding cache directory")
    p.add_argument("--out", type=Path, default=None,
                   help="output root (default runs); writes probes-mcp-<time>/")
    p.set_defaults(fn=_mcp_probes)

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
    if a.command == "golden" and a.corpus == TABLES_GOLDEN:
        if a.fn is not _golden_gen:
            ap.error("golden tables takes --gen only")
        missing = [f for f, v in (("--store", a.store), ("--facts", a.facts),
                                  ("--generator", a.generator), ("--max-calls", a.max_calls))
                   if v is None]
        if missing:
            ap.error(f"golden tables --gen needs {', '.join(missing)}")
        if a.judge is not None:
            ap.error("golden tables makes no judge call; remove --judge")
        if a.max_calls < 0:
            ap.error("--max-calls must not be negative")
    elif a.command == "golden" and (a.store is not None or a.facts is not None):
        ap.error("--store and --facts are options of `golden tables` only")
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
