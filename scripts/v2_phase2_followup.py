"""Follow-up after mixed hybrid ranking and non-count registry results."""
import json
from pathlib import Path
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.http import JsonHttpClient
from scimed_scout.discovery.structured_extraction_v2 import registry_leads
from scimed_scout.discovery.competitor_priority_v2 import focused_review_query
from scimed_scout.discovery.evidence_first import _record
from scimed_scout.discovery.novelty import _select_records
from scimed_scout.storage import CandidateRecord
def main():
    http=JsonHttpClient(timeout=15,retries=0,service="ctgov",min_interval=.3)
    pub=PubMedSource(JsonHttpClient(timeout=18,retries=1,service="ncbi",min_interval=.5),sort="relevance")
    report={"version":"V2_PHASE2_FOLLOWUP","ratio_checks":[],"focused_review_checks":[],"new_ai_requests":0,"qualification_granted":False}
    for nct,ref in [("NCT03036124",(.74,.65,.85)),("NCT03619213",(.82,.73,.92)),("NCT03057977",(.75,.65,.86))]:
        try:
            study=http.get_json("https://clinicaltrials.gov/api/v2/studies/"+nct)
            r=registry_leads(study,nct)["reported_ratio_estimates"]
            item={"registry":nct,"ratio_leads":len(r),"matches":[x for x in r if (x["ratio"],*x["reported_ci"])==ref],"analysis_field_examples":[{k:a.get(k) for k in ("paramType","ciNumSides","ciPctValue")} for o in study.get("resultsSection",{}).get("outcomeMeasuresModule",{}).get("outcomeMeasures",[])[:1] for a in o.get("analyses",[])[:2]]}
        except Exception as ex:item={"registry":nct,"status":"ACCESS_UNRESOLVED","error_type":type(ex).__name__}
        report["ratio_checks"].append(item);print(json.dumps(item),flush=True)
    for name,pop,inter,control,positive in [("cardiology","heart failure","dapagliflozin","placebo",{"36030328","42547169"}),("surgery","rectal cancer","robotic surgery","laparoscopic surgery",{"42581199","40022103","40770525","42223567"})]:
        c=CandidateRecord(name,"challenge","Q",name,population=pop,intervention_exposure_index_test=inter,comparator_reference=control)
        q=focused_review_query(c);r=pub.search(q,limit=40)
        ranked=_select_records(c,[{**_record(x),"evidence_type":"PUBLISHED_REVIEW"} for x in r.records],len(r.records))
        item={"topic":name,"query":q,"status":r.status.value,"total":r.total_count,"retrieved":len(r.records),"known_positive_ranks":{x["source_record_id"]:i+1 for i,x in enumerate(ranked) if x["source_record_id"] in positive},"known_positive_pmids":sorted(positive),"coverage_clearance_allowed":False}
        report["focused_review_checks"].append(item);print(json.dumps(item),flush=True)
    Path("v2-phase2-followup.json").write_text(json.dumps(report,indent=2)+"\n")
    print("V2_FOLLOWUP_SUMMARY "+json.dumps(report),flush=True)
if __name__=="__main__":main()
