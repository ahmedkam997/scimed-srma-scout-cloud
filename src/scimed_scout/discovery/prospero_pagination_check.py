"""Live production adapter regression: scoped ARDS queries, no AI or DB writes."""
import json
from pathlib import Path
from scimed_scout.sources.prospero import ProsperoCliSource
from scimed_scout.domain import SourceStatus

QUERIES=('"prone positioning" AND "respiratory distress"',
         '"prone positioning" AND "supine positioning"',
         '"prone positioning" AND "mortality"')

def main():
    report={"schema":"PRODUCTION_PROSPERO_PAGINATION_V1","cases":[],"new_ai_requests":0}
    for q in QUERIES:
        result=ProsperoCliSource().search(q,limit=8)
        ids=[r.record_id for r in result.records]
        item={"query":q,"status":result.status.value,"total":result.total_count,"retrieved":len(ids),"unique":len(set(ids)),"diagnostic":result.message}
        item["passed"]=result.status==SourceStatus.SEARCHED_POSITIVE and result.total_count==len(ids)==len(set(ids)) and "duplicates=0" in result.message and "count_changed=False" in result.message and "page_integrity_failed=False" in result.message
        report["cases"].append(item);print(json.dumps(item),flush=True)
        Path("prospero-production-check.json").write_text(json.dumps(report,indent=2)+"\n")
    return 0 if all(c["passed"] for c in report["cases"]) else 1

if __name__=="__main__":raise SystemExit(main())
