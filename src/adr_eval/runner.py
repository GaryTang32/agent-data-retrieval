"""Run a baseline system over a golden split: setup, index, clients, budget and output files."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from adr_eval.answer._prompts import load_prompt
from adr_eval.answer.answerer import answer_question
from adr_eval.answer.answerer import prompt_hash as answer_prompt_hash
from adr_eval.answer.query_gen import generate_query
from adr_eval.cache import Cache
from adr_eval.corpora import REPO_ROOT
from adr_eval.corpora.base import LoadedCorpus, load_corpus
from adr_eval.corpora.registry import MINI_ROOT, corpus_root, get_adapter, manifest_path
from adr_eval.llm import (
    AnthropicClient,
    ClaudeCodeClient,
    Completion,
    ModelClient,
    OpenAICompatibleClient,
    StubClient,
    is_subscription,
    load_prices,
    price_entry,
)
from adr_eval.models import GoldenItem, load_items
from adr_eval.pipeline import (
    Budget,
    Context,
    MeteredClient,
    estimate_tokens,
    model_id,
    price_usd,
    process_item,
)
from adr_eval.retrieval.chunker import Chunk, chunk_document
from adr_eval.retrieval.dense import DenseIndex
from adr_eval.retrieval.fusion import tune_linear_weight
from adr_eval.retrieval.index import _CHANNEL_K, RRF_K, TOP_N, HybridIndex
from adr_eval.retrieval.lexical import BM25Index
from adr_eval.scoring import compile_metrics
from adr_eval.scoring.exact import normalize_value
from adr_eval.scoring.judge import Judge
from adr_eval.scoring.judge import prompt_hash as judge_prompt_hash
from adr_eval.scoring.retrieval_metrics import ndcg_at_k, overlap

System = Literal["baseline-rrf", "baseline-linear"]
SYSTEMS = ("baseline-rrf", "baseline-linear")
CONFIG_PATH = REPO_ROOT / "config" / "eval.json"
MODELS_PATH = REPO_ROOT / "config" / "models.json"


class RunError(Exception):
    """A refusal with a message naming the file and the fix."""


class ProfileError(RunError, ValueError):
    """A model profile that is unknown or cannot be used yet."""


# -- paths and config -------------------------------------------------------------------


def load_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _repo_path(p: str | Path) -> Path:
    return REPO_ROOT / p  # an absolute `p` stays as is


def golden_dir(corpus: str) -> Path:
    """Where `golden --gen` writes items.jsonl and rejected.jsonl (for every corpus)."""
    return REPO_ROOT / "golden" / corpus / "v0.1"


def golden_items_path(corpus: str) -> Path:
    """The mini corpus uses its hand-checked fixture set; others the committed v0.1 set."""
    return MINI_ROOT / "golden.jsonl" if corpus == "mini" else golden_dir(corpus) / "items.jsonl"


def index_dir(config: dict, corpus: str) -> Path:
    return _repo_path(config.get("index_dir", ".cache/index")) / corpus


def llm_cache(config: dict) -> Cache:
    return Cache(_repo_path(config.get("cache_dir", ".cache/llm")))


# -- corpus, golden set, index ----------------------------------------------------------


def load_checked_corpus(corpus: str) -> LoadedCorpus:
    try:
        return load_corpus(manifest_path(corpus), corpus_root(corpus))
    except FileNotFoundError as e:
        raise RunError(f"{e.filename}: not found; run `adr-eval fetch {corpus}`") from e
    except ValueError as e:
        fix = ("the research corpus needs the local PDF library: see "
               "`adr-eval fetch research` for how to provide it" if corpus == "research"
               else f"run `adr-eval fetch {corpus}` to restore the files")
        raise RunError(f"{e}\nfix: {fix}") from e


def load_golden(corpus: str, loaded: LoadedCorpus) -> list[GoldenItem]:
    path = golden_items_path(corpus)
    if not path.is_file():
        raise RunError(f"{path}: golden set not found; run `adr-eval golden {corpus} --gen`")
    items = [i for i in load_items(path) if i.status != "rejected"]
    snapshot = loaded.manifest.snapshot()
    stale = sorted(i.id for i in items if i.snapshot != snapshot)
    if stale:
        raise RunError(
            f"{path}: {len(stale)} item(s) have a snapshot that differs from "
            f"{manifest_path(corpus)} (snapshot {snapshot[:12]}): {', '.join(stale[:5])}\n"
            f"fix: regenerate with `adr-eval golden {corpus} --gen`, or restore the manifest "
            f"the golden set was built from")
    return items


def _all_chunks(corpus: LoadedCorpus) -> list[Chunk]:
    return [c for doc_id in sorted(corpus.docs) for c in chunk_document(corpus.docs[doc_id])]


def expected_fingerprint(corpus: LoadedCorpus) -> str:
    """Fingerprint the index for `corpus` would have, without embedding anything."""
    chunks = {c.chunk_id: c for c in _all_chunks(corpus)}
    return HybridIndex(corpus.manifest.snapshot(), chunks, BM25Index(), DenseIndex()).fingerprint


def ensure_index(corpus: str, loaded: LoadedCorpus, config: dict,
                 rebuild: bool = False) -> tuple[HybridIndex, str]:
    """Load the saved index, or build and save one; returns (index, "loaded" | "built")."""
    d = index_dir(config, corpus)
    meta = d / "meta.json"
    if meta.is_file() and not rebuild:
        saved = json.loads(meta.read_text(encoding="utf-8"))["fingerprint"]
        expected = expected_fingerprint(loaded)
        if saved != expected:
            raise RunError(
                f"{d}: saved index fingerprint {saved[:12]} differs from the current corpus "
                f"and configuration ({expected[:12]})\nfix: rerun with --rebuild")
        return HybridIndex.load(d), "loaded"
    idx = HybridIndex.build(loaded)
    idx.save(d)
    return idx, "built"


def compile_report(items: list[GoldenItem], loaded: LoadedCorpus, index: HybridIndex,
                   source: str) -> dict:
    """G1: span containment, extracted-text fidelity, empty documents, fingerprint."""
    by_doc: dict[str, list[Chunk]] = {}
    for c in index.chunks.values():
        by_doc.setdefault(c.doc_id, []).append(c)
    return {
        "span_containment": compile_metrics.span_containment(items, by_doc),
        "text_fidelity": compile_metrics.text_fidelity(loaded),
        "empty_docs": sorted(loaded.empty_docs),
        "n_docs": len(loaded.docs), "n_chunks": len(index.chunks),
        "fingerprint": index.fingerprint, "index_source": source,
    }


def tune_w(index: HybridIndex, items: list[GoldenItem]) -> float:
    dev = [i for i in items if i.split == "dev" and i.evidence and i.qtype != "insufficient"]
    if not dev:
        raise RunError("baseline-linear needs dev-split items with evidence to tune w")

    def ndcg(item: GoldenItem):
        return lambda ids: ndcg_at_k([index.chunks[c] for c in ids], item.evidence, 10)

    return tune_linear_weight([
        (index.bm25.search(i.question, k=_CHANNEL_K), index.dense.search(i.question, k=_CHANNEL_K),
         ndcg(i))
        for i in sorted(dev, key=lambda i: i.id)
    ])


# -- clients ----------------------------------------------------------------------------


def load_profiles(path: Path = MODELS_PATH) -> dict[str, dict]:
    """The named model profiles in config/models.json (the "stub" entry is not one)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))["profiles"]


def _placeholder(value: object) -> bool:
    return isinstance(value, str) and value.startswith("<set")


def profile_status(profile: dict) -> str | None:
    """Why `profile` cannot be used now, or None when it is configured."""
    if _placeholder(profile.get("model")):
        return "placeholder model"
    if _placeholder(profile.get("family")):
        return "placeholder family"
    env = profile.get("api_key_env")
    if env and not os.environ.get(env):
        return f"missing key {env}"
    if profile.get("adapter") == "claude_code":
        binary = profile.get("binary", "claude")
        if shutil.which(binary) is None:
            return f"missing binary {binary}"
    return None


def get_profile(name: str, profiles: dict) -> dict:
    if name not in profiles:
        raise ProfileError(f"{MODELS_PATH}: unknown model profile {name!r}; known: "
                           f"{', '.join(sorted(profiles))}")
    return profiles[name]


def make_client(profile_name: str, profiles: dict, cache: Cache,
                max_retries: int = 5) -> ModelClient:
    """Build the client for a profile; ProfileError (a ValueError) names what is missing."""
    p = get_profile(profile_name, profiles)
    problem = profile_status(p)
    if problem:
        raise ProfileError(f"model profile {profile_name!r}: {problem} (in {MODELS_PATH}); "
                           f"see docs/eval/providers.md, or use --stub or --dry-run")
    adapter = p.get("adapter")
    if adapter == "claude_code":
        return ClaudeCodeClient(p["model"], cache, max_retries, binary=p.get("binary", "claude"))
    if adapter == "anthropic":
        return AnthropicClient(p["model"], cache, max_retries)
    if adapter == "openai_compatible":
        return OpenAICompatibleClient(p["base_url"], p["model"], p["api_key_env"], p["family"],
                                      cache, max_retries)
    raise ProfileError(f"model profile {profile_name!r}: unknown adapter {adapter!r}")


_PASSAGE_ID = re.compile(r"^\[([0-9a-f]{64})\]$", re.MULTILINE)
_JUDGE_MSG = re.compile(
    r"Gold answer: (.*?)\n\nAccepted variants: (.*?)\n\nCandidate answer: (.*)\Z", re.DOTALL)
_ABSTAIN = {"answer": None, "kind": "abstain", "citations": [], "abstain": True,
            "confidence": 0.0}


def _question_key(user: str) -> tuple[str | None, str | None]:
    """(question, as_of) from the last such lines of a generator user message."""
    q = re.findall(r"^Question: (.*)$", user, re.MULTILINE)
    a = re.findall(r"^Answer as of: (.*)$", user, re.MULTILINE)
    return (q[-1] if q else None), (a[-1] if a else None)


def stub_clients(
    items: list[GoldenItem], chunks: dict[str, Chunk]
) -> tuple[StubClient, StubClient]:
    """Deterministic generator and judge for tests and demos (family "stub").

    The generator looks the item up by question text (and as-of date): it returns the
    gold query, and answers with the gold value citing the passages that overlap gold
    evidence. The judge says "correct" iff the candidate equals the gold value or a variant
    after normalization.
    """
    by_q = {(i.question, i.as_of.isoformat() if i.as_of else None): i for i in items}
    query_prompt = load_prompt("query_gen")

    def generate(system: str, user: str, repeat: int) -> str:
        item = by_q.get(_question_key(user))
        if system == query_prompt:
            return json.dumps(item.gold_query.model_dump(mode="json") if item else {})
        if item is None or item.answer.kind == "abstain":
            return json.dumps(_ABSTAIN)
        cited = [cid for cid in _PASSAGE_ID.findall(user)
                 if cid in chunks and any(overlap(chunks[cid], e) > 0 for e in item.evidence)]
        return json.dumps({"answer": item.answer.value, "kind": item.answer.kind,
                           "citations": cited, "abstain": False, "confidence": 1.0})

    def judge(system: str, user: str, repeat: int) -> str:
        m = _JUDGE_MSG.search(user)
        if m is None:
            return "not a judge message"
        gold, variants, candidate = m.group(1), json.loads(m.group(2)), m.group(3)
        ok = normalize_value(candidate) in {normalize_value(g) for g in [gold, *variants]}
        return json.dumps({"label": "correct" if ok else "incorrect", "reason": "stub match"})

    return StubClient(generate), StubClient(judge)


def _client_info(client: ModelClient, prices: dict, profile_name: str | None,
                 profile: dict | None) -> dict:
    entry = price_entry(model_id(client), prices, client.name)
    return {"profile": profile_name, "adapter": profile["adapter"] if profile else client.name,
            "name": client.name, "model": model_id(client), "family": client.family,
            "billing": "subscription" if is_subscription(entry) else "api",
            "sampling": getattr(client, "sampling", None)}


def _served_mismatch(info: dict) -> bool:
    """Whether a provider reported a model other than the client's model ID."""
    return any(m != info["model"] for m in info["served_models"])


# -- dry run ----------------------------------------------------------------------------


class _Recorder:
    """Records prompts instead of calling a model; replies with a fixed text."""

    def __init__(self, reply: str, model: str, family: str = "dry-run"):
        self.reply, self.model, self.name, self.family = reply, model, "dry-run", family
        self.calls, self.tokens_in, self.tokens_out = 0, 0, 0

    def complete(self, system: str, user: str, *, max_tokens: int, repeat: int = 0) -> Completion:
        tin, tout = estimate_tokens(system, user, max_tokens)
        self.calls, self.tokens_in, self.tokens_out = (
            self.calls + 1, self.tokens_in + tin, self.tokens_out + tout)
        return Completion(self.reply, tin, tout, self.model, 0.0, False)


def _dry_run(run_id: str, items: list[GoldenItem], retrieved: dict, index: HybridIndex,
             schema: dict, gen_model: tuple[str, str], judge_model: tuple[str, str],
             prices: dict) -> None:
    """`gen_model` / `judge_model` are (model, provider) pairs for the price lookup."""
    gen = _Recorder(json.dumps(_ABSTAIN), gen_model[0])
    jrec = _Recorder('{"label": "correct", "reason": ""}', judge_model[0])
    providers = {"generator": gen_model[1], "judge": judge_model[1]}
    judge = Judge(jrec)
    for item in items:
        for repeat, hits in enumerate(retrieved[item.id]):
            generate_query(item.question, item.as_of, schema, gen, repeat)
            answer_question(item.question, item.as_of, [index.chunks[c] for c, _ in hits],
                            gen, repeat)
            judged = item.answer.kind == "text" or (
                repeat == 0 and item.answer.kind in ("number", "set", "id"))
            if judged:
                judge.judge(item.question, item.answer, item.answer.value)
            if repeat == 0 and item.answer.kind == "text":
                judge.judge(item.question, item.answer, item.answer.value, repeat=1)
    total = 0.0
    print(f"dry run {run_id}: {len(items)} items x {len(next(iter(retrieved.values())))} "
          f"repeats (estimates: prompt chars/4 tokens in, max_tokens out)")
    for role, rec in (("generator", gen), ("judge", jrec)):
        usd = price_usd(rec.model, rec.tokens_in, rec.tokens_out, prices, providers[role])
        total += usd
        billed = " (subscription)" if is_subscription(
            price_entry(rec.model, prices, providers[role])) else ""
        print(f"  {role} {rec.model}: {rec.calls} calls, ~{rec.tokens_in} tokens in, "
              f"<= {rec.tokens_out} tokens out, ~${usd:.4f}{billed}")
    print(f"  total: ~${total:.4f} (calls are an upper bound, since abstentions skip judge "
          f"calls; token counts and cost are estimates)")


# -- the run ----------------------------------------------------------------------------


def _new_run_dir(out_root: Path, run_id: str) -> Path:
    out_root.mkdir(parents=True, exist_ok=True)
    for n in range(1, 1000):
        d = out_root / (run_id if n == 1 else f"{run_id}-{n}")
        try:
            d.mkdir()
            return d
        except FileExistsError:
            continue
    raise RunError(f"{out_root}: too many runs named {run_id}")


def _display_path(p: Path) -> str:
    """`p` relative to the repo root when inside it (portable across checkouts)."""
    try:
        return Path(p).resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(p)


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _role_clients(config: dict, given: dict[str, ModelClient | None], stub: bool,
                  dry_run: bool) -> tuple[dict, dict, dict]:
    """Per role: (client, profile name, profile). A given client is kept (profile None);
    with `stub` a missing one is named "stub" and built later from the golden set; else the
    profile named in `config` is looked up and, unless `dry_run`, built now, so a missing
    key or placeholder model fails before any work."""
    profiles = load_profiles(_repo_path(config.get("models", "config/models.json")))
    clients, names, specs = dict(given), {}, {}
    for role, client in given.items():
        names[role], specs[role] = ("stub" if stub and client is None else None), None
        if client is None and not stub:
            names[role], specs[role] = config[role], get_profile(config[role], profiles)
            if not dry_run:
                clients[role] = make_client(config[role], profiles, llm_cache(config))
    return clients, names, specs


def run(
    corpus: str,
    system: System,
    split: Literal["dev", "test"],
    repeats: int,
    config: dict,
    out_root: Path = Path("runs"),
    max_dollars: float | None = None,
    dry_run: bool = False,
    *,
    rebuild: bool = False,
    generator: ModelClient | None = None,
    judge: ModelClient | None = None,
    max_calls: int | None = None,
) -> str:
    """Run `system` over the `split` items; returns the run id (the run directory's name).

    `config["generator"]` / `config["judge"]` name profiles in config/models.json;
    `generator` / `judge` override the clients built from them (tests).
    """
    if system not in SYSTEMS:
        raise RunError(f"unknown system {system!r}; expected one of {', '.join(SYSTEMS)}")
    stub = bool(config.get("stub"))
    clients, names, specs = _role_clients(config, {"generator": generator, "judge": judge},
                                          stub, dry_run)
    generator, judge = clients["generator"], clients["judge"]
    loaded = load_checked_corpus(corpus)
    all_items = load_golden(corpus, loaded)
    items = sorted((i for i in all_items if i.split == split), key=lambda i: i.id)
    if not items:
        raise RunError(f"{golden_items_path(corpus)}: no items in split {split!r}")
    index, source = ensure_index(corpus, loaded, config, rebuild)
    w = tune_w(index, all_items) if system == "baseline-linear" else None
    retrieved = {i.id: [index.retrieve(i.question, system, w=w) for _ in range(repeats)]
                 for i in items}
    prices = load_prices(_repo_path(config.get("prices", "config/prices.json")))
    if stub and (generator is None or judge is None):
        sg, sj = stub_clients(all_items, index.chunks)
        generator, judge = generator or sg, judge or sj
    pricing = {}  # role -> (model, provider) for profile-built clients
    for role, client in (("generator", generator), ("judge", judge)):
        spec = specs[role]
        if spec is not None:
            model, provider = pricing[role] = (
                (model_id(client), client.name) if client else (spec["model"], spec["adapter"]))
            if price_entry(model, prices, provider) is None:
                raise RunError(f"{config.get('prices', 'config/prices.json')}: no price for "
                               f"{role} model {model!r} (profile {names[role]!r}); "
                               f"add it before a real run")
    run_id = f"{corpus}-{system}-{split}-{datetime.now(UTC):%Y%m%dT%H%M%S}"
    adapter = get_adapter(corpus)
    schema = adapter.record_schema()
    if dry_run:
        _dry_run(run_id, items, retrieved, index, schema,
                 pricing.get("generator") or (model_id(generator), generator.name),
                 pricing.get("judge") or (model_id(judge), judge.name), prices)
        return run_id

    run_dir = _new_run_dir(Path(out_root), run_id)
    budget = Budget(max_dollars, max_calls)
    gen_meter, judge_meter = (MeteredClient(generator, budget, prices),
                              MeteredClient(judge, budget, prices))
    judge_ = Judge(judge_meter, recover=True)
    cfg = {
        "run_id": run_dir.name, "corpus": corpus, "system": system, "split": split,
        "repeats": repeats, "n_items": len(items), "stub": stub,
        "generator": _client_info(generator, prices, names["generator"], specs["generator"]),
        "judge": _client_info(judge, prices, names["judge"], specs["judge"]),
        "same_family_judge": Judge(judge).same_family_as(generator),
        "prompt_hashes": {"answer": answer_prompt_hash("answer"),
                          "query_gen": answer_prompt_hash("query_gen"),
                          "judge": judge_prompt_hash()},
        "snapshot": loaded.manifest.snapshot(), "fingerprint": index.fingerprint,
        "golden": _display_path(golden_items_path(corpus)),
        "golden_sha256": hashlib.sha256(golden_items_path(corpus).read_bytes()).hexdigest(),
        "retrieval": {"fusion": "rrf" if system == "baseline-rrf" else "linear",
                      "rrf_k": RRF_K if system == "baseline-rrf" else None,
                      "channel_k": _CHANNEL_K, "top_n": TOP_N, "linear_w": w},
        "seed": config.get("seed"),
        "price_table_as_of": {model_id(c): e.get("as_of") for c in (generator, judge)
                              if (e := price_entry(model_id(c), prices, c.name)) is not None},
        "w": w, "t_values": config.get("t_values", [0.5, 0.75, 0.9]),
        "concurrency": config.get("concurrency", 4), "max_dollars": max_dollars,
        "max_calls": max_calls,
        "status": "running", "started": datetime.now(UTC).isoformat(),
    }
    _write_json(run_dir / "config.json", cfg)
    _write_json(run_dir / "compile.json", compile_report(all_items, loaded, index, source))

    ctx = Context(index, adapter.records(loaded), schema,
                  gen_meter, judge_)
    results = run_dir / "results.jsonl"
    rows: list[dict] = []

    def write_sorted_rows() -> None:
        rows.sort(key=lambda r: (r["item_id"], r["repeat"]))
        results.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                                   for r in rows), encoding="utf-8")

    try:
        with results.open("w", encoding="utf-8") as f, \
                ThreadPoolExecutor(max_workers=cfg["concurrency"]) as pool:
            futures = [pool.submit(process_item, i, retrieved[i.id], ctx) for i in items]
            try:
                for fut in as_completed(futures):
                    for row in fut.result():  # written as they finish, so a crash keeps them
                        rows.append(row)
                        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                        f.flush()
            except BaseException:
                pool.shutdown(wait=True, cancel_futures=True)  # drop queued items
                raise
    except BaseException as e:  # budget stops are handled per item; anything else fails
        write_sorted_rows()
        cfg.update(status="failed", error=f"{type(e).__name__}: {e}",
                   finished=datetime.now(UTC).isoformat(), n_rows=len(rows),
                   spent_usd=budget.spent, calls=budget.calls)
        _write_json(run_dir / "config.json", cfg)
        raise
    write_sorted_rows()
    status = {"budget": "stopped_budget", "calls": "stopped_calls"}.get(
        budget.stop_reason, "complete")
    for role, meter in (("generator", gen_meter), ("judge", judge_meter)):
        cfg[role]["served_models"] = sorted(meter.served_models)
    cfg.update(status=status, finished=datetime.now(UTC).isoformat(), n_rows=len(rows),
               spent_usd=budget.spent, calls=budget.calls,
               served_model_mismatch=any(_served_mismatch(cfg[r]) for r in ("generator", "judge")))
    _write_json(run_dir / "config.json", cfg)
    return run_dir.name
