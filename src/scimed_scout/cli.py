from __future__ import annotations

import argparse
import json
import platform
import sys

from . import __version__
from .ai import CandidateDiscoveryService, OpenAICompatibleProvider
from .domain import CandidateStatus, SourceStatus
from .gates import final_decision
from .storage import ProjectRecord, SQLiteLedger


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


if __name__ == "__main__":
    main()
