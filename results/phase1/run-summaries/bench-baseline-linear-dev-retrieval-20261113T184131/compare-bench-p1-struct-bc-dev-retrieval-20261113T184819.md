# Retrieval comparison: p1-struct-bc minus baseline-linear

Run `bench-p1-struct-bc-dev-retrieval-20261113T184819` minus run `bench-baseline-linear-dev-retrieval-20261113T184131` on `bench` / `dev`, paired over 141 shared items; paired bootstrap 95% CIs; Holm-adjusted p across the four metrics. Metrics version 2.

| metric | n | A | B | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| recall@10 | 141 | 0.970 | 0.968 | -0.001 | [-0.022, 0.019] | 0.842 | 1.000 |
| ndcg@10 | 141 | 0.881 | 0.888 | 0.007 | [-0.020, 0.032] | 0.584 | 1.000 |
| mrr | 141 | 0.865 | 0.880 | 0.015 | [-0.017, 0.046] | 0.350 | 1.000 |
| coverage@10 | 141 | 0.811 | 0.804 | -0.006 | [-0.040, 0.025] | 0.718 | 1.000 |
