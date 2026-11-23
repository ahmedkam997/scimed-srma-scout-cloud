import json

from scimed_scout.cloud.worker import _unverified_topic_options
from scimed_scout.discovery.models import (
    DiscoveryCandidateResult, DiscoveryEvidenceSnapshot, DiscoveryRunResult,
)
from scimed_scout.discovery.review_package import build_discovery_review_package
from scimed_scout.domain import CandidateStatus, SourceStatus
from scimed_scout.ranking import RankingResult
from scimed_scout.storage import (
    CandidateRecord, ProjectRecord, SearchLogRecord, SQLiteLedger,
)
from scimed_scout.verification.coverage import VerificationCoverage


def question(cid="TOPIC1"):
    return CandidateRecord(
        candidate_id=cid,
        project_id="PROJECT1",
        title="Ketone monoester supplementation and cardiac biomarkers in endurance athletes",
        specialty="Cardiology",
        question_type="EFFECTIVENESS",
        review_question="Does ketone monoester supplementation alter cardiac injury biomarkers?",
        population="Adult endurance athletes",
        intervention_exposure_index_test="Ketone monoester supplementation",
        comparator_reference="Placebo or no supplementation",
        outcomes=["High sensitivity troponin", "Exercise capacity"],
        eligible_designs=["randomized controlled trials"],
        rationale="Uncertainty about physiological responses after strenuous exercise.",
        novelty_hypothesis="New trials published since an older competing review.",
        search_terms=["ketone monoester cardiac troponin", "endurance athletes exercise"],
    )


def test_provisional_dossier_has_full_pico_queries_links_and_verification_limits(tmp_path):
    with SQLiteLedger(tmp_path / "dossier.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("PROJECT1", "Cardiology"))
        candidate = question()
        candidate.status = CandidateStatus.PROVISIONAL_BACKUP
        candidate.metadata = {
            "discovery_registration_age_audit": [
                {"source": "PROSPERO", "registered_at": "2019",
                 "classification": "OLDER_REGISTRATION_UPDATE_OPPORTUNITY_TO_VERIFY"}
            ],
            "discovery_published_review_update_audit": [
                {"title": "Old competing review", "last_search_date": None,
                 "classification": "SEARCH_DATE_MISSING_MANUAL_CHECK"}
            ],
            "discovery_gate_inputs": {"overall_novelty": 0.0,
                                      "novelty_status": "NOT_ESTIMABLE"},
        }
        ledger.upsert_candidate(candidate)
        ledger.upsert_external_evidence(
            "TOPIC1", "PUBLISHED_REVIEW", "PMID-100",
            source="PubMed", title="Old competing systematic review",
            payload={
                "year": 2019, "doi": "10.1234/old",
                "url": "https://pubmed.ncbi.nlm.nih.gov/100/",
                "metadata": {"abstract": "The systematic review focused on athletes."},
            },
        )
        ledger.upsert_external_evidence(
            "TOPIC1", "REGISTRATION", "CRD420190000001",
            source="PROSPERO", title="Original registered review",
            payload={
                "year": 2019,
                "url": "https://www.crd.york.ac.uk/PROSPERO/view/CRD420190000001",
            },
        )
        ledger.upsert_external_evidence(
            "TOPIC1", "PRIMARY_STUDY", "PMID-101",
            source="PubMed",
            title="Ketone monoester in endurance athletes randomized trial NCT12345678",
            payload={"year": 2025, "doi": "10.1234/new",
                     "url": "https://pubmed.ncbi.nlm.nih.gov/101/"},
        )
        ledger.append_search_log(SearchLogRecord(
            project_id="PROJECT1", candidate_id="TOPIC1",
            source="PROSPERO", query="ketone monoester cardiac biomarkers",
            status=SourceStatus.PARTIAL, result_count=56,
            message="PROSPERO pagination incomplete",
        ))
        coverage = VerificationCoverage(
            source_statuses={"PROSPERO": SourceStatus.PARTIAL,
                             "OSF Registries": SourceStatus.ACCESS_FAILED},
            blockers=("TYPE-A: PROSPERO incomplete", "TYPE-A: OSF inaccessible"),
        )
        verification = DiscoveryCandidateResult(
            candidate_id="TOPIC1",
            ranking_score=80,
            coverage=coverage,
            evidence=DiscoveryEvidenceSnapshot(3, 1, 1, ("PubMed",)),
            pending=["TYPE-A: PROSPERO incomplete", "TYPE-A: OSF inaccessible"],
            decision="PROVISIONAL — SOURCE COVERAGE INCOMPLETE",
            candidate_status=CandidateStatus.PROVISIONAL_BACKUP,
        )
        run = DiscoveryRunResult(
            "PROJECT1", [RankingResult("TOPIC1", 80, ())],
            [verification], [], [], 3,
        )
        pkg = build_discovery_review_package(ledger, run)
        assert pkg["schema_version"] >= 2
        assert pkg["options"] == []
        assert "PROSPERO" in pkg["topic_review_prompt"]
        assert "GO / REFINE / NO-GO / UNRESOLVED" in pkg["topic_review_prompt"]
        assert "Never invent" in pkg["topic_review_prompt"]
        result = pkg["provisional_options"][0]
        assert result["rationale"] == candidate.rationale
        assert result["novelty_hypothesis"] == candidate.novelty_hypothesis
        assert result["search_terms"] == candidate.search_terms
        dossier = result["research_dossier"]
        assert dossier["qualification_label"] == "PROVISIONAL_NEEDS_VERIFICATION"
        assert dossier["scientific_question"]["population"] == "Adult endurance athletes"
        assert dossier["scientific_question"]["eligible_designs"] == ["randomized controlled trials"]
        assert dossier["evidence_search_audit"][0]["query_used"] == "ketone monoester cardiac biomarkers"
        assert dossier["evidence_search_audit"][0]["status"] == "PARTIAL"
        assert dossier["published_review_evidence"][0]["doi"] == "10.1234/old"
        assert "athletes" in dossier["published_review_evidence"][0]["source_abstract_excerpt"]
        assert dossier["registration_evidence"][0]["record_id"] == "CRD420190000001"
        assert dossier["bibliographic_counts_not_verified_eligible_studies"]["eligible_independent_studies_confirmed"] is None
        assert dossier["primary_study_screening_queue"][0]["fulltext_eligibility"] == "NOT_CHECKED"
        assert dossier["study_screening_and_trial_family_adjudication_complete"] is False
        assert dossier["registration_age_and_update_audit"][0]["registered_at"] == "2019"
        assert "TYPE-A: OSF inaccessible" in dossier["verification_and_quality"]["pending_verifications"]
        json.dumps(pkg, ensure_ascii=False)


def test_generated_but_unchecked_drafts_transfer_complete_pico_without_fake_evidence():
    a, b = question("CHECKED"), question("UNCHECKED")
    options = _unverified_topic_options([a, b], {"CHECKED"})
    assert len(options) == 1
    draft = options[0]
    assert draft["candidate_id"] == "UNCHECKED"
    assert draft["qualification_status"] == "AI_DRAFT_NOT_SOURCE_VERIFIED"
    assert draft["novelty_hypothesis"] == b.novelty_hypothesis
    assert draft["research_dossier"]["scientific_question"]["outcomes"] == [
        "High sensitivity troponin", "Exercise capacity"
    ]
    assert draft["research_dossier"]["verification_and_quality"]["source_statuses"]["PROSPERO"] == "NOT_SEARCHED"
    assert draft["research_dossier"]["primary_study_screening_queue"] == []
    assert draft["research_dossier"]["eligible_independent_studies_confirmed"] is None
    json.dumps(options)
