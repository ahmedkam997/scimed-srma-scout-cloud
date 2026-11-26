"""Bounded supplementary discovery, not a TARCiS-compliant systematic search.

Use evidence-linked abbreviation harvesting and direct citation links only.
Source failures remain explicit and never clear mandatory coverage.
"""
from __future__ import annotations
from collections import defaultdict
import re
from scimed_scout.discovery.query_optimizer import _concept,normalize,_contains,_expanded_group
from scimed_scout.discovery.competitor_records import identifiers
from scimed_scout.discovery.evidence_classification import classify_review_search_hit
from scimed_scout.discovery.pico_matching import assess_pico
from scimed_scout.discovery.constants import MIN_DISCOVERY_STUDIES
from scimed_scout.domain import SourceStatus
from scimed_scout.sources.base import SearchResult

VERSION="ADAPTIVE_SEARCH_V1"
MAX_ROWS=80
MAX_LINKS=12

def _text(row):
    m=(row.get("payload") or {}).get("metadata") or {}
    return " ".join(str(v or "") for v in (row.get("title"),m.get("abstractText"),m.get("abstract")))[:16000]

def _pmid(row):
    ids=identifiers(row)
    return next(iter(ids["pmid"])) if len(ids["pmid"])==1 and len(ids["doi"])<=1 else ""

def _matches(row,concept):
    return any(_contains(normalize(_text(row)),normalize(a)) for a in concept.aliases)

def harvest(candidate,rows):
    """Record observed headings and abbreviations, with source-linked support.
    New abbreviations require explicit long-form (ABBR) and two distinct PMIDs.
    Co-occurrence of a MeSH heading is NOT evidence of synonymy.
    """
    p,i=_concept(candidate.population),_concept(candidate.intervention_exposure_index_test)
    result={"abbreviations":[],"mesh_observations":[]}
    if not p or not i:return result
    observed=defaultdict(set)
    headings=defaultdict(set)
    for row in rows[:MAX_ROWS]:
        pmid=_pmid(row)
        if not pmid or not (_matches(row,p) and _matches(row,i)):continue
        text=_text(row)
        for dim,concept in (("population",p),("intervention",i)):
            for alias in concept.aliases:
                # Long phrase must be literally present apart from punctuation.
                words=normalize(alias).split()
                if len(words)<2:continue
                pattern=r"(?i)(?<!\w)"+r"[\s-]+".join(map(re.escape,words))+r"\s*\(([A-Za-z][A-Za-z0-9-]{2,11})\)"
                for m in re.finditer(pattern,text):
                    token=m.group(1)
                    initials="".join(w[0] for w in words if w not in {"with","and","of","a","the","in","for"})
                    if normalize(token).replace(" ","")!=initials or normalize(token) in {normalize(a) for a in concept.aliases}:continue
                    observed[(dim,token.upper())].add(pmid)
        meta=(row.get("payload") or {}).get("metadata") or {}
        for heading in (meta.get("meshHeadingList") or {}).get("meshHeading",[]) if isinstance(meta.get("meshHeadingList"),dict) else []:
            if isinstance(heading,dict):
                descriptor=heading.get("descriptorName")
                if isinstance(descriptor,str) and 0<len(descriptor)<=100:
                    headings[descriptor].add(pmid)
    result["abbreviations"]=[{"dimension":d,"term":t,"support_pmids":sorted(v)} for (d,t),v in sorted(observed.items()) if len(v)>=2][:6]
    result["mesh_observations"]=[{"heading":h,"support_pmids":sorted(v),"synonym_verified":False}
        for h,v in sorted(headings.items(),key=lambda x:(-len(x[1]),x[0])) if len(v)>=2][:12]
    return result

def refinement(candidate,rows,pico_audit):
    p,i=_concept(candidate.population),_concept(candidate.intervention_exposure_index_test)
    evidence=harvest(candidate,rows)
    if not p or not i:return "", "UNRECOGNIZED_OR_COMPLEX_SCOPE",evidence
    if pico_audit.get("pico_design_family_leads",0)>=MIN_DISCOVERY_STUDIES:
        return "", "MINIMUM_LEAD_SIGNAL_ALREADY_PRESENT",evidence
    groups={"population":_expanded_group(candidate.population,"Europe PMC"),
            "intervention":_expanded_group(candidate.intervention_exposure_index_test,"Europe PMC")}
    if evidence["abbreviations"]:
        for term in evidence["abbreviations"]:
            d=term["dimension"]
            groups[d]=groups[d][:-1]+' OR TITLE_ABS:"'+term["term"]+'")'
        return groups["population"]+" AND "+groups["intervention"],"OBSERVED_ABBREVIATION_EXPANSION",evidence
    # Precision-oriented supplemental query for a weak, noisy sample; both
    # anchors remain required. Do not remove or replace base searches.
    if len(rows)>=8:
        return groups["population"].replace("TITLE_ABS:","TITLE:")+" AND "+groups["intervention"],"TITLE_POPULATION_REFINEMENT",evidence
    return "", "NO_SUPPORTED_REFINEMENT",evidence

def direct_links(client,pmid,direction,*,limit=MAX_LINKS):
    if not re.fullmatch(r"[0-9]{1,12}",str(pmid)) or direction not in ("references","citations"):
        raise ValueError("invalid citation lookup")
    pmid=str(pmid)
    limit=max(1,min(MAX_LINKS,int(limit)))
    endpoint="https://www.ebi.ac.uk/europepmc/webservices/rest/MED/"+pmid+"/"+direction
    out={"direction":"BACKWARD" if direction=="references" else "FORWARD","seed_pmid":pmid,
         "source":"Europe PMC","url":endpoint,"page":1,"limit":limit,"status":"ACCESS_UNRESOLVED","reported_count":None,"links":[]}
    try:
        data=client.http.get_json(endpoint,{"format":"json","page":1,"pageSize":limit})
        count=data.get("hitCount")
        key="reference" if direction=="references" else "citation"
        block=data.get(key+"List")
        if not isinstance(count,int) or count<0 or (count>0 and not isinstance(block,dict)):
            return out
        records=(block or {}).get(key,[])
        if not isinstance(records,list):return out
        out["reported_count"]=count
        out["links"]=[{"pmid":str(r.get("id") or r.get("pmid") or "") if r.get("source")=="MED" or r.get("pmid") else "",
                       "title":str(r.get("title") or "")[:300]} for r in records[:limit] if isinstance(r,dict)]
        out["status"]="BOUNDED_LINK_SAMPLE" if out["links"] else "ZERO_INDEXED_LINKS" if count==0 else "LINK_METADATA_INCOMPLETE"
        out["sample_truncated"]=count>len(out["links"])
    except Exception as exc:
        out["error_type"]=type(exc).__name__
        out["rate_limited"]="429" in str(exc)
    return out

def citation_neighbors(client, seeds, known_rows=(), *, max_seeds=1, check=None):
    """One bounded hop, exact MED hydration, no evidence or novelty clearance."""
    seeds=list(dict.fromkeys(str(s) for s in seeds if re.fullmatch(r"[0-9]{1,12}",str(s))))[:max(0,min(2,int(max_seeds)))]
    known={_pmid(r) for r in known_rows}|set(seeds)
    audit={"status":"NO_SOURCE_LINKED_SEED","source_calls":0,"citation_search":[],"hydration":{},
           "eligibility_verified":False,"coverage_clearance_allowed":False,"new_ai_requests":0}
    if not seeds:return audit,[]
    novel={}
    streams=[]
    stopped=False
    for seed in seeds:
        for direction in ("references","citations"):
            if check:check()
            entry=direct_links(client,seed,direction)
            audit["source_calls"]+=1
            audit["citation_search"].append(entry)
            stream=[]
            for link in entry["links"]:
                pmid=link["pmid"]
                if re.fullmatch(r"[0-9]{1,12}",pmid) and pmid not in known:
                    edge={"seed_pmid":seed,"direction":entry["direction"]}
                    if edge not in novel.setdefault(pmid,[]):novel[pmid].append(edge)
                    if pmid not in stream:stream.append(pmid)
            streams.append(stream)
            if entry.get("rate_limited"):
                stopped=True
                break
        if stopped:break
    # Interleave directions/seed streams so references cannot exhaust the
    # hydration budget before citing articles (and vice versa).
    ids=[]
    for index in range(max(map(len,streams),default=0)):
        for stream in streams:
            if index<len(stream) and stream[index] not in ids:ids.append(stream[index])
    ids=ids[:MAX_LINKS]
    audit["status"]="PARTIAL_LINK_SAMPLE" if any(e["status"] not in ("BOUNDED_LINK_SAMPLE","ZERO_INDEXED_LINKS") for e in audit["citation_search"]) or any(e.get("sample_truncated") for e in audit["citation_search"]) or len(novel)>len(ids) else "BOUNDED_LINK_SAMPLE"
    audit["unique_linked_pmids"]=len(novel)
    if not ids or stopped:return audit,[]
    q="("+" OR ".join("EXT_ID:"+x for x in ids)+") AND SRC:MED"
    if check:check()
    audit["source_calls"]+=1
    try:
        retrieved=client.search(q,limit=len(ids))
        exact=[]
        seen=set()
        for r in retrieved.records:
            rid=str(r.record_id);m=r.metadata or {}
            if rid not in ids or rid in seen or not r.title.strip():continue
            if m.get("source") not in (None,"","MED") or (m.get("pmid") and str(m["pmid"])!=rid):continue
            if m.get("source")!="MED" and str(m.get("pmid") or "")!=rid:continue
            seen.add(rid)
            edges=novel[rid]
            r.metadata={**m,"supplementary_citation_link":{"seed_pmid":edges[0]["seed_pmid"],
                "directions":list(dict.fromkeys(e["direction"] for e in edges)),"edges":edges,"eligibility_verified":False}}
            exact.append(r)
        audit["hydration"]={"query":q,"status":retrieved.status.value,"requested_pmids":ids,
                            "retrieved_pmids":[str(r.record_id) for r in exact],"unresolved_pmids":[x for x in ids if x not in seen]}
        if len(seen)!=len(ids) or retrieved.status!=SourceStatus.SEARCHED_POSITIVE:audit["status"]="PARTIAL_LINK_SAMPLE"
        return audit,exact
    except Exception as exc:
        audit["status"]="PARTIAL_LINK_SAMPLE"
        audit["hydration"]={"query":q,"status":"ACCESS_FAILED","requested_pmids":ids,"error_type":type(exc).__name__}
        return audit,[]

def collect(candidate,primary,reviews,client,*,existing_queries=(),check=None):
    """Maximum four additional logical source calls; no recursive expansion.
    Returns source records separately for normal citation classification.
    """
    pico,plausible=assess_pico(candidate,primary)
    report={"version":VERSION,"status":"COMPLETE_BOUNDED_ATTEMPT","new_ai_requests":0,"source_calls":0,
            "initial_pico_family_leads":pico["pico_design_family_leads"],"refinement":{},
            "citation_search":[],"hydration":{},"eligibility_verified":False,
            "coverage_clearance_allowed":False}
    results=[]
    q,reason,terms=refinement(candidate,primary+reviews,pico)
    report["refinement"]={"reason":reason,"term_audit":terms,"query":q,"status":"NOT_RUN"}
    if q and q not in existing_queries:
        report["source_calls"]+=1
        if check:check()
        try:
            r=client.search(q,limit=12)
            report["refinement"].update(status=r.status.value,reported_count=r.total_count,retrieved=len(r.records))
            results.append(("ADAPTIVE_QUERY",q,r.records))
            if r.status not in (SourceStatus.SEARCHED_POSITIVE,SourceStatus.SEARCHED_NEGATIVE):
                report["status"]="REFINEMENT_ACCESS_UNRESOLVED"
                return report,results
        except Exception:
            report["refinement"]["status"]="ACCESS_FAILED"
            return report,results
    p,i=_concept(candidate.population),_concept(candidate.intervention_exposure_index_test)
    # Only source-linked PICO leads or review citations with both anchors
    # qualify as exploratory seeds. None are declared included studies.
    seed=next((_pmid(r) for r in plausible if _pmid(r)), "")
    if not seed and p and i:
        seed=next((_pmid(r) for r in reviews if _pmid(r) and _matches(r,p) and _matches(r,i)), "")
    if not seed:
        report["citation_status"]="NO_SOURCE_LINKED_SEED"
        return report,results
    graph,exact=citation_neighbors(client,[seed],primary+reviews,check=check)
    report["source_calls"]+=graph["source_calls"]
    report["citation_search"]=graph["citation_search"]
    report["hydration"]=graph["hydration"]
    report["citation_status"]=graph["status"]
    if exact:results.append(("CITATION_MINING",graph["hydration"]["query"],exact))
    return report,results
