"""The scan behind `adr grep` (`adr_store.tools`), run in a worker process so that a pattern
that backtracks for minutes can be stopped at a deadline. The tools start it as
`python -I grep_worker.py <request fd> <response fd> <timeout> <parent pid>`: a fresh
interpreter that imports only the standard library, so it starts in a few hundredths of a
second (a `multiprocessing` spawn child re-imports the parent's main module, which for `adr`
is the whole command line, about 1.5 s). `scan` is also what an in-process scan runs.

The worker does not outlive its parent: it limits its own CPU time to `timeout` + 2 s
(`RLIMIT_CPU`, all requests together, as the parent's deadline; SIGKILL 1 s later), and on
Linux asks to be killed when the parent dies (`PR_SET_PDEATHSIG`), then exits at once if the
parent is already gone. POSIX only (the pipes are passed as file descriptors).
"""

from __future__ import annotations

import math
import os
import re
import resource
import signal
import sys
from multiprocessing.connection import Connection

# scan status: every match returned; another match exists after `limit`; a zero-width match
DONE, MORE, EMPTY = "done", "more", "empty"


def scan(rx: re.Pattern, docs: list[tuple[str, str]], limit: int):
    """The matches of `rx` in `docs` ((doc_id, text), scanned in the given order), in offset
    order within a document, at most `limit`: ([(doc_id, start, end, line)], status). `line`
    is 1 plus the number of `\\n` before the match. The scan stops at the first match after
    `limit` (MORE) or at a zero-width match (EMPTY)."""
    out: list[tuple[str, int, int, int]] = []
    for doc_id, text in docs:
        line, counted = 1, 0  # line number at offset `counted`
        for m in rx.finditer(text):
            if len(out) == limit:
                return out, MORE
            if m.start() == m.end():
                return out, EMPTY
            line += text.count("\n", counted, m.start())
            counted = m.start()
            out.append((doc_id, m.start(), m.end(), line))
    return out, DONE


def serve(requests: Connection, responses: Connection) -> None:
    """The worker: say "ready", then answer each request (pattern, flags, limit, docs) with
    ("ok", scan result) or ("error", message), until None or the parent goes away."""
    try:
        responses.send("ready")
        while (request := requests.recv()) is not None:
            pattern, flags, limit, docs = request
            try:
                responses.send(("ok", scan(re.compile(pattern, flags), docs, limit)))
            except Exception as e:  # reported to the parent, which raises it
                responses.send(("error", f"{type(e).__name__}: {e}"))
    except (EOFError, BrokenPipeError):
        pass
    finally:
        requests.close()
        responses.close()


PR_SET_PDEATHSIG = 1  # <linux/prctl.h>


def bound(timeout: float, parent: int) -> None:
    """Limit the worker's CPU time to `timeout` (+ 2 s) and tie it to the `parent` process."""
    soft, hard = math.ceil(timeout) + 2, math.ceil(timeout) + 3
    limit = resource.getrlimit(resource.RLIMIT_CPU)[1]
    if limit != resource.RLIM_INFINITY:  # an unprivileged process cannot raise it
        soft, hard = min(soft, limit), min(hard, limit)
    resource.setrlimit(resource.RLIMIT_CPU, (soft, hard))
    if sys.platform.startswith("linux"):
        try:
            import ctypes

            ctypes.CDLL(None, use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)
        except (OSError, AttributeError):  # best effort; the CPU limit still applies
            pass
    if os.getppid() != parent:  # the parent died before the death signal was set
        sys.exit(1)


if __name__ == "__main__":
    bound(float(sys.argv[3]), int(sys.argv[4]))
    serve(Connection(int(sys.argv[1]), writable=False),
          Connection(int(sys.argv[2]), readable=False))
