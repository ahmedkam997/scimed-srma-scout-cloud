"""Exact registry results-reference suggestions, not automatic cohort merges."""
import re
from collections import defaultdict
from .trial_family import registration_signals
from .pico_matching import _pmid
from scimed_scout.sources.http import JsonHttpClient

def suggest(rows,*,lookup=None,max_lookups=3,check=None,previous=None):
    # Only registry IDs already observed in reports. Never use benchmark labels.
    known=sorted({n for r in rows for n in registration_signals(r) if re.fullmatch(r"NCT\d{8}",n)})
    missing={_pmid(r) for r in rows if _pmid(r) and not registration_signals(r)}
    audit={"method":"EXACT_REGISTRY_RESULT_REFERENCE_V1","source_calls":0,"attempts":[],"suggestions":[],"automatic_merge":False,"independence_confirmed":False}
    prior=(previous or {}).get("attempts",[])
    checked={a.get("nct") for a in prior if a.get("status")=="CHECKED"}
    audit["remaining_registry_ids"]=len(set(known)-checked) if missing else 0
    if not known or not missing:return audit
    if lookup is None:
        http=JsonHttpClient(timeout=10,retries=0,service="ctgov",min_interval=.2)
        lookup=lambda n:http.get_json("https://clinicaltrials.gov/api/v2/studies/"+n)
    edges=defaultdict(set)
    for hint in (previous or {}).get("suggestions",[]):
        if hint.get("pmid") in missing:edges[hint["pmid"]].update(n for n in hint.get("registry_ids",[]) if n in known)
    fresh=[n for n in known if n not in checked]
    attempted={a.get("nct") for a in prior}
    fresh.sort(key=lambda n:(n in attempted,n))
    for n in fresh[:max(0,min(5,int(max_lookups)))]:
        if check:check()
        audit["source_calls"]+=1
        try:
            study=lookup(n)
            p=study.get("protocolSection") or {}
            if (p.get("identificationModule") or {}).get("nctId")!=n:
                audit["attempts"].append({"nct":n,"status":"IDENTITY_MISMATCH"});continue
            refs=(p.get("referencesModule") or {}).get("references") or []
            matched=set()
            for ref in refs:
                if not isinstance(ref,dict) or ref.get("type")!="RESULT":continue
                pmid=str(ref.get("pmid") or "")
                if pmid in missing:edges[pmid].add(n);matched.add(pmid)
            audit["attempts"].append({"nct":n,"status":"CHECKED","matched_pmids":sorted(matched)})
        except Exception as exc:
            audit["attempts"].append({"nct":n,"status":"ACCESS_UNRESOLVED","error_type":type(exc).__name__})
            if "429" in str(exc):break
    new_attempts=list(audit["attempts"])
    audit["attempts"]=[*prior,*new_attempts]
    audit["new_attempts"]=new_attempts
    audit["remaining_registry_ids"]=len(set(known)-{a.get("nct") for a in audit["attempts"] if a.get("status")=="CHECKED"})
    audit["suggestions"]=[{"pmid":p,"registry_ids":sorted(ns),"status":"MANUAL_LINK_REVIEW" if len(ns)==1 else "AMBIGUOUS_REGISTRY_LINKS","source_urls":["https://clinicaltrials.gov/study/"+n for n in sorted(ns)]} for p,ns in sorted(edges.items())]
    return audit
