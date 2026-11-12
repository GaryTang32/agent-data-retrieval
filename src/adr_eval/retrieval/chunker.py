"""Structure-free recursive chunker and the shared tokenizer."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

from adr_eval.corpora.base import Document

CHUNKER_CONFIG = {"max_tokens": 400, "separators": ["\n\n", "\n", ". ", " "], "overlap": 0}
TOKENIZER_CONFIG = {
    "normalize": "NFKC",
    "lower": True,
    "pattern": r"[a-z0-9]+",
    "stopwords": "adr_eval/retrieval/stopwords_en.txt",
}

_TOKEN_RE = re.compile(TOKENIZER_CONFIG["pattern"])


@lru_cache(maxsize=1)
def _stopwords() -> frozenset[str]:
    text = resources.files("adr_eval.retrieval").joinpath("stopwords_en.txt").read_text("utf-8")
    return frozenset(w.strip() for w in text.splitlines() if w.strip())


def tokenize(text: str, drop_stopwords: bool = True) -> list[str]:
    toks = _TOKEN_RE.findall(unicodedata.normalize("NFKC", text).lower())
    if drop_stopwords:
        sw = _stopwords()
        return [t for t in toks if t not in sw]
    return toks


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    char_start: int
    char_end: int
    text: str


def make_chunk_id(doc_id: str, char_start: int, char_end: int) -> str:
    return hashlib.sha256(f"{doc_id}:{char_start}:{char_end}".encode()).hexdigest()


def _count(text: str) -> int:
    return len(tokenize(text, drop_stopwords=False))


def _split_spans(text: str, start: int, end: int, sep: str) -> list[tuple[int, int]]:
    """Split [start, end) after each occurrence of `sep`; the spans tile the range exactly."""
    spans, pos = [], start
    while pos < end:
        i = text.find(sep, pos, end)
        nxt = end if i < 0 else i + len(sep)
        spans.append((pos, nxt))
        pos = nxt
    return spans


def _max_cut(text: str, pos: int, end: int, max_tokens: int) -> int:
    """Largest cut in (pos, end] whose slice has <= max_tokens tokens as `tokenize` counts them.

    Counts normalized slices (NFKC, lower), so offsets stay exact in the original text.
    """
    if _count(text[pos:end]) <= max_tokens:
        return end
    lo, hi = pos + 1, end  # slice [pos, lo) is assumed to fit; hi does not
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if _count(text[pos:mid]) <= max_tokens:
            lo = mid
        else:
            hi = mid
    # Normalization can be non-monotonic (combining marks); enforce the limit regardless.
    while lo > pos + 1 and _count(text[pos:lo]) > max_tokens:
        lo -= 1
    return lo


def _leaves(
    text: str, start: int, end: int, seps: list[str], max_tokens: int
) -> list[tuple[int, int, int]]:
    """Recursively split into (start, end, n_tokens) pieces, each within max_tokens."""
    n = _count(text[start:end])
    if n <= max_tokens:
        return [(start, end, n)]
    if not seps:
        # Fixed-size token windows; only reachable for a single over-long separator-free run.
        out, pos = [], start
        while pos < end:
            cut = _max_cut(text, pos, end, max_tokens)
            out.append((pos, cut, _count(text[pos:cut])))
            pos = cut
        return out
    pieces = _split_spans(text, start, end, seps[0])
    if len(pieces) == 1:
        return _leaves(text, start, end, seps[1:], max_tokens)
    out = []
    for s, e in pieces:
        out.extend(_leaves(text, s, e, seps[1:], max_tokens))
    return out


def chunk_document(doc: Document, max_tokens: int = 400) -> list[Chunk]:
    text = doc.text
    if not text.strip():
        return []
    leaves = _leaves(text, 0, len(text), list(CHUNKER_CONFIG["separators"]), max_tokens)
    merged: list[tuple[int, int]] = []
    cur_s = cur_e = cur_n = -1
    for s, e, n in leaves:
        if cur_n >= 0 and cur_n + n <= max_tokens:
            cur_e, cur_n = e, cur_n + n
            continue
        if cur_n >= 0:
            merged.append((cur_s, cur_e))
        cur_s, cur_e, cur_n = s, e, n
    if cur_n >= 0:
        merged.append((cur_s, cur_e))
    chunks = []
    for s, e in merged:
        piece = text[s:e]
        lead = len(piece) - len(piece.lstrip())
        s2, e2 = s + lead, s + len(piece.rstrip())
        if e2 > s2:
            chunks.append(
                Chunk(make_chunk_id(doc.doc_id, s2, e2), doc.doc_id, s2, e2, text[s2:e2])
            )
    return chunks
