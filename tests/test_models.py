import json

import pytest
from pydantic import ValidationError

from adr_eval.models import Answer, Manifest, ManifestDoc, load_items, write_items
from tests.conftest import DOC_A, EV


def test_snapshot_is_order_independent_of_key_order_and_stable():
    m1 = Manifest(corpus="mini", version="1", license_summary="pd", documents=[DOC_A])
    d = m1.model_dump(mode="json")
    docs = [dict(reversed(list(doc.items()))) for doc in d["documents"]]
    rev = dict(reversed(list(d.items())))
    rev["documents"] = docs
    assert list(rev) != list(d)
    m2 = Manifest.model_validate(json.loads(json.dumps(rev)))
    assert m1.snapshot() == m2.snapshot()
    assert len(m1.snapshot()) == 64


def test_snapshot_changes_with_content():
    a = Manifest(corpus="mini", version="1", license_summary="pd", documents=[DOC_A])
    b = Manifest(
        corpus="mini",
        version="1",
        license_summary="pd",
        documents=[ManifestDoc(**{**DOC_A.model_dump(), "bytes": 11})],
    )
    assert a.snapshot() != b.snapshot()


def test_policy_asof_requires_as_of(make_item):
    with pytest.raises(ValidationError):
        make_item(qtype="policy_asof", as_of=None)


def test_abstain_answer_forbids_evidence(make_item):
    with pytest.raises(ValidationError):
        make_item(answer=Answer(kind="abstain", value=None), evidence=[EV])


def test_write_then_load_roundtrip_sorted(make_item, tmp_path):
    write_items(tmp_path / "i.jsonl", [make_item(id="b"), make_item(id="a")])
    assert [i.id for i in load_items(tmp_path / "i.jsonl")] == ["a", "b"]


# JSON leaves these characters unescaped inside strings, and str.splitlines() breaks on them.
UNICODE_LINE_BREAKS = "\u2028\u2029\x85"


def test_jsonl_lines_splits_only_on_newline():
    from adr_eval.models import jsonl_lines

    rows = [{"text": f"a{ch}b"} for ch in UNICODE_LINE_BREAKS] + [{"text": "plain"}]
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows) + "\n  \n"
    assert [json.loads(line) for line in jsonl_lines(text)] == rows
