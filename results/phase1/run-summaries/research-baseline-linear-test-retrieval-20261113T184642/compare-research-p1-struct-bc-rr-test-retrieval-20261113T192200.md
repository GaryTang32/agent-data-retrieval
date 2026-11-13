# Retrieval comparison: p1-struct-bc-rr minus baseline-linear

Run `research-p1-struct-bc-rr-test-retrieval-20261113T192200` minus run `research-baseline-linear-test-retrieval-20261113T184642` on `research` / `test`, paired over 180 shared items; paired bootstrap 95% CIs; Holm-adjusted p across the four metrics. Metrics version 2.

| metric | n | A | B | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| recall@10 | 180 | 0.856 | 0.715 | -0.141 | [-0.199, -0.085] | < 0.0002 | < 0.0008 |
| ndcg@10 | 180 | 0.710 | 0.576 | -0.133 | [-0.188, -0.079] | < 0.0002 | < 0.0008 |
| mrr | 180 | 0.676 | 0.545 | -0.131 | [-0.191, -0.071] | < 0.0002 | < 0.0008 |
| coverage@10 | 180 | 0.856 | 0.649 | -0.208 | [-0.264, -0.151] | < 0.0002 | < 0.0008 |
