"""Compare unmodified and fixed-line CLI; do not change production registry gates."""
import json,os,subprocess,sys
from pathlib import Path
QUERIES=['"prone positioning" AND "respiratory distress"','"prone positioning" AND "supine positioning"','"prone positioning" AND "mortality"']
def main():
    original,experimental=sys.argv[1:3];out={"schema":"PROSPERO_PAGINATION_EXPERIMENT_V1","production_changed":False,"cases":[]}
    target=Path("prospero-pagination.json")
    for q in QUERIES:
        item={"query":q,"arms":{}}
        for arm,entry in (("PINNED",original),("FIXED_LINE",experimental)):
            pages=[];seen=set();totals=[]
            for page in range(1,4):
                try:
                    r=subprocess.run(["node",entry,"search",q,"--page",str(page),"--page-size","50","--sort","accession","--order","asc"],capture_output=True,text=True,timeout=35,env={**os.environ,"PROSPERO_CACHE_ENABLED":"false"})
                    data=json.loads(r.stdout)["data"]
                    if r.returncode or not isinstance(data.get("hits"),list):raise ValueError("invalid")
                    ids={str(h.get("accession_number") or h.get("record_id")) for h in data["hits"] if h.get("accession_number") or h.get("record_id")}
                    total=data["total_hits"];totals.append(total)
                    pages.append({"page":page,"total":total,"records":len(ids),"overlap":len(ids&seen),"note":str(data.get("raw_note") or "")[:150]})
                    seen.update(ids)
                    if not ids or len(seen)>=max(totals):break
                except Exception as e:pages.append({"page":page,"error":type(e).__name__});break
            stable=bool(totals) and len(set(totals))==1
            item["arms"][arm]={"pages":pages,"unique":len(seen),"stable":stable,"complete":stable and len(seen)==totals[0] and all("error" not in p and p.get("overlap")==0 and not p.get("note") for p in pages)}
        out["cases"].append(item);target.write_text(json.dumps(out,indent=2)+"\n");print(json.dumps(item),flush=True)
if __name__=="__main__":main()
