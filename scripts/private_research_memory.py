"""Owner-local case memory; no network, no public logging, no qualification authority.
Read a private JSON export locally, retrieve relevant development examples, and
produce a private ideation brief. Do not commit input or output.
"""
import argparse,json,os,re
from pathlib import Path

SCHEMA="SCIMED_PRIVATE_RESEARCH_MEMORY_V1"
def tokens(text):
    return set(re.findall(r"[a-z0-9]+",str(text).casefold()))-{"a","an","and","the","of","in","for","after","versus","with","to","on"}
def load(path):
    if path.stat().st_size>5_000_000:raise ValueError("memory exceeds local cap")
    data=json.loads(path.read_text())
    if data.get("schema")!=SCHEMA or data.get("external_transfer_allowed") is not False or data.get("independent_test_use") is not False or data.get("qualification_granted") is not False:
        raise ValueError("expected owner-private development-only memory")
    if not isinstance(data.get("projects"),list):raise ValueError("projects missing")
    for row in data["projects"]:
        if row.get("scientific_status")!="DEVELOPMENT_EXAMPLE_ONLY" or row.get("qualification_granted") is not False or row.get("novelty_verified") is not False:
            raise ValueError("memory cannot grant scientific qualification")
        if not isinstance(row.get("project_label"),str) or not isinstance(row.get("pattern_hypothesis"),str):raise ValueError("invalid project")
    return data
def retrieve(data,question,limit=5):
    q=tokens(question)
    scored=[]
    for x in data["projects"]:
        t=tokens(x["project_label"]+" "+x["pattern_hypothesis"])
        score=len(q&t)/max(1,len(q|t))
        if score:scored.append((score,x))
    scored.sort(key=lambda v:(-v[0],v[1]["project_label"]))
    return [{"similarity":score,"project_label":x["project_label"],"pattern_hypothesis":x["pattern_hypothesis"],"observed_distinct_labels":x.get("observed_distinct_labels"),"status":"DEVELOPMENT_EXAMPLE_ONLY"} for score,x in scored[:max(1,min(10,limit))]]
def brief(data,question):
    return {"schema":"SCIMED_PRIVATE_IDEATION_BRIEF_V1","question":question,
        "examples":retrieve(data,question),"search_patterns":data.get("patterns",[]),
        "instructions":["Generate distinct candidate questions from public recent RCTs and review gaps, not copied portfolio titles.",
            "Treat memory as research experience and possible overlap, not verified evidence or independent test labels.",
            "For each hypothesis search public evidence, identify actual trial families, review cutoffs and clinical outcomes.",
            "Keep all existing qualification thresholds. Never infer a candidate is novel from a missing source."],
        "external_transfer_allowed":False,"qualification_granted":False}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("memory",type=Path);p.add_argument("--question",required=True);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();result=brief(load(a.memory),a.question)
    fd=os.open(a.output,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,"w") as f:json.dump(result,f,ensure_ascii=False,indent=2)
if __name__=="__main__":main()
