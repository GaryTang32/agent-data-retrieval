"""B1 through the MCP server (Phase 2 spec §10.2, §12 MCP; plan Task 13 step 1): a seeded
subset of the leak probes, each run through an `adr mcp` server process of its caller and
judged exactly as the Python-API probes are (`adr_eval.probes.acl.check` and `check_tool`).

**Universe.** The leak probes of every store, built as the API run builds them: the content
families of `acl.leak_probes` (search-rare, search-title, grep-literal, grep-doc, read and
alternate-cross-view) for each content store, and the tool families of
`acl.tool_leak_probes` (tool-search, tool-load) for the tool store. A probe's global id is
`<label>/<probe_id>` (label: the corpus, or `tools`). On the Phase 2 stores this is 853
content and 200 tool probes, 1,053 in all. The fail-closed probes are not leak probes and
are not sampled.

**Selection** (`select`): the `n` (300) probes with the lowest SHA-256 of
`"<seed>:<label>/<probe_id>"` (seed 20261116), in that order. Nothing forces a family's share:
`family_counts` reports each family's count, at the level of the probe families and at the
level of the spec's four tool families (search, grep, read, search_tools/load_tool), and
`short_families` names any spec family with fewer than `MIN_PER_FAMILY` (20).

**Running** (`run_subset`): one server per (store, caller), started with
`adr_store.mcp_client.McpTools` (`python -m adr_store.cli mcp --store S --as CALLER`), used for
that caller's probes and stopped; `user:ghost` gets a server too (the server validates only
that a caller is given; F4 is decided per call). Content probes are judged against the
caller's reference store, through the Python API (`reference_for`), so the count and score
kinds compare what MCP returns with an allowed-only store; tool probes against
`ToolContext.reference`. `CountingTools` counts the calls made through MCP, so the log lines
the servers wrote can be checked against them (B5: a call the server's input schema rejects
never reaches `Tools` and is not logged; the probes make no such call).

This module may import `adr_store` directly (plan, shared rules).
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable

from adr_eval.probes import SEED
from adr_eval.probes import acl as acl_probes

SUBSET = 300
MIN_PER_FAMILY = 20
TOOLS_LABEL = "tools"
SPEC_FAMILY = {"search-rare": "search", "search-title": "search",
               "alternate-cross-view": "search", "grep-literal": "grep", "grep-doc": "grep",
               "read": "read", "tool-search": "search_tools/load_tool",
               "tool-load": "search_tools/load_tool"}
SPEC_FAMILIES = ("search", "grep", "read", "search_tools/load_tool")


def global_id(label: str, probe_id: str) -> str:
    return f"{label}/{probe_id}"


def sample_key(label: str, probe_id: str, seed: int = SEED) -> str:
    """The selection key of a probe: SHA-256 of `"<seed>:<label>/<probe_id>"` (hex)."""
    return hashlib.sha256(f"{seed}:{global_id(label, probe_id)}".encode()).hexdigest()


def select(universe: list[tuple[str, acl_probes.Probe]], n: int = SUBSET,
           seed: int = SEED) -> list[tuple[str, acl_probes.Probe]]:
    """The `n` probes of `universe` ((label, probe) pairs) with the lowest sample key, in
    key order. Global ids must be unique."""
    ids = [global_id(label, p.probe_id) for label, p in universe]
    if len(set(ids)) != len(ids):
        raise ValueError("two probes share a global id")
    return sorted(universe, key=lambda lp: sample_key(lp[0], lp[1].probe_id, seed))[:n]


def family_counts(probes: list[tuple[str, acl_probes.Probe]]) -> dict:
    """Counts by probe family, by spec family and by store label."""
    return {"families": dict(sorted(Counter(p.family for _, p in probes).items())),
            "spec_families": {f: sum(SPEC_FAMILY[p.family] == f for _, p in probes)
                              for f in SPEC_FAMILIES},
            "stores": dict(sorted(Counter(label for label, _ in probes).items()))}


def short_families(counts: dict, minimum: int = MIN_PER_FAMILY) -> dict:
    """The spec families with fewer than `minimum` probes (empty when none)."""
    return {f: k for f, k in counts["spec_families"].items() if k < minimum}


class CountingTools:
    """A `Tools`-shaped object that forwards to `inner` and counts the calls."""

    METHODS = ("search", "grep", "read", "search_tools", "load_tool")

    def __init__(self, inner):
        self.inner = inner
        self.calls: Counter = Counter()

    def __getattr__(self, name: str):
        attr = getattr(self.inner, name)
        if name not in self.METHODS:
            return attr

        def call(*args, **kwargs):
            self.calls[name] += 1
            return attr(*args, **kwargs)

        return call


def run_subset(selected: list[tuple[str, acl_probes.Probe]], *, contexts: dict,
               reference_for: Callable[[str, str], object],
               make_server: Callable[[str, str | None], object]
               ) -> tuple[list[tuple[str, acl_probes.ProbeResult]], dict]:
    """Run the selected probes through MCP (module docstring); (one (label, result) per
    probe in `selected` order, the calls made per label and tool). `contexts[label]` is the
    store's `acl.Context` or `acl.ToolContext`; `reference_for(label, caller)` the caller's
    reference Tools for a content store (None outside the directory); `make_server(label,
    caller)` a started server's Tools-shaped client (closed here after the caller's
    probes)."""
    groups: dict[tuple[str, str | None], list[int]] = {}
    for i, (label, p) in enumerate(selected):
        groups.setdefault((label, p.caller), []).append(i)
    results: dict[int, acl_probes.ProbeResult] = {}
    calls: dict[str, Counter] = {}
    for (label, caller), idxs in sorted(groups.items(), key=lambda kv: (kv[0][0],
                                                                        str(kv[0][1]))):
        ctx = contexts[label]
        server = make_server(label, caller)
        counted = CountingTools(server)
        try:
            for i in idxs:
                p = selected[i][1]
                if isinstance(ctx, acl_probes.ToolContext):
                    results[i] = acl_probes.check_tool(p, lambda c, t=counted: t, ctx)
                else:
                    results[i] = acl_probes.check(
                        p, lambda c, t=counted: t, lambda c, lb=label: reference_for(lb, c),
                        ctx)
        finally:
            close = getattr(server, "close", None)
            if close is not None:
                close()
        calls.setdefault(label, Counter()).update(counted.calls)
    return ([(selected[i][0], results[i]) for i in range(len(selected))],
            {k: dict(sorted(v.items())) for k, v in sorted(calls.items())})


def summarize(results: list[tuple[str, acl_probes.ProbeResult]]) -> dict:
    """`acl.summarize` over all results, plus per spec family and per store."""
    out = acl_probes.summarize([r for _, r in results])
    out["spec_families"] = {
        f: {"n": sum(SPEC_FAMILY[r.family] == f for _, r in results),
            "leaks": sum(r.leak for _, r in results if SPEC_FAMILY[r.family] == f),
            "invalid": sum(not r.valid for _, r in results if SPEC_FAMILY[r.family] == f)}
        for f in SPEC_FAMILIES}
    out["stores"] = {label: {"n": sum(lb == label for lb, _ in results),
                             "leaks": sum(r.leak for lb, r in results if lb == label),
                             "invalid": sum(not r.valid for lb, r in results if lb == label)}
                     for label in sorted({lb for lb, _ in results})}
    return out
