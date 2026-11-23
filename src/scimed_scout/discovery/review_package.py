from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scimed_scout.storage import SQLiteLedger

from .models import DiscoveryRunResult
from .topic_diversity import same_clinical_question


CHATGPT_REVIEW_INSTRUCTIONS = """You are the independent final reviewer of systematic-review topic options.
Every included option has passed the discovery-only FIRST-CHOICE topic standard. The Scout has assessed
question coherence, novelty, competing published reviews, review registrations, source coverage, clinical
importance, publication potential, and discovery feasibility, and it has found at least four unique candidate
primary studies. The Scout has NOT performed full-text eligibility screening, data extraction, risk of bias,
study-family adjudication, or meta-analysis. Compare the supplied review topics and select the strongest one
to take forward for a full systematic review. Rank all options and explain the decisive differences."""


def build_discovery_review_package(
    ledger: SQLiteLedger,
    result: DiscoveryRunResult,
) -> dict[str, Any]:
    project = ledger.get_project(result.project_id)
    if project is None:
        raise ValueError(f"Project not found: {result.project_id}")

    verification_by_id = {item.candidate_id: item for item in result.verified}
    ranking_by_id = {item.candidate_id: item for item in result.ranked}
    options: list[dict[str, Any]] = []

    for candidate_id in result.final_option_candidate_ids:
        candidate = ledger.get_candidate(candidate_id)
        verification = verification_by_id.get(candidate_id)
        if candidate is None or verification is None:
            continue

        gate_result = verification.final_gate_result or {}
        if not (
            candidate.status.value == "QUALIFIED"
            and verification.decision == "QUALIFIED — FIRST-CHOICE REVIEW TOPIC"
            and not verification.pending
            and gate_result.get("all_discovery_gates_passed") is True
            and not gate_result.get("unresolved_type_a")
        ):
            continue

        ranking = ranking_by_id.get(candidate_id)
        reviews = ledger.list_external_evidence(candidate_id, "PUBLISHED_REVIEW")
        registrations = ledger.list_external_evidence(candidate_id, "REGISTRATION")
        primary = ledger.list_external_evidence(candidate_id, "PRIMARY_STUDY")
        decisions = ledger.list_decisions(candidate_id)

        options.append({
            "option_number": len(options) + 1,
            "candidate_id": candidate_id,
            "title": candidate.title,
            "specialty": candidate.specialty,
            "question_type": candidate.question_type,
            "review_question": candidate.review_question,
            "population": candidate.population,
            "intervention_exposure_index_test": candidate.intervention_exposure_index_test,
            "comparator_reference": candidate.comparator_reference,
            "outcomes": candidate.outcomes,
            "eligible_designs": candidate.eligible_designs,
            "rationale": candidate.rationale,
            "novelty_hypothesis": candidate.novelty_hypothesis,
            "preliminary_ranking": {
                "score": ranking.score if ranking else None,
                "reasons": list(ranking.reasons) if ranking else [],
                "role": "verification priority only",
            },
            "discovery_evidence": asdict(verification.evidence),
            "coverage": {
                "source_statuses": {
                    k: v.value for k, v in verification.coverage.source_statuses.items()
                },
                "warnings": list(verification.coverage.warnings),
            },
            "published_review_hits": len(reviews),
            "registration_hits": len(registrations),
            "raw_primary_records": len(primary),
            "discovery_gate_result": verification.final_gate_result,
            "latest_decision": (
                {
                    "decision": decisions[-1].decision,
                    "reason": decisions[-1].reason,
                    "payload": decisions[-1].payload,
                }
                if decisions
                else None
            ),
        })

    # Preserve useful follow-up candidates without mislabeling them as
    # scientifically qualified. Source gaps and all PICO details travel with
    # each provisional option for independent verification.
    provisional_options: list[dict[str, Any]] = []
    ordered_unresolved = sorted(
        (item for item in result.verified if item.candidate_status.value in
         {"PROVISIONAL_BACKUP", "DEEP_VERIFYING"}),
        key=lambda item: (
            (ranking_by_id.get(item.candidate_id).score if ranking_by_id.get(item.candidate_id) else 0),
            item.evidence.unique_primary_study_candidates,
        ),
        reverse=True,
    )
    for verified in ordered_unresolved[:6]:
        candidate = ledger.get_candidate(verified.candidate_id)
        if candidate is None:
            continue
        # A second safety layer: never present near-identical provisional
        # topics as two independent research opportunities in the export.
        if any(same_clinical_question(candidate, prior)
               for prior in provisional_options):
            continue
        metadata = candidate.metadata or {}
        provisional_options.append({
            "candidate_id": verified.candidate_id,
            "title": candidate.title,
            "specialty": candidate.specialty,
            "question_type": candidate.question_type,
            "review_question": candidate.review_question,
            "population": candidate.population,
            "intervention_exposure_index_test": candidate.intervention_exposure_index_test,
            "comparator_reference": candidate.comparator_reference,
            "outcomes": candidate.outcomes,
            "eligible_designs": candidate.eligible_designs,
            "provisional_only": True,
            "qualification_status": verified.candidate_status.value,
            "source_blockers": list(verified.coverage.blockers),
            "unresolved_checks": list(verified.pending),
            "source_statuses": {
                name: status.value for name, status in verified.coverage.source_statuses.items()
            },
            "discovered_primary_study_candidates": verified.evidence.unique_primary_study_candidates,
            "published_review_examples": [
                {
                    "title": str(record.get("title") or ""),
                    "source": str(record.get("source") or ""),
                    "doi": str((record.get("payload") or {}).get("doi") or ""),
                    "url": str((record.get("payload") or {}).get("url") or ""),
                    "record_id": str(record.get("source_record_id") or ""),
                }
                for record in ledger.list_external_evidence(verified.candidate_id, "PUBLISHED_REVIEW")[:5]
            ],
            "primary_study_examples": [
                {
                    "title": str(record.get("title") or ""),
                    "source": str(record.get("source") or ""),
                    "doi": str((record.get("payload") or {}).get("doi") or ""),
                    "url": str((record.get("payload") or {}).get("url") or ""),
                    "record_id": str(record.get("source_record_id") or ""),
                }
                for record in ledger.list_external_evidence(verified.candidate_id, "PRIMARY_STUDY")[:5]
            ],
            "preliminary_scoring": dict(metadata.get("discovery_gate_inputs") or {}),
            "decision": verified.decision,
            "next_action": "Manually verify source access, competing reviews, registrations and full-text eligibility before selecting this topic.",
        })

    return {
        "package_type": "SCIMED_REVIEW_DISCOVERY_CHATGPT_REVIEW",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "REVIEW_TOPIC_DISCOVERY_ONLY",
        "project": {
            "project_id": project.project_id,
            "specialty": project.specialty,
            "question_type": project.question_type,
        },
        "review_instructions": CHATGPT_REVIEW_INSTRUCTIONS,
        "selection_policy": {
            "system_does_not_select_winner": True,
            "all_included_options_are_first_choice_review_topics": True,
            "desired_options": result.desired_options,
            "available_options": len(options),
            "comparison_ready": len(options) >= 2,
            "shortfall": max(0, result.desired_options - len(options)),
            "minimum_unique_primary_study_candidates": 4,
            "full_review_execution_out_of_scope": True,
            "chatgpt_is_final_comparator": True,
        },
        "options": options,
        "provisional_options": provisional_options,
        "provisional_options_are_not_qualified": True,
        "duplicate_topics_skipped": result.duplicate_topics_skipped,
        "duplicate_topics_skipped_count": len(result.duplicate_topics_skipped),
        "provisional_leads_are_not_validated_novelty": True,
    }


def export_discovery_review_package(
    ledger: SQLiteLedger,
    result: DiscoveryRunResult,
    path: str | Path,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            build_discovery_review_package(ledger, result),
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return target
