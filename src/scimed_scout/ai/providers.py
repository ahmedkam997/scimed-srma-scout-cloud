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

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # The free router occasionally returns a successful HTTP response without
        # visible answer text. Retry only that condition, keeping the same free model.
        max_attempts = 3 if self.model == "openrouter/free" else 2
        last_empty_response = ""
        for attempt in range(max_attempts):
            token_limit = request.max_tokens if attempt == 0 else min(
                request.max_tokens * (attempt + 1), 12000
            )
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": request.system},
                    {"role": "user", "content": request.prompt},
                ],
                "temperature": request.temperature,
                "max_tokens": token_limit,
            }
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

            if not isinstance(data, dict):
                raise RuntimeError("AI provider response was not a JSON object")
            choices = data.get("choices") or []
            first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
            message = first_choice.get("message") or {}
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str):
                answer = content.strip()
            elif isinstance(content, list):
                answer = "".join(
                    str(part.get("text") or "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") in ("text", "output_text")
                ).strip()
            else:
                answer = ""

            if answer:
                actual_model = data.get("model")
                return AIResponse(
                    answer,
                    self.name,
                    actual_model if isinstance(actual_model, str) and actual_model else self.model,
                    data,
                )

            finish_reason = first_choice.get("finish_reason", "missing")
            usage = data.get("usage") or {}
            token_details = usage.get("completion_tokens_details") or {} if isinstance(usage, dict) else {}
            reasoning_tokens = token_details.get("reasoning_tokens", "unknown") if isinstance(token_details, dict) else "unknown"
            last_empty_response = (
                f"finish_reason={finish_reason}, "
                f"reasoning_tokens={reasoning_tokens}, "
                f"max_tokens={token_limit}"
            )

        raise RuntimeError(
            f"AI provider returned no visible text after {max_attempts} attempts "
            f"({last_empty_response}). No paid model was used."
        )

    def _request(self, req: urllib.request.Request) -> bytes:
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            return response.read()
