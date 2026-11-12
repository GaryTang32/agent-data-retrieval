import csv
import io
import json
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from adr_eval.corpora.base import HashMismatch, fetch_manifest, load_corpus, sha256_bytes
from adr_eval.corpora.bench import BenchAdapter
from adr_eval.corpora.gov import GovAdapter
from adr_eval.corpora.http import USER_AGENT, PoliteFetcher
from adr_eval.corpora.registry import get_adapter, write_manifest
from adr_eval.corpora.research import ResearchAdapter

HERE = Path(__file__).parent
HTTP = HERE / "fixtures" / "http"
MINI = HERE / "fixtures" / "mini"
REPO = HERE.parent
PDF = (MINI / "service_charter.pdf").read_bytes()


class RecordedFetcher:
    """Serves recorded responses from tests/fixtures/http/<corpus>/urls.json."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.urls = json.loads((directory / "urls.json").read_text(encoding="utf-8"))
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        return (self.directory / self.urls[url]).read_bytes()


@pytest.fixture
def recorded_gov(tmp_path):
    fetcher = RecordedFetcher(HTTP / "gov")
    GovAdapter(HTTP / "gov" / "config.json").download(tmp_path, fetcher)
    return SimpleNamespace(root=tmp_path, fetcher=fetcher)


@pytest.fixture
def recorded_gov_loaded(recorded_gov):
    m = get_adapter("gov").build_manifest(recorded_gov.root)
    path = recorded_gov.root / "manifest.json"
    write_manifest(m, path)
    return load_corpus(path, recorded_gov.root)


@pytest.fixture
def repo_root():
    return REPO


# --- gov -------------------------------------------------------------------


def test_gov_manifest_from_recorded_http(recorded_gov):
    m = get_adapter("gov").build_manifest(recorded_gov.root)
    assert {d.format for d in m.documents} >= {"xml", "json", "html"} and all(
        len(d.doc_id) == 64 for d in m.documents
    )


def test_gov_version_pairs_differ(recorded_gov_loaded):
    pairs = get_adapter("gov").version_pairs(recorded_gov_loaded)
    assert pairs and all(
        a.text != b.text and a.source_version < b.source_version for a, b in pairs
    )


def test_records_have_id_and_doc_id(recorded_gov_loaded):
    assert all(
        {"id", "_doc_id"} <= r.keys() for r in get_adapter("gov").records(recorded_gov_loaded)
    )


def test_gov_manifest_versions_uris_and_paths(recorded_gov):
    m = get_adapter("gov").build_manifest(recorded_gov.root)
    by_path = {d.path: d for d in m.documents}
    assert sorted(by_path) == [
        "data/gov/ecfr/title-33/part-117/2024-06-27.xml",
        "data/gov/ecfr/title-33/part-117/2025-06-27.xml",
        "data/gov/fr/2023-01707.json",
        "data/gov/fr/2023-01708.json",
        "data/gov/irm/part21/irm_21-005-001r.html",
    ]
    xml = by_path["data/gov/ecfr/title-33/part-117/2025-06-27.xml"]
    assert xml.source_version == "2025-06-27"
    assert xml.uri == "https://www.ecfr.gov/api/versioner/v1/full/2025-06-27/title-33.xml?part=117"
    assert by_path["data/gov/fr/2023-01707.json"].source_version == "2023-01707"
    irm = by_path["data/gov/irm/part21/irm_21-005-001r.html"]
    assert irm.source_version == "2026-09-15"  # Manual Transmittal date
    assert irm.uri == "https://www.irs.gov/irm/part21/irm_21-005-001r"
    assert {d.license for d in m.documents} == {"public-domain"}
    # every recorded uri reproduces the stored bytes, so fetch_manifest can rebuild the corpus
    fresh = recorded_gov.root / "fresh"
    fetch_manifest(m, fresh, RecordedFetcher(HTTP / "gov"))
    assert get_adapter("gov").build_manifest(fresh).snapshot() == m.snapshot()


def test_gov_download_is_resumable(recorded_gov):
    again = RecordedFetcher(HTTP / "gov")
    GovAdapter(HTTP / "gov" / "config.json").download(recorded_gov.root, again)
    # only the Federal Register list query is re-issued; no document is fetched twice
    assert len(again.calls) == 1 and "documents.json?" in again.calls[0]


def test_gov_records_shape(recorded_gov_loaded):
    rows = get_adapter("gov").records(recorded_gov_loaded)
    assert [r["id"] for r in rows] == ["2023-01707", "2023-01708"]
    row = rows[0]
    assert set(row) == {
        "id", "type", "agency", "publication_date", "year", "title", "cfr_parts", "_doc_id"
    }
    assert row["agency"] == "Coast Guard" and row["cfr_parts"] == ["33 CFR 117"]
    assert row["year"] == 2023 and row["type"] == "Proposed Rule"
    assert row["_doc_id"] in recorded_gov_loaded.docs
    assert set(get_adapter("gov").record_schema()) == set(row) - {"_doc_id"}


def test_gov_version_pairs_are_sections_of_their_documents(recorded_gov_loaded):
    pairs = get_adapter("gov").version_pairs(recorded_gov_loaded)
    sections = sorted(a.uri.rsplit("#", 1)[1] for a, _ in pairs)
    assert sections == ["117.189", "117.261"]  # 117.1 is unchanged between the two dates
    for a, b in pairs:
        assert a.uri.rsplit("#", 1)[1] == b.uri.rsplit("#", 1)[1]
        for section in (a, b):
            full = recorded_gov_loaded.docs[section.doc_id]
            assert section.text in full.text and section.source_version == full.source_version
            assert section.text.startswith("§ ")


# --- polite fetcher ------------------------------------------------------------


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.sleeps.append(round(s, 6))
        self.now += s


def test_polite_fetcher_rate_limits_per_host_and_sends_user_agent():
    seen = []

    def handler(request):
        seen.append((request.url.host, request.headers["User-Agent"]))
        return httpx.Response(200, content=b"ok")

    clock = FakeClock()
    f = PoliteFetcher(transport=httpx.MockTransport(handler), clock=clock.time, sleep=clock.sleep)
    f("https://a.example/1")
    clock.now += 0.25
    f("https://a.example/2")
    f("https://b.example/1")
    assert clock.sleeps == [0.75]
    assert USER_AGENT.startswith("adr-eval/0.1") and {ua for _, ua in seen} == {USER_AGENT}


def test_polite_fetcher_retries_server_errors_then_raises_on_404():
    codes = iter([503, 200, 404])

    def handler(request):
        return httpx.Response(next(codes), content=b"body")

    clock = FakeClock()
    f = PoliteFetcher(transport=httpx.MockTransport(handler), clock=clock.time, sleep=clock.sleep)
    assert f("https://a.example/x") == b"body"
    with pytest.raises(httpx.HTTPStatusError):
        f("https://a.example/missing")


def test_polite_fetcher_retries_dropped_connections():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadError("tunnel closed")
        return httpx.Response(200, content=b"ok")

    clock = FakeClock()
    f = PoliteFetcher(transport=httpx.MockTransport(handler), clock=clock.time, sleep=clock.sleep)
    assert f("https://a.example/x") == b"ok" and len(calls) == 2


def test_polite_download_resumes_partial_file_and_checks_hash(tmp_path):
    payload = bytes(range(256)) * 40
    ranges = []

    def handler(request):
        rng = request.headers.get("Range")
        ranges.append(rng)
        start = int(rng.removeprefix("bytes=").rstrip("-")) if rng else 0
        return httpx.Response(206 if rng else 200, content=payload[start:])

    clock = FakeClock()
    f = PoliteFetcher(transport=httpx.MockTransport(handler), clock=clock.time, sleep=clock.sleep)
    dest = tmp_path / "big.bin"
    (tmp_path / "big.bin.part").write_bytes(payload[:1000])
    f.download("https://a.example/big", dest, sha256_bytes(payload))
    assert dest.read_bytes() == payload and ranges == ["bytes=1000-"]
    assert not (tmp_path / "big.bin.part").exists()
    f.download("https://a.example/big", dest, sha256_bytes(payload))  # present: no request
    assert len(ranges) == 1
    with pytest.raises(HashMismatch):
        f.download("https://a.example/big", tmp_path / "other.bin", "0" * 64)
    assert not (tmp_path / "other.bin").exists()


# --- research --------------------------------------------------------------------


def _local_pdfs(root: Path) -> int:
    with open(root / "papers" / "manifest.csv", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return sum(r["status"] == "downloaded" and (root / r["local_file"]).is_file() for r in rows)


needs_local_pdfs = pytest.mark.skipif(
    _local_pdfs(REPO) < 200,
    reason="needs >=200 local papers/ PDFs (run scripts/download_papers.py); PDFs are not in git",
)


@needs_local_pdfs
def test_research_sample_is_seeded_and_stable(repo_root):
    a = get_adapter("research").build_manifest(repo_root)
    b = get_adapter("research").build_manifest(repo_root)
    assert a.snapshot() == b.snapshot()


@needs_local_pdfs
def test_research_manifest_schema(repo_root):
    m = get_adapter("research").build_manifest(repo_root)
    fmts = [d.format for d in m.documents]
    assert fmts.count("pdf") == 200 and fmts.count("csv") == 1 and fmts.count("md") >= 1
    assert all(d.uri == f"file://{d.path}" for d in m.documents)
    assert all(d.source_version == "sha256:" + d.doc_id[:12] for d in m.documents)


def _fake_repo(root: Path, n_pdfs: int) -> None:
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "a.md").write_text("# A\n", encoding="utf-8")
    (root / "reports" / "skip.html").write_text("<p>x</p>", encoding="utf-8")
    (root / "research_notes" / "t").mkdir(parents=True)
    (root / "research_notes" / "t" / "n.md").write_text("note\n", encoding="utf-8")
    (root / "papers" / "x").mkdir(parents=True)
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["title", "year", "url", "arxiv_id", "doi", "license", "status", "local_file"])
    for i in range(n_pdfs):
        rel = f"papers/x/p{i:03d}.pdf"
        (root / rel).write_bytes(PDF + b"\n%" + str(i).encode())
        w.writerow([f"Paper {i}, part {i}", 2020 + i % 5, f"https://e.org/{i}", f"25{i:02d}.0001",
                    "", "CC-BY-4.0", "downloaded", rel])
    w.writerow(["No pdf", "", "https://e.org/x", "", "10.1/x", "", "no_pdf_link", ""])
    w.writerow(["Gone", "2024", "https://e.org/g", "", "", "", "downloaded", "papers/x/gone.pdf"])
    (root / "papers" / "manifest.csv").write_text(out.getvalue(), encoding="utf-8")


def test_research_sample_offline(tmp_path):
    _fake_repo(tmp_path, 230)
    adapter = ResearchAdapter(sample_size=200)
    a, b = adapter.build_manifest(tmp_path), adapter.build_manifest(tmp_path)
    assert a.snapshot() == b.snapshot()
    paths = [d.path for d in a.documents]
    assert "reports/a.md" in paths and "research_notes/t/n.md" in paths
    assert "reports/skip.html" not in paths and "papers/x/gone.pdf" not in paths
    pdfs = [d for d in a.documents if d.format == "pdf"]
    assert len(pdfs) == 200 and {d.license for d in pdfs} == {"CC-BY-4.0"}
    assert ResearchAdapter(sample_size=200, seed=1).build_manifest(tmp_path).snapshot() != (
        a.snapshot()
    )


def test_research_versions_come_from_bytes_not_git(tmp_path, monkeypatch):
    _fake_repo(tmp_path, 210)
    before = ResearchAdapter(sample_size=200).build_manifest(tmp_path)

    def no_subprocess(*args, **kwargs):
        raise AssertionError(f"build_manifest must not run subprocesses: {args}")

    monkeypatch.setattr(subprocess, "run", no_subprocess)
    monkeypatch.setattr(subprocess, "Popen", no_subprocess)
    after = ResearchAdapter(sample_size=200).build_manifest(tmp_path)
    assert after.snapshot() == before.snapshot()
    assert all(d.source_version == "sha256:" + d.doc_id[:12] for d in after.documents)


def test_research_too_few_pdfs_raises(tmp_path):
    _fake_repo(tmp_path, 5)
    with pytest.raises(ValueError, match="download_papers"):
        ResearchAdapter(sample_size=200).build_manifest(tmp_path)


def test_research_records_spans_and_ids(tmp_path):
    _fake_repo(tmp_path, 3)
    adapter = ResearchAdapter(sample_size=3)
    write_manifest(adapter.build_manifest(tmp_path), tmp_path / "m.json")
    corpus = load_corpus(tmp_path / "m.json", tmp_path)
    rows = adapter.records(corpus)
    assert [r["id"] for r in rows][:3] == ["2500.0001", "2501.0001", "2502.0001"]
    assert rows[3]["id"] == "10.1/x" and rows[4]["id"].startswith("url:")
    assert rows[0]["year"] == 2020 and rows[3]["year"] is None
    text = corpus.docs[rows[0]["_doc_id"]].text
    for r in rows:
        start, end = r["_span"]
        assert next(csv.reader([text[start:end]]))[0] == r["title"]
    assert adapter.version_pairs(corpus) == []


# --- bench ---------------------------------------------------------------------------


def _write_parquet(rows: list[dict], path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)
    return sha256_bytes(path.read_bytes())


@pytest.fixture
def bench_setup(tmp_path):
    root = tmp_path / "root"
    docs = [
        {"doc_id": f"dsid_{i:02d}", "source_type": "slack" if i % 2 else "confluence",
         "title": f"Doc {i}", "content": f"Body of document {i}.\nSecond line."}
        for i in range(30)
    ]
    docs.append({"doc_id": "dsid_03", "source_type": "hubspot", "title": "Dup", "content": "x"})
    questions = [
        {"question_id": "q1", "question_type": "basic", "question": "?", "source_types": [],
         "expected_doc_ids": ["dsid_01"], "gold_answer": "a", "answer_facts": ["a"]},
        {"question_id": "q2", "question_type": "completeness", "question": "?",
         "source_types": [], "expected_doc_ids": ["dsid_03", "dsid_05"], "gold_answer": "b",
         "answer_facts": []},
        {"question_id": "q3", "question_type": "high_level", "question": "?",
         "source_types": [], "expected_doc_ids": [], "gold_answer": "c", "answer_facts": []},
        {"question_id": "q4", "question_type": "info_not_found", "question": "?",
         "source_types": [], "expected_doc_ids": [], "gold_answer": "d", "answer_facts": []},
    ]
    dsha = _write_parquet(docs, root / "data/bench/_source/documents.parquet")
    qsha = _write_parquet(questions, root / "data/bench/_source/questions.parquet")
    cfg = json.loads((REPO / "corpora/bench/config.json").read_text(encoding="utf-8"))
    cfg["max_docs"] = 10
    cfg["documents"].update(url="https://example.invalid/d.parquet", sha256=dsha)
    cfg["questions"].update(url="https://example.invalid/q.parquet", sha256=qsha)
    cfg_path = tmp_path / "bench.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    adapter = BenchAdapter(cfg_path)
    adapter.download(root, fetcher=None)
    return SimpleNamespace(root=root, adapter=adapter, config=cfg)


def test_bench_subset_keeps_gold_docs_and_is_seeded(bench_setup):
    m = bench_setup.adapter.build_manifest(bench_setup.root)
    assert len(m.documents) == 10
    uris = [d.uri for d in m.documents]
    for dsid in ("dsid_01", "dsid_05"):
        assert sum(f"doc_id={dsid}" in u for u in uris) == 1
    assert sum("doc_id=dsid_03" in u for u in uris) == 2  # both rows of a duplicated id
    assert {d.format for d in m.documents} == {"md"} and {d.license for d in m.documents} == {"MIT"}
    assert {d.source_version for d in m.documents} == {bench_setup.config["revision"]}
    again = BenchAdapter(bench_setup.adapter.config_path)
    shutil.rmtree(bench_setup.root / "data/bench/docs")
    again.download(bench_setup.root, fetcher=None)
    assert again.build_manifest(bench_setup.root).snapshot() == m.snapshot()


def test_bench_fetcher_rebuilds_documents_from_source(bench_setup):
    m = bench_setup.adapter.build_manifest(bench_setup.root)
    shutil.rmtree(bench_setup.root / "data/bench/docs")
    fetch_manifest(m, bench_setup.root, bench_setup.adapter.fetcher(bench_setup.root))
    assert bench_setup.adapter.build_manifest(bench_setup.root).snapshot() == m.snapshot()


def test_bench_native_items_and_records(bench_setup):
    m = bench_setup.adapter.build_manifest(bench_setup.root)
    write_manifest(m, bench_setup.root / "m.json")
    corpus = load_corpus(bench_setup.root / "m.json", bench_setup.root)
    items = bench_setup.adapter.native_items(bench_setup.root, manifest=m)
    assert [(i["question_id"], i["qtype"]) for i in items] == [
        ("q1", "factoid"), ("q2", "overview"), ("q4", "insufficient")
    ]
    q2 = items[1]
    assert len(q2["manifest_doc_ids"]) == 3 and set(q2["manifest_doc_ids"]) <= set(corpus.docs)
    rows = bench_setup.adapter.records(corpus)
    assert len(rows) == 10 and set(rows[0]) == {"id", "source_type", "title", "_doc_id"}
    one = next(r for r in rows if r["id"] == "dsid_01")
    assert one == {"id": "dsid_01", "source_type": "slack", "title": "Doc 1",
                   "_doc_id": one["_doc_id"]}
    assert corpus.docs[one["_doc_id"]].text.startswith("# Doc 1\n")
    assert bench_setup.adapter.version_pairs(corpus) == []


# --- mini and registry ---------------------------------------------------------------


def test_mini_manifest_matches_committed_fixture():
    built = get_adapter("mini").build_manifest(MINI)
    committed = json.loads((MINI / "manifest.json").read_text(encoding="utf-8"))
    assert built.model_dump(mode="json") == committed


def test_mini_records_and_version_pairs():
    corpus = load_corpus(MINI / "manifest.json", MINI)
    adapter = get_adapter("mini")
    rows = adapter.records(corpus)
    assert len(rows) == 6 and rows[0]["id"] == "REC-001" and rows[0]["year"] == 2019
    assert all(r["_doc_id"] in corpus.docs for r in rows)
    pairs = adapter.version_pairs(corpus)
    assert [(a.source_version, b.source_version) for a, b in pairs] == [
        ("2023-01-01", "2024-01-01")
    ]
    assert "60 days" in pairs[0][0].text and "45 days" in pairs[0][1].text


def test_make_manifest_script_delegates_to_registry(monkeypatch):
    import adr_eval.corpora.registry as registry

    built = []
    monkeypatch.setattr(registry, "build", lambda name, root=None: built.append(name))
    monkeypatch.setattr(sys, "argv", ["make_manifest.py", "mini"])
    runpy.run_path(str(REPO / "scripts" / "make_manifest.py"), run_name="__main__")
    assert built == ["mini"]


def test_get_adapter_names():
    assert {get_adapter(n).name for n in ("gov", "research", "bench", "mini")} == {
        "gov", "research", "bench", "mini"
    }
    with pytest.raises(ValueError):
        get_adapter("nope")
