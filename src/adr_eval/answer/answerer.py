"""Passage-grounded answerer."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import get_args

from adr_eval.answer._prompts import load_prompt, prompt_hash
from adr_eval.llm import (
    Completion,
    ModelClient,
    ModelOutputError,
    parse_json,
    parse_json_recovering,
)
from adr_eval.models import AnswerKind
from adr_eval.retrieval.chunker import Chunk

__all__ = ["SystemAnswer", "answer_question", "prompt_hash"]

MAX_TOKENS = 800
REQUIRED_KEYS = ("answer", "kind", "citations", "abstain", "confidence")
_KINDS = set(get_args(AnswerKind))


@dataclass
class SystemAnswer:
    value: str | float | list[str] | None
    kind: AnswerKind
    citations: list[str]
    abstain: bool
    confidence: float
    completion: Completion


def _user_message(question: str, as_of: date | None, chunks: list[Chunk]) -> str:
    passages = "\n\n".join(f"[{c.chunk_id}]\n{c.text}" for c in chunks) or "(no passages)"
    parts = [f"Passages:\n\n{passages}", f"Question: {question}"]
    if as_of is not None:
        parts.append(f"Answer as of: {as_of.isoformat()}")
    return "\n\n".join(parts)


def _is_number(x: object) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x)


def _value(kind: str, raw: object) -> str | float | list[str]:
    if kind == "set":
        if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
            raise ModelOutputError("answer for kind 'set' must be a list of strings")
        return raw
    if kind == "number":
        if _is_number(raw):
            return raw  # type: ignore[return-value]
        if isinstance(raw, str):
            try:
                float(raw.replace(",", ""))
            except ValueError as e:
                raise ModelOutputError("answer for kind 'number' is not numeric") from e
            return raw
        raise ModelOutputError("answer for kind 'number' is not numeric")
    if not isinstance(raw, str):
        raise ModelOutputError(f"answer for kind {kind!r} must be a string")
    return raw


def answer_question(
    question: str,
    as_of: date | None,
    chunks: list[Chunk],
    client: ModelClient,
    repeat: int = 0,
    recover: bool = False,
) -> SystemAnswer:
    """With `recover`, a reply holding several JSON objects is read by
    `parse_json_recovering` (the last object with every answer key)."""
    c = client.complete(
        load_prompt("answer"), _user_message(question, as_of, chunks),
        max_tokens=MAX_TOKENS, repeat=repeat,
    )
    d = parse_json_recovering(c.text, REQUIRED_KEYS)[0] if recover else parse_json(c.text)
    abstain = d.get("abstain")
    if abstain is not None and not isinstance(abstain, bool):
        raise ModelOutputError("abstain must be a boolean")
    known = {ch.chunk_id for ch in chunks}
    kind, conf, cites = d.get("kind"), d.get("confidence"), d.get("citations")
    if abstain is True or kind == "abstain":
        # Abstention is lenient: malformed secondary fields never turn it into an error.
        confidence = min(1.0, max(0.0, float(conf))) if _is_number(conf) else 0.0
        kept = (
            [x for x in cites if isinstance(x, str) and x in known]
            if isinstance(cites, list) else []
        )
        return SystemAnswer(None, "abstain", kept, True, confidence, c)
    if kind not in _KINDS:
        raise ModelOutputError(f"invalid kind: {kind!r}")
    if abstain is None:
        raise ModelOutputError("abstain must be a boolean")
    if not _is_number(conf):
        raise ModelOutputError("confidence must be a number")
    if not isinstance(cites, list) or not all(isinstance(x, str) for x in cites):
        raise ModelOutputError("citations must be a list of strings")
    confidence = min(1.0, max(0.0, float(conf)))
    citations = [x for x in cites if x in known]
    return SystemAnswer(_value(kind, d.get("answer")), kind, citations, False, confidence, c)
