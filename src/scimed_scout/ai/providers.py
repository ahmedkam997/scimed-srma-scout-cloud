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
    empty_retries: int | None = None

    @classmethod
    def from_env(cls) -> "OpenAICompatibleProvider":
        return cls(
            endpoint=os.getenv("SCIMED_AI_ENDPOINT", "").strip(),
            model=os.getenv("SCIMED_AI_MODEL", "").strip(),
            api_key=os.getenv("SCIMED_AI_API_KEY", "").strip(),
            empty_retries=1 if os.getenv("GROQ_API_KEY", "").strip() else 2,
            name="openrouter-free",
        )

    def complete(self, request: AIRequest) -> AIResponse:
        if not self.endpoint:
            raise RuntimeError("SCIMED_AI_ENDPOINT is not configured")
        if not self.model:
            raise RuntimeError("SCIMED_AI_MODEL is not configured")

        # Some gateways reject urllib's generic Python-urllib default UA.
        # A stable, descriptive application UA was verified to return HTTP 200
        # on Groq's model-list endpoint in GitHub Actions.
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "SciMed-Review-Scout/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # The free router occasionally returns a successful HTTP response without
        # visible answer text. Retry only that condition, keeping the same free model.
        max_attempts = self.empty_retries if self.empty_retries is not None else (3 if self.model == "openrouter/free" else 2)
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
            except urllib.error.HTTPError as exc:
                raise ProviderFailure(self.name, int(exc.code), f"HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                raise ProviderFailure(self.name, None, f"AI provider request failed: {type(exc).__name__}") from exc

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


class ProviderFailure(RuntimeError):
    """Safe provider error: no API keys, request bodies or sensitive payloads."""

    def __init__(self, provider: str, status_code: int | None, reason: str):
        self.provider = provider
        self.status_code = status_code
        super().__init__(f"{provider}: {reason}")


class FreeProviderFallback:
    """Fail over to a separate Groq free-plan account on quota/unavailable errors.

    This is not an OpenRouter-model switch, which shares account-level limits.
    The backup is used only after failure, never in parallel with the primary.
    """

    def __init__(self, primary: AIProvider, backup: AIProvider | None = None):
        self.primary = primary
        self.backup = backup
        self.name = "free-fallback" if backup else primary.name
        self.model = f"{primary.model}|{backup.model}" if backup else primary.model
        self.failover_count = 0
        self.last_provider = primary.name
        self.primary_quota_exhausted = False

    @classmethod
    def from_env(cls) -> "FreeProviderFallback":
        primary = OpenAICompatibleProvider.from_env()
        if primary.model != "openrouter/free" and not primary.model.endswith(":free"):
            raise RuntimeError(
                "Only OpenRouter free routing or explicit :free models are permitted in SciMed's no-charge mode"
            )
        key = os.getenv("GROQ_API_KEY", "").strip()
        backup = (
            OpenAICompatibleProvider(
                endpoint="https://api.groq.com/openai/v1/chat/completions",
                model="openai/gpt-oss-20b",
                api_key=key,
                timeout=60.0,
                empty_retries=1,
                name="groq-free-backup",
            )
            if key else None
        )
        return cls(primary, backup)

    def complete(self, request: AIRequest) -> AIResponse:
        if self.primary_quota_exhausted and self.backup is not None:
            return self._backup(request)
        try:
            response = self.primary.complete(request)
            self.last_provider = response.provider
            if self.backup is not None and not _looks_like_complete_json(response.text):
                # The discovery pipeline asks for JSON in every AI call. Let a
                # separate provider handle malformed/truncated free-router output.
                return self._backup(request, original=response)
            return response
        except ProviderFailure as exc:
            if self.backup is None or exc.status_code not in (402, 408, 429, 500, 502, 503, 504, None):
                raise
            if exc.status_code in (402, 429):
                self.primary_quota_exhausted = True
            return self._backup(request)
        except RuntimeError as exc:
            if self.backup is None or not any(
                marker in str(exc).lower()
                for marker in ("returned no visible text", "429", "rate limit", "quota", "timeout")
            ):
                raise
            return self._backup(request)

    def _backup(self, request: AIRequest, original: AIResponse | None = None) -> AIResponse:
        if self.backup is None:
            raise RuntimeError("Backup provider not configured")
        try:
            # Groq free quotas count output tokens, so bound request sizes.
            capped = AIRequest(
                system=request.system,
                prompt=request.prompt,
                temperature=request.temperature,
                max_tokens=min(request.max_tokens, 2200),
            )
            response = self.backup.complete(capped)
            if not _looks_like_complete_json(response.text):
                if original is not None:
                    return original
                raise ProviderFailure(self.backup.name, None, "Backup response was not complete JSON")
            self.failover_count += 1
            self.last_provider = response.provider
            return response
        except (ProviderFailure, RuntimeError):
            if original is not None:
                return original
            raise


def _looks_like_complete_json(text: str) -> bool:
    clean = text.strip()
    fence = "`" * 3
    if clean.startswith(fence):
        clean = clean.split("\n", 1)[-1].strip()
        if clean.endswith(fence):
            clean = clean[:-3].strip()
    try:
        parsed = json.loads(clean)
        return isinstance(parsed, dict)
    except (ValueError, TypeError):
        return False
