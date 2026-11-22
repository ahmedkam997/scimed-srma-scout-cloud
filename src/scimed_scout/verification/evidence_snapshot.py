from __future__ import annotations

from dataclasses import dataclass

from scimed_scout.evidence import MIN_STUDIES
from scimed_scout.storage import SQLiteLedger


@dataclass(frozen=True, slots=True)
class LedgerEvidenceSnapshot:
    study_audit_complete: bool
    synthesis_audit_complete: bool
    verified_independent_studies: int
    verified_usable_studies: int
    principal_outcome_studies: int

    @property
    def threshold_ready(self) -> bool:
        return self.study_audit_complete and self.synthesis_audit_complete

    @property
    def minimum_passes(self) -> bool:
        return (
            self.threshold_ready
            and self.verified_independent_studies >= MIN_STUDIES
            and self.verified_usable_studies >= MIN_STUDIES
        )


def snapshot_from_ledger(ledger: SQLiteLedger, candidate_id: str) -> LedgerEvidenceSnapshot:
    candidate = ledger.get_candidate(candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate not found: {candidate_id}")

    meta = candidate.metadata or {}
    study_audit_complete = bool(meta.get("study_audit_complete"))
    synthesis_audit_complete = bool(meta.get("synthesis_audit_complete"))

    families = ledger.list_payloads("study_families", candidate_id)
    outcomes = ledger.list_payloads("outcomes", candidate_id)

    verified_family_ids = {
        str(item.get("family_id") or "")
        for item in families
        if bool(item.get("independence_verified"))
        and bool(item.get("eligibility_verified"))
        and bool(item.get("design_verified"))
        and str(item.get("family_id") or "")
    }

    usable_family_ids = {
        str(item.get("family_id") or "")
        for item in outcomes
        if str(item.get("family_id") or "") in verified_family_ids
        and str(item.get("usability_status") or "").upper() == "VERIFIED_USABLE"
    }
    principal_ids = {
        str(item.get("family_id") or "")
        for item in outcomes
        if str(item.get("family_id") or "") in verified_family_ids
        and str(item.get("usability_status") or "").upper() == "VERIFIED_USABLE"
        and bool(item.get("principal"))
    }

    return LedgerEvidenceSnapshot(
        study_audit_complete=study_audit_complete,
        synthesis_audit_complete=synthesis_audit_complete,
        verified_independent_studies=len(verified_family_ids),
        verified_usable_studies=len(usable_family_ids),
        principal_outcome_studies=len(principal_ids),
    )
