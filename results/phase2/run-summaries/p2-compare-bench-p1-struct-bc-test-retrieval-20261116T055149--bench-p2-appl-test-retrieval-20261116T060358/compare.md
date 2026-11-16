# Phase 2 comparison: p2-appl minus p1-struct-bc

Run `bench-p2-appl-test-retrieval-20261116T060358` minus run `bench-p1-struct-bc-test-retrieval-20261116T055149` on `bench` / `test`. Store `.cache/store-p2/bench` (snapshot `7d8d1f8adda6`), applicability overlay `2709180fbeef`, dedup overlay `94a90b9859e0`. Paired bootstrap 95% CIs (10000 resamples, seed 20261108); non-inferiority margin 0.02: a metric passes when the lower bound is above -0.02.

| subset | n | Recall@10 | nDCG@10 | MRR | verdict |
|---|---|---|---|---|---|
| asof | 0 | - | - | - | - |
| in_force | 517 | 0.919 -> 0.919 (+0.000 [+0.000, +0.000]) | 0.853 -> 0.853 (+0.000 [+0.000, +0.000]) | 0.856 -> 0.856 (+0.000 [+0.000, +0.000]) | pass |
| superseded_only | 0 | - | - | - | - |
| scored | 517 | 0.919 -> 0.919 (+0.000 [+0.000, +0.000]) | 0.853 -> 0.853 (+0.000 [+0.000, +0.000]) | 0.856 -> 0.856 (+0.000 [+0.000, +0.000]) | pass |

A3 (asof, n 0): no items, A4 (in_force, n 517): pass

## Slots of run A (p1-struct-bc)

| subset | n_items | n_slots | superseded_slots | superseded_share | wrong_version_slots | wrong_version_share | duplicate_slots | duplicate_share | duplicate_cluster_slots | exact_copy_slots | exact_copy_share | evidence_groups_touched | evidence_groups_touched_mean | tokens@10 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| asof | 0 | 0 | 0 | - | - | - | 0 | - | 0 | 0 | - | 0 | - | - |
| in_force | 517 | 5170 | 0 | 0.000 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 648 | 1.253 | 2911.112 |
| superseded_only | 0 | 0 | 0 | - | - | - | 0 | - | 0 | 0 | - | 0 | - | - |
| scored | 517 | 5170 | 0 | 0.000 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 648 | 1.253 | 2911.112 |
| all | 572 | 5720 | 0 | 0.000 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 648 | 1.253 | 2911.112 |

## Slots of run B (p2-appl)

| subset | n_items | n_slots | superseded_slots | superseded_share | wrong_version_slots | wrong_version_share | duplicate_slots | duplicate_share | duplicate_cluster_slots | exact_copy_slots | exact_copy_share | evidence_groups_touched | evidence_groups_touched_mean | tokens@10 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| asof | 0 | 0 | 0 | - | - | - | 0 | - | 0 | 0 | - | 0 | - | - |
| in_force | 517 | 5170 | 0 | 0.000 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 648 | 1.253 | 2911.112 |
| superseded_only | 0 | 0 | 0 | - | - | - | 0 | - | 0 | 0 | - | 0 | - | - |
| scored | 517 | 5170 | 0 | 0.000 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 648 | 1.253 | 2911.112 |
| all | 572 | 5720 | 0 | 0.000 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 648 | 1.253 | 2911.112 |
