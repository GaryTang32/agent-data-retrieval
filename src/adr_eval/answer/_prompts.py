"""Prompt files shipped as package data."""

from __future__ import annotations

import hashlib
from importlib import resources

_NAMES = ("answer", "query_gen")


def _file(name: str):
    if name not in _NAMES:
        raise ValueError(f"unknown prompt {name!r}")
    return resources.files("adr_eval.answer").joinpath(f"prompts/{name}.txt")


def load_prompt(name: str) -> str:
    return _file(name).read_text(encoding="utf-8")


def prompt_hash(name: str) -> str:
    """SHA-256 of the prompt file bytes, recorded by the runner."""
    return hashlib.sha256(_file(name).read_bytes()).hexdigest()
