"""Versioned JSON audit snapshots. Never deserialize executable objects."""
from dataclasses import asdict

from scimed_scout.domain import CandidateStatus, SourceStatus
from scimed_scout.storage import CandidateRecord, SearchLogRecord, DecisionRecord
from scimed_scout.discovery.models import DiscoveryCandidateResult, DiscoveryEvidenceSnapshot
from scimed_scout.verification.coverage import VerificationCoverage

GENERATION = "generation:v1"
AUDIT_PREFIX = "audit:v1:"


def draft_from_saved(row, project_id):
    """Old browser checkpoints contain hypotheses only, not verified state."""
    return CandidateRecord(
        candidate_id=str(row["candidate_id"]), project_id=project_id,
        title=str(row["title"]), specialty=str(row.get("specialty") or ""),
        question_type=str(row.get("question_type") or ""),
        review_question=str(row.get("review_question") or ""),
        population=str(row.get("population") or ""),
        intervention_exposure_index_test=str(row.get("intervention_exposure_index_test") or ""),
        comparator_reference=str(row.get("comparator_reference") or ""),
        outcomes=list(row.get("outcomes") or []), eligible_designs=list(row.get("eligible_designs") or []),
        rationale=str(row.get("rationale") or row.get("rationale_hypothesis") or ""),
        novelty_hypothesis=str(row.get("novelty_hypothesis") or ""),
        search_terms=list(row.get("search_terms") or row.get("candidate_search_terms") or []),
    )


def audit_snapshot(ledger, item):
    cid = item.candidate_id
    candidate = ledger.get_candidate(cid)
    return {
        "version": 1, "candidate": asdict(candidate), "result": asdict(item),
        "evidence": ledger.list_external_evidence(cid),
        "search_log": [asdict(x) for x in ledger.list_search_log(cid)],
        "decisions": [asdict(x) for x in ledger.list_decisions(cid)],
        "queries": ledger.list_queries(cid),
    }


def restore_audit(ledger, snapshot, project_id, candidate_id):
    raw = dict(snapshot["candidate"])
    data = dict(snapshot["result"])
    if (snapshot.get("version") != 1 or raw["project_id"] != project_id
            or raw["candidate_id"] != candidate_id or data["candidate_id"] != candidate_id):
        raise ValueError("Checkpoint scope/version mismatch")
    # Restore scientific status from a worker-only stored result, never a draft.
    raw["status"] = CandidateStatus(raw["status"])
    data["candidate_status"] = CandidateStatus(data["candidate_status"])
    coverage = data["coverage"]
    data["coverage"] = VerificationCoverage(
        {k: SourceStatus(v) for k, v in coverage["source_statuses"].items()},
        tuple(coverage["blockers"]), tuple(coverage.get("warnings", [])),
    )
    evidence = dict(data["evidence"])
    evidence["primary_source_names"] = tuple(evidence["primary_source_names"])
    data["evidence"] = DiscoveryEvidenceSnapshot(**evidence)
    result = DiscoveryCandidateResult(**data)
    if raw["status"] != result.candidate_status:
        raise ValueError("Checkpoint candidate status mismatch")
    ledger.upsert_candidate(CandidateRecord(**raw))
    for record in snapshot["evidence"]:
        ledger.upsert_external_evidence(candidate_id, record["evidence_type"], record["source_record_id"],
                                       source=record["source"], title=record["title"], payload=record["payload"])
    for row in snapshot["search_log"]:
        if row["candidate_id"] != candidate_id or row["project_id"] != project_id:
            raise ValueError("Search checkpoint scope mismatch")
        ledger.append_search_log(SearchLogRecord(**{**row, "status": SourceStatus(row["status"])}))
    for row in snapshot["decisions"]:
        if row["candidate_id"] != candidate_id or row["project_id"] != project_id:
            raise ValueError("Decision checkpoint scope mismatch")
        ledger.append_decision(DecisionRecord(**row))
    for row in snapshot["queries"]:
        ledger.add_query(project_id, candidate_id, row["source"], row["query"], row["purpose"])
    return result
