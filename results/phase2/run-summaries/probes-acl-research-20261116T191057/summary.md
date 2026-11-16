# ACL probes: research

Store `.cache/store-p2/research` (snapshot `97c415b1aa71`, ACL snapshot `eb8d30401613` sequence 11), index `d3902b136e26`, 20 reference stores. Seed 20261116. No model calls.

## Leak probes

| family | probes | leaks | invalid | callers | kinds checked |
|---|---|---|---|---|---|
| search-rare | 100 | 0 | 0 | 20 | id_outside_view 96, alternate_outside_view 96, hidden_text 100, not_found_differs 0, count_includes_hidden 96, score_differs 96 |
| search-title | 50 | 0 | 0 | 18 | id_outside_view 50, alternate_outside_view 50, hidden_text 50, not_found_differs 0, count_includes_hidden 50, score_differs 50 |
| grep-literal | 50 | 0 | 0 | 19 | id_outside_view 46, alternate_outside_view 46, hidden_text 50, not_found_differs 0, count_includes_hidden 46, score_differs 46 |
| grep-doc | 20 | 0 | 0 | 12 | id_outside_view 0, alternate_outside_view 0, hidden_text 20, not_found_differs 17, count_includes_hidden 0, score_differs 0 |
| read | 60 | 0 | 0 | 20 | id_outside_view 0, alternate_outside_view 0, hidden_text 60, not_found_differs 56, count_includes_hidden 0, score_differs 0 |

Total: 280 probes, 0 leaks, 0 invalid.

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

655 log lines, 655 with caller, principals, acl_snapshot and acl_decision; 565 allowed, 0 of them with a null caller, principals, acl_snapshot or view.
