import json

import pytest

from scimed_scout.ai import (
    AIRequest,
    CandidateDiscoveryService,
    OpenAICompatibleProvider,
    StaticAIProvider,
    parse_candidate_proposals,
)
from scimed_scout.domain import CandidateStatus
from scimed_scout.storage import ProjectRecord, SQLiteLedger


def candidate_payload(extra=None):
    item = {
        "title": "Diagnostic accuracy of Test A",
        "question_type": "DIAGNOSTIC_ACCURACY",
        "review_question": "What is the accuracy of Test A for disease X?",
        "population": "Adults with suspected disease X",
        "intervention_exposure_index_test": "Test A",
        "comparator_reference": "Reference standard B",
        "outcomes": ["sensitivity", "specificity"],
        "eligible_designs": ["diagnostic accuracy"],
        "rationale": "Clinically relevant uncertainty",
        "novelty_hypothesis": "Prior syntheses may not include the current test generation",
        "search_terms": ["Test A", "disease X", "diagnostic accuracy"],
    }
    if extra:
        item.update(extra)
    return {"candidates": [item]}


def test_candidate_parser_accepts_json_code_fence():
    fence = chr(96) * 3
    text = fence + "json\n" + json.dumps(candidate_payload()) + "\n" + fence
    proposals = parse_candidate_proposals(text)
    assert proposals[0].question_type == "DIAGNOSTIC_ACCURACY"


@pytest.mark.parametrize(
    "field,value",
    [
        ("verified_independent_studies", 99),
        ("verified_usable_studies", 99),
        ("final_decision", "PROCEED"),
        ("publication_oriented_score", 100),
    ],
)
def test_ai_candidate_cannot_set_protected_methodological_fields(field, value):
    with pytest.raises(ValueError):
        parse_candidate_proposals(json.dumps(candidate_payload({field: value})))


def test_ai_root_cannot_set_final_decision():
    payload = candidate_payload()
    payload["decision"] = "PROCEED — FIRST-CHOICE"
    with pytest.raises(ValueError):
        parse_candidate_proposals(json.dumps(payload))


def test_discovery_service_stores_candidates_but_not_methodological_verdicts(tmp_path):
    provider = StaticAIProvider(json.dumps(candidate_payload()))
    with SQLiteLedger(tmp_path / "scout.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology"))
        service = CandidateDiscoveryService(provider, ledger)
        records = service.generate_and_store(
            project_id="P1",
            specialty="Radiology",
            question_types=["DIAGNOSTIC_ACCURACY"],
            design_scope=["diagnostic accuracy studies"],
            count=1,
        )
        assert len(records) == 1
        stored = ledger.get_candidate(records[0].candidate_id)
        assert stored is not None
        assert stored.metadata["ai_role"] == "candidate_generation_only"
        assert "decision" not in stored.metadata


def test_rejected_candidate_is_not_rediscovered_by_default(tmp_path):
    provider = StaticAIProvider(json.dumps(candidate_payload()))
    with SQLiteLedger(tmp_path / "scout.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology"))
        service = CandidateDiscoveryService(provider, ledger)
        first = service.generate_and_store(project_id="P1", specialty="Radiology", count=1)
        candidate_id = first[0].candidate_id
        ledger.set_candidate_status(candidate_id, CandidateStatus.REJECTED)

        second = service.generate_and_store(project_id="P1", specialty="Radiology", count=1)
        assert second == []
        assert ledger.get_candidate(candidate_id).status == CandidateStatus.REJECTED


def test_existing_nonrejected_candidate_preserves_status(tmp_path):
    provider = StaticAIProvider(json.dumps(candidate_payload()))
    with SQLiteLedger(tmp_path / "scout.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology"))
        service = CandidateDiscoveryService(provider, ledger)
        first = service.generate_and_store(project_id="P1", specialty="Radiology", count=1)
        candidate_id = first[0].candidate_id
        ledger.set_candidate_status(candidate_id, CandidateStatus.SHORTLISTED)

        second = service.generate_and_store(project_id="P1", specialty="Radiology", count=1)
        assert second[0].status == CandidateStatus.SHORTLISTED
        assert ledger.get_candidate(candidate_id).status == CandidateStatus.SHORTLISTED


def test_openai_compatible_provider_is_vendor_neutral_and_uses_bearer_key():
    captured = {}

    def requester(req, timeout):
        captured["url"] = req.full_url
        captured["auth"] = req.headers.get("Authorization")
        body = json.loads(req.data.decode("utf-8"))
        captured["model"] = body["model"]
        return json.dumps({
            "choices": [{"message": {"content": "{\"candidates\":[]}"}}]
        }).encode("utf-8")

    provider = OpenAICompatibleProvider(
        endpoint="https://example.invalid/v1/chat/completions",
        model="free-model",
        api_key="secret",
        requester=requester,
    )
    response = provider.complete(AIRequest(system="system", prompt="prompt"))
    assert response.model == "free-model"
    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["auth"] == "Bearer secret"
    assert captured["model"] == "free-model"



def test_free_router_retries_empty_text_and_uses_only_free_route():
    attempts = []

    def requester(req, timeout):
        body = json.loads(req.data.decode("utf-8"))
        attempts.append((body["model"], body["max_tokens"]))
        if len(attempts) < 3:
            return json.dumps({
                "model": "example/reasoning-model:free",
                "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                "usage": {"completion_tokens_details": {"reasoning_tokens": body["max_tokens"]}},
            }).encode("utf-8")
        return json.dumps({
            "model": "example/responding-model:free",
            "choices": [{"message": {"content": '{"candidates":[]}'}, "finish_reason": "stop"}],
        }).encode("utf-8")

    provider = OpenAICompatibleProvider(
        endpoint="https://example.invalid/v1/chat/completions",
        model="openrouter/free",
        api_key="test-key",
        requester=requester,
    )
    response = provider.complete(AIRequest(system="s", prompt="p"))
    assert response.text == '{"candidates":[]}'
    assert response.model == "example/responding-model:free"
    assert attempts == [("openrouter/free", 4000), ("openrouter/free", 8000), ("openrouter/free", 12000)]


def test_free_router_reports_empty_responses_after_limited_retries():
    def requester(req, timeout):
        return json.dumps({
            "choices": [{"message": {"content": None}, "finish_reason": "length"}],
            "usage": {"completion_tokens_details": {"reasoning_tokens": 4000}},
        }).encode("utf-8")

    provider = OpenAICompatibleProvider(
        endpoint="https://example.invalid/v1/chat/completions",
        model="openrouter/free",
        requester=requester,
    )
    with pytest.raises(RuntimeError, match="after 3 attempts"):
        provider.complete(AIRequest(system="s", prompt="p"))


def test_openai_provider_reads_text_part_array():
    provider = OpenAICompatibleProvider(
        endpoint="https://example.invalid/v1/chat/completions",
        model="free-model",
        requester=lambda req, timeout: json.dumps({
            "choices": [{"message": {"content": [{"type": "text", "text": "valid text"}]}}],
        }).encode("utf-8"),
    )
    assert provider.complete(AIRequest(system="s", prompt="p")).text == "valid text"


class SequenceProvider:
    name = "test-sequence"
    model = "free-mock"

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def complete(self, request):
        from scimed_scout.ai.models import AIResponse
        self.requests.append(request)
        text = self.replies[min(len(self.requests)-1, len(self.replies)-1)]
        if isinstance(text, Exception):
            raise text
        return AIResponse(text, self.name, self.model, {})


def _proposal_named(name):
    item = candidate_payload()["candidates"][0]
    return {**item, "title": name, "review_question": f"Does {name} change management?"}


def test_candidate_generation_salvages_complete_objects_then_retries_short_json(tmp_path):
    complete = json.dumps(_proposal_named("Fully formed topic A"))
    bad = '{"candidates":[' + complete + ',{"title":"unfinished string'
    second = json.dumps({"candidates": [
        _proposal_named("Fully formed topic B"), _proposal_named("Fully formed topic C"),
    ]})
    provider = SequenceProvider([bad, second])
    with SQLiteLedger(tmp_path / "recover.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Cardiology"))
        records = CandidateDiscoveryService(provider, ledger).generate_and_store(
            project_id="P1", specialty="Cardiology", count=3
        )
        assert len(records) == 3
        assert len(provider.requests) == 2
        assert [r.title for r in records] == [
            "Fully formed topic A", "Fully formed topic B", "Fully formed topic C"
        ]
        assert all("unfinished" not in record.title for record in records)


def test_discovery_large_requested_count_uses_small_bounded_batches(tmp_path):
    class BatchResponder:
        name = "batch-test"
        model = "free-mock"

        def __init__(self):
            self.counts = []

        def complete(self, request):
            from scimed_scout.ai.models import AIResponse
            import re
            count = int(re.search(r"Generate (\d+) candidate", request.prompt).group(1))
            assert count <= 4
            self.counts.append(count)
            start = sum(self.counts) - count
            payload = {"candidates": [
                _proposal_named(f"Distinct topic {start + j}") for j in range(count)
            ]}
            return AIResponse(json.dumps(payload), self.name, self.model, {})

    provider = BatchResponder()
    with SQLiteLedger(tmp_path / "batch.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Cardiology"))
        found = CandidateDiscoveryService(provider, ledger).generate_and_store(
            project_id="P1", specialty="Cardiology", count=12
        )
        assert len(found) == 12
        assert provider.counts == [4, 4, 4]


def test_truncated_json_does_not_invent_a_partial_candidate(tmp_path):
    provider = SequenceProvider([
        '{"candidates":[{"title":"Cut off before remaining required fields',
    ])
    with SQLiteLedger(tmp_path / "invalid.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Cardiology"))
        with pytest.raises(RuntimeError, match="no complete candidate JSON|did not return any complete candidate JSON"):
            CandidateDiscoveryService(provider, ledger).generate_and_store(
                project_id="P1", specialty="Cardiology", count=2
            )
        assert len(provider.requests) <= 4


def test_discovery_does_not_research_a_recently_checked_identical_pico(tmp_path):
    old = {
        **candidate_payload()["candidates"][0],
        "specialty": "Radiology",
        "status": "PROVISIONAL_BACKUP",
        "checked_at": "2026-11-22T12:00:00+00:00",
        "recheck_at": "2026-11-29T12:00:00+00:00",
    }
    provider = StaticAIProvider(json.dumps(candidate_payload()))
    skipped = []
    with SQLiteLedger(tmp_path / "recent.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology"))
        found = CandidateDiscoveryService(provider, ledger).generate_and_store(
            project_id="P1", specialty="Radiology", count=1,
            recent_topics=[old], skipped_recent=skipped,
        )
        assert found == []
        assert len(skipped) == 1
        assert skipped[0]["reason"] == "RECENTLY_CHECKED_PICO"


def test_discovery_preserves_different_clinical_comparator(tmp_path):
    old = {
        **candidate_payload()["candidates"][0],
        "specialty": "Radiology",
        "status": "REJECTED",
        "recheck_at": "2026-12-22T12:00:00+00:00",
    }
    changed = candidate_payload({"comparator_reference": "Completely different reference standard"})
    provider = StaticAIProvider(json.dumps(changed))
    with SQLiteLedger(tmp_path / "different.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology"))
        found = CandidateDiscoveryService(provider, ledger).generate_and_store(
            project_id="P1", specialty="Radiology", count=1,
            recent_topics=[old],
        )
        assert len(found) == 1


@pytest.mark.parametrize("status", [401, 403, 404, 429])
def test_discovery_stops_after_first_auth_or_quota_error(tmp_path, status):
    from scimed_scout.ai.providers import ProviderFailure

    class DeniedProvider:
        name = "groq-free-backup"
        model = "openai/gpt-oss-20b"
        calls = 0

        def complete(self, request):
            self.calls += 1
            raise ProviderFailure(self.name, status, f"HTTP {status}")

    provider = DeniedProvider()
    with SQLiteLedger(tmp_path / "failed_provider.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Cardiology"))
        with pytest.raises(RuntimeError, match=f"HTTP {status}"):
            CandidateDiscoveryService(provider, ledger).generate_and_store(
                project_id="P1", specialty="Cardiology", count=12
            )
        assert provider.calls == 1
