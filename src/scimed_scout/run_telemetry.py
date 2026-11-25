"""Bounded, aggregate worker telemetry. Never exports titles, IDs, prompts,
queries, raw provider responses, exception strings, credentials or user data.
Counts describe discovery signals, not eligible independent studies.
"""
from __future__ import annotations
from collections import Counter
import json
import math
import os
from pathlib import Path

from scimed_scout.diagnostics import exception_diagnostic
from scimed_scout.discovery.constants import MIN_DISCOVERY_STUDIES

VERSION = "WORKER_TELEMETRY_V1"
SOURCES = {"PubMed","Europe PMC","Crossref","OpenAlex","Semantic Scholar","PROSPERO","OSF Registries","ClinicalTrials.gov","WHO ICTRP"}
STATES = {"QUALIFIED","REJECTED","PROVISIONAL_BACKUP","DISCOVERED","SHORTLISTED","DEEP_VERIFYING"}
HTTP_CODES = {400,401,402,403,404,408,429,500,502,503,504}
REASONS = {"SOURCE_COVERAGE","COMPETITOR_REVIEW_PENDING","REGISTRATION_PENDING","REDUNDANCY_SIGNAL",
           "TRIAL_FAMILY_UNRESOLVED","PICO_LEADS_INSUFFICIENT","BIBLIOGRAPHIC_LEADS_INSUFFICIENT",
           "SCORING_PENDING","UPDATE_OR_CORRECTION_PENDING","FINAL_GATE_NOT_MET","OTHER_PENDING"}
OPPORTUNITIES = {"NOVEL_REVIEW_ASSESSMENT","UPDATE_SIGNAL","CORRECTIVE_SIGNAL","UPDATE_AND_CORRECTIVE_SIGNAL",
                 "OVERLAP_NEEDS_ADJUDICATION","OVERLAP_NO_POST_CUTOFF_SIGNAL"}

def n(x):
    return max(0,min(10_000_000,int(x))) if isinstance(x,int) and not isinstance(x,bool) else 0

class MeteredDiscoveryProvider:
    """Measure logical calls at the production fallback boundary, not HTTP retries."""
    def __init__(self, provider):
        self.provider=provider
        self.requests=0
        self.failed=0
        self.tokens=0
        self.usage_reports=0
        self.errors=Counter()
    def __getattr__(self,name):
        return getattr(self.provider,name)
    def complete(self,request):
        self.requests+=1
        try:
            response=self.provider.complete(request)
        except Exception as exc:
            self.failed+=1
            code=exception_diagnostic(exc)["code"]
            self.errors[code]+=1
            raise
        raw=getattr(response,"raw",None)
        usage=raw.get("usage") if isinstance(raw,dict) else None
        if isinstance(usage,dict) and isinstance(usage.get("total_tokens"),int) and usage["total_tokens"]>=0:
            self.usage_reports+=1
            self.tokens+=n(usage["total_tokens"])
        return response
    def snapshot(self):
        routing=self.provider.routing_snapshot() if hasattr(self.provider,"routing_snapshot") else {}
        return {"logical_requests":self.requests,"failed_logical_requests":self.failed,
                "reported_total_tokens":self.tokens if self.usage_reports else None,
                "responses_with_token_usage":self.usage_reports,
                "failure_categories":dict(self.errors),
                "failover_count":n(getattr(self.provider,"total_failover_count",0)),
                "unavailable_provider_count":len(getattr(self.provider,"unavailable_free_providers",[]) or []),
                "routing":routing,
                "http_attempts_known":routing.get("http_attempts_known",False),"remaining_quota_known":False}

def candidate_reasons(row):
    reasons=set()
    if row.get("coverage_blockers"):
        reasons.add("SOURCE_COVERAGE")
    if row.get("failed_gates"):
        reasons.add("FINAL_GATE_NOT_MET")
    if row.get("potential_fatal_review_overlap_ids") or "FATAL REVIEW REDUNDANCY" in str(row.get("decision","")):
        reasons.add("REDUNDANCY_SIGNAL")
    for value in row.get("pending",[]) or []:
        text=str(value).casefold()
        if "trial-family" in text or "registry-linked report families" in text:
            reasons.add("TRIAL_FAMILY_UNRESOLVED")
        elif "pico/design cues" in text:
            reasons.add("PICO_LEADS_INSUFFICIENT")
        elif "scoring" in text:
            reasons.add("SCORING_PENDING")
        elif "registration" in text:
            reasons.add("REGISTRATION_PENDING")
        elif "update/correction" in text:
            reasons.add("UPDATE_OR_CORRECTION_PENDING")
        elif "competing published" in text or "competitor assessment" in text:
            reasons.add("COMPETITOR_REVIEW_PENDING")
        elif "redundant" in text:
            reasons.add("REDUNDANCY_SIGNAL")
    if "FEWER THAN" in str(row.get("decision","")):
        reasons.add("BIBLIOGRAPHIC_LEADS_INSUFFICIENT")
    if row.get("pending") and not reasons:
        reasons.add("OTHER_PENDING")
    return reasons

def aggregate(result, *, elapsed_seconds, requested=None, specialty="", question_type=""):
    s=result.get("run_summary") or {}
    rows=[r for r in s.get("candidate_audits",[]) if isinstance(r,dict)]
    reasons=Counter()
    sources=Counter()
    opportunities=Counter()
    for row in rows:
        reasons.update(candidate_reasons(row))
        sources.update(name for name,status in (row.get("source_statuses") or {}).items()
                       if name in SOURCES and status in ("ACCESS_FAILED","PARTIAL","NOT_SEARCHED"))
        route=(row.get("review_opportunity") or {}).get("route")
        if route in OPPORTUNITIES:
            opportunities[route]+=1
    counts={k:n(v) for k,v in (s.get("status_counts") or {}).items() if k in STATES}
    verified=n(s.get("verified_candidates"))
    pico_known=[r["pico_design_family_leads"] for r in rows
                if isinstance(r.get("pico_design_family_leads"),int) and r["pico_design_family_leads"]>=0]
    ai=s.get("ai_telemetry") or {}
    scope=str(specialty).strip().casefold()
    scope=scope if scope in {"cardiology","radiology","general surgery","surgery","orthopedics","neurology","neurosurgery","nephrology","all","oncology","internal medicine"} else "other"
    q=str(question_type).upper()
    q=q if q in {"ALL","EFFECTIVENESS","DIAGNOSTIC_ACCURACY","PROGNOSIS","ETIOLOGY_RISK","ASSOCIATION","PREVALENCE_INCIDENCE","PREDICTION_MODEL","SAFETY_HARMS","OTHER"} else "OTHER"
    return {"version":VERSION,"status":"COMPLETED","scope":scope,"question_type":q,
            "elapsed_seconds":round(max(0,float(elapsed_seconds)),2),
            "requested":n(requested if requested is not None else s.get("requested_candidates")),
            "generated":n(s.get("generated_candidates")),"verified":verified,
            "qualified":counts.get("QUALIFIED",0),"status_counts":counts,
            "recent_topics_skipped":n(s.get("recent_topics_skipped_count")),
            "duplicate_topics_skipped":n(s.get("duplicate_topics_skipped_count")),
            "off_scope_skipped":n(s.get("off_scope_skipped_count")),
            "reused_generation":s.get("reused_generation") is True,
            "resumed_audits":n(s.get("resumed_completed_audits")),
            "cluster_anchored_candidates":n(s.get("source_cluster_anchored_candidates")),
            "pico_family_lead_counts_available":len(pico_known),
            "candidates_at_minimum_pico_lead_signal":sum(x>=MIN_DISCOVERY_STUDIES for x in pico_known),
            "reason_counts":dict(reasons),"source_incomplete_candidate_counts":dict(sources),
            "opportunity_counts":dict(opportunities),
            "ai":{k:ai[k] for k in ("logical_requests","failed_logical_requests","reported_total_tokens","responses_with_token_usage","failure_categories","failover_count","unavailable_provider_count","http_attempts_known","remaining_quota_known","routing") if k in ai},
            "clinical_accuracy_validated":False,"eligible_independent_studies_confirmed":None}

def incident(status,elapsed_seconds,exc=None):
    result={"version":VERSION,"status":status,"elapsed_seconds":round(max(0,float(elapsed_seconds)),2)}
    if exc is not None:
        result["failure_code"]=exception_diagnostic(exc)["code"]
    return result

def write_report(report):
    """Optional local artifact only; monitoring failure must not fail discovery."""
    location=os.environ.get("SCIMED_MONITOR_REPORT")
    if not location:
        return
    try:
        path=Path(location)
        temp=path.with_suffix(".tmp")
        temp.write_text(json.dumps(report,ensure_ascii=True,allow_nan=False),encoding="utf-8")
        temp.replace(path)
    except (OSError,ValueError,TypeError):
        print(json.dumps({"status":"TELEMETRY_WRITE_FAILED"}),flush=True)
