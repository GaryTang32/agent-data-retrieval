# Unit probes through MCP (D1)

The 60 of 400 unit leak probes with the lowest SHA-256 of `<seed>:<store>/<probe id>` (seed 20261121), each through an `adr mcp` server of its caller. No model calls.

60 probes, 0 leaks, 0 invalid. Handle replays: 66 of 66 identical, 66 handles naming the units.

| store | probes | leaks | invalid |
|---|---|---|---|
| bench | 14 | 0 | 0 |
| gov | 46 | 0 | 0 |

## Log fields

332 calls through MCP; 332 unit-tool log lines in the probed stores (equal per store: True). Complete (MCP and reference logs): True.
