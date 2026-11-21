"""SKILL.md and Mermaid renderers and their subset parsers (Phase 4 spec §9.2, criterion U3,
P39; preflight notes N19, C2). Pure functions on the IR and fixture stores under `tmp_path`:
no Node, no Mermaid CLI, no model and nothing under `.cache/`."""

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
         text="| Yes | the RTN is on file", condition="Yes; the RTN is on file"),
    step("s5", "subprocedure", [("s6", None)], text="Then refer to IRM 21.4.1.3.2.",
         subprocedure_ref="IRM 21.4.1.3.2"),
    step("s6", nxt=[("s7", None)], text="Reminder: document the action\non the account."),
    step("s7", "handoff", [("s8", None)], text="Refer the case to the Refund Unit."),
    step("s8", "end", text=""))
# guards that need escaping: quotes, pipes, hashes, entity look-alikes, newlines, edge spaces
AWKWARD = body(
    step("s1", "condition", [("s2", 'MISC: "AM" or "AMADJ"'), ("s3", "a | b #1 #quot; #124;"),
                             ("s4", "line one\nline two\ttab"), ("s5", " padded ")],
         text='Check "MISC" | codes #1'),
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
    assert ir_graph(renamed) == (frozenset({"s1", "s2", "s3"}),
                                 frozenset({("s1", "s2", "If so"), ("s1", "s3", "otherwise"),
                                            ("s2", "s1", None)}))
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
    assert edges == frozenset({
        ("s1", "s2", None), ("s2", "s3", "If the check was lost"), ("s2", "s4", "otherwise"),
        ("s3", "s6", None), ("s4", "s5", "Yes; the RTN is on file"), ("s4", "s6", "otherwise"),
        ("s5", "s6", None), ("s6", "s7", None), ("s7", "s8", None)})
    m = render_mermaid(IRM_SHAPE)
    assert parse_mermaid(m) == (nodes, edges)
    assert "IRM 21.4.1.3.2" not in {t for _, t, _ in edges}
    assert m.splitlines()[:9] == [
        "flowchart TD",
        '    s1["Research with Command Code IMFOLT."]',
        '    s2{"If the check was lost"}',
        '    s3["Then input TC 971."]',
        '    s4{"| Yes | the RTN is on file"}',
        '    s5["Then refer to IRM 21.4.1.3.2."]',
        '    s6["Reminder: document the action on the account."]',
        '    s7["Refer the case to the Refund Unit."]',
        '    s8["end"]']
    assert m.splitlines()[9:] == [
        "    s1 --> s2", "    s2 -->|If the check was lost| s3", "    s2 -->|otherwise| s4",
        "    s3 --> s6", "    s4 -->|Yes; the RTN is on file| s5", "    s4 -->|otherwise| s6",
        "    s5 --> s6", "    s6 --> s7", "    s7 --> s8"]
    assert m.endswith("s7 --> s8\n")


def test_guards_are_escaped_losslessly():
    m = render_mermaid(AWKWARD)
    edge_lines = [line for line in m.splitlines() if "-->" in line]
    assert edge_lines[0] == "    s1 -->|MISC: #quot;AM#quot; or #quot;AMADJ#quot;| s2"
    assert edge_lines[1] == "    s1 -->|a #124; b #35;1 #35;quot; #35;124;| s3"
    assert edge_lines[2] == "    s1 -->|line one#10;line two#9;tab| s4"
    assert edge_lines[3] == "    s1 -->|#32;padded#32;| s5"
    guards = {g for _, _, g in parse_mermaid(m)[1]}
    assert {'MISC: "AM" or "AMADJ"', "a | b #1 #quot; #124;", "line one\nline two\ttab",
            " padded "} <= guards


def test_an_empty_guard_cannot_be_rendered():
    with pytest.raises(ValueError, match="empty guard"):
        render_mermaid(body(step("s1", "condition", [("s2", "")]), step("s2", "end", text="")))


def test_the_round_trip_notices_a_lost_or_changed_edge():
    m = render_mermaid(IRM_SHAPE)
    graph = ir_graph(IRM_SHAPE)
    assert parse_mermaid(m.replace("    s5 --> s6\n", "")) != graph
    assert parse_mermaid(m.replace("|otherwise| s6", "|Otherwise| s6")) != graph
    assert parse_mermaid(m.replace("    s6 --> s7", "    s6 --> s8")) != graph


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
        good.replace("|otherwise|", '|other"wise|'),                  # a raw quote
        good.replace("|otherwise|", "|other#wise|"),                  # a stray hash
        good.replace("|otherwise|", "|other#amp;wise|"),              # an entity not emitted
        good.replace("|otherwise|", "||"),
        good.replace("Issue a paper check.", "z" * 81),                # a label over 80
        good.replace("    s1", "  s1", 1),
        good.replace("\n    s2 --> s4", "\n\n    s2 --> s4"),           # a blank line
        good.replace("s2 -->", "S2 -->"),
        good + "%% comment\n",
        good.replace('    s4["end"]\n', "") + '    s4["end"]\n',         # a node after edges
        good.rstrip("\n"),                                             # no final newline
        "",
    ]
    for text in bad:
        with pytest.raises(ValueError):
            parse_mermaid(text)


# -- SKILL.md --------------------------------------------------------------------------------

def test_skill_front_matter_parses_and_step_count_matches(units_store):
    units = procedure_units_of(units_store)
    assert {u.canonical_ref.split(":")[0] for u in units} == {"IRM 21.4.1.3.1",
                                                               "IRM 21.4.1.3.2", "bench"}
    types = set()
    for u in units:
        meta, n = parse_skill(render_skill(u))
        assert set(meta) == {"name", "description"} and len(meta["description"]) <= 1024
        assert n == len(u.body["steps"])
        assert meta["description"] == u.title  # when_to_use is not extracted yet
        b = ProcedureBody.model_validate(u.body)
        assert parse_mermaid(render_mermaid(b)) == ir_graph(b)
        types |= {s.type for s in b.steps}
    assert types == {"tool_call", "condition", "instruction", "subprocedure", "handoff", "end"}


def test_skill_renders_numbered_steps_guards_tools_references_and_the_source():
    text = render_skill(procedure_unit(IRM_SHAPE))
    assert text == (
        "---\n"
        "name: irm-21-4-1-3-1\n"
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
        "4. | Yes | the RTN is on file\n"
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
    assert parse_skill(text) == ({"name": "irm-21-4-1-3-1", "description": "IRM 21.4.1.3.1"}, 8)


def test_skill_guard_lines_drop_a_leading_if_and_trailing_punctuation():
    b = body(step("s1", "condition", [("s2", "IF  the RTN\nmatches."), ("s3", "otherwise")]),
             step("s2", nxt=[("s3", None)]), step("s3", "end", text=""))
    head, _ = split_skill(render_skill(procedure_unit(b)))
    assert head[3:6] == ["1. x", "   If the RTN matches then step 2", "   Otherwise step 3"]


def test_skill_name_is_the_canonical_ref_lower_cased_with_dashes():
    for ref, name in [("IRM 21.4.1.3.1", "irm-21-4-1-3-1"),
                      ("IRM Exhibit 5.19.1-6", "irm-exhibit-5-19-1-6"),
                      ("bench:" + "ab" * 32, "bench-" + "ab" * 32)]:
        assert parse_skill(render_skill(procedure_unit(LINEAR, ref)))[0]["name"] == name


def test_skill_description_is_when_to_use_and_is_capped():
    yaml = pytest.importorskip("yaml")
    value = 'Use when: a refund "never arrived"\nor bounced — see #3 \\ done'
    unit = procedure_unit(body(*LINEAR.steps, when_to_use=model_field(value)))
    text = render_skill(unit)
    meta, n = parse_skill(text)
    assert meta["description"] == value and n == 3
    front = text.split("---\n")[1]
    assert yaml.safe_load(front) == meta
    long = procedure_unit(body(*LINEAR.steps, when_to_use=model_field("w" * 1500)))
    described = parse_skill(render_skill(long))[0]["description"]
    assert len(described) == 1024 and described == "w" * 1023 + "…"
    odd = procedure_unit(body(*LINEAR.steps, when_to_use=model_field("a\u2028b\x85c\x01")))
    odd_text = render_skill(odd)
    assert parse_skill(odd_text)[0]["description"] == "a\u2028b\x85c\x01"
    assert yaml.safe_load(odd_text.split("---\n")[1])["description"] == "a\u2028b\x85c\x01"


def test_long_tables_go_to_references_and_body_stays_under_500_lines():
    big = rows_body(200)                          # 200 conditions, 403 steps
    assert REFERENCES_FROM == 8 and SKILL_BODY_MAX_LINES == 500
    text = render_skill(procedure_unit(big))
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
    assert parse_skill(text) == ({"name": "irm-21-4-1-3-1", "description": "IRM 21.4.1.3.1"},
                                 len(big.steps))
    # the same table inline would not fit the body
    assert len(big.steps) + 400 > SKILL_BODY_MAX_LINES
    # up to REFERENCES_FROM conditions the guards stay inline
    for n, referenced in [(REFERENCES_FROM, False), (REFERENCES_FROM + 1, True)]:
        head, refs = split_skill(render_skill(procedure_unit(rows_body(n))))
        assert bool(refs) is referenced
        assert any(line.startswith("   If case 1 holds") for line in head) is not referenced


def test_parse_skill_refuses_malformed_text():
    good = render_skill(procedure_unit(BRANCHING))
    assert parse_skill(good)[1] == 4
    for text in ["", good.replace("---\n", "", 1), good.replace("\n---\n", "\n", 1),
                 good.replace("2. ", "3. ", 1), good.replace('description: "', "description: ", 1),
                 good.replace("name: ", "name: !!", 1),
                 good.replace("name: irm", "name: x\nname: irm", 1),
                 good.replace("name: ", "name ", 1)]:
        with pytest.raises(ValueError):
            parse_skill(text)


def test_renderers_are_byte_stable():
    for b in [LINEAR, BRANCHING, CYCLIC, rows_body(12), IRM_SHAPE, AWKWARD]:
        again = ProcedureBody.model_validate(b.model_dump(mode="json"))
        assert render_mermaid(b) == render_mermaid(b) == render_mermaid(again)
        assert render_skill(procedure_unit(b)) == render_skill(procedure_unit(again))
        assert render_mermaid(b).encode() == render_mermaid(again).encode()
