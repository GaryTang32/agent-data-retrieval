# Retrieval comparison: p1-struct minus baseline-linear

Run `research-p1-struct-test-retrieval-20261113T190039` minus run `research-baseline-linear-test-retrieval-20261113T184642` on `research` / `test`, paired over 180 shared items; paired bootstrap 95% CIs; Holm-adjusted p across the four metrics. Metrics version 2.

| metric | n | A | B | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| recall@10 | 180 | 0.856 | 0.848 | -0.009 | [-0.042, 0.025] | 0.601 | 0.638 |
| ndcg@10 | 180 | 0.710 | 0.692 | -0.017 | [-0.049, 0.013] | 0.279 | 0.638 |
| mrr | 180 | 0.676 | 0.652 | -0.024 | [-0.064, 0.013] | 0.213 | 0.638 |
| coverage@10 | 180 | 0.856 | 0.765 | -0.091 | [-0.132, -0.052] | < 0.0002 | < 0.0008 |
