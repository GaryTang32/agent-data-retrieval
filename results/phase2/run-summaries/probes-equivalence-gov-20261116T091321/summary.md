# Equivalence probes (B2): gov

Store `.cache/store-p2/gov` (snapshot `f002821f2cb3`, ACL snapshot `4e3d4100e66d` sequence 3), index `54c12a3c2917`. 20 views x 50 questions x search and grep x 2 modes. Seed 20261116. No model calls.

| tool/mode | checks | identical | refused | empty |
|---|---|---|---|---|
| grep/p2-default | 1000 | 1000 | 0 | 98 |
| grep/phase1 | 1000 | 1000 | 0 | 90 |
| search/p2-default | 1000 | 1000 | 0 | 0 |
| search/phase1 | 1000 | 1000 | 0 | 0 |

Identical: 4000 of 4000. Log lines: 8000, all with caller, principals, acl_snapshot and acl_decision: True.
