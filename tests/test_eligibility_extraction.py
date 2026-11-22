import json

from scimed_scout.ai import StaticAIProvider
from scimed_scout.extraction import EligibilityStatus, StudyEligibilityExtractor
from scimed_scout.storage import CandidateRecord


def candidate():
    return CandidateRecord(
        "C1",
        "P1",
        "Test A for disease X",
        "Radiology",
        question_type="DIAGNOSTIC_ACCURACY",
        review_question="What is the accuracy of Test A for disease X?",
        population="Adults with suspected disease X",
        intervention_exposure_index_test="Test A",
        comparator_reference="Histopathology",
        outcomes=["sensitivity", "specificity"],
        eligible_designs=["diagnostic accuracy"],
    )


def extraction_payload(design_evidence="prospective diagnostic accuracy study"):
    return {
        "eligibility": "ELIGIBLE",
        "exclusion_reason": "",
        "overall_confidence": 0.92,
        "unresolved_fields": [],
        "fields": {
            "design_label": {
                "value": "prospective diagnostic accuracy study",
                "evidence": design_evidence,
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
                "value": ["sensitivity", "specificity"],
                "evidence": "sensitivity and specificity",
                "source_section": "abstract",
                "confidence": 0.90,
            },
            "sample_size": {
                "value": 120,
                "evidence": "120 participants",
                "source_section": "abstract",
                "confidence": 0.95,
            },
            "registry_ids": {"value": [], "evidence": "", "source_section": "", "confidence": 0.0},
            "first_author": {"value": "", "evidence": "", "source_section": "", "confidence": 0.0},
            "year": {"value": None, "evidence": "", "source_section": "", "confidence": 0.0},
        },
    }


def record():
    return {
        "source_record_id": "S1",
        "source": "Europe PMC",
        "title": "Prospective evaluation of Test A",
        "payload": {
            "metadata": {
                "abstract": (
                    "This prospective diagnostic accuracy study enrolled 120 participants. "
                    "Adults with suspected disease X underwent Test A and Histopathology. "
                    "We reported sensitivity and specificity."
                )
            }
        },
    }


def test_exact_source_provenance_keeps_eligible_extraction():
    extractor = StudyEligibilityExtractor(StaticAIProvider(json.dumps(extraction_payload())))
    result = extractor.extract(candidate(), record())
    assert result.eligibility == EligibilityStatus.ELIGIBLE
    assert result.ready_for_manual_verification
    assert result.design_label.confidence == 0.95
    assert result.unresolved_fields == []


def test_hallucinated_evidence_quote_forces_uncertain_status():
    payload = extraction_payload(design_evidence="randomized crossover diagnostic trial")
    extractor = StudyEligibilityExtractor(StaticAIProvider(json.dumps(payload)))
    result = extractor.extract(candidate(), record())
    assert result.eligibility == EligibilityStatus.UNCERTAIN
    assert "design_label" in result.unresolved_fields
    assert result.design_label.confidence == 0.0
    assert result.overall_confidence <= 0.79
