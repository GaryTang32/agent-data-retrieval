"""SKILL.md and Mermaid renderers and their subset parsers (Phase 4 spec §9.2, criterion U3,
P39, P40; preflight notes N19, C2; the Task 5 review's fix round 1). Pure functions on the IR
and fixture stores under `tmp_path`: no Node, no Mermaid CLI, no PyYAML, no model and nothing
under `.cache/`."""

import hashlib
import re

import pytest

from adr_store.units.procedures import Edge, ProcedureBody, Step, not_extracted, procedure_units
from adr_store.units.render import (
    LABEL_MAX,
    REFERENCES_FROM,
    SKILL_BODY_MAX_LINES,
    ir_graph,
    parse_mermaid,
    parse_skill,
    render_mermaid,
    render_skill,
)
from tests.store import units_fixtures as uf
from tests.store.units_fixtures import model_field, overlay_of

units_store = uf.units_store


# -- helpers ---------------------------------------------------------------------------------

def step(id_, type_="instruction", nxt=(), text="x", **extra) -> Step:
    """A step whose `nxt` holds (to, guard) pairs."""
    return Step(id=id_, type=type_, text=text, span=None,
                next=[Edge(to=t, guard=g) for t, g in nxt], **extra)


def body(*steps: Step, when_to_use: dict | None = None) -> ProcedureBody:
    return ProcedureBody(when_to_use=when_to_use or not_extracted(), steps=list(steps),
                         source_kind="authored")


def rows_body(n: int) -> ProcedureBody:
    """One instruction, then an If/Then table of `n` rows chained by "otherwise" (P39), every
    exit entering one unconditional step after the table, then the end."""
    steps = [step("s1", nxt=[("c1", None)], text="Use the table below:")]
    after = "after"
    for i in range(1, n + 1):
        other = f"c{i + 1}" if i < n else after
        steps.append(step(f"c{i}", "condition", [(f"a{i}", f"If case {i} holds"),
                                                 (other, "otherwise")], text=f"If case {i}"))
        steps.append(step(f"a{i}", nxt=[(after, None)], text=f"Then do action {i}."))
    steps += [step(after, nxt=[("end", None)], text="Note: record what was done."),
              step("end", "end", text="")]
    return body(*steps)


LINEAR = body(step("s1", nxt=[("s2", None)], text="First."),
              step("s2", nxt=[("s3", None)], text="Second."),
              step("s3", "end", text=""))
BRANCHING = body(step("s1", "condition", [("s2", "If the bank rejected it"), ("s3", "otherwise")],
                      text="If the bank rejected it"),
                 step("s2", nxt=[("s4", None)], text="Issue a paper check."),
                 step("s3", nxt=[("s4", None)], text="Wait for the deposit."),
                 step("s4", "end", text=""))
CYCLIC = body(step("s1", nxt=[("s2", None)], text="Check the queue."),
              step("s2", "condition", [("s1", "If messages remain"), ("s3", "otherwise")],
                   text="If messages remain"),
              step("s3", "end", text=""))
# The IRM shape of P39 with every step type the real data has: a tool call, a table whose
# rows are chained by "otherwise" (the last row's leading to the text after the table), a
# subprocedure whose reference adds no edge, the unconditional step after the table, a
# handoff and the end.
IRM_SHAPE = body(
    step("s1", "tool_call", [("s2", None)], text="Research with Command Code IMFOLT.",
         tool="IMFOLT"),
    step("s2", "condition", [("s3", "If the check was lost"), ("s4", "otherwise")],
         text="If the check was lost", condition="If the check was lost"),
    step("s3", "tool_call", [("s6", None)], text="Then input TC 971.", tool="TC 971"),
    step("s4", "condition", [("s5", "Yes; the RTN is on file"), ("s6", "otherwise")],
         text="Yes; the RTN is on file", condition="Yes; the RTN is on file"),
    step("s5", "subprocedure", [("s6", None)], text="Then refer to IRM 21.4.1.3.2.",
         subprocedure_ref="IRM 21.4.1.3.2"),
    step("s6", nxt=[("s7", None)], text="Reminder: document the action\non the account."),
    step("s7", "handoff", [("s8", None)], text="Refer the case to the Refund Unit."),
    step("s8", "end", text=""))
# guards that need escaping: quotes, pipes, hashes, entity look-alikes, newlines, edge spaces,
# brackets (Mermaid delimiters outside a quoted label) and backticks
BRACKETS = "TC 971 AC 111 (CC TXMOD) [AM] {x} `y`"
AWKWARD = body(
    step("s1", "condition", [("s2", 'MISC: "AM" or "AMADJ"'), ("s3", "a | b #1 #quot; #124;"),
                             ("s4", "line one\nline two\ttab"), ("s5", " padded "),
                             ("s5", BRACKETS)],
         text='Check "MISC" | codes #1 `z`'),
    step("s2", nxt=[("s5", None)], text="A."),
    step("s3", nxt=[("s5", None)], text="B."),
    step("s4", nxt=[("s5", None)], text="C."),
    step("s5", "end", text=""))
FIXTURE_BODIES = [pytest.param(LINEAR, id="linear"), pytest.param(BRANCHING, id="branching"),
                  pytest.param(CYCLIC, id="cyclic"),
                  pytest.param(rows_body(12), id="12-conditions"),
                  pytest.param(IRM_SHAPE, id="irm-shape"), pytest.param(AWKWARD, id="awkward")]


def body_with_label(text: str) -> ProcedureBody:
    return body(step("s1", nxt=[("s2", None)], text=text), step("s2", "end", text=""))


def labels_of(mermaid: str) -> list[str]:
    return [m.group(1) or m.group(2)
            for m in re.finditer(r'^ {4}s\d+(?:\["([^"]*)"\]|\{"([^"]*)"\})$', mermaid, re.M)]


def procedure_units_of(store) -> list:
    units = []
    for corpus in ("gov", "bench"):
        units += procedure_units(store, corpus, overlay_of(store))[0]
    return units


def procedure_unit(b: ProcedureBody, ref: str = "IRM 21.4.1.3.1"):
    return uf.sample_unit("procedure", ref=ref, body=b.model_dump(mode="json"))


def split_skill(text: str) -> tuple[list[str], list[str]]:
    """(body lines after the front matter up to the references heading, reference lines)."""
    lines = text.split("\n")
    end = lines.index("---", 1)
    rest = lines[end + 1:]
    if "## references/" in rest:
        i = rest.index("## references/")
        return rest[:i], rest[i:]
    return rest, []


# -- Mermaid ---------------------------------------------------------------------------------

@pytest.mark.parametrize("b", FIXTURE_BODIES)
def test_mermaid_round_trips_to_the_ir_graph(b):
    assert parse_mermaid(render_mermaid(b)) == ir_graph(b)


def test_ir_graph_is_the_step_graph_renumbered_in_step_order():
    renamed = body(step("start", "condition", [("x", "If so"), ("end", "otherwise")], text="?"),
                   step("x", nxt=[("start", None)], text="Loop."),
                   step("end", "end", text=""))
    assert ir_graph(renamed) == ((("s1", "rhombus"), ("s2", "box"), ("s3", "box")),
                                 (("s1", "s2", "If so"), ("s1", "s3", "otherwise"),
                                  ("s2", "s1", None)))
    with pytest.raises(ValueError, match="nope"):
        ir_graph(body(step("s1", nxt=[("nope", None)]), step("s2", "end", text="")))
    with pytest.raises(ValueError, match="duplicate"):
        ir_graph(body(step("s1", nxt=[("s1", None)]), step("s1", "end", text="")))


def test_the_irm_shape_round_trips_with_chained_otherwise_and_the_step_after_the_table():
    """P39: row conditions chained by "otherwise", the last row's and every action's exit
    entering the unconditional step after the table; the subprocedure's reference adds no
    edge; every real step type renders as a node."""
    nodes, edges = ir_graph(IRM_SHAPE)
    assert {s.type for s in IRM_SHAPE.steps} == {"tool_call", "condition", "instruction",
                                                 "subprocedure", "handoff", "end"}
    assert nodes == (("s1", "box"), ("s2", "rhombus"), ("s3", "box"), ("s4", "rhombus"),
                     ("s5", "box"), ("s6", "box"), ("s7", "box"), ("s8", "box"))
    assert edges == (
        ("s1", "s2", None), ("s2", "s3", "If the check was lost"), ("s2", "s4", "otherwise"),
        ("s3", "s6", None), ("s4", "s5", "Yes; the RTN is on file"), ("s4", "s6", "otherwise"),
        ("s5", "s6", None), ("s6", "s7", None), ("s7", "s8", None))
    m = render_mermaid(IRM_SHAPE)
    assert parse_mermaid(m) == (nodes, edges)
    assert "IRM 21.4.1.3.2" not in {t for _, t, _ in edges}
    assert m.splitlines()[:9] == [
        "flowchart TD",
        '    s1["Research with Command Code IMFOLT."]',
        '    s2{"If the check was lost"}',
        '    s3["Then input TC 971."]',
        '    s4{"Yes; the RTN is on file"}',
        '    s5["Then refer to IRM 21.4.1.3.2."]',
        '    s6["Reminder: document the action on the account."]',
        '    s7["Refer the case to the Refund Unit."]',
        '    s8["end"]']
    assert m.splitlines()[9:] == [
        "    s1 --> s2", '    s2 -->|"If the check was lost"| s3', '    s2 -->|"otherwise"| s4',
        "    s3 --> s6", '    s4 -->|"Yes; the RTN is on file"| s5', '    s4 -->|"otherwise"| s6',
        "    s5 --> s6", "    s6 --> s7", "    s7 --> s8"]
    assert m.endswith("s7 --> s8\n")


def test_guards_are_escaped_losslessly():
    m = render_mermaid(AWKWARD)
    edge_lines = [line for line in m.splitlines() if "-->" in line]
    assert edge_lines[0] == '    s1 -->|"MISC: #quot;AM#quot; or #quot;AMADJ#quot;"| s2'
    assert edge_lines[1] == '    s1 -->|"a #124; b #35;1 #35;quot; #35;124;"| s3'
    assert edge_lines[2] == '    s1 -->|"line one#10;line two#9;tab"| s4'
    assert edge_lines[3] == '    s1 -->|"#32;padded#32;"| s5'
    # I1: brackets stay bare inside the quoted label, where Mermaid reads them as text
    assert edge_lines[4] == '    s1 -->|"TC 971 AC 111 (CC TXMOD) [AM] {x} #96;y#96;"| s5'
    assert '    s1{"Check #quot;MISC#quot; | codes #35;1 #96;z#96;"}' in m
    guards = [g for _, _, g in parse_mermaid(m)[1]]
    assert guards[:5] == ['MISC: "AM" or "AMADJ"', "a | b #1 #quot; #124;",
                          "line one\nline two\ttab", " padded ", BRACKETS]


def test_an_empty_guard_cannot_be_rendered():
    for guard in ["", "  "]:
        b = body(step("s1", "condition", [("s2", guard)]), step("s2", "end", text=""))
        with pytest.raises(ValueError, match="empty guard"):
            render_mermaid(b)
        with pytest.raises(ValueError, match="empty guard"):
            render_skill(procedure_unit(b))


def test_the_round_trip_notices_a_lost_or_changed_edge():
    m = render_mermaid(IRM_SHAPE)
    graph = ir_graph(IRM_SHAPE)
    assert parse_mermaid(m.replace("    s5 --> s6\n", "")) != graph
    assert parse_mermaid(m.replace('|"otherwise"| s6', '|"Otherwise"| s6')) != graph
    assert parse_mermaid(m.replace("    s6 --> s7", "    s6 --> s8")) != graph


def test_the_round_trip_compares_node_shapes_and_edge_multiplicity():
    """M3: a box drawn for a condition, a doubled edge or a lost duplicate edge is noticed."""
    m = render_mermaid(IRM_SHAPE)
    graph = ir_graph(IRM_SHAPE)
    assert parse_mermaid(m.replace('    s2{"If the check was lost"}',
                                   '    s2["If the check was lost"]')) != graph
    assert parse_mermaid(m + "    s7 --> s8\n") != graph
    doubled = body(step("s1", nxt=[("s2", None), ("s2", None)]), step("s2", "end", text=""))
    dm = render_mermaid(doubled)
    assert dm.count("    s1 --> s2\n") == 2
    assert parse_mermaid(dm) == ir_graph(doubled) == ((("s1", "box"), ("s2", "box")),
                                                       (("s1", "s2", None), ("s1", "s2", None)))
    assert parse_mermaid(dm.replace("    s1 --> s2\n", "", 1)) != ir_graph(doubled)


def test_labels_are_escaped_and_cut():
    m = render_mermaid(body_with_label('He said "stop"\nnow ' + "x" * 100))
    assert '#quot;stop#quot; now' in m and max(map(len, labels_of(m))) <= 80
    assert LABEL_MAX == 80
    label = labels_of(m)[0]
    assert label.endswith("…") and len(label) == 80
    assert label == 'He said #quot;stop#quot; now ' + "x" * 50 + "…"


def test_a_cut_never_splits_an_entity():
    """N19: the escaped label is at most 80 characters and keeps whole entities."""
    for pad in range(70, 80):
        m = render_mermaid(body_with_label("y" * pad + '"' * 20))
        label = labels_of(m)[0]
        assert len(label) <= LABEL_MAX and label.endswith("…")
        assert re.fullmatch(r"(?:[^#]|#quot;|#35;)*…", label), label
        assert parse_mermaid(m)[0] == (("s1", "box"), ("s2", "box"))
    short = labels_of(render_mermaid(body_with_label("a" * 80)))[0]
    assert short == "a" * 80
    hashes = labels_of(render_mermaid(body_with_label("#1 # done")))[0]
    assert hashes == "#35;1 #35; done"


def test_parse_mermaid_refuses_outside_the_subset():
    good = render_mermaid(BRANCHING)
    assert parse_mermaid(good) == ir_graph(BRANCHING)
    bad = [
        good.replace("flowchart TD", "graph LR"),
        good.replace("flowchart TD", "flowchart LR"),
        good + "    subgraph one\n    end\n",
        good + '    click s1 "https://example.org"\n',
        good.replace('    s2["Issue a paper check."]', '    s2(("Issue a paper check."))'),
        good.replace('    s2["Issue a paper check."]', "    s2[Issue a paper check.]"),
        good.replace("    s2 --> s4", "    s2 -.-> s4"),
        good.replace("    s2 --> s4", "    s2 --> s9"),             # an undeclared node
        good.replace("    s2 --> s4", "    s2 --> s4 --> s1"),
        good + '    s2["again"]\n',                                  # a node declared twice
        good.replace('|"otherwise"|', "|otherwise|"),                 # I1: an unquoted label
        good.replace('|"otherwise"|', '|"other"wise"|'),              # a raw quote
        good.replace('|"otherwise"|', '|"other#wise"|'),              # a stray hash
        good.replace('|"otherwise"|', '|"other#amp;wise"|'),          # an entity not emitted
        good.replace('|"otherwise"|', '|"other#0124;wise"|'),         # M2: a leading zero
        good.replace('|"otherwise"|', '|"other#34;wise"|'),           # `"` is written #quot;
        good.replace('|"otherwise"|', '|"other#36;wise"|'),           # `$` is never escaped
        good.replace('|"otherwise"|', '|"other#32;wise"|'),           # a space inside
        good.replace('|"otherwise"|', '|"other#\u0661\u0662\u0664;wise"|'),  # non-ASCII digits
        good.replace('|"otherwise"|', '|"other#99999999;wise"|'),
        good.replace('|"otherwise"|', '|"other`wise"|'),              # a bare backtick
        good.replace('|"otherwise"|', '|""|'),
        good.replace("Issue a paper check.", "Issue a #36; check."),     # a label entity
        good.replace("Issue a paper check.", "Issue a  paper check."),   # a double space
        good.replace("Issue a paper check.", "Issue a paper `check`."),
        good.replace("Issue a paper check.", "z" * 81),                # a label over 80
        good.replace("    s1", "  s1", 1),
        good.replace("\n    s2 --> s4", "\n\n    s2 --> s4"),           # a blank line
        good.replace("s2 -->", "S2 -->"),
        good + "%% comment\n",
        good.replace('    s4["end"]\n', "") + '    s4["end"]\n',         # a node after edges
        good.replace("    s2 --> s4", "    s2 -->|otherwise| s4"),
        good.rstrip("\n"),                                             # no final newline
        "",
    ]
    for text in bad:
        with pytest.raises(ValueError):
            parse_mermaid(text)


# -- SKILL.md --------------------------------------------------------------------------------

NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
NOTE = "The branches of each step are listed under references/ below."
_YAML_ESCAPES = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v",
                 "f": "\f", "r": "\r", "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\",
                 "N": "\x85", "_": "\xa0", "L": " ", "P": " "}
_YAML_HEX = {"x": 2, "u": 4, "U": 8}


def yaml_double_quoted(raw: str) -> str:
    """A one-line YAML double-quoted scalar decoded by the YAML 1.2 rules (§5.7, §7.3.1),
    independently of `json`: every bare character must be YAML-printable and no line break
    (U+0085, U+2028 and U+2029 count as breaks in YAML 1.1), every escape a YAML escape."""
    assert len(raw) >= 2 and raw[0] == raw[-1] == '"'
    inner, out, i = raw[1:-1], [], 0
    while i < len(inner):
        ch = inner[i]
        if ch == "\\":
            key = inner[i + 1]
            if key in _YAML_HEX:
                width = _YAML_HEX[key]
                out.append(chr(int(inner[i + 2:i + 2 + width], 16)))
                i += 2 + width
            else:
                out.append(_YAML_ESCAPES[key])
                i += 2
            continue
        o = ord(ch)
        assert ch != '"' and ch not in "  ", repr(ch)
        assert (ch == "\t" or 0x20 <= o <= 0x7E or 0xA0 <= o <= 0xD7FF or 0xE000 <= o <= 0xFFFD
                or o >= 0x10000), repr(ch)
        out.append(ch)
        i += 1
    return "".join(out)


def yaml_front_matter(text: str) -> dict:
    """The two front-matter keys read as YAML (M6, pure Python): `name` a plain scalar that
    YAML resolves to a string, `description` a double-quoted scalar."""
    lines = text.split("\n")
    assert lines[0] == "---" and lines[3] == "---"
    assert lines[1].startswith("name: ") and lines[2].startswith("description: ")
    name = lines[1][len("name: "):]
    # a plain scalar of letters, digits and inner hyphens with a hyphen in it is a string in
    # YAML 1.1 and 1.2 (no bool, null, number or timestamp form ends in "-<12 hex>")
    assert NAME.fullmatch(name) and re.search(r"-[0-9a-f]{12}$", name)
    return {"name": name, "description": yaml_double_quoted(lines[2][len("description: "):])}


def hex12(unit) -> str:
    return hashlib.sha256(unit.unit_id.encode()).hexdigest()[:12]


def exhibit_body(tables: int) -> ProcedureBody:
    """IRM Exhibit 5.19.1-7's shape: a field instruction, then `tables` two-row If/Then tables
    whose cells do not start with "If", each followed by the next field."""
    steps = [step("s1", nxt=[("c1a", None)], text='REVIEW ACTION: Enter "1"')]
    for t in range(1, tables + 1):
        nxt = f"c{t + 1}a" if t < tables else "end"
        steps += [
            step(f"c{t}a", "condition", [(f"a{t}a", "Sending a systemic IA confirmation letter"),
                                         (f"c{t}b", "otherwise")],
                 text="Sending a systemic IA confirmation letter"),
            step(f"a{t}a", nxt=[(f"f{t}", None)], text="Enter the taxpayer’s five digit ZIP Code"),
            step(f"c{t}b", "condition",
                 [(f"a{t}b", "Not sending a systemic IA confirmation letter"),
                  (f"f{t}", "otherwise")],
                 text="Not sending a systemic IA confirmation letter"),
            step(f"a{t}b", nxt=[(f"f{t}", None)], text="Leave blank"),
            step(f"f{t}", nxt=[(nxt, None)], text=f"FIELD {t}: Auto-populated.")]
    return body(*steps, step("end", "end", text=""))


def test_skill_front_matter_parses_and_step_count_matches(units_store):
    units = procedure_units_of(units_store)
    assert {u.canonical_ref.split(":")[0] for u in units} == {"IRM 21.4.1.3.1",
                                                               "IRM 21.4.1.3.2", "bench"}
    types, names = set(), []
    for u in units:
        text = render_skill(u)
        meta, n = parse_skill(text)
        assert set(meta) == {"name", "description"} and len(meta["description"]) <= 1024
        assert n == len(u.body["steps"])
        assert meta["description"] == u.title  # when_to_use is not extracted yet
        assert yaml_front_matter(text) == meta
        assert len(meta["name"]) <= 64 and meta["name"].endswith("-" + hex12(u))
        names.append(meta["name"])
        b = ProcedureBody.model_validate(u.body)
        assert parse_mermaid(render_mermaid(b)) == ir_graph(b)
        types |= {s.type for s in b.steps}
    assert types == {"tool_call", "condition", "instruction", "subprocedure", "handoff", "end"}
    assert len(set(names)) == len(names) == 3
    assert sum(n.startswith("missing-refund-research-") for n in names) == 1


def test_skill_renders_numbered_steps_guards_tools_references_and_the_source():
    unit = procedure_unit(IRM_SHAPE)
    name = "irm-21-4-1-3-1-" + hex12(unit)
    text = render_skill(unit)
    assert text == (
        "---\n"
        f"name: {name}\n"
        'description: "IRM 21.4.1.3.1"\n'
        "---\n"
        "\n"
        "# IRM 21.4.1.3.1\n"
        "\n"
        "1. Research with Command Code IMFOLT.\n"
        "   Tool: IMFOLT\n"
        "2. If the check was lost\n"
        "   If the check was lost then step 3\n"
        "   Otherwise step 4\n"
        "3. Then input TC 971.\n"
        "   Tool: TC 971\n"
        "   Go to step 6\n"
        "4. If Yes; the RTN is on file\n"
        "   If Yes; the RTN is on file then step 5\n"
        "   Otherwise step 6\n"
        "5. Then refer to IRM 21.4.1.3.2.\n"
        "   Subprocedure: IRM 21.4.1.3.2\n"
        "6. Reminder: document the action on the account.\n"
        "7. Refer the case to the Refund Unit.\n"
        "   Handoff\n"
        "8. End.\n"
        "\n"
        "Source: IRM 21.4.1.3.1\n")
    assert parse_skill(text) == ({"name": name, "description": "IRM 21.4.1.3.1"}, 8)


def test_skill_guard_lines_drop_a_leading_if_and_trailing_punctuation():
    b = body(step("s1", "condition", [("s2", "IF  the RTN\nmatches."), ("s3", "otherwise")]),
             step("s2", nxt=[("s3", None)]), step("s3", "end", text=""))
    head, _ = split_skill(render_skill(procedure_unit(b)))
    assert head[3:6] == ["1. If x", "   If the RTN matches then step 2", "   Otherwise step 3"]


def test_skill_writes_a_dsl_guard_readably_and_keeps_the_json_elsewhere():
    """Task 21 fix (P52): an adr-dsl@1 guard in JSON, as the authored desk procedure has, is
    written readably in SKILL.md; the IR and the Mermaid keep the JSON; prose guards, and JSON
    that is no DSL expression, are written as before."""
    guards = ['{"eq":["outcome","allow"]}',
              '{"and":[{"cmp":["notice_hours",">=",2]},{"not":{"known":"vessel_class"}}]}',
              '{"or":[{"in":["vessel_class",["public_safety","police"]]},{"const":false}]}',
              '{"not":{"or":[{"eq":["accepts_alternative",true]},{"eq":["x","y"]}]}}',
              '{"eq":["x"]}', '["eq", "outcome", "allow"]', "If the RTN matches."]
    b = body(step("s1", "condition", [(f"t{i}", g) for i, g in enumerate(guards)]),
             *[step(f"t{i}", nxt=[("end", None)]) for i in range(len(guards))],
             step("end", "end", text=""))
    head, _ = split_skill(render_skill(procedure_unit(b)))
    assert head[4:11] == [
        '   If outcome == "allow" then step 2',
        "   If (notice_hours >= 2 and not (vessel_class is known)) then step 3",
        '   If (vessel_class in ["public_safety", "police"] or false) then step 4',
        '   If not (accepts_alternative == true or x == "y") then step 5',
        '   If {"eq":["x"]} then step 6',                       # no DSL: as written
        '   If ["eq", "outcome", "allow"] then step 7',
        "   If the RTN matches then step 8"]
    assert parse_mermaid(render_mermaid(b)) == ir_graph(b)
    assert [g for _, _, g in ir_graph(b)[1]][:len(guards)] == guards   # the graph keeps JSON


def test_a_condition_line_shows_that_it_branches_without_adding_lines():
    """I3, the IRM Exhibit 5.19.1-7 shape: a condition's numbered line starts "If " and, when
    its branch lines are under references/, ends by pointing there; the body gains no line."""
    big = exhibit_body(5)                         # ten conditions: references/ in use
    unit = procedure_unit(big, "IRM Exhibit 5.19.1-7")
    head, refs = split_skill(render_skill(unit))
    assert head[5:10] == [
        '1. REVIEW ACTION: Enter "1"',
        "2. If Sending a systemic IA confirmation letter (branches: see references, step 2)",
        "3. Enter the taxpayer’s five digit ZIP Code",
        "4. If Not sending a systemic IA confirmation letter (branches: see references, step 4)",
        "5. Leave blank"]
    numbered = [line for line in head if re.match(r"\d+\. ", line)]
    assert len(numbered) == len(big.steps)
    assert [line for line in head if not re.match(r"\d+\. ", line)] == [
        "", "# IRM Exhibit 5.19.1-7", "", NOTE, "", "", "Source: IRM Exhibit 5.19.1-7", ""]
    conditions = [i for i, s in enumerate(big.steps, 1) if s.type == "condition"]
    for i in conditions:
        line = numbered[i - 1]
        assert line.startswith(f"{i}. If ") and line.endswith(
            f"(branches: see references, step {i})")
        assert f"Step {i}:" in refs
    assert sum("(branches:" in line for line in numbered) == len(conditions) == 10
    # inline (up to REFERENCES_FROM conditions): the "If " but no pointer
    small_head, small_refs = split_skill(render_skill(procedure_unit(exhibit_body(1))))
    assert small_refs == []
    assert "2. If Sending a systemic IA confirmation letter" in small_head
    assert not any("(branches:" in line for line in small_head)


def test_skill_name_is_a_title_slug_with_a_unit_hash():
    """P40: the title folded to ASCII, lowercased, runs of other characters one hyphen,
    trimmed, cut to 51 characters with no trailing hyphen, then "-" and 12 hex of SHA-256 of
    the unit id; the unit type when the slug is empty."""
    base = procedure_unit(LINEAR)
    cases = [("IRM 21.4.1.3.1", "irm-21-4-1-3-1"),
             ("Café Déjà Vu — Ünïcode Rollout", "cafe-deja-vu-unicode-rollout"),
             ("  --Hosted Rollout + Rollback (Runtime/Gateway)--  ",
              "hosted-rollout-rollback-runtime-gateway"),
             ("———", "procedure"),
             ("a" * 50 + " bcd", "a" * 50),                # the cut leaves no trailing hyphen
             ("x" * 80, "x" * 51)]
    for title, slug in cases:
        unit = base.model_copy(update={"title": title})
        name = parse_skill(render_skill(unit))[0]["name"]
        assert name == f"{slug}-{hex12(base)}" and len(name) <= 64
        assert NAME.fullmatch(name)
    # one title in two units (IRM 21.4.1.5.9.4 and 5.19.1.5.3 are both "Deceased Taxpayers"):
    # two names, each the same on every render
    one = procedure_unit(LINEAR, "IRM 21.4.1.5.9.4").model_copy(
        update={"title": "Deceased Taxpayers"})
    two = procedure_unit(LINEAR, "IRM 5.19.1.5.3").model_copy(
        update={"title": "Deceased Taxpayers"})
    n1, n2 = (parse_skill(render_skill(u))[0]["name"] for u in (one, two))
    assert n1 != n2 and n1.startswith("deceased-taxpayers-") and n2.startswith(
        "deceased-taxpayers-")
    assert n1 == parse_skill(render_skill(one))[0]["name"]


def test_skill_description_is_when_to_use_and_is_capped():
    value = 'Use when: a refund "never arrived"\nor bounced — see #3 \\ done'
    unit = procedure_unit(body(*LINEAR.steps, when_to_use=model_field(value)))
    text = render_skill(unit)
    meta, n = parse_skill(text)
    assert meta["description"] == value and n == 3
    assert yaml_front_matter(text) == meta
    long = procedure_unit(body(*LINEAR.steps, when_to_use=model_field("w" * 1500)))
    described = parse_skill(render_skill(long))[0]["description"]
    assert len(described) == 1024 and described == "w" * 1023 + "…"
    odd = procedure_unit(body(*LINEAR.steps, when_to_use=model_field("a b\x85c\x01")))
    odd_text = render_skill(odd)
    assert parse_skill(odd_text)[0]["description"] == "a b\x85c\x01"
    assert yaml_front_matter(odd_text)["description"] == "a b\x85c\x01"


def test_long_tables_go_to_references_and_body_stays_under_500_lines():
    big = rows_body(200)                          # 200 conditions, 403 steps
    assert REFERENCES_FROM == 8 and SKILL_BODY_MAX_LINES == 500
    unit = procedure_unit(big)
    text = render_skill(unit)
    head, refs = split_skill(text)
    assert len(head) < SKILL_BODY_MAX_LINES
    assert not any(line.lstrip().startswith(("If ", "Otherwise ", "Go to ")) for line in head)
    assert "Source: IRM 21.4.1.3.1" in head
    assert refs[0] == "## references/"
    if_lines = [line for line in refs if line.startswith("   If ")]
    assert len(if_lines) == 200 and if_lines[0] == "   If case 1 holds then step 3"
    assert sum(line.startswith("   Otherwise step ") for line in refs) == 200
    # every action but the last jumps past the rest of the table
    assert sum(line == "   Go to step 402" for line in refs) == 199
    assert "Step 2:" in refs and "   Otherwise step 404" not in refs
    assert "   Otherwise step 402" in refs        # the last row's otherwise: after the table
    assert parse_skill(text) == ({"name": "irm-21-4-1-3-1-" + hex12(unit),
                                  "description": "IRM 21.4.1.3.1"}, len(big.steps))
    # the same table inline would not fit the body
    assert len(big.steps) + 400 > SKILL_BODY_MAX_LINES
    # up to REFERENCES_FROM conditions the guards stay inline
    for n, referenced in [(REFERENCES_FROM, False), (REFERENCES_FROM + 1, True)]:
        head, refs = split_skill(render_skill(procedure_unit(rows_body(n))))
        assert bool(refs) is referenced
        assert any(line.startswith("   If case 1 holds") for line in head) is not referenced


def test_parse_skill_refuses_malformed_text():
    good = render_skill(procedure_unit(BRANCHING))
    meta, n = parse_skill(good)
    assert n == 4
    name = meta["name"]
    for text in ["", good.replace("---\n", "", 1), good.replace("\n---\n", "\n", 1),
                 good.replace("2. ", "3. ", 1), good.replace('description: "', "description: ", 1),
                 good.replace("name: ", "name: !!", 1),
                 good.replace("name: ", "name: x\nname: ", 1),
                 good.replace("name: ", "name ", 1),
                 good.replace(f"name: {name}", "name: irm-21-4-1-3-1", 1),     # no unit hash
                 good.replace(f"name: {name}", f"name: {'a' * 52}-{name[-12:]}", 1),  # over 64
                 good.replace(f"name: {name}", f"name: Irm-{name}", 1),
                 good.replace(f"name: {name}", f"name: irm--{name}", 1),
                 good.replace(f"name: {name}", f'name: "{name}"', 1),
                 good.replace("description: ", 'license: "x"\ndescription: ', 1),
                 good.replace(f"name: {name}\n", "", 1),
                 good.replace('description: "IRM 21.4.1.3.1"',
                              f'description: "{"d" * 1025}"', 1)]:
        with pytest.raises(ValueError):
            parse_skill(text)


def test_renderers_are_byte_stable():
    for b in [LINEAR, BRANCHING, CYCLIC, rows_body(12), IRM_SHAPE, AWKWARD, exhibit_body(5)]:
        again = ProcedureBody.model_validate(b.model_dump(mode="json"))
        assert render_mermaid(b) == render_mermaid(b) == render_mermaid(again)
        assert render_skill(procedure_unit(b)) == render_skill(procedure_unit(again))
        assert render_mermaid(b).encode() == render_mermaid(again).encode()
