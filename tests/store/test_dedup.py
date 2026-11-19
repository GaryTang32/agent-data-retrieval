"""The dedup overlay and query-time collapse (Phase 2 spec §4.5, §12 Dedup): exact SHA-256
groups, MinHash/LSH near duplicates verified by exact Jaccard, canonical selection and collapse
over the members the caller's filters admit. Fixture chunks and gov-shaped fixture stores,
lexical-only indexes; nothing reads `data/` or `.cache/`."""

import dataclasses
import hashlib
import json
import random
import re
from datetime import date

import numpy as np
import pytest

from adr_eval.retrieval import fusion
from adr_eval.retrieval.chunker import make_chunk_id
from adr_store import applicability as ap
from adr_store import dedup, records, tools
from adr_store.applicability import Applicability
from adr_store.chunking import StoreChunk, chunker_config
from adr_store.cli import main
from adr_store.dedup import Alternate, Dedup, Slot
from adr_store.records import canonical_json, sha256_text
from adr_store.retrieval import StoreIndex
from adr_store.retrieval import index as index_mod
from adr_store.retrieval.index import CHANNEL_K, chunk_content_sha256
from adr_store.store import StoreError
from tests.store.test_applicability import ALL, GOV_CONFIG, V2024, V2025, V2026, doc_id, env
from tests.store.test_applicability import make_store as make_gov_store
from tests.store.test_chunking import doc
from tests.store.test_retrieval import fake_cache, fake_reranker

CHUNKER = chunker_config()
SNAP = "5" * 64
WORDS = [f"w{i:03d}" for i in range(400)]


def text(words) -> str:
    return " ".join(words)


BASE = WORDS[:100]
# Jaccard of their 5-shingle sets: BASE~ONE_END 95/97, BASE~MID 91/101, MID~MID2 91/101,
# BASE~MID2 86/106 (below 0.90)
ONE_END = BASE[:99] + ["x999"]
MID = BASE[:30] + ["x030"] + BASE[31:]
MID2 = MID[:70] + ["x070"] + MID[71:]
SHORT_FAR = WORDS[:30] + ["x015"] + WORDS[31:60]  # vs WORDS[:60]: 51/61


def chunk(doc_ch: str, start: int, body: str) -> StoreChunk:
    d = doc_ch * 64
    return StoreChunk(make_chunk_id(d, start, start + len(body)), d, start, start + len(body),
                      body, "Part > Section", ())


def by_id(chunks) -> dict[str, StoreChunk]:
    return {c.chunk_id: c for c in chunks}


def build(chunks) -> dedup.DedupOverlay:
    return dedup.build(list(chunks), SNAP, CHUNKER)


def loaded(overlay) -> Dedup:
    return Dedup(hashlib.sha256(canonical_json(overlay)).hexdigest(), overlay)


def sha_groups(chunks) -> set[tuple[str, ...]]:
    groups: dict[str, list[str]] = {}
    for c in chunks:
        groups.setdefault(sha256_text(c.text), []).append(c.chunk_id)
    return {tuple(sorted(g)) for g in groups.values() if len(g) > 1}


# -- shingles, MinHash, Jaccard --------------------------------------------------------------


def test_shingles_are_five_lower_cased_words_joined_by_one_space():
    assert dedup.shingles("A b, C-d\ne F") == frozenset({"a b c d e", "b c d e f"})
    assert dedup.shingles("Only four words here") == frozenset({"only four words here"})
    assert dedup.shingles("  ... ") == frozenset({""})
    assert len(dedup.shingles(text(BASE))) == 96


def test_the_parameters_are_the_spec_s_and_recorded():
    assert dedup.PARAMS == {
        "exact": "sha256(text)", "tokens": r"\w+", "lower": True, "shingle": 5,
        "num_perm": 128, "prime": 4294967311, "seed": 20261116, "a_range": [1, 2**32],
        "b_range": [0, 2**32], "bands": 16, "rows": 8, "threshold": 0.90}
    ov = build([chunk("a", 0, text(BASE))])
    assert ov.params == dedup.PARAMS and ov.chunker == CHUNKER


def reference_minhash(body: str) -> list[int]:
    """A pure-Python reference loop of the spec's hash family."""
    words = [t.lower() for t in re.findall(r"\w+", body)]
    sh = ({" ".join(words)} if len(words) < 5 else
          {" ".join(words[i:i + 5]) for i in range(len(words) - 4)})
    rng = random.Random(20261116)
    family = [(rng.randrange(1, 2**32), rng.randrange(0, 2**32)) for _ in range(128)]
    hs = [int.from_bytes(hashlib.sha256(s.encode("utf-8")).digest()[:4], "big") for s in sh]
    return [min((a * h + b) % 4294967311 for h in hs) for a, b in family]


PINNED = [  # (text, first four values, SHA-256 of the 128 values as 8-byte big-endian)
    ("The vessel shall carry one approved life jacket for each person on board.",
     [147584441, 450551914, 401076820, 100244712],
     "448444ebcfc79d0a90f4df9971a1c375342aec571e25e260ea3c8d426fa2d3b3"),
    ("Short text", [2524848906, 2954199896, 4111512557, 901742481],
     "9a35d048b5b730f29bda43fe8c5db87c0f922f5581cc6e4471e7b6946afdc808"),
    ("", [1568091977, 685817238, 3160198352, 4294615591],
     "ec91029897806baff3ca8050a1f67a9ad2de3810266175cebd49378ab0b8e7f8"),
]


@pytest.mark.parametrize("body,first,digest", PINNED)
def test_minhash_is_fixed_by_its_seed(body, first, digest):
    sig = dedup.minhash(dedup.shingles(body))
    assert sig.dtype == np.uint64 and sig.shape == (128,)
    values = [int(v) for v in sig]
    assert values == reference_minhash(body)
    assert values[:4] == first
    assert hashlib.sha256(b"".join(v.to_bytes(8, "big") for v in values)).hexdigest() == digest


def test_jaccard_is_exact_on_the_shingle_sets():
    s = dedup.shingles
    assert dedup.jaccard(s(text(BASE)), s(text(ONE_END))) == 95 / 97
    assert dedup.jaccard(s(text(BASE)), s(text(MID2))) == 86 / 106
    assert dedup.jaccard(s(""), s("")) == 1.0
    # the threshold is inclusive: 9 of 10 shingles shared
    a, b = s(text(WORDS[:14])), s(text(WORDS[:13]))
    assert dedup.jaccard(a, b) == 0.9 and dedup.qualifies(a, b)


# -- clusters ---------------------------------------------------------------------------------


def test_exact_clusters_equal_the_sha256_groups():
    t1, t2, t3 = text(WORDS[:50]), text(WORDS[100:160]), text(WORDS[200:240])
    chunks = [chunk("a", 0, t1), chunk("b", 0, t1), chunk("c", 7, t1), chunk("a", 900, t2),
              chunk("d", 0, t2), chunk("e", 0, t3), chunk("f", 0, text(WORDS[300:350]))]
    ov = build(chunks)
    assert {tuple(c.members) for c in ov.clusters} == sha_groups(chunks)
    assert all(c.kind == "exact" and c.min_jaccard == 1.0 for c in ov.clusters)
    three = next(c for c in ov.clusters if len(c.members) == 3)
    assert three.edges == [(0, 1, 1.0), (0, 2, 1.0), (1, 2, 1.0)]
    assert three.cluster_id == hashlib.sha256("\n".join(three.members).encode()).hexdigest()
    assert ov.stats["exact_clusters"] == 2 and ov.stats["exact_chunks"] == 5
    assert ov.stats["exact_redundant"] == 3 and ov.stats["redundant"] == 3
    assert ov.stats["chunks"] == 7 and ov.stats["near_pairs"] == 0


def test_a_near_cluster_holds_its_exact_members_and_every_qualifying_edge():
    chunks = [chunk("a", 0, text(BASE)), chunk("b", 0, text(BASE)), chunk("c", 0, text(ONE_END)),
              chunk("d", 0, text(WORDS[200:300]))]
    ov = build(chunks)
    (cl,) = ov.clusters
    assert cl.kind == "near" and cl.members == sorted(c.chunk_id for c in chunks[:3])
    idx = {cid: i for i, cid in enumerate(cl.members)}
    a, b, c = (idx[x.chunk_id] for x in chunks[:3])
    j = round(95 / 97, 6)
    assert cl.edges == sorted([tuple(sorted((a, b))) + (1.0,), tuple(sorted((a, c))) + (j,),
                               tuple(sorted((b, c))) + (j,)])
    assert cl.min_jaccard == j
    assert ov.stats["exact_clusters"] == 1 and ov.stats["near_text_pairs"] == 1
    assert ov.stats["near_pairs"] == 2 and ov.stats["clusters"] == 1
    assert ov.stats["redundant"] == 2


def test_every_candidate_pair_is_verified(monkeypatch):
    # every signature equal: LSH makes every pair of distinct texts a candidate
    monkeypatch.setattr(dedup, "minhash", lambda sh: np.zeros(128, dtype=np.uint64))
    chunks = [chunk("a", 0, text(WORDS[:60])), chunk("b", 0, text(SHORT_FAR)),
              chunk("c", 0, text(BASE)), chunk("d", 0, text(ONE_END)),
              chunk("e", 0, text(WORDS[200:300]))]
    ov = build(chunks)
    assert ov.stats["candidate_pairs"] == 10  # all pairs of the five texts collided
    assert ov.stats["verified_candidates"] == 1 and ov.stats["rejected_candidates"] == 9
    # only the pair at or above 0.90 is linked; 51/61 is not
    assert [sorted(cl.members) for cl in ov.clusters] == [
        sorted([chunks[2].chunk_id, chunks[3].chunk_id])]


def test_clusters_are_connected_components_and_a_below_threshold_pair_is_no_edge():
    a, b, c = chunk("a", 0, text(BASE)), chunk("b", 0, text(MID)), chunk("c", 0, text(MID2))
    (cl,) = build([a, b, c]).clusters
    assert cl.kind == "near" and len(cl.members) == 3
    pairs = {frozenset((cl.members[i], cl.members[j])) for i, j, _ in cl.edges}
    assert pairs == {frozenset((a.chunk_id, b.chunk_id)), frozenset((b.chunk_id, c.chunk_id))}
    assert cl.min_jaccard == round(91 / 101, 6)


def test_a_rebuild_is_byte_identical_and_independent_of_input_order():
    chunks = [chunk("a", 0, text(BASE)), chunk("b", 0, text(BASE)), chunk("c", 0, text(MID)),
              chunk("d", 0, text(WORDS[200:260]))]
    one = canonical_json(build(chunks))
    assert canonical_json(build(chunks)) == one
    assert canonical_json(build(list(reversed(chunks)))) == one


# -- canonical selection ----------------------------------------------------------------------

DA, DB = "a" * 64, "b" * 64


def overlay_of(**envs) -> Applicability:
    recs = {d: env(doc_id=d, **kw) for d, kw in envs.items()}
    return Applicability("o" * 64, SNAP, recs)


def two():
    a, b = chunk("a", 0, text(BASE)), chunk("b", 0, text(BASE))
    return [a.chunk_id, b.chunk_id], by_id([a, b])


def test_canonical_rule_1_in_force_at_the_reference_point():
    members, chunks = two()
    # a: superseded, but lower tier and later valid_from and smaller doc id
    app = overlay_of(**{DA: dict(superseded_by="e" * 64, authority_tier=1,
                                 valid_from=date(2026, 1, 1)),
                        DB: dict(authority_tier=2, valid_from=date(2020, 1, 1))})
    assert dedup.canonical(members, chunks, app, None) == members[1]
    # under as_of the dates decide, not the chain: b (superseded, an older version, a higher
    # tier, a larger doc id) is the one in force on 2022-06-01; a, the head, starts in 2025
    app = overlay_of(**{DA: dict(valid_from=date(2025, 1, 1), authority_tier=1,
                                 status="codified"),
                        DB: dict(superseded_by=DA, valid_from=date(2020, 1, 1),
                                 valid_to=date(2025, 1, 1), authority_tier=2,
                                 status="codified")})
    assert dedup.canonical(members, chunks, app, date(2022, 6, 1)) == members[1]
    assert dedup.canonical(members, chunks, app, date(2026, 6, 1)) == members[0]
    assert dedup.canonical(members, chunks, app, None) == members[0]
    # a proposal is never in force, even with the lower tier and the smaller doc id
    app = overlay_of(**{DA: dict(valid_from=date(2025, 1, 1), status="proposed_rule",
                                 authority_tier=1),
                        DB: dict(valid_from=date(2025, 1, 1), status="final_rule",
                                 authority_tier=4)})
    assert dedup.canonical(members, chunks, app, date(2026, 6, 1)) == members[1]


def test_canonical_rule_2_lower_tier_null_last():
    members, chunks = two()
    app = overlay_of(**{DA: dict(authority_tier=2, valid_from=date(2026, 1, 1)),
                        DB: dict(authority_tier=1, valid_from=date(2020, 1, 1))})
    assert dedup.canonical(members, chunks, app, None) == members[1]
    app = overlay_of(**{DA: dict(authority_tier=None, valid_from=date(2026, 1, 1)),
                        DB: dict(authority_tier=4)})
    assert dedup.canonical(members, chunks, app, None) == members[1]


def test_canonical_rule_3_later_valid_from_null_last():
    members, chunks = two()
    app = overlay_of(**{DA: dict(authority_tier=2, valid_from=date(2020, 1, 1)),
                        DB: dict(authority_tier=2, valid_from=date(2021, 1, 1))})
    assert dedup.canonical(members, chunks, app, None) == members[1]
    app = overlay_of(**{DA: dict(authority_tier=2), DB: dict(authority_tier=2,
                                                             valid_from=date(1990, 1, 1))})
    assert dedup.canonical(members, chunks, app, None) == members[1]


def test_canonical_rule_4_smaller_doc_id_then_smaller_char_start():
    members, chunks = two()
    app = overlay_of(**{DA: dict(authority_tier=2), DB: dict(authority_tier=2)})
    assert dedup.canonical(members[::-1], chunks, app, None) == members[0]
    assert dedup.canonical(members[::-1], chunks, None, None) == members[0]  # no overlay
    late, early = chunk("a", 500, text(BASE)), chunk("a", 100, text(BASE))
    assert dedup.canonical([late.chunk_id, early.chunk_id], by_id([late, early]), app,
                           None) == early.chunk_id


# -- collapse ---------------------------------------------------------------------------------


def test_collapse_shows_the_canonical_member_with_the_best_ranked_score():
    a, b, c = chunk("a", 0, text(BASE)), chunk("b", 0, text(BASE)), chunk("c", 0, text(ONE_END))
    other = chunk("d", 0, text(WORDS[200:300]))
    chunks = by_id([a, b, c, other])
    dd = loaded(build(chunks.values()))
    ranked = [(c.chunk_id, 9.0), (other.chunk_id, 5.0), (b.chunk_id, 4.0), (a.chunk_id, 4.0)]
    slots = dedup.collapse(ranked, dd, lambda cid: True, chunks, None, None, top=10)
    assert [s.chunk_id for s in slots] == [a.chunk_id, other.chunk_id]
    first = slots[0]
    assert first.score == 9.0 and first.scored_by == c.chunk_id
    assert first.alternates == (
        Alternate(b.chunk_id, b.doc_id, "exact", 1.0),
        Alternate(c.chunk_id, c.doc_id, "near", round(95 / 97, 6)))
    assert slots[1] == Slot(other.chunk_id, 5.0, other.chunk_id, ())
    assert dedup.collapse(ranked, dd, lambda cid: True, chunks, None, None, top=1) == slots[:1]


def test_collapse_never_shows_or_lists_a_member_the_caller_may_not_see():
    a, b, c = chunk("a", 0, text(BASE)), chunk("b", 0, text(MID)), chunk("c", 0, text(MID2))
    chunks = by_id([a, b, c])
    dd = loaded(build(chunks.values()))
    ranked = [(a.chunk_id, 3.0), (b.chunk_id, 2.0), (c.chunk_id, 1.0)]
    every = dedup.collapse(ranked, dd, lambda cid: True, chunks, None, None, top=10)
    assert len(every) == 1 and {x.chunk_id for x in every[0].alternates} | {
        every[0].chunk_id} == set(chunks)
    # b hidden: it was the only bridge between a and c, which are now two slots
    hidden = b.chunk_id

    def admitted(cid):
        return cid != hidden

    slots = dedup.collapse(ranked, dd, admitted, chunks, None, None, top=10)
    assert [s.chunk_id for s in slots] == [a.chunk_id, c.chunk_id]
    assert all(s.alternates == () for s in slots)
    assert dd.components(dd.cluster_of(a.chunk_id), admitted) == sorted(
        [[a.chunk_id], [c.chunk_id]])
    for s in slots:
        assert hidden not in {s.chunk_id, s.scored_by} | {x.chunk_id for x in s.alternates}


def test_collapse_shows_one_slot_per_admitted_component():
    bodies = [text(BASE), text(BASE), text(ONE_END), text(MID), text(WORDS[200:300]),
              text(WORDS[200:300]), text(WORDS[300:400])]
    chunks = by_id(chunk(ch, 0, body) for ch, body in zip("abcdefg", bodies, strict=True))
    dd = loaded(build(chunks.values()))
    rng = random.Random(7)
    ids = sorted(chunks)
    for _ in range(50):
        ranked = [(cid, float(rng.randint(1, 5))) for cid in rng.sample(ids, len(ids))]
        ranked.sort(key=lambda h: (-h[1], h[0]))
        hidden = set(rng.sample(ids, rng.randint(0, 3)))

        def admitted(cid, hidden=hidden):
            return cid not in hidden

        slots = dedup.collapse([h for h in ranked if admitted(h[0])], dd, admitted, chunks,
                               None, None, top=10)
        shown = [s.chunk_id for s in slots]
        listed = [x.chunk_id for s in slots for x in s.alternates]
        assert not hidden & (set(shown) | set(listed))
        assert len(set(shown + listed)) == len(shown + listed)  # no chunk twice
        keys = [tuple(next(comp for comp in dd.components(dd.cluster_of(cid), admitted)
                           if cid in comp)) if dd.cluster_of(cid) else (cid,) for cid in shown]
        assert len(keys) == len(set(keys))  # never two members of one admitted component


def test_collapse_under_as_of_shows_the_version_in_force_when_both_are_admitted():
    """Two versions of one chain in one component, both admitted (as include_superseded
    admits them): under as_of the one in force is shown, though the head has the later
    valid_from; without as_of the head is."""
    members, chunks = two()
    old, head = members[1], members[0]  # b is the old version, a the head
    app = overlay_of(**{DA: dict(valid_from=date(2025, 1, 1), status="codified",
                                 authority_tier=1),
                        DB: dict(superseded_by=DA, valid_from=date(2020, 1, 1),
                                 valid_to=date(2025, 1, 1), status="codified",
                                 authority_tier=1)})
    dd = loaded(build(chunks.values()))
    ranked = [(head, 2.0), (old, 1.0)]
    (slot,) = dedup.collapse(ranked, dd, lambda cid: True, chunks, app, date(2022, 6, 1), 10)
    assert (slot.chunk_id, slot.scored_by) == (old, head)
    assert [x.chunk_id for x in slot.alternates] == [head]
    (slot,) = dedup.collapse(ranked, dd, lambda cid: True, chunks, app, None, 10)
    assert slot.chunk_id == head


def test_collapse_skips_a_ranked_chunk_that_is_not_admitted():
    a, b = chunk("a", 0, text(BASE)), chunk("b", 0, text(WORDS[200:300]))
    chunks = by_id([a, b])
    dd = loaded(build(chunks.values()))
    slots = dedup.collapse([(a.chunk_id, 2.0), (b.chunk_id, 1.0)], dd,
                           lambda cid: cid != a.chunk_id, chunks, None, None, top=10)
    assert [s.chunk_id for s in slots] == [b.chunk_id]


# -- files ------------------------------------------------------------------------------------


@pytest.fixture
def gov(tmp_path):
    """A gov-shaped store (three eCFR versions sharing most chunks) plus two loose documents
    that are near duplicates, with its applicability overlay and an active lexical index."""
    para = text(BASE)
    near = [doc(f"# Guide {n}\n\n{body}\n".encode(), "md", f"file://guide-{n}.md")
            for n, body in (("one", para), ("two", text(ONE_END)))]
    s = make_gov_store(tmp_path / "store", [*ALL, *near])
    overlay, _ = ap.derive(s, GOV_CONFIG)
    ap.write_overlay(s.path, overlay)
    tools.Tools(s.path).index("p1-struct", lexical_only=True)
    return s


def active_index(store) -> StoreIndex:
    return tools.Tools(store.path).active_index()


def build_for(store) -> tuple[str, dedup.DedupOverlay]:
    idx = active_index(store)
    ov = dedup.build(list(idx.chunks.values()), idx.snapshot, idx.chunker)
    oid, _ = dedup.write_overlay(store.path, ov)
    return oid, ov


def opath(store):
    """The dedup overlay path of the store's active index's chunks."""
    idx = active_index(store)
    return dedup.overlay_path(store.path, store.snapshot_id, idx.chunker,
                              chunk_content_sha256(idx.chunks.values()))


def test_write_once_load_and_refusals(gov):
    idx = active_index(gov)
    content = chunk_content_sha256(idx.chunks.values())
    assert dedup.load_overlay(gov.path, gov.snapshot_id, idx.chunker, content) is None
    oid, ov = build_for(gov)
    path = opath(gov)
    assert path == (gov.path / "dedup" / gov.snapshot_id /
                    f"{dedup.overlay_key(idx.chunker, dedup.PARAMS)}-{content[:16]}.json")
    assert path.read_bytes() == canonical_json(ov)
    assert oid == hashlib.sha256(path.read_bytes()).hexdigest()
    assert dedup.write_overlay(gov.path, ov) == (oid, path)  # the same bytes: a no-op
    assert ov.chunk_content_sha256 == content and ov.snapshot == gov.snapshot_id
    got = dedup.load_overlay(gov.path, gov.snapshot_id, idx.chunker, content, overlay_id=oid)
    assert got.overlay_id == oid
    with pytest.raises(StoreError, match="overlay id"):
        dedup.load_overlay(gov.path, gov.snapshot_id, idx.chunker, content, overlay_id="0" * 64)
    # other chunks (a rechunked index): another file name, so no overlay for them yet
    assert dedup.load_overlay(gov.path, gov.snapshot_id, idx.chunker, "0" * 64) is None
    other = ov.model_copy(update={"stats": {**ov.stats, "chunks": 0}})
    with pytest.raises(StoreError, match="different"):
        dedup.write_overlay(gov.path, other)
    assert path.read_bytes() == canonical_json(ov)


@pytest.mark.parametrize("damage,match", [
    (lambda d: {**d, "snapshot": "6" * 64}, "snapshot"),
    (lambda d: {**d, "params": {**d["params"], "threshold": 0.8}}, "parameters"),
    (lambda d: {**d, "chunk_content_sha256": "8" * 64}, "other chunks"),
    (lambda d: {**d, "clusters": [{**d["clusters"][0], "cluster_id": "7" * 64}]}, "schema"),
    (lambda d: {**d, "clusters": [{**d["clusters"][0], "edges": []}]}, "schema"),
    (lambda d: {**d, "clusters": [d["clusters"][0], d["clusters"][0]]}, "schema"),
    (lambda d: {**d, "extra": 1}, "schema"),
])
def test_load_refuses_a_damaged_overlay(gov, damage, match):
    _, ov = build_for(gov)
    idx = active_index(gov)
    path = opath(gov)
    data = json.loads(path.read_bytes())
    path.write_bytes((json.dumps(damage(data), sort_keys=True, separators=(",", ":"))
                      + "\n").encode())
    with pytest.raises(StoreError, match=match):
        dedup.load_overlay(gov.path, gov.snapshot_id, idx.chunker, ov.chunk_content_sha256)


def test_an_overlay_of_other_chunks_under_this_name_names_both_hashes_and_a_fix(gov, capsys):
    """The refusal prints both content hashes in full and a remedy that works: delete the
    named file, then `adr dedup build`."""
    _, ov = build_for(gov)
    idx = active_index(gov)
    path = opath(gov)
    data = json.loads(path.read_bytes())
    data["chunk_content_sha256"] = "8" * 64
    path.write_bytes((json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode())
    with pytest.raises(StoreError) as e:
        dedup.load_overlay(gov.path, gov.snapshot_id, idx.chunker, ov.chunk_content_sha256)
    msg = str(e.value)
    assert "8" * 64 in msg and ov.chunk_content_sha256 in msg
    assert f"delete {path}" in msg and "adr dedup build" in msg
    path.unlink()  # the remedy
    code, out, _ = run(capsys, "dedup", "build", "--store", gov.path)
    assert code == 0 and "(written" in out
    assert dedup.load_overlay(gov.path, gov.snapshot_id, idx.chunker,
                              ov.chunk_content_sha256) is not None


def test_missing_counts_only_overlays_and_names_an_overlay_of_an_older_version(gov):
    idx = active_index(gov)
    content = chunk_content_sha256(idx.chunks.values())
    d = gov.path / "dedup" / gov.snapshot_id
    d.mkdir(parents=True)
    (d / "notes.json").write_text("{}\n")  # not an overlay
    (d / "stray.json").write_text("not json")
    assert dedup.missing(gov.path, gov.snapshot_id, idx.chunker, content) == dedup.NO_OVERLAY
    # an overlay of these chunks under the name of an older version (<key>.json)
    ov = dedup.build(list(idx.chunks.values()), idx.snapshot, idx.chunker)
    old = d / f"{dedup.overlay_key(idx.chunker, dedup.PARAMS)}.json"
    old.write_bytes(canonical_json(ov))
    why = dedup.missing(gov.path, gov.snapshot_id, idx.chunker, content)
    assert "older version" in why and old.name in why and "adr dedup build" in why
    t = tools.Tools(gov.path)
    res = t.search(COPIED, top=20, filters={"include_superseded": True})
    assert res.dedup is None and res.dedup_note == why
    with pytest.raises(tools.ToolError, match="older version"):
        t.search(COPIED, dedup=True)
    # of other chunks, the older name is just another overlay
    assert "older version" not in dedup.missing(gov.path, gov.snapshot_id, idx.chunker,
                                                "0" * 64)


def test_load_refuses_non_canonical_bytes(gov):
    _, ov = build_for(gov)
    idx = active_index(gov)
    path = opath(gov)
    path.write_text(json.dumps(json.loads(path.read_bytes()), indent=1) + "\n")
    with pytest.raises(StoreError, match="canonical"):
        dedup.load_overlay(gov.path, gov.snapshot_id, idx.chunker, ov.chunk_content_sha256)


def test_the_dedup_schema_is_one_of_the_record_schemas():
    assert records.schemas()["dedup.schema.json"] == dedup.DedupOverlay.model_json_schema()


COPIED = "draw opens on signal figure page marker"


# -- search -----------------------------------------------------------------------------------


def hit_pairs(res) -> list[tuple[str, float]]:
    return [(h.chunk_id, h.score) for h in res.hits]


def test_without_an_overlay_dedup_is_off_and_true_is_refused(gov):
    t = tools.Tools(gov.path)
    res = t.search("vessels", top=20)
    assert res.dedup is None
    assert all(h.scored_by == h.chunk_id and h.alternates == [] for h in res.hits)
    with pytest.raises(tools.ToolError) as e:
        t.search("vessels", dedup=True)
    assert str(e.value) == "no dedup overlay; run `adr dedup build`"
    for bad in ("yes", 1):
        with pytest.raises(tools.ToolError, match="dedup must be"):
            t.search("vessels", dedup=bad)


def test_dedup_off_is_the_phase1_ranking(gov):
    before = tools.Tools(gov.path).search("vessels", top=20, filters={"include_superseded": True})
    build_for(gov)
    t = tools.Tools(gov.path)
    for f in (None, {"include_superseded": True}, {"as_of": "2025-06-30"}):
        off = t.search("vessels", top=20, filters=f, dedup=False)
        idx = active_index(gov)
        a = ap.load_overlay(gov.path, gov.snapshot_id)
        allowed, excluded = a.allowed_docs(gov.doc_ids(), ap.Filters.parse(f))
        assert hit_pairs(off) == idx.retrieve("vessels", top=20,
                                              allowed_docs=None if excluded == 0 else allowed)
        assert off.dedup is None
        assert all(h.scored_by == h.chunk_id and h.alternates == [] for h in off.hits)
    off = t.search("vessels", top=20, filters={"include_superseded": True}, dedup=False)
    assert off.to_dict()["hits"] == before.to_dict()["hits"]


def test_dedup_is_on_by_default_once_an_overlay_exists(gov, monkeypatch):
    oid, _ = build_for(gov)
    tops = []
    real = StoreIndex.retrieve

    def spy(self, *args, **kw):
        tops.append(kw.get("top"))
        return real(self, *args, **kw)

    monkeypatch.setattr(StoreIndex, "retrieve", spy)
    t = tools.Tools(gov.path)
    res = t.search("vessels", top=5, filters={"include_superseded": True})
    assert res.dedup == oid and res.dedup_note is None and res.short_by == 0
    assert tops == []  # a collapsed search walks `ranking`, whose head is retrieve's top 200
    idx = active_index(gov)
    dd = dedup.load_overlay(gov.path, gov.snapshot_id, idx.chunker,
                            chunk_content_sha256(idx.chunks.values()))
    a = ap.load_overlay(gov.path, gov.snapshot_id)
    slots = dedup.collapse(full_ranking(idx, "vessels", None), dd, lambda cid: True,
                           idx.chunks, a, None, top=5)
    assert [(h.chunk_id, h.score, h.scored_by, h.alternates) for h in res.hits] == [
        (s.chunk_id, s.score, s.scored_by, list(s.alternates)) for s in slots]
    assert [h.rank for h in res.hits] == list(range(1, len(res.hits) + 1))
    line = json.loads((gov.path / "log" / "retrieval.jsonl").read_text().splitlines()[-1])
    assert line["dedup"] == oid and line["args"]["dedup"] is None


def test_superseded_copies_collapse_onto_the_head_version(gov):
    build_for(gov)
    t = tools.Tools(gov.path)
    idx = active_index(gov)
    # words of the three chunks the eCFR versions share
    versions = {doc_id(V2024): "old", doc_id(V2025): "middle", doc_id(V2026): "new"}
    res = t.search(COPIED, top=20, filters={"include_superseded": True})
    seen = set()
    for h in res.hits:
        members = {h.chunk_id, *(x.chunk_id for x in h.alternates)}
        assert not members & seen
        seen |= members
        if h.alternates and h.doc_id in versions:
            assert h.doc_id == doc_id(V2026)  # the head of the chain
            assert {x.doc_id for x in h.alternates} == {doc_id(V2024), doc_id(V2025)}
            assert all(x.kind == "exact" and x.jaccard == 1.0 for x in h.alternates)
            assert all(idx.chunks[x.chunk_id].text == idx.chunks[h.chunk_id].text
                       for x in h.alternates)
    assert any(h.alternates for h in res.hits)
    # as_of picks the version in force on the date
    res = t.search(COPIED, top=20, filters={"include_superseded": True, "as_of": "2025-07-01"})
    assert not {h.doc_id for h in res.hits} & {doc_id(V2024), doc_id(V2026)}
    # the default view hides the superseded versions: never shown, never listed
    res = t.search(COPIED, top=20)
    hidden = {doc_id(V2024), doc_id(V2025)}
    for h in res.hits:
        assert h.doc_id not in hidden and not {x.doc_id for x in h.alternates} & hidden


def test_near_copies_are_listed_with_their_jaccard(gov):
    build_for(gov)
    res = tools.Tools(gov.path).search(" ".join(BASE[:8]), top=10)
    near = [h for h in res.hits if any(x.kind == "near" for x in h.alternates)]
    assert len(near) == 1
    (alt,) = near[0].alternates
    assert alt.jaccard >= 0.9 and alt.chunk_id != near[0].chunk_id


def test_a_damaged_dedup_overlay_is_refused_on_search(gov):
    build_for(gov)
    path = opath(gov)
    path.write_bytes(b"{}\n")
    with pytest.raises(tools.ToolError, match="dedup"):
        tools.Tools(gov.path).search("vessels")
    with pytest.raises(tools.ToolError, match="dedup"):
        tools.Tools(gov.path).search("vessels", dedup=True)
    # dedup off does not read the overlay: the Phase 1 ranking
    assert tools.Tools(gov.path).search("vessels", dedup=False).dedup is None


def test_a_reranked_index_collapses_its_reranked_top_50(gov, monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "make_embedding_cache",
                        lambda path=None, *, threads=1: fake_cache(tmp_path / "emb"))
    monkeypatch.setattr(tools, "make_reranker", fake_reranker)
    tools.Tools(gov.path).index("p1-struct-bc-rr", w_bc=1, weight=0.5)
    build_for(gov)
    tops = []
    real = StoreIndex.retrieve_and_ranking

    def spy(self, *args, **kw):
        tops.append(kw.get("top"))
        return real(self, *args, **kw)

    monkeypatch.setattr(StoreIndex, "retrieve_and_ranking", spy)
    res = tools.Tools(gov.path).search("vessels", top=5, filters={"include_superseded": True})
    assert tops == [50] and res.dedup is not None and res.short_by == 0


# -- the command line -------------------------------------------------------------------------


def run(capsys, *argv):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out, err


def test_cli_dedup_build_prints_the_cluster_table_and_writes_once(gov, capsys):
    code, out, _ = run(capsys, "dedup", "build", "--store", gov.path)
    path = opath(gov)
    assert code == 0 and path.is_file() and "(written, built in" in out
    assert "all chunks" in out and "default view" in out and "threshold 0.9" in out
    first = path.read_bytes()
    code, out, _ = run(capsys, "dedup", "build", "--store", gov.path, "--json")
    got = json.loads(out)
    assert code == 0 and path.read_bytes() == first
    assert got["overlay_id"] == hashlib.sha256(first).hexdigest() and got["existed"]
    assert got["figures"]["all"]["exact_clusters"] == json.loads(first)["stats"][
        "exact_clusters"]
    # the default view (superseded versions excluded) has no exact copies of the eCFR text
    assert got["figures"]["default"]["exact_clusters"] == 0


def test_cli_dedup_build_needs_an_index(tmp_path, capsys):
    s = make_gov_store(tmp_path / "s")
    code, _, err = run(capsys, "dedup", "build", "--store", s.path)
    assert code == 2 and "adr index" in err


def test_cli_search_dedup_flags(gov, capsys):
    build_for(gov)
    s = gov.path
    code, out, _ = run(capsys, "search", COPIED, "--store", s, "--include-superseded",
                       "--top", 20, "--json")
    on = json.loads(out)
    assert code == 0 and on["dedup"] is not None and any(h["alternates"] for h in on["hits"])
    code, out, _ = run(capsys, "search", COPIED, "--store", s, "--include-superseded",
                       "--top", 20, "--no-dedup", "--json")
    off = json.loads(out)
    assert code == 0 and off["dedup"] is None and not any(h["alternates"] for h in off["hits"])
    code, out, _ = run(capsys, "search", COPIED, "--store", s, "--include-superseded")
    assert code == 0 and "dedup" in out and "alt" in out


def _assert_lined_up(table: list[str]) -> None:
    def cells(line):  # cells are separated by two or more spaces
        return [(m.start(), m.end()) for m in re.finditer(r"\S+(?: \S+)*", line)]

    header = cells(table[0])
    for row in table[1:]:
        got = cells(row)
        assert len(got) == len(header)
        assert got[0][0] == header[0][0]  # the view column is left-aligned
        assert [e for _, e in got[1:]] == [e for _, e in header[1:]]  # the others right-aligned


def test_cli_dedup_build_table_columns_line_up(gov, capsys):
    code, out, _ = run(capsys, "dedup", "build", "--store", gov.path)
    lines = out.splitlines()
    head = next(i for i, line in enumerate(lines) if line.strip().startswith("view"))
    table = lines[head:head + 3]
    assert code == 0 and len(table) == 3 and "default view" in table[2]
    _assert_lined_up(table)


def test_the_dedup_table_fits_five_digit_counts():
    from adr_store import cli

    wide = {"chunks": 99999, "exact_clusters": 99999, "exact_chunks": 99999,
            "exact_redundant": 99999, "exact_redundant_share": 1.0,
            "exact_redundant_token_share": 1.0, "near_pairs": 99999, "clusters": 99999,
            "redundant_share": 1.0}
    _assert_lined_up([cli._dedup_header(0.9), cli._dedup_row("all chunks", wide),
                      cli._dedup_row("default view", {**wide, "exact_redundant_share": 0.512})])


# -- deepening: collapse never comes back short while admitted chunks are left ---------------

def copies_body(n: str) -> bytes:
    """A document of 120 sections, each holding "vessel" 1 to 7 times and words of its own."""
    parts = [f"# Copy {n}\n"]
    for i in range(120):
        words = " ".join(f"s{i}w{j}" for j in range(45))
        parts.append(f"## Section {i}\n\n{'vessel ' * (i % 7 + 1)}{words}.\n")
    return "\n".join(parts).encode()


def make_copies(path):
    """Three copies of one 120-section document: 360 chunks matching "vessel", 120 clusters
    of three (the fused pool of 200 collapses to fewer than 70)."""
    return make_gov_store(path, [doc(copies_body(n), "md", f"file://copy-{n}.md")
                                 for n in "abc"])


@pytest.fixture
def fake_models(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "make_embedding_cache",
                        lambda path=None, *, threads=1: fake_cache(tmp_path / "emb"))
    monkeypatch.setattr(tools, "make_reranker", fake_reranker)


@pytest.fixture(params=["lexical", "dense"])
def copies(request, tmp_path, fake_models):
    s = make_copies(tmp_path / "copies")
    if request.param == "lexical":
        tools.Tools(s.path).index("p1-struct", lexical_only=True)
    else:
        tools.Tools(s.path).index("p1-struct", weight=0.5)
    build_for(s)
    return s


def full_ranking(idx, query, w, allowed=None):
    """Brute force: every candidate of the index in the order collapse walks. Lexical only:
    BM25's ranking of every chunk with a positive score. Fused: Phase 1's linear fusion of
    the channels' top CHANNEL_K (all of it), then every other chunk by the same weights over
    its channel scores scaled as that pool's (a chunk with no BM25 score has 0)."""
    def channel(ch, mask):
        return ch.search(query, k=10**9) if mask is None else ch.search(query, k=10**9,
                                                                         mask=mask)

    lex = channel(idx.lexical, None if allowed is None else idx.lexical.mask(allowed))
    if idx.dense is None:
        return lex
    rows = [idx.chunks[c].doc_id for c in idx.dense.chunk_ids]
    dense = channel(idx.dense, None if allowed is None else np.isin(rows, sorted(allowed)))
    head = fusion.linear(lex[:CHANNEL_K], dense[:CHANNEL_K], w, top=10**9)

    def scale(pool):
        if not pool:
            return lambda s: 0.0
        lo, hi = min(s for _, s in pool), max(s for _, s in pool)
        return lambda s: (s - lo) / ((hi - lo) or 1.0)

    nl, nd, bm25 = scale(lex[:CHANNEL_K]), scale(dense[:CHANNEL_K]), dict(lex)
    seen = {c for c, _ in head}
    tail = {c: w * nl(bm25.get(c, 0.0)) + (1 - w) * nd(s) for c, s in dense if c not in seen}
    return head + fusion.rank(tail, top=10**9)


def reference(store, query, top, filters=None):
    """The collapse of the brute-force full ranking, cut at `top`."""
    t = tools.Tools(store.path)
    idx, active = t.active_index(), json.loads(
        (store.path / "index" / "active.json").read_text())
    app = ap.load_overlay(store.path, store.snapshot_id)
    f = ap.Filters.parse(filters)
    allowed, excluded = (None, 0) if app is None else app.allowed_docs(store.doc_ids(), f)
    allowed = None if excluded == 0 else allowed
    dd = dedup.load_overlay(store.path, store.snapshot_id, idx.chunker,
                            chunk_content_sha256(idx.chunks.values()))
    ranked = full_ranking(idx, query, active["w"], allowed)
    return dedup.collapse(ranked, dd, lambda c: allowed is None or idx.chunks[c].doc_id in
                          allowed, idx.chunks, app, f.as_of, top)


def slots_of(res):
    return [(h.chunk_id, h.score, h.scored_by, h.alternates) for h in res.hits]


def test_lexical_only_retrieve_reaches_the_fused_depth(tmp_path):
    s = make_copies(tmp_path / "copies")
    tools.Tools(s.path).index("p1-struct", lexical_only=True)
    idx = active_index(s)
    assert idx.retrieve("vessel", top=200) == idx.lexical.search("vessel", k=200)
    assert len(idx.retrieve("vessel", top=200)) == 200
    for top in (10, 100):  # the Phase 1 depths are unchanged
        assert idx.retrieve("vessel", top=top) == idx.lexical.search("vessel", k=top)


@pytest.mark.parametrize("top", [10, 50, 70, 100])
def test_collapse_fills_top_from_the_full_ranking(copies, top):
    res = tools.Tools(copies.path).search("vessel", top=top)
    assert len(res.hits) == top and res.short_by == 0 and res.dedup is not None
    want = reference(copies, "vessel", top)
    assert slots_of(res) == [(s.chunk_id, s.score, s.scored_by, list(s.alternates))
                             for s in want]
    scores = [h.score for h in res.hits]
    assert scores == sorted(scores, reverse=True)


def test_ranking_is_the_fused_pool_then_every_other_candidate(copies):
    idx = active_index(copies)
    w = json.loads((copies.path / "index" / "active.json").read_text())["w"]
    got = list(idx.ranking("vessel", w))
    assert got == full_ranking(idx, "vessel", w)
    head = idx.retrieve("vessel", w=w, top=2 * CHANNEL_K)
    assert got[:len(head)] == head
    ids = [c for c, _ in got]
    assert len(ids) == len(set(ids))
    if idx.dense is not None:
        assert set(ids) == set(idx.chunks)  # every chunk is a dense candidate
        assert all(s <= 0 for _, s in got[len(head):]) and all(s >= 0 for _, s in head)
    some = frozenset(copies.doc_ids()[:2])
    masked = list(idx.ranking("vessel", w, allowed_docs=some))
    assert masked == full_ranking(idx, "vessel", w, some)
    assert {idx.chunks[c].doc_id for c, _ in masked} == some


def test_ranking_with_a_view_s_bm25_yields_only_the_allowed_documents(copies):
    """The view's BM25 covers two of the three documents, the view admits one: no chunk of
    the other two is ever yielded (the view's statistics, the view's mask)."""
    from adr_store.retrieval.lexical import FieldBM25

    idx = active_index(copies)
    w = json.loads((copies.path / "index" / "active.json").read_text())["w"]
    two = set(copies.doc_ids()[:2])
    view = FieldBM25(idx.lexical.w_bc, idx.lexical.bm25.k1, idx.lexical.bm25.b)
    view.build([c for c in idx.chunks.values() if c.doc_id in two])
    one = frozenset(copies.doc_ids()[:1])
    got = list(idx.ranking("vessel", w, allowed_docs=one, lexical=view))
    assert got and {idx.chunks[c].doc_id for c, _ in got} == one
    assert len(got) == sum(c.doc_id in one for c in idx.chunks.values())  # every one of them


def test_ranking_refuses_bad_arguments_when_called_not_when_iterated(copies):
    from adr_store.retrieval.lexical import FieldBM25

    idx = active_index(copies)
    view = FieldBM25(idx.lexical.w_bc, idx.lexical.bm25.k1, idx.lexical.bm25.b)
    view.build(list(idx.chunks.values()))
    some = frozenset(copies.doc_ids()[:1])
    with pytest.raises(ValueError, match="allowed_docs too"):
        idx.ranking("vessel", 0.5, lexical=view)
    with pytest.raises(ValueError, match="set of document ids"):
        idx.ranking("vessel", 0.5, allowed_docs=list(some))
    other = FieldBM25(idx.lexical.w_bc + 1)
    other.build(list(idx.chunks.values()))
    with pytest.raises(ValueError, match="does not match"):
        idx.ranking("vessel", 0.5, allowed_docs=some, lexical=other)
    if idx.dense is not None:
        with pytest.raises(ValueError, match="tuned weight"):
            idx.ranking("vessel", None)
    else:
        assert list(idx.ranking("vessel", None)) == idx.lexical.search("vessel", k=10**9)


def test_collapse_refuses_a_top_below_one():
    c = [chunk("a", 0, text(BASE))]
    for top in (0, -1):
        with pytest.raises(ValueError, match="top"):
            dedup.collapse([(c[0].chunk_id, 1.0)], loaded(build(c)), lambda m: True, by_id(c),
                           None, None, top)


def test_the_tail_of_the_ranking_has_no_negative_zero():
    """A score that rounds to zero from below is 0.0, not -0.0 (one JSON spelling)."""
    pool = [(f"p{i:03d}", 0.5 - i / 1000) for i in range(CHANNEL_K)]  # the dense pool
    lo = pool[-1][1]
    lex = [("p000", 2.0), ("p001", 1.0)]
    dense = [*pool, ("c", lo - 1e-9), ("d", lo)]  # c just below the pool's minimum
    tail = index_mod._tail(lex, dense, 0.0, {cid for cid, _ in pool})
    assert [cid for cid, _ in tail] == ["c", "d"]
    assert all(s == 0.0 and str(s) == "0.0" for _, s in tail)
    assert json.dumps(tail) == '[["c", 0.0], ["d", 0.0]]'


def test_the_rest_of_the_ranking_is_only_computed_when_the_pool_runs_out(copies, monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("the tail was computed")

    monkeypatch.setattr(index_mod, "_tail", boom)
    t = tools.Tools(copies.path)
    assert len(t.search("vessel", top=10).hits) == 10
    if active_index(copies).dense is not None:
        with pytest.raises(AssertionError, match="tail"):
            t.search("vessel", top=100)


def test_short_by_is_zero_when_the_admitted_chunks_run_out(copies):
    res = tools.Tools(copies.path).search("s3w1", top=10)
    assert res.short_by == 0
    idx = active_index(copies)
    if idx.dense is None:  # only the three copies of section 3 match
        assert len(res.hits) == 1 and len(res.hits[0].alternates) == 2


def test_a_reranked_search_short_of_top_embeds_the_query_once(tmp_path, fake_models,
                                                              monkeypatch):
    """`short_by` reuses the reranked head's channel lists: one dense search (one query
    embedding) per search, filtered or not."""
    from adr_store.retrieval.dense import CachedDense

    s = make_copies(tmp_path / "copies")
    tools.Tools(s.path).index("p1-struct-bc-rr", w_bc=1, weight=0.5)
    build_for(s)
    t = tools.Tools(s.path)
    t.active_index()
    calls = []
    real = CachedDense.search

    def spy(self, query, *a, **kw):
        calls.append(query)
        return real(self, query, *a, **kw)

    monkeypatch.setattr(CachedDense, "search", spy)
    for filters in (None, {"include_superseded": True}):
        calls.clear()
        res = t.search("vessel", top=50, filters=filters)
        assert res.short_by > 0 and calls == ["vessel"]


def test_a_reranked_index_says_how_many_slots_it_is_short(tmp_path, fake_models, capsys):
    s = make_copies(tmp_path / "copies")
    tools.Tools(s.path).index("p1-struct-bc-rr", w_bc=1, weight=0.5)
    build_for(s)
    t = tools.Tools(s.path)
    res = t.search("vessel", top=50)
    idx = active_index(s)
    head = idx.retrieve("vessel", w=0.5, top=50)  # the reranked top 50
    assert slots_of(res) == [(x.chunk_id, x.score, x.scored_by, list(x.alternates)) for x in
                             dedup.collapse(head, t._dedup_overlay(idx), lambda c: True,
                                            idx.chunks, None, None, 50)]
    seen = {c for c, _ in head}
    more = head + [h for h in full_ranking(idx, "vessel", 0.5) if h[0] not in seen]
    filled = dedup.collapse(more, t._dedup_overlay(idx), lambda c: True, idx.chunks, None,
                            None, 50)
    assert len(filled) == 50 and len(res.hits) < 50
    assert res.short_by == 50 - len(res.hits)
    assert t.search("vessel", top=5).short_by == 0
    assert t.search("vessel", top=50, dedup=False).short_by == 0
    code, out, _ = run(capsys, "search", "vessel", "--store", s.path, "--top", 50)
    assert code == 0 and f"short by {res.short_by}" in out
    code, out, _ = run(capsys, "search", "vessel", "--store", s.path, "--top", 5)
    assert code == 0 and "short by" not in out


# -- a rechunked index, another chunker ---------------------------------------------------------

def test_a_rechunked_index_searches_without_collapse_until_dedup_build(gov, monkeypatch,
                                                                         capsys):
    oid, ov = build_for(gov)
    old_path = opath(gov)
    old = old_path.read_bytes()
    before = active_index(gov)
    real = index_mod.chunk_store
    monkeypatch.setattr(index_mod, "chunk_store", lambda store, **kw: [
        dataclasses.replace(c, breadcrumb=c.breadcrumb + " (rechunked)")
        for c in real(store, **kw)])
    tools.Tools(gov.path).index("p1-struct", lexical_only=True)
    monkeypatch.undo()
    idx = active_index(gov)
    assert (idx.snapshot, idx.chunker, sorted(idx.chunks)) == (
        before.snapshot, before.chunker, sorted(before.chunks))
    assert chunk_content_sha256(idx.chunks.values()) != ov.chunk_content_sha256
    t = tools.Tools(gov.path)
    f = {"include_superseded": True}
    res = t.search(COPIED, top=20, filters=f)
    assert res.dedup is None and not any(h.alternates for h in res.hits)
    assert "other chunks" in res.dedup_note and "adr dedup build" in res.dedup_note
    assert hit_pairs(res) == hit_pairs(t.search(COPIED, top=20, filters=f, dedup=False))
    with pytest.raises(tools.ToolError, match="other chunks.*adr dedup build"):
        t.search(COPIED, top=20, filters=f, dedup=True)
    code, out, _ = run(capsys, "search", COPIED, "--store", gov.path, "--include-superseded")
    assert code == 0 and "other chunks" in out
    code, out, _ = run(capsys, "dedup", "build", "--store", gov.path)
    new_path = opath(gov)
    assert code == 0 and "(written" in out and new_path != old_path
    assert old_path.read_bytes() == old  # the old overlay is untouched
    res = tools.Tools(gov.path).search(COPIED, top=20, filters=f)
    assert res.dedup == hashlib.sha256(new_path.read_bytes()).hexdigest() != oid
    assert res.dedup_note is None and any(h.alternates for h in res.hits)


def test_an_overlay_for_another_chunker_is_ignored(gov):
    idx = active_index(gov)
    other = chunker_config(300, 40)
    assert other != idx.chunker
    ov = dedup.build(list(idx.chunks.values()), idx.snapshot, other)
    _, path = dedup.write_overlay(gov.path, ov)
    assert path.is_file() and path != opath(gov)
    assert dedup.load_overlay(gov.path, gov.snapshot_id, idx.chunker,
                              chunk_content_sha256(idx.chunks.values())) is None
    t = tools.Tools(gov.path)
    res = t.search(COPIED, top=20, filters={"include_superseded": True})
    assert res.dedup is None and not any(h.alternates for h in res.hits)
    with pytest.raises(tools.ToolError, match="adr dedup build"):
        t.search(COPIED, dedup=True)
