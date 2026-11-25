from __future__ import annotations

import json
import re
import os
import tempfile
import traceback
import time
from pathlib import Path
from typing import Any
from datetime import datetime, timezone
from dataclasses import asdict
from .checkpoints import GENERATION, AUDIT_PREFIX, draft_from_saved, audit_snapshot, restore_audit
from scimed_scout.sources.europe_pmc import EuropePMCSource
from scimed_scout.diagnostics import exception_diagnostic
from scimed_scout.run_telemetry import MeteredDiscoveryProvider, aggregate, incident, write_report

from scimed_scout.ai import CandidateDiscoveryService, FreeProviderFallback
from scimed_scout.competitors import SemanticCompetitorAssessor
from scimed_scout.discovery.topic_memory import (
    recent_topic_memory, recent_generated_topic_memory,
    saturated_intervention_themes, filter_saturated_evidence_cues,
)
from scimed_scout.discovery.open_access_dates import OpenAccessSearchDateResolver
from scimed_scout.discovery.evidence_first import collect_evidence_map, evidence_map_prompt, link_candidate
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
            "evidence_first_link": dict((candidate.metadata or {}).get("evidence_first_link") or {}),
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



def _within_specialty(candidate, specialty: str) -> bool:
    """Operational scope guard, not scientific eligibility screening."""
    scope = specialty.strip().casefold()
    if scope == "all":
        return True
    declared = str(candidate.specialty or "").casefold()
    text = " ".join([candidate.title, candidate.review_question, candidate.population,
                     candidate.intervention_exposure_index_test, " ".join(candidate.outcomes or [])])
    if scope == "cardiology":
        # NLM MeSH C14-inspired clinical anchors. Exclude generic ventilation,
        # physical fitness and generic stroke unless the PICO itself addresses
        # a cardiovascular condition, treatment or outcome.
        anchor = re.compile(
            r"\b(?:cardiac|cardiovascular|cardiomyopath\w*|cardiotoxic\w*|"
            r"cardiometabolic|cardiorenal|heart|coronary|atrial|ventricular|myocard\w*|"
            r"arrhythm\w*|aort\w*|valv\w*|hypertension|blood pressure|"
            r"dyslipid\w*|hyperlipid\w*|cholesterol|atheroscler\w*|"
            r"tavr|tavi|hfpef|hfref|cabg|pci|ecg|echocardiogra\w*|"
            r"pericardi\w*|endocardi\w*|peripheral arter\w*|"
            r"ldl|hdl|mace|cardio-oncology)\b", re.I)
        return bool(anchor.search(text))
    return scope in declared or declared in scope and bool(declared)

def process_job(job: DiscoveryJob, store: SupabaseJobStore) -> dict[str, Any]:
    store.ensure_active(job.id)
    history_rows = store.recent_completed_jobs(
        client_token_hash=job.client_token_hash,
        revisit_days=job.revisit_days,
    )
    print(json.dumps({"status": "TOPIC_HISTORY_LOADED", "job_id": job.id,
                      "history_jobs": len(history_rows),
                      "history_warning": getattr(store, "history_warning", "")}), flush=True)
    prior_topics = recent_topic_memory(history_rows, revisit_days=job.revisit_days)
    generated_history = recent_generated_topic_memory(
        history_rows, revisit_days=job.revisit_days,
    )
    saturated_themes = saturated_intervention_themes(generated_history)
    # The same broad "latest PubMed" search kept feeding Ketone Monoester
    # and exercise-trial titles into every Cardiology batch. Rotate the
    # search subject across clinical subfields by recent completed run count.
    seed_rotation_index = len(history_rows)
    recently_skipped: list[dict[str, Any]] = []
    provider = MeteredDiscoveryProvider(FreeProviderFallback.from_env())
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

            saved_generation = store.load_step(job.id, GENERATION)
            if not saved_generation:
                legacy = store.legacy_checkpoint(job.id)
                if legacy.get("candidates"):
                    saved_generation = {"version": 1, "job_id": job.id, "candidates": legacy["candidates"],
                                        "recent_pubmed_cues": legacy.get("recent_pubmed_cues", []),
                                        "published_review_gap_cues": legacy.get("published_review_gap_cues", [])}
            if saved_generation and (saved_generation.get("version") != 1 or saved_generation.get("job_id") != job.id):
                raise RuntimeError("Saved generation checkpoint has incompatible scope")
            store.update_job(
                job.id,
                stage="CANDIDATE_GENERATION",
                progress=5,
                message="Generating review-topic candidates",
            )
            generator = CandidateDiscoveryService(provider, ledger)
            if saved_generation and saved_generation.get("candidates"):
                evidence_cues = saved_generation.get("recent_pubmed_cues") or []
                review_gap_cues = saved_generation.get("published_review_gap_cues") or []
                evidence_map = saved_generation.get("evidence_first_map") or {}
                deferred_seed_cues = []
                candidates = []
                for row in saved_generation["candidates"]:
                    candidate = draft_from_saved(row, project_id)
                    if candidate.title and candidate.population and candidate.intervention_exposure_index_test:
                        ledger.upsert_candidate(candidate)
                        candidates.append(candidate)
                generator.generation_warnings = ["Resumed saved PICO drafts; no repeat AI generation."]
                print(json.dumps({"status": "GENERATION_REUSED", "job_id": job.id,
                                  "candidates": len(candidates)}), flush=True)
            else:
                saved_seeds = store.load_step(job.id, "evidence-seed:v1")
                if saved_seeds:
                    if saved_seeds.get("job_id") != job.id or saved_seeds.get("version") != 1:
                        raise RuntimeError("Evidence seed checkpoint scope/version mismatch")
                    evidence_cues = saved_seeds.get("recent_pubmed_cues") or []
                    review_gap_cues = saved_seeds.get("published_review_gap_cues") or []
                    evidence_map = saved_seeds.get("evidence_first_map") or {}
                    deferred_seed_cues = saved_seeds.get("deferred_seed_cues") or []
                else:
                    # Spread source-grounded brainstorming over independent clinical
                    # subfields; do not spend the whole run on one latest-paper theme.
                    rotations = (seed_rotation_index, seed_rotation_index + 3, seed_rotation_index + 6) if job.specialty.casefold() == "cardiology" else (seed_rotation_index,)
                    raw_evidence_cues = [
                        cue for rotation in rotations
                        for cue in recent_pubmed_cues(
                            job.specialty, job.question_type, rotation_index=rotation,
                            max_records=6 if len(rotations) > 1 else 12,
                        )
                    ]
                    raw_evidence_cues = list({str(cue.get("pmid") or cue.get("title")): cue
                                              for cue in raw_evidence_cues}.values())
                    evidence_cues, deferred_seed_cues = filter_saturated_evidence_cues(
                        raw_evidence_cues, saturated_themes,
                    )
                    # Campbell/3ie-style evidence-gap cues from *actual review
                    # abstracts*, not model-generated claims of novelty. One free
                    # Europe PMC query, with a safe empty result on source outages.
                    review_gap_cues = [
                        cue for rotation in rotations
                        for cue in recent_review_gap_cues(
                            job.specialty, job.question_type, max_records=2 if len(rotations) > 1 else 5,
                            rotation_index=rotation,
                        )
                    ]
                    review_gap_cues = list({str(cue.get("pmid") or cue.get("title")): cue
                                            for cue in review_gap_cues}.values())
                    evidence_map = collect_evidence_map(job.specialty, job.question_type,
                        rotation_index=seed_rotation_index, cancellation_check=lambda: store.ensure_active(job.id))
                    store.save_step(job.id, "evidence-seed:v1", {
                        "version": 1, "job_id": job.id, "recent_pubmed_cues": evidence_cues,
                        "published_review_gap_cues": review_gap_cues, "evidence_first_map": evidence_map,
                        "deferred_seed_cues": deferred_seed_cues,
                    })
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
                            "evidence_first_map": evidence_map,
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
                        evidence_map_prompt(evidence_map) + "\n" + cue_prompt(evidence_cues) + "\n" + review_gap_prompt(review_gap_cues)
                    ).strip(),
                    progress_callback=generation_progress,
                    recent_topics=prior_topics,
                    generated_history=generated_history,
                    skipped_recent=recently_skipped,
                )
            store.ensure_active(job.id)
            for candidate in candidates:
                candidate.metadata = {**(candidate.metadata or {}),
                    "evidence_first_link": link_candidate(candidate, evidence_map)}
                ledger.upsert_candidate(candidate)
            outside_scope = [candidate for candidate in candidates if not _within_specialty(candidate, job.specialty)]
            if outside_scope:
                from scimed_scout.domain import CandidateStatus
                for candidate in outside_scope:
                    ledger.set_candidate_status(candidate.candidate_id, CandidateStatus.REJECTED)
                candidates = [candidate for candidate in candidates if _within_specialty(candidate, job.specialty)]
                generator.generation_warnings.append(
                    f"Skipped {len(outside_scope)} off-specialty proposals before source verification."
                )
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
                            "requested_candidates": job.candidate_count,
                            "off_scope_skipped_count": len(outside_scope),
                            "ai_telemetry": provider.snapshot(),
                            "verified_candidates": 0,
                            "status_counts": {},
                            "candidate_audits": [],
                            "recent_topics_skipped": recently_skipped[:40],
                            "recent_topics_skipped_count": len(recently_skipped),
                            "revisit_days": job.revisit_days,
                            "message": "Only previously explored or recently checked questions were generated. No redundant literature searches were run.",
                        },
                    }
                raise RuntimeError("Candidate generation produced no new review topics")

            # Durable generation snapshot precedes any deep verification.
            store.save_step(job.id, GENERATION, {
                "version": 1, "job_id": job.id,
                "candidates": [asdict(candidate) for candidate in candidates],
                "recent_pubmed_cues": evidence_cues,
                "published_review_gap_cues": review_gap_cues,
                "evidence_first_map": evidence_map,
            })
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
                max_fulltext_reviews=3,
                max_reviews=18,
                max_registrations=12,
                batch_size=3,
                enrichment_client=EuropePMCSource(),
                max_enrichment_lookups=2,
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

            resumed = []
            candidate_ids = {c.candidate_id for c in candidates}
            for key in store.checkpoint_keys(job.id):
                if not key.startswith(AUDIT_PREFIX):
                    continue
                cid = key.removeprefix(AUDIT_PREFIX)
                if cid not in candidate_ids:
                    continue
                snapshot = store.load_step(job.id, key)
                if snapshot:
                    resumed.append(restore_audit(ledger, snapshot, project_id, cid))
            print(json.dumps({"status": "AUDITS_RESTORED", "job_id": job.id, "count": len(resumed)}), flush=True)
            completed_audits = {item.candidate_id: {
                "candidate_id": item.candidate_id, "status": item.candidate_status.value,
                "decision": item.decision, "pending": list(item.pending),
                "source_statuses": {k: v.value for k, v in item.coverage.source_statuses.items()},
            } for item in resumed}
            def save_candidate_checkpoint(item):
                store.save_step(job.id, AUDIT_PREFIX + item.candidate_id, audit_snapshot(ledger, item))
                completed_audits[item.candidate_id] = {
                    "candidate_id": item.candidate_id,
                    "status": item.candidate_status.value,
                    "decision": item.decision,
                    "pending": list(item.pending),
                    "source_statuses": {k: v.value for k, v in item.coverage.source_statuses.items()},
                }
                # Keep compact source audit checkpoints and all generated PICOs;
                # these are not complete dossiers or confirmed eligibility.
                store.update_job(job.id, result_json={"checkpoint": {
                    "stage": "REVIEW_DISCOVERY", "verified": False,
                    "recent_pubmed_cues": evidence_cues,
                    "published_review_gap_cues": review_gap_cues,
                    "candidates": _unverified_topic_options(candidates, set()),
                    "completed_candidate_audits": list(completed_audits.values()),
                }})

            source_clients = build_default_source_clients()
            pubmed_client = next(
                (source for source in source_clients if source.name == "PubMed"), None
            )
            preflight = (
                FocusedEvidencePreflight(
                    pubmed_client, max_candidates=20, per_query=10,
                    pause_seconds=1.0, review_risk_preflight=True,
                )
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
                candidate_checkpoint=save_candidate_checkpoint,
                resumed_results=resumed,
                require_pico_signals=True,
            )
            result = orchestrator.run(
                project_id,
                min_verify=job.min_verify,
                max_verify=job.max_verify,
                final_options=job.final_options,
                limit_per_query=job.limit_per_query,
                adaptive_extra=min(4, max(2, job.max_verify // 2)),
                recovery_pass=True,
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
                    "conservative_family_lead_count": verified.evidence.conservative_family_lead_count,
                    "registry_linked_families": verified.evidence.trial_family_audit.get("registry_linked_families"),
                    "pico_design_family_leads": verified.evidence.pico_audit.get("pico_design_family_leads"),
                    "pico_screening_status_counts": verified.evidence.pico_audit.get("status_counts", {}),
                    "scorecard": scorecard,
                    "review_opportunity": ((checked.metadata or {}).get("discovery_review_opportunity") or {}) if checked else {},
                    "competitor_audit": ({
                        "published_reviews_discovered": (checked.metadata or {}).get(
                            "discovery_competitor_records_discovered", 0
                        ),
                        "published_reviews_semantically_resolved": (checked.metadata or {}).get(
                            "discovery_competitor_resolved_count", 0
                        ),
                        "registrations_discovered": (checked.metadata or {}).get(
                            "discovery_registration_records_discovered", 0
                        ),
                        "registrations_semantically_resolved": (checked.metadata or {}).get(
                            "discovery_registration_resolved_count", 0
                        ),
                        "unassessed_reviews": (checked.metadata or {}).get(
                            "discovery_unassessed_review_count", 0
                        ),
                        "unassessed_registrations": (checked.metadata or {}).get(
                            "discovery_unassessed_registration_count", 0
                        ),
                        "review_queue": (checked.metadata or {}).get(
                            "discovery_unassessed_review_queue", []
                        ),
                        "registration_queue": (checked.metadata or {}).get(
                            "discovery_unassessed_registration_queue", []
                        ),
                        "queue_truncated": (checked.metadata or {}).get(
                            "discovery_unassessed_queue_truncated", False
                        ),
                    } if checked else {}),
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
                    "off_scope_skipped_count": len(outside_scope),
                    "ai_telemetry": provider.snapshot(),
                    "resumed_completed_audits": len(resumed),
                    "reused_generation": bool(saved_generation),
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
                    "evidence_first_map": evidence_map,
                    "source_cluster_anchored_candidates": sum(bool((c.metadata or {}).get("evidence_first_link", {}).get("links")) for c in candidates),
                    "seed_rotation_index": seed_rotation_index,
                    "saturated_prior_intervention_themes": saturated_themes[:20],
                    "deferred_repeated_seed_cues": deferred_seed_cues[:20],
                    "deferred_repeated_seed_cue_count": len(deferred_seed_cues),
                    "prior_generated_topic_count": len(generated_history),
                    "history_warning": getattr(store, "history_warning", ""),
                    "generated_topic_history": [
                        {
                            "candidate_id": item.candidate_id,
                            "title": item.title,
                            "specialty": item.specialty,
                            "question_type": item.question_type,
                            "population": item.population,
                            "intervention_exposure_index_test": item.intervention_exposure_index_test,
                            "comparator_reference": item.comparator_reference,
                            "outcomes": item.outcomes,
                            "eligible_designs": item.eligible_designs,
                        }
                        for item in candidates
                    ],
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
    started = time.monotonic()
    try:
        result_json = process_job(job, store)
        options = len((result_json.get("package") or {}).get("options") or [])
        store.complete(
            job.id,
            result_json,
            f"Discovery complete with {options} qualified first-choice topic(s)",
        )
        try:
            write_report(aggregate(result_json,elapsed_seconds=time.monotonic()-started,
                requested=job.candidate_count,specialty=job.specialty,question_type=job.question_type))
        except Exception:
            print(json.dumps({"status":"TELEMETRY_AGGREGATE_FAILED"}))
        print(json.dumps({"status": "COMPLETED", "job_id": job.id, "qualified_options": options}))
        return 0
    except JobCancelled:
        write_report(incident("CANCELLED",time.monotonic()-started))
        print(json.dumps({"status": "CANCELLED", "job_id": job.id}))
        return 0
    except Exception as exc:
        write_report(incident("FAILED",time.monotonic()-started,exc))
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        try:
            # Keep any previously saved literature checkpoint on error.
            # A FAILED run may still contain useful PubMed leads to inspect.
            store.fail(job.id, detail)
        except JobCancelled:
            print(json.dumps({"status": "CANCELLED", "job_id": job.id}))
            return 0
        print(json.dumps({"status": "FAILED", "job_id": job.id, "diagnostic": exception_diagnostic(exc)}))
        return 1


def main() -> None:
    raise SystemExit(run_once())


if __name__ == "__main__":
    main()
