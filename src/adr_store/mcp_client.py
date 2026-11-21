"""A blocking client of an `adr mcp` server process, shaped like `adr_store.tools.Tools` (the
tool methods of `mcp_server.TOOL_NAMES`, the same result dataclasses, the same exceptions), so
code written against
the Python API (the tests, the leak probes of `adr_eval.probes.acl`) can run through MCP
unchanged.

    with McpTools(store, "user:acme-0", emb_cache=...) as t:
        t.search("refund deadline").hits

`McpTools` starts `python -m adr_store.cli mcp --store S --as USER` as a subprocess and talks
to it with the SDK's `mcp.Client` over stdio, from an event loop in a thread of its own
(`anyio.from_thread`). Each method sends the arguments it is given (None ones are left out, so
the server's defaults apply), and returns the result dataclass rebuilt from the structured
content, or raises what the error text names: `AccessDenied` for "access denied (F<n>): …",
else `ToolError` with the text exactly. The client adds nothing to what the server returns.
Needs the `[mcp]` extra.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from adr_store import tools
from adr_store.dedup import Alternate
from adr_store.mcp_server import NO_MCP, McpUnavailable

DENIED = re.compile(r"^access denied \((F[1-5])\): ")


def result_of(name: str, d: dict):
    """The result dataclass of tool `name` from its structured content."""
    if name == "search":
        hits = [tools.Hit(**{**h, "alternates": [Alternate(**a) for a in h["alternates"]]})
                for h in d["hits"]]
        return tools.SearchResult(**{**d, "hits": hits})
    if name == "grep":
        return tools.GrepResult(**{**d, "matches": [tools.GrepMatch(**m)
                                                    for m in d["matches"]]})
    if name == "search_tools":
        return tools.SearchToolsResult(**{**d, "hits": [tools.ToolHit(**h)
                                                        for h in d["hits"]]})
    if name == "define":
        return tools.DefineResult(**{**d, "senses": [tools.Sense(**x) for x in d["senses"]]})
    if name == "rule_lookup":
        return tools.RuleLookupResult(**{**d, "cards": [tools.RuleCard(**c)
                                                        for c in d["cards"]]})
    return {"read": tools.ReadResult, "load_tool": tools.LoadToolResult,
            "describe_tables": tools.DescribeResult, "query_table": tools.QueryResult,
            "sql": tools.SqlResult, "procedure_lookup": tools.ProcedureLookupResult,
            "unit_search": tools.UnitSearchResult}[name](**d)


def error_of(text: str) -> tools.ToolError:
    m = DENIED.match(text)
    return tools.AccessDenied(m.group(1), text) if m else tools.ToolError(text)


def server_parameters(store: Path, caller: str | None, *, emb_cache: Path | None = None,
                      env: dict | None = None, cwd: Path | None = None):
    """The `StdioServerParameters` of `adr mcp` for this store and caller. The unit-index
    tuning override (`$ADR_UNITS_TUNING`, `units.index.TUNING_ENV`) is passed on when set."""
    try:
        from mcp import StdioServerParameters
    except ImportError as e:
        raise McpUnavailable(NO_MCP) from e
    args = ["-m", "adr_store.cli", "mcp", "--store", str(store)]
    from adr_store.units.index import TUNING_ENV  # the MCP SDK passes only a safe env subset

    if os.environ.get(TUNING_ENV) and TUNING_ENV not in (env or {}):
        env = {**(env or {}), TUNING_ENV: os.environ[TUNING_ENV]}
    if caller is not None:
        args += ["--as", caller]
    if emb_cache is not None:
        args += ["--emb-cache", str(emb_cache)]
    return StdioServerParameters(command=sys.executable, args=args, env=env,
                                 cwd=None if cwd is None else str(cwd))


class McpTools:
    """The tools of one `adr mcp` server process (module docstring). Close it (or use
    it as a context manager) to stop the server."""

    def __init__(self, store: Path, caller: str | None, *, emb_cache: Path | None = None,
                 env: dict | None = None, cwd: Path | None = None,
                 timeout: float | None = 120.0):
        from anyio.from_thread import start_blocking_portal
        from mcp import Client

        params = server_parameters(store, caller, emb_cache=emb_cache, env=env, cwd=cwd)
        self.caller = caller
        self._portal_cm = start_blocking_portal()
        self._portal = self._portal_cm.__enter__()
        try:
            self._client_cm = self._portal.wrap_async_context_manager(
                Client(params, read_timeout_seconds=timeout))
            self.client = self._client_cm.__enter__()
        except BaseException:
            self._portal_cm.__exit__(*sys.exc_info())
            raise

    def __enter__(self) -> McpTools:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._portal_cm is None:
            return
        try:
            self._client_cm.__exit__(None, None, None)
        finally:
            self._portal_cm.__exit__(None, None, None)
            self._portal_cm = None

    def list_tools(self):
        return self._portal.call(self.client.list_tools)

    def call(self, name: str, arguments: dict):
        """The raw `CallToolResult` of a call."""
        return self._portal.call(self.client.call_tool, name, arguments)

    def _run(self, name: str, **arguments):
        res = self.call(name, {k: v for k, v in arguments.items() if v is not None})
        if res.is_error:
            raise error_of("".join(c.text for c in res.content if c.type == "text"))
        return result_of(name, res.structured_content)

    def search(self, query, top=None, *, filters=None, dedup=None, cursor=None, handle=None):
        return self._run("search", query=query, top=top, filters=filters, dedup=dedup,
                         cursor=cursor, handle=handle)

    def read(self, doc_id, start=None, end=None, *, element=None, chunk=None, filters=None,
             handle=None):
        return self._run("read", doc_id=doc_id, start=start, end=end, element=element,
                         chunk=chunk, filters=filters, handle=handle)

    def grep(self, pattern, doc=None, max=None, ignore_case=None, timeout=None, *,
             filters=None, cursor=None, handle=None):
        return self._run("grep", pattern=pattern, doc=doc, max=max, ignore_case=ignore_case,
                         timeout=timeout, filters=filters, cursor=cursor, handle=handle)

    def search_tools(self, query, top=None, *, filters=None, handle=None):
        return self._run("search_tools", query=query, top=top, filters=filters, handle=handle)

    def load_tool(self, tool_id, *, handle=None):
        return self._run("load_tool", tool_id=tool_id, handle=handle)

    def describe_tables(self, table=None, *, handle=None):
        return self._run("describe_tables", table=table, handle=handle)

    def query_table(self, table, filters=None, op=None, *, fields=None, order=None, limit=None,
                    applicability=None, handle=None):
        return self._run("query_table", table=table, filters=filters, op=op, fields=fields,
                         order=order, limit=limit, applicability=applicability, handle=handle)

    def sql(self, statement, *, applicability=None, handle=None):
        return self._run("sql", statement=statement, applicability=applicability,
                         handle=handle)

    def define(self, term, context=None, *, as_of=None, include_superseded=None, handle=None):
        return self._run("define", term=term, context=context, as_of=as_of,
                         include_superseded=include_superseded, handle=handle)

    def rule_lookup(self, query=None, *, rule_id=None, part=None, as_of=None,
                    include_superseded=None, closure=None, limit=None, handle=None):
        return self._run("rule_lookup", query=query, rule_id=rule_id, part=part, as_of=as_of,
                         include_superseded=include_superseded, closure=closure, limit=limit,
                         handle=handle)

    def procedure_lookup(self, task=None, *, id=None, view=None, as_of=None, limit=None,
                         handle=None):
        return self._run("procedure_lookup", task=task, id=id, view=view, as_of=as_of,
                         limit=limit, handle=handle)

    def unit_search(self, query, types=None, *, as_of=None, limit=None, handle=None):
        return self._run("unit_search", query=query, types=types, as_of=as_of, limit=limit,
                         handle=handle)
