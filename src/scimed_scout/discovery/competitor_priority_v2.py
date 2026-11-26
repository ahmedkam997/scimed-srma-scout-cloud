"""BM25 lexical ranking of competitors. Prioritization only; no auto exclusions."""
import math,re
from collections import Counter
from .competitor_records import abstract,identity
def tokens(s):return re.findall(r"[a-z0-9]+",str(s or "").casefold())
def order(candidate,rows):
    # Corpus IDF and length normalization; preserve legacy rank as tie breaker.
    # No ML model dependency, no inference calls, no stop rule.
    rows=list(rows)
    if not rows:return []
    query=Counter(tokens(candidate.intervention_exposure_index_test)*3+tokens(candidate.population)*2+tokens(candidate.comparator_reference)+tokens(" ".join(candidate.outcomes or [])))
    stop={"a","an","the","in","of","for","and","or","with","to","versus","vs","patients","treatment","study","therapy"}
    query={t:w for t,w in query.items() if t not in stop}
    docs=[Counter(tokens(r.get("title"))*2+tokens(abstract(r))) for r in rows]
    lengths=[sum(d.values()) for d in docs];avg=max(1,sum(lengths)/len(rows))
    df=Counter(t for d in docs for t in d)
    def score(i):
        d=docs[i];norm=1.2*(.25+.75*lengths[i]/avg)
        return sum(w*math.log(1+(len(rows)-df[t]+.5)/(df[t]+.5))*d[t]*2.2/(d[t]+norm) for t,w in query.items() if d[t])
    return [rows[i] for i in sorted(range(len(rows)),key=lambda i:(-score(i),i))]
