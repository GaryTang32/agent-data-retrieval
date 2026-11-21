"""The procedure IR, IRM segmentation, and IRM and bench procedure skeletons (Phase 4 spec §4.2,
§5.3, §6.1, §9.1, P10, P31). Code only, no model: steps, guards and edges come from the
sources' explicit structure; `when_to_use`, `not_for`, `trigger_examples` and
`problem_abstractions` are left in the not-extracted form for the procedure pass (Task 10).

**The IR.** A `ProcedureBody` holds `Step`s whose `next` edges name successor steps; the first
step is the start. Step types: `instruction`, `condition`, `tool_call`, `subprocedure`,
`handoff`, `wait`, `end`. A condition step's edges carry guards (the last one "otherwise"); no
other step's do. `validate_ir` checks one start, reachability, a successor for every non-`end`
step, no dangling `next` and guards on condition steps only; `branch_paths` gives one path per
condition outcome (a body without conditions: its one path start to end). Every `risk` is
`unknown`: neither source marks it (P22).

**IRM sections** (`irm_sections`). The canonical text keeps no body headings, so section
boundaries come from the raw HTML (`blobs/`): every `div.section` whose `sectioninfo` holds a
section or exhibit number ("21.4.1.3 (10-01-2026)", "Exhibit 21.4.1-1"; the chapter's own
`div.section` has none). A section's own text is its content without its nested sections, its
`sectioninfo`, its `titlepage` and the labels of its notes ("Note:", "Reminder:"), which the
extractor drops. Its first own line is searched in the canonical text in document order, from
the end of the previous located section's first line, ignoring whitespace (the extractor spaces
inline markup differently); a match that starts or ends with a letter has no letter beside it
there, one that starts or ends with a digit no digit (the extractor glues some table cells,
"1424Fees"). A section runs from that line to the next located section (the last to the end of
the text), trailing whitespace off. A section whose line is not found is unlocated: it is
merged into the preceding located section (named in its `merged`, its HTML appended to that
section's) and reported (P10).

**IRM skeletons** (`irm_skeleton`, for the procedure-like sections: at least one If/Then table,
a table whose header row has a cell starting "If" and one starting "Then"). The numbered
paragraphs (the items of the section's top-level ordered lists) become steps in order, their
lettered items folded into their text. Each row of an If/Then table in a paragraph becomes a
`condition` step (the If-side cells, "Row" columns aside: its text is their slice of the
canonical text and its guard their HTML lines, a cell's lines joined by spaces and the cells by
"; "), whose first edge leads, under that guard, to the row's action step (the Then cell) and
whose "otherwise" edge leads to the next row's condition step; the last row's "otherwise", like
every action step, leads to what follows the table. The paragraph's own text after a table (a
note, a reminder, further lettered items, up to its next If/Then table) is an unconditional
step of its own, entered from every exit of the table; the paragraph's next table or the next
paragraph follows. Chaining the rows by "otherwise" reads the table as a decision table (a
ruling of the Task 4 review, M2). A paragraph, text after a table or action naming a command
code ("Command Code REQ77", "Command Code (CC) ERINV", or, by the ruling on review I4, "CC
ENMOD": four or more capitals and digits) or a transaction code ("TC 971") is a `tool_call`
whose `tool` is the first code ("REQ77", "TC 971"); else "refer to IRM <n>" makes a
`subprocedure` whose `subprocedure_ref` is "IRM <n>" (ruling M1: no edge leads to it, and
`tool` names systems and codes only); else "refer the case to" or "escalate" makes a `handoff`;
else an `instruction`. A final `end` step is appended.

Each step is located by its first line inside its section's span, the anchors placed as
sections are found (whitespace ignored, letter and digit bounds) but jointly: of all the ways
to give the anchors matches that follow one another in order, the one that places the most,
each at its earliest match that still allows that many (a row's condition is matched with the
row's "Row" cells before it). So a Then cell the extractor dropped, whose first line also opens
a later cell, does not take that cell's place and push out the anchors between them. A step's
span runs to the next placed anchor (the next paragraph, text after a table, table header, row
cell or the section's end), trailing whitespace, bullet remnants and, at a table cell, pipes
off. A step's text is that slice of the canonical text, so it always re-slices. A paragraph,
text after a table or row whose anchor is not placed is dropped and reported with the reason:
`not_in_text` (nowhere in the section), `out_of_order` (only where it would displace other
anchors) or `empty_cell`.

**Bench skeletons** (`bench_skeleton`). Headings starting "Step <n>" or "<n>." are the steps
when there are at least `MIN_STEPS` of them, each running to the next heading of the same or an
outer level; else the top-level numbered list items, each with its sub-items: the list items
that follow it, more indented, or bullets at its own indent right under it (no blank line
between). A list item starting with "If" becomes a `condition` whose guard is its If clause,
which ends at the first colon or comma followed by a space or the line's end, else at the end
of the first line; the rest of the item (its sub-items when the line ends there, a leading
bullet skipped) is the action. An "If" item with nothing after its clause stays an
`instruction` (counted as `no_action`). Every other step is an `instruction`. A bench candidate
(`bench_candidates`) is a markdown document whose title (its first line) holds a word of
`BENCH_KINDS` and that has at least `MIN_STEPS` steps; at most `BENCH_CAP` are drawn, the
smallest SHA-256 of "<seed>:<doc id>".

A skeleton with fewer than `MIN_STEPS` steps besides the end is flagged `coarse` and kept.
`procedure_units` builds one `procedure` unit per procedure-like IRM section (`canonical_ref`
"IRM <number>") or drawn bench document ("bench:<doc id>").
"""

from __future__ import annotations

import copy
import hashlib
import re
from bisect import bisect_left
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from lxml import etree
from lxml import html as lxml_html
from pydantic import BaseModel, ConfigDict, Field

from adr_store import applicability as ap
from adr_store.applicability import Applicability
from adr_store.store import Store
from adr_store.structure import markdown as md
from adr_store.units.envelope import Unit, link_versions, make_unit

__all__ = ["BENCH_CAP", "BENCH_KINDS", "MIN_STEPS", "SEED4", "STEP_TYPES", "WHEN_TO_USE_MAX",
           "Edge", "IrmSection", "ProcedureBody", "Step", "bench_candidates", "bench_skeleton",
           "branch_paths", "irm_sections", "irm_skeleton", "is_procedure_like",
           "not_extracted", "procedure_units", "validate_ir"]

STEP_TYPES = ("instruction", "condition", "tool_call", "subprocedure", "handoff", "wait", "end")
BENCH_KINDS = ("runbook", "playbook", "sop", "procedure", "process", "guide", "checklist")
BENCH_CAP = 110
MIN_STEPS = 3
WHEN_TO_USE_MAX = 1024
SEED4 = 20261121
SPEC_ID = "procedure.steps@1"
StepType = Literal["instruction", "condition", "tool_call", "subprocedure", "handoff", "wait",
                   "end"]


# -- the IR ----------------------------------------------------------------------------------

def not_extracted() -> dict:
    """The model-written field before its pass: `{value: null, quotes: [], status: null,
    null_reason: "not_extracted"}` (§5.3, §6.4)."""
    return {"value": None, "quotes": [], "status": None, "null_reason": "not_extracted"}


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    to: str
    guard: str | None = None


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    type: StepType
    text: str
    span: tuple[int, int] | None  # document offsets of `text`
    tool: str | None = None              # the system or command code a step uses
    subprocedure_ref: str | None = None  # the procedure a subprocedure step calls (no edge)
    args_schema: dict | None = None
    condition: str | None = None
    next: list[Edge] = []
    risk: Literal["unknown", "low", "irreversible"] = "unknown"
    requires_approval: bool = False
    preconditions: list[dict] = []  # binding-language expressions (Task 21)


class ProcedureBody(BaseModel):
    """A procedure unit's body (§5.3). The four model fields are `{value, quotes, status,
    null_reason}` objects, the not-extracted form until the procedure pass (Task 10)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    when_to_use: dict = Field(default_factory=not_extracted)
    not_for: dict = Field(default_factory=not_extracted)
    trigger_examples: dict = Field(default_factory=not_extracted)
    problem_abstractions: dict = Field(default_factory=not_extracted)
    inputs: list[str] = []
    preconditions: list[str] = []
    steps: list[Step]
    escalation: str | None = None
    success_criteria: str | None = None
    tests: list[list[str]] = []
    ambiguity_flags: list[str] = []
    source_kind: Literal["irm", "bench", "authored"]


def validate_ir(body: ProcedureBody) -> list[str]:
    """The problems of `body`'s step graph (§9.1), empty when it is valid: one start (the
    first step; any other step without a predecessor is a second start), every step
    reachable from it, a successor for every non-`end` step and none for an `end` step, no
    `next` naming a missing step, guards only on condition steps, unique step ids, and a
    `when_to_use` value of at most `WHEN_TO_USE_MAX` characters."""
    problems = []
    value = body.when_to_use.get("value")
    if isinstance(value, str) and len(value) > WHEN_TO_USE_MAX:
        problems.append(f"when_to_use is longer than {WHEN_TO_USE_MAX} characters")
    steps = body.steps
    if not steps:
        return [*problems, "no steps"]
    ids = [s.id for s in steps]
    problems += [f"{i}: duplicate step id" for i, n in Counter(ids).items() if n > 1]
    known = set(ids)
    incoming = {e.to for s in steps for e in s.next}
    if any(s.id not in incoming for s in steps[1:]):
        problems.append("more than one start step")
    for s in steps:
        for e in s.next:
            if e.to not in known:
                problems.append(f"{s.id}: next {e.to} does not exist")
            if e.guard is not None and s.type != "condition":
                problems.append(f"{s.id}: guard on a non-condition step")
        if s.type == "end" and s.next:
            problems.append(f"{s.id}: end step has a successor")
        if s.type != "end" and not s.next:
            problems.append(f"{s.id}: no successor")
    by = {s.id: s for s in steps}
    seen, todo = {ids[0]}, [ids[0]]
    while todo:
        for e in by[todo.pop()].next:
            if e.to in known and e.to not in seen:
                seen.add(e.to)
                todo.append(e.to)
    problems += [f"{s.id}: unreachable" for s in steps if s.id not in seen]
    return list(dict.fromkeys(problems))


def _shortest(by: dict[str, Step], src: str, goal: Callable[[str], bool],
              banned: set[tuple[str, str]]) -> list[str] | None:
    """The shortest path from `src` to a step satisfying `goal` (edges tried in order),
    avoiding the `banned` edges, or None."""
    prev: dict[str, str | None] = {src: None}
    queue = deque([src])
    while queue:
        node = queue.popleft()
        if goal(node):
            path = [node]
            while (p := prev[path[-1]]) is not None:
                path.append(p)
            return path[::-1]
        for e in by[node].next:
            if e.to in by and (node, e.to) not in banned and e.to not in prev:
                prev[e.to] = node
                queue.append(e.to)
    return None


def _edges(path: list[str]) -> set[tuple[str, str]]:
    return set(zip(path, path[1:], strict=False))


def branch_paths(body: ProcedureBody) -> list[list[str]]:
    """One path of step ids per condition outcome, in step and edge order: the shortest path
    from the start to the condition step, its edge, then the shortest way on to an `end`
    step that uses no edge already on the path (each edge at most once, so a loop is
    followed once and the path stops where it cannot go on). A body without condition steps
    has its one shortest path from the start to an `end` step."""
    if not body.steps:
        return []
    by = {s.id: s for s in body.steps}
    start = body.steps[0].id
    ends = {s.id for s in body.steps if s.type == "end"}
    conditions = [s for s in body.steps if s.type == "condition"]
    if not conditions:
        return [_shortest(by, start, ends.__contains__, set()) or [start]]
    paths = []
    for c in conditions:
        prefix = _shortest(by, start, c.id.__eq__, set())
        if prefix is None:
            continue
        for e in c.next:
            used = _edges(prefix) | {(c.id, e.to)}
            suffix = (_shortest(by, e.to, ends.__contains__, used) if e.to in by else None)
            paths.append(prefix + (suffix or [e.to]))
    return paths


class _Graph:
    """Builds a step list in order: each step or row group is entered from the exits of
    what came before it; `finish` appends the end step."""

    def __init__(self) -> None:
        self.steps: list[dict] = []
        self.exits: list[tuple[int, str | None]] = []  # (step index, guard) awaiting a successor

    def _new(self, type_: str, text: str, span: tuple[int, int] | None, **extra) -> int:
        self.steps.append({"id": f"s{len(self.steps) + 1}", "type": type_, "text": text,
                           "span": span, "next": [], **extra})
        return len(self.steps) - 1

    def _link(self, i: int, j: int, guard: str | None) -> None:
        self.steps[i]["next"].append(Edge(to=self.steps[j]["id"], guard=guard))

    def _enter(self, j: int) -> None:
        for i, guard in self.exits:
            self._link(i, j, guard)
        self.exits = []

    def step(self, type_: str, text: str, span: tuple[int, int], tool: str | None = None,
             ref: str | None = None) -> None:
        j = self._new(type_, text, span, tool=tool, subprocedure_ref=ref)
        self._enter(j)
        self.exits = [(j, None)]

    def rows(self, rows: list[tuple[str, str, tuple[int, int], tuple]]) -> None:
        """Condition steps chained by "otherwise", each with its action: rows of (guard,
        condition text, its span, (action type, text, span, tool, subprocedure ref))."""
        actions: list[int] = []
        prev = None
        for guard, text, span, (a_type, a_text, a_span, a_tool, a_ref) in rows:
            c = self._new("condition", text, span, condition=guard)
            if prev is None:
                self._enter(c)
            else:
                self._link(prev, c, "otherwise")
            a = self._new(a_type, a_text, a_span, tool=a_tool, subprocedure_ref=a_ref)
            self._link(c, a, guard)
            actions.append(a)
            prev = c
        if prev is not None:
            self.exits = [(a, None) for a in actions] + [(prev, "otherwise")]

    def finish(self) -> list[Step]:
        j = self._new("end", "", None)
        self._enter(j)
        return [Step(**s) for s in self.steps]


def _body(steps: list[Step], source_kind: str) -> ProcedureBody:
    flags = ["coarse"] if sum(s.type != "end" for s in steps) < MIN_STEPS else []
    draft = ProcedureBody(steps=steps, ambiguity_flags=flags, source_kind=source_kind)
    return draft.model_copy(update={"tests": branch_paths(draft)})


# -- locating text ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return " ".join(s.split())


_BOUND = {"letter": r"[^\W\d_]", "digit": r"\d"}


def _kind(c: str) -> str:
    return "digit" if c.isdigit() else "letter" if c.isalpha() else "other"


@lru_cache(maxsize=4096)
def _pattern(segments: tuple[str, ...]) -> re.Pattern | None:
    """A pattern for `segments` read in order, ignoring whitespace (between segments also
    pipes, colons and dashes: table cells). An end that is a letter is not next to another
    letter and one that is a digit not next to another digit, so "No" is not read in "Not"
    while "1424Fees", where the extractor glued two table cells, still holds "Fees"."""
    parts = ["".join(c for c in s if not c.isspace()) for s in segments]
    parts = [p for p in parts if p]
    if not parts:
        return None
    body = r"[\s|:\-]*".join(r"\s*".join(map(re.escape, p)) for p in parts)
    lead, trail = _BOUND.get(_kind(parts[0][0]), ""), _BOUND.get(_kind(parts[-1][-1]), "")
    lead = f"(?<!{lead})" if lead else ""
    trail = f"(?!{trail})" if trail else ""
    return re.compile(lead + body + trail)


def _find(text: str, segments: tuple[str, ...], lo: int, hi: int) -> tuple[int, int] | None:
    pat = _pattern(segments)
    m = pat.search(text, lo, hi) if pat is not None else None
    return (m.start(), m.end()) if m else None


_BULLET_LINE = re.compile(r"\n[ \t]*[-*+]?[ \t]*$")


def _trim_end(text: str, start: int, end: int, pipes: bool = False) -> int:
    """`end` moved back over trailing whitespace, lines holding only a list bullet and, with
    `pipes`, table pipes."""
    strip = " \t\r\n\f|" if pipes else " \t\r\n\f"
    while True:
        while end > start and text[end - 1] in strip:
            end -= 1
        m = _BULLET_LINE.search(text, start, end)
        if m is None or m.end() != end:
            return end
        end = m.start()


# -- IRM sections ----------------------------------------------------------------------------

_SECTION = 'contains(concat(" ", normalize-space(@class), " "), " section ")'
_NUMBER = re.compile(r"^((?:Exhibit\s+)?\d+(?:\.\d+)+(?:-\d+)?)(?!\S)")
_INLINE = frozenset({"a", "abbr", "b", "cite", "code", "em", "font", "i", "kbd", "mark", "q",
                     "s", "small", "span", "strike", "strong", "sub", "sup", "u", "var"})


def _is_section(el) -> bool:
    return el.tag == "div" and "section" in (el.get("class") or "").split()


_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})


def _skipped(el) -> bool:
    """Nested sections, `sectioninfo`, `titlepage`, and the label of a note ("Note:",
    "Reminder:", a heading in a `div.note`), which the extractor drops."""
    cls = el.get("class") or ""
    if el.tag in _HEADINGS:
        parent = el.getparent()
        if parent is not None and "note" in (parent.get("class") or "").split():
            return True
    return _is_section(el) or "sectioninfo" in cls or "titlepage" in cls


def _lines(root, after=None, until=None) -> list[str]:
    """The non-empty lines of `root`'s own text, whitespace collapsed: block elements break
    lines, inline ones do not; what `_skipped` names is left out. With `after`, only the text
    after that element counts; with `until`, the text stops at that element."""
    parts: list[str] = []
    state = {"on": after is None, "stop": False}

    def emit(s: str | None) -> None:
        if s and state["on"] and not state["stop"]:
            parts.append(s)

    def walk(el) -> None:
        if state["stop"] or not isinstance(el.tag, str):
            return
        if el is until:
            state["stop"] = True
            return
        if el is after:
            state["on"] = True
            return
        if el is not root and _skipped(el):
            return
        if el.tag == "br":
            emit("\n")
            return
        block = el.tag not in _INLINE
        if block:
            emit("\n")
        emit(el.text)
        for child in el:
            walk(child)
            emit(child.tail)
        if block:
            emit("\n")

    walk(root)
    return [line for line in map(_norm, "".join(parts).split("\n")) if line]


def _own_html(sec) -> str:
    """`sec` serialised without its nested sections (their tails kept)."""
    own = copy.deepcopy(sec)
    for inner in own.xpath(f".//div[{_SECTION}]"):
        parent, tail = inner.getparent(), inner.tail or ""
        if parent is None:
            continue
        before = inner.getprevious()
        if before is not None:
            before.tail = (before.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail
        parent.remove(inner)
    return etree.tostring(own, encoding="unicode", with_tail=False)


@dataclass(frozen=True)
class IrmSection:
    doc_id: str
    number: str            # "21.4.1.3.1"
    title: str             # "Missing Refund Research"
    start: int             # document offsets of its own text (and of the sections merged in)
    end: int
    html: str              # its own div.section, then those of the sections merged into it
    merged: tuple[str, ...]


@dataclass(frozen=True)
class _Raw:
    number: str
    title: str
    first_line: str | None
    html: str


def _irm_raw(store: Store, doc_id: str) -> tuple[str, list[_Raw]]:
    """(the chapter heading, "21.4.1 Refund Research"; the numbered sections in document
    order) of IRM document `doc_id`, read from its stored HTML."""
    if not (ap.chain_of(store.source(doc_id)) or "").startswith("irm:"):
        raise ValueError(f"{doc_id[:12]}: not an IRM document")
    raw = (Path(store.path) / "blobs" / doc_id[:2] / doc_id).read_bytes()
    if hashlib.sha256(raw).hexdigest() != doc_id:
        raise ValueError(f"{doc_id[:12]}: the stored bytes are not the document's bytes")
    root = lxml_html.document_fromstring(raw, parser=lxml_html.HTMLParser(
        no_network=True, remove_comments=True))
    heads = root.xpath(f'//div[{_SECTION}]/h2[contains(@class, "title")]')
    chapter = _norm(heads[0].text_content()) if heads else ap.chain_of(
        store.source(doc_id)).split(":", 1)[1]
    out = []
    for sec in root.xpath(f"//div[{_SECTION}]"):
        info = sec.xpath('./div[contains(@class, "sectioninfo")]//strong')
        m = _NUMBER.match(_norm(" ".join(i.text_content() for i in info)))
        if m is None:
            continue
        titles = sec.xpath('./div[contains(@class, "titlepage")]//*[self::h1 or self::h2 or '
                           'self::h3 or self::h4 or self::h5 or self::h6]')
        lines = _lines(sec)
        out.append(_Raw(m.group(1), _norm(titles[0].text_content()) if titles else "",
                        lines[0] if lines else None, _own_html(sec)))
    return chapter, out


def _segment(text: str, doc_id: str, raws: list[_Raw]) -> tuple[list[IrmSection], list[str]]:
    located: list[dict] = []
    unlocated: list[str] = []
    cursor = 0
    for r in raws:
        found = (_find(text, (r.first_line,), cursor, len(text))
                 if r.first_line is not None else None)
        if found is None:
            unlocated.append(r.number)
            if located:
                located[-1]["merged"].append(r)
            continue
        located.append({"raw": r, "start": found[0], "merged": []})
        cursor = found[1]
    out = []
    for i, s in enumerate(located):
        stop = located[i + 1]["start"] if i + 1 < len(located) else len(text)
        r = s["raw"]
        out.append(IrmSection(
            doc_id=doc_id, number=r.number, title=r.title, start=s["start"],
            end=_trim_end(text, s["start"], stop),
            html=r.html + "".join(m.html for m in s["merged"]),
            merged=tuple(m.number for m in s["merged"])))
    return out, unlocated


def irm_sections(store: Store, doc_id: str) -> tuple[list[IrmSection], list[str]]:
    """(the located sections of IRM document `doc_id` in document order, the numbers of the
    unlocated ones), as the module docstring says."""
    _, raws = _irm_raw(store, doc_id)
    return _segment(store.text(doc_id), doc_id, raws)


# -- IRM skeletons ---------------------------------------------------------------------------

_HEAD_IF = re.compile(r"if\b", re.IGNORECASE)
_HEAD_THEN = re.compile(r"then\b", re.IGNORECASE)
# a command code: "Command Code REQ77", "Command Code (CC) ERINV", "command codes ENREQ, ..."
# and, by the ruling on review I4, "CC ENMOD" (four or more capitals and digits, so the closing
# codes "cc 088" and words such as "CC ADD" do not count)
_COMMAND = re.compile(r"\b[Cc]ommand\s+[Cc]odes?\s+(?:\(CC\)\s+)?([A-Z][A-Z0-9]+)\b"
                      r"|\bCC\s+([A-Z][A-Z0-9]{3,})\b")
_TC = re.compile(r"\bTC\s+(\d{3})\b")
_IRM_REF = re.compile(r"\brefer\s+to\s+IRM\s+(\d+(?:\.\d+)+)", re.IGNORECASE)
_HANDOFF = re.compile(r"\brefer\s+the\s+case\s+to\b|\bescalate\b", re.IGNORECASE)


def _if_then(table) -> tuple[object, int, list[int], list[int]] | None:
    """(the header row, the Then column, the If-side columns, the "Row" columns) of an
    If/Then table, else None."""
    head = table.xpath("./thead/tr[1]") or table.xpath("./tbody/tr[1] | ./tr[1]")
    if not head:
        return None
    cells = [_norm(c.text_content()) for c in head[0].xpath("./th | ./td")]
    then = next((i for i, c in enumerate(cells) if _HEAD_THEN.match(c)), None)
    if then is None or not any(_HEAD_IF.match(c) for c in cells):
        return None
    rows = [i for i in range(then) if cells[i].lower() == "row"]
    return head[0], then, [i for i in range(then) if i not in rows], rows


def _group(s: IrmSection):
    return lxml_html.fragment_fromstring(s.html, create_parent="div")


def is_procedure_like(s: IrmSection) -> bool:
    """Whether `s` (with the sections merged into it) holds an If/Then table."""
    return any(_if_then(t) is not None for t in _group(s).iter("table"))


def _classify(text: str) -> tuple[str, str | None, str | None]:
    """(step type, tool, subprocedure reference) of a paragraph's or action's text."""
    codes = sorted([(m.start(), m.group(1) or m.group(2)) for m in _COMMAND.finditer(text)]
                   + [(m.start(), f"TC {m.group(1)}") for m in _TC.finditer(text)])
    if codes:
        return "tool_call", codes[0][1], None
    if m := _IRM_REF.search(text):
        return "subprocedure", None, f"IRM {m.group(1)}"
    if _HANDOFF.search(text):
        return "handoff", None, None
    return "instruction", None, None


@dataclass
class _Anchor:
    """A step's (or table header's) first line, `segments`, found after `lead` (a row's
    "Row" cells): `found` is the whole match, `start` where the step's text begins; `reason`
    says why an anchor was not found."""

    kind: Literal["paragraph", "after_table", "header", "condition", "action"]
    segments: tuple[str, ...]
    lead: tuple[str, ...] = ()
    found: tuple[int, int] | None = None
    start: int = 0
    reason: str | None = None


def _first(el, after=None, until=None) -> str | None:
    lines = _lines(el, after, until)
    return lines[0] if lines else None


def _locate(anchors: list[_Anchor], text: str, lo: int, hi: int) -> None:
    """Place the anchors in [lo, hi): of all the ways to give anchors matches that follow one
    another in anchor order, the one that places the most anchors, each placed anchor at its
    earliest match that still allows that many. So an anchor missing from the text never
    takes a later anchor's match when that would cost anchors (a Then cell dropped by the
    extractor whose first line opens a later cell), and a later anchor's text met early,
    inside an earlier step, does not unseat the anchor before it. An anchor left out is
    `not_in_text` when its text is nowhere in [lo, hi), else `out_of_order`."""
    occ = []
    for a in anchors:
        pat = _pattern(a.lead + a.segments)
        occ.append([m.span() for m in pat.finditer(text, lo, hi)] if pat is not None else [])
    starts = sorted({st for o in occ for st, _ in o})
    n = len(starts)
    tree = [0] * (n + 1)  # a Fenwick tree of maxima over match starts, high starts first

    def put(st: int, v: int) -> None:
        i = n - bisect_left(starts, st)
        while i <= n:
            tree[i] = max(tree[i], v)
            i += i & -i

    def best_from(pos: int) -> int:  # the longest chain of later anchors starting at >= pos
        i, out = n - bisect_left(starts, pos), 0
        while i > 0:
            out = max(out, tree[i])
            i -= i & -i
        return out

    best = [[0] * len(o) for o in occ]
    for i in reversed(range(len(anchors))):
        best[i] = [1 + best_from(en) for _, en in occ[i]]
        for (st, _), v in zip(occ[i], best[i], strict=True):
            put(st, v)
    need = max((v for vs in best for v in vs), default=0)
    cursor = lo
    for i, a in enumerate(anchors):
        pick = next((m for m, v in zip(occ[i], best[i], strict=True)
                     if m[0] >= cursor and v == need), None) if need else None
        if pick is None:
            a.found = None
            a.reason = "out_of_order" if occ[i] else "not_in_text"
            continue
        a.found, cursor, need = pick, pick[1], need - 1
        a.start = (_find(text, a.segments, *pick) or pick)[0] if a.lead else pick[0]


def _irm_skeleton(s: IrmSection, text: str) -> tuple[ProcedureBody, list[dict]]:
    # 1. the anchors in document order: per paragraph its first line, then per If/Then table
    # its header, per row its condition and action, and the paragraph's first line after the
    # table (before the next If/Then table); rows keep their guard (the If-side cells' lines)
    anchors: list[_Anchor] = []
    plan: list[tuple] = []  # ("p", anchor index) or ("t", [(guard, cond index, act index)])
    dropped: list[dict] = []

    def add(a: _Anchor) -> int:
        anchors.append(a)
        return len(anchors) - 1

    for sec in _group(s):
        if not isinstance(sec.tag, str) or not _is_section(sec):
            continue
        for li in sec.xpath('./ol/li | ./div[contains(@class, "orderedlist")]/ol/li'):
            first = _first(li)
            if first is None:
                continue
            plan.append(("p", add(_Anchor("paragraph", (first,)))))
            tables = [(t, shape) for t in li.iter("table") if (shape := _if_then(t)) is not None]
            for k, (table, (head, then, if_cols, row_cols)) in enumerate(tables):
                add(_Anchor("header", tuple(
                    _norm(c.text_content()) for c in head.xpath("./th | ./td"))))
                rows = []
                for tr in table.xpath("./tbody/tr | ./tr"):
                    if tr is head:
                        continue
                    cells = tr.xpath("./td | ./th")
                    sides = [cells[i] for i in if_cols if i < len(cells)]
                    guard = "; ".join(t for c in sides if (t := " ".join(_lines(c))))
                    cond = next((f for c in sides if (f := _first(c))), None)
                    act = _first(cells[then]) if then < len(cells) else None
                    if not guard or cond is None or act is None:
                        dropped.append({"kind": "row", "reason": "empty_cell",
                                        "text": (guard or act or "")[:80]})
                        continue
                    lead = tuple(f for i in row_cols if i < len(cells) and (f := _first(cells[i])))
                    rows.append((guard, add(_Anchor("condition", (cond,), lead)),
                                 add(_Anchor("action", (act,)))))
                plan.append(("t", rows))
                nxt = tables[k + 1][0] if k + 1 < len(tables) else None
                if (after := _first(li, after=table, until=nxt)) is not None:
                    plan.append(("p", add(_Anchor("after_table", (after,)))))
    # 2. locate them in order inside the section
    _locate(anchors, text, s.start, s.end)

    def span(i: int) -> tuple[int, int]:
        a = anchors[i]
        nxt = next((b for b in anchors[i + 1:] if b.found is not None), None)
        stop = nxt.found[0] if nxt is not None else s.end
        pipes = a.kind in ("condition", "action") or (
            nxt is not None and nxt.kind in ("header", "condition", "action"))
        return a.start, _trim_end(text, a.start, stop, pipes)

    # 3. the graph
    g = _Graph()
    for kind, item in plan:
        if kind == "p":
            a = anchors[item]
            if a.found is None:
                dropped.append({"kind": a.kind, "reason": a.reason, "text": a.segments[0][:80]})
                continue
            st, en = span(item)
            p_type, p_tool, p_ref = _classify(text[st:en])
            g.step(p_type, text[st:en], (st, en), tool=p_tool, ref=p_ref)
            continue
        rows = []
        for guard, ci, ai in item:
            missing = next((anchors[i] for i in (ai, ci) if anchors[i].found is None), None)
            if missing is not None:
                dropped.append({"kind": "row", "reason": missing.reason, "text": guard[:80]})
                continue
            cs, ce = span(ci)
            as_, ae = span(ai)
            a_type, a_tool, a_ref = _classify(text[as_:ae])
            rows.append((guard, text[cs:ce], (cs, ce),
                         (a_type, text[as_:ae], (as_, ae), a_tool, a_ref)))
        g.rows(rows)
    return _body(g.finish(), "irm"), dropped


def irm_skeleton(s: IrmSection, text: str) -> ProcedureBody:
    """The step skeleton of IRM section `s` in its document's canonical text `text` (rules
    in the module docstring)."""
    return _irm_skeleton(s, text)[0]


# -- bench -----------------------------------------------------------------------------------

_KIND = re.compile(r"\b(?:" + "|".join(BENCH_KINDS) + r")s?\b", re.IGNORECASE)
_NUMBERED = re.compile(r"\d{1,9}[.)](?:[ \t]+|$)")
_STEP_HEAD = re.compile(r"(?:step\s+\d+\b|\d+[.)](?:\s|$))", re.IGNORECASE)
_IF_ITEM = re.compile(r"If\b")
_IF_END = re.compile(r"[:,](?=\s|$)")         # a colon or comma ending the If clause
_BULLET = re.compile(r"(?:[-*+]|\d{1,9}[.)])[ \t]+")


def _title(text: str) -> str:
    first = next((line for line in text.split("\n") if line.strip()), "")
    return first.strip().lstrip("#").strip()


def _indent(text: str, at: int) -> int:
    return at - (text.rfind("\n", 0, at) + 1)


def _bench_steps(text: str) -> list[tuple[int, int, bool]]:
    """(start, end, is a list item) of the steps of a bench document."""
    headings, blocks = md.read_blocks(text)
    heads = [h for h in headings if _STEP_HEAD.match(h.title)]
    if len(heads) >= MIN_STEPS:
        out = []
        for h in heads:
            stop = next((o.start for o in headings if o.start > h.start and o.rank <= h.rank),
                        len(text))
            out.append((h.start, _trim_end(text, h.start, stop), False))
        return out
    out = []
    for k, b in enumerate(blocks):
        if b.type != "list_item" or _indent(text, b.start) > 3:
            continue
        m = _NUMBERED.match(text, b.start)
        if m is None:
            continue
        end, own = b.end, _indent(text, b.start)
        for nxt in blocks[k + 1:]:
            at = _indent(text, nxt.start)
            sub = at > own or (at == own and not _NUMBERED.match(text, nxt.start)
                               and "\n\n" not in text[end:nxt.start])
            if (nxt.type != "list_item" or not sub
                    or any(end <= h.start < nxt.start for h in headings)):
                break
            end = nxt.end
        out.append((m.end(), end, True))
    return out


def _if_split(text: str, start: int, end: int) -> tuple[int, int] | None:
    """(end of the If clause, start of the action) of a list item starting with "If" in
    [start, end): the clause runs to the first colon or comma followed by a space or the end
    of the line, else to the end of the first line; the action is what follows (a leading
    list bullet skipped), the item's sub-items when the line ends there. None when there is
    no action."""
    line_end = text.find("\n", start, end)
    line_end = end if line_end < 0 else line_end
    m = _IF_END.search(text, start, line_end)
    clause_end = m.start() if m else _trim_end(text, start, line_end)
    rest = m.end() if m else line_end
    while rest < end and text[rest].isspace():
        rest += 1
    if (b := _BULLET.match(text, rest, end)) is not None:
        rest = b.end()
    return (clause_end, rest) if rest < end and clause_end > start else None


def _bench_skeleton(text: str) -> tuple[ProcedureBody, Counter]:
    g, ifs = _Graph(), Counter()
    for start, end, item in _bench_steps(text):
        split = _if_split(text, start, end) if item and _IF_ITEM.match(text, start) else None
        if item and _IF_ITEM.match(text, start):
            ifs["conditions" if split else "no_action"] += 1
        if split is None:
            g.step("instruction", text[start:end], (start, end))
            continue
        clause_end, rest = split
        guard = text[start:clause_end]
        g.rows([(guard, guard, (start, clause_end),
                 ("instruction", text[rest:end], (rest, end), None, None))])
    return _body(g.finish(), "bench"), ifs


def _bench_candidates(store: Store) -> list[str]:
    out = []
    for d in sorted(store.doc_ids()):
        if store.source(d).format != "md":
            continue
        text = store.text(d)
        if _KIND.search(_title(text)) and len(_bench_steps(text)) >= MIN_STEPS:
            out.append(d)
    return out


def _draw(candidates: list[str], seed: int, cap: int) -> list[str]:
    key = lambda d: hashlib.sha256(f"{seed}:{d}".encode()).hexdigest()  # noqa: E731
    return sorted(sorted(candidates, key=key)[:cap])


def bench_candidates(store: Store, seed: int = SEED4, cap: int = BENCH_CAP) -> list[str]:
    """The bench procedure documents drawn (module docstring), sorted by doc id."""
    return _draw(_bench_candidates(store), seed, cap)


def bench_skeleton(store: Store, doc_id: str) -> ProcedureBody:
    """The step skeleton of bench document `doc_id` (rules in the module docstring)."""
    return _bench_skeleton(store.text(doc_id))[0]


# -- units -----------------------------------------------------------------------------------

def _resliced(body: ProcedureBody, text: str) -> list[str]:
    return [f"{s.id}: span does not re-slice" for s in body.steps
            if s.span is not None and text[s.span[0]:s.span[1]] != s.text]


def procedure_units(store: Store, corpus: str, overlay: Applicability | None
                    ) -> tuple[list[Unit], dict]:
    """(the procedure units of `corpus` in `store` sorted by unit id, the build report). gov:
    one per procedure-like IRM section; bench: one per drawn candidate; other corpora have
    none. A body that fails `validate_ir` or whose spans do not re-slice is rejected and
    reported. The report holds no run-varying value: IRM documents, sections (raw), located,
    unlocated (with the section each merged into), procedure-like sections and their If/Then
    tables, bench candidates and drawn, procedures, coarse ones, steps per type, dropped
    paragraphs, rows and text after tables (with the reason: `not_in_text`, `out_of_order`,
    `empty_cell`), procedure-like sections left with no condition step (with the reason),
    bench "If" items made conditions or left instructions for want of an action, rejected
    bodies."""
    report: dict = {"corpus": corpus, "documents": 0, "sections": 0, "located": 0,
                    "unlocated": [], "procedure_like": 0, "if_then_tables": 0,
                    "candidates": 0, "drawn": 0, "procedures": 0, "coarse": 0, "steps": {},
                    "dropped": [], "no_condition": [],
                    "if_items": {"conditions": 0, "no_action": 0}, "rejected": []}
    built: list[tuple[str, list[str], str, str, int, int, ProcedureBody, list[dict]]] = []
    if corpus == "gov":
        irm = sorted(d for d in store.doc_ids() if ap.family_of(store.source(d).uri) == "irm")
        for d in irm:
            text = store.text(d)
            chapter, raws = _irm_raw(store, d)
            titles = {r.number: r.title for r in raws}
            secs, unlocated = _segment(text, d, raws)
            report["documents"] += 1
            report["sections"] += len(raws)
            report["located"] += len(secs)
            merged_into = {m: s.number for s in secs for m in s.merged}
            report["unlocated"] += [{"doc_id": d, "number": n, "merged_into": merged_into.get(n)}
                                    for n in unlocated]
            for s in secs:
                tables = sum(_if_then(t) is not None for t in _group(s).iter("table"))
                if not tables:
                    continue
                report["procedure_like"] += 1
                report["if_then_tables"] += tables
                ancestors = [f"IRM {n} {titles[n]}" for n in titles
                             if s.number.startswith(n + ".")]
                body, dropped = _irm_skeleton(s, text)
                built.append((s.title, [f"IRM {chapter}", *ancestors, f"IRM {s.number} {s.title}"],
                              f"IRM {s.number}", d, s.start, s.end, body, dropped))
    elif corpus == "bench":
        candidates = _bench_candidates(store)
        report["candidates"] = len(candidates)
        for d in _draw(candidates, SEED4, BENCH_CAP):
            text = store.text(d)
            title = _title(text)
            body, ifs = _bench_skeleton(text)
            for k in report["if_items"]:
                report["if_items"][k] += ifs[k]
            built.append((title, [title], f"bench:{d}", d, 0, len(text), body, []))
        report["drawn"] = len(built)
    units, steps = [], Counter()
    for title, path, ref, d, start, end, body, dropped in built:
        text = store.text(d)
        report["dropped"] += [{"canonical_ref": ref, "doc_id": d, **x} for x in dropped]
        if ref.startswith("IRM ") and not any(s.type == "condition" for s in body.steps):
            rows = Counter(x["reason"] for x in dropped if x["kind"] == "row")
            report["no_condition"].append({
                "canonical_ref": ref, "doc_id": d,
                "reason": f"all {sum(rows.values())} If/Then rows dropped ("
                          + ", ".join(f"{k} {v}" for k, v in sorted(rows.items())) + ")"})
        problems = validate_ir(body) + _resliced(body, text)
        if problems:
            report["rejected"].append({"canonical_ref": ref, "doc_id": d, "problems": problems})
            continue
        units.append(make_unit(
            type_="procedure", title=title, heading_path=path, canonical_ref=ref,
            text=text[start:end], doc_id=d, spans=[(start, end, SPEC_ID)],
            body=body.model_dump(mode="json"), store=store, overlay=overlay, corpus=corpus))
        steps.update(s.type for s in body.steps)
        report["coarse"] += "coarse" in body.ambiguity_flags
    report["procedures"] = len(units)
    report["steps"] = dict(sorted(steps.items()))
    return sorted(link_versions(units, overlay), key=lambda u: u.unit_id), report
