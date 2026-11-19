"""Tool retrieval on ToolRet's `toolbench` subset (Phase 2 spec §8.3, §8.4, §10.1; plan Task 10).

Systems:

- `tools-bm25-raw`: the baseline. BM25 (the harness's `BM25Index`: tokenizer, bm25s, k1, b)
  over each tool's raw ToolRet documentation string, ranking ToolRet ids directly; no store.
- `tools-bm25f`: the store's `ToolIndex`, lexical only (`w_name` tuned).
- `tools-hybrid`: the store's `ToolIndex` with dense and linear fusion (`w_name` and `w` tuned;
  with `--lexical-only`, `w_name` alone, as `tools-bm25f`).

Tuning (planner's call 15): mean nDCG@10 over the dev queries, `w_name` in `W_NAMES` (0..3) and
`w` in `W_GRID` (0..1 step 0.05), ties (within 1e-12) to the smallest `w_name`, then the
smallest `w`. It ranks every tool with the index itself (the auditor's view is the whole
catalog under the committed policy; the dense channel by the row-exact kernel, as the ACL
layer scores it). The tuned index is then built (or loaded) and made the store's active tool
index (the run records and prints "active tool index: <old> → <new>", so the change is never
silent), and the Phase 2 systems are evaluated through `Tools.search_tools` with the ACL layer
as `CALLER` (`user:auditor`), each query's top 10 loaded with `load_tool`; a denied call (no
or stale ACL snapshot) stops the run with "run `adr acl sync`" (`--sync` runs one sync cycle
with the committed directory and policy first). Hits map back to ToolRet ids by the fragment
of their `source_uri` (`toolret:<repo>@<revision>/<config>#<toolret id>`).

Per query (gold = the query's ToolRet ids): `completeness@10` (1 when every gold tool is in the
top 10), `recall@10` (share of gold tools in the top 10) and `ndcg@10` (binary gain,
ideal = min(10, |gold|) gains). Tool context (§8.4), Phase 2 systems: `page` = tokens of the
canonical JSON of the `search_tools` result, `definitions` = tokens of the canonical JSON of
the `load_tool` definitions of its hits (at most 10), `loaded` = their sum, `catalog` = the
sum of every catalog record's `definition_tokens`, `reduction` = 1 - loaded / catalog,
`gold_share` = the loaded definition tokens of gold tools / loaded (page entries are not
counted as gold, even for gold hits), and the summary's gold share is the mean of that ratio
over queries; tokens as the harness counts them (`chunker._count`, stop words kept). The
baseline reports `top10_doc_tokens`, the raw documentation tokens of its top 10.

`run` writes `<out>/tools-<system>-<split>-<UTC time>/tools.json` (config, tuning table,
summary, one row per query: id, query, gold, ranked ToolRet ids, tool ids, scores, metrics,
context) and `tools.md`. Only the directory name and `config.started` hold the time; rows,
summary and tuning are a function of the store and the data. ToolRet text stays local
(`runs/`, Q2).

This module may import `adr_store` directly (plan, shared rules).
"""

from __future__ import annotations

import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path

from adr_eval import runner
from adr_eval.corpora import toolret
from adr_eval.retrieval.chunker import Chunk, _count
from adr_eval.retrieval.fusion import _GRID, linear
from adr_eval.retrieval.lexical import BM25Index
from adr_store import acl, tools
from adr_store.retrieval.tool_index import ToolIndex
from adr_store.tool_catalog import ToolCatalog
from adr_store.tool_records import canonical

SYSTEMS = ("tools-bm25-raw", "tools-bm25f", "tools-hybrid")
W_NAMES = (0, 1, 2, 3)
W_GRID = tuple(_GRID)
CALLER = "user:auditor"
TOP = 10
TIE = 1e-12
OUT_ROOT = Path("runs")  # where `adr-eval tools-retrieval` writes by default (tests redirect it)
KEYS = ("completeness@10", "recall@10", "ndcg@10")


class ToolEvalError(runner.RunError):
    """A tool-retrieval run that cannot go ahead (the message says what to fix; the command
    line prints it and exits 2, as any `RunError`)."""


# -- metrics --------------------------------------------------------------------------------------

def _gold(gold) -> list[str]:
    g = list(dict.fromkeys(gold))
    if not g:
        raise ValueError("a query without gold tools has no metric")
    return g


def completeness(ranked: list[str], gold, k: int = TOP) -> float:
    top = set(ranked[:k])
    return 1.0 if all(g in top for g in _gold(gold)) else 0.0


def recall(ranked: list[str], gold, k: int = TOP) -> float:
    g = _gold(gold)
    top = set(ranked[:k])
    return sum(x in top for x in g) / len(g)


def ndcg(ranked: list[str], gold, k: int = TOP) -> float:
    g = set(_gold(gold))
    seen: set[str] = set()
    dcg = 0.0
    for i, t in enumerate(ranked[:k], 1):
        if t in g and t not in seen:
            dcg += 1.0 / math.log2(i + 1)
        seen.add(t)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(k, len(g)) + 1))
    return dcg / ideal


def metrics(ranked: list[str], gold) -> dict:
    return {"completeness@10": completeness(ranked, gold), "recall@10": recall(ranked, gold),
            "ndcg@10": ndcg(ranked, gold)}


def best(table: list[dict]) -> dict:
    """The row of highest `ndcg@10`; ties (within `TIE`) to the smallest w_name, then w."""
    top = max(r["ndcg@10"] for r in table)
    tied = [r for r in table if r["ndcg@10"] >= top - TIE]
    return min(tied, key=lambda r: (r["w_name"], -1.0 if r.get("w") is None else r["w"]))


def toolret_id(source_uri: str) -> str:
    """The ToolRet id of a ToolRet record's `source_uri` (its fragment)."""
    if not source_uri.startswith("toolret:") or "#" not in source_uri:
        raise ValueError(f"{source_uri!r} is not a ToolRet source_uri")
    return source_uri.rpartition("#")[2]


# -- the baseline ---------------------------------------------------------------------------------

class RawBM25:
    """BM25 over the raw documentation strings of ToolRet rows (`toolret.tools`)."""

    def __init__(self, rows: list[dict]):
        self.docs = {r["id"]: r["documentation"] for r in rows}
        self.bm25 = BM25Index()
        self.bm25.build([Chunk(r["id"], r["id"], 0, 0, r["documentation"]) for r in rows])
        self.tokens = {i: _count(d) for i, d in self.docs.items()}
        self.catalog_tokens = sum(self.tokens.values())

    def search(self, query: str, k: int = TOP) -> list[tuple[str, float]]:
        return self.bm25.search(query, k=k)


# -- tool context ---------------------------------------------------------------------------------

def tool_context(res, loads, gold_tool_ids, catalog_tokens: int) -> dict:
    """The tool context of one query (module docstring): a `SearchToolsResult`, the
    `LoadToolResult`s of its hits, the gold tool ids and the catalog's definition tokens."""
    page = _count(canonical(res.to_dict()))
    defs = [_count(canonical(x.definition)) for x in loads]
    loaded = page + sum(defs)
    gold = [d for x, d in zip(loads, defs, strict=True) if x.tool_id in gold_tool_ids]
    return {"page": page, "definitions": sum(defs), "loaded": loaded,
            "catalog": catalog_tokens, "reduction": 1.0 - loaded / catalog_tokens,
            "gold_loaded": len(gold), "gold_tokens": sum(gold),
            "gold_share": sum(gold) / loaded}


# -- tuning ---------------------------------------------------------------------------------------

def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _to_toolret(idx: ToolIndex, hits) -> list[str]:
    return [toolret_id(idx.rows[t].source_uri) for t, _ in hits]


def tune(catalog: ToolCatalog, queries: list, *, dense: bool, cache=None) -> tuple[dict, list]:
    """(the chosen row, the table) of mean dev nDCG@10 over `W_NAMES` (and `W_GRID` when
    `dense`), every tool ranked by the index (module docstring)."""
    base = ToolIndex.build(catalog, W_NAMES[0], cache, dense=dense)
    table = []
    for w_name in W_NAMES:
        idx = base if w_name == base.w_name else base.with_w_name(w_name)
        if not dense:
            scores = [ndcg(_to_toolret(idx, idx.retrieve(q.query, None, TOP)), q.gold)
                      for q in queries]
            table.append({"w_name": w_name, "w": None, "ndcg@10": _mean(scores)})
            continue
        channels = [idx.channels(q.query, exact=True) for q in queries]
        for w in W_GRID:
            scores = [ndcg(_to_toolret(idx, linear(lex, dn, w, top=TOP)), q.gold)
                      for (lex, dn), q in zip(channels, queries, strict=True)]
            table.append({"w_name": w_name, "w": w, "ndcg@10": _mean(scores)})
    return best(table), table


# -- runs -----------------------------------------------------------------------------------------

def _summary(rows: list[dict], context: bool) -> dict:
    out = {"n": len(rows), **{k: _mean([r[k] for r in rows]) for k in KEYS}}
    if context and rows:
        for k in ("page", "definitions", "loaded", "reduction", "gold_share"):
            out[f"context_{k}"] = _mean([r["context"][k] for r in rows])
        out["context_catalog"] = rows[0]["context"]["catalog"]
    elif rows and "top10_doc_tokens" in rows[0]:
        out["top10_doc_tokens"] = _mean([r["top10_doc_tokens"] for r in rows])
    return out


def _queries(root: Path | None, split: str) -> tuple[list, list]:
    qs = toolret.queries(root)
    return [q for q in qs if q.split == "dev"], [q for q in qs if q.split == split]


def _raw_rows(root: Path | None, queries: list) -> tuple[list[dict], dict]:
    raw = RawBM25(toolret.tools(root))
    rows = []
    for q in queries:
        hits = raw.search(q.query, TOP)
        ranked = [i for i, _ in hits]
        rows.append({"id": q.id, "query": q.query, "gold": list(q.gold), "ranked": ranked,
                     "scores": [s for _, s in hits], **metrics(ranked, q.gold),
                     "top10_doc_tokens": sum(raw.tokens[i] for i in ranked)})
    return rows, {"tools": len(raw.docs), "catalog_doc_tokens": raw.catalog_tokens}


def _active_fingerprint(store: Path) -> str | None:
    """The fingerprint `tools/index/active.json` names, or None (none, or unreadable)."""
    try:
        fp = json.loads((Path(store) / "tools" / "index" / "active.json").read_text(
            encoding="utf-8")).get("fingerprint")
    except (OSError, ValueError, AttributeError):
        return None
    return fp if isinstance(fp, str) else None


def _store_rows(system: str, store: Path, root: Path | None, dev: list, queries: list, *,
                lexical_only: bool, emb_cache: Path, caller: str, threads: int,
                sync: bool) -> tuple[list[dict], dict, dict]:
    catalog = ToolCatalog.open(store)
    dense = system == "tools-hybrid" and not lexical_only
    cache = tools.make_embedding_cache(emb_cache, threads=threads) if dense else None
    chosen, table = tune(catalog, dev, dense=dense, cache=cache)
    before = _active_fingerprint(store)
    op = tools.Tools(store, emb_cache=emb_cache)
    info = op.tools_index(chosen["w_name"], weight=chosen["w"], lexical_only=not dense,
                          threads=threads)
    if sync:
        acl.sync(store)
    by_toolret = {}
    for tid in catalog.ids():
        rec = catalog.get(tid)
        if rec.source_kind == "toolret":
            by_toolret[toolret_id(rec.source_uri)] = tid
    total = sum(catalog.get(t).definition_tokens for t in catalog.ids())
    t = tools.Tools(store, emb_cache=emb_cache, acl=True, caller=caller)
    rows = []
    try:
        acl_snapshot = None
        for q in queries:
            missing = [g for g in q.gold if g not in by_toolret]
            if missing:
                raise ToolEvalError(f"{q.id}: gold tools {missing[:3]} are not in the store's "
                                    f"catalog; ingest the ToolRet tools (`adr tools ingest "
                                    f"--toolret`)")
            res = t.search_tools(q.query, top=TOP)
            loads = [t.load_tool(h.tool_id) for h in res.hits]
            gold_ids = {by_toolret[g] for g in q.gold}
            ranked = [toolret_id(h.source_uri) for h in res.hits]
            rows.append({"id": q.id, "query": q.query, "gold": list(q.gold),
                         "ranked": ranked, "tool_ids": [h.tool_id for h in res.hits],
                         "scores": [h.score for h in res.hits], **metrics(ranked, q.gold),
                         "context": tool_context(res, loads, gold_ids, total)})
        acl_snapshot = acl.read_head(store)[0]
    except tools.AccessDenied as e:
        raise ToolEvalError(f"{store}: {e}\nfix: run `adr acl sync --store {store}` (or pass "
                            f"--sync)") from e
    cfg = {"store": str(store), "tools_snapshot": catalog.snapshot_id,
           "acl_snapshot": acl_snapshot, "fingerprint": info.fingerprint,
           "w_name": info.w_name, "w": info.w, "lexical_only": info.lexical_only,
           "caller": caller, "tools": len(catalog), "catalog_definition_tokens": total,
           "active_tool_index": {"before": before, "after": info.fingerprint}}
    return rows, cfg, {"metric": "ndcg@10", "split": "dev", "queries": len(dev),
                       "chosen": chosen, "table": table}


def run(system: str, split: str, store: Path | None = None, *, root: Path | None = None,
        lexical_only: bool = False, out: Path | None = None, emb_cache: Path | None = None,
        caller: str = CALLER, threads: int = 1, sync: bool = False) -> Path:
    """Run one system over one split and write its run directory (module docstring)."""
    if system not in SYSTEMS:
        raise ToolEvalError(f"unknown system {system!r}; expected one of {', '.join(SYSTEMS)}")
    if split not in ("dev", "test"):
        raise ToolEvalError(f"split must be dev or test, got {split!r}")
    started = datetime.now(UTC)
    t0 = time.perf_counter()
    dev, queries = _queries(root, split)
    if system == "tools-bm25-raw":
        rows, cfg = _raw_rows(root, queries)
        tuning = None
    else:
        if store is None:
            raise ToolEvalError(f"{system} searches a store: pass --store (a tools-only store "
                                f"from `adr tools ingest --toolret`)")
        rows, cfg, tuning = _store_rows(
            system, Path(store), root, dev, queries, lexical_only=lexical_only,
            emb_cache=Path(emb_cache or tools.DEFAULT_EMB_CACHE), caller=caller,
            threads=threads, sync=sync)
    summary = _summary(rows, system != "tools-bm25-raw")
    config = {"track": "tools", "system": system, "split": split, "top": TOP,
              "started": started.isoformat(), **cfg,
              "lexical_only": cfg.get("lexical_only", True)}
    d = Path(out or OUT_ROOT) / f"tools-{system}-{split}-{started:%Y%m%dT%H%M%S}"
    n = 1
    while d.exists():
        n += 1
        d = d.with_name(f"tools-{system}-{split}-{started:%Y%m%dT%H%M%S}-{n}")
    d.mkdir(parents=True)
    rec = {"config": config, "tuning": tuning, "summary": summary, "rows": rows}
    (d / "tools.json").write_text(json.dumps(rec, indent=2, sort_keys=True,
                                             ensure_ascii=False) + "\n", encoding="utf-8")
    (d / "tools.md").write_text(render_markdown(rec, time.perf_counter() - t0),
                                encoding="utf-8")
    return d


def render_markdown(rec: dict, seconds: float | None = None) -> str:
    c, s = rec["config"], rec["summary"]
    lines = [f"# Tool retrieval: {c['system']} on {c['split']}", ""]
    if c["system"] == "tools-bm25-raw":
        lines.append(f"BM25 over the raw ToolRet documentation of {c['tools']} tools "
                     f"({c['catalog_doc_tokens']} tokens).")
    else:
        mode = "lexical only" if c["lexical_only"] else f"fusion weight w = {c['w']}"
        lines.append(f"Store `{c['store']}`, tool snapshot `{c['tools_snapshot'][:12]}`, ACL "
                     f"snapshot `{str(c['acl_snapshot'])[:12]}`, tool index "
                     f"`{c['fingerprint'][:12]}` (w_name {c['w_name']}, {mode}), searched as "
                     f"`{c['caller']}`. Tuned on dev nDCG@10 "
                     f"({rec['tuning']['queries']} queries).")
    if "active_tool_index" in c:
        old, new = c["active_tool_index"]["before"], c["active_tool_index"]["after"]
        same = " (unchanged)" if old == new else ""
        lines += ["", f"active tool index: {'none' if old is None else old[:12]} → "
                      f"{new[:12]}{same}"]
    lines += ["", "| queries | Completeness@10 | Recall@10 | nDCG@10 |", "|---|---|---|---|",
              f"| {s['n']} | {s['completeness@10']:.3f} | {s['recall@10']:.3f} | "
              f"{s['ndcg@10']:.3f} |", ""]
    if "context_loaded" in s:
        lines.append(f"Tool context (mean per query): loaded {s['context_loaded']:.0f} tokens "
                     f"(page {s['context_page']:.0f}, definitions "
                     f"{s['context_definitions']:.0f}) of a catalog of "
                     f"{s['context_catalog']} tokens; reduction {s['context_reduction']:.4%}; "
                     f"gold share {s['context_gold_share']:.3f} (the mean over queries of the "
                     f"loaded gold definition tokens / loaded tokens; page entries are not "
                     f"counted as gold).")
    elif "top10_doc_tokens" in s:
        lines.append(f"Top 10 raw documentation: {s['top10_doc_tokens']:.0f} tokens per query "
                     f"(mean).")
    if seconds is not None:
        lines += ["", f"Wall-clock {seconds:.1f} s. No model calls."]
    return "\n".join(lines) + "\n"
