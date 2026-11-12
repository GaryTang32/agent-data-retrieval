"""US government corpus: point-in-time eCFR parts, IRM chapters and Federal Register metadata.

Files live under `<root>/data/gov/`:
  ecfr/title-{T}/part-{P}/{YYYY-MM-DD}.xml   eCFR versioner XML for that date
  irm/part{N}/{slug}.html                    Internal Revenue Manual chapter page
  fr/{document_number}.json                  Federal Register API document (pinned fields)
The URI, format and source_version of each file follow from its path, so `build_manifest`
describes whatever is under `root` and `fetch_manifest` can re-download every file.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from lxml import etree

from adr_eval.corpora import REPO_ROOT
from adr_eval.corpora.base import Document, LoadedCorpus, sha256_bytes
from adr_eval.corpora.extract import extract_text
from adr_eval.corpora.http import PoliteFetcher
from adr_eval.models import Manifest, ManifestDoc

ECFR_FULL = "https://www.ecfr.gov/api/versioner/v1/full/{date}/title-{title}.xml?part={part}"
FR_API = "https://www.federalregister.gov/api/v1"
IRM_BASE = "https://www.irs.gov/irm"

_ECFR_PATH = re.compile(r"^ecfr/title-(\d+)/part-([\w.-]+)/(\d{4}-\d{2}-\d{2})\.xml$")
_ECFR_URI = re.compile(r"/full/(\d{4}-\d{2}-\d{2})/title-(\d+)\.xml\?part=([\w.-]+)$")
_IRM_PATH = re.compile(r"^irm/(part\d+)/(irm_[\w-]+)\.html$")
_FR_PATH = re.compile(r"^fr/([\w-]+)\.json$")
_TRANSMITTAL = re.compile(r"Manual Transmittal</h4>\s*<p>\s*([A-Z][a-z]+ \d{1,2}, \d{4})\s*</p>")
_LAST_REVIEWED = re.compile(r"Page Last Reviewed or Updated:\s*(\d{1,2}-[A-Z][a-z]{2}-\d{4})")

Fetcher = Callable[[str], bytes]


def ecfr_url(title: int | str, part: str, date: str) -> str:
    return ECFR_FULL.format(date=date, title=title, part=part)


def fr_list_url(agency: str, title: int | str, part: str, gte: str, lte: str, order: str,
                per_page: int) -> str:
    query = [
        ("conditions[agencies][]", agency),
        ("conditions[cfr][title]", str(title)),
        ("conditions[cfr][part]", str(part)),
        ("conditions[publication_date][gte]", gte),
        ("conditions[publication_date][lte]", lte),
        ("fields[]", "document_number"),
        ("order", order),
        ("per_page", str(per_page)),
    ]
    return f"{FR_API}/documents.json?{urlencode(query)}"


def fr_document_url(document_number: str, fields: list[str]) -> str:
    query = urlencode([("fields[]", f) for f in fields])
    return f"{FR_API}/documents/{document_number}.json?{query}"


def irm_version(html: bytes) -> str:
    """ISO date of the chapter's Manual Transmittal (fallback: page last reviewed date)."""
    text = html.decode("utf-8", errors="replace")
    if m := _TRANSMITTAL.search(text):
        return datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
    if m := _LAST_REVIEWED.search(text):
        return datetime.strptime(m.group(1), "%d-%b-%Y").date().isoformat()
    raise ValueError("IRM page has neither a Manual Transmittal nor a last-reviewed date")


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def _ecfr_sections(xml: bytes) -> list[tuple[str, str]]:
    """(section number, extracted text) for each <DIV8> in document order."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    root = etree.fromstring(xml, parser)
    out = []
    for div in root.iter("DIV8"):
        text = extract_text(etree.tostring(div, with_tail=False), "xml")
        if text:
            out.append((div.get("N") or "", text))
    return out


class GovAdapter:
    name = "gov"

    def __init__(self, config_path: Path | None = None):
        self.config_path = Path(config_path or REPO_ROOT / "corpora" / "gov" / "config.json")
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))

    # -- acquisition ---------------------------------------------------------------

    def fetcher(self, root: Path) -> Fetcher:
        return PoliteFetcher()

    def download(self, root: Path, fetcher: Fetcher | None = None) -> None:
        """Fetch every configured file into `root/data/gov`, skipping files already present."""
        fetcher = fetcher or self.fetcher(root)
        base = Path(root) / "data" / "gov"
        for p in self.config["parts"]:
            for date in p["dates"]:
                target = base / "ecfr" / f"title-{p['title']}" / f"part-{p['part']}" / f"{date}.xml"
                if not target.is_file():
                    _write(target, fetcher(ecfr_url(p["title"], p["part"], date)))
        for url in self.config["irm_urls"]:
            part, slug = url.rstrip("/").split("/")[-2:]
            target = base / "irm" / part / f"{slug}.html"
            if not target.is_file():
                _write(target, fetcher(url))
        fr = self.config["federal_register"]
        numbers: list[str] = []
        for p in self.config["parts"]:
            for gte, lte in fr["windows"]:
                url = fr_list_url(p["agency"], p["title"], p["part"], gte, lte, fr["order"],
                                  fr["per_page"])
                for r in json.loads(fetcher(url))["results"]:
                    if r["document_number"] not in numbers:
                        numbers.append(r["document_number"])
        for n in numbers:
            target = base / "fr" / f"{n}.json"
            if not target.is_file():
                _write(target, fetcher(fr_document_url(n, fr["fields"])))

    # -- manifest ------------------------------------------------------------------------

    def _describe(self, rel: str, data: bytes) -> tuple[str, str, str] | None:
        """(uri, format, source_version) for a path relative to data/gov, or None."""
        if m := _ECFR_PATH.match(rel):
            title, part, date = m.groups()
            return ecfr_url(title, part, date), "xml", date
        if m := _IRM_PATH.match(rel):
            part, slug = m.groups()
            return f"{IRM_BASE}/{part}/{slug}", "html", irm_version(data)
        if m := _FR_PATH.match(rel):
            n = m.group(1)
            return fr_document_url(n, self.config["federal_register"]["fields"]), "json", n
        return None

    def build_manifest(self, root: Path) -> Manifest:
        base = Path(root) / "data" / "gov"
        docs = []
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            data = p.read_bytes()
            described = self._describe(p.relative_to(base).as_posix(), data)
            if described is None:
                continue
            uri, fmt, version = described
            docs.append(
                ManifestDoc(
                    doc_id=sha256_bytes(data),
                    uri=uri,
                    format=fmt,
                    source_version=version,
                    bytes=len(data),
                    license=self.config["license"],
                    path=p.relative_to(root).as_posix(),
                )
            )
        return Manifest(
            corpus=self.name,
            version=self.config["version"],
            license_summary=self.config["license_summary"],
            documents=docs,
        )

    # -- structured views ------------------------------------------------------------------

    def records(self, corpus: LoadedCorpus) -> list[dict]:
        rows = []
        for d in corpus.manifest.documents:
            if not d.uri.startswith(f"{FR_API}/documents/"):
                continue
            fr = json.loads(corpus.docs[d.doc_id].text)
            agencies = fr.get("agencies") or []
            parents = {a.get("parent_id") for a in agencies}
            specific = [a for a in agencies if a.get("id") not in parents] or agencies
            cfr_parts: list[str] = []
            for ref in fr.get("cfr_references") or []:
                label = f"{ref['title']} CFR {ref['part']}"
                if label not in cfr_parts:
                    cfr_parts.append(label)
            rows.append(
                {
                    "id": fr["document_number"],
                    "type": fr.get("type"),
                    "agency": specific[0].get("name") if specific else None,
                    "publication_date": fr.get("publication_date"),
                    "year": int(fr["publication_date"][:4]),
                    "title": fr.get("title"),
                    "cfr_parts": cfr_parts,
                    "_doc_id": d.doc_id,
                }
            )
        return sorted(rows, key=lambda r: r["id"])

    def record_schema(self) -> dict[str, str]:
        return {
            "id": "str: Federal Register document number, e.g. '2023-01707'",
            "type": "str: 'Rule', 'Proposed Rule', 'Notice' or 'Presidential Document'",
            "agency": "str: most specific issuing agency, e.g. 'Coast Guard'",
            "publication_date": "str: ISO date the document was published in the Federal Register",
            "year": "int: publication year",
            "title": "str: document title",
            "cfr_parts": "list[str]: CFR parts the document affects, e.g. ['33 CFR 117']",
        }

    def version_pairs(self, corpus: LoadedCorpus) -> list[tuple[Document, Document]]:
        """Consecutive dated versions of each eCFR section (<DIV8>) whose text differs.

        Each returned Document carries the full document's doc_id and source_version (the
        eCFR date); its `text` is the section's extracted text, an exact substring of the
        full document's text; its `uri` is the document URI plus `#<section number>`.
        """
        if corpus.root is None:
            raise ValueError("version_pairs needs corpus.root to read the eCFR XML")
        by_part: dict[tuple[str, str], list] = {}
        for d in corpus.manifest.documents:
            if m := _ECFR_URI.search(d.uri):
                by_part.setdefault((m.group(2), m.group(3)), []).append(d)
        pairs: list[tuple[Document, Document]] = []
        for key in sorted(by_part):
            versions = sorted(by_part[key], key=lambda d: d.source_version)
            sections = [self._sections(corpus, d) for d in versions]
            for old, new in zip(sections, sections[1:], strict=False):
                for number, a in old.items():
                    b = new.get(number)
                    if b is not None and a.text != b.text:
                        pairs.append((a, b))
        return pairs

    def _sections(self, corpus: LoadedCorpus, d: ManifestDoc) -> dict[str, Document]:
        data = (Path(corpus.root) / d.path).read_bytes()
        if sha256_bytes(data) != d.doc_id:
            raise ValueError(f"{d.path}: bytes changed since the corpus was loaded")
        full = corpus.docs[d.doc_id].text
        out: dict[str, Document] = {}
        cursor = 0
        for number, text in _ecfr_sections(data):
            at = full.find(text, cursor)
            if at < 0:
                raise ValueError(f"{d.path}: section {number} not found in extracted text")
            cursor = at + len(text)
            if number and number not in out:
                out[number] = Document(d.doc_id, text, d.format, d.source_version,
                                       f"{d.uri}#{number}")
        return out
