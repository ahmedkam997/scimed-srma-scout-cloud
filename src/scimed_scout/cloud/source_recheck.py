"""Recheck failed/partial sources for ONE saved PICO, with no new AI generation.

Results are append-only diagnostics in scimed_source_rechecks. They do not
overwrite the original literature audit, novelty gates or qualified status.
"""
from __future__ import annotations

import json
import os
import re
import time
import traceback
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Iterable

from scimed_scout.cloud.supabase import SupabaseJobStore
from scimed_scout.domain import SourceStatus
from scimed_scout.sources import build_default_source_clients
from scimed_scout.storage import CandidateRecord
from scimed_scout.verification.queries import build_search_plan

ALLOWED_SOURCES = frozenset({
    "PubMed", "Europe PMC", "OpenAlex", "Crossref", "Semantic Scholar",
    "PROSPERO", "OSF Registries", "ClinicalTrials.gov",
})
RECHECK_STATUSES = frozenset({"PARTIAL", "ACCESS_FAILED", "NOT_SEARCHED"})
DEFINITIVE = frozenset({SourceStatus.SEARCHED_POSITIVE, SourceStatus.SEARCHED_NEGATIVE})


def saved_topic(parent: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    package = (parent.get("result_json") or {}).get("package") or {}
    for key in ("options", "provisional_options"):
        for item in package.get(key) or []:
            if isinstance(item, dict) and str(item.get("candidate_id") or "") == candidate_id:
                return item
    raise ValueError("The selected topic is absent from the original completed discovery job.")


def source_statuses(topic: dict[str, Any]) -> dict[str, str]:
    quality = ((topic.get("research_dossier") or {}).get("verification_and_quality") or {})
    entries = quality.get("source_statuses") or topic.get("source_statuses") or {}
    return {
        str(source): str(value)
        for source, value in entries.items()
        if str(source) in ALLOWED_SOURCES
    }


def candidate_from_saved(parent: dict[str, Any], topic: dict[str, Any]) -> CandidateRecord:
    q = (topic.get("research_dossier") or {}).get("scientific_question") or {}
    def field(name: str, default: Any = "") -> Any:
        return q.get(name) or topic.get(name) or default
    candidate = CandidateRecord(
        candidate_id=str(topic["candidate_id"]),
        project_id=str(parent["id"]),
        title=str(field("title", topic.get("title") or "")),
        specialty=str(field("specialty", parent.get("specialty") or "")),
        question_type=str(field("question_type", parent.get("question_type") or "EFFECTIVENESS")),
        review_question=str(field("review_question")),
        population=str(field("population")),
        intervention_exposure_index_test=str(field("intervention_exposure_index_test")),
        comparator_reference=str(field("comparator_reference")),
        outcomes=list(field("outcomes", []) or []),
        eligible_designs=list(field("eligible_designs", []) or []),
        search_terms=list(field("candidate_search_terms", field("search_terms", [])) or []),
    )
    if not candidate.intervention_exposure_index_test or not candidate.population:
        raise ValueError("The saved PICO has no sufficient population and intervention for a source recheck.")
    return candidate


def _dialysis_laao_pico(candidate: CandidateRecord | None) -> bool:
    """Specific evidence-tested clinical anchor; never infer PICO from a title alone."""
    if candidate is None:
        return False
    population = " ".join([
        candidate.population, candidate.title, candidate.review_question,
    ]).casefold()
    intervention = " ".join([
        candidate.intervention_exposure_index_test, candidate.title,
    ]).casefold()
    return bool(
        re.search(r"\b(dialysis|hemodialysis|haemodialysis|esrd|eskd|end.stage|kidney.failure|renal.failure)\b",population)
        and re.search(r"(left atrial appendage|\blaao\b|\blaac\b)",intervention)
    )


def query_plan_for_source(
    source: str, plan: Any, candidate: CandidateRecord | None = None,
) -> list[tuple[str, str]]:
    if _dialysis_laao_pico(candidate):
        if source in ("PROSPERO","OSF Registries"):
            # Precision variants avoid the old 131/340 broad PROSPERO matches.
            # This is a high-priority *screening* strategy, NOT an exhaustive
            # registry search. A zero response never clears review competition.
            return [
                ("REGISTRATION", '"left atrial appendage occlusion" AND "dialysis"'),
                ("REGISTRATION", '"left atrial appendage closure" AND "end stage renal"'),
                ("REGISTRATION", '"LAAO" AND "hemodialysis"'),
            ]
        if source == "Semantic Scholar":
            return [
                ("PRIMARY_STUDY", "left atrial appendage occlusion apixaban dialysis"),
                ("PUBLISHED_REVIEW", "left atrial appendage occlusion end stage renal meta analysis"),
            ]
    if source in ("PROSPERO", "OSF Registries"):
        return [("REGISTRATION", q) for q in plan.registry_queries[:2]]
    if source == "ClinicalTrials.gov":
        return [("ONGOING_STUDY", q) for q in plan.pipeline_queries[:2]]
    return ([("PUBLISHED_REVIEW", q) for q in plan.review_queries[:2]]
            + [("PRIMARY_STUDY", q) for q in plan.primary_queries[:1]])


def recheck_saved_topic(
    parent: dict[str, Any], candidate_id: str, *,
    source_clients: Iterable[Any] | None = None,
    max_sources: int = 5,
    max_results_per_query: int = 20,
    previous_result: dict[str, Any] | None = None,
    sleep_func: Any = time.sleep,
) -> dict[str, Any]:
    if parent.get("status") != "COMPLETED":
        raise ValueError("Only completed discovery jobs can be rechecked.")
    topic = saved_topic(parent, candidate_id)
    original = source_statuses(topic)
    previous = previous_result if isinstance(previous_result, dict) else {}
    if previous and (
        previous.get("job_id") != str(parent["id"])
        or previous.get("candidate_id") != candidate_id
    ):
        # Never reuse a different project's cached source conclusions.
        previous = {}
    completed_targeted_sources = {
        entry.get("source") for entry in previous.get("source_reports",[])
        if isinstance(entry,dict)
        and entry.get("targeted_search_status")
            == "TARGETED_QUERIES_COMPLETED_NOT_FULL_SEARCH_CLEARANCE"
    }
    target = [
        name for name, status in original.items()
        if status in RECHECK_STATUSES and name in ALLOWED_SOURCES
        and name not in completed_targeted_sources
    ][:max(1,min(8,max_sources))]
    clients = {client.name: client for client in
               (source_clients if source_clients is not None else build_default_source_clients())}
    candidate = candidate_from_saved(parent, topic)
    plan = build_search_plan(candidate)
    reports: list[dict[str, Any]] = []

    for source in target:
        client = clients.get(source)
        attempts: list[dict[str, Any]] = []
        planned = query_plan_for_source(source, plan, candidate)
        # A shared unauthenticated Semantic Scholar quota can return 429
        # even after one successful call. Budget one request per worker job
        # unless a private API key was supplied in the server environment.
        has_s2_key = bool(getattr(client,"api_key","")) if source == "Semantic Scholar" else False
        budget = 1 if source == "Semantic Scholar" and not has_s2_key else len(planned)
        for index, (purpose, query) in enumerate(planned[:budget]):
            if source == "Semantic Scholar" and index > 0:
                # Their documented personal-key allowance is 1 request/sec.
                sleep_func(1.1)
            if client is None:
                attempts.append({
                    "evidence_type": purpose, "query": query,
                    "status": "NOT_SEARCHED", "total_count": None,
                    "message": "Source client not configured", "citations": [],
                })
                break
            try:
                item = client.search(query, limit=max(5,min(30,max_results_per_query)))
                attempts.append({
                    "evidence_type": purpose, "query": query,
                    "status": item.status.value,
                    "total_count": item.total_count,
                    "message": (item.message or "")[:1200],
                    "citations": [{
                        "record_id": str(r.record_id)[:150],
                        "title": str(r.title)[:450],
                        "url": str(r.url)[:1000],
                        "doi": str(r.doi)[:200],
                        "year": r.year,
                        "classification": "UNSCREENED_BIBLIOGRAPHIC_LEAD",
                    } for r in item.records[:15]],
                    "citations_truncated": max(0,len(item.records)-15),
                })
                if item.status == SourceStatus.ACCESS_FAILED and (
                    "429" in (item.message or "")
                    or "Too Many Requests" in (item.message or "")
                ):
                    break
            except Exception as exc:
                attempts.append({
                    "evidence_type": purpose, "query": query,
                    "status": "ACCESS_FAILED", "total_count": None,
                    "message": str(exc)[:1200], "citations": [],
                })
                break

        statuses = [x["status"] for x in attempts]
        all_definitive = (
            len(statuses) == len(planned)
            and all(value in ("SEARCHED_POSITIVE","SEARCHED_NEGATIVE") for value in statuses)
        )
        reports.append({
            "source": source,
            "previous_status": original[source],
            "targeted_search_status": (
                "TARGETED_QUERIES_COMPLETED_NOT_FULL_SEARCH_CLEARANCE"
                if all_definitive else "TARGETED_QUERIES_INCOMPLETE"
            ),
            "attempted_queries": attempts,
            "unrun_query_variants": (
                max(0, len(planned) - len(attempts))
            ),
            "quota_strategy": (
                "ONE_REQUEST_UNAUTHENTICATED_SHARED_QUOTA"
                if source == "Semantic Scholar" and not has_s2_key else
                "PERSONAL_KEY_PACED_1_REQUEST_PER_SECOND"
                if source == "Semantic Scholar" else "NOT_APPLICABLE"
            ),
            "registry_query_strategy": (
                "DIALYSIS_SPECIFIC_PRECISION_SEARCH_NOT_EXHAUSTIVE"
                if source in ("PROSPERO","OSF Registries")
                   and _dialysis_laao_pico(candidate)
                else "ORIGINAL_PICO_FOCUSED"
            ),
            "note": (
                "These are new exploratory source queries only. A positive or negative "
                "query response is not a confirmed complete systematic search, "
                "PICO-overlap decision, eligible-study count or novelty clearance."
            ),
        })

    return {
        "schema": "SCIMED_TARGETED_SOURCE_RECHECK_V1",
        "job_id": str(parent["id"]),
        "candidate_id": candidate_id,
        "topic_title": str(topic.get("title") or ""),
        "searched_at_utc": datetime.now(timezone.utc).isoformat(),
        "original_source_statuses": original,
        "targeted_sources": target,
        "source_reports": reports,
        "remaining_originally_failed_sources_not_attempted": [
            name for name,status in original.items()
            if status in RECHECK_STATUSES and name not in target
            and name not in completed_targeted_sources
        ],
        "previously_targeted_technical_successes_not_repeated": sorted(completed_targeted_sources),
        "previous_targeted_report_reused": bool(previous),
        "source_search_exhaustiveness": "NOT_ESTABLISHED",
        "manual_pico_overlap_still_required": True,
        "independent_eligible_primary_studies": "NOT_VERIFIED",
        "original_discovery_result_unchanged": True,
        "qualification_status_unchanged": True,
        "decision": "RECHECK_EVIDENCE_FOR_MANUAL_RECONCILIATION_ONLY",
    }


class SourceRecheckStore(SupabaseJobStore):
    """Queue credential uses the existing, limited worker API key/token."""

    def _queue(self, params: dict[str, str]) -> list[dict[str, Any]]:
        return self._request("GET", "/rest/v1/scimed_source_rechecks?"
                             + urllib.parse.urlencode(params))

    def _update_recheck(self, request_id: str, fields: dict[str, Any],
                        *, allowed: tuple[str,...] = ("QUEUED","RUNNING")) -> list[dict[str, Any]]:
        values = {"id":f"eq.{request_id}"}
        if allowed:
            values["status"] = "in.(" + ",".join(allowed) + ")"
        return self._request("PATCH", "/rest/v1/scimed_source_rechecks?"
                             + urllib.parse.urlencode(values),
                             fields, prefer="return=representation")

    def claim_recheck(self) -> dict[str, Any] | None:
        rows = self._queue({"select":"*","status":"eq.QUEUED",
                            "order":"created_at.asc","limit":"1"})
        if not rows:
            return None
        row = rows[0]
        now = datetime.now(timezone.utc).isoformat()
        result = self._update_recheck(str(row["id"]), {
            "status":"RUNNING", "stage":"SOURCE_RECHECK",
            "progress":5, "message":"Checking only previously failed or partial sources",
            "started_at":now,"updated_at":now,
        },allowed=("QUEUED",))
        return result[0] if result else None

    def parent_job(self, job_id: str) -> dict[str, Any]:
        rows = self._select({"select":"id,status,specialty,question_type,result_json,client_token_hash",
                             "id":f"eq.{job_id}","limit":"1"})
        if not rows:
            raise ValueError("Parent discovery job not available.")
        return rows[0]

    def previous_completed_recheck(self, job_id: str, candidate_id: str) -> dict[str, Any]:
        rows = self._queue({
            "select":"result_json", "job_id":f"eq.{job_id}",
            "candidate_id":f"eq.{candidate_id}","status":"eq.COMPLETED",
            "order":"completed_at.desc","limit":"1",
        })
        return dict((rows[0].get("result_json") or {})) if rows else {}

    def finish_recheck(self, request_id: str, result: dict[str, Any],
                       *, error: str = "") -> None:
        now = datetime.now(timezone.utc).isoformat()
        updated = self._update_recheck(request_id, {
            "status":"FAILED" if error else "COMPLETED",
            "stage":"FAILED" if error else "COMPLETE",
            "progress":100,
            "message":"Targeted source recheck failed" if error else
                      "Source recheck completed; scientific clearance still pending",
            "error_text":error[:4000],
            "result_json":result if not error else {},
            "completed_at":now, "updated_at":now,
        }, allowed=("RUNNING",))
        if not updated:
            raise RuntimeError("Could not finalize targeted source recheck.")


def run_once(store: SourceRecheckStore | None = None,
             *, source_clients: Iterable[Any] | None = None) -> int:
    store = store or SourceRecheckStore.from_env()
    row = store.claim_recheck()
    if row is None:
        print(json.dumps({"status":"IDLE","message":"No queued targeted source rechecks"}))
        return 0
    try:
        parent = store.parent_job(str(row["job_id"]))
        if not row.get("client_token_hash") or (
            str(row["client_token_hash"]) != str(parent.get("client_token_hash"))
        ):
            raise PermissionError("Recheck request owner does not match the original job.")
        previous = (
            store.previous_completed_recheck(str(row["job_id"]),str(row["candidate_id"]))
            if callable(getattr(store,"previous_completed_recheck",None))
            else {}
        )
        result = recheck_saved_topic(parent,str(row["candidate_id"]),
                                     source_clients=source_clients,
                                     previous_result=previous)
        store.finish_recheck(str(row["id"]),result)
        print(json.dumps({"status":"COMPLETED","recheck_id":row["id"],
                          "sources":result["targeted_sources"]}))
        return 0
    except Exception as exc:
        detail="".join(traceback.format_exception(type(exc),exc,exc.__traceback__))
        try:
            store.finish_recheck(str(row["id"]),{},error=detail)
        except Exception:
            print(json.dumps({"status":"FAILED_TO_RECORD_ERROR","recheck_id":row["id"]}))
        print(json.dumps({"status":"FAILED","recheck_id":row["id"],"error":str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(run_once())
