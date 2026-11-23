from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Any, Callable

from scimed_scout.domain import CandidateStatus, SourceStatus
from scimed_scout.ranking import CandidateRankingService
from scimed_scout.sources.base import SearchRecord, SearchResult, SourceClient
from scimed_scout.storage import DecisionRecord, SearchLogRecord, SQLiteLedger
from scimed_scout.verification.coverage import DEFINITIVE, evaluate_coverage
from scimed_scout.verification.policy import policy_for_question_type
from scimed_scout.verification.queries import build_search_plan

from .constants import MIN_DISCOVERY_STUDIES
from .evidence import discovery_evidence_snapshot
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
    ):
        self.ledger = ledger
        self.clients = {client.name: client for client in clients}
        self.novelty_service = novelty_service
        self.scoring_service = scoring_service
        self.progress_callback = progress_callback
        self.cancellation_check = cancellation_check

    def run(
        self,
        project_id: str,
        *,
        min_verify: int = 3,
        max_verify: int = 10,
        final_options: int = 3,
        limit_per_query: int = 20,
    ) -> DiscoveryRunResult:
        if min_verify < 1 or max_verify < min_verify:
            raise ValueError("Require 1 <= min_verify <= max_verify")
        if final_options < 2 or final_options > max_verify:
            raise ValueError("Require 2 <= final_options <= max_verify")
        if self.ledger.get_project(project_id) is None:
            raise ValueError(f"Project not found: {project_id}")

        self._check_cancellation()
        ranked = CandidateRankingService(self.ledger).rank_project(project_id, top_n=max_verify)
        by_id = {c.candidate_id: c for c in self.ledger.list_candidates(project_id)}
        diverse, skipped_duplicates = select_diverse_ranked(ranked, by_id, limit=max_verify)
        ranking_message = (
            f"Ranked {len(ranked)} candidates, selected {len(diverse)} distinct PICOs; "
            f"skipped {len(skipped_duplicates)} near-duplicate questions"
        )
        self.ledger.update_checkpoint(project_id, stage="DISCOVERY_RANKING", progress=20, message=ranking_message)
        self._progress(20, "DISCOVERY_RANKING", ranking_message)

        results: list[DiscoveryCandidateResult] = []
        qualified: list[str] = []
        for index, ranked_item in enumerate(diverse, 1):
            self._check_cancellation()
            candidate = self.ledger.get_candidate(ranked_item.candidate_id)
            if candidate is None:
                continue
            self.ledger.set_candidate_status(candidate.candidate_id, CandidateStatus.DEEP_VERIFYING)
            candidate_progress = min(90, 20 + int(65 * index / max(1, len(diverse))))
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
            if result.candidate_status == CandidateStatus.QUALIFIED:
                qualified.append(result.candidate_id)
            if index >= min_verify and len(qualified) >= final_options:
                break

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
        )

    def verify_candidate(self, candidate_id: str, *, ranking_score: float = 0.0, limit_per_query: int = 20) -> DiscoveryCandidateResult:
        candidate = self.ledger.get_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate not found: {candidate_id}")

        self._check_cancellation()
        policy = policy_for_question_type(candidate.question_type)
        plan = build_search_plan(candidate)
        self._search_sources(candidate, policy.literature_sources, plan.review_queries, evidence_type="PUBLISHED_REVIEW", purpose="published-review novelty", limit_per_query=limit_per_query)
        self._search_sources(candidate, policy.literature_sources, plan.primary_queries, evidence_type="PRIMARY_STUDY", purpose="primary-study feasibility discovery", limit_per_query=limit_per_query)
        self._search_sources(candidate, policy.registry_sources, plan.registry_queries, evidence_type="REGISTRATION", purpose="review/protocol registration novelty", limit_per_query=limit_per_query)
        if policy.require_pipeline_source:
            self._search_sources(candidate, policy.pipeline_sources, plan.pipeline_queries, evidence_type="ONGOING_STUDY", purpose="future evidence pipeline", limit_per_query=limit_per_query)

        self._check_cancellation()
        logs = self.ledger.list_search_log(candidate_id)
        coverage = evaluate_coverage(logs, policy)
        evidence = discovery_evidence_snapshot(self.ledger, candidate_id)
        pending = list(coverage.blockers)
        reviews = self.ledger.list_external_evidence(candidate_id, "PUBLISHED_REVIEW")
        registrations = self.ledger.list_external_evidence(candidate_id, "REGISTRATION")
        ongoing = self.ledger.list_external_evidence(candidate_id, "ONGOING_STUDY")

        novelty = None
        if self.novelty_service is not None:
            try:
                novelty = self.novelty_service.assess_candidate(candidate_id)
            except Exception as exc:
                pending.append(f"TYPE-A: novelty assessment failed: {exc}")
            candidate = self.ledger.get_candidate(candidate_id) or candidate

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

        complete_literature = sum(coverage.source_statuses.get(name) in DEFINITIVE for name in policy.literature_sources)
        gate_inputs = dict(meta.get("discovery_gate_inputs") or {})
        if self.scoring_service is not None:
            try:
                gate_inputs = self.scoring_service.score(
                    candidate,
                    unique_primary_studies=evidence.unique_primary_study_candidates,
                    published_review_hits=len(reviews),
                    registration_hits=len(registrations),
                    competitor_summary=(novelty or {}).get("summary", ""),
                    review_records=reviews,
                    registration_records=registrations,
                    primary_records=self.ledger.list_external_evidence(candidate_id, "PRIMARY_STUDY"),
                    semantically_capped=bool(meta.get("discovery_semantic_scope_capped")),
                )
                candidate.metadata = {**(candidate.metadata or {}), "discovery_gate_inputs": gate_inputs}
                self.ledger.upsert_candidate(candidate)
            except Exception as exc:
                pending.append(f"TYPE-A: discovery scoring failed: {exc}")

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

        if coverage.complete and evidence.unique_primary_study_candidates < MIN_DISCOVERY_STUDIES:
            status = CandidateStatus.REJECTED
            decision = f"REJECT — FEWER THAN {MIN_DISCOVERY_STUDIES} UNIQUE PRIMARY-STUDY CANDIDATES FOUND"
        elif bool(meta.get("discovery_fatal_redundancy")):
            status = CandidateStatus.REJECTED
            decision = "REJECT — FATAL REVIEW REDUNDANCY"
        elif not pending:
            required_source_names = set(policy.literature_sources + policy.registry_sources)
            if policy.require_pipeline_source:
                required_source_names.update(policy.pipeline_sources)
            payload = {
                **gate_inputs,
                "unique_primary_study_candidates": evidence.unique_primary_study_candidates,
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
        elif coverage.blockers:
            status = CandidateStatus.PROVISIONAL_BACKUP
            decision = "PROVISIONAL — SOURCE COVERAGE INCOMPLETE"

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
            "final_gate_result": final_gate_result,
        })
        return DiscoveryCandidateResult(candidate_id, ranking_score, coverage, evidence, pending, decision, status, final_gate_result)

    def _search_sources(self, candidate, source_names: tuple[str, ...], queries: tuple[str, ...], *, evidence_type: str, purpose: str, limit_per_query: int) -> None:
        if not source_names or not queries:
            return

        configured: list[tuple[str, SourceClient]] = []
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

            configured.append((source_name, client))
            for query in queries:
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
                    queries,
                    limit_per_query,
                )
                for source_name, client in configured
            }

            # Remote sources run concurrently, but SQLite writes stay on the main
            # thread so the discovery ledger remains deterministic and thread-safe.
            for source_name, _ in configured:
                self._check_cancellation()
                for query, result in futures[source_name].result():
                    self._check_cancellation()
                    self.ledger.append_search_log(
                        SearchLogRecord(
                            candidate.project_id,
                            candidate.candidate_id,
                            source_name,
                            query,
                            result.status,
                            result.total_count,
                            message=result.message,
                        )
                    )
                    for record in result.records:
                        if evidence_type == "PRIMARY_STUDY":
                            if _obvious_review(record):
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
                            evidence_type,
                            record,
                            query,
                            purpose,
                        )

    def _store_record(self, candidate_id: str, evidence_type: str, record: SearchRecord, query: str, purpose: str) -> None:
        existing = next((item for item in self.ledger.list_external_evidence(candidate_id, evidence_type) if str(item.get("source_record_id") or "") == str(record.record_id)), None)
        previous = dict((existing or {}).get("payload") or {})
        previous_metadata = previous.get("metadata") if isinstance(previous.get("metadata"), dict) else {}
        new_metadata = record.metadata if isinstance(record.metadata, dict) else {}
        payload = {
            **previous,
            "url": record.url or previous.get("url", ""),
            "year": record.year if record.year is not None else previous.get("year"),
            "doi": record.doi or previous.get("doi", ""),
            "query": query,
            "purpose": purpose,
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
    title = " ".join(str(record.title or "").casefold().split())
    if any(marker in title for marker in ("systematic review", "meta-analysis", "meta analysis", "scoping review", "umbrella review", "narrative review", "review protocol")):
        return True
    metadata = record.metadata if isinstance(record.metadata, dict) else {}
    publication_types = metadata.get("publicationTypes") or metadata.get("pubtype") or []
    if isinstance(publication_types, str):
        publication_types = [publication_types]
    joined = " ".join(str(x).casefold() for x in publication_types)
    return "review" in joined or "meta-analysis" in joined or "meta analysis" in joined


def _run_source_queries(
    client: SourceClient,
    queries: tuple[str, ...],
    limit_per_query: int,
) -> list[tuple[str, SearchResult]]:
    results: list[tuple[str, SearchResult]] = []
    for query in queries:
        try:
            result = client.search(query, limit=limit_per_query)
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
            # and do not invent negative results for skipped queries.
            break
    return results
