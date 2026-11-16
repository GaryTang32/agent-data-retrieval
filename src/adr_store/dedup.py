r"""The dedup overlay: exact and near-duplicate chunks of one index's chunks, and collapse at
query time (Phase 2 spec §4.5).

    <store>/dedup/<snapshot_id>/<overlay_key>-<content>.json    the overlay (canonical JSON,
                                                                write-once)

`overlay_key` is the first 16 hex characters of the SHA-256 of the canonical JSON of
{chunker configuration, `PARAMS`} and `<content>` the first 16 of the `chunk_content_sha256`
of the chunks it was built over (as `StoreIndex` hashes its chunks: ids, breadcrumbs and
texts); the overlay id is the SHA-256 of the file. So chunks rechunked under the same snapshot
and chunker configuration (a chunker change that kept `CHUNKER_VERSION`) have no overlay
until `adr dedup build` writes theirs beside the old one, which stays as it was; the file
records the full `chunk_content_sha256`, checked on load. `missing` says why there is no
overlay for a set of chunks (none at all, or only for other chunks or settings).

Exact duplicates: chunks whose text (the body as stored) has the same SHA-256. Near
duplicates: MinHash over word 5-shingles (`\w+` tokens, each lower-cased, joined by one space; a
chunk of fewer than 5 tokens is one shingle of all its tokens, "" for none), 128 hash functions
`(a·h + b) mod 4294967311` where `h` is the first 4 bytes (big-endian) of the shingle's
SHA-256 and, for i in 0..127, `a_i = rng.randrange(1, 2**32)` then `b_i = rng.randrange(0,
2**32)` with `rng = random.Random(20261116)`. With `a, h, b < 2**32`, `a·h + b < 2**64`, so
the `uint64` arithmetic is exact. LSH with 16 bands of 8 rows proposes candidate pairs among
the distinct texts; every candidate is verified by exact Jaccard on the shingle sets and kept
at Jaccard >= 0.90 (compared in integers: 10·|A∩B| >= 9·|A∪B|).

Clusters are the connected components of the exact edges (every pair of chunks with one
text, Jaccard 1.0) and the verified near edges (every pair of chunks of two verified texts).
A cluster stores its sorted members, every qualifying edge (member indices, Jaccard rounded
to 6 decimals), `kind` (`exact` iff all its members have one text) and `min_jaccard`.

Collapse (`collapse`). Edges, not components, are what a query uses: a cluster's members are
restricted to those the caller's view and filters admit, and the slot unit is a connected
component of the cluster's edges among them, so a hidden or filtered member never joins two
visible ones. Walking the ranked candidates, the first member of each admitted component
takes the slot; the slot shows the component's canonical member (`canonical`, §4.5 rules 1-4)
with the best-ranked member's score (`scored_by`), and lists the other admitted members as
`alternates` (exact or near, Jaccard to the shown member from their shingles), in canonical
order. The walk stops at `top` slots. `ranked` may be lazy (`StoreIndex.ranking`): the walk reads
it only as far as it needs, so the slots are those of collapsing the whole ranking.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from adr_eval.retrieval.chunker import _count as count_tokens
from adr_store.applicability import Applicability, Envelope
from adr_store.chunking import StoreChunk
from adr_store.records import _HEX64, canonical_json, sha256_text
from adr_store.retrieval.index import chunk_content_sha256
from adr_store.store import StoreError, write_atomic

OVERLAY_DIR = "dedup"
FORMAT_VERSION = "0.1"
PARAMS = {"exact": "sha256(text)", "tokens": r"\w+", "lower": True, "shingle": 5,
          "num_perm": 128, "prime": 4294967311, "seed": 20261116,
          "a_range": [1, 2**32], "b_range": [0, 2**32], "bands": 16, "rows": 8,
          "threshold": 0.90}
NO_OVERLAY = "no dedup overlay; run `adr dedup build`"
OFF = "dedup off (dedup=false)"
_TOKEN = re.compile(PARAMS["tokens"])
_PRIME = np.uint64(PARAMS["prime"])


def _family() -> tuple[np.ndarray, np.ndarray]:
    rng = random.Random(PARAMS["seed"])
    a, b = [], []
    for _ in range(PARAMS["num_perm"]):
        a.append(rng.randrange(*PARAMS["a_range"]))
        b.append(rng.randrange(*PARAMS["b_range"]))
    return np.array(a, dtype=np.uint64), np.array(b, dtype=np.uint64)


_A, _B = _family()


# -- shingles, MinHash, Jaccard --------------------------------------------------------------

def shingles(text: str) -> frozenset[str]:
    """The word 5-shingles of `text`: `\\w+` tokens, each lower-cased, 5 consecutive joined by
    one space; fewer than 5 tokens give one shingle of all of them ("" for none)."""
    words = [t.lower() for t in _TOKEN.findall(text)]
    n = PARAMS["shingle"]
    if len(words) < n:
        return frozenset({" ".join(words)})
    return frozenset(" ".join(words[i:i + n]) for i in range(len(words) - n + 1))


def _shingle_hash(s: str) -> int:
    return int.from_bytes(hashlib.sha256(s.encode("utf-8")).digest()[:4], "big")


def minhash(sh: frozenset[str]) -> np.ndarray:
    """The 128 MinHash values (`uint64`) of a non-empty shingle set."""
    h = np.fromiter((_shingle_hash(s) for s in sorted(sh)), dtype=np.uint64, count=len(sh))
    return ((_A[:, None] * h[None, :] + _B[:, None]) % _PRIME).min(axis=1)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    union = len(a | b)
    return 1.0 if union == 0 else len(a & b) / union


def qualifies(a: frozenset[str], b: frozenset[str]) -> bool:
    """Jaccard >= the threshold (0.90), in integers."""
    inter, union = len(a & b), len(a | b)
    return 10 * inter >= 9 * union


def _j6(x: float) -> float:
    return round(x, 6)


# -- the overlay -------------------------------------------------------------------------------

class Cluster(BaseModel):
    """Chunks that are copies of each other: sorted `members`, every qualifying edge
    `(i, j, jaccard)` with `i < j` member indices, sorted."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="DedupCluster")

    cluster_id: str = Field(pattern=_HEX64)
    members: list[str] = Field(min_length=2)
    kind: Literal["exact", "near"]
    min_jaccard: float
    edges: list[tuple[int, int, float]] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> Cluster:
        m = self.members
        if m != sorted(set(m)):
            raise ValueError("members must be sorted and distinct")
        if self.cluster_id != hashlib.sha256("\n".join(m).encode("utf-8")).hexdigest():
            raise ValueError("cluster_id is not the SHA-256 of the members")
        pairs = [(i, j) for i, j, _ in self.edges]
        if pairs != sorted(set(pairs)) or not all(0 <= i < j < len(m) for i, j in pairs):
            raise ValueError("edges must be sorted distinct (i, j) with i < j < len(members)")
        if not all(PARAMS["threshold"] <= x <= 1.0 for _, _, x in self.edges):
            raise ValueError("an edge's Jaccard is outside [threshold, 1]")
        if self.min_jaccard != min(x for _, _, x in self.edges):
            raise ValueError("min_jaccard is not the minimum over the edges")
        if self.kind == "exact" and self.min_jaccard != 1.0:
            raise ValueError("an exact cluster has an edge below 1.0")
        if len(_components(range(len(m)), pairs)) != 1:
            raise ValueError("the edges do not connect the members")
        return self


class DedupOverlay(BaseModel):
    """The content of `<store>/dedup/<snapshot>/<overlay_key>-<content>.json`."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="DedupOverlay")

    format_version: Literal["0.1"]
    snapshot: str = Field(pattern=_HEX64)
    chunker: dict
    chunk_content_sha256: str = Field(pattern=_HEX64)
    params: dict
    clusters: list[Cluster]
    stats: dict

    @model_validator(mode="after")
    def _disjoint(self) -> DedupOverlay:
        ids = [c.cluster_id for c in self.clusters]
        if ids != sorted(set(ids)):
            raise ValueError("clusters must be sorted by cluster_id and distinct")
        seen: set[str] = set()
        for c in self.clusters:
            if seen & set(c.members):
                raise ValueError("a chunk is in two clusters")
            seen |= set(c.members)
        return self


def _components(nodes: Iterable, edges: Iterable[tuple]) -> list[list]:
    """Connected components (union-find), each sorted, in order of their smallest node."""
    parent = {n: n for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    groups: dict = {}
    for n in parent:
        groups.setdefault(find(n), []).append(n)
    return sorted((sorted(g) for g in groups.values()), key=lambda g: g[0])


def _candidates(signatures: list[np.ndarray]) -> set[tuple[int, int]]:
    """LSH: the pairs (i < j) of rows sharing the 8 values of at least one of the 16 bands."""
    pairs: set[tuple[int, int]] = set()
    rows = PARAMS["rows"]
    for band in range(PARAMS["bands"]):
        buckets: dict[bytes, list[int]] = {}
        for i, sig in enumerate(signatures):
            buckets.setdefault(sig[band * rows:(band + 1) * rows].tobytes(), []).append(i)
        for members in buckets.values():
            for x in range(len(members)):
                for y in range(x + 1, len(members)):
                    pairs.add((members[x], members[y]))
    return pairs


def build(chunks: list[StoreChunk], snapshot: str, chunker: dict) -> DedupOverlay:
    """The dedup overlay of `chunks` (one index's chunks of `snapshot`, made by `chunker`).
    Deterministic: the same chunks in any order give the same overlay."""
    by_id = {c.chunk_id: c for c in chunks}
    if len(by_id) != len(chunks):
        raise ValueError("duplicate chunk ids")
    ids = sorted(by_id)
    sha = {cid: sha256_text(by_id[cid].text) for cid in ids}
    texts: dict[str, list[str]] = {}
    for cid in ids:
        texts.setdefault(sha[cid], []).append(cid)
    keys = sorted(texts)
    sh = [shingles(by_id[texts[k][0]].text) for k in keys]
    candidates = sorted(_candidates([minhash(s) for s in sh]))
    edges: dict[tuple[str, str], float] = {}
    for group in texts.values():  # exact: every pair of one text
        for x in range(len(group)):
            for y in range(x + 1, len(group)):
                edges[(group[x], group[y])] = 1.0
    near_pairs = 0
    for i, j in candidates:
        if not qualifies(sh[i], sh[j]):
            continue
        near_pairs += 1
        jac = _j6(jaccard(sh[i], sh[j]))
        for a in texts[keys[i]]:
            for b in texts[keys[j]]:
                edges[(min(a, b), max(a, b))] = jac
    comps = [c for c in _components(ids, edges) if len(c) > 1]
    where = {cid: (n, i) for n, comp in enumerate(comps) for i, cid in enumerate(comp)}
    per_comp: list[list[tuple[int, int, float]]] = [[] for _ in comps]
    for (a, b), x in edges.items():
        (n, i), (_, j) = where[a], where[b]
        per_comp[n].append((i, j, x))
    clusters = []
    for comp, cl_edges in zip(comps, per_comp, strict=True):
        cl_edges.sort()
        clusters.append(Cluster(
            cluster_id=hashlib.sha256("\n".join(comp).encode("utf-8")).hexdigest(),
            members=comp, kind="exact" if len({sha[c] for c in comp}) == 1 else "near",
            min_jaccard=min(x for _, _, x in cl_edges), edges=cl_edges))
    clusters.sort(key=lambda c: c.cluster_id)
    stats = {**figures(by_id, clusters), "distinct_texts": len(keys),
             "candidate_pairs": len(candidates), "verified_candidates": near_pairs,
             "rejected_candidates": len(candidates) - near_pairs}
    return DedupOverlay(format_version=FORMAT_VERSION, snapshot=snapshot, chunker=chunker,
                        chunk_content_sha256=chunk_content_sha256(chunks), params=PARAMS,
                        clusters=clusters, stats=stats)


def _restricted(cluster: Cluster, admitted: Callable[[str], bool]) -> list[list[str]]:
    keep = [i for i, cid in enumerate(cluster.members) if admitted(cid)]
    kept = set(keep)
    comps = _components(keep, [(i, j) for i, j, _ in cluster.edges if i in kept and j in kept])
    return [[cluster.members[i] for i in comp] for comp in comps]


def figures(chunks: Mapping[str, StoreChunk], clusters: list[Cluster],
            admitted: Callable[[str], bool] | None = None) -> dict:
    """The §4.5 table row for the chunks `admitted` keeps (all when None): exact clusters
    (SHA-256 groups) and the chunks in them, redundant chunks (all but one per group) and
    their share of the tokens, verified near pairs (pairs of kept chunks with different texts
    joined by an edge) and the pairs of distinct texts among them, clusters at the threshold
    (components of the edges among the kept chunks) and their redundancy (all but one chunk
    per cluster)."""
    keep = sorted(c for c in chunks if admitted is None or admitted(c))
    sha = {c: sha256_text(chunks[c].text) for c in keep}
    tokens = {c: count_tokens(chunks[c].text) for c in keep}
    groups: dict[str, list[str]] = {}
    for c in keep:
        groups.setdefault(sha[c], []).append(c)
    exact = [g for g in groups.values() if len(g) > 1]
    keep_set = set(keep)
    comps, near_pairs, near_texts = [], 0, set()
    for cl in clusters:
        for comp in _restricted(cl, lambda c: c in keep_set):
            if len(comp) > 1:
                comps.append(comp)
        for i, j, _ in cl.edges:
            a, b = cl.members[i], cl.members[j]
            if a in keep_set and b in keep_set and sha[a] != sha[b]:
                near_pairs += 1
                near_texts.add(tuple(sorted((sha[a], sha[b]))))
    n, total = len(keep), sum(tokens.values())
    redundant = sum(len(c) - 1 for c in comps)
    exact_tokens = sum(tokens[c] for g in exact for c in g[1:])

    def share(part: int, whole: int) -> float | None:
        return None if whole == 0 else round(part / whole, 6)

    return {"chunks": n, "tokens": total, "exact_clusters": len(exact),
            "exact_chunks": sum(len(g) for g in exact),
            "exact_redundant": sum(len(g) - 1 for g in exact),
            "exact_redundant_share": share(sum(len(g) - 1 for g in exact), n),
            "exact_redundant_tokens": exact_tokens,
            "exact_redundant_token_share": share(exact_tokens, total),
            "near_pairs": near_pairs, "near_text_pairs": len(near_texts),
            "clusters": len(comps),
            "clustered_chunks": sum(len(c) for c in comps), "redundant": redundant,
            "redundant_share": share(redundant, n)}


# -- files -------------------------------------------------------------------------------------

def overlay_key(chunker: dict, params: dict) -> str:
    blob = json.dumps({"chunker": chunker, "params": params}, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _file_name(chunker: dict, params: dict, chunk_content_sha256: str) -> str:
    return f"{overlay_key(chunker, params)}-{chunk_content_sha256[:16]}.json"


def overlay_path(store_path: Path, snapshot: str, chunker: dict,
                 chunk_content_sha256: str) -> Path:
    """Where the overlay of these chunks (by chunker, content and `PARAMS`) is."""
    return Path(store_path) / OVERLAY_DIR / snapshot / _file_name(chunker, PARAMS,
                                                                   chunk_content_sha256)


def missing(store_path: Path, snapshot: str, chunker: dict, chunk_content_sha256: str) -> str:
    """Why these chunks have no overlay: `NO_OVERLAY` when the snapshot has none, else a
    line naming the chunks' content and how many overlays there are for other chunks or
    settings (the remedy is the same: `adr dedup build`)."""
    others = sorted(p.name for p in (Path(store_path) / OVERLAY_DIR / snapshot).glob("*.json")
                    if p.name != _file_name(chunker, PARAMS, chunk_content_sha256))
    if not others:
        return NO_OVERLAY
    return (f"no dedup overlay for the index's chunks (content "
            f"{chunk_content_sha256[:12]}); {len(others)} overlay(s) of this snapshot are "
            f"for other chunks or settings; run `adr dedup build`")


def write_overlay(store_path: Path, overlay: DedupOverlay) -> tuple[str, Path]:
    """Write the overlay once; returns (overlay id, path). The same bytes again are a no-op,
    other bytes under the same name are refused."""
    path = Path(store_path) / OVERLAY_DIR / overlay.snapshot / _file_name(
        overlay.chunker, overlay.params, overlay.chunk_content_sha256)
    data = canonical_json(overlay)
    if path.exists():
        if path.read_bytes() != data:
            raise StoreError(f"{path} already holds a different dedup overlay for these chunks "
                             f"and parameters; it is not replaced")
    else:
        write_atomic(path, data)
    return hashlib.sha256(data).hexdigest(), path


def load_overlay(store_path: Path, snapshot: str, chunker: dict, chunk_content_sha256: str,
                 overlay_id: str | None = None) -> Dedup | None:
    """The dedup overlay of these chunks (by chunker, content and `PARAMS`), or None if there
    is none (`missing` says why). Refuses (StoreError) a file whose hash is not `overlay_id`
    (when given), that is not a valid canonical overlay, or that describes another snapshot,
    chunker, parameters or chunks than its name says."""
    path = overlay_path(store_path, snapshot, chunker, chunk_content_sha256)
    if not path.is_file():
        return None
    data = path.read_bytes()
    oid = hashlib.sha256(data).hexdigest()
    if overlay_id is not None and oid != overlay_id:
        raise StoreError(f"{path}: content hash {oid[:12]} is not the overlay id "
                         f"{overlay_id[:12]}")
    try:
        overlay = DedupOverlay.model_validate_json(data)
    except ValidationError as e:
        raise StoreError(f"{path}: not a valid dedup overlay (schema): "
                         f"{e.errors()[0]['msg']}") from e
    if canonical_json(overlay) != data:
        raise StoreError(f"{path}: not canonical JSON (sorted keys, compact, one newline)")
    if overlay.snapshot != snapshot:
        raise StoreError(f"{path}: describes snapshot {overlay.snapshot[:12]}, not "
                         f"{snapshot[:12]}")
    if overlay.chunker != chunker or overlay.params != PARAMS:
        raise StoreError(f"{path}: built with another chunker or other parameters than "
                         f"its name says")
    if overlay.chunk_content_sha256 != chunk_content_sha256:
        raise StoreError(f"{path}: built over other chunks (content "
                         f"{overlay.chunk_content_sha256[:12]}) than its name says (the "
                         f"index's {chunk_content_sha256[:12]})")
    return Dedup(oid, overlay)


class Dedup:
    """A loaded dedup overlay."""

    def __init__(self, overlay_id: str, overlay: DedupOverlay):
        self.overlay_id = overlay_id
        self.overlay = overlay
        self.clusters = {c.cluster_id: c for c in overlay.clusters}
        self._of = {m: c.cluster_id for c in overlay.clusters for m in c.members}

    def cluster_of(self, chunk_id: str) -> str | None:
        return self._of.get(chunk_id)

    def components(self, cluster_id: str, admitted: Callable[[str], bool]) -> list[list[str]]:
        """Connected components of the cluster's edges restricted to the admitted members."""
        return _restricted(self.clusters[cluster_id], admitted)


# -- canonical selection and collapse ----------------------------------------------------------

def _in_force(env: Envelope | None, as_of: date | None) -> bool:
    if env is None:
        return True
    if as_of is None:
        return env.superseded_by is None
    return (env.valid_from is not None and env.valid_from <= as_of
            and (env.valid_to is None or as_of < env.valid_to)
            and env.status != "proposed_rule")


def _canonical_key(cid: str, chunks: Mapping[str, StoreChunk],
                   applicability: Applicability | None, as_of: date | None) -> tuple:
    c = chunks[cid]
    env = None if applicability is None else applicability.records.get(c.doc_id)
    tier = None if env is None else env.authority_tier
    start = None if env is None else env.valid_from
    return (0 if _in_force(env, as_of) else 1,
            (1, 0) if tier is None else (0, tier),
            (1, 0) if start is None else (0, -start.toordinal()),
            c.doc_id, c.char_start, cid)


def canonical(members: list[str], chunks: Mapping[str, StoreChunk],
              applicability: Applicability | None, as_of: date | None) -> str:
    """The member shown for a cluster (spec §4.5): in force at the reference point (`as_of`,
    else the head of its chain), then the lower authority tier, then the later `valid_from`
    (nulls last), then the smaller doc id, then the smaller `char_start`."""
    return min(members, key=lambda m: _canonical_key(m, chunks, applicability, as_of))


@dataclass(frozen=True)
class Alternate:
    chunk_id: str
    doc_id: str
    kind: str  # "exact" or "near"
    jaccard: float  # to the shown member, 6 decimals


@dataclass(frozen=True)
class Slot:
    chunk_id: str  # the member shown
    score: float  # of the best-ranked member
    scored_by: str  # the best-ranked member
    alternates: tuple[Alternate, ...]


def collapse(ranked: Iterable[tuple[str, float]], dedup: Dedup,
             admitted: Callable[[str], bool], chunks: Mapping[str, StoreChunk],
             applicability: Applicability | None, as_of: date | None,
             top: int) -> list[Slot]:
    """At most `top` slots from `ranked` (best first; read only as far as needed), one per
    admitted component; members `admitted` rejects are never chosen, never listed and never
    join two components."""
    slots: list[Slot] = []
    taken: set[str] = set()
    comps: dict[str, list[list[str]]] = {}
    if top <= 0:
        return slots
    for cid, score in ranked:
        if cid in taken or not admitted(cid):
            continue
        slots.append(_slot(cid, score, dedup, admitted, comps, taken, chunks, applicability,
                           as_of))
        if len(slots) == top:  # not one item further: the rest may be costly to rank
            break
    return slots


def _slot(cid: str, score: float, dedup: Dedup, admitted: Callable[[str], bool],
          comps: dict[str, list[list[str]]], taken: set[str], chunks: Mapping[str, StoreChunk],
          applicability: Applicability | None, as_of: date | None) -> Slot:
    """The slot `cid` takes (its admitted component, now taken)."""
    cluster = dedup.cluster_of(cid)
    if cluster is None:
        taken.add(cid)
        return Slot(cid, score, cid, ())
    if cluster not in comps:
        comps[cluster] = dedup.components(cluster, admitted)
    comp = next(c for c in comps[cluster] if cid in c)
    taken.update(comp)
    order = sorted(comp, key=lambda m: _canonical_key(m, chunks, applicability, as_of))
    shown = order[0]
    text = chunks[shown].text
    sh = None
    alternates = []
    for m in order[1:]:
        if chunks[m].text == text:
            alternates.append(Alternate(m, chunks[m].doc_id, "exact", 1.0))
            continue
        sh = shingles(text) if sh is None else sh
        alternates.append(Alternate(m, chunks[m].doc_id, "near",
                                    _j6(jaccard(sh, shingles(chunks[m].text)))))
    return Slot(shown, score, cid, tuple(alternates))
