# Phase 2 comparison: p2-default minus p1-struct-bc

Run `gov-p2-default-dev-retrieval-20261116T060631` minus run `gov-p1-struct-bc-dev-retrieval-20261116T055053` on `gov` / `dev`. Store `.cache/store-p2/gov` (snapshot `f002821f2cb3`), applicability overlay `4c81d25fe905`, dedup overlay `6fb05917038e`. Paired bootstrap 95% CIs (10000 resamples, seed 20261108); non-inferiority margin 0.02: a metric passes when the lower bound is above -0.02.

| subset | n | Recall@10 | nDCG@10 | MRR | verdict |
|---|---|---|---|---|---|
| asof | 6 | 0.833 -> 0.833 (+0.000 [+0.000, +0.000]) | 0.750 -> 0.833 (+0.083 [+0.000, +0.250]) | 0.722 -> 0.833 (+0.111 [+0.000, +0.333]) | pass |
| in_force | 35 | 0.702 -> 0.704 (+0.001 [+0.000, +0.004]) | 0.698 -> 0.702 (+0.004 [+0.000, +0.012]) | 0.729 -> 0.730 (+0.001 [+0.000, +0.003]) | pass |
| superseded_only | 2 | 1.000 -> 0.000 (-1.000 [-1.000, -1.000]) | 1.000 -> 0.000 (-1.000 [-1.000, -1.000]) | 1.000 -> 0.000 (-1.000 [-1.000, -1.000]) | fail |
| scored | 43 | 0.734 -> 0.689 (-0.046 [-0.116, +0.002]) | 0.719 -> 0.688 (-0.032 [-0.110, +0.027]) | 0.741 -> 0.711 (-0.030 [-0.114, +0.032]) | fail |

A3 (asof, n 6): pass, A4 (in_force, n 35): pass

## Slots of run A (p1-struct-bc)

| subset | n_items | n_slots | superseded_slots | superseded_share | wrong_version_slots | wrong_version_share | duplicate_slots | duplicate_share | duplicate_cluster_slots | exact_copy_slots | exact_copy_share | evidence_groups_touched | evidence_groups_touched_mean | tokens@10 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| asof | 6 | 60 | 41 | 0.683 | 43 | 0.717 | 32 | 0.533 | 32 | 25 | 0.417 | 5 | 0.833 | 3284.000 |
| in_force | 35 | 350 | 141 | 0.403 | - | - | 126 | 0.360 | 126 | 119 | 0.340 | 48 | 1.371 | 3079.029 |
| superseded_only | 2 | 20 | 12 | 0.600 | - | - | 10 | 0.500 | 10 | 9 | 0.450 | 2 | 1.000 | 2559.500 |
| scored | 43 | 430 | 194 | 0.451 | 43 | 0.717 | 168 | 0.391 | 168 | 153 | 0.356 | 55 | 1.279 | 3083.465 |
| all | 55 | 550 | 267 | 0.485 | 43 | 0.717 | 226 | 0.411 | 226 | 207 | 0.376 | 55 | 1.279 | 3083.465 |

## Slots of run B (p2-default)

| subset | n_items | n_slots | superseded_slots | superseded_share | wrong_version_slots | wrong_version_share | duplicate_slots | duplicate_share | duplicate_cluster_slots | exact_copy_slots | exact_copy_share | evidence_groups_touched | evidence_groups_touched_mean | tokens@10 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| asof | 6 | 60 | 30 | 0.500 | 0 | 0.000 | 0 | 0.000 | 0 | 0 | 0.000 | 5 | 0.833 | 3217.167 |
| in_force | 35 | 350 | 0 | 0.000 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 50 | 1.429 | 3023.886 |
| superseded_only | 2 | 20 | 0 | 0.000 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 0 | 0.000 | 3017.500 |
| scored | 43 | 430 | 30 | 0.070 | 0 | 0.000 | 0 | 0.000 | 0 | 0 | 0.000 | 55 | 1.279 | 3050.558 |
| all | 55 | 550 | 30 | 0.055 | 0 | 0.000 | 0 | 0.000 | 0 | 0 | 0.000 | 55 | 1.279 | 3050.558 |
