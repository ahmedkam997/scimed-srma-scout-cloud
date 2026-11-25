"""One isolated, bounded live production-verifier pilot.

Fixed PICO, real sources, production query and verification components,
no fabricated source clearance and no writing to the production database.
The candidate is not a new proposal; this is verification-stage E2E only.
"""
from __future__ import annotations
import argparse
import json
import tempfile
import time
from pathlib import Path
from scimed_scout.storage import ProjectRecord,SQLiteLedger
from scimed_scout.sources import build_default_source_clients
from scimed_scout.ai.adaptive_router import AdaptiveFreeRouter
from scimed_scout.competitors import SemanticCompetitorAssessor
from scimed_scout.sources.europe_pmc import EuropePMCSource
from .comparative_validation import MeteredProvider,_write
from .novelty import DiscoveryNoveltyService
from .scoring import DiscoveryScoringService
from .open_access_dates import OpenAccessSearchDateResolver
from .orchestrator import ReviewDiscoveryOrchestrator
from .scientific_benchmark import _candidate

BUDGET=8
CASE_ID="ARDS_PRONE"

def audit(case,clients,router,output=None):
    out={"version":"VERIFIER_E2E_PILOT_V1","case":case["id"],"status":"STARTED",
         "logical_ai_budget":BUDGET,"scientific_accuracy_validated":False,
         "human_go_label":None,"production_database_written":False,
         "qualification_means":"Engine label only; independent scientific adjudication is required.",
         "limitations":"One fixed published-review question, not generation validation. Fulltext and clinical independence not adjudicated. Budget exhaustion must remain explicit."}
    if output:_write(output,out)
    meter=MeteredProvider(router,BUDGET) if router else None
    started=time.monotonic()
    try:
        with tempfile.TemporaryDirectory() as directory:
            with SQLiteLedger(Path(directory)/"benchmark.sqlite") as ledger:
                c=_candidate(case)
                ledger.upsert_project(ProjectRecord("P",c.specialty,question_type="ALL"))
                ledger.upsert_candidate(c)
                novelty=DiscoveryNoveltyService(ledger,SemanticCompetitorAssessor(meter),
                    search_date_resolver=OpenAccessSearchDateResolver(),max_reviews=18,
                    max_registrations=12,max_fulltext_reviews=3,batch_size=3,
                    enrichment_client=EuropePMCSource(),max_enrichment_lookups=2) if meter else None
                scoring=DiscoveryScoringService(meter) if meter else None
                engine=ReviewDiscoveryOrchestrator(ledger,clients,novelty_service=novelty,
                    scoring_service=scoring,require_pico_signals=True,
                    optimize_literature_queries=True,adaptive_search=True)
                result=engine.verify_candidate(c.candidate_id,limit_per_query=8)
                saved=ledger.get_candidate(c.candidate_id)
                meta=saved.metadata or {}
                records=ledger.list_external_evidence(c.candidate_id,"PUBLISHED_REVIEW")
                expected={r["pmid"] for r in case["reviews"]}
                retrieved=set()
                for r in records:
                    m=(r.get("payload") or {}).get("metadata") or {}
                    pmid=str(m.get("pmid") or (r.get("source_record_id") if r.get("source")=="PubMed" else ""))
                    if pmid in expected:retrieved.add(pmid)
                out.update(status="COMPLETED",decision=result.decision,candidate_status=result.candidate_status.value,
                    coverage_complete=result.coverage.complete,
                    source_statuses={k:v.value for k,v in result.coverage.source_statuses.items()},
                    coverage_blockers=list(result.coverage.blockers),pending=list(result.pending),
                    primary_report_leads=result.evidence.unique_primary_study_candidates,
                    pico_family_leads=result.evidence.pico_audit.get("pico_design_family_leads"),
                    reference_competitor_pmids_retrieved=sorted(retrieved),
                    reference_competitor_count=len(expected),
                    published_review_records=len(records),
                    competitor_assessment_complete=meta.get("discovery_competitor_assessment_complete",False),
                    registration_assessment_complete=meta.get("discovery_registration_assessment_complete",False),
                    review_opportunity=meta.get("discovery_review_opportunity",{}),
                    adaptive_search_audit=meta.get("adaptive_search_audit",{}),
                    final_gate_result=result.final_gate_result)
                # A known prior review is not proof of fatal redundancy.
                # Flag a qualified result for independent assessment instead.
                out["reviewer_alert"]=result.candidate_status.value=="QUALIFIED"
    except Exception as exc:
        out.update(status="FAILED",error_type=type(exc).__name__)
    out["seconds"]=round(time.monotonic()-started,2)
    out["logical_ai_requests"]=meter.attempts if meter else 0
    out["ai_calls"]=meter.calls if meter else []
    out["ai_available"]=router is not None
    out["routing"]=router.routing_snapshot() if router else {}
    if output:_write(output,out)
    return out

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture",type=Path,default=Path("benchmarks/scientific_v1.json"))
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    case=next(c for c in json.loads(args.fixture.read_text())["cases"] if c["id"]==CASE_ID)
    try:router=AdaptiveFreeRouter.from_env()
    except RuntimeError:router=None
    report=audit(case,build_default_source_clients(),router,args.output)
    print(json.dumps({k:report.get(k) for k in ("status","case","candidate_status","decision","coverage_complete","source_statuses",
        "reference_competitor_pmids_retrieved","pico_family_leads","logical_ai_requests","seconds","reviewer_alert","error_type")}),flush=True)
    return 1 if report["status"]=="FAILED" else 0

if __name__=="__main__":raise SystemExit(main())
