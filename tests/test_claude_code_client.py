import json
import subprocess

import pytest

from adr_eval import llm
from adr_eval.cache import Cache
from adr_eval.llm import (
    USAGE_LIMIT_BACKOFF_SECONDS,
    ClaudeCodeClient,
    Completion,
    ModelError,
    cost_usd,
)


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(llm.time, "sleep", calls.append)
    return calls


def envelope(text="hello", **over) -> str:
    env = {
        "type": "result", "is_error": False, "result": text,
        "usage": {"input_tokens": 2, "output_tokens": 9, "cache_creation_input_tokens": 100,
                  "cache_read_input_tokens": 50},
        "total_cost_usd": 0.0039, "modelUsage": {"claude-haiku-5-5": {}},
        "session_id": "s", "stop_reason": "end_turn", "terminal_reason": "completed",
    }
    env.update(over)
    return json.dumps(env)


class FakeRunner:
    """Replays (returncode, stdout, stderr) tuples or exceptions; records each call."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[tuple[list[str], str, float]] = []

    def __call__(self, argv, stdin, timeout):
        self.calls.append((argv, stdin, timeout))
        o = self.outcomes.pop(0)
        if isinstance(o, BaseException):
            raise o
        rc, out, err = o
        return subprocess.CompletedProcess(argv, rc, out, err)


def client(tmp_path, runner, **kw) -> ClaudeCodeClient:
    return ClaudeCodeClient("haiku", Cache(tmp_path), runner=runner, **kw)


def test_parses_envelope_and_builds_plain_model_argv(tmp_path, sleeps):
    fake = FakeRunner((0, envelope("hello"), ""))
    cl = client(tmp_path, fake)
    c = cl.complete("SYS", "USER", max_tokens=50)
    assert (cl.name, cl.family) == ("claude_code", "anthropic")
    assert cl.sampling == "cli-default (temperature not pinned)"
    assert c.text == "hello" and c.model == "haiku" and not c.cached
    assert c.served_model == "claude-haiku-5-5"
    assert (c.input_tokens, c.output_tokens) == (2 + 100 + 50, 9)
    assert c.notional_cost_usd == pytest.approx(0.0039)
    assert c.latency_s >= 0.0
    argv, stdin, timeout = fake.calls[0]
    assert stdin == "USER" and timeout == 300
    assert argv[:2] == ["claude", "-p"]
    assert argv[argv.index("--model") + 1] == "haiku"
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--max-turns") + 1] == "1"
    assert argv[argv.index("--system-prompt") + 1] == "SYS"
    assert "--append-system-prompt" not in argv
    assert argv[argv.index("--tools") + 1] == ""
    assert "--safe-mode" in argv  # no hooks, plugins, MCP servers, CLAUDE.md
    assert "USER" not in argv  # the user message goes on stdin only
    assert sleeps == []


def test_custom_binary(tmp_path):
    fake = FakeRunner((0, envelope(), ""))
    client(tmp_path, fake, binary="/opt/bin/claude").complete("s", "u", max_tokens=5)
    assert fake.calls[0][0][0] == "/opt/bin/claude"


def test_retries_on_nonzero_exit_then_succeeds(tmp_path, sleeps):
    fake = FakeRunner((1, "", "boom"), (0, envelope("ok"), ""))
    c = client(tmp_path, fake).complete("s", "u", max_tokens=5)
    assert c.text == "ok" and len(fake.calls) == 2 and sleeps == [1]


@pytest.mark.parametrize("bad", [
    (0, envelope("x", is_error=True), ""),
    (0, json.dumps({"type": "result", "is_error": False}), ""),  # no result
    (0, "not json at all", ""),
    subprocess.TimeoutExpired(["claude"], 300),
])
def test_retryable_failures(tmp_path, sleeps, bad):
    fake = FakeRunner(bad, (0, envelope("ok"), ""))
    assert client(tmp_path, fake).complete("s", "u", max_tokens=5).text == "ok"
    assert sleeps == [1]


def test_gives_up_with_model_error(tmp_path, sleeps):
    fake = FakeRunner(*[(1, "", "boom")] * 3)
    with pytest.raises(ModelError):
        client(tmp_path, fake, max_retries=2).complete("s", "u", max_tokens=5)
    assert len(fake.calls) == 3 and sleeps == [1, 2]


def test_missing_binary_is_not_retried(tmp_path, sleeps):
    fake = FakeRunner(FileNotFoundError("claude"))
    with pytest.raises(ModelError, match="claude"):
        client(tmp_path, fake).complete("s", "u", max_tokens=5)
    assert sleeps == []


@pytest.mark.parametrize("bad", [
    (1, "", "Claude usage limit reached. Your limit will reset at 5pm."),
    (0, envelope("Claude AI usage limit reached|1700000000", is_error=True), ""),
    (1, envelope("5-hour limit reached ∙ resets 3am", is_error=True), ""),
])
def test_usage_limit_waits_with_long_backoff(tmp_path, sleeps, bad):
    fake = FakeRunner(bad, bad, (0, envelope("ok"), ""))
    assert client(tmp_path, fake).complete("s", "u", max_tokens=5).text == "ok"
    assert sleeps == [60, 120]
    assert USAGE_LIMIT_BACKOFF_SECONDS == (60, 120, 240, 480, 900)


def test_usage_limit_gives_up_after_full_schedule(tmp_path, sleeps):
    bad = (1, "", "usage limit reached")
    with pytest.raises(ModelError, match="limit"):
        client(tmp_path, FakeRunner(*[bad] * 6)).complete("s", "u", max_tokens=5)
    assert sleeps == [60, 120, 240, 480, 900]


def test_limit_word_in_a_successful_answer_is_not_a_usage_limit(tmp_path, sleeps):
    text = "The usage limit resets monthly."
    fake = FakeRunner((0, envelope(text), ""))
    assert client(tmp_path, fake).complete("s", "u", max_tokens=5).text == text
    assert sleeps == []


def test_cache_hit_avoids_second_process_and_repeat_changes_key(tmp_path, sleeps):
    fake = FakeRunner((0, envelope("a"), ""), (0, envelope("b"), ""))
    cl = client(tmp_path, fake)
    a = cl.complete("s", "u", max_tokens=5)
    a2 = cl.complete("s", "u", max_tokens=5)
    b = cl.complete("s", "u", max_tokens=5, repeat=1)
    assert len(fake.calls) == 2
    assert a2.cached and a2.text == "a" and a2.notional_cost_usd == a.notional_cost_usd
    assert not b.cached and b.text == "b"
    assert cl.is_cached("s", "u", max_tokens=5, repeat=1)
    assert not cl.is_cached("s", "u", max_tokens=5, repeat=2)


def test_cache_key_names_claude_code(tmp_path):
    cache = Cache(tmp_path)
    ClaudeCodeClient("haiku", cache, runner=FakeRunner((0, envelope("a"), ""))).complete(
        "s", "u", max_tokens=5, repeat=3)
    assert cache.get(Cache.key("claude_code", "haiku", "s", "u", 5, 3))["text"] == "a"


def test_cost_zero_for_subscription_billing(tmp_path):
    prices = {"claude_code:*": {"billing": "subscription", "as_of": "2026-11-09"},
              "m": {"input_per_mtok": 3.0, "output_per_mtok": 15.0}}
    c = client(tmp_path, FakeRunner((0, envelope(), ""))).complete("s", "u", max_tokens=5)
    assert c.provider == "claude_code"
    assert cost_usd(c, prices) == 0.0
    # an API-billed completion is still priced, and an unknown model still raises
    assert cost_usd(Completion("x", 1_000_000, 0, "m", 0.1, False), prices) == 3.0
    with pytest.raises(KeyError):
        cost_usd(Completion("x", 1, 1, "sonnet", 0.1, False), prices)


def test_shipped_prices_mark_claude_code_as_subscription(tmp_path):
    from pathlib import Path

    from adr_eval.llm import load_prices

    prices = load_prices(Path(__file__).parent.parent / "config" / "prices.json")
    for model in ("claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"):
        c = Completion("x", 10, 10, model, 0.1, False, provider="claude_code")
        assert cost_usd(c, prices) == 0.0


def test_served_model_joins_every_model_usage_key_and_survives_the_cache(tmp_path):
    fake = FakeRunner((0, envelope("a", modelUsage={"m-b": {}, "m-a": {}}), ""),
                      (0, envelope("b", modelUsage={}), ""))
    cl = client(tmp_path, fake)
    assert cl.complete("s", "u", max_tokens=5).served_model == "m-a,m-b"
    assert cl.complete("s", "u", max_tokens=5).served_model == "m-a,m-b"  # cache hit
    assert cl.complete("s", "u", max_tokens=5, repeat=1).served_model is None


def test_success_shaped_usage_limit_message_is_not_cached(tmp_path, sleeps):
    for msg in ("You've hit your limit · resets 3am (UTC)",
                "you’ve hit your weekly limit",
                "Opus limit · resets Monday"):
        fake = FakeRunner((0, envelope(msg), ""), (0, envelope("ok"), ""))
        cl = client(tmp_path / str(len(sleeps)), fake)
        assert cl.complete("s", "u", max_tokens=5).text == "ok"
        assert cl.complete("s", "u", max_tokens=5).text == "ok"  # the limit was not cached
    assert sleeps == [60, 60, 60]


def test_non_ascii_text_round_trips(tmp_path):
    text = "\u00a7 12\u00a0(a) \ufb01ling \u201cquoted\u201d"
    fake = FakeRunner((0, envelope(text), ""))
    c = client(tmp_path, fake).complete("s\u00a7", text, max_tokens=5)
    assert fake.calls[0][1] == text and c.text == text


FAKE_CLAUDE = """#!{python}
import json, os, sys
data = sys.stdin.buffer.read().decode("utf-8")
seen = [k for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
                  "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "ANTHROPIC_BASE_URL",
                  "ADR_EVAL_MARK")
        if k in os.environ]
out = {{"type": "result", "is_error": False, "result": json.dumps({{"stdin": data,
       "env": seen}}), "usage": {{"input_tokens": 1, "output_tokens": 1}},
       "total_cost_usd": 0.0, "modelUsage": {{"claude-haiku-5-5": {{}}}}}}
sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
"""


def test_default_runner_scrubs_api_credentials_and_uses_utf8(tmp_path, monkeypatch):
    """A fake `claude` script (not the real CLI) sees no Anthropic API credentials, so a
    claude_code call cannot silently move from the subscription to API billing."""
    import sys

    script = tmp_path / "fake-claude"
    script.write_text(FAKE_CLAUDE.format(python=sys.executable), encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    for cloud in ("BEDROCK", "VERTEX", "FOUNDRY"):  # would bill a cloud provider instead
        monkeypatch.setenv(f"CLAUDE_CODE_USE_{cloud}", "1")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.example")  # kept: not a credential
    monkeypatch.setenv("ADR_EVAL_MARK", "1")
    text = "\u00a7 12\u00a0\ufb01 \u201cq\u201d"
    c = ClaudeCodeClient("claude-haiku-5-5", Cache(tmp_path / "c"), binary=str(script)).complete(
        "s", text, max_tokens=5)
    assert json.loads(c.text) == {"stdin": text, "env": ["ANTHROPIC_BASE_URL", "ADR_EVAL_MARK"]}
    assert "ANTHROPIC_API_KEY" in __import__("os").environ  # the parent env is untouched


def test_default_runner_decodes_utf8_with_replacement(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(argv, 0, envelope(), "")

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.example")
    llm._run_subprocess(["claude"], "u", 300)
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"
    assert "ANTHROPIC_API_KEY" not in seen["env"]
    assert "CLAUDE_CODE_USE_BEDROCK" not in seen["env"] and "ANTHROPIC_BASE_URL" in seen["env"]


def test_claude_code_full_model_id_is_subscription_billed_not_api_priced():
    prices = {"claude-sonnet-5-5": {"input_per_mtok": 3.0, "output_per_mtok": 15.0},
              "claude_code:*": {"billing": "subscription"}}
    sub = Completion("x", 1_000_000, 0, "claude-sonnet-5-5", 0.1, False, provider="claude_code")
    api = Completion("x", 1_000_000, 0, "claude-sonnet-5-5", 0.1, False, provider="anthropic")
    assert cost_usd(sub, prices) == 0.0 and cost_usd(api, prices) == 3.0
