# Table probes: leak (gov)

Store `.cache/store-p2/gov` (snapshot `f002821f2cb3`, tables `2678b8da9633`, ACL snapshot `7099c7abca47` sequence 19). Seed 20261120. No model calls.

300 leak probes, 0 leaks, 0 invalid; 300 compared with a reference store, 0 as user:ghost (denied F4: no directory user has a hidden row).

| family | probes | leaks | invalid | callers | outcomes |
|---|---|---|---|---|---|
| by-key | 100 | 0 | 0 | 19 | ok 100 |
| by-filter | 80 | 0 | 0 | 19 | ok 80 |
| by-aggregate | 60 | 0 | 0 | 18 | ok 60 |
| by-group | 40 | 0 | 0 | 17 | ok 40 |
| by-error | 20 | 0 | 0 | 13 | refused,refused,ok 20 |

## Log fields

680 log lines (680 of the table tools), 680 with caller, principals, acl_snapshot and acl_decision; 0 without `tables`; 680 allowed, 0 of them with a null resolved field or tables id; 0 with statement text. Complete: True.
