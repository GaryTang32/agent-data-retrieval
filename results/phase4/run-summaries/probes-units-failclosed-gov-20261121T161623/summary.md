# Unit probes: failclosed (gov)

Store `.cache/store-p2/gov` (snapshot `f002821f2cb3`, units `a405942225cb`). Seed 20261121. Tools: define, rule_lookup, procedure_lookup, unit_search. No model calls.

120 probes (6 conditions × 4 tools × 5 callers), 120 passed, 0 with content.

| condition | probes | passed | with content | outcomes |
|---|---|---|---|---|
| F1 | 20 | 20 | 0 | denied:F1 20 |
| F2 | 20 | 20 | 0 | denied:F2 20 |
| F3 | 20 | 20 | 0 | denied:F3 20 |
| F4 | 20 | 20 | 0 | denied:F4 20 |
| F5 | 20 | 20 | 0 | denied:F5 20 |
| no_entry | 20 | 20 | 0 | ok 10, refused 10 |

## Log fields

150 log lines (150 of the unit tools, for 150 unit calls; 0 log(s) whose count differs, 0 missing), 150 with caller, principals, acl_snapshot and acl_decision; 0 without `units`; 50 allowed, 0 of them with a null resolved field or units id; 0 with statement text. Complete: True.
