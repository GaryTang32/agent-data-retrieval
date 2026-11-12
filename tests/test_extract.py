from pathlib import Path

import pytest

from adr_eval.corpora.extract import EXTRACTOR_VERSION, extract_text

MINI = Path(__file__).parent / "fixtures" / "mini"


def test_version_is_string():
    assert EXTRACTOR_VERSION == "2"


@pytest.mark.parametrize(
    "path",
    sorted(p for p in MINI.iterdir() if p.name not in {"manifest.json", "golden.jsonl"}),
)
def test_extract_is_deterministic_for_each_format(path):
    data = path.read_bytes()
    fmt = path.suffix[1:]
    first = extract_text(data, fmt)
    assert first.strip()
    assert extract_text(data, fmt) == first


def test_json_extraction_sorted_keys():
    out = extract_text(b'{"b":1,"a":2}', "json")
    assert out.index('"a"') < out.index('"b"')


def test_json_keeps_non_ascii():
    assert "é" in extract_text('{"a":"é"}'.encode(), "json")


def test_md_strict_decode():
    with pytest.raises(UnicodeDecodeError):
        extract_text(b"\xff\xfe\x00bad", "md")


def test_xml_blocks_separated_by_newline():
    text = extract_text((MINI / "regulation_s12_2023-01-01.xml").read_bytes(), "xml")
    assert text.splitlines()[0] == "Filing deadlines"
    assert "within 60 days" in text
    assert "<" not in text


def test_html_drops_navigation_chrome():
    text = extract_text((MINI / "procedure.html").read_bytes(), "html")
    assert "proof of residence" in text
    assert "Home | Services" not in text


def test_pdf_pages_joined_by_formfeed():
    text = extract_text((MINI / "service_charter.pdf").read_bytes(), "pdf")
    assert "\n\f\n" in text
    assert "Complaints" in text.split("\f")[1]


def test_unsupported_format():
    with pytest.raises(ValueError):
        extract_text(b"x", "docx")


def test_xml_compact_mixed_content_blocks_separated():
    xml = b"<s><p>Intro<item>1</item>tail</p><p>Two</p></s>"
    assert extract_text(xml, "xml").split("\n") == ["Intro", "1", "tail", "Two"]


def test_xml_inline_markup_does_not_split_words():
    # Real eCFR shapes: emphasis ending mid-word, superscripts, subscripts and fractions.
    xml = (
        b"<DIV8><HEAD>\xc2\xa7 117.1 Purpose.</HEAD>"
        b"<P>(d) <I>Enforcement period</I>s. This section applies.</P>"
        b"<P>Station BC<sup>1</sup> at <E T=\"03\">peak</E>; "
        b"T<sub>mp</sub> is <FR>1/2</FR> mile.</P>"
        b"<P>Note<SU>2</SU> <FTREF>3</FTREF><br/>next line</P></DIV8>"
    )
    assert extract_text(xml, "xml").split("\n") == [
        "\u00a7 117.1 Purpose.",
        "(d) Enforcement periods. This section applies.",
        "Station BC1 at peak; Tmp is 1/2 mile.",
        "Note2 3",
        "next line",
    ]
