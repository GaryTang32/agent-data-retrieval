"""Phase 2 comparisons on hand-made rows: item subsets, slot counts, non-inferiority and the
identity check (Phase 2 spec §10.1, §13 A3-A6)."""

import hashlib
from datetime import date

import pytest

from adr_eval import phase2
from adr_eval.models import Evidence
from adr_eval.retrieval.chunker import Chunk
from adr_store import dedup as dedup_mod
from adr_store.applicability import Applicability, Envelope, Filters

A, B, F = "a" * 64, "b" * 64, "f" * 64  # A superseded by B (one chain); F a Federal Register doc


def env(doc_id, **kw) -> Envelope:
    base = dict(doc_id=doc_id, chain_id=None, version_label="1", supersedes=None,
                superseded_by=None, valid_from=None, valid_to=None, validity_basis="unknown",
                status="unknown", jurisdiction=None, issuer=None, authority_tier=None,
                provenance=[])
    return Envelope(**{**base, **kw})


APP = Applicability("o" * 64, "s" * 64, {
    A: env(A, chain_id="c", superseded_by=B, valid_from=date(2024, 1, 1),
           valid_to=date(2025, 1, 1), status="codified", validity_basis="ecfr_snapshot"),
    B: env(B, chain_id="c", supersedes=A, valid_from=date(2025, 1, 1), status="codified",
           validity_basis="ecfr_snapshot"),
    F: env(F, valid_from=date(2024, 3, 1), status="final_rule",
           validity_basis="fr_effective_on"),
})


def chunk(cid, doc, start, text) -> Chunk:
    return Chunk(cid, doc, start, start + len(text), text)


CHUNKS = {c.chunk_id: c for c in [
    chunk("a1", A, 0, "the same section text"),
    chunk("b1", B, 0, "the same section text"),
    chunk("a2", A, 100, "only in the old version"),
    chunk("f1", F, 0, "a federal register rule"),
    chunk("b2", B, 200, "another section of the head"),
]}


def dedup_of(*groups, edges=None) -> dedup_mod.Dedup:
    """Exact clusters of the given members, chained in sorted order unless `edges` given."""
    clusters = []
    for members in groups:
        members = sorted(members)
        clusters.append(dedup_mod.Cluster(
            cluster_id=hashlib.sha256("\n".join(members).encode()).hexdigest(),
            members=members, kind="exact", min_jaccard=1.0,
            edges=edges or [(i, i + 1, 1.0) for i in range(len(members) - 1)]))
    clusters.sort(key=lambda c: c.cluster_id)
    overlay = dedup_mod.DedupOverlay(format_version="0.1", snapshot="5" * 64, chunker={},
                                     chunk_content_sha256="c" * 64, params=dedup_mod.PARAMS,
                                     clusters=clusters, stats={})
    return dedup_mod.Dedup("d" * 64, overlay)


def ev(doc, start, end) -> Evidence:
    return Evidence(doc_id=doc, char_start=start, char_end=end, quote="x" * (end - start))


@pytest.fixture
def items(make_item):
    return [
        make_item(id="asof", qtype="policy_asof", as_of=date(2024, 6, 1),
                  evidence=[ev(A, 100, 110)]),
        make_item(id="inforce", evidence=[ev(B, 0, 5), ev(F, 0, 5)]),
        make_item(id="old", evidence=[ev(A, 100, 105)]),
        make_item(id="none", qtype="insufficient", evidence=[]),
    ]


GROUPS = {"inforce": [[ev(A, 0, 5), ev(B, 0, 5)], [ev(F, 0, 5)]], "old": [[ev(A, 100, 105)]],
          "asof": [[ev(A, 100, 110)]]}


def test_item_subsets(items):
    s = phase2.item_subsets(items, GROUPS, APP)
    assert s == {"asof": ["asof"], "in_force": ["inforce"], "superseded_only": ["old"],
                 "scored": ["asof", "inforce", "old"]}
    # without an overlay nothing is superseded
    assert phase2.item_subsets(items, GROUPS, None)["in_force"] == ["inforce", "old"]


def test_an_item_is_in_force_only_when_every_group_is(items, make_item):
    """One group with an in-force member and one whose only member is superseded: the item
    needs the old version, so it is superseded_only."""
    mixed = make_item(id="mixed", evidence=[ev(B, 0, 5), ev(A, 100, 105)])
    groups = {**GROUPS, "mixed": [[ev(B, 0, 5)], [ev(A, 100, 105)]]}
    s = phase2.item_subsets([*items, mixed], groups, APP)
    assert s["superseded_only"] == ["mixed", "old"] and s["in_force"] == ["inforce"]


def rows():
    return [
        {"item_id": "asof", "ranked": ["b1", "b2", "a2"], "as_of": None,
         "metrics": {"tokens@10": 8.0}},
        {"item_id": "inforce", "ranked": ["a1", "b1", "f1"], "metrics": {"tokens@10": 12.0}},
        {"item_id": "old", "ranked": ["b2"], "metrics": {"tokens@10": 4.0}},
        {"item_id": "none", "ranked": ["f1"], "metrics": None},
    ]


def test_slot_stats_in_the_phase1_view(items):
    s = phase2.slot_stats(rows(), CHUNKS, APP, dedup_of(["a1", "b1"]), items, GROUPS)
    assert set(s) == {"asof", "in_force", "superseded_only", "scored", "all"}
    f = s["in_force"]
    assert (f["n_items"], f["n_slots"], f["superseded_slots"]) == (1, 3, 1)
    # b1 is an exact copy of a1 ranked above it: one duplicate by text, cluster and component
    assert (f["exact_copy_slots"], f["duplicate_cluster_slots"], f["duplicate_slots"]) == \
        (1, 1, 1)
    assert f["duplicate_share"] == pytest.approx(1 / 3)
    assert f["evidence_groups_touched"] == 2 and f["tokens@10"] == 12.0
    a = s["asof"]
    # b1 and b2 (in force from 2025) and a2 (in force 2024-2025, superseded since): two slots
    # of the wrong version on 2024-06-01, one of a superseded document
    assert (a["wrong_version_slots"], a["wrong_version_share"]) == (2, pytest.approx(2 / 3))
    assert a["superseded_slots"] == 1 and a["evidence_groups_touched"] == 1
    assert s["superseded_only"]["evidence_groups_touched"] == 0
    assert s["in_force"]["wrong_version_slots"] is None  # no dated item in the subset
    assert s["all"]["n_items"] == 4 and s["all"]["n_slots"] == 8
    assert s["scored"]["tokens@10"] == pytest.approx(8.0)


def test_duplicate_slots_count_admitted_components_not_clusters(items):
    """Under the default filters a1 (superseded) is not admitted, so b1 is the first slot of
    its admitted component: no duplicate, though the cluster repeats."""
    rs = rows()
    s = phase2.slot_stats(rs, CHUNKS, APP, dedup_of(["a1", "b1"]), items, GROUPS,
                          filters=Filters())
    f = s["in_force"]
    assert (f["duplicate_slots"], f["duplicate_cluster_slots"]) == (0, 1)
    # a member that is not admitted does not bridge two admitted ones: a1-b1 and a1-b2
    bridged = dedup_of(["a1", "b1", "b2"], edges=[(0, 1, 1.0), (0, 2, 1.0)])
    rs[1]["ranked"] = ["b1", "b2"]
    s = phase2.slot_stats(rs, CHUNKS, APP, bridged, items, GROUPS, filters=Filters())
    assert (s["in_force"]["duplicate_slots"], s["in_force"]["duplicate_cluster_slots"]) == \
        (0, 1)
    # in the Phase 1 view a1 is admitted and joins them
    s = phase2.slot_stats(rs, CHUNKS, APP, bridged, items, GROUPS)
    assert s["in_force"]["duplicate_slots"] == 1
    # a dated row is admitted by its own as_of: on 2024-06-01 only a1 and a2 are in force
    rs[0].update(ranked=["a1", "b1"], as_of="2024-06-01")
    s = phase2.slot_stats(rs, CHUNKS, APP, dedup_of(["a1", "b1"]), items, GROUPS,
                          filters=Filters())
    assert (s["asof"]["duplicate_slots"], s["asof"]["duplicate_cluster_slots"]) == (0, 1)


def test_a_dated_row_is_counted_in_the_view_of_its_own_as_of(items):
    """a1 (superseded, in force 2024-2025) and f1 (in force from 2024-03): under the run's
    default filters only f1 is admitted, on the row's 2024-06-01 both are, so they share a
    component and the second is a duplicate."""
    rs = rows()
    rs[0].update(ranked=["a1", "f1"], as_of="2024-06-01")
    dd = dedup_of(["a1", "f1"])
    dated = phase2.slot_stats(rs, CHUNKS, APP, dd, items, GROUPS, filters=Filters())
    assert dated["asof"]["duplicate_slots"] == 1
    rs[0]["as_of"] = None  # the same ranking counted in the run's default view
    plain = phase2.slot_stats(rs, CHUNKS, APP, dd, items, GROUPS, filters=Filters())
    assert plain["asof"]["duplicate_slots"] == 0


def test_slot_stats_without_overlays_report_none(items):
    s = phase2.slot_stats(rows(), CHUNKS, None, None, items, GROUPS)["all"]
    assert s["superseded_slots"] is None and s["duplicate_slots"] is None
    assert s["wrong_version_slots"] is None and s["exact_copy_slots"] == 1


def metric_rows(values: dict[str, float]) -> list[dict]:
    return [{"item_id": i, "metrics": {"recall@10": v, "ndcg@10": v, "mrr": v}}
            for i, v in values.items()]


def test_noninferiority_passes_above_minus_the_margin_and_fails_below():
    ids = [f"i{k}" for k in range(20)]
    a = metric_rows(dict.fromkeys(ids, 0.5))
    same = phase2.noninferiority(a, a, ids)
    assert same["pass"] is True and same["n"] == 20 and same["margin"] == 0.02
    assert set(same["keys"]) == {"recall@10", "ndcg@10", "mrr"}
    assert same["keys"]["ndcg@10"]["ci95"] == [0.0, 0.0]
    assert (same["n_resamples"], same["seed"]) == (10_000, 20261108)
    worse = phase2.noninferiority(a, metric_rows(dict.fromkeys(ids, 0.45)), ids)
    assert worse["pass"] is False and worse["keys"]["recall@10"]["mean_diff"] == \
        pytest.approx(-0.05)
    slightly = phase2.noninferiority(a, metric_rows(dict.fromkeys(ids, 0.49)), ids)
    assert slightly["pass"] is True  # -0.01 > -0.02
    # MRR alone does not decide the verdict (A3 and A4 name Recall@10 and nDCG@10)
    b = metric_rows(dict.fromkeys(ids, 0.5))
    for r in b:
        r["metrics"]["mrr"] = 0.1
    mixed = phase2.noninferiority(a, b, ids)
    assert mixed["keys"]["mrr"]["pass"] is False and mixed["pass"] is True
    # differences that vary: the verdict is the lower bound's, not the mean's or the upper
    # bound's (the interval straddles -margin, so it fails)
    spread = metric_rows({i: 0.5 + (0.09 if k % 2 else -0.11) for k, i in enumerate(ids)})
    wide = phase2.noninferiority(a, spread, ids)
    lo, hi = wide["keys"]["recall@10"]["ci95"]
    assert lo < -0.02 < hi and wide["keys"]["recall@10"]["mean_diff"] == pytest.approx(-0.01)
    assert wide["keys"]["recall@10"]["pass"] is False and wide["pass"] is False
    assert phase2.noninferiority(a, a, [])["pass"] is None
    with pytest.raises(Exception, match="lack metrics"):
        phase2.noninferiority(a, a, ["missing"])


def run(rows_) -> dict:
    return {"rows": [{"item_id": i, "ranked": [c for c, _ in hits],
                      "scores": [s for _, s in hits]} for i, hits in rows_.items()]}


def test_identical_requires_the_same_items_ids_and_exact_scores():
    base = {"x": [("c1", 1.0), ("c2", 0.5)], "y": [("c3", 0.25)]}
    assert phase2.identical(run(base), run(base))["identical"] is True
    r = phase2.identical(run(base), run({**base, "x": [("c1", 1.0), ("c2", 0.5000001)]}))
    assert r["identical"] is False and r["n_differing"] == 1
    assert r["differences"][0] == {"item_id": "x", "rank": 2, "a": ["c2", 0.5],
                                   "b": ["c2", 0.5000001], "len_a": 2, "len_b": 2}
    r = phase2.identical(run(base), run({**base, "y": []}))
    assert r["differences"][0]["rank"] == 1 and r["differences"][0]["b"] is None
    r = phase2.identical(run(base), run({"x": base["x"]}))
    assert r["identical"] is False and r["only_a"] == ["y"] and r["n_differing"] == 0
