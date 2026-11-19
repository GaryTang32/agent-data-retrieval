# Phase 2 comparison: p2-dedup minus p1-struct-bc

Run `research-p2-dedup-dev-retrieval-20261116T055908` minus run `research-p1-struct-bc-dev-retrieval-20261116T055053` on `research` / `dev`. Store `.cache/store-p2/research` (snapshot `97c415b1aa71`), applicability overlay `5b91123ae2d3`, dedup overlay `4aedcea37803`. Paired bootstrap 95% CIs (10000 resamples, seed 20261108); non-inferiority margin 0.02: a metric passes when the lower bound is above -0.02.

| subset | n | Recall@10 | nDCG@10 | MRR | verdict |
|---|---|---|---|---|---|
| asof | 0 | - | - | - | - |
| in_force | 45 | 0.872 -> 0.872 (+0.000 [+0.000, +0.000]) | 0.769 -> 0.769 (+0.000 [+0.000, +0.000]) | 0.737 -> 0.737 (+0.000 [+0.000, +0.000]) | pass |
| superseded_only | 0 | - | - | - | - |
| scored | 45 | 0.872 -> 0.872 (+0.000 [+0.000, +0.000]) | 0.769 -> 0.769 (+0.000 [+0.000, +0.000]) | 0.737 -> 0.737 (+0.000 [+0.000, +0.000]) | pass |

A3 (asof, n 0): no items, A4 (in_force, n 45): pass

## Slots of run A (p1-struct-bc)

| subset | n_items | n_slots | superseded_slots | superseded_share | wrong_version_slots | wrong_version_share | duplicate_slots | duplicate_share | duplicate_cluster_slots | exact_copy_slots | exact_copy_share | evidence_groups_touched | evidence_groups_touched_mean | tokens@10 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| asof | 0 | 0 | 0 | - | - | - | 0 | - | 0 | 0 | - | 0 | - | - |
| in_force | 45 | 450 | 0 | 0.000 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 61 | 1.356 | 3263.422 |
| superseded_only | 0 | 0 | 0 | - | - | - | 0 | - | 0 | 0 | - | 0 | - | - |
| scored | 45 | 450 | 0 | 0.000 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 61 | 1.356 | 3263.422 |
| all | 53 | 530 | 0 | 0.000 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 61 | 1.356 | 3263.422 |

## Slots of run B (p2-dedup)

| subset | n_items | n_slots | superseded_slots | superseded_share | wrong_version_slots | wrong_version_share | duplicate_slots | duplicate_share | duplicate_cluster_slots | exact_copy_slots | exact_copy_share | evidence_groups_touched | evidence_groups_touched_mean | tokens@10 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| asof | 0 | 0 | 0 | - | - | - | 0 | - | 0 | 0 | - | 0 | - | - |
| in_force | 45 | 450 | 0 | 0.000 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 61 | 1.356 | 3263.422 |
| superseded_only | 0 | 0 | 0 | - | - | - | 0 | - | 0 | 0 | - | 0 | - | - |
| scored | 45 | 450 | 0 | 0.000 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 61 | 1.356 | 3263.422 |
| all | 53 | 530 | 0 | 0.000 | - | - | 0 | 0.000 | 0 | 0 | 0.000 | 61 | 1.356 | 3263.422 |
