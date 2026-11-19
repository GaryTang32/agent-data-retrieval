# ACL probes through MCP (B1 subset)

The 300 of 1053 leak probes with the lowest SHA-256 of `<seed>:<store>/<probe id>` (seed 20261116), each through an `adr mcp` server of its caller. No model calls.

| family | universe | probes | leaks | invalid | callers | outcomes |
|---|---|---|---|---|---|---|
| search-title | 150 | 38 | 0 | 0 | 15 | ok 38 |
| search-rare | 300 | 95 | 0 | 0 | 20 | denied:F4 6, ok 89 |
| tool-load | 100 | 24 | 0 | 0 | 13 | denied:F4 1, refused 23 |
| read | 180 | 48 | 0 | 0 | 18 | denied:F4 5, refused 43 |
| grep-literal | 150 | 46 | 0 | 0 | 17 | denied:F4 4, ok 42 |
| tool-search | 100 | 28 | 0 | 0 | 14 | ok 28 |
| grep-doc | 60 | 19 | 0 | 0 | 9 | denied:F4 3, refused 16 |
| alternate-cross-view | 13 | 2 | 0 | 0 | 2 | ok 2 |

| spec family | universe | probes | leaks | invalid |
|---|---|---|---|---|
| search | 463 | 135 | 0 | 0 |
| grep | 210 | 65 | 0 | 0 |
| read | 180 | 48 | 0 | 0 |
| search_tools/load_tool | 200 | 52 | 0 | 0 |

Total: 300 probes, 0 leaks, 0 invalid. Spec families under 20: none.

## Log fields (MCP calls)

382 calls through MCP; 382 log lines in the probed stores, 382 with caller, principals, acl_snapshot and acl_decision; 363 allowed, 0 of them unresolved.
