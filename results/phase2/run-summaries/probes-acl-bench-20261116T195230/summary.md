# ACL probes: bench

Store `.cache/store-p2/bench` (snapshot `7d8d1f8adda6`, ACL snapshot `5e8668b7a3a7` sequence 14), index `8c7bb39d032b`, 20 reference stores. Seed 20261116. No model calls.

## Leak probes

| family | probes | leaks | invalid | callers | kinds checked |
|---|---|---|---|---|---|
| search-rare | 100 | 0 | 0 | 20 | id_outside_view 96, alternate_outside_view 96, hidden_text 100, not_found_differs 0, count_includes_hidden 96, score_differs 96 |
| search-title | 50 | 0 | 0 | 18 | id_outside_view 50, alternate_outside_view 50, hidden_text 50, not_found_differs 0, count_includes_hidden 50, score_differs 50 |
| grep-literal | 50 | 0 | 0 | 19 | id_outside_view 46, alternate_outside_view 46, hidden_text 50, not_found_differs 0, count_includes_hidden 46, score_differs 46 |
| grep-doc | 20 | 0 | 0 | 12 | id_outside_view 0, alternate_outside_view 0, hidden_text 20, not_found_differs 17, count_includes_hidden 0, score_differs 0 |
| read | 60 | 0 | 0 | 20 | id_outside_view 0, alternate_outside_view 0, hidden_text 60, not_found_differs 56, count_includes_hidden 0, score_differs 0 |
| alternate-cross-view | 13 | 0 | 0 | 13 | id_outside_view 13, alternate_outside_view 13, hidden_text 13, not_found_differs 0, count_includes_hidden 13, score_differs 13 |

Total: 293 probes, 0 leaks, 0 invalid.

## Fail closed

| condition | probes | passed | with content | visible before | top 10 before | outcomes |
|---|---|---|---|---|---|---|
| F1 | 15 | 15 | 0 | 15 | 15 | denied:F1 15 |
| F2 | 15 | 15 | 0 | 15 | 15 | denied:F2 15 |
| F3 | 15 | 15 | 0 | 15 | 15 | denied:F3 15 |
| F4 | 15 | 15 | 0 | 0 | 0 | denied:F4 15 |
| F5 | 15 | 15 | 0 | 0 | 0 | denied:F5 15 |
| no_entry | 15 | 15 | 0 | 15 | 15 | ok 10, refused 5 |

Total: 90 probes, 90 passed, 0 with content.

## Log fields

681 log lines, 681 with caller, principals, acl_snapshot and acl_decision; 591 allowed, 0 of them with a null caller, principals, acl_snapshot or view.
