"""Guards for tracked files that manifests and golden sets pin (offline, no corpus data)."""

import hashlib
import json
import shutil
import subprocess

import pytest

from adr_eval.corpora import REPO_ROOT
from adr_eval.golden.verify import EXCLUSIONS_FILE, assign_split, load_exclusions
from adr_eval.models import GoldenItem, Manifest, jsonl_lines

PINNED_PREFIXES = ("reports/", "research_notes/")
GOV_GOLDEN = REPO_ROOT / "golden" / "gov" / "v0.1"


def _manifest(corpus: str) -> Manifest:
    path = REPO_ROOT / "corpora" / corpus / "manifest.json"
    return Manifest.model_validate_json(path.read_text(encoding="utf-8"))


def _research_repo_docs():
    return [d for d in _manifest("research").documents
            if d.path.startswith(PINNED_PREFIXES) or d.path == "papers/manifest.csv"]


def test_research_manifest_pins_tracked_repo_files():
    docs = _research_repo_docs()
    assert docs, "the research manifest should pin reports, notes and papers/manifest.csv"
    changed = []
    for d in docs:
        path = REPO_ROOT / d.path
        if not path.is_file():
            changed.append(f"{d.path}: missing")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != d.doc_id:
            changed.append(f"{d.path}: bytes differ from the pinned doc_id")
    assert not changed, (
        "pinned research corpus documents changed:\n  " + "\n  ".join(changed) + "\n"
        "These files are part of the research corpus snapshot. Restore them (for example "
        "`git checkout papers/manifest.csv` after scripts/download_papers.py), or rebuild "
        "the manifest (`python -m adr_eval.corpora.registry build research`) and regenerate "
        "the research golden set (`adr-eval golden research --gen`).")


@pytest.fixture(scope="module")
def gov_items() -> list[GoldenItem]:
    text = (GOV_GOLDEN / "items.jsonl").read_text(encoding="utf-8")
    return [GoldenItem.model_validate_json(line) for line in jsonl_lines(text)]


def test_gov_golden_items_load_with_unique_ids(gov_items):
    ids = [i.id for i in gov_items]
    assert gov_items and len(ids) == len(set(ids))


def test_gov_golden_items_match_the_gov_manifest_snapshot(gov_items):
    snapshot = _manifest("gov").snapshot()
    assert {i.snapshot for i in gov_items} == {snapshot}


def test_gov_golden_splits_follow_assign_split(gov_items):
    seed = json.loads((REPO_ROOT / "config" / "eval.json").read_text())["seed"]
    assert [i.id for i in gov_items if i.split != assign_split(i.id, seed)] == []


def test_gov_golden_has_no_review_excluded_items(gov_items):
    excluded = load_exclusions(GOV_GOLDEN / EXCLUSIONS_FILE)
    assert excluded, "golden/gov/v0.1/review_exclusions.json should list the review findings"
    assert sorted(set(excluded) & {i.id for i in gov_items}) == []


@pytest.mark.parametrize("corpus", ["bench", "research"])
def test_local_only_golden_sets_are_pinned_by_readme(corpus):
    assert (REPO_ROOT / "golden" / corpus / "v0.1" / "README.md").is_file()


def _tracked(paths: list[str]) -> list[str]:
    git = shutil.which("git")
    if git is None or not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run([git, "ls-files", "--", *paths], cwd=REPO_ROOT, check=True,
                         capture_output=True, text=True).stdout
    return out.split()


@pytest.mark.parametrize("corpus", ["bench", "research"])
def test_local_only_golden_items_are_not_tracked(corpus):
    files = [f"golden/{corpus}/v0.1/{n}" for n in ("items.jsonl", "rejected.jsonl")]
    assert _tracked(files) == []
