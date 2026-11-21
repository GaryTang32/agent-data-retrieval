"""Zero-shot query generation: the G2 baseline (`generate_query`, a v0.1 `GoldQuery`) and, for
the gov-tables set (Phase 3 spec §10.3, §11), a `query_table` argument object over the drawbridge
tables (`generate_table_query`). Every system of a gov-tables run sends the same table prompt
and schema text, so one cached call per question serves them all."""

from __future__ import annotations

from datetime import date

from pydantic import ValidationError

from adr_eval.answer._prompts import load_prompt, prompt_hash
from adr_eval.golden.tables import TableQuery
from adr_eval.llm import (
    Completion,
    ModelClient,
    ModelOutputError,
    parse_json,
    parse_json_recovering,
)
from adr_eval.models import GoldQuery

__all__ = ["generate_query", "generate_table_query", "prompt_hash"]

MAX_TOKENS = 400
REQUIRED_KEYS = ("store", "op")  # the GoldQuery fields without a default
TABLE_REQUIRED_KEYS = ("table", "op")  # the TableQuery fields without a default


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


def generate_table_query(
    question: str,
    describe_text: str,
    client: ModelClient,
    repeat: int = 0,
    recover: bool = False,
) -> tuple[TableQuery | None, Completion]:
    """A `TableQuery` for `question` (None when the reply is not one): the `query_gen_tables`
    prompt, and the user message `describe_text` (the drawbridge tables' semantic layer,
    `golden.tables.describe_text()`) and the question. With `recover`, a reply holding several
    JSON objects is read by `parse_json_recovering` (the last one with "table" and "op")."""
    user = f"Tables:\n{describe_text}\n\nQuestion: {question}"
    c = client.complete(load_prompt("query_gen_tables"), user, max_tokens=MAX_TOKENS,
                        repeat=repeat)
    try:
        data = parse_json_recovering(c.text, TABLE_REQUIRED_KEYS)[0] if recover \
            else parse_json(c.text)
        return TableQuery.model_validate(data), c
    except (ModelOutputError, ValidationError):
        return None, c
