from __future__ import annotations

import json
import os
import re
import time
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
    rate_limit_sleeper: Callable[[float], None] | None = None

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
            if self.endpoint.startswith("https://api.groq.com/") and self.model in (
                "openai/gpt-oss-20b", "openai/gpt-oss-120b"
            ):
                # GPT-OSS output budget includes reasoning tokens. Groq supports
                # JSON object mode and low effort on these models, reducing
                # empty/truncated content during longer clinical topic requests.
                payload["reasoning_effort"] = "low"
                payload["response_format"] = {"type": "json_object"}
            req = urllib.request.Request(
                self.endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                try:
                    raw_bytes = self._request_with_bounded_rate_wait(req)
                except ProviderFailure as exc:
                    # Groq JSON object mode can fail to validate generated JSON
                    # with HTTP 400. A single plain-text retry is permissible
                    # for this specific failure only. All later parsing and
                    # scientific qualification checks remain mandatory.
                    if not (
                        payload.get("response_format")
                        and exc.status_code == 400
                        and exc.error_category == "json_mode_validation"
                    ):
                        raise
                    fallback_payload = dict(payload)
                    fallback_payload.pop("response_format", None)
                    fallback_payload["max_tokens"] = min(token_limit, 2500)
                    fallback_request = urllib.request.Request(
                        self.endpoint,
                        data=json.dumps(fallback_payload).encode("utf-8"),
                        headers=headers,
                        method="POST",
                    )
                    raw_bytes = self._request_with_bounded_rate_wait(fallback_request)
                data = json.loads(raw_bytes.decode("utf-8"))
            except ProviderFailure:
                raise
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

    def _request_with_bounded_rate_wait(self, req: urllib.request.Request) -> bytes:
        # Groq reports both daily requests and per-minute token limits.
        # Retry a *single* short-lived TPM/RPM throttle, never a daily
        # exhaustion. Do not reattempt long waits or repeat indefinitely.
        waited = False
        while True:
            try:
                return self.requester(req, self.timeout) if self.requester else self._request(req)
            except urllib.error.HTTPError as exc:
                header = exc.headers
                retry_after = _positive_float(_header_value(header, "retry-after"))
                requests_left = _nonnegative_int(
                    _header_value(header, "x-ratelimit-remaining-requests")
                )
                tokens_left = _nonnegative_int(
                    _header_value(header, "x-ratelimit-remaining-tokens")
                )
                is_gemini = self.endpoint.startswith(
                    "https://generativelanguage.googleapis.com/"
                )
                is_short_throttle = (
                    int(exc.code) == 429
                    and not waited
                    and retry_after is not None
                    and 0 < retry_after <= (12 if is_gemini else 60)
                    and (
                        (requests_left is not None and requests_left > 0)
                        or (is_gemini and requests_left is None)
                    )
                )
                if is_short_throttle:
                    waited = True
                    (self.rate_limit_sleeper or time.sleep)(retry_after + 0.5)
                    continue
                kind = _http_error_category(exc)
                raise ProviderFailure(
                    self.name, int(exc.code), f"HTTP {exc.code} ({kind})",
                    retry_after_seconds=retry_after,
                    remaining_daily_requests=requests_left,
                    remaining_minute_tokens=tokens_left,
                    error_category=kind,
                ) from exc

    def _request(self, req: urllib.request.Request) -> bytes:
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            return response.read()


def _header_value(headers: object, name: str) -> str | None:
    """Accept case-insensitive HTTP response headers from each provider."""
    if headers is None or not hasattr(headers, "items"):
        return None
    for key, value in headers.items():
        if str(key).casefold() == name:
            return str(value)
    return None


def _http_error_category(exc: urllib.error.HTTPError) -> str:
    """Return a strict, non-sensitive classification, never provider text."""
    try:
        payload = json.loads(exc.read(4096).decode("utf-8", errors="replace"))
        item = payload.get("error", {}) if isinstance(payload, dict) else {}
        if not isinstance(item, dict):
            return "unspecified"
        message = str(item.get("message") or "").casefold()
        code = str(item.get("code") or "").casefold()
        if "json" in message and any(token in message for token in (
            "validat", "invalid", "format", "generat", "schema", "parse",
        )):
            return "json_mode_validation"
        if "rate limit" in message or "tokens per minute" in message or "tpm" in message:
            return "rate_limit"
        if "context length" in message:
            return "context_window"
        if any(term in message for term in ("response_format", "reasoning_effort")):
            return "unsupported_parameter"
        if code in {"invalid_request_error", "model_not_found", "rate_limit_exceeded"}:
            return code
    except (ValueError, TypeError, OSError, UnicodeError):
        pass
    return "unspecified"


def _positive_float(value: object) -> float | None:
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if 0 < number <= 86400 else None


def _nonnegative_int(value: object) -> int | None:
    try:
        number = int(value)
    except (ValueError, TypeError):
        return None
    return number if 0 <= number <= 1000000000 else None


class ProviderFailure(RuntimeError):
    """Safe provider error: no API keys, request bodies or sensitive payloads."""

    def __init__(
        self,
        provider: str,
        status_code: int | None,
        reason: str,
        *,
        retry_after_seconds: float | None = None,
        remaining_daily_requests: int | None = None,
        remaining_minute_tokens: int | None = None,
        error_category: str = "unspecified",
    ):
        self.provider = provider
        self.status_code = status_code
        self.error_category = error_category
        self.retry_after_seconds = retry_after_seconds
        self.remaining_daily_requests = remaining_daily_requests
        self.remaining_minute_tokens = remaining_minute_tokens
        details = []
        if retry_after_seconds is not None:
            details.append(f"retry_after_seconds={retry_after_seconds:g}")
        if remaining_daily_requests is not None:
            details.append(f"remaining_daily_requests={remaining_daily_requests}")
        if remaining_minute_tokens is not None:
            details.append(f"remaining_minute_tokens={remaining_minute_tokens}")
        suffix = ("; " + ", ".join(details)) if details else ""
        super().__init__(f"{provider}: {reason}{suffix}")


class FreeProviderFallback:
    """Use independent explicitly free provider keys sequentially.

    With GEMINI_API_KEY: Gemini -> OpenRouter free -> Groq free.
    Otherwise: OpenRouter free -> Groq free (or Groq alone).
    No provider is called concurrently and no paid fallback is configured.
    """

    def __init__(self, primary: AIProvider, backup: AIProvider | None = None):
        self.primary = primary
        self.backup = backup
        self.name = "free-fallback" if backup else primary.name
        self.model = f"{primary.model}|{backup.model}" if backup else primary.model
        self.failover_count = 0
        self.last_provider = primary.name
        self.primary_quota_exhausted = False
        self.backup_quota_exhausted = False

    @classmethod
    def from_env(cls) -> "FreeProviderFallback":
        openrouter_model = os.getenv("SCIMED_AI_MODEL", "openrouter/free").strip()
        if openrouter_model != "openrouter/free" and not openrouter_model.endswith(":free"):
            raise RuntimeError(
                "Only OpenRouter free routing or explicit :free models are permitted in SciMed's no-charge mode"
            )

        openrouter_key = os.getenv("SCIMED_AI_API_KEY", "").strip()
        openrouter = (
            OpenAICompatibleProvider.from_env() if openrouter_key else None
        )
        groq_key = os.getenv("GROQ_API_KEY", "").strip()
        groq = (
            OpenAICompatibleProvider(
                endpoint="https://api.groq.com/openai/v1/chat/completions",
                model="openai/gpt-oss-20b",
                api_key=groq_key,
                timeout=60.0,
                empty_retries=1,
                name="groq-free-backup",
            ) if groq_key else None
        )
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        if gemini_key:
            # Explicit allowlist makes enabling Gemini safe even if a project
            # later enters a billable tier. No Pro/preview model selection.
            allowed = {
                "gemini-3.5-flash-lite",
                "gemini-3.1-flash-lite",
                "gemini-2.5-flash-lite",
            }
            gemini_model = os.getenv("GEMINI_FREE_MODEL", "gemini-3.5-flash-lite").strip()
            if gemini_model not in allowed:
                raise RuntimeError("GEMINI_FREE_MODEL is not in SciMed's free-only allowlist")
            gemini = OpenAICompatibleProvider(
                endpoint="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                model=gemini_model,
                api_key=gemini_key,
                timeout=60.0,
                empty_retries=1,
                name="gemini-free",
            )
            fallback = cls(openrouter, groq) if openrouter and groq else (openrouter or groq)
            return cls(gemini, fallback)
        if openrouter:
            return cls(openrouter, groq)
        if groq:
            return cls(groq)
        raise RuntimeError(
            "No free AI provider configured. Set GEMINI_API_KEY, "
            "SCIMED_AI_API_KEY or GROQ_API_KEY in GitHub Actions secrets."
        )

    @property
    def total_failover_count(self) -> int:
        nested = self.backup
        return self.failover_count + (
            nested.total_failover_count
            if isinstance(nested, FreeProviderFallback) else 0
        )

    @property
    def configured_free_route(self) -> list[str]:
        providers = [self.primary.name]
        if isinstance(self.backup, FreeProviderFallback):
            providers.extend(self.backup.configured_free_route)
        elif self.backup is not None:
            providers.append(self.backup.name)
        return providers

    @property
    def unavailable_free_providers(self) -> list[str]:
        unavailable = []
        if self.primary_quota_exhausted:
            unavailable.append(self.primary.name)
        if isinstance(self.backup, FreeProviderFallback):
            unavailable.extend(self.backup.unavailable_free_providers)
        elif self.backup is not None and self.backup_quota_exhausted:
            unavailable.append(self.backup.name)
        return unavailable

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
            unavailable = exc.status_code in (402, 408, 429, 500, 502, 503, 504, None)
            # New Gemini keys sometimes have project/model restrictions.
            # Use the independent free backup rather than aborting the whole
            # scientific discovery. Never send the key to the fallback.
            gemini_access_error = (
                self.primary.name == "gemini-free"
                and exc.status_code in (400, 401, 403, 404)
            )
            if self.backup is None or not (unavailable or gemini_access_error):
                raise
            if exc.status_code in (402, 429) or gemini_access_error:
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
        if self.backup_quota_exhausted:
            if original is not None:
                return original
            raise ProviderFailure(self.backup.name, 429, "Free backup provider is rate-limited")
        try:
            # Groq free quotas count output tokens, so bound request sizes.
            capped = AIRequest(
                system=request.system,
                prompt=request.prompt,
                temperature=request.temperature,
                max_tokens=min(request.max_tokens, 4000),
            )
            response = self.backup.complete(capped)
            if not _looks_like_complete_json(response.text):
                if original is not None:
                    return original
                raise ProviderFailure(self.backup.name, None, "Backup response was not complete JSON")
            self.failover_count += 1
            self.last_provider = response.provider
            return response
        except (ProviderFailure, RuntimeError) as exc:
            if isinstance(exc, ProviderFailure) and (
                exc.status_code in (400, 401, 402, 403, 404, 429)
            ):
                # A free provider with invalid credentials, exhausted tokens
                # or unsupported model should not be retried on every topic.
                # Its errors remain source-audited and scientific work stays
                # unresolved, never promoted by an AI response.
                self.backup_quota_exhausted = True
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
