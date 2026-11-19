# Phase 2 comparison: p2-dedup minus p1-struct-bc

Run `gov-p2-dedup-test-retrieval-20261116T060455` minus run `gov-p1-struct-bc-test-retrieval-20261116T055136` on `gov` / `test`. Store `.cache/store-p2/gov` (snapshot `f002821f2cb3`), applicability overlay `4c81d25fe905`, dedup overlay `6fb05917038e`. Paired bootstrap 95% CIs (10000 resamples, seed 20261108); non-inferiority margin 0.02: a metric passes when the lower bound is above -0.02.

| subset | n | Recall@10 | nDCG@10 | MRR | verdict |
|---|---|---|---|---|---|
| asof | 34 | 0.853 -> 0.588 (-0.265 [-0.412, -0.118]) | 0.567 -> 0.508 (-0.058 [-0.200, +0.078]) | 0.471 -> 0.480 (+0.010 [-0.135, +0.152]) | fail |
| in_force | 158 | 0.784 -> 0.801 (+0.016 [+0.002, +0.037]) | 0.727 -> 0.755 (+0.028 [+0.016, +0.042]) | 0.717 -> 0.746 (+0.028 [+0.014, +0.046]) | pass |
| superseded_only | 21 | 0.857 -> 0.476 (-0.381 [-0.571, -0.190]) | 0.746 -> 0.411 (-0.335 [-0.522, -0.155]) | 0.709 -> 0.389 (-0.320 [-0.506, -0.143]) | fail |
| scored | 213 | 0.802 -> 0.735 (-0.068 [-0.107, -0.029]) | 0.703 -> 0.681 (-0.022 [-0.056, +0.011]) | 0.677 -> 0.668 (-0.009 [-0.044, +0.025]) | fail |

A3 (asof, n 34): fail, A4 (in_force, n 158): pass

## Slots of run A (p1-struct-bc)

| subset | n_items | n_slots | superseded_slots | superseded_share | wrong_version_slots | wrong_version_share | duplicate_slots | duplicate_share | duplicate_cluster_slots | exact_copy_slots | exact_copy_share | evidence_groups_touched | evidence_groups_touched_mean | tokens@10 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| asof | 34 | 340 | 223 | 0.656 | 221 | 0.650 | 172 | 0.506 | 172 | 135 | 0.397 | 29 | 0.853 | 3337.412 |
| in_force | 158 | 1580 | 743 | 0.470 | - | - | 645 | 0.408 | 645 | 610 | 0.386 | 188 | 1.190 | 3127.715 |
| superseded_only | 21 | 210 | 139 | 0.662 | - | - | 102 | 0.486 | 102 | 91 | 0.433 | 18 | 0.857 | 3230.619 |
| scored | 213 | 2130 | 1105 | 0.519 | 221 | 0.650 | 919 | 0.431 | 919 | 836 | 0.392 | 235 | 1.103 | 3171.333 |
| all | 242 | 2420 | 1279 | 0.529 | 221 | 0.650 | 1076 | 0.445 | 1076 | 984 | 0.407 | 235 | 1.103 | 3171.333 |

## Slots of run B (p2-dedup)

| subset | n_items | n_slots | superseded_slots | superseded_share | wrong_version_slots | wrong_version_share | duplicate_slots | duplicate_share | duplicate_cluster_slots | exact_copy_slots | exact_copy_share | evidence_groups_touched | evidence_groups_touched_mean | tokens@10 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| asof | 34 | 340 | 51 | 0.150 | 182 | 0.535 | 0 | 0.000 | 0 | 0 | 0.000 | 20 | 0.588 | 3336.559 |
| in_force | 158 | 1580 | 135 | 0.085 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 196 | 1.241 | 3160.778 |
| superseded_only | 21 | 210 | 45 | 0.214 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 10 | 0.476 | 3174.714 |
| scored | 213 | 2130 | 231 | 0.108 | 182 | 0.535 | 0 | 0.000 | 0 | 0 | 0.000 | 226 | 1.061 | 3190.211 |
| all | 242 | 2420 | 254 | 0.105 | 182 | 0.535 | 0 | 0.000 | 0 | 0 | 0.000 | 226 | 1.061 | 3190.211 |
