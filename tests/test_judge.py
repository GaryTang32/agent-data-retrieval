import pytest

from adr_eval.llm import ModelOutputError, StubClient
from adr_eval.models import Answer
from adr_eval.scoring.judge import Judge, label_to_outcome, prompt_hash


def _judge(reply: str, family: str = "anthropic") -> Judge:
    return Judge(StubClient(lambda s, u, r: reply, family=family))


def test_judge_parses_label_and_flags_family():
    j = _judge('{"label": "partial", "reason": "missing unit"}')
    label, reason, comp = j.judge("q", Answer(kind="text", value="30 days"), "30")
    assert label == "partial" and reason == "missing unit" and comp.model == "stub"
    assert j.same_family_as(StubClient(lambda *a: "", family="anthropic"))
    assert not j.same_family_as(StubClient(lambda *a: "", family="openai"))


def test_judge_sees_gold_variants_and_candidate_not_passages():
    seen = []
    j = Judge(StubClient(lambda s, u, r: seen.append(u) or '{"label": "correct"}'))
    gold = Answer(kind="set", value=["a", "b"], accepted_variants=["alpha"])
    label, reason, _ = j.judge("What?", gold, "cand-x")
    assert (label, reason) == ("correct", "")
    assert "What?" in seen[0] and '"a"' in seen[0] and "alpha" in seen[0] and "cand-x" in seen[0]


def test_judge_invalid_label_or_json_raises():
    with pytest.raises(ModelOutputError):
        _judge('{"label": "maybe"}').judge("q", Answer(kind="text", value="x"), "y")
    with pytest.raises(ModelOutputError):
        _judge("not json").judge("q", Answer(kind="text", value="x"), "y")


def test_label_to_outcome():
    assert label_to_outcome("incorrect") == "wrong"
    assert label_to_outcome("correct") == "correct"
    assert label_to_outcome("partial") == "partial"


def test_prompt_hash_is_sha256():
    assert len(prompt_hash("judge")) == 64


@pytest.mark.parametrize("label", ['["correct"]', '{"x": 1}', "null", "3"])
def test_judge_non_string_label_raises_model_output_error(label):
    with pytest.raises(ModelOutputError):
        _judge('{"label": ' + label + '}').judge("q", Answer(kind="text", value="x"), "y")


def test_judge_null_reason_defaults_to_empty():
    _, reason, _ = _judge('{"label": "correct", "reason": null}').judge(
        "q", Answer(kind="text", value="x"), "y")
    assert reason == ""


DOUBLE = '{"label": "incorrect", "reason": "a"}\nOn reflection:\n{"label": "correct"}'


def test_judge_recovers_only_when_asked():
    gold = Answer(kind="text", value="x")
    with pytest.raises(ModelOutputError):
        _judge(DOUBLE).judge("q", gold, "y")
    j = Judge(StubClient(lambda s, u, r: DOUBLE), recover=True)
    assert j.judge("q", gold, "y")[:2] == ("correct", "")

