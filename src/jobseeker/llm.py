from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol, TypeVar

import groq
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)
MAX_WAITS = 4            # per call, for short per-minute 429s
MAX_WAIT_SECONDS = 65.0  # one token-per-minute window
QUOTA_THRESHOLD = 120.0  # a longer retry-after means the daily quota is gone
CONNECTION_RETRIES = 3  # dropped connections are retried after 2, 4 and 8 seconds


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
