"""FAQ pairs and KCS articles of bench documents, by code from explicit markup (Phase 4 spec
§5.3, §10). Both are `faq` units.

- **FAQ pairs.** A line whose text (after indentation, an optional list bullet and optional
  bold `**`) starts with "Q:" or "Question:", followed (blank lines aside) by a line that
  starts the same way with "A:" or "Answer:" (an aside in parentheses before the colon is
  allowed: "A (updated):"). The question is the rest of its line; the answer is the rest of
  its line and the lines after it up to a blank line, the next question line or a heading.
  Trailing bold markers are left out of both. A question on the same line as its answer
  ("Q: … A: …"), a question line with a speaker before it ("Leo: Question: …") and a
  question with no answer line are no pairs. One unit per pair: `canonical_ref`
  `<corpus>:<doc id> Q<k>` (k-th pair of the document), source refs the question and the
  answer spans, the KCS fields null.
- **KCS articles.** Markdown headings name the fields when their text (numbering such as
  "1." and a trailing colon removed, emphasis stripped, case-folded) starts with one of the
  field words, as a whole word not followed by a hyphen: `issue` (symptom, symptoms, issue),
  `environment`, `cause` (cause, causes, root cause, root causes) and `resolution`
  (resolution, workaround, workarounds). A field is the text under the first heading that
  names it, up to the next heading of the same or an outer level, outer whitespace
  trimmed; a field with no heading (or no text under it) is null (`absent`). A document is
  a KCS article when at least one field other than `environment` has text; one unit per
  article: `canonical_ref` `<corpus>:<doc id> KCS`, source refs the field spans in document
  order, the question and answer null.

Only markdown documents are read (the bench corpus is markdown). Every span is a span of the
document's canonical text and re-slices to the text stored with it.
"""

from __future__ import annotations

import re

from adr_store.applicability import Applicability
from adr_store.store import Store
from adr_store.structure.markdown import read_blocks
from adr_store.units.envelope import Unit, make_unit

KCS_FIELDS: dict[str, tuple[str, ...]] = {
    "issue": ("symptoms", "symptom", "issue"),
    "environment": ("environment",),
    "cause": ("root causes", "root cause", "causes", "cause"),
    "resolution": ("resolution", "workarounds", "workaround"),
}
FAQ_FIELDS = ("question", "answer")

_LEAD = r"^[ \t]*(?:[-*+][ \t]+)?(?:\*\*)?"
_QUESTION = re.compile(_LEAD + r"(?:Q|Question)[ \t]*:(?:\*\*)?[ \t]*(\S.*?)[ \t]*(?:\*\*)?[ \t]*$",
                       re.M)
_ANSWER = re.compile(_LEAD + r"(?:A|Answer)(?:[ \t]*\([^)\n]*\))?[ \t]*:(?:\*\*)?[ \t]*(\S.*)$",
                     re.M)
_HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
_FIELD_HEAD = {f: re.compile(r"(?:" + "|".join(map(re.escape, words)) + r")(?![\w-])")
               for f, words in KCS_FIELDS.items()}
_NUMBERING = re.compile(r"^(?:\d+(?:\.\d+)*[.)]?\s+)+")


def _md_docs(store: Store) -> list[str]:
    return [d for d in store.doc_ids() if store.source(d).format == "md"]


def _title(text: str) -> str:
    return text.split("\n", 1)[0].lstrip("#").strip()


def _lines(text: str) -> list[tuple[int, int]]:
    out, pos = [], 0
    for line in text.split("\n"):
        out.append((pos, pos + len(line)))
        pos += len(line) + 1
    return out


def _strip_end(text: str, start: int, end: int) -> int:
    """`end` moved back over whitespace and bold markers."""
    while end > start and (text[end - 1].isspace() or text[end - 1] == "*"):
        end -= 1
    return end


def faq_pairs(text: str) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """The (question span, answer span) of every FAQ pair of `text`, in document order."""
    lines = _lines(text)
    pairs = []
    for i, (a, b) in enumerate(lines):
        q = _QUESTION.match(text, a, b)
        if q is None:
            continue
        j = i + 1
        while j < len(lines) and not text[lines[j][0]:lines[j][1]].strip():
            j += 1
        if j == len(lines):
            continue
        ans = _ANSWER.match(text, *lines[j])
        if ans is None:
            continue
        end = lines[j][1]
        for c, d in lines[j + 1:]:
            line = text[c:d]
            if not line.strip() or _QUESTION.match(text, c, d) or _HEADING.match(line):
                break
            end = d
        q_span = (q.start(1), _strip_end(text, q.start(1), q.end(1)))
        a_span = (ans.start(1), _strip_end(text, ans.start(1), end))
        if q_span[0] < q_span[1] and a_span[0] < a_span[1]:
            pairs.append((q_span, a_span))
    return pairs


def faq_units(store: Store, overlay: Applicability | None, corpus: str = "bench") -> list[Unit]:
    """One `faq` unit per Q/A pair of every markdown document of `store`, sorted by unit id."""
    units = []
    for d in _md_docs(store):
        text = store.text(d)
        for k, (q, a) in enumerate(faq_pairs(text), 1):
            body = {"question": {"text": text[q[0]:q[1]], "span": list(q)},
                    "answer": {"text": text[a[0]:a[1]], "span": list(a)},
                    **{f: None for f in KCS_FIELDS}}
            units.append(make_unit(
                type_="faq", title=text[q[0]:q[1]], heading_path=[_title(text)],
                canonical_ref=f"{corpus}:{d} Q{k}", text=text[q[0]:a[1]], doc_id=d,
                spans=[(*q, "faq.question@1"), (*a, "faq.answer@1")], body=body,
                store=store, overlay=overlay, corpus=corpus))
    return sorted(units, key=lambda u: u.unit_id)


def _field_of(title: str) -> str | None:
    t = " ".join(title.replace("*", " ").replace("_", " ").split())
    t = _NUMBERING.sub("", t).rstrip(":").strip().casefold()
    return next((f for f, pat in _FIELD_HEAD.items() if pat.match(t)), None)


def kcs_fields(text: str) -> dict[str, tuple[int, int] | None]:
    """The span of each KCS field of markdown `text` (None: no heading names it, or no text
    under it)."""
    headings, _ = read_blocks(text)
    out: dict[str, tuple[int, int] | None] = {f: None for f in KCS_FIELDS}
    named: set[str] = set()
    for i, h in enumerate(headings):
        field = _field_of(h.title)
        if field is None or field in named:
            continue
        named.add(field)
        stop = next((g.start for g in headings[i + 1:] if g.rank <= h.rank), len(text))
        start, end = h.end, stop
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        out[field] = (start, end) if start < end else None
    return out


def kcs_units(store: Store, overlay: Applicability | None, corpus: str = "bench") -> list[Unit]:
    """One `faq` unit per KCS article among the markdown documents of `store`, sorted by unit
    id."""
    units = []
    for d in _md_docs(store):
        text = store.text(d)
        spans = kcs_fields(text)
        if not any(s is not None for f, s in spans.items() if f != "environment"):
            continue
        given = sorted((s, f) for f, s in spans.items() if s is not None)
        body = {"question": None, "answer": None,
                **{f: None if s is None else {"text": text[s[0]:s[1]], "span": list(s)}
                   for f, s in spans.items()}}
        start, end = given[0][0][0], max(s[1] for s, _ in given)
        units.append(make_unit(
            type_="faq", title=_title(text), heading_path=[_title(text)],
            canonical_ref=f"{corpus}:{d} KCS", text=text[start:end], doc_id=d,
            spans=[(*s, f"faq.{f}@1") for s, f in given], body=body, store=store,
            overlay=overlay, corpus=corpus))
    return sorted(units, key=lambda u: u.unit_id)
