# tools: ToolRet, `toolbench` subset (local-only)

The tool corpus of Phase 2C (spec §8.3): real RapidAPI endpoint descriptions from ToolBench,
as packaged by ToolRet ([arXiv 2503.01763](https://arxiv.org/abs/2503.01763)), with ToolRet's
1,100 `toolbench` queries and their gold tools. Like bench, it is **local-only** (ruling R13,
question Q2): the files are fetched into `data/tools/` (git-ignored) and nothing from them is
committed except revisions, hashes and counts. This directory commits `config.json` (what is
pinned), `manifest.json` (what was fetched: SHA-256 per file and the counts) and this README.

## Fetch and ingest

```
adr-eval tools-fetch                     # data/tools/, corpora/tools/manifest.json
adr tools ingest --toolret               # tools-only store .cache/store-p2/toolret
adr acl sync --store .cache/store-p2/toolret
```

`tools-fetch` downloads with `PoliteFetcher` from
`https://huggingface.co/datasets/<repo>/resolve/<revision>/<path>` and verifies each file
against the SHA-256 in `config.json` (the Hub's LFS object id at that revision; the paths were
found once with the Hub tree API, `/api/datasets/<repo>/tree/<revision>?recursive=true`).

| File | Repository @ revision | Path | Bytes | SHA-256 |
|---|---|---|---|---|
| tools | `mangopy/ToolRet-Tools` @ `e06c38c75612b6536bd959e08cdd345894aba6a7` | `web/tools-00000-of-00001.parquet` | 8,143,446 | `57faceebd778b2cb74571dca0e71e8bc8078c11ba05dce0efc562e818d3950e6` |
| queries | `mangopy/ToolRet-Queries` @ `b8c76ad3349ff17497b6bdb28bb5b8f61a0f6445` | `toolbench/queries-00000-of-00001.parquet` | 922,485 | `2bb32ea009d6ece37b1b785330247aacac037a20dd4522632cb3359809c8837d` |

The tools file has columns `id` and `documentation` (a ToolBench JSON string); the queries
file has `id`, `query`, `instruction`, `labels` (a JSON string of `{id, doc, relevance}`) and
`category`. The query field is used; `instruction` is not.

## Counts (measured 2026-11-16, `manifest.json`)

| | Measured | Spec §8.3 |
|---|---|---|
| Tools (`toolbench_tool_*` of config `web`) | **13,862** | 14,059 |
| Queries | 1,100 | 1,100 |
| Gold tools per query | 2.39 (2,629 labels, 1,632 distinct, all relevance 1) | 2.39 |
| Gold tools missing from the tools | 0 | 0 |
| Raw documentation tokens (harness tokenizer) | **1,218,889** (mean 87.9, median 58) | 1,227,462 (mean 87, median 58) |
| Dev / test (SHA-256 of the id mod 5) | 212 / 888 | about 220 / 880 |

**The spec's 14,059 counts 197 more tools.** ToolRet-Tools at the pinned revision holds 44,453
tools in three configs (`web` 37,292, `code` 3,794, `customized` 3,367; the spec's total). The
`web` config has 13,862 ids `toolbench_tool_*`; config `customized` has 197 ids
`toolbench_sam_tool_*` (ToolRet's separate `toolbench-sam` dataset). 13,862 + 197 = 14,059,
and the raw documentation tokens of the two sets together are exactly the spec's 1,227,462
(mean 87.3, median 58). So the spec's probe counted every id that starts with `toolbench`
across the configs, while the spec's own definition (ids `toolbench_tool_*` in `web`) gives
13,862. This corpus follows the definition; it is not tuned to the count. No gold label is a
`toolbench_sam` tool, so the queries and their gold are the same either way; only 197
distractor tools differ. C1 (at least 1,000 real tool records) is unaffected.

## Records

`adr tools ingest --toolret` turns each tool into a tool record (`adr_store.tool_records.
from_toolret`): `source_uri` `toolret:mangopy/ToolRet-Tools@<revision>/web#<toolret id>`
(gold ids map to `tool_id`s through it), `source_version` the revision, `license` from
`config.json`, parameters as an object schema with `required`, `operation` = category, API
name and method. Measured: 13,862 records, 100% structural conformance (C1), 806,936
definition tokens in all; the tool snapshot is
`a6a3a6cc171d941a0bb586ce03b3424ed324fe69ec5747bb6c0001d69819429f` on every ingest, into the
same store or a new one (the content snapshot of the tools-only store is the empty one,
`de13b4a8eeac…`).

ACL (`adr acl sync`, tools keyed by `tool_id` through the bucket rule of spec §5.2): public
2,783, two tenants 1,369, one tenant 6,260, one group 3,450 (20.1 / 9.9 / 45.2 / 24.9%).

## Licence

ToolBench data: Apache-2.0 (its README: "distributed under Apache License 2.0"). ToolRet code
repository: Apache-2.0. The ToolRet dataset cards declare no licence (open question Q2), which
is why the data stays local.
