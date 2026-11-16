"""Applicability overlay: envelope records, the deterministic deriver and filters (spec §4.2–§4.4,
§12 Applicability)."""

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from adr_eval.corpora.base import Document
from adr_eval.corpora.extract import extract_text
from adr_eval.corpora.gov import ecfr_url, fr_document_url
from adr_store import applicability as ap
from adr_store import cli, records
from adr_store.applicability import Envelope, Filters, admits
from adr_store.records import canonical_json
from adr_store.store import Store, StoreError

FIXTURES = Path(__file__).parents[1] / "fixtures" / "store"
ECFR = (FIXTURES / "ecfr_part.xml").read_bytes()
HTML = (FIXTURES / "nested.html").read_bytes()
GUIDE = (FIXTURES / "guide.md").read_bytes()
FR_FIELDS = ["document_number", "type", "action", "dates", "publication_date", "effective_on",
             "agencies"]
IRM_URI = "https://www.irs.gov/irm/part5/irm_05-019-001r"
GOV_CONFIG = {
    "corpus": "gov",
    "parts": [
        {"title": 47, "part": "73", "agency": "federal-communications-commission",
         "dates": ["2024-06-13"]},
        {"title": 33, "part": "99", "agency": "coast-guard",
         "dates": ["2024-06-27", "2025-06-30", "2026-06-30"]},
    ],
}
AGENCIES = [{"id": 1, "name": "Homeland Security Department", "parent_id": None},
            {"id": 2, "name": "Coast Guard", "parent_id": 1}]


def _doc(raw: bytes, fmt: str, version: str, uri: str) -> tuple[Document, bytes]:
    doc_id = hashlib.sha256(raw).hexdigest()
    return Document(doc_id, extract_text(raw, fmt), fmt, version, uri), raw


def ecfr(date_: str, word: str) -> tuple[Document, bytes]:
    raw = ECFR.replace(b"<I>test</I> vessels", f"<I>{word}</I> vessels".encode())
    return _doc(raw, "xml", date_, ecfr_url(33, "99", date_))


def fr(number: str, type_: str, action: str, dates: str, published: str,
       effective: str | None) -> tuple[Document, bytes]:
    body = {"document_number": number, "type": type_, "action": action, "dates": dates,
            "publication_date": published, "effective_on": effective, "agencies": AGENCIES}
    raw = json.dumps(body).encode("utf-8")
    return _doc(raw, "json", number, fr_document_url(number, FR_FIELDS))


# the eCFR versions are added out of date order: the chain is ordered by source_version
V2025 = ecfr("2025-06-30", "middle")
V2024 = ecfr("2024-06-27", "old")
V2026 = ecfr("2026-06-30", "new")
FINAL = fr("2024-00001", "Rule", "Final rule.", "This rule is effective March 1, 2024.",
           "2024-01-30", "2024-03-01")
TEMP = fr("2024-00002", "Rule", "Temporary final rule.",
          'Under the "Section 5" rule, this rule is effective from March 1, 2024, through '
          "June 30, 2024. Comments are due by April 1, 2024.", "2024-02-20", "2024-03-01")
TEMP_UNPARSED = fr("2024-00003", "Rule", "Temporary final rule.",
                   "This rule is effective from 8 a.m. on March 1, 2024 through 5 p.m. on "
                   "March 2, 2024.", "2024-02-25", None)
EXPIRED_LIST = fr("2024-00004", "Rule", "Notification of expired temporary rules issued.",
                  "This document lists temporary Coast Guard rules that expired.",
                  "2024-04-01", None)
PROPOSED = fr("2024-00005", "Proposed Rule", "Notice of proposed rulemaking.",
              "Comments must be received by May 1, 2024.", "2024-03-15", None)
NOTICE = fr("2024-00006", "Rule", "Notification of enforcement of regulation.",
            "The regulations will be enforced on July 4, 2024.", "2024-06-20", "2024-07-04")
IRM = _doc(HTML, "html", "2026-02-03", IRM_URI)
LOOSE = _doc(GUIDE, "md", "sha256:0123456789ab", "file://guide.md")
ALL = [V2025, V2024, V2026, FINAL, TEMP, TEMP_UNPARSED, EXPIRED_LIST, PROPOSED, NOTICE, IRM,
       LOOSE]


def make_store(path: Path, docs=ALL) -> Store:
    s = Store.create(path)
    for document, raw in docs:
        s.add(document, raw)
    s.commit()
    return Store.open(path)


def doc_id(d) -> str:
    return d[0].doc_id


@pytest.fixture
def store(tmp_path) -> Store:
    return make_store(tmp_path / "store")


@pytest.fixture
def derived(store):
    return ap.derive(store, GOV_CONFIG)


def env(**kw) -> Envelope:
    base = dict(doc_id="d" * 64, chain_id=None, version_label="1", supersedes=None,
                superseded_by=None, valid_from=None, valid_to=None, validity_basis="unknown",
                status="unknown", jurisdiction=None, issuer=None, authority_tier=None,
                provenance=[])
    return Envelope(**{**base, **kw})


# -- families by URI ---------------------------------------------------------------------

def test_chain_of_reads_the_family_from_the_uri(store):
    assert ap.chain_of(store.source(doc_id(V2024))) == "ecfr:33:99"
    assert ap.chain_of(store.source(doc_id(IRM))) == "irm:5.19.1"
    assert ap.chain_of(store.source(doc_id(FINAL))) is None
    assert ap.chain_of(store.source(doc_id(LOOSE))) is None


@pytest.mark.parametrize("uri,chain", [
    ("https://www.ecfr.gov/api/versioner/v1/full/2026-06-22/title-47.xml?part=73", "ecfr:47:73"),
    ("https://www.irs.gov/irm/part21/irm_21-004-001r", "irm:21.4.1"),
    ("https://www.irs.gov/irm/part20/irm_20-001-001r", "irm:20.1.1"),
    ("https://www.ecfr.gov/current/title-33", None),
    ("file://data/gov/ecfr/title-33/part-117/2024-06-27.xml", None),
])
def test_chain_rules(store, uri, chain):
    source = store.source(doc_id(LOOSE)).model_copy(update={"uri": uri})
    assert ap.chain_of(source) == chain


# -- the deriver -------------------------------------------------------------------------

def test_ecfr_versions_form_one_chain_ordered_by_date(derived):
    recs = derived[0].records
    old, mid, new = (recs[doc_id(v)] for v in (V2024, V2025, V2026))
    assert {e.chain_id for e in (old, mid, new)} == {"ecfr:33:99"}
    assert (old.supersedes, old.superseded_by) == (None, mid.doc_id)
    assert (mid.supersedes, mid.superseded_by) == (old.doc_id, new.doc_id)
    assert (new.supersedes, new.superseded_by) == (mid.doc_id, None)
    assert (old.valid_from, old.valid_to) == (date(2024, 6, 27), date(2025, 6, 30))
    assert (mid.valid_from, mid.valid_to) == (date(2025, 6, 30), date(2026, 6, 30))
    assert (new.valid_from, new.valid_to) == (date(2026, 6, 30), None)
    for e in (old, mid, new):
        assert (e.status, e.authority_tier, e.validity_basis) == ("codified", 1, "ecfr_snapshot")
        assert (e.jurisdiction, e.issuer) == ("US-federal", "Coast Guard")
    assert old.version_label == "2024-06-27"
    sources = {p.field: p.source for p in mid.provenance}
    assert sources["valid_from"] == "manifest.source_version"
    assert sources["issuer"] == "config.parts[1].agency"


def test_federal_register_status_dates_and_tiers(derived):
    recs = derived[0].records
    final, temp, unparsed, expired, proposed, notice = (
        recs[doc_id(d)] for d in (FINAL, TEMP, TEMP_UNPARSED, EXPIRED_LIST, PROPOSED, NOTICE))
    assert (final.status, final.authority_tier) == ("final_rule", 2)
    assert (final.valid_from, final.valid_to, final.validity_basis) == (
        date(2024, 3, 1), None, "fr_effective_on")
    assert (temp.status, temp.authority_tier) == ("temporary_rule", 2)
    assert (temp.valid_from, temp.valid_to) == (date(2024, 3, 1), date(2024, 7, 1))
    assert (unparsed.status, unparsed.valid_to) == ("temporary_rule", None)
    assert (unparsed.valid_from, unparsed.validity_basis) == (
        date(2024, 2, 25), "fr_publication_date")
    assert expired.status == "temporary_rule"
    assert (proposed.status, proposed.authority_tier) == ("proposed_rule", 4)
    assert (notice.status, notice.authority_tier) == ("notice", 3)
    for e in (final, temp, unparsed, expired, proposed, notice):
        assert e.chain_id is None and e.supersedes is None and e.superseded_by is None
        assert (e.jurisdiction, e.issuer) == ("US-federal", "Coast Guard")
    assert final.version_label == "2024-00001"


def test_the_through_date_provenance_is_a_range_of_the_canonical_text(store, derived):
    temp = derived[0].records[doc_id(TEMP)]
    (p,) = [p for p in temp.provenance if p.field == "valid_to"]
    assert p.source == "fr.dates"
    text = store.text(temp.doc_id)
    dates = json.loads(text)["dates"]
    matched = json.loads(f'"{text[p.char_start:p.char_end]}"')  # undo the JSON escaping
    assert matched.startswith("effective from March 1, 2024")
    assert matched.endswith("June 30, 2024. ")
    assert matched in dates
    # the two escaped quotes before the match shift it by two characters
    assert text.index(json.dumps(dates, ensure_ascii=False)) + 1 + dates.index(matched) + 2 \
        == p.char_start


def test_irm_and_unknown_documents(derived):
    recs = derived[0].records
    irm, loose = recs[doc_id(IRM)], recs[doc_id(LOOSE)]
    assert irm.chain_id == "irm:5.19.1"
    assert (irm.valid_from, irm.valid_to, irm.validity_basis) == (
        date(2026, 2, 3), None, "irm_transmittal")
    assert (irm.status, irm.authority_tier, irm.issuer, irm.jurisdiction) == (
        "guidance", 3, "Internal Revenue Service", "US-federal")
    assert (irm.supersedes, irm.superseded_by) == (None, None)
    assert loose == env(doc_id=loose.doc_id, version_label="sha256:0123456789ab")


def test_the_overlay_covers_every_document_and_names_its_inputs(store, derived):
    overlay, _ = derived
    assert list(overlay.records) == store.doc_ids()
    assert overlay.snapshot == store.snapshot_id
    assert overlay.deriver == "envelope-1" and overlay.format_version == "0.1"
    assert overlay.config_sha256 == hashlib.sha256(json.dumps(
        GOV_CONFIG, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()


def test_the_report_counts_and_lists_parse_failures(derived):
    _, report = derived
    assert report["families"] == {"ecfr": 3, "fr": 6, "irm": 1, "unknown": 1}
    assert report["status"] == {"codified": 3, "final_rule": 1, "guidance": 1, "notice": 1,
                                "proposed_rule": 1, "temporary_rule": 3, "unknown": 1}
    assert report["validity_basis"]["fr_effective_on"] == 3
    assert report["validity_basis"]["fr_publication_date"] == 3
    assert report["authority_tier"] == {"1": 3, "2": 4, "3": 2, "4": 1, "null": 1}
    assert report["chains"] == {"count": 2, "multi_version": 1, "documents": 4, "links": 2,
                                "by_chain": {"ecfr:33:99": 3, "irm:5.19.1": 1}}
    assert report["temporary_end_dates"] == {"parsed": 1, "of": 3}
    failed = report["fr_dates_parse_failures"]
    assert [f["doc_id"] for f in failed] == sorted([doc_id(TEMP_UNPARSED), doc_id(EXPIRED_LIST)])
    assert {f["document_number"] for f in failed} == {"2024-00003", "2024-00004"}
    assert len(report["caveats"]) == 2
    assert "between pinned snapshots" in report["caveats"][0]
    assert "current pages" in report["caveats"][1]


def test_a_research_like_store_is_all_unknown(tmp_path):
    s = make_store(tmp_path / "r", [LOOSE, _doc(HTML, "html", "v1", "file://nested.html")])
    overlay, report = ap.derive(s, GOV_CONFIG)
    assert {e.status for e in overlay.records.values()} == {"unknown"}
    assert {e.validity_basis for e in overlay.records.values()} == {"unknown"}
    assert report["families"] == {"ecfr": 0, "fr": 0, "irm": 0, "unknown": 2}


def test_an_unknown_agency_slug_is_refused(store):
    config = {"parts": [{"title": 33, "part": "99", "agency": "navy", "dates": []}]}
    with pytest.raises(ValueError, match="navy"):
        ap.derive(store, config)


# -- write-once overlay files ------------------------------------------------------------

def test_rederiving_gives_byte_identical_files(store, tmp_path):
    first, _ = ap.derive(store, GOV_CONFIG)
    oid, path = ap.write_overlay(store.path, first)
    data = path.read_bytes()
    assert path == store.path / "applicability" / store.snapshot_id / "envelope-1.json"
    assert oid == hashlib.sha256(data).hexdigest()
    assert data == canonical_json(first)
    again, _ = ap.derive(Store.open(store.path), GOV_CONFIG)
    assert canonical_json(again) == data
    assert ap.write_overlay(store.path, again) == (oid, path)
    assert path.read_bytes() == data
    other = make_store(tmp_path / "other")  # the same documents in another store
    assert canonical_json(ap.derive(other, GOV_CONFIG)[0]) == data


def test_a_differing_overlay_file_is_refused(store):
    overlay, _ = ap.derive(store, GOV_CONFIG)
    _, path = ap.write_overlay(store.path, overlay)
    changed = overlay.model_copy(update={"config_sha256": "0" * 64})
    with pytest.raises(StoreError, match="different"):
        ap.write_overlay(store.path, changed)
    assert path.read_bytes() == canonical_json(overlay)


def test_load_overlay_reads_what_was_written(store):
    overlay, _ = ap.derive(store, GOV_CONFIG)
    oid, _ = ap.write_overlay(store.path, overlay)
    loaded = ap.load_overlay(store.path, store.snapshot_id)
    assert loaded.overlay_id == oid and loaded.snapshot == store.snapshot_id
    assert loaded.records == overlay.records
    assert ap.load_overlay(store.path, store.snapshot_id, oid).overlay_id == oid


def test_load_overlay_without_a_file_is_none(store):
    assert ap.load_overlay(store.path, store.snapshot_id) is None


def test_load_overlay_refuses_a_wrong_hash(store):
    ap.write_overlay(store.path, ap.derive(store, GOV_CONFIG)[0])
    with pytest.raises(StoreError, match="hash"):
        ap.load_overlay(store.path, store.snapshot_id, "f" * 64)


def test_load_overlay_refuses_a_file_of_another_snapshot(store):
    _, path = ap.write_overlay(store.path, ap.derive(store, GOV_CONFIG)[0])
    s = Store.open(store.path)
    s.add(*_doc(b"# Extra\n\nAnother file.\n", "md", "1", "file://extra.md"))
    new = s.commit()
    target = store.path / "applicability" / new / "envelope-1.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(path.read_bytes())
    with pytest.raises(StoreError, match="snapshot"):
        ap.load_overlay(store.path, new)


def test_load_overlay_refuses_a_bad_schema_or_non_canonical_bytes(store):
    overlay, _ = ap.derive(store, GOV_CONFIG)
    _, path = ap.write_overlay(store.path, overlay)
    body = json.loads(path.read_bytes())
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    with pytest.raises(StoreError, match="canonical"):
        ap.load_overlay(store.path, store.snapshot_id)
    first = next(iter(body["records"]))
    body["records"][first]["status"] = "repealed"
    path.write_bytes(json.dumps(body, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    with pytest.raises(StoreError, match="schema"):
        ap.load_overlay(store.path, store.snapshot_id)


def test_load_overlay_refuses_records_that_do_not_match_the_snapshot(store):
    overlay, _ = ap.derive(store, GOV_CONFIG)
    first = next(iter(overlay.records))
    fewer = overlay.model_copy(update={"records": {k: v for k, v in overlay.records.items()
                                                   if k != first}})
    ap.write_overlay(store.path, fewer)
    with pytest.raises(StoreError, match="documents"):
        ap.load_overlay(store.path, store.snapshot_id)


def test_a_record_keyed_by_another_doc_id_is_invalid():
    with pytest.raises(ValueError):
        ap.ApplicabilityOverlay(format_version="0.1", snapshot="0" * 64, deriver="envelope-1",
                                config_sha256="0" * 64, records={"a" * 64: env(doc_id="b" * 64)})


def test_the_overlay_schema_is_one_of_the_record_schemas():
    schema = records.schemas()["applicability.schema.json"]
    assert schema["title"] == "ApplicabilityOverlay"
    assert set(schema["properties"]) == {"format_version", "snapshot", "deriver",
                                         "config_sha256", "records"}


# -- filters -----------------------------------------------------------------------------

D = date(2025, 6, 30)
NEWER = "e" * 64


def test_default_excludes_superseded_documents_only():
    assert admits(env(), Filters())
    assert not admits(env(superseded_by=NEWER), Filters())
    assert admits(env(superseded_by=NEWER), Filters(include_superseded=True))
    expired = env(status="temporary_rule", valid_from=date(2020, 1, 1),
                  valid_to=date(2020, 2, 1))
    assert admits(expired, Filters())  # expiry is not a default


def test_as_of_interval_boundaries():
    e = env(valid_from=D, valid_to=D + timedelta(days=10), status="codified")
    assert not admits(e, Filters(as_of=D - timedelta(days=1)))
    assert admits(e, Filters(as_of=D))  # D = valid_from is in
    assert admits(e, Filters(as_of=D + timedelta(days=9)))
    assert not admits(e, Filters(as_of=D + timedelta(days=10)))  # D = valid_to is out
    open_ended = env(valid_from=D, status="codified")
    assert admits(open_ended, Filters(as_of=date(2999, 1, 1)))
    assert not admits(env(valid_to=D, status="codified"), Filters(as_of=D - timedelta(days=1)))


def test_as_of_replaces_the_superseded_default():
    old = env(valid_from=D, valid_to=D + timedelta(days=5), superseded_by=NEWER,
              status="codified")
    assert admits(old, Filters(as_of=D))
    assert not admits(old, Filters())


def test_as_of_excludes_proposals_unless_status_names_them():
    p = env(valid_from=D, status="proposed_rule", authority_tier=4)
    assert not admits(p, Filters(as_of=D))
    assert admits(p, Filters(as_of=D, status=("proposed_rule",)))
    assert not admits(p, Filters(as_of=D, status=("final_rule",)))
    assert admits(p, Filters())  # no as_of: a proposal is a document like another


@pytest.mark.parametrize("f", [
    Filters(status=("final_rule", "codified", "guidance", "notice", "temporary_rule",
                    "proposed_rule")),
    Filters(jurisdiction=("US-federal",)),
    Filters(max_tier=4),
    Filters(as_of=D),
])
def test_unknown_never_matches(f):
    assert not admits(env(), f)


def test_status_jurisdiction_and_tier_filters():
    e = env(status="final_rule", jurisdiction="US-federal", authority_tier=2)
    assert admits(e, Filters(status=("final_rule",), jurisdiction=("US-federal",), max_tier=2))
    assert not admits(e, Filters(status=("notice",)))
    assert not admits(e, Filters(jurisdiction=("US-CA",)))
    assert not admits(e, Filters(max_tier=1))


def test_filters_parse_validate_and_serialise():
    f = Filters.parse({"as_of": "2025-06-30", "status": ["notice", "final_rule", "notice"],
                       "max_tier": 3})
    assert f == Filters(as_of=D, status=("final_rule", "notice"), max_tier=3)
    assert f.to_dict() == {"include_superseded": False, "as_of": "2025-06-30",
                           "status": ["final_rule", "notice"], "jurisdiction": None,
                           "max_tier": 3}
    assert Filters.parse(None) == Filters() and Filters.parse(f) is f
    assert f.needs_overlay() and Filters(jurisdiction=("US-federal",)).needs_overlay()
    assert not Filters(include_superseded=True).needs_overlay()
    assert Filters.parse(f.to_dict()) == f


@pytest.mark.parametrize("bad", [
    {"as_of": "30 June 2025"}, {"as_of": 20250630}, {"status": ["repealed"]},
    {"status": ["unknown"]}, {"status": []}, {"status": "final_rule"}, {"max_tier": 0},
    {"max_tier": 5}, {"max_tier": True}, {"max_tier": "2"}, {"jurisdiction": [""]},
    {"include_superseded": "yes"}, {"colour": "red"}, ["as_of"],
])
def test_filters_parse_refuses_bad_values(bad):
    with pytest.raises(ValueError):
        Filters.parse(bad)


def test_filters_refuse_a_datetime_as_of():
    from datetime import datetime
    with pytest.raises(ValueError):
        Filters(as_of=datetime(2025, 6, 30))


def test_allowed_docs_counts_what_the_filters_exclude(store):
    overlay, _ = ap.derive(store, GOV_CONFIG)
    ap.write_overlay(store.path, overlay)
    a = ap.load_overlay(store.path, store.snapshot_id)
    every = store.doc_ids()
    allowed, excluded = a.allowed_docs(every, Filters())
    assert allowed == frozenset(every) - {doc_id(V2024), doc_id(V2025)} and excluded == 2
    allowed, excluded = a.allowed_docs(every, Filters(as_of=date(2025, 7, 1)))
    assert doc_id(V2025) in allowed and doc_id(V2026) not in allowed
    assert doc_id(IRM) not in allowed and doc_id(LOOSE) not in allowed
    assert doc_id(PROPOSED) not in allowed and doc_id(TEMP) not in allowed
    assert doc_id(FINAL) in allowed and doc_id(TEMP_UNPARSED) in allowed
    assert excluded == len(every) - len(allowed)
    allowed, excluded = a.allowed_docs([doc_id(V2024)], Filters(include_superseded=True))
    assert (allowed, excluded) == (frozenset({doc_id(V2024)}), 0)
    with pytest.raises(KeyError):
        a.allowed_docs(["0" * 64], Filters())


# -- adr applicability derive ------------------------------------------------------------

def test_cli_derive_writes_then_is_a_no_op(store, tmp_path, capsys):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(GOV_CONFIG), encoding="utf-8")
    argv = ["applicability", "derive", "--store", str(store.path), "--gov-config", str(config)]
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    path = store.path / "applicability" / store.snapshot_id / "envelope-1.json"
    oid = hashlib.sha256(path.read_bytes()).hexdigest()
    assert oid[:12] in out and "temporary end dates parsed 1 of 3" in out
    report = path.with_name("envelope-1.report.json")
    assert json.loads(report.read_text(encoding="utf-8"))["families"]["ecfr"] == 3
    assert cli.main(argv) == 0
    assert hashlib.sha256(path.read_bytes()).hexdigest() == oid
    config.write_text(json.dumps({**GOV_CONFIG, "version": "x"}), encoding="utf-8")
    assert cli.main(argv) == 2
    assert "different" in capsys.readouterr().err
    assert hashlib.sha256(path.read_bytes()).hexdigest() == oid


def test_cli_derive_json(store, tmp_path, capsys):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(GOV_CONFIG), encoding="utf-8")
    assert cli.main(["applicability", "derive", "--store", str(store.path), "--gov-config",
                     str(config), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"overlay_id", "path", "snapshot", "report"}
    assert out["snapshot"] == store.snapshot_id


def test_cli_derive_without_a_store_is_a_clear_refusal(tmp_path, capsys):
    assert cli.main(["applicability", "derive", "--store", str(tmp_path / "none")]) == 2
    assert "no store here" in capsys.readouterr().err
