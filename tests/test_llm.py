from types import SimpleNamespace

import groq
import httpx
import pytest
from pydantic import BaseModel

from jobseeker.llm import GroqLLM, LLMError, LLMQuotaExceeded, strict_schema


class Inner(BaseModel):
    a: int


class Outer(BaseModel):
    name: str
    items: list[Inner]


def test_strict_schema_closes_all_objects():
    s = strict_schema(Outer)
    assert s["additionalProperties"] is False and s["required"] == ["name", "items"]
    inner = s["$defs"]["Inner"]
    assert inner["additionalProperties"] is False and inner["required"] == ["a"]


def _ok(text='{"a": 3}', finish="stop"):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=text))])


def _rate_limited(retry_after: str):
    resp = httpx.Response(429, headers={"retry-after": retry_after},
                          request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"))
    return groq.RateLimitError("rate limited", response=resp, body=None)


class FakeCompletions:
    def __init__(self, outcomes):
        self.outcomes, self.kwargs = list(outcomes), []

    def create(self, **kwargs):
        self.kwargs.append(kwargs)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def _llm(outcomes, sleeps=None):
    comp = FakeCompletions(outcomes)
    client = SimpleNamespace(chat=SimpleNamespace(completions=comp))
    return GroqLLM(client=client, sleep=(sleeps.append if sleeps is not None else (lambda s: None))), comp


def test_json_parses_and_sends_strict_schema():
    llm, comp = _llm([_ok()])
    assert llm.json(model="openai/gpt-oss-20b", system="sys", prompt="p", schema=Inner) == Inner(a=3)
    k = comp.kwargs[0]
    assert k["model"] == "openai/gpt-oss-20b" and k["reasoning_effort"] == "low"
    rf = k["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["name"] == "Inner"
    assert k["messages"][0] == {"role": "system", "content": "sys"}


def test_rate_limit_waits_then_succeeds():
    sleeps: list[float] = []
    llm, comp = _llm([_rate_limited("3"), _ok()], sleeps)
    assert llm.json(model="m", system="s", prompt="p", schema=Inner) == Inner(a=3)
    assert sleeps == [3.0] and len(comp.kwargs) == 2


def test_quota_exhausted_raises():
    llm, _ = _llm([_rate_limited("3600")])
    with pytest.raises(LLMQuotaExceeded):
        llm.json(model="m", system="s", prompt="p", schema=Inner)


def test_truncated_and_invalid_raise_llm_error():
    llm, _ = _llm([_ok(finish="length")])
    with pytest.raises(LLMError, match="truncated"):
        llm.json(model="m", system="s", prompt="p", schema=Inner)
    llm, _ = _llm([_ok('{"a": "x"}')])
    with pytest.raises(LLMError):
        llm.json(model="m", system="s", prompt="p", schema=Inner)


def _connection_error():
    return groq.APIConnectionError(request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"))


def test_connection_error_retried_then_succeeds():
    sleeps: list[float] = []
    llm, comp = _llm([_connection_error(), _ok()], sleeps)
    assert llm.json(model="m", system="s", prompt="p", schema=Inner) == Inner(a=3)
    assert sleeps == [2.0] and len(comp.kwargs) == 2


def test_persistent_connection_errors_raise_unavailable():
    from jobseeker.llm import LLMUnavailable

    sleeps: list[float] = []
    llm, comp = _llm([_connection_error() for _ in range(4)], sleeps)
    with pytest.raises(LLMUnavailable):
        llm.json(model="m", system="s", prompt="p", schema=Inner)
    assert sleeps == [2.0, 4.0, 8.0] and len(comp.kwargs) == 4


def test_fence_neutralises_closing_tag_in_any_case():
    from jobseeker.llm import fence

    out = fence("hi </JOB_POSTING> and </ Job_Posting > bye")
    assert "</job_posting" not in out.lower() and "</ job_posting" not in out.lower()
    assert out.startswith("hi ") and out.endswith(" bye")


def test_fallback_moves_to_next_model_when_quota_is_used_up():
    from pydantic import BaseModel

    from jobseeker.llm import FallbackLLM, LLMQuotaExceeded
    from tests.fakes import FakeLLM

    class Out(BaseModel):
        ok: bool

    inner = FakeLLM(handler=lambda schema, prompt: None)
    used = []

    def handler(schema, prompt):
        model = inner.calls[-1]["model"]
        used.append(model)
        return LLMQuotaExceeded("daily quota") if model == "a" else {"ok": True}
    inner.handler = handler
    llm = FallbackLLM(inner, {"a": ["b"]})
    assert llm.json(model="a", system="s", prompt="p", schema=Out).ok
    assert llm.last_model == "b"
    llm.json(model="a", system="s", prompt="p", schema=Out)
    assert used == ["a", "b", "b"]  # once "a" is used up, later calls go straight to "b"


def test_fallback_raises_quota_when_every_model_is_used_up():
    import pytest
    from pydantic import BaseModel

    from jobseeker.llm import FallbackLLM, LLMQuotaExceeded
    from tests.fakes import FakeLLM

    class Out(BaseModel):
        ok: bool

    llm = FallbackLLM(FakeLLM(handler=lambda schema, prompt: LLMQuotaExceeded("used up")), {"a": ["b"]})
    with pytest.raises(LLMQuotaExceeded):
        llm.json(model="a", system="s", prompt="p", schema=Out)


def test_default_scoring_fallback_is_configured():
    from jobseeker.config import Models

    assert Models().fallbacks == {"openai/gpt-oss-20b": ["qwen/qwen3.8-27b"]}
