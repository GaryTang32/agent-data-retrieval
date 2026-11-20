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


# -- failure caching, the cached stub and per-attempt budget (Phase 3 task 9) -----------------

def _raises(exc: Exception):
    def fn(system, user, repeat):
        raise exc
    return fn


def test_failures_are_cached_only_when_asked(tmp_path):
    from adr_eval.llm import CachedFailure, CachedStubClient

    cache = Cache(tmp_path / "llm")
    stub = CachedStubClient("stub-m", cache, _raises(ModelError("HTTP 400: bad")))
    # the default (Phase 0): the error is raised as it is and nothing is stored
    with pytest.raises(ModelError) as e:
        stub.complete("s", "u", max_tokens=10)
    assert not isinstance(e.value, CachedFailure)
    assert not stub.is_cached("s", "u", max_tokens=10, cache_failures=True)
    assert not (tmp_path / "llm").exists() or not any((tmp_path / "llm").rglob("*.json"))
    with pytest.raises(ModelError):
        stub.complete("s", "u", max_tokens=10)
    assert stub.calls == 2
    # asked: the failure is stored and raised as CachedFailure, then again with no call
    with pytest.raises(CachedFailure, match="bad"):
        stub.complete("s", "u", max_tokens=10, cache_failures=True)
    assert stub.calls == 3
    assert stub.is_cached("s", "u", max_tokens=10, cache_failures=True)
    assert not stub.is_cached("s", "u", max_tokens=10)   # a failure is no reply
    with pytest.raises(CachedFailure, match="bad"):
        stub.complete("s", "u", max_tokens=10, cache_failures=True)
    assert stub.calls == 3
    assert issubclass(CachedFailure, ModelError)
    # the failure is stored under its own key: a call without failure caching still runs
    with pytest.raises(ModelError):
        stub.complete("s", "u", max_tokens=10)
    assert stub.calls == 4


def test_cached_stub_client_caches_replies_and_counts_real_calls(tmp_path):
    from adr_eval.llm import CachedStubClient

    stub = CachedStubClient("stub-m", Cache(tmp_path), lambda s, u, r: f"{u}@{r}")
    a = stub.complete("s", "u", max_tokens=10)
    b = stub.complete("s", "u", max_tokens=10)
    c = stub.complete("s", "u", max_tokens=10, repeat=1)
    assert (a.text, a.cached, b.text, b.cached, c.text) == ("u@0", False, "u@0", True, "u@1")
    assert stub.calls == 2 and stub.name == "stub" and a.model == "stub-m"
    assert a.provider == "stub"
    # another model is another cache key
    other = CachedStubClient("stub-other", Cache(tmp_path), lambda s, u, r: "x")
    assert not other.complete("s", "u", max_tokens=10).cached


def _flaky(fails: int, text: str = "ok"):
    """A transport that fails `fails` times (retryable), then answers."""
    seen = {"n": 0}

    def fn(system, user, repeat):
        seen["n"] += 1
        if seen["n"] <= fails:
            raise llm._Retryable("connection reset")
        return text
    return fn


def test_each_transport_attempt_reserves_budget(tmp_path, sleeps):
    from adr_eval.llm import CachedStubClient
    from adr_eval.pipeline import Budget, BudgetExceeded, MeteredClient

    # two failures then a reply: three attempts, three units
    stub = CachedStubClient("stub-m", Cache(tmp_path / "a"), _flaky(2), max_retries=5)
    budget = Budget(None, 3, count_attempts=True)
    c = MeteredClient(stub, budget, {}).complete("s", "u", max_tokens=10)
    assert c.text == "ok" and budget.calls == 3 and stub.calls == 3
    # a budget of 2 stops before the third attempt runs
    stub = CachedStubClient("stub-m", Cache(tmp_path / "b"), _flaky(2), max_retries=5)
    budget = Budget(None, 2, count_attempts=True)
    with pytest.raises(BudgetExceeded):
        MeteredClient(stub, budget, {}).complete("s", "u", max_tokens=10,
                                                 cache_failures=True)
    assert stub.calls == 2 and budget.calls == 2 and budget.stop_reason == "calls"
    # the cap, not the transport, stopped it: nothing is cached as a failure
    assert not stub.is_cached("s", "u", max_tokens=10, cache_failures=True)
    again = MeteredClient(stub, Budget(None, 5, count_attempts=True), {})
    assert again.complete("s", "u", max_tokens=10, cache_failures=True).text == "ok"
    # Phase 0 counting (the default): one unit per call, whatever its retries
    stub = CachedStubClient("stub-m", Cache(tmp_path / "c"), _flaky(2), max_retries=5)
    budget = Budget(None, 1)
    assert MeteredClient(stub, budget, {}).complete("s", "u", max_tokens=10).text == "ok"
    assert budget.calls == 1 and stub.calls == 3


def test_a_metered_cached_failure_reserves_nothing(tmp_path):
    from adr_eval.llm import CachedFailure, CachedStubClient
    from adr_eval.pipeline import Budget, MeteredClient

    stub = CachedStubClient("stub-m", Cache(tmp_path), _raises(ModelError("down")))
    budget = Budget(None, 1, count_attempts=True)
    meter = MeteredClient(stub, budget, {})
    with pytest.raises(CachedFailure):
        meter.complete("s", "u", max_tokens=10, cache_failures=True)
    assert budget.calls == 1
    zero = Budget(None, 0, count_attempts=True)          # a zero-call rerun reproduces it
    with pytest.raises(CachedFailure):
        MeteredClient(stub, zero, {}).complete("s", "u", max_tokens=10, cache_failures=True)
    assert zero.calls == 0 and not zero.stopped and stub.calls == 1
