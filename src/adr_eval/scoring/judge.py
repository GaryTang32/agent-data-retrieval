"""LLM judge for answers that exact matching cannot score."""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from typing import Literal, get_args

from adr_eval.llm import (
    Completion,
    ModelClient,
    ModelOutputError,
    parse_json,
    parse_json_recovering,
)
from adr_eval.models import Answer
from adr_eval.scoring.outcomes import Outcome

__all__ = ["Judge", "JudgeLabel", "label_to_outcome", "prompt_hash"]

JudgeLabel = Literal["correct", "partial", "incorrect"]
MAX_TOKENS = 300
_LABELS = set(get_args(JudgeLabel))


def _file(name: str):
    if name != "judge":
        raise ValueError(f"unknown prompt {name!r}")
    return resources.files("adr_eval.scoring").joinpath("prompts/judge.txt")


def prompt_hash(name: str = "judge") -> str:
    """SHA-256 of the prompt file bytes, recorded by the runner."""
    return hashlib.sha256(_file(name).read_bytes()).hexdigest()


def label_to_outcome(label: JudgeLabel) -> Outcome:
    return "wrong" if label == "incorrect" else label


def _render(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


class Judge:
    """`recover` (runs only; golden generation stays strict) reads a reply holding several
    JSON objects with `parse_json_recovering` (the last object with a "label")."""

    def __init__(self, client: ModelClient, recover: bool = False):
        self.client = client
        self.recover = recover
        self._system = _file("judge").read_text(encoding="utf-8")

    def judge(
        self, question: str, gold: Answer, candidate: str | float | list[str] | None,
        repeat: int = 0,
    ) -> tuple[JudgeLabel, str, Completion]:
        user = "\n\n".join([
            f"Question: {question}",
            f"Gold answer: {_render(gold.value)}",
            f"Accepted variants: {json.dumps(gold.accepted_variants, ensure_ascii=False)}",
            f"Candidate answer: {_render(candidate)}",
        ])
        comp = self.client.complete(self._system, user, max_tokens=MAX_TOKENS, repeat=repeat)
        data = parse_json_recovering(comp.text, ("label",))[0] if self.recover \
            else parse_json(comp.text)
        label = data.get("label")
        if not isinstance(label, str) or label not in _LABELS:
            raise ModelOutputError(f"invalid judge label: {label!r}")
        reason = data.get("reason")
        return label, "" if reason is None else str(reason), comp

    def same_family_as(self, generator: ModelClient) -> bool:
        return self.client.family == generator.family
