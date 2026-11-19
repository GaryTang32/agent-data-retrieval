# Phase 2 comparison: p2-dedup minus p1-struct-bc

Run `gov-p2-dedup-dev-retrieval-20261116T060357` minus run `gov-p1-struct-bc-dev-retrieval-20261116T055053` on `gov` / `dev`. Store `.cache/store-p2/gov` (snapshot `f002821f2cb3`), applicability overlay `4c81d25fe905`, dedup overlay `6fb05917038e`. Paired bootstrap 95% CIs (10000 resamples, seed 20261108); non-inferiority margin 0.02: a metric passes when the lower bound is above -0.02.

| subset | n | Recall@10 | nDCG@10 | MRR | verdict |
|---|---|---|---|---|---|
| asof | 6 | 0.833 -> 0.500 (-0.333 [-0.667, +0.000]) | 0.750 -> 0.438 (-0.312 [-0.667, +0.044]) | 0.722 -> 0.417 (-0.306 [-0.667, +0.056]) | fail |
| in_force | 35 | 0.702 -> 0.732 (+0.030 [+0.000, +0.088]) | 0.698 -> 0.711 (+0.013 [+0.000, +0.035]) | 0.729 -> 0.734 (+0.004 [+0.000, +0.013]) | pass |
| superseded_only | 2 | 1.000 -> 0.500 (-0.500 [-1.000, +0.000]) | 1.000 -> 0.500 (-0.500 [-1.000, +0.000]) | 1.000 -> 0.500 (-0.500 [-1.000, +0.000]) | fail |
| scored | 43 | 0.734 -> 0.689 (-0.046 [-0.140, +0.047]) | 0.719 -> 0.663 (-0.056 [-0.142, +0.014]) | 0.741 -> 0.679 (-0.062 [-0.151, +0.007]) | fail |

A3 (asof, n 6): fail, A4 (in_force, n 35): pass

## Slots of run A (p1-struct-bc)

| subset | n_items | n_slots | superseded_slots | superseded_share | wrong_version_slots | wrong_version_share | duplicate_slots | duplicate_share | duplicate_cluster_slots | exact_copy_slots | exact_copy_share | evidence_groups_touched | evidence_groups_touched_mean | tokens@10 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| asof | 6 | 60 | 41 | 0.683 | 43 | 0.717 | 32 | 0.533 | 32 | 25 | 0.417 | 5 | 0.833 | 3284.000 |
| in_force | 35 | 350 | 141 | 0.403 | - | - | 126 | 0.360 | 126 | 119 | 0.340 | 48 | 1.371 | 3079.029 |
| superseded_only | 2 | 20 | 12 | 0.600 | - | - | 10 | 0.500 | 10 | 9 | 0.450 | 2 | 1.000 | 2559.500 |
| scored | 43 | 430 | 194 | 0.451 | 43 | 0.717 | 168 | 0.391 | 168 | 153 | 0.356 | 55 | 1.279 | 3083.465 |
| all | 55 | 550 | 267 | 0.485 | 43 | 0.717 | 226 | 0.411 | 226 | 207 | 0.376 | 55 | 1.279 | 3083.465 |

## Slots of run B (p2-dedup)

| subset | n_items | n_slots | superseded_slots | superseded_share | wrong_version_slots | wrong_version_share | duplicate_slots | duplicate_share | duplicate_cluster_slots | exact_copy_slots | exact_copy_share | evidence_groups_touched | evidence_groups_touched_mean | tokens@10 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| asof | 6 | 60 | 7 | 0.117 | 33 | 0.550 | 0 | 0.000 | 0 | 0 | 0.000 | 3 | 0.500 | 3183.167 |
| in_force | 35 | 350 | 25 | 0.071 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 51 | 1.457 | 3005.714 |
| superseded_only | 2 | 20 | 3 | 0.150 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 1 | 0.500 | 2974.500 |
| scored | 43 | 430 | 35 | 0.081 | 33 | 0.550 | 0 | 0.000 | 0 | 0 | 0.000 | 55 | 1.279 | 3029.023 |
| all | 55 | 550 | 51 | 0.093 | 33 | 0.550 | 0 | 0.000 | 0 | 0 | 0.000 | 55 | 1.279 | 3029.023 |
