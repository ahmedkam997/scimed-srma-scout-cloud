"""Bounded structured-arm discovery from already retrieved trial reports.

Registry data only propose a search; do not count as published eligible RCTs.
Never collapse complex/shared arms into a false head-to-head comparison.
"""
from .trial_family import registration_signals
from .pico_matching import _groups,_normalize
from .dynamic_anchors import clean
from scimed_scout.sources.http import JsonHttpClient
import re

VERSION="REGISTRY_ARM_ANCHORS_V1"
MAX_LOOKUPS=8
MAX_ANCHORS=2

def arm_names(arm):
    names=arm.get("interventionNames") or []
    return [clean(re.sub(r"^[A-Za-z /-]+:\s*","",n)) for n in names if isinstance(n,str)]

def extract(study,nct,report):
    from .rct_first import has,clean_passage,explicit_comparison
    p=study.get("protocolSection") or {}
    if (p.get("identificationModule") or {}).get("nctId")!=nct:return None,"IDENTITY_MISMATCH"
    d=p.get("designModule") or {}
    if d.get("studyType")!="INTERVENTIONAL" or (d.get("designInfo") or {}).get("allocation")!="RANDOMIZED":return None,"DESIGN_NOT_RANDOMIZED"
    if (d.get("designInfo") or {}).get("interventionModel")!="PARALLEL":return None,"NONPARALLEL_OR_UNKNOWN"
    arms=(p.get("armsInterventionsModule") or {}).get("armGroups") or []
    if len(arms)!=2:return None,"COMPLEX_ARM_STRUCTURE"
    exp=[a for a in arms if a.get("type")=="EXPERIMENTAL"]
    controls=[a for a in arms if a.get("type") in ("ACTIVE_COMPARATOR","PLACEBO_COMPARATOR","SHAM_COMPARATOR","NO_INTERVENTION")]
    if len(exp)!=1 or len(controls)!=1:return None,"AMBIGUOUS_ARM_ROLES"
    i,c=arm_names(exp[0]),arm_names(controls[0])
    if not c and controls[0].get("type")=="NO_INTERVENTION":c=["no intervention"]
    if len(i)!=1 or len(c)!=1 or not i[0] or not c[0] or _normalize(i[0])==_normalize(c[0]):return None,"MULTICOMPONENT_OR_UNCLEAR_ARMS"
    inter,control=i[0],c[0]
    if has(inter,control) or has(control,inter):return None,"OVERLAPPING_ARM_TERMS"
    m=(report.get("payload") or {}).get("metadata") or {}
    title=str(report.get("title") or "")
    abstract=str(m.get("abstractText") or m.get("abstract") or "")
    sentences=[title]+re.split(r"(?<=[.!?])\s+|\n+",abstract)
    # Explicit source-linked allocation or title contrast, not registry alone.
    matched=[clean_passage(t) for t in sentences if explicit_comparison(t,(inter,),control)]
    if not matched:return None,"NO_CORROBORATED_REPORT_COMPARISON"
    conditions=[clean(t) for t in (p.get("conditionsModule") or {}).get("conditions",[])]
    conditions=[t for t in conditions if t and has(title+" "+abstract,t)]
    if not conditions:return None,"POPULATION_NOT_CORROBORATED"
    pop=max(conditions,key=lambda x:(len(x),x))
    if has(pop,inter) or has(pop,control):return None,"POPULATION_ARM_OVERLAP"
    return {"pair":(pop,inter,(),()),"comparator":control,"family_cues":1,"registry_id":nct,
        "registry_url":"https://clinicaltrials.gov/study/"+nct,
        "source_reports":[{"title":title,"record_id":report.get("source_record_id"),"url":(report.get("payload") or {}).get("url"),"comparison_excerpt":matched[0][:400]}],
        "scope":"REGISTRY_AND_PUBLISHED_REPORT_SEARCH_ANCHOR_NOT_ELIGIBILITY"},"ANCHOR"

def derive_registry(rows,existing,*,check=None,lookup=None,limit=MAX_ANCHORS):
    from .rct_first import own_rct
    known={(_normalize(p),_normalize(i)) for p,i,*_ in existing}
    if lookup is None:
        http=JsonHttpClient(timeout=10,retries=0,service="ctgov",min_interval=.2)
        lookup=lambda n:http.get_json("https://clinicaltrials.gov/api/v2/studies/"+n)
    out=[];audit=[];seen=set()
    for group in _groups(rows):
        variants=group["records"]
        if not own_rct(variants):continue
        for report in variants:
            ids=list(registration_signals(report))
            if len(ids)!=1 or not re.fullmatch(r"NCT\d{8}",ids[0]):continue
            n=ids[0]
            if n in seen:continue
            if len(seen)>=MAX_LOOKUPS or len(out)>=limit:break
            seen.add(n)
            if check:check()
            try:
                candidate,status=extract(lookup(n),n,report)
            except Exception as exc:
                audit.append({"registry_id":n,"status":"ACCESS_FAILED","error_type":type(exc).__name__})
                if "429" in str(exc):return out,audit
                continue
            if candidate:
                key=tuple(_normalize(x) for x in candidate["pair"][:2])
                if key in known:status="ALREADY_KNOWN_ANCHOR"
                else:known.add(key);out.append(candidate)
            audit.append({"registry_id":n,"status":status,"report_id":report.get("source_record_id")})
        if len(seen)>=MAX_LOOKUPS or len(out)>=limit:break
    return out,audit
