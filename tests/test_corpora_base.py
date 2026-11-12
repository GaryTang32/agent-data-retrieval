import io
import json
import shutil
from pathlib import Path

import pytest

from adr_eval.corpora.base import (
    HashMismatch,
    fetch_manifest,
    load_corpus,
    sha256_bytes,
    verify_manifest,
)
from adr_eval.models import Manifest, ManifestDoc

MINI = Path(__file__).parent / "fixtures" / "mini"


def manifest_with(doc_id: str, fmt: str = "txt", size: int = 4, path: str = "d/a.txt") -> Manifest:
    return Manifest(
        corpus="t",
        version="1",
        license_summary="x",
        documents=[
            ManifestDoc(
                doc_id=doc_id,
                uri="mem://a",
                format=fmt,
                source_version="1",
                bytes=size,
                license="x",
                path=path,
            )
        ],
    )


def test_fetch_refuses_hash_mismatch(tmp_path):
    m = manifest_with(sha256_bytes(b"good"))
    with pytest.raises(HashMismatch):
        fetch_manifest(m, tmp_path, lambda uri: b"evil")
    assert not (tmp_path / m.documents[0].path).exists()


def test_fetch_downloads_then_skips_when_present(tmp_path):
    m = manifest_with(sha256_bytes(b"good"))
    calls = []

    def fetcher(uri):
        calls.append(uri)
        return b"good"

    fetch_manifest(m, tmp_path, fetcher)
    fetch_manifest(m, tmp_path, fetcher)
    assert calls == ["mem://a"]
    assert (tmp_path / "d/a.txt").read_bytes() == b"good"


def test_fetch_replaces_corrupt_local_file(tmp_path):
    m = manifest_with(sha256_bytes(b"good"))
    (tmp_path / "d").mkdir()
    (tmp_path / "d/a.txt").write_bytes(b"junk")
    fetch_manifest(m, tmp_path, lambda uri: b"good")
    assert (tmp_path / "d/a.txt").read_bytes() == b"good"


def test_verify_reports_missing_and_tampered(tmp_path):
    m = manifest_with(sha256_bytes(b"good"))
    assert "missing" in verify_manifest(m, tmp_path)[0]
    (tmp_path / "d").mkdir()
    (tmp_path / "d/a.txt").write_bytes(b"evil!")
    problems = verify_manifest(m, tmp_path)
    assert len(problems) == 2  # size and hash
    (tmp_path / "d/a.txt").write_bytes(b"good")
    assert verify_manifest(m, tmp_path) == []


def test_load_mini_corpus_verifies_and_extracts():
    lc = load_corpus(MINI / "manifest.json", MINI)
    assert len(lc.docs) == len(lc.manifest.documents) == 7
    assert lc.empty_docs == []
    assert {d.format for d in lc.docs.values()} == {"md", "html", "json", "xml", "pdf"}


def test_load_rejects_tampered_corpus(tmp_path):
    shutil.copytree(MINI, tmp_path / "c")
    (tmp_path / "c/refund_policy.md").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="refund_policy.md"):
        load_corpus(tmp_path / "c/manifest.json", tmp_path / "c")


def _blank_pdf() -> bytes:
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_empty_pdf_yields_empty_text_and_is_flagged(tmp_path):
    data = _blank_pdf()
    blank_id = sha256_bytes(data)
    (tmp_path / "blank.pdf").write_bytes(data)
    m = manifest_with(blank_id, fmt="pdf", size=len(data), path="blank.pdf")
    (tmp_path / "manifest.json").write_text(json.dumps(m.model_dump(mode="json")))
    lc = load_corpus(tmp_path / "manifest.json", tmp_path)
    assert lc.empty_docs == [blank_id]
    assert lc.docs[blank_id].text.strip() == ""
