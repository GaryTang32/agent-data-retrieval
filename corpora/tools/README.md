# tools: ToolRet, `toolbench` pool (local-only)

The tool corpus of Phase 2C (spec §8.3), as packaged by ToolRet
([arXiv 2503.01763](https://arxiv.org/abs/2503.01763)): 13,862 real RapidAPI endpoint
descriptions from ToolBench and 197 Python-library and curl function descriptions from a
different upstream (ToolRet's `toolbench-sam`), with ToolRet's 1,100 `toolbench` queries and
their gold tools. Like bench, it is **local-only** (ruling R13,
question Q2): the files are fetched into `data/tools/` (git-ignored) and nothing from them is
committed except revisions, hashes and counts. This directory commits `config.json` (what is
pinned), `manifest.json` (what was fetched: SHA-256 per file, the pool and the counts) and
this README.

## The pool: 14,059 tools (ruled in the Task 9 review)

The pool is the one the spec's counts and its 0.386 BM25 baseline were measured on: the
13,862 ids `toolbench_tool_*` of config `web` plus the 197 ids `toolbench_sam_tool_*` of
config `customized` (ToolRet's `toolbench-sam` tools), both in `mangopy/ToolRet-Tools` at
revision `e06c38c75612…`. The spec's first wording named config `web` alone (13,862 tools);
the review ruled for the 14,059 and corrected the spec and plan. ToolRet-Tools holds 44,453
tools at that revision (`web` 37,292, `code` 3,794, `customized` 3,367); the other ids are
other datasets' tools. No gold label is a `toolbench_sam` tool, so they are distractors.

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
| tools_web | `mangopy/ToolRet-Tools` @ `e06c38c75612b6536bd959e08cdd345894aba6a7` | `web/tools-00000-of-00001.parquet` | 8,143,446 | `57faceebd778b2cb74571dca0e71e8bc8078c11ba05dce0efc562e818d3950e6` |
| tools_customized | `mangopy/ToolRet-Tools` @ `e06c38c75612b6536bd959e08cdd345894aba6a7` | `customized/tools-00000-of-00001.parquet` | 384,413 | `e3d0cf64f5d5321751401677c820c5e8c7df79bfd67a85c01e275fe573cbde41` |
| queries | `mangopy/ToolRet-Queries` @ `b8c76ad3349ff17497b6bdb28bb5b8f61a0f6445` | `toolbench/queries-00000-of-00001.parquet` | 922,485 | `2bb32ea009d6ece37b1b785330247aacac037a20dd4522632cb3359809c8837d` |

The tools files have columns `id` and `documentation` (a JSON string: ToolBench's
`category_name`, `name`, `description`, `method`, parameter lists for `toolbench_tool_*`;
only `name` and `description` for `toolbench_sam_tool_*`); the queries file has `id`,
`query`, `instruction`, `labels` (a JSON string of `{id, doc, relevance}`) and `category`.
The query field is used; `instruction` is not.

## Counts (measured 2026-11-16, `manifest.json`)

| | Measured | Spec §8.3 |
|---|---|---|
| Tools | 14,059 (13,862 web + 197 customized) | 14,059 |
| Queries | 1,100 | 1,100 |
| Gold tools per query | 2.39 (2,629 labels, 1,632 distinct, all relevance 1) | 2.39 |
| Gold tools missing from the tools | 0 | 0 |
| Raw documentation tokens (harness tokenizer) | 1,227,462 (mean 87.3, median 58); web 1,218,889, customized 8,573 | 1,227,462 (mean 87, median 58) |
| Dev / test (SHA-256 of the id mod 5) | 212 / 888 | about 220 / 880 |

## Records

`adr tools ingest --toolret` turns each tool into a tool record (`adr_store.tool_records.
from_toolret`): `source_uri` `toolret:mangopy/ToolRet-Tools@<revision>/<config>#<toolret id>`
with the tool's own config (`web` or `customized`; gold ids map to `tool_id`s through it),
`source_version` the revision, `license` the tool file's own licence in `config.json`
(`Apache-2.0` for `web`, `NOASSERTION` for `customized`), parameters as an object schema
with `required`, `operation` = category, API name and method, or null for the
`toolbench_sam` tools, which have none of those fields. `toolbench_sam_tool_95` has an empty
name; a ToolRet document whose name is empty or whitespace is named by its ToolRet id.

Measured: 14,059 records, 100% structural conformance (C1), 816,284 definition tokens in all
(the 197 `toolbench_sam` records 9,348); the tool snapshot is
`a0dcedeff9abeb84f3d5994b8225c0d32408724fb087c2492fec644a66ef544e` on every ingest, into the
same store or a new one (the content snapshot of the tools-only store is the empty one,
`de13b4a8eeac…`). Earlier snapshots: `51536a400bba…` (Tasks 9–12), where all 14,059 records
said `Apache-2.0`; Task 13 gave each tools file its own licence, which changed the 197
`toolbench_sam` records' `license` field only (the 14,059 `tool_id`s are unchanged, since a
`tool_id` does not include the licence). The first ingest of the 13,862 web tools alone gave
`a6a3a6cc171d…`; the web records are byte-identical in all three.

ACL (`adr acl sync`, tools keyed by `tool_id` through the bucket rule of spec §5.2): public
2,832, two tenants 1,392, one tenant 6,337, one group 3,498 (20.1 / 9.9 / 45.1 / 24.9%).

Two things the records keep as the source gives them (notes, no change):

- **Defaults are not coerced to their type.** A ToolBench default is copied as given, so
  4,137 parameter defaults do not match their property's JSON type (for example a `number`
  parameter with the default `"5"`). JSON Schema treats `default` as an annotation, so the
  schema is still valid.
- **22 names fall outside MCP's recommended tool-name charset or length**
  (`[A-Za-z0-9_.-]`, 1 to 128 characters; a SHOULD in the MCP specification): 2 web names
  longer than 128 characters and 20 `toolbench_sam` names with spaces, quotes or `/` (such
  as `curl -X GET '…'` commands and `DataFrame.loc[...]`). `mcp.types.Tool` accepts them;
  Task 12 validates with it.

## Licence

- **The 13,862 `toolbench_tool_*` tools (config `web`):** ToolBench data, Apache-2.0 (its
  README: "distributed under Apache License 2.0").
- **The 197 `toolbench_sam_tool_*` tools (config `customized`): unclear.** They are not
  ToolBench's RapidAPI data. The ToolRet-Tools and ToolRet-Queries dataset cards (at the pinned
  revisions), the files' metadata and the ToolRet code README name neither their upstream nor a
  licence (checked in Task 11). Their style (Python spreadsheet and DataFrame methods, curl
  commands) matches SambaNova's ToolBench (Xu et al., 2023), whose repository carries an
  Apache-2.0 LICENSE on its default branch; that attribution is an inference, not stated by
  ToolRet. Their records therefore say `license` "NOASSERTION" (`config.json` gives each tools
  file its own licence since Task 13; until then one pool-wide "Apache-2.0" was copied into
  all 14,059 records, and `load_tool` returned it to agents).
- **ToolRet code repository:** Apache-2.0. **The ToolRet dataset cards declare no licence**
  (open question Q2), which is why the data stays local.
