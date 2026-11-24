"""Metadata-only competitor prioritization remains conservative."""

from scimed_scout.discovery.novelty import (
    DiscoveryNoveltyService, _select_records, _unassessed_citation_queue,
)
from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger


def candidate():
    return CandidateRecord(
        candidate_id="C1", project_id="P1",
        title="Inclisiran versus statins in ASCVD",
        specialty="Cardiology", question_type="EFFECTIVENESS",
        review_question="Does inclisiran improve outcomes after ASCVD?",
        population="Adults with established ASCVD",
        intervention_exposure_index_test="Inclisiran",
        comparator_reference="Statin therapy",
        outcomes=["LDL cholesterol", "myocardial infarction"],
        eligible_designs=["Randomized trials"],
    )


def row(i, title, kind="PUBLISHED_REVIEW"):
    return {
        "source": "OpenAlex",
        "source_record_id": f"R{i}",
        "evidence_type": kind,
        "title": title,
        "payload": {
            "doi": f"10.1000/record{i}",
            "url": f"https://doi.org/10.1000/record{i}",
            "year": 2026,
            "metadata": {"abstract": title},
        },
    }


def test_intervention_specific_review_ranks_above_generic_cardiology():
    topic = candidate()
    records = [
        row(1, "Systematic review of exercise and ASCVD"),
        row(2, "Systematic review of cholesterol in cardiac patients"),
        row(3, "Inclisiran in patients with ASCVD: systematic review"),
    ]
    selected = _select_records(topic, records, limit=1)
    assert selected[0]["source_record_id"] == "R3"
    queue = _unassessed_citation_queue(records, selected)
    assert len(queue) == 2
    assert {item["record_id"] for item in queue} == {"R1", "R2"}
    assert all(item["status"] == "UNASSESSED_BIBLIOGRAPHIC_COMPETITOR" for item in queue)
    assert all("NOT VERIFIED" in item["reason"] for item in queue)


def test_all_unassessed_reviews_and_registrations_remain_explicit_blockers(tmp_path):
    with SQLiteLedger(tmp_path / "novelty.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Cardiology", question_type="EFFECTIVENESS"))
        ledger.upsert_candidate(candidate())
        for i in range(1, 6):
            item = row(i, f"Inclisiran clinical review {i}")
            ledger.upsert_external_evidence(
                "C1", "PUBLISHED_REVIEW", item["source_record_id"],
                source=item["source"], title=item["title"], payload=item["payload"],
            )
        for i in range(6, 9):
            item = row(i, f"Review protocol for inclisiran {i}", "REGISTRATION")
            ledger.upsert_external_evidence(
                "C1", "REGISTRATION", item["source_record_id"],
                source="OSF Registries", title=item["title"], payload=item["payload"],
            )

        service = DiscoveryNoveltyService(
            ledger, assessor=None, max_reviews=2, max_registrations=1,
        )
        result = service.assess_candidate("C1", allow_ai=False)
        meta = ledger.get_candidate("C1").metadata
        assert result["published_reviews_discovered"] == 5
        assert result["published_reviews_assessed"] == 2
        assert result["published_reviews_prefiltered_out"] == 3
        assert result["registrations_prefiltered_out"] == 2
        assert len(result["published_reviews_unassessed_queue"]) == 3
        assert len(result["registrations_unassessed_queue"]) == 2
        assert meta["discovery_semantic_scope_capped"] is True
        assert meta["discovery_competitor_assessment_complete"] is False
        assert meta["discovery_registration_assessment_complete"] is False
        assert meta["discovery_unassessed_review_count"] == 3
        assert meta["discovery_unassessed_registration_count"] == 2
