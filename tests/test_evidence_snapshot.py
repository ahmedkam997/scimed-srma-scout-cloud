from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger
from scimed_scout.verification.evidence_snapshot import snapshot_from_ledger


def test_snapshot_counts_only_explicitly_verified_families_and_usable_outcomes(tmp_path):
    with SQLiteLedger(tmp_path / "snap.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Medicine"))
        ledger.upsert_candidate(
            CandidateRecord(
                "C1",
                "P1",
                "Topic",
                "Medicine",
                metadata={"study_audit_complete": True, "synthesis_audit_complete": True},
            )
        )
        for i in range(1, 5):
            ledger.upsert_payload(
                "study_families",
                "C1",
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
                "C1",
                f"O{i}",
                {
                    "outcome_id": f"O{i}",
                    "family_id": f"F{i}",
                    "usability_status": "VERIFIED_USABLE",
                    "principal": i <= 2,
                },
                family_id=f"F{i}",
            )

        ledger.upsert_payload(
            "study_families",
            "C1",
            "F5",
            {
                "family_id": "F5",
                "independence_verified": False,
                "eligibility_verified": True,
                "design_verified": True,
            },
        )

        snap = snapshot_from_ledger(ledger, "C1")
        assert snap.threshold_ready
        assert snap.verified_independent_studies == 4
        assert snap.verified_usable_studies == 4
        assert snap.principal_outcome_studies == 2
        assert snap.minimum_passes


def test_discovered_search_hits_do_not_become_verified_studies(tmp_path):
    with SQLiteLedger(tmp_path / "snap.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Medicine"))
        ledger.upsert_candidate(CandidateRecord("C1", "P1", "Topic", "Medicine"))
        ledger.upsert_external_evidence(
            "C1",
            "PRIMARY_STUDY",
            "PMID1",
            source="PubMed",
            title="Possible study",
            payload={"verification_status": "DISCOVERED_UNVERIFIED"},
        )
        snap = snapshot_from_ledger(ledger, "C1")
        assert snap.verified_independent_studies == 0
        assert snap.verified_usable_studies == 0
        assert not snap.threshold_ready
