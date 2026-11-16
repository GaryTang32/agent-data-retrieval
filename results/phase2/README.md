# Phase 2 results: applicability, permissions, tools as data and an MCP server

> **Work in progress.** Only part 2A (applicability and duplicates) is measured so far. These
> numbers were recorded on 16 November 2026 under version 2 of the metric definitions, with
> golden sets v0.1. Parts 2B (permissions), 2C (tools as data) and 2D (the MCP server) follow in
> their own sections.

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
