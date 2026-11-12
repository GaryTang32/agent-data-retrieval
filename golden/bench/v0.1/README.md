# bench golden set v0.1 (items not committed)

The item files are kept local. They hold EnterpriseRAG-Bench questions and verbatim quotes
from its documents, and the benchmark's canary asks that its data stay out of training
corpora (see `corpora/bench/README.md`). This file pins what the local files contain so a
regenerated set can be checked against it.

| File | Items | SHA-256 |
|---|---|---|
| `items.jsonl` | 728 | `54a0d90ef5c10b7f36397ecff494d5ded4e57ca6919dc3ecad6917dbf6700d15` |
| `rejected.jsonl` | 12 | `5de799bb68306b7ef824255bab391f5de07ffac3af3607826619f15d4f2231a7` |

| qtype | accepted | benchmark-native | generated |
|---|---|---|---|
| factoid | 418 | 370 | 48 |
| id_lookup | 43 | 0 | 43 |
| insufficient | 70 | 20 | 50 |
| overview | 149 | 100 | 49 |
| procedure | 48 | 0 | 48 |

Split: dev 156, test 572. Tail share among rated items: 0.53.

## Regenerate

```
adr-eval fetch bench
adr-eval golden bench --gen --generator claude_code_sonnet --judge claude_code_opus --max-calls 1500
adr-eval golden bench --verify
```

With the same cache the output is byte-identical; from a cold cache, model replies may
differ (Claude Code does not pin temperature), so compare the per-type counts above, not
the hashes.
