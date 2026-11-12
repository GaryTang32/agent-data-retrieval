"""Corpus loading, verification and text extraction."""

from pathlib import Path

# Repository checkout root: corpora/<name>/config.json and data/<name>/ live here.
REPO_ROOT = Path(__file__).resolve().parents[3]
