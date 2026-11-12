"""Model adapters: cached, retrying completions behind a small protocol."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import time
from collections import Counter
from collections.abc import Callable, Collection
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

import anthropic
import httpx

from adr_eval.cache import Cache

BACKOFF_SECONDS = (1, 2, 4, 8, 16)
USAGE_LIMIT_BACKOFF_SECONDS = (60, 120, 240, 480, 900)


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    latency_s: float
    cached: bool
    provider: str = ""  # the producing client's `name`; keys "<provider>:<model>" prices
    notional_cost_usd: float | None = None  # what the CLI reports; never budgeted
    served_model: str | None = None  # the model the provider says answered, when it says


class ModelError(Exception):
    pass


class ModelOutputError(ModelError):
    pass


class ModelClient(Protocol):
    name: str
    family: str

    def complete(
        self, system: str, user: str, *, max_tokens: int, repeat: int = 0
    ) -> Completion: ...


class _Retryable(Exception):
    """Raised by a single attempt to signal that it may be retried."""

    backoff: tuple[int, ...] = BACKOFF_SECONDS


class RateLimitedError(_Retryable):
    """A subscription usage limit: retried on the long schedule, waiting for the reset."""

    backoff = USAGE_LIMIT_BACKOFF_SECONDS


def _with_retries(attempt: Callable[[], Completion], max_retries: int) -> Completion:
    last: Exception | None = None
    waits: Counter = Counter()  # each backoff schedule advances on its own failures
    for i in range(max_retries + 1):
        try:
            return attempt()
        except _Retryable as e:
            last = e
            if i < max_retries:
                n = waits[e.backoff]
                waits[e.backoff] += 1
                time.sleep(e.backoff[min(n, len(e.backoff) - 1)])
    raise ModelError(f"giving up after {max_retries} retries: {last}") from last


class _CachedClient:
    name: str
    family: str
    model: str
    max_retries: int
    sampling = "temperature 0"

    def __init__(self, cache: Cache):
        self.cache = cache

    def _call(self, system: str, user: str, max_tokens: int) -> Completion:
        raise NotImplementedError

    def _key(self, system: str, user: str, max_tokens: int, repeat: int) -> str:
        return Cache.key(self.name, self.model, system, user, max_tokens, repeat)

    def is_cached(self, system: str, user: str, *, max_tokens: int, repeat: int = 0) -> bool:
        """Whether `complete` with these arguments would be answered from the cache."""
        return self.cache.get(self._key(system, user, max_tokens, repeat)) is not None

    def complete(
        self, system: str, user: str, *, max_tokens: int, repeat: int = 0
    ) -> Completion:
        key = self._key(system, user, max_tokens, repeat)
        hit = self.cache.get(key)
        if hit is not None:
            return Completion(**{"provider": self.name, **hit, "cached": True})
        c = _with_retries(lambda: self._call(system, user, max_tokens), self.max_retries)
        c = replace(c, provider=self.name)
        self.cache.put(key, {**c.__dict__, "cached": False})
        return c


class AnthropicClient(_CachedClient):
    name = "anthropic"
    family = "anthropic"

    def __init__(
        self,
        model: str,
        cache: Cache,
        max_retries: int = 5,
        sdk_client: anthropic.Anthropic | None = None,
    ):
        super().__init__(cache)
        self.model = model
        self.max_retries = max_retries
        # SDK retries disabled: this module owns the retry policy.
        self._sdk = sdk_client or anthropic.Anthropic(max_retries=0)

    def _call(self, system: str, user: str, max_tokens: int) -> Completion:
        t0 = time.monotonic()
        try:
            r = self._sdk.messages.create(
                model=self.model,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=max_tokens,
                temperature=0,
            )
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
            raise _Retryable(str(e)) from e
        except anthropic.APIStatusError as e:
            if e.status_code == 429 or e.status_code >= 500:
                raise _Retryable(f"HTTP {e.status_code}") from e
            raise ModelError(f"HTTP {e.status_code}: {e}") from e
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        return Completion(
            text, r.usage.input_tokens, r.usage.output_tokens, self.model,
            time.monotonic() - t0, False, served_model=getattr(r, "model", None),
        )


class OpenAICompatibleClient(_CachedClient):
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key_env: str,
        family: str,
        cache: Cache,
        max_retries: int = 5,
        http: httpx.Client | None = None,
    ):
        super().__init__(cache)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env
        self.family = family
        self.name = f"openai-compatible:{family}"
        self.max_retries = max_retries
        self._http = http or httpx.Client(timeout=120.0)

    def _call(self, system: str, user: str, max_tokens: int) -> Completion:
        headers = {}
        key = os.environ.get(self.api_key_env)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        t0 = time.monotonic()
        try:
            r = self._http.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise _Retryable(str(e)) from e
        if r.status_code == 429 or r.status_code >= 500:
            raise _Retryable(f"HTTP {r.status_code}")
        if r.status_code >= 400:
            raise ModelError(f"HTTP {r.status_code}: {r.text[:200]}")
        try:
            data = r.json()
            text = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise ModelError(f"malformed response: {e}") from e
        served = data.get("model")
        return Completion(
            text, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)),
            self.model, time.monotonic() - t0, False,
            served_model=served if isinstance(served, str) else None,
        )


_USAGE_LIMIT_HINT = re.compile(r"reset|usage", re.IGNORECASE)
# The CLI's own usage-limit phrasing, matched even in a successful-looking reply so that it
# is never cached as an answer.
_CLI_LIMIT_REPLY = re.compile(r"^\s*you['\u2019]ve hit your|limit \u00b7 resets", re.IGNORECASE)
# Removed from the CLI's environment: with any of these set, `claude -p` authenticates with
# the API or a cloud provider (Bedrock, Vertex, Foundry) instead of the subscription login,
# and calls recorded as "subscription" ($0) would be billed outside --max-dollars.
# ANTHROPIC_BASE_URL is kept: it routes requests but carries no credential.
_API_CREDENTIAL_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
                        "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")


def _is_usage_limit(text: str) -> bool:
    return "limit" in text.lower() and _USAGE_LIMIT_HINT.search(text) is not None


def _run_subprocess(argv: list[str], stdin: str, timeout: float) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in _API_CREDENTIAL_VARS}
    return subprocess.run(argv, input=stdin, capture_output=True, encoding="utf-8",
                          errors="replace", timeout=timeout, check=False, env=env)


class ClaudeCodeClient(_CachedClient):
    """Headless Claude Code (`claude -p`) as a plain model, billed to a Claude subscription.

    `--system-prompt` replaces Claude Code's own prompt, `--tools ""` removes every built-in
    tool and `--safe-mode` drops hooks, plugins, skills, MCP servers and CLAUDE.md, so the
    reply comes from the model alone. The CLI has no max-tokens or temperature flag:
    `max_tokens` only enters the cache key, and sampling is the CLI's default. The default
    runner strips Anthropic API credentials from the CLI's environment so that it always
    uses the subscription login.
    """

    name = "claude_code"
    family = "anthropic"
    sampling = "cli-default (temperature not pinned)"
    TIMEOUT_S = 300

    def __init__(
        self,
        model: str,
        cache: Cache,
        max_retries: int = 5,
        binary: str = "claude",
        runner: Callable[[list[str], str, float], subprocess.CompletedProcess] | None = None,
    ):
        super().__init__(cache)
        self.model = model
        self.max_retries = max_retries
        self.binary = binary
        self._runner = runner or _run_subprocess

    def argv(self, system: str) -> list[str]:
        return [self.binary, "-p", "--model", self.model, "--output-format", "json",
                "--max-turns", "1", "--safe-mode", "--disable-slash-commands",
                "--no-session-persistence", "--system-prompt", system, "--tools", ""]

    def _call(self, system: str, user: str, max_tokens: int) -> Completion:
        t0 = time.monotonic()
        try:
            p = self._runner(self.argv(system), user, self.TIMEOUT_S)
        except subprocess.TimeoutExpired as e:
            raise _Retryable(f"claude timed out after {self.TIMEOUT_S} s") from e
        except OSError as e:
            raise ModelError(f"cannot run {self.binary!r}: {e}") from e
        latency = time.monotonic() - t0
        try:
            env = json.loads(p.stdout)
        except ValueError:
            env = None
        result = env.get("result") if isinstance(env, dict) else None
        if p.returncode != 0 or not isinstance(env, dict) or env.get("is_error") \
                or not isinstance(result, str):
            detail = " ".join(x for x in (result, p.stderr, None if env else p.stdout)
                              if isinstance(x, str) and x.strip())[:300]
            if _is_usage_limit(detail):
                raise RateLimitedError(f"usage limit: {detail}")
            raise _Retryable(f"claude exit {p.returncode}: {detail or 'no result'}")
        if _CLI_LIMIT_REPLY.search(result):
            raise RateLimitedError(f"usage limit: {result[:300]}")
        usage = env.get("usage") or {}
        tokens_in = sum(int(usage.get(k) or 0) for k in (
            "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        cost = env.get("total_cost_usd")
        served = sorted(env.get("modelUsage") or {})
        return Completion(result, tokens_in, int(usage.get("output_tokens") or 0), self.model,
                          latency, False,
                          notional_cost_usd=float(cost) if cost is not None else None,
                          served_model=",".join(served) or None)


class StubClient:
    def __init__(self, fn: Callable[[str, str, int], str], family: str = "stub"):
        self.fn = fn
        self.name = "stub"
        self.family = family

    def complete(
        self, system: str, user: str, *, max_tokens: int, repeat: int = 0
    ) -> Completion:
        t0 = time.monotonic()
        text = self.fn(system, user, repeat)
        return Completion(
            text, (len(system) + len(user)) // 4, len(text) // 4, "stub",
            time.monotonic() - t0, False, provider="stub",
        )


_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


def parse_json(text: str) -> dict:
    m = _FENCE.match(text)
    body = m.group(1) if m else text
    try:
        value = json.loads(body)
    except ValueError as e:
        raise ModelOutputError(f"invalid JSON: {e}") from e
    if not isinstance(value, dict):
        raise ModelOutputError("expected a JSON object")
    return value


def parse_json_recovering(text: str, required: Collection[str]) -> tuple[dict, bool]:
    """`parse_json`, falling back to the last top-level JSON object in `text` that has every
    `required` key; returns (object, recovered).

    For run-time replies that hold more than one object (a self-correction) or prose around
    one. Raises ModelOutputError when no object qualifies, or when a "{" after the chosen
    object cannot be decoded (a truncated correction). Golden generation keeps `parse_json`.
    """
    try:
        return parse_json(text), False
    except ModelOutputError:
        pass
    decoder = json.JSONDecoder()
    found: list[tuple[int, dict]] = []  # (end, object) for each qualifying object
    failed: list[int] = []  # start of each "{" that does not decode
    i = 0
    while (start := text.find("{", i)) >= 0:
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            failed.append(start)
            i = start + 1
            continue
        if isinstance(value, dict) and all(k in value for k in required):
            found.append((end, value))
        i = end
    if not found:
        raise ModelOutputError(f"no JSON object with keys {sorted(required)} in the reply")
    end, value = found[-1]
    if any(start >= end for start in failed):
        raise ModelOutputError("reply ends with an undecodable (truncated?) JSON object")
    return value, True


def load_prices(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def price_entry(model: str, prices: dict, provider: str = "") -> dict | None:
    """The price-table entry for `model`: "<provider>:<model>", a wildcard key matching it
    (e.g. "claude_code:*"), then the bare model id; None when there is none."""
    for k in ([f"{provider}:{model}"] if provider else []) + [model]:
        if k in prices:
            return prices[k]
        for pattern, entry in prices.items():
            if "*" in pattern and fnmatch.fnmatchcase(k, pattern):
                return entry
    return None


def is_subscription(entry: dict | None) -> bool:
    return entry is not None and entry.get("billing") == "subscription"


def cost_usd(c: Completion, prices: dict) -> float:
    """Dollars charged for `c`: 0.0 when cached or subscription-billed; KeyError if unpriced."""
    if c.cached:
        return 0.0
    p = price_entry(c.model, prices, c.provider)
    if p is None:
        raise KeyError(c.model)
    if is_subscription(p):
        return 0.0
    return (
        c.input_tokens * p["input_per_mtok"] + c.output_tokens * p["output_per_mtok"]
    ) / 1_000_000
