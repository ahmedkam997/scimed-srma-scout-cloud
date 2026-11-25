"""Deterministic, read-only incident triage. No arbitrary commands or edits."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

def classify_failure(code=None, *, error_type="", context=""):
    # Only bounded structured classifications leave this module; no raw
    # exception, response body, authorization header or source text is emitted.
    if str(code)=="57014" or re.search(r"\b57014\b|statement timeout",context,re.I):
        return {"code":"DATABASE_STATEMENT_TIMEOUT","category":"STORAGE",
                "action":"Inspect payload size and query cost; preserve checkpoints; resume only after bounded storage checks.",
                "automatic_action":"PRESERVE_CHECKPOINTS"}
    if code in (500,502,503,504,408):
        return {"code":"UPSTREAM_UNAVAILABLE","category":"DEPENDENCY",
                "action":"Probe another configured free endpoint before a new paired experiment; do not switch between arms.",
                "automatic_action":"BOUNDED_PROVIDER_PROBE"}
    if code in (402,429):
        return {"code":"PROVIDER_LIMIT","category":"DEPENDENCY",
                "action":"Respect quota or retry-after; defer the request or probe an independent free endpoint.",
                "automatic_action":"DEFER_OR_PROBE"}
    if code in (400,401,403,404):
        return {"code":"PROVIDER_ACCESS_OR_CONFIGURATION","category":"CONFIGURATION",
                "action":"Check model availability, account and key configuration without exposing secrets.",
                "automatic_action":"NONE"}
    return {"code":"UNCLASSIFIED_FAILURE","category":"UNRESOLVED",
            "action":"Reproduce the failure in an isolated test; inspect sanitized evidence; propose a reviewed patch.",
            "automatic_action":"NONE"}

def exception_diagnostic(exc):
    chain=[]
    seen=set()
    while exc is not None and id(exc) not in seen and len(chain)<6:
        seen.add(id(exc))
        chain.append(exc)
        exc=exc.__cause__ or exc.__context__
    for item in chain:
        code=getattr(item,"status_code",None)
        result=classify_failure(code,error_type=type(item).__name__,context=str(item))
        if result["code"]!="UNCLASSIFIED_FAILURE":
            return result
    return classify_failure()

def comparison_diagnostic(report):
    findings=[]
    probes=report.get("provider_probes") or []
    arms=report.get("arms") or {}
    status=report.get("status","UNKNOWN")
    failures=[]
    for arm,entry in arms.items():
        for call in (entry.get("generation") or {}).get("calls",[]):
            if call.get("status")=="FAILED":
                failures.append((arm,call))
    if failures or (probes and not any(p.get("status")=="HEALTHY" for p in probes)):
        all_calls=[c for _,c in failures] or [p for p in probes if p.get("status")!="HEALTHY"]
        for call in all_calls:
            finding=classify_failure(call.get("http_status"),error_type=call.get("error_type",""))
            if finding not in findings:
                findings.append(finding)
    if not report.get("strict_generation_comparability"):
        findings.append({"code":"COMPARISON_INCONCLUSIVE","category":"EVALUATION",
            "action":"No superiority or inferiority claim. Inspect generation shortfall, model identity and source coverage before comparing.",
            "automatic_action":"NONE"})
    for arm,entry in arms.items():
        summary=entry.get("summary") or {}
        if summary.get("unresolved_source_samples",0):
            findings.append({"code":"SOURCE_SAMPLE_INCOMPLETE","category":"RETRIEVAL",
                "arm":arm,"action":"Recheck unavailable sources; do not count missing evidence as negative.","automatic_action":"NONE"})
        deep=entry.get("deep_audit") or {}
        if deep.get("status")=="COMPLETED" and deep.get("candidate_status")=="PROVISIONAL_BACKUP":
            findings.append({"code":"SCIENTIFIC_REVIEW_REQUIRED","category":"SCIENTIFIC",
                "arm":arm,"action":"Adjudicate pending novelty/PICO/independence evidence; never relax gates automatically.","automatic_action":"NONE"})
    return {"version":"DIAGNOSTICS_V1","input_status":status,"findings":findings,
            "scientific_superiority_established":False,"code_changes_authorized":False,
            "raw_logs_included":False,"automatic_code_repair":False,
            "next_step":"Run the bounded recovery when applicable; otherwise reproduce and test a patch on a separate branch before review."}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    report=json.loads(args.comparison.read_text(encoding="utf-8"))
    out=comparison_diagnostic(report)
    args.output.write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
