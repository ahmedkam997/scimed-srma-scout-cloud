"""Conservative bibliographic identity and bounded evidence enrichment.

Group only exact DOI/PMID identity; a contradictory identifier anywhere in a
connected component prevents merging the component. Never merge registrations
and publications, or similar titles alone. Raw ledger rows are retained.
"""
from __future__ import annotations
from collections import defaultdict
import re

def metadata(record):
    m=(record.get("payload") or {}).get("metadata")
    return m if isinstance(m,dict) else {}

def _doi(value):
    v=str(value or "").strip().casefold()
    v=re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)","",v).rstrip(".")
    return v if re.fullmatch(r"10\.\d{4,9}/[^\s\"<>]+",v) else ""

def identifiers(record):
    p=record.get("payload") or {}
    m=metadata(record)
    ext=m.get("externalIds") or m.get("ids") or {}
    ext=ext if isinstance(ext,dict) else {}
    doi={_doi(v) for v in (p.get("doi"),m.get("doi"),ext.get("DOI"),ext.get("doi"))}
    pmid=set()
    for v in (p.get("pmid"),m.get("pmid"),ext.get("PubMed"),ext.get("pmid")):
        v=str(v or "").removeprefix("https://pubmed.ncbi.nlm.nih.gov/").rstrip("/")
        if v.isdigit():
            pmid.add(v)
    if record.get("source") in ("PubMed","Europe PMC"):
        rid=str(record.get("source_record_id") or "")
        if rid.isdigit() and (record.get("source")=="PubMed" or m.get("source")=="MED"):
            pmid.add(rid)
    for item in m.get("articleids") or m.get("articleIds") or []:
        if isinstance(item,dict):
            kind=str(item.get("idtype") or item.get("idType") or "").casefold()
            value=item.get("value") or item.get("id")
            if kind=="doi": doi.add(_doi(value))
            if kind in ("pubmed","pmid") and str(value).isdigit(): pmid.add(str(value))
    return {"doi":doi-{""},"pmid":pmid}

def identity(record):
    return (str(record.get("evidence_type") or ""),str(record.get("source") or ""),
            str(record.get("source_record_id") or ""))

def abstract(record):
    m=metadata(record);p=record.get("payload") or {}
    values=[v.strip() for v in (m.get("abstract"),m.get("abstractText"),p.get("abstract"))
            if isinstance(v,str) and v.strip()]
    return max(values,key=len,default="")

def _rank(record):
    # Stable representative selection for repeated passes. Favor a genuine
    # abstract over title-only or provider-specific metadata length.
    return (-len(abstract(record)), -len(str(record.get("title") or "")),identity(record))

def groups(records):
    rows=list(records)
    parent=list(range(len(rows)))
    def root(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]]
            i=parent[i]
        return i
    index={}
    ids=[identifiers(r) for r in rows]
    for i,r in enumerate(rows):
        if r.get("evidence_type")!="PUBLISHED_REVIEW":
            continue
        for kind,vals in ids[i].items():
            for value in vals:
                key=(kind,value)
                if key in index:
                    parent[root(i)]=root(index[key])
                else:
                    index[key]=i
    components=defaultdict(list)
    for i in range(len(rows)):
        components[root(i)].append(i)
    result=[]
    for component in components.values():
        conflict=any(len({v for i in component for v in ids[i][kind]})>1 for kind in ("doi","pmid"))
        partitions=[[i] for i in component] if conflict else [component]
        for part in partitions:
            variants=sorted([rows[i] for i in part],key=_rank)
            result.append({"representative":variants[0],"variants":variants,"identifier_conflict":conflict})
    return sorted(result,key=lambda g:identity(g["representative"]))

def deduplicate(records):
    return [g["representative"] for g in groups(records)]

def audit(records):
    clusters=groups(records)
    return {"version":"COMPETITOR_IDENTITY_V1","raw_records":len(records),"unique_records":len(clusters),
            "duplicate_variants":len(records)-len(clusters),
            "conflicting_identifier_records":sum(len(g["variants"]) for g in clusters if g["identifier_conflict"]),
            "groups":[{"representative":{"source":g["representative"].get("source"),"record_id":g["representative"].get("source_record_id")},
                       "variants":[{"source":r.get("source"),"record_id":r.get("source_record_id")} for r in g["variants"]],
                       "identifier_conflict":g["identifier_conflict"]} for g in clusters if len(g["variants"])>1 or g["identifier_conflict"]][:40]}

def enrich_missing_abstracts(ledger,candidate_id,records,client,*,limit=2):
    """Only lookup selected published reviews lacking a useful abstract.
    Never treat a missing lookup or an ambiguous ID as non-overlap.
    """
    attempts=[]
    for r in records:
        if len(attempts)>=limit: break
        if r.get("evidence_type")!="PUBLISHED_REVIEW" or len(abstract(r))>=120: continue
        ids=identifiers(r)
        if any(len(x)>1 for x in ids.values()) or not any(ids.values()): continue
        key=next(iter(ids["pmid"]),None)
        doi=next(iter(ids["doi"]),None)
        query=f"EXT_ID:{key} AND SRC:MED" if key else f'DOI:"{doi}"'
        entry={"source":r.get("source"),"record_id":r.get("source_record_id"),"lookup_source":"Europe PMC",
               "status":"UNRESOLVED"}
        attempts.append(entry)
        try:
            result=client.search(query,limit=5)
            entry["source_status"]=result.status.value
            exact=[]
            for item in result.records:
                row={"source":item.source,"source_record_id":item.record_id,"evidence_type":"PUBLISHED_REVIEW",
                     "title":item.title,"payload":{"doi":item.doi,"metadata":item.metadata}}
                other=identifiers(row)
                if any(len(ids[k]|other[k])>1 for k in ids): continue
                if not any(ids[k]&other[k] for k in ids): continue
                if len(abstract(row))>=120: exact.append(row)
            # Identical source variants are harmless, conflicting text is not.
            texts={abstract(x) for x in exact}
            if len(texts)!=1:
                entry["status"]="AMBIGUOUS_OR_MISSING_ABSTRACT"
                continue
            match=exact[0]
            payload=dict(r.get("payload") or {})
            meta=dict(metadata(r))
            # Preserve original fields. Source text is explicitly attributed.
            meta["abstractText"]=abstract(match)
            payload["metadata"]=meta
            payload["competitor_abstract_enrichment"]={"source":"Europe PMC",
                "record_id":match["source_record_id"],"query":query,"matched_identifiers":sorted(
                    v for k in ids for v in ids[k]&identifiers(match)[k])}
            ledger.upsert_external_evidence(candidate_id,"PUBLISHED_REVIEW",r["source_record_id"],
                source=r.get("source",""),title=r.get("title",""),payload=payload)
            entry["status"]="ABSTRACT_ENRICHED"
        except Exception:
            entry["status"]="LOOKUP_FAILED"
    return attempts
