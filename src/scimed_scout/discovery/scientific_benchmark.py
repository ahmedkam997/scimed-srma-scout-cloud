"""Paired live retrieval and independent reference-record audit.

Reference identifiers are NEVER provided to discovery queries, scoring or
citation seeds. Separate exact-ID fetch is used only for label diagnostics.
No AI calls, no production DB, no automatic scientific GO labels.
"""
from __future__ import annotations
import argparse
import json
import time
from pathlib import Path
from collections import Counter
from scimed_scout.storage import CandidateRecord,ProjectRecord,SQLiteLedger
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.europe_pmc import EuropePMCSource
from scimed_scout.sources.base import SearchResult
from scimed_scout.domain import SourceStatus
from scimed_scout.verification.queries import build_search_plan
from .query_optimizer import optimized_queries
from .pico_matching import assess_pico
from .evidence_classification import classify_review_search_hit
from .trial_family import audit_trial_families
from .orchestrator import ReviewDiscoveryOrchestrator
from .adaptive_search import collect

ARMS=("LEGACY","OPTIMIZED")
def _record(r,kind):
    return {"source":r.source,"source_record_id":r.record_id,"title":r.title,"evidence_type":kind,
        "payload":{"metadata":r.metadata,"doi":r.doi,"year":r.year,"url":r.url}}

def _pmid(r):
    m=r.metadata or {}
    value=str(m.get("pmid") or (r.record_id if r.source=="PubMed" or m.get("source")=="MED" else ""))
    return value if value.isdigit() else ""

def _access(result):
    return (result.status==SourceStatus.SEARCHED_NEGATIVE and result.total_count==0) or (
        result.status==SourceStatus.SEARCHED_POSITIVE and any(str(r.title or "").strip() for r in result.records))

def safe_search(client,q,limit):
    try:return client.search(q,limit=limit)
    except Exception:return SearchResult(client.name,q,SourceStatus.ACCESS_FAILED)

def sample_metrics(reference_pmids,observed,complete):
    hits=sorted(set(reference_pmids)&set(observed))
    return {"reference_count":len(set(reference_pmids)),"observed_reference_pmids":hits,
        "observed_reference_count":len(hits),"sample_reference_retrieval_fraction":len(hits)/len(set(reference_pmids)) if reference_pmids and complete else None,
        "access_complete":bool(complete),"not_retrieved":sorted(set(reference_pmids)-set(observed))}
    
class RecordingSource:
    def __init__(self,client,cache):
        self.client=client;self.cache=cache;self.name=client.name
        self.calls=0
    def search(self,q,*,limit):
        key=(self.name,q,limit)
        if key not in self.cache:
            self.cache[key]=safe_search(self.client,q,limit)
            self.calls+=1
        return self.cache[key]

def paired_samples(candidate,case,clients,*,cap=2,limit=8):
    plan=build_search_plan(candidate,max_queries=cap)
    arms={}
    # Interleave arms by source/purpose to reduce order/time confounding.
    cache={}
    for arm in ARMS:
        arms[arm]={"logs":[],"PRIMARY":[],"REVIEW":[]}
    for client in clients:
        for purpose,base in (("PRIMARY",plan.primary_queries),("REVIEW",plan.review_queries)):
            queries={"LEGACY":base,"OPTIMIZED":optimized_queries(candidate,client.name,purpose,base,max_queries=cap)}
            for index in range(max(map(len,queries.values()))):
                for arm in ARMS:
                    if index>=len(queries[arm]):continue
                    q=queries[arm][index];key=(client.name,q,limit);cached=key in cache
                    if not cached:cache[key]=safe_search(client,q,limit)
                    r=cache[key]
                    arms[arm]["logs"].append({"source":client.name,"purpose":purpose,"query":q,"status":r.status.value,
                        "access_complete":_access(r),"total_count":r.total_count,"retrieved":len(r.records),"cache_hit":cached})
                    arms[arm][purpose].extend(r.records)
    result={}
    for arm,a in arms.items():
        prim=a["PRIMARY"];rev=a["REVIEW"]
        rows=[_record(r,"PRIMARY_STUDY") for r in prim if classify_review_search_hit(r)!="CONFIRMED_REVIEW_CUE"]
        pico,_=assess_pico(candidate,rows)
        result[arm]={"logs":a["logs"],"primary":sample_metrics([r["pmid"] for r in case["primary"]],
                [_pmid(r) for r in prim],all(l["access_complete"] for l in a["logs"] if l["purpose"]=="PRIMARY")),
            "reviews":sample_metrics([r["pmid"] for r in case["reviews"]],[_pmid(r) for r in rev],all(l["access_complete"] for l in a["logs"] if l["purpose"]=="REVIEW")),
            "pico_family_leads":pico["pico_design_family_leads"],"pico_report_leads":pico["pico_design_report_leads"],
            "queries_planned":len(a["logs"]),"unique_source_calls":sum(not l["cache_hit"] for l in a["logs"])}
    return result

def exact_reference_audit(candidate,case,client):
    """Lookup reference IDs separately; do not feed them back into retrieval."""
    refs=case["primary"]+case["reviews"]+case.get("controls",[])
    ids=[r["pmid"] for r in refs]
    q="("+" OR ".join("EXT_ID:"+p for p in ids)+") AND SRC:MED"
    response=safe_search(client,q,len(ids))
    found={_pmid(r):r for r in response.records if _pmid(r) in ids and r.title}
    items=[]
    for ref in refs:
        rid=ref["pmid"];r=found.get(rid)
        item={**ref,"reference_retrieved":r is not None,"citation_status":None,"pico_status":None}
        if r is not None:
            item["citation_status"]=classify_review_search_hit(r)
            if ref in case["primary"] or ref.get("kind","").endswith("_primary"):
                audit,_=assess_pico(candidate,[_record(r,"PRIMARY_STUDY")])
                item["pico_status"]=audit["rows"][0]["status"] if audit["rows"] else None
        items.append(item)
    return {"source_status":response.status.value,"expected_reference_count":len(ids),"retrieved_count":len(found),"items":items,
        "reference_labels_independently_double_screened":False}

def _candidate(case):
    return CandidateRecord(candidate_id=case["id"],project_id="P",**case["candidate"])

def run(fixture,clients,output=None):
    out={"version":fixture["version"],"status":"RUNNING","scientific_accuracy_validated":False,
        "scientific_go_accuracy":None,"new_ai_requests":0,"cases":[],"family_controls":[],
        "limitations":"Small selected public reference set. Fixed sample limits; recent sort and indexing differ. Missing access is unresolved. Sample retrieval fraction is not exhaustive search recall. Review leads do not establish overlap or novelty. No dual independent adjudication."}
    def save():
        if output:output.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    save()
    ep=next(c for c in clients if c.name=="Europe PMC")
    for case in fixture["cases"]:
        start=time.monotonic();c=_candidate(case)
        paired=paired_samples(c,case,clients,cap=fixture["limits"]["queries_per_purpose"],limit=fixture["limits"]["records_per_query"])
        entry={"id":case["id"],"split":case["split"],"paired":paired,"reference_audit":exact_reference_audit(c,case,ep),"elapsed_seconds":round(time.monotonic()-start,2)}
        out["cases"].append(entry);save()
        print(json.dumps({"case":entry["id"],"split":entry["split"],"elapsed_seconds":entry["elapsed_seconds"],
            "arms":{k:{x:v[x] for x in ("primary","reviews","pico_family_leads","queries_planned")} for k,v in paired.items()},
            "reference_retrieved":entry["reference_audit"]["retrieved_count"],"reference_expected":entry["reference_audit"]["expected_reference_count"]}),flush=True)
    for family in fixture.get("family_controls",[]):
        ids=family["pmids"]
        q="("+" OR ".join("EXT_ID:"+p for p in ids)+") AND SRC:MED"
        r=safe_search(ep,q,len(ids))
        rows=[_record(x,"PRIMARY_STUDY") for x in r.records if _pmid(x) in ids and x.title]
        audit=audit_trial_families(rows)
        out["family_controls"].append({"family":family["family"],"reference_pmids":ids,"retrieved":len(rows),
            "registry_linked_families":audit["registry_linked_families"],"conservative_family_lead_count":audit["conservative_family_lead_count"],
            "expected_max_trial_families":1,"fulltext_independence_confirmed":None})
    out["status"]="PILOT_COMPLETE"
    out["new_case_count"]=sum(c["split"]=="new_pilot" for c in out["cases"])
    out["unresolved_case_count"]=sum(any(not a[k]["access_complete"] for a in c["paired"].values() for k in ("primary","reviews")) for c in out["cases"])
    save();return out

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fixture",type=Path,default=Path("benchmarks/scientific_v1.json"))
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    result=run(json.loads(args.fixture.read_text()),[PubMedSource(),EuropePMCSource()],args.output)
    print(json.dumps({k:v for k,v in result.items() if k!="cases"}),flush=True)

if __name__=="__main__":main()
