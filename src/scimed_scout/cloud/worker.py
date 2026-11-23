from __future__ import annotations

import json
import os
import tempfile
import traceback
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from scimed_scout.ai import CandidateDiscoveryService, FreeProviderFallback
from scimed_scout.competitors import SemanticCompetitorAssessor
from scimed_scout.discovery.topic_memory import recent_topic_memory
from scimed_scout.discovery.open_access_dates import OpenAccessSearchDateResolver
from scimed_scout.discovery.candidate_preflight import FocusedEvidencePreflight
from scimed_scout.discovery.evidence_seed import (
    recent_pubmed_cues, cue_prompt, recent_review_gap_cues, review_gap_prompt,
)
from scimed_scout.discovery import (
    DiscoveryNoveltyService,
    DiscoveryScoringService,
    ReviewDiscoveryOrchestrator,
    build_discovery_review_package,
)
from scimed_scout.sources import build_default_source_clients
from scimed_scout.storage import ProjectRecord, SQLiteLedger

from .supabase import DiscoveryJob, JobCancelled, SupabaseJobStore


def _unverified_topic_options(candidates: list, checked_ids: set[str]) -> list[dict[str, Any]]:
    """Expose complete generated PICOs without implying source verification."""
    unverified_drafts = []
    for candidate in candidates:
        if candidate.candidate_id in checked_ids:
            continue
        question = {
            "review_question": candidate.review_question,
            "population": candidate.population,
            "intervention_exposure_index_test": candidate.intervention_exposure_index_test,
            "comparator_reference": candidate.comparator_reference,
            "outcomes": list(candidate.outcomes or []),
            "eligible_designs": list(candidate.eligible_designs or []),
            "rationale_hypothesis": candidate.rationale or "NOT_PROVIDED",
            "novelty_hypothesis": candidate.novelty_hypothesis or "NOT_PROVIDED",
            "candidate_search_terms": list(candidate.search_terms or []),
        }
        unverified_drafts.append({
            "candidate_id": candidate.candidate_id,
            "title": candidate.title,
            "specialty": candidate.specialty,
            "question_type": candidate.question_type,
            **question,
            "qualification_status": "AI_DRAFT_NOT_SOURCE_VERIFIED",
            "preflight_bibliographic_evidence": dict((candidate.metadata or {}).get("evidence_preflight") or {}),
            "provisional_only": True,
            "research_dossier": {
                "candidate_id": candidate.candidate_id,
                "title": candidate.title,
                "specialty": candidate.specialty,
                "question_type": candidate.question_type,
                "qualification_label": "AI_DRAFT_NOT_SOURCE_VERIFIED",
                "qualification_decision": "NOT_CHECKED",
                "scientific_question": question,
                "evidence_preflight": dict((candidate.metadata or {}).get("evidence_preflight") or {}),
                "verification_and_quality": {
                    "source_statuses": {
                        "PubMed": "NOT_SEARCHED",
                        "PROSPERO": "NOT_SEARCHED",
                        "OSF Registries": "NOT_SEARCHED",
                    },
                    "source_blockers": [
                        "Candidate was generated but no source verification was run."
                    ],
                    "pending_verifications": [
                        "Independent published-review, registration, primary-study and trial-family audit required."
                    ],
                    "preliminary_scoring": {},
                },
                "evidence_search_audit": [],
                "published_review_evidence": [],
                "registration_evidence": [],
                "primary_study_screening_queue": [],
                "ongoing_study_evidence": [],
                "eligible_independent_studies_confirmed": None,
                "independent_literature_confirmation_required": True,
                "next_actions": [
                    "Execute and document source searches before assessing novelty.",
                    "Verify published reviews and PROSPERO/OSF registrations.",
                    "Screen full texts and distinct eligible studies against the PICO.",
                ],
            },
        })
    return unverified_drafts


def process_job(job: DiscoveryJob, store: SupabaseJobStore) -> dict[str, Any]:
    store.ensure_active(job.id)
    history_rows = store.recent_completed_jobs(
        client_token_hash=job.client_token_hash,
        revisit_days=job.revisit_days,
    )
    prior_topics = recent_topic_memory(history_rows, revisit_days=job.revisit_days)
    recently_skipped: list[dict[str, Any]] = []
    provider = FreeProviderFallback.from_env()
    if not provider.primary.endpoint or not provider.primary.model or not provider.primary.api_key:
        raise RuntimeError("SCIMED_AI_ENDPOINT, SCIMED_AI_MODEL and SCIMED_AI_API_KEY are required")

    with tempfile.TemporaryDirectory(prefix="scimed-review-scout-") as temp_dir:
        db_path = Path(temp_dir) / "worker.sqlite3"
        with SQLiteLedger(db_path) as ledger:
            project_id = job.id
            ledger.upsert_project(
                ProjectRecord(
                    project_id=project_id,
                    specialty=job.specialty,
                    question_type=job.question_type,
                    metadata={"cloud_job_id": job.id, "worker": "github-actions"},
                )
            )

            store.update_job(
                job.id,
                stage="CANDIDATE_GENERATION",
                progress=5,
                message="Generating review-topic candidates",
            )
            generator = CandidateDiscoveryService(provider, ledger)
            evidence_cues = recent_pubmed_cues(job.specialty, job.question_type)
            # Campbell/3ie-style evidence-gap cues from *actual review
            # abstracts*, not model-generated claims of novelty. One free
            # Europe PMC query, with a safe empty result on source outages.
            review_gap_cues = recent_review_gap_cues(
                job.specialty, job.question_type, max_records=5,
            )
            # Save real bibliographic leads BEFORE any paid/free AI endpoint
            # is called. A quota or malformed JSON must not erase the evidence
            # already retrieved from PubMed. These are NOT review PICO proposals.
            store.update_job(
                job.id,
                result_json={
                    "checkpoint": {
                        "stage": "PUBMED_EVIDENCE_CUES",
                        "verified": False,
                        "note": "Real PubMed records. Not confirmed eligible primary studies, systematic-review ideas, or evidence of novelty.",
                        "candidate_count": 0,
                        "recent_pubmed_cues": evidence_cues,
                        "published_review_gap_cues": review_gap_cues,
                        "candidates": [],
                    }
                },
                message=(
                    f"Saved {len(evidence_cues)} PubMed research leads; checking free AI access"
                    if evidence_cues else "No PubMed leads available; checking free AI access"
                ),
            )

            def generation_progress(found: int, target: int) -> None:
                store.ensure_active(job.id)
                store.update_job(
                    job.id,
                    stage="CANDIDATE_GENERATION",
                    progress=5 + int(12 * found / max(1, target)),
                    message=f"Generated {found}/{target} complete topic proposals; checking more candidates",
                )

            candidates = generator.generate_and_store(
                project_id=project_id,
                specialty=job.specialty,
                question_types=[] if job.question_type.strip().upper() == "ALL" else [job.question_type],
                design_scope=[],
                count=job.candidate_count,
                additional_context=(
                    cue_prompt(evidence_cues) + "\n" + review_gap_prompt(review_gap_cues)
                ).strip(),
                progress_callback=generation_progress,
                recent_topics=prior_topics,
                skipped_recent=recently_skipped,
            )
            store.ensure_active(job.id)
            if not candidates:
                if recently_skipped:
                    return {
                        "package": {
                            "package_type": "SCIMED_REVIEW_DISCOVERY_CHATGPT_REVIEW",
                            "scope": "REVIEW_TOPIC_DISCOVERY_ONLY",
                            "options": [],
                            "provisional_options": [],
                            "selection_policy": {
                                "desired_options": job.final_options,
                                "available_options": 0,
                                "shortfall": job.final_options,
                                "comparison_ready": False,
                            },
                        },
                        "run_summary": {
                            "generated_candidates": 0,
                            "verified_candidates": 0,
                            "status_counts": {},
                            "candidate_audits": [],
                            "recent_topics_skipped": recently_skipped[:40],
                            "recent_topics_skipped_count": len(recently_skipped),
                            "revisit_days": job.revisit_days,
                            "message": "Only recently checked questions were generated. No redundant literature searches were run.",
                        },
                    }
                raise RuntimeError("Candidate generation produced no new review topics")

            # Persist completed candidate proposals before slower source checks.
            # A failed later stage must not discard all generated ideas.
            store.update_job(
                job.id,
                result_json={
                    "checkpoint": {
                        "stage": "CANDIDATE_GENERATION",
                        "verified": False,
                        "note": "AI-generated hypotheses. Novelty, eligibility and source coverage are not verified.",
                        "candidate_count": len(candidates),
                        "recent_pubmed_cues": evidence_cues,
                        "candidates": [
                            {
                                "candidate_id": candidate.candidate_id,
                                "title": candidate.title,
                                "specialty": candidate.specialty,
                                "question_type": candidate.question_type,
                                "review_question": candidate.review_question,
                                "population": candidate.population,
                                "intervention_exposure_index_test": candidate.intervention_exposure_index_test,
                                "comparator_reference": candidate.comparator_reference,
                                "outcomes": list(candidate.outcomes or []),
                                "eligible_designs": list(candidate.eligible_designs or []),
                                "rationale": candidate.rationale,
                                "novelty_hypothesis": candidate.novelty_hypothesis,
                                "search_terms": list(candidate.search_terms or []),
                                "qualification_status": "AI_DRAFT_NOT_SOURCE_VERIFIED",
                            }
                            for candidate in candidates
                        ],
                    }
                },
            )

            store.update_job(
                job.id,
                stage="DISCOVERY_RANKING",
                progress=18,
                message=f"Generated {len(candidates)} topics; ranking them for verification",
            )

            novelty = DiscoveryNoveltyService(
                ledger,
                SemanticCompetitorAssessor(provider),
                search_date_resolver=OpenAccessSearchDateResolver(),
                max_fulltext_reviews=2,
            )
            scoring = DiscoveryScoringService(provider)

            def progress_callback(progress: int, stage: str, message: str) -> None:
                store.ensure_active(job.id)
                store.update_job(
                    job.id,
                    stage=stage,
                    progress=progress,
                    message=message,
                )

            source_clients = build_default_source_clients()
            pubmed_client = next(
                (source for source in source_clients if source.name == "PubMed"), None
            )
            preflight = (
                FocusedEvidencePreflight(pubmed_client, max_candidates=24, per_query=10)
                if pubmed_client is not None else None
            )
            orchestrator = ReviewDiscoveryOrchestrator(
                ledger,
                source_clients,
                novelty_service=novelty,
                scoring_service=scoring,
                progress_callback=progress_callback,
                cancellation_check=lambda: store.ensure_active(job.id),
                evidence_preflight=preflight,
            )
            result = orchestrator.run(
                project_id,
                min_verify=job.min_verify,
                max_verify=job.max_verify,
                final_options=job.final_options,
                limit_per_query=job.limit_per_query,
                adaptive_extra=min(4, max(2, job.max_verify // 2)),
            )
            store.ensure_active(job.id)
            package = build_discovery_review_package(ledger, result)
            # Retain all fully parsed scientific PICO drafts even when the free
            # verification budget checked only the top six. These other drafts
            # are NOT novelty-cleared options and must never be counted as
            # screened eligible studies or qualified recommendations.
            checked_ids = {item.candidate_id for item in result.verified}
            unverified_drafts = _unverified_topic_options(candidates, checked_ids)
            package["unverified_generated_options"] = unverified_drafts
            package["unverified_generated_options_are_not_qualified"] = True

            status_counts: dict[str, int] = {}
            for item in result.verified:
                key = item.candidate_status.value
                status_counts[key] = status_counts.get(key, 0) + 1

            candidate_audits = []
            for verified in result.verified:
                checked = ledger.get_candidate(verified.candidate_id)
                scorecard = dict((checked.metadata or {}).get("discovery_gate_inputs") or {}) if checked else {}
                failed_gates = [
                    {"name": gate.get("name"), "requirement": gate.get("requirement")}
                    for gate in (verified.final_gate_result or {}).get("gates", [])
                    if gate.get("passed") is False
                ]
                candidate_audits.append({
                    "candidate_id": verified.candidate_id,
                    "title": checked.title if checked else verified.candidate_id,
                    "status": verified.candidate_status.value,
                    "decision": verified.decision,
                    "preflight": dict((checked.metadata or {}).get("evidence_preflight") or {}) if checked else {},
                    "pending": list(verified.pending)[:12],
                    "failed_gates": failed_gates,
                    "coverage_blockers": list(verified.coverage.blockers),
                    "coverage_warnings": list(verified.coverage.warnings),
                    "source_diagnostics": [
                        {
                            "source": log.source,
                            "status": log.status.value,
                            "query": log.query[:120],
                            "message": log.message[:280],
                        }
                        for log in ledger.list_search_log(verified.candidate_id)
                        if log.status.value in ("ACCESS_FAILED", "PARTIAL")
                    ][:12],
                    "source_statuses": {
                        name: status.value
                        for name, status in verified.coverage.source_statuses.items()
                    },
                    "unique_primary_study_candidates": verified.evidence.unique_primary_study_candidates,
                    "scorecard": scorecard,
                    "registration_age_audit": (
                        (checked.metadata or {}).get("discovery_registration_age_audit") or []
                    ) if checked else [],
                    "published_review_update_audit": (
                        (checked.metadata or {}).get("discovery_published_review_update_audit") or []
                    ) if checked else [],
                    "fulltext_search_date_resolutions": (
                        (checked.metadata or {}).get("discovery_fulltext_search_date_resolutions") or []
                    ) if checked else [],
                    "potential_fatal_review_overlap_ids": (
                        (checked.metadata or {}).get("discovery_potential_fatal_review_overlap_ids") or []
                    ) if checked else [],
                })

            result_json = {
                "package": package,
                "run_summary": {
                    "generated_candidates": len(candidates),
                    "unverified_generated_candidates": len(unverified_drafts),
                    "bibliographic_preflight": result.bibliographic_preflight_summary,
                    "adaptive_deep_checks_used": result.adaptive_deep_checks_used,
                    "adaptive_checks_skipped_reason": result.adaptive_checks_skipped_reason,
                    "requested_candidates": job.candidate_count,
                    "generation_shortfall": max(0, job.candidate_count - len(candidates)),
                    "generation_warnings": generator.generation_warnings[:5],
                    "verified_candidates": len(result.verified),
                    "qualified_candidate_ids": result.qualified_option_candidate_ids,
                    "final_option_candidate_ids": result.final_option_candidate_ids,
                    "desired_options": result.desired_options,
                    "status_counts": status_counts,
                    "candidate_audits": candidate_audits,
                    "initial_deep_verify_budget": job.max_verify,
                    "bibliographic_preflight": result.bibliographic_preflight_summary,
                    "adaptive_deep_checks_used": result.adaptive_deep_checks_used,
                    "adaptive_checks_skipped_reason": result.adaptive_checks_skipped_reason,
                    "duplicate_topics_skipped": result.duplicate_topics_skipped,
                    "duplicate_topics_skipped_count": len(result.duplicate_topics_skipped),
                    "recent_pubmed_cues": evidence_cues,
                    "published_review_gap_cues": review_gap_cues,
                    "ai_failover_count": provider.total_failover_count,
                    "configured_free_ai_route": provider.configured_free_route,
                    "unavailable_free_providers": provider.unavailable_free_providers,
                    "last_ai_provider": provider.last_provider,
                    "recent_topics_skipped": recently_skipped[:40],
                    "recent_topics_skipped_count": len(recently_skipped),
                    "revisit_days": job.revisit_days,
                    "topic_history": [
                        {
                            "candidate_id": item.candidate_id,
                            "title": checked.title,
                            "specialty": checked.specialty,
                            "question_type": checked.question_type,
                            "population": checked.population,
                            "intervention_exposure_index_test": checked.intervention_exposure_index_test,
                            "comparator_reference": checked.comparator_reference,
                            "outcomes": checked.outcomes,
                            "eligible_designs": checked.eligible_designs,
                            "status": item.candidate_status.value,
                            "checked_at": datetime.now(timezone.utc).isoformat(),
                        }
                        for item in result.verified
                        if (checked := ledger.get_candidate(item.candidate_id)) is not None
                    ],
                },
            }
            return result_json


def run_once(store: SupabaseJobStore | None = None) -> int:
    store = store or SupabaseJobStore.from_env()
    store.recover_stale_jobs()
    job = store.claim_next()
    if job is None:
        print(json.dumps({"status": "IDLE", "message": "No queued discovery jobs"}))
        return 0

    print(json.dumps({"status": "RUNNING", "job_id": job.id}))
    try:
        result_json = process_job(job, store)
        options = len((result_json.get("package") or {}).get("options") or [])
        store.complete(
            job.id,
            result_json,
            f"Discovery complete with {options} qualified first-choice topic(s)",
        )
        print(json.dumps({"status": "COMPLETED", "job_id": job.id, "qualified_options": options}))
        return 0
    except JobCancelled:
        print(json.dumps({"status": "CANCELLED", "job_id": job.id}))
        return 0
    except Exception as exc:
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        try:
            # Keep any previously saved literature checkpoint on error.
            # A FAILED run may still contain useful PubMed leads to inspect.
            store.fail(job.id, detail)
        except JobCancelled:
            print(json.dumps({"status": "CANCELLED", "job_id": job.id}))
            return 0
        print(json.dumps({"status": "FAILED", "job_id": job.id, "error": str(exc)}))
        return 1


def main() -> None:
    raise SystemExit(run_once())


if __name__ == "__main__":
    main()
