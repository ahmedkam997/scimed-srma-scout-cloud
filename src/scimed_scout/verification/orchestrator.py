from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from scimed_scout.domain import CandidateStatus, SourceStatus
from scimed_scout.evidence import MIN_STUDIES
from scimed_scout.gates import final_decision
from scimed_scout.ranking import CandidateRankingService, RankingResult
from scimed_scout.sources.base import SearchRecord, SourceClient
from scimed_scout.storage import DecisionRecord, SearchLogRecord, SQLiteLedger

from .coverage import VerificationCoverage, evaluate_coverage
from .evidence_snapshot import LedgerEvidenceSnapshot, snapshot_from_ledger
from .policy import VerificationPolicy, policy_for_question_type
from .queries import SearchPlan, build_search_plan


REQUIRED_GATE_INPUTS = {
    "design_framework_verified",
    "meaningful_synthesis",
    "clinical_question_novelty",
    "overall_novelty",
    "fatal_redundancy",
    "question_framework_coherent",
    "feasibility",
    "fatal_methodological_flaw",
    "clinical_importance",
    "publication_potential",
    "new_information_gain",
    "publication_oriented_score",
    "editorial_grade",
}


@dataclass(slots=True)
class CandidateVerificationResult:
    candidate_id: str
    ranking_score: float
    coverage: VerificationCoverage
    evidence: LedgerEvidenceSnapshot
    pending: list[str] = field(default_factory=list)
    decision: str = "PENDING"
    candidate_status: CandidateStatus = CandidateStatus.DEEP_VERIFYING
    final_gate_result: dict[str, Any] | None = None


@dataclass(slots=True)
class SequentialVerificationResult:
    project_id: str
    ranked: list[RankingResult]
    verified: list[CandidateVerificationResult]
    final_option_candidate_ids: list[str] = field(default_factory=list)
    qualified_option_candidate_ids: list[str] = field(default_factory=list)
    desired_options: int = 3


class SequentialDeepVerifier:
    def __init__(
        self,
        ledger: SQLiteLedger,
        clients: list[SourceClient],
        evidence_analysis_service=None,
        study_verification_bridge=None,
        synthesis_verification_bridge=None,
    ):
        self.ledger = ledger
        self.clients = {client.name: client for client in clients}
        self.evidence_analysis_service = evidence_analysis_service
        self.study_verification_bridge = study_verification_bridge
        self.synthesis_verification_bridge = synthesis_verification_bridge

    def run(
        self,
        project_id: str,
        *,
        min_verify: int = 3,
        max_verify: int = 10,
        final_options: int = 3,
        limit_per_query: int = 20,
    ) -> SequentialVerificationResult:
        if min_verify < 1 or max_verify < min_verify:
            raise ValueError("Require 1 <= min_verify <= max_verify")
        if final_options < 2 or final_options > max_verify:
            raise ValueError("Require 2 <= final_options <= max_verify")

        project = self.ledger.get_project(project_id)
        if project is None:
            raise ValueError(f"Project not found: {project_id}")

        ranking = CandidateRankingService(self.ledger)
        ranked = ranking.rank_project(project_id, top_n=max_verify)
        self.ledger.update_checkpoint(
            project_id,
            stage="RANKING",
            progress=20,
            message=f"Ranked {len(ranked)} candidates; up to {max_verify} selected for sequential verification",
        )

        selected = ranked[:max_verify]
        results: list[CandidateVerificationResult] = []
        qualified_ids: list[str] = []

        for index, ranked_item in enumerate(selected, start=1):
            candidate = self.ledger.get_candidate(ranked_item.candidate_id)
            if candidate is None:
                continue

            self.ledger.set_candidate_status(candidate.candidate_id, CandidateStatus.DEEP_VERIFYING)
            self.ledger.update_checkpoint(
                project_id,
                stage="DEEP_VERIFY",
                progress=min(85, 20 + int(60 * index / max(1, len(selected)))),
                message=f"Deep verifying candidate {index}/{len(selected)}: {candidate.title}",
            )

            result = self.verify_candidate(
                candidate.candidate_id,
                ranking_score=ranked_item.score,
                limit_per_query=limit_per_query,
            )
            results.append(result)

            if result.candidate_status == CandidateStatus.QUALIFIED:
                qualified_ids.append(result.candidate_id)

            # Verify at least the requested minimum. Stop early only after enough
            # independently qualified final-review options have been assembled.
            if index >= min_verify and len(qualified_ids) >= final_options:
                break

        # Strict final shortlist: only fully qualified, first-choice-eligible
        # candidates are allowed. Pending/provisional candidates are never
        # backfilled into the final list.
        final_ids = list(qualified_ids[:final_options])

        self.ledger.update_checkpoint(
            project_id,
            stage="EXPORT" if final_ids else "DEEP_VERIFY",
            progress=92 if final_ids else 75,
            message=(
                f"Prepared {len(final_ids)} fully qualified first-choice-eligible options "
                f"for ChatGPT comparison; requested {final_options}"
                if final_ids
                else "No fully qualified first-choice-eligible option is available for final review"
            ),
        )

        return SequentialVerificationResult(
            project_id=project_id,
            ranked=ranked,
            verified=results,
            final_option_candidate_ids=final_ids,
            qualified_option_candidate_ids=qualified_ids,
            desired_options=final_options,
        )

    def verify_candidate(
        self,
        candidate_id: str,
        *,
        ranking_score: float = 0.0,
        limit_per_query: int = 20,
    ) -> CandidateVerificationResult:
        candidate = self.ledger.get_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate not found: {candidate_id}")

        policy = policy_for_question_type(candidate.question_type)
        plan = build_search_plan(candidate)

        self._search_sources(
            candidate,
            policy.literature_sources,
            plan.review_queries,
            evidence_type="PUBLISHED_REVIEW",
            purpose="published-review overlap",
            limit_per_query=limit_per_query,
        )
        self._search_sources(
            candidate,
            policy.literature_sources,
            plan.primary_queries,
            evidence_type="PRIMARY_STUDY",
            purpose="primary-study discovery",
            limit_per_query=limit_per_query,
        )
        self._search_sources(
            candidate,
            policy.registry_sources,
            plan.registry_queries,
            evidence_type="REGISTRATION",
            purpose="review/protocol registration overlap",
            limit_per_query=limit_per_query,
        )
        self._search_sources(
            candidate,
            policy.pipeline_sources,
            plan.pipeline_queries,
            evidence_type="ONGOING_STUDY",
            purpose="ongoing/prospective study pipeline",
            limit_per_query=limit_per_query,
        )

        analysis_summary = None
        if self.evidence_analysis_service is not None:
            analysis_summary = self.evidence_analysis_service.analyze_candidate(candidate_id)
            candidate = self.ledger.get_candidate(candidate_id) or candidate

        study_verification_summary = None
        if self.study_verification_bridge is not None:
            study_verification_summary = self.study_verification_bridge.run(candidate_id)
            candidate = self.ledger.get_candidate(candidate_id) or candidate

        synthesis_verification_summary = None
        if self.synthesis_verification_bridge is not None:
            synthesis_verification_summary = self.synthesis_verification_bridge.run(candidate_id)
            candidate = self.ledger.get_candidate(candidate_id) or candidate

        logs = self.ledger.list_search_log(candidate_id)
        coverage = evaluate_coverage(logs, policy)
        evidence = snapshot_from_ledger(self.ledger, candidate_id)
        pending = list(coverage.blockers)

        published_reviews = self.ledger.list_external_evidence(candidate_id, "PUBLISHED_REVIEW")
        registrations = self.ledger.list_external_evidence(candidate_id, "REGISTRATION")
        ongoing = self.ledger.list_external_evidence(candidate_id, "ONGOING_STUDY")

        meta = candidate.metadata or {}
        if published_reviews and not bool(meta.get("competitor_assessment_complete")):
            pending.append(
                "TYPE-A: published-review hits require semantic/clinical overlap assessment before redundancy can be excluded"
            )
        if registrations and not bool(meta.get("registration_assessment_complete")):
            pending.append(
                "TYPE-A: registry hits require overlap assessment before novelty clearance"
            )
        material_registration_overlap_ids = list(meta.get("material_registration_overlap_ids") or [])
        if material_registration_overlap_ids and not bool(meta.get("material_registration_overlap_resolved")):
            pending.append(
                "TYPE-A: materially overlapping review registration(s) require resolution: "
                + ", ".join(material_registration_overlap_ids)
            )
        if policy.require_pipeline_source and ongoing and not bool(meta.get("pipeline_assessment_complete")):
            pending.append(
                "TYPE-A: ongoing-study hits require pipeline/new-information assessment"
            )

        if bool(meta.get("family_uncertainty_decision_changing")):
            pending.append(
                "TYPE-A: unresolved publication/population overlap can reduce the conservative independent-study count below 4"
            )
        if int(meta.get("study_records_needing_review") or 0) > 0:
            pending.append(
                f"TYPE-A: {int(meta.get('study_records_needing_review') or 0)} study record(s) still require eligibility/design verification"
            )
        if not evidence.study_audit_complete:
            pending.append("TYPE-A: study-family eligibility/independence audit is incomplete")
        if bool(meta.get("usable_family_uncertainty_decision_changing")):
            pending.append(
                "TYPE-A: unresolved family overlap can reduce the conservative synthesis-usable count below 4"
            )
        if not evidence.synthesis_audit_complete:
            pending.append("TYPE-A: synthesis-usability audit is incomplete")

        decision = "PENDING"
        status = CandidateStatus.DEEP_VERIFYING
        final_gate_result: dict[str, Any] | None = None

        if evidence.threshold_ready and (
            evidence.verified_independent_studies < MIN_STUDIES
            or evidence.verified_usable_studies < MIN_STUDIES
        ):
            decision = "REJECT — INSUFFICIENT VERIFIED EVIDENCE"
            status = CandidateStatus.REJECTED
        elif coverage.blockers:
            decision = "PROVISIONAL BACKUP — SOURCE COVERAGE INCOMPLETE"
            status = CandidateStatus.PROVISIONAL_BACKUP
        else:
            gate_inputs = dict(meta.get("gate_inputs") or {})
            missing_gate_inputs = sorted(REQUIRED_GATE_INPUTS - set(gate_inputs))
            if missing_gate_inputs:
                pending.append("Pending locked-gate inputs: " + ", ".join(missing_gate_inputs))
            elif not pending:
                if bool(meta.get("competitor_assessment_complete")) and "semantic_fatal_redundancy" in meta:
                    gate_inputs["fatal_redundancy"] = bool(meta.get("semantic_fatal_redundancy"))
                gate_inputs["verified_independent_studies"] = evidence.verified_independent_studies
                gate_inputs["verified_usable_studies"] = evidence.verified_usable_studies
                gate_inputs["principal_outcome_studies"] = evidence.principal_outcome_studies
                gate_inputs["unresolved_type_a"] = []
                required_source_names = set(policy.literature_sources + policy.registry_sources)
                if policy.require_pipeline_source:
                    required_source_names.update(policy.pipeline_sources)
                gate_inputs["sources"] = [
                    {"source": source, "status": status_value.value}
                    for source, status_value in coverage.source_statuses.items()
                    if source in required_source_names
                ]
                final_gate_result = final_decision(gate_inputs)
                decision = final_gate_result["decision"]
                status = (
                    CandidateStatus.QUALIFIED
                    if decision == "QUALIFIED — FIRST-CHOICE ELIGIBLE"
                    else CandidateStatus.REJECTED
                )

        if pending and status == CandidateStatus.DEEP_VERIFYING:
            decision = "PENDING — DEEP VERIFICATION INCOMPLETE"

        self.ledger.set_candidate_status(candidate_id, status)
        self._append_decision(
            candidate,
            decision=decision,
            stage="DEEP_VERIFY",
            reason="; ".join(pending),
            payload={
                "ranking_score": ranking_score,
                "coverage": {
                    "source_statuses": {k: v.value for k, v in coverage.source_statuses.items()},
                    "blockers": list(coverage.blockers),
                    "warnings": list(coverage.warnings),
                },
                "evidence": asdict(evidence),
                "published_review_hits": len(published_reviews),
                "registration_hits": len(registrations),
                "ongoing_study_hits": len(ongoing),
                "evidence_analysis_summary": asdict(analysis_summary) if analysis_summary is not None else None,
                "auto_study_extraction": {
                    "complete": bool(meta.get("study_auto_extraction_complete")),
                    "eligible": int(meta.get("auto_eligible_studies") or 0),
                    "ineligible": int(meta.get("auto_ineligible_studies") or 0),
                    "uncertain": int(meta.get("auto_uncertain_studies") or 0),
                    "counts_as_verified_evidence": False,
                },
                "study_verification_summary": asdict(study_verification_summary) if study_verification_summary is not None else None,
                "synthesis_verification_summary": asdict(synthesis_verification_summary) if synthesis_verification_summary is not None else None,
                "final_gate_result": final_gate_result,
            },
        )

        return CandidateVerificationResult(
            candidate_id=candidate_id,
            ranking_score=ranking_score,
            coverage=coverage,
            evidence=evidence,
            pending=pending,
            decision=decision,
            candidate_status=status,
            final_gate_result=final_gate_result,
        )

    def _search_sources(
        self,
        candidate,
        source_names: tuple[str, ...],
        queries: tuple[str, ...],
        *,
        evidence_type: str,
        purpose: str,
        limit_per_query: int,
    ) -> None:
        for source_name in source_names:
            client = self.clients.get(source_name)
            if client is None:
                self.ledger.append_search_log(
                    SearchLogRecord(
                        project_id=candidate.project_id,
                        candidate_id=candidate.candidate_id,
                        source=source_name,
                        query="",
                        status=SourceStatus.NOT_SEARCHED,
                        message="No configured source client",
                    )
                )
                continue

            for query in queries:
                self.ledger.add_query(candidate.project_id, candidate.candidate_id, source_name, query, purpose)
                result = client.search(query, limit=limit_per_query)
                self.ledger.append_search_log(
                    SearchLogRecord(
                        project_id=candidate.project_id,
                        candidate_id=candidate.candidate_id,
                        source=source_name,
                        query=query,
                        status=result.status,
                        result_count=result.total_count,
                        message=result.message,
                    )
                )
                for record in result.records:
                    self._store_record(candidate.candidate_id, evidence_type, record, query, purpose)

    def _store_record(
        self,
        candidate_id: str,
        evidence_type: str,
        record: SearchRecord,
        query: str,
        purpose: str,
    ) -> None:
        existing = next(
            (
                item
                for item in self.ledger.list_external_evidence(candidate_id, evidence_type)
                if str(item.get("source_record_id") or "") == str(record.record_id)
            ),
            None,
        )
        previous = dict((existing or {}).get("payload") or {})
        previous_metadata = previous.get("metadata") if isinstance(previous.get("metadata"), dict) else {}
        new_metadata = record.metadata if isinstance(record.metadata, dict) else {}
        verification_status = str(previous.get("verification_status") or "DISCOVERED_UNVERIFIED")

        merged_payload = {
            **previous,
            "url": record.url or previous.get("url", ""),
            "year": record.year if record.year is not None else previous.get("year"),
            "doi": record.doi or previous.get("doi", ""),
            "query": query,
            "purpose": purpose,
            "verification_status": verification_status,
            "metadata": {**previous_metadata, **new_metadata},
        }
        self.ledger.upsert_external_evidence(
            candidate_id,
            evidence_type,
            record.record_id,
            source=record.source or str((existing or {}).get("source") or ""),
            title=record.title or str((existing or {}).get("title") or ""),
            payload=merged_payload,
        )

    def _append_decision(self, candidate, *, decision: str, stage: str, reason: str, payload: dict[str, Any]) -> None:
        sequence = len(self.ledger.list_decisions(candidate.candidate_id)) + 1
        decision_id = f"{candidate.candidate_id}-{stage}-{sequence:04d}"
        self.ledger.append_decision(
            DecisionRecord(
                decision_id=decision_id,
                project_id=candidate.project_id,
                candidate_id=candidate.candidate_id,
                decision=decision,
                stage=stage,
                reason=reason,
                payload=payload,
            )
        )
