"""Phase 2 comparisons of retrieval runs (Phase 2 spec §10.1, §13 A3-A6): item subsets, slot
counts, non-inferiority and the identity check.

- `item_subsets`: the item subsets of spec §4.6 — `asof` (dated `policy_asof` items with
  evidence), `in_force` (other items with evidence whose every evidence group has a member in
  a document that is not superseded), `superseded_only` (the other items with evidence) and
  `scored` (every item with metrics).
- `slot_stats`: per subset, the top-10 slots holding a chunk of a superseded document, of a
  document not in force on an `asof` item's date (wrong version), a duplicate of a slot above
  it (sharing a dedup component among the chunks the run's filters admit, sharing a cluster,
  or holding the same text), the distinct evidence groups touched, and tokens@10.
- `noninferiority`: paired bootstrap of `run_b - run_a` (`adr_eval.scoring.stats`, 10,000
  resamples, seed 20261108); a key passes when the interval's lower bound is above
  `-margin` (0.02, fixed before any Phase 2 result, spec §13).
- `identical`: same items, ranked chunk ids equal, scores equal exactly (criterion A5).
- `compare` (`adr-eval p2-compare`): both runs' slot counts and every subset's paired
  differences and verdicts over the chunks and overlays of a store; A3 is the `asof`
  verdict, A4 the `in_force` one.

This module may import `adr_store` directly (plan, shared rules).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from adr_eval import runner
from adr_eval.models import Evidence, GoldenItem
from adr_eval.scoring import evidence_groups
from adr_eval.scoring.retrieval_metrics import overlap
from adr_eval.scoring.stats import paired_bootstrap_ci
from adr_store.applicability import Applicability, Filters, admits

MARGIN = 0.02
N_RESAMPLES = 10_000
SEED = 20261108
KEYS = ("recall@10", "ndcg@10", "mrr")
CRITERION_KEYS = ("recall@10", "ndcg@10")  # A3 and A4 are stated on these two
SUBSETS = ("asof", "in_force", "superseded_only", "scored")
CRITERIA = {"A3": "asof", "A4": "in_force"}
OUT_ROOT = Path("runs")  # where `adr-eval p2-compare` writes by default (tests redirect it)
Groups = dict[str, list[list[Evidence]]]


# -- item subsets ---------------------------------------------------------------------------


def _groups_of(item: GoldenItem, groups: Groups) -> list[list[Evidence]]:
    return groups.get(item.id) or [[e] for e in item.evidence]


def _superseded(doc_id: str, applicability: Applicability | None) -> bool:
    if applicability is None:
        return False
    return applicability.records[doc_id].superseded_by is not None


def item_subsets(items: Iterable[GoldenItem], groups: Groups,
                 applicability: Applicability | None) -> dict[str, list[str]]:
    """The item ids of each subset (sorted); without an overlay nothing is superseded."""
    out: dict[str, list[str]] = {k: [] for k in SUBSETS}
    for item in sorted(items, key=lambda i: i.id):
        if item.qtype == "insufficient" or not item.evidence:
            continue
        out["scored"].append(item.id)
        if item.qtype == "policy_asof" and item.as_of is not None:
            out["asof"].append(item.id)
        elif all(any(not _superseded(e.doc_id, applicability) for e in g)
                 for g in _groups_of(item, groups)):
            out["in_force"].append(item.id)
        else:
            out["superseded_only"].append(item.id)
    return out


# -- slot counts ----------------------------------------------------------------------------


def _share(part: int | None, whole: int) -> float | None:
    return None if part is None or whole == 0 else part / whole


def slot_stats(rows: list[dict], chunks: dict, applicability: Applicability | None, dedup,
               items: Iterable[GoldenItem], groups: Groups, *,
               filters: Filters | None = None) -> dict:
    """Slot counts of a run's top 10 per subset. `filters` are the run's own (None: the
    Phase 1 view, `include_superseded`); a row's `as_of` (the date its system's search
    applied, recorded by the runner; null or absent for none) replaces them as the run did.
    Duplicate components are those of the dedup overlay among the chunks these filters admit
    (None without an overlay); `duplicate_cluster_slots` ignores the filters."""
    by_id = {i.id: i for i in items}
    base = Filters(include_superseded=True) if filters is None else filters
    rows_by = {r["item_id"]: r for r in rows}
    subsets = item_subsets([by_id[i] for i in rows_by if i in by_id], groups, applicability)
    subsets["all"] = sorted(rows_by)
    out = {}
    for name, ids in subsets.items():
        out[name] = _slot_block([rows_by[i] for i in ids], by_id, chunks, applicability,
                                dedup, groups, base)
    return out


def _slot_block(rows, by_id, chunks, applicability, dedup, groups, base: Filters) -> dict:
    n_slots = superseded = wrong = wrong_slots = dup = dup_cluster = exact = 0
    touched, with_groups, tokens = 0, 0, []
    for r in rows:
        item = by_id.get(r["item_id"])
        ranked = r["ranked"][:10]
        n_slots += len(ranked)
        as_of = r.get("as_of")
        f = base if as_of is None else Filters(as_of=date.fromisoformat(as_of))

        def admitted(cid, f=f):
            return applicability is None or admits(
                applicability.records[chunks[cid].doc_id], f)

        comps: dict[str, list[list[str]]] = {}
        seen_comp, seen_cluster, seen_text = set(), set(), set()
        for cid in ranked:
            c = chunks[cid]
            superseded += _superseded(c.doc_id, applicability)
            if item is not None and item.as_of is not None and applicability is not None:
                wrong += not admits(applicability.records[c.doc_id],
                                    Filters(as_of=item.as_of))
            if c.text in seen_text:
                exact += 1
            seen_text.add(c.text)
            cluster = None if dedup is None else dedup.cluster_of(cid)
            if cluster is None:
                continue
            if cluster in seen_cluster:
                dup_cluster += 1
            seen_cluster.add(cluster)
            if not admitted(cid):
                continue
            if cluster not in comps:
                comps[cluster] = dedup.components(cluster, admitted)
            key = (cluster, min(next(m for m in comps[cluster] if cid in m)))
            if key in seen_comp:
                dup += 1
            seen_comp.add(key)
        if item is not None and item.as_of is not None:
            wrong_slots += len(ranked)
        if item is not None and item.evidence and item.qtype != "insufficient":
            gs = _groups_of(item, groups)
            with_groups += 1
            touched += sum(any(overlap(chunks[cid], e) > 0 for cid in ranked for e in g)
                           for g in gs)
        if r.get("metrics") and r["metrics"].get("tokens@10") is not None:
            tokens.append(r["metrics"]["tokens@10"])
    dated = applicability is not None and wrong_slots > 0
    no_dedup = dedup is None
    return {
        "n_items": len(rows), "n_slots": n_slots,
        "superseded_slots": None if applicability is None else superseded,
        "superseded_share": _share(None if applicability is None else superseded, n_slots),
        "wrong_version_slots": wrong if dated else None,
        "wrong_version_share": _share(wrong if dated else None, wrong_slots),
        "duplicate_slots": None if no_dedup else dup,
        "duplicate_share": _share(None if no_dedup else dup, n_slots),
        "duplicate_cluster_slots": None if no_dedup else dup_cluster,
        "duplicate_cluster_share": _share(None if no_dedup else dup_cluster, n_slots),
        "exact_copy_slots": exact, "exact_copy_share": _share(exact, n_slots),
        "evidence_groups_touched": touched,
        "evidence_groups_touched_mean": _share(touched, with_groups),
        "tokens@10": sum(tokens) / len(tokens) if tokens else None,
    }


# -- paired differences ---------------------------------------------------------------------


def noninferiority(rows_a: list[dict], rows_b: list[dict], item_ids: list[str],
                   keys: tuple[str, ...] = KEYS, margin: float = MARGIN,
                   n: int = N_RESAMPLES, seed: int = SEED,
                   criterion: tuple[str, ...] = CRITERION_KEYS) -> dict:
    """Paired differences `b - a` over `item_ids` with 95% bootstrap intervals; a key passes
    when the lower bound is above `-margin`; `pass` is all of `criterion` (None for no
    items)."""
    ra = {r["item_id"]: r for r in rows_a}
    rb = {r["item_id"]: r for r in rows_b}
    missing = [i for i in item_ids if not (ra.get(i) or {}).get("metrics")
               or not (rb.get(i) or {}).get("metrics")]
    if missing:
        raise runner.RunError(f"{len(missing)} item(s) lack metrics in one of the runs "
                              f"(e.g. {missing[0]})")
    out = {"n": len(item_ids), "margin": margin, "n_resamples": n, "seed": seed,
           "difference": "run_b - run_a", "keys": {}, "pass": None}
    if not item_ids:
        return out
    for k in keys:
        x = [ra[i]["metrics"][k] for i in item_ids]
        y = [rb[i]["metrics"][k] for i in item_ids]
        mean, lo, hi = paired_bootstrap_ci(x, y, n=n, seed=seed)
        out["keys"][k] = {"a": sum(x) / len(x), "b": sum(y) / len(y), "mean_diff": mean,
                          "ci95": [lo, hi], "pass": lo > -margin}
    out["pass"] = all(out["keys"][k]["pass"] for k in criterion if k in out["keys"])
    return out


# -- identity -------------------------------------------------------------------------------


def identical(run_a: dict, run_b: dict) -> dict:
    """Whether two retrieval runs (`retrieval.json` data) give the same items, the same ranked
    chunk ids and exactly the same scores; `differences` holds the first difference of each
    differing item."""
    ra = {r["item_id"]: r for r in run_a["rows"]}
    rb = {r["item_id"]: r for r in run_b["rows"]}
    diffs = []
    for item_id in sorted(ra.keys() & rb.keys()):
        a, b = ra[item_id], rb[item_id]
        pa = list(zip(a["ranked"], a["scores"], strict=True))
        pb = list(zip(b["ranked"], b["scores"], strict=True))
        if pa == pb:
            continue
        rank = next((k for k, (x, y) in enumerate(zip(pa, pb, strict=False)) if x != y),
                    min(len(pa), len(pb)))
        diffs.append({"item_id": item_id, "rank": rank + 1,
                      "a": list(pa[rank]) if rank < len(pa) else None,
                      "b": list(pb[rank]) if rank < len(pb) else None,
                      "len_a": len(pa), "len_b": len(pb)})
    only_a, only_b = sorted(ra.keys() - rb.keys()), sorted(rb.keys() - ra.keys())
    return {"identical": not diffs and not only_a and not only_b,
            "n_items_a": len(ra), "n_items_b": len(rb), "n_shared": len(ra.keys() & rb.keys()),
            "only_a": only_a, "only_b": only_b, "n_differing": len(diffs),
            "differences": diffs}


# -- p2-compare -----------------------------------------------------------------------------


def _store_view(store_path: Path, settings: dict):
    """(store, chunks by id, applicability, dedup, notes) of a store for a run's chunker;
    `notes` says which overlay is missing and so which counts are None."""
    from adr_store import applicability, dedup
    from adr_store.chunking import chunk_store, chunker_config
    from adr_store.retrieval.index import chunk_content_sha256
    from adr_store.store import Store, StoreError

    try:
        store = Store.open(store_path)
    except StoreError as e:
        raise runner.RunError(str(e)) from e
    chunker = settings.get("chunker")
    if not chunker or chunker.get("kind") != "structure":
        raise runner.RunError("p2-compare needs runs of the store systems (a structure "
                              "chunker in settings.chunker)")
    if chunker != chunker_config(chunker["max_tokens"], chunker["min_tokens"]):
        raise runner.RunError(f"the runs' chunker {chunker} is not this code's; the store's "
                              f"chunks cannot be rebuilt")
    chunks = {c.chunk_id: c for c in chunk_store(store, chunker["max_tokens"],
                                                 chunker["min_tokens"])}
    try:
        app = applicability.load_overlay(store.path, store.snapshot_id)
        dd = dedup.load_overlay(store.path, store.snapshot_id, chunker,
                                chunk_content_sha256(chunks.values()))
    except StoreError as e:
        raise runner.RunError(str(e)) from e
    notes = []
    if app is None:
        notes.append(f"no applicability overlay in {store_path}: superseded and "
                     f"wrong-version slots are not counted (None); run `adr applicability "
                     f"derive --store {store_path}`")
    if dd is None:
        why = dedup.missing(store.path, store.snapshot_id, chunker,
                            chunk_content_sha256(chunks.values()))
        fix = f"`adr dedup build --store {store_path}`"
        notes.append(f"{why.replace('`adr dedup build`', fix)}: duplicate slots are not "
                     f"counted (None)")
    return store, chunks, app, dd, notes


def _filters_of(settings: dict) -> Filters | None:
    f = settings.get("filters")
    return None if f is None else Filters.parse(f)


def compare(run_a: Path, run_b: Path, store_path: Path, margin: float = MARGIN,
            n: int = N_RESAMPLES, seed: int = SEED) -> dict:
    """The p2-compare record of two retrieval runs (`run_b - run_a`) over the chunks and
    overlays of the store at `store_path`. Refuses runs of other corpora, splits, golden sets
    or metrics versions, a run whose `store_snapshot` is not the store's HEAD, and a golden
    set that changed since the runs."""
    from adr_eval.report import load_retrieval

    a, b = load_retrieval(run_a), load_retrieval(run_b)
    ca, cb = a["config"], b["config"]
    for key in ("corpus", "split", "golden_sha256", "metrics_version"):
        if ca.get(key) != cb.get(key):
            raise runner.RunError(f"cannot compare runs of different {key}: "
                                  f"{ca.get(key)} and {cb.get(key)}")
    sa, sb = ca.get("settings") or {}, cb.get("settings") or {}
    if sa.get("chunker") != sb.get("chunker"):
        raise runner.RunError("cannot compare runs of different chunkers")
    store, chunks, app, dd, notes = _store_view(store_path, sa)
    for name, s in ((Path(run_a).name, sa), (Path(run_b).name, sb)):
        if s.get("store_snapshot") != store.snapshot_id:
            raise runner.RunError(
                f"{name}: store snapshot {str(s.get('store_snapshot'))[:12]} is not the "
                f"store's HEAD {store.snapshot_id[:12]} ({store_path})")
    for name, data in ((Path(run_a).name, a), (Path(run_b).name, b)):
        unknown = [c for r in data["rows"] for c in r["ranked"] if c not in chunks]
        if unknown:
            raise runner.RunError(f"{name}: {len(unknown)} ranked chunk(s) are not chunks of "
                                  f"the store (e.g. {unknown[0]})")
    for name, data, s in ((Path(run_a).name, a, sa), (Path(run_b).name, b, sb)):
        dated = [r["item_id"] for r in data["rows"] if r.get("as_of") is not None]
        if dated and s.get("as_of_from_item") is not True:
            raise runner.RunError(
                f"{name}: {len(dated)} row(s) record an as_of (e.g. {dated[0]}) that its "
                f"system does not apply (settings.as_of_from_item is not true); a run of an "
                f"older version, whose rows recorded the date passed: run it again")
    corpus = ca["corpus"]
    loaded = runner.load_checked_corpus(corpus)
    items = runner.load_golden(corpus, loaded)
    golden = runner.golden_items_path(corpus)
    if hashlib.sha256(golden.read_bytes()).hexdigest() != ca.get("golden_sha256"):
        raise runner.RunError(f"{golden}: changed since the runs (golden_sha256)")
    groups = evidence_groups.build_all(items, loaded.docs)
    split = [i for i in items if i.split == ca["split"]]
    subsets = item_subsets(split, groups, app)
    out_subsets = {k: noninferiority(a["rows"], b["rows"], ids, margin=margin, n=n, seed=seed)
                   for k, ids in subsets.items()}
    return {
        "run_a": Path(run_a).name, "run_b": Path(run_b).name,
        "system_a": ca["system"], "system_b": cb["system"], "corpus": corpus,
        "split": ca["split"], "golden_sha256": ca.get("golden_sha256"),
        "metrics_version": ca["metrics_version"], "difference": "run_b - run_a",
        "store": runner._display_path(store.path), "snapshot": store.snapshot_id,
        "applicability": None if app is None else app.overlay_id,
        "dedup": None if dd is None else dd.overlay_id,
        "dedup_params": None if dd is None else dd.overlay.params,
        "dedup_clusters": None if dd is None else len(dd.overlay.clusters),
        "notes": notes, "margin": margin, "n_resamples": n, "seed": seed,
        "subset_sizes": {k: len(v) for k, v in subsets.items()},
        "subsets": out_subsets,
        "criteria": {c: {"subset": s, "pass": out_subsets[s]["pass"], "n": out_subsets[s]["n"]}
                     for c, s in CRITERIA.items()},
        "slots": {side: slot_stats(d["rows"], chunks, app, dd, split, groups,
                                   filters=_filters_of(c["settings"]))
                  for side, d, c in (("a", a, ca), ("b", b, cb))},
    }


def _fmt(x) -> str:
    if x is None:
        return "-"
    if isinstance(x, float):
        return f"{x:.3f}"
    return str(x)


def render_compare_markdown(c: dict) -> str:
    out = [f"# Phase 2 comparison: {c['system_b']} minus {c['system_a']}", "",
           f"Run `{c['run_b']}` minus run `{c['run_a']}` on `{c['corpus']}` / `{c['split']}`. "
           f"Store `{c['store']}` (snapshot `{c['snapshot'][:12]}`), applicability overlay "
           f"`{_fmt(c['applicability'] and c['applicability'][:12])}`, dedup overlay "
           f"`{_fmt(c['dedup'] and c['dedup'][:12])}`. Paired bootstrap 95% CIs "
           f"({c['n_resamples']} resamples, seed {c['seed']}); non-inferiority margin "
           f"{c['margin']}: a metric passes when the lower bound is above -{c['margin']}.", "",
           *(line for note in c.get("notes", []) for line in (f"> **Note:** {note}", ""))]
    rows = []
    for name, s in c["subsets"].items():
        if not s["keys"]:
            rows.append([name, s["n"], "-", "-", "-", "-"])
            continue
        cells = [f"{m['a']:.3f} -> {m['b']:.3f} ({m['mean_diff']:+.3f} "
                 f"[{m['ci95'][0]:+.3f}, {m['ci95'][1]:+.3f}])" for m in s["keys"].values()]
        rows.append([name, s["n"], *cells, {True: "pass", False: "fail"}[s["pass"]]])
    out += ["| subset | n | Recall@10 | nDCG@10 | MRR | verdict |", "|---|---|---|---|---|---|",
            *("| " + " | ".join(str(x) for x in r) + " |" for r in rows), ""]
    out += [", ".join(f"{k} ({v['subset']}, n {v['n']}): "
                      f"{ {True: 'pass', False: 'fail', None: 'no items'}[v['pass']] }"
                      for k, v in c["criteria"].items()), ""]
    keys = ("n_items", "n_slots", "superseded_slots", "superseded_share",
            "wrong_version_slots", "wrong_version_share", "duplicate_slots", "duplicate_share",
            "duplicate_cluster_slots", "exact_copy_slots", "exact_copy_share",
            "evidence_groups_touched", "evidence_groups_touched_mean", "tokens@10")
    for side in ("a", "b"):
        out += [f"## Slots of run {side.upper()} ({c[f'system_{side}']})", "",
                "| subset | " + " | ".join(keys) + " |",
                "|---|" + "---|" * len(keys)]
        for name, s in c["slots"][side].items():
            out.append(f"| {name} | " + " | ".join(_fmt(s[k]) for k in keys) + " |")
        out.append("")
    return "\n".join(out)


def write_compare(c: dict, out_root: Path) -> Path:
    d = Path(out_root) / f"p2-compare-{c['run_a']}--{c['run_b']}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "compare.json").write_text(json.dumps(c, indent=2, sort_keys=True) + "\n",
                                    encoding="utf-8")
    (d / "compare.md").write_text(render_compare_markdown(c), encoding="utf-8")
    return d
