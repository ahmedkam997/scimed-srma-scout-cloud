"""Re-evaluate all eight frozen proposals with matched focused source sampling.

No AI calls. Post-hoc retrieval sensitivity analysis, not a new randomized
experiment or a scientifically validated comparison.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from scimed_scout.storage import CandidateRecord
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.europe_pmc import EuropePMCSource
from .comparative_validation import ARMS,TARGET,audit_candidate,summarize_arm,_write

def replay(old,clients,output=None):
    if old.get("version")!="PAIRED_DISCOVERY_PILOT_V1" or set(old.get("arms",{}))!=set(ARMS):
        raise ValueError("invalid original report")
    if any(len(old["arms"][arm].get("audits",[]))!=TARGET for arm in ARMS):
        raise ValueError("original proposals incomplete")
    evidence=old["frozen_seed"]["evidence_map"]
    out={"version":"FOCUSED_REPLAY_V1","status":"STARTED","new_ai_requests":0,
         "scientific_superiority_established":False,"arms":{},
         "limitations":"Post-hoc focused sampling, original proposals frozen. Query specificity and metadata availability can affect PICO signals. No validated study eligibility, novelty assessment or exhaustive retrieval."}
    cache={}
    for arm in ARMS:
        out["arms"][arm]={"audits":[],"original_summary":old["arms"][arm]["summary"]}
    if output:
        _write(output,out)
    for i in range(TARGET):
        for arm in ARMS:
            prior=old["arms"][arm]["audits"][i]
            candidate=CandidateRecord(**prior["candidate"])
            item=audit_candidate(candidate,clients,cache,evidence,focused=True)
            item["original_pico_family_leads"]=prior.get("pico_design_family_leads")
            item["original_source_complete"]=prior.get("sample_source_access_complete")
            out["arms"][arm]["audits"].append(item)
            if output:
                _write(output,out)
    for arm in ARMS:
        entry=out["arms"][arm]
        entry["summary"]=summarize_arm(old["arms"][arm]["generation"],entry["audits"])
    out["matched_samples_complete"]=all(out["arms"][a]["summary"]["complete_source_samples"]==TARGET for a in ARMS)
    out["status"]="COMPLETED" if out["matched_samples_complete"] else "INCOMPLETE_SOURCE_ACCESS"
    if output:
        _write(output,out)
    return out

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.prior.stat().st_size>2_000_000:
        raise ValueError("oversized source report")
    prior=json.loads(args.prior.read_text(encoding="utf-8"))
    result=replay(prior,[PubMedSource(),EuropePMCSource()],args.output)
    print(json.dumps({"status":result["status"],"new_ai_requests":0,
        "arms":{arm:{k:v for k,v in result["arms"][arm]["summary"].items() if k!="generation"} for arm in ARMS},
        "scientific_superiority_established":False}),flush=True)

if __name__=="__main__":
    main()
