"""Concepts: defined terms as `concept` units, and concept linking into rule cards (Phase 4
spec §5.3, §7, §8.3 `defines`, P9, P31; criterion D1's sources). Code only, no model.

**Sources.**
- **eCFR definition statements** (`ecfr_definitions`). A term set in italics (`<I>`/`<E>`) or
  in quotes (“…” or "…"), with at most one trailing `.`/`,`/`:`/`;` inside or after it, then
  whitespace and one of `DEFINING` ("<I>Drawtender.</I> means", "“Drawtender,” means",
  "“escort zone” shall mean"). "The term <I>x</I>, as used in this section, means" is not a
  statement (the term is not followed by the phrase), as in the survey (§4.1). The
  definition runs from the term (its opening quote) through the next defined term of the
  paragraph or the paragraph's end. A term "Long Form (ABBR)" or "Long Form or ABBR" whose
  initials spell the abbreviation (`long_forms`) gives the long form as the term and the
  abbreviation as an alternate label ("Regulated navigation area (RNA)", "Merchant mariner
  credential or MMC"); so do two italic runs "<I>Term</I> or (<I>ABBR</I>)" ("Certain
  Dangerous Cargo or (CDC) includes").
- **Scope** from the enclosing words "For [the] purpose(s) of this …", "As used in this …" or
  "… apply to this …" followed by part, subpart, section or paragraph [(x)…]: the last such
  words before the term in its own paragraph, else in the paragraph's marked ancestors,
  nearest first, else in the section's lead-in (an earlier unmarked top-level paragraph that
  ends with ":" and holds no definition: "The following definitions apply to this part:"
  covers every definition after it in the section). Without them the scope is the section,
  except in § 117.4, which takes the part. Scope refs: "33 CFR part 117",
  "33 CFR part 165, subpart C", "33 CFR 165.T01", "33 CFR 165.21(a)" (a paragraph scope
  names the paragraph its words name, else the paragraph holding the words).
- **IRM acronym tables** (`irm_acronyms`), read from the raw HTML (`blobs/`): every two-column
  table whose nearest enclosing `div.section` has a title containing "acronym", or whose first
  header cell is "Acronym(s)" or "Abbreviation(s)". Each body row gives the acronym (an
  alternate label) and the first line of its expansion, cut at ": " (the term). The row is
  located in the canonical text in document order (acronym, then the expansion's words; table
  pipes or plain spaces between them); a row the text does not hold is left out and listed
  (`misses`, `concept_census`); so is an eCFR paragraph that cannot be read. Scope: the
  chapter, kind `document` ("IRM 21.4.1"), since one stored document is one chapter.
- **research and bench** (`long_forms` over every document's text): "Long Form (ABBR)" where
  the initials of the long form's words spell the abbreviation, case-insensitive. Stop words
  `LONG_FORM_STOP` may be skipped inside the long form but never begin it; a hyphenated word
  gives the initials of its parts (stop-word parts optional, "state-of-the-art" for SOTA) or
  its first initial alone; the word just before the parenthesis must be used; a trailing
  plural "s" of the abbreviation ("LLMs") is not a letter. The long form never crosses
  `.,;:!?`, brackets, quotes or a blank line. Scope: the document, ref `"<corpus>:<doc id>"`.

**Units.** One `concept` per (term key, scope, document) (P31): `canonical_ref` is
`concept:<scope ref>:<term key>`, the term key is `tables.parse.base_key` of the term. When a
scope defines a term twice, the first definition is the unit's text and `definition`, and every
statement is a source ref. `pref_label` is the term as written (trailing punctuation dropped),
`alt_labels` the abbreviations, `hidden_labels` the `hidden_labels` of every label. `broader`
and `narrower` link senses of the same term key in the same document by scope nesting, the
nearest enclosing sense only (a part sense is broader than a section redefinition).

**Linking** (`link_concepts`, and `closure.closure(.., concepts)`). A card's `defines` are the
concepts of its own document one of whose hidden labels occurs in the card's text as whole
words (case-folded, whitespace collapsed) and whose scope contains the card (`scope_contains`),
ordered by first mention, then narrowest scope, then unit id. Every sense whose scope
contains the card is listed, a section redefinition before the part sense. A `defines` entry
is `{relation: "defines", ref: concept canonical_ref, unit_id, doc_id, span: the definition
span}`; `rule_card.defined_terms` holds the same unit ids in the same order.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lxml import etree
from lxml import html as lxml_html

from adr_eval.corpora.extract import extract_text
from adr_store import applicability as ap
from adr_store.applicability import Applicability
from adr_store.store import Store
from adr_store.tables.ecfr import located_div8
from adr_store.tables.parse import base_key
from adr_store.units import ecfr
from adr_store.units.closure import RELATIONS, ClosureEntry
from adr_store.units.envelope import Unit, make_unit, text_sha12, unit_id

__all__ = ["DEFINING", "LONG_FORM_STOP", "Definition", "concept_census", "concepts",
           "defines_entries",
           "ecfr_definitions", "hidden_labels", "irm_acronyms", "link_concepts", "long_forms",
           "scope_contains"]

DEFINING = ("means", "includes", "is defined", "refers to", "shall mean")
LONG_FORM_STOP = ("of", "and", "for", "the", "in", "on")
ScopeKind = Literal["part", "subpart", "section", "paragraph", "document"]
_SPEC = "concept.definition@1"
_PART_SCOPED = {("33", "117.4")}  # (title, section): definitions that take the part (§7)


@dataclass(frozen=True)
class Definition:
    doc_id: str
    term: str
    term_key: str
    text: str
    start: int                # document offsets of `text`
    end: int
    scope_kind: ScopeKind
    scope_ref: str
    alt_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Found:
    """A definition and what its unit needs besides: the breadcrumb of where it stands and,
    for an eCFR section, the subpart (for `scope_contains`)."""

    definition: Definition
    heading_path: tuple[str, ...]
    subpart: str | None = None


# -- labels ------------------------------------------------------------------------------------

def hidden_labels(label: str) -> list[str]:
    """The index-only variants of `label` (§7): its base key (NFKC, case-folded, whitespace
    collapsed, surrounding punctuation stripped), with spaces and hyphens swapped both ways and,
    for a hyphenated label, joined ("draw-bridge" → "drawbridge"); each with a plural "s"
    unless it ends in "s". Sorted, deduplicated."""
    key = base_key(label)
    if not key:
        return []
    forms = {key, key.replace("-", " "), key.replace(" ", "-")}
    if "-" in key:
        forms.add(key.replace("-", ""))
    return sorted(forms | {f + "s" for f in forms if not f.endswith("s")})


def _term(raw: str) -> str:
    """The term as written: whitespace collapsed, trailing punctuation dropped."""
    return " ".join(raw.split()).rstrip(".,:;").strip()


# -- long forms --------------------------------------------------------------------------------

_ABBR = re.compile(r"\(([A-Za-z]{2,12})\)")
_LONG_STOP = re.compile(r"[.,;:!?()\[\]{}\"“”]|\n\s*\n")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’]*(?:-[A-Za-z0-9'’]+)*")


def _letters(abbr: str) -> str | None:
    """The letters an abbreviation spells, lower-cased, or None when it is not one: at least
    two capitals; a plural "s" after a capital is dropped ("LLMs")."""
    if sum(ch.isupper() for ch in abbr) < 2:
        return None
    if abbr.endswith("s") and abbr[-2].isupper():
        abbr = abbr[:-1]
    return abbr.lower()


def _spellings(word: str) -> set[str]:
    """The letter sequences a word may give: its initial; for a hyphenated word also the
    initials of its parts, stop-word parts optional."""
    out = {word[0].lower()}
    parts = word.split("-")
    if len(parts) > 1:
        seqs = {""}
        for p in parts:
            seqs = {s + p[0].lower() for s in seqs} | (
                seqs if p.lower() in LONG_FORM_STOP else set())
        out |= {s for s in seqs if s}
    return out


def _long_start(words: list[str], letters: str) -> int | None:
    """The index of the first word of the long form ending at `words[-1]` whose spellings give
    `letters`, or None. Stop words may be skipped once a word has been used, and the first
    word is never a stop word ("before (BA) and after (AA)" gives no "and after")."""
    stop = set(LONG_FORM_STOP)
    memo: dict[tuple[int, int, bool], int | None] = {}

    def go(j: int, n: int, used: bool) -> int | None:  # words[:j+1], letters[:n] remain
        if n == 0:
            return j + 1
        if j < 0:
            return None
        key = (j, n, used)
        if key not in memo:
            found = None
            for s in sorted(_spellings(words[j]), key=lambda s: (-len(s), s)):
                if len(s) <= n and letters[n - len(s):n] == s and not (
                        n == len(s) and words[j].lower() in stop):  # no stop word first
                    found = go(j - 1, n - len(s), True)
                    if found is not None:
                        break
            if found is None and used and words[j].lower() in stop:
                found = go(j - 1, n, True)
            memo[key] = found
        return memo[key]

    return go(len(words) - 1, len(letters), False)


def long_forms(text: str) -> list[tuple[str, str, int, int]]:
    """Every "Long Form (ABBR)" of `text` in text order: (long form, abbreviation, start, end),
    `text[start:end]` being the whole statement "Long Form (ABBR)" (rules in the module
    docstring)."""
    out = []
    for m in _ABBR.finditer(text):
        letters = _letters(m.group(1))
        if letters is None:
            continue
        lo = 0
        for b in _LONG_STOP.finditer(text, 0, m.start()):
            lo = b.end()
        words = list(_WORD.finditer(text, lo, m.start()))
        if not words or text[words[-1].end():m.start()].strip():
            continue
        first = _long_start([w.group(0) for w in words], letters)
        if first is None:
            continue
        start = words[first].start()
        out.append((text[start:words[-1].end()], m.group(1), start, m.end()))
    return out


_OR_ABBR = re.compile(r"^(.*\S)\s+or\s+([A-Za-z]{2,12})$")


def _split_long_form(term: str) -> tuple[str, tuple[str, ...]]:
    """A term "Long Form (ABBR)" or "Long Form or ABBR" whose initials spell the abbreviation
    as (long form, (ABBR,)); any other term unchanged."""
    for long, abbr, _, end in long_forms(term):
        if end == len(term):
            return long, (abbr,)
    if (m := _OR_ABBR.match(term)) and (letters := _letters(m.group(2))):
        words = _WORD.findall(m.group(1))
        if words and _long_start(words, letters) == 0:
            return m.group(1), (m.group(2),)
    return term, ()


# -- eCFR definition statements ---------------------------------------------------------------

_PHRASE = re.compile(r"[.,:;]?\s+(?:" + "|".join(r"\s+".join(p.split()) for p in DEFINING)
                     + r")\b")
_QUOTED = re.compile(r"“([^“”]{1,120})”|\"([^\"]{1,120})\"")
_SCOPE_WORDS = re.compile(
    r"\b(?:for\s+(?:the\s+)?purposes?\s+of|as\s+used\s+in|appl(?:y|ies)\s+(?:to|in))\s+this\s+"
    r"(part|subpart|section|paragraph)\b((?:\s?\(\w{1,5}\))*)", re.IGNORECASE)
_ITALIC = ("I", "E")
_OR_RUN = re.compile(r"\s+or\s+(\()?")
_TRAILING_JOIN = re.compile(r"(?:[\s,;]|\band\b|\bor\b)+$")


def _find_run(text: str, run: str, cursor: int) -> int:
    """Where italic run `run` stands in `text` from `cursor`, not inside a longer word; -1
    when nowhere."""
    at = text.find(run, cursor)
    while at >= 0:
        j = at + len(run)
        if not ((run[0].isalnum() and at > 0 and text[at - 1].isalnum())
                or (run[-1].isalnum() and j < len(text) and text[j].isalnum())):
            return at
        at = text.find(run, at + 1)
    return -1


def _candidates(p: etree._Element, text: str, lost: list[str] | None = None
                ) -> list[tuple[int, int, str, tuple[str, ...]]]:
    """The defined terms of paragraph `p` (extracted text `text`): (statement start, end of
    the term and its closing quote, raw term, alternate labels) in text order. Italic runs are
    found in order in the text; two runs "<I>Term</I> or (<I>ABBR</I>)" are one term with an
    alternate label. An italic run the text does not hold at all is appended to `lost`."""
    found: list[tuple[int, int, str, tuple[str, ...]]] = []
    cursor = 0
    for el in p.iter(*_ITALIC):
        if el is p or any(a.tag in _ITALIC for a in el.iterancestors() if a is not p):
            continue
        run = " ".join("".join(el.itertext()).split())
        if not run:
            continue
        at = _find_run(text, run, cursor)
        if at < 0:
            # a run found only inside a word ("E<I>2</I>", "f<I>i</I>le") is not a term: a
            # term is followed by whitespace; a run found nowhere is lost
            if lost is not None and text.find(run, cursor) < 0:
                lost.append(run)
            continue
        cursor = at + len(run)
        if found and (gap := _OR_RUN.fullmatch(text, found[-1][1], at)):
            alt = run.strip("()")
            close = gap.group(1) is not None and text.startswith(")", at + len(run))
            stmt, _, first, _ = found.pop()
            found.append((stmt, at + len(run) + close, first, (alt,) if alt else ()))
            continue
        found.append((at, at + len(run), run, ()))
    for m in _QUOTED.finditer(text):
        found.append((m.start(), m.end(), m.group(1) if m.group(1) is not None
                      else m.group(2), ()))
    out: list[tuple[int, int, str, tuple[str, ...]]] = []
    for stmt, after, raw, alts in sorted(found):
        if not _term(raw) or not _PHRASE.match(text, after):
            continue
        if out and stmt < out[-1][1]:
            continue  # inside the previous term (an italic run within quotes)
        out.append((stmt, after, raw, alts))
    return out


def _scope_of_words(m: re.Match, prov: ecfr.Provision, title: str, part: str
                    ) -> tuple[ScopeKind, str]:
    kind = m.group(1).lower()
    if kind == "part" or (kind == "subpart" and prov.subpart is None):
        return "part", f"{title} CFR part {part}"
    if kind == "subpart":
        return "subpart", f"{title} CFR part {part}, subpart {prov.subpart}"
    if kind == "section":
        return "section", f"{title} CFR {prov.section}"
    marks = "".join(f"({x})" for x in re.findall(r"\((\w{1,5})\)", m.group(2)))
    return "paragraph", (f"{title} CFR {prov.section}{marks}" if marks else prov.provision_id)


def _last_words(text: str, end: int | None = None) -> re.Match | None:
    found = None
    for m in _SCOPE_WORDS.finditer(text, 0, len(text) if end is None else end):
        found = m
    return found


def _miss(misses: list | None, doc_id: str, where: str, reason: str, detail: str) -> None:
    if misses is not None:
        misses.append({"doc_id": doc_id, "where": where, "reason": reason, "detail": detail})


def _ecfr_found(store: Store, doc_id: str, misses: list | None = None) -> list[_Found]:
    title, part = ecfr._part_of(store, doc_id)
    provs = ecfr.provisions(store, doc_id)
    by_section: dict[str, list[ecfr.Provision]] = {}
    for p in provs:
        by_section.setdefault(p.section, []).append(p)
    _, divs = located_div8(store, doc_id)
    out: list[_Found] = []
    seen: set[str] = set()
    for div, _, _, _ in divs:
        number = div.get("N") or ""
        if number in seen or number not in by_section:
            continue
        seen.add(number)
        section = by_section[number]
        cands: list[list[tuple[int, int, str, tuple[str, ...]]]] = []
        k = 0
        for el in div.iter("P"):
            t = extract_text(etree.tostring(el, with_tail=False), "xml")
            if not t:
                continue
            if k < len(section) and section[k].text == t:
                lost: list[str] = []
                cands.append(_candidates(el, t, lost))
                for run in lost:
                    _miss(misses, doc_id, section[k].provision_id, "italic_run_not_found", run)
                k += 1
            elif _candidates(el, t):
                _miss(misses, doc_id, f"{title} CFR {number}", "paragraph_unaligned", t[:80])
        for prov in section[k:]:
            _miss(misses, doc_id, prov.provision_id, "provision_unaligned", prov.text[:80])
        cands += [[] for _ in range(len(section) - len(cands))]
        for i, prov in enumerate(section):
            for j, (stmt, _, raw, pair) in enumerate(cands[i]):
                end = cands[i][j + 1][0] if j + 1 < len(cands[i]) else len(prov.text)
                body = prov.text[stmt:end]
                body = body[:len(_TRAILING_JOIN.sub("", body))] if j + 1 < len(cands[i]) \
                    else body.rstrip()
                kind, ref = _scope(prov, i, section, cands, stmt, title, part)
                term, alts = _split_long_form(_term(raw))
                alts = tuple(dict.fromkeys(alts + pair))
                path = [prov.part] + ([f"Subpart {prov.subpart}"] if prov.subpart else []) + [
                    prov.heading]
                out.append(_Found(Definition(
                    doc_id=doc_id, term=term, term_key=base_key(term), text=body,
                    start=prov.start + stmt, end=prov.start + stmt + len(body),
                    scope_kind=kind, scope_ref=ref, alt_labels=alts),
                    (*path, term), prov.subpart))
    return out


def _scope(prov: ecfr.Provision, i: int, section: list[ecfr.Provision], cands: list,
           stmt: int, title: str, part: str) -> tuple[ScopeKind, str]:
    """The scope of a definition at `stmt` in `section[i]` (rules in the module docstring)."""
    if m := _last_words(prov.text, stmt):
        return _scope_of_words(m, prov, title, part)
    for anc in reversed([q for q in section[:i] if q.path and len(q.path) < len(prov.path)
                         and prov.path[:len(q.path)] == q.path
                         and not ecfr._UNMARKED.match(q.path[-1])]):
        if m := _last_words(anc.text):
            return _scope_of_words(m, anc, title, part)
    for k in range(i - 1, -1, -1):  # the section's lead-in
        q = section[k]
        if (len(q.path) == 1 and ecfr._UNMARKED.match(q.path[0]) and not cands[k]
                and q.text.rstrip().endswith(":") and (m := _last_words(q.text))):
            return _scope_of_words(m, q, title, part)
    if (title, prov.section) in _PART_SCOPED:
        return "part", f"{title} CFR part {part}"
    return "section", f"{title} CFR {prov.section}"


def ecfr_definitions(store: Store, doc_id: str, misses: list | None = None
                     ) -> list[Definition]:
    """The definition statements of eCFR document `doc_id` in document order, with their
    scope (rules in the module docstring). What could hold a definition but is not read is
    appended to `misses` as `{doc_id, where, reason, detail}`: `italic_run_not_found` (an
    italic run of a paragraph its text does not hold), `paragraph_unaligned` (a paragraph
    with a candidate term whose text is no provision's: located paragraphs only, see
    `ecfr.provisions(.., misses)`), `provision_unaligned` (a provision left without its
    paragraph, so its definitions are not read)."""
    return [f.definition for f in _ecfr_found(store, doc_id, misses)]


# -- IRM acronym tables ------------------------------------------------------------------------

_ACRONYM_HEAD = re.compile(r"^(?:acronyms?|abbreviations?)$", re.IGNORECASE)
_DATED = re.compile(r"\s*\(\d{2}-\d{2}-\d{4}\)$")  # "21.4.1.3 (10-01-2026)"
_SECTION_CLASS = 'contains(concat(" ", normalize-space(@class), " "), " section ")'


def _norm(s: str) -> str:
    return " ".join(s.split())


def _section_of(el) -> tuple[str, str]:
    """(number, title) of the nearest `div.section` holding `el`, or ("", "")."""
    secs = el.xpath(f"ancestor::div[{_SECTION_CLASS}][1]")
    if not secs:
        return "", ""
    sec = secs[0]
    info = sec.xpath('./div[contains(@class, "sectioninfo")]//strong')
    number = _DATED.sub("", _norm(" ".join(i.text_content() for i in info)))
    heads = sec.xpath('./div[contains(@class, "titlepage")]//*[self::h1 or self::h2 or self::h3'
                      ' or self::h4 or self::h5 or self::h6] | ./h2 | ./h3')
    return number, _norm(heads[0].text_content()) if heads else ""


def _cells(tr) -> list[str]:
    return [c.text_content() for c in tr.xpath("./td | ./th")]


def _irm_found(store: Store, doc_id: str, misses: list | None = None) -> list[_Found]:
    raw = (Path(store.path) / "blobs" / doc_id[:2] / doc_id).read_bytes()
    if hashlib.sha256(raw).hexdigest() != doc_id:
        raise ValueError(f"{doc_id[:12]}: the stored bytes are not the document's bytes")
    chain = ap.chain_of(store.source(doc_id)) or ""
    if not chain.startswith("irm:"):
        raise ValueError(f"{doc_id[:12]}: not an IRM document")
    chapter = "IRM " + chain.split(":", 1)[1]
    root = lxml_html.document_fromstring(raw, parser=lxml_html.HTMLParser(
        no_network=True, remove_comments=True))
    full = store.text(doc_id)
    out: list[_Found] = []
    cursor = 0
    for table in root.iter("table"):
        number, title = _section_of(table)
        head = table.xpath("./thead/tr[1]") or table.xpath("./tr[th][1] | ./tbody/tr[th][1]")
        head_cells = [_norm(c) for c in _cells(head[0])] if head else []
        if not ("acronym" in title.lower() or (head_cells and _ACRONYM_HEAD.match(
                head_cells[0]))):
            continue
        for tr in table.xpath("./tbody/tr | ./tr"):
            if head and tr is head[0]:
                continue
            cells = _cells(tr)
            if len(cells) != 2:
                continue
            acronym = _norm(cells[0])
            lines = [_norm(x) for x in cells[1].split("\n") if _norm(x)]
            if not acronym or not lines:
                continue
            expansion = lines[0]
            pattern = (r"(?<!\w)" + r"\s+".join(map(re.escape, acronym.split())) + r"[\s|]+"
                       + r"\s+".join(map(re.escape, expansion.split())))
            m = re.compile(pattern).search(full, cursor)
            if m is None:
                _miss(misses, doc_id, f"{number} {title}".strip(), "row_not_found",
                      f"{acronym} | {expansion}"[:80])
                continue
            cursor = m.end()
            term = _term(expansion.split(": ", 1)[0])
            out.append(_Found(Definition(
                doc_id=doc_id, term=term, term_key=base_key(term), text=m.group(0),
                start=m.start(), end=m.end(), scope_kind="document", scope_ref=chapter,
                alt_labels=(acronym,)), (chapter, f"{number} {title}".strip(), term)))
    return out


def irm_acronyms(store: Store, doc_id: str, misses: list | None = None) -> list[Definition]:
    """The rows of the acronym tables of IRM document `doc_id`, in document order, as
    definitions scoped to the chapter (rules in the module docstring). A row the text does
    not hold is appended to `misses` (reason `row_not_found`)."""
    return [f.definition for f in _irm_found(store, doc_id, misses)]


# -- long-form concepts of research and bench ------------------------------------------------

def _long_form_found(store: Store, doc_id: str, corpus: str) -> list[_Found]:
    text = store.text(doc_id)
    title = next((ln.strip() for ln in text.split("\n") if ln.strip()), doc_id)[:200]
    out = []
    for long, abbr, start, end in long_forms(text):
        term = _term(long)
        out.append(_Found(Definition(
            doc_id=doc_id, term=term, term_key=base_key(term), text=text[start:end],
            start=start, end=end, scope_kind="document", scope_ref=f"{corpus}:{doc_id}",
            alt_labels=(abbr,)), (title, term)))
    return out


# -- scopes ------------------------------------------------------------------------------------

_UNIT_ID = re.compile(r"^(?:concept|rule_card|procedure|faq|table_record)/(.+)/[0-9a-f]{12}/"
                      r"[0-9a-f]{16}$")
_PART_REF = re.compile(r"^(\d+) CFR part (\w+)(?:, subpart (\w+))?$")
_KIND_RANK = {"paragraph": 0, "section": 1, "subpart": 2, "part": 3, "document": 4}


def scope_contains(scope_ref: str, ref: str, *, subpart: str | None = None) -> bool:
    """Whether the scope `scope_ref` contains `ref`: a canonical ref, a scope ref or a unit id
    (its canonical ref is read). A part holds its sections, paragraphs and subparts; a section
    or paragraph the paragraphs under it; an IRM chapter its sections; a document scope only
    itself. A subpart holds a section ref only when `subpart` (the subpart holding `ref`)
    names it, since a section number does not say its subpart."""
    if m := _UNIT_ID.match(ref):
        ref = m.group(1)
    if ref == scope_ref:
        return True
    if m := _PART_REF.match(scope_ref):
        title, part, sub = m.groups()
        if sub is not None:
            return subpart == sub and ref.startswith(f"{title} CFR {part}.")
        return ref.startswith(f"{title} CFR {part}.") or ref.startswith(scope_ref + ", subpart ")
    if scope_ref.startswith("IRM "):
        return ref.startswith(scope_ref + ".")
    if " CFR " in scope_ref:
        return ref.startswith(scope_ref + "(")
    return False


# -- units -----------------------------------------------------------------------------------

def _found(store: Store, corpus: str, misses: list | None = None) -> list[_Found]:
    if corpus == "gov":
        irm = sorted(d for d in store.doc_ids() if ap.family_of(store.source(d).uri) == "irm")
        return ([f for d in ecfr.ecfr_docs(store) for f in _ecfr_found(store, d, misses)]
                + [f for d in irm for f in _irm_found(store, d, misses)])
    return [f for d in store.doc_ids() for f in _long_form_found(store, d, corpus)]


def concept_census(store: Store, corpus: str) -> dict:
    """What the concept sources of `corpus` read and what they could not: the statements
    (definitions, acronym rows, long forms), the distinct (document, term key) pairs, every
    miss (`ecfr_definitions`, `irm_acronyms`) sorted by (document, where, reason, detail),
    and the misses per reason. A clean build shows `missed: []`."""
    misses: list[dict] = []
    found = _found(store, corpus, misses)
    misses.sort(key=lambda m: (m["doc_id"], m["where"], m["reason"], m["detail"]))
    reasons: dict[str, int] = {}
    for m in misses:
        reasons[m["reason"]] = reasons.get(m["reason"], 0) + 1
    return {"statements": len(found),
            "terms": len({(f.definition.doc_id, f.definition.term_key) for f in found}),
            "missed": misses, "reasons": dict(sorted(reasons.items()))}


def concepts(store: Store, corpus: str, overlay: Applicability | None,
             misses: list | None = None) -> list[Unit]:
    """The concept units of `corpus` in `store`, sorted by unit id: eCFR definitions and IRM
    acronym rows for gov, long forms of every document otherwise; one unit per (term key,
    scope, document). Misses of the sources are appended to `misses` (`concept_census`)."""
    groups: dict[tuple[str, str, str], list[_Found]] = {}
    for f in _found(store, corpus, misses):
        d = f.definition
        if d.term_key:
            groups.setdefault((d.doc_id, d.scope_ref, d.term_key), []).append(f)
    ids = {}
    for key, fs in groups.items():
        d = fs[0].definition
        ids[key] = unit_id("concept", f"concept:{d.scope_ref}:{d.term_key}", text_sha12(d.text),
                           d.doc_id)
    senses: dict[tuple[str, str], list[tuple[str, str, ScopeKind]]] = {}
    for (doc, scope, term), fs in groups.items():
        senses.setdefault((doc, term), []).append(
            (scope, fs[0].subpart, fs[0].definition.scope_kind))

    def holds(a: tuple, b: tuple) -> bool:  # sense a's scope strictly holds sense b's
        return a[0] != b[0] and scope_contains(a[0], b[0], subpart=b[1])

    units = []
    for (doc, scope, term), fs in groups.items():
        d = fs[0].definition
        mine = next(s for s in senses[(doc, term)] if s[0] == scope)
        others = senses[(doc, term)]
        broader = [a for a in others if holds(a, mine)]
        broader = [a for a in broader if not any(holds(a, c) and holds(c, mine)
                                                 for c in broader)]
        narrower = [b for b in others if holds(mine, b)]
        narrower = [b for b in narrower if not any(holds(mine, c) and holds(c, b)
                                                   for c in narrower)]
        alts = sorted({a for f in fs for a in f.definition.alt_labels} - {d.term})
        body = {
            "pref_label": d.term, "alt_labels": alts,
            "hidden_labels": sorted({h for label in [d.term, *alts]
                                     for h in hidden_labels(label)}),
            "definition": {"text": d.text, "span": [d.start, d.end]},
            "scope": {"kind": d.scope_kind, "ref": scope}, "scope_note": None,
            "broader": sorted(ids[(doc, a[0], term)] for a in broader),
            "narrower": sorted(ids[(doc, b[0], term)] for b in narrower),
            "related": [], "exact_match": []}
        units.append(make_unit(
            type_="concept", title=d.term, heading_path=list(fs[0].heading_path),
            canonical_ref=f"concept:{scope}:{term}", text=d.text, doc_id=doc,
            spans=[(f.definition.start, f.definition.end, _SPEC) for f in fs], body=body,
            store=store, overlay=overlay, corpus=corpus))
    return sorted(units, key=lambda u: u.unit_id)


# -- linking -----------------------------------------------------------------------------------

def _fold(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


class _Labels:
    """The concepts of each document by hidden label, for matching card texts."""

    def __init__(self, concept_units: list[Unit]):
        self.by_doc: dict[str, dict[str, list[Unit]]] = {}
        self.longest: dict[str, int] = {}
        for u in concept_units:
            labels = self.by_doc.setdefault(u.doc_id, {})
            for h in u.body["hidden_labels"]:
                labels.setdefault(h, []).append(u)
                self.longest[u.doc_id] = max(self.longest.get(u.doc_id, 0), len(h))

    def mentions(self, doc_id: str, text: str) -> dict[str, int]:
        """{concept unit id: offset of its first whole-word label mention in `text`}."""
        labels = self.by_doc.get(doc_id)
        if not labels:
            return {}
        t = _fold(text)
        word = [ch.isalnum() or ch == "_" for ch in t]
        starts = [i for i in range(len(t)) if word[i] and (i == 0 or not word[i - 1])]
        ends = [i for i in range(1, len(t) + 1) if word[i - 1] and (i == len(t) or not word[i])]
        out: dict[str, int] = {}
        longest = self.longest[doc_id]
        for s in starts:
            for e in ends:
                if e <= s:
                    continue
                if e - s > longest:
                    break
                for u in labels.get(t[s:e], ()):
                    out.setdefault(u.unit_id, s)
        return out


def _subpart_of(card: Unit) -> str | None:
    return next((h.removeprefix("Subpart ") for h in card.heading_path
                 if h.startswith("Subpart ")), None)


def defines_entries(card: Unit, labels: _Labels | list[Unit]) -> list[ClosureEntry]:
    """The `defines` entries of rule card `card` (rules in the module docstring); `labels` is
    a `_Labels` index or the concept units."""
    if not isinstance(labels, _Labels):
        labels = _Labels(labels)
    found = labels.mentions(card.doc_id, card.body["text"])
    if not found:
        return []
    by_id = {u.unit_id: u for us in labels.by_doc[card.doc_id].values() for u in us}
    sub = _subpart_of(card)
    hits = [by_id[i] for i in found
            if scope_contains(by_id[i].body["scope"]["ref"], card.canonical_ref, subpart=sub)]
    hits.sort(key=lambda u: (found[u.unit_id], _KIND_RANK[u.body["scope"]["kind"]],
                             u.unit_id))
    return [ClosureEntry(relation="defines", ref=u.canonical_ref, unit_id=u.unit_id,
                         doc_id=u.doc_id, span=tuple(u.body["definition"]["span"]))
            for u in hits]


def _with_defines(entries: list[ClosureEntry], defines: list[ClosureEntry]
                  ) -> list[ClosureEntry]:
    """`entries` (in `RELATIONS` order) with their `defines` replaced by `defines`."""
    at = RELATIONS.index("defines")
    before = [e for e in entries if RELATIONS.index(e.relation) < at]
    after = [e for e in entries if RELATIONS.index(e.relation) > at]
    return before + defines + after


def link_concepts(cards: list[Unit], concept_units: list[Unit], closures: dict
                  ) -> tuple[list[Unit], dict]:
    """(`cards` with `defined_terms` filled, `closures` with each card's `defines` entries put
    between `cites` and `exception_of`, replacing any it had). Card ids and hashes do not
    change: the body is not hashed."""
    labels = _Labels(concept_units)
    out_cards = []
    out = dict(closures)
    for c in cards:
        defines = defines_entries(c, labels)
        out[c.unit_id] = _with_defines(list(closures.get(c.unit_id, [])), defines)
        out_cards.append(c.model_copy(update={"body": {
            **c.body, "defined_terms": [e.unit_id for e in defines]}}))
    return out_cards, out
