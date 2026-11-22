from __future__ import annotations

import argparse
import json
import platform
import sys

from . import __version__
from .ai import CandidateDiscoveryService, OpenAICompatibleProvider
from .competitors import SemanticCompetitorAssessor
from .extraction import StudyEligibilityExtractor
from .synthesis import SynthesisDataExtractor
from .domain import CandidateStatus, SourceStatus
from .gates import final_decision
from .ranking import CandidateRankingService
from .review_package import export_review_package
from .sources import build_default_source_clients
from .storage import ProjectRecord, SQLiteLedger
from .verification import CandidateEvidenceAnalysisService, SequentialDeepVerifier, StudyVerificationBridge, SynthesisVerificationBridge


def health() -> dict[str, object]:
    return {
        "app": "SciMed SRMA Scout Cloud",
        "version": __version__,
        "python": platform.python_version(),
        "status": "OK",
        "source_statuses": [s.value for s in SourceStatus],
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="scimed-scout")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("health")

    gate = sub.add_parser("evaluate-gates")
    gate.add_argument("json_file")

    init_db = sub.add_parser("init-db")
    init_db.add_argument("db")

    create_project = sub.add_parser("create-project")
    create_project.add_argument("db")
    create_project.add_argument("project_id")
    create_project.add_argument("specialty")
    create_project.add_argument("--question-type", default="")

    list_projects = sub.add_parser("list-projects")
    list_projects.add_argument("db")

    list_candidates = sub.add_parser("list-candidates")
    list_candidates.add_argument("db")
    list_candidates.add_argument("project_id")
    list_candidates.add_argument("--status", choices=[x.value for x in CandidateStatus])

    set_status = sub.add_parser("set-candidate-status")
    set_status.add_argument("db")
    set_status.add_argument("candidate_id")
    set_status.add_argument("status", choices=[x.value for x in CandidateStatus])

    generate = sub.add_parser("generate-candidates")
    generate.add_argument("db")
    generate.add_argument("project_id")
    generate.add_argument("--count", type=int, default=10)
    generate.add_argument("--question-type", action="append", default=[])
    generate.add_argument("--design", action="append", default=[])
    generate.add_argument("--context", default="")
    generate.add_argument("--allow-rejected-revisit", action="store_true")

    rank = sub.add_parser("rank-candidates")
    rank.add_argument("db")
    rank.add_argument("project_id")
    rank.add_argument("--top", type=int, default=3)

    verify = sub.add_parser("deep-verify")
    verify.add_argument("db")
    verify.add_argument("project_id")
    verify.add_argument("--min-verify", type=int, default=3)
    verify.add_argument("--max-verify", type=int, default=10)
    verify.add_argument("--final-options", type=int, default=3)
    verify.add_argument("--limit-per-query", type=int, default=20)
    verify.add_argument("--review-package", default="")

    verify_one = sub.add_parser("verify-candidate")
    verify_one.add_argument("db")
    verify_one.add_argument("candidate_id")
    verify_one.add_argument("--limit-per-query", type=int, default=20)

    analyze = sub.add_parser("analyze-evidence")
    analyze.add_argument("db")
    analyze.add_argument("candidate_id")
    analyze.add_argument("--force", action="store_true")

    verify_studies = sub.add_parser("verify-studies")
    verify_studies.add_argument("db")
    verify_studies.add_argument("candidate_id")

    manual_study = sub.add_parser("manual-verify-study")
    manual_study.add_argument("db")
    manual_study.add_argument("candidate_id")
    manual_study.add_argument("study_id")
    manual_study.add_argument("status", choices=["ELIGIBLE", "INELIGIBLE"])
    manual_study.add_argument("--design", default="")
    manual_study.add_argument("--reason", default="")

    family_link = sub.add_parser("resolve-family-link")
    family_link.add_argument("db")
    family_link.add_argument("candidate_id")
    family_link.add_argument("study_a")
    family_link.add_argument("study_b")
    family_link.add_argument("resolution", choices=["SAME_FAMILY", "DISTINCT_FAMILIES"])
    family_link.add_argument("--reason", default="")

    synth = sub.add_parser("verify-synthesis")
    synth.add_argument("db")
    synth.add_argument("candidate_id")
    synth.add_argument("--force", action="store_true")

    args = parser.parse_args()

    if args.command == "health":
        print(json.dumps(health(), indent=2))
        return

    if args.command == "evaluate-gates":
        with open(args.json_file, encoding="utf-8") as handle:
            payload = json.load(handle)
        print(json.dumps(final_decision(payload), ensure_ascii=False, indent=2, default=str))
        return

    if args.command == "init-db":
        with SQLiteLedger(args.db):
            pass
        print(json.dumps({"status": "OK", "db": args.db}, indent=2))
        return

    if args.command == "create-project":
        with SQLiteLedger(args.db) as ledger:
            ledger.upsert_project(
                ProjectRecord(
                    project_id=args.project_id,
                    specialty=args.specialty,
                    question_type=args.question_type,
                )
            )
        print(json.dumps({"status": "OK", "project_id": args.project_id}, indent=2))
        return

    if args.command == "list-projects":
        with SQLiteLedger(args.db) as ledger:
            projects = ledger.list_projects()
        print(json.dumps([_project_json(x) for x in projects], ensure_ascii=False, indent=2))
        return

    if args.command == "list-candidates":
        status = CandidateStatus(args.status) if args.status else None
        with SQLiteLedger(args.db) as ledger:
            candidates = ledger.list_candidates(args.project_id, status)
        print(json.dumps([_candidate_json(x) for x in candidates], ensure_ascii=False, indent=2))
        return

    if args.command == "set-candidate-status":
        with SQLiteLedger(args.db) as ledger:
            if ledger.get_candidate(args.candidate_id) is None:
                raise SystemExit(f"Candidate not found: {args.candidate_id}")
            ledger.set_candidate_status(args.candidate_id, CandidateStatus(args.status))
        print(json.dumps({"status": "OK", "candidate_id": args.candidate_id, "candidate_status": args.status}, indent=2))
        return

    if args.command == "generate-candidates":
        with SQLiteLedger(args.db) as ledger:
            project = ledger.get_project(args.project_id)
            if project is None:
                raise SystemExit(f"Project not found: {args.project_id}")

            provider = OpenAICompatibleProvider.from_env()
            service = CandidateDiscoveryService(provider, ledger)
            records = service.generate_and_store(
                project_id=project.project_id,
                specialty=project.specialty,
                question_types=args.question_type or ([project.question_type] if project.question_type else []),
                design_scope=args.design,
                count=args.count,
                additional_context=args.context,
                allow_rejected_revisit=args.allow_rejected_revisit,
            )
            ledger.update_checkpoint(
                project.project_id,
                stage="DISCOVERY",
                progress=15,
                message=f"{len(records)} candidate proposals stored",
            )

        print(json.dumps([_candidate_json(x) for x in records], ensure_ascii=False, indent=2))
        return

    if args.command == "rank-candidates":
        with SQLiteLedger(args.db) as ledger:
            if ledger.get_project(args.project_id) is None:
                raise SystemExit(f"Project not found: {args.project_id}")
            ranked = CandidateRankingService(ledger).rank_project(args.project_id, top_n=args.top)
            ledger.update_checkpoint(
                args.project_id,
                stage="RANKING",
                progress=20,
                message=f"Ranked {len(ranked)} candidates; top {args.top} shortlisted",
            )
        print(json.dumps([
            {
                "candidate_id": item.candidate_id,
                "score": item.score,
                "reasons": list(item.reasons),
            }
            for item in ranked
        ], ensure_ascii=False, indent=2))
        return

    if args.command == "deep-verify":
        with SQLiteLedger(args.db) as ledger:
            verifier = SequentialDeepVerifier(
                ledger,
                build_default_source_clients(),
                evidence_analysis_service=_optional_evidence_analysis_service(ledger),
                study_verification_bridge=StudyVerificationBridge(ledger),
                synthesis_verification_bridge=_optional_synthesis_bridge(ledger),
            )
            result = verifier.run(
                args.project_id,
                min_verify=args.min_verify,
                max_verify=args.max_verify,
                final_options=args.final_options,
                limit_per_query=args.limit_per_query,
            )
            review_path = args.review_package or f"data/{args.project_id}_chatgpt_review.json"
            export_review_package(ledger, result, review_path)
        payload = _sequential_verification_json(result)
        payload["review_package_path"] = review_path
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if args.command == "verify-candidate":
        with SQLiteLedger(args.db) as ledger:
            verifier = SequentialDeepVerifier(
                ledger,
                build_default_source_clients(),
                evidence_analysis_service=_optional_evidence_analysis_service(ledger),
            )
            result = verifier.verify_candidate(
                args.candidate_id,
                limit_per_query=args.limit_per_query,
            )
        print(json.dumps(_candidate_verification_json(result), ensure_ascii=False, indent=2))
        return

    if args.command == "analyze-evidence":
        with SQLiteLedger(args.db) as ledger:
            service = _required_evidence_analysis_service(ledger)
            summary = service.analyze_candidate(args.candidate_id, force=args.force)
        print(json.dumps({
            "candidate_id": summary.candidate_id,
            "published_reviews_assessed": summary.published_reviews_assessed,
            "published_reviews_unresolved": summary.published_reviews_unresolved,
            "fatal_redundancy": summary.fatal_redundancy,
            "registrations_assessed": summary.registrations_assessed,
            "registrations_unresolved": summary.registrations_unresolved,
            "material_registration_overlaps": list(summary.material_registration_overlaps),
            "primary_studies_extracted": summary.primary_studies_extracted,
            "auto_eligible_studies": summary.auto_eligible_studies,
            "auto_ineligible_studies": summary.auto_ineligible_studies,
            "auto_uncertain_studies": summary.auto_uncertain_studies,
            "warning": "AUTO_EXTRACTED studies do not count as verified evidence until the verification bridge promotes them.",
        }, ensure_ascii=False, indent=2))
        return

    if args.command == "verify-studies":
        with SQLiteLedger(args.db) as ledger:
            summary = StudyVerificationBridge(ledger).run(args.candidate_id)
        print(json.dumps(_study_verification_json(summary), ensure_ascii=False, indent=2))
        return

    if args.command == "manual-verify-study":
        with SQLiteLedger(args.db) as ledger:
            summary = StudyVerificationBridge(ledger).set_manual_study_verification(
                args.candidate_id,
                args.study_id,
                eligible=args.status == "ELIGIBLE",
                design_label=args.design,
                reason=args.reason,
            )
        print(json.dumps(_study_verification_json(summary), ensure_ascii=False, indent=2))
        return

    if args.command == "resolve-family-link":
        with SQLiteLedger(args.db) as ledger:
            summary = StudyVerificationBridge(ledger).set_family_link_override(
                args.candidate_id,
                args.study_a,
                args.study_b,
                resolution=args.resolution,
                reason=args.reason,
            )
        print(json.dumps(_study_verification_json(summary), ensure_ascii=False, indent=2))
        return

    if args.command == "verify-synthesis":
        with SQLiteLedger(args.db) as ledger:
            bridge = _required_synthesis_bridge(ledger)
            summary = bridge.run(args.candidate_id, force=args.force)
        print(json.dumps(_synthesis_verification_json(summary), ensure_ascii=False, indent=2))
        return

    raise SystemExit("Unknown command")


def _project_json(project) -> dict:
    return {
        "project_id": project.project_id,
        "specialty": project.specialty,
        "question_type": project.question_type,
        "stage": project.stage,
        "status": project.status,
        "progress": project.progress,
        "message": project.message,
        "updated_at": project.updated_at,
    }


def _candidate_json(candidate) -> dict:
    return {
        "candidate_id": candidate.candidate_id,
        "project_id": candidate.project_id,
        "title": candidate.title,
        "question_type": candidate.question_type,
        "review_question": candidate.review_question,
        "eligible_designs": candidate.eligible_designs,
        "status": candidate.status.value,
        "search_terms": candidate.search_terms,
        "metadata": candidate.metadata,
    }



def _candidate_verification_json(result) -> dict:
    return {
        "candidate_id": result.candidate_id,
        "ranking_score": result.ranking_score,
        "decision": result.decision,
        "candidate_status": result.candidate_status.value,
        "pending": result.pending,
        "coverage": {
            "source_statuses": {k: v.value for k, v in result.coverage.source_statuses.items()},
            "blockers": list(result.coverage.blockers),
            "warnings": list(result.coverage.warnings),
        },
        "evidence": {
            "study_audit_complete": result.evidence.study_audit_complete,
            "synthesis_audit_complete": result.evidence.synthesis_audit_complete,
            "verified_independent_studies": result.evidence.verified_independent_studies,
            "verified_usable_studies": result.evidence.verified_usable_studies,
            "principal_outcome_studies": result.evidence.principal_outcome_studies,
        },
        "final_gate_result": result.final_gate_result,
    }


def _study_verification_json(summary) -> dict:
    return {
        "candidate_id": summary.candidate_id,
        "records_seen": summary.records_seen,
        "verified_eligible": summary.verified_eligible,
        "verified_ineligible": summary.verified_ineligible,
        "needs_review": summary.needs_review,
        "deterministic_families": summary.deterministic_families,
        "conservative_independent_count": summary.conservative_independent_count,
        "possible_family_links": summary.possible_family_links,
        "decision_changing_family_uncertainty": summary.decision_changing_family_uncertainty,
        "study_audit_complete": summary.study_audit_complete,
    }


def _synthesis_verification_json(summary) -> dict:
    return {
        "candidate_id": summary.candidate_id,
        "verified_families_seen": summary.verified_families_seen,
        "outcomes_extracted": summary.outcomes_extracted,
        "verified_usable_families": summary.verified_usable_families,
        "conservative_verified_usable_families": summary.conservative_verified_usable_families,
        "principal_outcome_usable_families": summary.principal_outcome_usable_families,
        "potentially_usable_families": summary.potentially_usable_families,
        "families_needing_full_text": summary.families_needing_full_text,
        "threshold_met": summary.threshold_met,
        "synthesis_audit_complete": summary.synthesis_audit_complete,
    }


def _sequential_verification_json(result) -> dict:
    return {
        "project_id": result.project_id,
        "final_option_candidate_ids": result.final_option_candidate_ids,
        "qualified_option_candidate_ids": result.qualified_option_candidate_ids,
        "desired_options": result.desired_options,
        "ranked": [
            {
                "candidate_id": item.candidate_id,
                "score": item.score,
                "reasons": list(item.reasons),
            }
            for item in result.ranked
        ],
        "verified": [_candidate_verification_json(item) for item in result.verified],
    }





def _optional_evidence_analysis_service(ledger):
    provider = OpenAICompatibleProvider.from_env()
    if not provider.endpoint or not provider.model:
        return None
    return CandidateEvidenceAnalysisService(
        ledger,
        SemanticCompetitorAssessor(provider),
        StudyEligibilityExtractor(provider),
    )


def _required_evidence_analysis_service(ledger):
    provider = OpenAICompatibleProvider.from_env()
    if not provider.endpoint or not provider.model:
        raise SystemExit("SCIMED_AI_ENDPOINT and SCIMED_AI_MODEL are required for evidence analysis")
    return CandidateEvidenceAnalysisService(
        ledger,
        SemanticCompetitorAssessor(provider),
        StudyEligibilityExtractor(provider),
    )


def _optional_synthesis_bridge(ledger):
    provider = OpenAICompatibleProvider.from_env()
    extractor = SynthesisDataExtractor(provider) if provider.endpoint and provider.model else None
    return SynthesisVerificationBridge(ledger, extractor)


def _required_synthesis_bridge(ledger):
    provider = OpenAICompatibleProvider.from_env()
    if not provider.endpoint or not provider.model:
        raise SystemExit("SCIMED_AI_ENDPOINT and SCIMED_AI_MODEL are required for synthesis extraction")
    return SynthesisVerificationBridge(ledger, SynthesisDataExtractor(provider))


if __name__ == "__main__":
    main()
