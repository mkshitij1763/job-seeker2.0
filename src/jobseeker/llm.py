from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Protocol, TypeVar

import groq
import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)
MAX_WAITS = 4            # per call, for short per-minute 429s
MAX_WAIT_SECONDS = 65.0  # one token-per-minute window
QUOTA_THRESHOLD = 120.0  # a longer retry-after means the daily quota is gone
CONNECTION_RETRIES = 3  # dropped connections are retried after 2, 4 and 8 seconds


_FENCE_CLOSE = re.compile(r"<\s*/\s*job_posting\s*>", re.I)


def fence(text: str) -> str:
    """Untrusted job text can't close the <job_posting> fence, whatever its case or spacing."""
    return _FENCE_CLOSE.sub("[/job_posting]", text)


class LLMError(Exception):
    pass


class LLMQuotaExceeded(LLMError):
    pass


class LLMUnavailable(LLMError):
    """Groq could not be reached even after retrying; stop LLM work for this run."""


def strict_schema(model_cls: type[BaseModel]) -> dict:
    """JSON schema with every object closed and every property required (Groq strict mode).
    Keep Pydantic models free of Field constraints (min/max etc.); validate those in code."""
    schema = model_cls.model_json_schema()

    def visit(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)

    visit(schema)
    return schema


class LLM(Protocol):
    def json(self, *, model: str, system: str, prompt: str, schema: type[T],
             effort: str = "low", max_tokens: int = 8000) -> T: ...


def _retry_after(e: groq.RateLimitError) -> float:
    try:
        return float(e.response.headers.get("retry-after", "20"))
    except (AttributeError, TypeError, ValueError):
        return 20.0


class GroqLLM:
    def __init__(self, api_key: str = "", client=None, sleep: Callable[[float], None] = time.sleep):
        self._client = client or groq.Groq(api_key=api_key or None, max_retries=0)
        self._sleep = sleep

    def json(self, *, model: str, system: str, prompt: str, schema: type[T],
             effort: str = "low", max_tokens: int = 8000) -> T:
        request = dict(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": schema.__name__, "strict": True,
                                             "schema": strict_schema(schema)}},
            reasoning_effort=effort,
            max_completion_tokens=max_tokens,
        )
        waits = dropped = 0
        while True:
            try:
                resp = self._client.chat.completions.create(**request)
                break
            except groq.RateLimitError as e:
                wait = _retry_after(e)
                if wait > QUOTA_THRESHOLD:
                    raise LLMQuotaExceeded(f"Groq daily quota used up for {model}; retry in {wait:.0f}s") from e
                if waits == MAX_WAITS:
                    raise LLMError(f"still rate limited after {MAX_WAITS} waits") from e
                waits += 1
                self._sleep(min(wait, MAX_WAIT_SECONDS))
            except groq.APIConnectionError as e:
                if dropped == CONNECTION_RETRIES:
                    raise LLMUnavailable(f"Groq unreachable after {CONNECTION_RETRIES} retries: {e}") from e
                dropped += 1
                self._sleep(2.0 ** dropped)
            except groq.APIError as e:
                raise LLMError(f"{type(e).__name__}: {e}") from e
        choice = resp.choices[0]
        if choice.finish_reason == "length":
            raise LLMError("response truncated at max tokens")
        text = choice.message.content
        if not text:
            raise LLMError("empty response")
        try:
            return schema.model_validate_json(text)
        except ValidationError as e:
            raise LLMError(f"invalid structured output: {e}") from e


_DAILY = re.compile(r"per.?day|daily|PerDay", re.I)


class OpenAICompatLLM:
    """Any OpenAI-compatible chat endpoint (Gemini, Cloudflare Workers AI) with the same contract as GroqLLM."""

    def __init__(self, base_url: str, api_key: str, *, name: str, client: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = client or httpx.Client(timeout=120)
        self._sleep, self.name = sleep, name

    def json(self, *, model: str, system: str, prompt: str, schema: type[T],
             effort: str = "low", max_tokens: int = 8000) -> T:
        request = dict(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": schema.__name__, "strict": True,
                                             "schema": strict_schema(schema)}},
            reasoning_effort=effort,
            max_completion_tokens=max_tokens,
        )
        waits = dropped = 0
        while True:
            try:
                resp = self._client.post(self._url, json=request, headers=self._headers)
            except httpx.TransportError as e:
                if dropped == CONNECTION_RETRIES:
                    raise LLMUnavailable(f"{self.name} unreachable: {e}") from e
                dropped += 1
                self._sleep(2.0 ** dropped)
                continue
            if resp.status_code == 429:
                wait = _header_wait(resp)
                if _DAILY.search(resp.text) or wait > QUOTA_THRESHOLD or waits == MAX_WAITS:
                    raise LLMQuotaExceeded(f"{self.name} quota used up for {model}")
                waits += 1
                self._sleep(min(wait, MAX_WAIT_SECONDS))
                continue
            if resp.status_code >= 500:  # overloaded ("high demand") is often brief; then let the next provider try
                if dropped == CONNECTION_RETRIES:
                    raise LLMUnavailable(f"{self.name} HTTP {resp.status_code}: {resp.text[:120]}")
                dropped += 1
                self._sleep(2.0 ** dropped)
                continue
            if resp.status_code >= 400:
                raise LLMError(f"{self.name} HTTP {resp.status_code}: {resp.text[:200]}")
            break
        data = resp.json()
        data = data[0] if isinstance(data, list) else data
        try:
            choice = data["choices"][0]
            text = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"{self.name}: unexpected reply {str(data)[:120]}") from e
        if choice.get("finish_reason") == "length":
            raise LLMError("response truncated at max tokens")
        if not text:
            raise LLMError("empty response")
        try:
            return schema.model_validate_json(text)
        except ValidationError as e:
            raise LLMError(f"invalid structured output: {e}") from e


def _header_wait(resp: httpx.Response) -> float:
    try:
        return float(resp.headers.get("retry-after", "20"))
    except ValueError:
        return 20.0


class RouterLLM:
    """'gemini:<model>' and 'cloudflare:<model>' go to those providers; anything else goes to Groq.
    A provider set to None has no key configured and is skipped by FallbackLLM."""

    def __init__(self, default: LLM, providers: dict[str, LLM | None]):
        self._default, self._providers = default, providers

    def _split(self, model: str) -> tuple[str | None, str]:
        prefix, sep, rest = model.partition(":")
        return (prefix, rest) if sep and prefix in self._providers else (None, model)

    def available(self, model: str) -> bool:
        prefix, _ = self._split(model)
        return prefix is None or self._providers[prefix] is not None

    def json(self, *, model: str, system: str, prompt: str, schema: type[T],
             effort: str = "low", max_tokens: int = 8000) -> T:
        prefix, name = self._split(model)
        llm = self._default if prefix is None else self._providers[prefix]
        if llm is None:
            raise LLMUnavailable(f"no API key for {prefix}")
        return llm.json(model=name, system=system, prompt=prompt, schema=schema, effort=effort,
                        max_tokens=max_tokens)


def build_llm(settings) -> RouterLLM:
    """Groq plus whichever fallback providers have keys in .env."""
    gemini = (OpenAICompatLLM("https://generativelanguage.googleapis.com/v1beta/openai", settings.gemini_api_key,
                              name="Gemini") if settings.gemini_api_key else None)
    cloudflare = None
    if settings.cloudflare_api_token and settings.cloudflare_account_id:
        cloudflare = OpenAICompatLLM(
            f"https://api.cloudflare.com/client/v4/accounts/{settings.cloudflare_account_id}/ai/v1",
            settings.cloudflare_api_token, name="Cloudflare")
    return RouterLLM(GroqLLM(settings.groq_api_key), {"gemini": gemini, "cloudflare": cloudflare})


class FallbackLLM:
    """Free daily quotas are per model: when one is used up (or its provider is down), carry on with the next
    model in its chain. Such a model is skipped for the rest of this object's life (one run, one web request)."""

    def __init__(self, llm: LLM, fallbacks: dict[str, list[str]]):
        self._llm, self._fallbacks = llm, fallbacks
        self._used_up: set[str] = set()
        self.last_model: str | None = None

    def json(self, *, model: str, system: str, prompt: str, schema: type[T],
             effort: str = "low", max_tokens: int = 8000) -> T:
        available = getattr(self._llm, "available", lambda m: True)
        chain = [m for m in [model, *self._fallbacks.get(model, [])] if m not in self._used_up and available(m)]
        error: LLMQuotaExceeded | LLMUnavailable | None = None
        for m in chain:
            try:
                out = self._llm.json(model=m, system=system, prompt=prompt, schema=schema, effort=effort,
                                     max_tokens=max_tokens)
            except (LLMQuotaExceeded, LLMUnavailable) as e:  # used up or down: try the next provider
                self._used_up.add(m)
                error = e
                continue
            self.last_model = m
            return out
        raise error or LLMQuotaExceeded(f"daily quota used up for {model} and its fallbacks")
