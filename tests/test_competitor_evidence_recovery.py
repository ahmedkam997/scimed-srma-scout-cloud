from scimed_scout.competitors.assessment import _record_evidence_text, _assessment_from_raw
from scimed_scout.competitors.models import OverlapLevel
from scimed_scout.discovery.novelty import _record_text


def test_europe_pmc_native_abstract_and_title_are_available_for_provenance():
    row = {"source": "Europe PMC", "source_record_id": "123", "title": "Strain and stroke",
           "payload": {"metadata": {"abstractText": "Adults with atrial fibrillation were included."}}}
    evidence = _record_evidence_text(row)
    assert "Strain and stroke" in evidence
    assert "Adults with atrial fibrillation were included." in evidence
    assert "Adults with atrial fibrillation" in _record_text(row)
    assessment = _assessment_from_raw(
        {"overall_overlap": "LOW", "confidence": 0.9,
         "dimensions": [{"name": "population", "level": "LOW", "evidence": "Adults with atrial fibrillation"}]},
        row, evidence, "fixture", "test")
    assert not assessment.unresolved
    assert assessment.overall_overlap == OverlapLevel.LOW


def test_quote_not_in_provided_evidence_still_unresolved():
    row = {"source_record_id": "123", "title": "Review of clinical outcomes"}
    assessment = _assessment_from_raw(
        {"overall_overlap": "LOW", "confidence": 0.99,
         "dimensions": [{"name": "population", "level": "LOW", "evidence": "invented trial population"}]},
        row, _record_evidence_text(row), "fixture", "test")
    assert assessment.unresolved
