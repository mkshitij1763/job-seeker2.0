from __future__ import annotations


class FakeLLM:
    """responses: queue of dicts/models/exceptions; or handler(schema, prompt) -> dict/model/exception."""

    def __init__(self, responses=None, handler=None):
        self.responses = list(responses or [])
        self.handler = handler
        self.calls: list[dict] = []

    def json(self, *, model, system, prompt, schema, effort="low", max_tokens=8000):
        self.calls.append({"model": model, "system": system, "prompt": prompt, "schema": schema, "effort": effort})
        out = self.handler(schema, prompt) if self.handler else self.responses.pop(0)
        if isinstance(out, Exception):
            raise out
        return out if isinstance(out, schema) else schema.model_validate(out)
