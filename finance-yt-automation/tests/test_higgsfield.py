import sys
import types

import pytest

from finance_channel import higgsfield as hf


@pytest.fixture
def fake_sdk(monkeypatch):
    """Install a fake higgsfield_client whose subscribe() returns a canned payload."""
    mod = types.ModuleType("higgsfield_client")
    mod.calls = []

    def subscribe(app, arguments, on_enqueue=None, on_queue_update=None):
        mod.calls.append((app, arguments))
        if on_enqueue:
            on_enqueue("req-123")
        if isinstance(mod.payload, Exception):
            raise mod.payload
        return mod.payload

    mod.subscribe = subscribe
    mod.payload = {}
    monkeypatch.setitem(sys.modules, "higgsfield_client", mod)
    monkeypatch.setenv("HF_KEY", "id:secret")
    return mod


@pytest.fixture
def priced(config):
    config._data["higgsfield"]["models"]["seedance_t2v"]["credits_per_second"] = 2
    return config


def test_credential_status_never_reveals_value(monkeypatch):
    monkeypatch.setattr(hf, "load_env_files", lambda: None)
    monkeypatch.setenv("HF_KEY", "abc:supersecret")
    assert hf.credential_status() == "set (HF_KEY)"
    monkeypatch.setenv("HF_KEY", "no-colon")
    assert "malformed" in hf.credential_status()
    assert "no-colon" not in hf.credential_status()
    monkeypatch.delenv("HF_KEY")
    monkeypatch.delenv("HF_API_KEY", raising=False)
    monkeypatch.delenv("HF_API_SECRET", raising=False)
    assert hf.credential_status() == "missing"


def test_resolve_model_by_name_id_and_raw(config):
    assert hf.resolve_model(config, "seedance_t2v").id == "bytedance/seedance-2.5/text-to-video"
    assert hf.resolve_model(config, "some/new/model").id == "some/new/model"
    with pytest.raises(hf.HiggsfieldError):
        hf.resolve_model(config, "nope")


def test_extract_media_urls_shapes():
    assert hf.extract_media_urls({"video": {"url": "https://x/v.mp4"},
                                  "status_url": "https://api/s"}) == ["https://x/v.mp4"]
    assert hf.extract_media_urls({"images": [{"url": "https://x/1.png"}, {"url": "https://x/2.png"}]}) \
        == ["https://x/1.png", "https://x/2.png"]


def test_success_records_ledger(fake_sdk, priced):
    fake_sdk.payload = {"status": "completed", "video": {"url": "https://cdn/v.mp4"}}
    res = hf.generate(priced, "seedance_t2v", {"prompt": "sunset"}, purpose="test")
    assert res.urls == ["https://cdn/v.mp4"] and res.estimated_credits == 10
    app, args = fake_sdk.calls[0]
    assert app == "bytedance/seedance-2.5/text-to-video"
    assert args == {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "prompt": "sunset"}
    statuses = [e["status"] for e in hf.Ledger(priced.workdir).entries()]
    assert statuses == ["submitted", "completed"]
    assert hf.Ledger(priced.workdir).credits_today() == 20  # submitted + completed both counted


@pytest.mark.parametrize("payload,status", [
    ({"status": "nsfw"}, "nsfw"),
    ({"status": "failed", "error": "boom"}, "failed"),
    ({"status": "canceled"}, "canceled"),
    ({"status": "completed"}, "completed_without_media"),
])
def test_non_success_raises(fake_sdk, priced, payload, status):
    fake_sdk.payload = payload
    with pytest.raises(hf.GenerationFailed) as exc:
        hf.generate(priced, "seedance_t2v", {"prompt": "x"})
    assert exc.value.status == status and exc.value.request_id == "req-123"


def test_unknown_price_refused_by_default(fake_sdk, config):
    with pytest.raises(hf.BudgetError):
        hf.generate(config, "seedance_t2v", {"prompt": "x"})
    assert fake_sdk.calls == []


def test_per_request_and_daily_budget(fake_sdk, priced):
    priced._data["higgsfield"]["budget"]["max_credits_per_request"] = 5
    with pytest.raises(hf.BudgetError):
        hf.generate(priced, "seedance_t2v", {"prompt": "x"})
    priced._data["higgsfield"]["budget"]["max_credits_per_request"] = 100
    priced._data["higgsfield"]["budget"]["max_credits_per_day"] = 15
    fake_sdk.payload = {"status": "completed", "video": {"url": "https://cdn/v.mp4"}}
    hf.generate(priced, "seedance_t2v", {"prompt": "x", "duration": 4})   # 8 credits (x2 ledger rows)
    with pytest.raises(hf.BudgetError):
        hf.generate(priced, "seedance_t2v", {"prompt": "x"})
    assert len(fake_sdk.calls) == 1


def test_missing_credentials(fake_sdk, priced, monkeypatch):
    monkeypatch.setattr(hf, "load_env_files", lambda: None)
    monkeypatch.delenv("HF_KEY")
    with pytest.raises(hf.CredentialsError):
        hf.generate(priced, "seedance_t2v", {"prompt": "x"})
