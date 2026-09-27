import json
from types import SimpleNamespace

import pytest

from finance_channel import llm as llm_mod
from finance_channel.demo import demo_plan


class FakeMessages:
    def __init__(self, payload, stop_reason="end_turn"):
        self.payload, self.stop_reason, self.kwargs = payload, stop_reason, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            stop_reason=self.stop_reason, stop_details=None,
            content=[SimpleNamespace(type="text", text=json.dumps(self.payload))],
        )


def _llm(config, monkeypatch, payload, stop_reason="end_turn"):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    inst = llm_mod.LLM(config)
    fake = FakeMessages(payload, stop_reason)
    inst.client = SimpleNamespace(messages=fake, beta=SimpleNamespace(messages=fake))
    return inst, fake


def test_plan_video_uses_structured_output_and_fallbacks(config, monkeypatch):
    payload = demo_plan().model_dump()
    inst, fake = _llm(config, monkeypatch, payload)
    plan = inst.plan_video("compound interest", video_format="short")
    assert plan.title_idea == payload["title_idea"]
    assert fake.kwargs["model"] == "claude-opus-5"
    assert fake.kwargs["fallbacks"] == "default"
    assert fake.kwargs["betas"] == [llm_mod.FALLBACK_BETA]
    assert fake.kwargs["output_config"]["format"]["type"] == "json_schema"
    assert fake.kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_refusal_raises(config, monkeypatch):
    inst, _ = _llm(config, monkeypatch, {}, stop_reason="refusal")
    with pytest.raises(llm_mod.RefusalError):
        inst.plan_video("x", video_format="short")


def test_fallbacks_can_be_disabled(config, monkeypatch):
    config._data["llm"]["fallbacks"] = False
    inst, fake = _llm(config, monkeypatch, demo_plan().model_dump())
    inst.plan_video("x", video_format="long")
    assert "fallbacks" not in fake.kwargs and "betas" not in fake.kwargs
