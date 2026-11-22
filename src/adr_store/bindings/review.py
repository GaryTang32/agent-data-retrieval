"""The binding review (Phase 4 spec §12.5, P12, P48; builder note 16; preflight C3; Task 17).

There is no human reviewer. Each section whose draws have bindings goes to one review call
(`binding-review@1`, the review profile; `max_tokens` 2000 through `tables.extract._call`, so
the P21 retry and failure rules hold). A binding is reviewed in the section of the **draw** it
targets: a draw's specific rules, its § 117.5 general duty and its § 117.31(b) emergency
basis go together in that draw's section call, so no call carries every draw's emergency
basis and the pool's sections need at most 30 calls (builder note 16, amended after Task 17).
Only `analysed` bindings (tested and analysed) are sent; a section whose bindings are all
rejected gets no call.

**The message** (`review_message`), built by code: the section, the rule cards' verbatim text
with their provision ids (the section's own, every card holding a quote, and always the
§ 117.5 and § 117.31(b) cards, so the general duty and the emergency basis are judged in
context), then each binding with a label (`[B<n>] binding <id>`), its rule id,
version and effect, its draw, the plain-English sentence code rendered (`derivation`), what it
overrides, and each parameter with its quote. The flags of Task 15 are surfaced on their own
lines and the prompt asks the reviewer to judge them: `FLAG sentence_qualifiers (...)` (the
sentence states qualifiers the parameters lack), `FLAG sentence_conditions (...)` ("only",
"unless", "notice" around a closed window), each quoting the **full sentence** of every
parameter quote of the binding (`enrich.read_sentence` over the card holding the quote), and
`FLAG auto_accepted (...)`.

**The reply** is `{"verdicts": [{"binding": "B1", "verdict": "approve"|"reject", "reason"}]}`.
A binding with no verdict (none given, two that differ, neither approve nor reject, no reason,
an input rejection) is not approved. A reply still unparseable after the retry at repeat 1
(the usual sign of a reply cut at `max_tokens`) gives every binding of the section the reason
`review_unparseable`, so its draws are rejected and counted in the report
(`review_unparseable`: sections, draws, bindings), never dropped silently; replies whose
output reached `max_tokens` are counted too (`replies_at_max_tokens`).

**Draws** are keyed by document and target (`checks._draw_key`) over all the bindings given:
only a draw whose every binding is `analysed` is reviewed; a draw mixing statuses is rejected
whole (`incomplete_draw`, P48), never reviewed on a subset. A section whose reply names a
served model other than the review profile's (`claude_code_opus`, the only profile `adr units
review` takes) gives no verdict (`served_model_mismatch`).

**Sign-off** (`review_all`). The record is stored on the binding (validated): its `review`
keeps the compiler's flags and gains `verdict`, `reason`, `prompt_version` and `served_model`,
and `verifier` is `model-review:claude_code_opus` (never a human sign-off). A draw passes or
fails as a whole (P48): when every binding of a draw is approved the draw is `signed_off`;
when any is rejected or has no verdict every binding of the draw is `rejected`, the approved
ones naming the bindings that blocked them (`blocked_by`); a draw only partly reviewed (a
`--limit` run) stays `analysed`. Nothing else changes, so ids and versions stay.
"""

from __future__ import annotations

import functools
import json
from collections import Counter
from importlib import resources
from pathlib import Path
from typing import Any

from adr_eval.llm import ModelOutputError, parse_json_recovering
from adr_store.bindings.checks import _draw_key, _under, _with
from adr_store.bindings.compile import EMERGENCY, GENERAL_DUTY
from adr_store.bindings.dsl import Binding
from adr_store.bindings.enrich import _Recorder, in_section, read_sentence, section_key
from adr_store.tables import extract as ex
from adr_store.units.envelope import Unit

__all__ = ["FLAGS", "INCOMPLETE", "MAX_TOKENS", "PROMPT_VERSION", "REVIEW_PROFILE",
           "SERVED_MISMATCH", "UNPARSEABLE", "VERIFIER", "flagged", "review_all",
           "models_file_model", "review_message", "review_model", "review_section",
           "review_sections",
           "served_problem", "system_prompt", "target_section", "use_models_file",
           "verdict_records"]

PROMPT_VERSION = "binding-review@1"
MAX_TOKENS = 2000
REVIEW_PROFILE = "claude_code_opus"     # the only profile `adr units review` takes (I2)
VERIFIER = f"model-review:{REVIEW_PROFILE}"
FLAGS = ("sentence_qualifiers", "sentence_conditions")
VERDICTS = ("approve", "reject")
UNPARSEABLE = "review_unparseable"
INCOMPLETE = "incomplete_draw"
SERVED_MISMATCH = "served_model_mismatch"
_FLAG_TEXT = {
    "sentence_qualifiers": "the sentence states qualifiers the parameters lack",
    "sentence_conditions": "the sentence says only, unless or notice around the window",
}


@functools.cache
def system_prompt() -> str:
    """The review prompt (`prompts/binding_review.txt`), naming its version on line 1."""
    return resources.files("adr_store.units").joinpath(
        "prompts/binding_review.txt").read_text(encoding="utf-8")


_PINNED: list[str] = []      # the review model read once by `use_models_file` (the gate)


def review_model() -> str:
    """The model of the review profile (`REVIEW_PROFILE` in config/models.json, or in the file
    `use_models_file` read): a served model a provider reports for a review must be this
    one."""
    return _PINNED[0] if _PINNED else _configured_review_model()


@functools.cache
def _configured_review_model() -> str:
    from adr_eval import runner

    config = runner.load_config()
    profiles = runner.load_profiles(runner.REPO_ROOT / config.get("models", runner.MODELS_PATH))
    return profiles[REVIEW_PROFILE]["model"]


def models_file_model(path: Path) -> str:
    """The review profile's model in the models file `path`; ValueError when the file is
    missing, unreadable, not JSON, lacks the profile or names a placeholder model."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        model = data["profiles"][REVIEW_PROFILE]["model"]
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError) as e:
        raise ValueError(f"{path}: no {REVIEW_PROFILE} model ({type(e).__name__})") from e
    if not isinstance(model, str) or not model or model.startswith("<set"):
        raise ValueError(f"{path}: the {REVIEW_PROFILE} model is not set")
    return model


def use_models_file(path: Path) -> str:
    """Read the review profile's model from `path` once and use it for every later check in
    this process (the gate reads it at startup, so a missing or invalid file fails then, not
    at each request); the model. ValueError as `models_file_model`."""
    model = models_file_model(path)
    _PINNED[:] = [model]
    return model


def served_problem(served: str | None) -> str | None:
    """Why a review record's served model (comma-joined, or None when the provider reported
    none) is not the review profile's model, or None."""
    if served is None:
        return None
    other = sorted(set(served.split(",")) - {review_model()})
    return f"served model {', '.join(other)} != {review_model()}" if other else None


def flagged(b: Binding) -> bool:
    """Whether the binding carries a flag the review must surface (`FLAGS`)."""
    return any(b.review.get(f) for f in FLAGS)


# -- the message ---------------------------------------------------------------------------------

def _holder(cards: list[Unit], doc_id: str, start: int, end: int) -> Unit | None:
    """The first card (document order) of `doc_id` whose span holds [start, end)."""
    holding = [c for c in cards if c.doc_id == doc_id and c.source_refs
               and c.source_refs[0].start <= start and end <= c.source_refs[0].end]
    return min(holding, key=lambda c: c.source_refs[0].start) if holding else None


def _span(prov: Any) -> tuple[int, int] | None:
    span = prov.get("span") if isinstance(prov, dict) else None
    if isinstance(span, list) and len(span) == 2 and all(isinstance(x, int) for x in span):
        return span[0], span[1]
    return None


def _sentences(b: Binding, cards: list[Unit]) -> list[str]:
    """The full sentence of every parameter quote of `b`, distinct, in parameter order; a quote
    no card holds is named instead."""
    out: list[str] = []
    for prov in b.params_prov.values():
        span = _span(prov)
        if span is None:
            continue
        c = _holder(cards, b.doc_id, *span)
        if c is None:
            item = f'unavailable (no rule card holds the quote "{prov.get("quote")}")'
        else:
            offset = c.source_refs[0].start
            s = read_sentence(c.body["text"], span[0] - offset, span[1] - offset).sentence
            item = f'full sentence: "{s}"'
        if item not in out:
            out.append(item)
    return out


def _order(bindings: list[Binding]) -> list[Binding]:
    def key(b: Binding):
        sel = b.target.get("selector", {})
        return (b.rule_id, section_key(str(sel.get("section"))), str(sel.get("draw")),
                b.effect, b.binding_id)

    return sorted(bindings, key=key)


def _labels(bindings: list[Binding]) -> dict[str, str]:
    return {b.binding_id: f"B{i}" for i, b in enumerate(_order(bindings), 1)}


def _card_line(c: Unit) -> str:
    return f"[{c.canonical_ref}] {c.body.get('text', '')}"


def review_message(section: str, cards: list[Unit], bindings: list[Binding]) -> str:
    """The review call's user message for `section` (module text): every card of `cards`
    verbatim in document order, then every binding of `bindings` with its parameters, quotes,
    rendered sentence and flags."""
    labels = _labels(bindings)
    lines = [f"SECTION § {section}", "", "RULE CARDS (verbatim):"]
    shown = sorted({c.unit_id: c for c in cards}.values(),
                   key=lambda c: (c.doc_id, c.source_refs[0].start if c.source_refs else 0))
    lines += [_card_line(c) for c in shown] or ["(none)"]
    lines += ["", f"BINDINGS ({len(bindings)}):"]
    for b in _order(bindings):
        sel = b.target.get("selector", {})
        lines.append(f"[{labels[b.binding_id]}] binding {b.binding_id}")
        lines.append(f"  rule: {b.rule_id} version {b.rule_version}, effect {b.effect}")
        lines.append(f"  draw: § {sel.get('section')} draw {sel.get('draw')}")
        lines.append(f"  sentence: {b.derivation}")
        if b.overrides:
            names = [labels.get(x, x[:12]) for x in b.overrides]
            lines.append(f"  overrides {len(names)} forbid(s): {', '.join(names)}")
        if b.params_prov:
            lines.append("  parameters:")
            for key, prov in b.params_prov.items():
                lines.append(f"    {key} = {json.dumps(prov.get('value'))} quote: "
                             f"\"{prov.get('quote')}\"")
        sentences = _sentences(b, cards) if flagged(b) else []
        for flag in FLAGS:
            if b.review.get(flag):
                what = ", ".join(b.review[flag])
                lines.append(f"  FLAG {flag} ({what}) on binding {b.binding_id}: "
                             f"{_FLAG_TEXT[flag]}; judge it against the "
                             + "; ".join(sentences or ["(no quote)"]))
        if b.review.get("auto_accepted"):
            lines.append(f"  FLAG auto_accepted ({', '.join(b.review['auto_accepted'])}) on "
                         f"binding {b.binding_id}: a value code did not find in its quote; "
                         f"check it against the quote")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


# -- one call ------------------------------------------------------------------------------------

def _parse(text: str) -> dict:
    reply, _ = parse_json_recovering(text, ("verdicts",))
    verdicts = reply.get("verdicts")
    if not isinstance(verdicts, list) or not all(isinstance(v, dict) for v in verdicts):
        raise ModelOutputError('expected {"verdicts": [{"binding", "verdict", "reason"}, ...]}')
    return reply


def _no_verdict(why: str) -> dict:
    return {"verdict": None, "reason": f"no verdict: {why}"}


def _read_verdicts(reply: dict | None, outcome: str, labels: dict[str, str]) -> dict[str, dict]:
    if reply is None:
        v = _no_verdict("the input was rejected") if outcome == "model_error" else \
            {"verdict": None, "reason": UNPARSEABLE}
        return {bid: dict(v) for bid in labels}
    given: dict[str, list[dict]] = {}
    for v in reply["verdicts"]:
        given.setdefault(str(v.get("binding")), []).append(v)
    out = {}
    for bid, label in labels.items():
        entries = given.get(label, [])
        if not entries:
            out[bid] = _no_verdict("the reply gave none")
            continue
        pairs = {(e.get("verdict"), e.get("reason")) for e in entries
                 if isinstance(e.get("verdict"), str) and isinstance(e.get("reason"), str)}
        verdicts = {e.get("verdict") for e in entries}
        if len(verdicts) > 1:
            out[bid] = _no_verdict("the reply gave verdicts that differ")
        elif not verdicts <= set(VERDICTS):
            out[bid] = _no_verdict(f"{entries[0].get('verdict')!r} is neither approve nor "
                                   "reject")
        elif not pairs or not all(r.strip() for _, r in pairs):
            out[bid] = _no_verdict("the reply gave no reason")
        else:
            verdict, reason = sorted(pairs)[0]
            out[bid] = {"verdict": verdict, "reason": reason.strip()}
    return out


def _review(section: str, cards: list[Unit], bindings: list[Binding], client
            ) -> tuple[dict[str, dict], str, Counter, tuple[str, ...]]:
    labels = _labels(bindings)
    rec = _Recorder(client)
    reply, outcome, counts = ex._call(rec, system_prompt(), review_message(section, cards,
                                                                           bindings),
                                      _parse, max_tokens=MAX_TOKENS)
    served = tuple(sorted({c.served_model for c in rec.completions if c.served_model}))
    counts["at_max_tokens"] = sum(c.output_tokens >= MAX_TOKENS for c in rec.completions)
    return _read_verdicts(reply, outcome, labels), outcome, counts, served


def review_section(section: str, cards: list[Unit], bindings: list[Binding], client
                   ) -> dict[str, dict]:
    """One review call for `section` (module text): binding id -> {"verdict", "reason"}, with
    verdict None where the reply gives none that counts."""
    return _review(section, cards, bindings, client)[0]


# -- the whole review ----------------------------------------------------------------------------

def target_section(b: Binding) -> str:
    """The section of the draw a binding targets (its selector's `section`)."""
    return str(b.target.get("selector", {}).get("section"))


def review_sections(bindings: list[Binding]) -> list[str]:
    """The sections a review calls, in order: the sections of the draws the `analysed`
    bindings target."""
    return sorted({target_section(b) for b in bindings if b.status == "analysed"},
                  key=section_key)


def _cards_for(section: str, bindings: list[Binding], cards: list[Unit]) -> list[Unit]:
    """The cards a section's message shows, in the bindings' documents: the section's own
    cards, the § 117.5 and § 117.31(b) cards, and every card holding a parameter quote of its
    bindings."""
    docs = {b.doc_id for b in bindings}
    out = {c.unit_id: c for c in cards if c.doc_id in docs and (
        in_section(c.canonical_ref, section) or _under(c.canonical_ref, GENERAL_DUTY)
        or _under(c.canonical_ref, EMERGENCY))}
    for b in bindings:
        for prov in b.params_prov.values():
            span = _span(prov)
            c = _holder(cards, b.doc_id, *span) if span else None
            if c is not None:
                out.setdefault(c.unit_id, c)
    return list(out.values())


def review_all(store, bindings: list[Binding], client, *, limit: int | None = None,
               cards: list[Unit] | None = None) -> tuple[list[Binding], dict]:
    """(the bindings in order, with the review's statuses and records, the report) (module
    text). Draws are keyed by document and target (`checks._draw_key`) over **all** the
    bindings: a draw is reviewed only when every one of its bindings is `analysed`; a draw that
    mixes statuses (P48 forbids it) is rejected whole with reason `incomplete_draw`, and a
    draw wholly rejected is left as it is. A section whose reply names a served model other
    than the review profile's gives its bindings no verdict (`served_model_mismatch`, the
    model's verdict kept beside it). `cards` are the rule cards the messages quote (default:
    the store's newest 33 CFR 117 cards, built by code; `store` is read only then); with
    `limit` only the first sections are reviewed (the canary)."""
    draws: dict[str, list[Binding]] = {}
    for b in bindings:
        draws.setdefault(_draw_key(b), []).append(b)
    reviewable = {k for k, bs in draws.items() if all(b.status == "analysed" for b in bs)}
    incomplete = {k for k, bs in draws.items() if k not in reviewable
                  and not all(b.status == "rejected" for b in bs)}
    eligible = [b for b in bindings if _draw_key(b) in reviewable]
    sections = review_sections(eligible)
    chosen = sections if limit is None else sections[:limit]
    if cards is None and chosen:
        from adr_store.bindings.enrich import section_cards

        cards = section_cards(store)[1]
    groups: dict[str, list[Binding]] = {}
    for b in eligible:
        groups.setdefault(target_section(b), []).append(b)
    verdicts: dict[str, dict] = {}
    served_of: dict[str, str | None] = {}
    counts, outcomes, served_all = Counter(), Counter(), set()
    per_section = []
    mismatched = Counter()
    for s in chosen:
        bs = groups[s]
        got, outcome, c, served = _review(s, _cards_for(s, bs, cards), bs, client)
        if served_problem(",".join(served) or None):
            mismatched["sections"] += 1
            mismatched["bindings"] += len(got)
            got = {bid: {"verdict": None, "reason": SERVED_MISMATCH,
                         "model_verdict": v["verdict"], "model_reason": v["reason"]}
                   for bid, v in got.items()}
        verdicts.update(got)
        served_of.update({b.binding_id: ",".join(served) or None for b in bs})
        counts += c
        outcomes[outcome] += 1
        served_all.update(served)
        tally = Counter(v["verdict"] for v in got.values())
        per_section.append({"section": s, "bindings": len(bs),
                            "flagged": sum(flagged(b) for b in bs),
                            "approved": tally["approve"], "rejected": tally["reject"],
                            "no_verdict": tally[None], "outcome": outcome})
    updated: dict[str, Binding] = {}
    blocked = 0
    for key in incomplete:
        for b in draws[key]:
            updated[b.binding_id] = _with(b, status="rejected",
                                          review={**b.review, "reason": INCOMPLETE})
    for key in reviewable:
        draw = draws[key]
        bad = [b.binding_id for b in draw if b.binding_id in verdicts
               and verdicts[b.binding_id]["verdict"] != "approve"]
        whole = all(b.binding_id in verdicts for b in draw)
        for b in draw:
            v = verdicts.get(b.binding_id)
            if v is None and not bad:
                continue
            review = dict(b.review)
            update: dict[str, Any] = {}
            if v is not None:
                review.update({**v, "prompt_version": PROMPT_VERSION,
                               "served_model": served_of[b.binding_id]})
                update["verifier"] = VERIFIER
            if bad and b.binding_id not in bad:
                review["blocked_by"] = sorted(bad)
                blocked += 1
            status = "rejected" if bad else "signed_off" if whole else b.status
            updated[b.binding_id] = _with(b, status=status, review=review, **update)
    out = [updated.get(b.binding_id, b) for b in bindings]
    tally = Counter(v["verdict"] for v in verdicts.values())
    statuses = Counter(b.status for b in out)
    unparseable = [b for b in eligible if verdicts.get(b.binding_id, {}).get("reason")
                   == UNPARSEABLE]
    report = {
        "prompt_version": PROMPT_VERSION, "max_tokens": MAX_TOKENS, "limit": limit,
        "review_profile": REVIEW_PROFILE, "review_model": review_model(),
        "sections_total": len(sections), "sections_reviewed": len(chosen),
        "calls": {k: counts[k] for k in ("made", "cached", "failed")},
        "served_models": sorted(served_all), "outcomes": dict(sorted(outcomes.items())),
        "replies_at_max_tokens": counts["at_max_tokens"],
        "review_unparseable": {
            "sections": sum(s["outcome"] == "unparseable" for s in per_section),
            "draws": len({_draw_key(b) for b in unparseable}), "bindings": len(unparseable)},
        "served_by_another_model": {k: mismatched[k] for k in ("sections", "bindings")},
        "incomplete_draws": {"draws": len(incomplete),
                             "bindings": sum(len(draws[k]) for k in incomplete)},
        "flagged": sum(s["flagged"] for s in per_section), "sections": per_section,
        "bindings": {"candidates": len(bindings), "eligible": len(eligible),
                     "approved": tally["approve"], "rejected_by_review": tally["reject"],
                     "no_verdict": tally[None], "blocked": blocked,
                     "not_reviewed": sum(b.binding_id not in verdicts for b in eligible),
                     "signed_off": statuses["signed_off"], "rejected": statuses["rejected"]}}
    return out, report


def verdict_records(bindings: list[Binding]) -> list[dict]:
    """One record per reviewed or rejected-at-review binding (M2): id, draw, rule, status,
    verdict, reason, served model and what blocked it; for the local review file."""
    out = []
    for b in bindings:
        r = b.review
        if "verdict" not in r and r.get("reason") is None:
            continue
        sel = b.target.get("selector", {})
        out.append({"binding_id": b.binding_id, "doc_id": b.doc_id,
                    "section": sel.get("section"), "draw": sel.get("draw"),
                    "rule_id": b.rule_id, "effect": b.effect, "status": b.status,
                    "verdict": r.get("verdict"), "reason": r.get("reason"),
                    "model_verdict": r.get("model_verdict"),
                    "model_reason": r.get("model_reason"),
                    "served_model": r.get("served_model"),
                    "blocked_by": r.get("blocked_by", [])})
    return sorted(out, key=lambda x: x["binding_id"])
