"""Zero-shot query generation (G2 baseline)."""

from __future__ import annotations

from datetime import date

from pydantic import ValidationError

from adr_eval.answer._prompts import load_prompt, prompt_hash
from adr_eval.llm import (
    Completion,
    ModelClient,
    ModelOutputError,
    parse_json,
    parse_json_recovering,
)
from adr_eval.models import GoldQuery

__all__ = ["generate_query", "prompt_hash"]

MAX_TOKENS = 400
REQUIRED_KEYS = ("store", "op")  # the GoldQuery fields without a default


def generate_query(
    question: str,
    as_of: date | None,
    record_schema: dict[str, str],
    client: ModelClient,
    repeat: int = 0,
    recover: bool = False,
) -> tuple[GoldQuery | None, Completion]:
    """With `recover`, a reply holding several JSON objects is read by
    `parse_json_recovering` (the last object with "store" and "op")."""
    schema = "\n".join(f"- {k}: {v}" for k, v in record_schema.items()) or "(none)"
    user = f"Record schema:\n{schema}\n\nQuestion: {question}"
    if as_of is not None:
        user += f"\n\nAnswer as of: {as_of.isoformat()}"
    c = client.complete(load_prompt("query_gen"), user, max_tokens=MAX_TOKENS, repeat=repeat)
    try:
        data = parse_json_recovering(c.text, REQUIRED_KEYS)[0] if recover \
            else parse_json(c.text)
        return GoldQuery.model_validate(data), c
    except (ModelOutputError, ValidationError):
        return None, c
