"""The procedure IR, IRM segmentation and IRM and bench procedure skeletons (Phase 4 spec
§4.2, §5.3, §6.1, §9.1, P10, P31; preflight rulings C1, C7). Fixture stores under
`tmp_path`; nothing reads `data/` or `.cache/`, and nothing calls a model."""

import hashlib
from typing import get_args

import pytest

from adr_eval.golden.verify import normalize_ws
from adr_store.units.contracts import load_unit_contracts, validate_unit
from adr_store.units.procedures import (
    BENCH_CAP,
    MIN_STEPS,
    SEED4,
    STEP_TYPES,
    WHEN_TO_USE_MAX,
    Edge,
    IrmSection,
    ProcedureBody,
    Step,
    _find,
    bench_candidates,
    bench_skeleton,
    branch_paths,
    irm_sections,
    irm_skeleton,
    is_procedure_like,
    not_extracted,
    procedure_units,
    validate_ir,
)
from tests.store import units_fixtures as uf
from tests.store.tables_fixtures import _doc
from tests.store.units_fixtures import DOC_FAQ, DOC_IRM, DOC_KCS, DOC_RUNBOOK, overlay_of

units_store = uf.units_store


# -- helpers ---------------------------------------------------------------------------------

def proc_section(store) -> IrmSection:
    """§ 21.4.1.3.1 Missing Refund Research: four paragraphs, a two-row If/Then table."""
    return irm_sections(store, DOC_IRM)[0][1]


def skeleton_steps(store) -> list[Step]:
    return irm_skeleton(proc_section(store), store.text(DOC_IRM)).steps


def step(id_, type_="instruction", nxt=(), text="x") -> Step:
    """A step whose `nxt` holds (to, guard) pairs."""
    return Step(id=id_, type=type_, text=text, span=None,
                next=[Edge(to=t, guard=g) for t, g in nxt])


def body(*steps: Step) -> ProcedureBody:
    return ProcedureBody(when_to_use=not_extracted(), not_for=not_extracted(),
                         trigger_examples=not_extracted(), problem_abstractions=not_extracted(),
                         steps=list(steps), source_kind="authored")


def edges_of(path: list[str]) -> list[tuple[str, str]]:
    return list(zip(path, path[1:], strict=False))


def irm_html(sections: list[tuple[str, str, str]]) -> bytes:
    """An IRM chapter page with the fixture's markup: one `div.section` per (number, title,
    inner HTML of its ordered list)."""
    parts = ['<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
             "<title>21.4.1 Refund Research | Internal Revenue Service</title></head><body>"
             '<div class="col-md-8"><div class="section" id="id1">'
             '<h2 class="title">21.4.1 Refund Research</h2><p>September 02, 2026</p>']
    for i, (number, title, items) in enumerate(sections):
        parts.append(
            f'<div class="section" id="s{i}"><div class="sectioninfo"><strong>{number} '
            f'(10-01-2026)</strong></div><div class="titlepage"><div><div><h3 class="title">'
            f'{title}</h3></div></div></div>{items}</div>')
    parts.append("</div></div></body></html>")
    return "".join(parts).encode()


def ol(*items: str, before: str = "") -> str:
    lis = "".join(f'<li class="listitem"><p>{t}</p></li>' for t in items)
    return f'{before}<div class="orderedlist"><ol class="orderedlist" type="1">{lis}</ol></div>'


def irm_store(tmp_path, raw: bytes):
    doc = _doc(raw, "html", uf.IRM_VERSION, uf.IRM_URI)
    return uf.make_units_store(tmp_path / "irm", docs=[doc]), doc[0].doc_id


def bench_md(title: str, body_md: str, source: str = "confluence") -> bytes:
    return f"# {title}\n\nSource: {source}\n\n{body_md}\n".encode()


def bench_store(tmp_path, raws: list[bytes]):
    docs = [_doc(r, "md", uf.BENCH_CONFIG["revision"],
                 f"{uf.BENCH_CONFIG['documents']['url']}#row={i}&doc_id=dsid_t{i}")
            for i, r in enumerate(raws)]
    return uf.make_units_store(tmp_path / "bench", docs=docs), [d.doc_id for d, _ in docs]


STEPS6 = "\n".join(f"{i}. Do step {i} of the drill." for i in range(1, 7))


# -- IRM segmentation ------------------------------------------------------------------------

def test_irm_sections_locate_by_first_own_line_and_merge_unlocated(units_store):
    """§ 21.4.1.3.3 is unlocated because the canonical text drops it whole (trafilatura's
    `favor_precision` trims the trailing block), so it is reported and named in the preceding
    section's `merged`; but none of its text survives, so this fixture does not exercise
    merging text into the preceding section (`test_an_unlocated_section_s_text_is_merged_
    into_the_preceding_one` does). Unlike the real IRM text, this canonical text has no table
    of contents."""
    text = units_store.text(DOC_IRM)
    secs, unlocated = irm_sections(units_store, DOC_IRM)
    assert [s.number for s in secs] == ["21.4.1.3", "21.4.1.3.1", "21.4.1.3.2"]
    assert unlocated == ["21.4.1.3.3"] and secs[-1].merged == ("21.4.1.3.3",)
    assert "Refund Hold Codes" not in text and "refund hold code" not in text
    assert [s.title for s in secs] == ["Refund Inquiry Research", "Missing Refund Research",
                                       "Direct Deposit Rejects"]
    assert [s.merged for s in secs[:2]] == [(), ()]
    starts = [text.index("This section gives the procedures"),
              text.index("Research the account with Command Code IMFOLT"),
              text.index("Research the direct deposit reject")]
    assert [s.start for s in secs] == starts
    # a section runs to the next located section (trailing whitespace off), the last to the end
    assert [s.end for s in secs] == [text.rindex("|", 0, starts[1]) + 1,
                                     text.rindex(".", 0, starts[2]) + 1, len(text.rstrip())]
    assert all(s.doc_id == DOC_IRM for s in secs)
    assert "Refund Hold Codes" in secs[-1].html and "Refund Hold Codes" not in secs[1].html
    # the chapter's own div.section has no number and is not a section
    assert "Manual Transmittal" not in "".join(s.html for s in secs)


def test_an_unlocated_section_s_text_is_merged_into_the_preceding_one(tmp_path):
    """§ 1.1.2's first own line sits in an `<aside>`, which the HTML extractor drops, so the
    line cannot be located; its other paragraphs survive inside § 1.1.1's span, and § 1.1.1's
    skeleton holds them."""
    raw = irm_html([
        ("1.1.1", "First", ol("Open the case with Command Code ACTON.",
                              "Review the account history.")),
        ("1.1.2", "Second", ol("Send Letter 105C to the taxpayer.", "Close the case.",
                               before="<aside>A heading that the extractor drops.</aside>")),
        ("1.1.3", "Third", ol("Check the freeze codes.", "Release the refund.")),
        ("1.1.4", "Fourth", ol("Close out.")),
    ])
    store, doc = irm_store(tmp_path, raw)
    text = store.text(doc)
    assert "A heading that the extractor drops." not in text
    assert "Send Letter 105C" in text
    secs, unlocated = irm_sections(store, doc)
    by = {s.number: s for s in secs}
    assert unlocated == ["1.1.2"] and by["1.1.1"].merged == ("1.1.2",)
    assert by["1.1.1"].end <= text.index("Check the freeze codes.") == by["1.1.3"].start
    assert "Send Letter 105C" in text[by["1.1.1"].start:by["1.1.1"].end]
    texts = [s.text for s in irm_skeleton(by["1.1.1"], text).steps]
    assert texts == ["Open the case with Command Code ACTON.", "Review the account history.",
                     "Send Letter 105C to the taxpayer.", "Close the case.", ""]


def test_exhibits_are_sections(tmp_path):
    """An exhibit's `div.section` ("Exhibit 1.4-1") is a section like a numbered one."""
    table = ('<div class="informaltable"><table><thead><tr><th>If</th><th>Then</th></tr></thead>'
             "<tbody><tr><td>If the code is 60</td><td>Then suspend the case.</td></tr>"
             "</tbody></table></div>")
    raw = irm_html([
        ("1.4.1", "Codes", ol("Read the status code.", "Note it in the history.")),
        ("Exhibit 1.4-1", "Status Code Actions", '<div class="orderedlist"><ol '
         'class="orderedlist" type="1"><li class="listitem"><p>Use this chart:</p>'
         f'{table}</li><li class="listitem"><p>File the chart.</p></li></ol></div>'),
        ("1.4.2", "After", ol("Close out the file.", "Archive the box.")),
    ])
    store, doc = irm_store(tmp_path, raw)
    secs, unlocated = irm_sections(store, doc)
    assert [s.number for s in secs] == ["1.4.1", "Exhibit 1.4-1", "1.4.2"] and unlocated == []
    units, _ = procedure_units(store, "gov", overlay_of(store))
    assert [(u.canonical_ref, u.title, u.heading_path) for u in units] == [
        ("IRM Exhibit 1.4-1", "Status Code Actions",
         ["IRM 21.4.1 Refund Research", "IRM Exhibit 1.4-1 Status Code Actions"])]


def test_lines_are_found_across_spacing_and_glued_cells():
    """Whitespace is ignored; a letter end has no letter beside it and a digit end no digit,
    so a short cell is not read inside a word but is found where the extractor glued two
    table cells."""
    text = "Detroit, MI 48226-2414Fees TC 360 IRS\nNot applicable\nNo\nIRM 1.4.16 , Accounts"
    assert _find(text, ("Fees",), 0, len(text)) == (22, 26)
    assert _find(text, ("No",), 0, len(text)) == (text.index("\nNo\n") + 1,
                                                    text.index("\nNo\n") + 3)
    assert _find(text, ("IRM 1.4.16, Accounts",), 0, len(text)) == (
        text.index("IRM 1.4.16"), len(text))
    at = text.index("48226")
    assert _find(text, ("48226",), 0, len(text)) == (at, at + 5)
    assert _find(text, ("4822",), 0, len(text)) is None             # a digit after it
    assert _find(text, ("8226-2414",), 0, len(text)) is None        # a digit before it
    assert _find(text, ("applicable",), 0, len(text)) is not None
    assert _find(text, ("pplicable",), 0, len(text)) is None        # a letter before it
    assert _find(text, ("If", "Then"), 0, 9) is None
    assert _find("| If | Then |", ("If", "Then"), 0, 13) == (2, 11)


def test_is_procedure_like_needs_an_if_then_table(units_store):
    secs, _ = irm_sections(units_store, DOC_IRM)
    assert [is_procedure_like(s) for s in secs] == [False, True, True]


# -- IRM skeletons -----------------------------------------------------------------------------

def test_irm_skeleton_of_the_missing_refund_section(units_store):
    """Paragraphs in order; each If/Then row a condition step (the If cell) with the Then
    action behind its guard and an "otherwise" edge to the next row, the last one's to the
    next paragraph; codes, IRM references and referrals type the steps; an end step."""
    b = irm_skeleton(proc_section(units_store), units_store.text(DOC_IRM))
    got = [(s.id, s.type, s.tool, s.subprocedure_ref, [(e.to, e.guard) for e in s.next])
           for s in b.steps]
    g1 = "If the taxpayer received a paper check that was lost or stolen"
    g2 = "If the taxpayer requested a direct deposit and TC 846 shows the RTN on file"
    assert got == [
        ("s1", "tool_call", "IMFOLT", None, [("s2", None)]),
        ("s2", "tool_call", "REQ77", None, [("s3", None)]),
        ("s3", "instruction", None, None, [("s4", None)]),
        ("s4", "condition", None, None, [("s5", g1), ("s6", "otherwise")]),
        ("s5", "tool_call", "TC 971", None, [("s8", None)]),
        ("s6", "condition", None, None, [("s7", g2), ("s8", "otherwise")]),
        # the reference is not a tool and gets no edge (ruling M1)
        ("s7", "subprocedure", None, "IRM 21.4.1.3.2", [("s8", None)]),
        ("s8", "handoff", None, None, [("s9", None)]),
        ("s9", "end", None, None, []),
    ]
    assert [s.text for s in b.steps] == [
        "Research the account with Command Code IMFOLT to find the refund transaction.",
        "Request the refund trace with Command Code REQ77 when no TC 846 has posted after 21 "
        "days.",
        "Follow the chart below to decide the next action:",
        g1,
        "Then start a refund trace with Form 3911 and input TC 971 action code 001.",
        g2,
        "Then advise the taxpayer to contact the bank, and refer to IRM 21.4.1.3.2 if the "
        "bank rejected the deposit.",
        "If the refund is still missing after six weeks, refer the case to the Refund Inquiry "
        "Unit.",
        ""]
    assert [s.condition for s in b.steps if s.type == "condition"] == [g1, g2]
    assert all(s.risk == "unknown" and not s.requires_approval for s in b.steps)
    assert b.source_kind == "irm" and b.ambiguity_flags == [] and b.tests == branch_paths(b)
    for f in ("when_to_use", "not_for", "trigger_examples", "problem_abstractions"):
        assert getattr(b, f) == {"value": None, "quotes": [], "status": None,
                                 "null_reason": "not_extracted"}


def test_if_then_rows_become_condition_steps_with_otherwise(units_store):
    body_ = irm_skeleton(proc_section(units_store), units_store.text(DOC_IRM))
    cond = [s for s in body_.steps if s.type == "condition"]
    assert cond[0].next[0].guard.startswith("If the taxpayer")
    assert cond[0].next[-1].guard == "otherwise"
    by = {s.id: s for s in body_.steps}
    assert by[cond[0].next[0].to].text.startswith("Then start a refund trace")
    assert cond[0].next[-1].to == cond[1].id                   # the next row
    assert by[cond[-1].next[-1].to].text.startswith("If the refund is still missing")


def test_command_codes_are_tool_calls(units_store):
    steps = skeleton_steps(units_store)
    assert any(s.type == "tool_call" and s.tool == "REQ77" for s in steps)
    # the first code names the tool: Command Code REQ77 comes before TC 846 in s2
    assert [s.tool for s in steps if s.type == "tool_call"] == ["IMFOLT", "REQ77", "TC 971"]


def test_every_procedure_is_valid_and_spans_reslice(units_store):
    units, _ = procedure_units(units_store, "gov", overlay_of(units_store))
    for u in units:
        assert validate_ir(ProcedureBody(**u.body)) == []
        for s in u.body["steps"]:
            if s["span"] is not None:
                a, b = s["span"]
                assert normalize_ws(units_store.text(u.doc_id)[a:b]) == normalize_ws(s["text"])
    assert [u.canonical_ref for u in units] == ["IRM 21.4.1.3.1", "IRM 21.4.1.3.2"]
    contract = load_unit_contracts()["procedure"]
    text = units_store.text(DOC_IRM)
    secs = {f"IRM {s.number}": s for s in irm_sections(units_store, DOC_IRM)[0]}
    for u in units:
        assert validate_unit(contract, u) == []
        sec = secs[u.canonical_ref]
        assert u.type == "procedure" and u.doc_id == DOC_IRM and u.title == sec.title
        assert [(r.start, r.end) for r in u.source_refs] == [(sec.start, sec.end)]
        assert u.unit_id.startswith(f"procedure/{u.canonical_ref}/")
        assert u.heading_path == ["IRM 21.4.1 Refund Research",
                                  "IRM 21.4.1.3 Refund Inquiry Research",
                                  f"{u.canonical_ref} {sec.title}"]
        assert u.governance.authority_tier == 1
        body_ = ProcedureBody(**u.body)
        assert body_.tests == branch_paths(body_) and body_.source_kind == "irm"
        assert all(text[a:b] == s["text"] for s in u.body["steps"]
                   if s["span"] is not None for a, b in [s["span"]])


def test_a_two_step_section_is_flagged_coarse(units_store):
    """§ 21.4.1.3 has two paragraphs and no If/Then table: two steps and the end."""
    secs, _ = irm_sections(units_store, DOC_IRM)
    b = irm_skeleton(secs[0], units_store.text(DOC_IRM))
    assert [s.type for s in b.steps] == ["instruction", "instruction", "end"]
    assert b.ambiguity_flags == ["coarse"] and MIN_STEPS == 3
    assert validate_ir(b) == []
    assert irm_skeleton(secs[2], units_store.text(DOC_IRM)).ambiguity_flags == []


def test_procedure_units_report(units_store):
    units, report = procedure_units(units_store, "gov", overlay_of(units_store))
    assert report == {
        "corpus": "gov", "documents": 1, "sections": 4, "located": 3,
        "unlocated": [{"doc_id": DOC_IRM, "number": "21.4.1.3.3", "merged_into": "21.4.1.3.2"}],
        "procedure_like": 2, "if_then_tables": 2, "candidates": 0, "drawn": 0,
        "procedures": 2, "coarse": 0,
        "steps": {"condition": 3, "end": 2, "handoff": 1, "instruction": 3,
                  "subprocedure": 1, "tool_call": 4},
        # the paragraphs of the merged § 21.4.1.3.3 are not in the text (see above)
        "dropped": [
            {"canonical_ref": "IRM 21.4.1.3.2", "doc_id": DOC_IRM, "kind": "paragraph",
             "reason": "not_in_text",
             "text": "Research the account with Command Code IMFOLT to find the refund "
                     "transaction."},
            {"canonical_ref": "IRM 21.4.1.3.2", "doc_id": DOC_IRM, "kind": "paragraph",
             "reason": "not_in_text",
             "text": ("Check the account for a refund hold code before you tell the taxpayer "
                      "when the refund will issue")[:80]}],
        "no_condition": [], "if_items": {"conditions": 0, "no_action": 0}, "rejected": []}
    again, report2 = procedure_units(units_store, "gov", overlay_of(units_store))
    assert again == units and report2 == report
    assert procedure_units(units_store, "research", None) == ([], {
        "corpus": "research", "documents": 0, "sections": 0, "located": 0, "unlocated": [],
        "procedure_like": 0, "if_then_tables": 0, "candidates": 0, "drawn": 0,
        "procedures": 0, "coarse": 0, "steps": {}, "dropped": [], "no_condition": [],
        "if_items": {"conditions": 0, "no_action": 0}, "rejected": []})


def test_an_unlocatable_row_is_dropped_and_reported(tmp_path):
    """A Then cell whose text is not in the canonical text (inside an `<aside>`) loses its
    row; the drop is reported, and the skeleton stays valid."""
    table = ('<div class="informaltable"><table><thead><tr><th>If</th><th>Then</th></tr>'
             "</thead><tbody><tr><td>If the notice is back</td><td>Then close the case.</td></tr>"
             "<tr><td>If the notice is lost</td><td><aside>Then resend it.</aside></td></tr>"
             "</tbody></table></div>")
    raw = irm_html([
        ("1.2.1", "Notices", '<div class="orderedlist"><ol class="orderedlist" type="1">'
         '<li class="listitem"><p>Check the notice status.</p></li><li class="listitem">'
         f"<p>Use the chart:</p>{table}</li></ol></div>"),
        ("1.2.2", "After", ol("Close out the file.", "Archive the file.")),
    ])
    store, doc = irm_store(tmp_path, raw)
    units, report = procedure_units(store, "gov", overlay_of(store))
    assert [u.canonical_ref for u in units] == ["IRM 1.2.1"]
    b = ProcedureBody(**units[0].body)
    assert [s.type for s in b.steps] == ["instruction", "instruction", "condition",
                                         "instruction", "end"]
    assert validate_ir(b) == [] and b.ambiguity_flags == []
    assert report["dropped"] == [{"canonical_ref": "IRM 1.2.1", "doc_id": doc, "kind": "row",
                                  "reason": "not_in_text", "text": "If the notice is lost"}]
    assert report["no_condition"] == []


def test_row_and_and_columns(tmp_path):
    """A "Row" column is no part of the guard and its number no part of the step before; an
    "And" column joins the guard, a cell's lines joined by spaces."""
    table = ('<div class="informaltable"><table><thead><tr><th>Row</th><th>If ...</th>'
             "<th>And ...</th><th>Then ...</th></tr></thead><tbody>"
             "<tr><td>1</td><td>The notice is back</td><td>it is signed</td>"
             "<td>Close the case.</td></tr>"
             "<tr><td>2</td><td>The notice is lost</td><td><ul><li>no copy exists</li>"
             "<li>the case is open</li></ul></td>"
             "<td>Resend it with Command Code NOTIC.</td></tr></tbody></table></div>")
    raw = irm_html([
        ("1.3.1", "Returns", '<div class="orderedlist"><ol class="orderedlist" type="1">'
         f'<li class="listitem"><p>Use the chart:</p>{table}</li>'
         '<li class="listitem"><p>Archive the file.</p></li></ol></div>'),
        ("1.3.2", "After", ol("Close out the file.", "Archive the box.")),
    ])
    store, doc = irm_store(tmp_path, raw)
    text = store.text(doc)
    sec = irm_sections(store, doc)[0][0]
    b = irm_skeleton(sec, text)
    assert [s.type for s in b.steps] == ["instruction", "condition", "instruction",
                                         "condition", "tool_call", "instruction", "end"]
    assert [s.condition for s in b.steps if s.type == "condition"] == [
        "The notice is back; it is signed",
        "The notice is lost; no copy exists the case is open"]
    assert b.steps[1].text.startswith("The notice is back")
    assert b.steps[2].text == "Close the case."                    # no "2" of the next row
    assert b.steps[4].tool == "NOTIC" and b.steps[4].text.startswith("Resend it")
    assert all(text[s.span[0]:s.span[1]] == s.text for s in b.steps[:-1])
    assert validate_ir(b) == []


def if_table(*rows: tuple[str, str]) -> str:
    """An If/Then table of (If cell, Then cell HTML) rows, headed "If..." and "Then..."."""
    body = "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in rows)
    return ('<div class="informaltable"><table><thead><tr><th>If...</th><th>Then...</th></tr>'
            f"</thead><tbody>{body}</tbody></table></div>")


def lis(*items: str) -> str:
    return ('<div class="orderedlist"><ol class="orderedlist" type="1">'
            + "".join(f'<li class="listitem">{i}</li>' for i in items) + "</ol></div>")


def section_skeleton(tmp_path, items: str):
    raw = irm_html([("1.5.1", "Detainees", items),
                    ("1.5.2", "After", ol("Close out the file.", "Archive the box."))])
    store, doc = irm_store(tmp_path, raw)
    units, report = procedure_units(store, "gov", overlay_of(store))
    text = store.text(doc)
    assert all(text[s["span"][0]:s["span"][1]] == s["text"]
               for u in units for s in u.body["steps"] if s["span"] is not None)
    return store, doc, text, units, report


def test_a_missing_then_cell_does_not_match_a_later_table(tmp_path):
    """The shape of IRM 5.19.1.5.12.2: the extractor drops table 1's Then cells (here an
    `<aside>`), and row 1's first Then line also opens a Then cell of table 2, after the next
    paragraph. That line may not be matched past the next anchor, so table 1's rows are
    dropped and the next paragraph and table 2 keep their own text."""
    t1 = if_table(("Telephone call and an open collection issue,",
                   "<aside><p>Input the HSTG indicator</p><p>Suspend the account for 60 days"
                   "</p></aside>"),
                  ("Telephone call and no open collection issues,",
                   "<aside><p>Suspend the account for 60 days pending the letter</p></aside>"))
    t2 = if_table(("Telephone call and there is an open collection issue,",
                   "<p>Input the HSTG indicator</p><p>Suspend the account for 90 days</p>"),
                  ("Telephone call and there are no open collection issues,",
                   "<p>Input the HSTG indicator</p><p>Close the case</p>"))
    items = lis("<p>Check the detainee list.</p>",
                f"<p>Use the table below to address wrongful detainee cases:</p>{t1}",
                f"<p>If the taxpayer was a former detainee, use the table below:</p>{t2}")
    store, doc, text, units, report = section_skeleton(tmp_path, items)
    assert "Suspend the account for 60 days" not in text           # dropped by the extractor
    steps = units[0].body["steps"]
    by = {s["id"]: s for s in steps}
    assert [s["type"] for s in steps] == ["instruction", "instruction", "instruction",
                                         "condition", "instruction", "condition",
                                         "instruction", "end"]
    assert steps[2]["text"] == "If the taxpayer was a former detainee, use the table below:"
    for c in (s for s in steps if s["type"] == "condition"):
        action = by[c["next"][0]["to"]]
        assert action["span"][0] > c["span"][0]
        assert "90 days" in action["text"] if "is an open" in c["text"] else (
            "Close the case" in action["text"])
    assert [(d["kind"], d["reason"], d["text"]) for d in report["dropped"]] == [
        ("row", "out_of_order", "Telephone call and an open collection issue,"),
        ("row", "not_in_text", "Telephone call and no open collection issues,")]


def test_a_missing_then_cell_does_not_take_the_next_row_s_action(tmp_path):
    """The shape of IRM 21.4.1.4: row 2's Then cell is dropped, and its first line also
    opens row 3's Then cell. Row 2 is dropped; row 3 keeps its condition and its action."""
    table = if_table(("No, and the time frame has not been met.", "Do not research."),
                     ("Yes, and the time frame has been met.",
                      "<aside><p>Authenticate the taxpayer.</p></aside>"),
                     ("Yes, but the application cannot help.",
                      "<p>Authenticate the taxpayer. Then check the shared secrets.</p>"))
    items = lis("<p>Ask the taxpayer whether they used the automated tools.</p>",
                f"<p>Use the table:</p>{table}", "<p>Close the call.</p>")
    store, doc, text, units, report = section_skeleton(tmp_path, items)
    steps = units[0].body["steps"]
    conds = [s for s in steps if s["type"] == "condition"]
    by = {s["id"]: s for s in steps}
    assert [c["condition"] for c in conds] == ["No, and the time frame has not been met.",
                                               "Yes, but the application cannot help."]
    assert by[conds[1]["next"][0]["to"]]["text"] == (
        "Authenticate the taxpayer. Then check the shared secrets.")
    assert [(d["kind"], d["reason"], d["text"]) for d in report["dropped"]] == [
        ("row", "out_of_order", "Yes, and the time frame has been met.")]


def test_a_later_anchor_s_text_inside_an_earlier_step_unseats_nothing(tmp_path):
    """The shape of IRM 5.19.1.6.4.14: row 2's Then cell opens with "For NSIAs or PPIAs:",
    which row 1's Then cell also holds. Bounding row 2's condition by the next anchor's first
    match would drop it; placing the most anchors keeps every row."""
    table = if_table(("The customer can fax the request,",
                      "<p>Have the customer fax the form.</p><p>For NSIAs or PPIAs: send the "
                      "letter.</p>"),
                     ("The customer cannot fax the request,",
                      "<p>For NSIAs or PPIAs:</p><p>mail the form.</p>"))
    items = lis("<p>Offer a payroll deduction.</p>", f"<p>Use the table:</p>{table}",
                "<p>Advise the taxpayer.</p>")
    *_, units, report = section_skeleton(tmp_path, items)
    steps = units[0].body["steps"]
    assert [s["condition"] for s in steps if s["type"] == "condition"] == [
        "The customer can fax the request,", "The customer cannot fax the request,"]
    assert steps[3]["text"].startswith("Have the customer fax the form.")
    assert steps[5]["text"].startswith("For NSIAs or PPIAs:") and "mail" in steps[5]["text"]
    assert report["dropped"] == []


def test_text_after_a_table_is_its_own_unconditional_step(tmp_path):
    """The shape of IRM 5.19.1.3.2.4: a Reminder note after the paragraph's table is a step
    of its own, entered from every exit of the table (each action and the last
    "otherwise"), not part of the last row's action; the note's label, which the extractor
    drops, is no anchor."""
    table = if_table(("The case is assigned to a specific RO,", "Advise the taxpayer."),
                     ("The case is assigned to a group,", "Transfer the call to the group."))
    items = lis(f"<p>Refer to the following table to determine the appropriate action:</p>"
                f'{table}<div class="note"><h3 class="title">Reminder:</h3><p>Inform the '
                "taxpayer it is in their best interest to make payments.</p></div><p/>",
                "<p>If any correspondence is received, forward it to the RO.</p>")
    store, doc, text, units, report = section_skeleton(tmp_path, items)
    assert "Reminder:" not in text
    steps = units[0].body["steps"]
    got = [(s["id"], s["type"], [(e["to"], e["guard"]) for e in s["next"]]) for s in steps]
    assert got == [
        ("s1", "instruction", [("s2", None)]),
        ("s2", "condition", [("s3", "The case is assigned to a specific RO,"),
                             ("s4", "otherwise")]),
        ("s3", "instruction", [("s6", None)]),
        ("s4", "condition", [("s5", "The case is assigned to a group,"), ("s6", "otherwise")]),
        ("s5", "instruction", [("s6", None)]),
        ("s6", "instruction", [("s7", None)]),
        ("s7", "instruction", [("s8", None)]),
        ("s8", "end", [])]
    assert steps[4]["text"] == "Transfer the call to the group."
    assert steps[5]["text"] == ("Inform the taxpayer it is in their best interest to make "
                                "payments.")
    assert report["dropped"] == []


def test_text_between_two_tables_of_a_paragraph_is_a_step(tmp_path):
    t1 = if_table(("The account is open,", "Hold it."))
    t2 = if_table(("The letter is back,", "File it."))
    items = lis(f"<p>Use table 1:</p>{t1}<p>Then use table 2:</p>{t2}", "<p>Close out.</p>")
    *_, units, report = section_skeleton(tmp_path, items)
    steps = units[0].body["steps"]
    assert [(s["type"], s["text"]) for s in steps] == [
        ("instruction", "Use table 1:"), ("condition", "The account is open,"),
        ("instruction", "Hold it."), ("instruction", "Then use table 2:"),
        ("condition", "The letter is back,"), ("instruction", "File it."),
        ("instruction", "Close out."), ("end", "")]


def test_a_procedure_whose_rows_are_all_dropped_is_listed(tmp_path):
    """The shape of IRM 5.19.1.5.12.1: both Then cells are missing from the text."""
    table = if_table(("The account has an open issue,", "<aside>Suspend it.</aside>"),
                     ("The account has no open issue,", "<aside>Close it.</aside>"))
    items = lis("<p>Check the account.</p>", f"<p>Use the table below:</p>{table}",
                "<p>Record the action.</p>")
    *_, units, report = section_skeleton(tmp_path, items)
    assert [s["type"] for s in units[0].body["steps"]] == ["instruction"] * 3 + ["end"]
    assert report["no_condition"] == [{"canonical_ref": "IRM 1.5.1",
                                       "doc_id": units[0].doc_id,
                                       "reason": "all 2 If/Then rows dropped (not_in_text 2)"}]


def test_cc_command_codes_are_tool_calls(tmp_path):
    """Ruling I4: "CC ENMOD" names a command code as "Command Code ENMOD" does; "cc 088"
    (a closing code) and "CC ADD" (too short) do not."""
    items = lis("<p>Research the module with CC TXMOD and CC ENMOD.</p>",
                "<p>Input TC 290 with cc 088 and CC ADD fields.</p>",
                "<p>Use Command Code (CC) ERINV to find the return.</p>",
                "<p>Check the closing code with cc 088 only.</p>",
                f"<p>Use the chart:</p>{if_table(('The code is 60,', 'Use CC STAUP.'))}")
    *_, units, _ = section_skeleton(tmp_path, items)
    got = [(s["type"], s["tool"]) for s in units[0].body["steps"]]
    assert got == [("tool_call", "TXMOD"), ("tool_call", "TC 290"), ("tool_call", "ERINV"),
                   ("instruction", None), ("instruction", None), ("condition", None),
                   ("tool_call", "STAUP"), ("end", None)]


# -- validation and branch paths --------------------------------------------------------------

two_starts = body(step("s1", nxt=[("s3", None)]), step("s2", nxt=[("s3", None)]),
                  step("s3", "end"))
unreachable = body(step("s1", nxt=[("s2", None)]), step("s2", nxt=[("s3", None)]),
                   step("s3", "end"), step("s4", nxt=[("s4", None)]))
dangling = body(step("s1", nxt=[("s2", None)]), step("s2", nxt=[("s9", None)]),
                step("s3", "end"))
guard_on_instruction = body(step("s1", nxt=[("s2", "if late")]), step("s2", "end"))
dead_end = body(step("s1", nxt=[("s2", None)]), step("s2", nxt=[("s3", None)]), step("s3"),
                step("s4", "end"))


@pytest.mark.parametrize("bad,problem", [
    (two_starts, "more than one start step"), (unreachable, "s4: unreachable"),
    (dangling, "s2: next s9 does not exist"),
    (guard_on_instruction, "s1: guard on a non-condition step"),
    (dead_end, "s3: no successor"),
])
def test_validate_ir_problems(bad, problem):
    assert problem in validate_ir(bad)


def test_validate_ir_more_problems():
    assert validate_ir(body()) == ["no steps"]
    assert "s1: duplicate step id" in validate_ir(body(step("s1", nxt=[("s1", None)]),
                                                       step("s1", "end")))
    assert "s2: end step has a successor" in validate_ir(
        body(step("s1", nxt=[("s2", None)]), step("s2", "end", nxt=[("s1", None)])))
    long_ = body(step("s1", "end")).model_copy(update={"when_to_use": {
        "value": "x" * (WHEN_TO_USE_MAX + 1), "quotes": [{"text": "x", "span": [0, 1]}],
        "status": "verified", "null_reason": None}})
    assert validate_ir(long_) == [f"when_to_use is longer than {WHEN_TO_USE_MAX} characters"]
    # a loop back to the start is allowed: the first step is the start
    assert validate_ir(body(step("s1", nxt=[("s2", None)]),
                            step("s2", "condition", nxt=[("s1", "again"), ("s3", "otherwise")]),
                            step("s3", "end"))) == []


def test_validate_ir_refuses_empty_guards():
    """Fix round 1 of Task 5 (M1): a guard that is empty or only whitespace is a problem."""
    for guard in ["", "  \n"]:
        b = body(step("s1", "condition", nxt=[("s2", guard), ("s2", "otherwise")]),
                 step("s2", "end"))
        assert validate_ir(b) == ["s1: empty guard"]
    assert validate_ir(body(step("s1", "condition", nxt=[("s2", "If"), ("s2", "otherwise")]),
                            step("s2", "end"))) == []


def test_branch_paths_one_per_condition_outcome():
    b = body(step("s1", nxt=[("s2", None)]),
             step("s2", "condition", nxt=[("s3", "late"), ("s4", "otherwise")]),
             step("s3", nxt=[("s6", None)]),
             step("s4", "condition", nxt=[("s5", "lost"), ("s6", "otherwise")]),
             step("s5", nxt=[("s6", None)]),
             step("s6", "end"))
    paths = branch_paths(b)
    assert paths == [["s1", "s2", "s3", "s6"], ["s1", "s2", "s4", "s6"],
                     ["s1", "s2", "s4", "s5", "s6"], ["s1", "s2", "s4", "s6"]]
    outcomes = [(s.id, e.to) for s in b.steps if s.type == "condition" for e in s.next]
    assert len(paths) == len(outcomes)
    by = {s.id: s for s in b.steps}
    for path, (cond, to) in zip(paths, outcomes, strict=True):
        assert path[0] == "s1" and by[path[-1]].type == "end"
        es = edges_of(path)
        assert (cond, to) in es and len(es) == len(set(es))          # each edge once
        assert all(t in {e.to for e in by[a].next} for a, t in es)
    covered = {e for p in paths for e in edges_of(p)}
    assert covered == {(s.id, e.to) for s in b.steps for e in s.next}


def test_branch_paths_follow_loops_once_and_cover_linear_bodies():
    loop = body(step("s1", nxt=[("s2", None)]),
                step("s2", "condition", nxt=[("s1", "again"), ("s3", "otherwise")]),
                step("s3", "end"))
    assert branch_paths(loop) == [["s1", "s2", "s1"], ["s1", "s2", "s3"]]
    # without a condition the one path start to end is the body's test (Task 1 sample body)
    assert branch_paths(body(step("s1", nxt=[("s2", None)]), step("s2", "end"))) == [
        ["s1", "s2"]]


def test_branch_paths_of_the_fixture_skeleton(units_store):
    b = irm_skeleton(proc_section(units_store), units_store.text(DOC_IRM))
    assert branch_paths(b) == [
        ["s1", "s2", "s3", "s4", "s5", "s8", "s9"], ["s1", "s2", "s3", "s4", "s6", "s8", "s9"],
        ["s1", "s2", "s3", "s4", "s6", "s7", "s8", "s9"],
        ["s1", "s2", "s3", "s4", "s6", "s8", "s9"]]


# -- bench -------------------------------------------------------------------------------------

def test_bench_skeleton_of_the_runbook(units_store):
    """Numbered items become instruction steps; the item starting with "If" becomes a
    condition whose guard is its If clause and whose action is the rest of the item."""
    text = units_store.text(DOC_RUNBOOK)
    b = bench_skeleton(units_store, DOC_RUNBOOK)
    got = [(s.id, s.type, [(e.to, e.guard) for e in s.next]) for s in b.steps]
    guard = "If the error rate stays above one percent for ten minutes"
    assert got == [("s1", "instruction", [("s2", None)]), ("s2", "instruction", [("s3", None)]),
                   ("s3", "instruction", [("s4", None)]), ("s4", "instruction", [("s5", None)]),
                   ("s5", "condition", [("s6", guard), ("s7", "otherwise")]),
                   ("s6", "instruction", [("s7", None)]), ("s7", "instruction", [("s8", None)]),
                   ("s8", "end", [])]
    assert b.steps[0].text.startswith("Confirm the alert in the on-call dashboard")
    assert b.steps[4].text == guard and b.steps[4].condition == guard
    assert b.steps[5].text == "escalate to the Platform Reliability lead."
    for s in b.steps[:-1]:
        a, e = s.span
        assert text[a:e] == s.text
    assert b.source_kind == "bench" and b.ambiguity_flags == [] and b.tests == branch_paths(b)
    assert validate_ir(b) == []


def test_bench_headed_steps(tmp_path):
    md = bench_md("Cache Flush Playbook", "## Purpose\n\nKeep caches fresh.\n\n"
                  "## Step 1: Freeze writes\n\nSet the cluster read-only.\n\n"
                  "## Step 2: Flush\n\nRun the flush job.\n\n### Notes\n\nIt takes minutes.\n\n"
                  "## Step 3: Thaw\n\nRe-enable writes.\n\n## Contacts\n\nThe storage team.")
    store, (doc,) = bench_store(tmp_path, [md])
    text = store.text(doc)
    b = bench_skeleton(store, doc)
    assert [s.type for s in b.steps] == ["instruction"] * 3 + ["end"]
    assert [s.text for s in b.steps[:3]] == [
        "## Step 1: Freeze writes\n\nSet the cluster read-only.",
        "## Step 2: Flush\n\nRun the flush job.\n\n### Notes\n\nIt takes minutes.",
        "## Step 3: Thaw\n\nRe-enable writes."]
    assert all(text[s.span[0]:s.span[1]] == s.text for s in b.steps[:3])
    assert bench_candidates(store) == [doc]


def test_bench_candidates_are_seeded_and_capped(units_store, tmp_path):
    # the fixture store: the runbook only (the FAQ and the KCS article are not procedures)
    assert bench_candidates(units_store) == [DOC_RUNBOOK]
    assert DOC_FAQ not in bench_candidates(units_store) and DOC_KCS not in bench_candidates(
        units_store)
    raws = [bench_md(f"Drill {i} {kind}", STEPS6) for i, kind in enumerate(
        ["Runbook", "Playbooks", "SOP", "procedure", "Process", "Guide", "Checklist"])]
    raws += [bench_md("Drill notes", STEPS6),                         # no kind word
             bench_md("Two-step runbook", "1. Do one.\n2. Do two.")]  # under MIN_STEPS
    store, ids = bench_store(tmp_path, raws)
    candidates = ids[:7]
    assert bench_candidates(store) == sorted(candidates)
    assert BENCH_CAP == 110 and SEED4 == 20261121

    def drawn(seed, cap):
        key = lambda d: hashlib.sha256(f"{seed}:{d}".encode()).hexdigest()  # noqa: E731
        return sorted(sorted(candidates, key=key)[:cap])

    for seed in (SEED4, 1, 2):
        got = bench_candidates(store, seed=seed, cap=3)
        assert got == drawn(seed, 3) and len(got) == 3
        assert bench_candidates(store, seed=seed, cap=3) == got
    assert len({tuple(drawn(s, 3)) for s in range(20)}) > 1        # the seed matters
    assert bench_candidates(store, cap=0) == []


def test_bench_procedure_units(units_store):
    units, report = procedure_units(units_store, "bench", overlay_of(units_store))
    assert [u.canonical_ref for u in units] == [f"bench:{DOC_RUNBOOK}"]
    u = units[0]
    assert u.title == "Inference Gateway Failover Runbook"
    assert u.heading_path == ["Inference Gateway Failover Runbook"]
    assert u.governance.owner == "confluence"
    assert validate_unit(load_unit_contracts()["procedure"], u) == []
    assert report["candidates"] == report["drawn"] == report["procedures"] == 1
    assert report["documents"] == 0 and report["sections"] == 0
    assert report["if_items"] == {"conditions": 1, "no_action": 0}


def test_bench_if_items_split_at_the_first_colon_or_comma(tmp_path):
    """Review I3: the guard ends at the first ":" or "," followed by a space or the end of
    the line, whichever comes first; with nothing after it on the line, the item's sub-items
    (more indented, or bullets right under it at its own indent) are the action; an "If"
    item with no action stays an instruction."""
    md = bench_md("Queue Triage Runbook", "\n".join([
        "1. If routed to SE consult: assign to SE queue, tag customer tier.",
        "2. If the backlog grows, page the on-call at 10:30 or later.",
        "3. If p99 is rising and queue depth is rising:",
        "   - Scale the pool.",
        "   - Shed batch traffic.",
        "4. If single-link kernel regression",
        "   - Open a kernel perf ticket.",
        "5. If the cache is cold:",
        "- Warm the cache.",
        "- Recheck latency.",
        "6. If in doubt ask the lead.",
        "7. Close the incident.",
        "",
        "- A note list after a blank line, no part of step 7."]))
    store, (doc,) = bench_store(tmp_path, [md])
    text = store.text(doc)
    b = bench_skeleton(store, doc)
    conds = [(s.condition, next(t for t in b.steps if t.id == s.next[0].to).text)
             for s in b.steps if s.type == "condition"]
    assert conds == [
        ("If routed to SE consult", "assign to SE queue, tag customer tier."),
        ("If the backlog grows", "page the on-call at 10:30 or later."),
        ("If p99 is rising and queue depth is rising", "Scale the pool.\n   - Shed batch traffic."),
        ("If single-link kernel regression", "Open a kernel perf ticket."),
        # bullets right under the item at its own indent are its sub-items
        ("If the cache is cold", "Warm the cache.\n- Recheck latency.")]
    assert [s.type for s in b.steps[-3:]] == ["instruction", "instruction", "end"]
    assert b.steps[-3].text == "If in doubt ask the lead."
    assert all(text[s.span[0]:s.span[1]] == s.text for s in b.steps[:-1])
    assert all(s.text == s.condition for s in b.steps if s.type == "condition")
    _, report = procedure_units(store, "bench", None)
    assert b.steps[-2].text == "Close the incident."
    assert report["if_items"] == {"conditions": 5, "no_action": 1}


def test_bench_candidates_are_scanned_once(units_store, monkeypatch):
    import adr_store.units.procedures as procedures_mod
    calls = []
    real = procedures_mod._bench_candidates
    monkeypatch.setattr(procedures_mod, "_bench_candidates",
                        lambda store: calls.append(1) or real(store))
    procedure_units(units_store, "bench", None)
    assert calls == [1]


def test_step_types_and_flags_match_the_contract():
    contract = load_unit_contracts()["procedure"]
    steps = next(f for f in contract.fields if f.name == "steps")
    allowed = {f.name: f.allowed for f in steps.fields}
    assert tuple(allowed["type"]) == STEP_TYPES == get_args(Step.model_fields["type"].annotation)
    assert tuple(allowed["risk"]) == get_args(Step.model_fields["risk"].annotation)
    kinds = next(f for f in contract.fields if f.name == "source_kind").allowed
    assert tuple(kinds) == get_args(ProcedureBody.model_fields["source_kind"].annotation)
    assert set(ProcedureBody.model_fields) == {f.name for f in contract.fields}
    assert set(Step.model_fields) == {f.name for f in steps.fields}
