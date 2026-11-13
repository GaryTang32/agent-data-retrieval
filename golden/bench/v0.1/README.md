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

## Frozen data

The item files are frozen data. They are not regenerated when scoring rules change. The
generator's evidence-only check uses the harness's exact scorer, so regenerating with later
code (for example the whole-identifier rule of metrics version 2) can admit a different set;
that set would be a new version, not v0.1. `adr-eval golden bench --gen` refuses to write
over an existing `items.jsonl` unless `--overwrite` is given.

## Regenerate

```
adr-eval fetch bench
adr-eval golden bench --gen --generator claude_code_sonnet --judge claude_code_opus --max-calls 1500
adr-eval golden bench --verify
```

Add `--overwrite` to `--gen` when the item files already exist. With the same cache and the
code that generated them (metrics version 1, up to commit `4063a0e`) the output is
byte-identical; later code may admit a different set (see "Frozen data"). From a cold
cache, model replies may differ (Claude Code does not pin temperature), so compare the
per-type counts above, not the hashes.
