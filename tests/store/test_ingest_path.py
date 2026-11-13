"""`adr ingest --path <dir> --store <store>`: loose files into a store (spec §9)."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from adr_eval.corpora.extract import extract_text
from adr_store import cli
from adr_store import store as store_mod
from adr_store.store import Store
from adr_store.structure import parse_document

FIXTURES = Path(__file__).parents[1] / "fixtures"

# relative path in the folder -> fixture file
LOOSE = {
    "guide.md": FIXTURES / "store" / "guide.md",
    "notes/paper_pages.txt": FIXTURES / "store" / "paper_pages.txt",
    "notes/web/nested.html": FIXTURES / "store" / "nested.html",
    "service_charter.pdf": FIXTURES / "mini" / "service_charter.pdf",
}


@pytest.fixture
def folder(tmp_path) -> Path:
    root = tmp_path / "loose"
    for rel, src in LOOSE.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, root / rel)
    (root / "picture.png").write_bytes(b"\x89PNG\r\n\x1a\nnot really")  # unsupported
    (root / "notes" / "draft.docx").write_bytes(b"PK\x03\x04")  # unsupported
    (root / ".hidden.md").write_text("# Hidden\n\nnot ingested\n")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD.txt").write_text("ref: refs/heads/main\n")
    return root


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _ingest(folder: Path, store: Path) -> int:
    return cli.main(["ingest", "--path", str(folder), "--store", str(store)])


def test_ingest_path_stores_every_supported_file(folder, tmp_path, capsys):
    assert _ingest(folder, tmp_path / "s") == 0
    s = Store.open(tmp_path / "s")
    ids = {rel: _sha(src) for rel, src in LOOSE.items()}
    assert s.doc_ids() == sorted(ids.values())
    for rel, doc_id in ids.items():
        src = s.source(doc_id)
        fmt = Path(rel).suffix[1:]
        assert src.format == fmt and src.uri == f"file://{rel}"
        assert src.source_version == f"sha256:{doc_id[:12]}" and src.license is None
        assert s.text(doc_id) == extract_text(LOOSE[rel].read_bytes(), fmt)
        assert (tmp_path / "s" / "blobs" / doc_id[:2] / doc_id).read_bytes() == \
            LOOSE[rel].read_bytes()
    figures = json.loads((tmp_path / "s" / "compile" / f"{s.snapshot_id}.json").read_text())
    assert figures["corpus"] is None and figures["snapshot"] == s.snapshot_id
    assert figures["files"] == {"found": 6, "ingested": 4, "unsupported": 2, "duplicates": 0}
    assert figures["conformance"] == {"documents": 4, "failures": 0, "pass_rate": 1.0}
    assert sorted(figures["by_format"]) == ["html", "md", "pdf", "txt"]
    assert figures["by_format"]["pdf"]["share_leaves_with_page"] == 1.0
    assert figures["leaves_with_span"] == 1.0
    out = capsys.readouterr().out
    assert s.snapshot_id in out and "conformance failures: 0 of 4" in out
    assert "files 6: ingested 4, unsupported 2, duplicates 0" in out


def test_ingest_path_is_repeatable_and_independent_of_the_folder_location(folder, tmp_path):
    moved = tmp_path / "elsewhere" / "copy"
    shutil.copytree(folder, moved)
    assert _ingest(folder, tmp_path / "a") == 0
    assert _ingest(folder, tmp_path / "a") == 0
    assert _ingest(moved, tmp_path / "b") == 0
    a, b = _files(tmp_path / "a"), _files(tmp_path / "b")
    assert {k: v for k, v in a.items() if not k.startswith("compile/")} == \
        {k: v for k, v in b.items() if not k.startswith("compile/")}
    assert Store.open(tmp_path / "a").snapshot_id == Store.open(tmp_path / "b").snapshot_id


def test_ingest_path_keeps_the_first_of_identical_files(folder, tmp_path, capsys):
    shutil.copyfile(folder / "guide.md", folder / "zz_copy_of_guide.md")
    assert _ingest(folder, tmp_path / "s") == 0
    s = Store.open(tmp_path / "s")
    doc_id = _sha(folder / "guide.md")
    assert len(s.doc_ids()) == 4 and s.source(doc_id).uri == "file://guide.md"
    assert "files 7: ingested 4, unsupported 2, duplicates 1" in capsys.readouterr().out


def test_ingest_path_fails_on_a_conformance_violation(folder, tmp_path, capsys, monkeypatch):
    def broken(fmt, raw, text, doc_id):
        parsed = parse_document(fmt, raw, text, doc_id)
        if fmt != "md":
            return parsed
        return type(parsed)(parsed.elements[1:], 0, 0)

    monkeypatch.setattr(store_mod, "parse_document", broken)
    assert _ingest(folder, tmp_path / "s") == 1
    err = capsys.readouterr().err
    assert "1 of 4 documents fail conformance" in err and "guide.md (" in err
    assert not (tmp_path / "s" / "HEAD").exists()


def test_ingest_path_exits_3_naming_a_file_it_cannot_read(folder, tmp_path, capsys,
                                                          monkeypatch):
    real_read = Path.read_bytes

    def unreadable(self):
        if self.name == "nested.html":
            raise PermissionError(13, "Permission denied", str(self))
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", unreadable)
    assert _ingest(folder, tmp_path / "s") == 3
    err = capsys.readouterr().err
    assert err.count("\n") == 1, err
    assert "PermissionError" in err and "while processing notes/web/nested.html" in err
    assert not (tmp_path / "s" / "HEAD").exists()


def test_ingest_path_reports_a_file_whose_text_cannot_be_extracted(folder, tmp_path, capsys):
    (folder / "bad.txt").write_bytes(b"caf\xe9\n")  # not UTF-8
    assert _ingest(folder, tmp_path / "s") == 2
    err = capsys.readouterr().err
    assert "bad.txt" in err and "could not extract text (txt)" in err
    assert not (tmp_path / "s" / "HEAD").exists()


@pytest.mark.parametrize("argv", [
    ["ingest", "--path", "x"],  # --store is required
    ["ingest", "mini", "--path", "x", "--store", "s"],  # corpus and --path exclude each other
    ["ingest", "--store", "s"],  # one of them is required
])
def test_ingest_usage_errors_exit_2(argv, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as e:
        cli.main(argv)
    assert e.value.code == 2
    assert capsys.readouterr().err.strip()
    assert not (tmp_path / "s").exists()


def test_ingest_path_refuses_a_missing_folder_or_one_without_supported_files(tmp_path,
                                                                             capsys):
    assert _ingest(tmp_path / "nope", tmp_path / "s") == 2
    assert "not a directory" in capsys.readouterr().err
    (tmp_path / "empty").mkdir()
    (tmp_path / "empty" / "a.png").write_bytes(b"x")
    assert _ingest(tmp_path / "empty", tmp_path / "s") == 2
    assert "no supported files" in capsys.readouterr().err
    assert not (tmp_path / "s").exists()
