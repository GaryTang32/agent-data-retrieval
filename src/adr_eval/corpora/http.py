"""Polite HTTP fetcher: fixed User-Agent, at most one request per second per host, retries,
and resumable downloads of large files."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from adr_eval.corpora.base import HashMismatch

USER_AGENT = "adr-eval/0.1 (+https://github.com/GaryTang32/agent-data-retrieval)"
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class PoliteFetcher:
    """Callable `url -> bytes` that waits `min_interval` seconds between requests to a host."""

    def __init__(
        self,
        min_interval: float = 1.0,
        retries: int = 3,
        backoff: float = 5.0,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.min_interval, self.retries, self.backoff = min_interval, retries, backoff
        self._clock, self._sleep = clock, sleep
        self._last: dict[str, float] = {}
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=httpx.Timeout(120.0),
            transport=transport,
        )

    def _throttle(self, url: str) -> None:
        host = httpx.URL(url).host
        last = self._last.get(host)
        if last is not None:
            wait = self.min_interval - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last[host] = self._clock()

    def __call__(self, url: str) -> bytes:
        for attempt in range(self.retries + 1):
            self._throttle(url)
            try:
                r = self._client.get(url)
            except httpx.TransportError:
                if attempt == self.retries:
                    raise
                self._sleep(self.backoff * 2**attempt)
                continue
            if r.status_code in RETRY_STATUS and attempt < self.retries:
                self._sleep(self.backoff * 2**attempt)
                continue
            r.raise_for_status()
            return r.content
        raise AssertionError("unreachable")

    def download(self, url: str, dest: Path, sha256: str | None = None) -> None:
        """Stream `url` to `dest`, resuming from `dest.part`; verify `sha256` before renaming.

        A present `dest` whose hash matches is left alone (no request). On a hash mismatch
        the partial file is deleted and `HashMismatch` is raised; `dest` is not written.
        """
        dest = Path(dest)
        if dest.is_file() and (sha256 is None or sha256_file(dest) == sha256):
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        start = part.stat().st_size if part.is_file() else 0
        headers = {"Accept-Encoding": "identity"}
        if start:
            headers["Range"] = f"bytes={start}-"
        self._throttle(url)
        with self._client.stream("GET", url, headers=headers) as r:
            r.raise_for_status()
            mode = "ab" if start and r.status_code == 206 else "wb"
            with open(part, mode) as fh:
                for chunk in r.iter_bytes(1 << 20):
                    fh.write(chunk)
        if sha256 is not None:
            got = sha256_file(part)
            if got != sha256:
                part.unlink()
                raise HashMismatch(str(dest), sha256, got)
        part.replace(dest)
