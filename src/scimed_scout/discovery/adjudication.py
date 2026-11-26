"""Portable study-centric adjudication packet; no automatic scientific clearance.

All retrieved records remain addressable. Validation checks submitted data
consistency and provenance references, not the truth of a person's assertion.
"""
from collections import defaultdict
import math
from .competitor_records import identifiers, groups, abstract
from .trial_family import registration_signals
from .review_opportunity import _cutoff, date_bounds
from .novelty import _valid_cached, _select_records

VERSION="STUDY_CENTRIC_ADJUDICATION_V1"
def key(r):
    return str(r.get("source") or "")+":"+str(r.get("source_record_id") or "")
def citation(r):
    p=r.get("payload") or {}
    ids=identifiers(r)
    return {"id":key(r),"title":r.get("title",""),"url":p.get("url",""),"doi":sorted(ids["doi"]),"pmid":sorted(ids["pmid"]),"year":p.get("year")}

def build(candidate, primary, reviews, registrations, *, ambiguous=(), opportunity=None):
    """Export all records in compact index, no artificial exclusions."""
    ordered=sorted(primary,key=key)
    records=[{**citation(r),"registration_ids":sorted(registration_signals(r)),"screening_status":"AWAITING_FULL_TEXT","eligibility":None} for r in ordered]
    competitors=[]
    for kind,rows in (("REVIEW",reviews),("REGISTRATION",registrations),("UNCLASSIFIED",ambiguous)):
        for r in _select_records(candidate,list(rows),len(rows)):
            payload=r.get("payload") or {}
            assessment=payload.get("discovery_semantic_assessment") or {}
            competitors.append({**citation(r),"kind":kind,"model_overlap":assessment.get("overall_overlap") if _valid_cached(candidate,r) else None,
                "last_search_date_cue":_cutoff(r) if kind=="REVIEW" else None,
                "adjudication_status":"AWAITING_INDEPENDENT_REVIEW"})
    return {"schema":VERSION,"candidate_id":candidate.candidate_id,
        "pico":{"population":candidate.population,"intervention":candidate.intervention_exposure_index_test,"comparator":candidate.comparator_reference,"outcomes":list(candidate.outcomes or [])},
        "primary_report_index":records,"competitor_index":competitors,"primary_report_count":len(records),"competitor_count":len(competitors),
        "provenance":"All current ledger records; no exclusions based on absence of keywords.",
        "submission_template":{"candidate_id":candidate.candidate_id,"studies":[],"outcomes":[],"competitor_decisions":[]},
        "study_fields":["study_id","report_ids","registry_ids","design","population","intervention_arm","comparator_arm","independence_basis","eligibility_evidence","reviewers"],
        "outcome_fields":["study_id","report_id","outcome","definition","timepoint","measure","intervention_n","comparator_n","intervention_events","comparator_events","intervention_mean","comparator_mean","intervention_sd","comparator_sd","effect","se","evidence","reviewers"],
        "competitor_fields":["record_id","decision","last_search_date","included_study_ids","evidence","reviewers"],
        "scope":"HUMAN_ADJUDICATION_WORKSPACE_NOT_QUALIFICATION","qualification_granted":False}

def nonempty(x):
    return isinstance(x,str) and bool(x.strip())
def evidence(x):
    return isinstance(x,dict) and all(nonempty(x.get(k)) for k in ("url","locator","excerpt")) and x["url"].startswith(("https://","http://"))
def dual(x):
    return isinstance(x,list) and len({v.strip().casefold() for v in x if nonempty(v)})>=2
def number(x):
    return type(x) in (int,float) and math.isfinite(x)
def integer(x):
    return type(x) is int and x>=0

def validate(packet,submission):
    """Mechanical checks only; even a complete submission never grants GO."""
    if packet.get("schema")!=VERSION or submission.get("candidate_id")!=packet.get("candidate_id"):
        raise ValueError("candidate/scope mismatch")
    primary={r["id"]:r for r in packet["primary_report_index"]}
    competitors={r["id"]:r for r in packet["competitor_index"]}
    errors=[];studies={};used_reports=set();used_registry=set();valid_outcomes=defaultdict(set);decisions=set()
    for s in submission.get("studies",[]):
        if not isinstance(s,dict):errors.append("invalid study row");continue
        sid=s.get("study_id");reports=s.get("report_ids");registry=s.get("registry_ids",[])
        ok=nonempty(sid) and sid not in studies and isinstance(reports,list) and bool(reports) and all(isinstance(r,str) and r in primary for r in reports) and len(set(reports))==len(reports) and not used_reports.intersection(reports)
        ok=ok and isinstance(registry,list) and all(nonempty(r) for r in registry) and not used_registry.intersection(r.strip().upper() for r in registry)
        ok=ok and s.get("design")=="RCT" and all(nonempty(s.get(k)) for k in ("population","intervention_arm","comparator_arm","independence_basis")) and s.get("intervention_arm")!=s.get("comparator_arm") and evidence(s.get("eligibility_evidence")) and dual(s.get("reviewers"))
        if ok:
            observed={r for rid in reports for r in primary[rid]["registration_ids"]}
            ok=observed.issubset({r.strip().upper() for r in registry})
        if not ok:errors.append("study row unresolved or duplicate: "+str(sid));continue
        studies[sid]=s;used_reports.update(reports);used_registry.update(r.strip().upper() for r in registry)
    for o in submission.get("outcomes",[]):
        if not isinstance(o,dict):errors.append("invalid outcome row");continue
        sid=o.get("study_id");measure=o.get("measure")
        ok=isinstance(sid,str) and sid in studies and o.get("report_id") in studies[sid]["report_ids"] and all(nonempty(o.get(k)) for k in ("outcome","definition","timepoint")) and evidence(o.get("evidence")) and dual(o.get("reviewers"))
        ni,nc=o.get("intervention_n"),o.get("comparator_n")
        if measure in ("RR","OR","RD"):
            ei,ec=o.get("intervention_events"),o.get("comparator_events")
            ok=ok and integer(ni) and integer(nc) and ni>0 and nc>0 and integer(ei) and integer(ec) and ei<=ni and ec<=nc
        elif measure in ("MD","SMD"):
            values=[o.get(k) for k in ("intervention_mean","comparator_mean","intervention_sd","comparator_sd")]
            ok=ok and integer(ni) and integer(nc) and ni>1 and nc>1 and all(number(x) for x in values) and values[2]>=0 and values[3]>=0
            if ok and measure=="SMD":ok=values[2]>0 or values[3]>0
        elif measure=="LOG_HR":
            ok=ok and number(o.get("effect")) and number(o.get("se")) and o["se"]>0
        else:ok=False
        if not ok:errors.append("outcome unresolved: "+str(sid));continue
        group=tuple(o[k].strip().casefold() for k in ("outcome","definition","timepoint","measure"))
        if sid in valid_outcomes[group]:errors.append("duplicate study/outcome: "+sid);continue
        valid_outcomes[group].add(sid)
    for d in submission.get("competitor_decisions",[]):
        if not isinstance(d,dict):errors.append("invalid competitor row");continue
        rid=d.get("record_id")
        ok=isinstance(rid,str) and rid in competitors and rid not in decisions and d.get("decision") in ("NON_OVERLAP","OVERLAP","UPDATE_REQUIRED","CORRECTION_REQUIRED") and evidence(d.get("evidence")) and dual(d.get("reviewers"))
        if ok and d.get("decision") in ("UPDATE_REQUIRED","CORRECTION_REQUIRED"):
            ok=bool(date_bounds(d.get("last_search_date"))) and isinstance(d.get("included_study_ids"),list) and bool(d["included_study_ids"])
        if ok:decisions.add(rid)
        else:errors.append("competitor unresolved: "+str(rid))
    return {"schema":VERSION,"valid_study_rows":len(studies),"studies_with_valid_outcome_rows":len(set().union(*valid_outcomes.values())) if valid_outcomes else 0,
        "compatible_outcome_groups":[{"outcome":k[0],"definition":k[1],"timepoint":k[2],"measure":k[3],"study_ids":sorted(v),"count":len(v)} for k,v in sorted(valid_outcomes.items())],
        "competitors_with_complete_submitted_fields":len(decisions),"competitors_pending":len(competitors)-len(decisions),"errors":errors,
        "minimum_seven_study_rows":len(studies)>=7,"minimum_seven_with_outcomes":len(set().union(*valid_outcomes.values()))>=7 if valid_outcomes else False,
        "human_assertions_independently_verified":False,"qualification_granted":False}
