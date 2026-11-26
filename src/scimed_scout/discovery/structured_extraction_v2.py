"""Bounded evidence extraction. Source facts are leads, never adjudicated eligibility."""
import re,hashlib,xml.etree.ElementTree as ET
from .competitor_records import identifiers,abstract
from .open_access_dates import _pmcid,_fetch_xml
from .registry_outcomes import extract
from .trial_family import registration_signals

VERSION="STRUCTURED_EXTRACTION_V2"
def text(node):return " ".join("".join(node.itertext()).split()) if node is not None else ""
def abstract_counts(row):
    # Explicit count/denominator only. No percentages converted into counts;
    # no interpretation of arm, endpoint, study independence or timepoint.
    out=[]
    raw=abstract(row)
    for m in re.finditer(r"(?<![\d.])([\d,]+)\s+of\s+([\d,]+)\s+(?:patients|participants|subjects)\b",raw,re.I):
        a,n=(int(x.replace(",","")) for x in m.groups())
        if 0<=a<=n and n>0:
            out.append({"events":a,"denominator":n,"locator":f"abstract:characters:{m.start()}-{m.end()}",
                        "context":raw[max(0,m.start()-65):min(len(raw),m.end()+65)],"arm_mapping_verified":False})
    return out[:30]

def registry_leads(study,nct):
    p=study.get("protocolSection") or {}
    if (p.get("identificationModule") or {}).get("nctId")!=nct:return {"status":"IDENTITY_MISMATCH","pooling_allowed":False}
    d=p.get("designModule") or {};a=p.get("armsInterventionsModule") or {}
    design=d.get("designInfo") or {}
    groups=[]
    for outcome in extract(study,nct):
        # Only explicitly labeled participant counts; no unit conversion, no
        # inference from enrollment or percentages, no automatic arm mapping.
        if outcome["truncated"] or outcome["measure_type"]!="COUNT_OF_PARTICIPANTS":continue
        den={};vals={};ambiguous=False
        for r in outcome["denominators"]:
            k=r["group_id"];s=str(r.get("value") or "")
            if k in den or not s.isdigit() or str(r.get("units") or "").casefold() not in ("participants","participant","patients"):ambiguous=True;break
            den[k]=int(s)
        for r in outcome["measurements"]:
            k=r["group_id"];s=str(r.get("value") if r.get("value") is not None else "")
            if k in vals or not s.isdigit():ambiguous=True;break
            vals[k]=int(s)
        expected={g["id"] for g in outcome["groups"]}
        if ambiguous or len(expected)!=2 or set(den)!=expected or set(vals)!=expected or any(den[k]<=0 or not 0<=vals[k]<=den[k] for k in expected):continue
        groups.append({"title":outcome["title"],"time_frame":outcome["time_frame"],"locator":outcome["locator"],"url":outcome["url"],
                       "groups":[{"group_id":g["id"],"label":g["title"],"events":vals[g["id"]],"denominator":den[g["id"]]} for g in outcome["groups"]],
                       "arm_mapping_verified":False,"pooling_allowed":False})
    return {"status":"REGISTRY_LEADS","registry_id":nct,"study_type":d.get("studyType"),"allocation":design.get("allocation"),
            "intervention_model":design.get("interventionModel"),"enrollment":(d.get("enrollmentInfo") or {}).get("count"),
            "protocol_arms":[{"label":x.get("label"),"type":x.get("type"),"interventions":x.get("interventionNames",[])} for x in a.get("armGroups",[]) if isinstance(x,dict)],
            "numeric_outcome_leads":groups,"eligibility_confirmed":False,"independence_confirmed":False,"pooling_allowed":False}

def jats_leads(row,raw):
    pmc=_pmcid(row);ids=identifiers(row)
    if not pmc or not isinstance(raw,bytes) or len(raw)>1500000 or b"<!ENTITY" in raw.upper() or re.search(br"<!DOCTYPE[^>]*\[",raw,re.I):return {"status":"UNRESOLVED"}
    try:root=ET.fromstring(raw)
    except (ValueError,ET.ParseError):return {"status":"UNRESOLVED"}
    front=root.find("./front/article-meta")
    if root.tag!="article" or front is None:return {"status":"IDENTITY_MISMATCH"}
    actual={x.get("pub-id-type"):text(x) for x in front.findall("article-id")}
    p=(actual.get("pmc") or actual.get("pmcid") or "").upper().removeprefix("PMC")
    if p!=pmc.removeprefix("PMC") or any(len(v)>1 for v in ids.values()) or (ids["pmid"] and actual.get("pmid") not in ids["pmid"]) or (ids["doi"] and str(actual.get("doi","")).casefold() not in ids["doi"]):
        return {"status":"IDENTITY_MISMATCH"}
    body=root.find("body")
    if body is None:return {"status":"BODY_UNAVAILABLE"}
    tables=[];methods=[]
    for i,tab in enumerate(body.findall(".//table-wrap")):
        # Preserve raw cell layout with spans. Do not guess header mapping.
        rows=[]
        for tr in tab.findall(".//tr"):
            cells=[{"text":text(c)[:250],"rowspan":c.get("rowspan","1"),"colspan":c.get("colspan","1"),"header":c.tag=="th"} for c in tr if c.tag in ("th","td")]
            if cells:rows.append(cells[:20])
        if rows:tables.append({"locator":tab.get("id") or f"table-wrap[{i}]","caption":text(tab.find("caption"))[:300],"rows":rows[:35],"truncated":len(rows)>35 or any(len(r)>=20 for r in rows)})
        if len(tables)>=6:break
    for i,sec in enumerate(body.findall(".//sec")):
        if not re.search(r"\b(methods?|trial design|study design)\b",text(sec.find("title")),re.I):continue
        for j,p in enumerate(sec.findall("./p")):
            x=text(p)
            if re.search(r"\b(randomi[sz]|allocat|eligib|exclu|inclus|participants|enrol)",x,re.I):
                methods.append({"locator":f"body/sec[{i}]/p[{j}]","excerpt":x[:250]})
                if len(methods)>=8:break
        if len(methods)>=8:break
    return {"status":"JATS_SOURCE_LINKED_LEADS","url":"https://www.ebi.ac.uk/europepmc/webservices/rest/"+pmc+"/fullTextXML","sha256":hashlib.sha256(raw).hexdigest(),
            "tables":tables,"methods":methods,"eligibility_confirmed":False,"pooling_allowed":False}

def collect(rows,*,fetcher=None,previous=None,max_fulltexts=3,check=None):
    fetcher=fetcher or _fetch_xml
    prior={(x["source"],x["record_id"]):x for x in (previous or {}).get("reports",[])}
    results=[];calls=0
    ordered=sorted(rows,key=lambda r:(bool(prior.get((r["source"],r["source_record_id"]),{}).get("fulltext")),not bool(_pmcid(r)),r["source"],r["source_record_id"]))
    for r in ordered:
        k=(r["source"],r["source_record_id"]);entry={"source":k[0],"record_id":k[1],"url":(r.get("payload") or {}).get("url"),"registration_ids":sorted(registration_signals(r)),"abstract_count_leads":abstract_counts(r)}
        old=prior.get(k,{})
        pmc=_pmcid(r);prev=old.get("fulltext") or {}
        if prev.get("status")=="JATS_SOURCE_LINKED_LEADS":entry["fulltext"]=prev
        elif pmc and calls<min(3,max(0,max_fulltexts)):
            if check:check()
            calls+=1
            try:entry["fulltext"]=jats_leads(r,fetcher("https://www.ebi.ac.uk/europepmc/webservices/rest/"+pmc+"/fullTextXML"))
            except Exception as ex:entry["fulltext"]={"status":"ACCESS_UNRESOLVED","error_type":type(ex).__name__}
        elif prev:entry["fulltext"]=prev
        results.append(entry)
    return {"version":VERSION,"reports":results,"source_calls":calls,"eligibility_confirmed":False,"pooling_allowed":False}
