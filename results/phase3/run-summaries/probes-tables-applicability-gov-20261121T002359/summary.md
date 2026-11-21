# Table probes: applicability (gov)

Store `.cache/store-p2/gov` (snapshot `f002821f2cb3`, tables `fec2a2b12e31`, ACL snapshot `c94f2c47f239` sequence 23). Seed 20261120. No model calls.

153 probes on drawbridge_bridges, drawbridge_sections, fr_documents (3 default, 150 as_of over 56 dates), 153 passed, 0 rows of documents not in force.

| table | probes | passed | as_of | as_of with rows | rows outside | most versions returned |
|---|---|---|---|---|---|---|
| drawbridge_bridges | 51 | 51 | 50 | 14 | 0 | 1 |
| drawbridge_sections | 51 | 51 | 50 | 14 | 0 | 1 |
| fr_documents | 51 | 51 | 50 | 50 | 0 | 0 |

## Log fields

459 log lines (459 of the table tools), 459 with caller, principals, acl_snapshot and acl_decision; 0 without `tables`; 459 allowed, 0 of them with a null resolved field or tables id; 0 with statement text. Complete: True.
