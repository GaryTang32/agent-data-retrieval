# Unit probes: leak (gov)

Store `.cache/store-p2/gov` (snapshot `f002821f2cb3`, units `a405942225cb`). Seed 20261121. Tools: define, rule_lookup, procedure_lookup, unit_search. No model calls.

300 leak probes, 0 leaks, 0 invalid; 300 compared with a reference store.

| family | probes | leaks | invalid | callers | outcomes |
|---|---|---|---|---|---|
| by-id | 100 | 0 | 0 | 19 | refused,refused 100 |
| by-term | 60 | 0 | 0 | 19 | ok,ok 60 |
| by-query | 60 | 0 | 0 | 17 | ok,ok 18, ok,ok,ok 42 |
| by-closure | 40 | 0 | 0 | 17 | ok,ok 20, refused,ok 20 |
| by-error | 40 | 0 | 0 | 18 | refused,refused,refused 40 |

## Log fields

1364 log lines (1364 of the unit tools, for 1364 unit calls; 0 log(s) whose count differs, 0 missing), 1364 with caller, principals, acl_snapshot and acl_decision; 0 without `units`; 1364 allowed, 0 of them with a null resolved field or units id. SQL statement text: not applicable (the unit tools take no SQL). Complete: True.
