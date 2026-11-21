"""SKILL.md and Mermaid renderings of a procedure IR, and parsers of exactly the subset they
emit, for the round-trip check of criterion U3 (Phase 4 spec §9.2, §17; P39; preflight note
N19). Pure functions of the IR: byte-stable, no clock, no model, no Node (the Mermaid
reference parser is not run, §4.7).

**Mermaid** (`render_mermaid`). `flowchart TD`, then one node line per step in step order,
then one edge line per `next` edge in step and edge order, each indented four spaces. Node ids
are `s1`…`sN` by step position (the IR's own ids may differ); a condition step is a rhombus
`sN{"label"}`, every other step a box `sN["label"]`. A label is the step's text (the step type
when the text is empty) with whitespace runs as single spaces, `"` written `#quot;` and `#`
and control characters `#<code>;`, then cut so that it is at most `LABEL_MAX` characters, the
cut marked by "…" and never inside an entity. An edge is `sA --> sB`, or `sA -->|guard| sB`
when it has a guard. Guards are written losslessly, since they belong to the graph: `#` as
`#35;`, `"` as `#quot;`, `|` as `#124;`, control and line-break characters as `#<code>;`, and
a space at either end as `#32;`; an empty guard cannot be written and is refused. A subprocedure's
`subprocedure_ref` is no edge (P39), so neither rendering draws one.

**The graph** (`ir_graph`, `parse_mermaid`): (nodes, edges) with nodes `s1`…`sN` and edges
(from, to, guard). `parse_mermaid` accepts exactly the emitted subset (the header, node lines,
then edge lines, every edge between declared nodes, labels within `LABEL_MAX`, only the
emitted entities, no blank line) and raises ValueError on anything else, so the round trip
`parse_mermaid(render_mermaid(b)) == ir_graph(b)` checks nodes, edges and guards.

**SKILL.md** (`render_skill`, Agent Skills layout). YAML front matter with `name` (the
`canonical_ref` lower-cased, every character other than `a-z` and `0-9` written `-`) and
`description` (the `when_to_use` value, or the unit's title while it is null; cut to
`WHEN_TO_USE_MAX` characters with "…"), written as a double-quoted scalar (JSON string escapes,
which YAML reads, with C1 controls and U+2028/U+2029 escaped too). Then a `# <title>` heading
and one numbered line per step (its text on one line; the end step's "End."). Under a step,
indented three spaces: `Tool: <tool>` (a tool call), `Subprocedure: <ref>`, `Handoff` or `Wait`,
then its routing: `If <guard> then step N` per guarded edge (a leading "If" and trailing ".:;,"
of the guard dropped), `Otherwise step N` for an "otherwise" edge and `Go to step N` for an
unguarded edge, except a step's only edge when it leads to the next step. Then a `Source:
<canonical_ref>` line. With more than `REFERENCES_FROM` condition steps the routing lines move
under a `## references/` heading after the body, each step's under a `Step N:` line, and the
body says so, so a long If/Then table keeps the body compact (§9.2; it stays under
`SKILL_BODY_MAX_LINES` lines for every real procedure). `parse_skill` reads the front matter
back and counts the numbered step lines of the body, which must run 1…N.
"""

from __future__ import annotations

import json
import re

from adr_store.units.envelope import Unit
from adr_store.units.procedures import WHEN_TO_USE_MAX, ProcedureBody, Step

__all__ = ["LABEL_MAX", "REFERENCES_FROM", "SKILL_BODY_MAX_LINES", "Graph", "ir_graph",
           "parse_mermaid", "parse_skill", "render_mermaid", "render_skill"]

SKILL_BODY_MAX_LINES = 500
LABEL_MAX = 80
REFERENCES_FROM = 8   # condition steps beyond which the routing lines go to references/
Graph = tuple[frozenset[str], frozenset[tuple[str, str, str | None]]]  # (nodes, (from, to, guard))

_HEADER = "flowchart TD"
_INDENT = "    "
_ELLIPSIS = "…"
_REFERENCES = "## references/"


# -- the graph -------------------------------------------------------------------------------

def _positions(body: ProcedureBody) -> dict[str, str]:
    """IR step id -> `sK` by step position; ValueError on a duplicate id."""
    pos: dict[str, str] = {}
    for i, s in enumerate(body.steps, 1):
        if s.id in pos:
            raise ValueError(f"{s.id}: duplicate step id")
        pos[s.id] = f"s{i}"
    return pos


def _edges(body: ProcedureBody, pos: dict[str, str]) -> list[tuple[str, str, str | None]]:
    out = []
    for s in body.steps:
        for e in s.next:
            if e.to not in pos:
                raise ValueError(f"{s.id}: next {e.to} does not exist")
            out.append((pos[s.id], pos[e.to], e.guard))
    return out


def ir_graph(body: ProcedureBody) -> Graph:
    """The IR's step graph with ids renumbered `s1`…`sN` in step order."""
    pos = _positions(body)
    return frozenset(pos.values()), frozenset(_edges(body, pos))


# -- Mermaid ---------------------------------------------------------------------------------

_ENTITY = re.compile(r"#quot;|#\d+;")


def _special(ch: str) -> bool:
    """A character written as an entity in a guard besides `#`, `"` and `|`: controls and
    line breaks."""
    o = ord(ch)
    return o < 0x20 or 0x7F <= o <= 0x9F or ch in "\u2028\u2029"


def _escape_guard(guard: str) -> str:
    if not guard:
        raise ValueError("an empty guard cannot be written as a Mermaid edge label")
    out = []
    for i, ch in enumerate(guard):
        if ch == '"':
            out.append("#quot;")
        elif ch in "#|" or _special(ch) or (ch == " " and i in (0, len(guard) - 1)):
            out.append(f"#{ord(ch)};")
        else:
            out.append(ch)
    return "".join(out)


def _label(s: Step) -> str:
    """The node label: the text on one line, escaped, cut at `LABEL_MAX` whole tokens."""
    tokens = ["#quot;" if ch == '"' else f"#{ord(ch)};" if ch == "#" or _special(ch) else ch
              for ch in " ".join(s.text.split()) or s.type]
    if sum(map(len, tokens)) <= LABEL_MAX:
        return "".join(tokens)
    kept, size = [], 0
    for t in tokens:
        if size + len(t) > LABEL_MAX - len(_ELLIPSIS):
            break
        kept.append(t)
        size += len(t)
    return "".join(kept) + _ELLIPSIS


def render_mermaid(body: ProcedureBody) -> str:
    """`body` as a Mermaid `flowchart TD` (module docstring)."""
    pos = _positions(body)
    lines = [_HEADER]
    for s in body.steps:
        label = _label(s)
        lines.append(f'{_INDENT}{pos[s.id]}{{"{label}"}}' if s.type == "condition"
                     else f'{_INDENT}{pos[s.id]}["{label}"]')
    for a, b, guard in _edges(body, pos):
        arrow = "-->" if guard is None else f"-->|{_escape_guard(guard)}|"
        lines.append(f"{_INDENT}{a} {arrow} {b}")
    return "\n".join(lines) + "\n"


_NODE_ID = r"s[1-9]\d*"
_NODE = re.compile(rf'{_INDENT}({_NODE_ID})(?:\["([^"]*)"\]|\{{"([^"]*)"\}})')
_EDGE = re.compile(rf"{_INDENT}({_NODE_ID}) -->(?:\|([^|]*)\|)? ({_NODE_ID})")


def _unescape(text: str, what: str) -> str:
    """`text` with the emitted entities decoded; ValueError on a character the renderer
    never leaves bare."""
    bare = _ENTITY.sub("", text)
    if any(ch in '"#|' or _special(ch) for ch in bare):
        raise ValueError(f"{what}: a character outside the emitted subset in {text!r}")
    return _ENTITY.sub(lambda m: '"' if m.group() == "#quot;" else chr(int(m.group()[1:-1])),
                       text)


def parse_mermaid(text: str) -> Graph:
    """The graph of a Mermaid text in exactly the subset `render_mermaid` emits; ValueError
    otherwise."""
    if not text.endswith("\n"):
        raise ValueError("not newline-terminated")
    lines = text[:-1].split("\n")
    if lines[0] != _HEADER:
        raise ValueError(f"the first line is not {_HEADER!r}: {lines[0]!r}")
    nodes: list[str] = []
    edges: list[tuple[str, str, str | None]] = []
    for line in lines[1:]:
        if m := _NODE.fullmatch(line):
            if edges:
                raise ValueError(f"a node after the edges: {line!r}")
            if m.group(1) in nodes:
                raise ValueError(f"{m.group(1)} declared twice")
            label = m.group(2) if m.group(2) is not None else m.group(3)
            if not label or len(label) > LABEL_MAX:
                raise ValueError(f"{m.group(1)}: label empty or over {LABEL_MAX} characters")
            _unescape(label.replace("|", ""), m.group(1))  # a bare `|` is allowed in a label
            nodes.append(m.group(1))
        elif m := _EDGE.fullmatch(line):
            a, raw, b = m.groups()
            if a not in nodes or b not in nodes:
                raise ValueError(f"an edge to an undeclared node: {line!r}")
            if raw == "":
                raise ValueError(f"an empty edge label: {line!r}")
            edges.append((a, b, None if raw is None else _unescape(raw, f"{a} -> {b}")))
        else:
            raise ValueError(f"outside the emitted subset: {line!r}")
    return frozenset(nodes), frozenset(edges)


# -- SKILL.md --------------------------------------------------------------------------------

_YAML_EXTRA = re.compile("[\x7f-\x9f\u2028\u2029]")
_PLAIN = re.compile(r"[a-z0-9][a-z0-9-]*")
_META_LINE = re.compile(r"([a-z_]+): (.*)")
_STEP_LINE = re.compile(r"(\d+)\. ")
_LEADING_IF = re.compile(r"if\s+", re.IGNORECASE)


def _yaml_string(value: str) -> str:
    """A YAML double-quoted scalar: a JSON string, with the characters YAML will not take
    bare (C1 controls, its extra line breaks) escaped as well."""
    return _YAML_EXTRA.sub(lambda m: f"\\u{ord(m.group()):04x}",
                           json.dumps(value, ensure_ascii=False))


def _description(unit: Unit, body: ProcedureBody) -> str:
    value = body.when_to_use.get("value")
    text = value if isinstance(value, str) else unit.title
    if len(text) > WHEN_TO_USE_MAX:
        text = text[:WHEN_TO_USE_MAX - len(_ELLIPSIS)] + _ELLIPSIS
    return text


def _routing(s: Step, i: int, number: dict[str, int]) -> list[str]:
    """The routing lines of step number `i` (module docstring)."""
    if len(s.next) == 1 and s.next[0].guard is None and number[s.next[0].to] == i + 1:
        return []
    lines = []
    for e in s.next:
        n = number[e.to]
        if e.guard is None:
            lines.append(f"Go to step {n}")
        elif e.guard == "otherwise":
            lines.append(f"Otherwise step {n}")
        else:
            guard = _LEADING_IF.sub("", " ".join(e.guard.split()), count=1).rstrip(".:;, ")
            lines.append(f"If {guard} then step {n}")
    return lines


def _annotation(s: Step) -> list[str]:
    if s.type == "tool_call" and s.tool:
        return [f"Tool: {s.tool}"]
    if s.type == "subprocedure" and s.subprocedure_ref:
        return [f"Subprocedure: {s.subprocedure_ref}"]
    return {"handoff": ["Handoff"], "wait": ["Wait"]}.get(s.type, [])


def render_skill(unit: Unit) -> str:
    """The procedure `unit` as a SKILL.md (module docstring)."""
    body = ProcedureBody.model_validate(unit.body)
    _edges(body, _positions(body))  # refuses a duplicate id or a dangling edge
    number = {s.id: i for i, s in enumerate(body.steps, 1)}
    referenced = sum(s.type == "condition" for s in body.steps) > REFERENCES_FROM
    name = re.sub(r"[^a-z0-9]", "-", unit.canonical_ref.lower())
    lines = ["---", f"name: {name}", f"description: {_yaml_string(_description(unit, body))}",
             "---", "", f"# {unit.title}", ""]
    if referenced:
        lines += ["The branches of each step are listed under references/ below.", ""]
    refs: list[str] = []
    for i, s in enumerate(body.steps, 1):
        text = " ".join(s.text.split()) or ("End." if s.type == "end" else f"({s.type})")
        lines.append(f"{i}. {text}")
        lines += [f"   {a}" for a in _annotation(s)]
        routing = [f"   {r}" for r in _routing(s, i, number)]
        if referenced and routing:
            refs += [f"Step {i}:", *routing]
        else:
            lines += routing
    lines += ["", f"Source: {unit.canonical_ref}"]
    if refs:
        lines += ["", _REFERENCES, "", *refs]
    return "\n".join(lines) + "\n"


def parse_skill(text: str) -> tuple[dict, int]:
    """(the front matter, the number of numbered step lines in the body) of a SKILL.md in the
    form `render_skill` emits; ValueError when the front matter does not parse or the steps
    are not numbered 1…N."""
    lines = text.split("\n")
    if lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError("no front matter")
    end = lines.index("---", 1)
    meta: dict = {}
    for line in lines[1:end]:
        m = _META_LINE.fullmatch(line)
        if not m:
            raise ValueError(f"front matter line does not parse: {line!r}")
        key, raw = m.groups()
        if key in meta:
            raise ValueError(f"{key} given twice")
        if raw.startswith('"'):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{key}: not a double-quoted string: {raw!r}") from exc
            if not isinstance(value, str):
                raise ValueError(f"{key}: not a string")
        elif _PLAIN.fullmatch(raw):
            value = raw
        else:
            raise ValueError(f"{key}: not a plain or double-quoted scalar: {raw!r}")
        meta[key] = value
    rest = lines[end + 1:]
    if _REFERENCES in rest:
        rest = rest[:rest.index(_REFERENCES)]
    numbers = [int(m.group(1)) for line in rest if (m := _STEP_LINE.match(line))]
    if numbers != list(range(1, len(numbers) + 1)):
        raise ValueError(f"steps are not numbered 1…N: {numbers[:10]}")
    return meta, len(numbers)
