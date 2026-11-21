"""eCFR provisions and rule cards (Phase 4 spec §4.1, §6.1, §8.1–§8.3, P3, P4, P31).

A **provision** is one `P` element of a `DIV8` section of an eCFR part (33 CFR 117, 33 CFR
165, 47 CFR 73), in one stored version. Read from the stored XML, no model:

- **Span.** The section is located in the document's canonical text as `ecfr_sections` locates
  it (its extracted text, found from the end of the previous section); each `P` is located as
  a whole line block inside its section, from the end of the previous paragraph, and re-sliced.
  A paragraph that cannot be located is rejected (`provisions(.., misses)` lists it). A section
  number seen twice is kept once (the first), as `ecfr_sections` does.
- **Marker path.** Level 1 `(a)`, level 2 `(1)`, level 3 roman `(i)`, level 4 `(A)`; a
  paragraph starting with several markers ("(a)(1)") takes them all. A marker that is both a
  letter and a roman numeral (`i`, `v`, `x`, `ii`, ...) is roman when the current path is at
  level 2 or deeper, unless it is the letter right after the path's level-1 letter; at level 1
  a single letter is a letter, and a longer one is roman unless it is the next letter. Two
  additions the real parts need (they hold no duplicate ids in 33 CFR 117 either way): a
  marker read as a letter is roman when the next paragraph starts with its roman successor
  ("(i)" after "(h)(1)", then "(ii)"), and an italic marker ("(<I>1</I>)", eCFR level 5)
  sits below level 4. A paragraph without a marker takes the last marked path plus `p<n>`, n
  counting the unmarked paragraphs under that path from 1. The provision id is
  `"<title> CFR <section>"` followed by `(<marker>)` per level: § 117.5 is one unmarked
  paragraph, so its id is `33 CFR 117.5(p1)`.
- **Modality** (§8.1). The leftmost match of a lexicon phrase (case-insensitive, word-bounded),
  the longest at equal start, gives the class; `modal_spans` hold every match, scanned left to
  right without overlap. Provision `modal_spans` are document offsets. A paragraph with no
  match is a non-modal provision: not a rule card, but a closure target (P4).
- **Cross-references** (§8.3). "§ N.N", "§§ N.N and N.N" (any list joined by commas, "and",
  "or", "to" or "through"; one reference per number), "paragraph(s) (x)(y) of this section",
  "N CFR part N" and "N CFR N.N" (also "N CFR § N.N"), each section form with an optional
  trailing paragraph path ("§ 117.31(b)"); a range ("§§ 73.3587-3589") gives its first
  section. A "§" number takes the provision's title. Overlapping
  matches keep the earliest, then the longest. A target in another part is `external`; in the
  same part it is `resolved` when the version holds that section (a reference to the part
  itself always), else `dangling`. Offsets are document offsets.

A **rule card** is a modal provision as a `rule_card` unit: `canonical_ref` is the provision
id, the unit text is the paragraph, and the body holds the provision id, the verbatim text,
modality, modal spans, cross-references (`target_unit` is the card whose `canonical_ref` is the
target, else null) and the not-extracted form of the four enrichment fields; `closure` is
filled from `units.closure` and `bindings` later. Versions are linked by the build
(`envelope.link_versions` over every version's cards).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lxml import etree

from adr_eval.corpora.extract import extract_text
from adr_store import applicability as ap
from adr_store.applicability import Applicability
from adr_store.store import Store
from adr_store.tables.ecfr import _locate_line, chain_docs
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


def _level(tok: str, path: tuple[str, ...], italic: bool = False,
           following: str | None = None) -> int:
    """The level of marker `tok` read after the marked path `path`."""
    if tok.isdigit():
        return 5 if italic else 2
    if italic and tok.islower():
        return 6
    if tok.isupper():
        return 4
    roman, letter = bool(_ROMAN.match(tok)), _is_letter(tok)
    if not (roman and letter):
        return 3 if roman else 1
    levels = _stored_levels(path)
    first = path[0] if levels and levels[0] == 1 else None
    if first is not None and tok == _next_letter(first):
        lv = 1
    elif levels and levels[-1] >= 2:
        return 3
    else:
        lv = 1 if len(tok) == 1 else 3
    if lv == 1 and following is not None:
        nxt = _leading_markers(following.lstrip())
        if nxt and nxt[0] == _roman_successor(tok):
            return 3
    return lv


def _leading_markers(text: str) -> list[str]:
    toks, i = [], 0
    while (m := _TOKEN.match(text, i)) and _token_ok(m.group(1)):
        toks.append(m.group(1))
        i = m.end()
    return toks


def marker_path(prev: tuple[str, ...], text: str, *, italic: bool = False,
                following: str | None = None) -> tuple[str, ...]:
    """The marker path of paragraph `text` read after a paragraph whose path is `prev`.
    `italic`: the paragraph's first marker is set in italics (eCFR levels 5 and 6).
    `following`: the next paragraph's text; a marker read as a letter is roman instead when
    the next paragraph starts with its roman successor ("(i)" then "(ii)")."""
    base = prev[:-1] if prev and _UNMARKED.match(prev[-1]) else prev
    toks = _leading_markers(text.lstrip())
    if not toks:
        n = int(prev[-1][1:]) + 1 if prev and _UNMARKED.match(prev[-1]) else 1
        return (*base, f"p{n}")
    path, levels = list(base), _stored_levels(base)
    for k, tok in enumerate(toks):
        lv = _level(tok, tuple(path), italic and k == 0,
                    following if k == len(toks) - 1 else None)
        keep = [i for i, v in enumerate(levels) if v < lv]
        cut = keep[-1] + 1 if keep else 0
        path, levels = path[:cut] + [tok], levels[:cut] + [lv]
    return tuple(path)


def _italic_marker(p: etree._Element) -> bool:
    """Whether paragraph element `p` opens with an italic marker, "(<I>1</I>)"."""
    return ((p.text or "").strip() == "(" and len(p) > 0 and p[0].tag in ("I", "E")
            and (p[0].tail or "").startswith(")"))


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
    raw = (Path(store.path) / "blobs" / doc_id[:2] / doc_id).read_bytes()
    if hashlib.sha256(raw).hexdigest() != doc_id:
        raise ValueError(f"{doc_id[:12]}: the stored bytes are not the document's bytes")
    title, part = _part_of(store, doc_id)
    full = store.text(doc_id)
    root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
    out: list[Provision] = []
    sections: set[str] = set()
    cursor = 0
    for div in root.iter("DIV8"):
        text = extract_text(etree.tostring(div, with_tail=False), "xml")
        if not text:
            continue
        at = full.find(text, cursor)
        if at < 0:
            raise ValueError(f"{doc_id[:12]}: section {div.get('N')} not found in extracted text")
        cursor, end = at + len(text), at + len(text)
        number = div.get("N") or ""
        if not number or number in sections:
            continue
        sections.add(number)
        heading, subpart = text.split("\n", 1)[0], _subpart_of(div)
        path: tuple[str, ...] = ()
        inner = at + len(heading)
        paras = [(t, _italic_marker(p)) for p in div.iter("P")
                 if (t := extract_text(etree.tostring(p, with_tail=False), "xml"))]
        for i, (ptext, italic) in enumerate(paras):
            path = marker_path(path, ptext, italic=italic,
                               following=paras[i + 1][0] if i + 1 < len(paras) else None)
            pid = f"{title} CFR {number}" + "".join(f"({m})" for m in path)
            found = _locate_line(full, ptext, inner, end)
            if found is None or full[found[0]:found[1]] != ptext:
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


# -- cross-references --------------------------------------------------------------------------

# A section number: "117.5", "117.162T", "165.T01-0149", "1.05-1". A dash suffix is part of it
# after a "T" number or when it has one or two digits; "73.3587-3589" and "165.766-165.768"
# are ranges, read as their first section.
_SEC = r"\d+\.(?:T[0-9A-Za-z]+(?:-[0-9A-Za-z]+)?|[0-9A-Za-z]+(?:-\d{1,2})?)(?!\.?\d)"
_PATH = r"(?:\s?(?:\(\w{1,5}\))+)?"
_JOIN = r"(?:,\s*(?:and\s+|or\s+)?|\s+(?:and|or|to|through)\s+)"
_CFR_PART = re.compile(r"\b(\d+)\s+CFR\s+parts?\s+(\d+)\b")
_CFR_SEC = re.compile(rf"\b(\d+)\s+CFR\s+(?:§§?\s*)?({_SEC})({_PATH})")
_SECS = re.compile(rf"§§\s*({_SEC}{_PATH})((?:{_JOIN}{_SEC}{_PATH})*)")
_SEC1 = re.compile(rf"§\s*({_SEC})({_PATH})")
_PARAS = re.compile(r"\bparagraphs?\s+((?:\(\w{1,5}\))+)"
                    r"((?:(?:,\s*(?:and\s+|or\s+)?|\s+(?:and|or|through)\s+)(?:\(\w{1,5}\))+)*)"
                    r",?\s+of\s+this\s+section\b")
_ITEM = re.compile(rf"({_SEC})({_PATH})")
_MARKS = re.compile(r"\((\w{1,5})\)")


def _marks(path: str) -> str:
    return "".join(f"({m})" for m in _MARKS.findall(path))


def cross_refs(p: Provision, section_numbers: set[str]) -> list[CrossRef]:
    """The explicit references of provision `p` in text order (§8.3); `section_numbers` are
    the sections the version of `p` holds."""
    title, part = p.part.split(" CFR ")

    def resolve(t: str, sec: str) -> str:
        if sec.split(".", 1)[0] != part or t != title:
            return "external"
        return "resolved" if sec in section_numbers else "dangling"

    found: list[tuple[int, int, list[CrossRef]]] = []

    def at(a: int, b: int) -> tuple[int, int]:
        return p.start + a, p.start + b

    for m in _CFR_PART.finditer(p.text):
        same = (m.group(1), m.group(2)) == (title, part)
        found.append((m.start(), m.end(), [CrossRef(
            m.group(0), *at(m.start(), m.end()), f"{m.group(1)} CFR part {m.group(2)}",
            "resolved" if same else "external")]))
    for m in _CFR_SEC.finditer(p.text):
        sec = m.group(2)
        found.append((m.start(), m.end(), [CrossRef(
            m.group(0), *at(m.start(), m.end()), f"{m.group(1)} CFR {sec}{_marks(m.group(3))}",
            resolve(m.group(1), sec))]))
    for m in _SECS.finditer(p.text):
        refs = []
        for i, it in enumerate(_ITEM.finditer(p.text, m.start(), m.end())):
            a = m.start() if i == 0 else it.start()
            sec = it.group(1)
            refs.append(CrossRef(p.text[a:it.end()], *at(a, it.end()),
                                 f"{title} CFR {sec}{_marks(it.group(2))}", resolve(title, sec)))
        found.append((m.start(), m.end(), refs))
    for m in _SEC1.finditer(p.text):
        sec = m.group(1)
        found.append((m.start(), m.end(), [CrossRef(
            m.group(0), *at(m.start(), m.end()), f"{title} CFR {sec}{_marks(m.group(2))}",
            resolve(title, sec))]))
    for m in _PARAS.finditer(p.text):
        first = tuple(_MARKS.findall(m.group(1)))
        paths = [first] + [marker_path(first, g.group(0)) for g in
                           re.finditer(r"(?:\(\w{1,5}\))+", m.group(2))]
        own = "resolved" if p.section in section_numbers else "dangling"
        refs = [CrossRef(m.group(0), *at(m.start(), m.end()),
                         f"{title} CFR {p.section}" + "".join(f"({x})" for x in path), own)
                for path in paths]
        found.append((m.start(), m.end(), refs))
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
    modal = [p for p in provs if p.modality is not None and full[p.start:p.end] == p.text]
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
                for x in cross_refs(p, sections)],
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
