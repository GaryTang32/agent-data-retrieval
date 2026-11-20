# Table probes through MCP (D1)

The 60 of 400 table leak probes with the lowest SHA-256 of `<seed>:<store>/<probe id>` (seed 20261120), each through an `adr mcp` server of its caller. No model calls.

60 probes, 0 leaks, 0 invalid (16 as user:ghost, denied F4). Handle replays: 44 of 44 identical, 44 handles naming the tables.

| store | probes | leaks | invalid |
|---|---|---|---|
| gov | 44 | 0 | 0 |
| research | 16 | 0 | 0 |

## Log fields

196 calls through MCP; 196 log lines in the probed stores (equal per store: True). Complete (MCP and reference logs): True.
