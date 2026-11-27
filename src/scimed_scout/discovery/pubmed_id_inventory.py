"""Resumable PubMed identifier inventory; enumeration is not scientific coverage.
Use documented ESearch limits, split by publication date when a partition is
too large. Store lightweight IDs first; no arbitrary top-K exclusion.
"""
from datetime import date, timedelta
import re
from hashlib import sha256

PARTITION_LIMIT=10000
MAX_IDS=30000
MAX_PARTITIONS=256
MAX_RETRIES=3

def initial(query,start=date(1800,1,1),end=None):
    end=end or date.today()
    if not isinstance(query,str) or not query.strip() or start>end:
        raise ValueError("invalid query or dates")
    return {"schema":1,"query":query,"query_sha256":sha256(query.encode()).hexdigest(),
        "date_range":[str(start),str(end)],"pending":[{"start":str(start),"end":str(end),"attempts":0}],
        "complete_partitions":[],"unresolved":[],"ids":[],"cursor":0,
        "query_enumeration_complete":False,"qualification_granted":False}

def _valid_ids(ids):
    return all(isinstance(x,str) and re.fullmatch(r"[1-9][0-9]{0,11}",x) for x in ids) and len(ids)==len(set(ids))

def _query(state,part):
    a=date.fromisoformat(part["start"]);b=date.fromisoformat(part["end"])
    return f'({state["query"]}) AND ("{a:%Y/%m/%d}"[dp] : "{b:%Y/%m/%d}"[dp])'

def step(state,client,*,cap=PARTITION_LIMIT,storage_limit=MAX_IDS):
    if state.get("schema")!=1 or state.get("qualification_granted") is not False or state.get("query_sha256")!=sha256(state["query"].encode()).hexdigest():
        raise ValueError("invalid inventory checkpoint")
    if not 1<=cap<=PARTITION_LIMIT or not 1<=storage_limit<=MAX_IDS:
        raise ValueError("invalid budget")
    if not state["pending"]:
        return {"status":"DONE" if state["query_enumeration_complete"] else "UNRESOLVED","new_ids":0,"qualification_granted":False}
    part=state["pending"].pop(0);q=_query(state,part)
    report={"query":q,"partition":dict(part),"new_ids":0,"qualification_granted":False}
    try:
        raw=client.http.get_json(client.base+"esearch.fcgi",client._params({"db":"pubmed","term":q,"retmode":"json","retmax":cap,"sort":"relevance"}))
        block=raw.get("esearchresult") or {}
        total=int(block["count"]);ids=[str(x) for x in block.get("idlist",[])]
        warning=block.get("warninglist") or {}
        if block.get("errorlist") or raw.get("error") or raw.get("ERROR") or (isinstance(warning,dict) and warning.get("quotedphrasesnotfound")):
            raise ValueError("query translation error")
        if total<0 or not _valid_ids(ids) or len(ids)>min(total,cap):
            raise ValueError("inconsistent IDs")
        report["reported_total"]=total
        if total>cap:
            lo=date.fromisoformat(part["start"]);hi=date.fromisoformat(part["end"])
            if lo==hi or len(state["complete_partitions"])+len(state["pending"])+len(state["unresolved"])+2>MAX_PARTITIONS:
                state["unresolved"].append({**part,"reason":"PARTITION_CAP","reported_total":total});report["status"]="PARTITION_UNRESOLVED"
            else:
                mid=lo+(hi-lo)//2
                # Newer first, both intervals retained. No overlap or gap.
                state["pending"].extend([{"start":str(mid+timedelta(days=1)),"end":str(hi),"attempts":0},{"start":str(lo),"end":str(mid),"attempts":0}])
                report["status"]="SPLIT_REQUIRED"
        elif len(ids)!=total:
            raise ValueError("incomplete ID enumeration")
        else:
            before=set(state["ids"]);additional=[p for p in ids if p not in before]
            if len(before)+len(additional)>storage_limit:
                state["pending"].insert(0,part);report["status"]="STORAGE_LIMIT";state["storage_limit_reached"]=True
            else:
                state["ids"].extend(additional)
                state["complete_partitions"].append({**part,"reported_total":total,"query":q,"ids_sha256":sha256("\n".join(sorted(ids)).encode()).hexdigest()})
                report.update(status="PARTITION_ENUMERATED",new_ids=len(additional))
    except Exception as exc:
        part["attempts"]+=1
        report.update(status="ACCESS_OR_QUERY_UNRESOLVED",error_type=type(exc).__name__)
        if part["attempts"]<MAX_RETRIES:state["pending"].append(part)
        else:state["unresolved"].append({**part,"reason":"RETRY_LIMIT"})
    state["query_enumeration_complete"]=not state["pending"] and not state["unresolved"]
    report.update(stored_ids=len(state["ids"]),pending_partitions=len(state["pending"]),unresolved_partitions=len(state["unresolved"]),query_enumeration_complete=state["query_enumeration_complete"])
    return report

def next_page(state,size=30):
    if not 1<=size<=100:raise ValueError("invalid page")
    start=state.get("cursor",0)
    return state["ids"][start:start+size]

def acknowledge_page(state,ids):
    # Call only after exact source records have been persisted, not after a search hit.
    if not ids or list(ids)!=next_page(state,len(ids)):
        raise ValueError("out-of-order inventory acknowledgement")
    state["cursor"]+=len(ids)
