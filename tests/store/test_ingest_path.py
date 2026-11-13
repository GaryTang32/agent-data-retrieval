"""`adr ingest --path <dir> --store <store>`: loose files into a store (spec §9)."""

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from adr_eval.corpora.extract import extract_text
from adr_store import cli, tools
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


def _ingest(folder: Path | str, store: Path | str) -> int:
    return cli.main(["ingest", "--path", str(folder), "--store", str(store)])


def _figures(store: Path) -> dict:
    s = Store.open(store)
    return json.loads((store / "compile" / f"{s.snapshot_id}.json").read_text())


def test_ingest_path_stores_every_supported_file(folder, tmp_path, capsys):
    assert _ingest(folder, tmp_path / "s") == 0
    s = Store.open(tmp_path / "s")
    ids = {rel: _sha(src) for rel, src in LOOSE.items()}
    assert s.doc_ids() == sorted(ids.values())
    assert s.paths == dict(sorted(ids.items()))
    for rel, doc_id in ids.items():
        src = s.source(doc_id)
        fmt = Path(rel).suffix[1:]
        assert src.format == fmt and src.uri == f"file://{rel}"
        assert src.source_version == f"sha256:{doc_id[:12]}" and src.license is None
        assert s.text(doc_id) == extract_text(LOOSE[rel].read_bytes(), fmt)
        assert (tmp_path / "s" / "blobs" / doc_id[:2] / doc_id).read_bytes() == \
            LOOSE[rel].read_bytes()
        assert s.path_of(doc_id) == rel
    figures = _figures(tmp_path / "s")
    assert figures["corpus"] is None and figures["snapshot"] == s.snapshot_id
    assert "path" not in figures
    assert figures["files"] == {"found": 6, "ingested": 4, "unsupported": 2, "duplicates": 0,
                                "symlinks": 0, "bad_names": 0}
    assert figures["conformance"] == {"documents": 4, "failures": 0, "pass_rate": 1.0}
    assert sorted(figures["by_format"]) == ["html", "md", "pdf", "txt"]
    assert figures["by_format"]["pdf"]["share_leaves_with_page"] == 1.0
    assert figures["leaves_with_span"] == 1.0
    out = capsys.readouterr().out
    assert s.snapshot_id in out and "conformance failures: 0 of 4" in out
    assert "files 6: ingested 4, unsupported 2, duplicates 0, symlinks 0, bad names 0" in out


def test_ingest_path_is_repeatable_and_independent_of_the_folder_location(folder, tmp_path,
                                                                          monkeypatch):
    """The whole store, compile figures included, does not depend on where the folder is,
    on the current directory, or on how the folder is spelled."""
    moved = tmp_path / "elsewhere" / "copy"
    shutil.copytree(folder, moved)
    assert _ingest(folder.resolve(), tmp_path / "a") == 0
    first = Store.open(tmp_path / "a").snapshot_id
    monkeypatch.chdir(tmp_path / "elsewhere")
    assert _ingest("../loose/", tmp_path / "a") == 0
    assert Store.open(tmp_path / "a").snapshot_id == first
    assert _ingest("copy", "../b") == 0
    monkeypatch.chdir(moved)
    assert _ingest(".", tmp_path / "c") == 0
    a, b, c = (_files(tmp_path / n) for n in "abc")
    assert a == b == c
    assert Store.open(tmp_path / "b").snapshot_id == first


def test_ingest_path_keeps_the_first_of_identical_files(folder, tmp_path, capsys):
    shutil.copyfile(folder / "guide.md", folder / "zz_copy_of_guide.md")
    assert _ingest(folder, tmp_path / "s") == 0
    s = Store.open(tmp_path / "s")
    doc_id = _sha(folder / "guide.md")
    assert len(s.doc_ids()) == 4 and s.source(doc_id).uri == "file://guide.md"
    assert s.paths["guide.md"] == s.paths["zz_copy_of_guide.md"] == doc_id
    assert s.path_of(doc_id) == "guide.md"
    assert "files 7: ingested 4, unsupported 2, duplicates 1" in capsys.readouterr().out


# -- re-ingesting a changed folder into the same store ------------------------------------


def test_a_renamed_file_gives_a_new_snapshot_in_the_same_store(folder, tmp_path):
    assert _ingest(folder, tmp_path / "s") == 0
    first = Store.open(tmp_path / "s").snapshot_id
    doc_id = _sha(folder / "guide.md")
    record = tmp_path / "s" / "docs" / doc_id[:2] / f"{doc_id}.json"
    before = record.read_bytes()
    (folder / "guide.md").rename(folder / "handbook.md")
    assert _ingest(folder, tmp_path / "s") == 0
    s = Store.open(tmp_path / "s")
    assert s.snapshot_id != first and s.doc_ids() == Store.open(tmp_path / "s", first).doc_ids()
    assert "guide.md" not in s.paths and s.paths["handbook.md"] == doc_id
    assert s.path_of(doc_id) == "handbook.md"
    assert record.read_bytes() == before  # the record is write-once: its uri is the first
    assert s.source(doc_id).uri == "file://guide.md"
    read = tools.Tools(tmp_path / "s").read(doc_id[:12], 0, 5)
    assert read.path == "handbook.md" and read.uri == "file://guide.md"
    # renaming it back gives the first snapshot again
    (folder / "handbook.md").rename(folder / "guide.md")
    assert _ingest(folder, tmp_path / "s") == 0
    assert Store.open(tmp_path / "s").snapshot_id == first


def test_another_duplicate_winning_does_not_fail_a_re_ingest(folder, tmp_path):
    shutil.copyfile(folder / "guide.md", folder / "zz_copy_of_guide.md")
    assert _ingest(folder, tmp_path / "s") == 0
    first = Store.open(tmp_path / "s").snapshot_id
    (folder / "guide.md").rename(folder / "zzz_guide.md")  # now zz_copy_of_guide.md wins
    assert _ingest(folder, tmp_path / "s") == 0
    s = Store.open(tmp_path / "s")
    doc_id = _sha(folder / "zzz_guide.md")
    assert s.snapshot_id != first and s.path_of(doc_id) == "zz_copy_of_guide.md"
    assert s.paths["zzz_guide.md"] == doc_id


def test_a_re_ingest_after_a_failed_run_succeeds(folder, tmp_path, monkeypatch, capsys):
    real = parse_document

    def broken(fmt, raw, text, doc_id):
        parsed = real(fmt, raw, text, doc_id)
        return parsed if fmt != "md" else type(parsed)(parsed.elements[1:], 0, 0)

    monkeypatch.setattr(store_mod, "parse_document", broken)
    assert _ingest(folder, tmp_path / "s") == 1  # the other documents' files are written
    monkeypatch.setattr(store_mod, "parse_document", real)
    (folder / "notes" / "paper_pages.txt").rename(folder / "notes" / "pages.txt")
    assert _ingest(folder, tmp_path / "s") == 0
    s = Store.open(tmp_path / "s")
    assert s.paths["notes/pages.txt"] == _sha(folder / "notes" / "pages.txt")
    assert len(s.doc_ids()) == 4


def test_an_unchanged_folder_gives_the_same_snapshot(folder, tmp_path):
    assert _ingest(folder, tmp_path / "s") == 0
    before = _files(tmp_path / "s")
    assert _ingest(folder, tmp_path / "s") == 0
    assert _files(tmp_path / "s") == before


def test_a_new_extension_for_stored_bytes_is_refused_before_any_write(folder, tmp_path,
                                                                      capsys):
    """The format comes from the extension; a store keeps one reading of a file's bytes."""
    assert _ingest(folder, tmp_path / "s") == 0
    before = _files(tmp_path / "s")
    capsys.readouterr()
    (folder / "guide.md").rename(folder / "guide.txt")
    assert _ingest(folder, tmp_path / "s") == 2
    err = capsys.readouterr().err
    assert "guide.txt: the store holds these bytes as md" in err
    assert _files(tmp_path / "s") == before


def test_corpus_snapshots_have_no_paths(tmp_path):
    s = Store.create(tmp_path / "s")
    raw = LOOSE["guide.md"].read_bytes()
    from adr_eval.corpora.base import Document
    doc_id = hashlib.sha256(raw).hexdigest()
    s.add(Document(doc_id, extract_text(raw, "md"), "md", "1", "https://x/guide.md"), raw)
    snap = s.commit()
    body = json.loads((tmp_path / "s" / "snapshots" / f"{snap}.json").read_bytes())
    assert set(body) == {"format_version", "extractor", "parser", "documents"}
    opened = Store.open(tmp_path / "s")
    assert opened.paths is None and opened.path_of(doc_id) is None
    assert tools.Tools(tmp_path / "s").read(doc_id[:12], 0, 3).path is None


def test_snapshot_paths_must_name_documents_of_the_snapshot(tmp_path):
    s = Store.create(tmp_path / "s")
    with pytest.raises(ValueError, match="not in the snapshot"):
        s.commit(paths={"a.md": "0" * 64})


# -- failures: everything is read and extracted before the first write --------------------


def _unreadable(monkeypatch, *names):
    real_read = Path.read_bytes

    def read_bytes(self):
        if self.name in names:
            raise PermissionError(13, "Permission denied", str(self))
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)


def test_ingest_path_reports_every_file_it_cannot_read_and_writes_nothing(folder, tmp_path,
                                                                         capsys, monkeypatch):
    (folder / "bad.txt").write_bytes(b"caf\xe9\n")  # not UTF-8: cannot be extracted
    _unreadable(monkeypatch, "nested.html", "guide.md")
    assert _ingest(folder, tmp_path / "s") == 3
    lines = capsys.readouterr().err.splitlines()
    assert lines[:3] == [
        "error: bad.txt: could not extract text (txt): UnicodeDecodeError: 'utf-8' codec "
        "can't decode byte 0xe9 in position 3: invalid continuation byte",
        "error: cannot read guide.md: Permission denied",
        "error: cannot read notes/web/nested.html: Permission denied"]
    assert lines[3:] == ["error: 3 entries could not be read or extracted; nothing written"]
    assert not (tmp_path / "s").exists()


def test_ingest_path_reports_every_file_whose_text_cannot_be_extracted(folder, tmp_path,
                                                                       capsys):
    (folder / "bad.txt").write_bytes(b"caf\xe9\n")  # not UTF-8
    (folder / "notes" / "broken.pdf").write_bytes(b"%PDF-1.4 not really a pdf")
    assert _ingest(folder, tmp_path / "s") == 2
    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 3, lines
    assert lines[0].startswith("error: bad.txt: could not extract text (txt): ")
    assert lines[1].startswith("error: notes/broken.pdf: could not extract text (pdf): ")
    assert lines[2] == "error: 2 entries could not be read or extracted; nothing written"
    assert not (tmp_path / "s").exists()


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


# -- the walk: no silent skips -------------------------------------------------------------


def test_symlinks_are_not_followed_and_are_counted(folder, tmp_path, capsys):
    outside = tmp_path / "outside"
    outside.mkdir()
    shutil.copyfile(FIXTURES / "store" / "nested.html", outside / "elsewhere.html")
    (outside / "other.md").write_text("# Other\n\nnot in the folder\n")
    (folder / "link_to_dir").symlink_to(outside, target_is_directory=True)
    (folder / "link_to_file.md").symlink_to(outside / "other.md")
    (folder / "notes" / "dangling.md").symlink_to(tmp_path / "missing.md")
    assert _ingest(folder, tmp_path / "s") == 0
    s = Store.open(tmp_path / "s")
    assert sorted(s.paths) == sorted(LOOSE)
    assert _figures(tmp_path / "s")["files"] == {
        "found": 9, "ingested": 4, "unsupported": 2, "duplicates": 0, "symlinks": 3,
        "bad_names": 0}
    assert "symlinks 3" in capsys.readouterr().out


def test_an_unreadable_directory_fails_the_ingest_by_name(folder, tmp_path, capsys,
                                                          monkeypatch):
    """Running as root, chmod 000 does not stop reading: the listing is made to fail."""
    real_scandir = os.scandir
    blocked = os.fspath(folder / "notes" / "web")

    def scandir(path="."):
        if os.fspath(path) == blocked:
            raise PermissionError(13, "Permission denied", os.fspath(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    assert _ingest(folder, tmp_path / "s") == 3
    lines = capsys.readouterr().err.splitlines()
    assert lines == ["error: cannot read notes/web: Permission denied",
                     "error: 1 entry could not be read or extracted; nothing written"]
    assert not (tmp_path / "s").exists()


def test_hidden_directories_are_not_listed(folder, tmp_path, monkeypatch):
    real_scandir = os.scandir
    listed = []

    def scandir(path="."):
        listed.append(os.fspath(path))
        if os.path.basename(os.fspath(path)) == ".git":
            raise PermissionError(13, "Permission denied", os.fspath(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    assert _ingest(folder, tmp_path / "s") == 0
    assert listed and not [p for p in listed if ".git" in p]


def test_a_file_name_that_is_not_utf8_is_skipped_with_a_warning(folder, tmp_path, capsys):
    with open(os.path.join(os.fsencode(folder / "notes"), b"caf\xe9.md"), "wb") as f:
        f.write(b"# Cafe\n\nskipped\n")
    os.mkdir(os.path.join(os.fsencode(folder), b"dir\xff"))
    with open(os.path.join(os.fsencode(folder), b"dir\xff", b"inside.md"), "wb") as f:
        f.write(b"# Inside\n\nskipped\n")
    assert _ingest(folder, tmp_path / "s") == 0
    out, err = capsys.readouterr()
    assert err.splitlines() == [
        "warning: skipped dir\\xff: the name is not UTF-8",
        "warning: skipped notes/caf\\xe9.md: the name is not UTF-8"]
    assert "Traceback" not in err
    assert sorted(Store.open(tmp_path / "s").paths) == sorted(LOOSE)
    assert _figures(tmp_path / "s")["files"]["bad_names"] == 2
    assert "bad names 2" in out


def test_a_store_inside_the_folder_is_not_read(folder, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(folder)
    snapshots, figures = [], []
    for _ in range(3):
        assert _ingest(".", "adr-store") == 0
        snapshots.append(Store.open(folder / "adr-store").snapshot_id)
        figures.append(_figures(folder / "adr-store"))
        assert "store adr-store is inside the folder: not read" in capsys.readouterr().out
    assert snapshots[0] == snapshots[1] == snapshots[2]
    assert figures[0] == figures[1] == figures[2]
    assert sorted(Store.open(folder / "adr-store").paths) == sorted(LOOSE)
    # spelled another way, the store is still recognised
    assert _ingest(folder, folder / "notes" / ".." / "adr-store") == 0
    assert Store.open(folder / "adr-store").snapshot_id == snapshots[0]


# -- usage ---------------------------------------------------------------------------------


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
