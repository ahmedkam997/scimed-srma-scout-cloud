import json

from scimed_scout.ai import AIResponse
from scimed_scout.competitors import SemanticCompetitorAssessor
from scimed_scout.extraction import StudyEligibilityExtractor
from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger
from scimed_scout.verification import CandidateEvidenceAnalysisService


class ConditionalProvider:
    name = "conditional"
    model = "test"

    def complete(self, request):
        if "Existing record:" in request.prompt:
            overlap = "HIGH" if "PROSPERO" in request.prompt else "LOW"
            return AIResponse(
                json.dumps({
                    "overall_overlap": overlap,
                    "dimensions": [],
                    "adequate_review": False,
                    "recent_review": True,
                    "meaningful_new_information": True,
                    "confidence": 0.91,
                    "rationale": "structured test assessment",
                }),
                self.name,
                self.model,
                {},
            )

        return AIResponse(
            json.dumps({
                "eligibility": "ELIGIBLE",
                "exclusion_reason": "",
                "overall_confidence": 0.93,
                "unresolved_fields": [],
                "fields": {
                    "design_label": {
                        "value": "prospective diagnostic accuracy study",
                        "evidence": "prospective diagnostic accuracy study",
                        "source_section": "abstract",
                        "confidence": 0.95,
                    },
                    "population": {
                        "value": "Adults with suspected disease X",
                        "evidence": "Adults with suspected disease X",
                        "source_section": "abstract",
                        "confidence": 0.95,
                    },
                    "intervention_exposure_index_test": {
                        "value": "Test A",
                        "evidence": "Test A",
                        "source_section": "abstract",
                        "confidence": 0.95,
                    },
                    "comparator_reference": {
                        "value": "Histopathology",
                        "evidence": "Histopathology",
                        "source_section": "abstract",
                        "confidence": 0.95,
                    },
                    "outcomes": {
                        "value": ["sensitivity"],
                        "evidence": "sensitivity",
                        "source_section": "abstract",
                        "confidence": 0.90,
                    },
                    "sample_size": {
                        "value": 100,
                        "evidence": "100 participants",
                        "source_section": "abstract",
                        "confidence": 0.90,
                    },
                    "registry_ids": {"value": [], "evidence": "", "source_section": "", "confidence": 0.0},
                    "first_author": {"value": "", "evidence": "", "source_section": "", "confidence": 0.0},
                    "year": {"value": None, "evidence": "", "source_section": "", "confidence": 0.0},
                },
            }),
            self.name,
            self.model,
            {},
        )


def test_service_persists_semantic_assessments_and_auto_extraction_without_verification(tmp_path):
    with SQLiteLedger(tmp_path / "analysis.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology"))
        ledger.upsert_candidate(
            CandidateRecord(
                "C1",
                "P1",
                "Test A accuracy",
                "Radiology",
                question_type="DIAGNOSTIC_ACCURACY",
                review_question="What is the accuracy of Test A?",
                population="Adults with suspected disease X",
                intervention_exposure_index_test="Test A",
                comparator_reference="Histopathology",
                outcomes=["sensitivity", "specificity"],
                eligible_designs=["diagnostic accuracy"],
            )
        )
        ledger.upsert_external_evidence(
            "C1",
            "PUBLISHED_REVIEW",
            "R1",
            source="PubMed",
            title="Prior review",
            payload={"metadata": {"abstract": "Prior review assessed another imaging test in disease X."}},
        )
        ledger.upsert_external_evidence(
            "C1",
            "REGISTRATION",
            "CRD1",
            source="PROSPERO",
            title="Registered review",
            payload={"metadata": {"abstract": "Registered review of Test A accuracy in adults with disease X."}},
        )
        ledger.upsert_external_evidence(
            "C1",
            "PRIMARY_STUDY",
            "S1",
            source="Europe PMC",
            title="Study 1",
            payload={
                "url": "https://example.invalid/S1",
                "metadata": {
                    "abstract": (
                        "This prospective diagnostic accuracy study enrolled 100 participants. "
                        "Adults with suspected disease X underwent Test A and Histopathology. "
                        "Sensitivity was reported."
                    )
                },
            },
        )

        provider = ConditionalProvider()
        service = CandidateEvidenceAnalysisService(
            ledger,
            SemanticCompetitorAssessor(provider),
            StudyEligibilityExtractor(provider),
        )
        summary = service.analyze_candidate("C1")

        assert summary.published_reviews_assessed == 1
        assert summary.registrations_assessed == 1
        assert summary.material_registration_overlaps == ("CRD1",)
        assert summary.auto_eligible_studies == 1

        candidate = ledger.get_candidate("C1")
        assert candidate.metadata["competitor_assessment_complete"] is True
        assert candidate.metadata["registration_assessment_complete"] is True
        assert candidate.metadata["auto_extraction_is_verified_evidence"] is False

        study = ledger.list_payloads("studies", "C1")[0]
        assert study["eligibility_status"] == "ELIGIBLE"
        assert study["eligibility_verified"] is False
        assert study["design_verified"] is False
        assert study["independence_verified"] is False

        registration = ledger.list_external_evidence("C1", "REGISTRATION")[0]
        assert registration["payload"]["semantic_assessment"]["overall_overlap"] == "HIGH"
        primary = ledger.list_external_evidence("C1", "PRIMARY_STUDY")[0]
        assert primary["payload"]["verification_status"] == "AUTO_EXTRACTED"
