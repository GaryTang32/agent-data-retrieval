# ACL probes: tools

Store `.cache/store-p2/toolret` (tool snapshot `a0dcedeff9ab`, ACL snapshot `c8eea9f370d6` sequence 10), tool index `c7d17539c08d`. Seed 20261116. No model calls.

## Leak probes

| family | probes | leaks | invalid | callers | kinds checked |
|---|---|---|---|---|---|
| tool-search | 100 | 0 | 0 | 20 | id_outside_view 94, alternate_outside_view 0, hidden_text 100, not_found_differs 0, count_includes_hidden 94, score_differs 94 |
| tool-load | 100 | 0 | 0 | 19 | id_outside_view 0, alternate_outside_view 0, hidden_text 100, not_found_differs 96, count_includes_hidden 0, score_differs 0 |

Total: 200 probes, 0 leaks, 0 invalid.

## Fail closed

| condition | probes | passed | with content | outcomes |
|---|---|---|---|---|
| F1 | 10 | 10 | 0 | denied:F1 10 |
| F2 | 10 | 10 | 0 | denied:F2 10 |
| F3 | 10 | 10 | 0 | denied:F3 10 |
| F4 | 10 | 10 | 0 | denied:F4 10 |
| F5 | 10 | 10 | 0 | denied:F5 10 |
| no_entry | 10 | 10 | 0 | ok 5, refused 5 |
| F2-tools | 10 | 10 | 0 | denied:F2 10 |
| no-tool-snapshot | 10 | 10 | 0 | denied:F2 10 |

Total: 80 probes, 80 passed, 0 with content.

## Log fields

381 log lines, 381 with caller, principals, acl_snapshot and acl_decision; 301 allowed, 0 of them unresolved.
