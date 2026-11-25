"""Bounded open-access Methods registration enrichment.

Identity-verified JATS only; no acronym-only merges or references mining.
A registration link is not proof of eligible independent participants.
"""
from __future__ import annotations
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
import xml.etree.ElementTree as ET
from .open_access_dates import _pmcid,_fetch_xml
from .trial_family import registration_signals,_ids
from .pico_matching import _pmid

# Own-trial statements; generic mentions of past trials are not evidence.
OWN=re.compile(r"\b(?:the|this|our)\s+trial\s+(?:is|was)\s+registered\s+(?:at|with|in|on)\s+ClinicalTrials\.gov\s*[:;(,\s]*(?:identifier\s*[:;\s]*)?(NCT\d{8})\b",re.I)
LIMIT=1_500_000
OAI_NS="http://www.openarchives.org/OAI/2.0/"

def _routes(pmcid):
    yield "EUROPE_PMC_JATS",f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
    yield "NCBI_PMC_OAI", "https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/?"+urlencode({
        "verb":"GetRecord","identifier":"oai:pubmedcentral.nih.gov:"+pmcid.removeprefix("PMC"),"metadataPrefix":"pmc"})

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
    unique={x[0] for x in hits}
    if len(unique)!=1 or all_ids!=unique:return None
    trial,quote=hits[0]
    return {"registration_id":trial,"quote":quote[:200],
        "source_url":source_url or f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
        "pmid":pmid,"pmcid":pmcid,"scope":"OWN_TRIAL_REGISTRATION_IN_METHODS",
        "independence_confirmed":False}

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
                    evidence=extract_registration(row,raw,source_url=url)
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
    return out,{"method":"OPEN_ACCESS_REGISTRATION_V2","source_calls":attempts,"records_linked":sum(a["status"]=="LINK_FOUND" for a in audit),"attempts":audit,"independence_confirmed":False}

def enrich_ledger(ledger,candidate_id,*,fetcher=None,max_lookups=3):
    rows=ledger.list_external_evidence(candidate_id,"PRIMARY_STUDY")
    changed,audit=enrich_records(rows,fetcher=fetcher,max_lookups=max_lookups)
    for old,new in zip(rows,changed):
        if old is new:continue
        ledger.upsert_external_evidence(candidate_id,"PRIMARY_STUDY",new["source_record_id"],
            source=new.get("source",""),title=new.get("title",""),payload=new["payload"])
    return audit
