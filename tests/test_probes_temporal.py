"""Temporal probes (Phase 2 spec §10.2, T1-T5) on a synthetic gov-shaped store: one eCFR chain
of two versions with a changed and a removed section, Federal Register documents and an IRM
chapter. No model calls; lexical-only index."""

import json
import re
from collections import defaultdict
from datetime import date, timedelta

import pytest

from adr_eval import runner
from adr_eval.cli import main
from adr_eval.corpora.base import load_corpus
from adr_eval.corpora.gov import GovAdapter
from adr_eval.corpora.registry import write_manifest
from adr_eval.models import Evidence, GoldenItem
from adr_eval.probes import temporal
from adr_store import applicability, dedup, tools
from adr_store.store import Store
from tests.conftest import _base
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


# -- the probe sets -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def store(gov, tmp_path_factory):
    """A store of the gov fixture with its applicability and dedup overlays and an active
    lexical-only p1-struct-bc index."""
    path = tmp_path_factory.mktemp("gov-store") / "store"
    s = Store.create(path)
    for d in sorted(gov.manifest.documents, key=lambda d: d.doc_id):
        s.add(gov.docs[d.doc_id], (gov.root / d.path).read_bytes())
    s.commit()
    s = Store.open(path)
    overlay, _ = applicability.derive(s, GOV_CONFIG)
    applicability.write_overlay(path, overlay)
    t = tools.Tools(path)
    t.index("p1-struct-bc", lexical_only=True, w_bc=2)
    idx = t.active_index()
    dedup.write_overlay(path, dedup.build(list(idx.chunks.values()), idx.snapshot,
                                          idx.chunker))
    return path


def _item(gov, **kw) -> GoldenItem:
    old = _doc(gov, OLD)
    ev = Evidence(doc_id=old.doc_id, char_start=0, char_end=5,
                  quote=gov.docs[old.doc_id].text[:5])
    return GoldenItem(**{**_base(), "corpus": "gov", "evidence": [ev], **kw})


@pytest.fixture(scope="module")
def items(gov):
    return [_item(gov, id="gov-asof-1", qtype="policy_asof", as_of=date(2024, 6, 27),
                  question="Housatonic River drawbridge opening schedule"),
            _item(gov, id="gov-factoid-1", question="Which drawbridge regulations apply?"),
            _item(gov, id="gov-insufficient-1", qtype="insufficient", evidence=[],
                  question="What is the bridge toll?")]


@pytest.fixture(scope="module")
def overlay(store):
    s = Store.open(store)
    return applicability.load_overlay(store, s.snapshot_id)


def test_build_gives_the_five_sets(gov, items, overlay):
    probes = temporal.build(gov, items, overlay)
    by = {}
    for p in probes:
        by.setdefault((p.set, p.mode), []).append(p)
    assert {k: len(v) for k, v in by.items()} == {
        ("T1", "as_of"): 1, ("T2", "default"): 1, ("T2", "as_of"): 1, ("T3", "default"): 1,
        ("T3", "as_of"): 1, ("T4", "default"): 3, ("T5", "as_of"): 3}
    t1 = by["T1", "as_of"][0]
    assert (t1.query, t1.as_of) == (items[0].question, "2024-06-27")
    t2 = by["T2", "as_of"][0]
    assert t2.query.startswith("§ 117.189") and t2.as_of == OLD
    assert t2.target["head_doc"] == _doc(gov, NEW).doc_id
    assert by["T2", "default"][0].as_of is None
    t3 = by["T3", "as_of"][0]
    assert t3.query.startswith("§ 117.261") and t3.as_of == OLD
    t5 = {p.target["doc"]: p for p in by["T5", "as_of"]}
    for doc_id, p in t5.items():
        valid_from = overlay.records[doc_id].valid_from
        assert p.as_of == (valid_from - timedelta(days=1)).isoformat()
        assert len(p.target["grep"]) == 30 and p.target["grep"] in gov.docs[doc_id].text
        assert p.query and "Internal Revenue Service" not in p.query
    assert {p.target["family"] for p in t5.values()} == {"fr", "irm"}
    assert len({p.probe_id for p in probes}) == len(probes)
    again = temporal.build(gov, items, overlay)
    assert [p.to_dict() for p in again] == [p.to_dict() for p in probes]


@pytest.mark.parametrize("text, line", [
    ("§ 1.1 Title.\nBody", "§ 1.1 Title."),
    ("\u200b\n§ 165.T08-0413 Safety Zone.\nBody", "§ 165.T08-0413 Safety Zone."),
    ("\ufeff \u200c\n\n  \u200d\t\n\u200b§ 2.2 Title.\u200b \nBody", "§ 2.2 Title."),
    ("\n\u200b\n", ""),
])
def test_first_line_skips_lines_of_only_whitespace_and_format_characters(text, line):
    assert temporal.first_line(text) == line


@pytest.fixture(scope="module")
def gov_zw(tmp_path_factory):
    """As `gov`, with a line of only format characters (category Cf) opening the older
    versions of § 117.189 (a changed section, T2) and § 117.261 (a removed one, T3), as
    § 165.T08-0413 of the real corpus opens with a zero-width space line."""
    root = tmp_path_factory.mktemp("gov-zw")
    GovAdapter(HTTP / "gov" / "config.json").download(root, RecordedFetcher(HTTP / "gov"))
    new = next(root.rglob(f"part-117/{NEW}.xml"))
    new.write_bytes(_remove_section(new.read_bytes(), "117.261"))
    old = next(root.rglob(f"part-117/{OLD}.xml"))
    xml = old.read_bytes()
    for number, line in (("117.189", b"<P>&#xFEFF; &#x200C;</P>"), ("117.261", b"<P>&#x200B;</P>")):
        xml, n = re.subn(rf'(<DIV8 N="{re.escape(number)}"[^>]*>)'.encode(),
                         lambda m, line=line: m.group(1) + line, xml)
        assert n == 1
    old.write_bytes(xml)
    m = GovAdapter(HTTP / "gov" / "config.json").build_manifest(root)
    write_manifest(m, root / "manifest.json")
    return load_corpus(root / "manifest.json", root)


def test_section_queries_skip_a_leading_line_of_format_characters(gov_zw, items):
    removed = GovAdapter().removed_sections(gov_zw)
    assert [s.text.split("\n", 1)[0] for s, _, _ in removed] == ["\u200b"]
    by = {(p.set, p.mode): p for p in temporal.build(gov_zw, items[:0], _NoT5())}
    for mode in ("default", "as_of"):
        assert by["T3", mode].query == (
            "§ 117.261 Atlantic Intracoastal Waterway from St. Marys River to Key Largo.")
        assert by["T2", mode].query == "§ 117.189 Sacramento River."


class _NoT5:
    """An applicability overlay whose every document has a `valid_from` (T5 needs one)."""

    class _R:
        valid_from = date(2024, 1, 1)

    records = defaultdict(_R)


def test_the_probes_pass_on_the_tools(gov, items, overlay, store):
    r = temporal.run(temporal.build(gov, items, overlay), tools.Tools(store))
    s = r["summary"]
    for name, modes in s.items():
        for mode, block in modes.items():
            assert block["passed"] == block["n"] and block["failed"] == [], (name, mode)
    assert s["T3"]["as_of"]["recall@10"] == 1.0  # the removed section is found when dated
    assert s["T2"]["as_of"]["other_version_chunks"] == 0
    assert s["T2"]["default"]["head_found@10"] == 1
    t5 = s["T5"]["as_of"]
    assert t5["search_absent"] == t5["grep_absent"] == t5["read_refused"] == 3
    assert t5["control_grep_found"] == 3
    assert r["dedup"] is True and len(r["probes"]) == 11


class Leaky:
    """Tools that drop the caller's filters and dedup (the Phase 1 view): every rule fails."""

    def __init__(self, real):
        self.real = real

    def __getattr__(self, name):
        return getattr(self.real, name)

    def search(self, query, top=10, *, filters=None, dedup=None):
        return self.real.search(query, top, filters={"include_superseded": True}, dedup=False)

    def grep(self, pattern, doc=None, max=100, *, filters=None, **kw):
        return self.real.grep(pattern, doc, max, filters={"include_superseded": True}, **kw)

    def read(self, doc_id, *a, filters=None, **kw):
        return self.real.read(doc_id, *a, filters={"include_superseded": True}, **kw)


def test_the_probes_fail_when_the_filters_are_dropped(gov, items, overlay, store):
    r = temporal.run(temporal.build(gov, items, overlay), Leaky(tools.Tools(store)))
    s = r["summary"]
    assert s["T2"]["default"]["passed"] == 0 and s["T3"]["default"]["passed"] == 0
    assert s["T2"]["as_of"]["passed"] == 0 and s["T2"]["as_of"]["other_version_chunks"] > 0
    assert s["T1"]["as_of"]["passed"] == 0
    assert s["T5"]["as_of"]["passed"] == 0 and s["T5"]["as_of"]["read_refused"] == 0
    assert s["T5"]["as_of"]["grep_absent"] == 0
    failed = {p["probe_id"]: p for p in r["probes"] if not p["pass"]}
    assert set(s["T2"]["default"]["failed"]) <= set(failed)
    one = failed[s["T3"]["default"]["failed"][0]]
    assert one["offending"] and one["offending"][0]["doc_id"] == _doc(gov, OLD).doc_id


class Refusing(Leaky):
    """Tools whose `read` refuses for another reason: undated too (`always`), or dated with
    a reason that is not "not in force"."""

    def __init__(self, real, always: bool):
        super().__init__(real)
        self.always = always

    def search(self, *a, **kw):
        return self.real.search(*a, **kw)

    def grep(self, *a, **kw):
        return self.real.grep(*a, **kw)

    def read(self, doc_id, *a, filters=None, **kw):
        if self.always or filters:
            raise tools.ToolError(f"no document {doc_id[:12]} in snapshot")
        return self.real.read(doc_id, *a, **kw)


@pytest.mark.parametrize("always", [False, True], ids=["other-reason", "control-fails"])
def test_t5_passes_only_on_a_not_in_force_refusal_and_a_working_control_read(
        gov, items, overlay, store, always):
    t5 = [p for p in temporal.build(gov, items, overlay) if p.set == "T5"]
    good = temporal.run(t5, tools.Tools(store))
    for o in good["probes"]:
        assert o["pass"] and o["read_refused"] and o["control_read_ok"]
        assert f"not in force on {o['as_of']}" in o["read_refusal"]
    bad = temporal.run(t5, Refusing(tools.Tools(store), always))
    s = bad["summary"]["T5"]["as_of"]
    assert s["passed"] == 0 and s["read_refused"] == 0
    assert s["search_absent"] == s["grep_absent"] == len(t5)
    assert s["control_read_ok"] == (0 if always else len(t5))
    assert all("no document" in o["read_refusal"] for o in bad["probes"])


def test_a_caller_needs_the_acl_layer(gov, items, overlay, store):
    with pytest.raises(ValueError, match="ACL"):
        temporal.run(temporal.build(gov, items, overlay), tools.Tools(store),
                     caller="user:auditor")


def _recorded(monkeypatch, tmp_path, fingerprint: str | None) -> None:
    """Committed Phase 1 summaries holding a p1-struct-bc run of `fingerprint` (None: none)."""
    from adr_eval import systems

    root = tmp_path / "summaries"
    root.mkdir()
    monkeypatch.setattr(systems, "PHASE1_SUMMARIES", root)
    if fingerprint is not None:
        d = root / "gov-p1-struct-bc-test-retrieval-20261113T000000"
        d.mkdir()
        (d / "retrieval.json").write_text(json.dumps({"config": {"fingerprint": fingerprint}}))


def _cli_corpus(monkeypatch, gov, items):
    monkeypatch.setattr(runner, "load_checked_corpus", lambda corpus: gov)
    monkeypatch.setattr(runner, "load_golden", lambda corpus, loaded: items)


def test_the_cli_writes_the_probe_files_deterministically(gov, items, store, tmp_path,
                                                          monkeypatch, capsys):
    _cli_corpus(monkeypatch, gov, items)
    _recorded(monkeypatch, tmp_path, tools.Tools(store).active_index().fingerprint)
    out = tmp_path / "runs"
    for _ in range(2):
        assert main(["probes", "temporal", "gov", "--store", str(store), "--out",
                     str(out)]) == 0
    printed = capsys.readouterr().out
    assert "T1" in printed and "T5" in printed
    first, second = sorted(out.iterdir())
    assert first.name.startswith("probes-temporal-gov-")
    assert (first / "probes.json").read_bytes() == (second / "probes.json").read_bytes()
    data = json.loads((first / "probes.json").read_text())
    assert data["config"]["seed"] == 20261116 and data["config"]["sizes"]["T4"] == 3
    assert data["config"]["spec_sizes"] == {"T1": 40, "T2": 189, "T3": 145, "T4": 297,
                                            "T5": 171}
    assert data["config"]["index_system"] == "p1-struct-bc"
    assert (data["config"]["index_phase1"], data["config"]["allow_other_index"]) == \
        (True, False)
    assert (first / "probes.md").read_text().startswith("# Temporal probes")
    assert main(["probes", "temporal", "gov", "--store", str(store), "--out", str(out),
                 "--as", "user:auditor"]) == 2
    assert "ACL" in capsys.readouterr().err


def test_the_cli_refuses_an_index_that_is_not_the_recorded_phase1_one(gov, items, store,
                                                                      tmp_path, monkeypatch,
                                                                      capsys):
    """The probes check the Phase 1 index: the active index must be p1-struct-bc with the
    fingerprint of a committed Phase 1 run, unless --allow-other-index (recorded)."""
    _cli_corpus(monkeypatch, gov, items)
    _recorded(monkeypatch, tmp_path, "0" * 64)
    out = tmp_path / "runs"
    assert main(["probes", "temporal", "gov", "--store", str(store), "--out", str(out)]) == 2
    err = capsys.readouterr().err
    assert "p1-struct-bc" in err and "000000000000" in err and "--allow-other-index" in err
    assert not out.exists()
    assert main(["probes", "temporal", "gov", "--store", str(store), "--out", str(out),
                 "--allow-other-index"]) == 0
    data = json.loads(next(out.iterdir()).joinpath("probes.json").read_text())
    assert (data["config"]["index_phase1"], data["config"]["allow_other_index"]) == \
        (False, True)
    assert "other index" in next(out.iterdir()).joinpath("probes.md").read_text()
