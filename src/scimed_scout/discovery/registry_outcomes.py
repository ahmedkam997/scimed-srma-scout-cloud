"""Source-backed ClinicalTrials.gov outcome result leads; no arm mapping/eligibility claim."""
from math import isfinite

def extract(study,nct,*,max_outcomes=12,max_rows=80):
    p=study.get("protocolSection") or {}
    if (p.get("identificationModule") or {}).get("nctId")!=nct:return []
    module=(study.get("resultsSection") or {}).get("outcomeMeasuresModule") or {}
    out=[]
    for idx,o in enumerate(module.get("outcomeMeasures") or []):
        if not isinstance(o,dict) or len(out)>=max_outcomes:break
        group_rows=o.get("groups") or []
        if not isinstance(group_rows,list):continue
        groups={g["id"]:{"id":g["id"],"title":str(g.get("title") or ""),"description":str(g.get("description") or "")[:400]} for g in group_rows if isinstance(g,dict) and isinstance(g.get("id"),str) and g.get("title")}
        if len(groups)!=len(group_rows) or not groups:continue
        denominators=[];values=[]
        for count in o.get("denoms") or []:
            if not isinstance(count,dict):continue
            for v in count.get("counts") or []:
                if isinstance(v,dict) and v.get("groupId") in groups:
                    denominators.append({"group_id":v["groupId"],"value":v.get("value"),"units":count.get("units")})
        for cls in o.get("classes") or []:
            if not isinstance(cls,dict):continue
            for cat in cls.get("categories") or []:
                if not isinstance(cat,dict):continue
                for m in cat.get("measurements") or []:
                    if not isinstance(m,dict) or m.get("groupId") not in groups or "value" not in m:continue
                    values.append({"group_id":m["groupId"],"class":cls.get("title"),"category":cat.get("title"),"value":m.get("value"),"spread":m.get("spread"),"lower_limit":m.get("lowerLimit"),"upper_limit":m.get("upperLimit")})
        if not values:continue
        out.append({"registry_id":nct,"url":"https://clinicaltrials.gov/study/"+nct+"?tab=results",
                    "locator":f"resultsSection.outcomeMeasuresModule.outcomeMeasures[{idx}]",
                    "title":o.get("title"),"description":o.get("description"),"time_frame":o.get("timeFrame"),
                    "measure_type":o.get("paramType"),"dispersion_type":o.get("dispersionType"),"units":o.get("unitOfMeasure"),
                    "groups":list(groups.values()),"denominators":denominators[:max_rows],"measurements":values[:max_rows],
                    "truncated":len(values)>max_rows or len(denominators)>max_rows,"status":"REGISTRY_REPORTED_OUTCOME_NOT_PUBLISHED_DATA_VERIFIED",
                    "arm_mapping_verified":False,"independent_trial_verified":False,"pooling_allowed":False})
    return out
