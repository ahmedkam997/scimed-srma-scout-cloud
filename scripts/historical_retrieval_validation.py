"""Historical-corpus paired test: same query, date ceiling and budgets.
Frozen reference labels never shape retrieval queries. PubMed URL IDs are normalized. Publication date is
a historical proxy for searchable availability; current indexing can differ.
"""
import argparse,json
from datetime import date
from pathlib import Path
from external_reference_validation import load_csv,retrieval,SYNERGY
from scimed_scout.discovery.stratified_retrieval import collect,date_query
from scimed_scout.discovery.rct_first import RCT_FILTER,REVIEW_FILTER
from scimed_scout.sources.pubmed import PubMedSource

CASES=[
 ("Oud_2018","1800-01-01","2017-11-13",'("borderline personality disorder"[tiab]) AND (psychotherapy[tiab] OR "dialectical behavior therapy"[tiab] OR "mentalization based"[tiab] OR "schema therapy"[tiab] OR "transference focused"[tiab]) AND '+RCT_FILTER,"RCT_REPORTS"),
 ("van_Dis_2019","1980-01-01","2019-01-31",'(anxiety[tiab] OR "anxiety disorder"[tiab] OR "post-traumatic stress"[tiab] OR obsessive-compulsive[tiab]) AND ("cognitive behavioral therapy"[tiab] OR "cognitive behavioural therapy"[tiab] OR CBT[tiab]) AND '+RCT_FILTER,"RCT_REPORTS"),
 ("Moseng_2024","2012-01-01","2022-05-27",'(osteoarthritis[tiab] OR "knee pain"[tiab]) AND (exercise[tiab] OR education[tiab] OR "weight loss"[tiab] OR nonpharmacological[tiab] OR "non-pharmacological"[tiab]) AND '+REVIEW_FILTER,"SYSTEMATIC_REVIEW_REPORTS"),
 ("Hilfiker_2017","1800-01-01","2017-01-31",'(cancer[tiab] OR neoplasms[mh]) AND (fatigue[tiab] OR fatigue[mh]) AND (exercise[tiab] OR rehabilitation[tiab] OR psychological[tiab] OR relaxation[tiab] OR nonpharmacological[tiab]) AND '+RCT_FILTER,"RANDOMIZED_OR_QUASI_RANDOMIZED_REPORTS"),
 ("Kerschbaumer_2024a","2019-01-01","2022-12-28",'("psoriatic arthritis"[tiab] OR "arthritis, psoriatic"[mh]) AND (DMARD[tiab] OR biologic*[tiab] OR methotrexate[tiab] OR drug therapy[sh] OR inhibitor*[tiab]) AND '+RCT_FILTER,"MIXED_EFFICACY_SAFETY_CORPUS_NOT_RCT_ONLY"),
]

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",required=True,type=Path);a=p.parse_args()
    out={"schema":"SCIMED_HISTORICAL_RETRIEVAL_V1","scientific_accuracy_validated":False,"new_ai_requests":0,"corpora":{}}
    def save():
        a.output.write_text(json.dumps(out,indent=2)+"\n");print(json.dumps(out),flush=True)
    ranked=PubMedSource(sort="relevance")
    mixed=PubMedSource(http=ranked.http,sort="mixed");mixed.api_key=ranked.api_key;mixed.email=ranked.email
    for key,lo,hi,query,scope in CASES:
        try:
            rows,h=load_csv(SYNERGY+key+"/"+key+"_ids.csv")
            start,end=date.fromisoformat(lo),date.fromisoformat(hi)
            baseline=mixed.search(date_query(query,start,end),limit=60)
            equal,eq=collect(ranked,query,start=start,end=end,budget=60)
            expanded,ex=collect(ranked,query,start=start,end=end,budget=240)
            out["corpora"][key]={"sha256":h,"scope":scope,"query":query,"start":lo,"end":hi,
                "baseline":{"status":baseline.status.value,"reported_hits":baseline.total_count,**retrieval(rows,baseline.records)},
                "equal_budget":{"audit":equal,**retrieval(rows,eq)},
                "expanded_budget":{"audit":expanded,**retrieval(rows,ex)}}
        except Exception as exc:out["corpora"][key]={"status":"ACCESS_OR_SCHEMA_UNRESOLVED","error_type":type(exc).__name__}
        save()
if __name__=="__main__":main()
