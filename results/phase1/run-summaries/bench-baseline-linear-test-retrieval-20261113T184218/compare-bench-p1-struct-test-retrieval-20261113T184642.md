# Retrieval comparison: p1-struct minus baseline-linear

Run `bench-p1-struct-test-retrieval-20261113T184642` minus run `bench-baseline-linear-test-retrieval-20261113T184218` on `bench` / `test`, paired over 517 shared items; paired bootstrap 95% CIs; Holm-adjusted p across the four metrics. Metrics version 2.

| metric | n | A | B | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| recall@10 | 517 | 0.922 | 0.915 | -0.007 | [-0.019, 0.004] | 0.208 | 0.208 |
| ndcg@10 | 517 | 0.854 | 0.843 | -0.011 | [-0.020, -0.002] | 0.018 | 0.055 |
| mrr | 517 | 0.849 | 0.839 | -0.010 | [-0.022, 0.002] | 0.098 | 0.196 |
| coverage@10 | 517 | 0.782 | 0.739 | -0.043 | [-0.058, -0.028] | < 0.0002 | < 0.0008 |
