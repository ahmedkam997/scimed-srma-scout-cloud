"""Conservative, bounded supplemental PubMed retrieval.

Uses the same PICO-derived query at increasing depth, preserving baseline
records. No reference PMIDs, AI, exclusion decisions or coverage clearance.
"""
from __future__ import annotations
from dataclasses import replace
from scimed_scout.domain import SourceStatus
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.discovery.focused_queries import focused_query
from scimed_scout.discovery.query_optimizer import optimized_queries
from scimed_scout.discovery.pico_matching import assess_pico
from scimed_scout.discovery.evidence_classification import classify_review_search_hit,review_intervention_citation_signal

VERSION="ADAPTIVE_RETRIEVAL_V2"
MAX_UNIQUE=50
# Design cues prioritize a second exploratory search only; no exclusion.
RCT_CUE='(randomized controlled trial[pt] OR controlled clinical trial[pt] OR randomized[tiab] OR randomised[tiab] OR placebo[tiab] OR randomly[tiab] OR trial[tiab])'
DEPTHS=(25,50)
TARGET_PRIMARY=7
TARGET_REVIEW=2

def row(record):
    return {"source":record.source,"source_record_id":record.record_id,"title":record.title,
            "payload":{"metadata":record.metadata,"doi":record.doi,"year":record.year,"url":record.url}}

def lead_count(candidate,purpose,baseline,records):
    if purpose=="PRIMARY":
        primary=[row(r) for r in records if classify_review_search_hit(r)!="CONFIRMED_REVIEW_CUE"]
        return assess_pico(candidate,list(baseline)+primary)[0]["pico_design_family_leads"]
    seen=set()
    for r in records:
        if classify_review_search_hit(r)=="CONFIRMED_REVIEW_CUE" and review_intervention_citation_signal(candidate,r)=="INTERVENTION_IN_REVIEW_CITATION":
            seen.add((r.doi or r.record_id).casefold())
    # Baseline review cues are already classified by orchestrator. They are
    # NOT confirmed competitors or full-text judgments.
    for b in baseline:
        payload=b.get("payload") or {}
        seen.add(str(payload.get("doi") or b.get("source_record_id") or "").casefold())
    seen.discard("")
    return len(seen)

def adaptive_query(candidate,purpose,legacy):
    queries=optimized_queries(candidate,"PubMed",purpose,legacy,max_queries=4)
    # Prefer a fully formed, corrected P+I search. Ambiguous boolean scopes
    # use existing optimizer's conservative fallback, not new interpretation.
    import re
    from .query_optimizer import normalize
    scope=normalize(candidate.population)+" "+normalize(candidate.intervention_exposure_index_test)
    if re.search(r"\b(?:or|without|not|except|excluding)\b",scope):
        return ""
    return focused_query(candidate,"PubMed",purpose) or (queries[0] if queries else "")

def collect(candidate,purpose,legacy,baseline,client,*,initial_limit=12,base_access=True,cancellation_check=None):
    if purpose not in ("PRIMARY","REVIEW"):raise ValueError("invalid purpose")
    target=TARGET_PRIMARY if purpose=="PRIMARY" else TARGET_REVIEW
    initial=lead_count(candidate,purpose,baseline,[])
    report={"version":VERSION,"purpose":purpose,"target_cues":target,"initial_cues":initial,
            "final_cues":initial,"attempts":[],"source_calls":0,"new_ai_requests":0,
            "coverage_clearance_allowed":False,"eligibility_verified":False,"records":0,
            "status":"NOT_NEEDED"}
    if not base_access:
        report["status"]="DEFERRED_BASE_SOURCE_UNRESOLVED";return report,[]
    if initial>=target:return report,[]
    query=adaptive_query(candidate,purpose,legacy)
    if not query:
        report["status"]="NO_SAFE_QUERY";return report,[]
    report["query"]=query
    if isinstance(client,PubMedSource):
        ranked=PubMedSource(http=client.http,sort="relevance")
        ranked.api_key=client.api_key;ranked.email=client.email
    else:ranked=client
    records={}
    report["status"]="BOUNDED_ATTEMPT"
    previous_total=None
    previous_ids=[]
    previous_query=None
    for depth in DEPTHS:
        if depth<=initial_limit:continue
        if cancellation_check:cancellation_check()
        report["source_calls"]+=1
        # For a very broad first sample with insufficient PICO/design cues,
        # spend the remaining slots on a design-prioritized variant instead
        # of fetching more of the same broad ranking. Preserve first sample.
        refine=purpose=="PRIMARY" and previous_total is not None and previous_total>1000
        active_query=query+" AND "+RCT_CUE if refine else query
        requested=min(depth,MAX_UNIQUE-len(records)) if refine else depth
        if requested<=0:break
        try:r=ranked.search(active_query,limit=requested)
        except Exception as e:
            report["attempts"].append({"limit":depth,"status":"ACCESS_FAILED","error_type":type(e).__name__})
            report["status"]="SUPPLEMENTARY_ACCESS_UNRESOLVED";break
        capped=0
        current_ids=[r.record_id for r in r.records]
        prefix_drift=bool(previous_ids and previous_query==active_query and current_ids[:len(previous_ids)]!=previous_ids)
        for i,record in enumerate(r.records,1):
            if not record.title.strip():continue
            if record.record_id not in records:
                if len(records)>=MAX_UNIQUE:
                    capped+=1;continue
                records[record.record_id]=replace(record,metadata={**(record.metadata or {}),"adaptive_pubmed":{"query":active_query,"sort":"relevance","depth":requested,"rank":i,"eligibility_verified":False}})
        cues=lead_count(candidate,purpose,baseline,list(records.values()))
        drift=previous_total is not None and previous_query==active_query and r.total_count!=previous_total
        report["attempts"].append({"limit":requested,"query":active_query,"strategy":"DESIGN_PRIORITIZED" if refine else "FOCUSED", "status":r.status.value,"reported":r.total_count,"retrieved":len(r.records),"unique":len(records),"cues":cues,"count_drift":drift,"rank_prefix_changed":prefix_drift,"records_omitted_by_cap":capped})
        report.update(final_cues=cues,records=len(records))
        if drift or r.status not in (SourceStatus.SEARCHED_POSITIVE,SourceStatus.SEARCHED_NEGATIVE):
            report["status"]="SUPPLEMENTARY_ACCESS_UNRESOLVED";break
        previous_total=r.total_count
        previous_query=active_query
        previous_ids=current_ids
        if cues>=target:
            report["status"]="TARGET_CUES_REACHED";break
        if r.total_count is None or r.total_count<=requested:
            report["status"]="SCOPED_QUERY_EXHAUSTED";break
    else:
        report["status"]="BUDGET_EXHAUSTED"
    if not report["attempts"]:report["status"]="INITIAL_DEPTH_AT_CAP"
    return report,list(records.values())
