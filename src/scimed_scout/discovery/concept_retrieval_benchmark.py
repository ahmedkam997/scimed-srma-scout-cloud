"""Compare query changes and per-query ranking without extra record slots.
Replay V3 cases: explicitly development/calibration, not a holdout.
"""
import argparse,json
from pathlib import Path
from .scientific_benchmark import _candidate,_pmid,safe_search,_access,sample_metrics,exact_reference_audit
from .query_optimizer import optimized_queries
from .concept_retrieval import experimental_queries
from scimed_scout.verification.queries import build_search_plan
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.europe_pmc import EuropePMCSource

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);args=p.parse_args()
    fixture=json.loads(Path("benchmarks/ranking_v3.json").read_text())
    out={"schema":"CONCEPT_RETRIEVAL_DEVELOPMENT_V1","new_ai_requests":0,"scientific_accuracy_validated":False,"limitations":"Replay of cases used to identify missing concepts. Not independent validation; 12 slots per query, two queries per purpose, known records are never search inputs. Year counts are not relevance or novelty.","cases":[]}
    def save():args.output.write_text(json.dumps(out,indent=2)+"\n")
    clients={s:PubMedSource(sort=s) for s in ("pub_date","relevance")}
    for case in fixture["cases"]:
        c=_candidate(case);plan=build_search_plan(c,max_queries=2);entry={"case":case["id"],"arms":{}}
        for purpose,base,key in (("PRIMARY",plan.primary_queries,"primary"),("REVIEW",plan.review_queries,"reviews")):
            old=optimized_queries(c,"PubMed",purpose,base,max_queries=2)
            new=experimental_queries(c,purpose,base,max_queries=2)
            arms={"V1_RELEVANCE":(old,("relevance","relevance")),
                  "CONCEPT_RELEVANCE":(new,("relevance","relevance")),
                  "CONCEPT_DUAL_QUERY":(new,("relevance","pub_date"))}
            refs=[x["pmid"] for x in case[key]]
            control=[x["pmid"] for x in case.get("controls",[])]
            cache={}
            for arm,(queries,sorts) in arms.items():
                records={};logs=[]
                for q,sort in zip(queries,sorts):
                    if (q,sort) not in cache:cache[(q,sort)]=safe_search(clients[sort],q,12)
                    r=cache[(q,sort)]
                    for x in r.records:
                        if _pmid(x):records[_pmid(x)]=x
                    logs.append({"query":q,"sort":sort,"status":r.status.value,"total":r.total_count,"retrieved":len(r.records),"access":_access(r)})
                entry["arms"].setdefault(arm,{})[purpose]={"metrics":sample_metrics(refs,records,all(x["access"] for x in logs)),
                    "recent_2024_plus":sum(x.year is not None and x.year>=2024 for x in records.values()),"unique":len(records),
                    "controls":sorted(set(control)&records.keys()),"logs":logs}
        entry["reference_audit"]=exact_reference_audit(c,case,EuropePMCSource())
        out["cases"].append(entry);save()
        print(json.dumps({"case":entry["case"],"arms":{a:{k:{z:v[z] for z in ("metrics","recent_2024_plus","unique")} for k,v in x.items()} for a,x in entry["arms"].items()},"exact":entry["reference_audit"]["retrieved_count"],"expected":entry["reference_audit"]["expected_reference_count"]}),flush=True)
    out["status"]="COMPLETE";save()
if __name__=="__main__":main()
