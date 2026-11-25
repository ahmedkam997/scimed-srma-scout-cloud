"""Live retrieval smoke check; no AI, no eligibility claim."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from scimed_scout.storage import CandidateRecord
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.europe_pmc import EuropePMCSource
from scimed_scout.verification.queries import build_search_plan
from .query_optimizer import optimized_queries,sample_quality

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    fixtures=[
        (CandidateRecord("COLCOT","P","Colchicine after myocardial infarction","Cardiology",
            population="Adults with recent myocardial infarction",intervention_exposure_index_test="Colchicine",
            search_terms=["colchicine","myocardial infarction"]),"31733140"),
        (CandidateRecord("EMPEROR-Preserved","P","Empagliflozin in heart failure","Cardiology",
            population="Heart failure with preserved ejection fraction",intervention_exposure_index_test="Empagliflozin",
            search_terms=["empagliflozin","heart failure"]),"34449189"),
    ]
    out={"version":"QUERY_OPTIMIZER_SMOKE_V1","cases":[],"new_ai_requests":0,
         "scientific_accuracy_validated":False,
         "limitations":"Exact PMID intersection tests syntax/known record retrieval only, not rank, recall or eligible-study count. Broad and focused samples use the same record cap."}
    for candidate,pmid in fixtures:
        for source in (PubMedSource(),EuropePMCSource()):
            old=build_search_plan(candidate).primary_queries
            new=optimized_queries(candidate,source.name,"PRIMARY",old,max_queries=4)
            original=source.search(old[0],limit=8)
            optimized=source.search(new[0],limit=8)
            exact=f"({new[0]}) AND {pmid}[PMID]" if source.name=="PubMed" else f"({new[0]}) AND EXT_ID:{pmid} AND SRC:MED"
            check=source.search(exact,limit=2)
            entry={"case":candidate.candidate_id,"source":source.name,"old_query":old[0],"optimized_query":new[0],
                "old_sample":sample_quality(original),"optimized_sample":sample_quality(optimized),
                "known_pmid":pmid,"known_record_status":check.status.value,
                "known_record_retrieved":any(r.record_id==pmid and bool(r.title) for r in check.records)}
            out["cases"].append(entry)
            args.output.write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
            print(json.dumps(entry),flush=True)
    out["known_record_checks_passed"]=sum(r["known_record_retrieved"] for r in out["cases"])
    out["known_record_checks_total"]=len(out["cases"])
    out["status"]="KNOWN_RECORD_CHECKS_PASSED" if out["known_record_checks_passed"]==len(out["cases"]) else "KNOWN_RECORD_CHECKS_INCOMPLETE"
    args.output.write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in out.items() if k!="cases"}),flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
