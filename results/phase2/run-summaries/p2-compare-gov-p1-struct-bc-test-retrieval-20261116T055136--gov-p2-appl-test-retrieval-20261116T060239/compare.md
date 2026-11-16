# Phase 2 comparison: p2-appl minus p1-struct-bc

Run `gov-p2-appl-test-retrieval-20261116T060239` minus run `gov-p1-struct-bc-test-retrieval-20261116T055136` on `gov` / `test`. Store `.cache/store-p2/gov` (snapshot `f002821f2cb3`), applicability overlay `4c81d25fe905`, dedup overlay `6fb05917038e`. Paired bootstrap 95% CIs (10000 resamples, seed 20261108); non-inferiority margin 0.02: a metric passes when the lower bound is above -0.02.

| subset | n | Recall@10 | nDCG@10 | MRR | verdict |
|---|---|---|---|---|---|
| asof | 34 | 0.853 -> 0.853 (+0.000 [+0.000, +0.000]) | 0.567 -> 0.820 (+0.254 [+0.182, +0.325]) | 0.471 -> 0.809 (+0.338 [+0.243, +0.434]) | pass |
| in_force | 158 | 0.784 -> 0.807 (+0.023 [+0.004, +0.048]) | 0.727 -> 0.762 (+0.035 [+0.021, +0.051]) | 0.717 -> 0.752 (+0.035 [+0.019, +0.053]) | pass |
| superseded_only | 21 | 0.857 -> 0.000 (-0.857 [-1.000, -0.714]) | 0.746 -> 0.000 (-0.746 [-0.890, -0.581]) | 0.709 -> 0.000 (-0.709 [-0.869, -0.532]) | fail |
| scored | 213 | 0.802 -> 0.735 (-0.067 [-0.110, -0.026]) | 0.703 -> 0.696 (-0.007 [-0.050, +0.033]) | 0.677 -> 0.687 (+0.010 [-0.035, +0.053]) | fail |

A3 (asof, n 34): pass, A4 (in_force, n 158): pass

## Slots of run A (p1-struct-bc)

| subset | n_items | n_slots | superseded_slots | superseded_share | wrong_version_slots | wrong_version_share | duplicate_slots | duplicate_share | duplicate_cluster_slots | exact_copy_slots | exact_copy_share | evidence_groups_touched | evidence_groups_touched_mean | tokens@10 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| asof | 34 | 340 | 223 | 0.656 | 221 | 0.650 | 172 | 0.506 | 172 | 135 | 0.397 | 29 | 0.853 | 3337.412 |
| in_force | 158 | 1580 | 743 | 0.470 | - | - | 645 | 0.408 | 645 | 610 | 0.386 | 188 | 1.190 | 3127.715 |
| superseded_only | 21 | 210 | 139 | 0.662 | - | - | 102 | 0.486 | 102 | 91 | 0.433 | 18 | 0.857 | 3230.619 |
| scored | 213 | 2130 | 1105 | 0.519 | 221 | 0.650 | 919 | 0.431 | 919 | 836 | 0.392 | 235 | 1.103 | 3171.333 |
| all | 242 | 2420 | 1279 | 0.529 | 221 | 0.650 | 1076 | 0.445 | 1076 | 984 | 0.407 | 235 | 1.103 | 3171.333 |

## Slots of run B (p2-appl)

| subset | n_items | n_slots | superseded_slots | superseded_share | wrong_version_slots | wrong_version_share | duplicate_slots | duplicate_share | duplicate_cluster_slots | exact_copy_slots | exact_copy_share | evidence_groups_touched | evidence_groups_touched_mean | tokens@10 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| asof | 34 | 340 | 187 | 0.550 | 0 | 0.000 | 1 | 0.003 | 1 | 0 | 0.000 | 29 | 0.853 | 3345.412 |
| in_force | 158 | 1580 | 0 | 0.000 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 199 | 1.259 | 3149.335 |
| superseded_only | 21 | 210 | 0 | 0.000 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 0 | 0.000 | 3153.667 |
| scored | 213 | 2130 | 187 | 0.088 | 0 | 0.000 | 1 | 0.000 | 1 | 0 | 0.000 | 228 | 1.070 | 3181.061 |
| all | 242 | 2420 | 187 | 0.077 | 0 | 0.000 | 1 | 0.000 | 1 | 0 | 0.000 | 228 | 1.070 | 3181.061 |
