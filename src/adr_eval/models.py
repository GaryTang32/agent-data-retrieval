"""Data model for manifests and golden items."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, model_validator

QType = Literal[
    "factoid", "count_filter", "procedure", "policy_asof", "overview", "id_lookup", "insufficient"
]
AnswerKind = Literal["text", "set", "number", "id", "abstain"]


class ManifestDoc(BaseModel):
    doc_id: str
    uri: str
    format: Literal["xml", "json", "pdf", "html", "md", "csv", "txt"]
    source_version: str
    bytes: int
    license: str
    path: str


class Manifest(BaseModel):
    corpus: str
    version: str
    license_summary: str
    documents: list[ManifestDoc]

    def snapshot(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Evidence(BaseModel):
    doc_id: str
    char_start: int
    char_end: int
    quote: str


class Answer(BaseModel):
    kind: AnswerKind
    value: str | float | list[str] | None
    accepted_variants: list[str] = []


class GoldQuery(BaseModel):
    store: Literal["typed_db", "knowledge", "raw"]
    op: Literal["lookup", "count", "list", "explain", "procedure", "abstain"]
    filters: dict[str, str | int | float | list[str]] = {}
    entities: list[str] = []
    as_of: date | None = None


class Checks(BaseModel):
    span_ok: bool | None = None
    recompute_ok: bool | None = None
    evidence_only_ok: bool | None = None
    gold_query_exec_ok: bool | None = None
    dedup_ok: bool | None = None


class Provenance(BaseModel):
    model: str
    prompt_hash: str
    seed: int
    created: datetime


class GoldenItem(BaseModel):
    id: str
    corpus: str
    snapshot: str
    qtype: QType
    question: str
    as_of: date | None
    answer: Answer
    evidence: list[Evidence]
    gold_query: GoldQuery
    rarity: Literal["head", "torso", "tail"] | None
    split: Literal["dev", "test"] | None
    provenance: Provenance
    checks: Checks
    status: Literal["auto_verified", "human_vetted", "rejected"]
    reject_reason: str | None = None

    @model_validator(mode="after")
    def _check_invariants(self) -> GoldenItem:
        if self.qtype == "policy_asof" and self.as_of is None:
            raise ValueError("policy_asof items require as_of")
        if self.answer.kind == "abstain" and self.evidence:
            raise ValueError("abstain answers must have no evidence")
        return self


def jsonl_lines(text: str) -> list[str]:
    """The non-blank lines of JSONL text, split on "\n" only.

    `str.splitlines()` also breaks on U+2028, U+2029 and U+0085, which JSON leaves unescaped
    inside strings (extracted PDF text contains them), so it cuts a record in two.
    """
    return [line for line in text.split("\n") if line.strip()]


def load_items(path: Path) -> list[GoldenItem]:
    text = Path(path).read_text(encoding="utf-8")
    return [GoldenItem.model_validate_json(line) for line in jsonl_lines(text)]


def write_items(path: Path, items: list[GoldenItem]) -> None:
    lines = [
        json.dumps(i.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        for i in sorted(items, key=lambda i: i.id)
    ]
    Path(path).write_text("".join(line + "\n" for line in lines), encoding="utf-8")
