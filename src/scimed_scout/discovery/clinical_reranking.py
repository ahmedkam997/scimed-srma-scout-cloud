"""Local BM25 plus clinical cues, for prioritization only.
All input records remain available; no automatic exclusions or eligibility.
"""
from collections import Counter
from math import log
import re
from .pico_matching import _normalize,STOP
from .evidence_classification import classify_review_search_hit
from scimed_scout.sources.base import SearchRecord

VERSION="CLINICAL_BM25_V1"
def tokens(value):
    return [t for t in _normalize(value).split() if len(t)>=2 and t not in STOP]
def _text(record):
    m=(record.get("payload") or {}).get("metadata") or {}
    title=str(record.get("title") or "")
    abstract=max([str(m.get(k) or "") for k in ("abstract","abstractText","summary")],key=len)
    # Title weighted; capped abstract avoids unbounded provider text.
    return title+" "+title+" "+abstract[:16000]
def rank(candidate, records, purpose="REVIEW"):
    records=list(records)
    if not records:return []
    docs=[Counter(tokens(_text(r))) for r in records]
    n=len(docs);avg=max(1,sum(sum(d.values()) for d in docs)/n)
    df=Counter(t for d in docs for t in d)
    dims=[(.55,set(tokens(candidate.intervention_exposure_index_test))),(.30,set(tokens(candidate.population))),(.10,set(tokens(candidate.comparator_reference))),(.05,set(tokens(" ".join(candidate.outcomes or []))))]
    terms=set().union(*(ts for _,ts in dims))
    def bm25(d):
        length=sum(d.values())
        return sum(log(1+(n-df[t]+.5)/(df[t]+.5))*(d[t]*2.5)/(d[t]+1.5*(.25+.75*length/avg)) for t in terms if d[t])
    raw=[bm25(d) for d in docs];scale=max(raw) or 1
    result=[]
    for i,(r,d,b) in enumerate(zip(records,docs,raw)):
        match=sum(w*len(set(d)&ts)/len(ts) for w,ts in dims if ts)
        m=(r.get("payload") or {}).get("metadata") or {}
        item=SearchRecord(str(r.get("source") or ""),str(r.get("source_record_id") or ""),str(r.get("title") or ""),metadata=m)
        cue=classify_review_search_hit(item)
        design=1 if purpose=="REVIEW" and cue=="CONFIRMED_REVIEW_CUE" else 1 if purpose=="PRIMARY" and (re.search(r"\brandomi[sz]ed\b",_text(r),re.I) or "randomized controlled trial" in str(m).casefold()) and cue!="CONFIRMED_REVIEW_CUE" else 0
        score=.55*b/scale+.35*match+.10*design
        result.append({"record":r,"score":round(score,8),"bm25":round(b,8),"pico_term_overlap":round(match,8),"design_cue":design,"original_index":i,"eligibility_verified":False})
    return sorted(result,key=lambda x:(-x["score"],x["original_index"]))
