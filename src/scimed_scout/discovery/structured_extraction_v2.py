"""Bounded evidence extraction. Source facts are leads, never adjudicated eligibility."""
import re,hashlib,math,xml.etree.ElementTree as ET
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


def abstract_ratios(row):
    """Explicitly reported contrast estimates; never infer direction or pooling."""
    raw=abstract(row)
    num=r"(?:\d+(?:[.·]\d+)?|[.·]\d+)"
    measure=r"hazard ratio(?:\s*\[HR\])?|risk ratio(?:\s*\[RR\])?|relative risk|odds ratio(?:\s*\[OR\])?|(?-i:HR|RR|OR)"
    pat=rf"\b(?P<m>{measure})(?:\s+for\s+[A-Za-z][A-Za-z /-]{{1,100}},)?\s*(?:[,=:]\s*)?(?P<value>{num})\s*[,;]?\s*[\[(]?\s*(?P<pct>{num})\s*%\s*(?:confidence interval(?:\s*\[CI\])?|CI)\s*[,;:]?\s*(?P<lo>{num})\s*(?:to|[-–—−])\s*(?P<hi>{num})(?![\d.·])"
    norm={"hr":"hazard ratio","rr":"risk ratio","or":"odds ratio"}
    results=[]
    for m in re.finditer(pat,raw,re.I):
        v,lo,hi,pct=(float(m[k].replace("·",".")) for k in ("value","lo","hi","pct"))
        if not all(math.isfinite(x) for x in (v,lo,hi,pct)) or not 0<lo<=v<=hi or lo==hi or not 0<pct<100:continue
        typ=re.sub(r"\s*\[[A-Z]+\]$","",m["m"],flags=re.I).casefold()
        results.append({"measure":norm.get(typ,typ),"ratio":v,"reported_ci":[lo,hi],"ci_percent":pct,
                        "locator":f"abstract:characters:{m.start()}-{m.end()}","context":raw[max(0,m.start()-80):min(len(raw),m.end()+45)],
                        "direction_verified":False,"endpoint_verified":False,"wald_interval_verified":False,"pooling_allowed":False})
        if len(results)>=30:break
    return results

def report_role_cues(row):
    """Publication role cues, never automatic exclusion or independent RCT proof."""
    p=row.get("payload") or {};meta=p.get("metadata") or {}
    from scimed_scout.sources.base import SearchRecord
    from .evidence_classification import _types,classify_review_search_hit
    r=SearchRecord(str(row.get("source") or ""),str(row.get("source_record_id") or ""),str(row.get("title") or ""),metadata=meta)
    types=set(_types(r));title=str(row.get("title") or "");a=abstract(row)
    cues=[]
    if types.intersection({"clinical trial protocol","study protocol"}) or re.search(r"\b(?:rationale and design|design and rationale|study protocol|trial protocol)\b",title,re.I):
        cues.append("PROTOCOL_CUE")
    if re.search(r"\b(?:post[- ]hoc|secondary analysis|subgroup analysis|prespecified analysis|pre-specified analysis|substudy|learning effects)\b",title+" "+a[:1500],re.I):
        cues.append("SECONDARY_ANALYSIS_CUE")
    if "randomized controlled trial" in types or "randomised controlled trial" in types:cues.append("RCT_PUBLICATION_TYPE_CUE")
    if classify_review_search_hit(r)=="CONFIRMED_REVIEW_CUE":cues.append("REVIEW_CUE")
    return {"cues":cues,"primary_result_confirmed":False,"independence_confirmed":False,"eligibility_confirmed":False}

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
            "numeric_outcome_leads":groups,"reported_ratio_estimates":ratio_estimates(study,nct),"eligibility_confirmed":False,"independence_confirmed":False,"pooling_allowed":False}

def jats_leads(row,raw,*,source_url=None):
    pmc=_pmcid(row);ids=identifiers(row)
    if not pmc or not isinstance(raw,bytes) or len(raw)>1500000 or b"<!ENTITY" in raw.upper() or re.search(br"<!DOCTYPE[^>]*\[",raw,re.I):return {"status":"UNRESOLVED"}
    try:root=ET.fromstring(raw)
    except (ValueError,ET.ParseError):return {"status":"UNRESOLVED"}
    from .registration_enrichment import OAI_NS
    if root.tag==f"{{{OAI_NS}}}OAI-PMH":
        metadata=root.find(f"./{{{OAI_NS}}}GetRecord/{{{OAI_NS}}}record/{{{OAI_NS}}}metadata")
        if metadata is None or len(metadata)!=1:return {"status":"BODY_UNAVAILABLE"}
        root=metadata[0]
        for node in root.iter():
            if node.tag.startswith(f"{{{OAI_NS}}}"):node.tag=node.tag.split("}",1)[1]
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
    return {"status":"JATS_SOURCE_LINKED_LEADS","url":source_url or "https://www.ebi.ac.uk/europepmc/webservices/rest/"+pmc+"/fullTextXML","sha256":hashlib.sha256(raw).hexdigest(),
            "tables":tables,"methods":methods,"eligibility_confirmed":False,"pooling_allowed":False}

def collect(rows,*,fetcher=None,previous=None,max_fulltexts=3,check=None):
    fetcher=fetcher or _fetch_xml
    prior={(x["source"],x["record_id"]):x for x in (previous or {}).get("reports",[])}
    results=[];calls=0
    ordered=sorted(rows,key=lambda r:(bool(prior.get((r["source"],r["source_record_id"]),{}).get("fulltext")),not bool(_pmcid(r)),r["source"],r["source_record_id"]))
    for r in ordered:
        k=(r["source"],r["source_record_id"]);entry={"source":k[0],"record_id":k[1],"url":(r.get("payload") or {}).get("url"),"registration_ids":sorted(registration_signals(r)),"abstract_count_leads":abstract_counts(r),"abstract_ratio_leads":abstract_ratios(r),"report_role_cues":report_role_cues(r)}
        old=prior.get(k,{})
        pmc=_pmcid(r)
        if old.get("pmcid")!=pmc:old={}
        entry["pmcid"]=pmc
        prev=old.get("fulltext") or {}
        if prev.get("status")=="JATS_SOURCE_LINKED_LEADS":entry["fulltext"]=prev
        elif pmc and len(old.get("fulltext_attempts",[]))<2 and calls<min(3,max(0,max_fulltexts)):
            from .registration_enrichment import _routes
            attempts=list(old.get("fulltext_attempts",[]))
            route,url=list(_routes(pmc))[len(attempts)]
            if check:check()
            calls+=1
            try:entry["fulltext"]=jats_leads(r,fetcher(url),source_url=url)
            except Exception as ex:entry["fulltext"]={"status":"ACCESS_UNRESOLVED","error_type":type(ex).__name__}
            entry["fulltext_attempts"]=[*attempts,{"route":route,"status":entry["fulltext"]["status"]}]
        elif prev:entry["fulltext"]=prev
        if "fulltext_attempts" not in entry:entry["fulltext_attempts"]=old.get("fulltext_attempts",[])
        results.append(entry)
    return {"version":VERSION,"reports":results,"source_calls":calls,"eligibility_confirmed":False,"pooling_allowed":False}

def recover_pubmed_abstracts(ledger,candidate_id,client,*,previous=None,fetcher=None,check=None):
    from scimed_scout.sources.pubmed_abstracts import parse_efetch,_fetch
    prior=set((previous or {}).get("attempted_pmids",[]))
    rows=ledger.list_external_evidence(candidate_id,"PRIMARY_STUDY")
    # Only PMIDs positively identified in PubMed or supported external metadata.
    # Conflicting IDs and untyped native record IDs are not guesses.
    present=set()
    todo=set()
    for row in rows:
        ids=identifiers(row)
        if len(ids["pmid"])!=1 or len(ids["doi"])>1:continue
        pmid=next(iter(ids["pmid"]))
        if abstract(row):present.add(pmid)
        else:todo.add(pmid)
    ids=sorted(todo-present-prior)[:40]
    result={"method":"EXACT_PMID_ABSTRACT_RECOVERY_V2","requested":len(ids),"retrieved":0,"attempted_pmids":sorted(prior),"source_calls":0,"qualification_granted":False}
    if not ids:return result
    if check:check()
    result["source_calls"]=1
    try:
        found,diag=parse_efetch((fetcher or (lambda x:_fetch(client,x)))(ids),ids)
        for pmid,metadata in found.items():
            title=metadata.get("pubmed_efetch_title")
            if not title or not metadata.get("abstractText"):continue
            old=next((r for r in rows if r["source"]=="PubMed" and r["source_record_id"]==pmid),None)
            payload=dict((old or {}).get("payload") or {});meta=dict(payload.get("metadata") or {})
            for k,v in metadata.items():
                if v:meta[k]=v
            payload.update(url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",metadata=meta)
            from .evidence_classification import classify_review_search_hit
            from scimed_scout.sources.base import SearchRecord
            cue=classify_review_search_hit(SearchRecord("PubMed",pmid,title,metadata=meta))
            kind="PUBLISHED_REVIEW" if cue=="CONFIRMED_REVIEW_CUE" else "PRIMARY_STUDY"
            payload.update(citation_classification=cue,originally_requested_evidence_type="PRIMARY_STUDY")
            ledger.upsert_external_evidence(candidate_id,kind,pmid,source="PubMed",title=title,payload=payload)
            result["retrieved"]+=1
        result.update(status="SEARCHED_POSITIVE" if len(found)==len(ids) and not any(diag.values()) else "PARTIAL",**diag)
        result["attempted_pmids"]=sorted(prior|set(ids))
    except Exception as ex:
        result.update(status="ACCESS_UNRESOLVED",error_type=type(ex).__name__)
        # Transient access failure must not permanently consume IDs.
    return result

def ratio_estimates(study,nct):
    """Preserve reported ratio and interval, never assume level, sides or direction."""
    p=study.get("protocolSection") or {}
    if (p.get("identificationModule") or {}).get("nctId")!=nct:return []
    out=[]
    for i,o in enumerate((study.get("resultsSection") or {}).get("outcomeMeasuresModule",{}).get("outcomeMeasures",[])):
        if not isinstance(o,dict):continue
        groups={g["id"]:g.get("title") for g in o.get("groups",[]) if isinstance(g,dict) and g.get("id") and g.get("title")}
        for j,a in enumerate(o.get("analyses",[])):
            if not isinstance(a,dict):continue
            typ=str(a.get("paramType") or "").strip().casefold()
            typ=re.sub(r"\s*\([^)]*\)\s*$","",typ)
            if typ not in ("hazard ratio","risk ratio","relative risk","odds ratio"):continue
            ids=a.get("groupIds") or []
            if len(ids)!=2 or len(set(ids))!=2 or any(k not in groups for k in ids):continue
            try:
                value,lo,hi,pct=(float(a[k]) for k in ("paramValue","ciLowerLimit","ciUpperLimit","ciPctValue"))
            except (KeyError,TypeError,ValueError):continue
            if not all(math.isfinite(x) for x in (value,lo,hi,pct)) or not 0<pct<100 or not 0<lo<=value<=hi or lo==hi:continue
            sides=str(a.get("ciNumSides") or "").upper()
            if sides and sides not in ("2-SIDED","TWO_SIDED","TWO-SIDED","2"):continue
            two_sided=bool(sides)
            out.append({"title":o.get("title"),"time_frame":o.get("timeFrame"),"measure":typ,
                        "ratio":value,"reported_ci":[lo,hi],"ci_percent":pct,"two_sided_verified":two_sided,
                        "ci95":[lo,hi] if pct==95 and two_sided else None,"groups":[{"id":k,"label":groups[k]} for k in ids],
                        "comparison_description":a.get("groupDescription"),"statistical_method":a.get("statisticalMethod"),
                        "url":"https://clinicaltrials.gov/study/"+nct+"?tab=results",
                        "locator":f"resultsSection.outcomeMeasuresModule.outcomeMeasures[{i}].analyses[{j}]",
                        "direction_verified":False,"pooling_allowed":False})
            if len(out)>=30:return out
    return out
