from scimed_scout.domain import CandidateStatus, SourceStatus
from scimed_scout.sources.base import SearchRecord, SearchResult
from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger
from scimed_scout.verification import SequentialDeepVerifier


class FakeSource:
    def __init__(self, name, status=SourceStatus.SEARCHED_NEGATIVE, records=None):
        self.name = name
        self.status = status
        self.records = records or []

    def search(self, query, *, limit=20):
        return SearchResult(
            source=self.name,
            query=query,
            status=self.status,
            records=list(self.records),
            total_count=len(self.records) if self.status == SourceStatus.SEARCHED_POSITIVE else 0,
        )


def clients(*, prospero=SourceStatus.SEARCHED_NEGATIVE, osf=SourceStatus.MANUAL_VERIFIED, pipeline=SourceStatus.ACCESS_FAILED):
    names = ["PubMed", "Europe PMC", "OpenAlex", "Crossref", "Semantic Scholar"]
    result = [FakeSource(name) for name in names]
    result += [
        FakeSource("PROSPERO", prospero),
        FakeSource("OSF Registries", osf),
        FakeSource("ClinicalTrials.gov", pipeline),
    ]
    return result


def passing_gate_inputs():
    return {
        "design_framework_verified": True,
        "meaningful_synthesis": True,
        "clinical_question_novelty": 4,
        "overall_novelty": 4,
        "fatal_redundancy": False,
        "question_framework_coherent": True,
        "feasibility": "HIGH",
        "fatal_methodological_flaw": False,
        "clinical_importance": 5,
        "publication_potential": 5,
        "new_information_gain": 4,
        "publication_oriented_score": 85,
        "editorial_grade": "B",
    }


def candidate(cid, title, complete=True):
    metadata = {"gate_inputs": passing_gate_inputs()}
    if complete:
        metadata.update({"study_audit_complete": True, "synthesis_audit_complete": True})
    return CandidateRecord(
        candidate_id=cid,
        project_id="P1",
        title=title,
        specialty="Radiology",
        question_type="DIAGNOSTIC_ACCURACY",
        review_question=f"What is the diagnostic accuracy of {title}?",
        population="Adults with suspected disease",
        intervention_exposure_index_test=title,
        comparator_reference="Reference standard",
        outcomes=["sensitivity", "specificity"],
        eligible_designs=["diagnostic accuracy"],
        rationale="Clinically important diagnostic uncertainty",
        novelty_hypothesis="Current evidence may not synthesize this test generation",
        search_terms=[title, "diagnostic accuracy", "disease"],
        metadata=metadata,
    )


def add_four_verified(ledger, cid):
    for i in range(1, 5):
        ledger.upsert_payload(
            "study_families",
            cid,
            f"F{i}",
            {
                "family_id": f"F{i}",
                "independence_verified": True,
                "eligibility_verified": True,
                "design_verified": True,
            },
        )
        ledger.upsert_payload(
            "outcomes",
            cid,
            f"O{i}",
            {
                "outcome_id": f"O{i}",
                "family_id": f"F{i}",
                "usability_status": "VERIFIED_USABLE",
                "principal": True,
            },
            family_id=f"F{i}",
        )


def test_sequential_verifier_returns_multiple_final_options_for_chatgpt(tmp_path):
    with SQLiteLedger(tmp_path / "seq.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        c1 = candidate("C1", "MRI sign A")
        c2 = candidate("C2", "CT sign B")
        c3 = candidate("C3", "Ultrasound sign C")
        c2.search_terms = ["CT sign B"]
        c3.rationale = ""
        c3.novelty_hypothesis = ""
        for c in (c1, c2, c3):
            ledger.upsert_candidate(c)
            add_four_verified(ledger, c.candidate_id)

        result = SequentialDeepVerifier(ledger, clients()).run("P1", min_verify=3, max_verify=3, final_options=3)

        assert len(result.verified) == 3
        assert result.final_option_candidate_ids == ["C1", "C2", "C3"]
        assert result.qualified_option_candidate_ids == ["C1", "C2", "C3"]
        assert ledger.get_candidate("C1").status == CandidateStatus.QUALIFIED
        assert ledger.get_candidate("C2").status == CandidateStatus.QUALIFIED
        assert ledger.get_candidate("C3").status == CandidateStatus.QUALIFIED
        assert ledger.get_project("P1").stage == "EXPORT"
        assert ledger.list_search_log("C1")
        assert ledger.list_queries("C1")
        assert ledger.list_decisions("C1")[-1].decision == "QUALIFIED — FIRST-CHOICE ELIGIBLE"
        assert ledger.list_decisions("C2")[-1].decision == "QUALIFIED — FIRST-CHOICE ELIGIBLE"


def test_source_failure_yields_provisional_backup_not_false_clearance(tmp_path):
    with SQLiteLedger(tmp_path / "seq.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        c = candidate("C1", "MRI sign A")
        ledger.upsert_candidate(c)
        add_four_verified(ledger, "C1")

        result = SequentialDeepVerifier(
            ledger,
            clients(prospero=SourceStatus.ACCESS_FAILED),
        ).verify_candidate("C1", ranking_score=90)

        assert result.candidate_status == CandidateStatus.PROVISIONAL_BACKUP
        assert "SOURCE COVERAGE INCOMPLETE" in result.decision
        assert any("PROSPERO" in blocker for blocker in result.coverage.blockers)
        assert result.final_gate_result is None


def test_incomplete_study_and_synthesis_audits_remain_pending(tmp_path):
    with SQLiteLedger(tmp_path / "seq.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        c = candidate("C1", "MRI sign A", complete=False)
        ledger.upsert_candidate(c)

        result = SequentialDeepVerifier(ledger, clients()).verify_candidate("C1")

        assert result.candidate_status == CandidateStatus.DEEP_VERIFYING
        assert result.decision == "PENDING — DEEP VERIFICATION INCOMPLETE"
        assert any("study-family" in item for item in result.pending)
        assert any("synthesis-usability" in item for item in result.pending)


def test_positive_review_hits_require_overlap_assessment(tmp_path):
    review_record = SearchRecord("PubMed", "R1", "Potential prior systematic review")
    fake_clients = clients()
    fake_clients = [
        FakeSource("PubMed", SourceStatus.SEARCHED_POSITIVE, [review_record])
        if x.name == "PubMed" else x
        for x in fake_clients
    ]

    with SQLiteLedger(tmp_path / "seq.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        c = candidate("C1", "MRI sign A")
        ledger.upsert_candidate(c)
        add_four_verified(ledger, "C1")

        result = SequentialDeepVerifier(ledger, fake_clients).verify_candidate("C1")
        assert result.candidate_status == CandidateStatus.DEEP_VERIFYING
        assert any("published-review hits" in item for item in result.pending)
        reviews = ledger.list_external_evidence("C1", "PUBLISHED_REVIEW")
        assert reviews
        assert reviews[0]["payload"]["verification_status"] == "DISCOVERED_UNVERIFIED"


def test_final_shortlist_never_backfills_pending_or_provisional_candidates(tmp_path):
    with SQLiteLedger(tmp_path / "strict.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))

        c1 = candidate("C1", "MRI sign A")
        c2 = candidate("C2", "CT sign B")
        c3 = candidate("C3", "Ultrasound sign C", complete=False)

        for c in (c1, c2, c3):
            ledger.upsert_candidate(c)
        add_four_verified(ledger, "C1")
        add_four_verified(ledger, "C2")

        result = SequentialDeepVerifier(ledger, clients()).run(
            "P1",
            min_verify=3,
            max_verify=3,
            final_options=3,
        )

        assert result.qualified_option_candidate_ids == ["C1", "C2"]
        assert result.final_option_candidate_ids == ["C1", "C2"]
        assert "C3" not in result.final_option_candidate_ids
        assert ledger.get_candidate("C3").status == CandidateStatus.DEEP_VERIFYING


def test_repeated_search_preserves_full_text_and_existing_assessments(tmp_path):
    with SQLiteLedger(tmp_path / "preserve.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology"))
        ledger.upsert_candidate(CandidateRecord("C1", "P1", "Topic", "Radiology"))
        ledger.upsert_external_evidence(
            "C1",
            "PRIMARY_STUDY",
            "S1",
            source="PubMed",
            title="Old title",
            payload={
                "full_text": "Important full text content",
                "supplement_text": "Supplement content",
                "semantic_assessment": {"overall_overlap": "LOW"},
                "verification_status": "AUTO_EXTRACTED",
                "metadata": {"abstract": "Old abstract"},
            },
        )

        verifier = SequentialDeepVerifier(ledger, [])
        verifier._store_record(
            "C1",
            "PRIMARY_STUDY",
            SearchRecord(
                source="PubMed",
                record_id="S1",
                title="Updated title",
                url="https://example.invalid/S1",
                year=2026,
                doi="10.1000/test",
                metadata={"abstract": "Updated abstract", "journal": "Journal X"},
            ),
            "updated query",
            "primary-study discovery",
        )

        stored = ledger.list_external_evidence("C1", "PRIMARY_STUDY")[0]
        payload = stored["payload"]
        assert payload["full_text"] == "Important full text content"
        assert payload["supplement_text"] == "Supplement content"
        assert payload["semantic_assessment"]["overall_overlap"] == "LOW"
        assert payload["verification_status"] == "AUTO_EXTRACTED"
        assert payload["metadata"]["abstract"] == "Updated abstract"
        assert payload["metadata"]["journal"] == "Journal X"
