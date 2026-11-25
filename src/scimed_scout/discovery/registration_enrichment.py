"""Bounded open-access Methods registration enrichment.

Identity-verified JATS only; no acronym-only merges or references mining.
A registration link is not proof of eligible independent participants.
"""
from __future__ import annotations
import re
import xml.etree.ElementTree as ET
from .open_access_dates import _pmcid,_fetch_xml
from .trial_family import registration_signals,_ids
from .pico_matching import _pmid

# Own-trial statements; generic mentions of past trials are not evidence.
OWN=re.compile(r"\b(?:the|this|our)\s+trial\s+(?:is|was)\s+registered\s+(?:at|with|in|on)\s+ClinicalTrials\.gov\s*[:;(,\s]*(?:identifier\s*[:;\s]*)?(NCT\d{8})\b",re.I)
LIMIT=1_500_000

def extract_registration(row,raw):
    pmid=_pmid(row);pmcid=_pmcid(row)
    if not pmid or not pmcid or not isinstance(raw,bytes) or len(raw)>LIMIT:
        return None
    if b"<!ENTITY" in raw.upper() or re.search(br"<!DOCTYPE[^>]*\[",raw,re.I):
        return None
    try: root=ET.fromstring(raw)
    except (ET.ParseError,ValueError):return None
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
        "source_url":f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
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
            attempts+=1
            try:
                raw=fetcher(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML")
                cache[key]=extract_registration(row,raw)
                status="LINK_FOUND" if cache[key] else "NO_UNAMBIGUOUS_OWN_TRIAL_STATEMENT"
            except Exception:
                cache[key]=None;status="ACCESS_UNRESOLVED"
            audit.append({"pmid":pmid,"pmcid":pmcid,"status":status,"evidence":cache[key]})
        evidence=cache[key]
        if evidence:
            payload=dict(row.get("payload") or {})
            meta=dict(payload.get("metadata") or {})
            meta["trial_registration_id"]=evidence["registration_id"]
            meta["registration_enrichment_evidence"]=evidence
            payload["metadata"]=meta
            out[index]={**row,"payload":payload}
    return out,{"method":"OPEN_ACCESS_REGISTRATION_V1","source_calls":attempts,"records_linked":sum(a["status"]=="LINK_FOUND" for a in audit),"attempts":audit,"independence_confirmed":False}

def enrich_ledger(ledger,candidate_id,*,fetcher=None,max_lookups=3):
    rows=ledger.list_external_evidence(candidate_id,"PRIMARY_STUDY")
    changed,audit=enrich_records(rows,fetcher=fetcher,max_lookups=max_lookups)
    for old,new in zip(rows,changed):
        if old is new:continue
        ledger.upsert_external_evidence(candidate_id,"PRIMARY_STUDY",new["source_record_id"],
            source=new.get("source",""),title=new.get("title",""),payload=new["payload"])
    return audit
