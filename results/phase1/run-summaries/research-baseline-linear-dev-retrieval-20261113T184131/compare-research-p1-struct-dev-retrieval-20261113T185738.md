# Retrieval comparison: p1-struct minus baseline-linear

Run `research-p1-struct-dev-retrieval-20261113T185738` minus run `research-baseline-linear-dev-retrieval-20261113T184131` on `research` / `dev`, paired over 45 shared items; paired bootstrap 95% CIs; Holm-adjusted p across the four metrics. Metrics version 2.

| metric | n | A | B | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| recall@10 | 45 | 0.846 | 0.891 | 0.044 | [0.000, 0.111] | 0.260 | 0.260 |
| ndcg@10 | 45 | 0.697 | 0.771 | 0.073 | [0.003, 0.154] | 0.040 | 0.160 |
| mrr | 45 | 0.662 | 0.742 | 0.080 | [-0.003, 0.170] | 0.058 | 0.173 |
| coverage@10 | 45 | 0.846 | 0.791 | -0.055 | [-0.128, 0.013] | 0.113 | 0.227 |
