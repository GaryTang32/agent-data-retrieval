import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from adr_eval import llm
from adr_eval.cache import Cache
from adr_eval.llm import (
    AnthropicClient,
    Completion,
    ModelError,
    ModelOutputError,
    OpenAICompatibleClient,
    StubClient,
    cost_usd,
    load_prices,
    parse_json,
    parse_json_recovering,
)


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(llm.time, "sleep", calls.append)
    return calls


def _ok(text="ok"):
    return httpx.Response(
        200,
        json={
            "model": "served-m",
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        },
    )


def _client(handler, tmp_path, **kw):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    args = ("http://x/v1", "m", "K", "selfhost", Cache(tmp_path))
    return OpenAICompatibleClient(*args, http=http, **kw)


def test_parse_json_strips_fences_and_rejects_garbage():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('{"a": 1}') == {"a": 1}
    with pytest.raises(ModelOutputError):
        parse_json('{"a": ')
    with pytest.raises(ModelOutputError):
        parse_json("[1]")


def test_cost_zero_when_cached_and_uses_price_table():
    p = {"m": {"input_per_mtok": 3.0, "output_per_mtok": 15.0, "as_of": "2026-11-08"}}
    assert cost_usd(Completion("x", 1_000_000, 0, "m", 0.1, False), p) == 3.0
    assert cost_usd(Completion("x", 0, 1_000_000, "m", 0.1, False), p) == 15.0
    assert cost_usd(Completion("x", 1_000_000, 0, "m", 0.1, True), p) == 0.0
    with pytest.raises(KeyError):
        cost_usd(Completion("x", 1, 1, "unknown", 0.1, False), p)


def test_shipped_prices_load(tmp_path):
    from pathlib import Path

    prices = load_prices(Path(__file__).parent.parent / "config" / "prices.json")
    assert "claude-sonnet-5-5" in prices


def test_openai_compatible_retries_then_succeeds(tmp_path, sleeps):
    seq = iter([httpx.Response(429), httpx.Response(503), _ok()])
    cl = _client(lambda req: next(seq), tmp_path)
    c = cl.complete("s", "u", max_tokens=10)
    assert (c.text, c.input_tokens, c.output_tokens, c.cached) == ("ok", 7, 3, False)
    assert c.served_model == "served-m"
    assert sleeps == [1, 2]


def test_retries_on_connection_error_and_gives_up_with_backoff(tmp_path, sleeps):
    def boom(req):
        raise httpx.ConnectError("down")

    cl = _client(boom, tmp_path)
    with pytest.raises(ModelError):
        cl.complete("s", "u", max_tokens=10)
    assert sleeps == [1, 2, 4, 8, 16]


def test_client_error_not_retried(tmp_path, sleeps):
    cl = _client(lambda req: httpx.Response(400, text="bad"), tmp_path)
    with pytest.raises(ModelError):
        cl.complete("s", "u", max_tokens=10)
    assert sleeps == []


def test_cache_hit_and_repeat_index_changes_key(tmp_path, sleeps):
    n = {"calls": 0}

    def handler(req):
        n["calls"] += 1
        body = json.loads(req.content)
        assert body["temperature"] == 0
        return _ok(f"r{n['calls']}")

    cl = _client(handler, tmp_path)
    a = cl.complete("s", "u", max_tokens=10, repeat=0)
    a2 = cl.complete("s", "u", max_tokens=10, repeat=0)
    b = cl.complete("s", "u", max_tokens=10, repeat=1)
    assert n["calls"] == 2
    assert not a.cached and a2.cached and a2.text == a.text
    assert b.text == "r2"


def test_anthropic_client_retries_and_caches(tmp_path, sleeps):
    req = httpx.Request("POST", "http://x")
    outcomes = [
        anthropic.RateLimitError("slow", response=httpx.Response(429, request=req), body=None),
        SimpleNamespace(
            content=[SimpleNamespace(type="text", text="hi")],
            usage=SimpleNamespace(input_tokens=5, output_tokens=2),
            model="claude-sonnet-5-5-20261101",
        ),
    ]

    def create(**kw):
        assert kw["temperature"] == 0
        o = outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return o

    sdk = SimpleNamespace(messages=SimpleNamespace(create=create))
    cl = AnthropicClient("claude-sonnet-5-5", Cache(tmp_path), sdk_client=sdk)
    c = cl.complete("s", "u", max_tokens=10)
    assert (c.text, c.input_tokens, c.output_tokens) == ("hi", 5, 2)
    assert c.served_model == "claude-sonnet-5-5-20261101"
    assert sleeps == [1]
    assert cl.complete("s", "u", max_tokens=10).cached


def test_stub_client():
    cl = StubClient(lambda s, u, r: f"{u}-{r}" * 4)
    c = cl.complete("sys", "uu", max_tokens=5, repeat=2)
    assert c.text == "uu-2" * 4 and c.output_tokens == len(c.text) // 4 and not c.cached


# -- parse_json_recovering ---------------------------------------------------------------

REQ = ("label",)


def test_recovering_returns_strict_parse_unflagged():
    assert parse_json_recovering('{"label": "correct"}', REQ) == ({"label": "correct"}, False)
    # strict success is returned as is, even without the required keys (callers validate)
    assert parse_json_recovering('```json\n{"x": 1}\n```', REQ) == ({"x": 1}, False)


def test_recovering_takes_last_object_with_required_keys():
    text = ('{"label": "partial", "reason": "a"}\n\nWait, correction:\n'
            '{"label": "correct", "reason": "b"}\n{"note": "no label"}')
    assert parse_json_recovering(text, REQ) == ({"label": "correct", "reason": "b"}, True)


def test_recovering_ignores_braces_inside_decoded_objects_and_prose():
    text = 'Here it is: {"label": "correct", "reason": "uses {braces} and }"} done.'
    assert parse_json_recovering(text, REQ) == (
        {"label": "correct", "reason": "uses {braces} and }"}, True)


def test_recovering_finds_fenced_objects():
    text = ('```json\n{"label": "incorrect"}\n```\nActually:\n'
            '```json\n{"label": "correct", "nested": {"label": "x"}}\n```')
    assert parse_json_recovering(text, REQ) == (
        {"label": "correct", "nested": {"label": "x"}}, True)


@pytest.mark.parametrize("text", [
    "no json here",
    '{"other": 1} {"more": 2}',
    '["label"] {"x": 1} trailing',
    '{"label": "correct"} then a truncated correction {"label": "inc',
    '{"label": "correct"} {"label": "partial", "nested": {"a": 1}, "reason": "cut',
])
def test_recovering_raises_without_usable_object(text):
    with pytest.raises(ModelOutputError):
        parse_json_recovering(text, REQ)


def test_recovering_ignores_undecodable_brace_before_chosen_object():
    text = 'Draft {"label": "corr\nFinal: {"label": "correct"}'
    assert parse_json_recovering(text, REQ) == ({"label": "correct"}, True)
