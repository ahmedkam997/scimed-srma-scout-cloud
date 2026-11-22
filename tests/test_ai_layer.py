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
