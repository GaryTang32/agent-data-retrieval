"""Record format v0.1: the source record and the element records of one document (spec §4).

Regenerate the committed JSON Schema files with `python -m adr_store.records`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FORMAT_VERSION = "0.1"
SCHEMA_DIR = Path(__file__).parent / "schema"

Format = Literal["md", "txt", "html", "xml", "pdf", "json", "csv"]
ElementType = Literal["section", "heading", "paragraph", "list_item", "table", "code", "record"]
LEAF_TYPES = frozenset({"heading", "paragraph", "list_item", "table", "code", "record"})

_HEX64 = r"^[0-9a-f]{64}$"


def sha256_text(text: str) -> str:
    """SHA-256 of a string's UTF-8 bytes, lower-case hex: how records hash text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def element_id(doc_id: str, type_: str, char_start: int, char_end: int) -> str:
    """The element id of spec §4.2: SHA-256 of the four fields joined by newlines."""
    return sha256_text(f"{doc_id}\n{type_}\n{char_start}\n{char_end}")


class SourceRecord(BaseModel):
    """One stored document: where its bytes came from and how its text was made (spec §4.1)."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="SourceRecord")

    doc_id: str = Field(pattern=_HEX64)
    uri: str
    format: Format
    source_version: str
    byte_length: int = Field(ge=0)
    text_sha256: str = Field(pattern=_HEX64)
    text_length: int = Field(ge=0)
    extractor: str
    parser: str
    license: str | None


class Element(BaseModel):
    """A character range of the canonical text: a `section` container or a leaf (spec §4.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="Element")

    element_id: str = Field(pattern=_HEX64)
    doc_id: str = Field(pattern=_HEX64)
    type: ElementType
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    parent_id: str | None = Field(default=None, pattern=_HEX64)
    order: int = Field(ge=0)
    level: int | None = Field(default=None, ge=1)
    title: str | None = None
    section_path: list[str] = []
    page: int | None = Field(default=None, ge=1)
    confidence: float = Field(ge=0.0, le=1.0)
    text_sha256: str = Field(pattern=_HEX64)

    @model_validator(mode="after")
    def _range_is_ordered(self) -> Element:
        if self.char_end < self.char_start:
            raise ValueError(f"char_end {self.char_end} < char_start {self.char_start}")
        return self

    @property
    def is_leaf(self) -> bool:
        """Leaves tile the text (rule 1); sections only contain them."""
        return self.type in LEAF_TYPES


class DocRecord(BaseModel):
    """The content of `<store>/docs/<doc_id[:2]>/<doc_id>.json`: a source and its elements."""

    model_config = ConfigDict(extra="forbid", frozen=True, title="DocRecord")

    format_version: Literal["0.1"] = FORMAT_VERSION
    source: SourceRecord
    elements: list[Element]


def canonical_json(model: BaseModel) -> bytes:
    """The stored bytes of a record: sorted keys, no padding, UTF-8, one trailing newline.

    Record hashes in a snapshot are SHA-256 of exactly these bytes.
    """
    payload = json.dumps(model.model_dump(mode="json"), sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False)
    return payload.encode("utf-8") + b"\n"


def schemas() -> dict[str, dict]:
    """File name -> JSON Schema for every record model."""
    return {
        "source.schema.json": SourceRecord.model_json_schema(),
        "element.schema.json": Element.model_json_schema(),
        "document.schema.json": DocRecord.model_json_schema(),
    }


def render_schema(schema: dict) -> str:
    """The exact text of a committed schema file."""
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_schemas(out_dir: Path = SCHEMA_DIR) -> list[Path]:
    """Write every schema file into `out_dir`; returns the paths in name order."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, schema in sorted(schemas().items()):
        path = out_dir / name
        path.write_text(render_schema(schema), encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    for p in write_schemas():
        print(p)
