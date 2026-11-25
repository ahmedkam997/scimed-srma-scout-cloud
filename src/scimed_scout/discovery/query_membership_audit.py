"""Offline-labelled, live PubMed known-item membership audit.

Reference IDs are used ONLY in diagnostic intersections, never discovery.
No AI, production DB writes, or scientific eligibility decisions.
"""
from __future__ import annotations
import argparse,json,re
from pathlib import Path
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.europe_pmc import EuropePMCSource
from scimed_scout.verification.queries import build_search_plan
from .scientific_benchmark import _candidate,_pmid
from .query_optimizer import optimized_queries
from .concept_retrieval import experimental_queries

DEPTH=50
TOP=12
def uid_query(ids):
    ids=list(dict.fromkeys(ids))
    if not ids or any(not re.fullmatch(r"[0-9]{1,12}",str(i)) for i in ids):
        raise ValueError("Invalid reference IDs")
    return "("+" OR ".join(str(i)+"[uid]" for i in ids)+")"

def esearch(client,q,cap,sort="relevance"):
    out={"query":q,"sort":sort,"cap":cap,"ok":False,"total":None,"ids":[],"translation":"","warnings":{}}
    try:
        raw=client.http.get_json(client.base+"esearch.fcgi",client._params({"db":"pubmed","term":q,"retmode":"json","retmax":cap,"sort":sort}))
        block=raw.get("esearchresult")
        if not isinstance(block,dict):return out
        out["translation"]=str(block.get("querytranslation") or "")
        out["warnings"]=block.get("warninglist") or {}
        errors=block.get("errorlist") or raw.get("error") or raw.get("ERROR")
        if errors:
            out["errors"]=errors;return out
        if "count" not in block or not str(block["count"]).isdigit():return out
        count=int(block["count"]);ids=block.get("idlist")
        if not isinstance(ids,list) or any(not re.fullmatch(r"[0-9]{1,12}",str(i)) for i in ids):return out
        ids=list(map(str,ids))
        if len(ids)!=min(cap,count) or len(set(ids))!=len(ids):return out
        out.update(ok=True,total=count,ids=ids)
    except Exception as exc:out["error_type"]=type(exc).__name__
    return out

def membership(client,query,ids,sort="relevance"):
    target=uid_query(ids)
    return esearch(client,"("+query+") AND "+target,len(ids),sort)

def classify_one(pmid,baseline,checks):
    # A positive observation is meaningful even if another query failed;
    # a negative requires every planned query intersection to be valid.
    if not baseline.get("ok") or pmid not in baseline.get("ids",[]):
        return {"status":"REFERENCE_INDEX_UNRESOLVED","best_rank":None,"matched_queries":[]}
    ranks=[];matched=[];inconsistent=False;all_ok=bool(checks)
    for n,c in enumerate(checks,1):
        sample,inter=c["sample"],c["intersection"]
        all_ok=all_ok and sample["ok"] and inter["ok"]
        if not (sample["ok"] and inter["ok"]):continue
        if pmid in inter["ids"]:matched.append(n)
        if pmid in sample["ids"]:
            ranks.append(sample["ids"].index(pmid)+1)
            if pmid not in inter["ids"]:inconsistent=True
        if pmid in inter["ids"] and pmid not in sample["ids"] and sample["total"]<=sample["cap"]:inconsistent=True
    best=min(ranks) if ranks else None
    if inconsistent:status="INCONSISTENT_REMOTE_RESULTS"
    elif best is not None and best<=TOP:status="TOP_12"
    elif best is not None:status="RANK_13_TO_50"
    elif not all_ok:status="ACCESS_UNRESOLVED"
    elif matched:status="MATCHED_BEYOND_50"
    else:status="QUERY_MISMATCH"
    return {"status":status,"best_rank":best,"matched_queries":matched}

def audit_queries(client,queries,sorts,ids,baseline,cache):
    checks=[]
    for q,sort in zip(queries,sorts):
        key=(q,sort,"sample")
        if key not in cache:cache[key]=esearch(client,q,DEPTH,sort)
        interkey=(q,"membership",tuple(ids))
        if interkey not in cache:cache[interkey]=membership(client,q,ids,sort)
        checks.append({"sample":cache[key],"intersection":cache[interkey]})
    return {"queries":checks,"references":{i:classify_one(i,baseline,checks) for i in ids}}

def metadata(client,ids):
    q="("+" OR ".join("EXT_ID:"+i for i in ids)+") AND SRC:MED"
    r=client.search(q,limit=len(ids));out={}
    for item in r.records:
        pmid=_pmid(item)
        if pmid not in ids:continue
        m=item.metadata or {}
        mesh=m.get("meshHeadingList") or {}
        headings=mesh.get("meshHeading",[]) if isinstance(mesh,dict) else []
        out[pmid]={"title":item.title,"year":item.year,"doi":item.doi,"mesh":[x.get("descriptorName") for x in headings if isinstance(x,dict) and x.get("descriptorName")],"publication_types":m.get("pubTypeList") or {}}
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);args=p.parse_args()
    fixture=json.loads(Path("benchmarks/ranking_v3.json").read_text())
    pub=PubMedSource();ep=EuropePMCSource()
    report={"schema":"QUERY_MEMBERSHIP_AUDIT_V1","new_ai_requests":0,"scientific_accuracy_validated":False,"limitations":"Selected reference leads from development cases, not a complete or independently adjudicated gold standard. Intersections are diagnostic only. Rank positions may change with indexing; 50-result depth is bounded. No estimate of global scientific recall.","cases":[]}
    def save():args.output.write_text(json.dumps(report,indent=2)+"\n")
    for case in fixture["cases"]:
        c=_candidate(case);plan=build_search_plan(c,max_queries=2)
        ids=list(dict.fromkeys(x["pmid"] for x in case["primary"]+case["reviews"]+case.get("controls",[])))
        baseline=esearch(pub,uid_query(ids),len(ids))
        entry={"case":case["id"],"baseline":baseline,"reference_metadata":metadata(ep,ids),"arms":{}}
        for purpose,base,key in (("PRIMARY",plan.primary_queries,"primary"),("REVIEW",plan.review_queries,"reviews")):
            refs=[x["pmid"] for x in case[key]]
            old=optimized_queries(c,"PubMed",purpose,base,max_queries=2)
            new=experimental_queries(c,purpose,base,max_queries=2)
            arms={"V1_RELEVANCE":(old,("relevance","relevance")),"CONCEPT_RELEVANCE":(new,("relevance","relevance")),"CONCEPT_DUAL_QUERY":(new,("relevance","pub_date"))}
            cache={}
            for arm,(queries,sorts) in arms.items():
                entry["arms"].setdefault(arm,{})[purpose]=audit_queries(pub,queries,sorts,refs,baseline,cache)
        report["cases"].append(entry);save()
        print(json.dumps({"case":entry["case"],"baseline_ok":baseline["ok"],"reference_metadata":{i:{"title":x["title"],"mesh":x["mesh"]} for i,x in entry["reference_metadata"].items()},"arms":{a:{k:{"references":v["references"],"queries":[{"total":q["sample"]["total"],"translation":q["sample"]["translation"],"warnings":q["sample"]["warnings"],"errors":q["sample"].get("errors"),"intersection_ok":q["intersection"]["ok"]} for q in v["queries"]]} for k,v in x.items()} for a,x in entry["arms"].items()}},ensure_ascii=True),flush=True)
    report["status"]="COMPLETE";save()
if __name__=="__main__":main()
