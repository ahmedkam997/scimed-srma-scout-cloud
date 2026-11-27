"""Bounded NCBI EFetch enrichment by already-observed PMID.

No new search results, no credentials in audit, no external XML entity loading.
Keep ESummary records unchanged on transport/identity/parse failure.
"""
from __future__ import annotations
import re,urllib.request,urllib.parse,urllib.error,xml.etree.ElementTree as ET
from .http import _pace,_cooldown,_retry_seconds

MAX_BYTES=5_000_000
MAX_IDS=60

def _text(node):
    return " ".join("".join(node.itertext()).split()) if node is not None else ""

def parse_efetch(raw,expected):
    expected=set(expected)
    if not isinstance(raw,bytes) or len(raw)>MAX_BYTES or b"<!ENTITY" in raw.upper() or re.search(br"<!DOCTYPE[^>]*\[",raw,re.I):raise ValueError("Untrusted XML envelope")
    root=ET.fromstring(raw)
    if root.tag!="PubmedArticleSet":raise ValueError("Unexpected PubMed XML root")
    result={};duplicates=set();unexpected=0
    for node in root.findall("PubmedArticle"):
        med=node.find("MedlineCitation")
        if med is None:continue
        pmid=_text(med.find("PMID"))
        if pmid not in expected:unexpected+=1;continue
        if pmid in result:duplicates.add(pmid);continue
        article=med.find("Article")
        if article is None:continue
        chunks=[]
        for p in article.findall("Abstract/AbstractText"):
            t=_text(p)
            if not t:continue
            label=p.get("Label") or p.get("NlmCategory") or ""
            chunks.append((label+": " if label and label!="UNASSIGNED" else "")+t)
        types=[_text(p) for p in article.findall("PublicationTypeList/PublicationType") if _text(p)]
        accessions=[]
        for bank in article.findall("DataBankList/DataBank"):
            for acc in bank.findall("AccessionNumberList/AccessionNumber"):
                text=_text(acc)
                if re.fullmatch(r"(?:NCT\d{8}|ISRCTN\d{8}|ACTRN\d{14}|DRKS\d{8}|UMIN\d{9})",text,re.I):accessions.append(text.upper())
        mesh=[{"descriptor":_text(h.find("DescriptorName")),"qualifiers":[_text(q).casefold() for q in h.findall("QualifierName") if _text(q)]} for h in med.findall("MeshHeadingList/MeshHeading") if _text(h.find("DescriptorName"))]
        chemicals=[_text(c) for c in med.findall("ChemicalList/Chemical/NameOfSubstance") if _text(c)]
        pmc_ids={_text(x).upper() for x in node.findall("PubmedData/ArticleIdList/ArticleId") if x.get("IdType") in ("pmc","pmcid") and re.fullmatch(r"PMC\d{4,12}",_text(x),re.I)}
        doi_ids={_text(x).casefold() for x in node.findall("PubmedData/ArticleIdList/ArticleId") if x.get("IdType")=="doi" and re.fullmatch(r"10\.\d{4,9}/[^\s<>]+",_text(x))}
        result[pmid]={"doi":next(iter(doi_ids)) if len(doi_ids)==1 else "", "pmcid":next(iter(pmc_ids)) if len(pmc_ids)==1 else "", "abstractText":"\n".join(chunks),"pubtype":types,"trial_registration_ids":sorted(set(accessions)), "mesh_headings":mesh,"chemical_names":chemicals,
            "pubmed_efetch_title":_text(article.find("ArticleTitle")),"pubmed_efetch_identity":"EXACT_PMID"}
    for pmid in duplicates:result.pop(pmid,None)
    return result,{"unexpected_pmids":unexpected,"ambiguous_pmids":len(duplicates)}

def _fetch(client,ids):
    params=client._params({"db":"pubmed","id":",".join(ids),"retmode":"xml"})
    url=client.base+"efetch.fcgi?"+urllib.parse.urlencode({k:v for k,v in params.items() if v is not None})
    _pace("ncbi",0.15 if client.api_key else 0.45,8.0)
    req=urllib.request.Request(url,headers={"User-Agent":"SciMed-Review-Scout/1.0","Accept":"application/xml"})
    try:
        with urllib.request.urlopen(req,timeout=15) as response:
            return response.read(MAX_BYTES+1)
    except urllib.error.HTTPError as e:
        if e.code==429:_cooldown("ncbi",max(2,_retry_seconds(e.headers.get("Retry-After","") if e.headers else "")))
        raise

def enrich_rows(client,rows,*,fetcher=None):
    from scimed_scout.discovery.pico_matching import _pmid
    from scimed_scout.discovery.trial_family import registration_signals
    ids=list(dict.fromkeys(_pmid(r) for r in rows if r.get("source")=="PubMed" and _pmid(r)))[:MAX_IDS]
    audit={"source":"PubMed EFetch","stage":"ABSTRACT_ENRICHMENT","requested":len(ids),"retrieved":0,
           "abstracts_retrieved":0,"registry_id_records":0,"status":"NOT_SEARCHED"}
    if not ids:return rows,audit
    try:
        raw=(fetcher or (lambda i:_fetch(client,i)))(ids)
        found,diagnostic=parse_efetch(raw,ids)
    except Exception as exc:
        return rows,{**audit,"status":"ACCESS_FAILED","error_type":type(exc).__name__}
    enriched=[]
    for r in rows:
        key=_pmid(r);match=found.get(key)
        if r.get("source")!="PubMed" or not match:enriched.append(r);continue
        payload=dict(r.get("payload") or {});meta=dict(payload.get("metadata") or {})
        existing=registration_signals(r)
        if match["abstractText"]:meta["abstractText"]=match["abstractText"]
        if match["pubtype"]:meta["pubtype"]=match["pubtype"]
        meta["trial_registration_ids"]=sorted(set(existing)|set(match["trial_registration_ids"]))
        if match.get("pmcid") and not meta.get("pmcid"):meta["pmcid"]=match["pmcid"]
        meta["mesh_headings"]=match["mesh_headings"]
        meta["chemical_names"]=match["chemical_names"]
        meta["pubmed_efetch_identity"]="EXACT_PMID"
        payload["metadata"]=meta
        enriched.append({**r,"payload":payload})
    audit.update(diagnostic,retrieved=len(found),abstracts_retrieved=sum(bool(m["abstractText"]) for m in found.values()),
        registry_id_records=sum(bool(m["trial_registration_ids"]) for m in found.values()),
        status="SEARCHED_POSITIVE" if len(found)==len(ids) and not any(diagnostic.values()) else "PARTIAL")
    return enriched,audit
