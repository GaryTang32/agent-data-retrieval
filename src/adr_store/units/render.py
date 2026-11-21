"""SKILL.md and Mermaid renderings of a procedure IR, and parsers of exactly the subset they
emit, for the round-trip check of criterion U3 (Phase 4 spec §9.2, §17; P39; preflight note
N19). Pure functions of the IR: byte-stable, no clock, no model, no Node (the Mermaid
reference parser is not run, §4.7).

**Mermaid** (`render_mermaid`). `flowchart TD`, then one node line per step in step order,
then one edge line per `next` edge in step and edge order, each indented four spaces. Node ids
are `s1`…`sN` by step position (the IR's own ids may differ); a condition step is a rhombus
`sN{"label"}`, every other step a box `sN["label"]`. A label is the step's text (the step type
when the text is empty) with whitespace runs as single spaces, `"` written `#quot;` and `#`,
a backtick and control characters `#<code>;`, then cut so that it is at most `LABEL_MAX`
characters, the cut marked by "…" and never inside an entity. An edge is `sA --> sB`, or
`sA -->|"guard"| sB` when it has a guard: always quoted (P40), so brackets, braces and
parentheses, which Mermaid reads as delimiters in an unquoted label, stay text. Guards are
written losslessly, since they belong to the graph: `"` as `#quot;`, `#`, `|`, a backtick
(which would open a Mermaid markdown string) and control and line-break characters as
`#<code>;`, and a space at either end as `#32;`. An empty or blank guard cannot be written and
is refused (`validate_ir` refuses it too). A subprocedure's `subprocedure_ref` is no edge (P39),
so neither rendering draws one. Display limits, the graph unaffected: Mermaid shows `#0;` and
the C1 codes `#128;`–`#159;` as other characters, and its `style…:…#…;` pre-pass could eat a
`;` after "style:" (no real step has either).

**The graph** (`ir_graph`, `parse_mermaid`): (nodes, edges), nodes the `(sK, shape)` pairs in
step order (shape "rhombus" for a condition, else "box") and edges the `(from, to, guard)`
triples in step and edge order, so the round trip compares node shapes and edge multiplicity
as well. `parse_mermaid` accepts exactly the emitted subset (the header, node lines, then edge
lines, every edge between declared nodes, quoted edge labels, labels within `LABEL_MAX`, and
every label and guard exactly as the renderer writes its decoded text: only the entities it
emits, ASCII digits without leading zeros, no bare `"`, `#` or backtick, no blank line) and
raises ValueError on anything else, so `parse_mermaid(render_mermaid(b)) == ir_graph(b)` checks
nodes, shapes, edges and guards.

**SKILL.md** (`render_skill`, Agent Skills layout). YAML front matter with `name` and
`description`. The `name` (P40) is the title folded to ASCII (NFKD, other characters dropped),
lowercased, runs of characters other than `a-z0-9` written as one `-`, leading and trailing
hyphens off, cut to `NAME_SLUG_MAX` characters with no trailing hyphen (the unit type when
nothing is left), then `-` and the first 12 hex characters of SHA-256 of the unit id: at most
64 characters, the Agent Skills limit, and distinct for two units with one title. The
`description` is the `when_to_use` value, or the unit's title while it is null, cut to
`WHEN_TO_USE_MAX` characters with "…", written as a double-quoted scalar (JSON string escapes,
which YAML reads, with C1 controls and U+2028/U+2029 escaped too). Then a `# <title>` heading
and one numbered line per step (its text on one line; the end step's "End."). A condition
step's line starts "If " (added when its text does not start with "If"). Under a step,
indented three spaces: `Tool: <tool>` (a tool call), `Subprocedure: <ref>`, `Handoff` or
`Wait`, then its routing: `If <guard> then step N` per guarded edge (a leading "If" and
trailing ".:;," of the guard dropped), `Otherwise step N` for an "otherwise" edge and `Go to
step N` for an unguarded edge, except a step's only edge when it leads to the next step. Then
a `Source: <canonical_ref>` line. With more than `REFERENCES_FROM` condition steps the routing
lines move under a `## references/` heading after the body, each step's under a `Step N:`
line; the body says so once, and each condition line ends "(branches: see references, step
N)", so the body still shows where it branches without a line more (§9.2; it stays under
`SKILL_BODY_MAX_LINES` lines for every real procedure). Step lines are not wrapped, however
long, since the count is one line per step. `parse_skill` reads the front matter back (exactly
`name`, of the form above, and `description`, at most `WHEN_TO_USE_MAX` characters) and counts
the numbered step lines of the body, which must run 1…N.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable

from adr_store.units.envelope import Unit
from adr_store.units.procedures import WHEN_TO_USE_MAX, ProcedureBody, Step

__all__ = ["LABEL_MAX", "NAME_MAX", "NAME_SLUG_MAX", "REFERENCES_FROM", "SKILL_BODY_MAX_LINES",
           "Graph", "ir_graph",
           "parse_mermaid", "parse_skill", "render_mermaid", "render_skill"]

SKILL_BODY_MAX_LINES = 500
LABEL_MAX = 80
REFERENCES_FROM = 8   # condition steps beyond which the routing lines go to references/
NAME_MAX = 64        # the Agent Skills limit on `name`
NAME_SLUG_MAX = NAME_MAX - 13   # room for "-" and 12 hex characters (P40)
# ((sK, shape) per step, (from, to, guard) per edge), both in step order (fix round 1, M3)
Graph = tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str, str | None], ...]]

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


def _shape(s: Step) -> str:
    return "rhombus" if s.type == "condition" else "box"


def ir_graph(body: ProcedureBody) -> Graph:
    """The IR's step graph with ids renumbered `s1`…`sN` in step order: node shapes and edges
    in step and edge order."""
    pos = _positions(body)
    return tuple((pos[s.id], _shape(s)) for s in body.steps), tuple(_edges(body, pos))


# -- Mermaid ---------------------------------------------------------------------------------

_ENTITY = re.compile(r"#quot;|#(\d{1,7});", re.ASCII)


def _special(ch: str) -> bool:
    """A character written as an entity besides `#`, `"`, `|` and a backtick: controls and
    line breaks."""
    o = ord(ch)
    return o < 0x20 or 0x7F <= o <= 0x9F or ch in "\u2028\u2029"


def _check_guard(guard: str) -> None:
    if not guard.strip():
        raise ValueError(f"an empty guard cannot be rendered: {guard!r}")


def _escape_guard(guard: str) -> str:
    _check_guard(guard)
    out = []
    for i, ch in enumerate(guard):
        if ch == '"':
            out.append("#quot;")
        elif ch in "#|`" or _special(ch) or (ch == " " and i in (0, len(guard) - 1)):
            out.append(f"#{ord(ch)};")
        else:
            out.append(ch)
    return "".join(out)


def _label_tokens(text: str) -> list[str]:
    return ["#quot;" if ch == '"' else f"#{ord(ch)};" if ch in "#`" or _special(ch) else ch
            for ch in text]


def _label(s: Step) -> str:
    """The node label: the text on one line, escaped, cut at `LABEL_MAX` whole tokens."""
    tokens = _label_tokens(" ".join(s.text.split()) or s.type)
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
        arrow = "-->" if guard is None else f'-->|"{_escape_guard(guard)}"|'
        lines.append(f"{_INDENT}{a} {arrow} {b}")
    return "\n".join(lines) + "\n"


_NODE_ID = r"s[1-9]\d*"
_NODE = re.compile(rf'{_INDENT}({_NODE_ID})(?:\["([^"]*)"\]|\{{"([^"]*)"\}})')
_EDGE = re.compile(rf'{_INDENT}({_NODE_ID}) -->(?:\|"([^"]*)"\|)? ({_NODE_ID})')


def _decode(text: str, encode: Callable[[str], str], what: str) -> str:
    """`text` with its entities decoded, provided `encode` writes the decoded text back as
    exactly `text` (so only the entities and bare characters the renderer emits pass);
    ValueError otherwise."""
    try:
        decoded = _ENTITY.sub(lambda m: '"' if m.group() == "#quot;" else chr(int(m.group(1))),
                              text)
    except ValueError as exc:
        raise ValueError(f"{what}: an entity out of range in {text!r}") from exc
    if encode(decoded) != text:
        raise ValueError(f"{what}: outside the emitted subset: {text!r}")
    return decoded


def _encode_label(decoded: str) -> str:
    """A decoded label written back; a label is one line with single spaces."""
    if decoded != " ".join(decoded.split()):
        return ""
    return "".join(_label_tokens(decoded))


def parse_mermaid(text: str) -> Graph:
    """The graph of a Mermaid text in exactly the subset `render_mermaid` emits; ValueError
    otherwise."""
    if not text.endswith("\n"):
        raise ValueError("not newline-terminated")
    lines = text[:-1].split("\n")
    if lines[0] != _HEADER:
        raise ValueError(f"the first line is not {_HEADER!r}: {lines[0]!r}")
    nodes: list[tuple[str, str]] = []
    edges: list[tuple[str, str, str | None]] = []
    for line in lines[1:]:
        if m := _NODE.fullmatch(line):
            if edges:
                raise ValueError(f"a node after the edges: {line!r}")
            if m.group(1) in dict(nodes):
                raise ValueError(f"{m.group(1)} declared twice")
            label = m.group(2) if m.group(2) is not None else m.group(3)
            if not label or len(label) > LABEL_MAX:
                raise ValueError(f"{m.group(1)}: label empty or over {LABEL_MAX} characters")
            _decode(label, _encode_label, m.group(1))
            nodes.append((m.group(1), "box" if m.group(2) is not None else "rhombus"))
        elif m := _EDGE.fullmatch(line):
            a, raw, b = m.groups()
            if a not in dict(nodes) or b not in dict(nodes):
                raise ValueError(f"an edge to an undeclared node: {line!r}")
            edges.append((a, b, None if raw is None else _decode(raw, _escape_guard,
                                                                    f"{a} -> {b}")))
        else:
            raise ValueError(f"outside the emitted subset: {line!r}")
    return tuple(nodes), tuple(edges)


# -- SKILL.md --------------------------------------------------------------------------------

_YAML_EXTRA = re.compile("[\x7f-\x9f\u2028\u2029]")
_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{12}")
_META_LINE = re.compile(r"([a-z_]+): (.*)")
_STEP_LINE = re.compile(r"(\d+)\. ")
_LEADING_IF = re.compile(r"if\s+", re.IGNORECASE)
_STARTS_IF = re.compile(r"if\b", re.IGNORECASE)


def _yaml_string(value: str) -> str:
    """A YAML double-quoted scalar: a JSON string, with the characters YAML will not take
    bare (C1 controls, its extra line breaks) escaped as well."""
    return _YAML_EXTRA.sub(lambda m: f"\\u{ord(m.group()):04x}",
                           json.dumps(value, ensure_ascii=False))


def _name(unit: Unit) -> str:
    """The SKILL.md `name` (P40; module docstring)."""
    folded = unicodedata.normalize("NFKD", unit.title).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")[:NAME_SLUG_MAX].rstrip("-")
    return f"{slug or unit.type}-{hashlib.sha256(unit.unit_id.encode()).hexdigest()[:12]}"


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
            _check_guard(e.guard)
            whole = " ".join(e.guard.split())
            guard = _LEADING_IF.sub("", whole, count=1).rstrip(".:;, ") or whole
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
    lines = ["---", f"name: {_name(unit)}",
             f"description: {_yaml_string(_description(unit, body))}",
             "---", "", f"# {unit.title}", ""]
    if referenced:
        lines += ["The branches of each step are listed under references/ below.", ""]
    refs: list[str] = []
    for i, s in enumerate(body.steps, 1):
        text = " ".join(s.text.split()) or ("End." if s.type == "end" else f"({s.type})")
        routing = [f"   {r}" for r in _routing(s, i, number)]
        if s.type == "condition":
            text = text if _STARTS_IF.match(text) else f"If {text}"
            if referenced and routing:
                text += f" (branches: see references, step {i})"
        lines.append(f"{i}. {text}")
        lines += [f"   {a}" for a in _annotation(s)]
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
    pairs = [_META_LINE.fullmatch(line) for line in lines[1:end]]
    if not all(pairs) or [m.group(1) for m in pairs] != ["name", "description"]:
        raise ValueError(f"the front matter is not name then description: {lines[1:end]!r}")
    name, raw = pairs[0].group(2), pairs[1].group(2)
    if not _NAME.fullmatch(name) or len(name) > NAME_MAX:
        raise ValueError(f"name: not a title slug and unit hash of at most {NAME_MAX}: {name!r}")
    try:
        description = json.loads(raw) if raw.startswith('"') else None
    except json.JSONDecodeError as exc:
        raise ValueError(f"description: not a double-quoted string: {raw!r}") from exc
    if not isinstance(description, str) or len(description) > WHEN_TO_USE_MAX:
        raise ValueError(f"description: not a string of at most {WHEN_TO_USE_MAX}: {raw[:80]!r}")
    meta = {"name": name, "description": description}
    rest = lines[end + 1:]
    if _REFERENCES in rest:
        rest = rest[:rest.index(_REFERENCES)]
    numbers = [int(m.group(1)) for line in rest if (m := _STEP_LINE.match(line))]
    if numbers != list(range(1, len(numbers) + 1)):
        raise ValueError(f"steps are not numbered 1…N: {numbers[:10]}")
    return meta, len(numbers)
