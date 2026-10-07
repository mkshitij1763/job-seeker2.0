import httpx
import pytest
import respx
from pydantic import BaseModel

from jobseeker.llm import LLMError, LLMQuotaExceeded, LLMUnavailable, OpenAICompatLLM, RouterLLM

URL = "https://example.test/v1/chat/completions"


class Out(BaseModel):
    ok: bool


def ok_reply(content='{"ok": true}', finish="stop"):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": finish}]})


def client():
    return OpenAICompatLLM("https://example.test/v1", "k", sleep=lambda s: None, name="test")


@respx.mock
def test_openai_compat_sends_strict_schema_and_parses():
    route = respx.post(URL).mock(return_value=ok_reply())
    assert client().json(model="m", system="s", prompt="p", schema=Out).ok
    body = route.calls[0].request.read().decode()
    assert '"strict":true' in body.replace(" ", "") and '"model":"m"' in body.replace(" ", "")
    assert route.calls[0].request.headers["authorization"] == "Bearer k"


@respx.mock
def test_openai_compat_short_429_waits_then_succeeds():
    respx.post(URL).mock(side_effect=[httpx.Response(429, headers={"retry-after": "3"}), ok_reply()])
    assert client().json(model="m", system="s", prompt="p", schema=Out).ok


@respx.mock
def test_openai_compat_daily_limit_is_quota():
    body = {"error": {"message": "Quota exceeded for metric: generate_requests_per_model_per_day"}}
    respx.post(URL).mock(return_value=httpx.Response(429, json=body))
    with pytest.raises(LLMQuotaExceeded):
        client().json(model="m", system="s", prompt="p", schema=Out)


@respx.mock
def test_openai_compat_unreachable_and_bad_output():
    respx.post(URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(LLMUnavailable):
        client().json(model="m", system="s", prompt="p", schema=Out)
    respx.post(URL).mock(return_value=ok_reply('{"nope": 1}'))
    with pytest.raises(LLMError):
        client().json(model="m", system="s", prompt="p", schema=Out)
    respx.post(URL).mock(return_value=httpx.Response(503, json={"error": {"message": "high demand"}}))
    with pytest.raises(LLMUnavailable):  # overloaded: let the next provider take it
        client().json(model="m", system="s", prompt="p", schema=Out)


def test_router_sends_prefixed_models_to_their_provider():
    from tests.fakes import FakeLLM

    groq, gem = FakeLLM(handler=lambda s, p: {"ok": True}), FakeLLM(handler=lambda s, p: {"ok": True})
    router = RouterLLM(groq, {"gemini": gem, "cloudflare": None})
    router.json(model="openai/gpt-oss-20b", system="s", prompt="p", schema=Out)
    router.json(model="gemini:gemini-3.5-flash-lite", system="s", prompt="p", schema=Out)
    assert groq.calls[0]["model"] == "openai/gpt-oss-20b" and gem.calls[0]["model"] == "gemini-3.5-flash-lite"
    assert router.available("gemini:x") and not router.available("cloudflare:x") and router.available("qwen/q")


def test_fallback_skips_unconfigured_providers_and_moves_on_when_one_is_down():
    from jobseeker.llm import FallbackLLM
    from tests.fakes import FakeLLM

    groq = FakeLLM(handler=lambda s, p: LLMUnavailable("groq down"))
    gem = FakeLLM(handler=lambda s, p: {"ok": True})
    llm = FallbackLLM(RouterLLM(groq, {"gemini": gem, "cloudflare": None}),
                      {"a": ["cloudflare:x", "gemini:g"]})
    assert llm.json(model="a", system="s", prompt="p", schema=Out).ok and llm.last_model == "gemini:g"


def test_build_llm_wires_keys(tmp_path):
    from jobseeker.config import Settings
    from jobseeker.llm import build_llm

    router = build_llm(Settings(jobseeker_home=tmp_path, groq_api_key="g", gemini_api_key="x",
                                cloudflare_api_token="", cloudflare_account_id=""))
    assert router.available("gemini:m") and not router.available("cloudflare:m")


@respx.mock
def test_openai_compat_retries_brief_overload():
    respx.post(URL).mock(side_effect=[httpx.Response(503, json={}), ok_reply()])
    assert client().json(model="m", system="s", prompt="p", schema=Out).ok
