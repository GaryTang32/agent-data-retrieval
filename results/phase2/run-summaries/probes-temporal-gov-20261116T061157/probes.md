# Temporal probes (gov)

Store `.cache/store-p2/gov` (snapshot `f002821f2cb3`), index `54c12a3c2917`, applicability overlay `4c81d25fe905`, dedup on. Seed 20261116. No model calls.

| set | mode | probes (spec) | passed | failed | figures |
|---|---|---|---|---|---|
| T1 | as_of | 40 (40) | 40 | 0 | offending_chunks 0 |
| T2 | default | 189 (189) | 189 | 0 | offending_chunks 0, head_found@10 188, head_rank_mean 1.027, head_section_absent 1 |
| T2 | as_of | 189 (189) | 189 | 0 | offending_chunks 0, other_version_chunks 0, recall@10 1.000 |
| T3 | default | 145 (145) | 145 | 0 | offending_chunks 0, recall@10 0.000 |
| T3 | as_of | 145 (145) | 145 | 0 | offending_chunks 0, recall@10 0.993 |
| T4 | default | 297 (297) | 297 | 0 | offending_chunks 0 |
| T5 | as_of | 171 (171) | 171 | 0 | search_absent 171, grep_absent 171, grep_truncated 0, read_refused 171, control_read_ok 171, control_search_found 171, control_grep_found 171 |
