# Equivalence probes (B2): bench

Store `.cache/store-p2/bench` (snapshot `7d8d1f8adda6`, ACL snapshot `5e8668b7a3a7` sequence 14), index `8c7bb39d032b`. 20 views x 50 questions x search and grep x 2 modes. Seed 20261116. No model calls.

| tool/mode | checks | identical | refused | empty |
|---|---|---|---|---|
| grep/p2-default | 1000 | 1000 | 0 | 13 |
| grep/phase1 | 1000 | 1000 | 0 | 13 |
| search/p2-default | 1000 | 1000 | 0 | 0 |
| search/phase1 | 1000 | 1000 | 0 | 0 |

Identical: 4000 of 4000. Log lines: 8000, all with caller, principals, acl_snapshot and acl_decision: True.
