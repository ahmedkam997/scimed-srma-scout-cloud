"""V6–V10 integration: bounded public evidence recovery, private strict adjudication.
No change to existing qualification logic. Never run reviewer keys on public CI.
"""
import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import asdict
from scripts import scimed_autonomous_worker as v1, scimed_autonomous_worker_v2 as v2
from scimed_scout.discovery.scientific_verification_v2 import digest, snapshot, TrustedDirectory
from scimed_scout.storage import CandidateRecord, SearchLogRecord, SQLiteLedger
from scimed_scout.domain import SourceStatus
from scimed_scout.verification.policy import policy_for_question_type
from scimed_scout.verification.coverage import evaluate_coverage

SCHEDULE=("discovery","families","competitors","packet","discovery","families","registry","learning","competitors","packet","diagnostic","validation")
PROJECT="autonomous-scientist"
MAX_PACKETS=12
MAX_ROWS=120
MAX_QUERY_LOGS=32

def extension(state):
    x=state.setdefault("scientist",{"schema":1,"packets":{},"history":[],"task_counts":{},"registry_cursor":0})
    if x.get("schema")!=1:raise ValueError("unsupported scientist checkpoint")
    return x

def candidate(cid,row):
    return CandidateRecord(cid,PROJECT,row["title"],"research","EFFECTIVENESS",
        review_question=row["title"],population=row["population"],intervention_exposure_index_test=row["intervention"],
        comparator_reference=row["comparator"],eligible_designs=["Randomized controlled trial"])

def workspace(state,cid):
    x=extension(state)
    return x["packets"].setdefault(cid,{"rows":{},"logs":{},"last_packet":-1000,"last_registry":-1000,"registry_routes":{},"missing":[]})

def choose(state,kind):
    ext=extension(state); jobs=v2.extend(state)["jobs"]
    choices=[cid for cid,row in state["ledger"].items() if row.get("shortlist_cue") and cid in jobs
        and (cid in ext["packets"] or len(ext["packets"])<MAX_PACKETS)]
    if not choices:return None
    last="last_registry" if kind=="registry" else "last_packet"
    return min(choices,key=lambda c:(ext["packets"].get(c,{}).get(last,-1000),-state["ledger"][c]["family_leads"],c))

def append_rows(w,rows,kind):
    for row in rows:
        if not row.get("source") or not row.get("source_record_id"):continue
        key=kind+"|"+row["source"]+"|"+str(row["source_record_id"])
        if key not in w["rows"] and len(w["rows"])>=MAX_ROWS:
            w["inventory_cap_reached"]=True;continue
        # Keep old full metadata rather than replace it with an incomplete search result.
        old=w["rows"].get(key)
        if old:
            p={**old["payload"],**row.get("payload",{})}
            p["metadata"]={**old["payload"].get("metadata",{}),**{k:v for k,v in row.get("payload",{}).get("metadata",{}).items() if v is not None and v!=""}}
            row={**old,**row,"payload":p}
        w["rows"][key]={**row,"source_record_id":str(row["source_record_id"]),"evidence_type":kind}

def log(w,source,query,status,count,*,bounded=True):
    # Source success for a bounded sample does not prove a systematic search.
    status=SourceStatus.PARTIAL if bounded and status in (SourceStatus.SEARCHED_POSITIVE,SourceStatus.SEARCHED_NEGATIVE) else status
    key=source+"|"+query
    if key not in w["logs"] and len(w["logs"])>=MAX_QUERY_LOGS:
        w["search_log_cap_reached"]=True;return
    w["logs"][key]={"source":source,"query":query,"status":status.value,"result_count":count,
                   "searched_at":datetime.now(timezone.utc).isoformat()}

class WorkspaceLedger:
    """Read-only adapter for the existing snapshot builder; never claims full coverage."""
    def __init__(self,cid,w):self.cid=cid;self.w=w
    def list_external_evidence(self,cid,kind):
        assert cid==self.cid
        return [r for r in self.w["rows"].values() if r["evidence_type"]==kind]
    def list_search_log(self,cid):
        assert cid==self.cid
        return [SearchLogRecord(PROJECT,cid,source=x["source"],query=x["query"],status=SourceStatus(x["status"]),
                result_count=x["result_count"],searched_at=x["searched_at"]) for x in self.w["logs"].values()]
    def evidence_identity_legacy_risk(self,cid):return bool(self.w.get("inventory_cap_reached") or self.w.get("search_log_cap_reached"))

def ingest_recovery(state,report,raw):
    cid=report.get("candidate_id")
    if not cid or report["task"] not in ("families","competitors"):return
    ext=extension(state)
    if cid not in ext["packets"] and len(ext["packets"])>=MAX_PACKETS:return
    w=workspace(state,cid)
    result=raw.get("search",{})
    if not result.get("query"):return
    from scimed_scout.discovery.evidence_classification import classify_review_search_hit
    from scimed_scout.sources.base import SearchRecord
    for r in result.get("rows",[]):
        kind="PRIMARY_STUDY" if report["task"]=="families" else "PUBLISHED_REVIEW"
        if kind=="PUBLISHED_REVIEW":
            cue=classify_review_search_hit(SearchRecord(r["source"],r["source_record_id"],r["title"],metadata=r.get("payload",{}).get("metadata",{})))
            if cue!="CONFIRMED_REVIEW_CUE":kind="OTHER"
        if kind=="OTHER":
            r={**r,"payload":{**r.get("payload",{}),"originally_requested_evidence_type":"PUBLISHED_REVIEW"}}
        append_rows(w,[r],kind)
    try:status=SourceStatus(result["status"])
    except ValueError:status=SourceStatus.ACCESS_FAILED
    log(w,"PubMed",result["query"],status,result.get("reported_total"))

def registry(state,clients):
    cid=choose(state,"registry")
    if not cid or not clients:return None
    w=workspace(state,cid);row=state["ledger"][cid]
    # One source per cycle. Never infer an empty registry from a failed call.
    source=min(clients,key=lambda name:(w["registry_routes"].get(name,{}).get("cycle",-1000),name))
    client=clients[source];w["last_registry"]=state["cycles"]
    # Validate public candidate strings before constructing source-specific syntax.
    q=v2.phrase(row["intervention"]).removesuffix("[tiab]")+" AND "+v2.phrase(row["population"]).removesuffix("[tiab]")
    if source=="Europe PMC":
        q=" AND ".join("TITLE_ABS:"+term for term in q.split(" AND "))+" AND (PUB_TYPE:\"systematic review\" OR PUB_TYPE:\"meta-analysis\" OR TITLE_ABS:\"systematic review\" OR TITLE_ABS:\"meta-analysis\")"
    try:
        # use existing source-specific adapters
        from scimed_scout.discovery.evidence_first import _record
        result=client.search(q,limit=20)
        # Registry adapters may retrieve much more than the nominal limit.
        # Keep cap status and aggregate, never call truncated results exhaustive.
        rows=[_record(r) for r in result.records[:20]]
        extra=max(0,len(result.records)-len(rows))
        if extra:w["registry_truncated"]=True
        kind="ONGOING_STUDY" if source=="ClinicalTrials.gov" else ("PUBLISHED_REVIEW" if source=="Europe PMC" else "REGISTRATION")
        from scimed_scout.discovery.evidence_classification import classify_review_search_hit,classify_registration_search_hit
        from scimed_scout.sources.base import SearchRecord
        for r in rows:
            k=kind
            rec=SearchRecord(r["source"],r["source_record_id"],r["title"],metadata=r.get("payload",{}).get("metadata",{}))
            if kind=="PUBLISHED_REVIEW" and classify_review_search_hit(rec)!="CONFIRMED_REVIEW_CUE":k="OTHER"
            if kind=="REGISTRATION" and classify_registration_search_hit(rec)!="REVIEW_REGISTRATION_CUE":k="OTHER"
            if k=="OTHER":r={**r,"payload":{**r.get("payload",{}),"originally_requested_evidence_type":kind}}
            append_rows(w,[r],k)
        log(w,source,q,result.status,result.total_count)
        status=result.status.value
        w["registry_routes"][source]={"cycle":state["cycles"],"status":status,"records":len(rows)}
        raw={"source":source,"query":q,"records":rows,"reported_total":result.total_count,"status":status,"unpersisted_result_rows":extra}
        if source=="ClinicalTrials.gov":
            from scimed_scout.discovery.structured_extraction_v2 import registry_leads
            leads=[registry_leads(r["payload"].get("metadata",{}),str(r["source_record_id"])) for r in rows]
            raw["registry_result_cues"]=leads
            w["registry_result_cues"]={**w.get("registry_result_cues",{}),**{x["registry_id"]:{"allocation":x.get("allocation"),"intervention_model":x.get("intervention_model"),"numeric_outcome_count":len(x.get("numeric_outcome_leads",[])),"ratio_count":len(x.get("reported_ratio_estimates",[]))} for x in leads if x.get("registry_id")}}
            w["registry_result_cues"]={k:v for k,v in w["registry_result_cues"].items() if "ONGOING_STUDY|ClinicalTrials.gov|"+k in w["rows"]}
    except Exception as exc:
        status="ACCESS_FAILED"
        log(w,source,q,SourceStatus.ACCESS_FAILED,None)
        w["registry_routes"][source]={"cycle":state["cycles"],"status":status,"records":0}
        raw={"source":source,"query":q,"status":status,"error_type":type(exc).__name__}
    return {"task":"registry","candidate_id":cid,"source":source,"source_status":status,"records":len(raw.get("records",[])),
            "unpersisted_result_rows":raw.get("unpersisted_result_rows",0),"registry_result_cues":len(raw.get("registry_result_cues",[])),
            "qualification_granted":False},raw

def fetch_with_recovery(client,ids,*,fetcher=v2.fetch_rows,alternate=None):
    """Bounded alternate exact-ID route, with explicit recovery outcome."""
    from scimed_scout.discovery.competitor_records import identifiers
    from scimed_scout.discovery.evidence_first import _record
    try:
        found,diag=fetcher(client,ids)
    except Exception as exc:
        found={};diag={"error_type":type(exc).__name__}
    found={str(p):r for p,r in found.items() if str(p) in ids}
    missing=sorted(set(ids)-set(found))
    attempts=[]
    if alternate is not None:
        for pid in missing[:2]:
            try:
                q=f"EXT_ID:{pid} AND SRC:MED"
                response=alternate.search(q,limit=3)
                candidates=[]
                for item in response.records:
                    row=_record(item);identity=identifiers(row)
                    if identity["pmid"]=={pid} and len(identity["doi"])<=1:
                        candidates.append(row)
                # Exact identity only; multiple variants are unresolved.
                recovered=len(candidates)==1 and bool(candidates[0].get("title"))
                if recovered:found[pid]=candidates[0]
                attempts.append({"pmid":pid,"source":alternate.name,"status":response.status.value,"exact_recovered":recovered})
            except Exception as exc:
                attempts.append({"pmid":pid,"source":alternate.name,"status":"ACCESS_FAILED","error_type":type(exc).__name__,"exact_recovered":False})
    return found,{"primary":diag,"alternate_attempts":attempts,
                  "missing_after_recovery":sorted(set(ids)-set(found))}

def prepare_packet(state,client,*,fetcher=v2.fetch_rows,fulltext=None,alternate=None):
    from scimed_scout.discovery.structured_extraction_v2 import collect as extract
    cid=choose(state,"packet")
    if not cid:return None
    w=workspace(state,cid);w["last_packet"]=state["cycles"];j=v2.extend(state)["jobs"][cid]
    if alternate is None and fetcher is v2.fetch_rows:
        from scimed_scout.sources import EuropePMCSource
        alternate=EuropePMCSource()
    recovery_audit={}
    attempts=w.setdefault("missing_attempts",{})
    for field,kind in (("trial_ids","PRIMARY_STUDY"),("review_ids","PUBLISHED_REVIEW")):
        # Retrieve next page of actual source IDs; preserve all retrieved rows.
        offset=w.get(field+"_cursor",0)%max(1,len(j[field]))
        page=j[field][offset:offset+20]
        retry=sorted((p for p in w["missing"] if p in j[field]),key=lambda p:(attempts.get(p,0),p))[:3]
        ids=list(dict.fromkeys([*retry,*page]))[:23]
        try:
            found,diag=fetch_with_recovery(client,ids,fetcher=fetcher,alternate=alternate)
            recovery_audit[field]=diag
            missing=sorted(set(ids)-set(found))
            w["missing"]=sorted((set(w["missing"])|set(missing))-set(found))
            for pid in missing:attempts[pid]=attempts.get(pid,0)+1
            for pid in found:attempts.pop(pid,None)
            for pid,row in found.items():
                if kind=="PUBLISHED_REVIEW":
                    cue=j["methods"].get(pid,{}).get("date_cue")
                    if cue:
                        m=row["payload"]["metadata"];m.update(last_search_date=cue.get("date"),search_date_evidence_quote=cue.get("quote"),search_date_evidence_url=cue.get("source_url"),search_date_evidence_level=cue.get("source_type"))
                # Retain ambiguous records rather than promote them to competing reviews.
                from scimed_scout.discovery.evidence_classification import classify_review_search_hit
                from scimed_scout.sources.base import SearchRecord
                target=kind
                if kind=="PUBLISHED_REVIEW" and classify_review_search_hit(SearchRecord(row["source"],row["source_record_id"],row["title"],metadata=row["payload"].get("metadata",{})))!="CONFIRMED_REVIEW_CUE":
                    target="OTHER";row["payload"]["originally_requested_evidence_type"]="PUBLISHED_REVIEW"
                append_rows(w,[row],target)
            w[field+"_cursor"]=(offset+len(page))%max(1,len(j[field]))
        except Exception:
            w["missing"]=sorted(set(w["missing"])|set(ids))
    led=WorkspaceLedger(cid,w);c=candidate(cid,state["ledger"][cid])
    policy=policy_for_question_type(c.question_type)
    coverage=evaluate_coverage(led.list_search_log(cid),policy)
    rows=led.list_external_evidence(cid,"PRIMARY_STUDY")
    previous={"reports":w.get("extraction_attempts",[])}
    extraction=(fulltext or extract)(rows,previous=previous,max_fulltexts=2)
    # Persist attempt cursors and provenance only; full tables stay in raw artifact.
    w["extraction_attempts"]=[{k:r[k] for k in ("source","record_id","pmcid","fulltext_attempts","fulltext") if k in r} for r in extraction["reports"]]
    # Bind exact full-text retrieval fingerprints into the snapshot; all
    # table cells and passages remain in the extraction artifact/checkpoint.
    for entry in extraction["reports"]:
        ft=entry.get("fulltext") or {}
        if ft.get("status")=="JATS_SOURCE_LINKED_LEADS":
            key="PRIMARY_STUDY|"+entry["source"]+"|"+str(entry["record_id"])
            if key in w["rows"]:
                w["rows"][key]["payload"]["fulltext_source_fingerprint"]={k:ft[k] for k in ("sha256","url","status") if k in ft}
    packet=snapshot(led,c)
    blocked=["independent full-text review and signed approvals not submitted","bounded search is not independently adjudicated complete",*coverage.blockers]
    if w["missing"]:blocked.append("exact PMID retrieval incomplete")
    if w.get("registry_truncated"):blocked.append("registry retrieval inventory truncated")
    if w.get("inventory_cap_reached"):blocked.append("bounded workspace inventory cap reached")
    report={"task":"packet","candidate_id":cid,"status":"PROVISIONAL_REVIEWER_PACKET",
       "snapshot_sha256":packet["verification_v2"]["snapshot_sha256"],
       "primary_report_count":packet["primary_report_count"],"competitor_count":packet["competitor_count"],
       "fulltext_source_calls":extraction["source_calls"],"blockers":blocked,
       "qualification_granted":False}
    w["last_snapshot"]=report["snapshot_sha256"]
    report["exact_id_recoveries"]=sum(a["exact_recovered"] for d in recovery_audit.values() for a in d["alternate_attempts"])
    w["last_exact_id_recovery"]=recovery_audit
    return report,{"packet":packet,"raw_source_rows":list(w["rows"].values()),"extraction":extraction,"exact_id_recovery":recovery_audit,"search_log":[asdict(x) for x in led.list_search_log(cid)],"candidate":asdict(c)}

def validation_admission():
    from scripts.academy_benchmark import audit_manifest
    manifest=json.loads(Path("benchmarks/academy/benchmark.json").read_text())
    report=audit_manifest(manifest)
    return {"task":"validation","status":"READY" if report["benchmark_ready"] else "AWAITING_INDEPENDENT_CASE_ADJUDICATION","admission":report,"qualification_granted":False},report

def diagnose(state):
    report,raw=v2.diagnostic(state)
    ext=extension(state)
    report["packet_count"]=len(ext["packets"])
    report["pending_fulltext"]=sum(len(w.get("missing",[])) for w in ext["packets"].values())
    report["registry_routes"]={cid:w["registry_routes"] for cid,w in ext["packets"].items()}
    # Safe automated recovery: the next packet stage retries missing IDs, and
    # each registry source gets a turn. No repository writes or model execution.
    report["repair_scope"]="bounded route rotation and exact identity recovery; no automatic code edits"
    return report,raw

def cycle(state,collect,client,clients,*,live_ai=False):
    ext=extension(state);planned=SCHEDULE[state["cycles"]%len(SCHEDULE)]
    start=state["cycles"];result=None
    if planned=="registry":result=registry(state,clients)
    elif planned=="packet":result=prepare_packet(state,client)
    elif planned=="validation":result=validation_admission()
    elif planned=="diagnostic":result=diagnose(state)
    if result is None:
        actual=planned if planned in v2.SCHEDULE else "discovery"
        report,raw=v2.cycle(state,collect,client,live_ai=live_ai,planned_task=actual)
        ingest_recovery(state,report,raw)
    else:
        report,raw=result;state["cycles"]+=1
    assert state["cycles"]==start+1
    report.update(planned_task=planned,cycle=state["cycles"],qualification_granted=False,first_choice_count=0)
    ext["task_counts"][report["task"]]=ext["task_counts"].get(report["task"],0)+1
    ext["history"]=(ext["history"]+[{"cycle":state["cycles"],"task":report["task"],"candidate_id":report.get("candidate_id"),"status":report.get("status",report.get("coverage",report.get("source_status","RECORDED")))}])[-48:]
    # Keep state bounded without silently dropping unresolved records. Stop at
    # checkpoint size limit in scheduler, rather than pretending completeness.
    return report,raw

def private_adjudicate(db,cid):
    """Only operator-controlled local ledger and existing trusted key adapter.
    Never accepts a public packet, browser decisions or arbitrary coverage.
    """
    with SQLiteLedger(db) as ledger:
        c=ledger.get_candidate(cid)
        if c is None:raise ValueError("candidate does not exist")
        policy=policy_for_question_type(c.question_type)
        coverage=evaluate_coverage(ledger.list_search_log(cid),policy)
        packet=snapshot(ledger,c)
        trusted=TrustedDirectory.from_env()
        if trusted is None:return {"qualification_granted":False,"blockers":["private trusted reviewer configuration missing"]}
        result=trusted(packet,coverage,policy)
        # Descriptive precision metrics supplement, never replace, the existing
        # signed reconstruction and minimum clinically important effect-change gate.
        for a in result.get("update_audits",[]):
            old,new=a["baseline"],a["new"]
            a["descriptive_variance_reduction"]=1-(new["se"]/old["se"])**2
            a["descriptive_inverse_variance_ratio"]=(old["se"]/new["se"])**2
        return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--checkpoint",type=Path,default=Path("worker-state.json"))
    p.add_argument("--output",type=Path,default=Path("worker-output"))
    p.add_argument("--advisory",action="store_true")
    a=p.parse_args()
    from scimed_scout.discovery.rct_first import collect
    from scimed_scout.sources import PubMedSource,EuropePMCSource,ClinicalTrialsGovSource,OSFRegistrationsSource,ProsperoCliSource
    clients={x.name:x for x in (EuropePMCSource(),ClinicalTrialsGovSource(),OSFRegistrationsSource(),ProsperoCliSource())}
    s=v1.load(a.checkpoint);a.output.mkdir(parents=True,exist_ok=True)
    report,raw=cycle(s,collect,PubMedSource(sort="relevance"),clients,live_ai=a.advisory)
    v1.write(a.output/"report.json",report);v1.write(a.output/"source-evidence.json",raw);v1.write(a.output/"worker-state.json",s)
    print("SCIENTIST_CYCLE "+json.dumps({k:v for k,v in report.items() if k not in ("candidates","audit","admission","registry_routes")},default=str),flush=True)

if __name__=="__main__":main()
