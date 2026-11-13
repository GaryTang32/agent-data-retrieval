# Retrieval comparison: p1-struct-bc minus baseline-linear

Run `research-p1-struct-bc-test-retrieval-20261113T190713` minus run `research-baseline-linear-test-retrieval-20261113T184642` on `research` / `test`, paired over 180 shared items; paired bootstrap 95% CIs; Holm-adjusted p across the four metrics. Metrics version 2.

| metric | n | A | B | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| recall@10 | 180 | 0.856 | 0.844 | -0.013 | [-0.045, 0.017] | 0.390 | 1.000 |
| ndcg@10 | 180 | 0.710 | 0.710 | 0.000 | [-0.027, 0.028] | 0.960 | 1.000 |
| mrr | 180 | 0.676 | 0.677 | 0.001 | [-0.033, 0.035] | 0.936 | 1.000 |
| coverage@10 | 180 | 0.856 | 0.764 | -0.093 | [-0.131, -0.058] | < 0.0002 | < 0.0008 |
