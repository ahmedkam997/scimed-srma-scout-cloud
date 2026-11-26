"""Budgeted date-stratified PubMed sampling, not exhaustive coverage."""
from datetime import date
from dataclasses import replace
from scimed_scout.domain import SourceStatus

def date_query(query,start,end):
    if not isinstance(start,date) or not isinstance(end,date) or start>end:
        raise ValueError("invalid date interval")
    return f'({query}) AND ("{start:%Y/%m/%d}"[dp] : "{end:%Y/%m/%d}"[dp])'

def windows(start,end):
    if start>end:raise ValueError("invalid date interval")
    # Recent five years, previous ten years, and all older years.
    from datetime import timedelta
    edges=[date(end.year-4,1,1),date(end.year-14,1,1)]
    out=[];hi=end
    for edge in edges:
        if start<edge<=hi:
            out.append((edge,hi));hi=edge-timedelta(days=1)
    out.append((start,hi))
    return out

def collect(client,query,*,start=date(1800,1,1),end=None,budget=60,check=None):
    end=end or date.today()
    if not 3<=budget<=240:raise ValueError("budget outside bounded range")
    spans=windows(start,end)
    audit={"method":"DATE_STRATIFIED_V1","status":"BOUNDED_SAMPLE","source_calls":0,
           "record_budget":budget,"windows":[],"coverage_clearance_allowed":False,"eligibility_verified":False}
    found={}
    for i,(lo,hi) in enumerate(spans):
        if check:check()
        cap=budget//len(spans)+(i<budget%len(spans))
        q=date_query(query,lo,hi)
        audit["source_calls"]+=1
        try:
            r=client.search(q,limit=cap)
            rows=r.records[:cap]
            entry={"query":q,"start":str(lo),"end":str(hi),"limit":cap,"status":r.status.value,"reported":r.total_count,"retrieved":len(rows)}
            for x in rows:
                if not x.title.strip():continue
                if x.record_id not in found:
                    found[x.record_id]=replace(x,metadata={**(x.metadata or {}),"date_stratum":{"start":str(lo),"end":str(hi),"query":q}})
            if r.status not in (SourceStatus.SEARCHED_POSITIVE,SourceStatus.SEARCHED_NEGATIVE):
                audit["status"]="PARTIAL_SAMPLE"
            audit["windows"].append(entry)
            if "429" in str(r.message or ""):break
        except Exception as exc:
            audit["status"]="PARTIAL_SAMPLE"
            audit["windows"].append({"query":q,"start":str(lo),"end":str(hi),"limit":cap,"status":"ACCESS_FAILED","retrieved":0,"error_type":type(exc).__name__})
            if "429" in str(exc):break
    audit["unique_records"]=len(found)
    if len(audit["windows"])!=len(spans):audit["status"]="PARTIAL_SAMPLE"
    return audit,list(found.values())
