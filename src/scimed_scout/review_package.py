from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scimed_scout.storage import SQLiteLedger
from scimed_scout.verification.orchestrator import SequentialVerificationResult


CHATGPT_REVIEW_INSTRUCTIONS = """You are the independent final reviewer.
Compare the supplied systematic-review/meta-analysis options and select the strongest option.
Do not trust preliminary ranking alone. Prioritize verified evidence, novelty, methodological defensibility,
clinical importance, publication potential, source coverage, and absence of unresolved Type-A issues.
You may select one best option, rank all options, or conclude that none is ready.
Explain the decision and identify any final checks needed before protocol registration or full review work."""


def build_review_package(
    ledger: SQLiteLedger,
    result: SequentialVerificationResult,
) -> dict[str, Any]:
    project = ledger.get_project(result.project_id)
    if project is None:
        raise ValueError(f"Project not found: {result.project_id}")

    verification_by_id = {item.candidate_id: item for item in result.verified}
    ranking_by_id = {item.candidate_id: item for item in result.ranked}

    options: list[dict[str, Any]] = []
    for position, candidate_id in enumerate(result.final_option_candidate_ids, start=1):
        candidate = ledger.get_candidate(candidate_id)
        if candidate is None:
            continue
        verification = verification_by_id.get(candidate_id)
        ranking = ranking_by_id.get(candidate_id)

        published_reviews = ledger.list_external_evidence(candidate_id, "PUBLISHED_REVIEW")
        registrations = ledger.list_external_evidence(candidate_id, "REGISTRATION")
        ongoing = ledger.list_external_evidence(candidate_id, "ONGOING_STUDY")
        primary_hits = ledger.list_external_evidence(candidate_id, "PRIMARY_STUDY")
        decisions = ledger.list_decisions(candidate_id)

        options.append({
            "option_number": position,
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
            "candidate_status": candidate.status.value,
            "preliminary_ranking": {
                "score": ranking.score if ranking is not None else candidate.metadata.get("preliminary_ranking_score"),
                "reasons": list(ranking.reasons) if ranking is not None else candidate.metadata.get("preliminary_ranking_reasons", []),
                "role": "verification priority only, not final selection",
            },
            "verification": _verification_payload(verification),
            "evidence_discovery": {
                "primary_study_hits_discovered_unverified": len(primary_hits),
                "published_review_hits": len(published_reviews),
                "registration_hits": len(registrations),
                "ongoing_study_hits": len(ongoing),
            },
            "latest_decision": (
                {
                    "decision": decisions[-1].decision,
                    "stage": decisions[-1].stage,
                    "reason": decisions[-1].reason,
                    "payload": decisions[-1].payload,
                }
                if decisions else None
            ),
        })

    return {
        "package_type": "SCIMED_FINAL_CHATGPT_REVIEW",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": {
            "project_id": project.project_id,
            "specialty": project.specialty,
            "question_type": project.question_type,
        },
        "review_instructions": CHATGPT_REVIEW_INSTRUCTIONS,
        "selection_policy": {
            "system_does_not_select_winner": True,
            "desired_options": result.desired_options,
            "qualified_option_candidate_ids": result.qualified_option_candidate_ids,
            "final_option_candidate_ids": result.final_option_candidate_ids,
            "minimum_verified_independent_studies": 4,
            "minimum_verified_synthesis_usable_studies": 4,
            "chatgpt_is_final_comparator": True,
        },
        "options": options,
    }


def export_review_package(
    ledger: SQLiteLedger,
    result: SequentialVerificationResult,
    path: str | Path,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    package = build_review_package(ledger, result)
    target.write_text(json.dumps(package, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return target


def _verification_payload(verification) -> dict[str, Any] | None:
    if verification is None:
        return None
    return {
        "decision": verification.decision,
        "candidate_status": verification.candidate_status.value,
        "pending": list(verification.pending),
        "coverage": {
            "source_statuses": {k: v.value for k, v in verification.coverage.source_statuses.items()},
            "blockers": list(verification.coverage.blockers),
            "warnings": list(verification.coverage.warnings),
        },
        "evidence": asdict(verification.evidence),
        "final_gate_result": verification.final_gate_result,
    }
