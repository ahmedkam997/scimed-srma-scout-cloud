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

    possible_links = list(meta.get("family_possible_links_detail") or [])
    study_to_family = {
        str(study_id): str(item.get("family_id") or "")
        for item in families
        for study_id in (item.get("study_ids") or [])
        if str(item.get("family_id") or "")
    }

    conservative_verified = _conservative_family_count(
        verified_family_ids, possible_links, study_to_family
    )
    conservative_usable = _conservative_family_count(
        usable_family_ids, possible_links, study_to_family
    )
    conservative_principal = _conservative_family_count(
        principal_ids, possible_links, study_to_family
    )

    return LedgerEvidenceSnapshot(
        study_audit_complete=study_audit_complete,
        synthesis_audit_complete=synthesis_audit_complete,
        verified_independent_studies=conservative_verified,
        verified_usable_studies=conservative_usable,
        principal_outcome_studies=conservative_principal,
    )


def _conservative_family_count(
    family_ids: set[str],
    possible_links: list[dict],
    study_to_family: dict[str, str],
) -> int:
    ids = {x for x in family_ids if x}
    if not ids:
        return 0
    parent = {x: x for x in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for link in possible_links:
        a = study_to_family.get(str(link.get("study_a") or ""))
        b = study_to_family.get(str(link.get("study_b") or ""))
        if a in ids and b in ids and a != b:
            union(a, b)

    return len({find(x) for x in ids})
