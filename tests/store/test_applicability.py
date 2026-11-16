"""Applicability overlay: envelope records, the deterministic deriver and filters (spec §4.2–§4.4,
§12 Applicability)."""

import hashlib
import io
import json
import subprocess
import sys
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
       effective: str | None, agencies=AGENCIES) -> tuple[Document, bytes]:
    body = {"document_number": number, "type": type_, "action": action, "dates": dates,
            "publication_date": published, "effective_on": effective, "agencies": agencies}
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
# times before the dates: the end date is read past "5 p.m. on" (day granularity)
TEMP_TIMES = fr("2024-00003", "Rule", "Temporary final rule.",
                "This rule is effective from 8 a.m. on March 1, 2024 through 5 p.m. on "
                "March 2, 2024.", "2024-02-25", None)
EXPIRED_LIST = fr("2024-00004", "Rule", "Notification of expired temporary rules issued.",
                  "This document lists temporary Coast Guard rules and notifications of "
                  "enforcement that became effective, primarily between July 2021 and "
                  "September 2021, and expired before they could be published in the Federal "
                  "Register.", "2024-04-01", None)
PROPOSED = fr("2024-00005", "Proposed Rule", "Notice of proposed rulemaking.",
              "Comments must be received by May 1, 2024.", "2024-03-15", None)
NOTICE = fr("2024-00006", "Rule", "Notification of enforcement of regulation.",
            "The regulations will be enforced on July 4, 2024.", "2024-06-20", "2024-07-04")
TEMP_NO_END = fr("2024-00007", "Rule", "Temporary final rule.",
                 "This rule is effective on March 5, 2024.", "2024-03-01", "2024-03-05")
# the first sentence has no "from": the "from ... through" of the second sentence (the actual
# notice period) is not the rule's end
TEMP_CROSS = fr("2024-00008", "Rule", "Temporary final rule.",
                "This rule is effective without actual notice on March 10, 2024. For the "
                "purposes of enforcement, actual notice will be used from March 6, 2024 "
                "through March 10, 2024.", "2024-03-08", "2024-03-10")
IRM = _doc(HTML, "html", "2026-02-03", IRM_URI)
LOOSE = _doc(GUIDE, "md", "sha256:0123456789ab", "file://guide.md")
ALL = [V2025, V2024, V2026, FINAL, TEMP, TEMP_TIMES, EXPIRED_LIST, PROPOSED, NOTICE,
       TEMP_NO_END, TEMP_CROSS, IRM, LOOSE]


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
    final, temp, times, expired, proposed, notice, no_end, cross = (
        recs[doc_id(d)] for d in (FINAL, TEMP, TEMP_TIMES, EXPIRED_LIST, PROPOSED, NOTICE,
                                  TEMP_NO_END, TEMP_CROSS))
    assert (final.status, final.authority_tier) == ("final_rule", 2)
    assert (final.valid_from, final.valid_to, final.validity_basis) == (
        date(2024, 3, 1), None, "fr_effective_on")
    assert (temp.status, temp.authority_tier) == ("temporary_rule", 2)
    assert (temp.valid_from, temp.valid_to) == (date(2024, 3, 1), date(2024, 7, 1))
    # "through 5 p.m. on March 2, 2024": in force for all of March 2 (end-exclusive March 3)
    assert (times.status, times.valid_to) == ("temporary_rule", date(2024, 3, 3))
    assert (times.valid_from, times.validity_basis) == (date(2024, 2, 25), "fr_publication_date")
    # open-ended: an expired-rules list, a rule without an end date, a cross-sentence match
    assert (expired.status, expired.valid_to) == ("temporary_rule", None)
    assert (no_end.status, no_end.valid_to) == ("temporary_rule", None)
    assert (cross.status, cross.valid_to) == ("temporary_rule", None)
    assert (proposed.status, proposed.authority_tier) == ("proposed_rule", 4)
    assert (notice.status, notice.authority_tier) == ("notice", 3)
    for e in (final, temp, times, expired, proposed, notice, no_end, cross):
        assert e.chain_id is None and e.supersedes is None and e.superseded_by is None
        assert (e.jurisdiction, e.issuer) == ("US-federal", "Coast Guard")
    assert final.version_label == "2024-00001"


@pytest.mark.parametrize("dates,last", [
    ("This rule is effective from January 9, 2023 through January 30, 2023.", date(2023, 1, 30)),
    # "until D" is inclusive like "through D"
    ("This rule is effective without actual notice from January 22, 2021 until February 5, "
     "2021. For the purposes of enforcement, actual notice will be used from January 14, 2021 "
     "until January 22, 2021.", date(2021, 2, 5)),
    # a time before the end date, and a.m./p.m. are not sentence ends
    ("This rule is effective from 7 p.m. on April 1, 2022, through 7 p.m. on May 31, 2023.",
     date(2023, 5, 31)),
    ("This rule is effective from 6 p.m. through 7 p.m. on December 31, 2019.",
     date(2019, 12, 31)),
    ("This rule is effective from 8 a.m. Central Standard Time (CST) on Thursday, January 9, "
     "2025, through 8 p.m. CST on Thursday, January 9, 2025.", date(2025, 1, 9)),
    ("This deviation is effective without actual notice from 7:01 a.m. January 27, 2021 "
     "through 7 a.m. July 8, 2021. For the purposes of enforcement, actual notice will be "
     "used from 7 a.m. January 8, 2021 through 7 a.m. January 27, 2021.", date(2021, 7, 8)),
    ("This rule is effective without actual notice from January 13, 2026, through 11:59 p.m. "
     "on January 31, 2026, unless cancelled earlier by the COTP. For the purposes of "
     "enforcement, actual notice will be used from December 23, 2025, until January 13, 2026.",
     date(2026, 1, 31)),
    ("This rule is effective from 8 p.m. on January 15, 2022 until 8 p.m. on January 22, "
     "2022 .", date(2022, 1, 22)),
    # day granularity: a rule ending 12:01 a.m. on D is admitted for all of D
    ("This temporary final rule is effective from March 21, 2023 through 12:01 a.m. on July 1, "
     "2023.", date(2023, 7, 1)),
    # not parsed: no end date, no "from", "to", a later sentence, an expired-rules list
    ("This rule is effective on January 24, 2026.", None),
    ("This temporary interim rule is effective February 3, 2026 through 5 p.m. on June 26, "
     "2026.", None),
    ("This rule is effective from 8:30 p.m. to 10 p.m. on December 31, 2019.", None),
    ("This deviation is effective from midnight on April 15, 2020 and ends at midnight on "
     "November 2, 2020.", None),
    ("This rule is effective without actual notice on March 10, 2024. For the purposes of "
     "enforcement, actual notice will be used from March 6, 2024 until March 10, 2024.", None),
    ("This document lists temporary Coast Guard rules and notifications of enforcement that "
     "became effective, primarily between July 2021 and September 2021, and expired before "
     "they could be published in the Federal Register.", None),
    ("", None),
])
def test_temporary_end_dates(dates, last):
    found = ap.temporary_end(dates)
    assert (None if found is None else found[0]) == last
    if found is not None:
        _, start, end = found
        matched = dates[start:end]
        assert matched.startswith("effective") and last.strftime("%Y") in matched
        assert dates.index(matched) == start


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


def test_a_notice_of_enforcement_of_a_temporary_rule_is_a_notice():
    action = "Notification of enforcement of temporary regulation."
    assert "temporary" in action.lower()
    assert ap.fr_status({"type": "Rule", "action": action}) == ("notice", "fr.action")
    assert ap.fr_status({"type": "Rule", "action": "Temporary final rule."}) == (
        "temporary_rule", "fr.action")


def test_a_federal_register_document_without_agencies_has_no_issuer(tmp_path):
    bare = fr("2024-00009", "Rule", "Final rule.", "This rule is effective May 1, 2024.",
              "2024-04-01", "2024-05-01", agencies=[])
    s = make_store(tmp_path / "s", [bare])
    e = ap.derive(s, GOV_CONFIG)[0].records[doc_id(bare)]
    assert (e.status, e.issuer, e.jurisdiction) == ("final_rule", None, "US-federal")
    assert "issuer" not in {p.field for p in e.provenance}


def test_versions_of_one_date_are_ordered_by_doc_id(tmp_path):
    a, b = ecfr("2024-06-27", "alpha"), ecfr("2024-06-27", "beta")
    s = make_store(tmp_path / "s", [b, a])
    overlay, report = ap.derive(s, GOV_CONFIG)
    first, second = sorted([doc_id(a), doc_id(b)])
    older, newer = overlay.records[first], overlay.records[second]
    assert (older.supersedes, older.superseded_by) == (None, second)
    assert (newer.supersedes, newer.superseded_by) == (first, None)
    assert older.valid_from == older.valid_to == newer.valid_from == date(2024, 6, 27)
    assert report["chains"]["by_chain"] == {"ecfr:33:99": 2}


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
    # only the config fields the deriver reads: title, part and agency of each part, in order
    read = {"parts": [{"agency": p["agency"], "part": p["part"], "title": p["title"]}
                      for p in GOV_CONFIG["parts"]]}
    assert overlay.config_sha256 == hashlib.sha256(json.dumps(
        read, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()


def test_config_fields_the_deriver_does_not_read_do_not_change_the_overlay(store):
    base = canonical_json(ap.derive(store, GOV_CONFIG)[0])
    unrelated = {**GOV_CONFIG, "version": "2099-01-01", "irm_urls": ["x"],
                 "parts": [{**p, "dates": ["1999-01-01"]} for p in GOV_CONFIG["parts"]]}
    assert canonical_json(ap.derive(store, unrelated)[0]) == base
    agency = {**GOV_CONFIG, "parts": [{**GOV_CONFIG["parts"][0], "agency": "coast-guard"},
                                      GOV_CONFIG["parts"][1]]}
    assert ap.derive(store, agency)[0].config_sha256 != ap.derive(store, GOV_CONFIG)[0] \
        .config_sha256


def test_an_overlay_without_ecfr_documents_reads_no_config(tmp_path):
    s = make_store(tmp_path / "s", [LOOSE, FINAL, IRM])
    overlay, report = ap.derive(s, GOV_CONFIG)
    assert overlay.config_sha256 is None and report["config_sha256"] is None
    assert canonical_json(ap.derive(s, {"version": "other"})[0]) == canonical_json(overlay)


def test_the_report_counts_and_lists_parse_failures(derived):
    _, report = derived
    assert report["families"] == {"ecfr": 3, "fr": 8, "irm": 1, "unknown": 1}
    assert report["status"] == {"codified": 3, "final_rule": 1, "guidance": 1, "notice": 1,
                                "proposed_rule": 1, "temporary_rule": 5, "unknown": 1}
    assert report["validity_basis"]["fr_effective_on"] == 5
    assert report["validity_basis"]["fr_publication_date"] == 3
    assert report["authority_tier"] == {"1": 3, "2": 6, "3": 2, "4": 1, "null": 1}
    assert report["chains"] == {"count": 2, "multi_version": 1, "documents": 4, "links": 2,
                                "by_chain": {"ecfr:33:99": 3, "irm:5.19.1": 1}}
    assert report["temporary_end_dates"] == {"parsed": 2, "of": 5}
    failed = report["fr_dates_parse_failures"]
    assert [f["doc_id"] for f in failed] == sorted(
        doc_id(d) for d in (EXPIRED_LIST, TEMP_NO_END, TEMP_CROSS))
    assert {f["document_number"] for f in failed} == {"2024-00004", "2024-00007", "2024-00008"}
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


def test_load_overlay_refuses_another_deriver(store):
    overlay, _ = ap.derive(store, GOV_CONFIG)
    ap.write_overlay(store.path, overlay.model_copy(update={"deriver": "envelope-2"}))
    with pytest.raises(StoreError, match="deriver 'envelope-2'"):
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
    assert doc_id(FINAL) in allowed and doc_id(TEMP_TIMES) not in allowed
    # without a parsed end date a temporary rule is open-ended: a later as_of admits it
    assert {doc_id(EXPIRED_LIST), doc_id(TEMP_NO_END), doc_id(TEMP_CROSS)} <= allowed
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
    assert oid[:12] in out and "temporary end dates parsed 2 of 5" in out
    report = path.with_name("envelope-1.report.json")
    assert json.loads(report.read_text(encoding="utf-8"))["families"]["ecfr"] == 3
    assert cli.main(argv) == 0
    assert hashlib.sha256(path.read_bytes()).hexdigest() == oid
    config.write_text(json.dumps({**GOV_CONFIG, "version": "x"}), encoding="utf-8")
    assert cli.main(argv) == 0  # a field the deriver does not read
    assert "unchanged" in capsys.readouterr().out
    parts = [{**GOV_CONFIG["parts"][0], "agency": "coast-guard"}, GOV_CONFIG["parts"][1]]
    config.write_text(json.dumps({**GOV_CONFIG, "parts": parts}), encoding="utf-8")
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


class _ClosedPipe(io.TextIOBase):
    """A stdout whose reader has gone (`adr ... | head`)."""

    def write(self, s):
        raise BrokenPipeError(32, "Broken pipe")

    def flush(self):
        raise BrokenPipeError(32, "Broken pipe")

    def close(self):  # nothing to flush to
        pass


def test_cli_derive_into_a_closed_pipe_exits_quietly(store, tmp_path, capsys, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(GOV_CONFIG), encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", _ClosedPipe())
    assert cli.main(["applicability", "derive", "--store", str(store.path), "--gov-config",
                     str(config)]) == 0
    assert capsys.readouterr().err == ""


def test_cli_derive_piped_into_a_reader_that_stops(store, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(GOV_CONFIG), encoding="utf-8")
    child = subprocess.Popen([sys.executable, "-m", "adr_store.cli", "applicability", "derive",
                              "--store", str(store.path), "--gov-config", str(config)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
    child.stdout.close()  # the reader stops before the first line
    err = child.stderr.read()
    child.stderr.close()
    assert child.wait(timeout=60) == 0
    assert err == b""
    assert (store.path / "applicability" / store.snapshot_id / "envelope-1.json").is_file()
