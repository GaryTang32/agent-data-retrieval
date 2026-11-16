"""Tools as data: the tool record and its three adapters (Phase 2 spec §8.1).

A tool record describes one callable tool as an MCP Tool would (name, title, description,
input and output JSON Schema) plus where the description came from. Its id is

    tool_id = SHA-256(source_uri + "\\n" + name + "\\n" + SHA-256(canonical JSON of input_schema))

(hex digests; canonical JSON is sorted keys, compact separators, UTF-8, no trailing newline).
`definition_tokens` is the harness token count (`adr_eval.retrieval.chunker._count`) of the
canonical JSON of the MCP definition's name, description and inputSchema (spec §8.1; title and
outputSchema are not counted).

Adapters (each record is checked by `conformance`, which is structural in Phase 2C: the input
schema is an object schema with a `properties` object whose values are schemas, `required` is
a list of distinct property names, an output schema is null or an object schema, and the id and
token count are those computed here; Task 12 adds validation by `mcp.types.Tool`):

- `from_mcp`: one record per tool of a `tools/list` result. An `inputSchema` without
  `properties` (MCP makes it optional) gets an empty `properties` object; everything else is
  taken as the server gives it. Two tools with one name are refused.
- `from_openapi`: OpenAPI 3.x, one record per operation, paths in sorted order and methods in
  the order of the Path Item object. Local `$ref`s (`#/...`) are resolved, with three bounds
  that keep a record small: a `$ref` already on the current expansion branch (a cycle) is cut,
  at most `REF_DEPTH` (8) are nested on one branch, and once an operation has expanded
  `NODE_BUDGET` (10,000) nodes further `$ref`s are cut; a cut, non-local or missing `$ref`
  becomes `{}` (any value), and each kind is counted (`stats`). The name
  is the `operationId`, else `<method><path>` with every run of other characters than
  `[A-Za-z0-9_.-]` replaced by `_` (none kept at either end); a name that repeats in one
  spec gets `__2`, `__3`, ... in that order. Title = `summary`; description =
  `description`, else `summary`, else "".
  Input schema: the path item's and the operation's parameters (the operation's replace the
  path item's of the same name and location), each a property named as the parameter (a
  second parameter of the same name in another location is `<name>__<in>`) whose schema is
  the parameter's `schema` (or its first media type's), with the parameter's description when
  the schema has none; path parameters and `required: true` ones are required. A request body
  is the property `body` (`application/json` first, else the first media type with "json" in
  its name, else the first; the body's description when the schema has none), required when
  the body is. Output schema: the JSON schema of the first 2xx response (codes in sorted
  order) that has one, kept only when it is an object schema (MCP requires one).
  `operation` = `{method (upper case), path, operationId (or null)}`.
- `from_toolret`: one ToolBench-style documentation dict (`category_name`, `name`,
  `description`, `method`, `required_parameters`, `optional_parameters`). Each parameter
  becomes a property with a JSON type (STRING/string/ENUM/DATE/TIME/GEOPOINT/BINARY -> string,
  NUMBER -> number, BOOLEAN -> boolean, ARRAY -> array, OBJECT -> object; none or unknown: no
  type), its description when not empty and its default when not "" or null; the first of two
  parameters with one name wins, and a name listed as required is required (in the order
  listed). `operation` = `{category, api_name, method}`; no title and no output schema.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from adr_eval.retrieval.chunker import _count

REF_DEPTH = 8
NODE_BUDGET = 10_000
REF_STATS = ("cycle_cuts", "depth_cuts", "budget_cuts", "external_refs", "missing_refs")
_HEX64 = r"^[0-9a-f]{64}$"
_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
_NAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")

SourceKind = Literal["mcp", "openapi", "toolret"]


class ToolRecord(BaseModel):
    """`<store>/tools/records/<tool_id[:2]>/<tool_id>.json` (spec §8.1). The description is
    untrusted text from the source, returned as data, never as instructions."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="ToolRecord")

    tool_id: str = Field(pattern=_HEX64)
    name: str
    title: str | None
    description: str
    input_schema: dict
    output_schema: dict | None
    source_kind: SourceKind
    source_uri: str
    source_version: str
    operation: dict | None
    license: str
    definition_tokens: int = Field(ge=0)


def canonical(obj) -> str:
    """Canonical JSON text of a JSON value: sorted keys, compact, non-ASCII kept."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tool_id(source_uri: str, name: str, input_schema: dict) -> str:
    """SHA-256 of `source_uri`, `name` and the SHA-256 of the canonical input schema, joined
    by newlines (spec §8.1)."""
    return _sha(f"{source_uri}\n{name}\n{_sha(canonical(input_schema))}")


def _token_count(name: str, description: str, input_schema: dict) -> int:
    return _count(canonical({"name": name, "description": description,
                             "inputSchema": input_schema}))


def definition(rec: ToolRecord) -> dict:
    """The MCP Tool definition: name, title (when set), description, inputSchema,
    outputSchema (when set)."""
    d: dict = {"name": rec.name}
    if rec.title is not None:
        d["title"] = rec.title
    d["description"] = rec.description
    d["inputSchema"] = rec.input_schema
    if rec.output_schema is not None:
        d["outputSchema"] = rec.output_schema
    return d


def make_record(*, name: str, title: str | None, description: str, input_schema: dict,
                output_schema: dict | None, source_kind: SourceKind, source_uri: str,
                source_version: str, operation: dict | None, license: str) -> ToolRecord:
    """A record with its `tool_id` and `definition_tokens` computed."""
    return ToolRecord(
        tool_id=tool_id(source_uri, name, input_schema), name=name, title=title,
        description=description, input_schema=input_schema, output_schema=output_schema,
        source_kind=source_kind, source_uri=source_uri, source_version=source_version,
        operation=operation, license=license,
        definition_tokens=_token_count(name, description, input_schema))


# -- conformance ------------------------------------------------------------------------------

def _object_schema_problems(what: str, schema, *, need_properties: bool) -> list[str]:
    if not isinstance(schema, dict):
        return [f"{what} is not an object"]
    if schema.get("type") != "object":
        return [f"{what} type is {schema.get('type')!r}, not 'object'"]
    problems = []
    props = schema.get("properties")
    if props is None:
        if need_properties:
            problems.append(f"{what} has no properties")
        props = {}
    elif not isinstance(props, dict):
        problems.append(f"{what} properties is not an object")
        props = {}
    else:
        bad = sorted(k for k, v in props.items() if not isinstance(v, dict | bool))
        if bad:
            problems.append(f"{what} properties {bad[:3]} are not schemas")
    if "required" in schema:
        req = schema["required"]
        if not isinstance(req, list) or not all(isinstance(r, str) for r in req):
            problems.append(f"{what} required is not a list of names")
        else:
            if len(set(req)) != len(req):
                problems.append(f"{what} required repeats a name")
            missing = sorted(set(req) - set(props))
            if missing:
                problems.append(f"{what} required names {missing[:3]} not in properties")
    return problems


def conformance(rec: ToolRecord) -> list[str]:
    """Structural problems of a record (none: it conforms); see the module docstring."""
    problems = []
    if not rec.name:
        problems.append("empty name")
    problems += _object_schema_problems("inputSchema", rec.input_schema, need_properties=True)
    if rec.output_schema is not None:
        problems += _object_schema_problems("outputSchema", rec.output_schema,
                                            need_properties=False)
    if rec.tool_id != tool_id(rec.source_uri, rec.name, rec.input_schema):
        problems.append("tool_id is not the hash of source_uri, name and input_schema")
    try:
        tokens = _token_count(rec.name, rec.description, rec.input_schema)
    except TypeError:
        tokens = None
    if rec.definition_tokens != tokens:
        problems.append(f"definition_tokens {rec.definition_tokens} != {tokens}")
    return problems


# -- MCP --------------------------------------------------------------------------------------

def from_mcp(tools_list: dict, server: str, source_uri: str, version: str,
             license: str) -> list[ToolRecord]:
    """One record per tool of a `tools/list` result, in the server's order."""
    out, seen = [], set()
    for t in tools_list.get("tools", []):
        name = t.get("name")
        if not isinstance(name, str):
            raise ValueError(f"{server}: a tool without a string name")
        if name in seen:
            raise ValueError(f"{server}: two tools are named {name!r}")
        seen.add(name)
        schema = t.get("inputSchema")
        if isinstance(schema, dict) and schema.get("type") == "object" \
                and "properties" not in schema:
            schema = {**schema, "properties": {}}
        out.append(make_record(
            name=name, title=t.get("title"), description=t.get("description") or "",
            input_schema=schema, output_schema=t.get("outputSchema"), source_kind="mcp",
            source_uri=source_uri, source_version=version, operation={"server": server},
            license=license))
    return out


# -- OpenAPI ----------------------------------------------------------------------------------

class _Resolver:
    """Deep resolution of local `$ref`s, bounded (module docstring): a `$ref` already on the
    current expansion branch (a cycle), one REF_DEPTH deep, one met after NODE_BUDGET nodes
    of the current operation, a non-local one and a missing one all become `{}`; `stats`
    counts each kind."""

    def __init__(self, spec: dict, stats: dict | None = None):
        self.spec = spec
        self.stats = stats if stats is not None else {}
        for key in REF_STATS:
            self.stats.setdefault(key, 0)
        self.nodes = 0

    def start(self) -> None:
        """A new operation: its own node budget."""
        self.nodes = 0

    def _target(self, ref: str):
        if not ref.startswith("#/"):
            return None
        node = self.spec
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict) and part in node:
                node = node[part]
            elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
                node = node[int(part)]
            else:
                return None
        return node

    def _expand(self, ref: str, branch: tuple[str, ...]):
        if ref in branch:
            cut = "cycle_cuts"
        elif len(branch) >= REF_DEPTH:
            cut = "depth_cuts"
        elif self.nodes > NODE_BUDGET:
            cut = "budget_cuts"
        elif not ref.startswith("#/"):
            cut = "external_refs"
        else:
            target = self._target(ref)
            if target is not None:
                return self.resolve(target, branch + (ref,))
            cut = "missing_refs"
        self.stats[cut] += 1
        return {}

    def resolve(self, node, branch: tuple[str, ...] = ()):
        if isinstance(node, list):
            self.nodes += 1
            return [self.resolve(x, branch) for x in node]
        if not isinstance(node, dict):
            return node
        self.nodes += 1
        ref = node.get("$ref")
        if isinstance(ref, str):
            out = self._expand(ref, branch)
            siblings = {k: self.resolve(v, branch) for k, v in node.items() if k != "$ref"}
            if siblings and isinstance(out, dict):
                out = {**out, **siblings}
            return out
        return {k: self.resolve(v, branch) for k, v in node.items()}


def _media_schema(content, prefer_json: bool = True):
    """The schema of a content map's preferred media type (or None)."""
    if not isinstance(content, dict) or not content:
        return None
    keys = sorted(content)
    pick = None
    if "application/json" in content:
        pick = "application/json"
    elif prefer_json:
        pick = next((k for k in keys if "json" in k.lower()), None)
    if pick is None:
        pick = keys[0]
    media = content[pick]
    return media.get("schema") if isinstance(media, dict) else None


def _with_description(schema, description) -> dict:
    schema = dict(schema) if isinstance(schema, dict) else {}
    if isinstance(description, str) and description and "description" not in schema:
        schema["description"] = description
    return schema


def _free_key(props: dict, name: str, alt: str) -> str:
    if name not in props:
        return name
    key, n = alt, 2
    while key in props:
        key, n = f"{alt}{n}", n + 1
    return key


def _operation_input(res: _Resolver, item: dict, op: dict) -> dict:
    params: dict[tuple[str, str], dict] = {}
    for p in (item.get("parameters") or []) + (op.get("parameters") or []):
        p = res.resolve(p)
        if isinstance(p, dict) and isinstance(p.get("name"), str) and p["name"]:
            params[(p["name"], str(p.get("in", "")))] = p
    props: dict = {}
    required: list[str] = []
    for (name, loc), p in params.items():
        schema = p.get("schema")
        if schema is None:
            schema = _media_schema(p.get("content"))
        key = _free_key(props, name, f"{name}__{loc}")
        props[key] = _with_description(schema, p.get("description"))
        if loc == "path" or p.get("required") is True:
            required.append(key)
    body = res.resolve(op.get("requestBody"))
    if isinstance(body, dict):
        key = _free_key(props, "body", "body__requestBody")
        props[key] = _with_description(_media_schema(body.get("content")),
                                       body.get("description"))
        if body.get("required") is True:
            required.append(key)
    schema: dict = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


def _operation_output(res: _Resolver, op: dict) -> dict | None:
    responses = op.get("responses")
    if not isinstance(responses, dict):
        return None
    for code in sorted(responses, key=str):
        if not str(code).startswith("2"):
            continue
        resp = res.resolve(responses[code])
        schema = _media_schema(resp.get("content")) if isinstance(resp, dict) else None
        if schema is not None:
            return schema if isinstance(schema, dict) and schema.get("type") == "object" \
                else None
    return None


def from_openapi(spec: dict, source_uri: str, version: str, license: str, *,
                 stats: dict | None = None) -> list[ToolRecord]:
    """One record per operation of an OpenAPI 3.x document (module docstring). `stats`, when
    given, receives the counts of `$ref`s cut or left unresolved (`REF_STATS`)."""
    if not str(spec.get("openapi", "")).startswith("3."):
        raise ValueError(f"{source_uri}: not an OpenAPI 3.x document "
                         f"(openapi {spec.get('openapi')!r}, swagger {spec.get('swagger')!r})")
    res = _Resolver(spec, stats)
    paths = spec.get("paths") or {}
    out, used = [], set()
    for path in sorted(paths):
        res.start()
        item = res.resolve(paths[path]) if isinstance(paths[path], dict) and \
            "$ref" in paths[path] else paths[path]
        if not isinstance(item, dict):
            continue
        for method in _METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            op_id = op.get("operationId")
            op_id = op_id if isinstance(op_id, str) and op_id else None
            base = op_id or _NAME_CHARS.sub("_", f"{method}{path}").strip("_")
            name, n = base, 2
            while name in used:
                name, n = f"{base}__{n}", n + 1
            used.add(name)
            res.start()
            summary = op.get("summary") if isinstance(op.get("summary"), str) else None
            desc = op.get("description") if isinstance(op.get("description"), str) else None
            out.append(make_record(
                name=name, title=summary or None, description=desc or summary or "",
                input_schema=_operation_input(res, item, op),
                output_schema=_operation_output(res, op), source_kind="openapi",
                source_uri=source_uri, source_version=version,
                operation={"method": method.upper(), "path": path, "operationId": op_id},
                license=license))
    return out


# -- ToolRet ----------------------------------------------------------------------------------

_TOOLRET_TYPES = {"STRING": "string", "ENUM": "string", "NUMBER": "number",
                  "BOOLEAN": "boolean", "ARRAY": "array", "OBJECT": "object",
                  "BINARY": "string"}


def _toolret_type(t) -> str | None:
    if not isinstance(t, str):
        return None
    word = t.split(" ", 1)[0].upper()  # "DATE (YYYY-MM-DD)" -> "DATE"
    if word in ("DATE", "TIME", "GEOPOINT"):
        return "string"
    return _TOOLRET_TYPES.get(word)


def toolret_uri(repo: str, revision: str, config: str, toolret_id: str) -> str:
    """`toolret:<repo>@<revision>/<config>#<toolret id>`: a ToolRet record's source_uri."""
    return f"toolret:{repo}@{revision}/{config}#{toolret_id}"


def from_toolret(doc: dict, source_uri: str, version: str, license: str) -> ToolRecord:
    """The record of one ToolBench-style documentation dict (module docstring)."""
    props: dict = {}
    for p in list(doc.get("required_parameters") or []) + \
            list(doc.get("optional_parameters") or []):
        name = p.get("name")
        if not isinstance(name, str) or not name or name in props:
            continue
        schema: dict = {}
        jtype = _toolret_type(p.get("type"))
        if jtype is not None:
            schema["type"] = jtype
        if isinstance(p.get("description"), str) and p["description"]:
            schema["description"] = p["description"]
        if p.get("default") not in ("", None):
            schema["default"] = p["default"]
        props[name] = schema
    required: list[str] = []
    for p in doc.get("required_parameters") or []:
        name = p.get("name")
        if name in props and name not in required:
            required.append(name)
    input_schema: dict = {"type": "object", "properties": props}
    if required:
        input_schema["required"] = required
    return make_record(
        name=str(doc.get("name", "")), title=None, description=str(doc.get("description", "")),
        input_schema=input_schema, output_schema=None, source_kind="toolret",
        source_uri=source_uri, source_version=version,
        operation={"category": doc.get("category_name"), "api_name": doc.get("name"),
                   "method": doc.get("method")},
        license=license)
