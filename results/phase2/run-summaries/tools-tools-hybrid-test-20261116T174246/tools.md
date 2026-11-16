# Tool retrieval: tools-hybrid on test

Store `.cache/store-p2/toolret`, tool snapshot `a0dcedeff9ab`, ACL snapshot `530decdda933`, tool index `c7d17539c08d` (w_name 3, fusion weight w = 0.6), searched as `user:auditor`. Tuned on dev nDCG@10 (212 queries).

active tool index: c7d17539c08d → c7d17539c08d (unchanged)

| queries | Completeness@10 | Recall@10 | nDCG@10 |
|---|---|---|---|
| 888 | 0.411 | 0.603 | 0.529 |

Tool context (mean per query): loaded 1256 tokens (page 510, definitions 746) of a catalog of 816284 tokens; reduction 99.8461%; gold share 0.063 (the mean over queries of the loaded gold definition tokens / loaded tokens; page entries are not counted as gold).

Wall-clock 565.6 s. No model calls.
