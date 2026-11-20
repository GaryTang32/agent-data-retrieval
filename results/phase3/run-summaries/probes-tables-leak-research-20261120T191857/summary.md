# Table probes: leak (research)

Store `.cache/store-p2/research` (snapshot `97c415b1aa71`, tables `62604e913378`, ACL snapshot `e79478bafb8b` sequence 20). Seed 20261120. No model calls.

100 leak probes, 0 leaks, 0 invalid (100 as user:ghost, denied F4).

| family | probes | leaks | invalid | callers | outcomes |
|---|---|---|---|---|---|
| by-key | 20 | 0 | 0 | 1 | denied:F4 20 |
| by-filter | 20 | 0 | 0 | 1 | denied:F4 20 |
| by-aggregate | 20 | 0 | 0 | 1 | denied:F4 20 |
| by-group | 20 | 0 | 0 | 1 | denied:F4 20 |
| by-error | 20 | 0 | 0 | 1 | denied:F4,denied:F4,denied:F4 20 |

## Log fields

140 log lines (140 of the table tools), 140 with caller, principals, acl_snapshot and acl_decision; 0 without `tables`; 0 allowed, 0 of them with a null resolved field or tables id; 0 with statement text. Complete: True.
