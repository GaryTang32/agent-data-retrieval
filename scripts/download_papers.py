#!/usr/bin/env python3
"""Download the open-access PDFs listed in research source manifests.

Reads every ``*.sources.jsonl`` file in a research-notes folder, de-duplicates
papers (by arXiv ID, DOI, then PDF URL), downloads each available PDF into
``papers/<topic>/`` and writes a catalog:

* ``papers/manifest.csv``  - one row per unique source with download status
* ``papers/README.md``     - human-readable index grouped by topic

PDFs are git-ignored (see .gitignore): they are kept locally only, because many
publisher and arXiv licenses do not permit public redistribution. The manifest
and catalog are small and safe to commit, and re-running this script rebuilds
the local paper library on any machine.

Usage:
    python3 scripts/download_papers.py "research_notes/Deterministic retrieval data conversion"
    python3 scripts/download_papers.py <notes_dir> --out papers --dry-run

The script is resumable: files already present (and valid PDFs) are skipped.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

USER_AGENT = "agent-data-retrieval-research/1.0 (paper catalog; polite crawler)"
MAX_BYTES = 95 * 1024 * 1024  # skip anything larger than 95 MB
ARXIV_DELAY_S = 3.0  # arXiv asks automated clients for <= 1 request / 3 s
OTHER_DELAY_S = 1.0
ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")


def slugify(text: str, max_len: int = 70) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return text[:max_len].rstrip("_") or "untitled"


def first_author_surname(authors) -> str:
    if isinstance(authors, list):
        authors = authors[0] if authors else ""
    authors = str(authors or "")
    first = re.split(r",| and |;", authors)[0].strip()
    if not first:
        return "anon"
    parts = first.replace("et al.", "").split()
    return slugify(parts[-1] if parts else first, 20)


def normalize_arxiv_id(entry: dict) -> str | None:
    for key in ("arxiv_id", "pdf_url", "url"):
        val = entry.get(key)
        if not val:
            continue
        val = str(val)
        if key != "arxiv_id" and "arxiv.org" not in val:
            continue
        m = ARXIV_ID_RE.search(val)
        if m:
            return m.group(1)
    return None


def resolve_pdf_url(entry: dict, arxiv_id: str | None) -> str | None:
    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}"
    url = entry.get("pdf_url")
    if not url or not str(url).startswith(("http://", "https://")):
        return None
    url = str(url)
    # Normalize common abstract-page links to direct PDF links.
    url = re.sub(r"openreview\.net/forum\?id=", "openreview.net/pdf?id=", url)
    if re.match(r"https?://aclanthology\.org/[^/]+/?$", url) and not url.endswith(".pdf"):
        url = url.rstrip("/") + ".pdf"
    return url


def dedupe_key(entry: dict, arxiv_id: str | None, pdf_url: str | None) -> str:
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    doi = (entry.get("doi") or "").strip().lower()
    if doi and not doi.startswith("10.48550/arxiv"):
        return f"doi:{doi}"
    if pdf_url:
        return f"pdf:{pdf_url.lower()}"
    return f"url:{str(entry.get('url') or entry.get('title') or '').strip().lower()}"


def load_entries(notes_dir: Path) -> list[dict]:
    entries: list[dict] = []
    for path in sorted(notes_dir.glob("*.sources.jsonl")):
        topic_default = path.name.replace(".sources.jsonl", "")
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"warn: {path.name}:{lineno}: bad JSON ({exc})", file=sys.stderr)
                continue
            obj.setdefault("topic", topic_default)
            obj["_manifest"] = path.name
            entries.append(obj)
    return entries


def fetch(url: str) -> tuple[bytes | None, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            length = resp.headers.get("Content-Length")
            if length and int(length) > MAX_BYTES:
                return None, f"too_large({int(length) // (1024 * 1024)}MB)"
            data = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return None, f"http_{exc.code}"
    except Exception as exc:  # network errors, timeouts, TLS
        return None, f"error:{type(exc).__name__}"
    if len(data) > MAX_BYTES:
        return None, "too_large"
    if not data.lstrip()[:5].startswith(b"%PDF"):
        return None, "not_pdf"
    return data, "downloaded"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("notes_dir", type=Path)
    ap.add_argument("--out", type=Path, default=Path("papers"))
    ap.add_argument("--dry-run", action="store_true", help="build the catalog without downloading")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--workers", type=int, default=8, help="concurrent downloads (start rate per host is still limited)")
    args = ap.parse_args()

    entries = load_entries(args.notes_dir)
    if not entries:
        print(f"no *.sources.jsonl files found in {args.notes_dir}", file=sys.stderr)
        return 1

    unique: dict[str, dict] = {}
    for e in entries:
        arxiv_id = normalize_arxiv_id(e)
        pdf_url = resolve_pdf_url(e, arxiv_id)
        key = dedupe_key(e, arxiv_id, pdf_url)
        if key in unique:
            unique[key]["also_in"].add(e["topic"])
            continue
        unique[key] = {**e, "arxiv_id": arxiv_id, "resolved_pdf_url": pdf_url, "key": key, "also_in": set()}

    args.out.mkdir(parents=True, exist_ok=True)
    todo = [u for u in unique.values() if u["resolved_pdf_url"]]
    print(f"{len(entries)} manifest lines -> {len(unique)} unique sources, {len(todo)} with a PDF link")

    # Plan destinations, then download concurrently. Request *starts* are
    # rate-limited per host (arXiv: one every 3 s), but transfers may overlap,
    # which matters when per-connection bandwidth is the bottleneck.
    limiter_lock = threading.Lock()
    next_start: dict[str, float] = {}
    print_lock = threading.Lock()
    done_count = [0]

    def wait_turn(host: str) -> None:
        delay = ARXIV_DELAY_S if "arxiv.org" in host else OTHER_DELAY_S
        with limiter_lock:
            now = time.time()
            start = max(now, next_start.get(host, 0.0))
            next_start[host] = start + delay
        if start > now:
            time.sleep(start - now)

    def process(u: dict) -> None:
        u["status"], u["local"] = "no_pdf_link", ""
        url = u["resolved_pdf_url"]
        if not url:
            return
        topic_dir = args.out / slugify(str(u["topic"]), 60)
        fname = f"{u.get('year') or 'nd'}_{first_author_surname(u.get('authors'))}_{slugify(str(u.get('title') or ''), 60)}"
        if u["arxiv_id"]:
            fname += f"_{u['arxiv_id']}"
        dest = topic_dir / f"{fname}.pdf"
        u["local"] = str(dest)
        if dest.exists() and dest.stat().st_size > 1000:
            u["status"] = "downloaded"
        elif args.dry_run:
            u["status"] = "pending"
        else:
            host = urlparse(url).netloc
            data, status = None, "error"
            for attempt in range(args.retries):
                wait_turn(host)
                data, status = fetch(url)
                if data is not None or not status.startswith(("error", "http_429", "http_5")):
                    break
                time.sleep(5 * (2 ** attempt))
            u["status"] = status
            if data is not None:
                topic_dir.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(".part")
                tmp.write_bytes(data)
                tmp.replace(dest)
            else:
                u["local"] = ""
        with print_lock:
            done_count[0] += 1
            print(f"[{done_count[0]}/{len(todo)}] {u['status']:<14} {str(u.get('title') or '')[:80]}", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(process, unique.values()))

    rows = []
    for u in unique.values():
        status, local, url = u["status"], u["local"], u["resolved_pdf_url"]
        rows.append({
            "topic": u["topic"],
            "also_in": ";".join(sorted(u["also_in"] - {u["topic"]})),
            "type": u.get("type") or "",
            "title": u.get("title") or "",
            "authors": ", ".join(u["authors"]) if isinstance(u.get("authors"), list) else (u.get("authors") or ""),
            "year": u.get("year") or "",
            "venue": u.get("venue") or "",
            "url": u.get("url") or "",
            "pdf_url": url or "",
            "arxiv_id": u["arxiv_id"] or "",
            "doi": u.get("doi") or "",
            "license": u.get("license") or "",
            "status": status,
            "local_file": local,
            "relevance": u.get("relevance") or "",
        })

    with (args.out / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    write_readme(args.out, rows, args.notes_dir)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("summary:", json.dumps(counts, sort_keys=True))
    return 0


def md_escape(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def write_readme(out: Path, rows: list[dict], notes_dir: Path) -> None:
    n_papers = sum(1 for r in rows if r["type"] == "paper")
    n_pdf = sum(1 for r in rows if r["status"] == "downloaded")
    lines = [
        "# Research source library",
        "",
        f"Catalog of every unique source cited in `{notes_dir}`: {len(rows)} sources "
        f"({n_papers} papers, {len(rows) - n_papers} web/docs), {n_pdf} PDFs downloaded locally.",
        "",
        "PDFs are **not committed** (they are git-ignored) because many licenses do not allow public",
        "redistribution. Rebuild the local library on any machine with:",
        "",
        "```bash",
        f'python3 scripts/download_papers.py "{notes_dir}"',
        "```",
        "",
        "Full metadata (authors, DOI, license, relevance, local path) is in `manifest.csv`.",
        "",
    ]
    by_topic: dict[str, list[dict]] = {}
    for r in rows:
        by_topic.setdefault(r["topic"], []).append(r)
    for topic in sorted(by_topic):
        items = sorted(by_topic[topic], key=lambda r: (str(r["year"]), r["title"]), reverse=True)
        lines += [f"## {topic} ({len(items)})", "", "| Year | Title | Venue | Type | PDF |", "|---|---|---|---|---|"]
        for r in items:
            link = r["url"] or r["pdf_url"]
            title = f"[{md_escape(r['title'])}]({link})" if link else md_escape(r["title"])
            pdf = "local" if r["status"] == "downloaded" else ("—" if r["status"] == "no_pdf_link" else r["status"])
            lines.append(f"| {r['year']} | {title} | {md_escape(r['venue'])} | {r['type']} | {pdf} |")
        lines.append("")
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
