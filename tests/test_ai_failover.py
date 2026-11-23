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
    assert backup.calls[0].max_tokens == 4000


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


def test_http_client_uses_named_user_agent_instead_of_python_urllib():
    requests = []

    def respond(req, timeout):
        requests.append(req)
        return json.dumps({
            "model": "openai/gpt-oss-20b",
            "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
        }).encode("utf-8")

    provider = OpenAICompatibleProvider(
        endpoint="https://api.groq.com/openai/v1/chat/completions",
        model="openai/gpt-oss-20b",
        api_key="placeholder-never-log",
        requester=respond,
        empty_retries=1,
    )
    assert json.loads(provider.complete(AIRequest(system="s", prompt="p")).text)["ok"]
    assert requests[0].get_header("User-agent") == "SciMed-Review-Scout/1.0"


def test_groq_uses_low_reasoning_and_json_mode_for_complex_prompts():
    captured = {}

    def respond(req, timeout):
        body = json.loads(req.data.decode("utf-8"))
        captured.update(body)
        return json.dumps({
            "model": "openai/gpt-oss-20b",
            "choices": [{"message": {"content": '{"candidates":[]}'}, "finish_reason": "stop"}],
        }).encode("utf-8")

    provider = OpenAICompatibleProvider(
        endpoint="https://api.groq.com/openai/v1/chat/completions",
        model="openai/gpt-oss-20b", requester=respond,
        empty_retries=1, name="groq-free-backup"
    )
    provider.complete(AIRequest(system="Return JSON only", prompt="Generate clinical topics", max_tokens=3200))
    assert captured["reasoning_effort"] == "low"
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["max_tokens"] == 3200


def test_openrouter_free_does_not_receive_groq_specific_fields():
    captured = {}

    def respond(req, timeout):
        captured.update(json.loads(req.data.decode("utf-8")))
        return json.dumps({"choices": [{"message": {"content": '{"candidates":[]}'}}]}).encode()

    provider = OpenAICompatibleProvider(
        endpoint="https://openrouter.ai/api/v1/chat/completions",
        model="openrouter/free", requester=respond, empty_retries=1,
    )
    provider.complete(AIRequest(system="system", prompt="candidate task"))
    assert "reasoning_effort" not in captured
    assert "response_format" not in captured


def test_topic_generation_keeps_complete_proposals_after_free_quota_429(tmp_path):
    from scimed_scout.ai.discovery import CandidateDiscoveryService
    from scimed_scout.storage import ProjectRecord, SQLiteLedger

    class StopsAfterOneBatch:
        name = "mock-then-429"
        model = "free-test"

        def __init__(self):
            self.calls = 0

        def complete(self, request):
            self.calls += 1
            if self.calls > 1:
                raise ProviderFailure("groq-free-backup", 429, "HTTP 429")
            items = [
                {
                    "title": f"Review question {i}",
                    "question_type": "EFFECTIVENESS",
                    "review_question": f"Do interventions for phenotype {i} improve outcomes?",
                    "specialty": "Cardiology",
                    "population": f"Adults with phenotype {i}",
                    "intervention_exposure_index_test": f"Intervention {i}",
                    "comparator_reference": "Usual care",
                    "outcomes": ["mortality"],
                    "eligible_designs": ["RCT"],
                    "search_terms": [f"phenotype {i}"],
                }
                for i in range(4)
            ]
            return AIResponse(json.dumps({"candidates": items}), self.name, self.model, {})

    provider = StopsAfterOneBatch()
    with SQLiteLedger(tmp_path / "retained.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("p1", "Cardiology"))
        generator = CandidateDiscoveryService(provider, ledger)
        candidates = generator.generate_and_store(
            project_id="p1", specialty="Cardiology", count=8
        )
        assert len(candidates) == 4
        assert provider.calls == 2
        assert generator.generation_warnings
        assert "HTTP 429" in generator.generation_warnings[0]
        assert len(ledger.list_candidates("p1")) == 4


def test_free_router_does_not_repeat_groq_requests_after_backup_429():
    primary = FakeProvider(ProviderFailure("openrouter-free", 429, "HTTP 429"))
    backup = FakeProvider(ProviderFailure("groq-free-backup", 429, "HTTP 429"))
    router = FreeProviderFallback(primary, backup)
    with pytest.raises(ProviderFailure):
        router.complete(AIRequest(system="s", prompt="p"))
    assert router.backup_quota_exhausted
    with pytest.raises(ProviderFailure):
        router.complete(AIRequest(system="s", prompt="p"))
    assert len(primary.calls) == 1
    assert len(backup.calls) == 1
