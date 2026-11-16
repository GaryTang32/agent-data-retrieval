# Retrieval comparison: p1-struct-bc minus baseline-linear

Run `bench-p1-struct-bc-test-retrieval-20261113T184931` minus run `bench-baseline-linear-test-retrieval-20261113T184218` on `bench` / `test`, paired over 517 shared items; paired bootstrap 95% CIs; Holm-adjusted p across the four metrics. Metrics version 2.

| metric | n | A | B | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| recall@10 | 517 | 0.922 | 0.919 | -0.003 | [-0.016, 0.009] | 0.621 | 1.000 |
| ndcg@10 | 517 | 0.854 | 0.853 | -0.001 | [-0.012, 0.009] | 0.764 | 1.000 |
| mrr | 517 | 0.849 | 0.856 | 0.007 | [-0.005, 0.019] | 0.268 | 1.000 |
| coverage@10 | 517 | 0.782 | 0.780 | -0.002 | [-0.018, 0.015] | 0.833 | 1.000 |
