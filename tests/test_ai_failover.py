"""No network or real API tokens are required for these tests."""
import json
import urllib.error

import pytest

from scimed_scout.ai import AIRequest, AIResponse, FreeProviderFallback, OpenAICompatibleProvider
from scimed_scout.ai.providers import ProviderFailure


class FakeProvider:
    def __init__(self, value, name="mock", model="free"):
        self.value = value
        self.name = name
        self.model = model
        self.calls = []

    def complete(self, req):
        self.calls.append(req)
        if isinstance(self.value, Exception):
            raise self.value
        return AIResponse(self.value, self.name, self.model, {})


def test_groq_fallback_when_openrouter_quota_expires():
    primary = FakeProvider(ProviderFailure("openrouter-free", 429, "HTTP 429"))
    backup = FakeProvider('{"candidates":[]}', "groq-free-backup", "openai/gpt-oss-20b")
    router = FreeProviderFallback(primary, backup)
    got = router.complete(AIRequest(system="s", prompt="p", max_tokens=4000))
    assert got.provider == "groq-free-backup"
    assert router.failover_count == 1
    assert backup.calls[0].max_tokens == 2200


def test_invalid_json_fails_over_to_independent_provider():
    primary = FakeProvider('{"assessments":[{"record":"incomplete')
    backup = FakeProvider('{"assessments":[]}', name="groq-free-backup")
    router = FreeProviderFallback(primary, backup)
    assert json.loads(router.complete(AIRequest(system="s", prompt="p")).text) == {"assessments":[]}
    assert router.failover_count == 1


def test_malformed_primary_retained_if_backup_also_fails_for_salvage():
    primary = FakeProvider('{"candidates":[{"title":"valid"}], "broken"')
    backup = FakeProvider(ProviderFailure("groq-free-backup", 429, "HTTP 429"))
    router = FreeProviderFallback(primary, backup)
    assert router.complete(AIRequest(system="s", prompt="p")).text.startswith('{"candidates"')


def test_not_retrying_authorization_errors():
    primary = FakeProvider(ProviderFailure("openrouter-free", 401, "HTTP 401"))
    backup = FakeProvider('{"candidates":[]}')
    with pytest.raises(ProviderFailure):
        FreeProviderFallback(primary, backup).complete(AIRequest(system="s", prompt="p"))
    assert backup.calls == []


def test_no_backup_leaves_primary_response_unchanged():
    primary = FakeProvider('{"candidates":[{"title":"truncated')
    assert FreeProviderFallback(primary).complete(AIRequest(system="s", prompt="p")).text == primary.value


def test_live_provider_http_429_is_redacted_and_classified():
    def reject(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
    provider = OpenAICompatibleProvider(
        endpoint="https://example.invalid/chat/completions",
        model="openrouter/free",
        api_key="never-log-this-secret",
        requester=reject,
        empty_retries=1,
    )
    with pytest.raises(ProviderFailure) as caught:
        provider.complete(AIRequest(system="s", prompt="p"))
    assert caught.value.status_code == 429
    assert "never-log-this-secret" not in str(caught.value)


def test_fallback_is_opt_in_and_primary_free_only(monkeypatch):
    monkeypatch.setenv("SCIMED_AI_MODEL", "openrouter/free")
    monkeypatch.setenv("SCIMED_AI_ENDPOINT", "https://openrouter.ai/api/v1/chat/completions")
    monkeypatch.setenv("SCIMED_AI_API_KEY", "mock")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert FreeProviderFallback.from_env().backup is None
    monkeypatch.setenv("GROQ_API_KEY", "another-mock")
    router = FreeProviderFallback.from_env()
    assert router.backup.model == "openai/gpt-oss-20b"
    assert router.backup.endpoint == "https://api.groq.com/openai/v1/chat/completions"
    monkeypatch.setenv("SCIMED_AI_MODEL", "some-model-that-costs-money")
    with pytest.raises(RuntimeError, match="Only OpenRouter free"):
        FreeProviderFallback.from_env()


def test_once_daily_openrouter_quota_is_exhausted_only_backup_is_called_later():
    primary = FakeProvider(ProviderFailure("openrouter-free", 429, "HTTP 429"))
    backup = FakeProvider('{"candidates":[]}', "groq-free-backup", "openai/gpt-oss-20b")
    router = FreeProviderFallback(primary, backup)
    for _ in range(3):
        assert router.complete(AIRequest(system="s", prompt="p")).provider == "groq-free-backup"
    assert router.primary_quota_exhausted is True
    assert len(primary.calls) == 1
    assert len(backup.calls) == 3
    assert router.failover_count == 3
