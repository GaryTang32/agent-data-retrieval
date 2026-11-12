"""Corpus adapter registry and the build/fetch command.

  python -m adr_eval.corpora.registry build <corpus>   download sources, write manifest.json
  python -m adr_eval.corpora.registry fetch <corpus>   re-download files listed in the manifest
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal

from adr_eval.corpora import REPO_ROOT
from adr_eval.corpora.base import CorpusAdapter, fetch_manifest, load_corpus
from adr_eval.models import Manifest

CorpusName = Literal["gov", "research", "bench", "mini"]
NAMES: tuple[str, ...] = ("gov", "research", "bench", "mini")
MINI_ROOT = REPO_ROOT / "tests" / "fixtures" / "mini"


def get_adapter(name: CorpusName) -> CorpusAdapter:
    if name == "gov":
        from adr_eval.corpora.gov import GovAdapter

        return GovAdapter()
    if name == "research":
        from adr_eval.corpora.research import ResearchAdapter

        return ResearchAdapter()
    if name == "bench":
        from adr_eval.corpora.bench import BenchAdapter

        return BenchAdapter()
    if name == "mini":
        from adr_eval.corpora.mini import MiniAdapter

        return MiniAdapter()
    raise ValueError(f"unknown corpus {name!r}; expected one of {', '.join(NAMES)}")


def corpus_root(name: CorpusName) -> Path:
    """Directory that the manifest's `path`s are relative to."""
    return MINI_ROOT if name == "mini" else REPO_ROOT


def manifest_path(name: CorpusName) -> Path:
    if name == "mini":
        return MINI_ROOT / "manifest.json"
    return REPO_ROOT / "corpora" / name / "manifest.json"


def write_manifest(m: Manifest, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(m.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


def build(name: CorpusName, root: Path | None = None) -> Manifest:
    """Download the corpus sources, write its manifest and check that it loads cleanly."""
    adapter = get_adapter(name)
    root = Path(root or corpus_root(name))
    adapter.download(root)
    m = adapter.build_manifest(root)
    out = manifest_path(name)
    write_manifest(m, out)
    corpus = load_corpus(out, root)
    print(f"{name}: wrote {out} ({len(m.documents)} documents, snapshot {m.snapshot()[:12]}, "
          f"{len(corpus.empty_docs)} empty)")
    return m


class LocalFilesMissing(Exception):  # noqa: N818 - reads as the condition it reports
    """Files of a local-only corpus are absent; `fetch` cannot download them."""

    def __init__(self, corpus: str, missing: list[str], total: int, hint: str):
        shown = ", ".join(missing[:5]) + (f" (and {len(missing) - 5} more)"
                                          if len(missing) > 5 else "")
        super().__init__(f"{corpus}: {len(missing)} of {total} corpus files are missing "
                         f"locally: {shown}\n{hint}")
        self.corpus, self.missing = corpus, missing


def check_local_files(name: CorpusName, root: Path | None = None) -> None:
    """Raise `LocalFilesMissing` when a corpus whose sources are local only (its adapter has
    a `local_files_hint`) lacks manifest files on disk. Other corpora: no check."""
    if name not in NAMES:
        return
    adapter = get_adapter(name)
    hint = getattr(adapter, "local_files_hint", None)
    if hint is None:
        return
    root = Path(root or corpus_root(name))
    m = Manifest.model_validate_json(manifest_path(name).read_text(encoding="utf-8"))
    missing = [d.path for d in m.documents if not (root / d.path).is_file()]
    if missing:
        raise LocalFilesMissing(name, missing, len(m.documents), hint)


def fetch_corpus(name: CorpusName, root: Path | None = None) -> None:
    """Download any file of the committed manifest that is missing or corrupt."""
    adapter = get_adapter(name)
    root = Path(root or corpus_root(name))
    check_local_files(name, root)
    m = Manifest.model_validate_json(manifest_path(name).read_text(encoding="utf-8"))
    fetch_manifest(m, root, adapter.fetcher(root))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m adr_eval.corpora.registry")
    ap.add_argument("command", choices=["build", "fetch"])
    ap.add_argument("corpus", choices=NAMES)
    a = ap.parse_args(argv)
    if a.command == "build":
        build(a.corpus)
    else:
        fetch_corpus(a.corpus)


if __name__ == "__main__":
    main()
