from scimed_scout.discovery.models import (
    DiscoveryCandidateResult,
    DiscoveryEvidenceSnapshot,
    DiscoveryRunResult,
)
from scimed_scout.discovery.review_package import build_discovery_review_package
from scimed_scout.domain import CandidateStatus, SourceStatus
from scimed_scout.ranking import RankingResult
from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger
from scimed_scout.verification.coverage import VerificationCoverage


def test_package_contains_only_qualified_review_topics_and_states_scope(tmp_path):
    with SQLiteLedger(tmp_path / "p.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Cardiology"))
        candidate = CandidateRecord(
            "C1",
            "P1",
            "Strong review topic",
            "Cardiology",
            question_type="EFFECTIVENESS",
            review_question="Does intervention X improve outcome Y?",
            population="Adults with disease Z",
            intervention_exposure_index_test="Intervention X",
            comparator_reference="Usual care",
            outcomes=["Outcome Y"],
            eligible_designs=["randomized and non-randomized comparative studies"],
        )
        candidate.status = CandidateStatus.QUALIFIED
        ledger.upsert_candidate(candidate)

        coverage = VerificationCoverage(
            source_statuses={
                "PubMed": SourceStatus.SEARCHED_POSITIVE,
                "Europe PMC": SourceStatus.SEARCHED_POSITIVE,
                "PROSPERO": SourceStatus.SEARCHED_NEGATIVE,
                "OSF Registries": SourceStatus.MANUAL_VERIFIED,
                "ClinicalTrials.gov": SourceStatus.SEARCHED_NEGATIVE,
            },
            blockers=(),
        )
        evidence = DiscoveryEvidenceSnapshot(6, 4, 2, ("Europe PMC", "PubMed"))
        gate_result = {
            "decision": "QUALIFIED — FIRST-CHOICE REVIEW TOPIC",
            "all_discovery_gates_passed": True,
            "unresolved_type_a": [],
            "gates": [],
        }
        verification = DiscoveryCandidateResult(
            candidate_id="C1",
            ranking_score=90,
            coverage=coverage,
            evidence=evidence,
            pending=[],
            decision="QUALIFIED — FIRST-CHOICE REVIEW TOPIC",
            candidate_status=CandidateStatus.QUALIFIED,
            final_gate_result=gate_result,
        )
        run = DiscoveryRunResult(
            project_id="P1",
            ranked=[RankingResult("C1", 90, ("specific question",))],
            verified=[verification],
            final_option_candidate_ids=["C1"],
            qualified_option_candidate_ids=["C1"],
            desired_options=3,
        )

        package = build_discovery_review_package(ledger, run)
        assert package["scope"] == "REVIEW_TOPIC_DISCOVERY_ONLY"
        assert package["selection_policy"]["full_review_execution_out_of_scope"] is True
        assert package["selection_policy"]["minimum_unique_primary_study_candidates"] == 4
        assert len(package["options"]) == 1
        assert package["options"][0]["candidate_id"] == "C1"
        assert "full-text eligibility" in package["review_instructions"].lower()


def test_provisional_topics_are_visible_but_never_pretend_to_be_qualified(tmp_path):
    with SQLiteLedger(tmp_path / "provisional.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Cardiology"))
        proposed = CandidateRecord(
            "PX1", "P1", "Potential cardiology review", "Cardiology",
            question_type="DIAGNOSTIC_ACCURACY",
            review_question="Can biomarker X detect early disease Y?",
            population="Adults at risk",
            intervention_exposure_index_test="Biomarker X",
            comparator_reference="Reference test",
            outcomes=["sensitivity", "specificity"],
            eligible_designs=["diagnostic cross-sectional"],
        )
        proposed.status = CandidateStatus.PROVISIONAL_BACKUP
        ledger.upsert_candidate(proposed)
        coverage = VerificationCoverage(
            source_statuses={
                "PubMed": SourceStatus.SEARCHED_POSITIVE,
                "PROSPERO": SourceStatus.ACCESS_FAILED,
                "OSF Registries": SourceStatus.PARTIAL,
            },
            blockers=("TYPE-A: PROSPERO coverage incomplete", "TYPE-A: OSF incomplete"),
        )
        verification = DiscoveryCandidateResult(
            candidate_id="PX1",
            ranking_score=72.0,
            coverage=coverage,
            evidence=DiscoveryEvidenceSnapshot(12, 5, 1, ("PubMed",)),
            pending=["TYPE-A: PROSPERO coverage incomplete"],
            decision="PROVISIONAL - SOURCE COVERAGE INCOMPLETE",
            candidate_status=CandidateStatus.PROVISIONAL_BACKUP,
        )
        run = DiscoveryRunResult(
            project_id="P1",
            ranked=[RankingResult("PX1", 72.0, ("novel-looking question",))],
            verified=[verification],
            final_option_candidate_ids=[],
            qualified_option_candidate_ids=[],
            desired_options=3,
        )
        pkg = build_discovery_review_package(ledger, run)
        assert pkg["options"] == []
        assert pkg["provisional_options_are_not_qualified"] is True
        assert len(pkg["provisional_options"]) == 1
        choice = pkg["provisional_options"][0]
        assert choice["candidate_id"] == "PX1"
        assert choice["source_statuses"]["PROSPERO"] == "ACCESS_FAILED"
        assert choice["discovered_primary_study_candidates"] == 5
        assert choice["provisional_only"] is True



def test_provisional_export_removes_similar_af_questions_without_losing_audit(tmp_path):
    from scimed_scout.discovery.models import DiscoveryRunResult, DiscoveryCandidateResult, DiscoveryEvidenceSnapshot
    from scimed_scout.verification.coverage import VerificationCoverage

    topics = [
        "Effectiveness of adjunctive non-pulmonary vein trigger ablation versus pulmonary-vein isolation alone in persistent atrial fibrillation",
        "Adjunctive non-pulmonary vein trigger ablation versus pulmonary-vein isolation alone in persistent atrial fibrillation",
    ]
    with SQLiteLedger(tmp_path / "dedup.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Cardiology"))
        verifications = []
        ranked = []
        for i, title in enumerate(topics):
            cid = f"P{i}"
            candidate = CandidateRecord(
                cid, "P1", title, "Cardiology",
                question_type="EFFECTIVENESS",
                review_question="Does additional ablation improve persistent AF outcomes?",
                population="Adults with persistent atrial fibrillation undergoing catheter ablation",
                intervention_exposure_index_test="Adjunctive non-pulmonary vein trigger ablation plus pulmonary-vein isolation",
                comparator_reference="Pulmonary-vein isolation alone",
                outcomes=["Freedom from atrial fibrillation at 12 months", "Quality of life"],
                eligible_designs=["Randomized controlled trials"],
            )
            candidate.status = CandidateStatus.PROVISIONAL_BACKUP
            ledger.upsert_candidate(candidate)
            verifications.append(DiscoveryCandidateResult(
                candidate_id=cid, ranking_score=90-i,
                coverage=VerificationCoverage({"PROSPERO":SourceStatus.PARTIAL},("PROSPERO incomplete",)),
                evidence=DiscoveryEvidenceSnapshot(10,8,1,("PubMed",)),
                pending=["PROSPERO incomplete"],
                candidate_status=CandidateStatus.PROVISIONAL_BACKUP,
            ))
            ranked.append(RankingResult(cid,90-i,()))
        result=DiscoveryRunResult("P1",ranked,verifications,[],[],3)
        package=build_discovery_review_package(ledger,result)
        assert len(package["provisional_options"])==1
        assert package["selection_policy"]["available_options"]==0
        assert package["provisional_options"][0]["provisional_only"] is True


def test_relevant_study_examples_do_not_prioritize_unrelated_fracture_citations():
    from scimed_scout.discovery.review_package import _relevant_primary_examples
    from types import SimpleNamespace
    question = SimpleNamespace(
        intervention_exposure_index_test="Inclisiran",
        population="Adults with atherosclerotic cardiovascular disease",
        comparator_reference="High intensity statin therapy"
    )
    records=[
      {"title":"Models of Secondary Fracture Prevention","source":"Crossref"},
      {"title":"Inclisiran versus statin therapy in adults with atherosclerotic cardiovascular disease","source":"PubMed"},
      {"title":"An overview of secondary prevention strategies","source":"Crossref"},
    ]
    examples=_relevant_primary_examples(question, records)
    assert len(examples)==1
    assert examples[0]["source"]=="PubMed"


def test_primary_screening_queue_contains_newer_pico_leads_but_no_claimed_eligible_trials():
    from types import SimpleNamespace
    from scimed_scout.discovery.review_package import _primary_screening_queue
    candidate = SimpleNamespace(
        intervention_exposure_index_test="Ketone monoester supplementation",
        comparator_reference="Placebo",
        population="Endurance athletes",
    )
    records = [
        {"source":"PubMed","source_record_id":"1",
         "title":"Ketone monoester supplementation versus placebo in endurance athletes NCT01234567",
         "payload":{"year":2025,"doi":"10.1234/a","url":"https://pubmed.ncbi.nlm.nih.gov/1/",
                    "metadata":{"abstract":"Randomized crossover trial with 30 athletes"}}},
        {"source":"Europe PMC","source_record_id":"2",
         "title":"Unrelated knee osteoarthritis surgical study",
         "payload":{"year":2024,"doi":"10.1234/b","metadata":{}}},
    ]
    queue = _primary_screening_queue(
        candidate, records,
        [{"last_search_date":"January 2022"}],
    )
    assert queue[0]["registry_trial_ids"] == ["NCT01234567"]
    assert queue[0]["post_search_flag"] == "POST_SEARCH_BIBLIOGRAPHIC_LEAD"
    assert queue[0]["fulltext_eligibility"] == "NOT_CHECKED"
    assert queue[0]["trial_family_independence"] == "NOT_CONFIRMED"
    assert queue[0]["screening_decision"] == ""


def test_screening_queue_unknown_prior_search_date_does_not_infer_update():
    from types import SimpleNamespace
    from scimed_scout.discovery.review_package import _primary_screening_queue
    candidate = SimpleNamespace(
        intervention_exposure_index_test="Inclisiran",
        comparator_reference="Statins",
        population="Adults with ASCVD",
    )
    q = _primary_screening_queue(candidate, [{
        "source":"PubMed", "source_record_id":"1",
        "title":"Inclisiran trial in ASCVD",
        "payload":{"year":2025,"doi":"10.1234/x"},
    }], [{"publication_year":2018,"last_search_date":None}])
    assert q[0]["post_search_flag"] == "UNDETERMINED"
    assert q[0]["latest_documented_review_search_year"] is None
