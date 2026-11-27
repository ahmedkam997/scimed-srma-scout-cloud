"""Resumable scientific recovery and development learning; no qualification authority.
Uses existing RCT-first, family/Methods and Research Academy components.
Learning changes ordering only, not inclusion, stopping, thresholds or source coverage.
"""
import argparse
import json
import re
from pathlib import Path
from collections import Counter
from scripts import scimed_autonomous_worker as v1

SCHEDULE=("discovery","families","competitors","discovery","families","competitors","learning","diagnostic")
ROUTES=("exact","broad","stratified")
OK={"SEARCHED_POSITIVE","SEARCHED_NEGATIVE"}
MAX_IDS=100
MAX_JOBS=100
MAX_METHODS=3
MAX_HISTORY=32

def extend(state):
    ext=state.setdefault("v2",{"schema":2,"jobs":{},"history":[],"route_stats":{},
                              "policy":{"competitor_order":"baseline","production_approved":False},
                              "task_counts":{},"last_diagnostic":None})
    if ext.get("schema")!=2 or ext["policy"].get("production_approved") is not False:
        raise ValueError("Invalid experimental extension")
    return ext

def job_for(ext,cid):
    return ext["jobs"].setdefault(cid,{"trial_ids":[],"review_ids":[],"methods":{},
          "family_routes":{},"competitor_routes":{},"last_family":-1000,"last_competitor":-1000,
          "family_audits":0,"competitor_audits":0})

def union_ids(old,new):
    ids=list(dict.fromkeys([*old,*(str(x) for x in new if re.fullmatch(r"[1-9][0-9]{0,11}",str(x)))]))
    return ids[:MAX_IDS],len(ids)>MAX_IDS

def seed_jobs(state,raw):
    from scimed_scout.discovery.competitor_records import identifiers
    ext=extend(state)
    for row in raw.get("candidates",[]):
        cid=row["candidate_id"]
        if cid not in state["ledger"] or not state["ledger"][cid].get("shortlist_cue"):continue
        if cid not in ext["jobs"] and len(ext["jobs"])>=MAX_JOBS:continue
        j=job_for(ext,cid)
        hints=row["metadata"]["rct_first"]
        for key,records in (("trial_ids",hints.get("comparison_records",[])),
                             ("review_ids",(hints.get("competing_review_preflight") or {}).get("records",[]))):
            ids=[next(iter(x["pmid"])) for r in records if len((x:=identifiers(r))["pmid"])==1 and len(x["doi"])<=1]
            j[key],cap=union_ids(j[key],ids)
            if cap:j[key+"_truncated"]=True

def choose_job(state,kind):
    ext=extend(state); now=state["cycles"]
    last="last_family" if kind=="families" else "last_competitor"
    # All high-priority leads stay eligible for later surveillance. No negative inference.
    eligible=[(cid,row) for cid,row in state["ledger"].items() if row.get("shortlist_cue")
              and (cid in ext["jobs"] or len(ext["jobs"])<MAX_JOBS)]
    def cooldown(cid):
        j=ext["jobs"].get(cid,{})
        routes=j.get("family_routes" if kind=="families" else "competitor_routes",{})
        # Work through alternate routes before surveillance. Do not re-query unchanged
        # literature every half hour. Partial samples stay unresolved even after cooldown.
        return 48 if len(routes)==len(ROUTES) and all(v["status"] in OK for v in routes.values()) else 8
    due=[(cid,row) for cid,row in eligible if now-ext["jobs"].get(cid,{}).get(last,-1000)>=cooldown(cid)]
    if not due:return None
    return min(due,key=lambda x:(ext["jobs"].get(x[0],{}).get(last,-1000),-x[1]["family_leads"],x[0]))

def choose_route(ext,j,kind):
    field="family_routes" if kind=="families" else "competitor_routes"
    tried=j[field]
    missing=[r for r in ROUTES if r not in tried]
    if missing:
        # Use independent text routes before a date-stratified expansion.
        if len(missing)>1 and "stratified" in missing:missing.remove("stratified")
        # Development yield means extra bibliographic IDs only, not eligible trials.
        stats=ext["route_stats"]
        return max(missing,key=lambda r:(stats.get(kind+":"+r,{}).get("mean",0),r=="exact"))
    return min(ROUTES,key=lambda r:tried[r]["cycle"])

def phrase(value):
    if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 /+(),-]{0,119}",value) or re.search(r"\b(?:AND|OR|NOT)\b",value):
        raise ValueError("Unsupported search scope; requires manual query")
    return '"'+value+'"[tiab]'

def query_for(row,kind,route):
    from scimed_scout.discovery.rct_first import RCT_FILTER,REVIEW_FILTER,ANCHORS,phrases,control_terms
    pop,inter,comp=(row[k] for k in ("population","intervention","comparator"))
    pair=next((x for group in ANCHORS.values() for x in group if x[:2]==(pop,inter)),None)
    def group(terms):return "("+" OR ".join(phrase(v) for v in terms)+")"
    p=group(phrases(pop,pair[2] if pair else ()))
    i=group(phrases(inter,pair[3] if pair else ()))
    c=group(control_terms(comp))
    return p+" AND "+i+(" AND "+c if route=="exact" else "")+" AND "+(RCT_FILTER if kind=="families" else REVIEW_FILTER)

def learn_route(ext,kind,route,gain,status):
    if status not in OK:return
    key=kind+":"+route
    v=ext["route_stats"].setdefault(key,{"n":0,"mean":0.0})
    v["n"]+=1;v["mean"]+=(gain-v["mean"])/v["n"]

def search(client,row,kind,route):
    from scimed_scout.discovery.evidence_first import _record
    q=query_for(row,kind,route)
    if route=="stratified":
        from scimed_scout.discovery.stratified_retrieval import collect
        audit,records=collect(client,q,budget=60)
        # The source call budget, not exhaustive search, is complete.
        return {"query":q,"status":"PARTIAL" if audit["status"]!="BOUNDED_SAMPLE" else ("SEARCHED_POSITIVE" if records else "SEARCHED_NEGATIVE"),
                "reported_total":None,"strata":audit,"rows":[_record(x) for x in records]}
    result=client.search(q,limit=40)
    return {"query":q,"status":result.status.value,"reported_total":result.total_count,
            "rows":[_record(x) for x in result.records]}

def fetch_rows(client,ids):
    from scimed_scout.sources.pubmed_abstracts import _fetch,parse_efetch
    from scripts.phase3_family_methods import as_row
    if not ids:return {},{}
    found,diag=parse_efetch(_fetch(client,ids),ids)
    return {p:as_row(p,m) for p,m in found.items()},diag

def recover(state,kind,client,*,searcher=search,fetcher=fetch_rows,resolver=None):
    ext=extend(state)
    selected=choose_job(state,kind)
    if not selected:return None
    cid,row=selected;j=job_for(ext,cid)
    route=choose_route(ext,j,kind)
    field="trial_ids" if kind=="families" else "review_ids"
    routefield="family_routes" if kind=="families" else "competitor_routes"
    last="last_family" if kind=="families" else "last_competitor"
    j[last]=state["cycles"]
    from scimed_scout.discovery.competitor_records import identifiers
    try:
        result=searcher(client,row,kind,route)
        new=[next(iter(i["pmid"])) for r in result["rows"] if len((i:=identifiers(r))["pmid"])==1 and len(i["doi"])<=1]
        before=set(j[field]);j[field],cap=union_ids(j[field],new)
        if cap:j[field+"_truncated"]=True
        gain=len(set(j[field])-before)
        j[routefield][route]={"cycle":state["cycles"],"status":result["status"],"new_ids":gain,"reported_total":result.get("reported_total"),"sample_size":len(result["rows"])}
        learn_route(ext,kind,route,gain,result["status"])
    except Exception as exc:
        result={"status":"ACCESS_UNRESOLVED","error_type":type(exc).__name__,"rows":[]};gain=0
        j[routefield][route]={"cycle":state["cycles"],"status":result["status"],"new_ids":0}
    out={"task":kind,"candidate_id":cid,"title":row["title"],"route":route,
         "source_status":result["status"],"new_ids":gain,"total_ids":len(j[field]),
         "confirmed_independent_eligible_trials":None,"usable_trial_count":None,
         "novelty_confirmed":False,"qualification_granted":False}
    raw={"search":result}
    try:
        if kind=="families":
            from scimed_scout.discovery.trial_family import audit_trial_families
            from scimed_scout.discovery.structured_extraction_v2 import abstract_ratios,abstract_counts,report_role_cues
            # Page through inventory; never overwrite previously seen IDs.
            page=j.get("family_cursor",0)%max(1,len(j[field]))
            ids=j[field][page:page+30]
            found,diag=fetcher(client,ids)
            j["family_cursor"]=(page+len(ids))%max(1,len(j[field]))
            families=audit_trial_families(list(found.values()))
            cues={pid:{"roles":report_role_cues(r),"ratios":abstract_ratios(r),"counts":abstract_counts(r)} for pid,r in found.items()}
            raw.update(families=families,outcomes=cues,missing_pmids=sorted(set(ids)-set(found)),diagnostics=diag)
            out.update(registration_links_in_page=families["registry_linked_families"],
                       outcome_report_cues=sum(bool(x["ratios"] or x["counts"]) for x in cues.values()),
                       missing_pmids=raw["missing_pmids"])
            memory=j.setdefault("report_cues",{})
            links={r["report_id"]:f["registration_id"] for f in families["families"] for r in f["reports"]}
            for pid,x in cues.items():
                # Keep compact source-linked cues even after short-lived artifacts expire.
                memory[pid]={"registry":links.get(pid),"role_cues":x["roles"]["cues"],
                             "ratio_count":len(x["ratios"]),"count_cues":len(x["counts"])}
            j["family_audits"]+=1
        else:
            from scimed_scout.discovery.open_access_dates import OpenAccessSearchDateResolver
            from scimed_scout.discovery.competitor_priority_v2 import hybrid
            from scimed_scout.storage import CandidateRecord
            # All reviews remain queued; ordering may change, not eligibility.
            ordered=j[field]
            if ext["policy"]["competitor_order"]=="hybrid" and result["rows"]:
                cand=CandidateRecord(cid,"worker",row["title"],"worker",population=row["population"],
                     intervention_exposure_index_test=row["intervention"],comparator_reference=row["comparator"])
                ranked=hybrid(cand,result["rows"])
                rank=[next(iter(i["pmid"])) for r in ranked if len((i:=identifiers(r))["pmid"])==1 and len(i["doi"])<=1]
                ordered=list(dict.fromkeys([*(x for x in rank if x in j[field]),*j[field]]))
            due=sorted(ordered,key=lambda pid:j["methods"].get(pid,{}).get("last_cycle",-1000))
            ids=[pid for pid in due if not j["methods"].get(pid,{}).get("date_cue")][:MAX_METHODS]
            found,diag=fetcher(client,ids)
            resolver=resolver or OpenAccessSearchDateResolver(include_pmc_oai=True)
            evidence={}
            for pid in ids:
                cue=resolver.resolve(found[pid]) if pid in found else None
                j["methods"][pid]={"last_cycle":state["cycles"],"date_cue":cue}
                evidence[pid]=cue
            raw.update(methods=evidence,missing_pmids=sorted(set(ids)-set(found)),diagnostics=diag)
            out.update(methods_date_cues=sum(bool(x.get("date_cue")) for x in j["methods"].values()),
                       methods_pending=sum(not j["methods"].get(p,{}).get("date_cue") for p in j[field]))
            j["competitor_audits"]+=1
    except Exception as exc:
        out["audit_error"]=type(exc).__name__
    # No pooling or novelty confirmation from source-linked date or outcome cues.
    return out,raw

def learning(state,client):
    from scripts.academy_components import evaluate_competitors,evaluate_report_tasks
    from scripts.v2_real_family_contrast import CASES
    from scimed_scout.sources.pubmed_abstracts import _fetch,parse_efetch
    ext=extend(state)
    found,diag=parse_efetch(_fetch(client,list(CASES)),list(CASES))
    report=evaluate_report_tasks(found)
    competitors=evaluate_competitors(client)
    # Adopt only an ordering change on development evidence, never a stop/filter.
    valid=bool(competitors) and all(x["status"] in OK and all(v is not None for v in x["comparison_at_five"].values()) for x in competitors.values())
    improved=valid and all(x["comparison_at_five"]["hybrid_bm25"]>=x["comparison_at_five"]["lexical_baseline"] for x in competitors.values()) and any(x["comparison_at_five"]["hybrid_bm25"]>x["comparison_at_five"]["lexical_baseline"] for x in competitors.values())
    ext["policy"]={"competitor_order":"hybrid" if improved else "baseline",
                   "production_approved":False,"development_only":True,"last_cycle":state["cycles"],
                   "reference_cases":list(competitors),"held_out":False}
    return {"task":"learning","status":"DEVELOPMENT_COMPARISON","order":ext["policy"]["competitor_order"],
            "all_competitor_routes_resolved":valid,"qualification_granted":False,"llm_weights_changed":False}, {"report_tasks":report,"competitors":competitors,"diagnostics":diag}

def diagnostic(state):
    ext=extend(state)
    statuses=Counter()
    for j in ext["jobs"].values():
        for f in ("family_routes","competitor_routes"):
            statuses.update(x["status"] for x in j[f].values())
    result={"task":"diagnostic","route_status_counts":dict(statuses),
            "inventory_caps":sum(bool(j.get("trial_ids_truncated") or j.get("review_ids_truncated")) for j in ext["jobs"].values()),
            "recovery_queue_capacity":MAX_JOBS,"pending_shortlist_without_job":sum(row.get("shortlist_cue",False) and cid not in ext["jobs"] for cid,row in state["ledger"].items()),
            "next_recovery_action":"Try remaining bounded exact, broad and date-stratified routes; unresolved source access and methods remain manual or alternate-source recovery tasks.",
            "unresolved_methods":sum(sum(not j["methods"].get(p,{}).get("date_cue") for p in j["review_ids"]) for j in ext["jobs"].values()),
            "qualification_granted":False}
    ext["last_diagnostic"]=result
    return result,{"policy":ext["policy"],"route_stats":ext["route_stats"]}

def cycle(state,collect,client,*,live_ai=False,recoverer=recover,learner=learning,planned_task=None):
    ext=extend(state); planned=planned_task or SCHEDULE[state["cycles"]%len(SCHEDULE)]
    if planned not in SCHEDULE:raise ValueError("unknown task")
    start=state["cycles"]
    result=None
    if planned in ("families","competitors"):result=recoverer(state,planned,client)
    elif planned=="learning":
        try:result=learner(state,client)
        except Exception as exc:result=({"task":"learning","status":"UNRESOLVED","error_type":type(exc).__name__},{"qualification_granted":False})
    elif planned=="diagnostic":result=diagnostic(state)
    if result is None:
        out,raw=v1.run(state,collect,v1.triage_public,live_ai=live_ai)
        out["task"]="discovery"
        seed_jobs(state,raw)
    else:
        out,raw=result
        state["cycles"]+=1
    assert state["cycles"]==start+1
    out.update(planned_task=planned,cycle=state["cycles"],first_choice_count=0,qualification_granted=False)
    ext["task_counts"][out["task"]]=ext["task_counts"].get(out["task"],0)+1
    ext["history"]=(ext["history"]+[{"cycle":state["cycles"],"task":out["task"],"status":out.get("source_status",out.get("coverage",out.get("status","RECORDED"))),"candidate_id":out.get("candidate_id")}])[-MAX_HISTORY:]
    # Drop only recovery extensions for leads already removed by V1 bounded ledger.
    ext["jobs"]={k:v for k,v in ext["jobs"].items() if k in state["ledger"]}
    # The scheduler hard-caps serialized state; compact only verbose cue fields,
    # retaining the full raw audit in the cycle artifact. Never silently clear IDs.
    for j in ext["jobs"].values():
        for entry in j["methods"].values():
            cue=entry.get("date_cue")
            if cue:entry["date_cue"]={k:cue[k] for k in ("date","year","quote","source_url","source_type","full_text_eligibility_verified") if k in cue}
    return out,raw

def main():
    from scimed_scout.discovery.rct_first import collect
    from scimed_scout.sources.pubmed import PubMedSource
    p=argparse.ArgumentParser()
    p.add_argument("--checkpoint",type=Path,default=Path("worker-state.json"))
    p.add_argument("--output",type=Path,default=Path("worker-output"))
    p.add_argument("--advisory",action="store_true")
    args=p.parse_args()
    state=v1.load(args.checkpoint)
    args.output.mkdir(parents=True,exist_ok=True)
    report,raw=cycle(state,collect,PubMedSource(sort="relevance"),live_ai=args.advisory)
    v1.write(args.output/"report.json",report)
    v1.write(args.output/"source-evidence.json",raw)
    v1.write(args.output/"worker-state.json",state)
    summary={k:report[k] for k in ("task","planned_task","cycle","qualification_granted","first_choice_count","source_status","coverage","candidate_id","new_ids","total_ids","methods_date_cues","registration_links_in_page","order","status") if k in report}
    summary["task_counts"]=state["v2"]["task_counts"]
    print("WORKER_V2 "+json.dumps(summary),flush=True)

if __name__=="__main__":main()
