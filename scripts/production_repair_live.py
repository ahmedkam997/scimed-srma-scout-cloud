"""Small live, no-AI recovery probe for the exact scopes observed in production.
No qualification or comprehensive novelty claim; network results may vary.
"""
import json
from pathlib import Path
from scimed_scout.sources.clinicaltrials import ClinicalTrialsGovSource
from scimed_scout.sources.prospero import ProsperoCliSource
from scimed_scout.discovery.registry_outcomes import extract
from scimed_scout.sources.http import JsonHttpClient

def brief(r):
    return {"status":r.status.value,"total":r.total_count,"retrieved":len(r.records),"diagnostic":r.message}
def main():
    out={"schema":"SCIMED_PRODUCTION_REPAIR_LIVE_V1","new_ai_requests":0,"qualification_granted":False,"sources":{}}
    for src,query in [(ClinicalTrialsGovSource(),"catheter ablation medical therapy"),(ProsperoCliSource(),'"catheter ablation" AND "atrial fibrillation"')]:
        base=src.search(query);recovered=src.search_recovery(query,checkpoint=base.continuation,previous_records=base.records) if isinstance(src,ProsperoCliSource) else src.search_recovery(query)
        a={r.record_id for r in base.records};b={r.record_id for r in recovered.records}
        out["sources"][src.name]={"query":query,"baseline":brief(base),"recovery":brief(recovered),"new_ids":len(b-a),"baseline_ids_not_in_recovery":len(a-b),"same_query":base.query==recovered.query}
        if isinstance(src,ProsperoCliSource):
            chain=[];current=recovered
            for _ in range(3):
                if not current.continuation:break
                nxt=src.search_recovery(query,checkpoint=current.continuation,previous_records=current.records)
                chain.append({**brief(nxt),"baseline_ids_not_in_recovery":len(a-{r.record_id for r in nxt.records})})
                current=nxt
            out["sources"][src.name]["continuation_passes"]=chain
        print(json.dumps(out),flush=True)
    try:
        nct="NCT03057977"  # EMPEROR-Reduced, exact registry source
        study=JsonHttpClient(timeout=15,retries=0).get_json("https://clinicaltrials.gov/api/v2/studies/"+nct)
        rows=extract(study,nct)
        out["registry_outcomes"]={"registry_id":nct,"outcome_leads":len(rows),"examples":[{"title":r["title"],"time_frame":r["time_frame"],"measurements":len(r["measurements"]),"locator":r["locator"],"pooling_allowed":r["pooling_allowed"]} for r in rows[:3]]}
    except Exception as exc:out["registry_outcomes"]={"status":"UNRESOLVED","error_type":type(exc).__name__}
    Path("production-repair-live.json").write_text(json.dumps(out,indent=2)+"\n")
    print(json.dumps(out),flush=True)
if __name__=="__main__":main()
