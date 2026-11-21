# Unit probes: leak (bench)

Store `.cache/store-p2/bench` (snapshot `7d8d1f8adda6`, units `d50f23029eed`). Seed 20261121. Tools: define, rule_lookup, procedure_lookup, unit_search. No model calls.

100 leak probes, 0 leaks, 0 invalid; 100 compared with a reference store.

| family | probes | leaks | invalid | callers | outcomes |
|---|---|---|---|---|---|
| by-id | 20 | 0 | 0 | 13 | refused,refused 20 |
| by-term | 20 | 0 | 0 | 13 | ok,ok 20 |
| by-query | 20 | 0 | 0 | 12 | ok,ok 10, ok,ok,ok 10 |
| by-closure | 20 | 0 | 0 | 13 | ok,ok 20 |
| by-error | 20 | 0 | 0 | 13 | refused,refused,refused 20 |

## Log fields

460 log lines (460 of the unit tools, for 460 unit calls; 0 log(s) whose count differs, 0 missing), 460 with caller, principals, acl_snapshot and acl_decision; 0 without `units`; 460 allowed, 0 of them with a null resolved field or units id. SQL statement text: not applicable (the unit tools take no SQL). Complete: True.
