# Table probes: failclosed (gov)

Store `.cache/store-p2/gov` (snapshot `f002821f2cb3`, tables `fec2a2b12e31`, ACL snapshot `cd9f4c2335d8` sequence 26). Seed 20261120. No model calls.

90 probes, 90 passed, 0 with content; target document `7d10ca547e80` (fr_documents).

| condition | probes | passed | with content | outcomes |
|---|---|---|---|---|
| F1 | 15 | 15 | 0 | denied:F1 15 |
| F2 | 15 | 15 | 0 | denied:F2 15 |
| F3 | 15 | 15 | 0 | denied:F3 15 |
| F4 | 15 | 15 | 0 | denied:F4 15 |
| F5 | 15 | 15 | 0 | denied:F5 15 |
| no_entry | 15 | 15 | 0 | ok 15 |

## Log fields

115 log lines (115 of the table tools), 115 with caller, principals, acl_snapshot and acl_decision; 0 without `tables`; 40 allowed, 0 of them with a null resolved field or tables id; 0 with statement text. Complete: True.
