"""Temporal probes on gov (Phase 2 spec §10.2, criteria A1 and A2): built from the corpus, the
golden items and the store's applicability overlay; run through `adr_store.tools.Tools`.

- T1: every `policy_asof` item with a date, `as_of` = the item's. Pass: no chunk (hit or
  alternate) of a document not in force on `as_of`.
- T2: every changed section (`version_pairs`), query = its heading ("§ N Title."). Default
  mode, pass: no chunk of a superseded document; the head version's section rank is reported.
  `as_of` = the older version's date, pass: no chunk not in force on `as_of` (so none of
  another version); the old section's Recall@10 and other-version chunks are reported.
- T3: every removed section (`removed_sections`), query = its heading. Default mode as T2;
  `as_of` = its version's date, pass as T2, the removed section's Recall@10 reported.
- T4: every golden question, default mode. Pass: no chunk of a superseded document.
- T5: every Federal Register and IRM document, query = its title, `as_of` = `valid_from` - 1
  day. Pass: absent from `search`, from `grep` of a 30-character substring of its text (an
  untruncated result), `read` refused because it is not in force on that date (the refusal
  names its `valid_from` and the date; any other refusal fails), and the same `read` without
  the date succeeds (the control: the document is readable at all).

"In force on D" is read from the envelope (`valid_from <= D`, `valid_to` null or `D <
valid_to`, not a proposed rule), independently of the filter code it checks. Search uses the
default top 10 and dedup on (`dedup=True`, passed explicitly; `dedup=False` to run without).
T5 also reports controls without the date: the title's search finds the document, the grep
finds the substring in it. The substring is chosen by a seeded hash (`SEED`) of the doc id:
the first 30-character window from that offset (wrapping) with no line break, no space at
either end and at least three words.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from adr_eval.corpora.base import LoadedCorpus
from adr_eval.corpora.gov import GovAdapter
from adr_eval.models import GoldenItem
from adr_eval.probes import SEED
from adr_store.applicability import Applicability, Envelope, family_of, load_overlay

SETS = ("T1", "T2", "T3", "T4", "T5")
SPEC_SIZES = {"T1": 40, "T2": 189, "T3": 145, "T4": 297, "T5": 171}  # spec §4.1, §10.2
SUBSTRING = 30
_IRM_TITLE = re.compile(rb"<title>\s*(.*?)\s*</title>", re.DOTALL | re.IGNORECASE)
_IRM_SUFFIX = " | Internal Revenue Service"


@dataclass(frozen=True)
class Probe:
    probe_id: str
    set: str  # T1..T5
    mode: str  # "default" or "as_of"
    query: str
    as_of: str | None
    target: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# -- building ------------------------------------------------------------------------------


def _title(loaded: LoadedCorpus, doc) -> str:
    text = loaded.docs[doc.doc_id].text
    if family_of(doc.uri) == "fr":
        title = json.loads(text).get("title")
        if title:
            return title
    else:
        m = _IRM_TITLE.search((loaded.root / doc.path).read_bytes())
        if m:
            title = " ".join(m.group(1).decode("utf-8", "replace").split())
            return title.removesuffix(_IRM_SUFFIX).strip()
    return text.strip().split("\n", 1)[0][:200]


def substring(text: str, doc_id: str, n: int = SUBSTRING) -> str:
    """A deterministic `n`-character window of `text` (see the module docstring)."""
    last = len(text) - n
    if last < 0:
        return text
    start = int(hashlib.sha256(f"{SEED}:{doc_id}".encode()).hexdigest(), 16) % (last + 1)
    for k in range(last + 1):
        i = (start + k) % (last + 1)
        w = text[i:i + n]
        if "\n" not in w and w.strip() == w and len(w.split()) >= 3:
            return w
    return text[start:start + n]


def build(loaded: LoadedCorpus, items: list[GoldenItem],
          applicability: Applicability) -> list[Probe]:
    """The T1-T5 probes of the gov corpus, in set order (deterministic). `applicability` is
    the overlay of the store the probes run on (T5 reads `valid_from` from it)."""
    adapter = GovAdapter()
    chains = adapter.ecfr_chains(loaded)
    chain_of = {d.doc_id: (f"ecfr:{t}:{p}", versions)
                for (t, p), versions in chains.items() for d in versions}
    spans: dict[str, dict] = {}

    def spans_of(d):
        if d.doc_id not in spans:
            spans[d.doc_id] = adapter.section_spans(loaded, d)
        return spans[d.doc_id]

    probes: list[Probe] = []
    for item in sorted(items, key=lambda i: i.id):
        if item.qtype == "policy_asof" and item.as_of is not None:
            probes.append(Probe(f"T1:{item.id}", "T1", "as_of", item.question,
                                item.as_of.isoformat(), {"item_id": item.id}))
    for old, _new in adapter.version_pairs(loaded):
        number = old.uri.rsplit("#", 1)[1]
        chain, versions = chain_of[old.doc_id]
        old_doc = next(d for d in versions if d.doc_id == old.doc_id)
        start, end, heading = spans_of(old_doc)[number]
        head = versions[-1]
        head_span = spans_of(head).get(number)
        target = {"chain": chain, "section": number, "old_doc": old.doc_id,
                  "old_span": [start, end], "new_doc": _new.doc_id, "head_doc": head.doc_id,
                  "head_span": None if head_span is None else list(head_span[:2])}
        pid = f"T2:{chain}:{number}:{old.source_version}"
        probes.append(Probe(f"{pid}:default", "T2", "default", heading, None, target))
        probes.append(Probe(f"{pid}:as_of", "T2", "as_of", heading, old.source_version,
                            target))
    for section, start, end in adapter.removed_sections(loaded):
        number = section.uri.rsplit("#", 1)[1]
        chain, _ = chain_of[section.doc_id]
        heading = section.text.split("\n", 1)[0]
        target = {"chain": chain, "section": number, "doc": section.doc_id,
                  "span": [start, end]}
        pid = f"T3:{chain}:{number}:{section.source_version}"
        probes.append(Probe(f"{pid}:default", "T3", "default", heading, None, target))
        probes.append(Probe(f"{pid}:as_of", "T3", "as_of", heading, section.source_version,
                            target))
    for item in sorted(items, key=lambda i: i.id):
        probes.append(Probe(f"T4:{item.id}", "T4", "default", item.question, None,
                            {"item_id": item.id}))
    for d in sorted(loaded.manifest.documents, key=lambda d: d.doc_id):
        family = family_of(d.uri)
        if family not in ("fr", "irm"):
            continue
        valid_from = applicability.records[d.doc_id].valid_from
        if valid_from is None:
            raise ValueError(f"{d.doc_id}: no valid_from in the applicability overlay")
        probes.append(Probe(
            f"T5:{d.doc_id}", "T5", "as_of", _title(loaded, d),
            (valid_from - timedelta(days=1)).isoformat(),
            {"doc": d.doc_id, "family": family, "valid_from": valid_from.isoformat(),
             "grep": substring(loaded.docs[d.doc_id].text, d.doc_id)}))
    return probes


# -- running -------------------------------------------------------------------------------


def _in_force(env: Envelope, d: date) -> bool:
    return (env.valid_from is not None and env.valid_from <= d
            and (env.valid_to is None or d < env.valid_to) and env.status != "proposed_rule")


def _overlaps(hit, doc_id: str, span) -> bool:
    return span is not None and hit.doc_id == doc_id and hit.char_start < span[1] and \
        span[0] < hit.char_end


def _returned(res) -> list[tuple[str, str]]:
    """(chunk id, doc id) of every hit and alternate."""
    out = []
    for h in res.hits:
        out.append((h.chunk_id, h.doc_id))
        out += [(a.chunk_id, a.doc_id) for a in h.alternates]
    return out


def _search_probe(p: Probe, tools, records: dict[str, Envelope], dedup: bool) -> dict:
    filters = {} if p.as_of is None else {"as_of": p.as_of}
    res = tools.search(p.query, filters=filters, dedup=dedup)
    returned = _returned(res)
    if p.as_of is None:
        bad = [(c, d) for c, d in returned if records[d].superseded_by is not None]
    else:
        day = date.fromisoformat(p.as_of)
        bad = [(c, d) for c, d in returned if not _in_force(records[d], day)]
    out = {"n_hits": len(res.hits), "n_returned": len(returned),
           "offending": [{"chunk_id": c, "doc_id": d} for c, d in bad[:5]],
           "n_offending": len(bad), "pass": not bad}
    t = p.target
    if p.set == "T2" and p.mode == "default":
        out["head_rank"] = next((h.rank for h in res.hits
                                 if _overlaps(h, t["head_doc"], t["head_span"])), None)
        out["head_section_absent"] = t["head_span"] is None
    if p.set == "T2" and p.mode == "as_of":
        out["other_version_chunks"] = sum(
            records[d].chain_id == t["chain"] and d != t["old_doc"] for _, d in returned)
        out["found"] = any(_overlaps(h, t["old_doc"], t["old_span"]) for h in res.hits)
    if p.set == "T3":
        out["found"] = any(_overlaps(h, t["doc"], t["span"]) for h in res.hits)
    return out


def _absence_probe(p: Probe, tools, dedup: bool) -> dict:
    from adr_store.tools import ToolError

    doc, pattern = p.target["doc"], re.escape(p.target["grep"])
    dated = {"as_of": p.as_of}
    search = tools.search(p.query, filters=dated, dedup=dedup)
    search_absent = all(d != doc for _, d in _returned(search))
    grep = tools.grep(pattern, filters=dated)
    grep_absent = not grep.truncated and all(m.doc_id != doc for m in grep.matches)
    try:
        tools.read(doc, filters=dated)
        refusal = None
    except ToolError as e:
        refusal = str(e)
    # refused because the document is not in force on the date, not for any other reason
    span = f"in force from {p.target['valid_from']}"
    read_refused = refusal is not None and span in refusal and \
        f"not in force on {p.as_of}" in refusal
    try:
        control_read_ok = tools.read(doc).doc_id == doc
    except ToolError:
        control_read_ok = False
    control = tools.search(p.query, dedup=dedup)
    control_grep = tools.grep(pattern)
    return {"search_absent": search_absent, "grep_absent": grep_absent,
            "grep_truncated": grep.truncated, "read_refused": read_refused,
            "read_refusal": refusal, "control_read_ok": control_read_ok,
            "control_search_found": any(d == doc for _, d in _returned(control)),
            "control_grep_found": any(m.doc_id == doc for m in control_grep.matches),
            "pass": search_absent and grep_absent and read_refused and control_read_ok}


def run(probes: list[Probe], tools, caller: str | None = None, *, dedup: bool = True) -> dict:
    """Run the probes through `tools` (an `adr_store.tools.Tools`); per-probe outcomes and a
    summary per set and mode. `caller` needs the ACL layer (Phase 2B), which does not exist
    yet: any caller is refused."""
    if caller is not None:
        raise ValueError(f"caller {caller!r}: searching as a caller needs the ACL layer "
                         f"(Phase 2B); run without --as")
    overlay = load_overlay(tools.store_path, tools.snapshot)
    if overlay is None:
        raise ValueError(f"{tools.store_path}: no applicability overlay; run `adr "
                         f"applicability derive`")
    outcomes = []
    for p in probes:
        o = _absence_probe(p, tools, dedup) if p.set == "T5" else \
            _search_probe(p, tools, overlay.records, dedup)
        outcomes.append({**p.to_dict(), **o})
    return {"dedup": dedup, "applicability": overlay.overlay_id, "summary": summarize(outcomes),
            "probes": outcomes}


def _mean(xs: list) -> float | None:
    return sum(xs) / len(xs) if xs else None


def summarize(outcomes: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for o in outcomes:
        out.setdefault(o["set"], {}).setdefault(o["mode"], []).append(o)
    summary: dict[str, dict] = {}
    for name in SETS:
        for mode, rows in out.get(name, {}).items():
            b = {"n": len(rows), "passed": sum(r["pass"] for r in rows),
                 "failed": [r["probe_id"] for r in rows if not r["pass"]]}
            if name != "T5":
                b["offending_chunks"] = sum(r["n_offending"] for r in rows)
            if name == "T2" and mode == "default":
                ranks = [r["head_rank"] for r in rows if r["head_rank"] is not None]
                b.update({"head_found@10": len(ranks), "head_rank_mean": _mean(ranks),
                          "head_section_absent": sum(r["head_section_absent"] for r in rows)})
            if name == "T2" and mode == "as_of":
                b.update({"other_version_chunks": sum(r["other_version_chunks"] for r in rows),
                          "recall@10": _mean([float(r["found"]) for r in rows])})
            if name == "T3":
                b["recall@10"] = _mean([float(r["found"]) for r in rows])
            if name == "T5":
                for k in ("search_absent", "grep_absent", "grep_truncated", "read_refused",
                          "control_read_ok", "control_search_found", "control_grep_found"):
                    b[k] = sum(r[k] for r in rows)
            summary.setdefault(name, {})[mode] = b
    return summary


def render_markdown(data: dict) -> str:
    cfg, s = data["config"], data["summary"]
    out = ["# Temporal probes (gov)", "",
           f"Store `{cfg['store']}` (snapshot `{cfg['snapshot'][:12]}`), index "
           f"`{cfg['index'][:12]}`, applicability overlay `{cfg['applicability'][:12]}`, dedup "
           f"{'on' if cfg['dedup'] else 'off'}. Seed {cfg['seed']}. No model calls.", "",
           *([] if cfg.get("index_phase1", True) else [
               f"> **Warning:** the active index ({cfg['index_system']}) is not the recorded "
               f"Phase 1 p1-struct-bc index: an other index, probed with "
               f"--allow-other-index.", ""]),
           "| set | mode | probes (spec) | passed | failed | figures |",
           "|---|---|---|---|---|---|"]
    for name, modes in s.items():
        for mode, b in modes.items():
            figures = ", ".join(f"{k} {v:.3f}" if isinstance(v, float) else f"{k} {v}"
                                for k, v in b.items() if k not in ("n", "passed", "failed"))
            out.append(f"| {name} | {mode} | {b['n']} ({cfg['spec_sizes'][name]}) | "
                       f"{b['passed']} | {len(b['failed'])} | {figures} |")
    return "\n".join(out) + "\n"
