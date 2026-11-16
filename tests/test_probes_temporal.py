"""Temporal probes (Phase 2 spec §10.2, T1-T5) on a synthetic gov-shaped store: one eCFR chain
of two versions with a changed and a removed section, Federal Register documents and an IRM
chapter. No model calls; lexical-only index."""

import json
import re

import pytest

from adr_eval.corpora.base import load_corpus
from adr_eval.corpora.gov import GovAdapter
from adr_eval.corpora.registry import write_manifest
from tests.test_adapters import HTTP, RecordedFetcher

GOV_CONFIG = json.loads((HTTP / "gov" / "config.json").read_text())
OLD, NEW = "2024-06-27", "2025-06-27"


def _remove_section(xml: bytes, number: str) -> bytes:
    out, n = re.subn(rf'<DIV8 N="{re.escape(number)}".*?</DIV8>\s*'.encode(), b"", xml,
                     flags=re.DOTALL)
    assert n == 1
    return out


@pytest.fixture(scope="module")
def gov(tmp_path_factory):
    """The recorded gov download with § 117.261 removed from the newer eCFR version."""
    root = tmp_path_factory.mktemp("gov")
    GovAdapter(HTTP / "gov" / "config.json").download(root, RecordedFetcher(HTTP / "gov"))
    new = next(root.rglob(f"part-117/{NEW}.xml"))
    new.write_bytes(_remove_section(new.read_bytes(), "117.261"))
    m = GovAdapter(HTTP / "gov" / "config.json").build_manifest(root)
    write_manifest(m, root / "manifest.json")
    return load_corpus(root / "manifest.json", root)


def _doc(gov, version):
    return next(d for d in gov.manifest.documents if d.source_version == version)


# -- the gov adapter: section spans and removed sections ------------------------------------


def test_section_spans_are_the_sections_of_the_document(gov):
    adapter = GovAdapter()
    old = _doc(gov, OLD)
    spans = adapter.section_spans(gov, old)
    assert list(spans) == ["117.1", "117.189", "117.261"]
    text = gov.docs[old.doc_id].text
    for number, (start, end, heading) in spans.items():
        assert text[start:end].startswith(heading) and heading.startswith(f"§ {number}")
        assert "\n" not in heading
    assert list(adapter.section_spans(gov, _doc(gov, NEW))) == ["117.1", "117.189"]
    # the version pairs are unchanged and their texts are the spans' texts
    for a, _ in adapter.version_pairs(gov):
        start, end, _h = adapter.section_spans(gov, _doc(gov, a.source_version))[
            a.uri.rsplit("#", 1)[1]]
        assert gov.docs[a.doc_id].text[start:end] == a.text


def test_removed_sections_are_those_missing_from_the_next_version(gov):
    removed = GovAdapter().removed_sections(gov)
    assert len(removed) == 1
    section, start, end = removed[0]
    old = _doc(gov, OLD)
    assert section.doc_id == old.doc_id and section.source_version == OLD
    assert section.uri == f"{old.uri}#117.261"
    assert gov.docs[old.doc_id].text[start:end] == section.text
    assert section.text.startswith("§ 117.261")
    assert [a.uri.rsplit("#", 1)[1] for a, _ in GovAdapter().version_pairs(gov)] == ["117.189"]
