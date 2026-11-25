"""Targeted live linkage and registry diagnostics; no AI, no production writes."""
from __future__ import annotations
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from scimed_scout.discovery.registration_enrichment import _routes, extract_registration, _error_code, LIMIT, OAI_NS, OWN
from scimed_scout.discovery.open_access_dates import _fetch_xml
from scimed_scout.discovery.trial_family import _ids
from scimed_scout.discovery.scientific_benchmark import _candidate, safe_search, _pmid
from scimed_scout.sources.europe_pmc import EuropePMCSource
from scimed_scout.sources.prospero import ProsperoCliSource
from scimed_scout.verification.queries import build_search_plan

# Gold labels are used only to score this diagnostic, never to populate search results.
GROUPS={
    "NCT03619213":["36027570","36054231"],
    "NCT03057977":["32865377","34861154"],
    "NCT03036124":["31535829","32653447"],
    "NCT03057951":["34449189"],
}
BIOC="https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/{}/unicode"
REGISTRY="https://clinicaltrials.gov/api/v2/studies/{}"
ROW={"source":"Europe PMC","source_record_id":"36054231","payload":{"metadata":{"pmid":"36054231","pmcid":"PMC9804680"}}}

def jats_status(raw):
    if len(raw)>LIMIT:return "RESPONSE_TOO_LARGE"
    if b"<!ENTITY" in raw.upper() or re.search(br"<!DOCTYPE[^>]*\[",raw,re.I):return "UNSAFE_XML"
    try:root=ET.fromstring(raw)
    except (ET.ParseError,ValueError):return "NOT_XML"
    if root.tag==f"{{{OAI_NS}}}OAI-PMH":
        ns={"oai":OAI_NS}
        err=root.find("./oai:error",ns)
        if err is not None:return "OAI_"+str(err.get("code") or "UNKNOWN")[:60]
        metadata=root.find("./oai:GetRecord/oai:record/oai:metadata",ns)
        if metadata is None or len(metadata)!=1:return "OAI_METADATA_MISSING"
        root=metadata[0]
    if root.tag.split("}")[-1]!="article":return "NOT_JATS_ARTICLE"
    tags={x.tag.split("}")[-1] for x in root.iter()}
    if "body" not in tags:return "METADATA_ONLY"
    return "JATS_BODY_PRESENT"

def bioc_status(raw,pmid,pmcid):
    if len(raw)>LIMIT:return {"status":"RESPONSE_TOO_LARGE"}
    try:data=json.loads(raw)
    except (ValueError,UnicodeError):return {"status":"NOT_JSON"}
    if isinstance(data,list):collections=data
    elif isinstance(data,dict):collections=[data]
    else:return {"status":"INVALID_SCHEMA"}
    docs=[d for c in collections if isinstance(c,dict) for d in c.get("documents",[]) if isinstance(d,dict)]
    if len(docs)!=1:return {"status":"DOCUMENT_COUNT_UNRESOLVED","count":len(docs)}
    doc=docs[0]; passages=doc.get("passages") or []
    ids={str(doc.get("id") or "")}
    for p in passages:
        if not isinstance(p,dict):continue
        info=p.get("infons") or {}
        for key in ("article-id_pmid","article-id_pmc","article-id_pmcid","pmid","pmcid"):
            if info.get(key):ids.add(str(info[key]))
    if not ids.intersection({pmid,pmcid,pmcid.removeprefix("PMC")}):return {"status":"IDENTITY_UNRESOLVED"}
    methods=[]
    for p in passages:
        if not isinstance(p,dict):continue
        info=p.get("infons") or {}
        if str(info.get("section_type") or "").upper() in ("METHODS","METHOD","MATERIALS AND METHODS"):
            methods.append(str(p.get("text") or ""))
    text=" ".join(methods)
    matches={m.group(1).upper() for m in OWN.finditer(text)}
    status="METHODS_OWN_TRIAL_LEAD" if len(matches)==1 and _ids(text)==matches else "NO_UNAMBIGUOUS_METHODS_LINK"
    return {"status":status,"methods_passages":len(methods),"registration_leads":sorted(matches),"identity_observed":True,"auto_merge":False}

def registry_refs(raw,nct,pmids):
    if len(raw)>LIMIT:return {"status":"RESPONSE_TOO_LARGE"}
    try:
        data=json.loads(raw);p=data["protocolSection"]
        if p["identificationModule"]["nctId"]!=nct:return {"status":"REGISTRY_ID_MISMATCH"}
        refs=p.get("referencesModule",{}).get("references",[])
        if not isinstance(refs,list):return {"status":"INVALID_REFERENCES"}
        exact={x:sorted({str(r.get("type") or "UNKNOWN") for r in refs if isinstance(r,dict) and str(r.get("pmid") or "")==x}) for x in pmids}
        return {"status":"CHECKED","reference_count":len(refs),"exact_pmids":exact,"auto_merge":False}
    except (ValueError,TypeError,KeyError,AttributeError):return {"status":"INVALID_REGISTRY_RESPONSE"}

def main():
    report={"schema":"TARGETED_SOURCE_DIAGNOSTIC_V1","ai_requests":0,"production_writes":False,"scientific_accuracy_validated":False}
    target=Path("targeted-source-report.json")
    def save():target.write_text(json.dumps(report,indent=2)+"\n")
    report["fulltext"]=[]
    for route,url in [*_routes("PMC9804680"),("NCBI_BIOC",BIOC.format("PMC9804680"))]:
        start=time.monotonic()
        try:
            raw=_fetch_xml(url)
            if route=="NCBI_BIOC":item=bioc_status(raw,"36054231","PMC9804680")
            else:
                evidence=extract_registration(ROW,raw,source_url=url)
                item={"status":jats_status(raw),"verified_link":bool(evidence),"registration_id":evidence["registration_id"] if evidence else None}
            item["bytes"]=len(raw)
        except Exception as exc:item={"status":"ACCESS_UNRESOLVED","error":_error_code(exc)}
        item.update(route=route,seconds=round(time.monotonic()-start,2))
        report["fulltext"].append(item);save();print(json.dumps({"fulltext":item}),flush=True)
    pmids=list(dict.fromkeys(x for group in GROUPS.values() for x in group))
    result=safe_search(EuropePMCSource(),"("+" OR ".join("EXT_ID:"+x for x in pmids)+") AND SRC:MED",len(pmids))
    report["exact_id_control"]={"expected":len(pmids),"retrieved":sorted({_pmid(x) for x in result.records if _pmid(x) in pmids}),"status":result.status.value}
    report["registry"]=[]
    for nct in GROUPS:
        try:item=registry_refs(_fetch_xml(REGISTRY.format(nct)),nct,pmids)
        except Exception as exc:item={"status":"ACCESS_UNRESOLVED","error":_error_code(exc)}
        item["nct"]=nct;report["registry"].append(item);save();print(json.dumps({"registry":item}),flush=True)
    report["registry_control_summary"]={"expected_report_count":len(pmids),"expected_family_count":len(GROUPS),"result_reference_hits":sum("RESULT" in r.get("exact_pmids",{}).get(p,[]) for r in report["registry"] for p in GROUPS[r["nct"]]),"derived_reference_hits":sum("DERIVED" in r.get("exact_pmids",{}).get(p,[]) for r in report["registry"] for p in GROUPS[r["nct"]]),"cross_family_result_references":[{"nct":r["nct"],"pmid":p} for r in report["registry"] for p in pmids if p not in GROUPS[r["nct"]] and "RESULT" in r.get("exact_pmids",{}).get(p,[])],"not_a_validation_of_independence":True}
    print(json.dumps({"control_summary":report["registry_control_summary"],"exact_id_control":report["exact_id_control"]}),flush=True);save()
    case=next(c for c in json.loads(Path("benchmarks/scientific_v1.json").read_text())["cases"] if c["id"]=="ARDS_PRONE")
    queries=build_search_plan(_candidate(case),max_queries=4).registry_queries
    report["prospero"]=[]
    for q in queries:
        result=ProsperoCliSource().search(q,limit=8)
        item={"query":q,"status":result.status.value,"reported":result.total_count,"retrieved":len(result.records),"diagnostic":str(result.message or "")[:350]}
        report["prospero"].append(item);save();print(json.dumps({"prospero":item}),flush=True)
    report["status"]="COMPLETE";save()
if __name__=="__main__":main()
