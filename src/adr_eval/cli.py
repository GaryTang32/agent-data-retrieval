"""`adr-eval` command line: fetch, golden, index, run, report, doctor."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from adr_eval import runner
from adr_eval.cache import Cache
from adr_eval.corpora.base import ExtractionError, HashMismatch
from adr_eval.corpora.registry import (
    NAMES,
    LocalFilesMissing,
    check_local_files,
    fetch_corpus,
    get_adapter,
)
from adr_eval.models import GoldenItem, jsonl_lines, write_items
from adr_eval.report import compare, render_compare_markdown, render_markdown, write_report


def _fetch(a: argparse.Namespace) -> int:
    fetch_corpus(a.corpus)
    print(f"{a.corpus}: all manifest files present and verified")
    return 0


LOCAL_ONLY_GOLDEN = ("bench", "research")  # item files hold verbatim source text; not in git


def _exclusions(corpus: str) -> dict[str, str]:
    from adr_eval.golden.verify import EXCLUSIONS_FILE, load_exclusions

    return load_exclusions(runner.golden_dir(corpus) / EXCLUSIONS_FILE)


def _golden_gen(a: argparse.Namespace) -> int:
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

    p = sub.add_parser("golden", help="generate or verify the golden set")
    p.add_argument("corpus", choices=NAMES)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--gen", action="store_const", const=_golden_gen, dest="fn")
    mode.add_argument("--verify", action="store_const", const=_golden_verify, dest="fn")
    _profile_args(p, judge=True)

    p = sub.add_parser("index", help="build (or check) the saved hybrid index")
    p.add_argument("corpus", choices=NAMES)
    p.add_argument("--rebuild", action="store_true", help="replace a saved index")
    p.set_defaults(fn=_index)

    p = sub.add_parser("run", help="run a baseline system over a split")
    p.add_argument("corpus", choices=NAMES)
    p.add_argument("--system", required=True, choices=runner.SYSTEMS)
    p.add_argument("--repeats", type=int, default=None, help="default: config repeats")
    p.add_argument("--split", choices=("dev", "test"), default="test")
    p.add_argument("--max-dollars", type=float, default=None)
    p.add_argument("--dry-run", action="store_true", help="estimate calls and cost only")
    p.add_argument("--rebuild", action="store_true", help="rebuild a stale saved index")
    p.add_argument("--out", type=Path, default=Path("runs"), help="run output root")
    p.add_argument("--stub", action="store_true",
                   help="deterministic stub generator and judge (tests and demos)")
    _profile_args(p, judge=True)
    p.set_defaults(fn=_run)

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
                                ("--max-calls", a.max_calls)) if v is not None]
        if given:
            ap.error(f"golden --verify makes no model calls; remove {', '.join(given)} "
                     f"(used only with --gen)")
    try:
        if getattr(a, "corpus", None):
            check_local_files(a.corpus)
        return a.fn(a)
    except (runner.RunError, HashMismatch, LocalFilesMissing, ExtractionError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
