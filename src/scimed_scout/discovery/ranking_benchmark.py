"""Matched new-case ranking experiment; no candidate labels fed into queries."""
import json,argparse
from pathlib import Path
from .scientific_benchmark import _candidate,_pmid,safe_search,_access,sample_metrics,exact_reference_audit
from .query_optimizer import optimized_queries
from scimed_scout.verification.queries import build_search_plan
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.europe_pmc import EuropePMCSource

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);args=p.parse_args()
    fixture=json.loads(Path("benchmarks/ranking_v3.json").read_text())
    report={"schema":fixture["version"],"scientific_accuracy_validated":False,"new_ai_requests":0,"cases":[],"limitations":fixture["limitations"]}
    clients={s:PubMedSource(sort=s) for s in ("pub_date","relevance","mixed")}
    def save():args.output.write_text(json.dumps(report,indent=2)+"\n")
    for case in fixture["cases"]:
        c=_candidate(case);plan=build_search_plan(c,max_queries=2)
        entry={"case":case["id"],"arms":{s:{} for s in clients}}
        for purpose,base,key in (("PRIMARY",plan.primary_queries,"primary"),("REVIEW",plan.review_queries,"reviews")):
            queries=optimized_queries(c,"PubMed",purpose,base,max_queries=2)
            ref=[x["pmid"] for x in case[key]]
            controls=[x["pmid"] for x in case.get("controls",[])]
            for sort,client in clients.items():
                rows=[];logs=[]
                for q in queries:
                    r=safe_search(client,q,12);rows.extend(r.records)
                    logs.append({"query":q,"status":r.status.value,"access":_access(r),"retrieved":len(r.records),"total":r.total_count,"message":r.message})
                ids={_pmid(r) for r in rows if _pmid(r)}
                entry["arms"][sort][purpose]={"metrics":sample_metrics(ref,ids,all(x["access"] for x in logs)),"unique":len(ids),"controls_retrieved":sorted(ids.intersection(controls)),"logs":logs}
        entry["reference_audit"]=exact_reference_audit(c,case,EuropePMCSource())
        report["cases"].append(entry);save()
        print(json.dumps({"case":entry["case"],"arms":{s:{k:{"metrics":v["metrics"],"unique":v["unique"]} for k,v in x.items()} for s,x in entry["arms"].items()},"exact":entry["reference_audit"]["retrieved_count"],"expected":entry["reference_audit"]["expected_reference_count"]}),flush=True)
    report["status"]="COMPLETE";save()
if __name__=="__main__":main()
