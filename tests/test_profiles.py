import json
from collections import Counter

import pytest

from adr_eval import runner
from adr_eval.cache import Cache
from adr_eval.cli import main
from adr_eval.llm import AnthropicClient, ClaudeCodeClient, ModelError, OpenAICompatibleClient
from adr_eval.runner import RunError, load_profiles, make_client

MIX = {
    "cc": {"adapter": "claude_code", "model": "haiku"},
    "cc_nobin": {"adapter": "claude_code", "model": "haiku", "binary": "no-such-claude"},
    "api": {"adapter": "anthropic", "model": "claude-sonnet-5-5",
            "api_key_env": "ANTHROPIC_API_KEY"},
    "oai_placeholder": {"adapter": "openai_compatible", "base_url": "https://x/v1",
                        "model": "<set when key arrives>", "api_key_env": "OPENAI_API_KEY",
                        "family": "openai"},
    "oai_ok": {"adapter": "openai_compatible", "base_url": "http://localhost:8000/v1",
               "model": "llama-3", "api_key_env": "SELFHOST_API_KEY", "family": "selfhost"},
}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("SELFHOST_API_KEY", "dummy")
    monkeypatch.setattr(runner.shutil, "which",
                        lambda b: "/opt/node22/bin/claude" if b == "claude" else None)


def test_shipped_profiles():
    p = load_profiles()
    # full model IDs, so the cache key and the served-model check are model-exact
    assert p["claude_code_sonnet"] == {"adapter": "claude_code", "model": "claude-sonnet-5-5"}
    assert p["claude_code_opus"] == {"adapter": "claude_code", "model": "claude-opus-5-5"}
    assert p["claude_code_haiku"] == {"adapter": "claude_code", "model": "claude-haiku-5-5"}
    assert p["anthropic_sonnet"] == {"adapter": "anthropic", "model": "claude-sonnet-5-5",
                                     "api_key_env": "ANTHROPIC_API_KEY"}
    assert p["openai"]["base_url"] == "https://api.openai.com/v1"
    assert p["openai"]["api_key_env"] == "OPENAI_API_KEY" and p["openai"]["family"] == "openai"
    assert p["gemini"]["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert p["gemini"]["api_key_env"] == "GEMINI_API_KEY" and p["gemini"]["family"] == "google"
    assert p["selfhost"]["base_url"] == "http://localhost:8000/v1"
    assert p["selfhost"]["api_key_env"] == "SELFHOST_API_KEY"
    assert {"deepseek", "openrouter"} <= set(p)
    for name in ("openai", "gemini", "deepseek", "openrouter", "selfhost"):
        assert p[name]["adapter"] == "openai_compatible"
        assert p[name]["model"].startswith("<set")
    shipped = json.loads((runner.MODELS_PATH).read_text())
    assert "stub" in shipped and "stub" not in p


def test_shipped_config_uses_profile_names():
    cfg = runner.load_config()
    assert cfg["generator"] == "claude_code_sonnet" and cfg["judge"] == "claude_code_opus"
    assert {cfg["generator"], cfg["judge"]} <= set(load_profiles())


def test_make_client_builds_each_adapter(tmp_path, env, monkeypatch):
    cache = Cache(tmp_path)
    cc = make_client("cc", MIX, cache)
    assert isinstance(cc, ClaudeCodeClient) and cc.model == "haiku" and cc.family == "anthropic"
    oc = make_client("oai_ok", MIX, cache)
    assert isinstance(oc, OpenAICompatibleClient) and oc.family == "selfhost"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    assert isinstance(make_client("api", MIX, cache), AnthropicClient)


def test_make_client_errors_name_profile_and_cause(tmp_path, env):
    cache = Cache(tmp_path)
    with pytest.raises(ValueError, match=r"api.*ANTHROPIC_API_KEY"):
        make_client("api", MIX, cache)
    with pytest.raises(ValueError, match=r"oai_placeholder.*placeholder"):
        make_client("oai_placeholder", MIX, cache)
    with pytest.raises(ValueError, match="nope"):
        make_client("nope", MIX, cache)
    with pytest.raises(RunError):  # also a RunError, so the CLI prints it cleanly
        make_client("api", MIX, cache)


def test_doctor_reports_each_profile(env, monkeypatch, capsys):
    monkeypatch.setattr(runner, "load_profiles", lambda path=None: MIX)
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "api: missing key ANTHROPIC_API_KEY",
        "cc: ok",
        "cc_nobin: missing binary no-such-claude",
        "oai_ok: ok",
        "oai_placeholder: placeholder model",
    ]


def test_doctor_live_calls_configured_profiles_only(env, monkeypatch, capsys):
    calls = []

    class Fake:
        def __init__(self, name, fail):
            self.name, self.fail = name, fail

        def complete(self, system, user, *, max_tokens, repeat=0):
            calls.append((self.name, max_tokens))
            if self.fail:
                raise ModelError("HTTP 401: bad key")
            return None

    def fake_make_client(name, profiles, cache, max_retries=5):
        assert max_retries == 0  # a live check must not sit in the usage-limit backoff
        return Fake(name, fail=name == "oai_ok")

    monkeypatch.setattr(runner, "load_profiles", lambda path=None: MIX)
    monkeypatch.setattr(runner, "make_client", fake_make_client)
    assert main(["doctor", "--live"]) == 1
    out = capsys.readouterr().out.splitlines()
    assert "cc: ok" in out and "oai_ok: error: HTTP 401: bad key" in out
    assert "api: missing key ANTHROPIC_API_KEY" in out
    assert sorted(calls) == [("cc", 1), ("oai_ok", 1)]


def test_run_rejects_unknown_profile_before_any_work(tmp_path, capsys):
    rc = main(["run", "mini", "--system", "baseline-rrf", "--generator", "nope",
               "--out", str(tmp_path / "runs")])
    assert rc == 2 and "nope" in capsys.readouterr().err
    assert not (tmp_path / "runs").exists()


def test_golden_gen_uses_generator_profile_and_stops_at_max_calls(tmp_path, monkeypatch,
                                                                  capsys):
    from adr_eval.llm import StubClient

    seen = []

    def fake_make_client(name, profiles, cache, max_retries=5):
        seen.append(name)
        return StubClient(lambda s, u, r: "not json")

    monkeypatch.setattr(runner, "make_client", fake_make_client)
    monkeypatch.setattr(runner, "golden_dir", lambda corpus: tmp_path / corpus)
    rc = main(["golden", "mini", "--gen", "--generator", "claude_code_haiku",
               "--max-calls", "2"])
    captured = capsys.readouterr()
    assert seen == ["claude_code_haiku", "claude_code_opus"]  # judge: config default
    assert rc == 3 and "--max-calls 2" in captured.err
    assert not (tmp_path / "mini").exists()  # nothing half-written; rerun resumes from cache


def _golden_stubs(monkeypatch, tmp_path, calls: Counter):
    """make_client stubs for `golden --gen`: the generator re-answers overview items in other
    words, so they reach the judge, which always says "correct"."""
    from adr_eval.llm import StubClient
    from tests.test_generate import _paraphrase_overviews

    def gen(s, u, r):
        calls["generator"] += 1
        return _paraphrase_overviews(s, u, r)

    def judge(s, u, r):
        calls["judge"] += 1
        return json.dumps({"label": "correct", "reason": "stub"})

    def fake_make_client(name, profiles, cache, max_retries=5):
        calls[f"made:{name}"] += 1
        return StubClient(judge if name == "judge_profile" else gen)

    monkeypatch.setattr(runner, "make_client", fake_make_client)
    monkeypatch.setattr(runner, "golden_dir", lambda corpus: tmp_path / corpus)


def test_golden_gen_judge_profile_and_shared_max_calls(tmp_path, monkeypatch, capsys):
    calls = Counter()
    _golden_stubs(monkeypatch, tmp_path, calls)
    args = ["golden", "mini", "--gen", "--generator", "gen_profile", "--judge", "judge_profile"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "judge judge_profile" in out
    assert calls["made:gen_profile"] == calls["made:judge_profile"] == 1
    gen_calls, judge_calls = calls["generator"], calls["judge"]
    assert judge_calls > 0
    accepted = (tmp_path / "mini" / "items.jsonl").read_text()
    assert '"qtype":"overview"' in accepted.replace(" ", "")

    # a cap that fits the generator's calls alone stops once the judge's calls count too
    calls.clear()
    rc = main([*args, "--max-calls", str(gen_calls + judge_calls - 1)])
    assert rc == 3 and calls["judge"] > 0
    assert calls["generator"] + calls["judge"] == gen_calls + judge_calls - 1
    calls.clear()
    assert main([*args, "--max-calls", str(gen_calls + judge_calls)]) == 0


def test_doctor_checks_only_named_profiles(env, monkeypatch, capsys):
    monkeypatch.setattr(runner, "load_profiles", lambda path=None: MIX)
    assert main(["doctor", "cc", "api"]) == 0
    assert capsys.readouterr().out.splitlines() == ["api: missing key ANTHROPIC_API_KEY",
                                                    "cc: ok"]
    assert main(["doctor", "nope"]) == 2
    assert "nope" in capsys.readouterr().err
