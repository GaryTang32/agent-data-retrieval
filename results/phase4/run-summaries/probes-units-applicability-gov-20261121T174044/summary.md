# Unit probes: applicability (gov)

Store `.cache/store-p2/gov` (snapshot `f002821f2cb3`, units `a405942225cb`). Seed 20261121. Tools: define, rule_lookup, procedure_lookup, unit_search. No model calls.

255 probes (5 default, 250 as_of over 50 dates), 255 passed, 0 units of documents not in force.

| tool | probes | passed | with units | units outside | most versions returned |
|---|---|---|---|---|---|
| define | 51 | 51 | 38 | 0 | 1 |
| procedure_lookup | 51 | 51 | 25 | 0 | 1 |
| rule_lookup | 102 | 102 | 86 | 0 | 1 |
| unit_search | 51 | 51 | 44 | 0 | 1 |

## Log fields

255 log lines (255 of the unit tools, for 255 unit calls; 0 log(s) whose count differs, 0 missing), 255 with caller, principals, acl_snapshot and acl_decision; 0 without `units`; 255 allowed, 0 of them with a null resolved field or units id. SQL statement text: not applicable (the unit tools take no SQL). Complete: True.
