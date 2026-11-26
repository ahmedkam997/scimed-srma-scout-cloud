"""Bounded open-access Methods registration enrichment.

Identity-verified JATS or BioC Methods only; no acronym-only merges or references mining.
A registration link is not proof of eligible independent participants.
"""
from __future__ import annotations
import re
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
import xml.etree.ElementTree as ET
from .open_access_dates import _pmcid,_fetch_xml
from .trial_family import registration_signals,_ids
from .pico_matching import _pmid

# Own-trial statements; generic mentions of past trials are not evidence.
OWN=re.compile(r"\b(?:the|this|our)\s+trial\s+(?:is|was)\s+registered\s+(?:at|with|in|on)\s+ClinicalTrials\.gov\s*[:;(,\s]*(?:identifier\s*[:;\s]*)?(NCT\d{8})\b",re.I)
OWN_AS=re.compile(r"\b(?:the|this|our)\s+trial\s+(?:is|was)\s+registered\s+as\s+ClinicalTrials\.gov\s+Identifier\s*:\s*(NCT\d{8})\b",re.I)
LIMIT=1_500_000
OAI_NS="http://www.openarchives.org/OAI/2.0/"

def _routes(pmcid):
    yield "EUROPE_PMC_JATS",f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
    yield "NCBI_PMC_OAI", "https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/?"+urlencode({
        "verb":"GetRecord","identifier":"oai:pubmedcentral.nih.gov:"+pmcid.removeprefix("PMC"),"metadataPrefix":"pmc"})
    yield "NCBI_BIOC",f"https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/{pmcid}/unicode"

def _error_code(exc):
    if isinstance(exc,HTTPError):return f"HTTP_{exc.code}"
    if isinstance(exc,TimeoutError) or (isinstance(exc,URLError) and isinstance(exc.reason,TimeoutError)):return "TIMEOUT"
    if isinstance(exc,URLError):return "URL_ERROR"
    return type(exc).__name__

def extract_registration(row,raw,*,source_url=None):
    pmid=_pmid(row);pmcid=_pmcid(row)
    if not pmid or not pmcid or not isinstance(raw,bytes) or len(raw)>LIMIT:
        return None
    if b"<!ENTITY" in raw.upper() or re.search(br"<!DOCTYPE[^>]*\[",raw,re.I):
        return None
    try: root=ET.fromstring(raw)
    except (ET.ParseError,ValueError):return None
    if root.tag==f"{{{OAI_NS}}}OAI-PMH":
        ns={"oai":OAI_NS}
        metadata=root.find("./oai:GetRecord/oai:record/oai:metadata",ns)
        if metadata is None or len(metadata)!=1:return None
        root=metadata[0]
        # The OAI envelope may supply a default namespace to otherwise plain JATS.
        if root.tag==f"{{{OAI_NS}}}article":
            for node in root.iter():
                if node.tag.startswith(f"{{{OAI_NS}}}"):node.tag=node.tag.split("}",1)[1]
    if root.tag!="article":return None
    front=root.find("./front/article-meta")
    if front is None:return None
    ids={e.get("pub-id-type"):str(e.text or "").strip() for e in front.findall("article-id")}
    if ids.get("pmid")!=pmid:return None
    actual=ids.get("pmc") or ids.get("pmcid")
    if actual and actual.upper().removeprefix("PMC")!=pmcid.removeprefix("PMC"):return None
    hits=[];all_ids=set()
    for sec in root.findall("./body//sec"):
        title=" ".join(sec.find("title").itertext()) if sec.find("title") is not None else ""
        if not re.search(r"\b(?:methods?|study design|trial design|patients and methods)\b",title,re.I):continue
        # Restrict to Methods; bibliography and discussion never qualify.
        for para in sec.findall("./p"):
            text=" ".join("".join(para.itertext()).split())
            all_ids.update(_ids(text))
            for m in OWN.finditer(text):
                hits.append((m.group(1).upper(),m.group(0)))
    # An explicitly attributed registration statement can appear before
    # Methods (e.g. the DAPA-HF design article). Only initial/direct body
    # or Introduction paragraphs are eligible, not Discussion/references.
    body=root.find("body")
    if body is not None:
        early=list(body.findall("./p"))
        for sec in body.findall("./sec"):
            heading=" ".join(sec.find("title").itertext()) if sec.find("title") is not None else ""
            if re.fullmatch(r"\s*(?:introduction|background)\s*",heading,re.I):early.extend(sec.findall("./p"))
        for para in early:
            text=" ".join("".join(para.itertext()).split())
            for m in OWN_AS.finditer(text):
                if _ids(text)=={m.group(1).upper()}:
                    hits.append((m.group(1).upper(),m.group(0)));all_ids.update(_ids(text))
    unique={x[0] for x in hits}
    if len(unique)!=1 or all_ids!=unique:return None
    trial,quote=hits[0]
    return {"registration_id":trial,"quote":quote[:200],
        "source_url":source_url or f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
        "pmid":pmid,"pmcid":pmcid,"scope":"OWN_TRIAL_REGISTRATION_EARLY_BODY" if OWN_AS.search(quote) else "OWN_TRIAL_REGISTRATION_IN_METHODS",
        "independence_confirmed":False}

def extract_bioc_registration(row,raw,*,source_url):
    """Require exact article identity and own-trial Methods statement.
    
    BioC is queried by the independently observed PMCID. Reject conflicting
    explicit identifiers even if the returned document ID is correct.
    """
    pmid=_pmid(row);pmcid=_pmcid(row)
    if not pmid or not pmcid or not isinstance(raw,bytes) or len(raw)>LIMIT:return None
    try:
        data=json.loads(raw)
        collections=data if isinstance(data,list) else [data]
        docs=[d for c in collections if isinstance(c,dict) for d in c.get("documents",[]) if isinstance(d,dict)]
        if len(docs)!=1:return None
        doc=docs[0];passages=doc.get("passages") or []
        if not isinstance(passages,list):return None
        doc_id=str(doc.get("id") or "").upper()
        expected_pmc=pmcid.upper().removeprefix("PMC")
        seen_pmid=set();seen_pmc=set();methods=[]
        for p in passages:
            if not isinstance(p,dict):return None
            info=p.get("infons") or {}
            if not isinstance(info,dict):return None
            for key in ("article-id_pmid","pmid"):
                if info.get(key):seen_pmid.add(str(info[key]).strip())
            for key in ("article-id_pmc","article-id_pmcid","pmcid"):
                if info.get(key):seen_pmc.add(str(info[key]).strip().upper().removeprefix("PMC"))
            if str(info.get("section_type") or "").upper() in ("METHODS","METHOD","MATERIALS AND METHODS"):
                methods.append(str(p.get("text") or ""))
        if seen_pmid and seen_pmid!={pmid}:return None
        if seen_pmc and seen_pmc!={expected_pmc}:return None
        # Accept exact PMCID document identity (the PMCID-PMID mapping was
        # already obtained from the bibliographic source); otherwise demand
        # both explicit identifiers. An arbitrary ID or PMID alone is not enough.
        if doc_id not in (pmcid.upper(),expected_pmc) and not (seen_pmid=={pmid} and seen_pmc=={expected_pmc}):return None
        hits=[m for text in methods for m in OWN.finditer(text)]
        unique={m.group(1).upper() for m in hits}
        if len(unique)!=1 or _ids(" ".join(methods))!=unique:return None
        return {"registration_id":next(iter(unique)),"quote":hits[0].group(0)[:200],
                "source_url":source_url,"pmid":pmid,"pmcid":pmcid,
                "scope":"OWN_TRIAL_REGISTRATION_IN_BIOC_METHODS","independence_confirmed":False}
    except (ValueError,TypeError,AttributeError,KeyError,UnicodeError):return None

def enrich_records(rows,*,fetcher=None,max_lookups=3):
    fetcher=fetcher or _fetch_xml
    audit=[];out=list(rows);attempts=0;cache={}
    # Prefer apparently secondary reports (known under-linking risk).
    ranked=sorted(enumerate(rows),key=lambda x:(
        not bool(re.search(r"\b(?:analysis|subgroup|follow.up|secondary)\b",str(x[1].get("title") or ""),re.I)),x[0]))
    for index,row in ranked:
        if registration_signals(row):continue
        pmcid=_pmcid(row);pmid=_pmid(row)
        if not pmcid or not pmid:continue
        key=(pmid,pmcid)
        if key not in cache:
            if attempts>=max(0,min(3,int(max_lookups))):continue
            cache[key]=None;route_audit=[];status="ACCESS_UNRESOLVED"
            for route,url in _routes(pmcid):
                if attempts>=max(0,min(3,int(max_lookups))):break
                attempts+=1
                try:
                    raw=fetcher(url)
                    evidence=(extract_bioc_registration(row,raw,source_url=url) if route=="NCBI_BIOC" else extract_registration(row,raw,source_url=url))
                    if evidence:
                        cache[key]=evidence;status="LINK_FOUND"
                        route_audit.append({"route":route,"status":status})
                        break
                    # Non-JATS, OAI rights errors, identity mismatches and absent
                    # statements are all unresolved, never negative trial evidence.
                    route_audit.append({"route":route,"status":"NO_VERIFIED_LINK"})
                except Exception as exc:
                    route_audit.append({"route":route,"status":"ACCESS_UNRESOLVED","error":_error_code(exc)})
            audit.append({"pmid":pmid,"pmcid":pmcid,"status":status,"evidence":cache[key],"routes":route_audit})
        evidence=cache[key]
        if evidence:
            payload=dict(row.get("payload") or {})
            meta=dict(payload.get("metadata") or {})
            meta["trial_registration_id"]=evidence["registration_id"]
            meta["registration_enrichment_evidence"]=evidence
            payload["metadata"]=meta
            out[index]={**row,"payload":payload}
    return out,{"method":"OPEN_ACCESS_REGISTRATION_V3","source_calls":attempts,"records_linked":sum(a["status"]=="LINK_FOUND" for a in audit),"attempts":audit,"independence_confirmed":False}

def enrich_fair(rows,*,fetcher=None,max_lookups=3,previous=None,check=None):
    """Spend first requests on different reports, rotate attempts on resume."""
    fetcher=fetcher or _fetch_xml
    cap=max(0,min(3,int(max_lookups)))
    old=(previous or {}).get("attempts",[])
    counts={}
    for a in old:
        k=(a.get("pmid"),a.get("pmcid"));counts[k]=len(a.get("routes",[]))
    eligible={}
    for i,r in enumerate(rows):
        if registration_signals(r):continue
        p,m=_pmid(r),_pmcid(r)
        if p and m:eligible.setdefault((p,m),(i,r))
    ordered=sorted(eligible,key=lambda k:(counts.get(k,0),not bool(re.search(r"\b(?:analysis|subgroup|follow.up|secondary)\b",str(eligible[k][1].get("title") or ""),re.I)),k))
    out=list(rows);audit=[];calls=0;linked={}
    for k in ordered:
        if calls>=cap:break
        # Each report receives at most one route per pass. Previously
        # attempted reports use next route; no repeat of exhausted routes.
        routes=list(_routes(k[1]));n=counts.get(k,0)
        if n>=len(routes):continue
        if check:check()
        route,url=routes[n];calls+=1
        r=eligible[k][1];e=None
        item={"route":route,"status":"NO_VERIFIED_LINK"}
        try:
            raw=fetcher(url)
            e=extract_bioc_registration(r,raw,source_url=url) if route=="NCBI_BIOC" else extract_registration(r,raw,source_url=url)
            if e:item["status"]="LINK_FOUND";linked[k]=e
        except Exception as exc:item.update(status="ACCESS_UNRESOLVED",error=_error_code(exc))
        audit.append({"pmid":k[0],"pmcid":k[1],"status":"LINK_FOUND" if e else "ACCESS_UNRESOLVED","evidence":e,"routes":[item]})
    merged={(a["pmid"],a["pmcid"]):dict(a) for a in old if a.get("pmid") and a.get("pmcid")}
    for a in audit:
        k=(a["pmid"],a["pmcid"]);prior=merged.get(k,{})
        merged[k]={**a,"routes":[*prior.get("routes",[]),*a["routes"]]}
    for i,r in enumerate(rows):
        if registration_signals(r):continue
        if e:=linked.get((_pmid(r),_pmcid(r))):
            p=dict(r.get("payload") or {});m=dict(p.get("metadata") or {})
            m.update(trial_registration_id=e["registration_id"],registration_enrichment_evidence=e);p["metadata"]=m
            out[i]={**r,"payload":p}
    return out,{"method":"OPEN_ACCESS_REGISTRATION_FAIR_V1","source_calls":calls,"records_linked":len(linked),"attempts":list(merged.values()),"new_attempts":audit,"remaining_report_routes":sum(max(0,3-len(merged.get(k,{}).get("routes",[]))) for k in eligible if k not in linked),"independence_confirmed":False}

def enrich_ledger(ledger,candidate_id,*,fetcher=None,max_lookups=3,fair=False,previous=None,check=None):
    rows=ledger.list_external_evidence(candidate_id,"PRIMARY_STUDY")
    changed,audit=(enrich_fair(rows,fetcher=fetcher,max_lookups=max_lookups,previous=previous,check=check) if fair else enrich_records(rows,fetcher=fetcher,max_lookups=max_lookups))
    for old,new in zip(rows,changed):
        if old is new:continue
        ledger.upsert_external_evidence(candidate_id,"PRIMARY_STUDY",new["source_record_id"],
            source=new.get("source",""),title=new.get("title",""),payload=new["payload"])
    return audit
