# Retrieval comparison: p1-struct-bc-rr minus baseline-linear

Run `bench-p1-struct-bc-rr-dev-retrieval-20261113T185104` minus run `bench-baseline-linear-dev-retrieval-20261113T184131` on `bench` / `dev`, paired over 141 shared items; paired bootstrap 95% CIs; Holm-adjusted p across the four metrics. Metrics version 2.

| metric | n | A | B | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| recall@10 | 141 | 0.970 | 0.903 | -0.067 | [-0.115, -0.024] | 0.001 | 0.006 |
| ndcg@10 | 141 | 0.881 | 0.807 | -0.074 | [-0.125, -0.027] | 0.001 | 0.006 |
| mrr | 141 | 0.865 | 0.793 | -0.072 | [-0.131, -0.017] | 0.009 | 0.018 |
| coverage@10 | 141 | 0.811 | 0.742 | -0.069 | [-0.121, -0.017] | 0.009 | 0.018 |
