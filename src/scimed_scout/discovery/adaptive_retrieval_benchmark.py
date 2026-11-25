"""Development replay comparing fixed baseline and supplemental retrieval."""
import argparse,json
from pathlib import Path
from .scientific_benchmark import _candidate,_pmid,_access,sample_metrics,safe_search
from .adaptive_retrieval import collect,row
from .query_optimizer import optimized_queries
from .evidence_classification import classify_review_search_hit,review_intervention_citation_signal
from scimed_scout.verification.queries import build_search_plan
from scimed_scout.sources.pubmed import PubMedSource

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);args=p.parse_args()
    fixture=json.loads(Path("benchmarks/ranking_v3.json").read_text())
    out={"schema":"ADAPTIVE_RETRIEVAL_DEVELOPMENT_V1","scientific_accuracy_validated":False,"new_ai_requests":0,"cases":[]}
    def save():args.output.write_text(json.dumps(out,indent=2)+"\n")
    client=PubMedSource(sort="pub_date")
    for case in fixture["cases"]:
        c=_candidate(case);plan=build_search_plan(c,max_queries=2)
        entry={"case":case["id"],"purposes":{}}
        for purpose,legacy,key in (("PRIMARY",plan.primary_queries,"primary"),("REVIEW",plan.review_queries,"reviews")):
            refs=[r["pmid"] for r in case[key]]
            results=[safe_search(client,q,12) for q in optimized_queries(c,"PubMed",purpose,legacy,max_queries=2)]
            base_records=[r for x in results for r in x.records];access=bool(results) and all(_access(x) for x in results)
            classified=[r for r in base_records if (classify_review_search_hit(r)!="CONFIRMED_REVIEW_CUE" if purpose=="PRIMARY" else classify_review_search_hit(r)=="CONFIRMED_REVIEW_CUE" and review_intervention_citation_signal(c,r)=="INTERVENTION_IN_REVIEW_CITATION")]
            report,supp=collect(c,purpose,legacy,[row(r) for r in classified],client,initial_limit=12,base_access=access)
            b={_pmid(r) for r in base_records if _pmid(r)}
            a=b|{_pmid(r) for r in supp if _pmid(r)}
            entry["purposes"][purpose]={"baseline":sample_metrics(refs,b,access),"adaptive_union":sample_metrics(refs,a,access and report["status"]!="SUPPLEMENTARY_ACCESS_UNRESOLVED"),"baseline_unique":len(b),"union_unique":len(a),"new_reference_pmids":sorted(set(refs)&(a-b)),"audit":report}
        out["cases"].append(entry);save();print(json.dumps(entry),flush=True)
    out["status"]="COMPLETE";save()
if __name__=="__main__":main()
