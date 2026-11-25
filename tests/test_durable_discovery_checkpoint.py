import json

from scimed_scout.cloud.checkpoints import audit_snapshot, restore_audit, draft_from_saved
from scimed_scout.domain import CandidateStatus, SourceStatus
from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger, SearchLogRecord
from scimed_scout.discovery.models import DiscoveryCandidateResult, DiscoveryEvidenceSnapshot
from scimed_scout.verification.coverage import VerificationCoverage


def test_roundtrip_completed_candidate_audit_restores_evidence_and_logs(tmp_path):
    with SQLiteLedger(tmp_path / "first.sqlite") as ledger:
        ledger.upsert_project(ProjectRecord("J1", "Cardiology"))
        ledger.upsert_candidate(CandidateRecord("C1", "J1", "Cardiac trial", "Cardiology",
                                               status=CandidateStatus.PROVISIONAL_BACKUP))
        ledger.upsert_external_evidence("C1", "PRIMARY_STUDY", "PMID1", source="PubMed", title="Trial")
        ledger.append_search_log(SearchLogRecord("J1", "C1", "PubMed", "heart", SourceStatus.SEARCHED_POSITIVE))
        item = DiscoveryCandidateResult("C1", 80, VerificationCoverage({"PubMed": SourceStatus.SEARCHED_POSITIVE}, ()),
            DiscoveryEvidenceSnapshot(1, 1, 1, ("PubMed",)), ["Still unresolved"], "PROVISIONAL",
            CandidateStatus.PROVISIONAL_BACKUP)
        snap = json.loads(json.dumps(audit_snapshot(ledger, item)))
    with SQLiteLedger(tmp_path / "second.sqlite") as ledger:
        ledger.upsert_project(ProjectRecord("J1", "Cardiology"))
        restored = restore_audit(ledger, snap, "J1", "C1")
        assert restored == item
        assert ledger.get_candidate("C1").status == CandidateStatus.PROVISIONAL_BACKUP
        assert ledger.list_external_evidence("C1")[0]["source_record_id"] == "PMID1"
        assert ledger.list_search_log("C1")[0].status == SourceStatus.SEARCHED_POSITIVE


def test_legacy_draft_cannot_restore_qualification():
    draft = draft_from_saved({"candidate_id":"C1","title":"Cardiac trial","status":"QUALIFIED"}, "J1")
    assert draft.status == CandidateStatus.DISCOVERED


def test_cardio_scope_distinguishes_pulmonary_and_cardiovascular_questions():
    from scimed_scout.cloud.worker import _within_specialty
    pure = CandidateRecord("C2","J1","Dual bronchodilators for COPD","Cardiology",
                           population="COPD", outcomes=["Regional ventilation"])
    mixed = CandidateRecord("C3","J1","COPD treatment and cardiovascular mortality","Pulmonology",
                            population="COPD", outcomes=["Cardiovascular mortality"])
    neuro = CandidateRecord("C4","J1","Stroke rehabilitation and mobility","Neurology",
                            population="Stroke", outcomes=["Mobility"])
    assert not _within_specialty(pure, "Cardiology")
    assert _within_specialty(mixed, "Cardiology")
    assert not _within_specialty(neuro, "Cardiology")
