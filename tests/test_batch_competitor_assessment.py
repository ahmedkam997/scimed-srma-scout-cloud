import json

from scimed_scout.ai.models import AIResponse
from scimed_scout.competitors import SemanticCompetitorAssessor
from scimed_scout.discovery.novelty import DiscoveryNoveltyService
from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger


class CountingProvider:
    name = "counting"
    model = "fixture"

    def __init__(self):
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        prompt = request.prompt
        record_ids = []
        for marker in ['"record_id": "']:
            start = 0
            while True:
                idx = prompt.find(marker, start)
                if idx < 0:
                    break
                begin = idx + len(marker)
                end = prompt.find('"', begin)
                if end < 0:
                    break
                record_ids.append(prompt[begin:end])
                start = end + 1

        assessments = []
        seen = set()
        for rid in record_ids:
            if rid in seen:
                continue
            seen.add(rid)
            assessments.append({
                "record_id": rid,
                "overall_overlap": "LOW",
                "dimensions": [],
                "adequate_review": True,
                "recent_review": True,
                "meaningful_new_information": True,
                "confidence": 0.90,
                "rationale": "Different scope",
            })
        return AIResponse(
            json.dumps({"assessments": assessments}),
            self.name,
            self.model,
            {},
        )


def candidate():
    return CandidateRecord(
        candidate_id="C1",
        project_id="P1",
        title="Test A for disease X",
        specialty="Radiology",
        question_type="DIAGNOSTIC_ACCURACY",
        review_question="What is the diagnostic accuracy of Test A for disease X?",
        population="Adults with suspected disease X",
        intervention_exposure_index_test="Test A",
        comparator_reference="Reference B",
        outcomes=["sensitivity", "specificity"],
        eligible_designs=["diagnostic accuracy"],
    )


def record(i, source="PubMed", doi=None):
    doi = doi or f"10.1000/review{i}"
    return {
        "candidate_id": "C1",
        "evidence_type": "PUBLISHED_REVIEW",
        "source_record_id": f"{source}-{i}",
        "source": source,
        "title": f"Review {i} of Test A in disease X",
        "payload": {
            "doi": doi,
            "year": 2026,
            "metadata": {
                "abstract": f"Review {i} evaluated a related but different diagnostic question involving Test A."
            },
        },
    }


def test_assess_many_uses_one_provider_call_for_ten_records():
    provider = CountingProvider()
    assessor = SemanticCompetitorAssessor(provider)
    records = [record(i) for i in range(10)]

    results = assessor.assess_many(candidate(), records)

    assert provider.calls == 1
    assert len(results) == 10
    assert all(not item.unresolved for item in results)


def test_novelty_service_deduplicates_cross_database_records_and_batches(tmp_path):
    provider = CountingProvider()
    assessor = SemanticCompetitorAssessor(provider)

    with SQLiteLedger(tmp_path / "novelty.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology"))
        ledger.upsert_candidate(candidate())

        for i in range(12):
            item = record(i, "PubMed")
            ledger.upsert_external_evidence(
                "C1",
                "PUBLISHED_REVIEW",
                item["source_record_id"],
                source=item["source"],
                title=item["title"],
                payload=item["payload"],
            )

        duplicate = record(0, "Europe PMC", doi="10.1000/review0")
        duplicate["title"] = "Same publication from Europe PMC"
        ledger.upsert_external_evidence(
            "C1",
            "PUBLISHED_REVIEW",
            duplicate["source_record_id"],
            source=duplicate["source"],
            title=duplicate["title"],
            payload=duplicate["payload"],
        )

        service = DiscoveryNoveltyService(
            ledger,
            assessor,
            max_reviews=15,
            max_registrations=5,
            batch_size=10,
        )
        summary = service.assess_candidate("C1")

        assert summary["published_reviews_discovered"] == 13
        assert summary["published_reviews_assessed"] == 12
        assert provider.calls == 2
        assert summary["published_reviews_unresolved"] == 0


def test_novelty_service_caps_semantic_scope_to_control_free_ai_budget(tmp_path):
    provider = CountingProvider()
    assessor = SemanticCompetitorAssessor(provider)

    with SQLiteLedger(tmp_path / "cap.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology"))
        ledger.upsert_candidate(candidate())

        for i in range(30):
            item = record(i)
            ledger.upsert_external_evidence(
                "C1",
                "PUBLISHED_REVIEW",
                item["source_record_id"],
                source=item["source"],
                title=item["title"],
                payload=item["payload"],
            )

        service = DiscoveryNoveltyService(
            ledger,
            assessor,
            max_reviews=15,
            batch_size=10,
        )
        summary = service.assess_candidate("C1")

        assert summary["published_reviews_assessed"] == 15
        assert summary["published_reviews_prefiltered_out"] == 15
        assert provider.calls == 2
        assert ledger.get_candidate("C1").metadata["discovery_semantic_scope_capped"] is True
