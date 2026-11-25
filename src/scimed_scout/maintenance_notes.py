"""Create/update bounded maintenance notes from trusted GitHub run metadata.

No AI, no raw logs, no secrets in notes, no code writes or auto-close.
Artifact JSON is untrusted data: never extract or execute ZIP members.
"""
from __future__ import annotations
import argparse
import io
import json
import os
import re
import subprocess
import zipfile

WORKFLOWS = ("tests","discovery-worker","evidence-first-smoke","comparative-validation")
CODES = {
 "UPSTREAM_UNAVAILABLE": ("P1","AI provider unavailable","Check actual request failure and alternate fixed free route; do not infer scientific failure."),
 "PROVIDER_LIMIT": ("P2","Provider rate or quota limit","Defer or test a separate free quota; preserve evidence."),
 "PROVIDER_ACCESS_OR_CONFIGURATION": ("P1","Provider configuration/access failure","Check model and account configuration; do not expose credentials."),
 "DATABASE_STATEMENT_TIMEOUT": ("P1","Database timeout","Inspect storage payload and query cost; preserve checkpoints."),
 "COMPARISON_INCONCLUSIVE": ("P2","Comparison inconclusive","Review paired generation and source coverage; do not claim a winner."),
 "SOURCE_SAMPLE_INCOMPLETE": ("P2","Incomplete source sampling","Inspect source audit and distinguish access failure from negative search."),
 "SCIENTIFIC_REVIEW_REQUIRED": ("P3","Scientific assessment pending","Review evidence manually; no automatic gate change."),
 "WORKFLOW_FAILURE": ("P1","Workflow did not complete successfully","Inspect exact failing step and reproduce before proposing a tested fix."),
 "DIAGNOSTICS_UNAVAILABLE": ("P2","Comparison diagnostic artifact unavailable","Inspect artifact production and access; no scientific conclusion inferred."),
 "UNCLASSIFIED_FAILURE": ("P2","Unclassified incident","Inspect sanitized evidence and reproduce in isolation."),
 "REPEATED_LOW_DISCOVERY_YIELD": ("P2","Repeated zero-qualified discovery yield","Inspect reason counts in the last three comparable completed jobs; do not lower scientific gates."),
 "REPEATED_GENERATION_SHORTFALL": ("P2","Repeated generation shortfall","Check duplicate history and generation budgets before modifying discovery."),
 "REPEATED_SOURCE_COVERAGE": ("P2","Repeated incomplete source coverage","Inspect candidate-level source blockers, not optional index failures alone."),
 "SLOW_DISCOVERY_RUN": ("P2","Discovery nearing worker timeout","Inspect stage durations and checkpoints; no automatic deadline or gate change."),
 "AI_CAPACITY_PRESSURE": ("P2","Observed AI quota or fallback pressure","Inspect logical failures and provider limits; avoid repeated probes."),
 "TELEMETRY_UNAVAILABLE": ("P2","Worker telemetry missing or invalid","Inspect aggregate artifact; absence is not evidence of scientific failure."),
}
MARKER = "<!-- scimed-maintenance:v1:"
MAX_ARTIFACT = 2_000_000

def api(repo, endpoint, *, method="GET", payload=None, binary=False):
    # All endpoints are generated from validated repo and numeric run IDs.
    args=["gh","api","--method",method,f"repos/{repo}/{endpoint}"]
    data=None
    if payload is not None:
        args+=["--input","-"]
        data=json.dumps(payload).encode()
    out=subprocess.run(args,input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                       check=True,timeout=45).stdout
    return out if binary else json.loads(out)

def trusted_run(run, repo):
    return (run.get("head_branch")=="main" and run.get("status")=="completed"
            and (run.get("head_repository") or {}).get("full_name")==repo
            and run.get("name") in WORKFLOWS and run.get("event") in
            ("push","schedule","workflow_dispatch","repository_dispatch")
            and isinstance(run.get("id"),int) and run["id"]>0)

def parse_diagnostics_zip(raw):
    if len(raw)>MAX_ARTIFACT:
        raise ValueError("artifact too large")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        entries=[i for i in z.infolist() if i.filename=="diagnostics-report.json"]
        if len(entries)!=1 or entries[0].file_size>100_000:
            raise ValueError("missing or oversized diagnostic")
        report=json.loads(z.read(entries[0]))
    if not isinstance(report,dict) or report.get("version")!="DIAGNOSTICS_V1":
        raise ValueError("unknown diagnostic schema")
    return sorted({v["code"] for v in report.get("findings",[]) if isinstance(v,dict)
                   and isinstance(v.get("code"),str) and v["code"] in CODES})

def parse_worker_zip(raw):
    if len(raw)>MAX_ARTIFACT:
        raise ValueError("artifact too large")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        entries=[i for i in z.infolist() if i.filename=="scimed-worker-telemetry.json"]
        if len(entries)!=1 or entries[0].file_size>100_000:
            raise ValueError("missing or oversized telemetry")
        report=json.loads(z.read(entries[0]))
    if not isinstance(report,dict) or report.get("version")!="WORKER_TELEMETRY_V1":
        raise ValueError("unknown telemetry schema")
    if report.get("status") not in ("COMPLETED","FAILED","CANCELLED"):
        raise ValueError("unknown telemetry status")
    for k in ("requested","generated","verified","qualified"):
        if report.get("status")=="COMPLETED" and (not isinstance(report.get(k),int) or isinstance(report[k],bool) or not 0<=report[k]<=100):
            raise ValueError("invalid aggregate count")
    if report.get("status")=="COMPLETED" and not 0<=report["qualified"]<=report["verified"]<=report["generated"]:
        raise ValueError("inconsistent aggregate")
    return report

def worker_findings(current, previous=()):
    codes=[]
    if current.get("status")=="FAILED":
        code=current.get("failure_code")
        return [code] if isinstance(code,str) and code in CODES else ["UNCLASSIFIED_FAILURE"]
    if current.get("status")!="COMPLETED":
        return []
    seconds=current.get("elapsed_seconds")
    if isinstance(seconds,(int,float)) and 2700<=seconds<=10000:
        codes.append("SLOW_DISCOVERY_RUN")
    ai=current.get("ai") or {}
    errors=ai.get("failure_categories") or {}
    if errors.get("PROVIDER_LIMIT",0)>0 or ai.get("unavailable_provider_count",0)>0:
        codes.append("AI_CAPACITY_PRESSURE")
    # Require same scope and question type, three independent run records
    # and a meaningful verification denominator; no alert for one zero.
    history=[current]+[r for r in previous if r.get("status")=="COMPLETED"
        and r.get("scope")==current.get("scope") and r.get("question_type")==current.get("question_type")]
    recent=history[:3]
    if len(recent)==3:
        if all(r.get("verified",0)>=3 and r.get("qualified")==0 for r in recent):
            codes.append("REPEATED_LOW_DISCOVERY_YIELD")
        if all(r.get("requested",0)>=4 and r.get("generated",0)*2<r["requested"] and not r.get("reused_generation") for r in recent):
            codes.append("REPEATED_GENERATION_SHORTFALL")
        if all(r.get("verified",0)>=3 and (r.get("reason_counts") or {}).get("SOURCE_COVERAGE",0)*2>=r["verified"] for r in recent):
            codes.append("REPEATED_SOURCE_COVERAGE")
    return sorted(set(codes))

def _worker_report(repo,artifact):
    return parse_worker_zip(api(repo,f"actions/artifacts/{artifact['id']}/zip",binary=True))

def _worker_artifacts(items):
    return [a for a in items if a.get("name")=="scimed-worker-telemetry"
        and not a.get("expired") and isinstance(a.get("id"),int)
        and 0<a.get("size_in_bytes",0)<=MAX_ARTIFACT]

def _worker_findings_for_run(repo,run):
    artifacts=api(repo,f"actions/runs/{run['id']}/artifacts?per_page=100")["artifacts"]
    matches=_worker_artifacts(artifacts)
    if not matches:
        # Idle and source-only workers intentionally publish no telemetry.
        return []
    if len(matches)!=1:
        raise ValueError("multiple telemetry artifacts")
    current=_worker_report(repo,matches[0])
    history=[]
    if current.get("status")=="COMPLETED":
        recent=api(repo,"actions/artifacts?name=scimed-worker-telemetry&per_page=20")["artifacts"]
        seen={run["id"]}
        for a in _worker_artifacts(recent):
            rid=(a.get("workflow_run") or {}).get("id")
            if not isinstance(rid,int) or rid in seen or rid>=run["id"]:
                continue
            seen.add(rid)
            previous=api(repo,f"actions/runs/{rid}")
            if not trusted_run(previous,repo) or previous.get("name")!="discovery-worker":
                continue
            old=_worker_report(repo,a)
            history.append(old)
            if len(history)>=5:
                break
    return worker_findings(current,history)

def run_findings(repo,run):
    if not trusted_run(run,repo):
        return []
    findings=[]
    if run.get("conclusion") not in ("success","skipped","cancelled"):
        findings.append("WORKFLOW_FAILURE")
    if run["name"]=="discovery-worker":
        try:
            findings.extend(_worker_findings_for_run(repo,run))
        except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError,zipfile.BadZipFile):
            findings.append("TELEMETRY_UNAVAILABLE")
    if run["name"]=="comparative-validation":
        try:
            artifacts=api(repo,f"actions/runs/{run['id']}/artifacts?per_page=100")["artifacts"]
            items=[a for a in artifacts if a.get("name")=="paired-discovery-pilot"
                   and not a.get("expired") and isinstance(a.get("id"),int)
                   and 0<a.get("size_in_bytes",0)<=MAX_ARTIFACT]
            if len(items)!=1:
                raise ValueError("artifact missing")
            raw=api(repo,f"actions/artifacts/{items[0]['id']}/zip",binary=True)
            findings.extend(parse_diagnostics_zip(raw))
        except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError,zipfile.BadZipFile):
            findings.append("DIAGNOSTICS_UNAVAILABLE")
    return sorted(set(findings))

def note(repo,run,code):
    priority,title,action=CODES[code]
    workflow=run["name"]
    key=f"{workflow}:{code}"
    rid=run["id"]
    sha=str(run.get("head_sha",""))
    sha=sha if re.fullmatch(r"[0-9a-f]{40}",sha) else "unknown"
    conclusion=run.get("conclusion")
    conclusion=conclusion if conclusion in ("success","failure","timed_out","action_required","neutral","stale","cancelled","skipped","startup_failure") else "unknown"
    marker=MARKER+key+" -->"
    run_marker=f"<!-- scimed-run:{rid}:{run.get('run_attempt',1) if isinstance(run.get('run_attempt',1),int) else 1} -->"
    body=f"""{marker}
{run_marker}
## Maintenance review requested
Priority: {priority}
Workflow: {workflow}
Observed finding: {code}
Latest run: https://github.com/{repo}/actions/runs/{rid}
Commit: {sha}
Workflow conclusion: {conclusion}

## Suggested investigation
{action}

## Decision requested from reviewer
- Reproduce and establish root cause using source evidence and tests.
- Decide whether repair is beneficial, defer, or close with rationale.
- If changing code, add a regression test and verify before merging.
- Preserve scientific qualification requirements. A successful workflow is not proof of scientific validity.

Status: awaiting independent review. This note is not an autonomous code change.
"""
    return {"title":f"[SciMed monitor] {workflow}: {title}","body":body,"marker":marker,"run_marker":run_marker}

def publish(repo,run,code,issues):
    data=note(repo,run,code)
    existing=next((x for x in issues if data["marker"] in (x.get("body") or "")
                   and x.get("user",{}).get("login")=="github-actions[bot]" and "pull_request" not in x),None)
    if existing:
        if data["run_marker"] in (existing.get("body") or ""):
            return "UNCHANGED"
        # Keep human comments and review history, not duplicate issues.
        api(repo,f"issues/{int(existing['number'])}",method="PATCH",payload={"body":data["body"]})
        return "UPDATED"
    created=api(repo,"issues",method="POST",payload={"title":data["title"],"body":data["body"]})
    issues.append(created)
    return "CREATED"

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--run-id",type=int)
    args=parser.parse_args()
    repo=os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",repo):
        raise ValueError("invalid repository")
    runs=[]
    if args.run_id:
        runs=[api(repo,f"actions/runs/{args.run_id}")]
    else:
        for name in WORKFLOWS:
            # Query by fixed workflow filename, only the latest completed main run.
            response=api(repo,f"actions/workflows/{name}.yml/runs?branch=main&status=completed&per_page=10")
            run=next((r for r in response.get("workflow_runs",[]) if trusted_run(r,repo)),None)
            if run:
                runs.append(run)
    issues=[]
    for page in range(1,11):
        batch=api(repo,f"issues?state=open&per_page=100&page={page}")
        issues.extend(batch)
        if len(batch)<100:
            break
    else:
        raise RuntimeError("Issue deduplication limit exceeded; no notes published")
    for run in runs:
        for code in run_findings(repo,run):
            print(json.dumps({"run_id":run["id"],"finding":code,"note_status":publish(repo,run,code,issues)}))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
