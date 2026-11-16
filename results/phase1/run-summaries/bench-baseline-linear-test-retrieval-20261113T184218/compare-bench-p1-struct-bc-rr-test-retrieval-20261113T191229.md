# Retrieval comparison: p1-struct-bc-rr minus baseline-linear

Run `bench-p1-struct-bc-rr-test-retrieval-20261113T191229` minus run `bench-baseline-linear-test-retrieval-20261113T184218` on `bench` / `test`, paired over 517 shared items; paired bootstrap 95% CIs; Holm-adjusted p across the four metrics. Metrics version 2.

| metric | n | A | B | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| recall@10 | 517 | 0.922 | 0.901 | -0.021 | [-0.042, 0.000] | 0.054 | 0.108 |
| ndcg@10 | 517 | 0.854 | 0.825 | -0.029 | [-0.051, -0.007] | 0.010 | 0.029 |
| mrr | 517 | 0.849 | 0.830 | -0.019 | [-0.045, 0.006] | 0.144 | 0.144 |
| coverage@10 | 517 | 0.782 | 0.747 | -0.035 | [-0.059, -0.012] | 0.003 | 0.013 |
