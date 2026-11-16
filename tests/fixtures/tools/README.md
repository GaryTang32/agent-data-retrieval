# Tool fixtures (Phase 2C)

Fixtures for the tool adapters (`adr_store.tool_records`) and the ToolRet corpus module
(`adr_eval.corpora.toolret`). Phase 2 spec §8.1, §8.3, §12 Tools.

## Hand-made (CC0-1.0, written for these tests)

- `mcp/handmade.json`: a captured-`tools/list` file of an invented notes server: a tool with
  title and outputSchema, one whose `inputSchema` has no `properties`, one with annotations.
- `openapi/handmade.json`: an invented OpenAPI 3.0.3 document with path-item and operation
  parameters (path, query, header; a `$ref` parameter), a request body with JSON and XML media
  types, a `$ref` cycle (`Node.children[] -> Node`, cut at depth 8), the same parameter name
  in path and query, path parameters marked `required: false` or not marked (they are required
  all the same), an operation without `operationId`, and an array (non-object) response.
- `toolret_sample.jsonl`: **synthetic** rows in the shape of ToolRet's three parquet files,
  one JSON object per line, `{"table": "tools_web" | "tools_customized" | "queries", "row":
  {...}}`. Tool rows have ToolRet's `id` and `documentation` (a JSON string: for
  `toolbench_tool_*`, ToolBench's `category_name`, `name`, `description`, `method`,
  `required_parameters`, `optional_parameters`, optional `template_response`; for
  `toolbench_sam_tool_*`, only `name` and `description`); query rows have `id`, `query`,
  `instruction`, `labels` (a JSON string of `{"id", "doc", "relevance"}`) and `category`.
  Every name, description and query is invented: no ToolRet or ToolBench text is committed
  (Phase 2 spec Q2, ruling R13). It includes a `toolACE_tool_*` row in `web` and a
  `toolalpaca_tool_*` row in `customized`, which the prefixes leave out, a `toolbench_sam`
  tool with an empty name (as `toolbench_sam_tool_95` upstream), duplicate parameter names,
  every parameter type spelling seen in the real data, and `toolbench_query_18`, the one
  dev-split query.

## MCP reference servers (MIT), captured 2026-11-16

`mcp/<package>-<version>.json` holds the `tools/list` result of an official MCP reference
server, captured once with raw JSON-RPC over stdio (`initialize`, `notifications/initialized`,
`tools/list`; protocol version 2025-06-18) from a throwaway virtual environment outside the
repository (`pip install mcp-server-time==2026.10.28 mcp-server-fetch==2026.10.28
mcp-server-git==2026.10.28`; it pulled `mcp` 2.3.0). The pinned version is the newest
release at least two weeks old on the capture date (2026.11.4 and 2026.11.11 were newer). The
wheel digests below match PyPI's. Each file records `server`, `package`, `version`,
`license`, `source_uri` (`pypi:<package>@<version>`), `wheel`, `wheel_sha256`, `command`,
`protocol_version`, `server_info`, `captured`, `tools_list` and `tools_list_sha256` (SHA-256
of the canonical JSON of `tools_list`, checked by the tests).

| File | Tools | Wheel SHA-256 | `tools_list` SHA-256 |
|---|---|---|---|
| `mcp-server-time-2026.10.28.json` (run with `--local-timezone UTC`) | 2 | `4b8a1865e8c45da2d2247e72ca83ea087e5c8bc597c9ca93c63e9103aeb46c31` | `852dbce3bd6d75213fee934c586f7b260b513ed023dce1ec2bd54bd83cc23f0b` |
| `mcp-server-fetch-2026.10.28.json` | 1 | `b339038f5942ce9a2b067f8e9466447c88433296ba2589321bec20d533a4d2c5` | `24616d483e93c2086b60935a3090508ca6ffdb145d2ffca3a3eb5ace4d299dc0` |
| `mcp-server-git-2026.10.28.json` | 12 | `3c4a908d0f13731229bccd52b640147747413461d171297e9cdbc855783a9119` | `2ef64fc8faffd52542a8cf33007cf7144ca1db531e6218ccbeb1d7483528fbac` |

Tool descriptions are the servers' own text, kept verbatim. They are untrusted data (the
`fetch` description, for one, addresses the model); the store returns them as data.

## OpenAPI specs from APIs.guru (CC0-1.0)

`openapi/apisguru/` holds 20 OpenAPI 3.x JSON documents, byte for byte as served by the
`gh-pages` branch of [APIs-guru/openapi-directory](https://github.com/APIs-guru/openapi-directory)
at commit `aa43d9ae7f9594c1d5413f2596f3ef83ea9f3809` (the branch head on 2026-11-16, read with
`git ls-remote`), from
`https://raw.githubusercontent.com/APIs-guru/openapi-directory/<commit>/v2/specs/.../openapi.json`.
The collection is CC0 1.0 (the repository's `LICENSE`). JSON only, so no YAML parser is needed.

Selection (recorded in `openapi/apisguru/index.json` with each file's API key, version,
size, SHA-256 and `source_uri`, and the 10 candidates skipped): the APIs of `v2/list.json` at
the commit whose preferred version is OpenAPI 3.x with a `.../openapi.json` URL (1,521),
ordered by `SHA-256("adr-tools-openapi\n" + <api key>)`, fetched in that order, kept when
under 200,000 bytes, valid JSON with `openapi` 3.x and at least one operation, until 20 were
kept. The adapter's result played no part in the selection. All 20 (129 operations) ingest at
100% structural conformance.

| File | API | Version | OpenAPI | Bytes | SHA-256 (prefix) |
|---|---|---|---|---|---|
| `amazonaws.com__importexport__2010-06-01.json` | amazonaws.com:importexport | 2010-06-01 | 3.0.0 | 95,211 | `fd86f30dc8cfb416` |
| `amazonaws.com__runtime.lex.v2__2020-08-07.json` | amazonaws.com:runtime.lex.v2 | 2020-08-07 | 3.0.0 | 85,854 | `b3c8dd83162d64d5` |
| `amentum.space__gravity__1.1.1.json` | amentum.space:gravity | 1.1.1 | 3.0.0 | 8,792 | `c265a82568ec2ad9` |
| `apisetu.gov.in__hppanchayat__3.0.0.json` | apisetu.gov.in:hppanchayat | 3.0.0 | 3.0.0 | 37,572 | `2535707951efd3ed` |
| `apisetu.gov.in__maxlifeinsurance__3.0.0.json` | apisetu.gov.in:maxlifeinsurance | 3.0.0 | 3.0.0 | 38,199 | `d62ee21b76295791` |
| `apisetu.gov.in__phedharyana__3.0.0.json` | apisetu.gov.in:phedharyana | 3.0.0 | 3.0.0 | 43,420 | `60f3671671d73a7c` |
| `apisetu.gov.in__tbse__3.0.0.json` | apisetu.gov.in:tbse | 3.0.0 | 3.0.0 | 37,945 | `79ac51cc6f2ec660` |
| `apisetu.gov.in__transport__3.0.0.json` | apisetu.gov.in:transport | 3.0.0 | 3.0.0 | 89,782 | `8e15e26c98a7c16a` |
| `clickup.com__1.0.0.json` | clickup.com | 1.0.0 | 3.0.0 | 4,443 | `62e8866b8bf91477` |
| `googleapis.com__lifesciences__v2beta.json` | googleapis.com:lifesciences | v2beta | 3.0.0 | 65,122 | `f85aaf3a50a14ab0` |
| `googleapis.com__mybusinesslodging__v1.json` | googleapis.com:mybusinesslodging | v1 | 3.0.0 | 195,691 | `3b27f30dee9f253c` |
| `googleapis.com__playdeveloperreporting__v1beta1.json` | googleapis.com:playdeveloperreporting | v1beta1 | 3.0.0 | 131,087 | `a86832b0b70e0905` |
| `googleapis.com__secretmanager__v1beta1.json` | googleapis.com:secretmanager | v1beta1 | 3.0.0 | 65,615 | `a0fc6f0ac93e6482` |
| `hubapi.com__auth__v1.json` | hubapi.com:auth | v1 | 3.0.1 | 11,861 | `5f5c0d8785a5c61b` |
| `interzoid.com__getcitymatch__1.0.0.json` | interzoid.com:getcitymatch | 1.0.0 | 3.0.0 | 3,400 | `8fbf532330e71d98` |
| `interzoid.com__getfullnameparsedmatch__1.0.0.json` | interzoid.com:getfullnameparsedmatch | 1.0.0 | 3.0.0 | 4,082 | `eb5c1ad3f6779337` |
| `interzoid.com__lookupareacode__1.0.0.json` | interzoid.com:lookupareacode | 1.0.0 | 3.0.0 | 3,506 | `619a06be449447a3` |
| `lgtm.com__v1.0.json` | lgtm.com | v1.0 | 3.0.1 | 119,083 | `69a1c8a4de6c09fa` |
| `sportsdata.io__soccer-v3-scores__1.0.json` | sportsdata.io:soccer-v3-scores | 1.0 | 3.0.0 | 72,596 | `f152ce23a6ad9b38` |
| `telematicssdk.com__1.0.0.json` | telematicssdk.com | 1.0.0 | 3.0.3 | 199,622 | `7e37225732704596` |
