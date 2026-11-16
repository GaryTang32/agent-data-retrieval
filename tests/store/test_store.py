import hashlib
import json
from pathlib import Path

import pytest

from adr_eval.corpora.base import Document, load_corpus
from adr_eval.corpora.extract import EXTRACTOR_VERSION
from adr_store import store as store_mod
from adr_store.conformance import check
from adr_store.records import DocRecord, sha256_text
from adr_store.store import ConformanceError, Store, StoreError
from adr_store.structure import PARSER, parse_document

MINI = Path(__file__).parents[1] / "fixtures" / "mini"


@pytest.fixture(scope="module")
def mini():
    return load_corpus(MINI / "manifest.json", MINI)


def _raw(corpus, doc_id: str) -> bytes:
    path = next(d.path for d in corpus.manifest.documents if d.doc_id == doc_id)
    return (corpus.root / path).read_bytes()


def _build(path: Path, corpus) -> tuple[Store, str]:
    s = Store.create(path)
    for doc_id in sorted(corpus.docs):
        s.add(corpus.docs[doc_id], _raw(corpus, doc_id), license="fixture-original")
    return s, s.commit()


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_layout_and_snapshot_id(tmp_path, mini):
    _, snap = _build(tmp_path / "s", mini)
    root = tmp_path / "s"
    assert (root / "HEAD").read_text() == snap + "\n"
    snap_bytes = (root / "snapshots" / f"{snap}.json").read_bytes()
    assert hashlib.sha256(snap_bytes).hexdigest() == snap
    body = json.loads(snap_bytes)
    assert body["parser"] == PARSER == "adr_store.structure/3"
    assert body["extractor"] == f"adr_eval.extract/{EXTRACTOR_VERSION}"
    assert [d["doc_id"] for d in body["documents"]] == sorted(mini.docs)
    for d in body["documents"]:
        i = d["doc_id"]
        assert (root / "blobs" / i[:2] / i).read_bytes() == _raw(mini, i)
        record = (root / "docs" / i[:2] / f"{i}.json").read_bytes()
        assert hashlib.sha256(record).hexdigest() == d["record_sha256"]
        assert (root / "text" / i[:2] / f"{i}.txt").is_file()
    assert not [p for p in root.rglob("*") if p.name.endswith(".tmp")]


def test_open_reads_back_exactly_what_was_added(tmp_path, mini):
    _, snap = _build(tmp_path / "s", mini)
    s = Store.open(tmp_path / "s")
    assert s.snapshot_id == snap
    assert s.doc_ids() == sorted(mini.docs)
    for doc_id, doc in mini.docs.items():
        assert s.text(doc_id) == doc.text
        src = s.source(doc_id)
        assert (src.uri, src.format, src.source_version) == (doc.uri, doc.format,
                                                              doc.source_version)
        assert src.license == "fixture-original"
        assert src.text_sha256 == sha256_text(doc.text) and src.text_length == len(doc.text)
        raw = _raw(mini, doc_id)
        want = parse_document(doc.format, raw, doc.text, doc_id).elements
        assert s.elements(doc_id) == want
        assert check(src, s.elements(doc_id), s.text(doc_id), raw) == []


def _fixture_docs(mini) -> list[tuple[Document, bytes]]:
    """Every mini document, plus csv and txt documents (formats mini does not have)."""
    docs = [(doc, _raw(mini, doc_id)) for doc_id, doc in sorted(mini.docs.items())]
    for fmt, raw in (("csv", b'id,name\n1,"a, b"\n2,c\n'), ("txt", b"One.\n\nTwo.\n")):
        docs.append((Document(hashlib.sha256(raw).hexdigest(), raw.decode(), fmt, "1",
                              f"file://x.{fmt}"), raw))
    return docs


def test_every_format_conforms_and_parses_deterministically(mini):
    """Spec §4.3 rules 1 to 4 for every document, and rule 5: the same bytes parse to
    identical records."""
    docs = _fixture_docs(mini)
    assert {d.format for d, _ in docs} == {"md", "txt", "html", "xml", "pdf", "json", "csv"}
    for doc, raw in docs:
        first = parse_document(doc.format, raw, doc.text, doc.doc_id)
        second = parse_document(doc.format, raw, doc.text, doc.doc_id)
        assert first == second  # rule 5
        assert first.elements, doc.uri
        src = store_mod.source_record(doc, raw, None)
        assert check(src, first.elements, doc.text, raw) == [], doc.uri


def test_same_input_gives_the_same_store_bytes(tmp_path, mini):
    _, a = _build(tmp_path / "a", mini)
    _, b = _build(tmp_path / "b", mini)
    assert a == b
    assert _files(tmp_path / "a") == _files(tmp_path / "b")


def test_existing_files_are_left_untouched(tmp_path, mini):
    _build(tmp_path / "s", mini)
    before = {p: p.stat().st_mtime_ns for p in (tmp_path / "s").rglob("*") if p.is_file()
              and p.name != "HEAD"}
    _, snap = _build(tmp_path / "s", mini)
    after = {p: p.stat().st_mtime_ns for p in before}
    assert before == after
    assert Store.open(tmp_path / "s").snapshot_id == snap


def test_a_different_record_under_an_existing_id_is_refused(tmp_path, mini):
    _build(tmp_path / "s", mini)
    doc_id = sorted(mini.docs)[0]
    path = tmp_path / "s" / "docs" / doc_id[:2] / f"{doc_id}.json"
    path.write_bytes(path.read_bytes().replace(b'"license":"fixture-original"',
                                               b'"license":"other"'))
    s = Store.create(tmp_path / "s")
    with pytest.raises(StoreError, match="already holds a different"):
        s.add(mini.docs[doc_id], _raw(mini, doc_id), license="fixture-original")


def test_snapshots_are_immutable_and_head_moves(tmp_path, mini):
    _, full = _build(tmp_path / "s", mini)
    first = sorted(mini.docs)[0]
    s = Store.create(tmp_path / "s")
    s.add(mini.docs[first], _raw(mini, first), license="fixture-original")
    one = s.commit()
    assert one != full
    assert Store.open(tmp_path / "s").doc_ids() == [first]
    old = Store.open(tmp_path / "s", snapshot=full)
    assert old.doc_ids() == sorted(mini.docs) and old.snapshot_id == full


def test_open_store_adds_to_its_snapshot(tmp_path, mini):
    ids = sorted(mini.docs)
    s = Store.create(tmp_path / "s")
    s.add(mini.docs[ids[0]], _raw(mini, ids[0]))
    s.commit()
    s = Store.open(tmp_path / "s")
    s.add(mini.docs[ids[1]], _raw(mini, ids[1]))
    s.commit()
    assert Store.open(tmp_path / "s").doc_ids() == ids[:2]


def test_add_refuses_bytes_that_do_not_match_the_doc_id(tmp_path, mini):
    doc_id = sorted(mini.docs)[0]
    with pytest.raises(ValueError, match="SHA-256"):
        Store.create(tmp_path / "s").add(mini.docs[doc_id], b"other bytes")


def test_add_refuses_a_document_that_does_not_conform_and_writes_nothing(tmp_path, monkeypatch):
    text = "Some text.\n\nMore text."
    raw = text.encode()
    doc = Document(hashlib.sha256(raw).hexdigest(), text, "txt", "1", "file://t.txt")
    real = store_mod.parse_document

    def broken(fmt, raw, text, doc_id):
        parsed = real(fmt, raw, text, doc_id)
        return type(parsed)(parsed.elements[:1], 0, 0)  # drops the second paragraph

    monkeypatch.setattr(store_mod, "parse_document", broken)
    s = Store.create(tmp_path / "s")
    with pytest.raises(ConformanceError) as e:
        s.add(doc, raw)
    assert e.value.doc_id == doc.doc_id and e.value.problems[0].startswith("rule 1:")
    assert not list((tmp_path / "s").rglob(doc.doc_id + "*"))


def test_unknown_doc_and_missing_store(tmp_path, mini):
    _build(tmp_path / "s", mini)
    with pytest.raises(KeyError):
        Store.open(tmp_path / "s").text("0" * 64)
    with pytest.raises(StoreError, match="no store"):
        Store.open(tmp_path / "nothing")
    with pytest.raises(StoreError, match="snapshot"):
        Store.open(tmp_path / "s", snapshot="f" * 64)


def test_tampered_record_or_text_is_detected(tmp_path, mini):
    _build(tmp_path / "s", mini)
    doc_id = sorted(mini.docs)[0]
    text_path = tmp_path / "s" / "text" / doc_id[:2] / f"{doc_id}.txt"
    text_path.write_bytes(text_path.read_bytes() + b"x")
    with pytest.raises(StoreError, match="text"):
        Store.open(tmp_path / "s").text(doc_id)
    rec_path = tmp_path / "s" / "docs" / doc_id[:2] / f"{doc_id}.json"
    rec_path.write_bytes(rec_path.read_bytes() + b" ")
    with pytest.raises(StoreError, match="record"):
        Store.open(tmp_path / "s").source(doc_id)


def test_text_keeps_carriage_returns_and_form_feeds(tmp_path):
    text = "line one\r\nline two\n\f\npage two\r\n"
    raw = text.encode()
    doc = Document(hashlib.sha256(raw).hexdigest(), text, "txt", "1", "file://crlf.txt")
    s = Store.create(tmp_path / "s")
    s.add(doc, raw)
    s.commit()
    assert Store.open(tmp_path / "s").text(doc.doc_id) == text


def test_doc_record_file_is_a_valid_doc_record(tmp_path, mini):
    _build(tmp_path / "s", mini)
    doc_id = sorted(mini.docs)[0]
    data = (tmp_path / "s" / "docs" / doc_id[:2] / f"{doc_id}.json").read_bytes()
    rec = DocRecord.model_validate_json(data)
    assert rec.source.doc_id == doc_id and rec.format_version == "0.1"


# `adr ingest` (src/adr_store/cli.py)

def test_ingest_mini_writes_a_snapshot_and_compile_figures(tmp_path, capsys, mini):
    from adr_store import cli

    assert cli.main(["ingest", "mini", "--store", str(tmp_path / "s")]) == 0
    s = Store.open(tmp_path / "s")
    assert s.doc_ids() == sorted(mini.docs)
    assert s.source(s.doc_ids()[0]).license == "fixture-original"
    figures = json.loads((tmp_path / "s" / "compile" / f"{s.snapshot_id}.json").read_text())
    assert figures["corpus"] == "mini" and figures["snapshot"] == s.snapshot_id
    assert figures["documents"] == len(mini.docs)
    assert figures["conformance"] == {"documents": 7, "failures": 0, "pass_rate": 1.0}
    assert figures["leaves_with_span"] == 1.0
    assert figures["elements"] == figures["leaves"] + figures["sections"]
    by_format = figures["by_format"]
    assert sorted(by_format) == ["html", "json", "md", "pdf", "xml"]
    assert by_format["md"]["documents"] == 2 and by_format["md"]["share_with_sections"] == 1.0
    assert by_format["md"]["headings_found"] == by_format["md"]["headings_aligned"] == 5
    assert by_format["json"]["alignment_rate"] is None
    assert by_format["pdf"]["share_leaves_with_page"] == 1.0
    assert by_format["md"]["share_leaves_with_page"] is None
    out = capsys.readouterr().out
    assert s.snapshot_id in out and "conformance failures: 0" in out


def test_ingest_is_repeatable(tmp_path, mini):
    from adr_store import cli

    assert cli.main(["ingest", "mini", "--store", str(tmp_path / "a")]) == 0
    assert cli.main(["ingest", "mini", "--store", str(tmp_path / "a")]) == 0
    assert cli.main(["ingest", "mini", "--store", str(tmp_path / "b")]) == 0
    assert _files(tmp_path / "a") == _files(tmp_path / "b")


def test_ingest_fails_clearly_on_a_conformance_violation(tmp_path, capsys, monkeypatch):
    from adr_store import cli

    def broken(fmt, raw, text, doc_id):
        parsed = parse_document(fmt, raw, text, doc_id)
        return type(parsed)(parsed.elements[1:], 0, 0)

    monkeypatch.setattr(store_mod, "parse_document", broken)
    assert cli.main(["ingest", "mini", "--store", str(tmp_path / "s")]) == 1
    err = capsys.readouterr().err
    assert "7 of 7 documents fail conformance" in err and "rule 1:" in err
    assert "refund_policy.md" in err
    assert not (tmp_path / "s" / "HEAD").exists()


def test_ingest_reports_a_corpus_that_cannot_load(tmp_path, capsys, monkeypatch):
    from adr_eval import runner
    from adr_store import cli

    def missing(name):
        raise runner.RunError("corpora/x/manifest.json: not found; run `adr-eval fetch x`")

    monkeypatch.setattr(cli, "load_checked_corpus", missing)
    assert cli.main(["ingest", "mini", "--store", str(tmp_path / "s")]) == 2
    assert "not found" in capsys.readouterr().err


def test_ingest_exits_3_naming_the_document_on_an_unexpected_error(tmp_path, capsys,
                                                                   monkeypatch):
    from adr_store import cli

    def crashing(fmt, raw, text, doc_id):
        if fmt == "md":
            raise RuntimeError("parser bug\nwith a second line")
        return parse_document(fmt, raw, text, doc_id)

    monkeypatch.setattr(store_mod, "parse_document", crashing)
    assert cli.main(["ingest", "mini", "--store", str(tmp_path / "s")]) == 3
    err = capsys.readouterr().err
    assert err.count("\n") == 1, err  # one line
    assert "RuntimeError" in err and "parser bug" in err and ".md" in err
    assert not (tmp_path / "s" / "HEAD").exists()


def test_ingest_exits_3_naming_the_document_it_cannot_read(tmp_path, capsys, monkeypatch):
    from adr_store import cli

    real_load, real_read = cli.load_checked_corpus, Path.read_bytes

    def unreadable(self):
        if self.name == "refund_policy.md":
            raise PermissionError(13, "Permission denied", str(self))
        return real_read(self)

    def load(name):  # the corpus loads; reading one document for the store then fails
        loaded = real_load(name)
        monkeypatch.setattr(Path, "read_bytes", unreadable)
        return loaded

    monkeypatch.setattr(cli, "load_checked_corpus", load)
    assert cli.main(["ingest", "mini", "--store", str(tmp_path / "s")]) == 3
    err = capsys.readouterr().err
    assert err.count("\n") == 1, err
    assert "PermissionError" in err and "while processing refund_policy.md (" in err
    assert not (tmp_path / "s" / "HEAD").exists()


def test_ingest_exits_3_on_an_unexpected_error_after_the_documents(tmp_path, capsys,
                                                                   monkeypatch):
    from adr_store import cli

    def broken(*args):
        raise KeyError("by_format")

    monkeypatch.setattr(cli, "compile_figures", broken)
    assert cli.main(["ingest", "mini", "--store", str(tmp_path / "s")]) == 3
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "KeyError" in err
