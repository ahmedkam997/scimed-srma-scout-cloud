import json

from scimed_scout.ai import StaticAIProvider
from scimed_scout.competitors import OverlapLevel, SemanticCompetitorAssessor
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
        comparator_reference="Reference B",
        outcomes=["sensitivity", "specificity"],
        eligible_designs=["diagnostic accuracy"],
    )


def test_essentially_identical_adequate_recent_review_without_new_information_is_fatal():
    response = {
        "overall_overlap": "ESSENTIALLY_IDENTICAL",
        "dimensions": [
            {"name": "population", "level": "HIGH", "rationale": "same adults", "evidence": "Adults with suspected disease X"}
        ],
        "adequate_review": True,
        "recent_review": True,
        "meaningful_new_information": False,
        "confidence": 0.94,
        "rationale": "Near-equivalent question and scope",
    }
    assessor = SemanticCompetitorAssessor(StaticAIProvider(json.dumps(response)))
    record = {
        "source_record_id": "R1",
        "source": "PubMed",
        "title": "Systematic review of Test A in disease X",
        "payload": {"metadata": {"abstract": "Adults with suspected disease X were evaluated using Test A against Reference B."}},
    }

    result = assessor.assess(candidate(), record)
    assert result.overall_overlap == OverlapLevel.ESSENTIALLY_IDENTICAL
    assert result.fatal_redundancy
    assert not result.unresolved


def test_low_confidence_competitor_assessment_remains_unresolved():
    response = {
        "overall_overlap": "HIGH",
        "dimensions": [],
        "adequate_review": True,
        "recent_review": True,
        "meaningful_new_information": False,
        "confidence": 0.65,
        "rationale": "Evidence incomplete",
    }
    assessor = SemanticCompetitorAssessor(StaticAIProvider(json.dumps(response)))
    record = {
        "source_record_id": "R1",
        "source": "PubMed",
        "title": "Review of Test A",
        "payload": {"metadata": {"abstract": "Test A was studied in adults with disease X."}},
    }
    result = assessor.assess(candidate(), record)
    assert result.unresolved
    assert not result.fatal_redundancy


def test_missing_evidence_text_fails_closed_without_semantic_clearance():
    assessor = SemanticCompetitorAssessor(StaticAIProvider("{}"))
    record = {
        "source_record_id": "R1",
        "source": "Crossref",
        "title": "Short review",
        "payload": {"metadata": {}},
    }
    result = assessor.assess(candidate(), record)
    assert result.overall_overlap == OverlapLevel.UNRESOLVED
    assert result.unresolved
    assert not result.evidence_text_available


def test_hallucinated_dimension_quote_forces_unresolved_overlap():
    response = {
        "overall_overlap": "ESSENTIALLY_IDENTICAL",
        "dimensions": [
            {
                "name": "population",
                "level": "HIGH",
                "rationale": "claimed same population",
                "evidence": "children with confirmed disease X",
            }
        ],
        "adequate_review": True,
        "recent_review": True,
        "meaningful_new_information": False,
        "confidence": 0.95,
        "rationale": "Near-identical",
    }
    assessor = SemanticCompetitorAssessor(StaticAIProvider(json.dumps(response)))
    record = {
        "source_record_id": "R2",
        "source": "PubMed",
        "title": "Systematic review of Test A in disease X",
        "payload": {"metadata": {"abstract": "Adults with suspected disease X were evaluated using Test A."}},
    }
    result = assessor.assess(candidate(), record)
    assert result.overall_overlap == OverlapLevel.UNRESOLVED
    assert result.unresolved
    assert not result.fatal_redundancy
