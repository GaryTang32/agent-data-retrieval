# Table probes: sql (gov)

Store `.cache/store-p2/gov` (snapshot `f002821f2cb3`, tables `fec2a2b12e31`, ACL snapshot `01c6d9a22b83` sequence 22). Seed 20261120. No model calls.

120 statements, 120 refused with a fixed message or bounded, 120 with the database intact afterwards.

| category | cases | passed | outcomes |
|---|---|---|---|
| write | 15 | 15 | refused:syntax 15 |
| ddl | 15 | 15 | refused:denied 1, refused:syntax 14 |
| attach | 6 | 6 | refused:syntax 6 |
| pragma | 12 | 12 | refused:denied 4, refused:syntax 8 |
| extension | 4 | 4 | refused:denied 4 |
| multi | 12 | 12 | refused:syntax 12 |
| recursive | 8 | 8 | ok 1, refused:budget 6, refused:rows 1 |
| cross_join | 8 | 8 | ok 2, refused:budget 5, refused:rows 1 |
| function | 20 | 20 | refused:budget 5, refused:denied 14, refused:rows 1 |
| trick | 20 | 20 | ok 2, refused:denied 11, refused:syntax 7 |

## Log fields

241 log lines (241 of the table tools), 241 with caller, principals, acl_snapshot and acl_decision; 0 without `tables`; 241 allowed, 0 of them with a null resolved field or tables id; 0 with statement text. Complete: True.
