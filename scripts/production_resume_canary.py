"""One isolated, real production job using the ordinary owner-scoped REST API.
No fake result rows, no privileged access, no cooldown bypass, no tokens in logs.
"""
import json, re, secrets, time, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlencode
config=Path("web/config.js").read_text()
base=re.search(r'supabaseUrl:\s*"([^"]+)"',config).group(1)
anon=re.search(r'supabaseAnonKey:\s*"([^"]+)"',config).group(1)
token=secrets.token_hex(32)
out={"schema":"SCIMED_PRODUCTION_RESUME_CANARY_V1","isolated_owner":True,"status":"STARTED","events":[]}
def save(**kwargs):
    out.update(kwargs);Path("production-resume-canary.json").write_text(json.dumps(out,indent=2)+"\n")
    print(json.dumps({k:v for k,v in out.items() if k!="events"}),flush=True)
def api(path,body=None,prefer=False,owner=None):
    headers={"apikey":anon,"Authorization":"Bearer "+anon,"x-scimed-client-token":owner or token,"Content-Type":"application/json"}
    if prefer:headers["Prefer"]="return=representation"
    req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
    with urllib.request.urlopen(req,timeout=25) as response:
        raw=response.read();return json.loads(raw) if raw else None
def wake(job):
    try:
        res=api("/functions/v1/wake-discovery-worker",{"job_id":job})
        out["events"].append({"wake_status":res.get("status") if isinstance(res,dict) else "UNKNOWN"})
    except urllib.error.HTTPError as e:out["events"].append({"wake_http":e.code})
def read(job):
    rows=api("/rest/v1/discovery_jobs?"+urlencode({"id":"eq."+job,"select":"id,status,stage,completed_at,result_json"}))
    if not isinstance(rows,list) or len(rows)!=1:raise RuntimeError("canary row inaccessible")
    return rows[0]
def wait(job,seconds):
    deadline=time.monotonic()+seconds;previous=None
    while time.monotonic()<deadline:
        row=read(job)
        state=row["status"]
        if state!=previous:out["events"].append({"status":state,"stage":row["stage"]});save();previous=state
        if state in ("COMPLETED","FAILED","CANCELLED"):return row
        time.sleep(30)
    return read(job)
def main():
    save()
    try:
        rows=api("/rest/v1/discovery_jobs?select=id,status",{"specialty":"Cardiology","question_type":"ALL","candidate_count":4,"final_options":2,"min_verify":3,"max_verify":3,"limit_per_query":12,"revisit_days":30},True)
        job=rows[0]["id"];save(job_id=job,status="QUEUED");wake(job)
        initial=wait(job,1500)
        if initial["status"]!="COMPLETED":save(status="INITIAL_JOB_NOT_COMPLETED",initial_status=initial["status"]);return
        summary=(initial["result_json"] or {}).get("run_summary",{})
        save(status="INITIAL_COMPLETED",resume_eligible=summary.get("resume_eligible"),verified_candidates=summary.get("verified_candidates"))
        if not summary.get("resume_eligible"):save(status="NO_MACHINE_RECOVERY_ELIGIBLE");return
        denied=api("/rest/v1/rpc/scimed_resume_rct_job",{"p_job_id":job},owner=secrets.token_hex(32))
        if denied is not False:raise RuntimeError("foreign owner accepted")
        out["events"].append({"foreign_owner_denied":True})
        completed=datetime.fromisoformat(initial["completed_at"].replace("Z","+00:00"))
        delay=max(0,605-(datetime.now(timezone.utc)-completed).total_seconds())
        if delay:time.sleep(delay)
        accepted=api("/rest/v1/rpc/scimed_resume_rct_job",{"p_job_id":job})
        queued=read(job)
        retained=queued.get("result_json")==initial.get("result_json")
        save(status="RESUME_RPC_TESTED",accepted=accepted,prior_report_retained=retained)
        if accepted is not True or not retained:save(status="RESUME_CONTRACT_FAILED");return
        wake(job)
        final=wait(job,1200)
        audit=(final.get("result_json") or {}).get("run_summary",{}).get("resume_audit") or {}
        ok=final["status"]=="COMPLETED" and audit.get("reused_seed") is True and audit.get("restored_candidate_audits",0)>0 and audit.get("rechecked_candidates",0)>0
        save(status="END_TO_END_RESUME_PASSED" if ok else "END_TO_END_RESUME_UNRESOLVED",final_status=final["status"],resume_audit=audit)
    except urllib.error.HTTPError as exc:save(status="HTTP_UNRESOLVED",http_status=exc.code)
    except Exception as exc:save(status="CANARY_UNRESOLVED",error_type=type(exc).__name__)
if __name__=="__main__":main()
