# Retrieval comparison: p1-struct-bc minus baseline-linear

Run `research-p1-struct-bc-dev-retrieval-20261113T190354` minus run `research-baseline-linear-dev-retrieval-20261113T184131` on `research` / `dev`, paired over 45 shared items; paired bootstrap 95% CIs; Holm-adjusted p across the four metrics. Metrics version 2.

| metric | n | A | B | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| recall@10 | 45 | 0.846 | 0.872 | 0.025 | [-0.044, 0.111] | 0.512 | 0.512 |
| ndcg@10 | 45 | 0.697 | 0.769 | 0.071 | [0.006, 0.148] | 0.031 | 0.124 |
| mrr | 45 | 0.662 | 0.737 | 0.075 | [-0.004, 0.162] | 0.064 | 0.191 |
| coverage@10 | 45 | 0.846 | 0.790 | -0.057 | [-0.137, 0.015] | 0.130 | 0.259 |
