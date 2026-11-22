from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol

from .models import AIRequest, AIResponse


class AIProvider(Protocol):
    name: str
    model: str

    def complete(self, request: AIRequest) -> AIResponse:
        ...


@dataclass(slots=True)
class StaticAIProvider:
    text: str
    name: str = "static"
    model: str = "test-fixture"

    def complete(self, request: AIRequest) -> AIResponse:
        return AIResponse(self.text, self.name, self.model, {"offline": True})


@dataclass(slots=True)
class OpenAICompatibleProvider:
    """Generic provider for OpenAI-compatible chat-completions endpoints."""

    endpoint: str = ""
    model: str = ""
    api_key: str = ""
    timeout: float = 60.0
    requester: Callable[[urllib.request.Request, float], bytes] | None = None
    name: str = "openai-compatible"

    @classmethod
    def from_env(cls) -> "OpenAICompatibleProvider":
        return cls(
            endpoint=os.getenv("SCIMED_AI_ENDPOINT", "").strip(),
            model=os.getenv("SCIMED_AI_MODEL", "").strip(),
            api_key=os.getenv("SCIMED_AI_API_KEY", "").strip(),
        )

    def complete(self, request: AIRequest) -> AIResponse:
        if not self.endpoint:
            raise RuntimeError("SCIMED_AI_ENDPOINT is not configured")
        if not self.model:
            raise RuntimeError("SCIMED_AI_MODEL is not configured")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.prompt},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            raw_bytes = self.requester(req, self.timeout) if self.requester else self._request(req)
            data = json.loads(raw_bytes.decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError(f"AI provider request failed: {exc}") from exc

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("AI provider response did not contain choices")
        message = choices[0].get("message") or {}
        text = message.get("content")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("AI provider response did not contain text content")
        return AIResponse(text.strip(), self.name, self.model, data)

    def _request(self, req: urllib.request.Request) -> bytes:
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            return response.read()
