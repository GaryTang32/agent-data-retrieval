"""Serve `Tools` calls as JSON lines over stdin/stdout from one long-lived process (the
revocation tests' "process started before the change", Phase 2 spec §12 Revocation).

    python -m tests.store.tools_proc --store DIR --emb-cache DIR [--as USER] [--clock ISO]

`--as` turns the ACL layer on (`Tools(acl=True, caller=USER)`); `--clock` fixes the clock the
freshness check (F3) reads (an ISO time with its offset; default: the real clock). Each
request is one line `{"method": "search" | "read" | "grep", "args": [...], "kwargs": {...}}`;
each reply is one line, `{"ok": <the result as a dict>}` or `{"error": <message>,
"type": <exception class>, "code": <F1..F5 or null>}`. The process ends at end of input.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from adr_store import tools

METHODS = ("search", "read", "grep")


def serve(t: tools.Tools, lines, out) -> None:
    for line in lines:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            if req.get("method") not in METHODS:
                raise tools.ToolError(f"unknown method {req.get('method')!r}")
            res = getattr(t, req["method"])(*req.get("args", []), **req.get("kwargs", {}))
            reply = {"ok": res.to_dict()}
        except Exception as e:  # every failure is a reply; the process keeps serving
            reply = {"error": str(e), "type": type(e).__name__,
                     "code": getattr(e, "code", None)}
        out.write(json.dumps(reply, ensure_ascii=False) + "\n")
        out.flush()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools_proc")
    ap.add_argument("--store", type=Path, required=True)
    ap.add_argument("--emb-cache", type=Path, required=True)
    ap.add_argument("--as", dest="caller", default=None)
    ap.add_argument("--clock", default=None, help="a fixed ISO time for the F3 check")
    a = ap.parse_args(argv)
    kw = {}
    if a.clock is not None:
        now = datetime.fromisoformat(a.clock)
        kw["clock"] = lambda: now
    t = tools.Tools(a.store, emb_cache=a.emb_cache, acl=a.caller is not None,
                    caller=a.caller, **kw)
    out = sys.stdout
    out.write(json.dumps({"ready": True}) + "\n")
    out.flush()
    serve(t, sys.stdin, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
