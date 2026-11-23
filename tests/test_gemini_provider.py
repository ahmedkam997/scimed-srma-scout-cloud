"""Simulated Gemini/OpenRouter/Groq routing tests; no real keys are loaded."""
from __future__ import annotations

import json

import pytest

from scimed_scout.ai import AIRequest, AIResponse, FreeProviderFallback, OpenAICompatibleProvider
from scimed_scout.ai.providers import ProviderFailure


class Stub:
    def __init__(self, name: str, reply):
        self.name = name
        self.model = name + "-free-model"
        self.reply = reply
        self.calls = []

    def complete(self, request):
        self.calls.append(request)
        if isinstance(self.reply, Exception):
            raise self.reply
        return AIResponse(str(self.reply), self.name, self.model, {})


def _configure(monkeypatch, *, gemini="example-gemini", router="example-router", groq="example-groq"):
    monkeypatch.setenv("SCIMED_AI_MODEL", "openrouter/free")
    monkeypatch.setenv("SCIMED_AI_ENDPOINT", "https://openrouter.ai/api/v1/chat/completions")
    for key, value in [
        ("GEMINI_API_KEY", gemini),
        ("SCIMED_AI_API_KEY", router),
        ("GROQ_API_KEY", groq),
    ]:
        if value:
            monkeypatch.setenv(key, value)
        else:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("GEMINI_FREE_MODEL", raising=False)


def test_gemini_primary_config_uses_openai_compatible_google_endpoint(monkeypatch):
    _configure(monkeypatch)
    provider = FreeProviderFallback.from_env()
    assert provider.primary.name == "gemini-free"
    assert provider.primary.model == "gemini-3.5-flash-lite"
    assert provider.primary.endpoint == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert provider.backup.primary.name == "openrouter-free"
    assert provider.backup.backup.name == "groq-free-backup"
    assert provider.backup.primary.model == "openrouter/free"


def test_gemini_only_environment_never_requires_openrouter_key(monkeypatch):
    _configure(monkeypatch, router="", groq="")
    provider = FreeProviderFallback.from_env()
    assert provider.primary.name == "gemini-free"
    assert provider.backup is None
    assert provider.name == "gemini-free"


def test_gemini_and_groq_without_openrouter_stay_free(monkeypatch):
    _configure(monkeypatch, router="")
    provider = FreeProviderFallback.from_env()
    assert provider.primary.name == "gemini-free"
    assert provider.backup.name == "groq-free-backup"


def test_groq_only_is_valid_for_no_cost_mode(monkeypatch):
    _configure(monkeypatch, gemini="", router="")
    provider = FreeProviderFallback.from_env()
    assert provider.primary.name == "groq-free-backup"
    assert provider.backup is None


def test_no_provider_key_reports_safe_configuration_error(monkeypatch):
    _configure(monkeypatch, gemini="", router="", groq="")
    with pytest.raises(RuntimeError, match="No free AI provider configured"):
        FreeProviderFallback.from_env()


def test_paid_or_unallowlisted_gemini_model_is_rejected(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("GEMINI_FREE_MODEL", "gemini-4-carbon")
    with pytest.raises(RuntimeError, match="allowlist"):
        FreeProviderFallback.from_env()


def test_gemini_request_is_openai_compatible_without_paid_features(monkeypatch):
    _configure(monkeypatch)
    provider = FreeProviderFallback.from_env().primary
    requests = []

    def requester(req, timeout):
        payload = json.loads(req.data)
        requests.append((req, payload))
        return json.dumps({
            "model": "gemini-3.5-flash-lite",
            "choices": [{"message": {"content": '{"candidates":[]}'}, "finish_reason": "stop"}],
        }).encode()

    provider.requester = requester
    assert json.loads(provider.complete(AIRequest(system="JSON", prompt="topics")).text) == {"candidates":[]}
    req, payload = requests[0]
    assert req.full_url.endswith("/v1beta/openai/chat/completions")
    assert req.get_header("Authorization") == "Bearer example-gemini"
    assert payload["model"] == "gemini-3.5-flash-lite"
    assert payload["messages"][0]["role"] == "system"
    assert "tools" not in payload
    assert "google_search" not in payload
    assert "response_format" not in payload
    assert "example-gemini" not in str(payload)


def test_gemini_quota_then_openrouter_quota_then_groq_succeeds_once_each():
    gemini = Stub("gemini-free", ProviderFailure("gemini-free", 429, "HTTP 429"))
    openrouter = Stub("openrouter-free", ProviderFailure("openrouter-free", 429, "HTTP 429"))
    groq = Stub("groq-free-backup", '{"candidates":[]}')
    chained = FreeProviderFallback(gemini, FreeProviderFallback(openrouter, groq))
    request = AIRequest(system="JSON", prompt="Generate")
    assert chained.complete(request).provider == "groq-free-backup"
    assert chained.primary_quota_exhausted
    assert chained.backup.primary_quota_exhausted
    assert (len(gemini.calls), len(openrouter.calls), len(groq.calls)) == (1,1,1)
    assert chained.complete(request).provider == "groq-free-backup"
    assert (len(gemini.calls), len(openrouter.calls), len(groq.calls)) == (1,1,2)


def test_gemini_project_restriction_falls_back_without_leaking_key():
    gemini = Stub("gemini-free", ProviderFailure("gemini-free", 403, "HTTP 403"))
    openrouter = Stub("openrouter-free", '{"candidates":[]}')
    router = FreeProviderFallback(gemini, openrouter)
    got = router.complete(AIRequest(system="JSON", prompt="Generate"))
    assert got.provider == "openrouter-free"
    assert router.primary_quota_exhausted
    assert len(gemini.calls) == 1


def test_gemini_bad_json_uses_separate_free_provider_without_promoting_source_claims():
    gemini = Stub("gemini-free", '{"candidates":[{"title":"broken"')
    openrouter = Stub("openrouter-free", '{"candidates":[]}')
    router = FreeProviderFallback(gemini, openrouter)
    response = router.complete(AIRequest(system="Return JSON only", prompt="Generate"))
    assert response.provider == "openrouter-free"
    assert router.failover_count == 1


def test_gemini_429_with_no_backups_is_reported_not_fabricated():
    gemini = Stub("gemini-free", ProviderFailure("gemini-free", 429, "HTTP 429"))
    router = FreeProviderFallback(gemini)
    with pytest.raises(ProviderFailure):
        router.complete(AIRequest(system="JSON", prompt="Generate"))
