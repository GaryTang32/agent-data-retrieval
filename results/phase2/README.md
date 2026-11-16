# Phase 2 results: applicability, permissions, tools as data and an MCP server

> **Work in progress.** Parts 2A (applicability and duplicates), 2B (permissions, for the
> content tools) and 2C (tools as data, with B1, B3 and B4 completed for the tool tools) are
> measured so far. These numbers were recorded on 16 November 2026 under version 2 of the
> metric definitions, with golden sets v0.1. Part 2D (the MCP server) follows in its own
> section, and completes B1 and B3 for the MCP server.

Design: [`docs/superpowers/specs/2026-11-16-phase2-design.md`](../../docs/superpowers/specs/2026-11-16-phase2-design.md).
Plan: [`docs/superpowers/plans/2026-11-16-phase2.md`](../../docs/superpowers/plans/2026-11-16-phase2.md).
Phase 1 results: [`results/phase1/README.md`](../phase1/README.md).

## 2A: applicability and duplicates

**Verdict.** All six 2A criteria pass on every corpus where they apply.
- **Default search** returns no chunk from a superseded version (A1).
- **`as_of`** returns only documents in force on that date (A2).
- **Dated questions** gain +0.254 nDCG@10 on gov, with Recall@10 unchanged (A3).
- **Other questions** are not served worse: on gov they gain +0.023 Recall@10 and +0.035 nDCG@10 (A4).
- **`p2-identity`** reproduces Phase 1 exactly (A5).
- **Dedup** leaves no top-10 slot holding two copies of one passage (A6).

Two results need care when reading these numbers:
- **21 gov test questions lose all their evidence by design (ruling R3).** Their evidence exists only in superseded versions, so default search no longer returns it. They are kept out of A4 and reported apart. With them counted, gov Recall@10 falls from 0.802 to 0.735.
- **Dedup is not a retrieval gain here.** It matters on gov only when superseded versions are kept (`include_superseded`). In the default view it changed 2 of 242 gov test rankings and no quality metric (Recall/nDCG/MRR); tokens@10 moved by a few tokens on one item (2,840 → 2,835). On research it changed one ranking, with no quality metric change and tokens@10 3,541 → 3,543 on that item; on bench nothing changed.

### What was run

- **Retrieval only, no model calls** (ruling R1), with `adr-eval retrieval` on the dev and test splits of gov, research and bench.
- **Configurations** (spec §10.1). Each builds on `p1-struct-bc` with its Phase 1 weights, not retuned (R2). There is no ACL layer yet: the 2A runs search as no caller, and Task 8 re-runs them as `user:auditor`.

  | Configuration | Applicability filter | `as_of` | Dedup collapse |
  |---|---|---|---|
  | `p1-struct-bc` | none (the Phase 1 path) | – | – |
  | `p2-identity` | `include_superseded` | – | off |
  | `p2-appl` | default (no superseded documents) | the item's own date, for `policy_asof` items | off |
  | `p2-dedup` | `include_superseded` | – | on |
  | `p2-default` | default | the item's own date, for `policy_asof` items | on |

- **Runs:** 6 reference runs of `p1-struct-bc`, then 24 Phase 2 runs (4 configurations × 3 corpora × 2 splits).
- **Comparisons and checks:**
  - 18 comparisons with `adr-eval p2-compare`: `p2-appl`, `p2-dedup` and `p2-default` against `p1-struct-bc`, per corpus and split;
  - `adr-eval retrieval-identical` for A5 and for determinism;
  - the gov temporal probes T1–T5 with `adr-eval probes temporal gov`, with dedup on and off.
- **Statistics.** The paired bootstrap of `adr_eval.scoring.stats`, with 10,000 resamples and seed 20261108.
  - The margin, 0.02, was fixed before any Phase 2 result (R10).
  - A criterion passes when the lower bound of the 95% interval of the difference (Phase 2 minus Phase 1) is above −0.02, on both Recall@10 and nDCG@10.
  - Each criterion is one pre-declared comparison per corpus, so there is no Holm correction.
- **Stores.**
  - Every Phase 2 run searched a scratch copy, `.cache/store-p2/<corpus>`, at the Phase 1 snapshots: gov `f002821f2cb3…`, research `97c415b1aa71…`, bench `7d8d1f8adda6…`.
  - `.cache/store` and `.cache/index` were only read: the SHA-256 and modification time of all 7,320 files were unchanged after the runs.
- **Overlays** (spec §4.2, §4.5):

  | Corpus | Applicability overlay | Dedup overlay |
  |---|---|---|
  | gov | `4c81d25fe905…` | `6fb05917038e…` |
  | research | `5b91123ae2d3…` | `4aedcea37803…` |
  | bench | `2709180fbeef…` | `94a90b9859e0…` |

- **Machine.** One 4-core Intel Xeon at 2.10 GHz, 15 GB of memory, Python 3.13.18. It was idle at the start (load average 0.83).
  - The 6 reference runs ran three at a time and took 8 minutes.
  - The 24 Phase 2 runs ran four at a time and took 21.5 minutes.
  - The per-run wall times below are therefore under shared load.
  - Research runs spend most of their time loading the PDF corpus.

### Reference runs and A5

The committed Phase 1 summaries hold no per-item rows, so `p1-struct-bc` was re-run with
unchanged code (plan, Task 5 step 2).

**Reproduction.** All six runs reproduced the committed
`results/phase1/run-summaries/<corpus>-p1-struct-bc-<split>-retrieval-*/retrieval.json`
exactly:
- `fingerprint`, `w`, `settings` (including `store_snapshot`, `w_bc` and the tuning record), and the whole `summary`;
- also `snapshot` and `golden_sha256`.

**Identity.** `p2-identity` then gave the same items, ranked chunk ids and exact scores as each reference run:

| Corpus | dev items | test items | Identical |
|---|---|---|---|
| gov | 55 | 242 | yes, both splits |
| research | 53 | 222 | yes, both splits |
| bench | 156 | 572 | yes, both splits |

Other configurations whose rankings are identical to `p1-struct-bc`:
- **research:** `p2-appl` on both splits, and `p2-dedup` and `p2-default` on dev.
- **bench:** all three configurations on both splits.

On research test, `p2-dedup` and `p2-default` differ from `p1-struct-bc` in one item: dedup removed one near-duplicate slot (below). No research or bench document has a successor version, so the default filter excludes nothing there.

### Retrieval (test split)

Pooled over items with evidence (`insufficient` items carry no metrics). Wall time is the run's own `wall_clock_s`.

| Corpus | System | n | Recall@10 | nDCG@10 | MRR | Coverage@10 | Tokens@10 | Wall (s) |
|---|---|---|---|---|---|---|---|---|
| gov | `p1-struct-bc` | 213 | 0.802 | 0.703 | 0.677 | 0.746 | 3,171 | 54 |
| gov | `p2-identity` | 213 | 0.802 | 0.703 | 0.677 | 0.746 | 3,171 | 76 |
| gov | `p2-appl` | 213 | 0.735 | 0.696 | 0.687 | 0.701 | 3,181 | 74 |
| gov | `p2-dedup` | 213 | 0.735 | 0.681 | 0.668 | 0.694 | 3,190 | 92 |
| gov | `p2-default` | 213 | 0.735 | 0.696 | 0.687 | 0.701 | 3,181 | 78 |
| research | all five | 180 | 0.844 | 0.710 | 0.677 | 0.764 | 3,182 | 228–368 |
| bench | all five | 517 | 0.919 | 0.853 | 0.856 | 0.780 | 2,911 | 80–137 |

**The pooled gov figures mix three kinds of question,** and the 21 superseded-only items
dominate the pooled Recall@10 fall (−0.067 [−0.110, −0.026]). The subsets below separate them.

On dev:
- gov `p1-struct-bc` and `p2-identity`: 0.734 / 0.719 / 0.741 (Recall@10 / nDCG@10 / MRR);
- gov `p2-appl` and `p2-default`: 0.689 / 0.688 / 0.711;
- gov `p2-dedup`: 0.689 / 0.663 / 0.679;
- research and bench: all five systems equal (0.872 / 0.769 / 0.737 and 0.968 / 0.888 / 0.880).

### Item subsets on gov test: predicted against measured

The subsets are those of spec §4.6, as `adr_eval.phase2.item_subsets` computes them:

| Subset | Items | Definition |
|---|---|---|
| `asof` | 34 | `policy_asof` items with a date |
| `in_force` | 158 | Other items with evidence whose every evidence group has a member in a document that is not superseded |
| `superseded_only` | 21 | The other items with evidence |

Each cell shows Phase 1, then Phase 2, then the difference with its 95% paired interval. The
predicted values are the prototype figures of spec §4.6.

| Subset | n | Configuration | Recall@10 | nDCG@10 | MRR | Superseded / wrong-version slots | Predicted (§4.6) |
|---|---|---|---|---|---|---|---|
| `asof` | 34 | `p2-default` | 0.853 → 0.853 (+0.000 [+0.000, +0.000]) | 0.567 → 0.820 (+0.254 [+0.182, +0.325]) | 0.471 → 0.809 (+0.338 [+0.243, +0.434]) | wrong-version 221 → 0 | Recall@10 +0.000, nDCG@10 +0.254 [+0.182, +0.325], MRR 0.471 → 0.809, wrong-version 213 → 0 |
| `in_force` | 158 | `p2-default` | 0.784 → 0.807 (+0.023 [+0.004, +0.048]) | 0.727 → 0.762 (+0.035 [+0.021, +0.051]) | 0.717 → 0.752 (+0.035 [+0.019, +0.053]) | superseded 743 → 0 | Recall@10 +0.023 [+0.004, +0.048], nDCG@10 +0.035 [+0.021, +0.051], MRR 0.717 → 0.752, superseded 743 → 0 |
| `superseded_only` | 21 | `p2-default` | 0.857 → 0.000 | 0.746 → 0.000 | 0.709 → 0.000 | superseded 139 → 0 | 0.857 → 0, 0.746 → 0, 0.709 → 0, 139 → 0 |
| `in_force` | 158 | `p2-dedup` | 0.784 → 0.801 (+0.016 [+0.002, +0.037]) | 0.727 → 0.755 (+0.028 [+0.016, +0.042]) | 0.717 → 0.746 (+0.028 [+0.014, +0.046]) | duplicate slots 645 → 0 | +0.016, +0.020, MRR 0.717 → 0.735 |
| `asof`, without the date | 34 | `p2-dedup` | 0.853 → 0.588 (−0.265 [−0.412, −0.118]) | 0.567 → 0.508 (−0.058 [−0.200, +0.078]) | 0.471 → 0.480 (+0.010 [−0.135, +0.152]) | wrong-version 221 → 182 | 0.853 → 0.588, 0.567 → 0.434, 0.471 → 0.380 |

`p2-appl` gives exactly the `p2-default` metrics on every subset above. Dedup under the
default filters changes no quality metric (Recall/nDCG/MRR); tokens@10 moved by a few tokens on
one item (next section).

**Applicability matches the prediction to three decimals,** intervals included.

**The wrong-version count is 221, not the predicted 213.** The prototype ignored Federal
Register and IRM validity. The 8 extra Phase 1 slots are documents not in force on the item's
date:
- 2 proposed rules;
- 3 temporary rules;
- 3 IRM chapters dated after the question's date.

The 213 eCFR slots match exactly.

**Dedup alone differs from the prototype.** Recall@10 matches on both rows. nDCG@10 and MRR are
higher than predicted:
- `in_force`: nDCG@10 +0.028 against +0.020; MRR 0.746 against 0.735;
- `asof` without the date: nDCG@10 0.508 against 0.434; MRR 0.480 against 0.380.

The prototype collapsed exact copies only. The build also collapses near copies (Jaccard ≥ 0.90)
and chooses the shown member by the four canonical rules of §4.5. That is the most likely cause,
but it was not isolated: the prototype's code is not in the repository.

Dated questions need `as_of`. Collapse without a date shows the head version, which loses 9 of
the 29 dated items Phase 1 had found. Copies are never credited for dated items.

### The 21 gov items whose evidence is only superseded (R3)

- **Who they are.** Their gold passage lies in a section that was later removed or changed, and the question carries no date.
- **Default search returns none of them** (`p2-appl` and `p2-default`: Recall@10, nDCG@10 and MRR 0.000, from 0.857, 0.746 and 0.709). This is the intended behaviour: the passage is no longer in force.
- **They are not counted in A4.** With them, gov `p2-default` test is Recall@10 0.735 (−0.067 [−0.110, −0.026]) and nDCG@10 0.696 (−0.007 [−0.050, +0.033]) over all 213 scored items.
  - This pooled comparison would not pass the 0.02 margin (its Recall@10 lower bound is −0.110). A3 and A4 exclude these items by ruling R3 (spec §15).
- **Dev:** the same holds for the 2 dev items (1.000 → 0.000).
- **Golden v0.2.** Giving these items an `as_of` date belongs there (spec §15, Q1).

**Dedup alone** (superseded versions kept) keeps 10 of these items and loses 8: Recall@10
0.857 → 0.476 [−0.571, −0.190]. In each of the 8, a chunk that Phase 1 had found is replaced
by a member of its cluster from another version, and that member is not credited:
- **In 4 items the replacement has exactly the same text.** This is the v2 copy-rule artefact of spec §4.6: a copy in another document is credited only when 200 characters of context on each side also match, and a section edge breaks that.
- **In the other 4 it is a near copy** (Jaccard ≥ 0.90) whose text differs.

The metric is not changed.

### Slots (test split, all items)

The top-10 slots of each run, counted by `p2-compare` against the store's overlays.
- **Superseded:** a chunk of a document with a successor version.
- **Wrong version:** on dated items, a chunk of a document not in force on the item's date.
- **Duplicate:** a slot sharing a dedup component with a slot above it. Components are computed among the chunks the run's own filters admit.
- **Cluster:** a slot sharing a dedup cluster with a slot above it, ignoring the filters.
- **Exact copy:** a slot whose text equals a slot above it.
- **Groups touched:** distinct evidence groups touched in the top 10, per item with evidence.

| Corpus | System | Slots | Superseded | Wrong version (of 340) | Duplicate | Cluster | Exact copy | Groups touched per item | Tokens@10 |
|---|---|---|---|---|---|---|---|---|---|
| gov | `p1-struct-bc` | 2,420 | 1,279 (52.9%) | 221 | 1,076 (44.5%) | 1,076 | 984 (40.7%) | 1.103 | 3,171.3 |
| gov | `p2-appl` | 2,420 | 187 | 0 | 1 | 1 | 0 | 1.070 | 3,181.1 |
| gov | `p2-dedup` | 2,420 | 254 | 182 | 0 | 0 | 0 | 1.061 | 3,190.2 |
| gov | `p2-default` | 2,420 | 187 | 0 | 0 | 0 | 0 | 1.070 | 3,181.0 |
| research | `p1-struct-bc`, `p2-appl` | 2,220 | 0 | – | 1 | 1 | 0 | 1.211 | 3,181.7 |
| research | `p2-dedup`, `p2-default` | 2,220 | 0 | – | 0 | 0 | 0 | 1.211 | 3,181.7 |
| bench | all | 5,720 | 0 | – | 0 | 0 | 0 | 1.253 | 2,911.1 |

**The Phase 1 shares of spec §4.1 are reproduced.**
- Gov test: 52.9% of slots superseded, 40.7% exact copies of a slot above.
- Counting near copies and copies with different text too, 44.5% of slots repeat a passage above them.

**The 187 superseded slots of `p2-appl` and `p2-default` are all on dated items.** Under
`as_of` the version in force on that date is often superseded. These are the right versions:
there are 0 wrong-version slots.

**Groups touched.** On the `in_force` items, evidence groups touched per item rise from 1.190
to 1.241 with dedup and to 1.259 with `p2-default`.

### Dedup (A6)

The cluster parameters are recorded in each overlay and in every `p2-compare` record:
- exact clusters by the SHA-256 of the chunk text;
- near copies by MinHash over lower-cased word 5-shingles: 128 hash functions modulo 4,294,967,311, seed 20261116, 16 bands of 8 rows;
- every candidate pair verified by exact Jaccard, with a threshold of 0.90;
- clusters are connected components.

| Corpus | Chunks | Clusters | Exact clusters (chunks) | Redundant, exact | Verified near pairs | Redundant, exact and near |
|---|---|---|---|---|---|---|
| gov | 6,783 | 1,976 | 1,958 (5,430) | 3,472 = 51.2% (48.7% of tokens) | 366 | 3,664 = 54.0% |
| research | 9,554 | 3 | 1 (3) | 2 | 3 | 5 = 0.05% |
| bench | 7,400 | 1 | 1 (3) | 2 | 0 | 2 = 0.03% |

These equal the spec §4.5 table at the spec's rounding (research redundant is 5 of 9,554 = 0.05%; the spec shows 0.1%).

**After collapse, no top-10 slot shares a component, a cluster or a text** with a slot above it.
This holds for `p2-dedup` and `p2-default` on all three corpora and both splits. Phase 1 had
1,076 such slots on gov test, and 1 on research test.

**Effect.**
- **gov, superseded versions kept** (`p2-dedup`): `in_force` gains +0.016 Recall@10 and +0.028 nDCG@10, both with intervals above zero.
- **gov, default filters** (`p2-default` against `p2-appl`): dedup changed 2 rankings (one dated item, one superseded-only item) and no quality metric (Recall/nDCG/MRR); tokens@10 moved by a few tokens on one item (2,840 → 2,835). The in-force view has no exact copies and 1 near cluster.
- **research:** one test ranking changed, with no quality metric change (tokens@10 3,541 → 3,543 on that item). **bench:** nothing changed.
- **Tokens@10** moves by at most +0.6% (gov `p2-dedup`, 3,171 → 3,190). Dedup swaps copies for other chunks of similar length.

**So dedup matters on gov only when superseded versions are kept.** Research and bench have
almost no copies. Dedup is not presented as a retrieval gain.

### Temporal probes (gov, A1 and A2)

The probes are deterministic, with seed 20261116, and were run through `adr_store.tools.Tools`
on the gov copy. They passed with dedup on (the default) and with dedup off, with identical
counts.

| Set | Mode | Probes | Passed | Pass rule and reported figures |
|---|---|---|---|---|
| T1: `policy_asof` items | `as_of` = the item's date | 40 | 40 | 0 chunks (hits or alternates) from documents not in force |
| T2: changed sections, query = heading | default | 189 | 189 | 0 superseded chunks. Head version's section found in the top 10 for 188, mean rank 1.03; 1 section has no head version |
| T2 | `as_of` = older date | 189 | 189 | 0 chunks from other versions; old section Recall@10 1.000 |
| T3: removed sections, query = heading | default | 145 | 145 | 0 superseded chunks (Recall@10 0.000, as intended) |
| T3 | `as_of` = its version's date | 145 | 145 | 0 chunks not in force; removed section Recall@10 1.000 (145 of 145) |
| T4: all gov golden questions, no date | default | 297 | 297 | 0 superseded chunks |
| T5: Federal Register and IRM documents | `as_of` = `valid_from` − 1 day | 171 | 171 | Absent from `search` (171), from `grep` of a 30-character substring (171, none truncated) and refused by `read` (171). Controls without the date find each document by `search` and `grep` and read it (171 each) |

**A1 on research and bench** is measured from the superseded slots of the `p2-default` runs over
every golden item (275 research, 728 bench): 0. This holds by construction: no research or bench
document has a successor version, so nothing there can be superseded.

**T3 probe-construction defect, fixed in `5fb86cb`.** The first probe runs found 144 of the 145
removed sections under their date (Recall@10 0.993). The one missed, § 165.T08-0413 (33 CFR 165,
the 2024-06-27 version), was a defect of the probe, not a retrieval miss:
- The section's text starts with a line holding only a zero-width space (U+200B), with the heading on the next line, and the probe took the first line as its query.
- The probes now take the first line that is non-empty once whitespace and Unicode format characters (category Cf) are stripped (`adr_eval.probes.temporal.first_line`, also used for T2 headings and the T5 title fallback).
- On re-running, only that section's two probes changed (its query is now its heading), and it is found. Pass counts are unchanged (1,176 of 1,176, dedup on and off).

### Determinism

Gov `p2-default` test was re-run in a fresh process. It gave identical rows (items, ranked ids
and exact scores) and an identical summary.

The full determinism criterion X1 is measured in the final write-up.

### Exit criteria (2A)

| # | Criterion | Threshold | gov | research | bench |
|---|---|---|---|---|---|
| A1 | No superseded unit in default top-k | 0 superseded chunks in any default top 10 | **Pass:** T2 default 189/189, T3 default 145/145, T4 297/297, 0 offending chunks | **Pass:** 0 of 2,750 slots (0 by construction) | **Pass:** 0 of 7,280 slots (0 by construction) |
| A2 | `as_of` selects the version in force | 0 chunks from documents not in force on `as_of` | **Pass:** T1 40/40, T2 `as_of` 189/189, T3 `as_of` 145/145, T5 171/171 | No dated documents (R6) | No dated documents (R6) |
| A3 | Dated questions served at least as well | Lower bound > −0.02 on Recall@10 and nDCG@10, `p2-default` against `p1-struct-bc`, test | **Pass**, n 34: Recall@10 +0.000 [+0.000, +0.000]; nDCG@10 +0.254 [+0.182, +0.325] | No `policy_asof` items | No `policy_asof` items |
| A4 | Applicability does not lower non-as-of items | As A3, on `in_force` items (test) | **Pass**, n 158: Recall@10 +0.023 [+0.004, +0.048]; nDCG@10 +0.035 [+0.021, +0.051]. The 21 superseded-only items are reported apart (above) | **Pass**, n 180: +0.000 [+0.000, +0.000] on both (identical rankings) | **Pass**, n 517: +0.000 [+0.000, +0.000] on both (identical rankings) |
| A5 | Regression guard | `p2-identity` identical to the recorded `p1-struct-bc` runs, all items, dev and test | **Pass:** 297 of 297 items | **Pass:** 275 of 275 | **Pass:** 728 of 728 |
| A6 | Dedup does what it says | 0 top-10 slots holding two members of one cluster; clusters and parameters recorded; effect reported | **Pass:** 0 duplicate, cluster and exact-copy slots for `p2-dedup` and `p2-default`, dev and test (Phase 1 test: 1,076 = 44.5%; exact copies 984 = 40.7%) | **Pass:** 0 (Phase 1 test: 1) | **Pass:** 0 (Phase 1: 0) |

On dev, for information:
- gov A3 passes on 6 items (nDCG@10 +0.083 [+0.000, +0.250]);
- gov A4 passes on 35 items (Recall@10 +0.001 [+0.000, +0.004], nDCG@10 +0.004 [+0.000, +0.012]);
- research and bench rankings are identical to Phase 1.

`p2-dedup` fails the A3 comparison on gov (Recall@10 −0.265 [−0.412, −0.118]). A3 is stated
for `p2-default`, so this is not a criterion failure. It is the dated-items row above: dedup
without the date shows the head version.

### Limits

- **Retrieval only.** Answer accuracy under `as_of` is not measured (R1).
- **No ACL layer yet.** The 2A runs search as no caller. Task 8 re-runs them as `user:auditor` and requires identical rows.
- **A3 rests on 34 items, all on gov.** Research and bench have no dated documents, so A2 and A3 say nothing about them. Under `as_of` they return nothing (R6).
- **The eCFR interval is the gap between pinned snapshots** (R4). A date between snapshots gets the earlier snapshot, which may predate an amendment. The IRM pages are current pages.
- **The 21 superseded-only gov items** need golden v0.2 dates to be scored fairly (R3).
- **The v2 copy rule** leaves some identical copies uncredited (4 of the 8 items dedup loses on the superseded-only subset).
- **Small dev splits** (43, 45 and 141 scored items).
- **The §4.6 prototype differs from the build** (exact-only collapse), so its dedup rows are only a rough prediction.
- **One machine;** wall times were taken under shared load.

### Files

`run-summaries/` holds:
- **31 retrieval runs:** the 6 `p1-struct-bc` reference runs, the 24 Phase 2 runs, and the gov `p2-default` test re-run (`…T063055`). Each has `retrieval.md`, and `retrieval.json` without per-item rows.
- **18 `p2-compare` records** (`compare.json`, `compare.md`): slot counts, subset sizes, paired differences and verdicts. They hold no item ids.
- **The two temporal probe runs** (dedup on: `probes-temporal-gov-20261116T070327`; dedup off: `…T070706`), re-run after the T3 fix `5fb86cb`. Only their configuration and pass counts are committed; the probe lists stay local.

Per-item rows, probe sets and anything quoting research or bench text stay local in `runs/`, as
in Phase 1.

```
adr-eval retrieval gov --system p2-default --split test
adr-eval retrieval-identical <p1-struct-bc run> <p2-identity run>
adr-eval p2-compare <p1-struct-bc run> <p2-default run> --store .cache/store-p2/gov
adr-eval probes temporal gov --store .cache/store-p2/gov
```

## 2B: permissions (content tools)

**Verdict.** Every 2B criterion measured here passes for the three content tools, `search`,
`grep` and `read`.
- **No leak** in 853 leak probes (B1): the 840 of spec §10.2, plus 13 for bench's one dedup cluster that crosses access lists. All six leak kinds of spec §10.2 were judged. On these corpora the alternate kind, the filter counts and an ambiguous prefix can barely occur or not at all (see "What the corpus probes can and cannot show"); fixtures and B2 cover those.
- **Filtering equals an allowed-only index** in 12,000 of 12,000 checks (B2). These are 60 reference stores × 50 questions × `search` and `grep` × 2 filter views. Ids and scores are equal at full float precision.
- **Revocation within one sync cycle** passes in all 5 revocation tests (B3), both in a new process and in a long-lived process.
- **Fail closed:** none of the 270 fail-closed probes returned content (B4). That is 90 per corpus. Before the "no entry" rule, the target was visible to every one of the five callers, ranked first in their search, matched by the grep and readable, so those probes could fail.
- **Log fields:** all 26,114 log lines written in steps 2–5 carry `caller`, `principals`, `acl_snapshot` and `acl_decision` (B5). Every allowed line still on disk (20,031) also has a non-null `caller`, `principals`, `acl_snapshot` and `view`.

B1, B3 and B4 cover the content tools only. They are completed in 2C (`search_tools`,
`load_tool`) and 2D (the MCP server), as plan builder note 4 says.

**Step 1 follows a ruling made in this task's review: `p2-identity` means every Phase 2 layer
is off, the ACL layer included.**
- **`p2-identity`** therefore never searches as `p2_caller`. It keeps the Phase 1 matrix-product path, and it is bit-identical to its Task 5 runs and to the `p1-struct-bc` reference runs: A5, 1,300 of 1,300 items.
- **`p2-appl`, `p2-dedup` and `p2-default`** search as `user:auditor` through the ACL layer. Ranked chunk ids and every metric are identical to their Task 5 runs.
- **Their scores** are within the row-exact kernel's difference. The largest absolute difference is 0 on gov, 3.0e-06 on research and 1.8e-05 on bench.
- **Why.** With the ACL layer, the dense channel scores each row with the row-exact kernel `(row * q).sum()` (`f84bfc0`, `c25a437`). That kernel is what makes B2 hold bit for bit against a view-only store. The Phase 1 matrix product `vectors @ q` can differ from it in the last float32 bits.
- **Gov is unaffected** because its fusion weight is `w` = 1.0 (BM25 only).

### What was run

- **No model calls** (ruling R1). Everything ran through `adr_store.tools.Tools`, with the ACL layer, on the scratch copies `.cache/store-p2/<corpus>` at the Phase 1 snapshots (gov `f002821f2cb3…`, research `97c415b1aa71…`, bench `7d8d1f8adda6…`).
- **Callers.** The measured harness caller is `user:auditor` (`config/eval.json` `p2_caller`), except for `p2-identity`, which never uses it (the ruling). The probes call as the directory's users and as `user:ghost`. The directory and policy are the committed ones (`config/acl/`, `directory_sha256` `d83f6043cffc…`, `policy_sha256` `0e3024f237fc…`).
- **ACL freshness.** The Task 6 ACL snapshots (sequence 1) were two hours old, older than `max_sync_age_s` (3,600 s). So every acl=True call would have been denied F3.
  - Each p2 copy was re-synced with `adr acl sync` right before each step. This is an operator action on the scratch copies; the clock was not injected.
  - For the long B2 runs on research and bench, a loop re-synced the p2 copy and its reference stores every 20 minutes, as a deployment's cron would (spec §5.5). That made 70 syncs (42 bench, 28 research), with no error and no access change.
- **Steps** (plan, Task 8):
  1. The 24 `p2-*` runs (4 configurations × 3 corpora × dev and test) re-run. Each was compared with `retrieval-identical` against its Task 5 run, and `p2-identity` also against the `p1-struct-bc` reference runs (A5).
     - `p2-appl`, `p2-dedup` and `p2-default` ran as `user:auditor`.
     - `p2-identity` ran with the ACL layer off, per the ruling; it was re-run once that ruling was made.
  2. B2 with `adr-eval probes equivalence <corpus>`.
  3. and 4. B1 and B4 with `adr-eval probes acl <corpus>`. They were re-run after the review, with the "no entry" precondition and the `alternate-cross-view` family; the numbers here are from that re-run.
  5. B3 with `pytest tests/store/test_revocation.py`.
  6. B5 from every log line written in steps 2–5.
  7. ACL lag from the sync logs.
- **Reference stores** (`adr_eval.probes.equivalence.view_store`). Each holds one view's documents and was built under `.cache/store-p2/views/<corpus>/<view[:12]>`:
  - each document re-ingested from the p2 copy (raw blob, stored text, uri, version and licence); every doc record hashes as the source's;
  - the overlays derived;
  - `p1-struct-bc` indexed with the source's `w_bc` and `w`;
  - one ACL sync from the same directory and policy, so the view's caller sees all of it.

  The auditor's reference store reproduces the source exactly: the same content snapshot and the same index fingerprint (gov `54c12a3c2917…`, research `d3902b136e26…`, bench `8c7bb39d032b…`). All 60 stores were removed after the run. Their content snapshots, index fingerprints and ACL snapshot ids are in each `probes-equivalence-*` and `probes-acl-*` `summary.json` (`config.views`).
- **Destructive probes** (F1, F2, F3, "no entry") ran on `cp -a` clones of the p2 copy, one condition at a time, each removed afterwards.
- **`.cache/store` and `.cache/index` were only read.** The SHA-256 and modification time of all 7,320 files were unchanged after the runs.

### Exit criteria (2B)

| # | Criterion | Threshold | Result |
|---|---|---|---|
| B1 | Zero leaks (content tools; completed in 2C (tools) and 2D (MCP)) | 0 leaks; ≥ 500 probes; ≥ 100 per family | **Pass for `search`, `grep`, `read`:** 853 probes, 0 leaks, 0 invalid. Families: search 450 (+13 `alternate-cross-view`), grep 210, read 180. The `search_tools`/`load_tool` family (200) and the 300 MCP probes follow in 2C and 2D |
| B2 | Filtering equals an allowed-only index | Identical ids and scores | **Pass:** 12,000 of 12,000 identical (3 corpora × 20 views × 50 questions × `search` and `grep` × Phase 1 view and `p2-default` view) |
| B3 | Revocation within one sync cycle (content tools; completed in 2C (tools) and 2D (MCP)) | All revocation tests pass | **Pass for `search`, `grep`, `read`:** 5 of 5. The three change kinds were checked in-process, in a new process and in a `tools_proc` process started before the change, plus F2 and F3. The already-running MCP server leg follows in 2D |
| B4 | Fail closed (content tools; completed in 2C (tools) and 2D (MCP)) | No content in any case | **Pass for `search`, `grep`, `read`:** 270 of 270 (90 per corpus: F1–F5 and "no entry" × 3 tools × 5 callers), 0 with content. "No entry" precondition met for 45 of 45 probes: the target was visible and ranked 1 for each caller beforehand |
| B5 | Every log line carries its principals | 100% | **Pass:** 26,114 of 26,114 lines: B2 24,000, B1 and B4 2,007, B3 107. 0 allowed lines on disk with a null `caller`, `principals`, `acl_snapshot` or `view` |

Not a criterion, but required by the plan (step 1):
- A5 holds bit for bit: `p2-identity`, with every Phase 2 layer off, gives 1,300 of 1,300 items identical to the `p1-struct-bc` references.
- The three other configurations, run as `user:auditor`, give identical ranked ids and metrics in 18 of 18 runs. Their scores are within the row-exact kernel's difference (below).

### Step 1: the 2A runs again

`p2-identity` ran with every Phase 2 layer off, the ACL layer included (the ruling). The
other three configurations searched as `user:auditor`. Each of those resolved the auditor's
access at build and recorded it in its run config (`settings.acl`): the ACL snapshot,
sequence 2, and the view of every document (180, 245 and 2,000).

| Corpus | Configuration | Items (dev / test) | Ranked ids equal | Metrics equal | Items with a score difference (dev / test) | Largest score difference |
|---|---|---|---|---|---|---|
| gov | `p2-identity` (ACL off) | 55 / 242 | all | all | 0 / 0 | 0 |
| gov | `p2-appl`, `p2-dedup`, `p2-default` (auditor) | 55 / 242 | all | all | 0 / 0 | 0 |
| research | `p2-identity` (ACL off) | 53 / 222 | all | all | 0 / 0 | 0 |
| research | each of the three (auditor) | 53 / 222 | all | all | 11 / 55 | 3.0e-06 |
| bench | `p2-identity` (ACL off) | 156 / 572 | all | all | 0 / 0 | 0 |
| bench | each of the three (auditor) | 156 / 572 | all | all | 33 / 132 | 1.8e-05 |

- **A5.** `p2-identity` is identical (ranked ids and exact scores) to the `p1-struct-bc` reference runs: gov 297, research 275 and bench 728 of 728 items.
- **The first round** ran `p2-identity` as the auditor too. It then showed the same score differences as the other three configurations, which led to the ruling.
- **The cause was checked directly before the runs.** On bench dev, the two dense kernels give different top-10 fused rankings or scores for exactly 33 of 156 questions. That is the 33 items above.
- **Why the differences grow.** A 1-ulp difference in a cosine can cross the 6-decimal rounding. Min-max fusion then scales it by the candidate range, hence up to 1.8e-05 after fusion.

### Probe families (B1)

Each leak probe is a (caller, target) pair:
- **Target:** a document or chunk the caller cannot see.
- **Caller:** chosen by seeded hash (20261116) among the directory users with something hidden, and `user:ghost`. The auditor sees every document and has nothing hidden.

Search, grep and read run with `include_superseded`, so applicability masks nothing. Search
runs with dedup on, so alternates are exercised. Each result was judged against:
- the caller's view under the ACL snapshot;
- the caller's reference store, for counts and scores;
- a control call naming an id that does not exist, in the same store as the same caller, for not-found messages.

| Family | Probe | Per corpus | Total | Outcomes (all corpora) | Leaks |
|---|---|---|---|---|---|
| search | Query = the 10 rarest tokens (highest IDF over all chunks) of a hidden chunk | 100 | 300 | 288 answered, 12 denied F4 (`user:ghost`) | 0 |
| search | Query = a hidden document's title (even probes) or first breadcrumb (odd) | 50 | 150 | 150 answered | 0 |
| grep | Pattern = a 30-character substring found in that hidden document only | 50 | 150 | 139 answered, 11 denied F4 | 0 |
| grep | `doc=` a hidden document, by full id (even) or 8-character prefix (odd) | 20 | 60 | 51 "not found", 9 denied F4 | 0 |
| read | A hidden document by full id, by 8-character prefix, a hidden chunk (with a visible document), a hidden document's element; 15 each | 60 | 180 | 168 "not found", 12 denied F4 | 0 |
| search, `alternate-cross-view` | For each dedup cluster whose members have different access lists, each user who sees some members and not others searches the 10 rarest tokens of a visible member | as found: gov 0, research 0, bench 13 | 13 | 13 answered | 0 |
| total | | | 853 | | **0** |

Each probe draws its caller afresh: 19 or 20 callers per family on each corpus, and 12 for
the doc-scoped grep. `user:outsider` appears in every family, and `user:ghost` in every family
but the title family. No 8-character prefix of a hidden document began a visible id, so every
prefix probe of a directory user was answered "not found".

**The six leak kinds**, with the number of probes each was checked on and the number of leaks:

| Leak kind (spec §10.2) | How it is judged | Checked | Leaks |
|---|---|---|---|
| A returned id outside the view | Every hit, scoring chunk, match and read names a document of the caller's view | 590 | 0 |
| An alternate outside the view | Every alternate's document is in the caller's view (only the 13 `alternate-cross-view` probes could fire; see below) | 590 | 0 |
| Text of a hidden document | Every breadcrumb, match, context and read text is the visible document's own. The grep secret appears nowhere in a result or refusal. No refusal holds 8+ hex characters beginning a hidden id the caller did not give | 853 | 0 |
| A not-found message that differs from a nonexistent id's | A full id: byte for byte against an id with the same first 12 characters. A prefix: with the given string replaced | 219 | 0 |
| A count that includes hidden items | `excluded_by_filter`, `short_by`, `truncated` and the number of hits or matches equal the reference store's (in B1 only the number and `truncated` can differ; see below) | 590 | 0 |
| A score that differs from the reference allowed-only index | Hits (ids, full-precision scores, scoring chunks, alternates) and matches equal the reference store's | 590 | 0 |

The checker was tested before the run (`tests/test_probes_acl.py`). Each kind fires on a tool
that leaks it: tools without the ACL layer, an added hidden alternate, a louder not-found
message, a shifted count, a score off by 1e-9, and a refusal naming a hidden id.

**What the corpus probes can and cannot show.** Three of the kinds can barely fire, or cannot
fire at all, on these corpora. They are covered by fixtures instead.

- **An alternate outside the view cannot fire on these corpora.** It needs a dedup cluster whose members have different access lists. There are none on gov (0 of 1,976 clusters) or research (0 of 3), and one on bench (1 of 1: two public chunks and one `tenant:initech` chunk). Chains share access and buckets are keyed by chain, so copies across versions always share a list.
  - The "590 checked" figure above is therefore not evidence for this kind: only the 13 `alternate-cross-view` probes among them could fire.
  - It is covered by the fixture tests: `test_permissions.py`, where a public and a `group:acme/0` document share an exact duplicate, and `test_probes_acl.py`, where a collapse that ignores the view is caught.
  - Bench's one crossing cluster is probed by the extra family `alternate-cross-view`. The 12 acme and globex users and `user:outsider` see its two public members but not the `tenant:initech` one, giving 13 probes.
  - In every one, the visible member ranked 1 and its one alternate was the other public member. The hidden member was never shown, listed or counted.
- **Counts barely move in B1.** B1 runs with `include_superseded`, so `excluded_by_filter` is 0. `short_by` is 0 without a reranker. So the count kind compares only the number of hits or matches and `truncated`.
  - Filter counts are covered by B2's `p2-default` view, which compares `excluded_by_filter` against the reference stores in 3,000 checks.
  - The reviewer's whole-store-count variant (below) passes B1 but is caught there: on gov, 60 of 60 `p2-default` checks differed.
- **An ambiguous 8-character prefix cannot occur on the corpora.** No two document ids share an 8-character prefix on any corpus. So B1 cannot detect an "ambiguous prefix" message that counts hidden ids. That case is covered by the pinned fixture in `test_permissions.py`: two documents sharing the prefix `0913e881`, one visible and one hidden.

**Probe strength: an independent reviewer's check on gov.** The reviewer ran B1's checker,
with 20 probes per family, against deliberately leaky variants of the tools (monkeypatched):

| Leaky variant | Leaks found (of 100) | Caught by |
|---|---|---|
| None (the real tools) | 0 | – |
| Global IDF (one BM25 over the whole store) | 28 | score kind (search families) |
| A prefix resolving among every id, hidden ones included | 37 | id, text, not-found, count and score kinds (grep-doc, read) |
| A not-found message that differs for hidden ids (also a one-space variant) | 37 | not-found kind |
| A hidden chunk id that resolves, with a refusal naming its document | 5 | text and not-found kinds (5 of 5 chunk probes) |
| "Ambiguous prefix" judged over every id | 0 | cannot occur on gov; covered by the fixture |
| Hidden dedup members shown | 0 | cannot occur on gov; covered by the fixtures and `alternate-cross-view` |
| `excluded_by_filter` counted over the whole store | 0 in B1 | B2 (`p2-default` view) |

### B2: equivalence with allowed-only stores

- **Questions.** 50 golden questions per corpus, by seeded hash of the item id (seed 20261116), the same for every view. Gov's sample holds 7 dated `policy_asof` items, searched with their own `as_of` in the `p2-default` view.
- **Grep pattern.** The question's longest word of at least four letters or digits, escaped, case-insensitive.
- **Calls.** Both sides were called with the ACL layer as the view's first user (sorted). That user sees the whole reference store.

| Corpus | Views (documents per view) | Checks | Identical | Search hits compared | Grep matches compared | Empty grep results |
|---|---|---|---|---|---|---|
| gov | 20 (40–93, auditor 180) | 4,000 | 4,000 | 20,000 | 115,268 | 188 |
| research | 20 (46–113, auditor 245) | 4,000 | 4,000 | 20,000 | 147,262 | 60 |
| bench | 20 (436–975, auditor 2,000) | 4,000 | 4,000 | 20,000 | 123,774 | 26 |

- **Views.** Each corpus has 20 distinct views, one per directory user: 18 tenant users, `user:auditor` (everything) and `user:outsider` (`public` only).
- **Phase 1 view** (`include_superseded`, dedup off) and **`p2-default` view** (default filters or the item's `as_of`, dedup on) were each identical in all 6,000 of their checks.
- **What is compared.** Search: rank, chunk, document, span, breadcrumb, score, scoring chunk, alternates, `excluded_by_filter`, `short_by` and the dedup state. Grep: document, span, line, match, context, `truncated` and `excluded_by_filter`.
- No call was refused on either side.

### B4: fail closed

90 probes per corpus: 6 conditions × `search`, `grep`, `read` × 5 callers. The target is one
document per corpus. It is not in a chain, and its uri begins no other document's.

**The target must pass a precondition, so that "no entry" can fail.** Before the rule, each
of the five callers (`user:auditor`, `user:outsider`, `user:initech-0`, `user:globex-3`,
`user:initech-2`) must:
- see it;
- find it in the top 10 of the search query;
- match it with the grep pattern (a 30-character substring found in that document only);
- read it by id.

The builder takes candidates in seeded hash order and checks each with the tools as each
caller (`failclosed_target`, `tools_precheck`). It refuses to build when none qualifies. The
query is the title, else the 10 rarest tokens of the document's first chunk. Candidates are
public, since `user:outsider` must see them.
- **Gov:** a Federal Register document, with the rare-token query (its title did not rank for every caller).
- **Research and bench:** the title.

On all three corpora the target ranked 1 for every caller, grep matched it and read returned
it. The local result rows record `visible_before`, `top10_before` and `rank_before` per probe:
"visible before" and "top 10 before" are 45 of 45 for the "no entry" probes (and for F1–F3).
A tool that ignores the rule now fails all 15 "no entry" probes (tested).

| Condition | How it was produced | Callers | Per corpus | Result (3 corpora) |
|---|---|---|---|---|
| F1 | A clone: `acl/HEAD` missing, `acl/HEAD` unreadable (a directory), an unparsable snapshot, a schema-invalid one (`sequence` 0), a snapshot file whose hash is not its id. One variant per caller | `user:auditor`, `user:outsider`, `user:initech-0`, `user:globex-3`, `user:initech-2` | 15 | 45 denied F1, 0 content |
| F2 | A clone with a new content snapshot (the target dropped) | as F1 | 15 | 45 denied F2, 0 content |
| F3 | A clone synced with the clock 2 h behind (3 callers) or 1 h ahead (2 callers); real clock in the tools | as F1 | 15 | 45 denied F3, 0 content |
| F4 | The p2 copy | `None`, `user:ghost`, `user:nobody`, `user:acme-6`, `user:auditor2` | 15 | 45 denied F4, 0 content |
| F5 | The p2 copy | `group:acme/0`, `public`, `user:`, `user:Ghost`, `tenant:acme` | 15 | 45 denied F5, 0 content |
| "no entry" | A clone re-synced from the policy plus an attribute rule mapping the target's uri to `[]`. Only the target's access changed | as F1 | 15 | 30 answered without the target, 15 `read` refused exactly as a nonexistent id; 0 content |

A probe passes only on:
- the expected code with nothing returned, and a refusal that holds neither the target's secret substring nor, for search and grep, its id;
- for "no entry": no hit, alternate, scoring chunk or match of the target, its 30-character substring nowhere, and `read` refused byte for byte as an id that names nothing.

### B3 and B5

- **B3.** `tests/store/test_revocation.py` passes (5 of 5, 10 s). It covers three change kinds: a user removed from a group, a document's rule changed by an attribute rule, and a user deleted. Steps 1–5 of §12 are checked in-process, in a new process and in a `tools_proc` process started before the change. Two further tests: a new content snapshot denies all until a sync (F2), and a stale snapshot denies all (F3, injected clock).
- **B5.** Every log line written in steps 2–5 has the four fields:
  - B2: 24,000 lines;
  - B1 and B4: 2,007 lines (1,738 allowed; denied F1 45, F2 45, F3 45, F4 89, F5 45);
  - B3: 107 lines in the tests' stores (78 allowed, 9 F2, 6 F3, 9 F4, 5 `off` for the operator's `index` calls).
- **Allowed lines must be resolved.** The scan was tightened after the review: an `allowed` line must also have a non-null `caller`, `principals`, `acl_snapshot` and `view`. A denied line may hold nulls where access was not resolved, as specified; an `off` line has no ACL layer. 0 allowed lines fail this:
  - the B1 and B4 re-run (1,738 allowed);
  - the B3 logs (78);
  - a re-scan of the p2 copies' logs over Task 8's first window, 08:54–11:36 UTC (18,215 allowed of 18,373 lines: step 1, B2's store side, the first B1/B4 run).
- **What was not re-scanned.** The B2 reference stores' 12,000 lines and the first run's clone logs were removed with their stores. They were checked for the four fields only.

### ACL lag (spec §5.5)

- **Sync durations.** The 16 syncs of the p2 copies in this task took 0.29–1.52 s: 12 by hand and 4 by the periodic loop. All 70 periodic re-syncs, of p2 copies and reference stores, took at most 0.82 s. That was with the probes running beside them.
- **Logged `lag_s`.** On those syncs, `lag_s` (HEAD swap minus the newer modification time of the directory and the policy) was 6,939–18,314 s. That is the time since the committed config files were checked out, not a propagation delay: nothing changed.
- **Lag after a real change.** It was measured on `cp -a` clones: `user:acme-4` was removed from `group:acme/1` in a copy of the directory and one sync run at once. The swap came 0.99 s (gov), 0.22 s (research) and 0.77 s (bench) after the change, essentially the sync duration. The user lost 5, 7 and 43 documents.
- **Bound.** By §5.5 the lag is at most one sync cycle after the change. Phase 2 runs syncs on demand; between a change and the next sync, access stays the old one for at most `max_sync_age_s` (3,600 s), after which every call is denied F3.

### Machine and wall times

The same machine as 2A: 4-core Intel Xeon at 2.10 GHz, 15 GB of memory, Python 3.13.18.

| Step | Wall time | Notes |
|---|---|---|
| 1: 24 re-runs | 17.4 min | Four at a time; per-run wall times 66–330 s, in each run's `retrieval.json` |
| 1: `p2-identity` re-run (ACL off) | 5.9 min | Six runs, three at a time, after the ruling; per-run 55–352 s |
| 2: B2 gov | 36.3 min | Includes building 20 reference stores |
| 2: B2 research | 33.4 min | Parallel with B2 bench and B1 gov for part of the time |
| 2: B2 bench | 46.8 min | Parallel with B2 research and B1 research |
| 3 and 4: B1 + B4 (re-run) | 10.5 min (gov), 11.4 (research), 10.2 (bench) | One corpus at a time; includes building the 20 reference stores, then removing them. The first run, which reused the B2 stores, took 8.6, 6.5 and 6.8 min |
| 5: B3 | 10 s | |
| Test suite | 4 min | 1,462 tests, under the load of the B2 runs |

- **Disk.** The 20 reference stores took 0.83 GB on gov, about 4 GB on research (PDF blobs) and 0.99 GB on bench. At most about 5 GB were in use at once, when research and bench were both built.

### Limits

- **Content tools only.** B1, B3 and B4 do not yet cover `search_tools`, `load_tool` or the MCP server (2C, 2D). B1's 300-probe MCP subset is also 2D.
- **Two dense kernels, one per path (the ruling).** `p2-identity` keeps the Phase 1 matrix product, because it is every Phase 2 layer off, the ACL layer included. So A5 holds bit for bit against the recorded runs. The configurations searching as a caller use the ACL layer's row-exact kernel, because B2 requires scores independent of the other rows: a full view of a reference store is not a full view of the source when a document has an empty list. Their scores therefore differ from the 2A runs in the 6th decimal on 66 research and 165 bench items per configuration, with no ranked id or metric changed.
- **The leak probes judge what the content tools return,** not timing or resource side channels. Per-view BM25 removes the IDF channel by construction (§6.2). B2 checks that within the scores.
- **The fail-closed probes use one target per corpus.** The F1–F5 decision is made per call before any document is touched, so the target matters only for "no entry".
- **One policy.** Phase 2 ships no attribute rules: every document's list comes from the buckets, so no view splits a chain. The probe policy adds one rule for "no entry" only.
- **One machine;** the B2 and B1 runs overlapped in part, so wall times were taken under shared load.

### Files

`run-summaries/` holds:
- **The step 1 re-runs**, as `retrieval.md` and `retrieval.json` without per-item rows:
  - `p2-appl`, `p2-dedup` and `p2-default` as the auditor (`…T08*`/`T09*`), each with `config.settings.acl` recording the caller's ACL snapshot and view;
  - `p2-identity` with the ACL layer off (`…T11*`).
- **The probe runs** `probes-equivalence-<corpus>-*` (B2) and `probes-acl-<corpus>-*` (B1, B4, B5). Each has `summary.json` and `summary.md`: configuration, the reference stores' snapshot ids, counts and log-field scans. They hold no probe lists, queries or corpus text.
- **`acl-2b-checks/auditor-reruns.json`:** the identity counts of step 1.
- **`acl-2b-checks/checks.json`:** the p2 copies' sync log entries, the periodic re-syncs, the lag measured after a directory change, the B3 log scan, the B5 re-scan with the allowed-line fields, and the read-only check of the real stores.

The probe sets (`probes.json`, byte-identical across runs of the same store; tested), the
per-probe results and the per-check B2 rows stay local in `runs/`.

```
adr acl sync --store .cache/store-p2/gov
adr-eval retrieval gov --system p2-default --split test         # as config p2_caller (user:auditor)
adr-eval probes equivalence gov --store .cache/store-p2/gov --keep-views
adr-eval probes acl gov --store .cache/store-p2/gov             # reuses, then removes, the reference stores
pytest tests/store/test_revocation.py
```

## 2C: tools as data

**Verdict.** All three 2C criteria pass. B1, B3, B4 and B5 now also pass for the two tool tools, `search_tools` and `load_tool`.
- **C1.** 14,059 real tool records were ingested from ToolRet's `toolbench` pool, with 100% adapter conformance (Task 9).
- **C2.** Loading the top 10 tools uses 99.848% fewer tokens than loading the whole catalog, on average over the 888 test queries (threshold 80%). An agent loads 1,240 tokens per query instead of 816,284.
- **C3.** The chosen system, `tools-hybrid`, has a test Completeness@10 of 0.411, against 0.384 for `tools-bm25-raw`. The difference is +0.027, with a 95% interval of [+0.002, +0.053]. The point estimate is at least the baseline's, and the lower bound is above −0.02.
- **B1.** 200 tool leak probes found 0 leaks. With the content tools, that makes 1,053 leak probes over all five tools, all with 0 leaks.
- **B3.** The 5 tool revocation tests pass. All 10 revocation tests pass in all.
- **B4.** None of the 80 tool fail-closed probes returned content. With the content tools, that makes 350 fail-closed probes, none with content.
- **B5.** All 461 log lines written by the tool probes and tool tests carry their principals.

Three results need care when reading these numbers:
- **The C3 margin is thin.** The interval's lower bound is +0.002. On test, `tools-hybrid` completes 80 queries that the baseline misses, and misses 56 that the baseline completes.
- **Both systems chose `w_name` 3, the edge of the spec's grid {0, 1, 2, 3}.** The grid was not extended (see the tuning table). A larger name weight might do better on dev. That is a limit of the grid, not a measured optimum.
- **The gold share is low: 6.3%.** On average, only 6.3% of the tokens an agent loads are definitions of gold tools. C2 measures how small the loaded context is, not how much of it is useful (see "Tool context").

### What was run

- **No model calls** (ruling R1). The only model was the local embedding model, `BAAI/bge-small-en-v1.5`.
  - It is the ONNX file already in `.cache/fastembed` (hash `51f1bd0addd6…`), the one Phase 1 uses, and it was run through the store's embedding cache.
  - Every command ran with `HF_HUB_OFFLINE=1`, so nothing could be downloaded. Nothing was.
- **Store.** Everything ran on the tools-only scratch store `.cache/store-p2/toolret`:
  - the tool snapshot `51536a400bba…` (14,059 records);
  - the empty content snapshot `de13b4a8eeac…`;
  - ACL snapshots from the committed directory and policy (`entries_sha256` `3906197e26ef…` on every sync).
- **`.cache/store` and `.cache/index` were only read.** The SHA-256 and modification time of all 7,320 files were unchanged after the runs.
- **Steps** (plan, Task 11):
  1. **Indexing.** The lexical-only `tools-bm25f` index (`8b4e2e07cfd5…`, `w_name` 3) existed from Task 10 and was loaded. The `tools-hybrid` index needed the 14,059 dense texts embedded once. That happened inside the `tools-hybrid` dev run, whose tuning builds the base index, with `--threads 0` (vectors do not depend on the thread count). Its tuned index is `c93ceea6fae2…` (`w_name` 3, `w` 0.6).
  2. **Tuning, dev runs and test runs.** Both systems were tuned on dev nDCG@10 (planner's call 15), over the spec's grid only: `w_name` ∈ {0, 1, 2, 3}, and for `tools-hybrid` also `w` ∈ {0, 0.05, …, 1}. Ties go to the smallest values. All three systems ran on dev. The best Phase 2 system on dev Completeness@10, `tools-hybrid`, ran on test, and so did `tools-bm25-raw`. Each run was `adr-eval tools-retrieval … --sync`, searching through `Tools.search_tools` and `load_tool` as `user:auditor`.
  3. **C2 and C3** were computed from the two test runs' per-query rows (`tools-2c-checks/checks.json`). C3 uses the paired bootstrap of `adr_eval.scoring.stats`: 10,000 resamples, seed 20261108, chosen minus baseline.
  4. **Probes.** The probes ran with `adr-eval tools-probes --index c93ceea6fae2`, after `adr acl sync` (sequence 9), against the chosen system's index, which was active since its runs. That covered B1 (200 leak probes), B4 (80 fail-closed probes on `cp -a` clones, each removed afterwards) and B5 (their log lines). B3 ran with `pytest tests/store/test_revocation.py`.
  5. **Determinism.** The `tools-hybrid` test run was repeated in a fresh process.
- **Active tool index.** `tools-retrieval` makes the tuned index active and records the change in each run. The records read `8b4e2e07cfd5 → 8b4e2e07cfd5` (bm25f dev), `8b4e2e07cfd5 → c93ceea6fae2` (hybrid dev), then `c93ceea6fae2 → c93ceea6fae2` (both hybrid test runs). The probes and the latency measurement ran on `c93ceea6fae2`.
- **ACL freshness.** Each store run's `--sync` and the sync before the probes kept the snapshot within `max_sync_age_s`. That was 5 syncs (sequences 5–9), taking 0.75–1.23 s each, with no access change.

### Tuning (dev, 212 queries, nDCG@10)

`tools-bm25f` (lexical only) and `tools-hybrid` (each `w_name` at its best `w`, plus the two ends of the `w` range):

| `w_name` | `tools-bm25f` | `tools-hybrid`: best `w` | nDCG@10 at best `w` | at `w` = 1 (BM25 alone) | at `w` = 0 (dense alone) |
|---|---|---|---|---|---|
| 0 | 0.3906 | 0.45 | 0.5076 | 0.3906 | 0.4551 |
| 1 | 0.5347 | 0.60 | 0.5732 | 0.5347 | 0.4551 |
| 2 | 0.5398 | 0.60 | 0.5798 | 0.5398 | 0.4551 |
| 3 | **0.5422** | 0.60 | **0.5826** | 0.5422 | 0.4551 |

- **Chosen values.** `tools-bm25f` chose `w_name` 3. `tools-hybrid` chose `w_name` 3 and `w` 0.6. Both rows at `w` = 1 reproduce `tools-bm25f`, as they should.
- **Along `w` at `w_name` 3,** nDCG@10 rises from 0.455 at `w` = 0 to 0.583 at `w` = 0.6, then falls to 0.542 at `w` = 1. The fusion weight is an interior optimum.
- **Grid edge.** `w_name` 3 is the largest value of the spec's grid, and the gain is still rising there, though slowly: +0.0024 and +0.0028 from `w_name` 2 to 3. The grid was not extended (the spec fixes it). So the chosen `w_name` is the grid's limit, not a measured optimum.
- **Tuning matched the evaluation.** The tuning table ranks with the index itself, while the evaluation searches through `search_tools` as the auditor. The evaluated dev nDCG@10 of both systems equals their tuning value: 0.542 and 0.583.

### Retrieval

**Dev (212 queries).** This is the table the system was chosen from.

| System | Completeness@10 | Recall@10 | nDCG@10 | Loaded tokens (mean) | Reduction | Gold share |
|---|---|---|---|---|---|---|
| `tools-bm25-raw` | 0.396 | 0.592 | 0.516 | – (top 10 raw documents: 1,075) | – | – |
| `tools-bm25f` (`w_name` 3) | 0.425 | 0.630 | 0.542 | 1,136 | 99.861% | 0.063 |
| `tools-hybrid` (`w_name` 3, `w` 0.6) | **0.458** | **0.656** | **0.583** | 1,197 | 99.853% | 0.065 |

`tools-hybrid` has the best dev Completeness@10, so it is the chosen system. `tools-bm25f` was not run on test.

**Test (888 queries).** 95% bootstrap intervals in brackets (10,000 resamples, seed 20261108). Differences are paired (chosen minus baseline).

| System | Completeness@10 | Recall@10 | nDCG@10 |
|---|---|---|---|
| `tools-bm25-raw` | 0.384 [0.352, 0.417] | 0.578 [0.553, 0.603] | 0.509 [0.485, 0.532] |
| `tools-hybrid` | 0.411 [0.378, 0.444] | 0.603 [0.578, 0.629] | 0.529 [0.505, 0.553] |
| Difference | **+0.027 [+0.002, +0.053]** | +0.025 [+0.006, +0.044] | +0.021 [+0.005, +0.037] |
| Queries better / worse | 80 / 56 | 143 / 110 | 309 / 252 |

- **The baseline matches the spec's probe.** Over all 1,100 queries (Task 10), it gives Completeness@10 0.3864 and Recall@10 0.581, the spec's 0.386 and 0.581. On test it gives 0.384.

### Exit criteria (2C)

| # | Criterion | Threshold | Result |
|---|---|---|---|
| C1 | At least 1,000 real tool records | 14,059 ingested, 100% adapter conformance | **Pass:** 14,059 records (13,862 `toolbench_tool_*` of config `web`, 197 `toolbench_sam_tool_*` of config `customized`), 100% structural conformance, the same tool snapshot `51536a400bba…` on every ingest (Task 9). The 20 OpenAPI specs (129 operations) and the 3 MCP reference servers (15 tools) also ingest at 100% (conformance only) |
| C2 | Tool-context reduction | Mean over test ≥ 80% (expected > 99%) | **Pass:** 99.848% (lowest per query 99.378%). Loaded 1,240 tokens per query (median 1,082, range 520–5,081), against a catalog of 816,284 definition tokens. Gold share 0.063 |
| C3 | Tool search at least as complete as BM25 | Point estimate ≥ the baseline's, and the paired lower bound > −0.02 | **Pass:** `tools-hybrid` 0.411 against `tools-bm25-raw` 0.384 on test. The difference is +0.027 [+0.002, +0.053] |

**Two Task 9 details about C1's records**, from that task's review:
- **Cutting `$ref` cycles changed records, not just the token totals.** The cut happens where a `$ref` repeats on its branch, plus a depth limit of 8 and a budget of 10,000 nodes per operation. It also shrank output schemas, which `definition_tokens` does not count. For example, the output schema of lgtm.com's `getHealth` went from 4,290 to 538 bytes. The token totals (60,629 definition tokens over the 129 operations) show only the input side.
- **`updateLodging` is genuinely large.** The largest OpenAPI record, googleapis `mybusinesslodging.locations.updateLodging`, is 27,768 tokens. Its schema has no cycle; it expands to 1,652 nodes of long descriptions, so the cycle cut did not change it.

### Tool context (C2)

The definitions follow spec §8.4 and `adr_eval.tools_eval`. Tokens are counted as the harness counts them (`chunker._count`).
- **`loaded`** is the tokens of the canonical JSON of the `search_tools` result (the page) plus the canonical JSON of the `load_tool` definitions of its hits (at most 10).
- **`catalog`** is the sum of every record's `definition_tokens`: 816,284. That is the MCP Tool definitions (name, description, `inputSchema`), not the 1,227,462 tokens of raw ToolRet documentation.
- **Reduction** is `1 − loaded / catalog`, averaged over queries.
- **Gold share** is the mean over queries of (loaded definition tokens of gold tools) ÷ (loaded tokens). Page entries are not counted as gold, even for gold hits.

| Test, `tools-hybrid` | Mean | Notes |
|---|---|---|
| Page (`search_tools` result) | 494 tokens | 40% of what is loaded |
| Definitions (top 10 `load_tool`) | 746 tokens | |
| Loaded | 1,240 tokens | median 1,082; min 520; max 5,081 |
| Catalog | 816,284 tokens | every definition |
| Reduction | 99.848% | min 99.378%, max 99.936% |
| Gold tools loaded | 1.37 of 2.38 gold tools per test query | 180 of 888 queries load no gold tool |
| Gold share | 0.063 (median 0.047) | pooled over all queries (gold tokens ÷ loaded tokens): 0.067 |

- **Most of the loaded context is not gold.** An agent that loads the top 10 still spends about 94% of those tokens on tools it will not use. A lower `top` would trade gold share against Completeness@10; it was not measured here.
- **Comparison with the raw baseline.** `tools-bm25-raw`'s top 10 raw documents average 1,123 tokens on test, which is the same order as the 1,240 tokens loaded here. Those are raw ToolRet strings, not MCP definitions plus a page, so the two are not the same quantity.

### B1, B3, B4 and B5 for the tool tools

**Leak probes (B1).** Each probe is a (caller, target) pair: a tool the caller cannot see, with the caller drawn by seeded hash (20261116) among the directory users and `user:ghost`.
- Each result was judged against the caller's tool view under the ACL snapshot.
- Search results were also compared with a reference index of the caller's visible tools only (`ToolIndex.subset`, with the row-exact dense kernel). That comparison covers ids, full-precision scores, the number of hits and `excluded_by_filter`.

| Family | Probe | Probes | Outcomes | Leaks |
|---|---|---|---|---|
| `tool-search`, unfiltered | Query = a hidden tool's name and summary | 60 | 56 answered, 4 denied F4 (`user:ghost`) | 0 |
| `tool-search`, filtered | The same, with `source_kind` `["mcp"]` (excludes the whole view) or `["mcp", "toolret"]` (admits it), alternately | 40 | 38 answered, 2 denied F4 | 0 |
| `tool-load` | `load_tool` of a hidden tool by full id (even) or 8-character prefix (odd), with a control id or prefix that names nothing | 100 (50 + 50) | 96 "not found", byte for byte as the control; 4 denied F4 | 0 |
| total | | 200 | | **0** |

- **Kinds checked** (the kinds of spec §10.2 that apply to the tool tools):
  - search: 94 probes each for id outside the view, count and score; 100 for hidden text;
  - load: 96 for the not-found message; 100 for hidden text.
- **Callers.** The families drew 20 and 19 distinct callers, with `user:outsider` and `user:ghost` in both.
- **Probe strength.** The tool checker's power against leaky variants was measured in Task 10's review: 19 to 96 leaks found per variant, and 0 on the real tools.

**Fail closed (B4).** 80 probes: 8 conditions × 2 tools × 5 callers.
- **The target.** A tool every fail-closed caller sees, that ranked 1 in its name-and-summary search for each of them and that each could load before any change. The `before` fields record this: rank 1 for all 60 probes of the six conditions on a directory caller.
- **The callers** are those of 2B: `user:auditor`, `user:outsider`, `user:initech-0`, `user:globex-3` and `user:initech-2` (F4 and F5 have their own callers).

| Condition | How it was produced | Probes | Result |
|---|---|---|---|
| F1 | A clone with `acl/HEAD` missing, unreadable, unparsable, schema-invalid, or naming a snapshot whose hash is not its id | 10 | 10 denied F1 |
| F2 | A clone with a new content snapshot (one note added) after the sync | 10 | 10 denied F2 |
| F3 | A clone synced with the clock 2 h behind or 1 h ahead | 10 | 10 denied F3 |
| F4 | The store; callers `None`, `user:ghost`, `user:nobody`, `user:acme-6`, `user:auditor2` | 10 | 10 denied F4 |
| F5 | The store; malformed or non-user callers | 10 | 10 denied F5 |
| "no entry" | A clone re-synced with an attribute rule mapping the target's uri to `[]` (only the target's access changed) | 10 | 5 `search_tools` answered without the target; 5 `load_tool` refused exactly as a nonexistent id |
| `F2-tools` (Task 10) | A clone with a tool snapshot committed after the sync, without the target | 10 | 10 denied F2 |
| `no-tool-snapshot` (Task 10) | A clone whose ACL snapshot was synced while the catalog was moved away (`tool_snapshot` null), then the catalog restored | 10 | 10 denied F2 |
| total | | 80 | 80 passed, 0 with content |

**Revocation (B3).** `tests/store/test_revocation.py` passes: 10 of 10 in 14 s, the 5 content tests of 2B and 5 tool tests.
- **The three change kinds** run on both tool tools: a user removed from a group, a tool's rule changed in the policy, and a user deleted.
- **Each test checks** that before the sync the tool is unchanged, and that after one sync it is invisible in-process, in a new process (the new-process leg) and in a `tools_proc` process started before the change (the long-lived leg).
- **Two further tests:** a new tool snapshot denies both tool tools (F2) until a sync, while the content tools are unaffected; and a stale snapshot denies them (F3).

**Log fields (B5).** Every line carries `caller`, `principals`, `acl_snapshot` and `acl_decision`. Every allowed line also has a non-null `caller`, `principals`, `acl_snapshot` and `view`: the same rule as 2B's `scan_log`.
- **The probe run: 381 lines,** 301 allowed. Denials: F1 10, F2 30, F3 10, F4 20, F5 10. That is 316 lines in the store and 65 in the clones.
- **The tool revocation tests: 80 lines,** 54 allowed. Denials: F2 6, F3 4, F4 6. There are 10 `off` lines, for the operator's `index` and `tools_index` calls.
- **Beyond B1–B4,** every line written to the store's log during this task also passes: 26,734 lines, 26,700 allowed, 0 unresolved. That includes the four store-backed `tools-retrieval` runs (24,204 lines), the probes' precheck and the latency measurement.

**B totals over the five tools.** The content counts are 2B's (Task 8); the tool counts are this task's.

| Family (spec §10.2) | Content tools (2B) | Tool tools (2C) | Total | Spec §10.2 |
|---|---|---|---|---|
| search (rare tokens 300, title 150, `alternate-cross-view` 13) | 463 | – | 463 | 450 |
| grep (literal 150, doc-scoped 60) | 210 | – | 210 | 210 |
| read | 180 | – | 180 | 180 |
| `search_tools` / `load_tool` (100 + 100) | – | 200 | 200 | 200 |
| **Leak probes (B1)** | **853** | **200** | **1,053** | **1,040** |
| Fail closed (B4) | 270 (6 conditions × 3 tools × 5 callers × 3 corpora) | 80 (8 conditions × 2 tools × 5 callers) | **350** | 150 (90 content + 60 tools) |
| **All probes** | **1,123** | **280** | **1,403** | **1,190** |
| Leaks / fail-open | 0 / 0 | 0 / 0 | **0 / 0** | 0 |
| B5 log lines (B1–B4) | 26,114 | 461 | 26,575 | 100% complete |
| B3 revocation tests | 5 | 5 | 10 | all pass |

- **Why there are 213 more probes than the spec's 1,190:**
  - **+180:** Task 8 ran the content fail-closed set on each of the three corpora (90 each), where the spec counted 90 once.
  - **+13:** Task 8 added the `alternate-cross-view` leak family on bench.
  - **+20:** Task 10 added the two tool-snapshot conditions (`F2-tools`, `no-tool-snapshot`).
- **Family sizes.** Every family of §10.2 has at least 100 probes: search 463, grep 210, read 180, the tool family 200 (each of its two halves 100), fail closed 350.
- **Still to come.** The 300-probe MCP subset of B1 and the MCP leg of B3 follow in 2D.

### Determinism

- **The `tools-hybrid` test run, repeated in a fresh process, gave identical rows, summary and tuning table** (`…T153716` and `…T154432`).
- **Only two config fields differ.** One is `started`. The other is `acl_snapshot`, because each `--sync` writes a new snapshot: sequences 7 and 8, with the same `entries_sha256` `3906197e26ef…` and no access change.
- **Both test runs loaded the same tool index** (`c93ceea6fae2…`), built once in the dev run.

### Latency

Latency was measured in a fresh process per caller, through `Tools(acl=True)` on `c93ceea6fae2`, over the first 101 test queries. That is the first call, then 100 searches and the 1,000 `load_tool` calls of their top 10.

| Caller (visible tools) | First `search_tools` (index and model load) | `search_tools` median / p95 | `load_tool` median / p95 |
|---|---|---|---|
| `user:auditor` (14,059) | 2.23 s | 191 / 251 ms | 23 / 31 ms |
| `user:initech-0` (6,238) | 2.65 s | 117 / 159 ms | 16 / 22 ms |

- **Search** includes embedding the query and scoring the visible rows with the row-exact kernel, so it scales with the view.
- **Lexical-only `tools-bm25f`** searched in 33–73 ms (Task 10).
- **`load_tool`** resolves the caller's tool view again on every call (Task 10), hence about 20 ms.

### Machine and wall times

The same machine as 2A and 2B: 4-core Intel Xeon at 2.10 GHz, 15 GB of memory, Python 3.13.18. Runs were one at a time unless noted.

| Step | Wall time | Notes |
|---|---|---|
| `tools-bm25-raw` dev / test | 6.7 s / 14.1 s | |
| `tools-bm25f` dev | 95 s | Tuning 4 `w_name` values, then 212 searches and 2,120 loads |
| `tools-hybrid` dev | 35.7 min | Of this, embedding the 14,059 tool texts took 32.5 min (first vector 15:01:08, last 15:33:38 UTC; 4 ONNX threads; the B3 run and the real-store hashing overlapped for about a minute) |
| `tools-hybrid` test (and re-run) | 7.0 min (7.5 min) | Re-tuning on dev from cached vectors, then 888 searches and 8,880 loads |
| Tool probes (200 + 80) | 2.3 min | Including 6 `cp -a` clones of the store, made and removed one at a time |
| B3 | 14–29 s | 10 tests |
| Test suite | 4.4 min | 1,660 tests, `pytest -q -W error`; `ruff check .` clean |

- **Disk.** 9.8 GB were free at the start. The 14,059 vectors took 55 MB in `.cache/emb`. The store grew from 137 MB to 205 MB: the hybrid index is 33 MB (vectors and rows), and the rest is log lines. Each fail-closed clone was about 200 MB, one at a time.

### Limits

- **Grid edge.** Both Phase 2 systems chose `w_name` 3, the largest value of the spec's grid. The grid was not extended, so a larger name weight is untested.
- **A thin C3 margin, on one split.** The lower bound is +0.002, and the dev split that chose the system is small (212 queries). `tools-bm25f` was not run on test, by the selection rule.
- **The filter probes are degenerate on this store.** Every record is `source_kind` `toolret`, so `["mcp"]` excludes the whole view and `["mcp", "toolret"]` admits all of it. Mixed catalogs are covered by the fixture tests.
- **Synthetic views.** Tool access comes from the committed bucket rule (spec §5.2): public 2,832, two tenants 1,392, one tenant 6,337, one group 3,498. It is not a real organisation's shape.
- **One fail-closed target.** As in 2B, F1–F5 are decided per call before any tool is touched, so the target matters only for "no entry".
- **The probes judge what the tools return,** not timing side channels. Search latency scales with the view size (see "Latency").
- **No `toolbench_sam` tool is gold.** The 197 are distractors only, so C3 says nothing about retrieving them.
- **A leftover file.** The tool fail-closed run removes its clones but left the 551-byte "no entry" policy in `.cache/store-p2/clones/tools/`. It was removed by hand; it holds one ToolRet `source_uri` and is git-ignored.
- **One machine.**

### Licence (ToolRet, Q2)

- **ToolRet is local-only** (ruling R13, question Q2). Nothing from it is committed: no queries, tool names or descriptions. Only pinned revisions, hashes, run configs, summaries and counts are committed. Per-query rows, probe sets and probe results stay in `runs/`.
- **The 13,862 `toolbench_tool_*` tools (config `web`)** are ToolBench's RapidAPI endpoint documentation, under Apache-2.0 (the ToolBench README).
- **The 197 `toolbench_sam_tool_*` tools (config `customized`) are not RapidAPI data, and their licence is unclear.** They are Python-library function descriptions (spreadsheet and DataFrame methods) and curl commands, from a different upstream. Checked in this task:
  - the ToolRet-Tools and ToolRet-Queries dataset cards at the pinned revisions;
  - the parquet files' metadata (only the Hugging Face feature schema);
  - the ToolRet code README.

  None names their upstream or a licence. Their content matches SambaNova's ToolBench (Xu et al., 2023), whose repository carries an Apache-2.0 LICENSE on its default branch. That attribution is our inference; ToolRet does not state it.
- **Their records still say Apache-2.0.** The records' `license` field reads "Apache-2.0" for all 14,059, because `corpora/tools/config.json` gives one licence for the pool; changing it would change the tool snapshot. Spec §8.3 and `corpora/tools/README.md` were corrected in this task to say this.
- **The ToolRet dataset cards declare no licence for any of the data,** which is why it stays local.

### Files

`run-summaries/` holds:
- **The tool runs**, as `tools.json` (config, tuning table and summary, without per-query rows) and `tools.md`:
  - `tools-tools-bm25-raw-dev-20261116T145901`, `tools-tools-bm25f-dev-20261116T145907`, `tools-tools-hybrid-dev-20261116T150058`;
  - `tools-tools-bm25-raw-test-20261116T153702`, `tools-tools-hybrid-test-20261116T153716`;
  - the determinism re-run `tools-tools-hybrid-test-20261116T154432`.
- **`probes-tools-20261116T155230/`:** `summary.json` and `probes.md` for B1, B4 and B5 (configuration, tool index, ACL snapshot, counts and log scans). They hold no probe lists or ToolRet text.
- **`tools-2c-checks/checks.json`:**
  - the C2 and C3 numbers (with intervals and per-query win counts);
  - the determinism comparison;
  - the embedding timing;
  - the B3 run and its log scan;
  - the B5 scan of every log line written in this task;
  - latency;
  - the syncs;
  - the read-only check of the real stores;
  - the licence check.

Per-query rows (`tools.json` in `runs/`), the probe set (`probes.json`) and the per-probe results stay local.

```
adr-eval tools-retrieval --system tools-bm25-raw --split dev
adr-eval tools-retrieval --system tools-bm25f   --split dev  --store .cache/store-p2/toolret --sync
adr-eval tools-retrieval --system tools-hybrid  --split dev  --store .cache/store-p2/toolret --sync --threads 0
adr-eval tools-retrieval --system tools-hybrid  --split test --store .cache/store-p2/toolret --sync --threads 0
adr-eval tools-retrieval --system tools-bm25-raw --split test
adr acl sync --store .cache/store-p2/toolret
adr-eval tools-probes --store .cache/store-p2/toolret --index c93ceea6fae2
pytest tests/store/test_revocation.py
```
