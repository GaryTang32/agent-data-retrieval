# Table probes: leak (gov)

Store `.cache/store-p2/gov` (snapshot `f002821f2cb3`, tables `2678b8da9633`, ACL snapshot `c4573fde7762` sequence 18). Seed 20261120. No model calls.

300 leak probes, 0 leaks, 0 invalid (19 as user:ghost, denied F4).

| family | probes | leaks | invalid | callers | outcomes |
|---|---|---|---|---|---|
| by-key | 100 | 0 | 0 | 20 | denied:F4 7, ok 93 |
| by-filter | 80 | 0 | 0 | 20 | denied:F4 3, ok 77 |
| by-aggregate | 60 | 0 | 0 | 20 | denied:F4 5, ok 55 |
| by-group | 40 | 0 | 0 | 18 | denied:F4 2, ok 38 |
| by-error | 20 | 0 | 0 | 10 | denied:F4,denied:F4,denied:F4 2, refused,refused,ok 18 |

## Log fields

657 log lines (657 of the table tools), 657 with caller, principals, acl_snapshot and acl_decision; 0 without `tables`; 634 allowed, 0 of them with a null resolved field or tables id; 0 with statement text. Complete: True.
