"""eCFR provisions and rule cards (Phase 4 spec §4.1, §6.1, §8.1–§8.3, P3, P4, P31).

A **provision** is one `P` element of a `DIV8` section of an eCFR part (33 CFR 117, 33 CFR
165, 47 CFR 73), in one stored version. Read from the stored XML, no model:

- **Span.** The section is located in the document's canonical text as `ecfr_sections` locates
  it (its extracted text, found from the end of the previous section); each `P` is located as
  a whole line block inside its section, from the end of the previous paragraph, and re-sliced.
  A paragraph that cannot be located is rejected (`provisions(.., misses)` lists it). A section
  number seen twice is kept once (the first), as `ecfr_sections` does.
- **Marker path.** Level 1 `(a)`, level 2 `(1)`, level 3 roman `(i)`, level 4 `(A)`, and the
  italic levels 5 `(<I>1</I>)` and 6 `(<I>i</I>)`. A paragraph starting with several markers
  ("(a)(1)") takes them all, each one deeper than the one before it ("(4)(i)" after (h)(3) is
  (h)(4)(i); "(L)(1)" puts the (1) at level 5). A marker after an italic subject heading
  counts as a leading marker too: "(d) <I>Regulations</I>—(1) <I>Positive control.</I> (i)
  Except" is (d)(1)(i), the deepest marker, and its heading text belongs to that provision.
  For a paragraph's first marker that is both a letter and a roman numeral (`i`, `v`, `x`,
  `ii`, ...): it is the next roman numeral's sibling when it follows that numeral ("(ii)"
  after "(i)", at any level); else it is roman when the current path is at level 2 or deeper,
  unless it is the letter right after the path's level-1 letter; at level 1 a single letter
  is a letter, and a longer one is roman unless it is the next letter. A marker read as a
  letter is roman when the next paragraph starts with its roman successor ("(i)" after
  "(h)(1)", then "(ii)"). A paragraph without a marker takes the last marked path plus `p<n>`,
  n counting the unmarked paragraphs under that path from 1. The provision id is
  `"<title> CFR <section>"` followed by `(<marker>)` per level: § 117.5 is one unmarked
  paragraph, so its id is `33 CFR 117.5(p1)`. Repeated markers in the source can give two
  provisions one id; `closure.duplicate_provision_ids` lists them.
- **Modality** (§8.1). The leftmost match of a lexicon phrase (case-insensitive, word-bounded),
  the longest at equal start, gives the class; `modal_spans` hold every match, scanned left to
  right without overlap. Provision `modal_spans` are document offsets. A paragraph with no
  match is a non-modal provision: not a rule card, but a closure target (P4).
- **Cross-references** (§8.3 as amended after the Task 2 review). "§ N.N", "§§ N.N and N.N"
  (any list joined by commas, "and", "or", "to" or "through"; one reference per number),
  ranges "§ A-B" and "§§ 73.3587-3589" (both ends, as "A through B"),
  "paragraph(s) (x)(y) of this section", "N CFR part N" and "N CFR N.N" (also "N CFR § N.N"),
  each section form with an optional trailing paragraph path ("§ 117.31(b)"). A "§" number
  takes the provision's title. Overlapping matches keep the earliest, then the longest. A
  target in another part is `external`. In the same part, a target is `resolved` only when a
  provision at or under it exists in the version; a missing section or a section without the
  cited paragraph is `dangling` (`closure.closure_census` gives the reason). A reference to
  the provision's own part is recorded as `resolved` and counted apart from U2. Offsets are
  document offsets.

A **rule card** is a modal provision as a `rule_card` unit: `canonical_ref` is the provision
id, the unit text is the paragraph, and the body holds the provision id, the verbatim text,
modality, modal spans, cross-references (`target_unit` is the card whose `canonical_ref` is the
target, the first in document order when several share it, else null) and the not-extracted
form of the four enrichment fields; `closure` is filled from `units.closure` and `bindings`
later. Versions are linked by the build
(`envelope.link_versions` over every version's cards).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from lxml import etree

from adr_eval.corpora.extract import extract_text
from adr_store import applicability as ap
from adr_store.applicability import Applicability
from adr_store.store import Store
from adr_store.tables.ecfr import _locate_line, chain_docs, located_div8
from adr_store.units.envelope import Unit, make_unit, text_sha12, unit_id

__all__ = ["MODAL_LEXICON", "PARTS", "CrossRef", "Provision", "cross_refs", "ecfr_docs",
           "marker_path", "modality", "normalise_rule_id", "provisions", "rule_cards"]

PARTS = ("ecfr:33:117", "ecfr:33:165", "ecfr:47:73")  # chain ids
MODAL_LEXICON: dict[str, tuple[str, ...]] = {
    "prohibition": ("may not", "shall not", "must not", "no person may", "no vessel may",
                    "is prohibited", "are prohibited"),
    "exemption": ("need not",),
    "obligation": ("shall", "must")}
_TITLE_OF_PART = {"117": "33", "165": "33", "73": "47"}  # for bare numbers (normalise_rule_id)
_MODEL_FIELDS = ("subject", "conditions", "thresholds", "exceptions")


@dataclass(frozen=True)
class Provision:
    doc_id: str
    part: str                 # "33 CFR 117"
    section: str              # "117.1081"
    subpart: str | None       # "B"
    heading: str              # the section's first line, "§ 117.1081 Coast Channel."
    path: tuple[str, ...]     # ("a", "2")
    provision_id: str         # "33 CFR 117.1081(a)(2)"
    start: int
    end: int
    text: str
    modality: str | None
    modal_spans: tuple[tuple[int, int, str], ...]  # document offsets, lexicon phrase


@dataclass(frozen=True)
class CrossRef:
    raw: str
    start: int                # document offsets of `raw`
    end: int
    target_ref: str
    resolution: Literal["resolved", "external", "dangling"]


# -- modality --------------------------------------------------------------------------------

_CLASS_OF = {ph: cls for cls, phrases in MODAL_LEXICON.items() for ph in phrases}
_MODAL = re.compile(
    r"\b(?:" + "|".join(r"\s+".join(map(re.escape, ph.split()))
                        for ph in sorted(_CLASS_OF, key=lambda p: (-len(p), p))) + r")\b",
    re.IGNORECASE)


def modality(text: str) -> tuple[str | None, list[tuple[int, int, str]]]:
    """(the class of the leftmost-longest lexicon match or None, every match as (start, end,
    lexicon phrase) in `text`'s offsets)."""
    spans = [(m.start(), m.end(), " ".join(m.group(0).lower().split()))
             for m in _MODAL.finditer(text)]
    return (_CLASS_OF[spans[0][2]] if spans else None), spans


# -- marker paths ------------------------------------------------------------------------------

_ROMAN = re.compile(r"^(?=[ivx])x{0,3}(?:ix|iv|v?i{0,3})$")
_TOKEN = re.compile(r"\((\d{1,3}|[a-z]{1,5}|[A-Z]{1,2})\)")
_UNMARKED = re.compile(r"^p\d+$")


def _is_letter(tok: str) -> bool:
    """A letter marker: one lower-case letter, or one repeated ("aa" after "z")."""
    return tok.islower() and len(set(tok)) == 1


def _next_letter(tok: str) -> str:
    return "a" * (len(tok) + 1) if tok[0] == "z" else chr(ord(tok[0]) + 1) * len(tok)


def _token_ok(tok: str) -> bool:
    if tok.isdigit():
        return True
    if tok.isupper():
        return len(set(tok)) == 1
    return _is_letter(tok) or bool(_ROMAN.match(tok))


def _stored_levels(path: tuple[str, ...]) -> list[int]:
    """The level of each element of a marked path. Levels rise strictly along a path, so a
    digit after level 2 is the italic level 5, and a marker that is both a letter and a roman
    numeral is level 1 first and roman after (3, or the italic 6 below level 3)."""
    out: list[int] = []
    for i, m in enumerate(path):
        prev = out[-1] if out else 0
        if m.isdigit():
            out.append(2 if prev < 2 else 5)
        elif m.isupper():
            out.append(4)
        elif _ROMAN.match(m) and not (i == 0 and _is_letter(m)):
            out.append(3 if prev < 3 else 6)
        else:
            out.append(1)
    return out


def _roman_successor(tok: str) -> str:
    values = {"i": 1, "v": 5, "x": 10}
    n = sum(-values[c] if values[c] < values.get(nxt, 0) else values[c]
            for c, nxt in zip(tok, tok[1:] + " ", strict=True)) + 1
    out = ""
    for v, r in ((10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out, n = out + r, n - v
    return out


def _candidates(tok: str, italic: bool) -> tuple[int, ...]:
    """The levels marker `tok` can hold, shallowest first."""
    if tok.isdigit():
        return (5,) if italic else (2, 5)
    if tok.isupper():
        return (4,)
    if italic:
        return (6,)
    roman, letter = bool(_ROMAN.match(tok)), _is_letter(tok)
    return (1, 3, 6) if roman and letter else (3, 6) if roman else (1,)


def _level(tok: str, path: tuple[str, ...], italic: bool = False,
           following: str | None = None) -> int:
    """The level of the first marker of a paragraph, `tok`, read after the marked path
    `path`; `following` is the first marker of the next paragraph, if any."""
    cands = _candidates(tok, italic)
    if len(cands) == 1 or cands == (2, 5):
        return cands[0]
    levels = _stored_levels(path)
    if path and _ROMAN.match(path[-1]) and tok == _roman_successor(path[-1]):
        return levels[-1]                            # "(ii)" after "(i)": a sibling
    if cands == (3, 6):
        return 3
    first = path[0] if levels and levels[0] == 1 else None
    if first is not None and tok == _next_letter(first):
        lv = 1
    elif levels and levels[-1] >= 2:
        return 3
    else:
        lv = 1 if len(tok) == 1 else 3
    if lv == 1 and following == _roman_successor(tok):
        return 3
    return lv


_SMALL_WORDS = frozenset({"and", "or", "of", "the", "for", "to", "in", "on", "a", "an"})
_PLAIN_HEADING = re.compile(r"\s*([^().\u2014\n]{1,200}?)(?:\. |\u2014)")


def _plain_heading_end(text: str, i: int, last: str, last_italic: bool) -> int | None:
    """Where the marker after a plain subject heading starts, for "(x) <Heading>. (y) …" or
    "(x) <Heading>—(y) …" read from `i` (just after marker `last`), or None. The heading is
    at most 10 words, each capitalised apart from small words (and, or, of, the, for, to,
    in, on, a, an); it ends in ". " or "—"; "(y)" follows at once, one level below (x)."""
    m = _PLAIN_HEADING.match(text, i)
    if m is None:
        return None
    words = m.group(1).split()
    if not words or len(words) > 10:
        return None
    for w in words:
        letters = [c for c in w if c.isalpha()]
        if letters and not letters[0].isupper() and w.lower() not in _SMALL_WORDS:
            return None
    y = _TOKEN.match(text, m.end())
    if y is None or not _token_ok(y.group(1)):
        return None
    if not any(ly == lx + 1 for lx in _candidates(last, last_italic)
               for ly in _candidates(y.group(1), False)):
        return None
    return m.end()


def _leading_markers(text: str) -> list[str]:
    """The leading markers of `text`, including those after a plain subject heading
    (`_plain_heading_end`)."""
    toks, i = [], 0
    while True:
        if (m := _TOKEN.match(text, i)) and _token_ok(m.group(1)):
            toks.append(m.group(1))
            i = m.end()
        elif toks and (k := _plain_heading_end(text, i, toks[-1], False)) is not None:
            i = k
        else:
            return toks


def _path_of(prev: tuple[str, ...], toks: list[str], italic: tuple[bool, ...],
             following: str | None) -> tuple[str, ...]:
    base = prev[:-1] if prev and _UNMARKED.match(prev[-1]) else prev
    if not toks:
        n = int(prev[-1][1:]) + 1 if prev and _UNMARKED.match(prev[-1]) else 1
        return (*base, f"p{n}")
    path, levels = list(base), _stored_levels(base)
    for k, tok in enumerate(toks):
        it = k < len(italic) and italic[k]
        if k == 0:
            lv = _level(tok, tuple(path), it, following if len(toks) == 1 else None)
        else:   # each later marker of the paragraph sits deeper than the one before it
            deeper = [c for c in _candidates(tok, it) if c > levels[-1]]
            lv = deeper[0] if deeper else _level(tok, tuple(path), it)
        keep = [i for i, v in enumerate(levels) if v < lv]
        cut = keep[-1] + 1 if keep else 0
        path, levels = path[:cut] + [tok], levels[:cut] + [lv]
    return tuple(path)


def marker_path(prev: tuple[str, ...], text: str, *, italic: tuple[bool, ...] = (),
                following: str | None = None) -> tuple[str, ...]:
    """The marker path of paragraph `text` read after a paragraph whose path is `prev`.
    `italic`: per leading marker, whether it is set in italics (eCFR levels 5 and 6).
    `following`: the next paragraph's text; a marker read as a letter is roman instead when
    the next paragraph starts with its roman successor ("(i)" then "(ii)")."""
    nxt = _leading_markers(following.lstrip()) if following is not None else []
    return _path_of(prev, _leading_markers(text.lstrip()), italic, nxt[0] if nxt else None)


_HEADING_GAP = re.compile(r"[\s.:—–-]*")


def _element_markers(p: etree._Element) -> tuple[list[str], tuple[bool, ...]]:
    """The leading markers of paragraph element `p` and whether each is italic. A marker may
    be italic ("(<I>1</I>)"), and an italic subject heading after a marker may be followed by
    more markers ("(d) <I>Regulations</I>—(1) <I>Positive control.</I> (i) Except"): the
    paragraph then starts with all of them. So may a plain heading
    (`_plain_heading_end`: "(e) Procedural Matters. (1) Applications …")."""
    text, mask = "", []
    for seg, it in _segments_until_other(p):
        text += seg
        mask += [it] * len(seg)
    toks: list[str] = []
    italic: list[bool] = []
    i = len(text) - len(text.lstrip())
    while True:
        m = _TOKEN.match(text, i)
        if m and _token_ok(m.group(1)):
            toks.append(m.group(1))
            # an italic marker sets the token, not its parentheses, in italics ("(<I>1</I>)");
            # "<I>(2) Representative</I>" is an italic run, not a level-5 marker
            italic.append(all(mask[m.start(1):m.end(1)]) and not mask[m.start()])
            i = m.end()
            continue
        if not toks:
            break
        j = i + len(text[i:]) - len(text[i:].lstrip())
        if j >= len(text) or not mask[j] or text[j] == "(":
            k = _plain_heading_end(text, i, toks[-1], italic[-1])
            if k is None or any(mask[i:k]):
                break
            i = k
            continue
        k = j
        while k < len(text) and mask[k]:
            k += 1
        k = _HEADING_GAP.match(text, k).end()
        nxt = _TOKEN.match(text, k)
        if not (nxt and _token_ok(nxt.group(1))):
            break
        i = k
    return toks, tuple(italic)


def _segments_until_other(p: etree._Element) -> list[tuple[str, bool]]:
    """(text, italic) segments of `p` up to its first child that is not `I` or `E`."""
    out = [(p.text or "", False)]
    for c in p:
        if c.tag not in ("I", "E"):
            break
        out += [("".join(c.itertext()), True), (c.tail or "", False)]
    return out


# -- provisions ------------------------------------------------------------------------------

def _part_of(store: Store, doc_id: str) -> tuple[str, str]:
    chain = ap.chain_of(store.source(doc_id)) or ""
    if not chain.startswith("ecfr:"):
        raise ValueError(f"{doc_id[:12]}: not an eCFR document")
    _, title, part = chain.split(":")
    return title, part


def _subpart_of(div: etree._Element) -> str | None:
    for up in div.iterancestors():
        if up.tag == "DIV6" and up.get("TYPE") == "SUBPART":
            return up.get("N")
    return None


def _read(store: Store, doc_id: str, misses: list | None = None
          ) -> tuple[list[Provision], set[str]]:
    """(the provisions of `doc_id` in document order, the section numbers it holds)."""
    title, part = _part_of(store, doc_id)
    full, divs = located_div8(store, doc_id)
    out: list[Provision] = []
    sections: set[str] = set()
    for div, at, text, _ in divs:
        end = at + len(text)
        number = div.get("N") or ""
        if not number or number in sections:
            continue
        sections.add(number)
        heading, subpart = text.split("\n", 1)[0], _subpart_of(div)
        path: tuple[str, ...] = ()
        inner = at + len(heading)
        paras = [(t, *_element_markers(p)) for p in div.iter("P")
                 if (t := extract_text(etree.tostring(p, with_tail=False), "xml"))]
        for i, (ptext, toks, italic) in enumerate(paras):
            following = paras[i + 1][1][0] if i + 1 < len(paras) and paras[i + 1][1] else None
            path = _path_of(path, toks, italic, following)
            pid = f"{title} CFR {number}" + "".join(f"({m})" for m in path)
            found = _locate_line(full, ptext, inner, end)
            if found is None:
                if misses is not None:
                    misses.append((number, pid))
                continue
            start, stop = found
            inner = stop
            mod, spans = modality(ptext)
            out.append(Provision(
                doc_id=doc_id, part=f"{title} CFR {part}", section=number, subpart=subpart,
                heading=heading, path=path, provision_id=pid, start=start, end=stop,
                text=ptext, modality=mod,
                modal_spans=tuple((start + a, start + b, ph) for a, b, ph in spans)))
    return out, sections


def provisions(store: Store, doc_id: str, misses: list | None = None) -> list[Provision]:
    """Every located `P` of every `DIV8` section of eCFR document `doc_id`, in document order.
    A paragraph that cannot be located is left out and, when `misses` is given, appended to
    it as (section, provision id)."""
    return _read(store, doc_id, misses)[0]


def ecfr_docs(store: Store) -> list[str]:
    """The documents of `PARTS`, all versions: part by part, oldest version first."""
    return [d for chain in PARTS for d in chain_docs(store, chain)]


def skips_a_level(path: tuple[str, ...]) -> bool:
    """Whether a marker path skips a level ("(d)(iv)" holds no level 2), ignoring `p<n>`."""
    marked = tuple(m for m in path if not _UNMARKED.match(m))
    levels = _stored_levels(marked)
    return any(b - a > 1 for a, b in zip([0, *levels], levels, strict=False))


# -- cross-references --------------------------------------------------------------------------

# A section number: "117.5", "117.162T", "165.T01-0149", "1.05-1". A dash suffix is part of it
# after a "T" number or when it has one or two digits; otherwise a dash starts a range end
# ("73.3587-3589", "165.766-165.768"), and a range gives both ends.
_SEC = r"\d+\.(?:T[0-9A-Za-z]+(?:-[0-9A-Za-z]+)?|[0-9A-Za-z]+(?:-\d{1,2})?)(?!\.?\d)"
_PATH = r"(?:\s?(?:\(\w{1,5}\))+)?"
_CFR_PART = re.compile(r"\b(\d+)\s+CFR\s+parts?\s+(\d+)\b")
_CFR_SEC = re.compile(rf"\b(\d+)\s+CFR\s+(?:§§?\s*)?({_SEC})({_PATH})")
_SIGN = re.compile(r"(§§?)\s*")
_ITEM = re.compile(rf"({_SEC})({_PATH})")
_LIST_JOIN = re.compile(r",\s*(?:and\s+|or\s+)?|\s+(?:and|or|to|through)\s+")
_RANGE_END = re.compile(r"-(?:(" + _SEC + r")|(\d+)(?!\w|\.\d))")
_PARAS = re.compile(r"\bparagraphs?\s+((?:\(\w{1,5}\))+)"
                    r"((?:(?:,\s*(?:and\s+|or\s+)?|\s+(?:and|or|through)\s+)(?:\(\w{1,5}\))+)*)"
                    r",?\s+of\s+this\s+section\b")
_MARKS = re.compile(r"\((\w{1,5})\)")


def _marks(path: str) -> str:
    return "".join(f"({m})" for m in _MARKS.findall(path))


def _sign_items(text: str, m: re.Match) -> tuple[list[tuple[int, int, str, str]], int]:
    """The section items after a "§" or "§§" sign at `m`: (start, end, section, path) each,
    and where they end. A "§§" takes a list; either sign takes range ends."""
    first = _ITEM.match(text, m.end())
    if first is None:
        return [], m.end()
    items = [(m.start(), first.end(), first.group(1), first.group(2))]
    i = first.end()
    while True:
        if r := _RANGE_END.match(text, i):
            sec = items[-1][2]
            if r.group(1):
                sec_end = r.group(1)
            else:
                head, rest = sec.split(".", 1)
                d = r.group(2)
                sec_end = f"{head}.{rest[:-len(d)] + d if len(d) <= len(rest) else d}"
            items.append((r.start() + 1, r.end(), sec_end, ""))
            i = r.end()
            continue
        j = _LIST_JOIN.match(text, i) if m.group(1) == "§§" else None
        it = _ITEM.match(text, j.end()) if j else None
        if it is None:
            break
        items.append((it.start(), it.end(), it.group(1), it.group(2)))
        i = it.end()
    return items, i


def cross_refs(p: Provision, section_numbers: set[str],
               provision_ids: set[str] | None = None) -> list[CrossRef]:
    """The explicit references of provision `p` in text order (§8.3). `section_numbers` are
    the sections the version of `p` holds; with `provision_ids` (the version's provision
    ids), an in-part target resolves only when a provision at or under it exists (spec §8.3:
    a section without the cited paragraph is `dangling`)."""
    title, part = p.part.split(" CFR ")

    def resolve(t: str, sec: str, target: str) -> str:
        if sec.split(".", 1)[0] != part or t != title:
            return "external"
        if sec not in section_numbers:
            return "dangling"
        if provision_ids is not None and not any(
                q == target or q.startswith(target + "(") for q in provision_ids):
            return "dangling"
        return "resolved"

    found: list[tuple[int, int, list[CrossRef]]] = []

    def ref(a: int, b: int, t: str, sec: str, path: str) -> CrossRef:
        target = f"{t} CFR {sec}{_marks(path)}"
        return CrossRef(p.text[a:b], p.start + a, p.start + b, target, resolve(t, sec, target))

    for m in _CFR_PART.finditer(p.text):
        same = (m.group(1), m.group(2)) == (title, part)
        found.append((m.start(), m.end(), [CrossRef(
            m.group(0), p.start + m.start(), p.start + m.end(),
            f"{m.group(1)} CFR part {m.group(2)}", "resolved" if same else "external")]))
    for m in _CFR_SEC.finditer(p.text):
        found.append((m.start(), m.end(), [ref(m.start(), m.end(), m.group(1), m.group(2),
                                               m.group(3))]))
    for m in _SIGN.finditer(p.text):
        items, end = _sign_items(p.text, m)
        if items:
            found.append((m.start(), end, [ref(a, b, title, sec, path)
                                           for a, b, sec, path in items]))
    for m in _PARAS.finditer(p.text):
        first = tuple(_MARKS.findall(m.group(1)))
        paths = [first] + [marker_path(first, g.group(0)) for g in
                           re.finditer(r"(?:\(\w{1,5}\))+", m.group(2))]
        found.append((m.start(), m.end(), [
            ref(m.start(), m.end(), title, p.section, "".join(f"({x})" for x in path))
            for path in paths]))
    out: list[CrossRef] = []
    taken = -1
    for a, b, refs in sorted(found, key=lambda f: (f[0], -f[1])):
        if a >= taken:
            out.extend(refs)
            taken = b
    return out


# -- rule ids ----------------------------------------------------------------------------------

_RULE_ID = re.compile(
    r"^(?:(\d+)\s*C\.?\s?F\.?\s?R\.?\s*)?(?:§+\s*)?(\d+)\.([0-9A-Za-z]+(?:-[0-9A-Za-z]+)?)"
    r"((?:\s*\(\w{1,5}\))*)$")


def normalise_rule_id(raw: str) -> str | None:
    """`"<title> CFR <section>(<marker>)..."` for a provision or section reference written
    in any of the usual forms ("§117.1081(a)(2)", "33 C.F.R. § 117.1081 (a)(2)", ...), or
    None. A bare number takes title 33 for parts 117 and 165 and title 47 for part 73; any
    other bare number is None."""
    m = _RULE_ID.match(raw.strip())
    if m is None:
        return None
    title, part, rest, path = m.groups()
    title = title or _TITLE_OF_PART.get(part)
    if title is None:
        return None
    return f"{int(title)} CFR {part}.{rest}" + "".join(f"({x})" for x in _MARKS.findall(path))


# -- rule cards --------------------------------------------------------------------------------

def _not_extracted() -> dict:
    return {"value": None, "quotes": [], "status": None, "null_reason": "not_extracted"}


def rule_cards(store: Store, doc_id: str, overlay: Applicability | None,
               corpus: str = "gov") -> tuple[list[Unit], list[Provision]]:
    """(the rule cards of eCFR document `doc_id`, one per modal provision in document order,
    every provision of it). The cards' closure is empty here (`units.closure` computes it)."""
    provs, sections = _read(store, doc_id)
    full = store.text(doc_id)
    ids = {p.provision_id for p in provs}
    modal = [p for p in provs if p.modality is not None and full[p.start:p.end] == p.text]
    # a provision id held by several cards (repeated markers in the source) names the first
    # of them in document order
    card_ids: dict[str, str] = {}
    for p in modal:
        card_ids.setdefault(p.provision_id,
                            unit_id("rule_card", p.provision_id, text_sha12(p.text), doc_id))
    cards = []
    for p in modal:
        body = {
            "provision_id": p.provision_id, "text": p.text, "modality": p.modality,
            "modal_spans": [{"span": [a, b], "phrase": ph} for a, b, ph in p.modal_spans],
            **{f: _not_extracted() for f in _MODEL_FIELDS},
            "defined_terms": [],
            "cross_refs": [
                {"raw": x.raw, "target_ref": x.target_ref,
                 "target_unit": card_ids.get(x.target_ref) if x.resolution == "resolved"
                 else None, "resolution": x.resolution, "span": [x.start, x.end]}
                for x in cross_refs(p, sections, ids)],
            "closure": [], "bindings": []}
        cards.append(_card(store, overlay, corpus, p, body))
    return cards, provs


def _card(store: Store, overlay: Applicability | None, corpus: str, p: Provision,
          body: dict) -> Unit:
    path = [p.part] + ([f"Subpart {p.subpart}"] if p.subpart else []) + [p.heading]
    return make_unit(
        type_="rule_card", title=p.provision_id, heading_path=[*path, p.provision_id],
        canonical_ref=p.provision_id, text=p.text, doc_id=p.doc_id,
        spans=[(p.start, p.end, "rule_card.text@1")], body=body, store=store,
        overlay=overlay, corpus=corpus)
