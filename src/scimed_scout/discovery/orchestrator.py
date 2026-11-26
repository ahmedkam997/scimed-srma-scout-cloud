from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from typing import Any, Callable

from scimed_scout.domain import CandidateStatus, SourceStatus
from scimed_scout.ranking import CandidateRankingService, RankingResult
from scimed_scout.sources.base import SearchRecord, SearchResult, SourceClient
from scimed_scout.storage import DecisionRecord, SearchLogRecord, SQLiteLedger
from scimed_scout.verification.coverage import DEFINITIVE, evaluate_coverage
from scimed_scout.verification.policy import policy_for_question_type
from scimed_scout.verification.queries import build_search_plan

from .constants import MIN_DISCOVERY_STUDIES
from .candidate_preflight import FocusedEvidencePreflight
from .query_optimizer import optimized_queries, sample_quality, VERSION as QUERY_OPTIMIZER_VERSION
from .adaptive_search import collect as collect_supplementary
from .adaptive_retrieval import collect as collect_adaptive_retrieval
from .registration_enrichment import enrich_ledger
from .evidence import discovery_evidence_snapshot
from .pico_matching import assess_pico
from .review_opportunity import assess_review_opportunity
from .evidence_classification import (
    classify_review_search_hit, classify_registration_search_hit,
    review_intervention_citation_signal,
)
from .gates import final_discovery_decision
from .models import DiscoveryCandidateResult, DiscoveryRunResult
from .novelty import DiscoveryNoveltyService
from .scoring import DiscoveryScoringService
from .topic_diversity import select_diverse_ranked


class ReviewDiscoveryOrchestrator:
    """Discovery-only workflow. No full-text review, extraction, or meta-analysis."""

    def __init__(
        self,
        ledger: SQLiteLedger,
        clients: list[SourceClient],
        *,
        novelty_service: DiscoveryNoveltyService | None = None,
        scoring_service: DiscoveryScoringService | None = None,
        progress_callback: Callable[[int, str, str], None] | None = None,
        cancellation_check: Callable[[], None] | None = None,
        evidence_preflight: FocusedEvidencePreflight | None = None,
        candidate_checkpoint: Callable[[DiscoveryCandidateResult], None] | None = None,
        resumed_results: list[DiscoveryCandidateResult] | None = None,
        require_pico_signals: bool = False,
        optimize_literature_queries: bool = False,
        adaptive_search: bool = False,
        adaptive_retrieval: bool = False,
        adaptive_recovery_only: bool = False,
        strict_rct_minimum: int = 0,
    ):
        self.ledger = ledger
        self.clients = {client.name: client for client in clients}
        self.novelty_service = novelty_service
        self.scoring_service = scoring_service
        self.progress_callback = progress_callback
        self.cancellation_check = cancellation_check
        self.evidence_preflight = evidence_preflight
        self.candidate_checkpoint = candidate_checkpoint
        self.resumed_results = list(resumed_results or [])
        self.require_pico_signals = require_pico_signals
        self.optimize_literature_queries = optimize_literature_queries
        self.adaptive_search = adaptive_search
        self.adaptive_retrieval = adaptive_retrieval
        self.adaptive_recovery_only = adaptive_recovery_only
        self.strict_rct_minimum = max(0,int(strict_rct_minimum))

    def run(
        self,
        project_id: str,
        *,
        min_verify: int = 3,
        max_verify: int = 10,
        final_options: int = 3,
        limit_per_query: int = 20,
        adaptive_extra: int = 0,
        recovery_pass: bool = False,
    ) -> DiscoveryRunResult:
        if min_verify < 1 or max_verify < min_verify:
            raise ValueError("Require 1 <= min_verify <= max_verify")
        if final_options < 2 or final_options > max_verify:
            raise ValueError("Require 2 <= final_options <= max_verify")
        if self.ledger.get_project(project_id) is None:
            raise ValueError(f"Project not found: {project_id}")

        self._check_cancellation()
        preflight_summary = {}
        if self.evidence_preflight is not None:
            self._progress(
                18, "EVIDENCE_PREFLIGHT",
                "Checking focused PubMed bibliographic title signals for topic priority",
            )
            preflight_summary = self.evidence_preflight.annotate(
                self.ledger, project_id, cancellation_check=self._check_cancellation,
            )
        # Select distinct PICOs from ALL ranked proposals. The initial deep
        # verification limit is not an index cutoff on the raw topic list.
        extra_budget = max(0, min(4, int(adaptive_extra)))
        total_budget = max_verify + extra_budget
        ranked = CandidateRankingService(self.ledger).rank_project(
            project_id, top_n=total_budget, return_all=True,
        )
        by_id = {c.candidate_id: c for c in self.ledger.list_candidates(project_id)}
        # Previously completed candidates are fixed members of this audit;
        # spend the remaining verification budget on new distinct questions.
        resumed_ids = {item.candidate_id for item in self.resumed_results}
        resume_rank = [RankingResult(item.candidate_id, item.ranking_score, ("Restored durable audit",))
                       for item in self.resumed_results]
        ranked = resume_rank + [item for item in ranked if item.candidate_id not in resumed_ids]
        diverse, skipped_duplicates = select_diverse_ranked(ranked, by_id, limit=total_budget)
        diverse = [item for item in diverse if item.candidate_id not in resumed_ids]
        ranking_message = (
            f"Ranked {len(ranked)} candidates using title-signal priority, "
            f"selected up to {len(diverse)} distinct PICOs "
            f"({max_verify} initial, {extra_budget} conditional backups); "
            f"skipped {len(skipped_duplicates)} near-duplicate questions"
        )
        self.ledger.update_checkpoint(project_id, stage="DISCOVERY_RANKING", progress=20, message=ranking_message)
        self._progress(20, "DISCOVERY_RANKING", ranking_message)

        results: list[DiscoveryCandidateResult] = list(self.resumed_results)
        # A saved qualification from an older gate version must never bypass
        # the new evidence checks. Keep the audit, but require reassessment.
        if self.require_pico_signals:
            for item in results:
                if not item.evidence.pico_audit:
                    old_candidate = self.ledger.get_candidate(item.candidate_id)
                    if old_candidate is not None:
                        audit, _ = assess_pico(old_candidate, self.ledger.list_external_evidence(item.candidate_id, "PRIMARY_STUDY"))
                        item.evidence = replace(item.evidence, pico_audit=audit)
                    if item.candidate_status == CandidateStatus.QUALIFIED:
                        item.candidate_status = CandidateStatus.PROVISIONAL_BACKUP
                        item.decision = "PROVISIONAL — LEGACY QUALIFICATION REQUIRES PICO REASSESSMENT"
                        item.pending.append("TYPE-A: previous gate did not assess PICO/design-supported evidence")
                        item.final_gate_result = None
        qualified: list[str] = [item.candidate_id for item in results
                                if item.candidate_status == CandidateStatus.QUALIFIED]
        for item in results:
            self.ledger.set_candidate_status(item.candidate_id, item.candidate_status)
        adaptive_skipped = ""
        for index, ranked_item in enumerate(diverse, len(results) + 1):
            if index > total_budget or (len(results) >= min_verify and len(qualified) >= final_options):
                break
            self._check_cancellation()
            if index > max_verify:
                adaptive_skipped = self._adaptive_skip_reason(results)
                if adaptive_skipped:
                    break
            candidate = self.ledger.get_candidate(ranked_item.candidate_id)
            if candidate is None:
                continue
            self.ledger.set_candidate_status(candidate.candidate_id, CandidateStatus.DEEP_VERIFYING)
            candidate_progress = min(90, 20 + int(65 * index / max(1, len(diverse) + len(self.resumed_results))))
            candidate_message = f"Checking review topic {index}: {candidate.title}"
            self.ledger.update_checkpoint(
                project_id,
                stage="REVIEW_DISCOVERY",
                progress=candidate_progress,
                message=candidate_message,
            )
            self._progress(candidate_progress, "REVIEW_DISCOVERY", candidate_message)
            result = self.verify_candidate(candidate.candidate_id, ranking_score=ranked_item.score, limit_per_query=limit_per_query)
            results.append(result)
            if self.candidate_checkpoint:
                self.candidate_checkpoint(result)
            if result.candidate_status == CandidateStatus.QUALIFIED:
                qualified.append(result.candidate_id)
            if index >= min_verify and len(qualified) >= final_options:
                break

        # One targeted recovery pass for the most promising incomplete audit,
        # not another broad search of every generated topic.
        if recovery_pass and len(qualified) < final_options:
            provisional = [
                (i, item) for i, item in enumerate(results)
                if item.candidate_status == CandidateStatus.PROVISIONAL_BACKUP
                and item.evidence.conservative_family_lead_count >= MIN_DISCOVERY_STUDIES
                and not any("materially overlapping" in reason or "potentially redundant" in reason
                            for reason in item.pending)
            ]
            if provisional:
                def recovery_priority(pair):
                    item = pair[1]
                    saved = self.ledger.get_candidate(item.candidate_id)
                    meta = (saved.metadata or {}) if saved else {}
                    preflight = meta.get("evidence_preflight") or {}
                    remaining = max(0, int(meta.get("discovery_competitor_records_discovered", 0))
                                    - int(meta.get("discovery_competitor_resolved_count", 0)))
                    remaining += max(0, int(meta.get("discovery_registration_records_discovered", 0))
                                     - int(meta.get("discovery_registration_resolved_count", 0)))
                    return (len(item.coverage.blockers),
                            -int(preflight.get("priority_signal") or 0),
                            remaining, len(item.pending), -item.ranking_score)
                i, item = min(provisional, key=recovery_priority)
                self._progress(92, "DISCOVERY_RECOVERY", "Rechecking unresolved evidence for the best provisional topic")
                recovered = self.verify_candidate(
                    item.candidate_id, ranking_score=item.ranking_score,
                    limit_per_query=limit_per_query, recover_only=True,
                )
                results[i] = recovered
                if self.candidate_checkpoint:
                    self.candidate_checkpoint(recovered)
                if recovered.candidate_status == CandidateStatus.QUALIFIED:
                    qualified.append(recovered.candidate_id)

        final_ids = qualified[:final_options]
        final_stage = "DISCOVERY_EXPORT" if final_ids else "REVIEW_DISCOVERY"
        final_progress = 95 if final_ids else 75
        final_message = (
            f"Prepared {len(final_ids)} first-choice review topics for ChatGPT"
            if final_ids
            else "No fully qualified review topic is ready for the final list"
        )
        self.ledger.update_checkpoint(
            project_id,
            stage=final_stage,
            progress=final_progress,
            message=final_message,
        )
        self._progress(final_progress, final_stage, final_message)
        return DiscoveryRunResult(
            project_id, ranked, results, final_ids, qualified, final_options,
            duplicate_topics_skipped=skipped_duplicates,
            bibliographic_preflight_summary=preflight_summary,
            adaptive_deep_checks_used=max(0, len(results) - max_verify),
            adaptive_checks_skipped_reason=adaptive_skipped,
        )

    def _adaptive_skip_reason(self, prior: list[DiscoveryCandidateResult]) -> str:
        if not prior:
            return "No initial candidate reviews exist"
        provider = getattr(self.scoring_service, "provider", None)
        if provider is not None and getattr(provider, "primary_quota_exhausted", False):
            backup = getattr(provider, "backup", None)
            if backup is None or getattr(provider, "backup_quota_exhausted", False):
                return "Free AI provider quota exhausted; further deep checks deferred"
        if all(result.coverage.blockers for result in prior):
            return (
                "All initial candidate reviews have mandatory source-coverage blockers. "
                "Checking additional proposals would repeat the same unavailable registry "
                "or pipeline sources; retain them as unscreened drafts."
            )
        return ""

    def verify_candidate(self, candidate_id: str, *, ranking_score: float = 0.0, limit_per_query: int = 20, recover_only: bool = False) -> DiscoveryCandidateResult:
        candidate = self.ledger.get_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate not found: {candidate_id}")

        self._check_cancellation()
        policy = policy_for_question_type(candidate.question_type)
        plan = build_search_plan(candidate)
        self._search_sources(candidate, policy.literature_sources, plan.review_queries, evidence_type="PUBLISHED_REVIEW", purpose="published-review novelty", limit_per_query=limit_per_query, recover_only=recover_only)
        self._search_sources(candidate, policy.literature_sources, plan.primary_queries, evidence_type="PRIMARY_STUDY", purpose="primary-study feasibility discovery", limit_per_query=limit_per_query, recover_only=recover_only)
        self._search_sources(candidate, policy.registry_sources, plan.registry_queries, evidence_type="REGISTRATION", purpose="review/protocol registration novelty", limit_per_query=limit_per_query, recover_only=recover_only)
        if policy.require_pipeline_source:
            self._search_sources(candidate, policy.pipeline_sources, plan.pipeline_queries, evidence_type="ONGOING_STUDY", purpose="future evidence pipeline", limit_per_query=limit_per_query, recover_only=recover_only)

        self._check_cancellation()
        # Use additional retrieval only in the existing bounded recovery
        # pass for production; test/explicit callers can opt in directly.
        if self.adaptive_retrieval and (recover_only or not self.adaptive_recovery_only) and not (candidate.metadata or {}).get("adaptive_retrieval_audit"):
            self._adaptive_pubmed_retrieval(candidate,plan,limit_per_query)
            candidate=self.ledger.get_candidate(candidate_id) or candidate
        previous_supplement=(candidate.metadata or {}).get("adaptive_search_audit") or {}
        if self.adaptive_search and (not previous_supplement or
                (recover_only and previous_supplement.get("status")=="DEFERRED_BASE_SOURCE_FAILURE")):
            self._supplementary_search(candidate)
            candidate=self.ledger.get_candidate(candidate_id) or candidate
        prior_enrichment=(candidate.metadata or {}).get("registration_enrichment_audit") or {}
        if self.adaptive_search and (not prior_enrichment or (recover_only and prior_enrichment.get("remaining_report_routes",1)>0)):
            self._check_cancellation()
            registration_audit=enrich_ledger(self.ledger,candidate_id,max_lookups=3,fair=True,previous=prior_enrichment,check=self._check_cancellation)
            candidate=self.ledger.get_candidate(candidate_id) or candidate
            candidate.metadata={**(candidate.metadata or {}),"registration_enrichment_audit":registration_audit}
            self.ledger.upsert_candidate(candidate)
        from scimed_scout.sources.clinicaltrials import ClinicalTrialsGovSource
        registry_client=self.clients.get("ClinicalTrials.gov")
        prior_registry=(candidate.metadata or {}).get("registry_result_reference_audit") or {}
        if self.adaptive_search and isinstance(registry_client,ClinicalTrialsGovSource) and registry_client.http.loader is None and (not prior_registry or (recover_only and prior_registry.get("remaining_registry_ids",1)>0)):
            from .registry_reference_suggestions import suggest
            registry_audit=suggest(self.ledger.list_external_evidence(candidate_id,"PRIMARY_STUDY"),max_lookups=3,check=self._check_cancellation,previous=prior_registry)
            candidate=self.ledger.get_candidate(candidate_id) or candidate
            candidate.metadata={**(candidate.metadata or {}),"registry_result_reference_audit":registry_audit}
            self.ledger.upsert_candidate(candidate)
        logs = self.ledger.list_search_log(candidate_id)
        coverage = evaluate_coverage(logs, policy)
        evidence = discovery_evidence_snapshot(self.ledger, candidate_id)
        primary_records = self.ledger.list_external_evidence(candidate_id, "PRIMARY_STUDY")
        pico_audit, pico_records = assess_pico(candidate, primary_records)
        evidence = replace(evidence, pico_audit=pico_audit)
        pending = list(coverage.blockers)
        if self.require_pico_signals and evidence.conservative_family_lead_count >= MIN_DISCOVERY_STUDIES and pico_audit["pico_design_family_leads"] < MIN_DISCOVERY_STUDIES:
            pending.append("TYPE-A: insufficient source-linked PICO/design cues for the minimum family-lead count; unresolved records need title/abstract and full-text assessment")
        strict_ready=True
        if self.strict_rct_minimum:
            # No full-text screening / extraction or independently adjudicated trial ledger exists here.
            pending.append(f"TYPE-A: independent eligibility, exact arms and extractable outcomes for at least {self.strict_rct_minimum} RCTs require independent adjudication; bibliography is not a final GO")
            from .rct_first import strict_candidate_audit
            strict_audit=strict_candidate_audit(candidate,primary_records)
            strict_ready=min(strict_audit.get('family_leads',0),pico_audit['pico_design_family_leads'])>=self.strict_rct_minimum
            candidate.metadata={**(candidate.metadata or {}),'rct_first_final_audit':strict_audit}
            self.ledger.upsert_candidate(candidate)
            if not strict_ready:
                pending.append(f'TYPE-A: fewer than {self.strict_rct_minimum} comparison-linked RCT family cues in bounded retrieval; not an eligibility exclusion')
        scoring_records = pico_records if self.require_pico_signals else primary_records
        reviews = self.ledger.list_external_evidence(candidate_id, "PUBLISHED_REVIEW")
        registrations = self.ledger.list_external_evidence(candidate_id, "REGISTRATION")
        ongoing = self.ledger.list_external_evidence(candidate_id, "ONGOING_STUDY")

        novelty = None
        if self.novelty_service is not None:
            try:
                novelty = self.novelty_service.assess_candidate(
                    candidate_id, allow_ai=coverage.complete and strict_ready,
                    **({"recovery": True} if recover_only else {}),
                )
            except Exception as exc:
                pending.append(f"TYPE-A: novelty assessment failed: {exc}")
            candidate = self.ledger.get_candidate(candidate_id) or candidate

        # Novelty assessment writes source-linked semantic judgments and
        # resolved search dates back to the ledger. Refresh these records:
        # the pre-assessment snapshots have no judgments and incorrectly
        # force evidence_metrics() to report zero assessed competitors.
        # Unassessed records remain in the complete corpus and still block
        # final qualification; this is a data-freshness fix, not clearance.
        reviews = self.ledger.list_external_evidence(candidate_id, "PUBLISHED_REVIEW")
        registrations = self.ledger.list_external_evidence(candidate_id, "REGISTRATION")

        meta = candidate.metadata or {}
        if reviews and not bool(meta.get("discovery_competitor_assessment_complete")):
            pending.append("TYPE-A: competing published reviews are not fully assessed")
        if registrations and not bool(meta.get("discovery_registration_assessment_complete")):
            pending.append("TYPE-A: competing review registrations are not fully assessed")
        if bool(meta.get("discovery_semantic_scope_capped")):
            pending.append("TYPE-A: limited competitor assessment scope; not all records were verified")
        potential_redundant_reviews = list(meta.get("discovery_potential_fatal_review_overlap_ids") or [])
        if potential_redundant_reviews:
            pending.append(
                "TYPE-A: potentially redundant published review(s) require verified last "
                "search dates, update assessment and human confirmation: "
                + ", ".join(potential_redundant_reviews[:5])
            )

        material_regs = list(meta.get("discovery_material_registration_overlap_ids") or [])
        if material_regs and not bool(meta.get("discovery_material_registration_overlap_resolved")):
            pending.append("TYPE-A: materially overlapping review registration(s): " + ", ".join(material_regs))

        opportunity = assess_review_opportunity(
            reviews, pico_records, primary_records, coverage_complete=coverage.complete,
            registrations_unresolved=bool(material_regs or (registrations and not meta.get("discovery_registration_assessment_complete"))),
            competitor_scope_unresolved=bool(reviews and not meta.get("discovery_competitor_assessment_complete")),
        )
        candidate.metadata = {**(candidate.metadata or {}), "discovery_review_opportunity": opportunity}
        self.ledger.upsert_candidate(candidate)
        meta = candidate.metadata
        if opportunity["route"] in ("UPDATE_SIGNAL", "CORRECTIVE_SIGNAL", "UPDATE_AND_CORRECTIVE_SIGNAL", "OVERLAP_NEEDS_ADJUDICATION"):
            pending.append("TYPE-A: overlapping review opportunity requires independent update/correction adjudication; novelty score alone is not a decision")
        complete_literature = sum(coverage.source_statuses.get(name) in DEFINITIVE for name in policy.literature_sources)
        gate_inputs = dict(meta.get("discovery_gate_inputs") or {})
        # Preliminary clinical importance, feasibility and editorial
        # judgments remain useful when mandatory source coverage is complete
        # but competitor semantic assessment is still unresolved. Computing
        # these does NOT remove unresolved blockers or permit a final GO.
        # Keep AI calls deferred for incomplete mandatory registry/pipeline
        # searches, when the source-based context is insufficient.
        scoring_preliminary = bool(pending)
        if self.scoring_service is not None and coverage.complete and strict_ready:
            try:
                gate_inputs = self.scoring_service.score(
                    candidate,
                    unique_primary_studies=(pico_audit['pico_design_family_leads'] if self.require_pico_signals else evidence.unique_primary_study_candidates),
                    published_review_hits=len(reviews),
                    registration_hits=len(registrations),
                    competitor_summary=(novelty or {}).get("summary", ""),
                    review_records=reviews,
                    registration_records=registrations,
                    primary_records=scoring_records,
                    semantically_capped=bool(meta.get("discovery_semantic_scope_capped")),
                )
                candidate.metadata = {
                    **(candidate.metadata or {}),
                    "discovery_gate_inputs": gate_inputs,
                    "discovery_scoring_preliminary_only": scoring_preliminary,
                    "discovery_scoring_preliminary_reason": (
                        "Competitor overlap and review registration still require "
                        "independent adjudication; AI scores are not novelty clearance."
                        if scoring_preliminary else ""
                    ),
                    "discovery_scoring_deferred": False,
                }
                self.ledger.upsert_candidate(candidate)
            except Exception as exc:
                pending.append(f"TYPE-A: discovery scoring failed: {exc}")

        if self.scoring_service is not None and (not coverage.complete or not gate_inputs):
            candidate.metadata = {
                **(candidate.metadata or {}),
                "discovery_scoring_deferred": True,
                "discovery_scoring_deferred_reason": (
                    "Mandatory source coverage unavailable"
                    if not coverage.complete else
                    "Preliminary free AI scoring did not finish"
                ),
            }
            self.ledger.upsert_candidate(candidate)

        required_scoring = {
            "design_framework_defined", "meaningful_synthesis_plausible", "clinical_question_novelty",
            "overall_novelty", "question_framework_coherent", "feasibility", "fatal_methodological_flaw",
            "clinical_importance", "publication_potential", "new_information_gain",
            "publication_oriented_score", "editorial_grade",
        }
        missing = sorted(required_scoring - set(gate_inputs))
        if missing:
            pending.append("Pending discovery scoring fields: " + ", ".join(missing))

        status = CandidateStatus.DEEP_VERIFYING
        decision = "PENDING — DISCOVERY VERIFICATION INCOMPLETE"
        final_gate_result = None

        if self.strict_rct_minimum and not strict_ready:
            status=CandidateStatus.PROVISIONAL_BACKUP
            decision='PROVISIONAL — RCT COMPARISON FAMILY SIGNAL INSUFFICIENT'
        elif (coverage.complete and evidence.unique_primary_study_candidates >= MIN_DISCOVERY_STUDIES
                and evidence.conservative_family_lead_count < MIN_DISCOVERY_STUDIES):
            pending.append('TYPE-A: registry-linked report families reduce apparent study availability; comparison-level and population independence must be adjudicated manually')
            status = CandidateStatus.PROVISIONAL_BACKUP
            decision = 'PROVISIONAL — TRIAL-FAMILY INDEPENDENCE UNRESOLVED'
        elif coverage.complete and evidence.unique_primary_study_candidates < MIN_DISCOVERY_STUDIES:
            status = CandidateStatus.REJECTED
            decision = f"REJECT — FEWER THAN {MIN_DISCOVERY_STUDIES} UNIQUE PRIMARY-STUDY CANDIDATES FOUND"
        elif bool(meta.get("discovery_fatal_redundancy")):
            status = CandidateStatus.REJECTED
            decision = "REJECT — FATAL REVIEW REDUNDANCY"
        elif opportunity["route"] in ("UPDATE_SIGNAL", "CORRECTIVE_SIGNAL", "UPDATE_AND_CORRECTIVE_SIGNAL", "OVERLAP_NEEDS_ADJUDICATION"):
            status = CandidateStatus.PROVISIONAL_BACKUP
            decision = "PROVISIONAL — " + opportunity["route"] + " (INDEPENDENT VERIFICATION REQUIRED)"
        elif not pending:
            # Coverage defines a minimum of conclusive literature sources,
            # not a requirement to search every optional bibliographic index.
            # Include all conclusive literature audits and the mandatory
            # registry/pipeline audits in the gate. Preserve ALL statuses in
            # coverage/decision provenance, including optional failures.
            required_source_names = {
                name for name in policy.literature_sources
                if coverage.source_statuses.get(name) in DEFINITIVE
            }
            if policy.require_prospero:
                required_source_names.add("PROSPERO")
            if policy.require_osf:
                required_source_names.add("OSF Registries")
            if policy.require_pipeline_source:
                required_source_names.update(
                    name for name in policy.pipeline_sources
                    if coverage.source_statuses.get(name) in DEFINITIVE
                )
            payload = {
                **gate_inputs,
                "unique_primary_study_candidates": min(evidence.conservative_family_lead_count, pico_audit["pico_design_family_leads"]) if self.require_pico_signals else evidence.conservative_family_lead_count,
                "distinct_bibliographic_report_leads": evidence.unique_primary_study_candidates,
                "complete_literature_sources": complete_literature,
                "fatal_redundancy": bool(meta.get("discovery_fatal_redundancy", False)),
                "sources": [
                    {"source": source, "status": source_status.value}
                    for source, source_status in coverage.source_statuses.items()
                    if source in required_source_names
                ],
                "unresolved_type_a": [],
            }
            final_gate_result = final_discovery_decision(payload)
            decision = final_gate_result["decision"]
            status = CandidateStatus.QUALIFIED if decision == "QUALIFIED — FIRST-CHOICE REVIEW TOPIC" else CandidateStatus.REJECTED
        elif pending:
            # A job marked COMPLETED must not leave records as DEEP_VERIFYING.
            # Missing scientific assessments remain provisional even when
            # registry coverage happens to be complete for this question.
            status = CandidateStatus.PROVISIONAL_BACKUP
            decision = (
                "PROVISIONAL — SOURCE COVERAGE INCOMPLETE"
                if coverage.blockers
                else "PROVISIONAL — SCIENTIFIC ASSESSMENT INCOMPLETE"
            )

        self.ledger.set_candidate_status(candidate_id, status)
        self._append_decision(candidate, decision=decision, reason="; ".join(pending), payload={
            "scope": "REVIEW_DISCOVERY_ONLY",
            "ranking_score": ranking_score,
            "coverage": {"source_statuses": {k: v.value for k, v in coverage.source_statuses.items()}, "blockers": list(coverage.blockers), "warnings": list(coverage.warnings)},
            "discovery_evidence": asdict(evidence),
            "published_review_hits": len(reviews),
            "registration_hits": len(registrations),
            "ongoing_study_hits": len(ongoing),
            "novelty_assessment": novelty,
            "review_opportunity": opportunity,
            "final_gate_result": final_gate_result,
        })
        return DiscoveryCandidateResult(candidate_id, ranking_score, coverage, evidence, pending, decision, status, final_gate_result)

    def _search_sources(self, candidate, source_names: tuple[str, ...], queries: tuple[str, ...], *, evidence_type: str, purpose: str, limit_per_query: int, recover_only: bool = False) -> None:
        if not source_names or not queries:
            return

        configured: list[tuple[str, SourceClient]] = []
        source_queries: dict[str, tuple[str, ...]] = {}
        latest = {(log.source, log.query): log.status
                  for log in self.ledger.list_search_log(candidate.candidate_id)} if recover_only else {}
        for source_name in source_names:
            client = self.clients.get(source_name)
            if client is None:
                self.ledger.append_search_log(
                    SearchLogRecord(
                        candidate.project_id,
                        candidate.candidate_id,
                        source_name,
                        "",
                        SourceStatus.NOT_SEARCHED,
                        message="No configured source client",
                    )
                )
                continue

            planned = queries
            if self.optimize_literature_queries and evidence_type in ("PRIMARY_STUDY","PUBLISHED_REVIEW"):
                planned = optimized_queries(candidate,source_name,
                    "PRIMARY" if evidence_type=="PRIMARY_STUDY" else "REVIEW",
                    queries,max_queries=len(queries))
            selected = tuple(q for q in planned if not recover_only
                             or latest.get((source_name, q)) not in DEFINITIVE)
            if not selected:
                continue
            configured.append((source_name, client))
            source_queries[source_name] = selected
            for query in selected:
                self.ledger.add_query(
                    candidate.project_id,
                    candidate.candidate_id,
                    source_name,
                    query,
                    purpose,
                )

        if not configured:
            return

        self._check_cancellation()
        with ThreadPoolExecutor(
            max_workers=min(5, len(configured)),
            thread_name_prefix="scout-source",
        ) as executor:
            futures = {
                source_name: executor.submit(
                    _run_source_queries,
                    client,
                    source_queries[source_name],
                    limit_per_query,
                    recover_only,
                )
                for source_name, client in configured
            }

            # Remote sources run concurrently, but SQLite writes stay on the main
            # thread so the discovery ledger remains deterministic and thread-safe.
            for source_name, _ in configured:
                self._check_cancellation()
                completed_results=futures[source_name].result()
                for query, result in completed_results:
                    self._check_cancellation()
                    message=result.message
                    if self.optimize_literature_queries and evidence_type in ("PRIMARY_STUDY","PUBLISHED_REVIEW") and source_name in ("PubMed","Europe PMC"):
                        import json
                        quality=sample_quality(result)
                        message=(message or "")+" | "+QUERY_OPTIMIZER_VERSION+" "+json.dumps(quality,ensure_ascii=True)
                        # A positive hit count without usable metadata cannot
                        # establish a completed bibliographic retrieval.
                        if result.status==SourceStatus.SEARCHED_POSITIVE and quality["records_with_title"]==0:
                            result=replace(result,status=SourceStatus.PARTIAL)
                    self.ledger.append_search_log(
                        SearchLogRecord(
                            candidate.project_id,
                            candidate.candidate_id,
                            source_name,
                            query,
                            result.status,
                            result.total_count,
                            message=message,
                        )
                    )
                    for record in result.records:
                        record_type = evidence_type
                        classification = ""
                        if evidence_type == "PUBLISHED_REVIEW":
                            kind = classify_review_search_hit(record)
                            classification = kind
                            if kind == "CONFIRMED_REVIEW_CUE":
                                signal = review_intervention_citation_signal(
                                    candidate, record,
                                )
                                classification = kind + ":" + signal
                                if signal == (
                                    "NO_INTERVENTION_MENTION_IN_REVIEW_CITATION_MANUAL_CHECK"
                                ) and record.source not in ("PubMed","Europe PMC"):
                                    # A broad bibliographic search can yield
                                    # systematic reviews on green tea, carotenoids
                                    # or oncology when investigating ketone esters.
                                    # Keep them in OTHER for manual assessment;
                                    # do not pretend they are excluded by a
                                    # full-text/PICO review.
                                    record_type = "OTHER"
                            else:
                                # Peer-review reports, unrelated primary studies
                                # and unknown citation types remain auditable.
                                record_type = "OTHER"
                        elif evidence_type == "REGISTRATION":
                            kind = classify_registration_search_hit(record)
                            classification = kind
                            if kind in ("PRIMARY_STUDY_PREREGISTRATION", "UNCLASSIFIED_REGISTRATION"):
                                record_type = "OTHER"
                        elif evidence_type == "PRIMARY_STUDY":
                            if _obvious_review(record):
                                signal=review_intervention_citation_signal(candidate,record)
                                self._store_record(candidate.candidate_id,
                                    "PUBLISHED_REVIEW" if signal!="NO_INTERVENTION_MENTION_IN_REVIEW_CITATION_MANUAL_CHECK" or record.source in ("PubMed","Europe PMC") else "OTHER",
                                    record,query,purpose,classification="CONFIRMED_REVIEW_CUE:"+signal,
                                    originally_requested=evidence_type)
                                continue
                            # Crossref title search covers books, chapters and
                            # nonclinical citations without dependable study
                            # design metadata. Keep Crossref for competitor
                            # literature, but do not inflate primary-study
                            # candidate availability from these loose matches.
                            if record.source == "Crossref":
                                continue
                        self._store_record(
                            candidate.candidate_id,
                            record_type,
                            record,
                            query,
                            purpose,
                            classification=classification,
                            originally_requested=evidence_type,
                        )
                if self.progress_callback:
                    self.progress_callback(-1,"SOURCE_COMPLETE",f"{source_name}: {purpose}; {len(completed_results)} queries returned")

    def _adaptive_pubmed_retrieval(self,candidate,plan,limit_per_query):
        client=self.clients.get("PubMed")
        if client is None:return
        logs=[l for l in self.ledger.list_search_log(candidate.candidate_id) if l.source=="PubMed"]
        # Separate supplemental audit; never overwrite the mandatory search
        # log or use this bounded retrieval to clear source failures.
        access=any(l.status in DEFINITIVE for l in logs) and not any(l.status==SourceStatus.ACCESS_FAILED or "429" in (l.message or "") for l in logs)
        audits=[]
        for purpose,legacy,kind in (("PRIMARY",plan.primary_queries,"PRIMARY_STUDY"),("REVIEW",plan.review_queries,"PUBLISHED_REVIEW")):
            self._check_cancellation()
            baseline=self.ledger.list_external_evidence(candidate.candidate_id,kind)
            report,records=collect_adaptive_retrieval(candidate,purpose,legacy,baseline,client,
                initial_limit=limit_per_query,base_access=access,cancellation_check=self._check_cancellation)
            audits.append(report)
            for record in records:
                self._check_cancellation()
                citation=classify_review_search_hit(record)
                if purpose=="REVIEW":
                    signal=review_intervention_citation_signal(candidate,record)
                    record_type="PUBLISHED_REVIEW" if citation=="CONFIRMED_REVIEW_CUE" and (signal!="NO_INTERVENTION_MENTION_IN_REVIEW_CITATION_MANUAL_CHECK" or record.source in ("PubMed","Europe PMC")) else "OTHER"
                else:
                    if citation=="CONFIRMED_REVIEW_CUE":
                        record_type="PUBLISHED_REVIEW" if (review_intervention_citation_signal(candidate,record)!="NO_INTERVENTION_MENTION_IN_REVIEW_CITATION_MANUAL_CHECK" or record.source in ("PubMed","Europe PMC")) else "OTHER"
                    else:record_type="PRIMARY_STUDY"
                self._store_record(candidate.candidate_id,record_type,record,(record.metadata.get("adaptive_pubmed") or {}).get("query",report.get("query","")),"ADAPTIVE_PUBMED",classification=citation,originally_requested="SUPPLEMENTARY_DISCOVERY")
        candidate=self.ledger.get_candidate(candidate.candidate_id) or candidate
        candidate.metadata={**(candidate.metadata or {}),"adaptive_retrieval_audit":audits}
        self.ledger.upsert_candidate(candidate)

    def _supplementary_search(self,candidate):
        client=self.clients.get("Europe PMC")
        if client is None or not hasattr(client,"http"):
            return
        logs=self.ledger.list_search_log(candidate.candidate_id)
        latest={(log.source,log.query):log.status for log in logs}
        if any(source=="Europe PMC" and status==SourceStatus.ACCESS_FAILED for (source,_),status in latest.items()):
            candidate.metadata={**(candidate.metadata or {}),"adaptive_search_audit":{
                "version":"ADAPTIVE_SEARCH_V1","status":"DEFERRED_BASE_SOURCE_FAILURE","coverage_clearance_allowed":False}}
            self.ledger.upsert_candidate(candidate)
            return
        try:
            report,rows=collect_supplementary(candidate,
                self.ledger.list_external_evidence(candidate.candidate_id,"PRIMARY_STUDY"),
                self.ledger.list_external_evidence(candidate.candidate_id,"PUBLISHED_REVIEW"),
                client,existing_queries={log.query for log in logs if log.source=="Europe PMC"},check=self._check_cancellation)
            # Supplementary attempts are deliberately separate from the
            # mandatory database coverage ledger. Preserve all returned hits;
            # only confirmed review cues are tagged as competing reviews.
            for purpose,query,records in rows:
                for record in records:
                    self._check_cancellation()
                    kind=classify_review_search_hit(record)
                    record_type=("PUBLISHED_REVIEW" if (review_intervention_citation_signal(candidate,record)!="NO_INTERVENTION_MENTION_IN_REVIEW_CITATION_MANUAL_CHECK" or record.source in ("PubMed","Europe PMC")) else "OTHER") if kind=="CONFIRMED_REVIEW_CUE" else "PRIMARY_STUDY"
                    self._store_record(candidate.candidate_id,record_type,record,query,purpose,
                        classification=kind,originally_requested="SUPPLEMENTARY_DISCOVERY")
            candidate=self.ledger.get_candidate(candidate.candidate_id) or candidate
            candidate.metadata={**(candidate.metadata or {}),"adaptive_search_audit":report}
            self.ledger.upsert_candidate(candidate)
        except Exception as exc:
            self._check_cancellation()
            candidate=self.ledger.get_candidate(candidate.candidate_id) or candidate
            candidate.metadata={**(candidate.metadata or {}),"adaptive_search_audit":{
                "version":"ADAPTIVE_SEARCH_V1","status":"FAILED","error_type":type(exc).__name__,
                "coverage_clearance_allowed":False}}
            self.ledger.upsert_candidate(candidate)

    def _store_record(
        self, candidate_id: str, evidence_type: str, record: SearchRecord,
        query: str, purpose: str, *,
        classification: str = "", originally_requested: str = "",
    ) -> None:
        existing = next((item for item in self.ledger.list_external_evidence(candidate_id, evidence_type) if str(item.get("source_record_id") or "") == str(record.record_id)), None)
        previous = dict((existing or {}).get("payload") or {})
        previous_metadata = previous.get("metadata") if isinstance(previous.get("metadata"), dict) else {}
        new_metadata = dict(record.metadata) if isinstance(record.metadata, dict) else {}
        if existing and record.source == "PubMed" and existing.get("source") == "PubMed" and previous_metadata.get("pubmed_efetch_identity") == "EXACT_PMID":
            for key in ("abstractText", "pubtype", "trial_registration_ids", "pubmed_efetch_identity"):
                if previous_metadata.get(key):
                    new_metadata[key] = previous_metadata[key]
        payload = {
            **previous,
            "url": record.url or previous.get("url", ""),
            "year": record.year if record.year is not None else previous.get("year"),
            "doi": record.doi or previous.get("doi", ""),
            "query": query,
            "purpose": purpose,
            "citation_classification": classification or previous.get("citation_classification", ""),
            "originally_requested_evidence_type": originally_requested or evidence_type,
            "metadata": {**previous_metadata, **new_metadata},
        }
        self.ledger.upsert_external_evidence(candidate_id, evidence_type, record.record_id, source=record.source or str((existing or {}).get("source") or ""), title=record.title or str((existing or {}).get("title") or ""), payload=payload)

    def _check_cancellation(self) -> None:
        if self.cancellation_check is not None:
            self.cancellation_check()

    def _progress(self, progress: int, stage: str, message: str) -> None:
        self._check_cancellation()
        if self.progress_callback is not None:
            self.progress_callback(progress, stage, message)

    def _append_decision(self, candidate, *, decision: str, reason: str, payload: dict[str, Any]) -> None:
        sequence = len(self.ledger.list_decisions(candidate.candidate_id)) + 1
        self.ledger.append_decision(DecisionRecord(
            decision_id=f"{candidate.candidate_id}-DISCOVERY-{sequence:04d}",
            project_id=candidate.project_id,
            candidate_id=candidate.candidate_id,
            decision=decision,
            stage="REVIEW_DISCOVERY",
            reason=reason,
            payload=payload,
        ))


def _obvious_review(record: SearchRecord) -> bool:
    # Share the evidence classifier across both source-search purposes.
    # A confirmed review cue belongs in PUBLISHED_REVIEW, never the
    # PRIMARY_STUDY bibliographic feasibility pool.
    return classify_review_search_hit(record) == "CONFIRMED_REVIEW_CUE"

def _run_source_queries(
    client: SourceClient,
    queries: tuple[str, ...],
    limit_per_query: int,
    recover_only: bool = False,
) -> list[tuple[str, SearchResult]]:
    results: list[tuple[str, SearchResult]] = []
    for index, query in enumerate(queries):
        try:
            search=getattr(client,"search_recovery",client.search) if recover_only else client.search
            result = search(query, limit=limit_per_query)
        except Exception as exc:
            result = SearchResult(
                source=getattr(client, "name", "Unknown"),
                query=query,
                status=SourceStatus.ACCESS_FAILED,
                records=[],
                total_count=None,
                message=str(exc),
            )
        results.append((query, result))
        if result.status == SourceStatus.ACCESS_FAILED and (
            "429" in (result.message or "") or "Too Many Requests" in (result.message or "")
        ):
            # A provider-wide limit is not solved by issuing the other PICO
            # query variants immediately. Retain the failed search audit,
            # and explicitly retain every unexecuted planned query. Otherwise
            # a later recovery of the failed variant can make coverage appear
            # conclusive despite unexecuted variants.
            for deferred in queries[index + 1:]:
                results.append((deferred, SearchResult(
                    client.name, deferred, SourceStatus.NOT_SEARCHED,
                    message="Deferred after provider HTTP 429; query not executed",
                )))
            break
    return results
